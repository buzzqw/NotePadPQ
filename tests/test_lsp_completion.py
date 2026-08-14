import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QApplication

from core.session import restore_cursor_after_load
from editor.autocomplete import AutoCompleteLevel, AutoCompleteManager
from editor.editor_widget import EditorWidget
from editor.lsp_client import LSPClient, _path_to_uri, normalize_completion_item
from ui.keybinding import KeyBindingDialog, load_and_apply_shortcuts


class _CompletionClient(QObject):
    completion_response = pyqtSignal(int, str, list)

    def __init__(self):
        super().__init__()
        self.requests = []

    def request_completions(self, path, line, col):
        self.requests.append((path, line, col))
        return len(self.requests)


class LSPCompletionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = EditorWidget()
        self.editor.file_path = Path("/tmp/notepadpq-completion.py")
        self.manager = AutoCompleteManager(self.editor)
        self.manager.set_language("python")

    def tearDown(self):
        self.manager.shutdown()
        self.editor.deleteLater()
        self.app.processEvents()

    def test_completion_item_normalizes_documentation_and_text_edit(self):
        item = normalize_completion_item({
            "label": "request",
            "detail": "(url: str) -> Response",
            "documentation": {"kind": "markdown", "value": "Fetch **url**"},
            "textEdit": {
                "range": {
                    "start": {"line": 1, "character": 2},
                    "end": {"line": 1, "character": 5},
                },
                "newText": "requests.get($0)",
            },
        })

        self.assertEqual(item["label"], "request")
        self.assertEqual(item["detail"], "(url: str) -> Response")
        self.assertEqual(item["documentation"], "Fetch **url**")
        self.assertEqual(item["insertText"], "requests.get($0)")
        self.assertEqual(item["textEdit"]["newText"], "requests.get($0)")

    def test_lsp_response_uses_async_context_and_normalized_items(self):
        client = LSPClient("python", "/tmp")
        client._initialized = True
        client._worker = mock.Mock()
        path = Path("/tmp/notepadpq-completion.py")
        received = []
        client.completion_response.connect(
            lambda request_id, uri, items: received.append((request_id, uri, items))
        )

        request_id = client.request_completions(path, 2, 4)
        client._handle_response({
            "id": request_id,
            "result": {"items": [{
                "label": "Response",
                "documentation": {"value": "HTTP response"},
                "insertText": "Response()",
            }]},
        })

        self.assertEqual(received[0][0], request_id)
        self.assertEqual(received[0][1], path.as_uri())
        self.assertEqual(received[0][2][0]["documentation"], "HTTP response")
        self.assertEqual(received[0][2][0]["insertText"], "Response()")
        client.stop()

    def test_popup_filters_local_api_duplicates_and_inserts_text_edit(self):
        client = _CompletionClient()
        self.editor._lsp_client = client
        self.manager.set_level(AutoCompleteLevel.LSP, True)
        self.editor.setText("res")
        self.editor.setCursorPosition(0, 3)
        self.manager._local_completion_keys = {"response"}
        shown = []
        self.editor.showUserList = lambda list_id, labels: shown.append((list_id, labels))

        self.manager._request_lsp_completions()
        uri = self.editor.file_path.as_uri()
        client.completion_response.emit(1, uri, [
            {"label": "response", "insertText": "response()"},
            {
                "label": "result",
                "insertText": "result_value",
                "textEdit": {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 3},
                    },
                    "newText": "result_value",
                },
            },
        ])

        self.assertEqual(shown, [(20, ["result"])])
        self.assertEqual(self.manager._lsp_items["result"]["insertText"], "result_value")
        self.manager._on_lsp_user_list_selection(20, "result")
        self.assertEqual(self.editor.text(), "result_value")

    def test_char_added_debounces_and_coalesces_completion_requests(self):
        # Senza debounce, digitare N caratteri genera N richieste JSON-RPC,
        # quasi tutte obsolete prima ancora della risposta. Qui verifichiamo
        # che _on_char_added_for_lsp (il path "a ogni carattere") accorpi le
        # digitazioni ravvicinate in una sola richiesta.
        client = _CompletionClient()
        self.editor._lsp_client = client
        self.manager.set_level(AutoCompleteLevel.LSP, True)
        self.editor.setText("res")
        self.editor.setCursorPosition(0, 3)

        for _ in range(3):
            self.manager._on_char_added_for_lsp(ord("s"))
        self.assertEqual(client.requests, [])
        self.assertTrue(self.manager._lsp_completion_timer.isActive())

        self.manager._lsp_completion_timer.timeout.emit()
        self.assertEqual(len(client.requests), 1)

    def test_trigger_manual_requests_completions_immediately(self):
        # Ctrl+Space è un'azione esplicita: deve restare immediata e non
        # passare dal debounce pensato per il flusso "a ogni carattere".
        client = _CompletionClient()
        self.editor._lsp_client = client
        self.manager.set_level(AutoCompleteLevel.LSP, True)
        self.editor.setText("res")
        self.editor.setCursorPosition(0, 3)

        self.manager.trigger_manual()

        self.assertEqual(len(client.requests), 1)
        self.assertFalse(self.manager._lsp_completion_timer.isActive())

    def test_completion_request_flushes_pending_content_sync_first(self):
        # didChange verso il server e' debounced (main_window.py); prima di
        # chiedere un completamento dobbiamo garantire che il server veda
        # gia' il testo corrente, altrimenti risponderebbe su una snapshot
        # vecchia di qualche centinaio di ms.
        client = _CompletionClient()
        self.editor._lsp_client = client
        self.manager.set_level(AutoCompleteLevel.LSP, True)
        self.editor.setText("res")
        self.editor.setCursorPosition(0, 3)

        flushed = []
        fake_window = mock.Mock()
        fake_window._lsp_flush_content_sync = lambda ed, cl: flushed.append((ed, cl))
        self.editor.window = lambda: fake_window

        self.manager._request_lsp_completions()

        self.assertEqual(flushed, [(self.editor, client)])
        self.assertEqual(len(client.requests), 1)

    def test_incremental_change_uses_utf16_range_and_minimal_replacement(self):
        change = LSPClient._incremental_change("one\nold 😀\nthree", "one\nnew 😀\nthree")

        self.assertEqual(change["range"], {
            "start": {"line": 1, "character": 0},
            "end": {"line": 1, "character": 3},
        })
        self.assertEqual(change["text"], "new")

    def test_workspace_uri_escapes_reserved_path_characters(self):
        self.assertEqual(
            _path_to_uri("/tmp/lsp workspace#one"),
            "file:///tmp/lsp%20workspace%23one",
        )

    def test_position_requests_use_utf16_columns(self):
        client = LSPClient("python", "/tmp")
        client._initialized = True
        client._worker = mock.Mock()
        path = Path("/tmp/notepadpq-utf16.py")
        client.open_file(path, "a😀b", "python")

        client.request_completions(path, 0, 2)
        params = client._worker.send.call_args.args[0]["params"]

        self.assertEqual(params["position"], {"line": 0, "character": 3})
        client.stop()

    def test_missing_server_and_server_error_are_noops(self):
        with mock.patch("editor.lsp_client.is_server_available", return_value=False):
            self.assertIsNone(LSPClient.get("python", "/tmp"))

        client = LSPClient("python", "/tmp")
        client._pending[7] = "completion"
        client._completion_uris[7] = "file:///tmp/a.py"
        received = []
        client.completion_response.connect(
            lambda request_id, uri, items: received.append((request_id, uri, items))
        )
        client._handle_server_error("server stopped")

        self.assertEqual(received, [(7, "file:///tmp/a.py", [])])
        self.assertEqual(client._pending, {})


class SessionCursorRestoreTest(unittest.TestCase):
    def test_cursor_is_restored_after_lazy_loader_finishes(self):
        class Signal:
            def __init__(self):
                self.slots = []

            def connect(self, slot):
                self.slots.append(slot)

            def emit(self):
                for slot in self.slots:
                    slot()

        class Editor:
            def __init__(self, path):
                self.file_path = path
                self.cursor = None
                self.visible_line = None

            def setCursorPosition(self, line, col):
                self.cursor = (line, col)

            def ensureLineVisible(self, line):
                self.visible_line = line

        path = Path("/tmp/notepadpq-session-cursor.txt")
        editor = Editor(path)
        loader = type("Loader", (), {"load_finished": Signal()})()
        tab_manager = type("TabManager", (), {"all_editors": lambda self: [editor]})()
        window = type("Window", (), {
            "_tab_manager": tab_manager,
            "_lazy_loaders": {editor: loader},
        })()

        restore_cursor_after_load(window, path, 4, 7)

        self.assertIsNone(editor.cursor)
        loader.load_finished.emit()
        self.assertEqual(editor.cursor, (3, 6))
        self.assertEqual(editor.visible_line, 3)


class KeyBindingDefaultsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.tempdir.name)
        self.actions = {
            "format_document": QAction("Format document"),
            "lsp_format": QAction("Format with LSP"),
            "view_lang_toolbar": QAction("Language toolbar"),
            "toggle_checklist": QAction("Checklist"),
            "save": QAction("Save"),
        }
        for key, shortcut in {
            "format_document": "Alt+Shift+F",
            "lsp_format": "Alt+Shift+F",
            "view_lang_toolbar": "Ctrl+Shift+L",
            "toggle_checklist": "Ctrl+Shift+L",
            "save": "Ctrl+S",
        }.items():
            self.actions[key].setShortcut(QKeySequence(shortcut))
        self.config_patch = mock.patch("ui.keybinding.get_config_dir", return_value=self.config_dir)
        self.config_patch.start()

    def tearDown(self):
        self.config_patch.stop()
        self.tempdir.cleanup()

    def test_shipped_collisions_have_distinct_defaults(self):
        self.actions["distraction_free"] = QAction("Distraction free")
        self.actions["distraction_free"].setShortcuts([
            QKeySequence("F11"), QKeySequence("Ctrl+Shift+F11"),
        ])
        load_and_apply_shortcuts(self.actions)

        shortcuts = [action.shortcut().toString() for action in self.actions.values()]
        self.assertEqual(len(shortcuts), len(set(shortcuts)))
        self.assertEqual(self.actions["lsp_format"].shortcut().toString(), "Ctrl+Alt+Shift+F")
        self.assertEqual(self.actions["toggle_checklist"].shortcut().toString(), "Ctrl+Alt+L")
        self.assertEqual(
            [shortcut.toString() for shortcut in self.actions["distraction_free"].shortcuts()],
            ["F11", "Ctrl+Shift+F11"],
        )

    def test_reset_restores_captured_default_after_saved_override(self):
        (self.config_dir / "shortcuts.json").write_text(
            '{"save": "Ctrl+K"}', encoding="utf-8",
        )
        load_and_apply_shortcuts(self.actions)
        self.assertEqual(self.actions["save"].shortcut().toString(), "Ctrl+K")

        dialog = KeyBindingDialog(self.actions)
        dialog._saved.clear()
        dialog._on_ok()

        self.assertEqual(self.actions["save"].shortcut().toString(), "Ctrl+S")


if __name__ == "__main__":
    unittest.main()

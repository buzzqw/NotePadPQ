import os
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from editor.autocomplete import AutoCompleteLevel, AutoCompleteManager
from editor.editor_widget import EditorWidget
from editor.lsp_client import LSPClient, normalize_completion_item


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


if __name__ == "__main__":
    unittest.main()

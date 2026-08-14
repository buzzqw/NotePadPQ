import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

from config.settings import Settings
from editor.editor_widget import EditorWidget, LineEnding
from main import _startup_language
from ui.main_window import MainWindow
from ui.preferences import PreferencesDialog
from ui.tab_manager import TabManager


class TabCloseFlowTests(unittest.TestCase):
    class Manager:
        close_other_tabs = TabManager.close_other_tabs
        close_all_tabs = TabManager.close_all_tabs

        def __init__(self, widgets, current, outcomes=None):
            self.widgets = list(widgets)
            self.current = current
            self.outcomes = outcomes or {}
            self.requests = []

        def currentWidget(self):
            return self.current

        def count(self):
            return len(self.widgets)

        def widget(self, index):
            return self.widgets[index]

        def indexOf(self, widget):
            return self.widgets.index(widget) if widget in self.widgets else -1

        def setCurrentIndex(self, index):
            self.current = self.widgets[index]

        def _on_close_requested(self, index):
            widget = self.widgets[index]
            self.requests.append(widget)
            if not self.outcomes.get(widget, True):
                return False
            self.widgets.pop(index)
            return True

    def test_close_others_requests_every_close_and_keeps_current_tab(self):
        manager = self.Manager(["first", "current", "last"], "current")

        self.assertTrue(manager.close_other_tabs())

        self.assertEqual(manager.requests, ["last", "first"])
        self.assertEqual(manager.widgets, ["current"])
        self.assertEqual(manager.current, "current")

    def test_close_all_closes_clean_tabs_and_stops_after_cancel(self):
        manager = self.Manager(["first", "cancel", "last"], "first", {"cancel": False})

        self.assertFalse(manager.close_all_tabs())

        self.assertEqual(manager.requests, ["last", "cancel"])
        self.assertEqual(manager.widgets, ["first", "cancel"])


class EditorPreferenceAndFormattingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_editor_applies_indentation_and_save_formatting(self):
        editor = EditorWidget()
        editor.apply_indentation_preferences(7, True, False)
        editor.setText("one  \n\ttwo\t")
        editor.apply_save_formatting(True, True)

        self.assertEqual(editor.tabWidth(), 7)
        self.assertTrue(editor.indentationsUseTabs())
        self.assertFalse(editor.autoIndent())
        self.assertEqual(editor.text(), "one\n\ttwo\n")

    def test_new_editor_uses_configured_defaults(self):
        values = {
            "file/default_encoding": "UTF-8-BOM",
            "file/default_line_ending": "CRLF",
            "editor/tab_width": 6,
            "editor/use_tabs": True,
            "editor/auto_indent": False,
        }

        def get(key, default=None):
            return values.get(key, default)

        with patch.object(Settings.instance(), "get", side_effect=get):
            editor = EditorWidget()

        self.assertEqual(editor.encoding, "UTF-8 BOM")
        self.assertEqual(editor.line_ending, LineEnding.CRLF)
        self.assertEqual(editor.tabWidth(), 6)
        self.assertTrue(editor.indentationsUseTabs())
        self.assertFalse(editor.autoIndent())

    def test_preferences_apply_updates_open_editors(self):
        editor = EditorWidget()
        parent = QWidget()
        parent._tab_manager = SimpleNamespace(all_editors=lambda: [editor])
        dialog = PreferencesDialog(parent)
        dialog._tab_width.setValue(3)
        dialog._use_tabs.setChecked(True)
        dialog._auto_indent.setChecked(False)
        dialog._settings = SimpleNamespace(
            set=lambda *_args: None,
            get=lambda _key, default=None: default,
        )

        dialog._apply()

        self.assertEqual(editor.tabWidth(), 3)
        self.assertTrue(editor.indentationsUseTabs())
        self.assertFalse(editor.autoIndent())
        dialog.deleteLater()
        parent.deleteLater()


class ReloadAndExternalChangeTests(unittest.TestCase):
    class Signal:
        def connect(self, _callback):
            pass

    class ReloadWindow:
        APP_NAME = "NotePadPQ"
        action_reload = MainWindow.action_reload

        def __init__(self, editor):
            self.editor = editor
            self.reloaded = []

        def _current_editor(self):
            return self.editor

        def _reload_editor(self, editor):
            self.reloaded.append(editor)
            return True

    def test_action_reload_dispatches_to_existing_editor_reload(self):
        editor = SimpleNamespace(file_path=Path("document.txt"), is_modified=lambda: False)
        window = self.ReloadWindow(editor)

        window.action_reload()

        self.assertEqual(window.reloaded, [editor])

    def test_action_reload_respects_dirty_buffer_confirmation(self):
        editor = SimpleNamespace(file_path=Path("document.txt"), is_modified=lambda: True)
        window = self.ReloadWindow(editor)
        with patch("ui.main_window.QMessageBox.question", return_value=0):
            window.action_reload()

        self.assertEqual(window.reloaded, [])

    def test_reload_uses_the_size_aware_loader_for_the_open_editor(self):
        class Loader:
            created = []

            def __init__(self, path, editor, window):
                self.path = path
                self.editor = editor
                self.window = window
                self.load_finished = ReloadAndExternalChangeTests.Signal()
                self.load_error = ReloadAndExternalChangeTests.Signal()
                self.started = False
                self.created.append(self)

            def start(self):
                self.started = True

        class Editor:
            file_path = Path("document.txt")

        editor = Editor()
        window = SimpleNamespace(_lazy_loaders={})
        with patch("core.lazy_loader.LazyLoader", Loader):
            self.assertTrue(MainWindow._reload_editor(window, editor))

        self.assertEqual(window._lazy_loaders[editor], Loader.created[0])
        self.assertTrue(Loader.created[0].started)

    def test_dirty_buffer_is_not_silently_auto_reloaded(self):
        class Watcher:
            def __init__(self):
                self.blocked = []

            def blockSignals(self, value):
                self.blocked.append(value)

            def addPath(self, _path):
                pass

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "document.txt"
            path.write_text("disk", encoding="utf-8")
            editor = SimpleNamespace(
                file_path=path,
                _is_saving=False,
                _tail_mode=False,
                _watcher=Watcher(),
                is_modified=lambda: True,
            )
            shown = []
            window = SimpleNamespace(
                _current_editor=lambda: editor,
                _show_external_change_dialog=lambda item: shown.append(item),
            )
            with patch("config.settings.Settings.instance", return_value=SimpleNamespace(
                    get=lambda *_args: True)):
                MainWindow._on_file_changed_externally(window, editor)

        self.assertEqual(shown, [editor])


class AutobackupTests(unittest.TestCase):
    class Window:
        _autobackup_source_id = staticmethod(MainWindow._autobackup_source_id)
        _autobackup_bytes = staticmethod(MainWindow._autobackup_bytes)
        _prune_autobackups = MainWindow._prune_autobackups
        _write_autobackup = MainWindow._write_autobackup
        _autosave_file_to_backup = MainWindow._autosave_file_to_backup

        def __init__(self, backup_dir):
            self.backup_dir = backup_dir
            self.failures = []

        def _get_backup_dir(self):
            return self.backup_dir

        def _report_autobackup_failure(self, path, error):
            self.failures.append((path, error))

    class Editor:
        def __init__(self, path, content, encoding="UTF-8"):
            self.file_path = path
            self._content = content
            self.encoding = encoding
            self._write_bom = False

        def get_content(self):
            return self._content

    def _settings(self, *, autosave=True, per_file=20, total=200):
        values = {
            "file/autosave_to_backup": autosave,
            "file/autobackup_max_per_file": per_file,
            "file/autobackup_max_total": total,
        }
        return SimpleNamespace(get=lambda key, default=None: values.get(key, default))

    def test_autosave_separates_same_basenames_and_preserves_format(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "one" / "notes.txt"
            second = root / "two" / "notes.txt"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_bytes(b"old\r\n")
            second.write_bytes(b"old\r\n")
            window = self.Window(root / "backups")
            one = self.Editor(first, "caf\u00e8\r\n", "Latin-1")
            two = self.Editor(second, "second\r\n", "Latin-1")

            with patch("config.settings.Settings.instance", return_value=self._settings()):
                one_backup = window._write_autobackup(one, snapshot=False)
                two_backup = window._write_autobackup(two, snapshot=False)

            self.assertNotEqual(one_backup, two_backup)
            self.assertEqual(one_backup.read_bytes(), "caf\u00e8\r\n".encode("latin-1"))
            self.assertEqual(two_backup.read_bytes(), b"second\r\n")

    def test_autosave_preserves_utf16_bom_and_crlf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "notes.txt"
            source.write_bytes("old\r\n".encode("utf-16"))
            window = self.Window(root / "backups")
            editor = self.Editor(source, "new\r\n", "UTF-16-LE")

            with patch("config.settings.Settings.instance", return_value=self._settings()):
                backup = window._write_autobackup(editor, snapshot=False)

            self.assertEqual(backup.read_bytes(), "new\r\n".encode("utf-16"))

    def test_timestamped_backups_are_unique_and_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "notes.txt"
            source.write_text("old\n", encoding="utf-8")
            window = self.Window(root / "backups")
            editor = self.Editor(source, "new\n")

            with patch("config.settings.Settings.instance", return_value=self._settings(per_file=2, total=2)):
                backups = [window._write_autobackup(editor, snapshot=True) for _ in range(3)]

            self.assertEqual(len(set(backups)), 3)
            self.assertFalse(backups[0].exists())
            self.assertEqual(len(list(window.backup_dir.glob("*.autobackup*.bak"))), 2)

    def test_autosave_write_errors_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "notes.txt"
            source.write_text("old\n", encoding="utf-8")
            window = self.Window(root / "backups")
            editor = self.Editor(source, "new\n")

            with patch("config.settings.Settings.instance", return_value=self._settings()), patch(
                "core.persistence.atomic_write_bytes", side_effect=OSError("disk full")
            ):
                window._autosave_file_to_backup(editor)

            self.assertEqual(window.failures[0][0], source)
            self.assertIn("disk full", str(window.failures[0][1]))


class StartupLocaleTests(unittest.TestCase):
    def test_explicit_language_wins_over_locale_detection(self):
        settings = SimpleNamespace(get=lambda _key, _default=None: "de")
        i18n = SimpleNamespace(available_languages=lambda: {"en": "English", "it": "Italiano"})

        self.assertEqual(_startup_language(settings, i18n), "de")

    def test_unconfigured_language_uses_supported_system_locale(self):
        settings = SimpleNamespace(get=lambda _key, default=None: default)
        i18n = SimpleNamespace(available_languages=lambda: {"en": "English", "fr": "Francais"})
        locale = SimpleNamespace(name=lambda: "fr_CA")

        with patch("PyQt6.QtCore.QLocale.system", return_value=locale):
            self.assertEqual(_startup_language(settings, i18n), "fr")


if __name__ == "__main__":
    unittest.main()

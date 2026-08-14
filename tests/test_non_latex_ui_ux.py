import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

from ui.file_browser import FileBrowser
from ui.main_window import MainWindow
from ui.preferences import PreferencesDialog
from ui.project_manager import ProjectManager


class NonLatexUiUxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_preferences_cancel_restores_previewed_theme(self):
        editor = object()
        parent = QWidget()
        editors = []
        parent._tab_manager = SimpleNamespace(all_editors=lambda: editors)
        dialog = PreferencesDialog(parent)
        calls = []
        dialog._theme_mgr = SimpleNamespace(
            set_active=lambda name: calls.append(("active", name)),
            apply_to_editor=lambda target, name: calls.append(("editor", target, name)),
        )
        dialog._theme_preview_baseline = "Baseline"
        editors.append(editor)

        dialog._restore_theme_preview()

        self.assertEqual(calls, [("active", "Baseline"), ("editor", editor, "Baseline")])
        dialog.deleteLater()
        parent.deleteLater()

    def test_dock_visibility_updates_menu_action_without_triggering_it(self):
        action = QAction("Panel")
        action.setCheckable(True)
        window = SimpleNamespace(_actions={"panel": action})

        MainWindow._on_dock_visibility_changed(window, "panel", True)

        self.assertTrue(action.isChecked())

    def test_file_deletion_uses_trash_and_defaults_to_cancel(self):
        browser = FileBrowser()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "delete-me.txt"
            path.write_text("data", encoding="utf-8")
            sent_to_trash = []
            trash_module = SimpleNamespace(send2trash=lambda value: sent_to_trash.append(value))
            with patch.dict(sys.modules, {"send2trash": trash_module}), patch(
                "ui.file_browser.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ) as question:
                browser._delete(path)

        self.assertEqual(sent_to_trash, [str(path)])
        self.assertEqual(question.call_args.args[4], QMessageBox.StandardButton.Cancel)
        browser.deleteLater()

    def test_group_label_edits_update_project_data_and_mark_dirty(self):
        manager = ProjectManager(QWidget())
        manager._data = {"name": "Test", "groups": [{"name": "Old", "files": []}]}
        manager._dirty = False
        manager._rebuild_tree()
        group = manager._tree.topLevelItem(0)

        group.setText(0, "New")

        self.assertEqual(manager._project_data()["groups"][0]["name"], "New")
        self.assertTrue(manager._dirty)
        manager.deleteLater()

    def test_dirty_unsaved_project_cannot_be_replaced_after_cancelled_save(self):
        manager = ProjectManager(QWidget())
        manager._data = {"name": "Test", "groups": []}
        manager._dirty = True
        manager._project_path = None
        with patch("ui.project_manager.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes), patch.object(
            manager, "action_save"
        ):
            self.assertFalse(manager._confirm_project_replacement())
        manager.deleteLater()


if __name__ == "__main__":
    unittest.main()

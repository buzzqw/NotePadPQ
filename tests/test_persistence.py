import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from config.themes import ThemeManager
from core.file_manager import FileManager
from core.macro import MacroManager
from core.persistence import atomic_write_json, atomic_write_text, load_json
from core.recent_files import RecentFiles
from core.session import Session
from editor.snippets import SnippetManager


class PersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_atomic_text_replaces_existing_content_without_temp_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.txt"
            path.write_text("old", encoding="utf-8")

            atomic_write_text(path, "new")

            self.assertEqual(path.read_text(encoding="utf-8"), "new")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_invalid_json_is_archived_before_default_is_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("{broken", encoding="utf-8")

            self.assertEqual(load_json(path, validate=lambda value: isinstance(value, dict), default={}), {})

            archived = list(Path(directory).glob("state.json.invalid-*"))
            self.assertFalse(path.exists())
            self.assertEqual(len(archived), 1)
            self.assertEqual(archived[0].read_text(encoding="utf-8"), "{broken")

    def test_schema_invalid_json_is_archived(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            atomic_write_json(path, ["not", "an", "object"])

            self.assertIsNone(load_json(path, validate=lambda value: isinstance(value, dict)))

            self.assertEqual(len(list(Path(directory).glob("state.json.invalid-*"))), 1)

    def test_recent_files_rejects_invalid_entry_types_without_overwriting_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recent_files.json"
            path.write_text('{"recent": [42], "pinned": []}', encoding="utf-8")
            recent = RecentFiles.__new__(RecentFiles)
            recent._path = path

            self.assertEqual(recent._load(), ([], set()))

            self.assertEqual(len(list(Path(directory).glob("recent_files.json.invalid-*"))), 1)

    def test_session_rejects_invalid_manifest_and_preserves_it(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Session()
            session._path = Path(directory) / "session.json"
            session._path.write_text('{"tabs": "wrong"}', encoding="utf-8")

            self.assertFalse(session.restore(object()))

            self.assertEqual(len(list(Path(directory).glob("session.json.invalid-*"))), 1)

    def test_user_snippet_schema_errors_are_archived(self):
        with tempfile.TemporaryDirectory() as directory:
            snippets_dir = Path(directory) / "snippets"
            snippets_dir.mkdir()
            bad = snippets_dir / "python.json"
            bad.write_text('{"bad": {"trigger": "x", "body": 1}}', encoding="utf-8")

            with patch("editor.snippets.get_data_dir", return_value=Path(directory)):
                manager = SnippetManager()

            self.assertNotIn("bad", manager._snippets["python"])
            self.assertEqual(len(list(snippets_dir.glob("python.json.invalid-*"))), 1)

    def test_invalid_theme_is_archived_instead_of_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            themes_dir = Path(directory) / "themes"
            themes_dir.mkdir()
            bad = themes_dir / "broken.json"
            bad.write_text('{"meta": {"name": "Broken"}, "ui": []}', encoding="utf-8")

            with patch("core.platform.get_data_dir", return_value=Path(directory)):
                manager = ThemeManager()

            self.assertNotIn("Broken", manager.available_themes())
            self.assertEqual(len(list(themes_dir.glob("broken.json.invalid-*"))), 1)

    def test_invalid_macro_is_archived_without_replacing_current_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            path.write_text('{"name": "Broken", "actions": ["not an action"]}', encoding="utf-8")
            manager = MacroManager()
            manager._actions = [{"type": "insert", "text": "keep"}]

            self.assertFalse(manager.load(path))
            self.assertEqual(manager._actions, [{"type": "insert", "text": "keep"}])
            self.assertEqual(len(list(Path(directory).glob("broken.json.invalid-*"))), 1)

    def test_backup_is_an_atomic_byte_for_byte_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "document.txt"
            payload = b"\xff\xfeencoded\x00"
            path.write_bytes(payload)

            FileManager._make_backup(path)

            backup = path.with_suffix(".txt.bak")
            self.assertEqual(backup.read_bytes(), payload)
            self.assertEqual(sorted(entry.name for entry in Path(directory).iterdir()),
                             ["document.txt", "document.txt.bak"])


if __name__ == "__main__":
    unittest.main()

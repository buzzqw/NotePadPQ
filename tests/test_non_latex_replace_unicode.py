import os
import re
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QTreeWidget

from editor.editor_widget import INDICATOR_SPELL, EditorWidget
from ui.find_replace import (
    FindReplaceDialog,
    _nearest_result_index,
    _ReplaceInFilesWorker,
    _ReplaceWriterWorker,
)
from ui.incremental_search import IncrementalSearchBar, _IncrementalSearchWorker
from ui.spell_check_dialog import SpellCheckDialog


class ReplaceInFilesSafetyTest(unittest.TestCase):
    def _scan(self, path: Path, pattern: str, replacement: str):
        worker = _ReplaceInFilesWorker(
            str(path.parent), [path.name], replacement, re.compile(pattern), False
        )
        result = []
        worker.finished.connect(lambda files, _matches, _count: result.extend(files))
        worker.scan()
        return result

    def test_preserves_latin1_crlf_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.txt"
            path.write_bytes("caffè\r\nneedle\r\n".encode("latin-1"))

            files = self._scan(path, "needle", "done")
            writer = _ReplaceWriterWorker(files)
            writer.write_all()

            self.assertEqual(path.read_bytes(), "caffè\r\ndone\r\n".encode("latin-1"))
            self.assertEqual(path.with_suffix(".txt.bak").read_bytes(), "caffè\r\nneedle\r\n".encode("latin-1"))

    def test_preserves_utf16_bom_and_crlf(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.txt"
            original = "alpha\r\nneedle\r\n".encode("utf-16")
            path.write_bytes(original)

            files = self._scan(path, "needle", "done")
            _ReplaceWriterWorker(files).write_all()

            self.assertEqual(path.read_bytes(), "alpha\r\ndone\r\n".encode("utf-16"))
            self.assertEqual(path.with_suffix(".txt.bak").read_bytes(), original)

    def test_refuses_stale_source_after_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.txt"
            path.write_text("needle\n", encoding="utf-8")
            files = self._scan(path, "needle", "done")
            path.write_text("changed\n", encoding="utf-8")

            writer = _ReplaceWriterWorker(files)
            errors = []
            writer.finished.connect(lambda _matches, _files, result: errors.extend(result))
            writer.write_all()

            self.assertEqual(path.read_text(encoding="utf-8"), "changed\n")
            self.assertTrue(errors)

    def test_result_list_starts_at_match_nearest_to_cursor_line(self):
        self.assertEqual(_nearest_result_index([2, 8, 14], 9), 1)
        self.assertEqual(_nearest_result_index([2, 8, 14], 11), 2)
        self.assertEqual(_nearest_result_index([2, 8, 14], 5), 1)
        self.assertIsNone(_nearest_result_index([], 5))


class FindReplaceSelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_occurrence_list_selects_result_nearest_to_saved_cursor_line(self):
        dialog = FindReplaceDialog.__new__(FindReplaceDialog)
        dialog._mw = None
        dialog._find_occurrences = QTreeWidget()
        dialog._lbl_status = QLabel()
        dialog._find_anchor_line = 9

        class Editor:
            file_path = None

            def text(self):
                lines = [""] * 15
                for line in (2, 8, 14):
                    lines[line] = "needle"
                return "\n".join(lines)

        dialog._populate_occurrences(
            Editor(), "needle", {
                "case_sensitive": False,
                "whole_word": False,
                "regex": False,
            },
            publish_panel=False,
        )

        selected = dialog._find_occurrences.currentItem()
        self.assertIsNotNone(selected)
        self.assertEqual(selected.data(0, Qt.ItemDataRole.UserRole)["line"], 9)
        dialog._find_occurrences.deleteLater()


class UnicodeCoordinateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = EditorWidget()
        self.editor.load_content("àbc\n", "UTF-8")
        self.addCleanup(self.editor.deleteLater)

    def test_spell_indicator_and_replacement_use_utf8_byte_columns(self):
        self.editor._spell_gen = 0
        self.editor._spell_check_range = (0, 1)
        self.editor._on_spell_check_done(0, [(0, 1, 0, 3)])
        self.assertEqual(self.editor.indicatorValueAt(INDICATOR_SPELL, 2), 1)
        self.assertEqual(self.editor.indicatorValueAt(INDICATOR_SPELL, 1), 0)

        self.editor._spell_replace(0, 2, 0, 4, "XY")
        self.assertEqual(self.editor.text(), "àXY\n")

    def test_spell_dialog_offsets_are_converted_to_bytes(self):
        dialog = SpellCheckDialog.__new__(SpellCheckDialog)
        dialog._editor = self.editor
        self.assertEqual(dialog._abs_to_line_col(1, 3), (0, 2, 0, 4))

    def test_incremental_pattern_honors_match_case(self):
        bar = IncrementalSearchBar.__new__(IncrementalSearchBar)

        class Check:
            def __init__(self, checked):
                self.checked = checked

            def isChecked(self):
                return self.checked

        bar._cb_regex = Check(False)
        bar._cb_word = Check(False)
        bar._cb_case = Check(True)
        self.assertEqual([m.group(0) for m in bar._build_pattern("abc").finditer("Abc abc")], ["abc"])
        bar._cb_case = Check(False)
        self.assertEqual([m.group(0) for m in bar._build_pattern("abc").finditer("Abc abc")], ["Abc", "abc"])

    def test_incremental_worker_returns_snapshot_offsets(self):
        emitted = []
        worker = _IncrementalSearchWorker("Alpha alpha", re.compile("alpha", re.IGNORECASE))
        worker.finished.connect(emitted.append)

        worker.run()

        self.assertEqual(emitted, [[(0, 5), (6, 11)]])


if __name__ == "__main__":
    unittest.main()

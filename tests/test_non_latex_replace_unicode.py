import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QTreeWidget, QTreeWidgetItem

from core.safe_regex import has_catastrophic_backtracking, pattern_error
from editor.editor_widget import INDICATOR_FIND, INDICATOR_SPELL, EditorWidget
from ui.find_replace import (
    FindReplaceDialog,
    _FindInFilesWorker,
    _nearest_result_index,
    _OccurrenceScanWorker,
    _ReplaceInFilesWorker,
    _ReplaceWriterWorker,
)
from ui.incremental_search import (
    _INC_CUR_INDICATOR,
    IncrementalSearchBar,
    _IncrementalSearchWorker,
)
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
        dialog._occurrence_gen = 0
        dialog._occurrence_worker = None
        dialog._old_occurrence_workers = []

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

    def test_auto_refresh_restores_editor_position_after_find(self):
        class Check:
            def isChecked(self):
                return True

        class Tabs:
            def currentIndex(self):
                return 0

        class Edit:
            def currentText(self):
                return "needle"

        class Editor:
            def __init__(self):
                self.position = (4, 7)
                self.selection = None

            def getCursorPosition(self):
                return self.position

            def hasSelectedText(self):
                return self.selection is not None

            def getSelection(self):
                return self.selection

            def setCursorPosition(self, line, column):
                self.position = (line, column)
                self.selection = None

            def setSelection(self, line, column, end_line, end_column):
                self.selection = (line, column, end_line, end_column)

        editor = Editor()
        dialog = SimpleNamespace(
            _tabs=Tabs(),
            _chk_auto_refresh=Check(),
            _find_edit=Edit(),
            _find_anchor_line=None,
            _current_editor=lambda: editor,
            _get_flags=lambda: {
                "case_sensitive": False,
                "whole_word": False,
                "regex": False,
            },
            _radio_fwd=SimpleNamespace(isChecked=lambda: True),
            _find_occurrences=SimpleNamespace(clear=lambda: None),
            isVisible=lambda: True,
        )

        def move_to_match(*_args, **_kwargs):
            editor.setSelection(12, 0, 12, 6)

        dialog._do_find = move_to_match
        dialog._populate_occurrences = lambda *_args, **_kwargs: None

        FindReplaceDialog._refresh_find_results(dialog)

        self.assertEqual(editor.position, (4, 7))
        self.assertIsNone(editor.selection)


class TypographySearchTest(unittest.TestCase):
    """La ricerca letterale deve trattare come equivalenti apostrofi,
    virgolette e trattini tipografici e gli accenti NFC/NFD."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = FindReplaceDialog.__new__(FindReplaceDialog)
        self.flags = {
            "case_sensitive": False,
            "whole_word": False,
            "regex": False,
            "wrap": True,
            "in_selection": False,
            "smart_search": False,
        }

    def test_build_pattern_folds_apostrophes_and_quotes(self):
        pattern = self.dialog._build_pattern("un po’ “casa”", self.flags)
        self.assertTrue(pattern.search("un po' \"casa\""))
        self.assertTrue(pattern.search("un po’ “casa”"))

    def test_build_pattern_folds_ellipsis_and_double_dash(self):
        ellipsis = self.dialog._build_pattern("...", self.flags)
        self.assertTrue(ellipsis.search("test… fine"))
        self.assertTrue(self.dialog._build_pattern("…", self.flags).search("test... fine"))

        em_dash = self.dialog._build_pattern("--", self.flags)
        self.assertTrue(em_dash.search("a—b"))
        self.assertTrue(em_dash.search("a–b"))

    def test_build_pattern_folds_nfc_and_nfd(self):
        pattern = self.dialog._build_pattern("perché", self.flags)
        self.assertTrue(pattern.search("perché"))
        self.assertTrue(pattern.search("perche\u0301"))

    def test_whole_word_and_regex_modes_still_work(self):
        whole = self.dialog._build_pattern(
            "casa", {**self.flags, "whole_word": True})
        self.assertTrue(whole.search("una casa qui"))
        self.assertFalse(whole.search("casalinga"))

        regex = self.dialog._build_pattern(
            "po.", {**self.flags, "regex": True})
        self.assertTrue(regex.search("po’"))

    def test_smart_search_folds_variants(self):
        patterns = self.dialog._smart_patterns("serve po’ Forza", self.flags)
        self.assertTrue(
            self.dialog._smart_line_matches("serve un po' di Forza", patterns))

    def _dialog_for(self, editor):
        dialog = FindReplaceDialog.__new__(FindReplaceDialog)
        dialog._lbl_status = QLabel()
        dialog._mw = SimpleNamespace(
            _tab_manager=SimpleNamespace(current_editor=lambda: editor))
        dialog._do_smart_find = lambda *_a, **_k: False
        dialog._highlight_all = lambda *_a, **_k: 0
        dialog._emphasize_find_selection = lambda *_a, **_k: None
        dialog._in_selection_range = None
        dialog._in_selection_match = None
        dialog._last_pattern_error = None
        return dialog

    def test_replace_pattern_matches_every_variant(self):
        pattern = self.dialog._build_pattern("po’", self.flags)
        replaced, count = pattern.subn("X", "po' e po’ e PO'")
        self.assertEqual(count, 3)
        self.assertEqual(replaced, "X e X e X")

    def test_in_selection_stays_in_range_and_advances(self):
        editor = EditorWidget()
        editor.setText("foo bar foo baz foo")
        self.addCleanup(editor.deleteLater)
        dialog = self._dialog_for(editor)
        flags = {**self.flags, "in_selection": True}
        widget = SimpleNamespace(text=lambda: "foo", currentText=lambda: "foo")

        editor.setSelection(0, 0, 0, 11)  # "foo bar foo"
        self.assertTrue(dialog._do_find(
            widget, forward=True, flags=flags,
            status_label=dialog._lbl_status))
        self.assertEqual(editor.getSelection(), (0, 0, 0, 3))

        self.assertTrue(dialog._do_find(
            widget, forward=True, flags=flags,
            status_label=dialog._lbl_status))
        self.assertEqual(editor.getSelection(), (0, 8, 0, 11))

        # Il terzo "foo" (colonna 16) è fuori dalla selezione: si avvolge.
        self.assertTrue(dialog._do_find(
            widget, forward=True, flags=flags,
            status_label=dialog._lbl_status))
        self.assertEqual(editor.getSelection(), (0, 0, 0, 3))

    def test_in_selection_reports_no_match_outside_range(self):
        editor = EditorWidget()
        editor.setText("foo bar foo")
        self.addCleanup(editor.deleteLater)
        dialog = self._dialog_for(editor)
        flags = {**self.flags, "in_selection": True}
        widget = SimpleNamespace(text=lambda: "foo", currentText=lambda: "foo")

        editor.setSelection(0, 4, 0, 7)  # "bar"
        self.assertFalse(dialog._do_find(
            widget, forward=True, flags=flags,
            status_label=dialog._lbl_status))

    def test_regex_find_uses_python_semantics(self):
        editor = EditorWidget()
        editor.setText("a1 b2 c3")
        self.addCleanup(editor.deleteLater)
        dialog = self._dialog_for(editor)
        flags = {**self.flags, "regex": True}
        widget = SimpleNamespace(text=lambda: r"\d", currentText=lambda: r"\d")

        self.assertTrue(dialog._do_find(
            widget, forward=True, flags=flags,
            status_label=dialog._lbl_status))
        self.assertEqual(editor.selectedText(), "1")
        self.assertTrue(dialog._do_find(
            widget, forward=True, flags=flags,
            status_label=dialog._lbl_status))
        self.assertEqual(editor.selectedText(), "2")

    def test_do_find_matches_variant_and_advances(self):
        editor = EditorWidget()
        editor.setText("un po' qui\nun po’ là")
        self.addCleanup(editor.deleteLater)
        dialog = self._dialog_for(editor)
        widget = SimpleNamespace(text=lambda: "po’", currentText=lambda: "po’")

        self.assertTrue(dialog._do_find(
            widget, forward=True, flags=self.flags,
            status_label=dialog._lbl_status))
        self.assertEqual(editor.selectedText(), "po'")

        self.assertTrue(dialog._do_find(
            widget, forward=True, flags=self.flags,
            status_label=dialog._lbl_status))
        self.assertEqual(editor.selectedText(), "po’")


class CharacterColumnAlignmentTest(unittest.TestCase):
    """setSelection usa colonne in caratteri, gli indicatori in byte: su righe
    con accenti prima del match i due valori devono restare distinti."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = EditorWidget()
        self.editor.setText("à parola fine\ncittà parola")
        self.addCleanup(self.editor.deleteLater)

    def test_highlight_find_match_accepts_character_columns(self):
        self.editor.highlight_find_match(0, 2, 8)
        self.assertEqual(self.editor.getSelection(), (0, 2, 0, 8))
        self.assertEqual(self.editor.selectedText(), "parola")
        # Byte: "à " occupa 3 byte, quindi la parola parte dal byte 3.
        self.assertEqual(
            self.editor.indicatorValueAt(
                INDICATOR_FIND, self.editor.positionFromLineIndex(0, 2)), 1)
        self.assertEqual(
            self.editor.indicatorValueAt(
                INDICATOR_FIND, self.editor.positionFromLineIndex(0, 8)), 0)

    def test_goto_occurrence_selects_the_word_after_an_accent(self):
        dialog = FindReplaceDialog.__new__(FindReplaceDialog)
        dialog._current_editor = lambda: self.editor
        item = QTreeWidgetItem()
        item.setData(0, Qt.ItemDataRole.UserRole,
                     {"line": 1, "col": 2, "len": 6})
        dialog._goto_occurrence(item)
        self.assertEqual(self.editor.getSelection(), (0, 2, 0, 8))
        self.assertEqual(self.editor.selectedText(), "parola")

    def test_incremental_goto_keeps_character_selection(self):
        bar = IncrementalSearchBar.__new__(IncrementalSearchBar)
        bar._current_editor = lambda: self.editor
        bar._matches = [(0, 2, 0, 8)]
        bar._current_idx = -1
        bar._count_lbl = QLabel()
        self.addCleanup(bar._count_lbl.deleteLater)
        bar._goto(0)
        self.assertEqual(self.editor.getSelection(), (0, 2, 0, 8))
        self.assertEqual(self.editor.selectedText(), "parola")
        self.assertEqual(
            self.editor.indicatorValueAt(
                _INC_CUR_INDICATOR,
                self.editor.positionFromLineIndex(0, 2)), 1)


class SmartSearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = FindReplaceDialog.__new__(FindReplaceDialog)

    def test_smart_search_requires_all_terms_on_one_line(self):
        patterns = self.dialog._smart_patterns(
            "armatura prova di magia",
            {"case_sensitive": False, "whole_word": False, "regex": False},
        )

        self.assertIsNotNone(patterns)
        self.assertTrue(
            self.dialog._smart_line_matches(
                "armatura con parole nel mezzo prova di magia", patterns
            )
        )
        self.assertFalse(
            self.dialog._smart_line_matches("armatura su una riga", patterns)
        )
        self.assertFalse(
            self.dialog._smart_line_matches("prova di magia su un'altra riga", patterns)
        )

    def test_smart_search_respects_whole_word(self):
        patterns = self.dialog._smart_patterns(
            "armatura magia",
            {"case_sensitive": False, "whole_word": True, "regex": False},
        )

        self.assertFalse(
            self.dialog._smart_line_matches("armaturata e magia", patterns)
        )
        self.assertTrue(
            self.dialog._smart_line_matches("armatura e magia", patterns)
        )

    def test_smart_search_navigates_matching_lines(self):
        editor = EditorWidget()
        editor.load_content(
            "armatura con testo prova di magia\n"
            "nessuna corrispondenza\n"
            "prova di magia e armatura\n",
            "UTF-8",
        )
        self.addCleanup(editor.deleteLater)
        editor.setCursorPosition(0, 0)
        flags = {
            "case_sensitive": False,
            "whole_word": False,
            "regex": False,
            "wrap": True,
            "smart_search": True,
        }
        status = QLabel()

        self.assertTrue(
            self.dialog._do_smart_find(
                editor, "armatura prova di magia", flags, True, status
            )
        )
        self.assertEqual(editor.getSelection()[0], 0)

        self.assertTrue(
            self.dialog._do_smart_find(
                editor, "armatura prova di magia", flags, True, status
            )
        )
        self.assertEqual(editor.getSelection()[0], 2)


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

    def test_incremental_pattern_folds_typography(self):
        bar = IncrementalSearchBar.__new__(IncrementalSearchBar)

        class Check:
            def __init__(self, checked):
                self.checked = checked

            def isChecked(self):
                return self.checked

        bar._cb_regex = Check(False)
        bar._cb_word = Check(False)
        bar._cb_case = Check(False)
        pattern = bar._build_pattern("po’")
        self.assertEqual(
            [m.group(0) for m in pattern.finditer("po' po’")],
            ["po'", "po’"],
        )

    def test_incremental_worker_returns_snapshot_offsets(self):
        emitted = []
        worker = _IncrementalSearchWorker("Alpha alpha", re.compile("alpha", re.IGNORECASE))
        worker.finished.connect(emitted.append)

        worker.run()

        self.assertEqual(emitted, [[(0, 5), (6, 11)]])


class OccurrenceScanWorkerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_nested_quantifier_patterns_are_rejected(self):
        for pattern in (r"(a+)+$", r"(.*)*", r"(\d+){2,}", r"(ab*)+"):
            self.assertTrue(
                has_catastrophic_backtracking(pattern), pattern)
            self.assertIsNotNone(pattern_error(pattern))

    def test_normal_regex_patterns_are_allowed(self):
        for pattern in (
                r"hello", r"(\w+)@(\w+)", r"(foo|bar)+", r"a+?",
                r"(\d{1,3}\.){3}\d{1,3}"):
            self.assertFalse(
                has_catastrophic_backtracking(pattern), pattern)

    def test_scan_counts_all_matches_but_reports_one_row_per_line(self):
        worker = _OccurrenceScanWorker(
            "alfa alfa\nbeta\nalfa", re.compile("alfa"), None, 4, 2000
        )
        captured = []
        worker.done.connect(
            lambda gen, count, truncated, rows:
            captured.append((gen, count, truncated, rows))
        )

        worker.run()

        generation, count, truncated, rows = captured[0]
        self.assertEqual(generation, 4)
        self.assertEqual(count, 3)
        self.assertFalse(truncated)
        self.assertEqual([row[0] for row in rows], [0, 2])
        self.assertEqual(rows[0][1:3], (0, 4))

    def test_scan_truncates_rows_but_keeps_count(self):
        text = "\n".join(f"alfa {index}" for index in range(10))
        worker = _OccurrenceScanWorker(
            text, re.compile("alfa"), None, 1, 3
        )
        captured = []
        worker.done.connect(
            lambda gen, count, truncated, rows:
            captured.append((gen, count, truncated, rows))
        )

        worker.run()

        _gen, count, truncated, rows = captured[0]
        self.assertEqual(count, 10)
        self.assertTrue(truncated)
        self.assertEqual(len(rows), 3)

    def test_find_in_files_skips_binary_and_ignored_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "text.txt").write_text("needle\n", encoding="utf-8")
            (root / "binary.bin").write_bytes(b"\x00" * 32 + b"needle")
            ignored = root / ".git"
            ignored.mkdir()
            (ignored / "hidden.txt").write_text("needle\n", encoding="utf-8")

            found = []
            worker = _FindInFilesWorker(
                str(root), [], "needle", False, False, True)
            worker.file_done.connect(
                lambda rel, abs_path, count, entries:
                found.append((rel, count, entries)))
            worker.run()

            self.assertEqual([item[0] for item in found], ["text.txt"])
            self.assertEqual(found[0][1], 1)


if __name__ == "__main__":
    unittest.main()

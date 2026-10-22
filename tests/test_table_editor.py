"""Tests for editor.table_editor, with focus on tabularray environments."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from editor.editor_widget import EditorWidget
from editor.table_editor import (
    _row_terminator_index,
    _split_cells,
    add_column,
    add_row,
    delete_column,
    detect_table,
)


class TableEditorTabularrayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _editor(self, text: str, line: int = 1, column: int = 0) -> EditorWidget:
        editor = EditorWidget()
        editor.setText(text)
        editor.setCursorPosition(line, column)
        return editor

    def test_detect_tblr_reads_colspec(self):
        editor = self._editor(
            "\\begin{tblr}{colspec={|l|X[c]|}, hlines}\n"
            "a & b \\\\\n"
            "\\end{tblr}"
        )
        info = detect_table(editor)
        self.assertIsNotNone(info)
        self.assertEqual(info["env_name"], "tblr")
        self.assertEqual(info["col_spec"], "|l|X[c]|")
        self.assertEqual(info["col_count"], 2)

    def test_detect_longtblr_with_nested_caption(self):
        editor = self._editor(
            "\\begin{longtblr}[caption={A {nested} caption}]{colspec={lcr}}\n"
            "a & b & c \\\\\n"
            "\\end{longtblr}"
        )
        info = detect_table(editor)
        self.assertIsNotNone(info)
        self.assertEqual(info["col_spec"], "lcr")
        self.assertEqual(info["col_count"], 3)

    def test_add_column_updates_colspec_and_rows(self):
        editor = self._editor(
            "\\begin{tblr}{colspec={|l|X[c]|}}\n"
            "a & b \\\\\n"
            "\\end{tblr}"
        )
        self.assertTrue(add_column(editor, "right"))
        text = editor.text()
        self.assertIn("colspec={|l|cX[c]|}", text)
        self.assertIn("a & & b", text)

    def test_delete_column_removes_x_option(self):
        editor = self._editor(
            "\\begin{tblr}{colspec={|l|X[c]|}}\n"
            "a & b \\\\\n"
            "\\end{tblr}",
            line=1,
            column=4,
        )
        self.assertTrue(delete_column(editor))
        text = editor.text()
        self.assertIn("colspec={|l|}", text)
        self.assertIn("a \\\\", text)
        self.assertNotIn("& b", text)

    def test_row_terminator_ignores_double_backslash_in_braces(self):
        line = "\\SetCell[r=2]{c}{a \\\\ b} & c \\\\"
        self.assertEqual(_row_terminator_index(line), line.rfind("\\\\"))

    def test_split_cells_ignores_ampersand_in_braces(self):
        self.assertEqual(_split_cells("a & {b & c} & d"), ["a ", " {b & c} ", " d"])

    def test_add_row_infers_width_without_colspec(self):
        editor = self._editor(
            "\\begin{tblr}\na & b \\\\\n\\end{tblr}"
        )
        self.assertTrue(add_row(editor, "below"))
        self.assertIn(" &  \\\\", editor.text())


if __name__ == "__main__":
    unittest.main()

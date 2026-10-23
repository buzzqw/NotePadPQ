import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QWidget

from ui.toolbar_quick_search import ToolbarQuickSearch, _match_score


class _Editor(QWidget):
    def __init__(self, path=None, content=""):
        super().__init__()
        self.file_path = Path(path) if path else None
        self._content = content
        self.cursor = None
        self.visible_line = None
        self.selection = None

    def text(self):
        return self._content

    def setCursorPosition(self, line, col):
        self.cursor = (line, col)

    def setSelection(self, line_from, col_from, line_to, col_to):
        self.selection = (line_from, col_from, line_to, col_to)

    def ensureLineVisible(self, line):
        self.visible_line = line


class _MainWindow(QWidget):
    def __init__(self, editors, actions):
        super().__init__()
        self._editors = editors
        self._actions = actions
        self.active_editor = None

    def all_editors(self):
        return self._editors

    def set_current_editor(self, editor):
        self.active_editor = editor

    def _current_editor(self):
        return self._editors[0]


class ToolbarQuickSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.analysis = _Editor(
            "/tmp/analisi.md",
            "def alpha():\n    pass\nclass Beta:\n    pass\n",
        )
        self.report = _Editor("/tmp/relazione.txt", "testo\n")
        self.window = _MainWindow(
            [self.analysis, self.report],
            {
                "find": QAction("Trova"),
                "save": QAction("Salva"),
                "prefs": QAction("Preferenze"),
            },
        )
        self.window._tab_manager = self.window
        self.field = ToolbarQuickSearch(self.window)

    def tearDown(self):
        self.field.deleteLater()
        self.window.deleteLater()
        self.analysis.deleteLater()
        self.report.deleteLater()

    def test_match_score_prefers_prefix_over_subsequence(self):
        self.assertEqual(_match_score("", "qualsiasi"), 1)
        self.assertGreater(_match_score("ana", "analisi"), _match_score("ana", "relana"))
        self.assertEqual(_match_score("xyz", "analisi"), 0)

    def test_match_score_folds_typographic_variants(self):
        self.assertGreater(_match_score("po’", "un po' di"), 0)
        self.assertGreater(_match_score("“ciao”", '"ciao"'), 0)

    def test_file_rows_match_name_and_path(self):
        rows = self.field._file_rows("ana")
        self.assertEqual(len(rows), 1)
        label, kind, payload = rows[0]
        self.assertIn("analisi.md", label)
        self.assertEqual(kind, "file")
        self.assertIs(payload, self.analysis)

        by_path = self.field._file_rows("tmp/rel")
        self.assertEqual(len(by_path), 1)
        self.assertIs(by_path[0][2], self.report)

    def test_prefix_rows_for_commands_lines_and_symbols(self):
        commands = self.field._command_rows("trov")
        self.assertEqual(commands[0][1], "command")
        self.assertEqual(commands[0][2].text(), "Trova")

        self.assertEqual(self.field._line_rows("12"), [("Go to line 12", "line", 12)])
        self.assertEqual(self.field._line_rows("zero"), [])

        symbols = self.field._symbol_rows("alp")
        self.assertEqual(symbols[0][1:], ("symbol", 1))

    def test_content_rows_search_text_of_open_files(self):
        rows = self.field._content_rows("class beta")
        self.assertEqual(len(rows), 1)
        label, kind, payload = rows[0]
        self.assertIn("analisi.md:3", label)
        self.assertIn("class Beta", label)
        self.assertEqual(kind, "content")
        editor, line, col_start, col_end = payload
        self.assertIs(editor, self.analysis)
        self.assertEqual((line, col_start, col_end), (2, 0, 10))

    def test_content_rows_ignore_short_queries(self):
        self.assertEqual(self.field._content_rows("pa"), [])

    def test_content_rows_match_typographic_apostrophes(self):
        rules = _Editor(
            "/tmp/regole.md",
            "A tutti serve un po' di Forza. Determina quanto equipaggiamento.\n",
        )
        self.window._editors.append(rules)
        self.addCleanup(rules.deleteLater)

        for query in ("serve un po’ di Fo", "serve un po' di Fo", "serve un po‘ di Fo"):
            rows = self.field._content_rows(query)
            self.assertEqual(len(rows), 1, query)
            label, kind, payload = rows[0]
            self.assertIn("regole.md:1", label)
            self.assertIn("serve un po' di Forza", label)
            self.assertEqual(kind, "content")
            editor, line, col_start, col_end = payload
            self.assertIs(editor, rules)
            self.assertEqual((line, col_start, col_end), (0, 8, 26))
            self.assertEqual(
                rules.text().encode("utf-8")[col_start:col_end],
                b"serve un po' di Fo",
            )

    def test_content_rows_match_decomposed_accents(self):
        editor = _Editor("/tmp/accenti.md", "perche\u0301 sia chiaro\n")
        self.window._editors.append(editor)
        self.addCleanup(editor.deleteLater)

        rows = self.field._content_rows("perché sia")
        self.assertEqual(len(rows), 1)
        editor_out, line, col_start, col_end = rows[0][2]
        self.assertIs(editor_out, editor)
        # Colonna in caratteri: setSelection non usa i byte.
        self.assertEqual((line, col_start, col_end), (0, 0, 11))

    def test_content_result_columns_are_characters_not_bytes(self):
        editor = _Editor("/tmp/accenti.md", "à serve un po' di Forza\n")
        self.window._editors.append(editor)
        self.addCleanup(editor.deleteLater)

        rows = self.field._content_rows("serve un po")
        self.assertEqual(len(rows), 1)
        _editor, line, col_start, col_end = rows[0][2]
        self.assertEqual((line, col_start, col_end), (0, 2, 13))
        self.assertEqual(editor._content[col_start:col_end], "serve un po")
        self.field._run("content", (editor, line, col_start, col_end))
        self.assertEqual(editor.selection, (0, 2, 0, 13))

    def test_default_query_merges_files_and_content(self):
        rows = self.field._rows_for_query("analisi")
        self.assertEqual(rows[0][1], "file")       # il nome del tab resta primo
        self.assertEqual(self.field._rows_for_query("beta")[0][1], "content")

    def test_run_content_activates_editor_and_selects_match(self):
        self.field._run("content", (self.analysis, 2, 0, 10))
        self.assertIs(self.window.active_editor, self.analysis)
        self.assertEqual(self.analysis.selection, (2, 0, 2, 10))
        self.assertEqual(self.analysis.visible_line, 2)

    def test_run_file_activates_tab_and_clears_field(self):
        self.field.setText("analisi")
        self.field._run("file", self.analysis)
        self.assertIs(self.window.active_editor, self.analysis)
        self.assertEqual(self.field.text(), "")

    def test_run_symbol_moves_cursor_to_requested_line(self):
        self.field._run("symbol", 3)
        self.assertEqual(self.analysis.cursor, (2, 0))
        self.assertEqual(self.analysis.visible_line, 2)


if __name__ == "__main__":
    unittest.main()

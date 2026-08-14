import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

from editor.editor_widget import EditorWidget
from editor.snippets import SnippetManager, _process_tabstops


def _tab_event() -> QKeyEvent:
    return QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier)


class SnippetTabstopParsingTest(unittest.TestCase):
    def test_numbered_and_final_stops_are_ordered_correctly(self):
        expanded, stops = _process_tabstops("a${2:two}b${1:one}c$0d")
        self.assertEqual(expanded, "atwobonecd")
        self.assertEqual([n for n, _, _ in stops], [1, 2, 0])

    def test_nested_placeholder_defaults_are_expanded_and_navigable(self):
        expanded, stops = _process_tabstops("${1:open('${2:file}')} ${0}")

        self.assertEqual(expanded, "open('file') ")
        self.assertEqual(stops, [(1, 0, 12), (2, 6, 4), (0, 13, 0)])


class SnippetExpandTest(unittest.TestCase):
    """Copre SnippetManager.expand() e il suo aggancio a Tab in
    editor_widget.py. Prima di questo fix expand() non era mai chiamato da
    nessun punto della UI: i 30 snippet LaTeX predefiniti comparivano solo
    come voci nel popup di completamento, e selezionarle inseriva la sola
    parola trigger — nessuna espansione, nessun tab-stop."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = EditorWidget()
        self.editor._current_language = "latex"

    def tearDown(self):
        self.editor.deleteLater()
        self.app.processEvents()

    def test_expand_replaces_trigger_and_selects_first_tabstop(self):
        self.editor.setText("eq")
        self.editor.setCursorPosition(0, 2)

        expanded = SnippetManager.instance().expand(self.editor, "latex")

        self.assertTrue(expanded)
        self.assertEqual(
            self.editor.text(),
            "\\begin{equation}\n    formula\n    \\label{eq:label}\n\\end{equation}",
        )
        self.assertEqual(self.editor.selectedText(), "formula")

    def test_expand_returns_false_for_unknown_trigger(self):
        self.editor.setText("notasnippet")
        self.editor.setCursorPosition(0, len("notasnippet"))

        expanded = SnippetManager.instance().expand(self.editor, "latex")

        self.assertFalse(expanded)
        self.assertEqual(self.editor.text(), "notasnippet")

    def test_tab_key_expands_known_trigger(self):
        self.editor.setText("eq")
        self.editor.setCursorPosition(0, 2)

        self.editor.keyPressEvent(_tab_event())

        self.assertTrue(self.editor.text().startswith("\\begin{equation}"))
        self.assertEqual(self.editor.selectedText(), "formula")

    def test_tab_key_falls_through_when_no_matching_trigger(self):
        self.editor.setText("hello")
        self.editor.setCursorPosition(0, len("hello"))

        self.editor.keyPressEvent(_tab_event())

        self.assertTrue(self.editor.text().startswith("hello"))
        self.assertEqual(self.editor._tabstops, [])

    def test_tab_key_navigates_active_tabstops_instead_of_re_expanding(self):
        self.editor.setText("eq")
        self.editor.setCursorPosition(0, 2)
        self.editor.keyPressEvent(_tab_event())
        self.assertEqual(self.editor.selectedText(), "formula")

        # Secondo Tab: naviga al tab-stop successivo (${2:label}) invece di
        # tentare di espandere di nuovo un trigger sul testo corrente.
        self.editor.keyPressEvent(_tab_event())
        self.assertEqual(self.editor.selectedText(), "label")

    def test_tab_key_does_not_expand_with_active_selection(self):
        self.editor.setText("eq more text")
        self.editor.setSelection(0, 0, 0, 12)

        self.editor.keyPressEvent(_tab_event())

        self.assertNotIn("\\begin{equation}", self.editor.text())


if __name__ == "__main__":
    unittest.main()

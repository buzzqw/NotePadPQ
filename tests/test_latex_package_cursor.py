import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from editor.editor_widget import EditorWidget
from ui.language_toolbar import _LanguageToolbarWidget


class LatexPackageCursorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _editor(self, text: str) -> EditorWidget:
        ed = EditorWidget()
        ed.setText(text)
        return ed

    def test_package_insertion_restores_cursor_in_body(self):
        ed = self._editor(
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "Hello world\n"
            "\\end{document}\n"
        )
        ed.setCursorPosition(2, 5)

        _LanguageToolbarWidget._ensure_latex_package(ed, "graphicx")

        line, col = ed.getCursorPosition()
        self.assertEqual((line, col), (3, 5))
        ed.insert("<<IMG>>")
        self.assertIn("Hello<<IMG>> world", ed.text())
        self.assertIn("\\usepackage{graphicx}", ed.text())

    def test_package_insertion_keeps_selection(self):
        ed = self._editor(
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "Hello world\n"
            "\\end{document}\n"
        )
        ed.setSelection(2, 0, 2, 5)   # "Hello"

        _LanguageToolbarWidget._ensure_latex_package(ed, "graphicx")

        self.assertTrue(ed.hasSelectedText())
        self.assertEqual(ed.selectedText(), "Hello")
        ed.replaceSelectedText("Bye")
        self.assertIn("Bye world", ed.text())

    def test_existing_package_does_not_move_cursor(self):
        ed = self._editor(
            "\\usepackage{graphicx}\n"
            "\\begin{document}\n"
            "Hello\n"
            "\\end{document}\n"
        )
        ed.setCursorPosition(2, 3)

        _LanguageToolbarWidget._ensure_latex_package(ed, "graphicx")

        ed.insert("!")
        self.assertIn("Hel!lo", ed.text())


if __name__ == "__main__":
    unittest.main()

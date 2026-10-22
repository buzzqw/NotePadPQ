"""Tests for dropping files from the File Browser into a LaTeX editor."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from editor.editor_widget import EditorWidget


class EditorLatexDropTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_document_root_inserts_include_with_relative_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "chapters").mkdir()
            editor = EditorWidget()
            editor.setText(
                "\\documentclass{article}\n\\begin{document}\n\n\\end{document}"
            )
            editor.file_path = root / "main.tex"
            editor.setCursorPosition(2, 0)

            editor._insert_latex_include(root / "chapters" / "ch1.tex")

            text = editor.text()
            self.assertIn("\\include{chapters/ch1}", text)
            self.assertNotIn(".tex}", text)

    def test_subfile_uses_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            editor = EditorWidget()
            editor.setText("Some text")
            editor.file_path = root / "ch1.tex"
            editor.setCursorPosition(0, 0)

            editor._insert_latex_include(root / "ch2.tex")

            self.assertIn("\\input{ch2}", editor.text())


if __name__ == "__main__":
    unittest.main()

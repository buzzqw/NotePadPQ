import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QApplication

from editor.editor_widget import EditorWidget
from ui.latex_insert_image_dialog import LatexInsertImageDialog


class LatexImageDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dropped_absolute_image_path_becomes_project_relative(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            image = base / "figures" / "plot.png"
            image.parent.mkdir()
            dialog = LatexInsertImageDialog(base_dir=base)
            dialog.set_image_file(str(image))

            self.assertIn(r"{figures/plot.png}", dialog.get_latex_code())

    def test_latex_image_drop_emits_image_signal_instead_of_opening_tab(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tex = root / "main.tex"
            image = root / "plot.png"
            tex.write_text(r"\documentclass{article}")
            image.write_bytes(b"not a real image")

            editor = EditorWidget()
            editor.file_path = tex
            editor._current_language = "LaTeX"
            received = []
            editor.latex_image_drop_requested.connect(received.append)

            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(image))])
            event = QDropEvent(
                QPointF(0, 0),
                Qt.DropAction.CopyAction,
                mime,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            editor.dropEvent(event)

            self.assertEqual(received, [image])
            editor.deleteLater()


if __name__ == "__main__":
    unittest.main()

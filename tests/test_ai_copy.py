import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from plugins.ai_plugin import _AIPanel


class AICopyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_copy_uses_original_markdown_from_history(self):
        markdown = (
            "# Titolo\n\n"
            "```python\n"
            "    valore = r\"$α\"\n"
            "```\n\n"
            "Formula: $\\LaTeX$\n"
        )
        panel = mock.Mock()
        panel._history = [
            {"role": "assistant", "content": "risposta precedente"},
            {"role": "assistant", "content": markdown},
        ]
        panel._worker = None
        panel._status = mock.Mock()
        panel._last_assistant_response = lambda: _AIPanel._last_assistant_response(panel)

        QApplication.clipboard().setText("testo precedente")
        _AIPanel._copy_last_response(panel)

        self.assertEqual(QApplication.clipboard().text(), markdown)
        panel._status.setText.assert_called_once_with("✓ Risposta copiata negli appunti")

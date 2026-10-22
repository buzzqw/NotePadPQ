"""Tests for Pygments language completion in minted/listings commands."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from editor.autocomplete import AutoCompleteManager, _code_language_terms
from editor.editor_widget import EditorWidget


class CodeLanguageCompletionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _manager(self):
        editor = EditorWidget()
        manager = AutoCompleteManager(editor)
        shown = []
        editor.showUserList = lambda list_id, labels: shown.append((list_id, labels))
        manager.set_language("latex")
        return editor, manager, shown

    def test_pygments_aliases_are_available_and_short_first(self):
        terms = _code_language_terms()
        self.assertIn("py  [Python]", terms)
        self.assertIn("python  [Python]", terms)
        self.assertLess(terms.index("py  [Python]"), terms.index("python  [Python]"))

    def test_minted_environment_offers_languages_and_inserts_alias(self):
        editor, manager, shown = self._manager()
        editor.setText(r"\begin{minted}{py")
        editor.setCursorPosition(0, len(editor.text(0)))
        try:
            self.assertTrue(manager.handle_latex_special("{"))
            self.assertEqual(shown[-1][0], 13)
            self.assertEqual(shown[-1][1][0], "py  [Python]")

            editor._on_user_list_selection(13, "py  [Python]")
            self.assertEqual(editor.text(), r"\begin{minted}{py}")
        finally:
            manager.shutdown()
            editor.deleteLater()
            self.app.processEvents()

    def test_lstset_brace_language_replaces_only_the_value(self):
        editor, manager, shown = self._manager()
        editor.setText(r"\lstset{language=py")
        editor.setCursorPosition(0, len(editor.text(0)))
        try:
            self.assertTrue(manager.handle_latex_special("{"))
            self.assertEqual(shown[-1][0], 15)
            self.assertTrue(shown[-1][1][0].startswith("py  ["))

            editor._on_user_list_selection(15, "py  [Python]")
            self.assertEqual(editor.text(), r"\lstset{language=py}")
        finally:
            manager.shutdown()
            editor.deleteLater()
            self.app.processEvents()

    def test_lstset_option_language_offers_values(self):
        editor, manager, shown = self._manager()
        editor.setText(r"\lstset[language=py")
        editor.setCursorPosition(0, len(editor.text(0)))
        try:
            self.assertTrue(manager.handle_latex_option("["))
            self.assertEqual(shown[-1][0], 14)
            self.assertEqual(shown[-1][1][0], "py")
        finally:
            manager.shutdown()
            editor.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()

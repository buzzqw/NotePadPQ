"""Tests for Pygments language completion in minted/listings commands."""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from editor import autocomplete as autocomplete_module
from editor.autocomplete import (
    AutoCompleteLevel,
    AutoCompleteManager,
    _ApiRebuildWorker,
    _code_language_terms,
    _DocumentWordsWorker,
)
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


class DocumentWordCompletionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_worker_emits_document_words_for_non_latex_languages(self):
        worker = _ApiRebuildWorker(
            "python", AutoCompleteLevel.DOCUMENT,
            "alfa beta gamma alfa", None, [], 7,
        )
        captured = []
        worker.document_words.connect(
            lambda words, gen: captured.append((words, gen))
        )

        worker.run()

        self.assertEqual(len(captured), 1)
        words, generation = captured[0]
        self.assertEqual(generation, 7)
        self.assertEqual(words, ["alfa", "beta", "gamma"])

    def test_document_terms_use_cached_words_without_rescanning(self):
        editor = EditorWidget()
        manager = AutoCompleteManager(editor)
        manager._document_words_cache = ["alfa", "beta"]
        try:
            with mock.patch.object(
                autocomplete_module.re, "findall",
                side_effect=AssertionError("full document scan"),
            ):
                self.assertEqual(
                    manager._document_completion_terms(), ["alfa", "beta"]
                )
        finally:
            manager.shutdown()
            editor.deleteLater()
            self.app.processEvents()

    def test_light_worker_emits_unique_document_words(self):
        worker = _DocumentWordsWorker("alfa beta gamma alfa", 3)
        captured = []
        worker.done.connect(lambda words, gen: captured.append((words, gen)))

        worker.run()

        self.assertEqual(captured, [(["alfa", "beta", "gamma"], 3)])

    def test_non_latex_edits_schedule_light_document_word_refresh(self):
        editor = EditorWidget()
        manager = AutoCompleteManager(editor)
        manager.set_language("python")
        try:
            manager.on_document_changed()
            self.assertTrue(manager._doc_words_timer.isActive())
            self.assertFalse(manager._doc_change_timer.isActive())
        finally:
            manager.shutdown()
            editor.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()

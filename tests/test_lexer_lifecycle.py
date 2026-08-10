import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core.lazy_loader import LazyLoader
from editor.editor_widget import EditorWidget
from editor.latex_support import LaTeXSupport
from editor.lexers import set_lexer_by_extension, set_lexer_by_name
from editor.markdown_support import MarkdownSupport


class LexerLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = EditorWidget()

    def tearDown(self):
        ac = getattr(self.editor, "_autocomplete", None)
        if ac is not None:
            ac.shutdown()
        checker = getattr(self.editor, "_latex_checker", None)
        if checker is not None:
            checker.stop()
        self.editor.deleteLater()
        self.app.processEvents()

    def test_support_activation_replaces_signal_slots(self):
        with mock.patch.object(LaTeXSupport, "_on_char_added") as latex_slot:
            LaTeXSupport.activate(self.editor)
            LaTeXSupport.activate(self.editor)
            self.editor.SCN_CHARADDED.emit(ord("a"))
            self.assertEqual(latex_slot.call_count, 1)

            LaTeXSupport.deactivate(self.editor)
            self.editor.SCN_CHARADDED.emit(ord("a"))
            self.assertEqual(latex_slot.call_count, 1)

        with mock.patch.object(MarkdownSupport, "_apply_yaml_fm") as yaml_slot:
            MarkdownSupport.activate(self.editor)
            yaml_slot.reset_mock()
            MarkdownSupport.activate(self.editor)
            yaml_slot.reset_mock()
            self.editor.textChanged.emit()
            self.assertEqual(yaml_slot.call_count, 1)

            MarkdownSupport.deactivate(self.editor)
            self.editor.textChanged.emit()
            self.assertEqual(yaml_slot.call_count, 1)

    def test_manager_created_after_latex_lexer_gets_support_and_checker(self):
        set_lexer_by_extension(self.editor, ".tex")

        from editor.autocomplete import AutoCompleteManager
        manager = AutoCompleteManager(self.editor)

        self.assertEqual(manager._language, "latex")
        self.assertTrue(self.editor._latex_support_active)
        self.assertTrue(self.editor._latex_checker._started)
        manager.shutdown()

    def test_language_transition_clears_stale_support_and_emits_once(self):
        changed = []
        self.editor.language_changed.connect(changed.append)

        set_lexer_by_extension(self.editor, ".tex")
        set_lexer_by_extension(self.editor, ".md")
        set_lexer_by_name(self.editor, "testo normale")

        self.assertIsNone(getattr(self.editor, "_latex_checker", None))
        self.assertFalse(getattr(self.editor, "_latex_support_active", False))
        self.assertFalse(getattr(self.editor, "_markdown_support_active", False))
        self.assertEqual(changed, ["LaTeX", "Markdown", "Text"])

        from editor.autocomplete import AutoCompleteManager
        manager = AutoCompleteManager(self.editor)
        set_lexer_by_extension(self.editor, ".tex")
        set_lexer_by_name(self.editor, "testo normale")
        self.assertEqual(manager._language, "text")
        manager.shutdown()

    def test_pygments_transition_also_clears_latex_state(self):
        changed = []
        self.editor.language_changed.connect(changed.append)

        set_lexer_by_extension(self.editor, ".tex")
        self.assertTrue(set_lexer_by_extension(self.editor, ".go"))

        self.assertIsNone(getattr(self.editor, "_latex_checker", None))
        self.assertFalse(getattr(self.editor, "_latex_support_active", False))
        self.assertEqual(changed, ["LaTeX", "Go"])

    def test_language_aliases_use_the_expected_support(self):
        for ext in (".latex", ".ltx"):
            self.assertTrue(set_lexer_by_extension(self.editor, ext))
            self.assertEqual(self.editor._current_language, "LaTeX")
        for ext in (".mdown", ".mkdn", ".mdwn", ".rmd"):
            self.assertTrue(set_lexer_by_extension(self.editor, ext))
            self.assertEqual(self.editor._current_language, "Markdown")
        self.assertTrue(set_lexer_by_extension(self.editor, ".rest"))
        self.assertEqual(self.editor._current_language, "reStructuredText")

    def test_load_content_recolors_latex_and_forces_checker(self):
        set_lexer_by_extension(self.editor, ".tex")
        lexer = self.editor.lexer()
        lexer._bytes_cache = b"stale"
        checker = self.editor._latex_checker

        with mock.patch.object(lexer, "recolor", wraps=lexer.recolor) as recolor, \
                mock.patch.object(checker, "force_check") as force_check:
            self.editor.load_content(r"\section{Loaded}")

        self.assertEqual(self.editor.text(), r"\section{Loaded}")
        recolor.assert_called_once()
        force_check.assert_called_once()
        lexer.invalidate_cache()
        self.assertIsNone(lexer._bytes_cache)

    def test_lazy_finalization_refreshes_language_support(self):
        set_lexer_by_extension(self.editor, ".tex")
        loader = LazyLoader(None, self.editor)
        loader._close_progress = mock.Mock()

        with mock.patch.object(self.editor, "refresh_language_support") as refresh:
            loader._on_lazy_finished("UTF-8", "LF")

        refresh.assert_called_once_with(force_check=True)


if __name__ == "__main__":
    unittest.main()

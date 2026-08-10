import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from editor.latex_checker import _CheckWorker
from editor.latex_support import LaTeXSupport, strip_latex_comments
from editor.lexer_latex_custom import S_MATH, LaTeXLexer


class _DollarEditor:
    def __init__(self, text, col):
        self._text = text
        self._col = col

    def getCursorPosition(self):
        return 0, self._col

    def text(self, line):
        return self._text

    def beginUndoAction(self):
        pass

    def endUndoAction(self):
        pass

    def insert(self, value):
        self._text = self._text[:self._col] + value + self._text[self._col:]

    def setCursorPosition(self, line, col):
        self._col = col


class LatexSupportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_comment_escaping_uses_backslash_parity(self):
        text = "one \\% two\ntwo \\\\% three\n"
        self.assertEqual(strip_latex_comments(text), "one \\% two\n" + "two " + "\\\\" + "\n")

    def test_dollar_handler_ignores_escaped_and_existing_closer(self):
        escaped = _DollarEditor(r"\$", 2)
        LaTeXSupport._handle_dollar(escaped)
        self.assertEqual(escaped._text, r"\$")

        existing = _DollarEditor("$|$".replace("|", ""), 1)
        LaTeXSupport._handle_dollar(existing)
        self.assertEqual(existing._text, "$$")

        opening = _DollarEditor("$", 1)
        LaTeXSupport._handle_dollar(opening)
        self.assertEqual(opening._text, "$$")

    def test_environment_balance_is_source_ordered_without_pop_cascade(self):
        errors = LaTeXSupport.check_environment_balance(
            r"\begin{a} \begin{b} \end{a} \end{b}"
        )
        self.assertEqual(len(errors), 2)
        self.assertIn("closes 'b'", errors[0]["msg"])
        self.assertIn("a} not closed", errors[1]["msg"])

    def test_math_mode_handles_delimiters_and_math_environments(self):
        text = "text \\(a $ b\n c\\) text \\[d\\] \\begin{align}x\n y\\end{align}"
        self.assertTrue(LaTeXSupport.is_in_math_mode(text, text.index("c")))
        self.assertTrue(LaTeXSupport.is_in_math_mode(text, text.index("y")))
        self.assertFalse(LaTeXSupport.is_in_math_mode(text, len(text)))

    def test_table_count_ignores_escaped_and_nested_separators(self):
        self.assertEqual(_CheckWorker._count_row_cols(r"a \& b & c"), 2)
        self.assertEqual(
            _CheckWorker._count_row_cols(r"a & \multicolumn{2}{c}{x & y} & z"),
            4,
        )
        self.assertEqual(_CheckWorker._count_tabular_cols(r"*{2}{c}"), 2)
        self.assertEqual(
            _CheckWorker._count_tabular_cols(r">{\raggedright}p{2cm}X"), 2
        )

    def test_collect_project_files_supports_two_argument_imports_and_cycles(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "chapters" / "nested").mkdir(parents=True)
            main = root / "main.tex"
            one = root / "chapters" / "one.tex"
            two = root / "chapters" / "two.tex"
            three = root / "chapters" / "nested" / "three.tex"
            main.write_text(r"\import{chapters}{one}\subimport{chapters}{two}")
            one.write_text(r"\includefrom{../}{main}\subinputfrom{nested}{three}")
            two.write_text("two")
            three.write_text("three")

            files = LaTeXSupport.collect_project_files(main)
            self.assertEqual(files, [main.resolve(), one.resolve(),
                                     three.resolve(), two.resolve()])

    def test_bibtex_keys_include_current_bib_text_and_referenced_files(self):
        current = "@article{current, title={Now}}\n% @book{ignored, title={No}}"
        self.assertEqual(LaTeXSupport.extract_bibtex_keys(current), ["current"])

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tex = root / "main.tex"
            bib = root / "refs.bib"
            tex.write_text(r"\addbibresource{refs}")
            bib.write_text("@book{saved, title={Saved}}")
            self.assertEqual(
                LaTeXSupport.extract_bibtex_keys(
                    r"\addbibresource{refs}", tex
                ),
                ["saved"],
            )

    def test_dynamic_api_and_environment_list_include_included_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main = root / "main.tex"
            child = root / "child.tex"
            main.write_text(r"\input{child}")
            child.write_text(
                r"\usepackage{listings}\newenvironment{customenv}{}{}"
            )

            api = LaTeXSupport.build_dynamic_api("", main)
            self.assertIn(r"\begin{customenv}", api)
            self.assertIn(r"\lstinline{}", api)
            self.assertIn("lstlisting", LaTeXSupport.get_all_environments("", main))

    def test_lexer_preserves_math_state_between_style_chunks(self):
        lexer = LaTeXLexer()
        lexer.startStyling = mock.Mock()
        lexer.setStyling = mock.Mock()
        text = b"$$a\nb$$\n"
        lexer._style_with_state(0, 4, text)
        lexer.setStyling.reset_mock()
        lexer._style_with_state(4, len(text), text)
        styles = [call.args[1] for call in lexer.setStyling.call_args_list]
        self.assertIn(S_MATH, styles)
        self.assertEqual(lexer._state_at(text, len(text))[0], "default")

    def test_lexer_recognizes_all_multiline_math_delimiters(self):
        lexer = LaTeXLexer()
        for text in (b"\\(x\ny\\)", b"\\[x\ny\\]",
                     b"\\begin{gather}x\ny\\end{gather}"):
            lexer._state_cache = {0: ("default", ())}
            self.assertEqual(lexer._state_at(text, len(text))[0], "default")


if __name__ == "__main__":
    unittest.main()

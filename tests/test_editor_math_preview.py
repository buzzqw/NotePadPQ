"""Tests for math formula extraction used by the editor hover preview."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from editor.editor_widget import _extract_math_formula


class MathHoverExtractionTest(unittest.TestCase):
    def test_inline_and_display_delimiters(self):
        cases = [
            (r"text $x^2$ end", 7, "x^2"),
            (r"\[ a+b \]", 3, "a+b"),
            (r"\(a+b\)", 2, "a+b"),
            (r"$$E=mc^2$$", 5, "E=mc^2"),
        ]
        for text, position, expected in cases:
            self.assertEqual(_extract_math_formula(text, position), expected)

    def test_equation_environment_and_alignment_rows(self):
        self.assertEqual(
            _extract_math_formula(
                r"\begin{equation*} E=mc^2 \end{equation*}", 20
            ),
            "E=mc^2",
        )
        self.assertEqual(
            _extract_math_formula(
                r"\begin{align} a &= b \\ c &= d \end{align}", 22
            ),
            "a = b",
        )

    def test_escaped_dollar_is_not_a_formula_delimiter(self):
        self.assertEqual(
            _extract_math_formula(r"price \$5 and $x$", 16), "x"
        )

    def test_position_outside_formula_returns_none(self):
        self.assertIsNone(_extract_math_formula(r"text $x$ end", 0))


if __name__ == "__main__":
    unittest.main()

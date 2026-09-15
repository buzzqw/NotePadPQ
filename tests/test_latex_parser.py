import unittest

from core.latex_citations import extract_latex_citation_occurrences
from core.latex_parser import (
    extract_label_reference_occurrences,
    extract_sections,
    mask_latex_comments,
    read_latex_group,
    strip_latex_comments,
)


class LatexParserTests(unittest.TestCase):
    def test_comment_scanning_preserves_offsets_and_backslash_parity(self):
        text = "escaped \\% kept\ncomment % ignored \\label{fake}\n"

        masked = mask_latex_comments(text)

        self.assertEqual(len(masked), len(text))
        comment_line = masked.splitlines()[1]
        self.assertTrue(comment_line.startswith("comment "))
        self.assertEqual(len(comment_line), len("comment % ignored \\label{fake}"))
        self.assertNotIn("label", comment_line)
        self.assertEqual(
            strip_latex_comments(text),
            "escaped \\% kept\ncomment \n",
        )

    def test_balanced_groups_skip_escaped_delimiters_and_comments(self):
        text = r"{one {two} \} three} trailing"

        self.assertEqual(read_latex_group(text, 0), (1, text.index("} trailing")))
        self.assertIsNone(read_latex_group(text, 1))
        commented = "{one % ignored }\ntwo}"
        self.assertEqual(read_latex_group(commented, 0), (1, commented.rindex("}")))
        bracketed = "[one [two]]"
        self.assertEqual(read_latex_group(bracketed, 0, "["), (1, len(bracketed) - 1))

    def test_reference_scanner_skips_opaque_content_and_keeps_locations(self):
        text = (
            r"\label{sec:intro} \ref{sec:intro, sec:other}" "\n"
            r"\begin{verbatim}\label{fake}\end{verbatim}" "\n"
            r"\url{\ref{opaque}} % \label{comment}" "\n"
            r"\hyperref[target]{visible}"
        )

        occurrences = extract_label_reference_occurrences(text)

        self.assertEqual(
            [(item["kind"], item["key"]) for item in occurrences],
            [
                ("label", "sec:intro"),
                ("reference", "sec:intro"),
                ("reference", "sec:other"),
                ("reference", "target"),
            ],
        )
        for occurrence in occurrences:
            self.assertEqual(
                text[occurrence["start"]:occurrence["end"]], occurrence["key"]
            )

    def test_sections_ignore_comments_and_support_short_titles(self):
        text = r"\section[Short]{Long}" "\n" r"% \section{Ignored}" "\n"

        self.assertEqual(extract_sections(text), [("section", "Short", 0)])

    def test_citation_scanner_handles_optional_notes_and_reports_locations(self):
        text = r"\citep[see][p. 2]{first, second}" "\n" r"\texttt{\cite{opaque}}"

        occurrences = extract_latex_citation_occurrences(text)

        self.assertEqual([item["key"] for item in occurrences], ["first", "second"])
        self.assertEqual(occurrences[1]["line"], 0)
        self.assertEqual(occurrences[1]["column"], text.index("second"))


if __name__ == "__main__":
    unittest.main()

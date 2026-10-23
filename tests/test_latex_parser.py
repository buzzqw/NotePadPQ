import time
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

    def test_citation_locations_use_zero_based_lines_after_first(self):
        text = (
            "prima riga\n"
            "seconda riga con \\cite{alpha}\n"
            "terza riga con \\citep[p. 1]{beta}\n"
        )

        occurrences = extract_latex_citation_occurrences(text)

        self.assertEqual(
            [(item["key"], item["line"], item["column"]) for item in occurrences],
            [
                ("alpha", 1, text.splitlines()[1].index("alpha")),
                ("beta", 2, text.splitlines()[2].index("beta")),
            ],
        )

    def test_many_citations_are_scanned_in_linear_time(self):
        text = ("testo con \\cite{key}\n" * 50_000)
        started = time.perf_counter()
        occurrences = extract_latex_citation_occurrences(text)

        self.assertEqual(len(occurrences), 50_000)
        # La versione precedente ricalcolava riga/colonna dall'inizio per ogni
        # citazione e impiegava diversi secondi su questo input.
        self.assertLess(time.perf_counter() - started, 2.0)

    def test_many_sections_report_lines_in_linear_time(self):
        text = ("\\section{Sezione}\n" + "testo " * 15 + "\n") * 20_000
        started = time.perf_counter()
        sections = extract_sections(text)

        self.assertEqual(len(sections), 20_000)
        self.assertEqual(sections[10_000][2], 20_000)
        # La versione precedente contava i newline dall'inizio per ogni
        # sezione, con costo quadratico.
        self.assertLess(time.perf_counter() - started, 2.0)


if __name__ == "__main__":
    unittest.main()

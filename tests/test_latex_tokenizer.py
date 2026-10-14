"""Tests for the group-aware LaTeX tokenizer (core.latex_tokenizer)."""

import unittest

from core.latex_parser import extract_sections, mask_latex_comments
from core.latex_tokenizer import (
    scan_bibliography_references,
    scan_custom_command_definitions,
    scan_custom_environments,
    scan_document,
    scan_hypertargets,
    scan_packages,
    scan_sections,
)


class SectionScanTest(unittest.TestCase):
    def test_short_title_wins_and_offsets_are_kept(self):
        code = mask_latex_comments(r"\section[Short]{Long}" + "\n")
        sections = scan_sections(code)
        self.assertEqual([(s.kind, s.name) for s in sections], [("section", "Short")])
        self.assertEqual(code[sections[0].offset:sections[0].offset + 8], r"\section")

    def test_nested_braces_in_title_are_kept_whole(self):
        # The old per-line regex stopped at the first closing brace.
        code = r"\section{A \textbf{bold} title}"
        self.assertEqual(
            [(s.kind, s.name) for s in scan_sections(code)],
            [("section", r"A \textbf{bold} title")],
        )

    def test_multi_line_title_is_supported(self):
        code = "\\section{A title\nover two lines}"
        self.assertEqual(
            [s.name for s in scan_sections(code)],
            ["A title\nover two lines"],
        )

    def test_extract_sections_ignores_comments(self):
        text = "\\section{Real}\n% \\section{Comment}\n"
        self.assertEqual(extract_sections(text), [("section", "Real", 0)])


class PackageScanTest(unittest.TestCase):
    def test_packages_and_class_are_collected(self):
        code = (
            "\\documentclass[a4paper]{book}\n"
            "\\usepackage[utf8]{inputenc}\n"
            "\\usepackage{graphicx,amsmath}\n"
        )
        self.assertEqual(
            scan_packages(code),
            {"book", "inputenc", "graphicx", "amsmath"},
        )


class DefinitionScanTest(unittest.TestCase):
    def test_command_arguments_and_default(self):
        code = (
            "\\newcommand{\\foo}[2][x]{body}\n"
            "\\newcommand\\bar{y}\n"
            "\\DeclareMathOperator{\\op}{op}\n"
            "\\def\\baz#1{#1}\n"
        )
        defs = {d.name: d for d in scan_custom_command_definitions(code)}
        self.assertEqual(defs["\\foo"].arguments, 2)
        self.assertTrue(defs["\\foo"].has_default)
        self.assertIsNone(defs["\\bar"].arguments)
        self.assertEqual(set(defs), {"\\foo", "\\bar", "\\op", "\\baz"})

    def test_custom_environments(self):
        code = "\\newenvironment{myenv}[1][x]{begin}{end}\n"
        self.assertEqual(scan_custom_environments(code), {"myenv"})


class MiscScanTest(unittest.TestCase):
    def test_hypertargets(self):
        code = "\\hypertarget{Licenza}{}\n\\hypertarget{Parte 1}{x}\n"
        self.assertEqual(scan_hypertargets(code), {"Licenza", "Parte 1"})

    def test_bibliography_references_split_on_commas(self):
        code = "\\bibliography{refs,other}\n\\addbibresource{more.bib}\n"
        self.assertEqual(
            scan_bibliography_references(code),
            ["refs", "other", "more.bib"],
        )


class SinglePassTest(unittest.TestCase):
    def test_individual_views_match_the_single_pass(self):
        code = (
            "\\documentclass{book}\n"
            "\\section{One}\n"
            "\\newcommand{\\c}{x}\n"
            "\\newenvironment{env}{}{}\n"
            "\\hypertarget{t}{}\n"
            "\\bibliography{refs}\n"
        )
        spans = scan_document(code)
        self.assertEqual(spans.sections, tuple(scan_sections(code)))
        self.assertEqual(spans.packages, frozenset(scan_packages(code)))
        self.assertEqual(
            spans.custom_commands, tuple(scan_custom_command_definitions(code)))
        self.assertEqual(
            {e.name for e in spans.custom_environments}, scan_custom_environments(code))
        self.assertEqual(spans.hypertargets, frozenset(scan_hypertargets(code)))
        self.assertEqual(
            spans.bibliography_references,
            tuple(scan_bibliography_references(code)),
        )


if __name__ == "__main__":
    unittest.main()

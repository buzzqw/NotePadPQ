"""Regressioni per i blocchi dell'anteprima quando si incolla testo.

Python-Markdown ha pattern quadratici su parentesi non chiuse, '<' senza
tag chiuso e marcatori di enfasi/backtick molto densi. Il rendering avviene
in un QThread, ma le regex in C non rilasciano il GIL: senza una
preparazione del sorgente un incollaggio di poche decine di KB può portare
una CPU al 100% e congelare la GUI.
"""

import time

import pytest

from ui.preview_panel import (
    _latex_section_on_line,
    _markdown_heading_count,
    _sanitize_markdown_source,
)


def test_unmatched_bracket_is_escaped_before_rendering():
    text = "testo [ senza chiusura\n" * 50
    safe, too_complex = _sanitize_markdown_source(text)

    assert too_complex is False
    assert "\\[" in safe
    assert "[" not in safe.replace("\\[", "")


def test_balanced_brackets_are_left_untouched():
    text = "Vedi [la nota](https://example.test) e [riferimento].\n"
    safe, too_complex = _sanitize_markdown_source(text)

    assert too_complex is False
    assert safe == text


def test_code_blocks_are_not_rewritten():
    text = "```\narr[0\n```\n\n`a < b`\n"
    safe, too_complex = _sanitize_markdown_source(text)

    assert too_complex is False
    assert safe == text


def test_unclosed_angle_bracket_is_escaped():
    text = "confronto < senza chiusura\n" * 50
    safe, too_complex = _sanitize_markdown_source(text)

    assert too_complex is False
    assert "&lt;" in safe
    assert "<" not in safe


def test_normal_markdown_formatting_is_not_downgraded():
    text = ("# Titolo\n\nTesto [ok](https://example.test) e **grassetto**.\n\n" * 500)
    _, too_complex = _sanitize_markdown_source(text)

    assert too_complex is False


def test_dense_markers_fall_back_to_plain_text():
    _, too_complex = _sanitize_markdown_source("_a _b " * 20000)
    assert too_complex is True

    _, too_complex = _sanitize_markdown_source("`a " * 20000)
    assert too_complex is True


def test_deeply_nested_brackets_fall_back_to_plain_text():
    _, too_complex = _sanitize_markdown_source("[" * 5000 + "x" + "]" * 5000)
    assert too_complex is True


def test_pathological_markdown_renders_quickly():
    markdown = pytest.importorskip("markdown")
    text = "testo [ senza chiusura\n" * 2000
    safe, too_complex = _sanitize_markdown_source(text)

    assert too_complex is False
    started = time.perf_counter()
    markdown.markdown(
        safe, extensions=["tables", "fenced_code", "md_in_html"]
    )
    # Senza la sanificazione questo caso impiega >10 secondi.
    assert time.perf_counter() - started < 5.0


def test_latex_section_scan_is_linear_on_malformed_input():
    text = "\\section{" * 20000
    started = time.perf_counter()
    for line in text.split("\n"):
        _latex_section_on_line(line)

    assert time.perf_counter() - started < 1.0


def test_latex_section_scan_handles_valid_and_commented_commands():
    assert _latex_section_on_line(r"\section{Introduzione}") == (
        "section", "Introduzione"
    )
    assert _latex_section_on_line(r"testo \subsection*{Dettagli}") == (
        "subsection", "Dettagli"
    )
    assert _latex_section_on_line(r"\\section{non è un comando}") is None
    assert _latex_section_on_line(r"% \section{commentato}") is None
    assert _latex_section_on_line(r"\section{senza chiusura") is None
    assert _latex_section_on_line(r"\section{Il 50\% di prova}") == (
        "section", r"Il 50\% di prova"
    )


def test_heading_count_matches_atx_headings():
    text = "# Uno\n\n## Due\n\n```\n# codice\n```\n\n### Tre\n"
    assert _markdown_heading_count(text) == 3

"""Equivalence tests for the optional native LaTeX scanner."""

from __future__ import annotations

from unittest import mock

import pytest

from editor.lexer_latex_custom import LaTeXLexer


try:
    from core import _latex_native
except ImportError:  # pragma: no cover - source-only installs
    _latex_native = None


def _python_styles(text: bytes) -> bytes:
    lexer = LaTeXLexer()
    lexer._native_enabled = False
    lexer.startStyling = mock.Mock()
    lexer.setStyling = mock.Mock()
    lexer._style_with_state(0, len(text), text)
    styles = bytearray()
    for call in lexer.setStyling.call_args_list:
        length, style = call.args
        styles.extend([style] * length)
    return bytes(styles)


@pytest.mark.skipif(_latex_native is None, reason="native accelerator not compiled")
def test_native_scanner_matches_python_reference():
    text = (
        "\\documentclass[12pt]{article}\n"
        "\\usepackage{amsmath}\n"
        "% a comment with $math$\n"
        "\\begin{document}\n"
        "\\section{Title} \\label{sec:title}\n"
        "Text $x^2$ and $$y + 1$$ and \\[z\\].\n"
        "\\begin{equation}\n"
        "x = 1\n"
        "\\end{equation}\n"
        "\\begin{verbatim}\n"
        "$x % \\section{raw}\n"
        "\\end{verbatim}\n"
        "\\end{document}\n"
    ).encode()

    safe, styles, _checkpoints = _latex_native.style(
        text, 0, len(text), "default", ()
    )
    assert safe == 0
    assert styles == _python_styles(text)


@pytest.mark.skipif(_latex_native is None, reason="native accelerator not compiled")
def test_native_state_handles_long_random_access_prefix():
    text = (
        "\\begin{equation}\n"
        + "".join(f"line {i} $x_{i}$\n" for i in range(50_000))
        + "\\end{equation}\n"
    ).encode()
    offset = text.index(b"line 40000")
    mode, envs = _latex_native.state(text, 0, offset, "default", ())
    assert mode == "environment"
    assert envs == ("equation",)

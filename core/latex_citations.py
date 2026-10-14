"""LaTeX citation occurrences, shared with the label/reference scanner.

Citations and labels are produced together by the single pass in
:func:`core.latex_parser.scan_annotations`; this module keeps the historical
entry point for callers and tests.

Sharing the pass also fixed two long-standing edge cases: a ``%`` inside
``\\verb|...|`` no longer masks the rest of the line, and a ``\\cite`` inside a
``verbatim`` environment is no longer reported.
"""

from __future__ import annotations

from core.latex_parser import LatexOccurrence, scan_annotations


def extract_latex_citation_occurrences(text: str) -> list[LatexOccurrence]:
    """Return citation key spans while preserving original source offsets."""
    return list(scan_annotations(text, tokens=False).citations)


__all__ = ["extract_latex_citation_occurrences"]

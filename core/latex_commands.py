"""Single source of truth for LaTeX command/environment classification.

The custom lexer (both the Python reference and the optional C++ accelerator)
classifies a command into *structure*, *reference* or plain *command*, and
treats verbatim/math environments specially.  Those tables used to be written
out three times — in the lexer, in the parser and in the C++ scanner.  They
live here now so the Python consumers share one definition; a regression test
parses ``native/latex_native.cpp`` and fails if the accelerator drifts.

This module has no dependencies and no side effects.
"""

from __future__ import annotations

# Commands that carry document structure and are highlighted as such.
STRUCTURE_COMMANDS: frozenset[str] = frozenset({
    "begin", "end", "chapter", "section", "subsection", "subsubsection",
    "paragraph", "subparagraph", "part", "documentclass", "usepackage",
    "RequirePackage", "input", "include", "subfile", "import", "newcommand",
    "renewcommand", "providecommand", "newenvironment", "renewenvironment",
    "title", "author", "date", "maketitle", "appendix", "frontmatter",
    "mainmatter", "backmatter",
})

# Commands whose braced argument is a cross-reference / citation key.
REFERENCE_COMMANDS: frozenset[str] = frozenset({
    "label", "ref", "eqref", "pageref", "nameref", "autoref", "cref", "Cref",
    "vref", "fullref", "hyperref", "cite", "citep", "citet", "citealt", "citealp",
    "citenum", "nocite", "footcite", "parencite", "textcite", "index", "glossary",
    "nomenclature", "href", "url", "nolinkurl", "footnote", "footnotemark",
    "footnotetext",
})

# Environments typeset in math mode.
MATH_ENVIRONMENTS: frozenset[str] = frozenset({
    "equation", "align", "gather", "multline", "math", "displaymath", "split",
    "cases", "alignat", "flalign", "subequations",
})

# Environments whose body is literal text LaTeX does not interpret.
VERBATIM_ENVIRONMENTS: frozenset[str] = frozenset({
    "verbatim", "verbatim*", "lstlisting", "Verbatim", "BVerbatim", "minted",
})

__all__ = [
    "MATH_ENVIRONMENTS",
    "REFERENCE_COMMANDS",
    "STRUCTURE_COMMANDS",
    "VERBATIM_ENVIRONMENTS",
]

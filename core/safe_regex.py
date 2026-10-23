"""Lightweight guard against obviously catastrophic user-supplied regexes.

Python's ``re`` module has no timeout. We cannot interrupt a backtracking
catastrophe safely inside the process, so the editor rejects the most common
quadratic/exponential shapes before compiling them (nested quantified groups,
e.g. ``(a+)+``, ``(.*)*``, ``(\\d+){2,}``). It is a heuristic, not a full
sandbox: callers still need worker isolation for hostile input.
"""

from __future__ import annotations

import re

_QUANTIFIER = r"(?:[*+]|\{\s*\d+\s*,\s*\})"
_NESTED_QUANTIFIER = re.compile(
    r"(?<!\\)\((?:[^()\\]|\\.)*" + _QUANTIFIER
    + r"(?:[^()\\]|\\.)*\)\s*" + _QUANTIFIER
)


def has_catastrophic_backtracking(pattern: str) -> bool:
    """True for common nested-quantifier regex patterns."""
    return bool(_NESTED_QUANTIFIER.search(pattern or ""))


def pattern_error(pattern: str) -> str | None:
    """Return a user-facing error when a pattern is clearly unsafe."""
    if has_catastrophic_backtracking(pattern):
        return (
            "Pattern regex potenzialmente catastrofico: evita quantificatori "
            "annidati come (a+)+ o (.*)*."
        )
    return None


__all__ = ["has_catastrophic_backtracking", "pattern_error"]

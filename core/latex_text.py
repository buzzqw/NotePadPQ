"""Qt-free LaTeX text utilities extracted from the editor adapter.

``find_open_environments``, ``count_words`` and ``is_in_math_mode`` are pure
functions over text, yet they used to live in ``editor.latex_support`` (a Qt
module).  They live here so they can be reused and tested without an editor and
without a QApplication, completing the migration of the pure logic out of the
support adapter.
"""

from __future__ import annotations

import re

from core.latex_commands import MATH_ENVIRONMENTS
from core.latex_parser import (
    BEGIN_END_RE as _RE_BEGIN_END,
    is_latex_escaped as _is_escaped,
    strip_latex_comments,
)

_MATH_ENV_NAMES = MATH_ENVIRONMENTS


def find_open_environments(text: str, line: int, col: int) -> list[str]:
    """Environments still open just before ``(line, col)``, innermost first.

    Ignores comments; used to suggest the right environment after ``\\end{``.
    """
    all_lines = text.split("\n")
    lines = all_lines[:line]
    if line < len(all_lines):
        last = all_lines[line][:col] if col <= len(all_lines[line]) else all_lines[line]
    else:
        last = ""
    lines.append(last)

    stack: list[str] = []
    for raw_line in lines:
        code = strip_latex_comments(raw_line)
        for m in _RE_BEGIN_END.finditer(code):
            kind, env = m.group(1), m.group(2)
            if kind == "begin":
                stack.append(env)
            else:
                for i in range(len(stack) - 1, -1, -1):
                    if stack[i] == env:
                        del stack[i]
                        break
    return list(reversed(stack))


def count_words(text: str) -> dict:
    """Count words/characters/lines/paragraphs of a document body.

    Excludes the preamble and LaTeX commands.  Returns
    ``{words, chars, chars_nospace, lines, paragraphs}``.
    """
    text_nc = strip_latex_comments(text)
    m = re.search(r'\\begin\{document\}', text_nc)
    body = text_nc[m.end():] if m else text_nc
    m2 = re.search(r'\\end\{document\}', body)
    body = body[:m2.start()] if m2 else body

    body_clean = re.sub(
        r'\\[a-zA-Z]+\*?\s*(\[[^\]]*\])?\s*\{([^}]*)\}', r'\2', body
    )
    body_clean = re.sub(r'\\[a-zA-Z]+\*?\s*(\[[^\]]*\])?', ' ', body_clean)
    body_clean = re.sub(r'[{}]', ' ', body_clean)

    return {
        "words":         len(re.findall(r'\b\w+\b', body_clean)),
        "chars":         len(text),
        "chars_nospace": len(re.sub(r'\s', '', text)),
        "lines":         text.count("\n") + 1,
        "paragraphs":    len(re.findall(r'\n\s*\n', body)) + 1,
    }


def is_in_math_mode(text: str, pos: int) -> bool:
    """True when ``pos`` sits inside a math delimiter or math environment."""
    limit = max(0, min(pos, len(text)))
    i = 0
    dollar_delim: str | None = None
    paired_delim: str | None = None
    env_stack: list[str] = []

    while i < limit:
        if text[i] == "%" and not _is_escaped(text, i):
            newline = text.find("\n", i, limit)
            i = limit if newline < 0 else newline + 1
            continue

        if env_stack:
            match = re.match(r'\\(begin|end)\{([^}]+)\}', text[i:limit])
            if match:
                name = match.group(2).rstrip("*")
                if match.group(1) == "begin" and name in _MATH_ENV_NAMES:
                    env_stack.append(name)
                elif (match.group(1) == "end" and
                      env_stack[-1] == name):
                    env_stack.pop()
                i += match.end()
                continue
            i += 1
            continue

        if dollar_delim:
            if text.startswith(dollar_delim, i) and not _is_escaped(text, i):
                i += len(dollar_delim)
                dollar_delim = None
            else:
                i += 1
            continue
        if paired_delim:
            closer = "\\)" if paired_delim == "\\(" else "\\]"
            if text.startswith(closer, i) and not _is_escaped(text, i):
                i += 2
                paired_delim = None
            else:
                i += 1
            continue

        if text.startswith("\\(", i) or text.startswith("\\[", i):
            paired_delim = text[i:i + 2]
            i += 2
            continue
        if text.startswith("$$", i) and not _is_escaped(text, i):
            dollar_delim = "$$"
            i += 2
            continue
        if text[i] == "$" and not _is_escaped(text, i):
            dollar_delim = "$"
            i += 1
            continue
        match = re.match(r'\\begin\{([^}]+)\}', text[i:limit])
        if match and match.group(1).rstrip("*") in _MATH_ENV_NAMES:
            env_stack.append(match.group(1).rstrip("*"))
            i += match.end()
            continue
        i += 2 if text[i] == "\\" and i + 1 < limit else 1

    return bool(dollar_delim or paired_delim or env_stack)


__all__ = ["count_words", "find_open_environments", "is_in_math_mode"]

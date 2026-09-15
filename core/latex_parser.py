"""Pure LaTeX scanning primitives shared by editor and project analysis.

This module deliberately has no Qt, editor or filesystem dependencies.  The
public helpers preserve source offsets where possible so callers can map a
token back to a QScintilla document or a project diagnostic.
"""

from __future__ import annotations

import bisect
import re
from typing import TypedDict


class LatexToken(TypedDict):
    """Source span produced by one of the LaTeX token scanners."""

    kind: str
    key: str
    start: int
    end: int
    command_start: int


class LatexOccurrence(LatexToken):
    """LaTeX token enriched with zero-based line and column information."""

    line: int
    column: int


def is_latex_escaped(text: str, position: int) -> bool:
    """Return whether the character at ``position`` has an odd slash prefix."""
    slashes = 0
    position -= 1
    while position >= 0 and text[position] == "\\":
        slashes += 1
        position -= 1
    return bool(slashes % 2)


def _transform_comments(text: str, replacement: str | None) -> str:
    """Apply TeX comment rules, optionally preserving source length."""
    output: list[str] = []
    in_comment = False
    for index, char in enumerate(text):
        if char == "\n":
            in_comment = False
            output.append(char)
        elif in_comment:
            if replacement is not None:
                output.append(replacement)
        elif char == "%" and not is_latex_escaped(text, index):
            in_comment = True
            if replacement is not None:
                output.append(replacement)
        else:
            output.append(char)
    return "".join(output)


def mask_latex_comments(text: str) -> str:
    """Mask comments with spaces without changing any character offsets."""
    return _transform_comments(text, " ")


def strip_latex_comments(text: str) -> str:
    """Remove TeX comments while preserving line breaks."""
    return _transform_comments(text, None)


def read_latex_group(
    text: str,
    start: int,
    opening: str = "{",
) -> tuple[int, int] | None:
    """Return the content span of a balanced group starting at ``start``."""
    closing = "}" if opening == "{" else "]"
    if start >= len(text) or text[start] != opening:
        return None
    depth = 1
    index = start + 1
    while index < len(text):
        if text[index] == "%" and not is_latex_escaped(text, index):
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline + 1
            continue
        if text[index] == "\\" and index + 1 < len(text):
            index += 2
            continue
        if text[index] == opening:
            depth += 1
        elif text[index] == closing:
            depth -= 1
            if depth == 0:
                return start + 1, index
        index += 1
    return None


_LABEL_COMMANDS = frozenset({"label"})
_REFERENCE_COMMANDS = frozenset({
    "ref", "eqref", "pageref", "cref", "Cref", "autoref", "nameref",
    "vref", "vpageref", "cpageref", "labelcref", "namecref", "nameCref",
    "namecrefs", "lcnamecref", "crefrange", "fullref", "hyperref",
})
_MULTI_REFERENCE_COMMANDS = frozenset({"crefrange"})
_OPAQUE_GROUP_COMMANDS = frozenset({
    "url", "path", "nolinkurl", "texttt", "textsf", "textrm", "textit",
    "textbf", "textrup", "textnormal", "emph", "mbox", "fbox",
})
_VERBATIM_COMMANDS = frozenset({"verb", "Verb", "lstinline", "mintinline"})
_OPAQUE_ENVIRONMENTS = frozenset({
    "verbatim", "verbatim*", "Verbatim", "BVerbatim", "lstlisting",
    "minted", "comment",
})


def _skip_latex_space(text: str, start: int) -> int:
    """Skip whitespace and comments between a command and its argument."""
    index = start
    while index < len(text):
        if text[index].isspace():
            index += 1
        elif text[index] == "%" and not is_latex_escaped(text, index):
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline + 1
        else:
            break
    return index


def _skip_latex_bracket_group(text: str, start: int) -> int:
    """Skip one optional ``[...]`` argument, returning its end."""
    if start >= len(text) or text[start] != "[":
        return start
    depth = 1
    index = start + 1
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text):
            index += 2
            continue
        if text[index] == "[":
            depth += 1
        elif text[index] == "]":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(text)


def _skip_latex_opaque_command(text: str, name: str, start: int) -> int:
    """Skip verbatim/string-like command content."""
    index = _skip_latex_space(text, start)
    if index < len(text) and text[index] == "*":
        index = _skip_latex_space(text, index + 1)
    if name == "mintinline":
        index = _skip_latex_bracket_group(text, index)
        index = _skip_latex_space(text, index)
        language = read_latex_group(text, index)
        if language is not None:
            index = language[1] + 1
        index = _skip_latex_space(text, index)
    elif name == "lstinline":
        index = _skip_latex_bracket_group(text, index)
        index = _skip_latex_space(text, index)
    if index >= len(text):
        return index
    delimiter = text[index]
    end = text.find(delimiter, index + 1)
    return len(text) if end < 0 else end + 1


def _skip_latex_opaque_environment(text: str, start: int, name: str) -> int:
    """Skip a verbatim-like environment, including its matching end token."""
    index = start
    while index < len(text):
        if text[index] == "%" and not is_latex_escaped(text, index):
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline + 1
            continue
        if text[index] != "\\":
            index += 1
            continue
        command_start = index
        index += 1
        if not text.startswith("end", index) or (
                index + 3 < len(text) and
                (text[index + 3].isalpha() or text[index + 3] == "@")):
            continue
        group = read_latex_group(text, _skip_latex_space(text, index + 3))
        if group is not None and text[group[0]:group[1]].strip() == name:
            return group[1] + 1
        index = max(index, command_start + 1)
    return len(text)


def _split_reference_argument(
    text: str,
    start: int,
    end: int,
    command_start: int,
) -> list[LatexToken]:
    tokens: list[LatexToken] = []
    part_start = start
    for position in range(start, end + 1):
        if position != end and text[position] != ",":
            continue
        key_start, key_end = part_start, position
        while key_start < key_end and text[key_start].isspace():
            key_start += 1
        while key_end > key_start and text[key_end - 1].isspace():
            key_end -= 1
        if key_start < key_end:
            tokens.append({
                "kind": "reference", "key": text[key_start:key_end],
                "start": key_start, "end": key_end,
                "command_start": command_start,
            })
        part_start = position + 1
    return tokens


def label_reference_tokens(text: str) -> list[LatexToken]:
    """Scan exact label/reference commands outside comments and string content."""
    tokens: list[LatexToken] = []
    index = 0
    while index < len(text):
        if text[index] == "%" and not is_latex_escaped(text, index):
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline + 1
            continue
        if text[index] != "\\":
            index += 1
            continue

        command_start = index
        index += 1
        if index >= len(text):
            break
        if not text[index].isalpha() and text[index] != "@":
            index += 1
            continue
        name_start = index
        while index < len(text) and (text[index].isalpha() or text[index] == "@"):
            index += 1
        name = text[name_start:index]

        if name in _VERBATIM_COMMANDS:
            index = _skip_latex_opaque_command(text, name, index)
            continue
        if name in _OPAQUE_GROUP_COMMANDS:
            group_start = _skip_latex_space(text, index)
            group = read_latex_group(text, group_start)
            index = len(text) if group is None else group[1] + 1
            continue
        if name == "begin":
            group = read_latex_group(text, _skip_latex_space(text, index))
            if group is not None:
                environment = text[group[0]:group[1]].strip()
                if environment in _OPAQUE_ENVIRONMENTS:
                    index = _skip_latex_opaque_environment(
                        text, group[1] + 1, environment,
                    )
                    continue
        if name not in _LABEL_COMMANDS and name not in _REFERENCE_COMMANDS:
            continue

        argument_start = _skip_latex_space(text, index + (text[index:index + 1] == "*"))
        groups: list[tuple[int, int]] = []
        group_limit = 1 if name not in _MULTI_REFERENCE_COMMANDS else 2
        while len(groups) < group_limit:
            group = read_latex_group(text, argument_start)
            if group is None:
                break
            groups.append(group)
            argument_start = _skip_latex_space(text, group[1] + 1)

        if name == "hyperref":
            bracket_start = _skip_latex_space(text, index)
            if bracket_start < len(text) and text[bracket_start] == "[":
                bracket_end = _skip_latex_bracket_group(text, bracket_start)
                content_start = bracket_start + 1
                content_end = max(content_start, bracket_end - 1)
                if bracket_end > content_start:
                    tokens.extend(_split_reference_argument(
                        text, content_start, content_end, command_start,
                    ))
                index = bracket_end
            continue

        if name == "label" and groups:
            content_start, content_end = groups[0]
            key = text[content_start:content_end].strip()
            if key:
                key_start = content_start + (
                    len(text[content_start:content_end]) -
                    len(text[content_start:content_end].lstrip())
                )
                tokens.append({
                    "kind": "label", "key": key,
                    "start": key_start, "end": key_start + len(key),
                    "command_start": command_start,
                })
        elif name in _REFERENCE_COMMANDS:
            for content_start, content_end in groups:
                tokens.extend(_split_reference_argument(
                    text, content_start, content_end, command_start,
                ))
        index = max(index, argument_start)
    return tokens


def extract_label_reference_occurrences(text: str) -> list[LatexOccurrence]:
    """Return label/reference tokens with zero-based line and column."""
    occurrences: list[LatexOccurrence] = []
    newline_positions = [match.start() for match in re.finditer("\n", text)]
    for token in label_reference_tokens(text):
        occurrence: LatexOccurrence = {
            **token,
            "line": 0,
            "column": 0,
        }
        position = occurrence["start"]
        line = bisect.bisect_left(newline_positions, position)
        occurrence["line"] = line
        previous_newline = newline_positions[line - 1] if line else -1
        occurrence["column"] = (
            position if previous_newline < 0 else position - previous_newline - 1
        )
        occurrences.append(occurrence)
    return occurrences


_SECTION_COMMANDS = (
    "part", "chapter", "section", "subsection",
    "subsubsection", "paragraph", "subparagraph",
)
_SECTION_RE = re.compile(
    r'\\(' + "|".join(_SECTION_COMMANDS) + r')\*?(?:\[([^]]*)\])?\{([^}]*)\}'
)


def extract_sections(text: str) -> list[tuple[str, str, int]]:
    """Return ``(kind, title, zero_based_line)`` section entries."""
    sections: list[tuple[str, str, int]] = []
    for line_number, line in enumerate(strip_latex_comments(text).split("\n")):
        for match in _SECTION_RE.finditer(line):
            title = match.group(2) if match.group(2) is not None else match.group(3)
            sections.append((match.group(1), title, line_number))
    return sections


__all__ = [
    "extract_label_reference_occurrences",
    "extract_sections",
    "is_latex_escaped",
    "label_reference_tokens",
    "LatexOccurrence",
    "LatexToken",
    "mask_latex_comments",
    "read_latex_group",
    "strip_latex_comments",
]

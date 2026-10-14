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
    """Apply TeX comment rules, optionally preserving source length.

    Salta tra i '%' con ``str.find`` (e copia i tratti con slicing) invece di
    iterare carattere per carattere: su un documento multi-MB il ciclo
    per-carattere costava centinaia di ms e costruiva una lista di milioni di
    stringhe di un carattere.
    """
    if "%" not in text:
        return text
    output: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        pct = text.find("%", index)
        if pct < 0:
            output.append(text[index:])
            break
        if is_latex_escaped(text, pct):
            # Percentuale escapata (\%): non apre un commento.
            output.append(text[index:pct + 1])
            index = pct + 1
            continue
        output.append(text[index:pct])
        newline = text.find("\n", pct)
        if newline < 0:
            if replacement is not None:
                output.append(replacement * (length - pct))
            break
        if replacement is not None:
            output.append(replacement * (newline - pct))
        output.append("\n")
        index = newline + 1
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
    length = len(text)
    if start >= length or text[start] != opening:
        return None
    # Fast path (C-level): when the group up to the first closing delimiter has
    # no nested opener, backslash or comment, that delimiter closes it.  Most
    # groups seen by the scanners are simple, so this skips the Python loop.
    end = text.find(closing, start + 1)
    if end >= 0:
        inner = text[start + 1:end]
        if opening not in inner and "\\" not in inner and "%" not in inner:
            return start + 1, end
    depth = 1
    index = start + 1
    while index < length:
        if text[index] == "%" and not is_latex_escaped(text, index):
            newline = text.find("\n", index)
            index = length if newline < 0 else newline + 1
            continue
        if text[index] == "\\" and index + 1 < length:
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
    length = len(text)
    while index < length:
        if text[index].isspace():
            index += 1
        elif text[index] == "%" and not is_latex_escaped(text, index):
            newline = text.find("\n", index)
            index = length if newline < 0 else newline + 1
        else:
            break
    return index


def _skip_latex_bracket_group(text: str, start: int) -> int:
    """Skip one optional ``[...]`` argument, returning its end."""
    length = len(text)
    if start >= length or text[start] != "[":
        return start
    depth = 1
    index = start + 1
    while index < length:
        if text[index] == "\\" and index + 1 < length:
            index += 2
            continue
        if text[index] == "[":
            depth += 1
        elif text[index] == "]":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return length


def _skip_latex_opaque_command(text: str, name: str, start: int) -> int:
    """Skip verbatim/string-like command content."""
    length = len(text)
    index = _skip_latex_space(text, start)
    if index < length and text[index] == "*":
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
    if index >= length:
        return index
    delimiter = text[index]
    end = text.find(delimiter, index + 1)
    return length if end < 0 else end + 1


def _skip_latex_opaque_environment(text: str, start: int, name: str) -> int:
    """Skip a verbatim-like environment, including its matching end token."""
    index = start
    length = len(text)
    while index < length:
        if text[index] == "%" and not is_latex_escaped(text, index):
            newline = text.find("\n", index)
            index = length if newline < 0 else newline + 1
            continue
        if text[index] != "\\":
            index += 1
            continue
        command_start = index
        index += 1
        if not text.startswith("end", index) or (
                index + 3 < length and
                (text[index + 3].isalpha() or text[index + 3] == "@")):
            continue
        group = read_latex_group(text, _skip_latex_space(text, index + 3))
        if group is not None and text[group[0]:group[1]].strip() == name:
            return group[1] + 1
        index = max(index, command_start + 1)
    return length


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


# Comandi realmente rilevanti: label/ref, argomenti opachi e verbatim, più
# 'begin' per gli ambienti verbatim. Un'unica regex in C li individua e scarta
# in blocco i ~50k comandi non pertinenti di un documento grande, invece di
# eseguire un match del nome per ogni backslash.
_SCAN_COMMANDS = tuple(sorted(
    _LABEL_COMMANDS | _REFERENCE_COMMANDS | _OPAQUE_GROUP_COMMANDS
    | _VERBATIM_COMMANDS | {"begin"},
    key=len, reverse=True,
))
_SCAN_RE = re.compile(
    r"%|\\(?P<name>"
    + "|".join(re.escape(name) for name in _SCAN_COMMANDS)
    + r")(?![A-Za-z@])"
)


def label_reference_tokens(text: str) -> list[LatexToken]:
    """Scan exact label/reference commands outside comments and string content.

    Scandisce i soli caratteri speciali ('%' e '\\\\') in un unico passaggio
    regex (eseguito in C) invece di iterare carattere per carattere in Python:
    su un documento da 3 MB il vecchio ciclo costava ~500 ms. ``skip_until``
    ignora i match interni a commenti/gruppi opachi già consumati.
    """
    tokens: list[LatexToken] = []
    length = len(text)
    skip_until = 0
    for match in _SCAN_RE.finditer(text):
        index = match.start()
        if index < skip_until:
            continue
        if text[index] == "%":
            if is_latex_escaped(text, index):
                continue
            newline = text.find("\n", index)
            skip_until = length if newline < 0 else newline + 1
            continue

        command_start = index
        name = match.group("name")
        index = match.end()

        if name in _VERBATIM_COMMANDS:
            skip_until = _skip_latex_opaque_command(text, name, index)
            continue
        if name in _OPAQUE_GROUP_COMMANDS:
            group_start = _skip_latex_space(text, index)
            group = read_latex_group(text, group_start)
            skip_until = length if group is None else group[1] + 1
            continue
        if name == "begin":
            group = read_latex_group(text, _skip_latex_space(text, index))
            if group is not None:
                environment = text[group[0]:group[1]].strip()
                if environment in _OPAQUE_ENVIRONMENTS:
                    skip_until = _skip_latex_opaque_environment(
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
            if bracket_start < length and text[bracket_start] == "[":
                bracket_end = _skip_latex_bracket_group(text, bracket_start)
                content_start = bracket_start + 1
                content_end = max(content_start, bracket_end - 1)
                if bracket_end > content_start:
                    tokens.extend(_split_reference_argument(
                        text, content_start, content_end, command_start,
                    ))
                skip_until = bracket_end
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
        # Riprende la scansione dopo gli argomenti già letti.
        if argument_start > skip_until:
            skip_until = argument_start
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


def extract_sections(text: str) -> list[tuple[str, str, int]]:
    """Return ``(kind, title, zero_based_line)`` section entries."""
    from core.latex_tokenizer import scan_sections

    code = mask_latex_comments(text)
    sections: list[tuple[str, str, int]] = []
    for section in scan_sections(code):
        sections.append((section.kind, section.name, code.count("\n", 0, section.offset)))
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

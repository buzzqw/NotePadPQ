"""Dependency-free citation span parser used by project analysis."""

from __future__ import annotations

import bisect

from core.latex_parser import (
    LatexOccurrence,
    is_latex_escaped,
    mask_latex_comments,
    read_latex_group,
)

_CITATION_COMMANDS = frozenset({
    "parencite", "parencites", "textcite", "textcites", "footcite",
    "footcites", "autocite", "autocites", "smartcite", "smartcites",
    "supercite", "supercites", "citeauthor", "citeyear", "citeyearpar",
    "citealp", "citealt", "citet", "citep", "cites", "nocite",
})
_OPAQUE_COMMANDS = frozenset({
    "url", "path", "nolinkurl", "texttt", "textsf", "textrm", "textit",
    "textbf", "textup", "textnormal", "emph", "mbox", "fbox",
})
_VERBATIM_COMMANDS = frozenset({"verb", "Verb", "lstinline", "mintinline"})


_escaped = is_latex_escaped
_scan = mask_latex_comments
_group = read_latex_group


def extract_latex_citation_occurrences(text: str) -> list[LatexOccurrence]:
    """Return citation key spans while preserving original source offsets."""
    scanned = _scan(text)
    occurrences: list[LatexOccurrence] = []
    newline_positions = [index for index, char in enumerate(text) if char == "\n"]
    index = 0
    while index < len(scanned):
        if scanned[index] != "\\" or _escaped(scanned, index):
            index += 1
            continue
        command_start = index
        index += 1
        name_start = index
        while index < len(scanned) and (scanned[index].isalpha() or scanned[index] == "@"):
            index += 1
        name = scanned[name_start:index]
        if name in _OPAQUE_COMMANDS:
            while index < len(scanned) and scanned[index].isspace():
                index += 1
            if index < len(scanned) and scanned[index] == "*":
                index += 1
            group = _group(scanned, index)
            index = len(scanned) if group is None else group[1] + 1
            continue
        if name in _VERBATIM_COMMANDS:
            while index < len(scanned) and scanned[index].isspace():
                index += 1
            if index < len(scanned):
                delimiter = scanned[index]
                end = scanned.find(delimiter, index + 1)
                index = len(scanned) if end < 0 else end + 1
            continue
        if not name or (name not in _CITATION_COMMANDS and not name.lower().startswith("cite")):
            continue
        if index < len(scanned) and scanned[index] == "*":
            index += 1
        for _ in range(2):
            while index < len(scanned) and scanned[index].isspace():
                index += 1
            if index >= len(scanned) or scanned[index] != "[":
                break
            optional = _group(scanned, index, "[")
            if optional is None:
                index = len(scanned)
                break
            index = optional[1] + 1
        while index < len(scanned) and scanned[index].isspace():
            index += 1
        group = _group(scanned, index)
        if group is None:
            continue
        content_start, content_end = group
        part_start = content_start
        for position in range(content_start, content_end + 1):
            if position != content_end and scanned[position] != ",":
                continue
            key_start, key_end = part_start, position
            while key_start < key_end and scanned[key_start].isspace():
                key_start += 1
            while key_end > key_start and scanned[key_end - 1].isspace():
                key_end -= 1
            if key_start < key_end:
                line = bisect.bisect_left(newline_positions, key_start)
                previous_newline = newline_positions[line - 1] if line else -1
                occurrences.append({
                    "kind": "citation", "key": text[key_start:key_end],
                    "start": key_start, "end": key_end,
                    "command_start": command_start,
                    "line": line,
                    "column": key_start if previous_newline < 0 else key_start - previous_newline - 1,
                })
            part_start = position + 1
        index = group[1] + 1
    return occurrences


__all__ = ["extract_latex_citation_occurrences"]

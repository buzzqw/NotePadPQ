"""Dependency-free citation span parser used by project analysis."""

from __future__ import annotations

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


def _escaped(text: str, position: int) -> bool:
    slashes = 0
    position -= 1
    while position >= 0 and text[position] == "\\":
        slashes += 1
        position -= 1
    return bool(slashes % 2)


def _scan(text: str) -> str:
    chars = list(text)
    in_comment = False
    for index, char in enumerate(text):
        if char == "\n":
            in_comment = False
        elif in_comment:
            chars[index] = " "
        elif char == "%" and not _escaped(text, index):
            chars[index] = " "
            in_comment = True
    return "".join(chars)


def _group(text: str, start: int, opening: str = "{") -> tuple[int, int] | None:
    closing = "}" if opening == "{" else "]"
    if start >= len(text) or text[start] != opening:
        return None
    depth = 1
    index = start + 1
    while index < len(text):
        if text[index] == "\\":
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


def extract_latex_citation_occurrences(text: str) -> list[dict]:
    """Return citation key spans while preserving original source offsets."""
    scanned = _scan(text)
    occurrences: list[dict] = []
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
                occurrences.append({
                    "kind": "citation", "key": text[key_start:key_end],
                    "start": key_start, "end": key_end,
                    "command_start": command_start,
                    "line": text.count("\n", 0, key_start),
                    "column": key_start - text.rfind("\n", 0, key_start) - 1,
                })
            part_start = position + 1
        index = group[1] + 1
    return occurrences


__all__ = ["extract_latex_citation_occurrences"]

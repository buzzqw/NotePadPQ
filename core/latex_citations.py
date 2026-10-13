"""Dependency-free citation span parser used by project analysis."""

from __future__ import annotations

import re

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

# I comandi rilevanti si localizzano con un'unica regex (in C): su OBSSv2.tex
# (~3 MB, ~57k backslash) scorrere tutti i comandi e leggerne il nome in Python
# costava ~110 ms, quasi tutto speso a scartare i comandi non citazionali.
# L'alternanza copre le citazioni (famiglia ``cite*`` più i nomi biblatex), i
# comandi opachi e verbatim; il lookahead finale garantisce il nome completo
# (`\verb` non deve catturare `\verbatim`). ``skip_until`` ignora i match dentro
# argomenti opachi/verbatim già consumati. ``scanned`` è già mascherato, quindi
# i '%' residui sono solo '\%' escapati e non serve scorciatoia per i commenti.
_EXPLICIT_COMMANDS = tuple(sorted(
    set(_OPAQUE_COMMANDS) | set(_VERBATIM_COMMANDS)
    | {name for name in _CITATION_COMMANDS if not name.lower().startswith("cite")},
    key=len, reverse=True,
))
_COMMAND_RE = re.compile(
    r"\\(?P<name>(?i:cite[A-Za-z@]*)"
    + "".join("|" + re.escape(name) for name in _EXPLICIT_COMMANDS)
    + r")(?![A-Za-z@])"
)


def extract_latex_citation_occurrences(text: str) -> list[LatexOccurrence]:
    """Return citation key spans while preserving original source offsets."""
    scanned = _scan(text)
    occurrences: list[LatexOccurrence] = []
    length = len(scanned)
    skip_until = 0
    for match in _COMMAND_RE.finditer(scanned):
        index = match.start()
        # Dentro un argomento opaco/verbatim già consumato, o se la barra è
        # escapata ("\\"), non c'è un comando.
        if index < skip_until or (
                index > 0 and scanned[index - 1] == "\\" and _escaped(scanned, index)):
            continue
        command_start = index
        name = match.group("name")
        index = match.end()

        if name in _OPAQUE_COMMANDS:
            while index < length and scanned[index].isspace():
                index += 1
            if index < length and scanned[index] == "*":
                index += 1
            group = _group(scanned, index)
            skip_until = length if group is None else group[1] + 1
            continue
        if name in _VERBATIM_COMMANDS:
            while index < length and scanned[index].isspace():
                index += 1
            if index < length:
                delimiter = scanned[index]
                end = scanned.find(delimiter, index + 1)
                skip_until = length if end < 0 else end + 1
            continue
        if not name or (name not in _CITATION_COMMANDS and not name.lower().startswith("cite")):
            continue
        if index < length and scanned[index] == "*":
            index += 1
        for _ in range(2):
            while index < length and scanned[index].isspace():
                index += 1
            if index >= length or scanned[index] != "[":
                break
            optional = _group(scanned, index, "[")
            if optional is None:
                index = length
                break
            index = optional[1] + 1
        while index < length and scanned[index].isspace():
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
                line = text.count("\n", 0, key_start)
                previous_newline = text.rfind("\n", 0, key_start)
                occurrences.append({
                    "kind": "citation", "key": text[key_start:key_end],
                    "start": key_start, "end": key_end,
                    "command_start": command_start,
                    "line": line,
                    "column": key_start if previous_newline < 0 else key_start - previous_newline - 1,
                })
            part_start = position + 1
        skip_until = group[1] + 1
    return occurrences


__all__ = ["extract_latex_citation_occurrences"]

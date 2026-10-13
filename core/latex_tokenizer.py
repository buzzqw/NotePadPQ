"""Group-aware LaTeX scanners shared by the analysis layer.

The analysis layer used to describe the same constructs with a handful of
single-line regular expressions (``_SECTION_RE``, ``_PACKAGE_RE``,
``_CUSTOM_COMMAND_RE`` ...).  Those cannot see an argument spread over several
lines or one that contains nested braces.  These scanners walk the text once
and read balanced groups with :func:`read_latex_group`, so the same construct
is described identically by every consumer.

``scan_document`` classifies the whole command surface in a single pass;
the per-construct helpers are thin views over it.  Unless stated otherwise the
input must already be comment-masked (``mask_latex_comments``), which preserves
offsets so callers can map a span back to the editor or a project diagnostic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.latex_parser import is_latex_escaped, read_latex_group

_COMMAND_RE = re.compile(r"\\([A-Za-z@]+)(\*?)")
_COMMAND_NAME_RE = re.compile(r"\\[A-Za-z@]+")

_SECTION_COMMANDS = frozenset({
    "part", "chapter", "section", "subsection", "subsubsection",
    "paragraph", "subparagraph",
})
_PACKAGE_COMMANDS = frozenset({"usepackage", "RequirePackage", "documentclass"})
_COMMAND_DEFINITION_COMMANDS = frozenset({"newcommand", "renewcommand", "providecommand"})
_OPERATOR_DEFINITION_COMMANDS = frozenset({"DeclareMathOperator", "def", "let"})
_ENVIRONMENT_DEFINITION_COMMANDS = frozenset({"newenvironment", "renewenvironment"})
_BIBLIOGRAPHY_COMMANDS = frozenset({"bibliography", "addbibresource"})
_HYPERTARGET_COMMANDS = frozenset({"hypertarget"})


@dataclass(frozen=True, slots=True)
class SectionSpan:
    kind: str
    name: str
    offset: int


@dataclass(frozen=True, slots=True)
class CustomCommandSpan:
    name: str            # including the leading backslash, e.g. "\\foo"
    offset: int
    arguments: int | None = None
    has_default: bool = False


@dataclass(frozen=True, slots=True)
class CustomEnvironmentSpan:
    name: str
    offset: int


@dataclass(frozen=True, slots=True)
class DocumentSpans:
    """Everything the analysis layer reads from one document source."""

    sections: tuple[SectionSpan, ...] = ()
    packages: frozenset[str] = frozenset()
    custom_commands: tuple[CustomCommandSpan, ...] = ()
    custom_environments: tuple[CustomEnvironmentSpan, ...] = ()
    hypertargets: frozenset[str] = frozenset()
    bibliography_references: tuple[str, ...] = ()


def skip_space(text: str, index: int) -> int:
    """Skip whitespace and TeX comments from ``index`` onwards."""
    length = len(text)
    while index < length:
        char = text[index]
        if char.isspace():
            index += 1
        elif char == "%" and not is_latex_escaped(text, index):
            newline = text.find("\n", index)
            index = length if newline < 0 else newline + 1
        else:
            break
    return index


def read_bracket(text: str, start: int) -> tuple[int, int] | None:
    """Return the content span of a balanced ``[...]`` group at ``start``."""
    length = len(text)
    if start >= length or text[start] != "[":
        return None
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
                return start + 1, index
        index += 1
    return None


def iter_command_calls(code: str, names, n_optional: int = 0, n_mandatory: int = 1):
    """Yield ``(name, command_start, optionals, mandatories)`` for commands.

    ``optionals``/``mandatories`` are tuples of ``(content_start, content_end)``
    spans.  Commands nested inside a consumed argument are still yielded on
    their own, matching the linear regular-expression behaviour.
    """
    names = frozenset(names)
    for match in _COMMAND_RE.finditer(code):
        name = match.group(1)
        if name not in names:
            continue
        yield (name, match.start()) + _read_arguments(
            code, match.end(), n_optional, n_mandatory)


def _read_arguments(code: str, cursor: int, n_optional: int, n_mandatory: int):
    optionals: list[tuple[int, int]] = []
    mandatories: list[tuple[int, int]] = []
    for _ in range(n_optional):
        cursor = skip_space(code, cursor)
        if cursor >= len(code) or code[cursor] != "[":
            break
        bracket = read_bracket(code, cursor)
        if bracket is None:
            break
        optionals.append(bracket)
        cursor = bracket[1] + 1
    for _ in range(n_mandatory):
        cursor = skip_space(code, cursor)
        group = read_latex_group(code, cursor)
        if group is None:
            break
        mandatories.append(group)
        cursor = group[1] + 1
    return tuple(optionals), tuple(mandatories)


def _read_command_name(code: str, cursor: int) -> tuple[str, int] | None:
    """Read ``{\\name}`` or a bare ``\\name`` definition target."""
    cursor = skip_space(code, cursor)
    if cursor < len(code) and code[cursor] == "{":
        group = read_latex_group(code, cursor)
        if group is None:
            return None
        inner = code[group[0]:group[1]].strip()
        return (inner, group[1] + 1) if inner.startswith("\\") else None
    match = _COMMAND_NAME_RE.match(code, cursor)
    if match is None:
        return None
    return match.group(0), match.end()


def _custom_command(code: str, match) -> CustomCommandSpan | None:
    parsed = _read_command_name(code, match.end())
    if parsed is None:
        return None
    command, cursor = parsed
    arguments: int | None = None
    has_default = False
    cursor = skip_space(code, cursor)
    if cursor < len(code) and code[cursor] == "[":
        bracket = read_bracket(code, cursor)
        if bracket is not None:
            raw = code[bracket[0]:bracket[1]].strip()
            if raw.isdigit():
                arguments = int(raw)
                cursor = skip_space(code, bracket[1] + 1)
                if cursor < len(code) and code[cursor] == "[":
                    if read_bracket(code, cursor) is not None:
                        has_default = True
    return CustomCommandSpan(command, match.start(), arguments, has_default)


def scan_document(code: str) -> DocumentSpans:
    """Classify sections, packages, custom macros and bibliographies in one pass."""
    sections: list[SectionSpan] = []
    packages: set[str] = set()
    custom_commands: list[CustomCommandSpan] = []
    custom_environments: list[CustomEnvironmentSpan] = []
    hypertargets: set[str] = set()
    bibliography: list[str] = []

    for match in _COMMAND_RE.finditer(code):
        name = match.group(1)
        if name in _SECTION_COMMANDS:
            optionals, mandatories = _read_arguments(code, match.end(), 1, 1)
            if not mandatories:
                continue
            content_start, content_end = mandatories[0]
            title = code[content_start:content_end]
            if optionals:
                short_start, short_end = optionals[0]
                title = code[short_start:short_end]
            sections.append(SectionSpan(name, title, match.start()))
        elif name in _PACKAGE_COMMANDS:
            _optionals, mandatories = _read_arguments(code, match.end(), 1, 1)
            if mandatories:
                content_start, content_end = mandatories[0]
                packages.update(
                    package.strip()
                    for package in code[content_start:content_end].split(",")
                    if package.strip()
                )
        elif name in _COMMAND_DEFINITION_COMMANDS or name in _OPERATOR_DEFINITION_COMMANDS:
            definition = _custom_command(code, match)
            if definition is not None:
                custom_commands.append(definition)
        elif name in _ENVIRONMENT_DEFINITION_COMMANDS:
            _optionals, mandatories = _read_arguments(code, match.end(), 1, 1)
            if mandatories:
                content_start, content_end = mandatories[0]
                environment = code[content_start:content_end].strip()
                if environment:
                    custom_environments.append(
                        CustomEnvironmentSpan(environment, match.start()))
        elif name in _HYPERTARGET_COMMANDS:
            _optionals, mandatories = _read_arguments(code, match.end(), 0, 1)
            if mandatories:
                content_start, content_end = mandatories[0]
                target = code[content_start:content_end].strip()
                if target:
                    hypertargets.add(target)
        elif name in _BIBLIOGRAPHY_COMMANDS:
            _optionals, mandatories = _read_arguments(code, match.end(), 1, 1)
            if mandatories:
                content_start, content_end = mandatories[0]
                bibliography.extend(
                    reference.strip()
                    for reference in code[content_start:content_end].split(",")
                    if reference.strip()
                )

    return DocumentSpans(
        sections=tuple(sections),
        packages=frozenset(packages),
        custom_commands=tuple(custom_commands),
        custom_environments=tuple(custom_environments),
        hypertargets=frozenset(hypertargets),
        bibliography_references=tuple(bibliography),
    )


# ── Views over a single document pass ─────────────────────────────────────────

def scan_sections(code: str) -> list[SectionSpan]:
    """Return document sections with offsets (nested/multi-line safe)."""
    return list(scan_document(code).sections)


def scan_packages(code: str) -> set[str]:
    """Return package/class names from ``\\usepackage``/``\\documentclass``."""
    return set(scan_document(code).packages)


def scan_custom_command_definitions(code: str) -> list[CustomCommandSpan]:
    """Return ``\\newcommand``-family and operator definitions."""
    return list(scan_document(code).custom_commands)


def scan_custom_environment_spans(code: str) -> list[CustomEnvironmentSpan]:
    """Return environment definitions with their offsets."""
    return list(scan_document(code).custom_environments)


def scan_custom_environments(code: str) -> set[str]:
    """Return environment names defined with ``\\newenvironment``."""
    return {span.name for span in scan_custom_environment_spans(code)}


def scan_hypertargets(code: str) -> set[str]:
    """Return names defined with ``\\hypertarget{name}{...}``."""
    return set(scan_document(code).hypertargets)


def scan_bibliography_references(code: str) -> list[str]:
    """Return raw ``\\bibliography``/``\\addbibresource`` reference names."""
    return list(scan_document(code).bibliography_references)


_BIB_ENTRY_RE = re.compile(r"@[A-Za-z][\w-]*\s*[({]\s*([^,\s]+)\s*,")


def scan_bib_entries(code: str) -> set[str]:
    """Return BibTeX entry keys from a ``.bib`` source."""
    return set(_BIB_ENTRY_RE.findall(code))


def scan_citation_keys(code: str) -> set[str]:
    """Return citation keys, ignoring the ``*`` wildcard and ``nocite``."""
    from core.latex_citations import extract_latex_citation_occurrences
    keys = {occurrence["key"]
            for occurrence in extract_latex_citation_occurrences(code)}
    keys.discard("*")
    return keys


__all__ = [
    "CustomCommandSpan",
    "CustomEnvironmentSpan",
    "DocumentSpans",
    "SectionSpan",
    "iter_command_calls",
    "read_bracket",
    "scan_bibliography_references",
    "scan_bib_entries",
    "scan_citation_keys",
    "scan_custom_command_definitions",
    "scan_custom_environment_spans",
    "scan_custom_environments",
    "scan_document",
    "scan_hypertargets",
    "scan_packages",
    "scan_sections",
    "skip_space",
]

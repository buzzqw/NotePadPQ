"""Project-wide LaTeX references analysis.

The scanner in this module is deliberately independent from widgets and editor
instances.  It accepts a file path plus an optional in-memory snapshot, which
makes it suitable for a QThread, a command-line caller, or a future service.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from core.latex_citations import extract_latex_citation_occurrences
from editor.latex_support import LaTeXSupport, strip_latex_comments

_BIB_ENTRY_RE = re.compile(r"@[A-Za-z][\w-]*\s*[({]\s*([^,\s]+)\s*,")
_BIBITEM_RE = re.compile(r"\\bibitem(?:\[[^]]*\])?\s*\{([^}]+)\}")
_COMMAND_RE = re.compile(r"\\([A-Za-z@]+)")
_TEX_EXTENSIONS = (".tex", ".ltx", ".latex")
_BIB_EXTENSIONS = (".bib",)
_IMAGE_EXTENSIONS = (
    ".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg", ".webp",
    ".bmp", ".gif", ".tif", ".tiff",
)
_SOURCE_COMMANDS = frozenset({
    "input", "include", "subfile", "import", "subimport", "includefrom",
    "subinputfrom",
})
_ASSET_COMMANDS = frozenset({
    "includegraphics", "includesvg", "includepdf", "inputminted",
    "lstinputlisting", "verbatiminput",
})
_BIB_COMMANDS = frozenset({"bibliography", "addbibresource"})


@dataclass(frozen=True, slots=True)
class LatexLocation:
    """A source location. Lines are one-based; columns are zero-based."""

    file: Path
    line: int
    column: int = 0
    end_column: int | None = None


@dataclass(frozen=True, slots=True)
class LatexReference:
    """A label definition, label reference, or citation occurrence."""

    key: str
    location: LatexLocation
    kind: str
    command: str = ""

    @property
    def file(self) -> Path:
        return self.location.file

    @property
    def line(self) -> int:
        return self.location.line

    @property
    def column(self) -> int:
        return self.location.column


@dataclass(frozen=True, slots=True)
class LatexInclude:
    """A source, bibliography, or asset path used by a LaTeX command."""

    requested: str
    kind: str
    location: LatexLocation
    resolved: Path | None = None

    @property
    def file(self) -> Path:
        return self.location.file

    @property
    def line(self) -> int:
        return self.location.line

    @property
    def missing(self) -> bool:
        return self.resolved is None


@dataclass(frozen=True, slots=True)
class LatexReferencesAnalysis:
    """Immutable result returned by :func:`analyze_latex_project`."""

    root: Path | None
    files: tuple[Path, ...]
    definitions: tuple[LatexReference, ...] = ()
    references: tuple[LatexReference, ...] = ()
    citations: tuple[LatexReference, ...] = ()
    undefined: tuple[LatexReference, ...] = ()
    undefined_citations: tuple[LatexReference, ...] = ()
    duplicates: tuple[LatexReference, ...] = ()
    unused: tuple[LatexReference, ...] = ()
    includes: tuple[LatexInclude, ...] = ()
    assets: tuple[LatexInclude, ...] = ()
    missing_includes: tuple[LatexInclude, ...] = ()
    missing_assets: tuple[LatexInclude, ...] = ()
    bibliography_files: tuple[Path, ...] = ()
    bibliography_keys: tuple[str, ...] = ()
    unused_citations: tuple[str, ...] = ()

    @property
    def duplicate(self) -> tuple[LatexReference, ...]:
        """Singular compatibility spelling for consumers displaying a list."""
        return self.duplicates


def _balanced_group(text: str, start: int) -> tuple[int, int] | None:
    if start >= len(text) or text[start] != "{":
        return None
    depth = 1
    index = start + 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return start + 1, index
        index += 1
    return None


def _command_name(text: str, position: int) -> str:
    match = _COMMAND_RE.match(text, position)
    return "" if match is None else match.group(1)


def _line_column(text: str, position: int) -> tuple[int, int]:
    line_start = text.rfind("\n", 0, position) + 1
    return text.count("\n", 0, position) + 1, position - line_start


def _masked_comments(text: str) -> str:
    """Mask comments without changing offsets used for navigation."""
    chars = list(text)
    in_comment = False
    for index, char in enumerate(text):
        if char == "\n":
            in_comment = False
        elif in_comment:
            chars[index] = " "
        elif char == "%":
            slashes = 0
            previous = index - 1
            while previous >= 0 and text[previous] == "\\":
                slashes += 1
                previous -= 1
            if slashes % 2 == 0:
                chars[index] = " "
                in_comment = True
    return "".join(chars)


def _source_texts(
    current_file: str | Path | None,
    content: str | None,
    max_depth: int,
) -> tuple[Path | None, list[tuple[Path, str]]]:
    if current_file is None:
        return None, [(Path("<memory>"), content or "")]

    current = Path(current_file).expanduser().resolve()
    root = current
    try:
        from core.latex_project import resolve_project_root

        root = resolve_project_root(current, content)
    except (OSError, RuntimeError, ValueError):
        pass

    paths = LaTeXSupport.collect_project_files(root, max_depth=max_depth)
    if not paths and root != current and current.is_file():
        paths = [current]
    elif not paths and (current.is_file() or content is not None):
        paths = [current]

    sources: list[tuple[Path, str]] = []
    for path in paths:
        try:
            source = content if path == current and content is not None else path.read_text(
                encoding="utf-8", errors="replace",
            )
        except OSError:
            continue
        sources.append((path.resolve(), source))
    if not sources and content is not None:
        sources.append((current, content))
    return root, sources


def _iter_group_commands(text: str, names: Iterable[str]):
    """Yield ``(command, argument, argument_start)`` for simple group commands."""
    allowed = set(names)
    code = _masked_comments(text)
    for match in _COMMAND_RE.finditer(code):
        command = match.group(1)
        if command not in allowed:
            continue
        index = match.end()
        while index < len(code) and code[index].isspace():
            index += 1
        if index < len(code) and code[index] == "*":
            index += 1
            while index < len(code) and code[index].isspace():
                index += 1
        group = _balanced_group(code, index)
        if group is not None:
            start, end = group
            yield command, code[start:end], start


def _iter_command_groups(text: str, names: Iterable[str], max_groups: int = 2):
    """Yield command arguments while accepting optional and multiple groups."""
    allowed = set(names)
    code = _masked_comments(text)
    for match in _COMMAND_RE.finditer(code):
        command = match.group(1)
        if command not in allowed:
            continue
        index = match.end()
        groups: list[tuple[int, int]] = []
        while index < len(code) and len(groups) < max_groups:
            while index < len(code) and code[index].isspace():
                index += 1
            if index < len(code) and code[index] == "*":
                index += 1
                continue
            if index < len(code) and code[index] == "[":
                depth = 1
                index += 1
                while index < len(code) and depth:
                    if code[index] == "\\":
                        index += 2
                    else:
                        depth += code[index] == "["
                        depth -= code[index] == "]"
                        index += 1
                continue
            group = _balanced_group(code, index)
            if group is None:
                break
            groups.append(group)
            index = group[1] + 1
        if groups:
            yield command, [(code[start:end], start) for start, end in groups]


def _resolve_candidates(base: Path, requested: str, extensions: tuple[str, ...]) -> Path | None:
    path = (base / requested.strip()).expanduser().resolve()
    candidates = [path]
    if path.suffix == "":
        candidates.extend(path.with_suffix(extension) for extension in extensions)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _resolve_source(base: Path, requested: str) -> Path | None:
    return _resolve_candidates(base, requested, _TEX_EXTENSIONS)


def _parse_include_entries(path: Path, text: str) -> tuple[list[LatexInclude], list[LatexInclude]]:
    includes: list[LatexInclude] = []
    assets: list[LatexInclude] = []
    code = _masked_comments(text)

    for command, groups in _iter_command_groups(code, _SOURCE_COMMANDS | _BIB_COMMANDS):
        argument, argument_start = groups[-1]
        line, column = _line_column(text, argument_start)
        location = LatexLocation(path, line, column, column + len(argument))
        if command in _SOURCE_COMMANDS:
            requested = argument.strip()
            base = path.parent
            if command in {"import", "subimport", "includefrom", "subinputfrom"} and len(groups) >= 2:
                prefix, _ = groups[-2]
                base = (base / prefix.strip()).resolve()
            includes.append(LatexInclude(
                requested, command, location, _resolve_source(base, requested),
            ))
        else:
            for requested in argument.split(","):
                requested = requested.strip()
                if not requested:
                    continue
                includes.append(LatexInclude(
                    requested, command, location,
                    _resolve_candidates(path.parent, requested, _BIB_EXTENSIONS),
                ))

    graphics_dirs = [path.parent]
    for _, argument, _ in _iter_group_commands(code, {"graphicspath"}):
        graphics_dirs.extend(
            (path.parent / item).resolve()
            for item in re.findall(r"\{([^{}]+)\}", argument)
            if item.strip()
        )

    for command, groups in _iter_command_groups(code, _ASSET_COMMANDS):
        argument, argument_start = groups[-1]
        line, column = _line_column(text, argument_start)
        location = LatexLocation(path, line, column, column + len(argument))
        requested = argument.strip()
        extensions = (".svg",) if command == "includesvg" else _IMAGE_EXTENSIONS
        resolved = next(
            (candidate for directory in graphics_dirs
             if (candidate := _resolve_candidates(directory, requested, extensions)) is not None),
            None,
        )
        assets.append(LatexInclude(requested, command, location, resolved))
    return includes, assets


def _bib_keys(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return set(_BIB_ENTRY_RE.findall(strip_latex_comments(text)))


def analyze_latex_project(
    current_file: str | Path | None,
    content: str | None = None,
    *,
    max_depth: int = 5,
) -> LatexReferencesAnalysis:
    """Scan the resolved project containing ``current_file``.

    ``content`` replaces the on-disk text for ``current_file`` and is useful
    for unsaved editor state. The function performs no UI or network work.
    """
    root, sources = _source_texts(current_file, content, max_depth)
    definitions: list[LatexReference] = []
    references: list[LatexReference] = []
    citations: list[LatexReference] = []
    includes: list[LatexInclude] = []
    assets: list[LatexInclude] = []
    bibliography_files: set[Path] = set()

    for path, text in sources:
        for occurrence in LaTeXSupport.extract_label_reference_occurrences(text):
            location = LatexLocation(
                path, occurrence["line"] + 1, occurrence["column"],
                occurrence["column"] + len(occurrence["key"]),
            )
            item = LatexReference(
                occurrence["key"], location, occurrence["kind"],
                _command_name(text, occurrence["command_start"]),
            )
            (definitions if item.kind == "label" else references).append(item)

        for occurrence in extract_latex_citation_occurrences(text):
            if occurrence["key"] == "*":  # ``\nocite{*}`` is not a key.
                continue
            location = LatexLocation(
                path, occurrence["line"] + 1, occurrence["column"],
                occurrence["column"] + len(occurrence["key"]),
            )
            citations.append(LatexReference(
                occurrence["key"], location, "citation",
                _command_name(text, occurrence["command_start"]),
            ))
        file_includes, file_assets = _parse_include_entries(path, text)
        includes.extend(file_includes)
        assets.extend(file_assets)
        bibliography_files.update(
            entry.resolved for entry in file_includes
            if entry.kind in _BIB_COMMANDS and entry.resolved is not None
        )

    definitions_by_key: dict[str, list[LatexReference]] = {}
    for item in definitions:
        definitions_by_key.setdefault(item.key, []).append(item)
    defined = set(definitions_by_key)
    referenced = {item.key for item in references}
    duplicates = [item for values in definitions_by_key.values() for item in values[1:]]
    unused = [values[0] for key, values in definitions_by_key.items() if key not in referenced]
    undefined = [item for item in references if item.key not in defined]

    bibliography_keys = set().union(*(_bib_keys(path) for path in bibliography_files)) if bibliography_files else set()
    # ``\\bibitem`` is valid in a source file and supplies data without a .bib.
    for _path, text in sources:
        bibliography_keys.update(_BIBITEM_RE.findall(strip_latex_comments(text)))
    undefined_citations = [item for item in citations if bibliography_keys and item.key not in bibliography_keys]
    cited_keys = {item.key for item in citations}
    unused_citations = tuple(sorted(bibliography_keys - cited_keys)) if bibliography_keys else ()

    return LatexReferencesAnalysis(
        root, tuple(path for path, _ in sources), tuple(definitions), tuple(references),
        tuple(citations), tuple(undefined), tuple(undefined_citations),
        tuple(duplicates), tuple(unused), tuple(includes), tuple(assets),
        tuple(item for item in includes if item.missing),
        tuple(item for item in assets if item.missing),
        tuple(sorted(bibliography_files)), tuple(sorted(bibliography_keys)),
        unused_citations,
    )


# Short aliases are useful to non-UI callers and keep the public entry point
# independent from the implementation's historical project terminology.
scan_latex_project = analyze_latex_project
analyze_project = analyze_latex_project


__all__ = [
    "LatexInclude", "LatexLocation", "LatexReference", "LatexReferencesAnalysis",
    "analyze_latex_project", "analyze_project", "scan_latex_project",
]

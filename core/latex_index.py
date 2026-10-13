"""Shared, revision-aware LaTeX analysis for editor services.

The checker, completion worker and Function List used to scan the same source
tree independently.  On a large document that meant several full comment
strips, regular-expression passes and project walks for one edit.  This module
builds one immutable analysis snapshot and shares it between those consumers.

The index is intentionally Qt-free.  It can therefore be built in a worker
thread and safely reused by the GUI only after the worker has emitted it.
"""

from __future__ import annotations

import re
import threading
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.latex_parser import label_reference_tokens, mask_latex_comments, strip_latex_comments
from core.latex_project import (
    collect_included_files,
    read_cached_text,
    resolve_project_root,
)


_BEGIN_END_RE = re.compile(r"\\(begin|end)\{([^}]+)\}")
_SECTION_RE = re.compile(
    r"\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)"
    r"\*?(?:\[([^]]*)\])?\{([^}]*)\}"
)
_PACKAGE_RE = re.compile(
    r"\\(?:usepackage|RequirePackage|documentclass)"
    r"(?:\[[^]]*\])?\s*\{([^}]+)\}"
)
_CUSTOM_COMMAND_RE = re.compile(
    r"\\(?:new|renew|provide)command\*?\s*"
    r"(?:\{(?P<braced>\\[A-Za-z@]+)\}|(?P<plain>\\[A-Za-z@]+))\s*"
    r"(?:\[(?P<arguments>\d+)\])?"
    r"(?:\[(?P<default>[^]]*)\])?"
)
_OTHER_CUSTOM_COMMAND_RE = re.compile(
    r"\\(?:DeclareMathOperator|def|let)\*?\s*"
    r"(?:\{(?P<braced>\\[A-Za-z@]+)\}|(?P<plain>\\[A-Za-z@]+))"
)
_CUSTOM_ENV_RE = re.compile(r"\\(?:new|renew)environment\*?\{([^}]+)\}")
_HYPERTARGET_RE = re.compile(r"\\hypertarget\{([^}]+)\}")
_CITATION_RE = re.compile(
    r"\\(?:cite[A-Za-z]*|parencite|footcite|textcite|autocite)"
    r"\{([^}]+)\}"
)
_BIB_REFERENCE_RE = re.compile(
    r"\\(?:bibliography|addbibresource)\s*(?:\[[^]]*\])?\s*\{([^}]+)\}"
)
_BIB_ENTRY_RE = re.compile(r"@[A-Za-z][\w-]*\s*[({]\s*([^,\s]+)\s*,")
_WORD_RE = re.compile(r"(?u)[\w\\]{2,}")

_SECTION_LEVELS = {
    "part": 1,
    "chapter": 2,
    "section": 3,
    "subsection": 4,
    "subsubsection": 5,
    "paragraph": 6,
    "subparagraph": 7,
}
_SECTION_TYPES = {
    "part": "parte",
    "chapter": "capitolo",
    "section": "sezione",
    "subsection": "sottosezione",
    "subsubsection": "sottosottosezione",
    "paragraph": "paragrafo",
    "subparagraph": "sottoparagrafo",
}
_SECTION_ICONS = {
    "part": "📚",
    "chapter": "📖",
    "section": "§",
    "subsection": "§",
    "subsubsection": "§",
    "paragraph": "§",
    "subparagraph": "§",
}


@dataclass(frozen=True)
class IndexedSource:
    path: Path | None
    text: str
    code: str
    line_starts: tuple[int, ...]

    def line_for_offset(self, offset: int) -> int:
        return bisect_right(self.line_starts, max(0, offset)) - 1


class LatexIndex:
    """Immutable analysis snapshot shared by LaTeX editor services."""

    def __init__(self, sources: list[IndexedSource], current_path: Path | None):
        self.sources = tuple(sources)
        self.current_path = current_path
        self._by_path = {source.path: source for source in sources if source.path is not None}

        self.definitions: list[dict] = []
        self.references: list[dict] = []
        self.sections: list[dict] = []
        self.packages: set[str] = set()
        self.custom_environments: set[str] = set()
        self.custom_commands: list[str] = []
        self.custom_command_completions: list[str] = []
        self.custom_declarations: list[dict] = []
        self.hypertargets: set[str] = set()
        self.citation_references: set[str] = set()
        self.bibtex_keys: set[str] = set()
        self.balance_issues: list[dict] = []
        self.document_words: list[str] = []
        self.current_document_words: list[str] = []

        self._build()
        # Freeze the published collections.  A worker may still hold an older
        # snapshot while a newer revision is being built, so consumers must
        # never observe partially updated lists or sets.
        for name in (
                "sources", "definitions", "references", "sections",
                "custom_declarations", "balance_issues", "document_words",
                "current_document_words", "custom_command_completions",
                "label_contexts", "duplicates", "unused", "undefined"):
            setattr(self, name, tuple(getattr(self, name)))
        for name in (
                "packages", "custom_environments", "hypertargets",
                "citation_references", "bibtex_keys", "labels"):
            setattr(self, name, frozenset(getattr(self, name)))

    def _build(self) -> None:
        command_completions: set[str] = set()
        words: set[str] = set()
        for source in self.sources:
            tokens = label_reference_tokens(source.code)
            for token in tokens:
                item = dict(token)
                item["line"] = source.line_for_offset(int(token["command_start"]))
                if source.path is not None:
                    item["file"] = source.path
                if token["kind"] == "label":
                    self.definitions.append(item)
                else:
                    self.references.append(item)

            self._scan_sections(source)
            self.packages.update(
                package.strip()
                for match in _PACKAGE_RE.finditer(source.code)
                for package in match.group(1).split(",")
                if package.strip()
            )
            self.custom_environments.update(
                match.group(1).strip()
                for match in _CUSTOM_ENV_RE.finditer(source.code)
                if match.group(1).strip()
            )
            self.hypertargets.update(_HYPERTARGET_RE.findall(source.code))
            self.citation_references.update(
                key.strip()
                for match in _CITATION_RE.finditer(source.code)
                for key in match.group(1).split(",")
                if key.strip()
            )
            self._scan_custom_commands(source, command_completions)
            self._scan_balance(source)
            if source.path is None or source.path.suffix.lower() != ".bib":
                source_words = {match.group(0) for match in _WORD_RE.finditer(source.code)}
                words.update(source_words)
                if source.path == self.current_path or (
                        self.current_path is None and source.path is None):
                    self.current_document_words = sorted(source_words, key=str.casefold)
                # Keep compatibility with the existing helper, which also
                # accepts inline BibTeX entries in a non-.bib snapshot.
                self.bibtex_keys.update(_BIB_ENTRY_RE.findall(source.code))
            else:
                self.bibtex_keys.update(_BIB_ENTRY_RE.findall(source.code))

        self._scan_referenced_bibliographies()
        self.custom_commands = sorted({
            command for command in command_completions
        })
        self.custom_command_completions = sorted(command_completions)
        self.document_words = sorted(words, key=str.casefold)

        by_key: dict[str, list[dict]] = {}
        for definition in self.definitions:
            by_key.setdefault(str(definition["key"]), []).append(definition)
        defined = set(by_key)
        referenced = {str(item["key"]) for item in self.references}
        self.duplicates = [item for values in by_key.values() for item in values[1:]]
        self.unused = [values[0] for key, values in by_key.items() if key not in referenced]
        self.undefined = [item for item in self.references if item["key"] not in defined]
        self.labels = defined
        self.label_contexts = self._label_contexts()

    def _scan_sections(self, source: IndexedSource) -> None:
        for line_number, line in enumerate(source.code.splitlines()):
            for match in _SECTION_RE.finditer(line):
                kind = match.group(1)
                self.sections.append({
                    "kind": kind,
                    "name": match.group(2) if match.group(2) is not None else match.group(3),
                    "line": line_number,
                    "level": _SECTION_LEVELS[kind],
                    "signature": line.strip()[:80],
                    "icon": _SECTION_ICONS[kind],
                    "file": source.path,
                })

    def _scan_custom_commands(self, source: IndexedSource,
                              completions: set[str]) -> None:
        for match in _CUSTOM_COMMAND_RE.finditer(source.code):
            command = match.group("braced") or match.group("plain")
            if not command:
                continue
            self.custom_declarations.append({
                "name": command, "kind": "command", "line": source.line_for_offset(match.start()),
                "file": source.path, "signature": source.text.splitlines()[
                    source.line_for_offset(match.start())].strip()[:80]
                if source.text.splitlines() else "",
            })
            arguments = match.group("arguments")
            if arguments is None:
                completions.add(command)
                continue
            count = int(arguments)
            suffix = "[]" if match.group("default") is not None else ""
            suffix += "{}" * (count - int(match.group("default") is not None))
            completions.add(f"{command}{suffix}?1")
        for match in _OTHER_CUSTOM_COMMAND_RE.finditer(source.code):
            command = match.group("braced") or match.group("plain")
            if command:
                completions.add(command)
                self.custom_declarations.append({
                    "name": command, "kind": "command", "line": source.line_for_offset(match.start()),
                    "file": source.path, "signature": source.text.splitlines()[
                        source.line_for_offset(match.start())].strip()[:80]
                    if source.text.splitlines() else "",
                })
        for match in _CUSTOM_ENV_RE.finditer(source.code):
            self.custom_declarations.append({
                "name": match.group(1), "kind": "environment",
                "line": source.line_for_offset(match.start()), "file": source.path,
                "signature": source.text.splitlines()[source.line_for_offset(match.start())].strip()[:80]
                if source.text.splitlines() else "",
            })

    def _scan_balance(self, source: IndexedSource) -> None:
        stack: list[tuple[str, int]] = []
        for match in _BEGIN_END_RE.finditer(source.code):
            kind, environment = match.groups()
            line = source.line_for_offset(match.start())
            if kind == "begin":
                stack.append((environment, line))
                continue
            if not stack:
                issue = {
                    "line": line,
                    "env": environment,
                    "severity": "error",
                    "msg": f"\\end{{{environment}}} without matching \\begin",
                }
            else:
                top_environment, top_line = stack[-1]
                if top_environment == environment:
                    stack.pop()
                    continue
                issue = {
                    "line": line,
                    "env": environment,
                    "severity": "error",
                    "msg": (
                        f"Mismatched environment: \\end{{{environment}}} "
                        f"closes \\begin{{{top_environment}}}"
                    ),
                }
            if source.path is not None:
                issue["file"] = source.path
            self.balance_issues.append(issue)
        for environment, line in reversed(stack):
            issue = {
                "line": line,
                "env": environment,
                "severity": "error",
                "msg": f"\\begin{{{environment}}} without matching \\end",
            }
            if source.path is not None:
                issue["file"] = source.path
            self.balance_issues.append(issue)

    def _scan_referenced_bibliographies(self) -> None:
        for source in self.sources:
            if source.path is None:
                continue
            base = source.path.parent
            for match in _BIB_REFERENCE_RE.finditer(source.code):
                for raw_name in match.group(1).split(","):
                    name = raw_name.strip()
                    if not name:
                        continue
                    candidate = base / name
                    candidates = [candidate]
                    if candidate.suffix.lower() != ".bib":
                        candidates.extend((candidate.with_suffix(candidate.suffix + ".bib"),
                                           candidate.with_suffix(".bib")))
                    for bib_path in candidates:
                        if not bib_path.is_file():
                            continue
                        try:
                            self.bibtex_keys.update(
                                _BIB_ENTRY_RE.findall(read_cached_text(bib_path))
                            )
                        except OSError:
                            pass
                        break

    def _label_contexts(self) -> list[tuple[str, str]]:
        prefix_types = {
            "fig": "figura", "figure": "figura",
            "tab": "tabella", "tbl": "tabella", "table": "tabella",
            "eq": "equazione", "eqn": "equazione",
            "sec": "sezione", "sect": "sezione", "section": "sezione",
            "sub": "sottosezione", "subsec": "sottosezione",
            "ch": "capitolo", "chap": "capitolo",
            "alg": "algoritmo", "algo": "algoritmo",
            "lst": "codice", "listing": "codice", "code": "codice",
            "thm": "teorema", "theorem": "teorema", "lem": "lemma",
            "prop": "proposizione", "cor": "corollario",
            "def": "definizione", "app": "appendice",
        }
        environment_types = {
            "figure": "figura", "figure*": "figura", "subfigure": "figura",
            "table": "tabella", "table*": "tabella",
            "equation": "equazione", "equation*": "equazione",
            "align": "equazione", "align*": "equazione",
            "gather": "equazione", "gather*": "equazione",
            "eqnarray": "equazione", "eqnarray*": "equazione",
            "multline": "equazione", "multline*": "equazione",
            "flalign": "equazione", "flalign*": "equazione",
            "algorithm": "algoritmo", "algorithm2e": "algoritmo",
            "lstlisting": "codice", "verbatim": "codice", "minted": "codice",
            "theorem": "teorema", "thm": "teorema", "lemma": "lemma",
            "lem": "lemma", "proposition": "proposizione",
            "corollary": "corollario", "definition": "definizione",
            "defn": "definizione", "proof": "dimostrazione", "frame": "slide",
        }
        seen: set[str] = set()
        result: list[tuple[str, str]] = []
        section_re = re.compile(
            r"\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)"
        )
        env_re = re.compile(r"\\begin\{([^}]+)\}")
        source_by_path = {source.path: source for source in self.sources}
        for definition in self.definitions:
            key = str(definition["key"])
            if key in seen:
                continue
            seen.add(key)
            prefix = key.split(":", 1)[0].casefold() if ":" in key else ""
            if prefix in prefix_types:
                result.append((key, prefix_types[prefix]))
                continue
            source = source_by_path.get(definition.get("file"))
            if source is None:
                source = next((item for item in self.sources if item.path is None), None)
            context = ""
            if source is not None:
                start = int(definition.get("command_start", 0))
                # Match the historical helper exactly: comment stripping is
                # applied to the local context, not to the complete source
                # followed by slicing (a comment may begin before the window).
                context = strip_latex_comments(source.text[max(0, start - 600):start])
            section_matches = list(section_re.finditer(context))
            env_matches = list(env_re.finditer(context))
            if section_matches and (
                    not env_matches or section_matches[-1].start() >= env_matches[-1].start()):
                result.append((key, _SECTION_TYPES.get(section_matches[-1].group(1), "sezione")))
            elif env_matches:
                env_name = env_matches[-1].group(1).casefold()
                result.append((key, environment_types.get(env_name, "label")))
            else:
                result.append((key, "label"))
        return sorted(result, key=lambda item: item[0])

    def source_for(self, path: Path | None) -> IndexedSource | None:
        if path is None:
            return next((source for source in self.sources if source.path is None), None)
        return self._by_path.get(path.resolve())


_CACHE_LOCK = threading.Lock()
_INDEX_BUILD_LOCK = threading.Lock()
_INDEX_CACHE: dict[tuple, LatexIndex] = {}
_INDEX_CACHE_ORDER: list[tuple] = []
_PROJECT_PATH_CACHE: dict[Path, tuple[Path, tuple[str, ...], tuple[Path, ...], tuple[tuple, ...]]] = {}
_MAX_INDEX_CACHE = 8
_INCLUDE_HINT_RE = re.compile(
    r"\\(?:input|include|subfile|import|subimport|includefrom|subinputfrom)"
    r"\s*(?:\{[^}]*\}|\[[^]]*\])?\s*(?:\{[^}]*\})?"
)


def _line_starts(text: str) -> tuple[int, ...]:
    starts = [0]
    starts.extend(index + 1 for index, char in enumerate(text) if char == "\n")
    return tuple(starts)


def _source_paths(current: Path, content: str | None = None) -> list[Path]:
    current = current.resolve()
    include_signature = tuple(_INCLUDE_HINT_RE.findall(content or ""))

    # Root discovery itself may require comment stripping of a multi-megabyte
    # document.  If the include directives and all previously discovered files
    # are unchanged, skip that work entirely.
    with _CACHE_LOCK:
        cached = _PROJECT_PATH_CACHE.get(current)
    if cached is not None:
        cached_root, cached_includes, cached_paths, cached_signatures = cached
        if cached_includes == include_signature:
            signatures = tuple(_file_signature(path) for path in cached_paths)
            if signatures == cached_signatures:
                return list(cached_paths)

    try:
        root = resolve_project_root(current, content)
    except (OSError, RuntimeError, ValueError):
        root = current

    with _CACHE_LOCK:
        cached = _PROJECT_PATH_CACHE.get(current)
    if cached is not None:
        cached_root, cached_includes, cached_paths, cached_signatures = cached
        if cached_root == root and cached_includes == include_signature:
            signatures = tuple(_file_signature(path) for path in cached_paths)
            if signatures == cached_signatures:
                return list(cached_paths)

    paths = collect_included_files(root)
    paths = paths or [current]
    signatures = tuple(_file_signature(path) for path in paths)
    with _CACHE_LOCK:
        _PROJECT_PATH_CACHE[current] = (
            root, include_signature, tuple(paths), signatures
        )
    return paths


def _file_signature(path: Path) -> tuple:
    try:
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size, getattr(stat, "st_ino", 0))
    except OSError:
        return (None,)


def get_latex_index(text: str, tex_path: Optional[Path] = None,
                    include_project: bool = True) -> LatexIndex:
    """Return a cached immutable index for the current document/project."""
    current = Path(tex_path).resolve() if tex_path else None
    paths = _source_paths(current, text) if current and include_project else []
    if current and current not in paths:
        paths.insert(0, current)
    if not paths:
        paths = [current] if current else []

    signatures = []
    for path in paths:
        try:
            stat = path.stat()
            signatures.append((path, stat.st_mtime_ns, stat.st_size, getattr(stat, "st_ino", 0)))
        except OSError:
            signatures.append((path, None))
    key = (current, include_project, hash(text), len(text), tuple(signatures))
    with _CACHE_LOCK:
        cached = _INDEX_CACHE.get(key)
        if cached is not None:
            if key in _INDEX_CACHE_ORDER:
                _INDEX_CACHE_ORDER.remove(key)
            _INDEX_CACHE_ORDER.append(key)
            return cached

    # Several debounced services can wake up close together.  Serialize only
    # cache misses so two workers never parse the same large revision twice.
    with _INDEX_BUILD_LOCK:
        with _CACHE_LOCK:
            cached = _INDEX_CACHE.get(key)
            if cached is not None:
                if key in _INDEX_CACHE_ORDER:
                    _INDEX_CACHE_ORDER.remove(key)
                _INDEX_CACHE_ORDER.append(key)
                return cached

        sources: list[IndexedSource] = []
        for path in paths:
            try:
                source_text = text if current is not None and path == current else read_cached_text(path)
            except OSError:
                continue
            source = IndexedSource(
                path=path,
                text=source_text,
                # Masking removes comments semantically while preserving offsets;
                # label/reference positions must still map to the editor buffer.
                code=mask_latex_comments(source_text),
                line_starts=_line_starts(source_text),
            )
            sources.append(source)
        if not sources and text:
            sources.append(IndexedSource(
                None, text, mask_latex_comments(text), _line_starts(text)
            ))

        index = LatexIndex(sources, current)
        with _CACHE_LOCK:
            _INDEX_CACHE[key] = index
            if key in _INDEX_CACHE_ORDER:
                _INDEX_CACHE_ORDER.remove(key)
            _INDEX_CACHE_ORDER.append(key)
            while len(_INDEX_CACHE_ORDER) > _MAX_INDEX_CACHE:
                old = _INDEX_CACHE_ORDER.pop(0)
                _INDEX_CACHE.pop(old, None)
        return index


def invalidate_latex_index(path: Path | None = None) -> None:
    """Drop cached indexes affected by a changed file."""
    if path is None:
        with _CACHE_LOCK:
            _INDEX_CACHE.clear()
            _INDEX_CACHE_ORDER.clear()
            _PROJECT_PATH_CACHE.clear()
        return
    resolved = Path(path).resolve()
    with _CACHE_LOCK:
        _PROJECT_PATH_CACHE.pop(resolved, None)
        for key in list(_INDEX_CACHE_ORDER):
            index = _INDEX_CACHE.get(key)
            if index is not None and any(source.path == resolved for source in index.sources):
                _INDEX_CACHE.pop(key, None)
                _INDEX_CACHE_ORDER.remove(key)


__all__ = ["IndexedSource", "LatexIndex", "get_latex_index", "invalidate_latex_index"]

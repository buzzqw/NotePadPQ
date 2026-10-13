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

from core.latex_checks import environment_balance, format_balance_issue
from core.latex_parser import label_reference_tokens, mask_latex_comments, strip_latex_comments
from core.latex_project import (
    collect_included_files,
    read_cached_text,
    resolve_project_root,
)
from core.latex_tokenizer import scan_bib_entries, scan_citation_keys, scan_document


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

    def line_text(self, line: int) -> str:
        """Testo di una riga (0-based) senza spezzare tutto il documento."""
        starts = self.line_starts
        if line < 0 or line >= len(starts):
            return ""
        start = starts[line]
        end = starts[line + 1] if line + 1 < len(starts) else len(self.text)
        return self.text[start:end].rstrip("\n").rstrip("\r")


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
        # Calcolato su richiesta: nessun consumatore attuale legge balance_issues
        # durante il build (il checker riscansiona per conto proprio).
        self._balance_issues: tuple[dict, ...] | None = None
        # Le parole del documento sono calcolate su richiesta (servono solo
        # all'autocomplete): vedi le property document_words/current_document_words.
        self._all_words: tuple[str, ...] | None = None
        self._current_words: tuple[str, ...] | None = None

        self._build()
        # Freeze the published collections.  A worker may still hold an older
        # snapshot while a newer revision is being built, so consumers must
        # never observe partially updated lists or sets.
        for name in (
                "sources", "definitions", "references", "sections",
                "custom_declarations", "custom_command_completions",
                "label_contexts", "duplicates", "unused", "undefined"):
            setattr(self, name, tuple(getattr(self, name)))
        for name in (
                "packages", "custom_environments", "hypertargets",
                "citation_references", "bibtex_keys", "labels"):
            setattr(self, name, frozenset(getattr(self, name)))

    def _build(self) -> None:
        command_completions: set[str] = set()
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

            spans = scan_document(source.code)
            self._scan_sections(source, spans)
            self.packages.update(spans.packages)
            self.custom_environments.update(
                environment.name for environment in spans.custom_environments)
            self.hypertargets.update(spans.hypertargets)
            self.citation_references.update(scan_citation_keys(source.code))
            self._scan_custom_commands(source, spans, command_completions)
            # Le chiavi BibTeX servono sempre; le parole del documento invece
            # sono rimandate (vedi _compute_words): su un documento da 3 MB la
            # scansione di ogni parola costava centinaia di migliaia di .group().
            self.bibtex_keys.update(scan_bib_entries(source.code))
            if spans.bibliography_references:
                self._scan_referenced_bibliographies(
                    source, spans.bibliography_references)

        self.custom_commands = sorted(command_completions)
        self.custom_command_completions = sorted(command_completions)

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

    def _compute_words(self) -> None:
        """Calcola (una sola volta, su richiesta) le parole del documento."""
        words: set[str] = set()
        current: list[str] | None = None
        for source in self.sources:
            if source.path is not None and source.path.suffix.lower() == ".bib":
                continue
            source_words = {match.group(0) for match in _WORD_RE.finditer(source.code)}
            words.update(source_words)
            if source.path == self.current_path or (
                    self.current_path is None and source.path is None):
                current = sorted(source_words, key=str.casefold)
        self._all_words = tuple(sorted(words, key=str.casefold))
        self._current_words = tuple(current) if current is not None else ()

    @property
    def document_words(self) -> tuple[str, ...]:
        if self._all_words is None:
            self._compute_words()
        return self._all_words

    @property
    def current_document_words(self) -> tuple[str, ...]:
        if self._current_words is None:
            self._compute_words()
        return self._current_words

    def _scan_sections(self, source: IndexedSource, spans) -> None:
        for section in spans.sections:
            line_number = source.line_for_offset(section.offset)
            self.sections.append({
                "kind": section.kind,
                "name": section.name,
                "line": line_number,
                "level": _SECTION_LEVELS[section.kind],
                "signature": source.line_text(line_number).strip()[:80],
                "icon": _SECTION_ICONS[section.kind],
                "file": source.path,
            })

    def _scan_custom_commands(self, source: IndexedSource, spans,
                              completions: set[str]) -> None:
        for definition in spans.custom_commands:
            command = definition.name
            line = source.line_for_offset(definition.offset)
            self.custom_declarations.append({
                "name": command, "kind": "command", "line": line,
                "file": source.path,
                "signature": source.line_text(line).strip()[:80],
            })
            if definition.arguments is None:
                completions.add(command)
                continue
            suffix = "[]" if definition.has_default else ""
            suffix += "{}" * (definition.arguments - int(definition.has_default))
            completions.add(f"{command}{suffix}?1")
        for environment in spans.custom_environments:
            line = source.line_for_offset(environment.offset)
            self.custom_declarations.append({
                "name": environment.name, "kind": "environment",
                "line": line, "file": source.path,
                "signature": source.line_text(line).strip()[:80],
            })

    def _compute_balance(self) -> list[dict]:
        """Balance problems from the shared, Qt-free checker."""
        issues: list[dict] = []
        for source in self.sources:
            for balance in environment_balance(source.code):
                open_line = (
                    source.line_for_offset(balance.open_offset)
                    if balance.open_offset is not None else None
                )
                issue = format_balance_issue(
                    balance, source.line_for_offset(balance.offset), open_line,
                )
                if source.path is not None:
                    issue["file"] = source.path
                issues.append(issue)
        return issues

    @property
    def balance_issues(self) -> tuple[dict, ...]:
        if self._balance_issues is None:
            self._balance_issues = tuple(self._compute_balance())
        return self._balance_issues

    def _scan_referenced_bibliographies(self, source: IndexedSource,
                                        references) -> None:
        if source.path is None:
            return
        base = source.path.parent
        for name in references:
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
                        scan_bib_entries(read_cached_text(bib_path))
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


_MAX_INDEX_CACHE = 8


class LatexAnalysisCache:
    """Revision-keyed analysis cache shared by the debounced LaTeX services.

    Holds the immutable :class:`LatexIndex` snapshots (an LRU) and the resolved
    project-source lists, replacing the module globals that used to carry the
    same state.
    """

    def __init__(self, max_indexes: int = _MAX_INDEX_CACHE) -> None:
        self._lock = threading.Lock()
        self._build_lock = threading.Lock()
        self._max_indexes = max_indexes
        self._indexes: dict[tuple, LatexIndex] = {}
        self._order: list[tuple] = []
        self._project_paths: dict[Path, tuple] = {}

    def get_index(self, key: tuple) -> LatexIndex | None:
        with self._lock:
            cached = self._indexes.get(key)
            if cached is None:
                return None
            if key in self._order:
                self._order.remove(key)
            self._order.append(key)
            return cached

    def put_index(self, key: tuple, index: LatexIndex) -> None:
        with self._lock:
            self._indexes[key] = index
            if key in self._order:
                self._order.remove(key)
            self._order.append(key)
            while len(self._order) > self._max_indexes:
                self._indexes.pop(self._order.pop(0), None)

    def get_paths(self, current: Path):
        with self._lock:
            return self._project_paths.get(current)

    def put_paths(self, current: Path, value: tuple) -> None:
        with self._lock:
            self._project_paths[current] = value

    @property
    def build_lock(self) -> threading.Lock:
        return self._build_lock

    def invalidate(self, path: Path | None = None) -> None:
        with self._lock:
            if path is None:
                self._indexes.clear()
                self._order.clear()
                self._project_paths.clear()
                return
            resolved = Path(path).resolve()
            self._project_paths.pop(resolved, None)
            for key in list(self._order):
                index = self._indexes.get(key)
                if index is not None and any(
                        source.path == resolved for source in index.sources):
                    self._indexes.pop(key, None)
                    self._order.remove(key)

    def clear(self) -> None:
        self.invalidate(None)


_DEFAULT_ANALYSIS_CACHE = LatexAnalysisCache()
_INCLUDE_HINT_RE = re.compile(
    r"\\(?:input|include|subfile|import|subimport|includefrom|subinputfrom)"
    r"\s*(?:\{[^}]*\}|\[[^]]*\])?\s*(?:\{[^}]*\})?"
)


def _line_starts(text: str) -> tuple[int, ...]:
    # Posizioni di inizio riga tramite str.find, senza scandire ogni carattere
    # in Python (un generatore su milioni di caratteri costava ~150 ms/3 MB).
    starts = [0]
    index = text.find("\n")
    while index >= 0:
        starts.append(index + 1)
        index = text.find("\n", index + 1)
    return tuple(starts)


def _source_paths(current: Path, content: str | None = None) -> list[Path]:
    current = current.resolve()
    include_signature = tuple(_INCLUDE_HINT_RE.findall(content or ""))

    # Root discovery itself may require comment stripping of a multi-megabyte
    # document.  If the include directives and all previously discovered files
    # are unchanged, skip that work entirely.
    cached = _DEFAULT_ANALYSIS_CACHE.get_paths(current)
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

    cached = _DEFAULT_ANALYSIS_CACHE.get_paths(current)
    if cached is not None:
        cached_root, cached_includes, cached_paths, cached_signatures = cached
        if cached_root == root and cached_includes == include_signature:
            signatures = tuple(_file_signature(path) for path in cached_paths)
            if signatures == cached_signatures:
                return list(cached_paths)

    paths = collect_included_files(root)
    paths = paths or [current]
    signatures = tuple(_file_signature(path) for path in paths)
    _DEFAULT_ANALYSIS_CACHE.put_paths(
        current, (root, include_signature, tuple(paths), signatures))
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
    cached = _DEFAULT_ANALYSIS_CACHE.get_index(key)
    if cached is not None:
        return cached

    # Several debounced services can wake up close together.  Serialize only
    # cache misses so two workers never parse the same large revision twice.
    with _DEFAULT_ANALYSIS_CACHE.build_lock:
        cached = _DEFAULT_ANALYSIS_CACHE.get_index(key)
        if cached is not None:
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
        _DEFAULT_ANALYSIS_CACHE.put_index(key, index)
        return index


def invalidate_latex_index(path: Path | None = None) -> None:
    """Drop cached indexes affected by a changed file."""
    _DEFAULT_ANALYSIS_CACHE.invalidate(path)


__all__ = ["IndexedSource", "LatexAnalysisCache", "LatexIndex",
           "get_latex_index", "invalidate_latex_index"]

"""
editor/latex_checker.py — Controllo sintattico LaTeX in tempo reale
NotePadPQ

Rileva in background:
  - Ambienti \\begin{}/\\end{} sbilanciati
  - Riferimenti \\ref{} a label non definite
  - Citazioni \\cite{} a chiavi non trovate

Segnala gli errori tramite marcatori nel margine (gutter) e una lista
accessibile dalla MainWindow.

Uso:
    checker = LaTeXChecker(editor)
    checker.start()
    checker.check_requested.connect(my_slot)   # slot(list[dict])
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.Qsci import QsciScintilla
from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor

from core.diagnostics import profile_operation
from core.latex_checks import (
    count_row_cols,
    count_tabular_cols,
    environment_balance,
    format_balance_issue,
    tabular_column_issues,
    tikz_semicolon_issues,
)
from core.latex_citations import extract_latex_citation_occurrences
from core.latex_index import get_latex_index
from core.latex_parser import strip_latex_comments

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

# Numero del marcatore gutter usato da questo checker (1-31, evita conflitti)
_MARKER_ERROR   = 22
_MARKER_WARNING = 23

# Simbolo nel margine: cerchio rosso per errori, triangolo giallo per warning
_MARKER_ERROR_SYM   = QsciScintilla.MarkerSymbol.Circle
_MARKER_WARNING_SYM = QsciScintilla.MarkerSymbol.RightTriangle

# Full-project checks are too expensive to repeat after every pause while
# editing a large source. They are still run on initial load and on demand.
_LIVE_CHECK_MAX_BYTES = 1 * 1024 * 1024


class _CheckWorker(QThread):
    """Esegue i tre controlli LaTeX in un thread separato per non bloccare la UI."""

    done = pyqtSignal(int, list)   # (generation, list[dict])

    def __init__(self, text: str, file_path, generation: int, include_project: bool = True):
        super().__init__(None)
        self._text       = text
        self._file_path  = file_path
        self._generation = generation
        self._include_project = include_project
        self._cancelled  = False
        self._sources = None
        self._label_analysis = None
        self._index = None

    def cancel(self) -> None:
        self._cancelled = True

    @profile_operation("latex.check")
    def run(self) -> None:
        issues: list[dict] = []
        if self._cancelled:
            return
        # One immutable snapshot is shared by all checks in this worker.  The
        # cache also lets autocomplete and Function List reuse it when their
        # debounced workers analyze the same revision.
        try:
            self._index = get_latex_index(
                self._text, self._file_path, self._include_project
            )
        except Exception:
            # Keep the established Python fallbacks available if an unusual
            # project/file cannot be indexed.
            self._index = None
        issues.extend(self._check_balance())
        if self._cancelled:
            return
        issues.extend(self._check_undefined_labels())
        if self._cancelled:
            return
        issues.extend(self._check_label_consistency())
        if self._cancelled:
            return
        issues.extend(self._check_undefined_citations())
        if self._cancelled:
            return
        issues.extend(self._check_tabular_columns())
        if self._cancelled:
            return
        issues.extend(self._check_tikz_semicolons())
        if not self._cancelled:
            self.done.emit(self._generation, issues)

    def _project_sources(self):
        """Restituisce i sorgenti del progetto con il testo corrente in memoria."""
        if self._sources is not None:
            return self._sources
        if self._index is not None:
            self._sources = [(source.path, source.text) for source in self._index.sources]
            return self._sources
        if not self._file_path or not self._include_project:
            self._sources = [(None, self._text)]
            return self._sources
        from editor.latex_support import LaTeXSupport, _cached_read_text
        current = Path(self._file_path).resolve()
        sources = []
        for path in LaTeXSupport.collect_project_files(current):
            try:
                source_text = (self._text if path.resolve() == current
                               else _cached_read_text(path))
            except OSError:
                continue
            sources.append((path, source_text))
        self._sources = sources or [(current, self._text)]
        return self._sources

    def _check_balance(self) -> list[dict]:
        # The shared index owns the balance snapshot; the fallback path scans
        # only when an unusual project could not be indexed.
        if self._index is not None:
            return [dict(issue) for issue in self._index.balance_issues]
        issues = []
        for path, source in self._project_sources():
            code = strip_latex_comments(source)
            for balance in environment_balance(code):
                open_line = (
                    code.count("\n", 0, balance.open_offset)
                    if balance.open_offset is not None else None
                )
                issue = format_balance_issue(
                    balance, code.count("\n", 0, balance.offset), open_line)
                if path is not None:
                    issue["file"] = path
                issues.append(issue)
        return issues

    def _check_undefined_labels(self) -> list[dict]:
        from editor.latex_support import LaTeXSupport
        analysis = self._get_label_analysis()
        defined = {item["key"] for item in analysis["definitions"]}
        if self._index is None:
            defined.update(LaTeXSupport.extract_labels(self._text))

        issues: list[dict] = []
        if self._index is not None:
            current_path = self._index.current_path
            occurrences = [
                item for item in self._index.references
                if item.get("file") == current_path
                or (current_path is None and item.get("file") is None)
            ]
        else:
            occurrences = LaTeXSupport.extract_label_reference_occurrences(self._text)
        for occurrence in occurrences:
            if self._cancelled:
                return []
            if occurrence["kind"] != "reference":
                continue
            key = occurrence["key"]
            if key and key not in defined:
                issues.append({
                    "line":     occurrence["line"],
                    "severity": "warning",
                    "msg":      f"Undefined label: '{key}'",
                })
        return issues

    def _check_label_consistency(self) -> list[dict]:
        """Check duplicate definitions and labels never referenced.

        Cross-file issues retain ``file`` for a future editor/navigation
        integration.  Current marker rendering deliberately handles only the
        open file, so no UI files are required by this checker refactor.
        """
        analysis = self._get_label_analysis()
        issues: list[dict] = []
        for item in analysis["duplicates"]:
            issue = {
                "line": item["line"],
                "severity": "error",
                "msg": f"Duplicate label: '{item['key']}'",
                "label": item["key"],
            }
            if item.get("file") is not None:
                issue["file"] = item["file"]
            issues.append(issue)
        for item in analysis["unused"]:
            issue = {
                "line": item["line"],
                "severity": "warning",
                "msg": f"Unused label: '{item['key']}'",
                "label": item["key"],
            }
            if item.get("file") is not None:
                issue["file"] = item["file"]
            issues.append(issue)
        return issues

    def _get_label_analysis(self) -> dict:
        if self._label_analysis is None:
            if self._index is not None:
                self._label_analysis = {
                    "definitions": list(self._index.definitions),
                    "references": list(self._index.references),
                    "duplicates": list(self._index.duplicates),
                    "unused": list(self._index.unused),
                    "undefined": list(self._index.undefined),
                }
                return self._label_analysis
            from editor.latex_support import LaTeXSupport
            self._label_analysis = LaTeXSupport.analyze_label_references(
                self._text, self._file_path if self._include_project else None,
            )
        return self._label_analysis

    def _check_undefined_citations(self) -> list[dict]:
        from editor.latex_support import LaTeXSupport
        fp = self._file_path
        if self._index is not None:
            known = set(self._index.bibtex_keys)
        elif fp:
            known = (set(LaTeXSupport.extract_bibtex_keys_multifile(fp))
                     if self._include_project else set())
            known.update(LaTeXSupport.extract_bibtex_keys(self._text, fp))
        else:
            known = set(LaTeXSupport.extract_bibtex_keys(self._text, fp))

        if not known:
            return []

        # The index already parsed every citation once; reuse its occurrences
        # for the current file instead of re-scanning the whole document. The
        # fallback (index unavailable) still uses the shared group-aware parser
        # so ``\citep[see]{key}`` and the biblatex plural forms are seen.
        if self._index is not None:
            current_path = self._index.current_path
            occurrences = [
                item for item in self._index.citation_occurrences
                if item.get("file") == current_path
                or (current_path is None and item.get("file") is None)
            ]
        else:
            occurrences = extract_latex_citation_occurrences(
                strip_latex_comments(self._text))

        issues: list[dict] = []
        for occurrence in occurrences:
            if self._cancelled:
                return []
            key = occurrence["key"]
            if key and key != "*" and key not in known:
                issues.append({
                    "line":     occurrence["line"],
                    "severity": "warning",
                    "msg":      f"BibTeX key not found: '{key}'",
                })
        return issues

    def _check_tabular_columns(self) -> list[dict]:
        """Warn when table rows disagree with the declared column count."""
        if self._index is not None:
            issues = []
            for source in self._index.sources:
                for issue in tabular_column_issues(
                        source.code, already_stripped=True,
                        cancelled=lambda: self._cancelled):
                    if source.path is not None:
                        issue["file"] = source.path
                    issues.append(issue)
            return issues
        sources = (self._project_sources()
                   if self._file_path and self._include_project
                   else [(None, self._text)])
        issues = []
        for path, source in sources:
            for issue in tabular_column_issues(
                    source, cancelled=lambda: self._cancelled):
                if path is not None:
                    issue["file"] = path
                issues.append(issue)
        return issues

    def _check_tikz_semicolons(self) -> list[dict]:
        """Warn when a TikZ drawing command is not terminated by ``;``."""
        if self._index is not None:
            issues = []
            for source in self._index.sources:
                for issue in tikz_semicolon_issues(
                        source.code, already_stripped=True):
                    if source.path is not None:
                        issue["file"] = source.path
                    issues.append(issue)
            return issues
        sources = (self._project_sources() if self._file_path
                   else [(None, self._text)])
        issues = []
        for path, source in sources:
            for issue in tikz_semicolon_issues(source):
                if path is not None:
                    issue["file"] = path
                issues.append(issue)
        return issues

    # ── Pure helpers re-exported for callers and tests ──────────────────────
    # The algorithms live in core.latex_checks (Qt-free and worker-safe); these
    # aliases are kept so the existing call sites and tests keep working.
    @staticmethod
    def _check_tabular_columns_single(text: str,
                                      already_stripped: bool = False) -> list[dict]:
        return tabular_column_issues(text, already_stripped=already_stripped)

    _check_tikz_semicolons_single = staticmethod(tikz_semicolon_issues)
    _count_row_cols = staticmethod(count_row_cols)
    _count_tabular_cols = staticmethod(count_tabular_cols)


# Workers that outlive their editor must remain referenced until QThread emits
# finished; otherwise QObject destruction aborts the process while the thread
# is still executing.
_ORPHANED_WORKERS: set[_CheckWorker] = set()


def wait_for_orphaned_workers() -> None:
    """Stop checker workers retained during shutdown and wait for completion."""
    for worker in list(_ORPHANED_WORKERS):
        try:
            worker.cancel()
            worker.wait()
            worker.deleteLater()
        except RuntimeError:
            pass
        finally:
            _ORPHANED_WORKERS.discard(worker)


class LaTeXChecker(QObject):
    """
    Checker LaTeX asincrono per un EditorWidget.
    Emette `issues_found` con la lista dei problemi rilevati.
    """

    issues_found = pyqtSignal(list)   # list[dict{line, severity, msg}]

    def __init__(self, editor: EditorWidget, parent: QObject = None):
        super().__init__(parent)
        self._editor  = editor
        self._enabled = True
        self._worker: _CheckWorker | None = None
        self._old_workers: set[_CheckWorker] = set()
        self._gen: int = 0
        self._started = False
        self._last_issues: list[dict] = []

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(1500)  # debounce: 1.5 secondi dopo l'ultima modifica
        self._timer.timeout.connect(self._run_live_check)
        editor.destroyed.connect(self.stop)

        self._setup_markers()

    # ── Setup marcatori gutter ────────────────────────────────────────────────

    def _setup_markers(self) -> None:
        ed = self._editor
        ed.markerDefine(_MARKER_ERROR_SYM,   _MARKER_ERROR)
        ed.markerDefine(_MARKER_WARNING_SYM, _MARKER_WARNING)
        ed.setMarkerBackgroundColor(QColor("#ff4444"), _MARKER_ERROR)
        ed.setMarkerForegroundColor(QColor("#ffffff"), _MARKER_ERROR)
        ed.setMarkerBackgroundColor(QColor("#ffcc00"), _MARKER_WARNING)
        ed.setMarkerForegroundColor(QColor("#000000"), _MARKER_WARNING)

    # ── Attivazione ───────────────────────────────────────────────────────────

    def start(self) -> None:
        """Collega il checker all'editor."""
        if self._started:
            return
        self._editor.textChanged.connect(self._on_text_changed)
        self._started = True

    def stop(self) -> None:
        """Scollega il checker."""
        if self._started:
            try:
                self._editor.textChanged.disconnect(self._on_text_changed)
            except (RuntimeError, TypeError):
                pass
            self._started = False
        self._timer.stop()
        self._gen += 1
        self._last_issues = []
        workers = set(self._old_workers)
        self._old_workers.clear()
        if self._worker is not None:
            workers.add(self._worker)
            self._worker = None
        for worker in workers:
            try:
                worker.finished.connect(self._forget_finished_workers)
            except RuntimeError:
                pass
            if not self._retire_worker(worker):
                self._old_workers.add(worker)
        self._clear_markers()
        self._clear_tabular_indicators()
        try:
            self.issues_found.emit([])
        except RuntimeError:
            pass

    def _retire_worker(self, worker: _CheckWorker) -> bool:
        """Cancella e attende un worker senza lasciarlo vivere oltre l'editor."""
        try:
            worker.cancel()
            if worker.isRunning():
                worker.wait(1000)
            if not worker.isRunning():
                worker.deleteLater()
                return True
        except RuntimeError:
            return True
        # The editor can be destroyed before a long check reacts to cancel().
        # Keep the QThread alive until it finishes instead of letting Python
        # garbage collection invoke QThread::~QThread while it is running.
        _ORPHANED_WORKERS.add(worker)
        try:
            worker.finished.connect(lambda w=worker: _ORPHANED_WORKERS.discard(w))
        except RuntimeError:
            _ORPHANED_WORKERS.discard(worker)
        return False

    def _forget_finished_workers(self) -> None:
        remaining = set()
        for worker in self._old_workers:
            try:
                if worker.isRunning():
                    remaining.add(worker)
            except RuntimeError:
                # The worker's finished signal can be delivered after
                # deleteLater has already removed its C++ object.
                continue
        self._old_workers = remaining

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self._last_issues = []
            self._clear_markers()
            self._clear_tabular_indicators()
            self.issues_found.emit([])

    # ── Trigger ───────────────────────────────────────────────────────────────

    def _on_text_changed(self) -> None:
        if self._enabled and self._editor.length() <= _LIVE_CHECK_MAX_BYTES:
            self._timer.start()

    def _run_live_check(self) -> None:
        self._run_check(include_project=False)

    def force_check(self) -> None:
        """Esegui subito il controllo (es. su salvataggio file)."""
        self._timer.stop()
        self._run_check()

    # ── Controllo (asincrono) ──────────────────────────────────────────────────

    def _run_check(self, include_project: bool = True) -> None:
        if not self._enabled or not self._started:
            return
        if self._worker is not None:
            self._worker.cancel()
            old = self._worker
            self._old_workers.add(old)
            old.finished.connect(self._forget_finished_workers)

        self._gen += 1
        text = self._editor.text()
        fp   = getattr(self._editor, "file_path", None)

        worker = _CheckWorker(text, fp, self._gen, include_project=include_project)
        worker.done.connect(self._on_check_done)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _on_check_done(self, gen: int, issues: list[dict]) -> None:
        if gen != self._gen:
            return
        self._worker = None
        self._last_issues = list(issues)
        self._apply_markers(issues)
        self._apply_tabular_indicators(issues)
        self.issues_found.emit(issues)

    # ── Marcatori gutter ─────────────────────────────────────────────────────

    def _clear_markers(self) -> None:
        try:
            self._editor.markerDeleteAll(_MARKER_ERROR)
            self._editor.markerDeleteAll(_MARKER_WARNING)
        except RuntimeError:
            pass

    def _apply_markers(self, issues: list[dict]) -> None:
        self._clear_markers()
        current_file = getattr(self._editor, "file_path", None)
        if current_file is not None:
            try:
                current_file = Path(current_file).resolve()
            except (OSError, TypeError, ValueError):
                current_file = None
        for issue in issues:
            issue_file = issue.get("file")
            if issue_file is not None and current_file is None:
                continue
            if issue_file is not None and current_file is not None:
                try:
                    if Path(issue_file).resolve() != current_file:
                        continue
                except (OSError, TypeError, ValueError):
                    continue
            line = issue.get("line", 0)
            marker = (_MARKER_ERROR
                      if issue.get("severity") == "error"
                      else _MARKER_WARNING)
            self._editor.markerAdd(line, marker)

    # ── Indicatori colonne tabella ──────────────────────────────────────────

    def _clear_tabular_indicators(self) -> None:
        """Rimuove gli indicatori colonne tabella dall'editor."""
        try:
            from editor.editor_widget import INDICATOR_LATEX_COL
            ed = self._editor
            last_line = ed.lines() - 1
            if last_line < 0:
                return
            ed.clearIndicatorRange(0, 0, last_line,
                                   len(ed.text(last_line)), INDICATOR_LATEX_COL)
        except RuntimeError:
            pass

    def _apply_tabular_indicators(self, issues: list[dict]) -> None:
        """Sottolinea con squiggly ambra: (a) & di troppo nelle righe del corpo
        tabella, (b) X in eccesso nella column spec della riga \\begin."""
        from editor.editor_widget import INDICATOR_LATEX_COL
        self._clear_tabular_indicators()
        seen = set()
        for issue in issues:
            # (a) Body row: highlight from excess & to end of line
            hs = issue.get("highlight_start")
            he = issue.get("highlight_end")
            line = issue.get("line", 0)
            if hs is not None and hs >= 0 and he is not None and he > hs:
                key = (line, hs)
                if key in seen:
                    continue
                seen.add(key)
                # hs/he sono colonne in caratteri (fillIndicatorRange non usa byte).
                self._editor.fillIndicatorRange(
                    line, hs, line, he, INDICATOR_LATEX_COL
                )
                continue

            # (b) Column spec: highlight only excess column chars (if any)
            excess = issue.get("excess_positions")
            cl = issue.get("col_line")
            if excess and cl is not None:
                for pos in excess:
                    key = (cl, pos)
                    if key in seen:
                        continue
                    seen.add(key)
                    self._editor.fillIndicatorRange(
                        cl, pos, cl, pos + 1, INDICATOR_LATEX_COL
                    )

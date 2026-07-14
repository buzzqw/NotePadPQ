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

import re
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal, Qt
from PyQt6.QtGui import QColor
from PyQt6.Qsci import QsciScintilla

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

# Numero del marcatore gutter usato da questo checker (1-31, evita conflitti)
_MARKER_ERROR   = 22
_MARKER_WARNING = 23

# Simbolo nel margine: cerchio rosso per errori, triangolo giallo per warning
_MARKER_ERROR_SYM   = QsciScintilla.MarkerSymbol.Circle
_MARKER_WARNING_SYM = QsciScintilla.MarkerSymbol.RightTriangle


class _CheckWorker(QThread):
    """Esegue i tre controlli LaTeX in un thread separato per non bloccare la UI."""

    done = pyqtSignal(int, list)   # (generation, list[dict])

    def __init__(self, text: str, file_path, generation: int):
        super().__init__(None)
        self._text       = text
        self._file_path  = file_path
        self._generation = generation
        self._cancelled  = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        issues: list[dict] = []
        if self._cancelled:
            return
        issues.extend(self._check_balance())
        if self._cancelled:
            return
        issues.extend(self._check_undefined_labels())
        if self._cancelled:
            return
        issues.extend(self._check_undefined_citations())
        if not self._cancelled:
            self.done.emit(self._generation, issues)

    def _check_balance(self) -> list[dict]:
        from editor.latex_support import LaTeXSupport
        raw = LaTeXSupport.check_environment_balance(self._text)
        return [
            {"line": e["line"], "severity": "error", "msg": e["msg"]}
            for e in raw
        ]

    def _check_undefined_labels(self) -> list[dict]:
        from editor.latex_support import LaTeXSupport
        fp = self._file_path
        if fp:
            defined = set(LaTeXSupport.extract_labels_multifile(fp))
        else:
            defined = set(LaTeXSupport.extract_labels(self._text))

        issues: list[dict] = []
        for lineno, line in enumerate(self._text.split("\n")):
            if self._cancelled:
                return []
            stripped = re.sub(r'(?<!\\)%.*', '', line)
            for m in re.finditer(
                r'\\(?:ref|eqref|pageref|cref|Cref|autoref|nameref|vref)\{([^}]+)\}',
                stripped
            ):
                key = m.group(1).strip()
                if key and key not in defined:
                    issues.append({
                        "line":     lineno,
                        "severity": "warning",
                        "msg":      f"Label non definita: '{key}'",
                    })
        return issues

    def _check_undefined_citations(self) -> list[dict]:
        from editor.latex_support import LaTeXSupport
        fp = self._file_path
        if fp:
            known = set(LaTeXSupport.extract_bibtex_keys_multifile(fp))
        else:
            known = set(LaTeXSupport.extract_bibtex_keys(self._text, fp))

        if not known:
            return []

        issues: list[dict] = []
        cite_pat = re.compile(
            r'\\(?:cite[a-zA-Z]*|parencite|footcite|textcite|autocite)\{([^}]+)\}'
        )
        for lineno, line in enumerate(self._text.split("\n")):
            if self._cancelled:
                return []
            stripped = re.sub(r'(?<!\\)%.*', '', line)
            for m in cite_pat.finditer(stripped):
                for key in m.group(1).split(","):
                    key = key.strip()
                    if key and key not in known:
                        issues.append({
                            "line":     lineno,
                            "severity": "warning",
                            "msg":      f"Chiave BibTeX non trovata: '{key}'",
                        })
        return issues


class LaTeXChecker(QObject):
    """
    Checker LaTeX asincrono per un EditorWidget.
    Emette `issues_found` con la lista dei problemi rilevati.
    """

    issues_found = pyqtSignal(list)   # list[dict{line, severity, msg}]

    def __init__(self, editor: "EditorWidget", parent: QObject = None):
        super().__init__(parent)
        self._editor  = editor
        self._enabled = True
        self._worker: Optional[_CheckWorker] = None
        self._gen: int = 0

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(1500)  # debounce: 1.5 secondi dopo l'ultima modifica
        self._timer.timeout.connect(self._run_check)

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
        self._editor.textChanged.connect(self._on_text_changed)

    def stop(self) -> None:
        """Scollega il checker."""
        try:
            self._editor.textChanged.disconnect(self._on_text_changed)
        except Exception:
            pass
        self._timer.stop()
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None
        self._clear_markers()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self._clear_markers()
            self.issues_found.emit([])

    # ── Trigger ───────────────────────────────────────────────────────────────

    def _on_text_changed(self) -> None:
        if self._enabled:
            self._timer.start()

    def force_check(self) -> None:
        """Esegui subito il controllo (es. su salvataggio file)."""
        self._timer.stop()
        self._run_check()

    # ── Controllo (asincrono) ──────────────────────────────────────────────────

    def _run_check(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

        self._gen += 1
        text = self._editor.text()
        fp   = getattr(self._editor, "file_path", None)

        worker = _CheckWorker(text, fp, self._gen)
        worker.done.connect(self._on_check_done)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _on_check_done(self, gen: int, issues: list[dict]) -> None:
        if gen != self._gen:
            return
        self._worker = None
        self._apply_markers(issues)
        self.issues_found.emit(issues)

    # ── Marcatori gutter ─────────────────────────────────────────────────────

    def _clear_markers(self) -> None:
        self._editor.markerDeleteAll(_MARKER_ERROR)
        self._editor.markerDeleteAll(_MARKER_WARNING)

    def _apply_markers(self, issues: list[dict]) -> None:
        self._clear_markers()
        for issue in issues:
            line = issue.get("line", 0)
            marker = (_MARKER_ERROR
                      if issue.get("severity") == "error"
                      else _MARKER_WARNING)
            self._editor.markerAdd(line, marker)

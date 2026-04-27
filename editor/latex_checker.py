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

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, Qt
from PyQt6.QtGui import QColor
from PyQt6.Qsci import QsciScintilla

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

# Numero del marcatore gutter usato da questo checker (1-31, evita conflitti)
_MARKER_ERROR   = 22
_MARKER_WARNING = 23

# Simbolo nel margine: cerchio rosso per errori, triangolo giallo per warning
_MARKER_ERROR_SYM   = QsciScintilla.MarkerSymbol.Circle
_MARKER_WARNING_SYM = QsciScintilla.MarkerSymbol.SmallArrow


class LaTeXChecker(QObject):
    """
    Checker LaTeX asincrono per un EditorWidget.
    Emette `issues_found` con la lista dei problemi rilevati.
    """

    issues_found = pyqtSignal(list)   # list[dict{line, severity, msg}]

    def __init__(self, editor: "EditorWidget", parent: QObject = None):
        super().__init__(parent)
        self._editor = editor
        self._enabled = True

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

    # ── Controllo ─────────────────────────────────────────────────────────────

    def _run_check(self) -> None:
        text = self._editor.text()
        issues: list[dict] = []

        issues.extend(self._check_balance(text))
        issues.extend(self._check_undefined_labels(text))
        issues.extend(self._check_undefined_citations(text))

        self._apply_markers(issues)
        self.issues_found.emit(issues)

    def _check_balance(self, text: str) -> list[dict]:
        """Rileva \\begin{}/\\end{} sbilanciati."""
        from editor.latex_support import LaTeXSupport
        raw = LaTeXSupport.check_environment_balance(text)
        return [
            {"line": e["line"], "severity": "error", "msg": e["msg"]}
            for e in raw
        ]

    def _check_undefined_labels(self, text: str) -> list[dict]:
        """Rileva \\ref{} che puntano a label non definite nel documento."""
        from editor.latex_support import LaTeXSupport
        fp = getattr(self._editor, "file_path", None)
        if fp:
            defined = set(LaTeXSupport.extract_labels_multifile(fp))
        else:
            defined = set(LaTeXSupport.extract_labels(text))

        issues: list[dict] = []
        for lineno, line in enumerate(text.split("\n")):
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

    def _check_undefined_citations(self, text: str) -> list[dict]:
        """Rileva \\cite{} a chiavi BibTeX non trovate."""
        from editor.latex_support import LaTeXSupport
        fp = getattr(self._editor, "file_path", None)
        if fp:
            known = set(LaTeXSupport.extract_bibtex_keys_multifile(fp))
        else:
            known = set(LaTeXSupport.extract_bibtex_keys(text, fp))

        if not known:
            return []   # nessun .bib trovato, non segnalare falsi positivi

        issues: list[dict] = []
        cite_pat = re.compile(
            r'\\(?:cite[a-zA-Z]*|parencite|footcite|textcite|autocite)\{([^}]+)\}'
        )
        for lineno, line in enumerate(text.split("\n")):
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

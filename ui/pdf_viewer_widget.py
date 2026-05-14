"""
ui/pdf_viewer_widget.py — Visualizzatore PDF (sola lettura)
NotePadPQ

Usa QWebEngineView (Chromium built-in PDF renderer) per visualizzare PDF.
Fallback a PyMuPDF se WebEngine non disponibile.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QToolBar, QToolButton,
    QLabel, QSizePolicy, QScrollArea
)

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEngineSettings
    WEBENGINE_OK = True
except ImportError:
    WEBENGINE_OK = False

from i18n.i18n import tr


class PdfViewerWidget(QWidget):
    """Tab widget per la visualizzazione PDF in sola lettura."""

    modified_changed = pyqtSignal(bool)   # stub — sempre False

    def __init__(self, path: Path, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.file_path: Optional[Path] = path
        self._build_ui()
        if path:
            self._load(path)

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        bar = QToolBar(self)
        bar.setMovable(False)
        bar.setFloatable(False)

        self._title_lbl = QLabel("", bar)
        self._title_lbl.setStyleSheet("padding: 0 8px; font-weight: bold;")
        bar.addWidget(self._title_lbl)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)

        self._pages_lbl = QLabel("", bar)
        self._pages_lbl.setStyleSheet("padding: 0 8px; color: gray;")
        bar.addWidget(self._pages_lbl)

        layout.addWidget(bar)

        if WEBENGINE_OK:
            self._view = QWebEngineView(self)
            self._view.settings().setAttribute(
                QWebEngineSettings.WebAttribute.PluginsEnabled, True
            )
            self._view.settings().setAttribute(
                QWebEngineSettings.WebAttribute.PdfViewerEnabled, True
            )
            self._view.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            layout.addWidget(self._view)
        else:
            self._view = None
            self._fallback_label = QLabel(
                "⚠ PyQt6-WebEngine non installato.\n"
                "pip install PyQt6-WebEngine",
                self
            )
            self._fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self._fallback_label)

    # ── Loading ───────────────────────────────────────────────────────────────

    def _load(self, path: Path) -> None:
        self._title_lbl.setText(path.name)
        self._pages_lbl.setText("")
        if self._view is not None:
            self._view.setUrl(QUrl.fromLocalFile(str(path.resolve())))
            self._view.loadFinished.connect(self._on_load_finished)

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            return
        self._view.page().runJavaScript(
            "document.title",
            lambda t: self._pages_lbl.setText(str(t) if t else "")
        )

    # ── Interface stubs for tab system ────────────────────────────────────────

    def is_modified(self) -> bool:
        return False

    def save(self) -> bool:
        return True

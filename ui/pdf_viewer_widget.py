"""
ui/pdf_viewer_widget.py — Visualizzatore PDF con evidenziazione hyperlink
NotePadPQ

Renderer preferito: PyMuPDF (fitz) — pagine rasterizzate con link visibili.
Fallback: QWebEngineView (Chromium) — link non evidenziati ma testo selezionabile.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, List

from PyQt6.QtCore import Qt, QUrl, pyqtSignal, QPoint, QRect
from PyQt6.QtGui import (
    QPixmap, QImage, QPainter, QPen, QBrush, QColor,
    QCursor, QDesktopServices
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QToolBar, QToolButton,
    QLabel, QSizePolicy, QScrollArea, QFrame, QApplication,
    QSpinBox
)

from i18n.i18n import tr

# ── Dipendenze opzionali ───────────────────────────────────────────────────────

try:
    import fitz as _fitz
    FITZ_OK = True
except ImportError:
    _fitz = None
    FITZ_OK = False

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEngineSettings
    WEBENGINE_OK = True
except ImportError:
    WEBENGINE_OK = False

# Colori overlay link
_LINK_BORDER = QColor(0, 100, 220, 200)
_LINK_FILL   = QColor(0, 100, 220, 35)
_LINK_HOVER  = QColor(0, 140, 255, 80)


# ── Singola pagina renderizzata ───────────────────────────────────────────────

class _PdfPageLabel(QLabel):
    """Riquadro che mostra una pagina PDF con link evidenziati e cliccabili."""

    link_activated = pyqtSignal(dict)   # emette il dict link di fitz

    def __init__(self, fitz_page, zoom: float, show_links: bool,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._fitz_page  = fitz_page
        self._zoom       = zoom
        self._show_links = show_links
        self._links: List[dict] = fitz_page.get_links() if fitz_page else []
        self._hovered_link: Optional[dict] = None

        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.setMouseTracking(True)
        self._render()

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render(self) -> None:
        mat = _fitz.Matrix(self._zoom, self._zoom)
        pix = self._fitz_page.get_pixmap(matrix=mat, colorspace=_fitz.csRGB)
        img = QImage(pix.samples, pix.width, pix.height,
                     pix.stride, QImage.Format.Format_RGB888)
        pm  = QPixmap.fromImage(img)

        if self._show_links and self._links:
            painter = QPainter(pm)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            for lnk in self._links:
                rect = self._link_rect_px(lnk)
                if lnk is self._hovered_link:
                    painter.setBrush(QBrush(_LINK_HOVER))
                    painter.setPen(QPen(_LINK_BORDER.darker(110), 2))
                else:
                    painter.setBrush(QBrush(_LINK_FILL))
                    painter.setPen(QPen(_LINK_BORDER, 1))
                painter.drawRoundedRect(rect, 2, 2)
            painter.end()

        self.setPixmap(pm)
        self.setFixedSize(pm.size())

    def _link_rect_px(self, lnk: dict) -> QRect:
        r = lnk["from"]
        return QRect(
            int(r.x0 * self._zoom), int(r.y0 * self._zoom),
            int((r.x1 - r.x0) * self._zoom),
            int((r.y1 - r.y0) * self._zoom),
        )

    def _link_at(self, pos: QPoint) -> Optional[dict]:
        x = pos.x() / self._zoom
        y = pos.y() / self._zoom
        pt = _fitz.Point(x, y)
        for lnk in self._links:
            if pt in lnk["from"]:
                return lnk
        return None

    # ── Mouse events ──────────────────────────────────────────────────────────

    def mouseMoveEvent(self, ev) -> None:
        lnk = self._link_at(ev.pos())
        if lnk is not self._hovered_link:
            self._hovered_link = lnk
            self.setCursor(
                QCursor(Qt.CursorShape.PointingHandCursor)
                if lnk else QCursor(Qt.CursorShape.ArrowCursor)
            )
            if self._show_links:
                self._render()
        # tooltip con destinazione
        if lnk:
            tip = _link_label(lnk)
            self.setToolTip(tip)
        else:
            self.setToolTip("")
        super().mouseMoveEvent(ev)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            lnk = self._link_at(ev.pos())
            if lnk:
                self.link_activated.emit(lnk)
                return
        super().mousePressEvent(ev)

    def update_show_links(self, show: bool) -> None:
        self._show_links = show
        self._render()


def _link_label(lnk: dict) -> str:
    """Restituisce una stringa descrittiva del link per tooltip."""
    uri = lnk.get("uri", "")
    if uri:
        return uri
    page = lnk.get("page", -1)
    if page >= 0:
        return tr("label.pdf_link_page", default=f"Vai a pagina {page + 1}", n=page + 1)
    return ""


# ── Widget principale ─────────────────────────────────────────────────────────

class PdfViewerWidget(QWidget):
    """Tab widget per la visualizzazione PDF."""

    modified_changed = pyqtSignal(bool)   # stub — sempre False

    _DEFAULT_ZOOM = 1.5

    def __init__(self, path: Path, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.file_path: Optional[Path] = path
        self._doc         = None          # fitz.Document
        self._zoom        = self._DEFAULT_ZOOM
        self._show_links  = True
        self._page_labels: List[_PdfPageLabel] = []

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
        bar.setStyleSheet("QToolBar { spacing: 4px; }")

        self._title_lbl = QLabel("", bar)
        self._title_lbl.setStyleSheet("padding: 0 8px; font-weight: bold;")
        bar.addWidget(self._title_lbl)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)

        if FITZ_OK:
            # pulsante toggle link
            self._btn_links = QToolButton(bar)
            self._btn_links.setText("🔗")
            self._btn_links.setCheckable(True)
            self._btn_links.setChecked(True)
            self._btn_links.setToolTip(
                tr("tooltip.pdf_toggle_links",
                   default="Mostra/nascondi hyperlink nel documento")
            )
            self._btn_links.toggled.connect(self._on_toggle_links)
            bar.addWidget(self._btn_links)

            bar.addSeparator()

            # zoom out
            btn_zm = QToolButton(bar)
            btn_zm.setText("−")
            btn_zm.setToolTip(tr("tooltip.pdf_zoom_out", default="Riduci zoom (−25%)"))
            btn_zm.clicked.connect(self._zoom_out)
            bar.addWidget(btn_zm)

            self._zoom_lbl = QLabel(f"{int(self._zoom * 100)}%", bar)
            self._zoom_lbl.setStyleSheet("padding: 0 4px; min-width: 42px; text-align: center;")
            self._zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bar.addWidget(self._zoom_lbl)

            # zoom in
            btn_zp = QToolButton(bar)
            btn_zp.setText("+")
            btn_zp.setToolTip(tr("tooltip.pdf_zoom_in", default="Aumenta zoom (+25%)"))
            btn_zp.clicked.connect(self._zoom_in)
            bar.addWidget(btn_zp)

            bar.addSeparator()

        self._pages_lbl = QLabel("", bar)
        self._pages_lbl.setStyleSheet("padding: 0 8px; color: gray;")
        bar.addWidget(self._pages_lbl)

        layout.addWidget(bar)

        if FITZ_OK:
            # Area di scorrimento pagine
            self._scroll = QScrollArea(self)
            self._scroll.setWidgetResizable(True)
            self._scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter)

            self._pages_container = QWidget()
            self._pages_layout = QVBoxLayout(self._pages_container)
            self._pages_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self._pages_layout.setContentsMargins(12, 12, 12, 12)
            self._pages_layout.setSpacing(10)

            self._scroll.setWidget(self._pages_container)
            layout.addWidget(self._scroll)
            self._view = None

        elif WEBENGINE_OK:
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
            self._scroll = None
        else:
            self._view   = None
            self._scroll = None
            lbl = QLabel(
                "⚠ PyMuPDF e PyQt6-WebEngine non installati.\n"
                "pip install pymupdf  oppure  pip install PyQt6-WebEngine",
                self
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)

    # ── Loading ───────────────────────────────────────────────────────────────

    def _load(self, path: Path) -> None:
        self._title_lbl.setText(path.name)

        if FITZ_OK:
            self._load_fitz(path)
        elif WEBENGINE_OK and self._view:
            self._view.setUrl(QUrl.fromLocalFile(str(path.resolve())))
            self._view.loadFinished.connect(self._on_webengine_loaded)

    def _load_fitz(self, path: Path) -> None:
        try:
            self._doc = _fitz.open(str(path.resolve()))
        except Exception as e:
            self._pages_lbl.setText(f"Errore: {e}")
            return

        n = len(self._doc)
        self._pages_lbl.setText(
            tr("label.pdf_pages", default=f"{n} pagine", n=n)
        )
        self._rebuild_pages()

    def _rebuild_pages(self) -> None:
        if not self._doc or not FITZ_OK:
            return
        # svuota
        for lbl in self._page_labels:
            lbl.setParent(None)
        self._page_labels.clear()

        for i in range(len(self._doc)):
            pg  = self._doc.load_page(i)
            lbl = _PdfPageLabel(pg, self._zoom, self._show_links, self._pages_container)
            lbl.link_activated.connect(self._on_link_activated)

            # separatore pagina
            if i > 0:
                sep = QFrame(self._pages_container)
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setStyleSheet("color: #555; margin: 0 20px;")
                self._pages_layout.addWidget(sep)

            self._pages_layout.addWidget(lbl)
            self._page_labels.append(lbl)

    # ── Interazione ───────────────────────────────────────────────────────────

    def _on_toggle_links(self, checked: bool) -> None:
        self._show_links = checked
        for lbl in self._page_labels:
            lbl.update_show_links(checked)

    def _zoom_out(self) -> None:
        if self._zoom > 0.5:
            self._zoom = round(self._zoom - 0.25, 2)
            self._apply_zoom()

    def _zoom_in(self) -> None:
        if self._zoom < 4.0:
            self._zoom = round(self._zoom + 0.25, 2)
            self._apply_zoom()

    def _apply_zoom(self) -> None:
        self._zoom_lbl.setText(f"{int(self._zoom * 100)}%")
        self._rebuild_pages()

    def _on_link_activated(self, lnk: dict) -> None:
        uri = lnk.get("uri", "")
        if uri:
            QDesktopServices.openUrl(QUrl(uri))
            return
        page = lnk.get("page", -1)
        if page >= 0 and 0 <= page < len(self._page_labels):
            lbl = self._page_labels[page]
            self._scroll.ensureWidgetVisible(lbl)

    def _on_webengine_loaded(self, ok: bool) -> None:
        if not ok or not self._view:
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

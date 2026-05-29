"""
ui/pdf_viewer_widget.py — Visualizzatore PDF con evidenziazione hyperlink
NotePadPQ

Renderer preferito: PyMuPDF (fitz) — pagine rasterizzate con link visibili.
Fallback: QWebEngineView (Chromium) — link non evidenziati ma testo selezionabile.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, List

from PyQt6.QtCore import Qt, QUrl, pyqtSignal, QPoint, QRect, QSize
from PyQt6.QtGui import (
    QPixmap, QImage, QPainter, QPen, QBrush, QColor,
    QCursor, QDesktopServices, QIcon, QShortcut, QKeySequence
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QToolBar, QToolButton,
    QLabel, QSizePolicy, QScrollArea, QFrame, QComboBox, QLineEdit,
    QSplitter, QListWidget, QListWidgetItem, QTabWidget
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
    from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
    WEBENGINE_OK = True
except ImportError:
    WEBENGINE_OK = False

# Colori overlay link
_LINK_BORDER = QColor(0, 100, 220, 200)
_LINK_FILL   = QColor(0, 100, 220, 35)
_LINK_HOVER  = QColor(0, 140, 255, 80)

_THUMB_W = 120   # larghezza miniatura in pixel


# ── Singola pagina renderizzata ───────────────────────────────────────────────

class _PdfPageLabel(QLabel):
    """Riquadro che mostra una pagina PDF con link evidenziati e cliccabili."""

    link_activated = pyqtSignal(dict)

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
        self.setToolTip(_link_label(lnk) if lnk else "")
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
    uri = lnk.get("uri", "")
    if uri:
        return uri
    page = lnk.get("page", -1)
    if page >= 0:
        return tr("label.pdf_link_page", n=page + 1)
    return ""


# ── Pannello laterale (miniature + segnalibri) ────────────────────────────────

class _SidePanel(QWidget):
    """Pannello sinistra con tab Miniature e Segnalibri."""

    page_requested = pyqtSignal(int)   # indice pagina (0-based)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumWidth(80)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget(self)
        self._tabs.setTabPosition(QTabWidget.TabPosition.South)
        self._tabs.setDocumentMode(True)

        self._thumb_list = QListWidget(self)
        self._thumb_list.setViewMode(QListWidget.ViewMode.IconMode)
        self._thumb_list.setIconSize(QSize(_THUMB_W, 160))
        self._thumb_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._thumb_list.setMovement(QListWidget.Movement.Static)
        self._thumb_list.setSpacing(4)
        self._thumb_list.setUniformItemSizes(False)
        self._thumb_list.itemClicked.connect(self._on_thumb_clicked)
        self._tabs.addTab(self._thumb_list, "☰")

        self._bm_list = QListWidget(self)
        self._bm_list.itemClicked.connect(self._on_bm_clicked)
        self._tabs.addTab(self._bm_list, "🔖")

        layout.addWidget(self._tabs)

    def populate(self, doc) -> None:
        self._populate_thumbs(doc)
        self._populate_bookmarks(doc)

    def _populate_thumbs(self, doc) -> None:
        self._thumb_list.clear()
        zoom = _THUMB_W / max(doc[0].rect.width, 1) if len(doc) > 0 else 1.0
        for i in range(len(doc)):
            pg  = doc.load_page(i)
            mat = _fitz.Matrix(zoom, zoom)
            pix = pg.get_pixmap(matrix=mat, colorspace=_fitz.csRGB)
            img = QImage(pix.samples, pix.width, pix.height,
                         pix.stride, QImage.Format.Format_RGB888)
            item = QListWidgetItem(f"{i + 1}")
            item.setIcon(QIcon(QPixmap.fromImage(img)))
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
            self._thumb_list.addItem(item)

    def _populate_bookmarks(self, doc) -> None:
        self._bm_list.clear()
        toc = doc.get_toc(simple=True)
        if not toc:
            placeholder = QListWidgetItem("—")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._bm_list.addItem(placeholder)
            return
        for level, title, page in toc:
            indent = "  " * (level - 1)
            item = QListWidgetItem(f"{indent}{title}  [{page}]")
            item.setData(Qt.ItemDataRole.UserRole, page - 1)  # 0-based
            item.setToolTip(tr("label.pdf_link_page", n=page))
            self._bm_list.addItem(item)

    def highlight_page(self, page_idx: int) -> None:
        if page_idx < self._thumb_list.count():
            self._thumb_list.setCurrentRow(page_idx)

    def _on_thumb_clicked(self, item: QListWidgetItem) -> None:
        page = item.data(Qt.ItemDataRole.UserRole)
        if page is not None:
            self.page_requested.emit(page)

    def _on_bm_clicked(self, item: QListWidgetItem) -> None:
        page = item.data(Qt.ItemDataRole.UserRole)
        if page is not None:
            self.page_requested.emit(page)


# ── Widget principale (renderer fitz) ─────────────────────────────────────────

class PdfViewerWidget(QWidget):
    """Tab widget per la visualizzazione PDF."""

    modified_changed = pyqtSignal(bool)

    _DEFAULT_ZOOM = 1.5

    def __init__(self, path: Path, parent: Optional[QWidget] = None,
                 main_window=None):
        super().__init__(parent)
        self.file_path: Optional[Path] = path
        self._main_window = main_window
        self._doc         = None
        self._zoom        = self._DEFAULT_ZOOM
        self._show_links  = True
        self._page_labels: List[_PdfPageLabel] = []

        from PyQt6.QtCore import QTimer
        self._zoom_timer = QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.setInterval(300)
        self._zoom_timer.timeout.connect(self._rebuild_pages)

        self._build_ui()
        if path:
            self._load(path)

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

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
            # pannello laterale
            self._btn_side = QToolButton(bar)
            self._btn_side.setText("◧")
            self._btn_side.setCheckable(True)
            self._btn_side.setChecked(True)
            self._btn_side.setToolTip(tr("tooltip.pdf_toggle_thumbs"))
            self._btn_side.toggled.connect(self._on_toggle_side)
            bar.addWidget(self._btn_side)

            bar.addSeparator()

            # link overlay
            self._btn_links = QToolButton(bar)
            self._btn_links.setText("🔗")
            self._btn_links.setCheckable(True)
            self._btn_links.setChecked(True)
            self._btn_links.setToolTip(tr("tooltip.pdf_toggle_links"))
            self._btn_links.toggled.connect(self._on_toggle_links)
            bar.addWidget(self._btn_links)

            bar.addSeparator()

            # zoom combo con preset + valore libero
            self._zoom_combo = QComboBox(bar)
            self._zoom_combo.setEditable(True)
            self._zoom_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            self._zoom_combo.setFixedWidth(130)
            self._zoom_combo.setToolTip(tr("tooltip.pdf_zoom_in"))
            self._zoom_combo.blockSignals(True)
            for z in [tr("label.pdf_auto"),
                      "25%", "50%", "75%", "100%", "125%", "150%",
                      "175%", "200%", "300%", "400%",
                      tr("label.pdf_fit_width"), tr("label.pdf_fit_page")]:
                self._zoom_combo.addItem(z)
            self._zoom_combo.setCurrentText(tr("label.pdf_auto"))
            self._zoom_combo.blockSignals(False)
            self._zoom_combo.currentIndexChanged.connect(self._apply_zoom_combo)
            self._zoom_combo.lineEdit().returnPressed.connect(self._apply_zoom_combo)
            bar.addWidget(self._zoom_combo)

            bar.addSeparator()

            # stampa
            btn_print = QToolButton(bar)
            btn_print.setText("🖨")
            btn_print.setToolTip(tr("tooltip.pdf_print"))
            btn_print.clicked.connect(self._print)
            bar.addWidget(btn_print)

            bar.addSeparator()

        # apri nel pannello Qt Web
        if WEBENGINE_OK:
            btn_web = QToolButton(bar)
            btn_web.setText("🌐")
            btn_web.setToolTip(tr("tooltip.pdf_open_web"))
            btn_web.clicked.connect(self._open_in_web_viewer)
            bar.addWidget(btn_web)

        # apri con visualizzatore esterno
        btn_ext = QToolButton(bar)
        btn_ext.setText("↗")
        btn_ext.setToolTip(tr("tooltip.pdf_open_external"))
        btn_ext.clicked.connect(self._open_external)
        bar.addWidget(btn_ext)

        bar.addSeparator()

        self._pages_lbl = QLabel("", bar)
        self._pages_lbl.setStyleSheet("padding: 0 8px; color: gray;")
        bar.addWidget(self._pages_lbl)

        layout.addWidget(bar)

        if FITZ_OK:
            self._splitter = QSplitter(Qt.Orientation.Horizontal, self)

            self._side_panel = _SidePanel(self._splitter)
            self._side_panel.page_requested.connect(self._scroll_to_page)
            self._splitter.addWidget(self._side_panel)

            self._scroll = QScrollArea(self)
            self._scroll.setWidgetResizable(True)
            self._scroll.setAlignment(
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

            self._pages_container = QWidget()
            self._pages_layout = QVBoxLayout(self._pages_container)
            self._pages_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self._pages_layout.setContentsMargins(12, 12, 12, 12)
            self._pages_layout.setSpacing(10)

            self._scroll.setWidget(self._pages_container)
            self._scroll.viewport().installEventFilter(self)
            self._splitter.addWidget(self._scroll)
            self._splitter.setStretchFactor(0, 0)
            self._splitter.setStretchFactor(1, 1)
            self._splitter.setSizes([140, 800])

            layout.addWidget(self._splitter)
            self._view = None

        elif WEBENGINE_OK:
            from ui._webengine import safe_webview
            self._view = safe_webview(self)
            if self._view is not None:
                self._view.settings().setAttribute(
                    QWebEngineSettings.WebAttribute.PluginsEnabled, True)
                self._view.settings().setAttribute(
                    QWebEngineSettings.WebAttribute.PdfViewerEnabled, True)
                self._view.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                layout.addWidget(self._view)
                self._scroll = None
            else:
                self._scroll = None
                lbl = QLabel(
                    "⚠ OpenGL non disponibile su questo sistema.\n"
                    "Il visualizzatore PDF WebEngine richiede GLX/EGL.\n"
                    "Installa PyMuPDF per usare il renderer alternativo:\n"
                    "pip install pymupdf", self)
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setWordWrap(True)
                layout.addWidget(lbl)
        else:
            self._view   = None
            self._scroll = None
            lbl = QLabel(
                "⚠ PyMuPDF e PyQt6-WebEngine non installati.\n"
                "pip install pymupdf  oppure  pip install PyQt6-WebEngine", self)
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
        self._pages_lbl.setText(tr("label.pdf_pages", n=n))
        self._side_panel.populate(self._doc)
        # primo caricamento: aspetta che il widget sia visibile per calcolare
        # correttamente la larghezza del viewport
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._initial_fit)

    def _initial_fit(self) -> None:
        if self._zoom_combo.currentText() == tr("label.pdf_auto"):
            self._auto_fit()
        else:
            self._rebuild_pages()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if FITZ_OK and self._doc and hasattr(self, "_zoom_combo"):
            if self._zoom_combo.currentText() == tr("label.pdf_auto"):
                self._auto_fit()

    def eventFilter(self, obj, event) -> bool:
        from PyQt6.QtCore import QEvent
        if (obj is self._scroll.viewport() and
                event.type() == QEvent.Type.Wheel and
                event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            delta = event.angleDelta().y()
            self._zoom_step(+0.1 if delta > 0 else -0.1)
            return True   # consuma l'evento: non fa scorrere la pagina
        return super().eventFilter(obj, event)

    def _zoom_step(self, step: float) -> None:
        new_zoom = round(max(0.25, min(4.0, self._zoom + step)), 2)
        if new_zoom == self._zoom:
            return
        self._zoom = new_zoom
        self._zoom_combo.blockSignals(True)
        self._zoom_combo.setCurrentText(f"{int(new_zoom * 100)}%")
        self._zoom_combo.blockSignals(False)
        # debounce: ricostruisce solo dopo 300ms di inattività dalla rotella
        if self._doc:
            self._zoom_timer.start()

    def _rebuild_pages(self) -> None:
        if not self._doc or not FITZ_OK:
            return
        # rimuove TUTTI i widget dal layout (label + separatori QFrame)
        while self._pages_layout.count():
            item = self._pages_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
        self._page_labels.clear()

        for i in range(len(self._doc)):
            pg  = self._doc.load_page(i)
            lbl = _PdfPageLabel(pg, self._zoom, self._show_links, self._pages_container)
            lbl.link_activated.connect(self._on_link_activated)
            if i > 0:
                sep = QFrame(self._pages_container)
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setStyleSheet("color: #555; margin: 0 20px;")
                self._pages_layout.addWidget(sep)
            self._pages_layout.addWidget(lbl)
            self._page_labels.append(lbl)
        # Imposta il minimum width sul contenuto più largo così setWidgetResizable(True)
        # espande il container fino a quella dimensione e mostra la scrollbar orizzontale
        if self._page_labels:
            self._pages_container.setMinimumWidth(
                max(lbl.width() for lbl in self._page_labels) + 24)

    # ── Zoom ──────────────────────────────────────────────────────────────────

    def _apply_zoom_combo(self) -> None:
        text = self._zoom_combo.currentText().strip()
        if text == tr("label.pdf_auto"):
            self._auto_fit()
            return
        if text == tr("label.pdf_fit_width"):
            self._fit_width()
            return
        if text == tr("label.pdf_fit_page"):
            self._fit_page()
            return
        try:
            pct = float(text.rstrip("% "))
        except ValueError:
            return
        pct = max(25.0, min(400.0, pct))
        new_zoom = round(pct / 100, 4)
        if new_zoom == self._zoom and self._doc:
            return
        self._zoom = new_zoom
        self._zoom_combo.blockSignals(True)
        self._zoom_combo.setCurrentText(f"{int(pct)}%")
        self._zoom_combo.blockSignals(False)
        if self._doc:
            self._rebuild_pages()

    def _auto_fit(self) -> None:
        """Adatta la larghezza della pagina al viewport, max 125%."""
        if not self._doc:
            return
        vw = self._scroll.viewport().width() - 24
        if vw <= 0:
            return
        pw = self._doc.load_page(0).rect.width
        if pw > 0:
            new_zoom = max(0.25, min(1.25, round(vw / pw, 4)))
            if new_zoom != self._zoom or not self._page_labels:
                self._zoom = new_zoom
                self._rebuild_pages()

    def _fit_width(self) -> None:
        if not self._doc:
            return
        vw = self._scroll.viewport().width() - 24
        pw = self._doc.load_page(0).rect.width
        if pw > 0:
            self._zoom = max(0.25, min(4.0, round(vw / pw, 4)))
            self._rebuild_pages()

    def _fit_page(self) -> None:
        if not self._doc:
            return
        vw = self._scroll.viewport().width() - 24
        vh = self._scroll.viewport().height() - 24
        page0 = self._doc.load_page(0)
        pw, ph = page0.rect.width, page0.rect.height
        if pw > 0 and ph > 0:
            self._zoom = max(0.25, min(4.0, round(min(vw / pw, vh / ph), 4)))
            self._rebuild_pages()

    # ── Stampa ────────────────────────────────────────────────────────────────

    def _print(self) -> None:
        if not self._doc:
            return
        from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dlg = QPrintDialog(printer, self)
        if dlg.exec() != QPrintDialog.DialogCode.Accepted:
            return
        dpi  = printer.resolution()
        zoom = dpi / 72.0  # PDF points = 1/72 inch
        mat  = _fitz.Matrix(zoom, zoom)
        painter = QPainter(printer)
        for i in range(len(self._doc)):
            if i > 0:
                printer.newPage()
            pg  = self._doc.load_page(i)
            pix = pg.get_pixmap(matrix=mat, colorspace=_fitz.csRGB)
            img = QImage(pix.samples, pix.width, pix.height,
                         pix.stride, QImage.Format.Format_RGB888)
            pr  = printer.pageRect(QPrinter.Unit.DevicePixel)
            img_s = img.scaled(
                int(pr.width()), int(pr.height()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            x = (int(pr.width())  - img_s.width())  // 2
            y = (int(pr.height()) - img_s.height()) // 2
            painter.drawImage(x, y, img_s)
        painter.end()

    # ── Interazione ───────────────────────────────────────────────────────────

    def _on_toggle_side(self, checked: bool) -> None:
        self._side_panel.setVisible(checked)

    def _on_toggle_links(self, checked: bool) -> None:
        self._show_links = checked
        for lbl in self._page_labels:
            lbl.update_show_links(checked)

    def _scroll_to_page(self, page_idx: int) -> None:
        if 0 <= page_idx < len(self._page_labels):
            self._scroll.ensureWidgetVisible(self._page_labels[page_idx])

    def _on_link_activated(self, lnk: dict) -> None:
        uri = lnk.get("uri", "")
        if uri:
            QDesktopServices.openUrl(QUrl(uri))
            return
        page = lnk.get("page", -1)
        if page >= 0:
            self._scroll_to_page(page)

    def _open_external(self) -> None:
        if self.file_path and self.file_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.file_path.resolve())))

    def _open_in_web_viewer(self) -> None:
        if not self.file_path or not WEBENGINE_OK or self._main_window is None:
            return
        tab_name = f"[Web] {self.file_path.name}"
        widget = PdfWebTabWidget(self.file_path)
        self._main_window._tab_manager.add_spreadsheet_tab(
            widget, tab_name, self.file_path)

    def _on_webengine_loaded(self, ok: bool) -> None:
        if not ok or not self._view:
            return
        self._view.page().runJavaScript(
            "document.title",
            lambda t: self._pages_lbl.setText(str(t) if t else ""))

    # ── Interface stubs for tab system ────────────────────────────────────────

    def is_modified(self) -> bool:
        return False

    def save(self) -> bool:
        return True


# ── Tab web Qt (testo selezionabile, find, stampa) ────────────────────────────

class PdfWebTabWidget(QWidget):
    """Tab con QWebEngineView: testo selezionabile, zoom nativo, ricerca inline."""

    modified_changed = pyqtSignal(bool)

    def __init__(self, path: Path, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.file_path: Optional[Path] = path
        self._view        = None
        self._find_edit   = None
        self._find_lbl    = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar = QToolBar(self)
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setStyleSheet("QToolBar { spacing: 4px; }")

        title = QLabel(self.file_path.name if self.file_path else "", bar)
        title.setStyleSheet("padding: 0 8px; font-weight: bold;")
        bar.addWidget(title)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)

        # ── Barra ricerca inline ───────────────────────────────────────────────
        bar.addWidget(QLabel("🔍", bar))

        self._find_edit = QLineEdit(bar)
        self._find_edit.setPlaceholderText(tr("label.find"))
        self._find_edit.setFixedWidth(190)
        self._find_edit.setClearButtonEnabled(True)
        self._find_edit.textChanged.connect(self._on_find_changed)
        self._find_edit.returnPressed.connect(self._find_next)
        bar.addWidget(self._find_edit)

        btn_prev = QToolButton(bar)
        btn_prev.setText("◀")
        btn_prev.setToolTip(tr("tooltip.search_prev"))
        btn_prev.clicked.connect(self._find_prev)
        bar.addWidget(btn_prev)

        btn_next = QToolButton(bar)
        btn_next.setText("▶")
        btn_next.setToolTip(tr("tooltip.search_next"))
        btn_next.clicked.connect(self._find_next)
        bar.addWidget(btn_next)

        self._find_lbl = QLabel("", bar)
        self._find_lbl.setStyleSheet("padding: 0 4px; min-width: 44px; color: gray;")
        bar.addWidget(self._find_lbl)

        bar.addSeparator()

        btn_print = QToolButton(bar)
        btn_print.setText("🖨")
        btn_print.setToolTip(tr("tooltip.pdf_print"))
        btn_print.clicked.connect(self._print)
        bar.addWidget(btn_print)

        bar.addSeparator()

        btn_ext = QToolButton(bar)
        btn_ext.setText("↗")
        btn_ext.setToolTip(tr("tooltip.pdf_open_external"))
        btn_ext.clicked.connect(self._open_external)
        bar.addWidget(btn_ext)

        layout.addWidget(bar)

        if WEBENGINE_OK:
            from ui._webengine import safe_webview
            self._view = safe_webview(self)
            if self._view is not None:
                self._view.settings().setAttribute(
                    QWebEngineSettings.WebAttribute.PluginsEnabled, True)
                self._view.settings().setAttribute(
                    QWebEngineSettings.WebAttribute.PdfViewerEnabled, True)
                self._view.setUrl(QUrl.fromLocalFile(str(self.file_path.resolve())))
                layout.addWidget(self._view)
            else:
                lbl = QLabel("⚠ OpenGL non disponibile: visualizzatore web PDF non utilizzabile.", self)
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setWordWrap(True)
                layout.addWidget(lbl)
        else:
            lbl = QLabel("⚠ PyQt6-WebEngine non installato.", self)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)

        # Ctrl+F porta il focus nel campo ricerca della toolbar
        sc = QShortcut(QKeySequence("Ctrl+F"), self)
        sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(self._focus_find)
        sc.activatedAmbiguously.connect(self._focus_find)

    # ── Ricerca ───────────────────────────────────────────────────────────────

    def _focus_find(self) -> None:
        if self._find_edit:
            self._find_edit.setFocus()
            self._find_edit.selectAll()

    def _on_find_changed(self, text: str) -> None:
        if self._view:
            self._view.findText(text, resultCallback=self._on_find_result)

    def _find_next(self) -> None:
        if self._view and self._find_edit and self._find_edit.text():
            self._view.findText(
                self._find_edit.text(),
                resultCallback=self._on_find_result)

    def _find_prev(self) -> None:
        if self._view and self._find_edit and self._find_edit.text():
            self._view.findText(
                self._find_edit.text(),
                QWebEnginePage.FindFlag.FindBackward,
                resultCallback=self._on_find_result)

    def _on_find_result(self, result) -> None:
        if self._find_lbl is None:
            return
        try:
            n   = result.numberOfMatches()
            cur = result.activeMatch()
            if n == 0:
                self._find_lbl.setText("—")
                self._find_lbl.setStyleSheet(
                    "padding: 0 4px; min-width: 44px; color: red;")
            else:
                self._find_lbl.setText(f"{cur}/{n}")
                self._find_lbl.setStyleSheet(
                    "padding: 0 4px; min-width: 44px; color: gray;")
        except Exception:
            pass

    # ── Stampa ────────────────────────────────────────────────────────────────

    def _print(self) -> None:
        if self._view:
            self._view.page().runJavaScript("window.print()")

    def _open_external(self) -> None:
        if self.file_path and self.file_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.file_path.resolve())))

    # ── Interface stubs for tab system ────────────────────────────────────────

    def is_modified(self) -> bool:
        return False

    def save(self) -> bool:
        return True

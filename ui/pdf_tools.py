"""
ui/pdf_tools.py — Tool aggiuntivi per il visualizzatore PDF: ricerca testo,
selezione mouse e lente di ingrandimento. Integrabile senza rompere nulla.
NotePadPQ
"""
from __future__ import annotations

from typing import Optional, List
from PyQt6.QtCore import Qt, QRectF, QPoint, QRect, QTimer
from PyQt6.QtGui import (
    QColor, QPen, QBrush, QPainter
)
from PyQt6.QtWidgets import (
    QWidget, QApplication
)

from i18n.i18n import tr  # noqa — riservato per uso futuro

try:
    import fitz
    FITZ_OK = True
except ImportError:
    fitz = None
    FITZ_OK = False


_SEARCH_HIGHLIGHT = QColor(255, 200, 50, 90)
_SEARCH_CURRENT  = QColor(255, 140, 0, 140)
_SELECTION_COLOR  = QColor(66, 133, 244, 60)
_SELECTION_BORDER = QColor(66, 133, 244, 180)
_MAG_BG = QColor(50, 50, 50, 240)
_MAG_BORDER = QColor(120, 120, 120, 200)


class PdfSearchManager:
    """Gestisce la ricerca testo in un documento PyMuPDF.

    Uso:
        mgr = PdfSearchManager(doc, page_labels, scroll_to_fn)
        mgr.search("hello")
        mgr.next_match()
        mgr.draw_matches()  # chiamato dopo ogni rebuild/zoom
    """

    def __init__(self, doc: fitz.Document, page_labels: list,
                 scroll_to_fn, rebuild_fn):
        self._doc = doc
        self._page_labels = page_labels
        self._scroll_to = scroll_to_fn
        self._rebuild = rebuild_fn
        self._query = ""
        self._matches: List[dict] = []
        self._current_idx = -1
        self._pages_with_matches: set = set()
        self._visible_ranges = {}

    @property
    def query(self) -> str:
        return self._query

    @property
    def match_count(self) -> int:
        return len(self._matches)

    @property
    def current_index(self) -> int:
        return self._current_idx

    def search(self, query: str) -> int:
        self._query = query.strip()
        self._matches.clear()
        self._current_idx = -1
        self._pages_with_matches.clear()
        if not self._query or not self._doc or not FITZ_OK:
            self._clear_highlights()
            return 0
        for page_idx in range(len(self._doc)):
            page = self._doc.load_page(page_idx)
            rects = page.search_for(self._query)
            for r in rects:
                self._matches.append({"page": page_idx, "rect": r, "rect_px": r})
                self._pages_with_matches.add(page_idx)
        if self._matches:
            self._current_idx = 0
        return len(self._matches)

    def _clear_highlights(self):
        for lbl in self._page_labels:
            if hasattr(lbl, '_search_matches'):
                lbl._search_matches = []
            if hasattr(lbl, '_search_current'):
                lbl._search_current = -1
            lbl.update()

    def next_match(self) -> int:
        if not self._matches:
            return -1
        self._current_idx = (self._current_idx + 1) % len(self._matches)
        self._goto_current()
        return self._current_idx

    def prev_match(self) -> int:
        if not self._matches:
            return -1
        self._current_idx = (self._current_idx - 1) % len(self._matches)
        self._goto_current()
        return self._current_idx

    def _goto_current(self):
        if not (0 <= self._current_idx < len(self._matches)):
            return
        m = self._matches[self._current_idx]
        self._scroll_to(m["page"], m["rect"])

    def draw_matches(self):
        """Applica gli highlight alle page label visibili."""
        for i, lbl in enumerate(self._page_labels):
            page_matches = [m for m in self._matches if m["page"] == i]
            lbl._search_matches = page_matches
            cur_local = -1
            if 0 <= self._current_idx < len(self._matches):
                cur_match = self._matches[self._current_idx]
                if cur_match["page"] == i:
                    try:
                        cur_local = page_matches.index(cur_match)
                    except ValueError:
                        pass
            lbl._search_current = cur_local
            lbl.update()

    def on_zoom_changed(self):
        """Ricalcola i rect in pixel dopo un cambio zoom, poi riesegue la ricerca."""
        if self._query:
            self.search(self._query)


# ── Selezione testo via mouse ─────────────────────────────────────────────────

class PdfTextSelector:
    """Gestisce la selezione testo con mouse drag su pagine PDF.

    Da attaccare a un _PdfPageLabel per aggiungere la capacità di selezione.
    """

    def __init__(self, page_label, fitz_page, zoom: float):
        self._lbl = page_label
        self._page = fitz_page
        self._zoom = zoom
        self._selecting = False
        self._start_pos: Optional[QPoint] = None
        self._end_pos: Optional[QPoint] = None
        self._selection_rect: Optional[QRectF] = None
        self._words_cache = None

    def _get_words(self):
        if self._words_cache is None:
            try:
                self._words_cache = self._page.get_text("words")
            except Exception:
                self._words_cache = []
        return self._words_cache

    def start_selection(self, pos: QPoint):
        self._selecting = True
        self._start_pos = pos
        self._end_pos = pos
        self._selection_rect = None

    def update_selection(self, pos: QPoint):
        if not self._selecting:
            return
        self._end_pos = pos

    def end_selection(self):
        if not self._selecting:
            return None
        self._selecting = False
        if self._start_pos and self._end_pos:
            dx = self._end_pos.x() - self._start_pos.x()
            dy = self._end_pos.y() - self._start_pos.y()
            if abs(dx) < 3 and abs(dy) < 3:
                self._selection_rect = None
                return None
            x0 = min(self._start_pos.x(), self._end_pos.x()) / self._zoom
            y0 = min(self._start_pos.y(), self._end_pos.y()) / self._zoom
            x1 = max(self._start_pos.x(), self._end_pos.x()) / self._zoom
            y1 = max(self._start_pos.y(), self._end_pos.y()) / self._zoom
            self._selection_rect = QRectF(x0, y0, x1 - x0, y1 - y0)
            text = self._extract_text()
            if text:
                QApplication.clipboard().setText(text)
                return text
            return ""

    def _extract_text(self) -> str:
        if not self._selection_rect:
            return ""
        r = self._selection_rect
        try:
            fitz_r = fitz.Rect(r.x(), r.y(), r.right(), r.bottom())
            return self._page.get_textbox(fitz_r).strip()
        except Exception:
            return ""

    def get_selection_rect_px(self) -> Optional[QRect]:
        if not self._start_pos or not self._end_pos:
            return None
        x0 = min(self._start_pos.x(), self._end_pos.x())
        y0 = min(self._start_pos.y(), self._end_pos.y())
        x1 = max(self._start_pos.x(), self._end_pos.x())
        y1 = max(self._start_pos.y(), self._end_pos.y())
        return QRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))

    def clear_selection(self):
        self._selecting = False
        self._start_pos = None
        self._end_pos = None
        self._selection_rect = None

    def clear_cache(self):
        self._words_cache = None


# ── Lente di ingrandimento ────────────────────────────────────────────────────

class _MagnifierOverlay(QWidget):
    """Widget flottante che mostra l'area sotto il cursore ingrandita."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._size = 200
        self._zoom_factor = 2.5
        self._source_pixmap = None
        self._visible = False
        self.setFixedSize(self._size, self._size)
        self.hide()

    def show_at(self, viewport_pos: QPoint, global_screen_pos: QPoint, source_pixmap):
        if source_pixmap is None or source_pixmap.isNull():
            self.hide()
            return
        self._source_pixmap = source_pixmap
        half_src = int((self._size / self._zoom_factor) / 2)
        src_x = max(0, min(source_pixmap.width() - half_src * 2,
                          int(viewport_pos.x()) - half_src))
        src_y = max(0, min(source_pixmap.height() - half_src * 2,
                          int(viewport_pos.y()) - half_src))
        self._src_rect = QRect(src_x, src_y, half_src * 2, half_src * 2)

        gx = global_screen_pos.x()
        gy = global_screen_pos.y()
        x = gx + 24
        y = gy - self._size - 24
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            if x + self._size > sg.right():
                x = gx - self._size - 24
            if y < sg.top():
                y = gy + 24
        self.move(x, y)
        self._visible = True
        self.show()
        self.update()

    def paintEvent(self, event):
        if not self._visible or self._source_pixmap is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(_MAG_BG))
        p.setPen(QPen(_MAG_BORDER, 2))
        r = QRect(2, 2, self._size - 4, self._size - 4)
        p.drawRoundedRect(r, self._size // 2, self._size // 2)
        if not self._src_rect.isEmpty():
            cropped = self._source_pixmap.copy(self._src_rect)
            scaled = cropped.scaled(
                self._size - 12, self._size - 12,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            ox = (self._size - scaled.width()) // 2
            oy = (self._size - scaled.height()) // 2
            p.drawPixmap(ox, oy, scaled)
            cx = self._size // 2
            cy = self._size // 2
            p.setPen(QPen(QColor(255, 255, 255, 180), 1))
            p.drawLine(cx - 8, cy, cx + 8, cy)
            p.drawLine(cx, cy - 8, cx, cy + 8)
        p.end()

    def hide_lens(self):
        self._visible = False
        self.hide()


class PdfMagnifier:
    """Gestisce la lente di ingrandimento per un PdfViewerWidget."""

    def __init__(self, viewer):
        self._viewer = viewer
        self._overlay: Optional[_MagnifierOverlay] = None
        self._active = False
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(50)
        self._debounce.timeout.connect(self._update_position)

    def toggle(self):
        self._active = not self._active
        if not self._active:
            self._hide()
        return self._active

    @property
    def active(self) -> bool:
        return self._active

    def on_mouse_move(self, global_pos: QPoint):
        if not self._active:
            return
        self._pending_pos = global_pos
        if not self._debounce.isActive():
            self._debounce.start()

    def _update_position(self):
        if not self._active or not hasattr(self, '_pending_pos'):
            return
        pos = self._pending_pos
        viewport = self._viewer._scroll.viewport() if hasattr(self._viewer, '_scroll') and self._viewer._scroll else None
        if viewport is None:
            return
        local = viewport.mapFromGlobal(pos)
        if not viewport.rect().contains(local):
            self._hide()
            return
        if not self._overlay:
            self._overlay = _MagnifierOverlay(self._viewer)
        src = viewport.grab()
        self._overlay.show_at(local, pos, src)

    def _hide(self):
        if self._overlay:
            self._overlay.hide_lens()
        self._overlay = None

"""
ui/minimap.py — Minimap laterale
NotePadPQ

Mostra una vista rimpicciolita del documento con indicatore
della posizione corrente. Clic sulla minimap scrolla l'editor.
Implementato come QAbstractScrollArea ridisegnato.
"""

from __future__ import annotations

import re
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, QRect, QTimer, QThread, QPoint, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QPixmap, QImage
from PyQt6.QtWidgets import QWidget, QAbstractScrollArea, QLabel
if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

# Configurazione minimap
MINIMAP_WIDTH   = 100    # px larghezza widget
CHAR_WIDTH      = 1      # px per carattere
LINE_HEIGHT     = 2      # px per riga
MAX_LINES       = 3000   # limite righe renderizzate
UPDATE_DELAY_MS = 500    # ms debounce aggiornamento (era 300 — ridotto carico main thread)

# Regex compilate una volta sola a livello modulo
_RE_COMMENT = re.compile(r'^\s*(#|//|--|%|;)')
_RE_STRING  = re.compile(r'["\']')
_RE_KEYWORD = re.compile(
    r'\b(def|class|import|from|if|else|elif|for|while|return|'
    r'function|var|let|const|public|private|void|int|str)\b'
)


class _MinimapWorker(QThread):
    """Disegna la minimap su QImage in un thread separato per non bloccare la UI.
    QPainter su QImage è thread-safe; QPixmap.fromImage() viene fatto sul main thread."""

    done = pyqtSignal(object)   # emette QImage quando il rendering è completo

    def __init__(self, lines: list, height: int,
                 bg: str, fg: str, kw: str, st: str, cm: str):
        super().__init__(None)
        self._lines     = lines
        self._height    = height
        self._bg        = bg
        self._fg        = fg
        self._kw        = kw
        self._st        = st
        self._cm        = cm
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        img = QImage(MINIMAP_WIDTH, self._height, QImage.Format.Format_RGB32)
        img.fill(QColor(self._bg))
        painter = QPainter(img)
        fg_c  = QColor(self._fg)
        kw_c  = QColor(self._kw)
        st_c  = QColor(self._st)
        cm_c  = QColor(self._cm)
        for i, line in enumerate(self._lines):
            if self._cancelled:
                break
            stripped = line.rstrip()
            if not stripped:
                continue
            if _RE_COMMENT.match(stripped):
                col = cm_c
            elif _RE_STRING.search(stripped):
                col = st_c
            elif _RE_KEYWORD.search(stripped):
                col = kw_c
            else:
                col = fg_c
            y      = i * LINE_HEIGHT
            indent = len(line) - len(line.lstrip())
            x      = min(indent * CHAR_WIDTH, MINIMAP_WIDTH - 2)
            w      = min(len(stripped) * CHAR_WIDTH, MINIMAP_WIDTH - x - 1)
            if w > 0:
                painter.fillRect(x, y, w, max(LINE_HEIGHT - 1, 1), col)
        painter.end()
        if not self._cancelled:
            self.done.emit(img)


class MinimapWidget(QWidget):
    """
    Widget minimap. Viene affiancato all'editor (a destra)
    dal TabManager o dalla MainWindow.
    """

    def __init__(self, editor: "EditorWidget", parent: QWidget = None):
        super().__init__(parent)
        self._editor = editor
        self._pixmap: Optional[QPixmap] = None
        self._dirty  = True
        self._needs_refresh = False

        self._worker: Optional[_MinimapWorker] = None
        self._old_workers: list = []

        self._popup: QLabel | None = None
        self._popup_y: float = 0.0
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Debounce aggiornamento minimap
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(UPDATE_DELAY_MS)
        self._timer.timeout.connect(self._rebuild)

        # Debounce popup hover
        self._popup_timer = QTimer(self)
        self._popup_timer.setSingleShot(True)
        self._popup_timer.setInterval(300)
        self._popup_timer.timeout.connect(self._show_popup_now)

        # Connette i segnali dell'editor
        self._editor.textChanged.connect(self._schedule_rebuild)
        self._editor.verticalScrollBar().valueChanged.connect(
            self.update
        )

        self._rebuild()

    def set_editor(self, editor: "EditorWidget") -> None:
        """Collega la minimap a un nuovo editor, disconnettendo il precedente."""
        if editor is self._editor:
            return
        # Disconnetti dal vecchio editor
        if self._editor is not None:
            try:
                self._editor.textChanged.disconnect(self._schedule_rebuild)
            except (RuntimeError, TypeError):
                pass
            try:
                self._editor.verticalScrollBar().valueChanged.disconnect(self.update)
            except (RuntimeError, TypeError):
                pass
        self._editor = editor
        if editor is None:
            self._pixmap = None
            self.update()
        else:
            editor.textChanged.connect(self._schedule_rebuild)
            editor.verticalScrollBar().valueChanged.connect(self.update)
            self._dirty = True
            self._schedule_rebuild()

    def _schedule_rebuild(self) -> None:
        self._dirty = True
        if self.isVisible():
            self._timer.start()
        else:
            self._needs_refresh = True

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._needs_refresh:
            self._needs_refresh = False
            self._timer.start()

    @pyqtSlot()
    def _rebuild(self) -> None:
        """Avvia il worker di rendering in background (non blocca il main thread)."""
        # Elimina worker precedenti non più in esecuzione (previene memory leak
        # anche se un worker crasha senza emettere finished)
        self._old_workers[:] = [
            w for w in self._old_workers if w.isRunning()
        ]

        total = self._editor.lines()
        n = min(total, MAX_LINES)
        lines = [self._editor.text(i) for i in range(n)]
        height = max(n * LINE_HEIGHT, self.height())

        try:
            from config.themes import ThemeManager
            tm    = ThemeManager.instance()
            theme = tm.get_theme(tm.active_name()) or {}
            ui    = theme.get("ui", {})
            bg  = ui.get("editor_bg", "#1e1e1e")
            fg  = ui.get("editor_fg", "#d4d4d4")
            kw  = theme.get("tokens", {}).get("keyword", {}).get("fg", "#569cd6")
            st  = theme.get("tokens", {}).get("string",  {}).get("fg", "#ce9178")
            cm  = theme.get("tokens", {}).get("comment", {}).get("fg", "#6a9955")
        except Exception:
            bg, fg, kw, st, cm = "#1e1e1e", "#d4d4d4", "#569cd6", "#ce9178", "#6a9955"

        if self._worker is not None:
            self._worker.cancel()
            self._old_workers.append(self._worker)
            self._worker = None

        worker = _MinimapWorker(lines, height, bg, fg, kw, st, cm)
        worker.done.connect(self._on_image_ready)
        self._worker = worker
        self._old_workers.append(worker)
        worker.start()

    @pyqtSlot(object)
    def _on_image_ready(self, img: "QImage") -> None:
        """Riceve il QImage dal worker e lo converte in QPixmap (main thread)."""
        self._worker = None
        self._pixmap = QPixmap.fromImage(img)
        self._dirty  = False
        self.update()

    def paintEvent(self, event) -> None:
        if not self._pixmap:
            return

        painter = QPainter(self)

        # Scala il pixmap nella viewport
        target = QRect(0, 0, self.width(), self.height())
        painter.drawPixmap(target, self._pixmap)

        # Evidenzia la zona visibile dell'editor
        self._draw_viewport_indicator(painter)

        painter.end()

    def _draw_viewport_indicator(self, painter: QPainter) -> None:
        """Disegna il rettangolo che indica la porzione visibile."""
        sb     = self._editor.verticalScrollBar()
        total  = max(1, self._editor.lines())
        vmin   = sb.minimum()
        vmax   = max(1, sb.maximum())
        vval   = sb.value()
        vpage  = sb.pageStep()

        if vmax == 0:
            return

        h = self.height()
        top    = int((vval - vmin)  / (vmax - vmin + vpage) * h)
        bottom = int((vval - vmin + vpage) / (vmax - vmin + vpage) * h)
        bottom = min(bottom, h)

        rect = QRect(0, top, self.width(), max(bottom - top, 4))
        painter.fillRect(rect, QColor(255, 255, 255, 30))
        pen = QPen(QColor(255, 255, 255, 80))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawRect(rect)

    def mousePressEvent(self, event) -> None:
        self._hide_popup()
        self._scroll_to(event.position().y())

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._popup_timer.stop()
            self._hide_popup()
            self._scroll_to(event.position().y())
        else:
            self._popup_y = event.position().y()
            self._popup_timer.start()

    def leaveEvent(self, event) -> None:
        self._popup_timer.stop()
        self._hide_popup()
        super().leaveEvent(event)

    def _scroll_to(self, y: float) -> None:
        """Scrolla l'editor alla posizione corrispondente alla y nella minimap."""
        h = max(1, self.height())
        ratio = y / h
        sb = self._editor.verticalScrollBar()
        target = int(ratio * (sb.maximum() - sb.minimum()) + sb.minimum())
        sb.setValue(target)

    def _line_from_y(self, y: float) -> int:
        total = max(1, self._editor.lines())
        ratio = max(0.0, min(1.0, y / max(1, self.height())))
        return int(ratio * total)

    def _show_popup_now(self) -> None:
        from config.settings import Settings
        if not Settings.instance().get("editor/minimap_hover_preview", False):
            self._hide_popup()
            return

        y = self._popup_y
        line = self._line_from_y(y)
        total = self._editor.lines()
        if total == 0:
            return

        CONTEXT = 9
        start = max(0, line - CONTEXT)
        end   = min(total, line + CONTEXT + 1)
        MAX_W = 72
        excerpt_lines = []
        for i in range(start, end):
            l = self._editor.text(i).rstrip("\r\n")
            excerpt_lines.append((l[:MAX_W] + "…") if len(l) > MAX_W else l)
        excerpt = "\n".join(excerpt_lines)
        if not excerpt.strip():
            self._hide_popup()
            return

        if self._popup is None:
            self._popup = QLabel()
            self._popup.setWindowFlags(
                Qt.WindowType.Tool |
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint
            )
            self._popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self._popup.setStyleSheet(
                "QLabel{background:#252526;color:#d4d4d4;"
                "font-family:monospace;font-size:11px;"
                "padding:6px 10px;border:1px solid #555;}"
            )

        self._popup.setText(excerpt)
        self._popup.adjustSize()

        # Posiziona a destra della minimap se è sul bordo sinistro, altrimenti a sinistra
        global_left  = self.mapToGlobal(QPoint(0, int(y)))
        global_right = self.mapToGlobal(QPoint(self.width(), int(y)))
        pw = self._popup.width()
        ph = self._popup.height()
        if global_left.x() >= pw + 10:
            px = global_left.x() - pw - 6
        else:
            px = global_right.x() + 6
        py = global_left.y() - ph // 2

        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().availableGeometry()
        px = max(screen.left(), min(px, screen.right() - pw))
        py = max(screen.top(),  min(py, screen.bottom() - ph))

        self._popup.move(px, py)
        self._popup.show()
        self._popup.raise_()

    def _hide_popup(self) -> None:
        if self._popup:
            self._popup.hide()

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

from PyQt6.QtCore import Qt, QRect, QTimer, pyqtSlot
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QFont,
    QFontMetrics, QPixmap,
)
from PyQt6.QtWidgets import QWidget, QAbstractScrollArea

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

# Configurazione minimap
MINIMAP_WIDTH   = 100    # px larghezza widget
CHAR_WIDTH      = 1      # px per carattere
LINE_HEIGHT     = 2      # px per riga
MAX_LINES       = 3000   # limite righe renderizzate
UPDATE_DELAY_MS = 300    # ms debounce aggiornamento

# Regex compilate una volta sola a livello modulo
_RE_COMMENT = re.compile(r'^\s*(#|//|--|%|;)')
_RE_STRING  = re.compile(r'["\']')
_RE_KEYWORD = re.compile(
    r'\b(def|class|import|from|if|else|elif|for|while|return|'
    r'function|var|let|const|public|private|void|int|str)\b'
)


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

        self.setFixedWidth(MINIMAP_WIDTH)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Minimap — clic per navigare")

        # Debounce aggiornamento
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(UPDATE_DELAY_MS)
        self._timer.timeout.connect(self._rebuild)

        # Connette i segnali dell'editor
        self._editor.textChanged.connect(self._schedule_rebuild)
        self._editor.verticalScrollBar().valueChanged.connect(
            self.update
        )

        self._rebuild()

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
        """Ridisegna il pixmap della minimap."""
        text   = self._editor.text()
        lines  = text.split("\n")[:MAX_LINES]
        height = max(len(lines) * LINE_HEIGHT, self.height())

        self._pixmap = QPixmap(MINIMAP_WIDTH, height)
        self._pixmap.fill(QColor("#1a1a1a"))

        painter = QPainter(self._pixmap)

        # Determina i colori dal tema corrente
        try:
            from config.themes import ThemeManager
            tm     = ThemeManager.instance()
            theme  = tm.get_theme(tm.active_name()) or {}
            ui     = theme.get("ui", {})
            bg     = QColor(ui.get("editor_bg", "#1e1e1e"))
            fg     = QColor(ui.get("editor_fg", "#d4d4d4"))
            kw_col = QColor(
                theme.get("tokens", {}).get("keyword", {}).get("fg", "#569cd6")
            )
            str_col = QColor(
                theme.get("tokens", {}).get("string", {}).get("fg", "#ce9178")
            )
            cmt_col = QColor(
                theme.get("tokens", {}).get("comment", {}).get("fg", "#6a9955")
            )
        except Exception:
            bg      = QColor("#1e1e1e")
            fg      = QColor("#d4d4d4")
            kw_col  = QColor("#569cd6")
            str_col = QColor("#ce9178")
            cmt_col = QColor("#6a9955")

        self._pixmap.fill(bg)
        painter.begin(self._pixmap)

        for i, line in enumerate(lines):
            y = i * LINE_HEIGHT
            stripped = line.rstrip()
            if not stripped:
                continue

            if _RE_COMMENT.match(stripped):
                col = cmt_col
            elif _RE_STRING.search(stripped):
                col = str_col
            elif _RE_KEYWORD.search(stripped):
                col = kw_col
            else:
                col = fg

            # Disegna la riga come barra orizzontale
            indent = len(line) - len(line.lstrip())
            x = min(indent * CHAR_WIDTH, MINIMAP_WIDTH - 2)
            w = min(len(stripped) * CHAR_WIDTH, MINIMAP_WIDTH - x - 1)
            if w > 0:
                painter.fillRect(x, y, w, max(LINE_HEIGHT - 1, 1), col)

        painter.end()
        self._dirty = False
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
        self._scroll_to(event.position().y())

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._scroll_to(event.position().y())

    def _scroll_to(self, y: float) -> None:
        """Scrolla l'editor alla posizione corrispondente alla y nella minimap."""
        h = max(1, self.height())
        ratio = y / h
        sb = self._editor.verticalScrollBar()
        target = int(ratio * (sb.maximum() - sb.minimum()) + sb.minimum())
        sb.setValue(target)

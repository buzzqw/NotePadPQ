"""
ui/tab_switcher.py — Popup Ctrl+Tab per switch rapido tra tab
NotePadPQ

Overlay di sola visualizzazione, stile Notepad++/VSCode: mostra i tab in
ordine di ultimo utilizzo (MRU) mentre l'utente tiene Ctrl premuto e preme
Tab ripetutamente; il rilascio di Ctrl conferma la selezione evidenziata.

La logica di intercettazione tastiera (Ctrl+Tab, Ctrl+Shift+Tab, rilascio
Ctrl, Esc) vive in MainWindow tramite un eventFilter installato sulla
QApplication: questo widget si limita a disegnare la lista e non prende mai
il focus da tastiera, altrimenti l'editor perderebbe il focus ad ogni
apertura del popup.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem


class TabSwitcherPopup(QWidget):

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        # Non deve mai rubare il focus da tastiera: la selezione è pilotata
        # a distanza da MainWindow mentre il focus resta nell'editor.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setObjectName("tabSwitcherRoot")
        self.setStyleSheet("""
            #tabSwitcherRoot {
                background: #252526;
                border: 1px solid #3c3c3c;
                border-radius: 6px;
            }
            QListWidget {
                background: #252526;
                color: #d4d4d4;
                border: none;
                outline: none;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 4px 14px;
                border-radius: 3px;
            }
            QListWidget::item:selected {
                background: #264f78;
                color: #ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self._list = QListWidget()
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setMinimumWidth(220)
        layout.addWidget(self._list)

    def set_items(self, labels: list, index: int) -> None:
        self._list.clear()
        for lbl in labels:
            self._list.addItem(QListWidgetItem(lbl))
        self.set_index(index)
        self._list.setFixedHeight(
            min(self._list.sizeHintForRow(0) * min(len(labels), 10) + 8, 320)
        )
        self.adjustSize()

    def set_index(self, index: int) -> None:
        self._list.setCurrentRow(index)

    def popup_at_center_of(self, widget: QWidget) -> None:
        """Mostra il popup centrato sopra `widget` (tipicamente la MainWindow)."""
        self.adjustSize()
        top_left = widget.mapToGlobal(widget.rect().topLeft())
        x = top_left.x() + (widget.width() - self.width()) // 2
        y = top_left.y() + (widget.height() - self.height()) // 2
        self.move(max(0, x), max(0, y))
        self.show()
        self.raise_()

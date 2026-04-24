"""
ui/command_palette.py — Command Palette (Ctrl+Shift+P)
NotePadPQ

Finestra fuzzy-search su tutti i comandi registrati in MainWindow._actions.
Si apre centrata sulla finestra principale e si chiude appena si esegue
un comando o si preme Esc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QSortFilterProxyModel
from PyQt6.QtGui import QStandardItemModel, QStandardItem
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QListView, QLabel,
)

if TYPE_CHECKING:
    from ui.main_window import MainWindow


class CommandPaletteDialog(QDialog):
    """
    Palette fuzzy-search stile VS Code / Sublime.
    Digita per filtrare, Invio per eseguire, Esc per chiudere.
    """

    def __init__(self, main_window: "MainWindow"):
        super().__init__(
            main_window,
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint,
        )
        self._mw = main_window
        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        self.setMinimumWidth(520)
        self.setMaximumHeight(420)
        self.setStyleSheet("""
            QDialog { border: 1px solid #555; border-radius: 4px; }
            QLineEdit {
                font-size: 14px; padding: 6px 8px;
                border: none; border-bottom: 1px solid #444;
                background: #252526; color: #cccccc;
            }
            QListView {
                background: #1e1e1e; color: #cccccc;
                border: none; font-size: 13px;
            }
            QListView::item:selected { background: #094771; }
            QListView::item:hover    { background: #2a2d2e; }
        """)

        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Cerca comando…")
        self._search.textChanged.connect(self._filter)
        vl.addWidget(self._search)

        self._model = QStandardItemModel()
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(0)

        self._list = QListView()
        self._list.setModel(self._proxy)
        self._list.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self._list.doubleClicked.connect(self._execute)
        vl.addWidget(self._list)

    def _populate(self) -> None:
        for action in self._mw._actions.values():
            text = action.text().replace("&", "").strip()
            if not text:
                continue
            sc = action.shortcut().toString()
            label = f"{text}    [{sc}]" if sc else text
            item = QStandardItem(label)
            item.setData(action, Qt.ItemDataRole.UserRole)
            self._model.appendRow(item)

        if self._proxy.rowCount() > 0:
            self._list.setCurrentIndex(self._proxy.index(0, 0))

    def _filter(self, text: str) -> None:
        self._proxy.setFilterFixedString(text)
        if self._proxy.rowCount() > 0:
            self._list.setCurrentIndex(self._proxy.index(0, 0))

    def _execute(self, _index=None) -> None:
        idx = self._list.currentIndex()
        if not idx.isValid():
            return
        action = self._proxy.data(idx, Qt.ItemDataRole.UserRole)
        if action:
            self.accept()
            action.trigger()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._execute()
        elif key == Qt.Key.Key_Escape:
            self.reject()
        elif key == Qt.Key.Key_Down:
            row = self._list.currentIndex().row() + 1
            if row < self._proxy.rowCount():
                self._list.setCurrentIndex(self._proxy.index(row, 0))
        elif key == Qt.Key.Key_Up:
            row = self._list.currentIndex().row() - 1
            if row >= 0:
                self._list.setCurrentIndex(self._proxy.index(row, 0))
        else:
            super().keyPressEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        parent = self.parent()
        if parent:
            geo = parent.geometry()
            self.adjustSize()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + 80
            self.move(x, y)
        self._search.setFocus()

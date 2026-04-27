"""
ui/goto_anything.py — Goto Anything (Ctrl+P)
NotePadPQ

Navigazione rapida fuzzy-search stile Sublime Text:
  (niente prefisso)  → cerca tra i file aperti per nome
  >testo             → cerca tra i comandi (come la command palette)
  :N                 → salta alla riga N del file corrente
  @testo             → salta al simbolo (def/class/function) nel file corrente
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QSortFilterProxyModel
from PyQt6.QtGui import QStandardItemModel, QStandardItem
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QListView, QLabel,
)

if TYPE_CHECKING:
    from ui.main_window import MainWindow


_SYMBOL_RE = re.compile(
    r"^\s*(?:def|class|function|func|sub|procedure|void|int|float|double|bool)\s+(\w+)",
    re.IGNORECASE,
)


class GotoAnythingDialog(QDialog):

    def __init__(self, main_window: "MainWindow"):
        super().__init__(
            main_window,
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint,
        )
        self._mw = main_window
        self._mode = "files"
        self._build_ui()
        self._show_files("")

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setMinimumWidth(560)
        self.setMaximumHeight(440)
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
            QLabel {
                background: #252526; color: #777; font-size: 11px;
                padding: 2px 8px 4px 8px;
            }
        """)

        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        self._search = QLineEdit()
        self._search.setPlaceholderText(
            "Cerca file aperto… (>comando  :riga  @simbolo)"
        )
        self._search.textChanged.connect(self._on_text_changed)
        vl.addWidget(self._search)

        self._hint = QLabel("")
        vl.addWidget(self._hint)

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

    # ── Content population ────────────────────────────────────────────────────

    def _clear(self) -> None:
        self._model.clear()

    def _show_files(self, query: str) -> None:
        self._mode = "files"
        self._hint.setText("↩ apri tab  |  digita > per comandi  : per riga  @ per simbolo")
        self._clear()
        tm = self._mw._tab_manager
        for editor in tm.all_editors():
            path = editor.file_path
            name = path.name if path else "Senza titolo"
            full = str(path) if path else ""
            if query and query.lower() not in name.lower() and query.lower() not in full.lower():
                continue
            label = f"{name}    {full}" if full else name
            item = QStandardItem(label)
            item.setData(editor, Qt.ItemDataRole.UserRole)
            self._model.appendRow(item)
        self._proxy.setFilterFixedString("")
        self._select_first()

    def _show_commands(self, query: str) -> None:
        self._mode = "commands"
        self._hint.setText("> comandi — ↩ per eseguire")
        self._clear()
        for action in self._mw._actions.values():
            text = action.text().replace("&", "").strip()
            if not text:
                continue
            sc = action.shortcut().toString()
            label = f"{text}    [{sc}]" if sc else text
            item = QStandardItem(label)
            item.setData(action, Qt.ItemDataRole.UserRole)
            self._model.appendRow(item)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterFixedString(query)
        self._select_first()

    def _show_symbols(self, query: str) -> None:
        self._mode = "symbols"
        self._hint.setText("@ simboli — def/class nel file corrente")
        self._clear()
        editor = self._mw._current_editor()
        if not editor:
            return
        text = editor.text()
        for lineno, line in enumerate(text.splitlines(), start=1):
            m = _SYMBOL_RE.match(line)
            if m:
                symbol = m.group(1)
                if query and query.lower() not in symbol.lower():
                    continue
                label = f"{symbol}    riga {lineno}"
                item = QStandardItem(label)
                item.setData(lineno, Qt.ItemDataRole.UserRole)
                self._model.appendRow(item)
        self._proxy.setFilterFixedString("")
        self._select_first()

    def _show_goto_line(self, text: str) -> None:
        self._mode = "line"
        self._clear()
        try:
            n = int(text)
            editor = self._mw._current_editor()
            lines = editor.lines() if editor else 0
            label = f"Vai alla riga {n}" + (f"  (file: {lines} righe)" if lines else "")
            self._hint.setText(f": riga — file corrente ha {lines} righe")
        except ValueError:
            label = "Inserisci un numero di riga"
            self._hint.setText(": riga — inserisci numero")
        item = QStandardItem(label)
        item.setData(text, Qt.ItemDataRole.UserRole)
        self._model.appendRow(item)
        self._proxy.setFilterFixedString("")
        self._select_first()

    # ── Events ────────────────────────────────────────────────────────────────

    def _on_text_changed(self, text: str) -> None:
        if text.startswith(">"):
            self._show_commands(text[1:].strip())
        elif text.startswith(":"):
            self._show_goto_line(text[1:].strip())
        elif text.startswith("@"):
            self._show_symbols(text[1:].strip())
        else:
            self._show_files(text.strip())

    def _execute(self, _index=None) -> None:
        idx = self._list.currentIndex()
        if not idx.isValid():
            return
        data = self._proxy.data(idx, Qt.ItemDataRole.UserRole)
        mode = self._mode

        self.accept()

        if mode == "files":
            editor = data
            if editor:
                tm = self._mw._tab_manager
                for i in range(tm.count()):
                    if tm.widget(i) is editor or (
                        hasattr(tm, "_get_editor_at") and tm._get_editor_at(i) is editor
                    ):
                        tm.setCurrentIndex(i)
                        break
                    ed = getattr(tm.widget(i), "_editor", None)
                    if ed is editor:
                        tm.setCurrentIndex(i)
                        break
                editor.setFocus()

        elif mode == "commands":
            action = data
            if action:
                action.trigger()

        elif mode == "line":
            try:
                n = int(data) - 1
                editor = self._mw._current_editor()
                if editor and n >= 0:
                    editor.setCursorPosition(n, 0)
                    editor.ensureLineVisible(n)
                    editor.setFocus()
            except (ValueError, TypeError):
                pass

        elif mode == "symbols":
            lineno = data
            if lineno:
                editor = self._mw._current_editor()
                if editor:
                    n = lineno - 1
                    editor.setCursorPosition(n, 0)
                    editor.ensureLineVisible(n)
                    editor.setFocus()

    def _select_first(self) -> None:
        if self._proxy.rowCount() > 0:
            self._list.setCurrentIndex(self._proxy.index(0, 0))

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

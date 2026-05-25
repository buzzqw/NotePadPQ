"""
ui/customize_toolbar_dialog.py — Dialogo personalizzazione toolbar principale
NotePadPQ

Permette di aggiungere, rimuovere e riordinare i pulsanti della toolbar
principale scegliendo tra tutte le azioni registrate nel programma.

Settings: toolbar/items  — lista JSON di chiavi azione con "|" per i separatori.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow

_SEPARATOR_KEY = "|"
def _get_separator_label():
    return tr("customize_toolbar.separator_label")

_SEPARATOR_LABEL = "─────── Separatore ───────"  # fallback statico

DEFAULT_TOOLBAR: list[str] = [
    "new", "open", "save", "save_all",
    "|",
    "find", "replace",
    "|",
    "undo", "redo",
    "|",
    "compile", "run",
]


def _action_label(key: str, actions: dict) -> str:
    if key == _SEPARATOR_KEY:
        return tr("customize_toolbar.separator_label")
    action = actions.get(key)
    if action is None:
        return key
    text = action.text().replace("&", "").strip(" .")
    return text or key


class CustomizeToolbarDialog(QDialog):
    def __init__(self, main_window: "MainWindow") -> None:
        super().__init__(main_window)
        self._mw = main_window
        self.setWindowTitle(tr("action.customize_toolbar", default="Personalizza barra degli strumenti"))
        self.setMinimumSize(680, 420)
        self._build_ui()
        self._populate()

    # ── costruzione UI ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        cols = QHBoxLayout()
        cols.setSpacing(8)

        # Colonna sinistra: azioni disponibili
        left = QVBoxLayout()
        left.addWidget(QLabel("Azioni disponibili"))
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("customize_toolbar.placeholder_search"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._filter_avail)
        left.addWidget(self._search)
        self._avail = QListWidget()
        self._avail.setDragDropMode(QListWidget.DragDropMode.NoDragDrop)
        self._avail.itemDoubleClicked.connect(self._add_selected)
        left.addWidget(self._avail)
        cols.addLayout(left, stretch=1)

        # Centro: bottoni add/remove
        center = QVBoxLayout()
        center.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        center.addStretch()
        self._btn_add = QPushButton("→")
        self._btn_add.setFixedWidth(36)
        self._btn_add.setToolTip(tr("customize_toolbar.tooltip_add"))
        self._btn_add.clicked.connect(self._add_selected)
        self._btn_remove = QPushButton("←")
        self._btn_remove.setFixedWidth(36)
        self._btn_remove.setToolTip(tr("customize_toolbar.tooltip_remove"))
        self._btn_remove.clicked.connect(self._remove_selected)
        center.addWidget(self._btn_add)
        center.addSpacing(4)
        center.addWidget(self._btn_remove)
        center.addStretch()
        cols.addLayout(center)

        # Colonna destra: toolbar corrente
        right = QVBoxLayout()
        right.addWidget(QLabel("Toolbar corrente"))
        self._curr = QListWidget()
        self._curr.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._curr.setDefaultDropAction(Qt.DropAction.MoveAction)
        right.addWidget(self._curr, stretch=1)

        # bottoni ordinamento
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self._btn_up   = QPushButton("Su")
        self._btn_down = QPushButton(tr("customize_toolbar.btn_down"))
        self._btn_sep  = QPushButton(tr("customize_toolbar.btn_separator"))
        self._btn_rem2 = QPushButton(tr("customize_toolbar.btn_remove"))
        self._btn_up.clicked.connect(self._move_up)
        self._btn_down.clicked.connect(self._move_down)
        self._btn_sep.clicked.connect(self._add_separator)
        self._btn_rem2.clicked.connect(self._remove_selected)
        for b in (self._btn_up, self._btn_down, self._btn_sep, self._btn_rem2):
            btn_row.addWidget(b)
        right.addLayout(btn_row)
        cols.addLayout(right, stretch=1)

        root.addLayout(cols)

        # Reset + OK/Cancel
        bottom = QHBoxLayout()
        btn_reset = QPushButton(tr("customize_toolbar.btn_reset"))
        btn_reset.clicked.connect(self._reset_default)
        bottom.addWidget(btn_reset)
        bottom.addStretch()
        bbox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bbox.accepted.connect(self._on_ok)
        bbox.rejected.connect(self.reject)
        bottom.addWidget(bbox)
        root.addLayout(bottom)

    # ── popolamento liste ─────────────────────────────────────────────────────

    def _populate(self) -> None:
        from config.settings import Settings
        saved = Settings.instance().get("toolbar/items", None)
        current_items: list[str] = saved if isinstance(saved, list) else list(DEFAULT_TOOLBAR)

        # Lista corrente
        self._curr.clear()
        for key in current_items:
            self._curr.addItem(self._make_item(key))

        # Lista disponibili: tutte le azioni non già in toolbar (esclusi separatori)
        in_toolbar = {k for k in current_items if k != _SEPARATOR_KEY}
        self._avail.clear()
        for key in sorted(self._mw._actions.keys()):
            if key not in in_toolbar:
                self._avail.addItem(self._make_item(key))

    def _make_item(self, key: str) -> QListWidgetItem:
        label = _action_label(key, self._mw._actions)
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, key)
        if key == _SEPARATOR_KEY:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            f = item.font()
            f.setItalic(True)
            item.setFont(f)
        return item

    # ── operazioni ────────────────────────────────────────────────────────────

    def _filter_avail(self, text: str) -> None:
        text = text.strip().lower()
        for i in range(self._avail.count()):
            item = self._avail.item(i)
            item.setHidden(bool(text) and text not in item.text().lower())

    def _add_selected(self) -> None:
        row = self._avail.currentRow()
        if row < 0:
            return
        item = self._avail.takeItem(row)
        key = item.data(Qt.ItemDataRole.UserRole)
        ins = self._curr.currentRow()
        if ins < 0:
            ins = self._curr.count()
        else:
            ins += 1
        self._curr.insertItem(ins, self._make_item(key))
        self._curr.setCurrentRow(ins)

    def _remove_selected(self) -> None:
        row = self._curr.currentRow()
        if row < 0:
            return
        item = self._curr.item(row)
        key = item.data(Qt.ItemDataRole.UserRole)
        self._curr.takeItem(row)
        if key != _SEPARATOR_KEY:
            # rimetti nella lista disponibili in ordine alfabetico
            label = _action_label(key, self._mw._actions)
            new_item = self._make_item(key)
            # trova posizione alfabetica (considera solo item visibili per non rompere l'ordine)
            for i in range(self._avail.count()):
                if self._avail.item(i).text() > label:
                    self._avail.insertItem(i, new_item)
                    break
            else:
                self._avail.addItem(new_item)
            # applica il filtro corrente al nuovo item
            flt = self._search.text().strip().lower()
            if flt and flt not in label.lower():
                new_item.setHidden(True)

    def _move_up(self) -> None:
        row = self._curr.currentRow()
        if row <= 0:
            return
        item = self._curr.takeItem(row)
        self._curr.insertItem(row - 1, item)
        self._curr.setCurrentRow(row - 1)

    def _move_down(self) -> None:
        row = self._curr.currentRow()
        if row < 0 or row >= self._curr.count() - 1:
            return
        item = self._curr.takeItem(row)
        self._curr.insertItem(row + 1, item)
        self._curr.setCurrentRow(row + 1)

    def _add_separator(self) -> None:
        row = self._curr.currentRow()
        ins = row + 1 if row >= 0 else self._curr.count()
        self._curr.insertItem(ins, self._make_item(_SEPARATOR_KEY))
        self._curr.setCurrentRow(ins)

    def _reset_default(self) -> None:
        self._curr.clear()
        for key in DEFAULT_TOOLBAR:
            self._curr.addItem(self._make_item(key))
        # ricostruisce disponibili e riapplica il filtro corrente
        in_toolbar = {k for k in DEFAULT_TOOLBAR if k != _SEPARATOR_KEY}
        self._avail.clear()
        flt = self._search.text().strip().lower()
        for key in sorted(self._mw._actions.keys()):
            if key not in in_toolbar:
                item = self._make_item(key)
                self._avail.addItem(item)
                if flt and flt not in item.text().lower():
                    item.setHidden(True)

    # ── OK ────────────────────────────────────────────────────────────────────

    def _on_ok(self) -> None:
        from config.settings import Settings
        items = []
        for i in range(self._curr.count()):
            key = self._curr.item(i).data(Qt.ItemDataRole.UserRole)
            items.append(key)
        # Rimuovi separatori doppi e iniziali/finali
        cleaned: list[str] = []
        for k in items:
            if k == _SEPARATOR_KEY and (not cleaned or cleaned[-1] == _SEPARATOR_KEY):
                continue
            cleaned.append(k)
        while cleaned and cleaned[-1] == _SEPARATOR_KEY:
            cleaned.pop()
        Settings.instance().set("toolbar/items", cleaned)
        self._mw._rebuild_toolbar()
        self.accept()

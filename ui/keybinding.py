"""
ui/keybinding.py — Editor scorciatoie da tastiera
NotePadPQ

Dialog con tabella azioni/shortcut, rimappatura, rilevamento conflitti,
reset ai default, salvataggio persistente.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLineEdit, QPushButton, QLabel, QDialogButtonBox,
    QMessageBox, QAbstractItemView,
)

from i18n.i18n import tr
from core.platform import get_config_dir


class KeySequenceEdit(QLineEdit):
    """Campo di testo che cattura una combinazione di tasti."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Premi la combinazione di tasti...")
        self.setReadOnly(True)
        self._sequence = QKeySequence()

    def keyPressEvent(self, event) -> None:
        modifiers = event.modifiers()
        key = event.key()

        # Ignora tasti soli modificatori
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift,
                   Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return

        combo = int(modifiers.value) | key
        self._sequence = QKeySequence(combo)
        self.setText(self._sequence.toString())

    def sequence(self) -> QKeySequence:
        return self._sequence

    def clear_sequence(self) -> None:
        self._sequence = QKeySequence()
        self.clear()


class KeyBindingDialog(QDialog):
    """
    Dialog per la rimappatura delle scorciatoie.
    Riceve il dizionario actions da MainWindow._actions.
    """

    def __init__(self, actions: dict[str, QAction], parent=None):
        super().__init__(parent)
        self._actions = actions
        self._modified: dict[str, str] = {}   # action_key → new shortcut string
        self._saved = self._load_saved()

        self.setWindowTitle(tr("action.keybinding_editor"))
        self.resize(720, 500)
        self._build_ui()
        self._populate()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Ricerca
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Filtra:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Cerca azione...")
        self._search.textChanged.connect(self._filter)
        search_layout.addWidget(self._search, 1)
        layout.addLayout(search_layout)

        # Tabella
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Azione", "Scorciatoia", "Default"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table, 1)

        # Pannello modifica
        edit_grp_layout = QHBoxLayout()
        edit_grp_layout.addWidget(QLabel("Nuova scorciatoia:"))
        self._key_edit = KeySequenceEdit()
        edit_grp_layout.addWidget(self._key_edit, 1)

        self._btn_assign  = QPushButton("Assegna")
        self._btn_clear   = QPushButton("Rimuovi")
        self._btn_reset1  = QPushButton("Reset azione")
        self._btn_assign.setEnabled(False)
        self._btn_clear.setEnabled(False)
        self._btn_reset1.setEnabled(False)
        self._btn_assign.clicked.connect(self._assign_shortcut)
        self._btn_clear.clicked.connect(self._clear_shortcut)
        self._btn_reset1.clicked.connect(self._reset_action)

        for btn in [self._btn_assign, self._btn_clear, self._btn_reset1]:
            edit_grp_layout.addWidget(btn)
        layout.addLayout(edit_grp_layout)

        # Conflict label
        self._conflict_lbl = QLabel("")
        self._conflict_lbl.setStyleSheet("color: #f44747;")
        layout.addWidget(self._conflict_lbl)

        # Pulsanti dialog
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.Reset
        )
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        btns.button(QDialogButtonBox.StandardButton.Reset).setText(
            "Reset tutti"
        )
        btns.button(QDialogButtonBox.StandardButton.Reset).clicked.connect(
            self._reset_all
        )
        layout.addWidget(btns)

    # ── Dati ─────────────────────────────────────────────────────────────────

    def _populate(self) -> None:
        self._table.setRowCount(0)
        self._rows: list[tuple[str, QAction]] = []   # (key, action)

        for key, action in sorted(self._actions.items(),
                                   key=lambda x: x[1].text()):
            action_text = action.text().replace("&", "")
            if not action_text:
                continue

            # Scorciatoia corrente (da saved o dall'azione)
            current = self._saved.get(key, action.shortcut().toString())
            default = action.shortcut().toString()

            row = self._table.rowCount()
            self._table.insertRow(row)

            item_name = QTableWidgetItem(action_text)
            item_name.setData(Qt.ItemDataRole.UserRole, key)
            item_curr = QTableWidgetItem(current)
            item_def  = QTableWidgetItem(default)

            if current != default:
                item_curr.setForeground(
                    __import__("PyQt6.QtGui", fromlist=["QColor"]).QColor("#4fc1ff")
                )

            self._table.setItem(row, 0, item_name)
            self._table.setItem(row, 1, item_curr)
            self._table.setItem(row, 2, item_def)
            self._rows.append((key, action))

    def _filter(self, text: str) -> None:
        text = text.lower()
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            self._table.setRowHidden(
                row, text not in item.text().lower()
            )

    def _on_selection_changed(self) -> None:
        has_sel = bool(self._table.selectedItems())
        self._btn_assign.setEnabled(has_sel)
        self._btn_clear.setEnabled(has_sel)
        self._btn_reset1.setEnabled(has_sel)
        self._conflict_lbl.setText("")

    # ── Modifica ──────────────────────────────────────────────────────────────

    def _current_key(self) -> Optional[str]:
        rows = self._table.selectedItems()
        if not rows:
            return None
        return self._table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    def _assign_shortcut(self) -> None:
        key = self._current_key()
        if not key:
            return
        row = self._table.currentRow()
        if row < 0:
            return

        seq = self._key_edit.sequence()
        seq_str = seq.toString()
        if not seq_str:
            return

        # Controlla conflitti
        conflict = self._find_conflict(seq_str, key)
        if conflict:
            self._conflict_lbl.setText(
                f"⚠ Conflitto con: {self._actions[conflict].text()}"
            )
            return

        self._conflict_lbl.setText("")
        self._modified[key] = seq_str

        # Aggiorna tabella
        item_curr = self._table.item(row, 1)
        if item_curr:
            item_curr.setText(seq_str)
            item_curr.setForeground(
                __import__("PyQt6.QtGui", fromlist=["QColor"]).QColor("#4fc1ff")
            )

    def _clear_shortcut(self) -> None:
        key = self._current_key()
        if not key:
            return
        row = self._table.currentRow()
        if row < 0:
            return

        self._modified[key] = ""
        item_curr = self._table.item(row, 1)
        if item_curr:
            item_curr.setText("")
        self._conflict_lbl.setText("")

    def _reset_action(self) -> None:
        key = self._current_key()
        if not key:
            return
        row = self._table.currentRow()
        if row < 0:
            return

        action = self._actions.get(key)
        if action:
            default = action.shortcut().toString()
            self._modified.pop(key, None)
            self._saved.pop(key, None)
            item_curr = self._table.item(row, 1)
            if item_curr:
                item_curr.setText(default)
                # Ripristina colore normale (ereditato)
                item_curr.setData(Qt.ItemDataRole.ForegroundRole, None)

    def _reset_all(self) -> None:
        reply = QMessageBox.question(
            self, tr("action.keybinding_editor"),
            "Ripristinare tutte le scorciatoie ai valori predefiniti?"
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._modified.clear()
            self._saved.clear()
            self._save()
            self._populate()

    def _find_conflict(self, seq_str: str, exclude_key: str) -> Optional[str]:
        """Trova un'azione che usa già questa scorciatoia."""
        if not seq_str:
            return None
        for key, action in self._actions.items():
            if key == exclude_key:
                continue
            current = self._saved.get(key, action.shortcut().toString())
            if current == seq_str:
                return key
        return None

    # ── Persistenza ──────────────────────────────────────────────────────────

    def _shortcuts_path(self) -> Path:
        return get_config_dir() / "shortcuts.json"

    def _load_saved(self) -> dict[str, str]:
        p = self._shortcuts_path()
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save(self) -> None:
        all_saved = dict(self._saved)
        all_saved.update(self._modified)
        try:
            self._shortcuts_path().write_text(
                json.dumps(all_saved, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    def _on_ok(self) -> None:
        # Applica le modifiche alle azioni Qt
        all_changes = dict(self._saved)
        all_changes.update(self._modified)
        for key, seq_str in all_changes.items():
            action = self._actions.get(key)
            if action:
                action.setShortcut(QKeySequence(seq_str))
        self._save()
        self.accept()


def load_and_apply_shortcuts(actions: dict[str, QAction]) -> None:
    """
    Carica e applica le scorciatoie salvate all'avvio dell'applicazione.
    Chiamato da MainWindow dopo aver costruito i menu.
    """
    p = get_config_dir() / "shortcuts.json"
    if not p.exists():
        return
    try:
        saved = json.loads(p.read_text(encoding="utf-8"))
        for key, seq_str in saved.items():
            action = actions.get(key)
            if action:
                action.setShortcut(QKeySequence(seq_str))
    except Exception:
        pass

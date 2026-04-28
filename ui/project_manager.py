"""
ui/project_manager.py — Gestione progetti stile PSPad
NotePadPQ

Dock panel con albero file raggruppati in gruppi.
Il progetto viene salvato come JSON con estensione .npqproj.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QToolBar, QTreeWidget,
    QTreeWidgetItem, QFileDialog, QInputDialog, QMessageBox,
    QMenu, QAbstractItemView, QLabel, QPushButton,
)

if TYPE_CHECKING:
    from ui.main_window import MainWindow


_PROJ_FILTER = "Progetto NotePadPQ (*.npqproj);;Tutti i file (*)"

# ── Struttura dati progetto ────────────────────────────────────────────────────
# {
#   "name": "Nome Progetto",
#   "groups": [
#     { "name": "Gruppo", "files": ["/path/file1.py", ...] }
#   ]
# }


class ProjectManager(QWidget):
    """Widget dock per la gestione progetti."""

    file_open_requested = pyqtSignal(Path)

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._mw = main_window
        self._project_path: Optional[Path] = None
        self._dirty = False
        self._build_ui()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setContentsMargins(2, 2, 2, 2)
        vl.setSpacing(2)

        # Toolbar
        tb = QToolBar()
        tb.setIconSize(__import__('PyQt6.QtCore', fromlist=['QSize']).QSize(16, 16))

        def _act(text: str, tip: str, slot) -> QAction:
            a = QAction(text, self)
            a.setToolTip(tip)
            a.triggered.connect(slot)
            return a

        tb.addAction(_act("Nuovo",   "Nuovo progetto",       self.action_new))
        tb.addAction(_act("Apri",    "Apri progetto…",       self.action_open))
        tb.addAction(_act("Salva",   "Salva progetto",       self.action_save))
        tb.addSeparator()
        tb.addAction(_act("+File",   "Aggiungi file…",       self.action_add_files))
        tb.addAction(_act("+Gruppo", "Aggiungi gruppo…",     self.action_add_group))
        tb.addAction(_act("Rimuovi", "Rimuovi selezionato",  self.action_remove))
        vl.addWidget(tb)

        # Etichetta nome progetto
        self._title_lbl = QLabel("(nessun progetto)")
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_lbl.setStyleSheet("font-weight: bold; padding: 2px;")
        vl.addWidget(self._title_lbl)

        # Albero
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._context_menu)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        vl.addWidget(self._tree)

    # ── Struttura albero ────────────────────────────────────────────────────────

    def _rebuild_tree(self) -> None:
        self._tree.clear()
        proj = self._project_data()
        self._title_lbl.setText(proj.get("name", "Progetto"))
        for grp in proj.get("groups", []):
            grp_item = QTreeWidgetItem([grp.get("name", "Gruppo")])
            grp_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "group", "name": grp["name"]})
            grp_item.setFlags(
                grp_item.flags() | Qt.ItemFlag.ItemIsEditable
            )
            for fpath in grp.get("files", []):
                p = Path(fpath)
                fi = QTreeWidgetItem([p.name])
                fi.setData(0, Qt.ItemDataRole.UserRole, {"type": "file", "path": fpath})
                fi.setToolTip(0, fpath)
                grp_item.addChild(fi)
            self._tree.addTopLevelItem(grp_item)
            grp_item.setExpanded(True)

    def _project_data(self) -> dict:
        return getattr(self, "_data", {"name": "Progetto", "groups": []})

    def _set_data(self, data: dict) -> None:
        self._data = data
        self._dirty = True
        self._rebuild_tree()

    # ── Azioni toolbar ─────────────────────────────────────────────────────────

    def action_new(self) -> None:
        if self._dirty and self._project_path:
            r = QMessageBox.question(
                self, "Salva progetto",
                "Il progetto ha modifiche non salvate. Salvare?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                QMessageBox.StandardButton.Cancel,
            )
            if r == QMessageBox.StandardButton.Cancel:
                return
            if r == QMessageBox.StandardButton.Yes:
                self.action_save()

        name, ok = QInputDialog.getText(self, "Nuovo progetto", "Nome del progetto:")
        if not ok or not name.strip():
            return
        self._project_path = None
        self._dirty = False
        self._data = {"name": name.strip(), "groups": []}
        self._rebuild_tree()

    def action_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Apri progetto", "", _PROJ_FILTER
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self._project_path = Path(path)
            self._dirty = False
            self._data = data
            self._rebuild_tree()
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile aprire il progetto:\n{e}")

    def action_save(self) -> None:
        if self._project_path is None:
            self.action_save_as()
            return
        self._write(self._project_path)

    def action_save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Salva progetto", "", _PROJ_FILTER
        )
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() != ".npqproj":
            p = p.with_suffix(".npqproj")
        self._project_path = p
        self._write(p)

    def _write(self, path: Path) -> None:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._project_data(), f, ensure_ascii=False, indent=2)
            self._dirty = False
        except Exception as e:
            QMessageBox.critical(self, "Errore", f"Impossibile salvare:\n{e}")

    def action_add_files(self) -> None:
        if not self._project_data().get("groups"):
            QMessageBox.information(
                self, "Aggiungi file",
                "Crea prima un gruppo con il pulsante '+Gruppo'."
            )
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Aggiungi file al progetto", "", "Tutti i file (*)"
        )
        if not paths:
            return
        # Usa il gruppo selezionato o il primo
        grp_name = self._selected_group_name()
        data = self._project_data()
        for grp in data["groups"]:
            if grp["name"] == grp_name:
                existing = set(grp["files"])
                for p in paths:
                    if p not in existing:
                        grp["files"].append(p)
                break
        self._set_data(data)

    def action_add_group(self) -> None:
        name, ok = QInputDialog.getText(self, "Aggiungi gruppo", "Nome del gruppo:")
        if not ok or not name.strip():
            return
        data = self._project_data()
        data.setdefault("groups", []).append({"name": name.strip(), "files": []})
        self._set_data(data)

    def action_remove(self) -> None:
        items = self._tree.selectedItems()
        if not items:
            return
        data = self._project_data()
        for item in items:
            d = item.data(0, Qt.ItemDataRole.UserRole)
            if not d:
                continue
            if d["type"] == "group":
                data["groups"] = [g for g in data["groups"] if g["name"] != d["name"]]
            elif d["type"] == "file":
                parent = item.parent()
                if parent:
                    pd = parent.data(0, Qt.ItemDataRole.UserRole)
                    if pd and pd["type"] == "group":
                        for grp in data["groups"]:
                            if grp["name"] == pd["name"]:
                                grp["files"] = [f for f in grp["files"] if f != d["path"]]
        self._set_data(data)

    # ── Interazione albero ──────────────────────────────────────────────────────

    def _selected_group_name(self) -> str:
        items = self._tree.selectedItems()
        for item in items:
            d = item.data(0, Qt.ItemDataRole.UserRole)
            if d and d["type"] == "group":
                return d["name"]
            elif d and d["type"] == "file":
                parent = item.parent()
                if parent:
                    pd = parent.data(0, Qt.ItemDataRole.UserRole)
                    if pd:
                        return pd["name"]
        # fallback: primo gruppo
        data = self._project_data()
        if data.get("groups"):
            return data["groups"][0]["name"]
        return ""

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        d = item.data(0, Qt.ItemDataRole.UserRole)
        if d and d["type"] == "file":
            self.file_open_requested.emit(Path(d["path"]))

    def _context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        menu = QMenu(self)
        if item:
            d = item.data(0, Qt.ItemDataRole.UserRole)
            if d and d["type"] == "file":
                menu.addAction("Apri file", lambda: self.file_open_requested.emit(Path(d["path"])))
                menu.addSeparator()
            menu.addAction("Rimuovi", self.action_remove)
        menu.addSeparator()
        menu.addAction("Aggiungi file…",  self.action_add_files)
        menu.addAction("Aggiungi gruppo…", self.action_add_group)
        menu.exec(self._tree.viewport().mapToGlobal(pos))

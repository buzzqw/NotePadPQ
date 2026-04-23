"""
ui/named_sessions.py — Gestione sessioni nominate
NotePadPQ

Dialog per salvare e caricare sessioni con nome personalizzato,
come in Notepad++. Ogni sessione salva i file aperti e le posizioni cursore.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QInputDialog, QMessageBox, QLabel
)

from core.platform import get_config_dir
from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


def _sessions_dir() -> Path:
    p = get_config_dir() / "sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_named_session(name: str, main_window: "MainWindow") -> bool:
    """Salva la sessione corrente con il nome dato."""
    safe = "".join(c for c in name if c.isalnum() or c in " _-").strip()
    if not safe:
        return False
    path = _sessions_dir() / f"{safe}.json"
    tm = main_window._tab_manager
    data = {
        "name": name,
        "current_index": tm.currentIndex(),
        "tabs": [],
    }
    for editor in tm.all_editors():
        if editor.file_path and editor.file_path.exists():
            line, col = editor.getCursorPosition()
            data["tabs"].append({
                "path": str(editor.file_path),
                "line": line,
                "col": col,
                "encoding": editor.encoding,
            })
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def load_named_session(name: str, main_window: "MainWindow") -> bool:
    """Carica la sessione con il nome dato."""
    safe = "".join(c for c in name if c.isalnum() or c in " _-").strip()
    path = _sessions_dir() / f"{safe}.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False

    for tab in data.get("tabs", []):
        p = Path(tab.get("path", ""))
        if p.exists():
            main_window.open_files([p])
            editor = main_window._tab_manager.current_editor()
            if editor:
                line = tab.get("line", 0)
                col = tab.get("col", 0)
                editor.setCursorPosition(line, col)

    idx = data.get("current_index", 0)
    if 0 <= idx < main_window._tab_manager.count():
        main_window._tab_manager.setCurrentIndex(idx)
    return True


def list_sessions() -> list[str]:
    return [f.stem for f in sorted(_sessions_dir().glob("*.json"))]


def delete_session(name: str) -> bool:
    safe = "".join(c for c in name if c.isalnum() or c in " _-").strip()
    path = _sessions_dir() / f"{safe}.json"
    try:
        if path.exists():
            path.unlink()
            return True
    except Exception:
        pass
    return False


class NamedSessionsDialog(QDialog):
    """Dialog per gestire le sessioni nominate."""

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._mw = main_window
        self.setWindowTitle("Gestione sessioni")
        self.setMinimumSize(380, 300)
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Sessioni salvate:"))

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        self._btn_save   = QPushButton("💾  Salva corrente...")
        self._btn_load   = QPushButton("📂  Carica")
        self._btn_delete = QPushButton("🗑  Elimina")
        btn_row.addWidget(self._btn_save)
        btn_row.addWidget(self._btn_load)
        btn_row.addWidget(self._btn_delete)
        layout.addLayout(btn_row)

        close_btn = QPushButton("Chiudi")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._btn_save.clicked.connect(self._on_save)
        self._btn_load.clicked.connect(self._on_load)
        self._btn_delete.clicked.connect(self._on_delete)
        self._list.itemDoubleClicked.connect(lambda _: self._on_load())

    def _refresh(self) -> None:
        self._list.clear()
        for name in list_sessions():
            self._list.addItem(QListWidgetItem(name))

    def _selected_name(self) -> Optional[str]:
        item = self._list.currentItem()
        return item.text() if item else None

    def _on_save(self) -> None:
        name, ok = QInputDialog.getText(self, "Salva sessione", "Nome sessione:")
        if ok and name.strip():
            if save_named_session(name.strip(), self._mw):
                self._refresh()
            else:
                QMessageBox.warning(self, "Errore", "Impossibile salvare la sessione.")

    def _on_load(self) -> None:
        name = self._selected_name()
        if not name:
            return
        if not load_named_session(name, self._mw):
            QMessageBox.warning(self, "Errore", f"Impossibile caricare la sessione '{name}'.")
        else:
            self.accept()

    def _on_delete(self) -> None:
        name = self._selected_name()
        if not name:
            return
        r = QMessageBox.question(self, "Elimina sessione",
                                 f"Eliminare la sessione '{name}'?")
        if r == QMessageBox.StandardButton.Yes:
            delete_session(name)
            self._refresh()

"""
ui/named_sessions.py — Gestione sessioni nominate
NotePadPQ

Dialog per salvare e caricare sessioni con nome personalizzato,
come in Notepad++. Ogni sessione salva i file aperti e le posizioni cursore.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QInputDialog, QMessageBox, QLabel
)

from core.platform import get_config_dir
from core.persistence import atomic_write_json, load_json
from core.session import restore_cursor_after_load
from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


def _sessions_dir() -> Path:
    p = get_config_dir() / "sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_session_name(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in " _-").strip()


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_named_session(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    if not isinstance(data.get("tabs"), list):
        return False
    if "name" in data and not isinstance(data["name"], str):
        return False
    if "current_index" in data and not _is_int(data["current_index"]):
        return False
    for tab in data["tabs"]:
        if not (isinstance(tab, dict) and isinstance(tab.get("path"), str)):
            return False
        if any(field in tab and not _is_int(tab[field]) for field in ("line", "col")):
            return False
        if "encoding" in tab and not isinstance(tab["encoding"], str):
            return False
    return True


def save_named_session(name: str, main_window: "MainWindow") -> bool:
    """Salva la sessione corrente con il nome dato."""
    safe = _safe_session_name(name)
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
        atomic_write_json(path, data)
        return True
    except OSError:
        return False


def load_named_session(name: str, main_window: "MainWindow") -> bool:
    """Carica la sessione con il nome dato."""
    safe = _safe_session_name(name)
    if not safe:
        return False
    path = _sessions_dir() / f"{safe}.json"
    if not path.exists():
        return False
    data = load_json(path, validate=_valid_named_session)
    if not isinstance(data, dict):
        return False

    for tab in data["tabs"]:
        p = Path(tab.get("path", ""))
        if p.is_file():
            main_window.open_files([p])
            restore_cursor_after_load(
                main_window, p, tab.get("line", 0), tab.get("col", 0),
                positions_are_one_based=False,
            )

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
        self.setWindowTitle(tr("named_sessions.title"))
        self.setMinimumSize(380, 300)
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("named_sessions.label_saved")))

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        self._btn_save   = QPushButton(tr("named_sessions.btn_save"))
        self._btn_load   = QPushButton(tr("named_sessions.btn_load"))
        self._btn_delete = QPushButton(tr("named_sessions.btn_delete"))
        btn_row.addWidget(self._btn_save)
        btn_row.addWidget(self._btn_load)
        btn_row.addWidget(self._btn_delete)
        layout.addLayout(btn_row)

        close_btn = QPushButton(tr("named_sessions.btn_close"))
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
        name, ok = QInputDialog.getText(self, tr("named_sessions.save_title"), tr("named_sessions.save_prompt"))
        if ok and name.strip():
            if save_named_session(name.strip(), self._mw):
                self._refresh()
            else:
                QMessageBox.warning(self, tr("named_sessions.error_title"), tr("named_sessions.save_error"))

    def _on_load(self) -> None:
        name = self._selected_name()
        if not name:
            return
        if not load_named_session(name, self._mw):
            QMessageBox.warning(self, tr("named_sessions.error_title"), tr("named_sessions.load_error", name=name))
        else:
            self.accept()

    def _on_delete(self) -> None:
        name = self._selected_name()
        if not name:
            return
        r = QMessageBox.question(self, tr("named_sessions.delete_title"),
                                 tr("named_sessions.delete_confirm", name=name))
        if r == QMessageBox.StandardButton.Yes:
            delete_session(name)
            self._refresh()

"""
core/macro.py — Registrazione e riproduzione macro
NotePadPQ

Registra le azioni dell'utente (tasti, inserimenti) e le riproduce.
Le macro vengono salvate in JSON nella directory dati utente.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QInputDialog, QFileDialog

from core.platform import get_data_dir
from i18n.i18n import tr

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget


class MacroManager(QObject):
    """Singleton. Gestisce registrazione e riproduzione macro."""

    recording_started = pyqtSignal()
    recording_stopped = pyqtSignal(int)  # numero di azioni registrate
    macro_played      = pyqtSignal()

    _instance: Optional["MacroManager"] = None

    def __init__(self):
        super().__init__()
        self._recording  = False
        self._actions: list[dict] = []
        self._current_editor: Optional["EditorWidget"] = None

    @classmethod
    def instance(cls) -> "MacroManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _macros_dir(self) -> Path:
        p = get_data_dir() / "macros"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def is_recording(self) -> bool:
        return self._recording

    def start_recording(self, editor: Optional["EditorWidget"]) -> None:
        if self._recording or editor is None:
            return
        self._recording = True
        self._actions   = []
        self._current_editor = editor
        self.recording_started.emit()

    def stop_recording(self) -> None:
        if not self._recording:
            return
        self._recording = False
        self.recording_stopped.emit(len(self._actions))

    def _play_actions(self, editor) -> None:
        """Riproduce la lista di azioni sull'editor dato."""
        from PyQt6.QtCore import Qt as _Qt
        from PyQt6.Qsci import QsciScintilla
        for action in self._actions:
            t = action.get("type")
            try:
                if t == "insert":
                    editor.insert(action["text"])
                    # Sposta il cursore dopo il testo inserito
                    line, col = editor.getCursorPosition()
                    txt = action["text"]
                    if "\n" in txt:
                        lines = txt.split("\n")
                        editor.setCursorPosition(line + len(lines) - 1, len(lines[-1]))
                    else:
                        editor.setCursorPosition(line, col + len(txt))
                elif t == "backspace":
                    editor.SendScintilla(QsciScintilla.SCI_DELETEBACK)
                elif t == "delete":
                    editor.SendScintilla(QsciScintilla.SCI_CLEAR)
            except Exception:
                pass

    def play(self, editor: Optional["EditorWidget"]) -> None:
        if not editor or self._recording:
            return
        self._play_actions(editor)
        self.macro_played.emit()

    def play_n_times(self, editor: Optional["EditorWidget"], n: int) -> None:
        """Riproduce la macro N volte."""
        if not editor or self._recording or n < 1:
            return
        for _ in range(n):
            self._play_actions(editor)
        self.macro_played.emit()

    def has_macro(self) -> bool:
        """Restituisce True se c'è una macro registrata."""
        return len(self._actions) > 0

    def save_dialog(self, parent) -> None:
        name, ok = QInputDialog.getText(
            parent, tr("action.save_macro"), "Nome macro:"
        )
        if ok and name:
            self.save(name)

    def save(self, name: str) -> bool:
        safe = "".join(c for c in name if c.isalnum() or c in " _-")
        path = self._macros_dir() / f"{safe}.json"
        try:
            path.write_text(
                json.dumps({
                    "name": name,
                    "actions": self._actions,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            return True
        except Exception:
            return False

    def load_dialog(self, parent) -> None:
        path, _ = QFileDialog.getOpenFileName(
            parent, tr("action.load_macro"),
            str(self._macros_dir()), "JSON (*.json)"
        )
        if path:
            self.load(Path(path))

    def load(self, path: Path) -> bool:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._actions = data.get("actions", [])
            return True
        except Exception:
            return False

    def list_saved(self) -> list[str]:
        return [f.stem for f in sorted(self._macros_dir().glob("*.json"))]

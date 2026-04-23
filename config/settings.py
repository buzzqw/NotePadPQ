"""
config/settings.py — Wrapper QSettings
NotePadPQ

Centralizza la lettura/scrittura di tutte le preferenze persistenti.
Tutti i moduli leggono le preferenze da qui — mai da QSettings direttamente.
"""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import QSettings, QObject, pyqtSignal


class Settings(QObject):

    settings_changed = pyqtSignal(str, object)   # chiave, valore

    _instance: Optional["Settings"] = None

    # Valori default
    DEFAULTS: dict[str, Any] = {
        # Editor
        "editor/font_family":      None,    # None = auto da piattaforma
        "editor/font_size":        11,
        "editor/tab_width":        4,
        "editor/use_tabs":         False,
        "editor/auto_indent":      True,
        "editor/show_line_numbers":True,
        "editor/show_fold_margin": True,
        "editor/show_whitespace":  False,
        "editor/show_eol":         False,
        "editor/word_wrap":        False,
        "editor/show_minimap":     False,
        # Tema
        "theme/active":            "Dark",
        # File
        "file/default_encoding":   "UTF-8",
        "file/default_line_ending":"LF",
        "file/backup_on_save":     False,
        "file/trim_trailing":      False,
        "file/add_newline_eof":    True,
        "file/restore_session":    True,
        "file/recent_max":         20,
        # Autocompletamento
        "autocomplete/enabled":    True,
        "autocomplete/threshold":  2,
        "autocomplete/cross_tab":  False,
        "autocomplete/snippets":   True,
        "autocomplete/api_dict":   True,
        "autocomplete/lsp":        False,
        # Preview
        "preview/enabled":         False,
        "preview/delay_ms":        500,
        "preview/sync_cursor":     True,
        # Build
        "build/save_before":       True,
        # i18n
        "i18n/language":           "it",
        # Finestra
        "window/geometry":         None,
        "window/state":            None,
        "window/fullscreen":       False,
    }

    def __init__(self):
        super().__init__()
        self._qs = QSettings("NotePadPQ", "NotePadPQ")

    @classmethod
    def instance(cls) -> "Settings":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get(self, key: str, default: Any = None) -> Any:
        fallback = default if default is not None else self.DEFAULTS.get(key)
        value = self._qs.value(key, fallback)
        # QSettings restituisce stringhe — converti i bool
        if isinstance(fallback, bool) and isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        if isinstance(fallback, int) and isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return fallback
        return value

    def set(self, key: str, value: Any) -> None:
        self._qs.setValue(key, value)
        self.settings_changed.emit(key, value)

    def reload(self) -> None:
        self._qs.sync()
        self.settings_changed.emit("*", None)

    def reset_to_defaults(self) -> None:
        self._qs.clear()
        self.settings_changed.emit("*", None)

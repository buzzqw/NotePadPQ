"""
config/settings.py — Wrapper QSettings
NotePadPQ

Centralizza la lettura/scrittura di tutte le preferenze persistenti.
Tutti i moduli leggono le preferenze da qui — mai da QSettings direttamente.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject, QSettings, pyqtSignal

_DEFAULTS: dict[str, Any] = {
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
    "editor/vim_mode_enabled": False,
    # Tema
    "theme/active":            "Dark",
    # File
    "file/default_encoding":   "UTF-8",
    "file/default_line_ending":"LF",
    "file/backup_on_save":     False,
    "file/autobackup_enabled": False,
    "file/autosave_to_backup": False,
    "file/autobackup_interval": 5,
    "file/autobackup_dir":     "",
    "file/autobackup_max_per_file": 20,
    "file/autobackup_max_total": 200,
    "file/trim_trailing":      False,
    "file/add_newline_eof":    True,
    "file/restore_session":    True,
    "file/restore_unsaved":    True,
    # Caricamento differito dei tab di sessione (load-on-activation).
    "file/defer_session_tabs":      True,   # carica il contenuto solo all'attivazione
    "file/defer_tabs_threshold_mb": 4,      # differisce i file sotto questa soglia
    "file/prefetch_budget_mb":      256,    # budget RAM per il prefetch in idle
    "file/recent_max":         20,
    # File Browser: sincronizza la radice con la cartella del file attivo.
    "file_browser/follow_active_file": True,
    "search/auto_refresh_results": True,
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
    "preview/sync_highlight":  False,
    "preview/external_viewer_command": "",
    "rest/max_response_bytes": 50 * 1024 * 1024,
    # Build
    "build/save_before":       True,
    "build/keep_synctex":      True,
    "build/trigger_on_save":   False,
    "build/trigger_on_edit":   False,
    "build/trigger_on_edit_delay_ms": 900,
    "build/latex_auxiliary_auto": False,
    "build/output_max_lines":  10000,
    "build/timeout_seconds":    300,
    "build/unified_errors":    True,
    # i18n
    # None means no explicit user choice: select the first-run language from
    # the system locale in main.py rather than pinning new installs to Italian.
    "i18n/language":           None,
    # Finestra
    "window/geometry":         None,
    "window/state":            None,
    "window/fullscreen":       False,
    # Barre
    "view/toolbar":            True,
    "view/quick_search":       False,   # mini barra di ricerca nella toolbar
    "view/statusbar":          True,
    "view/split_sync_zoom":    False,
    # Controllo ortografico
    "spellcheck/enabled":      False,
    "spellcheck/language":     "it",
    # LanguageTool locale (plugin disattivato al primo avvio)
    "languagetool/enabled":    False,
    "languagetool/endpoint":   "http://127.0.0.1:8081/v2/check",
    "languagetool/command":    "languagetool",
    "languagetool/auto_start": True,
    "languagetool/language":   "it",
    "languagetool/max_chars":  100000,
    # LaTeX
    "latex/env_usage_counts":  "{}",  # JSON: {env_name: count} per ordinare il popup \begin{
    "latex/cwl_directories":    [],    # directory .cwl aggiuntive, in ordine di precedenza
    "latex/completion_usage_counts": "{}",  # JSON: frequenza dei completamenti scelti
    # Function List
    "function_list/latex_hidden_kinds": "",  # CSV: "subsubsection,command" ecc.
    "function_list/disabled_presets":   "",  # CSV: preset JSON disabilitati
    "function_list/hidden_kinds":       "{}",  # JSON: {lang: [hidden kinds]}
}


class Settings(QObject):

    settings_changed = pyqtSignal(str, object)   # chiave, valore

    _instance: Settings | None = None

    def __init__(self):
        super().__init__()
        self._qs = QSettings("NotePadPQ", "NotePadPQ")

    @classmethod
    def instance(cls) -> Settings:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get(self, key: str, default: Any = None) -> Any:
        fallback = default if default is not None else _DEFAULTS.get(key)
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

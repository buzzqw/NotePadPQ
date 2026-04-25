"""
core/session.py — Salvataggio e ripristino sessione
NotePadPQ

Salva e ripristina:
- File aperti (percorsi)
- Posizione cursore per ogni file
- Tab attivo
- Stato scroll per ogni editor
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from core.platform import get_config_dir

if TYPE_CHECKING:
    from ui.tab_manager import TabManager


class Session:

    _instance: Optional["Session"] = None

    def __init__(self):
        self._path = get_config_dir() / "session.json"

    @classmethod
    def instance(cls) -> "Session":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def save(self, tab_manager: "TabManager") -> None:
        """Salva la sessione corrente su disco."""
        data = {
            "current_index": tab_manager.currentIndex(),
            "tabs": [],
        }
        for editor in tab_manager.all_editors():
            if editor.file_path and editor.file_path.exists():
                line, col = editor.get_cursor_position_1based()
                data["tabs"].append({
                    "path":    str(editor.file_path),
                    "line":    line,
                    "col":     col,
                    "encoding": editor.encoding,
                })
        try:
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            print(f"[session] Errore salvataggio: {e}")

    def restore(self, main_window) -> bool:
        """
        Ripristina la sessione salvata.
        Restituisce True se almeno un file è stato aperto.
        """
        if not self._path.exists():
            return False
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return False

        tabs = data.get("tabs", [])
        opened = 0

        # Sopprime il ridisegno durante il caricamento batch: evita N repaint
        main_window.setUpdatesEnabled(False)
        try:
            for tab in tabs:
                p = Path(tab.get("path", ""))
                if p.exists():
                    main_window.open_files([p])
                    # Ripristina posizione cursore
                    editor = main_window._tab_manager.current_editor()
                    if editor:
                        line = tab.get("line", 1)
                        col  = tab.get("col", 1)
                        editor.go_to_line(line)
                        editor.setCursorPosition(line - 1, col - 1)
                    opened += 1
        finally:
            main_window.setUpdatesEnabled(True)

        # Ripristina tab attivo
        idx = data.get("current_index", 0)
        if 0 <= idx < main_window._tab_manager.count():
            main_window._tab_manager.setCurrentIndex(idx)

        return opened > 0

    def save_ui_state(self, main_window) -> None:
        """Salva tema, minimap, word wrap, profilo build attivo e layout dock/toolbar."""
        try:
            from config.themes import ThemeManager
            from core.build_manager import BuildManager
            from config.settings import Settings
            import json as _json

            state = {
                "active_theme":    ThemeManager.instance().active_name(),
                "minimap":         bool(main_window._actions.get("view_minimap") and
                                        main_window._actions["view_minimap"].isChecked()),
                "word_wrap":       bool(main_window._actions.get("view_word_wrap") and
                                        main_window._actions["view_word_wrap"].isChecked()),
                "active_profile":  BuildManager.instance()._active_profile or "",
                "symbol_panel":    bool(main_window._actions.get("view_symbol_panel") and
                                        main_window._actions["view_symbol_panel"].isChecked()),
                "file_browser":    bool(main_window._actions.get("view_file_browser") and
                                        main_window._actions["view_file_browser"].isChecked()),
                "build_panel":     hasattr(main_window, "_build_dock") and
                                   main_window._build_dock.isVisible(),
                "minimap_side":    Settings.instance().get("editor/minimap_side", "right"),
                "show_preview":    Settings.instance().get("editor/show_preview", False),
            }

            ui_path = self._path.parent / "ui_state.json"
            ui_path.write_text(
                _json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

            # Salva il layout completo dock/toolbar di QMainWindow —
            # include posizione, dimensioni e visibilità di tutti i QDockWidget
            # e QToolBar. QByteArray → base64 per serializzarlo in JSON.
            try:
                import base64
                layout_bytes = main_window.saveState().data()
                geom_bytes   = main_window.saveGeometry().data()
                layout_path  = self._path.parent / "window_layout.bin"
                geom_path    = self._path.parent / "window_geometry.bin"
                layout_path.write_bytes(layout_bytes)
                geom_path.write_bytes(geom_bytes)
            except Exception as le:
                print(f"[session] Layout dock non salvato: {le}")

        except Exception as e:
            print(f"[session] Errore salvataggio ui_state: {e}")

    def restore_ui_state(self, main_window) -> None:
        """Ripristina tema, minimap, word wrap, profilo build attivo e layout dock."""
        ui_path = self._path.parent / "ui_state.json"
        if not ui_path.exists():
            return
        try:
            import json as _json
            state = _json.loads(ui_path.read_text(encoding="utf-8"))
        except Exception:
            return

        # Tema
        theme = state.get("active_theme", "")
        if theme:
            try:
                from config.themes import ThemeManager
                tm = ThemeManager.instance()
                tm.set_active(theme)
                for ed in main_window._tab_manager.all_editors():
                    tm.apply_to_editor(ed, theme)
            except Exception:
                pass

        # Minimap
        minimap_side = state.get("minimap_side", "right")
        try:
            from config.settings import Settings
            Settings.instance().set("editor/minimap_side", minimap_side)
        except Exception:
            pass
        if state.get("minimap"):
            act = main_window._actions.get("view_minimap")
            if act:
                act.setChecked(True)
                main_window._tab_manager.toggle_minimap(True)

        # Word wrap
        if state.get("word_wrap"):
            act = main_window._actions.get("view_word_wrap")
            if act:
                act.setChecked(True)
                for ed in main_window._tab_manager.all_editors():
                    ed.set_word_wrap(True)

        # Profilo build attivo
        profile = state.get("active_profile", "")
        if profile:
            try:
                from core.build_manager import BuildManager
                bm = BuildManager.instance()
                if profile in bm._profiles:
                    bm._active_profile = profile
            except Exception:
                pass

        # Pannello struttura documento
        if state.get("symbol_panel"):
            act = main_window._actions.get("view_symbol_panel")
            if act:
                act.setChecked(True)
                if hasattr(main_window, "_symbol_dock"):
                    main_window._symbol_dock.show()

        # File browser
        if state.get("file_browser"):
            act = main_window._actions.get("view_file_browser")
            if act:
                act.setChecked(True)
                if hasattr(main_window, "_file_browser_dock"):
                    main_window._file_browser_dock.show()

        # Pannello build
        if state.get("build_panel"):
            if hasattr(main_window, "_build_dock"):
                main_window._build_dock.show()

        # Preview
        if state.get("show_preview"):
            try:
                from config.settings import Settings
                Settings.instance().set("editor/show_preview", True)
            except Exception:
                pass

        # Ripristina geometria e layout dock/toolbar.
        # Chiamato da main.py con QTimer(200ms) dopo win.show() —
        # a questo punto tutti i dock sono già inizializzati.
        try:
            from PyQt6.QtCore import QByteArray
            geom_path   = self._path.parent / "window_geometry.bin"
            layout_path = self._path.parent / "window_layout.bin"

            if geom_path.exists():
                geom_bytes = QByteArray(geom_path.read_bytes())
                main_window.restoreGeometry(geom_bytes)

            if layout_path.exists():
                layout_bytes = QByteArray(layout_path.read_bytes())
                main_window.restoreState(layout_bytes)
                # Sincronizza i checkmark del menu con lo stato reale dei dock
                self._sync_dock_actions(main_window)

        except Exception as le:
            print(f"[session] Layout dock non ripristinato: {le}")

    def _sync_dock_actions(self, main_window) -> None:
        """
        Dopo restoreState(), sincronizza i checkmark del menu Visualizza
        con la visibilità effettiva dei dock (che Qt ha ripristinato).
        """
        dock_action_map = {
            "_build_dock":        "view_build_panel",
            "_file_browser_dock": "view_file_browser",
            "_symbol_dock":       "view_symbol_panel",
            "_preview_dock":      "preview_toggle",
        }
        for dock_attr, action_key in dock_action_map.items():
            dock = getattr(main_window, dock_attr, None)
            act  = main_window._actions.get(action_key)
            if dock is not None and act is not None:
                act.blockSignals(True)
                act.setChecked(dock.isVisible())
                act.blockSignals(False)

    def clear(self) -> None:
        try:
            if self._path.exists():
                self._path.unlink()
        except Exception:
            pass

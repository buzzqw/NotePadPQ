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

from pathlib import Path
from typing import Optional, TYPE_CHECKING
from uuid import uuid4

from PyQt6.QtCore import QTimer

from core.persistence import atomic_write_bytes, atomic_write_json, atomic_write_text, load_json
from core.platform import get_config_dir

if TYPE_CHECKING:
    from ui.tab_manager import TabManager


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_session(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    if "current_index" in data and not _is_int(data["current_index"]):
        return False
    for key in ("tabs", "spreadsheets", "unsaved_buffers"):
        if key in data and not isinstance(data[key], list):
            return False
    for tab in data.get("tabs", []):
        if not (isinstance(tab, dict) and isinstance(tab.get("path"), str)):
            return False
        if any(field in tab and not _is_int(tab[field]) for field in ("line", "col")):
            return False
        if "encoding" in tab and not isinstance(tab["encoding"], str):
            return False
    for entry in data.get("spreadsheets", []):
        if not (isinstance(entry, dict) and isinstance(entry.get("path"), str)):
            return False
        if "delimiter" in entry and not isinstance(entry["delimiter"], str):
            return False
        if "encoding" in entry and not isinstance(entry["encoding"], str):
            return False
        if "first_row_header" in entry and not isinstance(entry["first_row_header"], bool):
            return False
    for entry in data.get("unsaved_buffers", []):
        if not (isinstance(entry, dict) and isinstance(entry.get("buffer_file"), str)):
            return False
        if any(field in entry and not _is_int(entry[field]) for field in ("line", "col")):
            return False
        if "encoding" in entry and not isinstance(entry["encoding"], str):
            return False
    return True


def _valid_ui_state(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    bool_keys = {"minimap", "word_wrap", "symbol_panel", "file_browser", "build_panel", "show_preview"}
    string_keys = {"active_theme", "active_profile", "minimap_side"}
    return (all(key not in data or isinstance(data[key], bool) for key in bool_keys)
            and all(key not in data or isinstance(data[key], str) for key in string_keys)
            and ("layout_version" not in data or _is_int(data["layout_version"])))


def restore_cursor_after_load(main_window, path: Path, line: int, col: int,
                              *, positions_are_one_based: bool = True) -> None:
    """Restore a cursor only after a potentially lazy document load completes."""
    def find_editor():
        for editor in main_window._tab_manager.all_editors():
            try:
                if editor.file_path and editor.file_path.resolve() == path.resolve():
                    return editor
            except OSError:
                continue
        return None

    def set_cursor() -> None:
        editor = find_editor()
        if editor is None:
            return
        target_line = max(0, line - 1) if positions_are_one_based else max(0, line)
        target_col = max(0, col - 1) if positions_are_one_based else max(0, col)
        editor.setCursorPosition(target_line, target_col)
        editor.ensureLineVisible(target_line)

    editor = find_editor()
    loader = getattr(main_window, "_lazy_loaders", {}).get(editor) if editor else None
    if loader is not None and hasattr(loader, "load_finished"):
        loader.load_finished.connect(set_cursor)
    else:
        QTimer.singleShot(0, set_cursor)


class Session:

    _instance: Optional["Session"] = None

    # Incrementare quando cambia la disposizione predefinita dei dock
    # (es. angoli/corner di QMainWindow) in modo che un layout salvato
    # con una versione precedente venga ignorato e si riparta dal nuovo
    # default, invece di riprodurre per sempre la vecchia disposizione.
    _DOCK_LAYOUT_VERSION = 2

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
            "spreadsheets": [],
            "unsaved_buffers": [],
        }

        # Cartella per i buffer non salvati — indipendente dal backup folder
        buffers_dir = self._path.parent / "unsaved_buffers"

        saved_buffer_names: set[str] = set()
        for editor in tab_manager.all_editors():
            if editor.file_path and editor.file_path.exists():
                line, col = editor.get_cursor_position_1based()
                data["tabs"].append({
                    "path":    str(editor.file_path),
                    "line":    line,
                    "col":     col,
                    "encoding": editor.encoding,
                })
            elif not editor.file_path:
                # Buffer non salvato: salva il contenuto in un file temporaneo
                content = editor.text()
                if not content:
                    continue
                try:
                    buffers_dir.mkdir(parents=True, exist_ok=True)
                    buf_path = buffers_dir / f"buffer_{uuid4().hex}.txt"
                    atomic_write_text(buf_path, content)
                    line, col = editor.get_cursor_position_1based()
                    data["unsaved_buffers"].append({
                        "buffer_file": buf_path.name,
                        "line":        line,
                        "col":         col,
                        "encoding":    editor.encoding,
                    })
                    saved_buffer_names.add(buf_path.name)
                except Exception as e:
                    print(f"[session] Buffer non salvato non persistito: {e}")
        if hasattr(tab_manager, "all_custom_tabs"):
            for widget, path in tab_manager.all_custom_tabs():
                if path and path.exists():
                    data["spreadsheets"].append({
                        "path":             str(path),
                        "delimiter":        getattr(widget, "_delimiter", ","),
                        "encoding":         getattr(widget, "_encoding", "utf-8-sig"),
                        "first_row_header": getattr(widget, "_first_row_header", True),
                    })
        try:
            atomic_write_json(self._path, data)
            # The manifest now points at the new buffers, so old ones can be removed.
            if buffers_dir.exists():
                for old in buffers_dir.glob("buffer_*.txt"):
                    if old.name not in saved_buffer_names:
                        old.unlink(missing_ok=True)
        except Exception as e:
            print(f"[session] Errore salvataggio: {e}")

    def restore(self, main_window) -> bool:
        """
        Ripristina la sessione salvata.
        Restituisce True se almeno un file è stato aperto.
        """
        if not self._path.exists():
            return False
        data = load_json(self._path, validate=_valid_session)
        if not isinstance(data, dict):
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
                    restore_cursor_after_load(
                        main_window, p, tab.get("line", 1), tab.get("col", 1),
                    )
                    opened += 1
        finally:
            main_window.setUpdatesEnabled(True)

        # Ripristina fogli di calcolo
        plugin = getattr(main_window, "_spreadsheet_plugin", None)
        if plugin is not None:
            for entry in data.get("spreadsheets", []):
                p = Path(entry.get("path", ""))
                if p.exists():
                    try:
                        plugin.open_spreadsheet_silent(
                            p,
                            delimiter=entry.get("delimiter", ","),
                            encoding=entry.get("encoding", "utf-8-sig"),
                            first_row_header=entry.get("first_row_header", True),
                        )
                        opened += 1
                    except Exception as e:
                        print(f"[session] Foglio non ripristinato {p}: {e}")

        # Ripristina buffer non salvati (documenti senza path su disco)
        try:
            from config.settings import Settings as _Settings
            restore_unsaved = _Settings.instance().get("file/restore_unsaved", True)
        except Exception:
            restore_unsaved = True

        if restore_unsaved:
            buffers_dir = self._path.parent / "unsaved_buffers"
            for entry in data.get("unsaved_buffers", []):
                buf_file = entry.get("buffer_file", "")
                if not buf_file:
                    continue
                buf_path = buffers_dir / buf_file
                if buf_path.parent != buffers_dir or not buf_path.exists():
                    continue
                try:
                    content = buf_path.read_text(encoding="utf-8")
                    if not content:
                        continue
                    editor = main_window._tab_manager.new_tab()
                    # Carica il contenuto senza resettare il flag modified
                    editor.blockSignals(True)
                    editor.setText(content)
                    editor.setModified(True)
                    editor.blockSignals(False)
                    editor.modified_changed.emit(True)
                    # Ripristina posizione cursore
                    line = entry.get("line", 1)
                    col  = entry.get("col", 1)
                    editor.setCursorPosition(max(0, line - 1), max(0, col - 1))
                    opened += 1
                except Exception as e:
                    print(f"[session] Buffer non salvato non ripristinato ({buf_file}): {e}")

        # Ripristina tab attivo
        idx = data.get("current_index", 0)
        if 0 <= idx < main_window._tab_manager.count():
            main_window._tab_manager.set_current_index(idx)

        return opened > 0

    def save_ui_state(self, main_window) -> None:
        """Salva tema, minimap, word wrap, profilo build attivo e layout dock/toolbar."""
        try:
            from config.themes import ThemeManager
            from core.build_manager import BuildManager
            from config.settings import Settings

            state = {
                "active_theme":    ThemeManager.instance().active_name(),
                "minimap":         bool(main_window._actions.get("view_minimap") and
                                        main_window._actions["view_minimap"].isChecked()),
                "word_wrap":       bool(main_window._actions.get("view_word_wrap") and
                                        main_window._actions["view_word_wrap"].isChecked()),
                "active_profile":  BuildManager.instance()._active_profile or "",
                "symbol_panel":    bool(main_window._actions.get("function_list") and
                                        main_window._actions["function_list"].isChecked()),
                "file_browser":    bool(main_window._actions.get("view_file_browser") and
                                        main_window._actions["view_file_browser"].isChecked()),
                "build_panel":     hasattr(main_window, "_build_dock") and
                                   main_window._build_dock.isVisible(),
                "minimap_side":    Settings.instance().get("editor/minimap_side", "right"),
                "show_preview":    Settings.instance().get("editor/show_preview", False),
                "layout_version":  self._DOCK_LAYOUT_VERSION,
            }

            ui_path = self._path.parent / "ui_state.json"
            atomic_write_json(ui_path, state)

            # Salva il layout completo dock/toolbar di QMainWindow —
            # include posizione, dimensioni e visibilità di tutti i QDockWidget
            # e QToolBar. QByteArray → base64 per serializzarlo in JSON.
            try:
                import base64
                layout_bytes = main_window.saveState().data()
                geom_bytes   = main_window.saveGeometry().data()
                layout_path  = self._path.parent / "window_layout.bin"
                geom_path    = self._path.parent / "window_geometry.bin"
                atomic_write_bytes(layout_path, layout_bytes)
                atomic_write_bytes(geom_path, geom_bytes)
            except Exception as le:
                print(f"[session] Layout dock non salvato: {le}")

        except Exception as e:
            print(f"[session] Errore salvataggio ui_state: {e}")

    def restore_ui_state(self, main_window) -> None:
        """Ripristina tema, minimap, word wrap, profilo build attivo e layout dock."""
        ui_path = self._path.parent / "ui_state.json"
        if not ui_path.exists():
            return
        state = load_json(ui_path, validate=_valid_ui_state)
        if not isinstance(state, dict):
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
        if state.get("minimap"):
            act = main_window._actions.get("view_minimap")
            if act:
                act.setChecked(True)
            if hasattr(main_window, "_toggle_minimap"):
                main_window._toggle_minimap(True)

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
            act = main_window._actions.get("function_list")
            if act:
                act.setChecked(True)
                if hasattr(main_window, "_function_list_dock"):
                    main_window._function_list_dock.show()

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

            # Un layout salvato da una versione precedente (corner dock
            # diversi) va ignorato: riprodurrebbe la vecchia disposizione
            # anche dopo un aggiornamento che cambia i default.
            saved_layout_version = state.get("layout_version", 1)
            if layout_path.exists() and saved_layout_version >= self._DOCK_LAYOUT_VERSION:
                layout_bytes = QByteArray(layout_path.read_bytes())
                main_window.restoreState(layout_bytes)
                # Sincronizza i checkmark del menu con lo stato reale dei dock
                self._sync_dock_actions(main_window)
                # restoreState() può alterare lo stato interno della toolbar;
                # forza un rebuild delle icone per garantirne la visibilità.
                try:
                    main_window._rebuild_toolbar()
                except Exception:
                    pass

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
            "_function_list_dock": "function_list",
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

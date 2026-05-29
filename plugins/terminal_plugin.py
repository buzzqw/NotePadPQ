"""
plugins/terminal_plugin.py — Plugin Terminale Dedicato
NotePadPQ

Aggiunge un pannello dock dedicato con un terminale integrato,
riutilizzando il TerminalPanel esistente (basato su xterm.js).

Funzionalità:
  - Pannello dock "Terminale" ancorable su tutti i lati
  - Sessione shell persistente e interattiva
  - Cambio automatico directory al file corrente (opzionale)
  - Azioni: Pulisci, Riavvia, Stop
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDockWidget, QLabel, QWidget

from plugins.base_plugin import BasePlugin
from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


class TerminalPlugin(BasePlugin):

    NAME        = "Terminal"
    VERSION     = "1.0"
    DESCRIPTION = "Pannello dock con terminale integrato (xterm.js + shell)."
    AUTHOR      = "NotePadPQ Team"

    def on_load(self, main_window: "MainWindow") -> None:
        super().on_load(main_window)

        self._panel = None
        self._panel_ready = False

        # Dock con placeholder — il TerminalPanel viene creato solo alla prima apertura
        # per evitare che l'inizializzazione di QWebEngineView/GL blocchi lo startup.
        self._dock = QDockWidget(tr("plugin.terminal.dock_title"), main_window)
        self._dock.setObjectName("TerminalPluginDock")
        self._dock.setWidget(QWidget())
        self._dock.setMinimumWidth(350)
        self._dock.setMinimumHeight(200)
        self._dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        main_window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._dock)
        self._dock.hide()

        self._dock.visibilityChanged.connect(self._on_dock_visibility)

        self.add_menu_action(
            main_window,
            "plugins",
            tr("plugin.terminal.menu"),
            lambda: self._dock.setVisible(not self._dock.isVisible()),
            shortcut="Ctrl+Alt+T",
            icon_key="plugin_terminal",
        )
        main_window._menus["plugins"].menuAction().setVisible(True)

    def _ensure_panel(self) -> None:
        """Crea TerminalPanel al primo accesso; mostra errore se WebEngine/GL non è disponibile."""
        if self._panel_ready:
            return
        self._panel_ready = True
        try:
            from ui.terminal_panel import TerminalPanel
            panel = TerminalPanel(self._mw)
            if panel.is_available():
                self._panel = panel
                self._dock.setWidget(panel)
            else:
                panel.deleteLater()
                self._dock.setWidget(self._no_gl_label())
        except Exception as e:
            print(f"[TerminalPlugin] init error: {e}")
            self._dock.setWidget(self._no_gl_label())

    def _no_gl_label(self) -> QLabel:
        lbl = QLabel(tr("plugin.terminal.no_gl"))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        return lbl

    def _on_dock_visibility(self, visible: bool) -> None:
        if not visible:
            return
        self._ensure_panel()
        if self._panel is None or not hasattr(self, "_mw"):
            return
        editor = self._mw._tab_manager.current_editor()
        if editor and getattr(editor, "file_path", None):
            self._panel.set_cwd_from_file(editor.file_path)

    def on_editor_changed(self, editor) -> None:
        if not hasattr(self, "_dock") or self._panel is None:
            return
        if self._dock.isVisible() and editor and getattr(editor, "file_path", None):
            self._panel.set_cwd_from_file(editor.file_path)

    def on_file_opened(self, path) -> None:
        if not hasattr(self, "_dock") or self._panel is None:
            return
        if self._dock.isVisible():
            from pathlib import Path
            self._panel.set_cwd_from_file(Path(path))

    def on_unload(self) -> None:
        if hasattr(self, "_dock"):
            self._dock.setParent(None)
            self._dock.deleteLater()
        super().on_unload()

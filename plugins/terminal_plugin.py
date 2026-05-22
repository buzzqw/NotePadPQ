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
from PyQt6.QtWidgets import QDockWidget

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

        # Istanzia il pannello terminale
        from ui.terminal_panel import TerminalPanel
        self._panel = TerminalPanel(main_window)

        # Crea il dock
        self._dock = QDockWidget(tr("plugin.terminal.dock_title"), main_window)
        self._dock.setObjectName("TerminalPluginDock")
        self._dock.setWidget(self._panel)
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

        # Aggiorna la directory del terminale quando il dock diventa visibile
        self._dock.visibilityChanged.connect(self._on_dock_visibility)

        # Voce nel menu Plugin
        self.add_menu_action(
            main_window,
            "plugins",
            tr("plugin.terminal.menu"),
            lambda: self._dock.setVisible(not self._dock.isVisible()),
            shortcut="Ctrl+Alt+T",
            icon_key="plugin_terminal",
        )
        main_window._menus["plugins"].menuAction().setVisible(True)

    def _on_dock_visibility(self, visible: bool) -> None:
        """Quando il dock diventa visibile sincronizza la directory con il file aperto."""
        if not visible:
            return
        if not hasattr(self, "_panel") or not hasattr(self, "_mw"):
            return
        editor = self._mw._tab_manager.current_editor()
        if editor and getattr(editor, "file_path", None):
            self._panel.set_cwd_from_file(editor.file_path)

    def on_editor_changed(self, editor) -> None:
        """Aggiorna la label della directory corrente quando si cambia tab (solo se visibile)."""
        if not hasattr(self, "_dock") or not hasattr(self, "_panel"):
            return
        if self._dock.isVisible() and editor and getattr(editor, "file_path", None):
            self._panel.set_cwd_from_file(editor.file_path)

    def on_file_opened(self, path) -> None:
        """Aggiorna la directory del terminale al file appena aperto (solo se visibile)."""
        if not hasattr(self, "_dock") or not hasattr(self, "_panel"):
            return
        if self._dock.isVisible():
            from pathlib import Path
            self._panel.set_cwd_from_file(Path(path))

    def on_unload(self) -> None:
        if hasattr(self, "_dock"):
            self._dock.setParent(None)
            self._dock.deleteLater()
        super().on_unload()

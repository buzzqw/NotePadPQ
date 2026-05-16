"""
plugins/db_plugin.py — Plugin Database
NotePadPQ

Menu: Plugin → Database → Nuova connessione / Connessioni salvate / Gestione driver
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from plugins.base_plugin import BasePlugin
from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


class DatabasePlugin(BasePlugin):

    NAME        = "Database"
    VERSION     = "1.0"
    DESCRIPTION = (
        "Browser e query editor per SQLite, PostgreSQL, MySQL/MariaDB, Oracle.\n"
        "I risultati vengono mostrati nel modulo Foglio di calcolo.\n"
        "Supporto AI: genera SQL da linguaggio naturale."
    )
    AUTHOR = "NotePadPQ Team"

    def on_load(self, main_window: "MainWindow") -> None:
        super().on_load(main_window)

        m = main_window._menus.get("plugins")
        if m is None:
            return

        from PyQt6.QtGui import QAction
        sub = m.addMenu(tr("plugin.db.menu", default="Database"))
        _icon = self.load_plugin_icon("plugin_db", main_window)
        if not _icon.isNull():
            sub.setIcon(_icon)
        self._register_icon(sub, "plugin_db", main_window)

        act_new = QAction(
            tr("plugin.db.new_connection", default="Nuova connessione…"), main_window)
        act_new.triggered.connect(self._action_new_connection)
        sub.addAction(act_new)
        self._menu_actions.append(act_new)

        act_saved = QAction(
            tr("plugin.db.saved_connections", default="Connessioni salvate…"), main_window)
        act_saved.triggered.connect(self._action_saved_connections)
        sub.addAction(act_saved)
        self._menu_actions.append(act_saved)

        sub.addSeparator()

        act_drivers = QAction(
            tr("plugin.db.manage_drivers", default="Gestione driver…"), main_window)
        act_drivers.triggered.connect(self._action_drivers)
        sub.addAction(act_drivers)
        self._menu_actions.append(act_drivers)

        main_window._db_plugin = self

    # ── Actions ───────────────────────────────────────────────────────────────

    def _action_new_connection(self) -> None:
        from ui.db_widget import DBConnectDialog, DBConnectionsManager
        dlg = DBConnectDialog(parent=self._mw)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        info = dlg.get_info()
        DBConnectionsManager.add(info)
        self.open_connection(info)

    def _action_saved_connections(self) -> None:
        from ui.db_widget import DBSavedConnectionsDialog
        dlg = DBSavedConnectionsDialog(parent=self._mw)
        dlg.connection_selected.connect(self.open_connection)
        dlg.exec()

    def _action_drivers(self) -> None:
        from ui.db_widget import DBDriverManagerDialog
        DBDriverManagerDialog(parent=self._mw).exec()

    def open_connection(self, conn_info: dict) -> None:
        """Apre un tab DBBrowserWidget per la connessione specificata."""
        from ui.db_widget import DBBrowserWidget

        # Controlla se già aperta in qualsiasi pannello
        sv = self._mw._tab_manager
        for panel in sv._panels():
            for widget, _ in panel.tab_manager.all_custom_tabs():
                if (isinstance(widget, DBBrowserWidget) and
                        widget._conn_info.get("name") == conn_info.get("name")):
                    sv._active = panel
                    idx = panel.tab_manager.indexOf(widget)
                    if idx >= 0:
                        panel.tab_manager.setCurrentIndex(idx)
                    return

        widget = DBBrowserWidget(conn_info, self._mw, parent=self._mw)
        title = conn_info.get('name', 'DB')
        sv.add_spreadsheet_tab(widget, title, None)

    def on_unload(self) -> None:
        if hasattr(self._mw, "_db_plugin"):
            del self._mw._db_plugin
        super().on_unload()

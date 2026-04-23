"""
plugins/base_plugin.py — Classe base per plugin
NotePadPQ

Ogni plugin deve estendere BasePlugin e implementare i metodi
on_load / on_unload. Può aggiungere voci di menu, toolbar, e
reagire agli eventi dell'editor.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ui.main_window import MainWindow


class BasePlugin:
    """
    Classe base astratta per i plugin NotePadPQ.

    Struttura minima di un plugin (file my_plugin.py in plugins/):

        from plugins.base_plugin import BasePlugin

        class MyPlugin(BasePlugin):
            NAME        = "Il mio plugin"
            VERSION     = "1.0"
            DESCRIPTION = "Fa cose fantastiche"
            AUTHOR      = "Nome Cognome"

            def on_load(self, main_window):
                action = self.add_menu_action(
                    main_window, "Strumenti", "Fai cose",
                    self.do_stuff
                )

            def do_stuff(self):
                editor = self._mw._tab_manager.current_editor()
                if editor:
                    editor.insert("Hello from plugin!")

            def on_unload(self):
                pass
    """

    NAME        = "Plugin senza nome"
    VERSION     = "0.0"
    DESCRIPTION = ""
    AUTHOR      = ""

    def __init__(self):
        self._mw: Optional["MainWindow"] = None
        self._menu_actions = []

    def on_load(self, main_window: "MainWindow") -> None:
        """Chiamato quando il plugin viene caricato. Override obbligatorio."""
        self._mw = main_window

    def on_unload(self) -> None:
        """Chiamato quando il plugin viene disabilitato/rimosso."""
        # Rimuove le voci di menu aggiunte
        for action in self._menu_actions:
            action.parent().removeAction(action)
        self._menu_actions.clear()

    def on_editor_changed(self, editor) -> None:
        """Chiamato quando l'utente cambia tab."""
        pass

    def on_file_opened(self, path) -> None:
        """Chiamato quando viene aperto un file."""
        pass

    def on_file_saved(self, path) -> None:
        """Chiamato quando viene salvato un file."""
        pass

    # ── Helper per aggiungere voci di menu ────────────────────────────────────

    def add_menu_action(self, main_window: "MainWindow",
                        menu_name: str, action_text: str,
                        slot, shortcut: str = "") -> None:
        """Aggiunge un'azione al menu specificato."""
        from PyQt6.QtGui import QAction
        menus = main_window._menus
        menu = menus.get(menu_name.lower())
        if menu is None:
            return None
        action = QAction(action_text, main_window)
        if shortcut:
            from PyQt6.QtGui import QKeySequence
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        self._menu_actions.append(action)
        return action

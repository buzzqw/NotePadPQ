"""
plugins/richtext_plugin.py — Plugin Editor Rich Text
NotePadPQ

Apre .docx, .odt, .rtf in un tab WYSIWYG basato su Jodit (QWebEngineView).
Attivazione automatica: i file richtext vengono intercettati da open_files().

Menu: Plugin → Editor Rich Text → Nuovo documento / Apri documento / Scarica dipendenze
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from plugins.base_plugin import BasePlugin
from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


_RICHTEXT_EXTS = frozenset({".doc", ".docx", ".odt", ".rtf", ".html", ".htm"})
_FILTER = (
    "Documenti (*.doc *.docx *.odt *.rtf *.html *.htm);;"
    "Word (*.doc *.docx);;"
    "OpenDocument (*.odt);;"
    "RTF (*.rtf);;"
    "HTML (*.html *.htm);;"
    "Tutti i file (*)"
)


class RichTextPlugin(BasePlugin):

    NAME        = "Editor Rich Text"
    VERSION     = "1.0"
    DESCRIPTION = (
        "Editor WYSIWYG per .docx, .odt, .rtf, .html basato su Jodit.\n"
        "Richiede PyQt6-WebEngine e, per i formati Office, mammoth/pandoc."
    )
    AUTHOR      = "NotePadPQ Team"

    def on_load(self, main_window: "MainWindow") -> None:
        super().on_load(main_window)
        self._unloading = False
        self._jodit_download = None
        self._jodit_callbacks = []
        self._jodit_notify = False

        m = main_window._menus.get("plugins")
        if m is None:
            return

        from PyQt6.QtGui import QAction

        menu_name = tr("plugin.richtext.menu", default="Editor Rich Text")
        sub = m.addMenu(menu_name)
        _icon = self.load_plugin_icon("plugin_richtext", main_window)
        if not _icon.isNull():
            sub.setIcon(_icon)
        self._register_icon(sub, "plugin_richtext", main_window)

        act_new = QAction(tr("plugin.richtext.new", default="Nuovo documento"), main_window)
        act_new.triggered.connect(self.new_document)
        sub.addAction(act_new)
        self._menu_actions.append(act_new)

        act_open = QAction(tr("plugin.richtext.open", default="Apri documento…"), main_window)
        act_open.triggered.connect(self._action_open)
        sub.addAction(act_open)
        self._menu_actions.append(act_open)

        sub.addSeparator()

        act_deps = QAction(tr("plugin.richtext.download_deps", default="Scarica dipendenze Jodit…"), main_window)
        act_deps.triggered.connect(self._download_deps)
        sub.addAction(act_deps)
        self._menu_actions.append(act_deps)

        m.menuAction().setVisible(True)
        main_window._richtext_plugin = self

    _FORMAT_WARNING_EXTS = frozenset({".doc", ".docx", ".odt", ".rtf"})

    def _maybe_show_format_warning(self, path: Path) -> None:
        from PyQt6.QtWidgets import QCheckBox
        from config.settings import Settings
        if path.suffix.lower() not in self._FORMAT_WARNING_EXTS:
            return
        if Settings.instance().get("richtext/format_warning_shown", False):
            return
        msg = QMessageBox(self._mw)
        msg.setWindowTitle(tr("plugin.richtext.format_warning_title", default="Avviso formattazione"))
        msg.setText(tr("plugin.richtext.format_warning_text",
                       default="L'apertura di file .doc, .docx e .odt potrebbe non preservare tutta la formattazione originale.\n"
                               "Tabelle complesse, stili, immagini e altre strutture potrebbero essere alterate o perdute.\n"
                               "Lo stesso vale per il salvataggio."))
        msg.setIcon(QMessageBox.Icon.Warning)
        cb = QCheckBox(tr("plugin.richtext.format_warning_dont_show", default="Non mostrare più questo avviso"))
        msg.setCheckBox(cb)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
        if cb.isChecked():
            Settings.instance().set("richtext/format_warning_shown", True)

    def open_document(self, path: Path) -> None:
        """Carica il file e apre un tab rich text. Chiamato da main_window.open_files."""
        if getattr(self, "_unloading", False):
            return
        from ui.richtext_widget import RichTextWidget, WEBENGINE_OK

        if not WEBENGINE_OK:
            QMessageBox.warning(
                self._mw, "NotePadPQ",
                tr("plugin.richtext.no_webengine",
                   default="PyQt6-WebEngine non è installato.\n"
                           "pip install PyQt6-WebEngine")
            )
            return

        # Controlla se già aperto
        existing = self._mw._tab_manager.find_tab_by_path(path)
        if existing is not None:
            self._mw._tab_manager.set_current_index(existing)
            return

        self._maybe_show_format_warning(path)

        if not self._ensure_jodit_then(lambda: self.open_document(path)):
            return

        widget = RichTextWidget(path, parent=self._mw)
        widget.convert_to_text.connect(self._open_as_text)
        widget.load_finished.connect(
            lambda ok, w=widget: self._on_load_finished(w, ok)
        )

        title = path.name
        self._mw._tab_manager.add_spreadsheet_tab(widget, title, path)

        if not widget.load_document(path):
            self._on_load_finished(widget, False)

    def new_document(self) -> None:
        """Apre un documento richtext vuoto."""
        if getattr(self, "_unloading", False):
            return
        from ui.richtext_widget import RichTextWidget, WEBENGINE_OK

        if not WEBENGINE_OK:
            QMessageBox.warning(
                self._mw, "NotePadPQ",
                tr("plugin.richtext.no_webengine",
                   default="PyQt6-WebEngine non è installato.\n"
                           "pip install PyQt6-WebEngine")
            )
            return

        if not self._ensure_jodit_then(self.new_document):
            return

        widget = RichTextWidget(None, parent=self._mw)
        widget.convert_to_text.connect(self._open_as_text)
        title = tr("plugin.richtext.new_doc_title", default="Nuovo documento")
        self._mw._tab_manager.add_spreadsheet_tab(widget, title, None)

    def _action_open(self) -> None:
        dialog_title = tr("plugin.richtext.open_dialog", default="Apri documento rich text")
        paths, _ = QFileDialog.getOpenFileNames(
            self._mw, dialog_title,
            str(Path.home()),
            _FILTER
        )
        for p in paths:
            self.open_document(Path(p))

    def _download_deps(self) -> None:
        from ui.richtext_widget import _JODIT_JS, _JODIT_CSS
        if _JODIT_JS.exists() and _JODIT_CSS.exists():
            QMessageBox.information(
                self._mw, "NotePadPQ",
                tr("plugin.richtext.deps_ok", default="Jodit è già disponibile.")
            )
            return
        self._start_jodit_download(True)

    def _ensure_jodit_then(self, callback) -> bool:
        from ui.richtext_widget import _JODIT_JS, _JODIT_CSS
        if _JODIT_JS.exists() and _JODIT_CSS.exists():
            return True
        self._start_jodit_download(False, callback)
        return False

    def _start_jodit_download(self, notify: bool, callback=None) -> None:
        if getattr(self, "_unloading", False):
            return
        from ui.richtext_widget import download_jodit
        if getattr(self, "_jodit_download", None) is not None:
            if callback is not None:
                self._jodit_callbacks.append(callback)
            self._jodit_notify = self._jodit_notify or notify
            return
        self._jodit_callbacks = [callback] if callback is not None else []
        self._jodit_notify = notify
        controller = download_jodit(self._mw)
        self._jodit_download = controller

        def _finished(ok: bool) -> None:
            self._jodit_download = None
            callbacks = self._jodit_callbacks
            self._jodit_callbacks = []
            notify_done = self._jodit_notify
            self._jodit_notify = False
            if getattr(self, "_unloading", False):
                return
            if ok and notify_done:
                QMessageBox.information(
                    self._mw, "NotePadPQ",
                    tr("plugin.richtext.deps_downloaded", default="Jodit scaricato con successo.")
                )
            if ok:
                for pending_callback in callbacks:
                    pending_callback()

        controller.finished.connect(_finished)

    def _on_load_finished(self, widget, ok: bool) -> None:
        if ok:
            return
        manager = self._mw._tab_manager
        if hasattr(manager, "_panels"):
            for panel in manager._panels():
                idx = panel.tab_manager.indexOf(widget)
                if idx >= 0:
                    panel.tab_manager._close_tab_at(idx)
                    return
        elif hasattr(manager, "_close_tab_at"):
            idx = manager.indexOf(widget)
            if idx >= 0:
                manager._close_tab_at(idx)

    def _open_as_text(self, content: str, suggested_name: str) -> None:
        if getattr(self, "_unloading", False):
            return
        ext = Path(suggested_name).suffix.lower()
        editor = self._mw._tab_manager.new_tab(template_ext=ext)
        editor.load_content(content)

    def on_unload(self) -> None:
        self._unloading = True
        self._jodit_callbacks = []
        self._jodit_notify = False
        controller = getattr(self, "_jodit_download", None)
        self._jodit_download = None
        if controller is not None:
            try:
                controller.finished.disconnect()
            except (TypeError, RuntimeError):
                pass
            controller.cancel()
        if hasattr(self._mw, "_richtext_plugin"):
            del self._mw._richtext_plugin
        super().on_unload()

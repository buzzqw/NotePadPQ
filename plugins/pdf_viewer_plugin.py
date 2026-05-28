"""
plugins/pdf_viewer_plugin.py — Plugin Visualizzatore PDF
NotePadPQ

Apre file .pdf in un tab di sola lettura usando QWebEngineView.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QMessageBox

from plugins.base_plugin import BasePlugin
from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


class PdfViewerPlugin(BasePlugin):

    NAME        = "Visualizzatore PDF"
    VERSION     = "1.0"
    DESCRIPTION = "Apre file .pdf in un tab di sola lettura (motore Chromium)."
    AUTHOR      = "NotePadPQ Team"

    def on_load(self, main_window: "MainWindow") -> None:
        super().on_load(main_window)

        m = main_window._menus.get("plugins")
        if m is None:
            return

        from PyQt6.QtGui import QAction
        sub = m.addMenu(tr("plugin.pdf.menu", default="Visualizzatore PDF"))
        _icon = self.load_plugin_icon("plugin_pdf", main_window)
        if not _icon.isNull():
            sub.setIcon(_icon)
        self._register_icon(sub, "plugin_pdf", main_window)

        act = QAction(tr("plugin.pdf.open", default="Apri PDF…"), main_window)
        act.triggered.connect(self._action_open)
        sub.addAction(act)
        self._menu_actions.append(act)

        main_window._pdf_plugin = self

    def open_document(self, path: Path) -> None:
        """Apre un PDF in un nuovo tab. Chiamato da main_window.open_files."""
        from ui.pdf_viewer_widget import PdfViewerWidget, FITZ_OK, WEBENGINE_OK

        if not FITZ_OK and not WEBENGINE_OK:
            QMessageBox.warning(
                self._mw, "NotePadPQ",
                tr("plugin.pdf.no_webengine",
                   default="PyMuPDF e PyQt6-WebEngine non sono installati.\n"
                           "pip install pymupdf  oppure  pip install PyQt6-WebEngine")
            )
            return

        existing = self._mw._tab_manager.find_tab_by_path(path)
        if existing is not None:
            self._mw._tab_manager.set_current_index(existing)
            return

        widget = PdfViewerWidget(path, parent=self._mw, main_window=self._mw)
        self._mw._tab_manager.add_spreadsheet_tab(widget, path.name, path)

    def _action_open(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        paths, _ = QFileDialog.getOpenFileNames(
            self._mw,
            tr("plugin.pdf.open_dialog", default="Apri PDF"),
            str(Path.home()),
            "PDF (*.pdf);;Tutti i file (*)"
        )
        for p in paths:
            self.open_document(Path(p))

    def on_unload(self) -> None:
        if hasattr(self._mw, "_pdf_plugin"):
            del self._mw._pdf_plugin
        super().on_unload()

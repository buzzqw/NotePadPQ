"""
plugins/spreadsheet_plugin.py — Plugin Foglio di Calcolo
NotePadPQ

Visualizza e modifica file CSV, XLSX, XLS, ODS in un tab dedicato.
CSV: wizard import per scegliere delimitatore, encoding e riga intestazione.
XLSX/ODS: caricamento diretto.
XLS: sola lettura (formato legacy).

Attivazione:
  Menu Plugin → Foglio di calcolo → Apri foglio...
  I file CSV/XLSX/XLS/ODS vengono aperti automaticamente come foglio.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from plugins.base_plugin import BasePlugin

if TYPE_CHECKING:
    from ui.main_window import MainWindow


_SPREADSHEET_EXTS = frozenset({".csv", ".tsv", ".xlsx", ".xlsm", ".xls", ".ods"})
_FILTER = (
    "Fogli di calcolo (*.csv *.tsv *.xlsx *.xlsm *.xls *.ods);;"
    "CSV (*.csv *.tsv);;"
    "Excel (*.xlsx *.xlsm *.xls);;"
    "ODS (*.ods);;"
    "Tutti i file (*)"
)


class SpreadsheetPlugin(BasePlugin):

    NAME        = "Foglio di Calcolo"
    VERSION     = "1.0"
    DESCRIPTION = "Apre CSV, XLSX, XLS, ODS come foglio di calcolo con editing e ordinamento."
    AUTHOR      = "NotePadPQ Team"

    def on_load(self, main_window: "MainWindow") -> None:
        super().on_load(main_window)

        m = main_window._menus.get("plugins")
        if m is None:
            return

        from PyQt6.QtGui import QAction
        sub = m.addMenu("📊 Foglio di calcolo")

        act_open = QAction("Apri foglio...", main_window)
        act_open.triggered.connect(self._action_open)
        sub.addAction(act_open)
        self._menu_actions.append(act_open)

        m.menuAction().setVisible(True)
        main_window._spreadsheet_plugin = self

    def open_spreadsheet(self, path: Path) -> None:
        """Carica il file e apre un tab spreadsheet. Chiamato da main_window.open_files."""
        from ui.spreadsheet_widget import SpreadsheetWidget, SpreadsheetIO, ImportWizardDialog

        # Controlla se già aperto
        existing = self._mw._tab_manager.find_tab_by_path(path)
        if existing is not None:
            self._mw._tab_manager.set_current_index(existing)
            return

        ext = path.suffix.lower()
        read_only = ext == ".xls"
        delimiter = ","
        encoding = "utf-8-sig"
        first_row_header = True

        if ext in (".csv", ".tsv"):
            # Mostra wizard
            dlg = ImportWizardDialog(path, self._mw)
            if dlg.exec() != ImportWizardDialog.DialogCode.Accepted:
                return
            delimiter, encoding, first_row_header = dlg.get_settings()
            headers, data, error = SpreadsheetIO.load(
                path, delimiter=delimiter, encoding=encoding,
                first_row_header=first_row_header
            )
        else:
            headers, data, error = SpreadsheetIO.load(path)

        if error:
            QMessageBox.critical(
                self._mw, "Foglio di calcolo",
                f"Impossibile aprire il file:\n{error}"
            )
            return

        if not headers and not data:
            # File vuoto: avvia con una griglia minimale
            headers = [f"Col{i+1}" for i in range(5)]
            data = [[""] * 5 for _ in range(20)]

        widget = SpreadsheetWidget(
            path, headers, data,
            read_only=read_only,
            delimiter=delimiter,
            encoding=encoding,
            first_row_header=first_row_header,
            parent=self._mw
        )
        self._mw._tab_manager.add_spreadsheet_tab(widget, path.name, path)

    def open_spreadsheet_silent(self, path: Path, delimiter: str = ",",
                                encoding: str = "utf-8-sig",
                                first_row_header: bool = True) -> None:
        """Riapre un foglio senza mostrare il wizard (usato da Session.restore)."""
        from ui.spreadsheet_widget import SpreadsheetWidget, SpreadsheetIO

        existing = self._mw._tab_manager.find_tab_by_path(path)
        if existing is not None:
            return

        ext = path.suffix.lower()
        read_only = ext == ".xls"

        if ext in (".csv", ".tsv"):
            headers, data, error = SpreadsheetIO.load(
                path, delimiter=delimiter, encoding=encoding,
                first_row_header=first_row_header
            )
        else:
            headers, data, error = SpreadsheetIO.load(path)

        if error or (not headers and not data):
            return

        widget = SpreadsheetWidget(
            path, headers, data,
            read_only=read_only,
            delimiter=delimiter,
            encoding=encoding,
            first_row_header=first_row_header,
            parent=self._mw
        )
        self._mw._tab_manager.add_spreadsheet_tab(widget, path.name, path)

    def _action_open(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self._mw, "Apri foglio di calcolo",
            str(Path.home()),
            _FILTER
        )
        for p in paths:
            self.open_spreadsheet(Path(p))

    def on_unload(self) -> None:
        if hasattr(self._mw, "_spreadsheet_plugin"):
            del self._mw._spreadsheet_plugin
        super().on_unload()

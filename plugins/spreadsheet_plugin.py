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

from PyQt6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from plugins.base_plugin import BasePlugin
from i18n.i18n import tr

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
        
        # Traduzione per il menu principale
        menu_name = tr("plugin.spreadsheet.menu", default="Foglio di calcolo")
        sub = m.addMenu(menu_name)
        _icon = self.load_plugin_icon("plugin_spreadsheet", main_window)
        if not _icon.isNull():
            sub.setIcon(_icon)
        self._register_icon(sub, "plugin_spreadsheet", main_window)

        # Traduzione per l'azione "Apri foglio"
        act_open_name = tr("plugin.spreadsheet.open", default="Apri foglio...")
        act_open = QAction(act_open_name, main_window)
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

        selected_sheet = None
        sheet_names: list[str] = []

        if ext in (".csv", ".tsv"):
            dlg = ImportWizardDialog(path, self._mw)
            if dlg.exec() != ImportWizardDialog.DialogCode.Accepted:
                return
            delimiter, encoding, first_row_header = dlg.get_settings()
            headers, data, error = SpreadsheetIO.load(
                path, delimiter=delimiter, encoding=encoding,
                first_row_header=first_row_header
            )
        else:
            sheet_names = SpreadsheetIO.get_sheet_names(path)
            if len(sheet_names) > 1:
                prompt = tr("plugin.spreadsheet.select_sheet_prompt", count=len(sheet_names), 
                            default="Il file contiene {count} fogli.\nScegli il foglio da aprire:")
                title = tr("plugin.spreadsheet.select_sheet_title", default="Seleziona foglio")
                
                chosen, ok = QInputDialog.getItem(
                    self._mw, title, prompt, sheet_names, 0, False
                )
                if not ok:
                    return
                selected_sheet = chosen
            headers, data, error = SpreadsheetIO.load(path, sheet=selected_sheet)

        if error and not headers:
            msg_title = tr("plugin.spreadsheet.title", default="Foglio di calcolo")
            msg_error = tr("plugin.spreadsheet.open_error", error=error, 
                           default="Impossibile aprire il file:\n{error}")
            QMessageBox.critical(self._mw, msg_title, msg_error)
            return

        if not headers and not data:
            headers = [f"Col{i+1}" for i in range(5)]
            data = [[""] * 5 for _ in range(20)]

        widget = SpreadsheetWidget(
            path, headers, data,
            read_only=read_only,
            delimiter=delimiter,
            encoding=encoding,
            first_row_header=first_row_header,
            sheet_names=sheet_names,
            current_sheet=selected_sheet or (sheet_names[0] if sheet_names else ""),
            parent=self._mw
        )
        widget.convert_to_text.connect(self._open_as_text)
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

        sheet_names: list[str] = []
        if ext in (".csv", ".tsv"):
            headers, data, error = SpreadsheetIO.load(
                path, delimiter=delimiter, encoding=encoding,
                first_row_header=first_row_header
            )
        else:
            sheet_names = SpreadsheetIO.get_sheet_names(path)
            headers, data, error = SpreadsheetIO.load(path)

        if error and not headers:
            return
        if not headers and not data:
            return

        widget = SpreadsheetWidget(
            path, headers, data,
            read_only=read_only,
            delimiter=delimiter,
            encoding=encoding,
            first_row_header=first_row_header,
            sheet_names=sheet_names,
            current_sheet=sheet_names[0] if sheet_names else "",
            parent=self._mw
        )
        widget.convert_to_text.connect(self._open_as_text)
        self._mw._tab_manager.add_spreadsheet_tab(widget, path.name, path)

    def _action_open(self) -> None:
        dialog_title = tr("plugin.spreadsheet.open_dialog", default="Apri foglio di calcolo")
        paths, _ = QFileDialog.getOpenFileNames(
            self._mw, dialog_title,
            str(Path.home()),
            _FILTER
        )
        for p in paths:
            self.open_spreadsheet(Path(p))

    def _open_as_text(self, content: str, suggested_name: str) -> None:
        """Apre il contenuto convertito in una nuova scheda editor."""
        ext = Path(suggested_name).suffix.lower()
        editor = self._mw._tab_manager.new_tab(template_ext=ext)
        editor.load_content(content)

    def on_unload(self) -> None:
        if hasattr(self._mw, "_spreadsheet_plugin"):
            del self._mw._spreadsheet_plugin
        super().on_unload()

"""
plugins/spreadsheet_plugin.py — Plugin Foglio di Calcolo
NotePadPQ

Visualizza e modifica file CSV, XLSX, XLS, ODS in un tab dedicato.
CSV: wizard import per scegliere delimitatore, encoding e riga intestazione.
XLSX/ODS: caricamento diretto.
XLS: sola lettura (formato legacy).

Attivazione:
  Menu Plugin → Foglio di calcolo → Apri foglio...
  I file TSV/XLSX/XLS/ODS vengono aperti automaticamente come foglio;
  per i CSV l'apertura automatica propone la modalità testo o foglio.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QProgressDialog

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
        self._active = True
        self._load_jobs: dict = {}
        self._loading_paths: set[Path] = set()

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
        from ui.spreadsheet_widget import ImportWizardDialog

        # Controlla se già aperto
        existing = self._mw._tab_manager.find_tab_by_path(path)
        if existing is not None:
            self._mw._tab_manager.set_current_index(existing)
            return
        if path in self._loading_paths:
            return

        ext = path.suffix.lower()
        read_only = ext == ".xls"
        delimiter = ","
        encoding = "utf-8-sig"
        first_row_header = True

        if ext in (".csv", ".tsv"):
            dlg = ImportWizardDialog(path, self._mw)
            if dlg.exec() != ImportWizardDialog.DialogCode.Accepted:
                return
            delimiter, encoding, first_row_header = dlg.get_settings()
        self._start_load(path, delimiter, encoding, first_row_header,
                         read_only, silent=False,
                         defer_multi_sheet=ext not in (".csv", ".tsv"))

    def open_spreadsheet_silent(self, path: Path, delimiter: str = ",",
                                encoding: str = "utf-8-sig",
                                first_row_header: bool = True) -> None:
        """Riapre un foglio senza mostrare il wizard (usato da Session.restore)."""
        existing = self._mw._tab_manager.find_tab_by_path(path)
        if existing is not None or path in self._loading_paths:
            return

        ext = path.suffix.lower()
        read_only = ext == ".xls"

        self._start_load(path, delimiter, encoding, first_row_header,
                         read_only, silent=True, defer_multi_sheet=False)

    def _start_load(self, path: Path, delimiter: str, encoding: str,
                    first_row_header: bool, read_only: bool, silent: bool,
                    defer_multi_sheet: bool, sheet: str | None = None) -> None:
        from ui.spreadsheet_widget import SpreadsheetLoadWorker

        if not self._active:
            return
        self._loading_paths.add(path)
        progress = QProgressDialog(
            tr("plugin.spreadsheet.loading", default="Caricamento foglio in corso..."),
            "", 0, 0, self._mw)
        progress.setWindowTitle(tr("plugin.spreadsheet.title", default="Foglio di calcolo"))
        progress.setMinimumDuration(150)
        progress.setAutoClose(False)
        progress.show()

        worker = SpreadsheetLoadWorker(
            path, delimiter, encoding, first_row_header, sheet,
            defer_multi_sheet)
        self._load_jobs[worker] = progress
        progress.canceled.connect(worker.requestInterruption)
        worker.loaded.connect(
            lambda headers, data, message, names, current, w=worker:
            self._on_load_ready(w, path, delimiter, encoding, first_row_header,
                                read_only, silent, headers, data, message,
                                names, current),
            type=Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(lambda w=worker, p=path: self._finish_load(w, p))
        worker.start()

    def _finish_load(self, worker, path: Path) -> None:
        progress = self._load_jobs.pop(worker, None)
        if progress is not None:
            progress.close()
            progress.deleteLater()
        if not any(getattr(job, "_path", None) == path for job in self._load_jobs):
            self._loading_paths.discard(path)
        worker.deleteLater()

    def _on_load_ready(self, worker, path: Path, delimiter: str, encoding: str,
                       first_row_header: bool, read_only: bool, silent: bool,
                       headers: list[str], data: list[list[str]], message: str,
                       sheet_names: list[str], current_sheet: str) -> None:
        if not self._active or worker.isInterruptionRequested():
            return
        progress = self._load_jobs.get(worker)
        if progress is not None:
            progress.close()

        # Primo passaggio XLSX/XLS multi-foglio: il worker ha ispezionato i nomi
        # senza materializzare inutilmente il foglio attivo.
        if sheet_names and len(sheet_names) > 1 and not headers and not message:
            prompt = tr("plugin.spreadsheet.select_sheet_prompt", count=len(sheet_names),
                        default="Il file contiene {count} fogli.\nScegli il foglio da aprire:")
            title = tr("plugin.spreadsheet.select_sheet_title", default="Seleziona foglio")
            chosen, ok = QInputDialog.getItem(
                self._mw, title, prompt, sheet_names, 0, False)
            if not ok:
                self._loading_paths.discard(path)
                return
            self._start_load(path, delimiter, encoding, first_row_header,
                             read_only, silent, False, chosen)
            return

        if message and not headers:
            if not silent:
                msg_error = tr("plugin.spreadsheet.open_error", error=message,
                               default="Impossibile aprire il file:\n{error}")
                QMessageBox.critical(
                    self._mw, tr("plugin.spreadsheet.title", default="Foglio di calcolo"),
                    msg_error)
            return
        if not headers and not data:
            headers = [f"Col{i+1}" for i in range(5)]
            data = [[""] * 5 for _ in range(20)]

        from ui.spreadsheet_widget import SpreadsheetWidget
        widget = SpreadsheetWidget(
            path, headers, data, read_only=read_only, delimiter=delimiter,
            encoding=encoding, first_row_header=first_row_header,
            sheet_names=sheet_names, current_sheet=current_sheet,
            take_data_ownership=True, parent=self._mw)
        widget.convert_to_text.connect(self._open_as_text)
        self._mw._tab_manager.add_spreadsheet_tab(widget, path.name, path)
        if message:
            QMessageBox.warning(
                self._mw, tr("plugin.spreadsheet.title", default="Foglio di calcolo"),
                message)

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
        self._active = False
        self._shutdown_workers()
        if hasattr(self._mw, "_spreadsheet_plugin"):
            del self._mw._spreadsheet_plugin
        super().on_unload()

    def _shutdown_workers(self) -> None:
        jobs = list(getattr(self, "_load_jobs", {}).items())
        for worker, progress in jobs:
            try:
                worker.loaded.disconnect()
            except (TypeError, RuntimeError):
                pass
            try:
                worker.finished.disconnect()
            except (TypeError, RuntimeError):
                pass
            progress.close()
            progress.deleteLater()
            worker.requestInterruption()
        for worker, _progress in jobs:
            worker.wait()
            worker.deleteLater()
        self._load_jobs.clear()
        self._loading_paths.clear()

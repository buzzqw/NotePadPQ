"""
ui/spreadsheet_widget.py — Visualizzatore/editor foglio di calcolo per NotePadPQ.
Supporta: CSV (con wizard import), XLSX, XLS (sola lettura), ODS.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, pyqtSignal,
)
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox,
    QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton,
    QSizePolicy, QTableView, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)


# ─── ImportWizardDialog ───────────────────────────────────────────────────────

class ImportWizardDialog(QDialog):
    """Wizard stile Excel per scegliere delimitatore, encoding e riga intestazione."""

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self._path = path
        self._raw_lines: list[str] = []
        self._encoding = "utf-8-sig"
        self._parsed_headers: list[str] = []
        self._parsed_data: list[list[str]] = []

        self.setWindowTitle(f"Importa: {path.name}")
        self.setMinimumSize(720, 560)
        self.resize(820, 620)

        self._detect_encoding()
        self._load_raw_lines()
        self._build_ui()
        self._auto_select_delimiter()
        self._update_preview()

    def _detect_encoding(self) -> None:
        try:
            import chardet
            raw = self._path.read_bytes()
            detected = chardet.detect(raw)
            self._encoding = detected.get("encoding") or "utf-8"
        except (ImportError, Exception):
            self._encoding = "utf-8-sig"

    def _load_raw_lines(self) -> None:
        try:
            with open(self._path, "r", encoding=self._encoding, errors="replace") as f:
                self._raw_lines = [f.readline() for _ in range(60)]
            self._raw_lines = [ln.rstrip("\n\r") for ln in self._raw_lines if ln.strip()]
        except Exception:
            self._raw_lines = []

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        grp_raw = QGroupBox("Anteprima testo grezzo (prime 15 righe)")
        raw_lay = QVBoxLayout(grp_raw)
        self._raw_view = QPlainTextEdit()
        self._raw_view.setReadOnly(True)
        self._raw_view.setMaximumHeight(110)
        self._raw_view.setFont(QFont("Monospace", 9))
        self._raw_view.setPlainText("\n".join(self._raw_lines[:15]))
        raw_lay.addWidget(self._raw_view)
        layout.addWidget(grp_raw)

        opts_row = QHBoxLayout()

        grp_delim = QGroupBox("Separatore di colonna")
        delim_lay = QVBoxLayout(grp_delim)
        self._delim_group = QButtonGroup(self)

        for label, char in [
            ("Virgola  ,", ","), ("Punto e virgola  ;", ";"),
            ("Tab  \\t", "\t"), ("Pipe  |", "|"),
            ("Backslash  \\", "\\"), ("Spazio   ", " "),
        ]:
            rb = QRadioButton(label)
            rb.setProperty("delim_char", char)
            rb.toggled.connect(self._update_preview)
            self._delim_group.addButton(rb)
            delim_lay.addWidget(rb)

        rb_custom = QRadioButton("Altro:")
        rb_custom.setProperty("delim_char", "__custom__")
        rb_custom.toggled.connect(self._update_preview)
        self._delim_group.addButton(rb_custom)
        custom_row = QHBoxLayout()
        custom_row.addWidget(rb_custom)
        self._custom_delim = QLineEdit()
        self._custom_delim.setMaximumWidth(40)
        self._custom_delim.setMaxLength(1)
        self._custom_delim.textChanged.connect(self._update_preview)
        custom_row.addWidget(self._custom_delim)
        custom_row.addStretch()
        delim_lay.addLayout(custom_row)
        grp_delim.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        opts_row.addWidget(grp_delim)

        grp_opts = QGroupBox("Opzioni aggiuntive")
        other_lay = QVBoxLayout(grp_opts)
        self._cb_header = QCheckBox("Prima riga come intestazione colonne")
        self._cb_header.setChecked(True)
        self._cb_header.toggled.connect(self._update_preview)
        other_lay.addWidget(self._cb_header)
        enc_row = QHBoxLayout()
        enc_row.addWidget(QLabel("Codifica testo:"))
        self._enc_combo = QComboBox()
        _ENCS = ["utf-8", "utf-8-sig", "latin-1", "windows-1252", "utf-16", "iso-8859-1"]
        self._enc_combo.addItems(_ENCS)
        dl = self._encoding.lower().replace("-", "")
        for i, e in enumerate(_ENCS):
            if e.replace("-", "") == dl:
                self._enc_combo.setCurrentIndex(i)
                break
        self._enc_combo.currentIndexChanged.connect(self._on_encoding_changed)
        enc_row.addWidget(self._enc_combo)
        enc_row.addStretch()
        other_lay.addLayout(enc_row)
        other_lay.addWidget(QLabel("(rilevata automaticamente)"))
        other_lay.addStretch()
        opts_row.addWidget(grp_opts)
        layout.addLayout(opts_row)

        grp_prev = QGroupBox("Anteprima tabella (prime 10 righe dati)")
        prev_lay = QVBoxLayout(grp_prev)
        self._preview_table = QTableWidget()
        self._preview_table.setMaximumHeight(180)
        self._preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._preview_table.setAlternatingRowColors(True)
        prev_lay.addWidget(self._preview_table)
        layout.addWidget(grp_prev)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Importa")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _auto_select_delimiter(self) -> None:
        if not self._raw_lines:
            return
        sample = "\n".join(self._raw_lines[:5])
        counts = {",": sample.count(","), ";": sample.count(";"),
                  "\t": sample.count("\t"), "|": sample.count("|"),
                  " ": sample.count(" ")}
        best = max(counts, key=counts.get)
        idx = {",": 0, ";": 1, "\t": 2, "|": 3, "\\": 4, " ": 5}.get(best, 0)
        buttons = self._delim_group.buttons()
        if idx < len(buttons):
            buttons[idx].setChecked(True)

    def _get_delimiter(self) -> str:
        for btn in self._delim_group.buttons():
            if btn.isChecked():
                d = btn.property("delim_char")
                return self._custom_delim.text() or "," if d == "__custom__" else d
        return ","

    def _on_encoding_changed(self) -> None:
        self._encoding = self._enc_combo.currentText()
        self._load_raw_lines()
        self._raw_view.setPlainText("\n".join(self._raw_lines[:15]))
        self._update_preview()

    def _update_preview(self) -> None:
        delim = self._get_delimiter()
        first_row_header = self._cb_header.isChecked()
        rows: list[list[str]] = []
        for line in self._raw_lines[:20]:
            if not line:
                continue
            try:
                parsed = next(csv.reader([line], delimiter=delim))
            except Exception:
                parsed = [line]
            rows.append(parsed)
        if not rows:
            self._parsed_headers = []
            self._parsed_data = []
            self._preview_table.clear()
            return
        if first_row_header:
            self._parsed_headers = rows[0]
            self._parsed_data = rows[1:]
        else:
            n = max((len(r) for r in rows), default=1)
            self._parsed_headers = [f"Col{i+1}" for i in range(n)]
            self._parsed_data = rows
        n_cols = len(self._parsed_headers)
        n_rows = min(len(self._parsed_data), 10)
        self._preview_table.clear()
        self._preview_table.setColumnCount(n_cols)
        self._preview_table.setRowCount(n_rows)
        self._preview_table.setHorizontalHeaderLabels(self._parsed_headers)
        for r, row in enumerate(self._parsed_data[:10]):
            for c in range(n_cols):
                val = row[c] if c < len(row) else ""
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._preview_table.setItem(r, c, item)
        self._preview_table.resizeColumnsToContents()

    def get_settings(self) -> tuple[str, str, bool]:
        return self._get_delimiter(), self._encoding, self._cb_header.isChecked()


# ─── _FilterProxy ─────────────────────────────────────────────────────────────

class _FilterProxy(QSortFilterProxyModel):
    """Filtro testo su colonna specifica o su tutte le colonne."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._col: int = -1    # -1 = tutte le colonne
        self._text: str = ""
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setDynamicSortFilter(True)

    def set_filter(self, col: int, text: str) -> None:
        self._col = col
        self._text = text.strip().lower()
        self.invalidateFilter()

    def clear(self) -> None:
        self._col = -1
        self._text = ""
        self.invalidateFilter()

    def active_col(self) -> int:
        return self._col

    def active_text(self) -> str:
        return self._text

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self._text:
            return True
        model = self.sourceModel()
        if self._col == -1:
            for c in range(model.columnCount()):
                idx = model.index(source_row, c, source_parent)
                val = (model.data(idx, Qt.ItemDataRole.DisplayRole) or "").lower()
                if self._text in val:
                    return True
            return False
        idx = model.index(source_row, self._col, source_parent)
        val = (model.data(idx, Qt.ItemDataRole.DisplayRole) or "").lower()
        return self._text in val

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        return False


# ─── SpreadsheetModel ─────────────────────────────────────────────────────────

class SpreadsheetModel(QAbstractTableModel):
    modified_changed = pyqtSignal(bool)

    def __init__(self, headers: list[str], data: list[list[str]], parent=None):
        super().__init__(parent)
        self._headers: list[str] = headers[:]
        self._data: list[list[str]] = [row[:] for row in data]
        self._modified = False
        self._sort_keys: list[tuple[int, Qt.SortOrder]] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._data)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if self._headers:
            return len(self._headers)
        return max((len(r) for r in self._data), default=0)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        if r >= len(self._data):
            return None
        row = self._data[r]
        value = row[c] if c < len(row) else ""
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return value
        if role == Qt.ItemDataRole.TextAlignmentRole:
            try:
                float(value.replace(",", "."))
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            except (ValueError, AttributeError):
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            name = self._headers[section] if section < len(self._headers) else str(section + 1)
            # Aggiunge indicatori di ordinamento
            for priority, (col, order) in enumerate(self._sort_keys):
                if col == section:
                    arrow = "↑" if order == Qt.SortOrder.AscendingOrder else "↓"
                    suffix = f" {arrow}" if len(self._sort_keys) == 1 else f" {arrow}{priority+1}"
                    return name + suffix
            return name
        return str(section + 1)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                Qt.ItemFlag.ItemIsEditable)

    def setData(self, index: QModelIndex, value: Any,
                role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        r, c = index.row(), index.column()
        while len(self._data[r]) <= c:
            self._data[r].append("")
        if self._data[r][c] != str(value):
            self._data[r][c] = str(value)
            self._set_modified(True)
            self.dataChanged.emit(index, index, [role])
        return True

    # ── Ordinamento ───────────────────────────────────────────────────────────

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """Compatibilità Qt — chiama sort_multi con chiave singola."""
        self.sort_multi([(column, order)])

    def sort_multi(self, keys: list[tuple[int, Qt.SortOrder]]) -> None:
        """Ordinamento multi-colonna. keys = [(col, order), ...] in priorità decrescente."""
        self.layoutAboutToBeChanged.emit()
        self._sort_keys = list(keys)

        def _key(row: list[str]) -> tuple:
            parts = []
            for col, order in keys:
                val = row[col] if col < len(row) else ""
                try:
                    num = float(val.replace(",", "."))
                    parts.append((0, num if order == Qt.SortOrder.AscendingOrder else -num))
                except (ValueError, AttributeError):
                    s = val.lower()
                    parts.append((1, s if order == Qt.SortOrder.AscendingOrder else
                                  "".join(chr(0x10FFFF - ord(c)) for c in s)))
            return tuple(parts)

        self._data.sort(key=_key)
        self.layoutChanged.emit()
        # Aggiorna header per mostrare indicatori
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.columnCount() - 1)

    def clear_sort(self) -> None:
        self._sort_keys = []
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.columnCount() - 1)

    # ── Struttura ─────────────────────────────────────────────────────────────

    def add_row(self) -> None:
        self.insert_row_at(len(self._data))

    def insert_row_at(self, position: int) -> None:
        n = self.columnCount()
        position = max(0, min(position, len(self._data)))
        self.beginInsertRows(QModelIndex(), position, position)
        self._data.insert(position, [""] * n)
        self.endInsertRows()
        self._set_modified(True)

    def add_column(self, name: str = "") -> None:
        col = self.columnCount()
        self.beginInsertColumns(QModelIndex(), col, col)
        self._headers.append(name or f"Col{col + 1}")
        for row in self._data:
            row.append("")
        self.endInsertColumns()
        self._set_modified(True)

    def delete_rows(self, rows: list[int]) -> None:
        for r in sorted(set(rows), reverse=True):
            if 0 <= r < len(self._data):
                self.beginRemoveRows(QModelIndex(), r, r)
                del self._data[r]
                self.endRemoveRows()
        self._set_modified(True)

    def reorder_columns(self, new_order: list[int]) -> None:
        """new_order[i] = indice vecchio della colonna che va in posizione i."""
        self.layoutAboutToBeChanged.emit()
        self._headers = [self._headers[i] if i < len(self._headers) else "" for i in new_order]
        self._data = [
            [row[i] if i < len(row) else "" for i in new_order]
            for row in self._data
        ]
        # Aggiorna sort keys se presenti
        old_to_new = {old: new for new, old in enumerate(new_order)}
        self._sort_keys = [
            (old_to_new[c], o) for c, o in self._sort_keys if c in old_to_new
        ]
        self._set_modified(True)
        self.layoutChanged.emit()

    def reorder_rows(self, new_order: list[int]) -> None:
        """new_order[i] = indice vecchio della riga che va in posizione i."""
        self.layoutAboutToBeChanged.emit()
        self._data = [self._data[i] for i in new_order if i < len(self._data)]
        self._set_modified(True)
        self.layoutChanged.emit()

    # ── Stato ─────────────────────────────────────────────────────────────────

    def is_modified(self) -> bool:
        return self._modified

    def mark_saved(self) -> None:
        self._set_modified(False)

    def get_headers(self) -> list[str]:
        return self._headers[:]

    def get_data(self) -> list[list[str]]:
        return [row[:] for row in self._data]

    def _set_modified(self, value: bool) -> None:
        if self._modified != value:
            self._modified = value
            self.modified_changed.emit(value)


# ─── SpreadsheetIO ────────────────────────────────────────────────────────────

class SpreadsheetIO:
    EXTENSIONS = frozenset({".csv", ".tsv", ".xlsx", ".xlsm", ".xls", ".ods"})

    @staticmethod
    def load(path: Path, delimiter: str = ",", encoding: str = "utf-8-sig",
             first_row_header: bool = True) -> tuple[list[str], list[list[str]], Optional[str]]:
        ext = path.suffix.lower()
        try:
            if ext in (".csv", ".tsv"):
                return SpreadsheetIO._load_csv(path, delimiter, encoding, first_row_header)
            elif ext in (".xlsx", ".xlsm"):
                return SpreadsheetIO._load_xlsx(path)
            elif ext == ".xls":
                return SpreadsheetIO._load_xls(path)
            elif ext == ".ods":
                return SpreadsheetIO._load_ods(path)
            else:
                return [], [], f"Formato non supportato: {ext}"
        except Exception as exc:
            return [], [], str(exc)

    @staticmethod
    def _load_csv(path: Path, delimiter: str, encoding: str,
                  first_row_header: bool) -> tuple[list[str], list[list[str]], Optional[str]]:
        with open(path, "r", encoding=encoding, newline="", errors="replace") as f:
            reader = csv.reader(f, delimiter=delimiter)
            rows = list(reader)
        if not rows:
            return [], [], None
        if first_row_header:
            headers = rows[0]
            data = rows[1:]
        else:
            n = max((len(r) for r in rows), default=1)
            headers = [f"Col{i + 1}" for i in range(n)]
            data = rows
        n = len(headers)
        data = [(row + [""] * n)[:n] for row in data]
        return headers, data, None

    @staticmethod
    def _load_xlsx(path: Path) -> tuple[list[str], list[list[str]], Optional[str]]:
        try:
            import openpyxl
        except ImportError:
            return [], [], "openpyxl non installato.  pip install openpyxl"
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = [[str(c.value) if c.value is not None else "" for c in row]
                for row in ws.iter_rows()]
        wb.close()
        if not rows:
            return [], [], None
        headers = rows[0]
        data = rows[1:]
        n = len(headers)
        data = [(r + [""] * n)[:n] for r in data]
        return headers, data, None

    @staticmethod
    def _load_xls(path: Path) -> tuple[list[str], list[list[str]], Optional[str]]:
        try:
            import xlrd
        except ImportError:
            return [], [], "xlrd non installato.  pip install xlrd"
        wb = xlrd.open_workbook(str(path))
        ws = wb.sheet_by_index(0)
        rows = [[str(ws.cell_value(r, c)) for c in range(ws.ncols)] for r in range(ws.nrows)]
        if not rows:
            return [], [], None
        headers = rows[0]
        data = rows[1:]
        n = len(headers)
        data = [(r + [""] * n)[:n] for r in data]
        return headers, data, None

    @staticmethod
    def _load_ods(path: Path) -> tuple[list[str], list[list[str]], Optional[str]]:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            rows = [[str(c.value) if c.value is not None else "" for c in row]
                    for row in ws.iter_rows()]
            wb.close()
            if rows:
                headers = rows[0]
                data = rows[1:]
                n = len(headers)
                data = [(r + [""] * n)[:n] for r in data]
                return headers, data, None
        except Exception:
            pass
        try:
            from odf.opendocument import load as ods_load
            from odf.table import Table, TableRow, TableCell
            from odf.text import P
            doc = ods_load(str(path))
            sheets = doc.spreadsheet.getElementsByType(Table)
            if not sheets:
                return [], [], "Nessun foglio trovato"
            rows = []
            for trow in sheets[0].getElementsByType(TableRow):
                row: list[str] = []
                for cell in trow.getElementsByType(TableCell):
                    ps = cell.getElementsByType(P)
                    row.append(str(ps[0]) if ps else "")
                rows.append(row)
            if not rows:
                return [], [], None
            headers = rows[0]
            data = rows[1:]
            n = len(headers)
            data = [(r + [""] * n)[:n] for r in data]
            return headers, data, None
        except ImportError:
            return [], [], "odfpy non installato.  pip install odfpy"

    @staticmethod
    def save(path: Path, headers: list[str], data: list[list[str]],
             delimiter: str = ",") -> Optional[str]:
        ext = path.suffix.lower()
        try:
            if ext in (".csv", ".tsv"):
                return SpreadsheetIO._save_csv(path, headers, data, delimiter)
            elif ext in (".xlsx", ".xlsm"):
                return SpreadsheetIO._save_xlsx(path, headers, data)
            elif ext == ".xls":
                new_path = path.with_suffix(".xlsx")
                err = SpreadsheetIO._save_xlsx(new_path, headers, data)
                return err or f"Salvato come XLSX: {new_path.name} (formato .xls non scrivibile)"
            elif ext == ".ods":
                return SpreadsheetIO._save_ods(path, headers, data)
            else:
                return f"Formato non supportato: {ext}"
        except Exception as exc:
            return str(exc)

    @staticmethod
    def _save_csv(path: Path, headers: list[str], data: list[list[str]],
                  delimiter: str) -> Optional[str]:
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter=delimiter)
            writer.writerow(headers)
            writer.writerows(data)
        return None

    @staticmethod
    def _save_xlsx(path: Path, headers: list[str], data: list[list[str]]) -> Optional[str]:
        try:
            import openpyxl
        except ImportError:
            return "openpyxl non installato.  pip install openpyxl"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(headers)
        for row in data:
            ws.append(row)
        wb.save(path)
        return None

    @staticmethod
    def _save_ods(path: Path, headers: list[str], data: list[list[str]]) -> Optional[str]:
        try:
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(headers)
            for row in data:
                ws.append(row)
            wb.save(path)
            return None
        except Exception:
            pass
        try:
            from odf.opendocument import OpenDocumentSpreadsheet
            from odf.table import Table, TableRow, TableCell
            from odf.text import P
            doc = OpenDocumentSpreadsheet()
            table = Table(name="Foglio1")
            doc.spreadsheet.addElement(table)
            for row_data in [headers] + data:
                tr = TableRow()
                table.addElement(tr)
                for val in row_data:
                    tc = TableCell()
                    tr.addElement(tc)
                    tc.addElement(P(text=str(val)))
            doc.save(str(path))
            return None
        except ImportError:
            return "odfpy non installato.  pip install odfpy"


# ─── SpreadsheetWidget ────────────────────────────────────────────────────────

class SpreadsheetWidget(QWidget):
    """Widget principale foglio di calcolo. Va inserito come tab nel TabManager."""

    modified_changed = pyqtSignal(bool)

    def __init__(self, path: Path, headers: list[str], data: list[list[str]],
                 read_only: bool = False, delimiter: str = ",",
                 encoding: str = "utf-8-sig", first_row_header: bool = True,
                 parent=None):
        super().__init__(parent)
        self.file_path = path
        self._read_only = read_only
        self._delimiter = delimiter
        self._encoding = encoding
        self._first_row_header = first_row_header
        self._sort_keys: list[tuple[int, Qt.SortOrder]] = []

        self._model = SpreadsheetModel(headers, data)
        self._model.modified_changed.connect(self._on_model_modified)

        self._proxy = _FilterProxy(self)
        self._proxy.setSourceModel(self._model)

        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = QHBoxLayout()

        self._file_label = QLabel(self.file_path.name)
        self._file_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        toolbar.addWidget(self._file_label)

        if self._read_only:
            ro_lbl = QLabel("⚠ Sola lettura (.xls)")
            ro_lbl.setStyleSheet("color: orange; font-size: 11px; margin-left: 12px;")
            toolbar.addWidget(ro_lbl)

        toolbar.addStretch()

        if not self._read_only:
            btn_ins_row = QPushButton("+ Riga")
            btn_ins_row.setFixedHeight(24)
            btn_ins_row.setToolTip(
                "Inserisce una riga vuota sotto l'ultima riga selezionata\n"
                "(in fondo se nessuna riga è selezionata)"
            )
            btn_ins_row.clicked.connect(self._add_row_below)
            toolbar.addWidget(btn_ins_row)

            btn_add_col = QPushButton("+ Colonna")
            btn_add_col.setFixedHeight(24)
            btn_add_col.setToolTip("Aggiunge una colonna vuota a destra")
            btn_add_col.clicked.connect(self._model.add_column)
            toolbar.addWidget(btn_add_col)

            btn_del_rows = QPushButton("− Righe sel.")
            btn_del_rows.setFixedHeight(24)
            btn_del_rows.setToolTip("Elimina le righe selezionate")
            btn_del_rows.clicked.connect(self._delete_selected_rows)
            toolbar.addWidget(btn_del_rows)

        btn_filter = QPushButton("🔍 Filtro")
        btn_filter.setFixedHeight(24)
        btn_filter.setCheckable(True)
        btn_filter.setToolTip("Mostra/nasconde la barra filtri (Ctrl+F)")
        btn_filter.clicked.connect(self._toggle_filter_bar)
        toolbar.addWidget(btn_filter)
        self._btn_filter = btn_filter

        if not self._read_only:
            self._btn_save = QPushButton("💾 Salva")
            self._btn_save.setFixedHeight(24)
            self._btn_save.setEnabled(False)
            self._btn_save.setToolTip("Salva il foglio sul disco (Ctrl+S)")
            self._btn_save.clicked.connect(self._save)
            toolbar.addWidget(self._btn_save)

        btn_save_as = QPushButton("📤 Esporta/Salva come…")
        btn_save_as.setFixedHeight(24)
        btn_save_as.setToolTip(
            "Salva il foglio in un nuovo file scegliendo il formato\n"
            "Conversione disponibile: CSV ↔ XLSX ↔ ODS ↔ TSV"
        )
        btn_save_as.clicked.connect(self._save_as)
        toolbar.addWidget(btn_save_as)

        layout.addLayout(toolbar)

        # ── Barra filtri (nascosta di default) ────────────────────────────────
        self._filter_bar = self._build_filter_bar()
        self._filter_bar.hide()
        layout.addWidget(self._filter_bar)

        # ── Tabella ───────────────────────────────────────────────────────────
        self._view = QTableView()
        self._view.setModel(self._proxy)
        self._view.setSortingEnabled(False)   # sort manuale via header click
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._view.setAlternatingRowColors(True)

        hh = self._view.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setStretchLastSection(True)
        hh.setSortIndicatorShown(True)
        hh.setSectionsMovable(True)
        hh.setToolTip(
            "Click: ordina per questa colonna\n"
            "Shift+Click: aggiunge colonna all'ordinamento\n"
            "Trascina: sposta la colonna"
        )
        hh.sectionClicked.connect(self._on_header_clicked)
        hh.sectionMoved.connect(self._on_column_moved)

        vh = self._view.verticalHeader()
        vh.setDefaultSectionSize(22)
        vh.setSectionsMovable(True)
        vh.setToolTip("Trascina per spostare la riga")
        vh.sectionMoved.connect(self._on_row_moved)

        if self._read_only:
            self._view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        else:
            self._view.setEditTriggers(
                QAbstractItemView.EditTrigger.DoubleClicked |
                QAbstractItemView.EditTrigger.EditKeyPressed |
                QAbstractItemView.EditTrigger.AnyKeyPressed
            )

        self._view.resizeColumnsToContents()
        self._view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        # Intercetta Ctrl+S e Ctrl+F direttamente sul viewport della tabella
        self._view.viewport().installEventFilter(self)
        layout.addWidget(self._view, 1)

        # ── Status bar ────────────────────────────────────────────────────────
        self._status = QLabel("Pronto")
        self._status.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(self._status)

    def _build_filter_bar(self) -> QWidget:
        """Barra filtro testo (aperta da pulsante 🔍 Filtro o Ctrl+F)."""
        bar = QWidget()
        bar.setStyleSheet("background: #2a2a3a; border-radius: 4px; padding: 2px;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(6)

        lay.addWidget(QLabel("🔍 Filtra:"))

        self._filter_col = QComboBox()
        self._filter_col.setFixedHeight(22)
        self._filter_col.setMinimumWidth(120)
        self._filter_col.addItem("— Tutte le colonne —", -1)
        for i, h in enumerate(self._model.get_headers()):
            self._filter_col.addItem(h, i)
        self._filter_col.currentIndexChanged.connect(lambda _: self._apply_filter())
        lay.addWidget(self._filter_col)

        self._filter_text = QLineEdit()
        self._filter_text.setFixedHeight(22)
        self._filter_text.setPlaceholderText("testo da cercare…")
        self._filter_text.setMinimumWidth(180)
        self._filter_text.setStyleSheet(
            "QLineEdit { background: #1e1e2e; color: #dddddd;"
            " border: 1px solid #555; border-radius: 2px; padding: 1px 4px; }"
        )
        self._filter_text.textChanged.connect(self._apply_filter)
        lay.addWidget(self._filter_text)

        self._filter_active_label = QLabel("")
        self._filter_active_label.setStyleSheet("color: #f0a030; font-size: 11px;")
        lay.addWidget(self._filter_active_label)

        lay.addStretch()

        btn_clear = QPushButton("✗ Pulisci")
        btn_clear.setFixedHeight(22)
        btn_clear.setToolTip("Rimuove il filtro attivo")
        btn_clear.clicked.connect(self._clear_filters)
        lay.addWidget(btn_clear)

        return bar

    # ── Slot toolbar / filtri ─────────────────────────────────────────────────

    def _toggle_filter_bar(self, checked: bool) -> None:
        if checked:
            self._filter_bar.show()
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self._filter_text.setFocus)
        else:
            self._filter_bar.hide()
            self._proxy.clear()
            self._update_filter_label()

    def _apply_filter(self) -> None:
        text = self._filter_text.text()
        col = self._filter_col.currentData()
        if text.strip():
            self._proxy.set_filter(col, text)
        else:
            self._proxy.clear()
        self._update_filter_label()

    def _clear_filters(self) -> None:
        self._filter_text.clear()
        self._proxy.clear()
        self._update_filter_label()

    def _update_filter_label(self) -> None:
        text = self._proxy.active_text()
        if text:
            col = self._proxy.active_col()
            headers = self._model.get_headers()
            col_name = ("Tutte" if col == -1
                        else headers[col] if col < len(headers) else str(col))
            n_vis = self._proxy.rowCount()
            n_tot = self._model.rowCount()
            self._filter_active_label.setText(
                f"Filtro: {col_name} «{text}»  ({n_vis}/{n_tot} righe)"
            )
        else:
            self._filter_active_label.setText("")

    # ── Event filter (Ctrl+S, Ctrl+F) ────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        from PyQt6.QtCore import QEvent
        if obj is self._view.viewport() and event.type() == QEvent.Type.KeyPress:
            mods = event.modifiers()
            ctrl = Qt.KeyboardModifier.ControlModifier
            if mods == ctrl:
                if event.key() == Qt.Key.Key_S:
                    if not self._read_only:
                        self._save()
                    return True
                if event.key() == Qt.Key.Key_F:
                    self._btn_filter.setChecked(True)
                    self._toggle_filter_bar(True)
                    return True
        return super().eventFilter(obj, event)

    # ── Ordinamento multi-colonna ─────────────────────────────────────────────

    def _on_header_clicked(self, col: int) -> None:
        from PyQt6.QtWidgets import QApplication
        modifiers = QApplication.keyboardModifiers()

        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            # Aggiunge/toglie questa colonna dall'ordinamento
            existing = [(c, o) for c, o in self._sort_keys if c == col]
            if existing:
                # Inverte l'ordine
                new_order = Qt.SortOrder.DescendingOrder if existing[0][1] == Qt.SortOrder.AscendingOrder else Qt.SortOrder.AscendingOrder
                self._sort_keys = [(c, new_order if c == col else o)
                                   for c, o in self._sort_keys]
            else:
                self._sort_keys.append((col, Qt.SortOrder.AscendingOrder))
        else:
            # Ordinamento singolo: primo click ASC, secondo DESC, terzo rimuove
            if len(self._sort_keys) == 1 and self._sort_keys[0][0] == col:
                if self._sort_keys[0][1] == Qt.SortOrder.AscendingOrder:
                    self._sort_keys = [(col, Qt.SortOrder.DescendingOrder)]
                else:
                    self._sort_keys = []
                    self._model.clear_sort()
                    self._view.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
                    return
            else:
                self._sort_keys = [(col, Qt.SortOrder.AscendingOrder)]

        if self._sort_keys:
            self._model.sort_multi(self._sort_keys)
            primary_col, primary_order = self._sort_keys[0]
            self._view.horizontalHeader().setSortIndicator(primary_col, primary_order)

    # ── Spostamento colonne/righe (drag header) ────────────────────────────────

    def _on_column_moved(self, logical: int, old_visual: int, new_visual: int) -> None:
        hh = self._view.horizontalHeader()
        n = self._model.columnCount()
        new_order = [hh.logicalIndex(i) for i in range(n)]
        hh.blockSignals(True)
        self._model.reorder_columns(new_order)
        for visual in range(n):
            cur = hh.visualIndex(visual)
            if cur != visual:
                hh.moveSection(cur, visual)
        hh.blockSignals(False)
        self._sort_keys = list(self._model._sort_keys)
        # Filtre testo rimane valido (usa indici logici che non cambiano)
        self._update_filter_label()

    def _on_row_moved(self, logical: int, old_visual: int, new_visual: int) -> None:
        vh = self._view.verticalHeader()
        n = self._model.rowCount()
        new_order = [vh.logicalIndex(i) for i in range(n)]
        vh.blockSignals(True)
        self._model.reorder_rows(new_order)
        for visual in range(n):
            cur = vh.visualIndex(visual)
            if cur != visual:
                vh.moveSection(cur, visual)
        vh.blockSignals(False)

    # ── Righe ─────────────────────────────────────────────────────────────────

    def _add_row_below(self) -> None:
        sel = self._view.selectionModel().selectedIndexes()
        if sel:
            max_proxy_row = max(idx.row() for idx in sel)
            src_idx = self._proxy.mapToSource(self._proxy.index(max_proxy_row, 0))
            insert_pos = src_idx.row() + 1
        else:
            insert_pos = self._model.rowCount()
        self._model.insert_row_at(insert_pos)

    def _delete_selected_rows(self) -> None:
        sel = self._view.selectionModel().selectedIndexes()
        if not sel:
            return
        proxy_rows = {idx.row() for idx in sel}
        source_rows = []
        for pr in proxy_rows:
            src = self._proxy.mapToSource(self._proxy.index(pr, 0))
            source_rows.append(src.row())
        self._model.delete_rows(source_rows)

    # ── Selezione / Status ────────────────────────────────────────────────────

    def _on_selection_changed(self) -> None:
        sel = self._view.selectionModel().selectedIndexes()
        if not sel:
            self._status.setText("Pronto")
            return
        rows = {idx.row() for idx in sel}
        cols = {idx.column() for idx in sel}
        nums: list[float] = []
        for idx in sel:
            src = self._proxy.mapToSource(idx)
            v = self._model.data(src, Qt.ItemDataRole.DisplayRole)
            if v:
                try:
                    nums.append(float(v.replace(",", ".")))
                except (ValueError, AttributeError):
                    pass
        parts = [f"Selezione: {len(rows)}r × {len(cols)}c ({len(sel)} celle)"]
        if nums:
            parts += [
                f"Somma: {sum(nums):.6g}",
                f"Media: {sum(nums)/len(nums):.6g}",
                f"Min: {min(nums):.6g}",
                f"Max: {max(nums):.6g}",
                f"Num: {len(nums)}",
            ]
        self._status.setText("   |   ".join(parts))

    # ── Salvataggio ───────────────────────────────────────────────────────────

    def _on_model_modified(self, modified: bool) -> None:
        if not self._read_only:
            self._btn_save.setEnabled(modified)
        self.modified_changed.emit(modified)

    def _save(self) -> None:
        if self._read_only:
            # XLS sola lettura: offri salva-come
            self._save_as()
            return
        err = SpreadsheetIO.save(
            self.file_path,
            self._model.get_headers(),
            self._model.get_data(),
            self._delimiter,
        )
        if err:
            QMessageBox.warning(self, "Errore salvataggio", err)
        else:
            self._model.mark_saved()

    def _save_as(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        _FILTER = (
            "CSV (*.csv);;"
            "Excel XLSX (*.xlsx);;"
            "ODS LibreOffice (*.ods);;"
            "TSV (*.tsv)"
        )
        default = str(self.file_path.with_suffix(".csv")
                      if self._read_only else self.file_path)
        dest, _ = QFileDialog.getSaveFileName(
            self, "Salva foglio come…", default, _FILTER
        )
        if not dest:
            return
        dest_path = Path(dest)

        # Scegli delimiter per CSV/TSV
        delim = "\t" if dest_path.suffix.lower() == ".tsv" else self._delimiter

        err = SpreadsheetIO.save(
            dest_path,
            self._model.get_headers(),
            self._model.get_data(),
            delim,
        )
        if err:
            QMessageBox.warning(self, "Errore salvataggio", err)
        else:
            # Aggiorna il widget per puntare al nuovo file
            self.file_path = dest_path
            self._delimiter = delim
            self._read_only = False
            self._file_label.setText(dest_path.name)
            self._model.mark_saved()

    # ── API pubblica ──────────────────────────────────────────────────────────

    def is_modified(self) -> bool:
        return self._model.is_modified()

    def save(self) -> bool:
        self._save()
        return not self._model.is_modified()

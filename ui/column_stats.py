"""
ui/column_stats.py — Column Statistics
NotePadPQ

Analisi statistica dei numeri presenti nel testo selezionato.
Stile Notepad++ "Column Statistics".

Funzionalità:
  - Conta, Somma, Media, Mediana, Moda
  - Min, Max, Range
  - Deviazione standard, Varianza
  - Funziona su selezione normale o selezione rettangolare (colonna)
  - Riconosce interi, decimali (virgola o punto), notazione scientifica
  - Risultati copiabili negli appunti

Integrazione:
  Strumenti → 📊 Column Statistics…  (Ctrl+Alt+S)
  oppure chiamata diretta: ColumnStatsDialog(editor, parent).exec()
"""

from __future__ import annotations

import re
import math
import statistics
from typing import List, Optional, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QLabel,
    QDialogButtonBox, QHeaderView, QApplication,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget


# ─── Estrazione numeri ────────────────────────────────────────────────────────

_NUMBER_RE = re.compile(
    r"[+-]?"                          # segno opzionale
    r"(?:"
    r"\d+\.?\d*"                      # 42 o 3.14
    r"|"
    r"\.\d+"                          # .5
    r")"
    r"(?:[eE][+-]?\d+)?"              # esponente opzionale
)


def extract_numbers(text: str) -> List[float]:
    """Estrae tutti i numeri dal testo, sostituendo la virgola col punto."""
    # Normalizza separatore decimale italiano (3,14 → 3.14)
    # ma non confonde i separatori delle migliaia (1.000 → non è 1000)
    normalized = re.sub(r"(\d),(\d)", r"\1.\2", text)
    results = []
    for m in _NUMBER_RE.finditer(normalized):
        try:
            results.append(float(m.group()))
        except ValueError:
            pass
    return results


# ─── Calcolo statistiche ──────────────────────────────────────────────────────

def compute_stats(numbers: List[float]) -> dict:
    if not numbers:
        return {}

    n      = len(numbers)
    total  = sum(numbers)
    mean   = total / n
    mn     = min(numbers)
    mx     = max(numbers)
    rng    = mx - mn

    sorted_n = sorted(numbers)
    if n % 2 == 1:
        median = sorted_n[n // 2]
    else:
        median = (sorted_n[n // 2 - 1] + sorted_n[n // 2]) / 2

    variance = sum((x - mean) ** 2 for x in numbers) / n
    std_dev  = math.sqrt(variance)

    # Moda: valore più frequente (arrotondato a 6 cifre per evitare floating noise)
    freq: dict[float, int] = {}
    for v in numbers:
        k = round(v, 6)
        freq[k] = freq.get(k, 0) + 1
    max_freq = max(freq.values())
    modes = [k for k, c in freq.items() if c == max_freq]
    mode_str = ", ".join(f"{m:g}" for m in modes[:3])
    if len(modes) > 3:
        mode_str += "…"

    return {
        "Conteggio":           n,
        "Somma":               total,
        "Media":               mean,
        "Mediana":             median,
        "Moda":                mode_str,
        "Minimo":              mn,
        "Massimo":             mx,
        "Range":               rng,
        "Deviazione standard": std_dev,
        "Varianza":            variance,
    }


def _fmt(v) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, int):
        return f"{v:,}"
    # Usa g per togliere zeri superflui, poi aggiunge separatori migliaia
    s = f"{v:.6g}"
    # Se c'è un punto decimale, non aggiungere separatori (troppo complesso)
    return s


# ─── Dialog ───────────────────────────────────────────────────────────────────

class ColumnStatsDialog(QDialog):

    def __init__(self, editor: "EditorWidget", parent=None):
        super().__init__(parent)
        self.setWindowTitle("📊 Column Statistics")
        self.resize(420, 380)
        self._editor = editor
        self._build_ui()
        self._compute()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Info selezione
        self._info = QLabel("")
        self._info.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(self._info)

        # Tabella risultati
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Statistica", "Valore"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._table.setAlternatingRowColors(True)
        self._table.setFont(QFont("Monospace", 10))
        layout.addWidget(self._table, 1)

        # Pulsanti
        btns = QHBoxLayout()
        btn_copy = QPushButton("📋 Copia tutto")
        btn_copy.clicked.connect(self._copy_all)
        btns.addWidget(btn_copy)
        btns.addStretch()
        btn_close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_close.rejected.connect(self.accept)
        btns.addWidget(btn_close)
        layout.addLayout(btns)

    def _compute(self) -> None:
        ed = self._editor

        if ed.hasSelectedText():
            text = ed.selectedText()
            sel_info = f"Selezione: {len(text)} caratteri"
        else:
            text = ed.text()
            sel_info = "Intero documento"

        numbers = extract_numbers(text)
        stats   = compute_stats(numbers)

        self._info.setText(
            f"{sel_info}  —  {len(numbers)} numeri trovati"
        )

        self._table.setRowCount(0)

        if not stats:
            row = self._table.rowCount()
            self._table.insertRow(row)
            item = QTableWidgetItem("Nessun numero trovato")
            item.setForeground(QColor("#888"))
            self._table.setItem(row, 0, item)
            return

        _HIGHLIGHT = {"Media", "Somma", "Conteggio"}

        for label, value in stats.items():
            row = self._table.rowCount()
            self._table.insertRow(row)

            lbl_item = QTableWidgetItem(label)
            val_item = QTableWidgetItem(_fmt(value))
            val_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

            if label in _HIGHLIGHT:
                for item in (lbl_item, val_item):
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)

            self._table.setItem(row, 0, lbl_item)
            self._table.setItem(row, 1, val_item)

        self._stats = stats

    def _copy_all(self) -> None:
        lines = []
        for row in range(self._table.rowCount()):
            lbl = self._table.item(row, 0)
            val = self._table.item(row, 1)
            if lbl and val:
                lines.append(f"{lbl.text():<25}{val.text()}")
        QApplication.clipboard().setText("\n".join(lines))
        self.setWindowTitle("📊 Column Statistics  (copiato)")

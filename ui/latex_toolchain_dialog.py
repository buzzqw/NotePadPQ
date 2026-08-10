"""Dialogo per verificare gli strumenti LaTeX disponibili."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core.latex_toolchain import ToolInfo, detect_latex_toolchain


class _ToolchainWorker(QThread):
    completed = pyqtSignal(object)

    def __init__(self, path: str | None, context: str | None) -> None:
        super().__init__()
        self._path = path
        self._context = context

    def run(self) -> None:
        self.completed.emit(
            detect_latex_toolchain(path=self._path, context=self._context, refresh=True)
        )


class LatexToolchainDialog(QDialog):
    """Mostra disponibilita, percorso e versione degli strumenti LaTeX."""

    def __init__(self, project_file: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LaTeX toolchain")
        self.setMinimumSize(720, 500)
        self._project_file = project_file
        self._worker: _ToolchainWorker | None = None
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self._summary = QLabel("Verifica strumenti in corso…")
        self._summary.setStyleSheet("color: #9cdcfe;")
        layout.addWidget(self._summary)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Tool", "Stato", "Percorso", "Versione"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, 1)

        buttons = QHBoxLayout()
        self._refresh_button = QPushButton("Aggiorna")
        self._refresh_button.clicked.connect(self._refresh)
        buttons.addWidget(self._refresh_button)
        buttons.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        close.accepted.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _refresh(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        context = str(self._project_file) if self._project_file else None
        self._refresh_button.setEnabled(False)
        self._summary.setText("Verifica strumenti in corso…")
        self._worker = _ToolchainWorker(None, context)
        self._worker.completed.connect(self._show_report)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _show_report(self, report: dict[str, ToolInfo]) -> None:
        self._table.setRowCount(0)
        available = 0
        for info in report.values():
            row = self._table.rowCount()
            self._table.insertRow(row)
            values = [
                info.name,
                info.status,
                info.path or "non trovato",
                info.version or "",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 1:
                    item.setForeground(
                        QColor("#4ec9b0" if info.status == "available" else
                               ("#ffcc00" if info.available else "#f44747"))
                    )
                self._table.setItem(row, column, item)
            if info.status == "available":
                available += 1
        self._summary.setText(f"{available}/{len(report)} strumenti disponibili")
        self._refresh_button.setEnabled(True)

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait()
        super().closeEvent(event)


__all__ = ["LatexToolchainDialog"]

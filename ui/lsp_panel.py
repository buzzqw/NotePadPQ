"""
ui/lsp_panel.py — Pannello Diagnostics LSP
NotePadPQ

Mostra errori/warning emessi dai Language Server (publishDiagnostics).
Click doppio → apre il file alla riga esatta.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt

from i18n.i18n import tr
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTreeWidget, QTreeWidgetItem,
)

if TYPE_CHECKING:
    from ui.main_window import MainWindow

# Severity LSP → (label, colore)
_SEV = {1: ("ERR",  "#f44747"), 2: ("WARN", "#ffcc00"), 3: ("INFO", "#9cdcfe"), 4: ("HINT", "#858585")}


class DiagnosticsPanel(QWidget):

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self._mw = main_window
        self._data: dict[str, list] = {}  # uri → list of diag
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar = QHBoxLayout()
        bar.setContentsMargins(4, 2, 4, 2)
        self._lbl_count = QLabel(tr("lsp_panel.no_problems"))
        self._lbl_count.setStyleSheet("color: #858585; font-size: 11px;")
        btn_clear = QPushButton(tr("button.clear"))
        btn_clear.setFixedWidth(60)
        btn_clear.clicked.connect(self._clear)
        bar.addWidget(self._lbl_count)
        bar.addStretch()
        bar.addWidget(btn_clear)
        layout.addLayout(bar)

        self._tree = QTreeWidget()
        self._tree.setStyleSheet("""
            QTreeWidget {
                background-color: #1e1e1e; color: #d4d4d4;
                border: none; alternate-background-color: #252526;
                selection-background-color: #264f78;
            }
            QHeaderView::section {
                background-color: #2d2d2d; color: #cccccc;
                border: 1px solid #3c3c3c; padding: 3px;
            }
        """)
        self._tree.setAlternatingRowColors(True)
        self._tree.setHeaderLabels(["", "File", "Riga", "Messaggio"])
        self._tree.setColumnWidth(0, 42)
        self._tree.setColumnWidth(1, 220)
        self._tree.setColumnWidth(2, 50)
        self._tree.itemDoubleClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree, 1)

    def update_diagnostics(self, uri: str, diags: list) -> None:
        self._data[uri] = diags
        self._rebuild()

    def _rebuild(self) -> None:
        self._tree.clear()
        total = 0
        for uri, diags in self._data.items():
            if not diags:
                continue
            try:
                fname = Path(uri.replace("file://", "")).name
            except Exception:
                fname = uri
            file_item = QTreeWidgetItem(self._tree, ["", fname, "", f"{len(diags)} problema/i"])
            file_item.setForeground(1, QColor("#9cdcfe"))
            file_item.setExpanded(True)
            for d in diags:
                sev   = d.get("severity", 1)
                label, color = _SEV.get(sev, ("?", "#858585"))
                start = d.get("range", {}).get("start", {})
                line  = start.get("line", 0) + 1
                msg   = d.get("message", "")
                row = QTreeWidgetItem(file_item, [label, "", str(line), msg[:300]])
                row.setForeground(0, QColor(color))
                row.setForeground(2, QColor("#858585"))
                row.setData(0, Qt.ItemDataRole.UserRole, {"uri": uri, "line": line - 1})
                total += 1
        errors = sum(
            1 for diags in self._data.values()
            for d in diags if d.get("severity", 1) == 1
        )
        warns = sum(
            1 for diags in self._data.values()
            for d in diags if d.get("severity", 1) == 2
        )
        if total == 0:
            self._lbl_count.setText(tr("lsp_panel.no_problems"))
        else:
            self._lbl_count.setText(f"{errors} errori  {warns} warning  ({total} totale)")

    def _on_item_clicked(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        uri  = data.get("uri", "")
        line = data.get("line", 0)
        try:
            path = Path(uri.replace("file://", ""))
            if path.exists():
                self._mw.open_files([path])
                editor = self._mw._tab_manager.current_editor()
                if editor:
                    editor.go_to_line(line + 1)
                    editor.setFocus()
        except Exception:
            pass

    def _clear(self) -> None:
        self._data.clear()
        self._tree.clear()
        self._lbl_count.setText(tr("lsp_panel.no_problems"))

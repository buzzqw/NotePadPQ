"""
ui/file_properties.py — Dialog Proprietà File
NotePadPQ

Mostra: percorso completo, dimensione, date creazione/modifica,
        encoding, line ending, righe, parole, caratteri.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QDialogButtonBox,
    QGroupBox, QApplication,
)
from PyQt6.QtCore import Qt

from i18n.i18n import tr

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _fmt_date(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d  %H:%M:%S")


class FilePropertiesDialog(QDialog):

    def __init__(self, editor: "EditorWidget", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("action.file_properties"))
        self.setMinimumWidth(460)
        self._editor = editor
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        path = self._editor.file_path
        text = self._editor.text()
        lines = self._editor.lines()
        words = len(text.split())
        chars = len(text)
        chars_no_ws = len(text.replace(" ", "").replace("\n", "").replace("\t", ""))

        # ── File su disco ──────────────────────────────────────────────────
        grp_file = QGroupBox("File")
        form_file = QFormLayout(grp_file)

        if path and path.exists():
            stat = path.stat()
            size_str   = _fmt_size(stat.st_size)
            mtime_str  = _fmt_date(stat.st_mtime)
            try:
                ctime_str = _fmt_date(stat.st_ctime)
            except Exception:
                ctime_str = "—"
            path_str = str(path)
        else:
            size_str  = "—"
            mtime_str = "—"
            ctime_str = "—"
            path_str  = tr("label.untitled")

        lbl_path = QLabel(path_str)
        lbl_path.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        lbl_path.setWordWrap(True)

        btn_copy = QPushButton("Copia percorso")
        btn_copy.setMaximumWidth(120)
        btn_copy.clicked.connect(
            lambda: QApplication.clipboard().setText(path_str)
        )

        path_row = QHBoxLayout()
        path_row.addWidget(lbl_path, 1)
        path_row.addWidget(btn_copy)

        form_file.addRow("Percorso:", path_row)  # type: ignore
        form_file.addRow("Dimensione:", QLabel(size_str))
        form_file.addRow("Modificato:", QLabel(mtime_str))
        form_file.addRow("Creato:",    QLabel(ctime_str))
        layout.addWidget(grp_file)

        # ── Documento ─────────────────────────────────────────────────────
        grp_doc = QGroupBox("Documento")
        form_doc = QFormLayout(grp_doc)
        form_doc.addRow(tr("label.encoding"),    QLabel(self._editor.encoding))
        form_doc.addRow(tr("label.line_ending"), QLabel(self._editor.line_ending.label()))
        form_doc.addRow(tr("label.lines_total"), QLabel(str(lines)))
        form_doc.addRow(tr("label.words"),       QLabel(str(words)))
        form_doc.addRow(tr("label.chars"),       QLabel(f"{chars}  (senza spazi: {chars_no_ws})"))
        layout.addWidget(grp_doc)

        # ── Pulsanti ──────────────────────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.accept)
        layout.addWidget(btns)

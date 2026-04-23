"""
ui/number_converter.py — Convertitore bin/oct/dec/hex
NotePadPQ

Dialog semplice per convertire numeri tra basi diverse,
come in Notepad++. Se c'è testo selezionato nell'editor,
viene usato come valore iniziale.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QHBoxLayout, QFrame
)


class NumberConverterDialog(QDialog):
    """Dialog per conversione numeri tra basi."""

    def __init__(self, parent=None, initial_text: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Convertitore numeri")
        self.setMinimumWidth(320)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._building = False
        self._build_ui()

        # Prova a usare il testo selezionato come valore iniziale
        val = initial_text.strip()
        if val:
            # Prova a rilevare la base
            if val.startswith(("0x", "0X")):
                self._hex_edit.setText(val[2:].upper())
                self._on_hex_changed()
            elif val.startswith(("0b", "0B")):
                self._bin_edit.setText(val[2:])
                self._on_bin_changed()
            elif val.isdigit():
                self._dec_edit.setText(val)
                self._on_dec_changed()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        grid = QGridLayout()
        grid.setColumnMinimumWidth(0, 80)

        grid.addWidget(QLabel("Decimale:"),   0, 0)
        grid.addWidget(QLabel("Esadecimale:"),1, 0)
        grid.addWidget(QLabel("Binario:"),    2, 0)
        grid.addWidget(QLabel("Ottale:"),     3, 0)

        self._dec_edit = QLineEdit(); self._dec_edit.setPlaceholderText("es. 255")
        self._hex_edit = QLineEdit(); self._hex_edit.setPlaceholderText("es. FF")
        self._bin_edit = QLineEdit(); self._bin_edit.setPlaceholderText("es. 11111111")
        self._oct_edit = QLineEdit(); self._oct_edit.setPlaceholderText("es. 377")

        grid.addWidget(self._dec_edit, 0, 1)
        grid.addWidget(self._hex_edit, 1, 1)
        grid.addWidget(self._bin_edit, 2, 1)
        grid.addWidget(self._oct_edit, 3, 1)

        layout.addLayout(grid)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("Pulisci")
        close_btn = QPushButton("Chiudi")
        clear_btn.clicked.connect(self._clear)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._dec_edit.textEdited.connect(self._on_dec_changed)
        self._hex_edit.textEdited.connect(self._on_hex_changed)
        self._bin_edit.textEdited.connect(self._on_bin_changed)
        self._oct_edit.textEdited.connect(self._on_oct_changed)

    def _set_all(self, value: int) -> None:
        self._building = True
        self._dec_edit.setText(str(value))
        self._hex_edit.setText(hex(value)[2:].upper())
        self._bin_edit.setText(bin(value)[2:])
        self._oct_edit.setText(oct(value)[2:])
        self._building = False

    def _clear_others(self, keep: QLineEdit) -> None:
        for w in (self._dec_edit, self._hex_edit, self._bin_edit, self._oct_edit):
            if w is not keep:
                w.clear()

    def _on_dec_changed(self) -> None:
        if self._building:
            return
        txt = self._dec_edit.text().strip()
        if not txt:
            self._clear_others(self._dec_edit)
            return
        try:
            self._set_all(int(txt, 10))
        except ValueError:
            self._clear_others(self._dec_edit)

    def _on_hex_changed(self) -> None:
        if self._building:
            return
        txt = self._hex_edit.text().strip()
        if not txt:
            self._clear_others(self._hex_edit)
            return
        try:
            self._set_all(int(txt, 16))
        except ValueError:
            self._clear_others(self._hex_edit)

    def _on_bin_changed(self) -> None:
        if self._building:
            return
        txt = self._bin_edit.text().strip()
        if not txt:
            self._clear_others(self._bin_edit)
            return
        try:
            self._set_all(int(txt, 2))
        except ValueError:
            self._clear_others(self._bin_edit)

    def _on_oct_changed(self) -> None:
        if self._building:
            return
        txt = self._oct_edit.text().strip()
        if not txt:
            self._clear_others(self._oct_edit)
            return
        try:
            self._set_all(int(txt, 8))
        except ValueError:
            self._clear_others(self._oct_edit)

    def _clear(self) -> None:
        for w in (self._dec_edit, self._hex_edit, self._bin_edit, self._oct_edit):
            w.clear()

"""
ui/lorem_ipsum.py — Generatore testo segnaposto (Lorem Ipsum)
NotePadPQ
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QSpinBox, QComboBox, QPushButton, QTextEdit, QCheckBox,
    QGroupBox,
)

if TYPE_CHECKING:
    from ui.main_window import MainWindow

# ── Vocabolario base per generazione ─────────────────────────────────────────

_WORDS = [
    "lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing",
    "elit", "sed", "eiusmod", "tempor", "incididunt", "labore", "dolore",
    "magna", "aliqua", "enim", "minim", "veniam", "quis", "nostrud",
    "exercitation", "ullamco", "laboris", "nisi", "aliquip", "commodo",
    "consequat", "duis", "aute", "irure", "reprehenderit", "voluptate",
    "velit", "esse", "cillum", "fugiat", "nulla", "pariatur", "excepteur",
    "sint", "occaecat", "cupidatat", "proident", "culpa", "officia",
    "deserunt", "mollit", "anim", "laborum", "perspiciatis", "unde", "omnis",
    "natus", "error", "voluptatem", "accusantium", "doloremque", "laudantium",
    "totam", "aperiam", "eaque", "ipsa", "quae", "illo", "inventore",
    "veritatis", "quasi", "architecto", "beatae", "vitae", "dicta",
    "explicabo", "nemo", "ipsam", "quia", "voluptas", "aspernatur", "odit",
    "fugit", "consequuntur", "magni", "dolores", "ratione", "sequi",
    "nesciunt", "neque", "porro", "quisquam", "dolorem", "adipisci",
    "numquam", "eius", "modi", "tempora", "incidunt", "laborum",
]

# Primo paragrafo classico (parole predefinite)
_FIRST_WORDS = [
    "lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing",
    "elit", "sed", "eiusmod", "tempor", "incididunt", "labore", "dolore",
    "magna", "aliqua",
]


def _make_sentence(words: list[str], min_w: int = 6, max_w: int = 14) -> str:
    n = random.randint(min_w, max_w)
    chosen = random.choices(words, k=n)
    s = " ".join(chosen)
    return s[0].upper() + s[1:] + "."


def _make_paragraph(
    words: list[str],
    sentences: int = 4,
    classic_first: bool = False,
) -> str:
    parts = []
    for i in range(sentences):
        if classic_first and i == 0:
            s = " ".join(_FIRST_WORDS)
            parts.append(s[0].upper() + s[1:] + ".")
        else:
            parts.append(_make_sentence(words))
    return " ".join(parts)


def generate(
    paragraphs: int = 3,
    sentences_per_para: int = 4,
    classic_first: bool = True,
    separator: str = "\n\n",
) -> str:
    result = []
    for i in range(paragraphs):
        p = _make_paragraph(
            _WORDS,
            sentences=sentences_per_para,
            classic_first=(classic_first and i == 0),
        )
        result.append(p)
    return separator.join(result)


# ── Dialog ────────────────────────────────────────────────────────────────────

class LoremIpsumDialog(QDialog):

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._mw = main_window
        self.setWindowTitle("Generatore testo segnaposto")
        self.setMinimumWidth(540)
        self.setMinimumHeight(380)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()
        self._generate()

    def _build_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setSpacing(8)

        # Opzioni
        opt_box = QGroupBox("Opzioni")
        grid = QGridLayout(opt_box)

        grid.addWidget(QLabel("Paragrafi:"), 0, 0)
        self._spin_para = QSpinBox()
        self._spin_para.setRange(1, 20)
        self._spin_para.setValue(3)
        grid.addWidget(self._spin_para, 0, 1)

        grid.addWidget(QLabel("Frasi per paragrafo:"), 0, 2)
        self._spin_sent = QSpinBox()
        self._spin_sent.setRange(1, 12)
        self._spin_sent.setValue(4)
        grid.addWidget(self._spin_sent, 0, 3)

        grid.addWidget(QLabel("Separatore:"), 1, 0)
        self._combo_sep = QComboBox()
        self._combo_sep.addItems([
            "Riga vuota (\\n\\n)",
            "Singola riga (\\n)",
            "Nessuno",
        ])
        grid.addWidget(self._combo_sep, 1, 1)

        self._chk_classic = QCheckBox("Primo paragrafo classico")
        self._chk_classic.setChecked(True)
        grid.addWidget(self._chk_classic, 1, 2, 1, 2)

        vl.addWidget(opt_box)

        # Anteprima
        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        vl.addWidget(self._preview)

        # Pulsanti
        btn_row = QHBoxLayout()
        gen_btn = QPushButton("Genera")
        gen_btn.clicked.connect(self._generate)
        ins_btn = QPushButton("Inserisci nel documento")
        ins_btn.clicked.connect(self._insert)
        close_btn = QPushButton("Chiudi")
        close_btn.clicked.connect(self.reject)

        btn_row.addWidget(gen_btn)
        btn_row.addStretch()
        btn_row.addWidget(ins_btn)
        btn_row.addWidget(close_btn)
        vl.addLayout(btn_row)

    def _get_separator(self) -> str:
        idx = self._combo_sep.currentIndex()
        return ["\n\n", "\n", ""][idx]

    def _generate(self) -> None:
        text = generate(
            paragraphs=self._spin_para.value(),
            sentences_per_para=self._spin_sent.value(),
            classic_first=self._chk_classic.isChecked(),
            separator=self._get_separator(),
        )
        self._preview.setPlainText(text)

    def _insert(self) -> None:
        text = self._preview.toPlainText()
        editor = self._mw._current_editor()
        if editor:
            editor.insert(text)
            editor.setFocus()
        self.accept()

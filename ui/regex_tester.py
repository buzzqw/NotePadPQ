"""
ui/regex_tester.py — Tester Espressioni Regolari
NotePadPQ

Dialog non modale con:
- Campo pattern + flag (IGNORECASE, MULTILINE, DOTALL)
- Testo di test con evidenziazione match in tempo reale
- Lista gruppi di cattura
- Anteprima sostituzione con backreference
- Riferimento rapido sintassi regex
"""

from __future__ import annotations

import re
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPlainTextEdit, QCheckBox,
    QTableWidget, QTableWidgetItem, QTabWidget,
    QWidget, QSplitter, QPushButton, QGroupBox,
    QScrollArea,
)

from i18n.i18n import tr


# Colori per i gruppi di cattura (ciclano)
_GROUP_COLORS = [
    QColor("#264f78"),  # blu
    QColor("#4a3f00"),  # arancio scuro
    QColor("#0f4a00"),  # verde scuro
    QColor("#4a0020"),  # rosso scuro
    QColor("#2a004a"),  # viola scuro
]

_REGEX_REFERENCE = """
CARATTERI BASE
.       Qualsiasi carattere (tranne \\n)
\\d      Cifra [0-9]
\\D      Non-cifra
\\w      Parola [a-zA-Z0-9_]
\\W      Non-parola
\\s      Spazio bianco
\\S      Non-spazio
\\b      Confine di parola
\\B      Non-confine

QUANTIFICATORI
*       0 o più (greedy)
+       1 o più (greedy)
?       0 o 1 (greedy)
*?      0 o più (lazy)
+?      1 o più (lazy)
{n}     Esattamente n volte
{n,m}   Da n a m volte

ANCORE
^       Inizio riga/stringa
$       Fine riga/stringa
\\A      Inizio stringa
\\Z      Fine stringa

GRUPPI
(...)       Gruppo di cattura
(?:...)     Gruppo non catturante
(?P<n>...)  Gruppo con nome n
(?=...)     Lookahead positivo
(?!...)     Lookahead negativo
(?<=...)    Lookbehind positivo
(?<!...)    Lookbehind negativo

CLASSI
[abc]   a, b o c
[^abc]  Non a, b o c
[a-z]   Da a a z
[\\d\\w]  Cifre e parole

SOSTITUZIONE
\\1, \\2  Gruppo catturato per numero
\\g<n>   Gruppo catturato per nome n
"""


class RegexTesterDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("action.regex_tester"))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.resize(780, 580)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._run_match)

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # ── Pattern ───────────────────────────────────────────────────────
        grp_pat = QGroupBox("Pattern")
        pat_lay = QVBoxLayout(grp_pat)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Regex:"))
        self._pattern = QLineEdit()
        self._pattern.setFont(QFont("Monospace", 11))
        self._pattern.setPlaceholderText(r"es. (\w+)\s+(\d+)")
        self._pattern.textChanged.connect(self._schedule)
        row1.addWidget(self._pattern, 1)
        pat_lay.addLayout(row1)

        row2 = QHBoxLayout()
        self._chk_i = QCheckBox("Ignora maiuscole (i)")
        self._chk_m = QCheckBox("Multiriga (m)")
        self._chk_s = QCheckBox("Punto=tutto (s)")
        self._chk_x = QCheckBox("Verbose (x)")
        for chk in [self._chk_i, self._chk_m, self._chk_s, self._chk_x]:
            chk.stateChanged.connect(self._schedule)
            row2.addWidget(chk)
        row2.addStretch()
        self._lbl_err = QLabel("")
        self._lbl_err.setStyleSheet("color: #f44747;")
        row2.addWidget(self._lbl_err)
        pat_lay.addLayout(row2)

        layout.addWidget(grp_pat)

        # ── Sostituzione ──────────────────────────────────────────────────
        grp_sub = QGroupBox("Sostituzione (backreference)")
        sub_lay = QHBoxLayout(grp_sub)
        sub_lay.addWidget(QLabel("Replace:"))
        self._replace = QLineEdit()
        self._replace.setFont(QFont("Monospace", 11))
        self._replace.setPlaceholderText(r"es. \1 - \2  oppure  \g<nome>")
        self._replace.textChanged.connect(self._schedule)
        sub_lay.addWidget(self._replace, 1)
        layout.addWidget(grp_sub)

        # ── Corpo principale ──────────────────────────────────────────────
        tabs = QTabWidget()

        # Tab: Testo di test
        test_widget = QWidget()
        test_lay = QVBoxLayout(test_widget)

        self._test_edit = QPlainTextEdit()
        self._test_edit.setFont(QFont("Monospace", 11))
        self._test_edit.setPlaceholderText("Incolla qui il testo su cui testare la regex...")
        self._test_edit.textChanged.connect(self._schedule)
        test_lay.addWidget(self._test_edit, 2)

        # Risultato sostituzione
        test_lay.addWidget(QLabel("Risultato sostituzione:"))
        self._result_edit = QPlainTextEdit()
        self._result_edit.setFont(QFont("Monospace", 11))
        self._result_edit.setReadOnly(True)
        self._result_edit.setMaximumHeight(100)
        test_lay.addWidget(self._result_edit, 1)

        tabs.addTab(test_widget, "Testo di test")

        # Tab: Gruppi di cattura
        groups_widget = QWidget()
        groups_lay = QVBoxLayout(groups_widget)
        self._lbl_match_count = QLabel("0 match trovati")
        groups_lay.addWidget(self._lbl_match_count)
        self._groups_table = QTableWidget(0, 4)
        self._groups_table.setHorizontalHeaderLabels(
            ["Match #", "Testo completo", "Inizio", "Fine"]
        )
        self._groups_table.horizontalHeader().setStretchLastSection(True)
        groups_lay.addWidget(self._groups_table, 1)
        tabs.addTab(groups_widget, "Match e gruppi")

        # Tab: Riferimento sintassi
        ref_widget = QScrollArea()
        ref_inner = QLabel(_REGEX_REFERENCE)
        ref_inner.setFont(QFont("Monospace", 10))
        ref_inner.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        ref_inner.setMargin(12)
        ref_widget.setWidget(ref_inner)
        ref_widget.setWidgetResizable(True)
        tabs.addTab(ref_widget, "Riferimento sintassi")

        layout.addWidget(tabs, 1)

        # ── Pulsanti ──────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_copy = QPushButton("Copia pattern")
        btn_copy.clicked.connect(
            lambda: __import__("PyQt6.QtWidgets", fromlist=["QApplication"])
            .QApplication.clipboard().setText(self._pattern.text())
        )
        btn_clear = QPushButton("Pulisci tutto")
        btn_clear.clicked.connect(self._clear_all)
        btn_close = QPushButton(tr("button.close"))
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_copy)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    # ── Logica ────────────────────────────────────────────────────────────────

    def _schedule(self) -> None:
        self._timer.start()

    def _get_flags(self) -> int:
        flags = 0
        if self._chk_i.isChecked(): flags |= re.IGNORECASE
        if self._chk_m.isChecked(): flags |= re.MULTILINE
        if self._chk_s.isChecked(): flags |= re.DOTALL
        if self._chk_x.isChecked(): flags |= re.VERBOSE
        return flags

    def _run_match(self) -> None:
        pattern_str = self._pattern.text()
        text        = self._test_edit.toPlainText()
        replace_str = self._replace.text()

        self._lbl_err.setText("")
        self._groups_table.setRowCount(0)
        self._result_edit.setPlainText("")
        self._lbl_match_count.setText("0 match trovati")

        if not pattern_str:
            self._clear_highlights()
            return

        try:
            compiled = re.compile(pattern_str, self._get_flags())
        except re.error as e:
            self._lbl_err.setText(f"⚠ {e}")
            self._clear_highlights()
            return

        matches = list(compiled.finditer(text))
        self._lbl_match_count.setText(
            f"{len(matches)} match troват{'o' if len(matches)==1 else 'i'}"
        )

        # Evidenzia nel test editor
        self._highlight_matches(matches, text)

        # Popola tabella gruppi
        self._groups_table.setRowCount(0)
        for i, m in enumerate(matches):
            row = self._groups_table.rowCount()
            self._groups_table.insertRow(row)
            self._groups_table.setItem(row, 0, QTableWidgetItem(str(i + 1)))
            self._groups_table.setItem(row, 1, QTableWidgetItem(m.group(0)[:80]))
            self._groups_table.setItem(row, 2, QTableWidgetItem(str(m.start())))
            self._groups_table.setItem(row, 3, QTableWidgetItem(str(m.end())))

            # Sottorighe per i gruppi
            if m.lastindex:
                for gi in range(1, m.lastindex + 1):
                    sub_row = self._groups_table.rowCount()
                    self._groups_table.insertRow(sub_row)
                    self._groups_table.setItem(
                        sub_row, 0,
                        QTableWidgetItem(f"  └ gruppo {gi}")
                    )
                    self._groups_table.setItem(
                        sub_row, 1,
                        QTableWidgetItem(str(m.group(gi)))
                    )

        # Sostituzione
        if replace_str and matches:
            try:
                result = compiled.sub(replace_str, text)
                self._result_edit.setPlainText(result)
            except re.error as e:
                self._result_edit.setPlainText(f"Errore sostituzione: {e}")

    def _highlight_matches(self, matches: list, text: str) -> None:
        cursor = self._test_edit.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        fmt_clear = QTextCharFormat()
        cursor.setCharFormat(fmt_clear)

        for i, m in enumerate(matches):
            color = _GROUP_COLORS[i % len(_GROUP_COLORS)]
            fmt = QTextCharFormat()
            fmt.setBackground(color)
            fmt.setForeground(QColor("#ffffff"))

            c = self._test_edit.textCursor()
            c.setPosition(m.start())
            c.setPosition(m.end(), QTextCursor.MoveMode.KeepAnchor)
            c.setCharFormat(fmt)

    def _clear_highlights(self) -> None:
        cursor = self._test_edit.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.setCharFormat(QTextCharFormat())

    def _clear_all(self) -> None:
        self._pattern.clear()
        self._replace.clear()
        self._test_edit.clear()
        self._result_edit.clear()
        self._groups_table.setRowCount(0)
        self._lbl_err.setText("")
        self._lbl_match_count.setText("0 match trovati")

    def set_pattern(self, pattern: str) -> None:
        """Imposta il pattern dall'esterno (es. da Find/Replace)."""
        self._pattern.setText(pattern)

    def set_test_text(self, text: str) -> None:
        """Imposta il testo di test (es. dal documento corrente)."""
        self._test_edit.setPlainText(text[:10000])  # limite ragionevole

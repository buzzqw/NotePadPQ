"""
editor/latex_wizard.py — Wizard LaTeX
NotePadPQ

Dialog per generare codice LaTeX per:
- Tabelle (con booktabs, colonne configurabili)
- Formule matematiche (con anteprima testo)
- Ambienti comuni (figure, enumerate, ecc.)
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QFormLayout, QLabel, QLineEdit, QSpinBox,
    QCheckBox, QComboBox, QPushButton, QPlainTextEdit,
    QTableWidget, QTableWidgetItem, QDialogButtonBox,
    QGroupBox, QHeaderView,
)

from i18n.i18n import tr

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget


class LaTeXWizardDialog(QDialog):

    def __init__(self, editor: "EditorWidget", parent=None):
        super().__init__(parent)
        self._editor = editor
        self.setWindowTitle("LaTeX Wizard")
        self.resize(680, 520)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_table_tab(),   "Tabella")
        self._tabs.addTab(self._build_formula_tab(), "Formula matematica")
        self._tabs.addTab(self._build_env_tab(),     "Ambienti")
        layout.addWidget(self._tabs, 1)

        # Preview codice
        grp = QGroupBox("Codice generato")
        gl  = QVBoxLayout(grp)
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(False)  # modificabile manualmente
        self._preview.setMaximumHeight(140)
        gl.addWidget(self._preview)
        layout.addWidget(grp)

        btns = QDialogButtonBox()
        btn_insert = btns.addButton("Inserisci nell'editor",
                                    QDialogButtonBox.ButtonRole.AcceptRole)
        btn_copy   = btns.addButton(tr("button.copy"),
                                    QDialogButtonBox.ButtonRole.ActionRole)
        btn_close  = btns.addButton(tr("button.close"),
                                    QDialogButtonBox.ButtonRole.RejectRole)
        btn_insert.clicked.connect(self._insert)
        btn_copy.clicked.connect(self._copy)
        btn_close.clicked.connect(self.reject)
        layout.addWidget(btns)

    # ── Tab Tabella ───────────────────────────────────────────────────────────

    def _build_table_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Configurazione
        cfg = QFormLayout()
        self._tbl_rows = QSpinBox(); self._tbl_rows.setRange(1, 30); self._tbl_rows.setValue(3)
        self._tbl_cols = QSpinBox(); self._tbl_cols.setRange(1, 15); self._tbl_cols.setValue(3)
        self._tbl_rows.valueChanged.connect(self._rebuild_table_editor)
        self._tbl_cols.valueChanged.connect(self._rebuild_table_editor)
        cfg.addRow("Righe:", self._tbl_rows)
        cfg.addRow("Colonne:", self._tbl_cols)

        self._tbl_booktabs = QCheckBox("Usa booktabs (\\toprule, \\midrule, \\bottomrule)")
        self._tbl_booktabs.setChecked(True)
        self._tbl_caption = QLineEdit(); self._tbl_caption.setPlaceholderText("Caption tabella")
        self._tbl_label   = QLineEdit(); self._tbl_label.setPlaceholderText("tab:etichetta")
        self._tbl_pos     = QComboBox(); self._tbl_pos.addItems(["htbp", "h", "t", "b", "p"])
        self._tbl_align   = QComboBox()
        self._tbl_align.addItems(["centrato", "sinistra", "destra"])

        cfg.addRow("", self._tbl_booktabs)
        cfg.addRow("Caption:", self._tbl_caption)
        cfg.addRow("Label:", self._tbl_label)
        cfg.addRow("Posizione:", self._tbl_pos)
        cfg.addRow("Allineamento:", self._tbl_align)
        layout.addLayout(cfg)

        # Editor celle
        self._cell_table = QTableWidget(3, 3)
        self._cell_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self._cell_table, 1)

        # Allineamento colonne
        col_cfg = QHBoxLayout()
        col_cfg.addWidget(QLabel("Allineamento colonne:"))
        self._col_align = QLineEdit("lll")
        self._col_align.setPlaceholderText("es. llr  o  l|c|r")
        col_cfg.addWidget(self._col_align, 1)
        layout.addLayout(col_cfg)

        btn_gen = QPushButton("Genera codice tabella")
        btn_gen.clicked.connect(self._generate_table)
        layout.addWidget(btn_gen)

        self._rebuild_table_editor()
        return w

    def _rebuild_table_editor(self) -> None:
        rows = self._tbl_rows.value()
        cols = self._tbl_cols.value()
        self._cell_table.setRowCount(rows)
        self._cell_table.setColumnCount(cols)
        # Header di default
        for c in range(cols):
            if not self._cell_table.item(0, c):
                self._cell_table.setItem(
                    0, c, QTableWidgetItem(f"Col {c+1}")
                )

    def _generate_table(self) -> None:
        rows    = self._tbl_rows.value()
        cols    = self._tbl_cols.value()
        booktabs= self._tbl_booktabs.isChecked()
        caption = self._tbl_caption.text().strip()
        label   = self._tbl_label.text().strip()
        pos     = self._tbl_pos.currentText()
        col_spec= self._col_align.text().strip() or "l" * cols

        align_map = {"centrato": "\\centering", "sinistra": "\\raggedright", "destra": "\\raggedleft"}
        align_cmd = align_map.get(self._tbl_align.currentText(), "\\centering")

        lines = [
            f"\\begin{{table}}[{pos}]",
            f"    {align_cmd}",
        ]
        if caption:
            lines.append(f"    \\caption{{{caption}}}")
        if label:
            lines.append(f"    \\label{{{label}}}")

        lines.append(f"    \\begin{{tabular}}{{{col_spec}}}")
        if booktabs:
            lines.append("        \\toprule")

        for r in range(rows):
            cells = []
            for c in range(cols):
                item = self._cell_table.item(r, c)
                cells.append(item.text() if item else "")
            row_str = "        " + " & ".join(cells) + " \\\\"
            lines.append(row_str)
            if booktabs and r == 0:
                lines.append("        \\midrule")

        if booktabs:
            lines.append("        \\bottomrule")
        lines.append("    \\end{tabular}")
        lines.append("\\end{table}")

        self._preview.setPlainText("\n".join(lines))

    # ── Tab Formula ───────────────────────────────────────────────────────────

    def _build_formula_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        cfg = QFormLayout()
        self._formula_type = QComboBox()
        self._formula_type.addItems([
            "equation (numerata)",
            "equation* (non numerata)",
            "align (multi-riga numerata)",
            "align* (multi-riga non numerata)",
            "inline $...$",
            "display \\[...\\]",
        ])
        cfg.addRow("Tipo:", self._formula_type)

        self._formula_label = QLineEdit()
        self._formula_label.setPlaceholderText("eq:etichetta (opzionale)")
        cfg.addRow("Label:", self._formula_label)
        layout.addLayout(cfg)

        layout.addWidget(QLabel("Formula LaTeX:"))
        self._formula_edit = QPlainTextEdit()
        self._formula_edit.setMaximumHeight(100)
        self._formula_edit.setPlaceholderText(
            r"es. E = mc^2  oppure  \frac{a}{b} = \sqrt{c^2 - d^2}"
        )
        layout.addWidget(self._formula_edit)

        # Inserimento rapido simboli
        layout.addWidget(QLabel("Simboli rapidi:"))
        symbols_layout = QHBoxLayout()
        common_symbols = [
            ("α", "\\alpha"), ("β", "\\beta"), ("γ", "\\gamma"),
            ("δ", "\\delta"), ("π", "\\pi"), ("σ", "\\sigma"),
            ("∑", "\\sum"), ("∫", "\\int"), ("∞", "\\infty"),
            ("→", "\\to"), ("≤", "\\leq"), ("≥", "\\geq"),
            ("½", "\\frac{}{}"), ("√", "\\sqrt{}"),
        ]
        for sym, code in common_symbols:
            btn = QPushButton(sym)
            btn.setFixedWidth(30)
            btn.setToolTip(code)
            btn.clicked.connect(
                lambda checked, c=code: self._formula_edit.insertPlainText(c)
            )
            symbols_layout.addWidget(btn)
        symbols_layout.addStretch()
        layout.addLayout(symbols_layout)

        btn_gen = QPushButton("Genera codice formula")
        btn_gen.clicked.connect(self._generate_formula)
        layout.addWidget(btn_gen)
        layout.addStretch()
        return w

    def _generate_formula(self) -> None:
        formula = self._formula_edit.toPlainText().strip()
        label   = self._formula_label.text().strip()
        ftype   = self._formula_type.currentText()

        if "inline" in ftype:
            code = f"${formula}$"
        elif "display" in ftype:
            code = f"\\[\n    {formula}\n\\]"
        else:
            env = ftype.split()[0]
            lines = [f"\\begin{{{env}}}"]
            if label and "*" not in env:
                lines.append(f"    {formula}")
                lines.append(f"    \\label{{{label}}}")
            else:
                lines.append(f"    {formula}")
            lines.append(f"\\end{{{env}}}")
            code = "\n".join(lines)

        self._preview.setPlainText(code)

    # ── Tab Ambienti ──────────────────────────────────────────────────────────

    def _build_env_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel("Seleziona un ambiente da inserire:"))

        environments = {
            "figure": self._gen_figure,
            "itemize": self._gen_itemize,
            "enumerate": self._gen_enumerate,
            "verbatim": self._gen_verbatim,
            "abstract": self._gen_abstract,
            "multicols": self._gen_multicols,
        }

        grid = QGridLayout()
        for i, (name, fn) in enumerate(environments.items()):
            btn = QPushButton(f"\\begin{{{name}}}")
            btn.clicked.connect(lambda checked, f=fn: (f(), None))
            grid.addWidget(btn, i // 3, i % 3)
        layout.addLayout(grid)
        layout.addStretch()
        return w

    def _gen_figure(self):
        self._preview.setPlainText(
            "\\begin{figure}[htbp]\n"
            "    \\centering\n"
            "    \\includegraphics[width=\\textwidth]{nome_file}\n"
            "    \\caption{Caption}\n"
            "    \\label{fig:etichetta}\n"
            "\\end{figure}"
        )

    def _gen_itemize(self):
        self._preview.setPlainText(
            "\\begin{itemize}\n"
            "    \\item Primo elemento\n"
            "    \\item Secondo elemento\n"
            "    \\item Terzo elemento\n"
            "\\end{itemize}"
        )

    def _gen_enumerate(self):
        self._preview.setPlainText(
            "\\begin{enumerate}\n"
            "    \\item Primo elemento\n"
            "    \\item Secondo elemento\n"
            "    \\item Terzo elemento\n"
            "\\end{enumerate}"
        )

    def _gen_verbatim(self):
        self._preview.setPlainText(
            "\\begin{verbatim}\n"
            "testo letterale qui\n"
            "\\end{verbatim}"
        )

    def _gen_abstract(self):
        self._preview.setPlainText(
            "\\begin{abstract}\n"
            "    Testo dell'abstract.\n"
            "\\end{abstract}"
        )

    def _gen_multicols(self):
        self._preview.setPlainText(
            "\\begin{multicols}{2}\n"
            "    Testo su due colonne.\n"
            "\\end{multicols}"
        )

    # ── Azioni ────────────────────────────────────────────────────────────────

    def _insert(self) -> None:
        code = self._preview.toPlainText()
        if code and self._editor:
            self._editor.insert(code)
        self.accept()

    def _copy(self) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._preview.toPlainText())

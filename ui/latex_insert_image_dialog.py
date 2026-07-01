"""
ui/latex_insert_image_dialog.py — Dialogo "Inserisci immagine" per LaTeX
NotePadPQ

Genera codice LaTeX per \\includegraphics (semplice) o per un ambiente
figure/figure* completo, con opzioni dimensioni, didascalia ed etichetta.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QCheckBox, QComboBox, QPushButton, QSizePolicy,
    QTextEdit, QVBoxLayout, QWidget,
)

from i18n.i18n import tr


_WIDTH_UNITS  = ["\\linewidth", "\\textwidth", "\\columnwidth", "cm", "mm", "in", "px"]
_HEIGHT_UNITS = ["\\textheight", "\\lineheight", "cm", "mm", "in", "px"]
_POSITIONS    = ["htbp", "h", "t", "b", "p", "H", "ht", "tb", "!htbp"]
_CAP_POS      = [
    tr("latex_img_dlg.caption_below", default="Sotto"),
    tr("latex_img_dlg.caption_above", default="Sopra"),
]


class LatexInsertImageDialog(QDialog):
    """Dialogo per inserire un'immagine LaTeX (stile TeXstudio)."""

    def __init__(self, parent: Optional[QWidget] = None,
                 base_dir: Optional[Path] = None) -> None:
        super().__init__(parent)
        self._base_dir = base_dir
        self.setWindowTitle(tr("latex_img_dlg.title", default="Inserisci immagine"))
        self.setMinimumWidth(480)
        self._build_ui()

    # ── Costruzione UI ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 8)

        # File
        root.addWidget(self._build_file_row())

        # Opzioni immagine
        root.addWidget(self._build_image_options())

        # Ambiente figure
        root.addWidget(self._build_figure_group())

        # Bottoni
        self._bbox = QDialogButtonBox(parent=self)
        self._btn_defaults = self._bbox.addButton(
            tr("latex_img_dlg.btn_defaults", default="Predefinite"),
            QDialogButtonBox.ButtonRole.ResetRole
        )
        self._bbox.addButton(QDialogButtonBox.StandardButton.Ok)
        self._bbox.addButton(QDialogButtonBox.StandardButton.Cancel)

        self._bbox.accepted.connect(self.accept)
        self._bbox.rejected.connect(self.reject)
        self._btn_defaults.clicked.connect(self._reset_defaults)

        root.addWidget(self._bbox)

    def _build_file_row(self) -> QWidget:
        w = QWidget(self)
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        lbl = QLabel(tr("latex_img_dlg.file", default="File immagine:"), w)
        lbl.setFixedWidth(120)
        self._file_edit = QLineEdit(w)
        self._file_edit.setPlaceholderText(
            tr("latex_img_dlg.file_placeholder", default="Percorso immagine…")
        )
        btn_browse = QPushButton(
            tr("latex_img_dlg.browse", default="Sfoglia…"), w
        )
        btn_browse.setFixedWidth(80)
        btn_browse.clicked.connect(self._browse_file)

        row.addWidget(lbl)
        row.addWidget(self._file_edit)
        row.addWidget(btn_browse)
        return w

    def _build_image_options(self) -> QGroupBox:
        gb = QGroupBox(tr("latex_img_dlg.image_options", default="Opzioni immagine"), self)
        form = QFormLayout(gb)
        form.setSpacing(6)

        # Larghezza
        self._use_width = QCheckBox(tr("latex_img_dlg.width", default="Larghezza:"), gb)
        self._use_width.setChecked(True)
        w_row = QWidget(gb)
        w_lay = QHBoxLayout(w_row)
        w_lay.setContentsMargins(0, 0, 0, 0)
        w_lay.setSpacing(4)
        self._width_val = QLineEdit("0.8", w_row)
        self._width_val.setFixedWidth(60)
        self._width_unit = QComboBox(w_row)
        self._width_unit.addItems(_WIDTH_UNITS)
        w_lay.addWidget(self._width_val)
        w_lay.addWidget(self._width_unit)
        w_lay.addStretch()
        form.addRow(self._use_width, w_row)

        # Altezza
        self._use_height = QCheckBox(tr("latex_img_dlg.height", default="Altezza:"), gb)
        h_row = QWidget(gb)
        h_lay = QHBoxLayout(h_row)
        h_lay.setContentsMargins(0, 0, 0, 0)
        h_lay.setSpacing(4)
        self._height_val = QLineEdit("", h_row)
        self._height_val.setFixedWidth(60)
        self._height_unit = QComboBox(h_row)
        self._height_unit.addItems(_HEIGHT_UNITS)
        h_lay.addWidget(self._height_val)
        h_lay.addWidget(self._height_unit)
        h_lay.addStretch()
        self._height_val.setEnabled(False)
        self._height_unit.setEnabled(False)
        form.addRow(self._use_height, h_row)

        self._use_height.toggled.connect(self._height_val.setEnabled)
        self._use_height.toggled.connect(self._height_unit.setEnabled)

        # Centra
        self._center_chk = QCheckBox(
            tr("latex_img_dlg.center", default="Centra orizzontalmente"), gb
        )
        self._center_chk.setChecked(True)
        form.addRow("", self._center_chk)

        return gb

    def _build_figure_group(self) -> QGroupBox:
        gb = QGroupBox(
            tr("latex_img_dlg.use_figure", default="Inserisci in un ambiente figure"),
            self
        )
        gb.setCheckable(True)
        gb.setChecked(False)
        self._figure_gb = gb

        form = QFormLayout(gb)
        form.setSpacing(6)

        # Posizione didascalia
        self._cap_pos = QComboBox(gb)
        self._cap_pos.addItems([
            tr("latex_img_dlg.caption_below", default="Sotto"),
            tr("latex_img_dlg.caption_above", default="Sopra"),
        ])
        form.addRow(
            tr("latex_img_dlg.caption_position", default="Posizione didascalia:"),
            self._cap_pos
        )

        # Didascalia breve
        self._caption_short = QLineEdit(gb)
        self._caption_short.setPlaceholderText(
            tr("latex_img_dlg.caption_short_hint", default="Didascalia breve (per il sommario figure)")
        )
        form.addRow(
            tr("latex_img_dlg.caption_short", default="Didascalia:"),
            self._caption_short
        )

        # Didascalia estesa
        self._caption_long = QTextEdit(gb)
        self._caption_long.setPlaceholderText(
            tr("latex_img_dlg.caption_long_hint", default="Testo esteso della didascalia (opzionale)")
        )
        self._caption_long.setFixedHeight(60)
        form.addRow(
            tr("latex_img_dlg.caption_long", default="Testo esteso:"),
            self._caption_long
        )

        # Etichetta
        self._label_edit = QLineEdit(gb)
        self._label_edit.setPlaceholderText("fig:nome")
        form.addRow(
            tr("latex_img_dlg.label", default="Etichetta (\\label):"),
            self._label_edit
        )

        # Posizione ambiente
        pos_row = QWidget(gb)
        pos_lay = QHBoxLayout(pos_row)
        pos_lay.setContentsMargins(0, 0, 0, 0)
        pos_lay.setSpacing(4)
        self._fig_pos_edit = QLineEdit("htbp", pos_row)
        self._fig_pos_edit.setFixedWidth(60)
        self._fig_pos_combo = QComboBox(pos_row)
        self._fig_pos_combo.addItems(_POSITIONS)
        self._fig_pos_combo.currentTextChanged.connect(self._fig_pos_edit.setText)
        pos_lay.addWidget(self._fig_pos_edit)
        pos_lay.addWidget(self._fig_pos_combo)
        pos_lay.addStretch()
        form.addRow(
            tr("latex_img_dlg.position", default="Posizione:"),
            pos_row
        )

        # figure*
        self._two_col_chk = QCheckBox(
            tr("latex_img_dlg.two_columns", default="Estendi a coprire due colonne (figure*)"),
            gb
        )
        form.addRow("", self._two_col_chk)

        return gb

    # ── Azioni UI ─────────────────────────────────────────────────────────────

    def set_image_file(self, path: str) -> None:
        """Pre-popola il campo file con il percorso dato."""
        self._file_edit.setText(path)

    def _browse_file(self) -> None:
        start = ""
        if self._base_dir:
            start = str(self._base_dir)
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("latex_img_dlg.browse_title", default="Seleziona immagine"),
            start,
            tr("latex_img_dlg.image_filter",
               default="Immagini (*.png *.jpg *.jpeg *.pdf *.eps *.svg *.gif);;Tutti i file (*)")
        )
        if path:
            if self._base_dir:
                try:
                    path = str(Path(path).relative_to(self._base_dir))
                except ValueError:
                    pass
            self._file_edit.setText(path)

    def _reset_defaults(self) -> None:
        self._file_edit.clear()
        self._use_width.setChecked(True)
        self._width_val.setText("0.8")
        self._width_unit.setCurrentIndex(0)
        self._use_height.setChecked(False)
        self._height_val.clear()
        self._height_unit.setCurrentIndex(0)
        self._center_chk.setChecked(True)
        self._figure_gb.setChecked(False)
        self._cap_pos.setCurrentIndex(0)
        self._caption_short.clear()
        self._caption_long.clear()
        self._label_edit.clear()
        self._fig_pos_edit.setText("htbp")
        self._fig_pos_combo.setCurrentIndex(0)
        self._two_col_chk.setChecked(False)

    # ── Generazione codice LaTeX ──────────────────────────────────────────────

    def get_latex_code(self) -> str:
        """Restituisce il codice LaTeX da inserire nell'editor."""
        file_path = self._file_edit.text().strip()
        if not file_path:
            return ""

        # Opzioni \includegraphics
        opts: list[str] = []
        if self._use_width.isChecked() and self._width_val.text().strip():
            unit = self._width_unit.currentText()
            val  = self._width_val.text().strip()
            if unit.startswith("\\"):
                opts.append(f"width={val}{unit}")
            else:
                opts.append(f"width={val}{unit}")
        if self._use_height.isChecked() and self._height_val.text().strip():
            unit = self._height_unit.currentText()
            val  = self._height_val.text().strip()
            opts.append(f"height={val}{unit}")

        opt_str = f"[{','.join(opts)}]" if opts else ""
        include = f"\\includegraphics{opt_str}{{{file_path}}}"

        if not self._figure_gb.isChecked():
            if self._center_chk.isChecked():
                return f"\\begin{{center}}\n{include}\n\\end{{center}}"
            return include

        # Ambiente figure
        env      = "figure*" if self._two_col_chk.isChecked() else "figure"
        pos      = self._fig_pos_edit.text().strip()
        pos_str  = f"[{pos}]" if pos else ""
        cap_short = self._caption_short.text().strip()
        cap_long  = self._caption_long.toPlainText().strip()
        label    = self._label_edit.text().strip()
        cap_above = self._cap_pos.currentIndex() == 1

        if cap_long and cap_short:
            caption_cmd = f"\\caption[{cap_short}]{{{cap_long}}}"
        elif cap_short:
            caption_cmd = f"\\caption{{{cap_short}}}"
        else:
            caption_cmd = ""

        label_cmd = f"\\label{{{label}}}" if label else ""

        lines = [f"\\begin{{{env}}}{pos_str}"]
        if self._center_chk.isChecked():
            lines.append("    \\centering")
        if cap_above and caption_cmd:
            lines.append(f"    {caption_cmd}")
            if label_cmd:
                lines.append(f"    {label_cmd}")
        lines.append(f"    {include}")
        if not cap_above:
            if caption_cmd:
                lines.append(f"    {caption_cmd}")
            if label_cmd:
                lines.append(f"    {label_cmd}")
        lines.append(f"\\end{{{env}}}")
        return "\n".join(lines)

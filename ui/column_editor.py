"""Column editor — inserisce numeri sequenziali o testo fisso su selezione rettangolare."""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QRadioButton, QSpinBox, QLineEdit,
    QComboBox, QLabel, QDialogButtonBox, QButtonGroup,
)
from PyQt6.QtCore import Qt

from i18n.i18n import tr


class ColumnEditorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Column editor")
        self.setFixedWidth(380)

        vl = QVBoxLayout(self)

        # ── Modalità ──────────────────────────────────────────────────────────
        grp_mode = QGroupBox(tr("column_editor.grp_mode"))
        mode_layout = QHBoxLayout(grp_mode)
        self._rb_numbers = QRadioButton("Numeri")
        self._rb_text    = QRadioButton("Testo")
        self._rb_numbers.setChecked(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._rb_numbers, 0)
        self._mode_group.addButton(self._rb_text,    1)
        mode_layout.addWidget(self._rb_numbers)
        mode_layout.addWidget(self._rb_text)
        vl.addWidget(grp_mode)

        # ── Opzioni numeri ────────────────────────────────────────────────────
        self._grp_num = QGroupBox(tr("column_editor.grp_num_options"))
        fl_num = QFormLayout(self._grp_num)

        self._num_initial = QSpinBox()
        self._num_initial.setRange(-999999, 999999)
        self._num_initial.setValue(1)
        fl_num.addRow(tr("column_editor.label_initial"), self._num_initial)

        self._num_step = QSpinBox()
        self._num_step.setRange(-999999, 999999)
        self._num_step.setValue(1)
        fl_num.addRow("Incremento:", self._num_step)

        self._num_fmt = QComboBox()
        self._num_fmt.addItem(tr("column_editor.item_decimal"),     "dec")
        self._num_fmt.addItem(tr("column_editor.item_hex"),  "hex")
        self._num_fmt.addItem(tr("column_editor.item_octal"),       "oct")
        self._num_fmt.addItem(tr("column_editor.item_binary"),      "bin")
        fl_num.addRow(tr("column_editor.label_format"), self._num_fmt)

        self._num_padding = QSpinBox()
        self._num_padding.setRange(0, 20)
        self._num_padding.setValue(0)
        self._num_padding.setToolTip("0 = nessun padding, N = larghezza fissa con zero iniziali")
        fl_num.addRow("Padding (cifre):", self._num_padding)

        self._num_prefix = QLineEdit()
        self._num_prefix.setPlaceholderText("es. #, 0x, …")
        fl_num.addRow("Prefisso:", self._num_prefix)

        self._num_suffix = QLineEdit()
        self._num_suffix.setPlaceholderText("es. ,  ;  .")
        fl_num.addRow("Suffisso:", self._num_suffix)

        vl.addWidget(self._grp_num)

        # ── Opzioni testo ─────────────────────────────────────────────────────
        self._grp_txt = QGroupBox(tr("column_editor.grp_text_options"))
        fl_txt = QFormLayout(self._grp_txt)
        self._txt_value = QLineEdit()
        self._txt_value.setPlaceholderText(tr("column_editor.placeholder_text"))
        fl_txt.addRow(tr("column_editor.label_text"), self._txt_value)
        self._grp_txt.setVisible(False)
        vl.addWidget(self._grp_txt)

        # ── Preview ───────────────────────────────────────────────────────────
        self._preview = QLabel("")
        self._preview.setStyleSheet("font-family: monospace; color: gray;")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignLeft)
        vl.addWidget(QLabel(tr("column_editor.label_preview")))
        vl.addWidget(self._preview)

        # ── Bottoni ───────────────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        vl.addWidget(btns)

        # Connessioni per aggiornamento preview
        self._rb_numbers.toggled.connect(self._on_mode_changed)
        for w in (self._num_initial, self._num_step, self._num_padding):
            w.valueChanged.connect(self._update_preview)
        for w in (self._num_prefix, self._num_suffix, self._txt_value):
            w.textChanged.connect(self._update_preview)
        self._num_fmt.currentIndexChanged.connect(self._update_preview)

        self._update_preview()

    def _on_mode_changed(self, numbers: bool) -> None:
        self._grp_num.setVisible(numbers)
        self._grp_txt.setVisible(not numbers)
        self._update_preview()

    def _format_number(self, n: int) -> str:
        fmt  = self._num_fmt.currentData()
        pad  = self._num_padding.value()
        pre  = self._num_prefix.text()
        suf  = self._num_suffix.text()
        if fmt == "hex":
            s = format(n, f"0{pad}x" if pad else "x")
        elif fmt == "oct":
            s = format(n, f"0{pad}o" if pad else "o")
        elif fmt == "bin":
            s = format(n, f"0{pad}b" if pad else "b")
        else:
            s = format(n, f"0{pad}d" if pad else "d")
        return f"{pre}{s}{suf}"

    def _update_preview(self) -> None:
        lines = []
        if self._rb_numbers.isChecked():
            val  = self._num_initial.value()
            step = self._num_step.value()
            for _ in range(5):
                lines.append(self._format_number(val))
                val += step
        else:
            txt = self._txt_value.text() or "(vuoto)"
            lines = [txt] * 5
        self._preview.setText("\n".join(lines))

    # ── Risultato ─────────────────────────────────────────────────────────────

    def get_values(self, n_lines: int) -> list[str]:
        """Restituisce la lista di stringhe da inserire, una per riga."""
        if self._rb_numbers.isChecked():
            val  = self._num_initial.value()
            step = self._num_step.value()
            result = []
            for _ in range(n_lines):
                result.append(self._format_number(val))
                val += step
            return result
        else:
            return [self._txt_value.text()] * n_lines

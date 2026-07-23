"""
ui/table_grid_picker.py — Popup griglia (Markdown) + Dialog avanzato (LaTeX)
NotePadPQ

Per Markdown: popup griglia NxM stile Word/LibreOffice.
Per LaTeX:    dialog completo con scelta ambiente, bordi, merge, caption/label.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, QRect, QSize, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QDialog,
    QDialogButtonBox, QFormLayout, QGroupBox, QSpinBox, QComboBox,
    QCheckBox, QPushButton, QTableWidget, QTableWidgetItem, QLineEdit,
    QHeaderView, QSizePolicy,
)

from i18n.i18n import tr

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget


# ─── Costanti griglia ────────────────────────────────────────────────────────

_MAX_COLS = 10
_MAX_ROWS = 10
_CELL_SIZE = 22
_GAP       = 2

_MAX_TABLE = 20   # max cols/rows nel dialog avanzato

def _get_table_env_items() -> list[tuple[str, str]]:
    return [
        ("tabular",   "tabular  —  standard"),
        ("tabularx",  tr("table_grid_picker.env_tabularx_desc",  default="tabularx  —  fixed width (X col)")),
        ("xltabular", tr("table_grid_picker.env_xltabular_desc", default="xltabular  —  multipage + fixed width")),
        ("longtable", "longtable  —  multipage"),
        ("tabulary",  tr("table_grid_picker.env_tabulary_desc",  default="tabulary  —  adaptive columns (L/C/R)")),
    ]


def _get_align_items() -> list[tuple[str, str]]:
    return [
        ("l",  tr("table_grid_picker.align_left",       default="l  —  left")),
        ("c",  tr("table_grid_picker.align_center",     default="c  —  center")),
        ("r",  tr("table_grid_picker.align_right",      default="r  —  right")),
        ("X",  tr("table_grid_picker.align_X",          default="X  —  auto-width  [tabularx]")),
        ("L",  tr("table_grid_picker.align_L_tabulary", default="L  —  adaptive left  [tabulary]")),
        ("C",  tr("table_grid_picker.align_C_tabulary", default="C  —  adaptive center  [tabulary]")),
        ("R",  tr("table_grid_picker.align_R_tabulary", default="R  —  adaptive right  [tabulary]")),
        ("p",  tr("table_grid_picker.align_paragraph",  default="p{3cm}  —  paragraph")),
    ]


def _get_border_items() -> list[tuple[str, str]]:
    return [
        ("",    tr("table_grid_picker.border_none",   default="none")),
        ("|",   tr("table_grid_picker.border_single", default="|  —  single")),
        ("||",  tr("table_grid_picker.border_double", default="||  —  double")),
    ]


_MERGE_ALIGN_ITEMS = [("l", "l"), ("c", "c"), ("r", "r")]


# ─── Widget griglia (Markdown popup) ─────────────────────────────────────────

class _GridWidget(QWidget):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._hover_col = 0
        self._hover_row = 0
        self.setMouseTracking(True)
        total_w = _MAX_COLS * (_CELL_SIZE + _GAP) + _GAP
        total_h = _MAX_ROWS * (_CELL_SIZE + _GAP) + _GAP
        self.setFixedSize(total_w, total_h)

    def sizeHint(self) -> QSize:
        return QSize(
            _MAX_COLS * (_CELL_SIZE + _GAP) + _GAP,
            _MAX_ROWS * (_CELL_SIZE + _GAP) + _GAP,
        )

    def _cell_at(self, pos: QPoint):
        col = (pos.x() - _GAP) // (_CELL_SIZE + _GAP) + 1
        row = (pos.y() - _GAP) // (_CELL_SIZE + _GAP) + 1
        if 1 <= col <= _MAX_COLS and 1 <= row <= _MAX_ROWS:
            return col, row
        return 0, 0

    def mouseMoveEvent(self, event) -> None:
        col, row = self._cell_at(event.pos())
        if col > 0 and row > 0:
            self._hover_col = col
            self._hover_row = row
            self.update()
            self.parent()._update_label(col, row)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            col, row = self._cell_at(event.pos())
            if col > 0 and row > 0:
                self.parent()._confirm(col, row)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        col_sel        = QColor("#264f78")
        col_hover      = QColor("#094771")
        col_empty      = QColor("#3c3c3c")
        col_border_sel = QColor("#4fc1ff")
        col_border_emp = QColor("#555555")
        for r in range(1, _MAX_ROWS + 1):
            for c in range(1, _MAX_COLS + 1):
                x = _GAP + (c - 1) * (_CELL_SIZE + _GAP)
                y = _GAP + (r - 1) * (_CELL_SIZE + _GAP)
                rect = QRect(x, y, _CELL_SIZE, _CELL_SIZE)
                in_sel = c <= self._hover_col and r <= self._hover_row
                is_edge = c == self._hover_col or r == self._hover_row
                fill   = (col_hover if is_edge else col_sel) if in_sel else col_empty
                border = col_border_sel if in_sel else col_border_emp
                p.fillRect(rect, fill)
                p.setPen(QPen(border, 1))
                p.drawRect(rect)
        p.end()


class _GridPopup(QFrame):
    def __init__(self, editor: "EditorWidget", parent: Optional[QWidget] = None):
        super().__init__(parent, Qt.WindowType.Popup)
        self._editor = editor
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)
        self.setStyleSheet(
            "QFrame { background: #252526; border: 1px solid #555; border-radius: 4px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        lang_label = QLabel(tr("table_grid_picker.label_markdown"))
        lang_label.setStyleSheet("color: #9cdcfe; font-size: 10px; font-weight: bold;")
        lang_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lang_label)
        self._grid = _GridWidget(self)
        layout.addWidget(self._grid)
        self._lbl = QLabel(tr("table_grid_picker.label_hint"))
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setStyleSheet("color: #cccccc; font-size: 11px; padding: 2px;")
        f = QFont(); f.setBold(True); self._lbl.setFont(f)
        layout.addWidget(self._lbl)
        hint = QLabel("Click per inserire  •  Esc per annullare")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #666; font-size: 9px;")
        layout.addWidget(hint)
        self.adjustSize()

    def _update_label(self, cols: int, rows: int) -> None:
        self._lbl.setText(f"{cols} colonne × {rows} righe")

    def _confirm(self, cols: int, rows: int) -> None:
        self.hide()
        _insert_code(self._editor, _build_markdown_table(rows, cols))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)


# ─── Dialog avanzato LaTeX ────────────────────────────────────────────────────

class _LaTeXTableDialog(QDialog):
    def __init__(self, editor: "EditorWidget", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(tr("table_grid_picker.latex_dialog_title", default="Tabella rapida"))
        self.resize(780, 700)
        self._editor = editor

        # ── Stato per-colonna ────────────────────────────────────────────────
        self._cols = 2
        self._col_align   = ["c"] * _MAX_TABLE
        self._col_lborder = ["|"] * _MAX_TABLE
        self._right_border = "|"

        # ── Stato per-riga ───────────────────────────────────────────────────
        self._rows = 2
        self._row_hline   = [True,  False] + [False] * (_MAX_TABLE - 2)
        # merge: None o (from_1based, to_1based, align_char)
        self._row_merge: list = [None] * _MAX_TABLE

        # ── Stato globale ────────────────────────────────────────────────────
        self._bottom_hline = True
        self._booktabs_pad = False

        self._build_ui()
        self._populate_col_combo()
        self._populate_row_combo()
        self._sync_col_ui(0)
        self._sync_row_ui(0)
        self._update_preview()

    # ── Costruzione UI ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        main = QVBoxLayout(self)
        main.setSpacing(6)

        # ── Preview ──────────────────────────────────────────────────────────
        self._preview = QTableWidget(self._rows, self._cols, self)
        self._preview.setFixedHeight(190)
        self._preview.horizontalHeader().setDefaultSectionSize(80)
        self._preview.verticalHeader().setDefaultSectionSize(28)
        self._preview.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        main.addWidget(self._preview)

        # ── Righe / Colonne ───────────────────────────────────────────────────
        rc = QHBoxLayout()
        rc.addWidget(QLabel(tr("table_grid_picker.num_cols", default="Numero di colonne")))
        self._spin_cols = QSpinBox()
        self._spin_cols.setRange(1, _MAX_TABLE)
        self._spin_cols.setValue(self._cols)
        self._spin_cols.setFixedWidth(90)
        rc.addWidget(self._spin_cols)
        rc.addSpacing(30)
        rc.addWidget(QLabel(tr("table_grid_picker.num_rows", default="Numero di righe")))
        self._spin_rows = QSpinBox()
        self._spin_rows.setRange(1, _MAX_TABLE)
        self._spin_rows.setValue(self._rows)
        self._spin_rows.setFixedWidth(90)
        rc.addWidget(self._spin_rows)
        rc.addStretch()
        main.addLayout(rc)

        # ── Pannelli Colonne + Righe ──────────────────────────────────────────
        panels = QHBoxLayout()

        # Pannello colonne
        col_grp = QGroupBox(tr("table_grid_picker.cols_group", default="Colonne"))
        col_form = QFormLayout(col_grp)

        self._combo_col_sel = QComboBox(); self._combo_col_sel.setFixedWidth(90)
        col_form.addRow(tr("table_grid_picker.col_label", default="Colonna:"), self._combo_col_sel)

        self._combo_col_align = QComboBox()
        for val, label in _get_align_items():
            self._combo_col_align.addItem(label, val)
        self._combo_col_align.setMinimumWidth(260)
        col_form.addRow(tr("table_grid_picker.alignment", default="Allineamento:"), self._combo_col_align)

        self._combo_col_lborder = QComboBox()
        for val, label in _get_border_items():
            self._combo_col_lborder.addItem(label, val)
        self._combo_col_lborder.setFixedWidth(160)
        col_form.addRow(tr("table_grid_picker.left_border", default="Bordo sinistro:"), self._combo_col_lborder)

        self._btn_apply_cols = QPushButton(tr("table_grid_picker.apply_all_cols", default="Applica a tutte le colonne"))
        col_form.addRow("", self._btn_apply_cols)

        self._combo_right_border = QComboBox()
        for val, label in _get_border_items():
            self._combo_right_border.addItem(label, val)
        self._combo_right_border.setFixedWidth(160)
        self._combo_right_border.setCurrentIndex(1)  # default "|"
        col_form.addRow(
            tr("table_grid_picker.right_border_last", default="Bordo destro (ultima colonna):"),
            self._combo_right_border,
        )

        panels.addWidget(col_grp)

        # Pannello righe
        row_grp = QGroupBox(tr("table_grid_picker.rows_group", default="Righe"))
        row_form = QFormLayout(row_grp)

        self._combo_row_sel = QComboBox(); self._combo_row_sel.setFixedWidth(90)
        row_form.addRow(tr("table_grid_picker.row_label", default="Riga:"), self._combo_row_sel)

        self._chk_row_hline = QCheckBox(tr("table_grid_picker.top_border", default="Bordo superiore"))
        row_form.addRow("", self._chk_row_hline)

        # Merge
        merge_row = QHBoxLayout()
        self._chk_merge = QCheckBox(tr("table_grid_picker.merge_cols", default="Unisci colonne:"))
        self._spin_merge_from = QSpinBox(); self._spin_merge_from.setRange(1, _MAX_TABLE); self._spin_merge_from.setFixedWidth(55)
        self._lbl_merge_arrow = QLabel("→")
        self._spin_merge_to   = QSpinBox(); self._spin_merge_to.setRange(1, _MAX_TABLE); self._spin_merge_to.setFixedWidth(55)
        self._combo_merge_align = QComboBox(); self._combo_merge_align.setFixedWidth(52)
        for val, label in _MERGE_ALIGN_ITEMS:
            self._combo_merge_align.addItem(label, val)
        merge_row.addWidget(self._spin_merge_from)
        merge_row.addWidget(self._lbl_merge_arrow)
        merge_row.addWidget(self._spin_merge_to)
        merge_row.addWidget(self._combo_merge_align)
        merge_row.addStretch()
        row_form.addRow(self._chk_merge, merge_row)

        self._btn_apply_rows = QPushButton(tr("table_grid_picker.apply_all_rows", default="Applica a tutte le righe"))
        row_form.addRow("", self._btn_apply_rows)

        panels.addWidget(row_grp)
        main.addLayout(panels)

        # ── Opzioni globali ───────────────────────────────────────────────────
        glob = QHBoxLayout()
        self._chk_bottom_hline = QCheckBox(tr("table_grid_picker.bottom_border", default="Bordo inferiore (ultima riga)"))
        self._chk_bottom_hline.setChecked(True)
        self._chk_booktabs_pad = QCheckBox(tr("table_grid_picker.booktabs_pad", default="Aggiungi margine verticale per ogni riga"))
        self._chk_booktabs = QCheckBox(tr("table_grid_picker.use_booktabs", default="Usa booktabs  (\\toprule / \\midrule / \\bottomrule)"))
        self._chk_booktabs.setToolTip(
            tr("table_grid_picker.use_booktabs_tip",
               default="Sostituisce \\hline con i comandi booktabs:\n"
                       "• 1ª riga → \\toprule\n"
                       "• Righe intermedie → \\midrule\n"
                       "• Bordo inferiore → \\bottomrule\n"
                       "Richiede \\usepackage{booktabs}")
        )
        glob.addWidget(self._chk_bottom_hline)
        glob.addWidget(self._chk_booktabs_pad)
        glob.addWidget(self._chk_booktabs)
        glob.addStretch()
        main.addLayout(glob)

        # ── Ambiente ──────────────────────────────────────────────────────────
        env_form = QFormLayout()
        self._combo_env = QComboBox()
        for val, label in _get_table_env_items():
            self._combo_env.addItem(label, val)
        self._combo_env.setMinimumWidth(340)
        env_form.addRow(tr("table_grid_picker.env_label", default="Ambiente:"), self._combo_env)

        self._lbl_width = QLabel(tr("table_grid_picker.width_label", default="Larghezza:"))
        self._edit_width = QLineEdit(r"\linewidth")
        self._edit_width.setFixedWidth(160)
        env_form.addRow(self._lbl_width, self._edit_width)

        self._edit_caption = QLineEdit()
        self._edit_caption.setPlaceholderText(tr("table_grid_picker.caption_ph", default="Didascalia (opzionale)"))
        env_form.addRow(tr("table_grid_picker.caption_label", default="Didascalia:"), self._edit_caption)

        self._edit_label = QLineEdit("tab:")
        env_form.addRow(tr("table_grid_picker.label_label", default="Label:"), self._edit_label)
        main.addLayout(env_form)

        # ── Bottoni ───────────────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        main.addWidget(btns)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText(tr("button.ok", default="OK"))
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("button.cancel", default="Cancel"))

        # ── Connessioni ───────────────────────────────────────────────────────
        self._spin_cols.valueChanged.connect(self._on_cols_changed)
        self._spin_rows.valueChanged.connect(self._on_rows_changed)

        self._combo_col_sel.currentIndexChanged.connect(self._on_col_sel_changed)
        self._combo_col_align.currentIndexChanged.connect(self._on_col_align_changed)
        self._combo_col_lborder.currentIndexChanged.connect(self._on_col_lborder_changed)
        self._combo_right_border.currentIndexChanged.connect(self._on_right_border_changed)
        self._btn_apply_cols.clicked.connect(self._apply_to_all_cols)

        self._combo_row_sel.currentIndexChanged.connect(self._on_row_sel_changed)
        self._chk_row_hline.toggled.connect(self._on_row_hline_toggled)
        self._chk_merge.toggled.connect(self._on_merge_toggled)
        self._spin_merge_from.valueChanged.connect(self._on_merge_from_changed)
        self._spin_merge_to.valueChanged.connect(self._on_merge_to_changed)
        self._combo_merge_align.currentIndexChanged.connect(self._on_merge_align_changed)
        self._btn_apply_rows.clicked.connect(self._apply_to_all_rows)

        self._chk_bottom_hline.toggled.connect(lambda _: self._update_preview())
        self._chk_booktabs_pad.toggled.connect(lambda _: self._update_preview())
        self._chk_booktabs.toggled.connect(self._on_booktabs_toggled)
        self._combo_env.currentIndexChanged.connect(self._on_env_changed)
        self._update_width_visibility()

    # ── Popola combo ──────────────────────────────────────────────────────────

    def _populate_col_combo(self) -> None:
        cur = self._combo_col_sel.currentIndex()
        self._combo_col_sel.blockSignals(True)
        self._combo_col_sel.clear()
        for i in range(self._cols):
            self._combo_col_sel.addItem(str(i + 1))
        idx = min(cur, self._cols - 1) if cur >= 0 else 0
        self._combo_col_sel.setCurrentIndex(idx)
        self._combo_col_sel.blockSignals(False)

    def _populate_row_combo(self) -> None:
        cur = self._combo_row_sel.currentIndex()
        self._combo_row_sel.blockSignals(True)
        self._combo_row_sel.clear()
        for i in range(self._rows):
            self._combo_row_sel.addItem(str(i + 1))
        idx = min(cur, self._rows - 1) if cur >= 0 else 0
        self._combo_row_sel.setCurrentIndex(idx)
        self._combo_row_sel.blockSignals(False)

    # ── Sync UI ↔ stato ───────────────────────────────────────────────────────

    def _sync_col_ui(self, col_idx: int) -> None:
        self._combo_col_align.blockSignals(True)
        self._combo_col_lborder.blockSignals(True)
        align = self._col_align[col_idx]
        for i in range(self._combo_col_align.count()):
            if self._combo_col_align.itemData(i) == align:
                self._combo_col_align.setCurrentIndex(i)
                break
        border = self._col_lborder[col_idx]
        for i in range(self._combo_col_lborder.count()):
            if self._combo_col_lborder.itemData(i) == border:
                self._combo_col_lborder.setCurrentIndex(i)
                break
        self._combo_col_align.blockSignals(False)
        self._combo_col_lborder.blockSignals(False)

        self._combo_right_border.blockSignals(True)
        rb = self._right_border
        for i in range(self._combo_right_border.count()):
            if self._combo_right_border.itemData(i) == rb:
                self._combo_right_border.setCurrentIndex(i)
                break
        self._combo_right_border.blockSignals(False)

    def _sync_row_ui(self, row_idx: int) -> None:
        self._chk_row_hline.blockSignals(True)
        self._chk_merge.blockSignals(True)
        self._spin_merge_from.blockSignals(True)
        self._spin_merge_to.blockSignals(True)
        self._combo_merge_align.blockSignals(True)

        self._chk_row_hline.setChecked(self._row_hline[row_idx])
        merge = self._row_merge[row_idx]
        has_merge = merge is not None
        self._chk_merge.setChecked(has_merge)
        self._spin_merge_from.setEnabled(has_merge)
        self._lbl_merge_arrow.setEnabled(has_merge)
        self._spin_merge_to.setEnabled(has_merge)
        self._combo_merge_align.setEnabled(has_merge)
        if merge:
            self._spin_merge_from.setValue(merge[0])
            self._spin_merge_to.setValue(merge[1])
            for i in range(self._combo_merge_align.count()):
                if self._combo_merge_align.itemData(i) == merge[2]:
                    self._combo_merge_align.setCurrentIndex(i)
                    break
        else:
            self._spin_merge_from.setValue(1)
            self._spin_merge_to.setValue(min(2, self._cols))

        self._chk_row_hline.blockSignals(False)
        self._chk_merge.blockSignals(False)
        self._spin_merge_from.blockSignals(False)
        self._spin_merge_to.blockSignals(False)
        self._combo_merge_align.blockSignals(False)

    # ── Slot colonne ──────────────────────────────────────────────────────────

    def _on_booktabs_toggled(self, checked: bool) -> None:
        if checked:
            # Setup predefinito booktabs: toprule sopra riga 0, midrule sopra riga 1, bottomrule in fondo
            self._row_hline[0] = True
            if self._rows > 1:
                self._row_hline[1] = True
            self._chk_bottom_hline.setChecked(True)
            # Rimuovi bordi verticali (sconsigliati con booktabs)
            for i in range(_MAX_TABLE):
                self._col_lborder[i] = ""
            self._right_border = ""
            self._combo_right_border.blockSignals(True)
            self._combo_right_border.setCurrentIndex(0)
            self._combo_right_border.blockSignals(False)
        row_idx = self._combo_row_sel.currentIndex()
        if row_idx >= 0:
            self._sync_row_ui(row_idx)
        col_idx = self._combo_col_sel.currentIndex()
        if col_idx >= 0:
            self._sync_col_ui(col_idx)
        self._update_preview()

    def _on_cols_changed(self, n: int) -> None:
        self._cols = n
        self._populate_col_combo()
        self._update_preview()

    def _on_col_sel_changed(self, idx: int) -> None:
        if idx >= 0:
            self._sync_col_ui(idx)

    def _on_col_align_changed(self, _: int) -> None:
        idx = self._combo_col_sel.currentIndex()
        if idx >= 0:
            self._col_align[idx] = self._combo_col_align.currentData()
            self._update_preview()

    def _on_col_lborder_changed(self, _: int) -> None:
        idx = self._combo_col_sel.currentIndex()
        if idx >= 0:
            self._col_lborder[idx] = self._combo_col_lborder.currentData()
            self._update_preview()

    def _on_right_border_changed(self, _: int) -> None:
        self._right_border = self._combo_right_border.currentData()
        self._update_preview()

    def _apply_to_all_cols(self) -> None:
        align  = self._combo_col_align.currentData()
        border = self._combo_col_lborder.currentData()
        for i in range(_MAX_TABLE):
            self._col_align[i]   = align
            self._col_lborder[i] = border
        self._update_preview()

    # ── Slot righe ────────────────────────────────────────────────────────────

    def _on_rows_changed(self, n: int) -> None:
        self._rows = n
        self._populate_row_combo()
        self._update_preview()

    def _on_row_sel_changed(self, idx: int) -> None:
        if idx >= 0:
            self._sync_row_ui(idx)

    def _on_row_hline_toggled(self, checked: bool) -> None:
        idx = self._combo_row_sel.currentIndex()
        if idx >= 0:
            self._row_hline[idx] = checked
            self._update_preview()

    def _on_merge_toggled(self, checked: bool) -> None:
        idx = self._combo_row_sel.currentIndex()
        self._spin_merge_from.setEnabled(checked)
        self._lbl_merge_arrow.setEnabled(checked)
        self._spin_merge_to.setEnabled(checked)
        self._combo_merge_align.setEnabled(checked)
        if idx >= 0:
            if checked:
                f = self._spin_merge_from.value()
                t = self._spin_merge_to.value()
                a = self._combo_merge_align.currentData() or "c"
                self._row_merge[idx] = (f, max(t, f + 1), a)
            else:
                self._row_merge[idx] = None
            self._update_preview()

    def _on_merge_from_changed(self, _: int) -> None:
        if not self._chk_merge.isChecked():
            return
        idx = self._combo_row_sel.currentIndex()
        if idx >= 0:
            f = self._spin_merge_from.value()
            t = max(self._spin_merge_to.value(), f + 1)
            self._spin_merge_to.setValue(t)
            a = self._combo_merge_align.currentData() or "c"
            self._row_merge[idx] = (f, t, a)
            self._update_preview()

    def _on_merge_to_changed(self, _: int) -> None:
        if not self._chk_merge.isChecked():
            return
        idx = self._combo_row_sel.currentIndex()
        if idx >= 0:
            f = self._spin_merge_from.value()
            t = self._spin_merge_to.value()
            a = self._combo_merge_align.currentData() or "c"
            self._row_merge[idx] = (f, max(t, f + 1), a)
            self._update_preview()

    def _on_merge_align_changed(self, _: int) -> None:
        if not self._chk_merge.isChecked():
            return
        idx = self._combo_row_sel.currentIndex()
        if idx >= 0 and self._row_merge[idx]:
            f, t, _ = self._row_merge[idx]
            self._row_merge[idx] = (f, t, self._combo_merge_align.currentData())

    def _apply_to_all_rows(self) -> None:
        hline = self._chk_row_hline.isChecked()
        for i in range(_MAX_TABLE):
            self._row_hline[i] = hline
        self._update_preview()

    # ── Slot ambiente ─────────────────────────────────────────────────────────

    def _on_env_changed(self, _: int) -> None:
        self._update_width_visibility()

    def _update_width_visibility(self) -> None:
        env = self._combo_env.currentData() or "tabular"
        needs_width = env in ("tabularx", "xltabular", "tabulary")
        self._lbl_width.setVisible(needs_width)
        self._edit_width.setVisible(needs_width)

    # ── Preview ───────────────────────────────────────────────────────────────

    def _build_col_spec(self) -> str:
        spec = ""
        for c in range(self._cols):
            spec += self._col_lborder[c]
            a = self._col_align[c]
            spec += "p{3cm}" if a == "p" else a
        spec += self._right_border
        return spec

    def _update_preview(self) -> None:
        self._preview.blockSignals(True)
        self._preview.setRowCount(self._rows)
        self._preview.setColumnCount(self._cols)

        # Column headers: show spec
        for c in range(self._cols):
            lb = self._col_lborder[c]
            a  = self._col_align[c]
            rb = self._right_border if c == self._cols - 1 else ""
            spec_str = f"{lb}{a}{rb}"
            self._preview.setHorizontalHeaderItem(c, QTableWidgetItem(spec_str))

        # Row headers: show hline / booktabs command
        booktabs = self._chk_booktabs.isChecked()
        for r in range(self._rows):
            if self._row_hline[r]:
                if booktabs:
                    cmd = "\\toprule" if r == 0 else "\\midrule"
                else:
                    cmd = "\\hline"
                label = f"{cmd} {r + 1}"
            else:
                label = f"  {r + 1}"
            self._preview.setVerticalHeaderItem(r, QTableWidgetItem(label))

        # Fill cells (first row = header text)
        for r in range(self._rows):
            merge = self._row_merge[r]
            # Reset all spans in this row first
            for c in range(self._cols):
                try:
                    self._preview.setSpan(r, c, 1, 1)
                except Exception:
                    pass
            if merge:
                f0, t0, a0 = merge[0] - 1, merge[1] - 1, merge[2]
                f0 = max(0, min(f0, self._cols - 1))
                t0 = max(f0 + 1, min(t0, self._cols - 1))
                span = t0 - f0 + 1
                try:
                    self._preview.setSpan(r, f0, 1, span)
                except Exception:
                    pass
                for c in range(self._cols):
                    if c == f0:
                        txt = f"\\multicolumn{{{span}}}{{{a0}}}{{}}" if r > 0 else f"Col {c+1}…{t0+1}"
                    elif f0 < c <= t0:
                        txt = ""
                    else:
                        txt = f"Col {c+1}" if r == 0 else ""
                    self._preview.setItem(r, c, QTableWidgetItem(txt))
            else:
                for c in range(self._cols):
                    txt = f"Col {c+1}" if r == 0 else ""
                    self._preview.setItem(r, c, QTableWidgetItem(txt))

        self._preview.blockSignals(False)

    # ── Generazione codice ────────────────────────────────────────────────────

    def _row_cells_str(self, r: int) -> str:
        merge = self._row_merge[r]
        if merge:
            f, t, a = merge[0] - 1, merge[1] - 1, merge[2]
            f = max(0, min(f, self._cols - 1))
            t = max(f + 1, min(t, self._cols - 1))
            cells = []
            c = 0
            while c < self._cols:
                if c == f:
                    span = t - f + 1
                    lb = self._col_lborder[c] if c == 0 else ""
                    rb = self._right_border if t == self._cols - 1 else ""
                    mc_spec = f"{lb}{a}{rb}" or a
                    cells.append(f"\\multicolumn{{{span}}}{{{mc_spec}}}{{}}")
                    c += span
                else:
                    cells.append("" if r > 0 else f"Col {c+1}")
                    c += 1
        else:
            cells = [f"Col {c+1}" if r == 0 else "" for c in range(self._cols)]
        return " & ".join(cells)

    def _generate_code(self) -> str:
        env      = self._combo_env.currentData() or "tabular"
        col_spec = self._build_col_spec()
        width    = self._edit_width.text().strip() or r"\linewidth"
        caption  = self._edit_caption.text().strip()
        label    = self._edit_label.text().strip()
        pad      = self._chk_booktabs_pad.isChecked()
        booktabs = self._chk_booktabs.isChecked()

        has_width = env in ("tabularx", "xltabular", "tabulary")
        wrapped   = env in ("tabular", "tabularx", "tabulary")
        long_env  = env in ("longtable", "xltabular")

        I1 = "    "
        I2 = "        "

        def env_open() -> str:
            if has_width:
                return f"\\begin{{{env}}}{{{width}}}{{{col_spec}}}"
            return f"\\begin{{{env}}}{{{col_spec}}}"

        def env_close() -> str:
            return f"\\end{{{env}}}"

        def hline_cmd(r: int) -> str:
            if booktabs:
                return "\\toprule" if r == 0 else "\\midrule"
            return "\\hline"

        def bottom_cmd() -> str:
            return "\\bottomrule" if booktabs else "\\hline"

        def build_data_rows(indent: str) -> list[str]:
            out = []
            for r in range(self._rows):
                if self._row_hline[r]:
                    out.append(f"{indent}{hline_cmd(r)}")
                if pad and r > 0:
                    spacer = "\\addlinespace" if booktabs else "\\rule{0pt}{2.5ex}"
                    out.append(f"{indent}{spacer}")
                out.append(f"{indent}{self._row_cells_str(r)} \\\\")
            return out

        lines: list[str] = []

        if booktabs:
            lines.append("% \\usepackage{booktabs}  % required")

        if wrapped:
            lines += [
                "\\begin{table}[htbp]",
                f"{I1}\\centering",
                f"{I1}{env_open()}",
            ]
            lines += build_data_rows(I2)
            if self._chk_bottom_hline.isChecked():
                lines.append(f"{I2}{bottom_cmd()}")
            lines.append(f"{I1}{env_close()}")
            if caption:
                lines.append(f"{I1}\\caption{{{caption}}}")
            if label:
                lines.append(f"{I1}\\label{{{label}}}")
            lines.append("\\end{table}")

        elif long_env:
            lines.append(env_open())
            if caption or label:
                c_str = f"\\caption{{{caption}}}" if caption else ""
                l_str = f"\\label{{{label}}}" if label else ""
                lines.append(f"{I1}{c_str}{l_str} \\\\")
            hdr = " & ".join(f"Col {c+1}" for c in range(self._cols))
            if booktabs:
                lines += [
                    f"{I1}\\toprule",
                    f"{I1}{hdr} \\\\",
                    f"{I1}\\midrule",
                    f"{I1}\\endfirsthead",
                    f"{I1}\\toprule",
                    f"{I1}{hdr} \\\\",
                    f"{I1}\\midrule",
                    f"{I1}\\endhead",
                    f"{I1}\\bottomrule",
                    f"{I1}\\endfoot",
                    f"{I1}\\bottomrule",
                    f"{I1}\\endlastfoot",
                ]
            else:
                lines += [
                    f"{I1}\\hline",
                    f"{I1}{hdr} \\\\",
                    f"{I1}\\hline",
                    f"{I1}\\endfirsthead",
                    f"{I1}\\hline",
                    f"{I1}{hdr} \\\\",
                    f"{I1}\\hline",
                    f"{I1}\\endhead",
                    f"{I1}\\hline",
                    f"{I1}\\endfoot",
                    f"{I1}\\hline",
                    f"{I1}\\endlastfoot",
                ]
            lines += build_data_rows(I1)
            if self._chk_bottom_hline.isChecked():
                lines.append(f"{I1}{bottom_cmd()}")
            lines.append(env_close())

        return "\n".join(lines)

    def _on_accept(self) -> None:
        code = self._generate_code()
        _insert_code(self._editor, code)
        self.accept()


# ─── Generatori di codice ─────────────────────────────────────────────────────

def _build_markdown_table(rows: int, cols: int) -> str:
    headers   = [f"Col {c+1}" for c in range(cols)]
    col_widths = [len(h) for h in headers]
    header   = "| " + " | ".join(headers) + " |"
    sep      = "| " + " | ".join("-" * w for w in col_widths) + " |"
    data_row = "| " + " | ".join(" " * w for w in col_widths) + " |"
    return "\n".join([header, sep] + [data_row] * (rows - 1))


def _insert_code(editor: "EditorWidget", code: str) -> None:
    editor.beginUndoAction()
    if editor.hasSelectedText():
        editor.replaceSelectedText(code)
    else:
        line, col = editor.getCursorPosition()
        line_text = editor.text(line).rstrip('\n')
        if line_text.strip():
            editor.insert("\n" + code)
        else:
            editor.insert(code)
    editor.endUndoAction()
    editor.setFocus()


# ─── Entry point pubblico ─────────────────────────────────────────────────────

class TableGridPicker:
    @staticmethod
    def show_for_editor(
        editor: "EditorWidget",
        is_latex: bool,
        parent: Optional[QWidget] = None,
        pos: Optional[QPoint] = None,
    ) -> None:
        if is_latex:
            dlg = _LaTeXTableDialog(editor, parent)
            dlg.exec()
        else:
            popup = _GridPopup(editor, parent)
            if pos is not None:
                popup.move(pos)
            elif parent is not None:
                popup.move(parent.mapToGlobal(QPoint(0, parent.height())))
            popup.show()
            popup.activateWindow()

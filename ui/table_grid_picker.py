"""
ui/table_grid_picker.py — Popup griglia per inserimento rapido tabelle
NotePadPQ

Popup stile Word/LibreOffice: una griglia NxM su cui si sposta
il mouse (o si trascina) per scegliere righe e colonne.
Alla conferma (click) genera il codice LaTeX o Markdown e lo
inserisce nell'editor corrente.

Uso:
    TableGridPicker.show_for_editor(editor, is_latex=True, parent=parent_widget)
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, QRect, QSize, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget


# ─── Costanti griglia ────────────────────────────────────────────────────────

_MAX_COLS = 10
_MAX_ROWS = 10
_CELL_SIZE = 22   # pixel per cella
_GAP       = 2    # spazio tra celle


# ─── Widget griglia ───────────────────────────────────────────────────────────

class _GridWidget(QWidget):
    """
    Griglia interattiva NxM.
    Il mouse seleziona le celle; il click conferma la selezione.
    """

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._hover_col = 0
        self._hover_row = 0
        self.setMouseTracking(True)

        total_w = _MAX_COLS * (_CELL_SIZE + _GAP) + _GAP
        total_h = _MAX_ROWS * (_CELL_SIZE + _GAP) + _GAP
        self.setFixedSize(total_w, total_h)

    def sizeHint(self) -> QSize:
        w = _MAX_COLS * (_CELL_SIZE + _GAP) + _GAP
        h = _MAX_ROWS * (_CELL_SIZE + _GAP) + _GAP
        return QSize(w, h)

    def _cell_at(self, pos: QPoint):
        """Restituisce (col, row) 1-based o (0,0) se fuori griglia."""
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

        col_sel = QColor("#264f78")
        col_hover = QColor("#094771")
        col_empty = QColor("#3c3c3c")
        col_border_sel = QColor("#4fc1ff")
        col_border_empty = QColor("#555555")

        for r in range(1, _MAX_ROWS + 1):
            for c in range(1, _MAX_COLS + 1):
                x = _GAP + (c - 1) * (_CELL_SIZE + _GAP)
                y = _GAP + (r - 1) * (_CELL_SIZE + _GAP)
                rect = QRect(x, y, _CELL_SIZE, _CELL_SIZE)

                in_sel = c <= self._hover_col and r <= self._hover_row
                is_edge = c == self._hover_col or r == self._hover_row

                if in_sel:
                    fill = col_hover if is_edge else col_sel
                    border = col_border_sel
                else:
                    fill = col_empty
                    border = col_border_empty

                p.fillRect(rect, fill)
                p.setPen(QPen(border, 1))
                p.drawRect(rect)

        p.end()


# ─── Popup ────────────────────────────────────────────────────────────────────

class _GridPopup(QFrame):
    """
    Finestra popup flottante con la griglia e l'etichetta NxM.
    """

    def __init__(self, editor: "EditorWidget", is_latex: bool,
                 parent: Optional[QWidget] = None):
        super().__init__(parent, Qt.WindowType.Popup)
        self._editor = editor
        self._is_latex = is_latex

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)
        self.setStyleSheet(
            "QFrame { background: #252526; border: 1px solid #555; border-radius: 4px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Etichetta tipo linguaggio
        lang_label = QLabel("LaTeX tabular" if is_latex else "Tabella Markdown")
        lang_label.setStyleSheet("color: #9cdcfe; font-size: 10px; font-weight: bold;")
        lang_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lang_label)

        # Griglia
        self._grid = _GridWidget(self)
        layout.addWidget(self._grid)

        # Etichetta selezione corrente
        self._lbl = QLabel("Sposta il mouse sulla griglia")
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setStyleSheet("color: #cccccc; font-size: 11px; padding: 2px;")
        font = QFont()
        font.setBold(True)
        self._lbl.setFont(font)
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
        if self._is_latex:
            code = _build_latex_table(rows, cols)
        else:
            code = _build_markdown_table(rows, cols)
        _insert_code(self._editor, code)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)


# ─── Generatori di codice ─────────────────────────────────────────────────────

def _build_markdown_table(rows: int, cols: int) -> str:
    """Genera tabella Markdown con header riga e separatore allineati."""
    headers   = [f"Col {c+1}" for c in range(cols)]
    col_widths = [len(h) for h in headers]
    header   = "| " + " | ".join(h for h in headers) + " |"
    sep      = "| " + " | ".join("-" * w for w in col_widths) + " |"
    data_row = "| " + " | ".join(" " * w for w in col_widths) + " |"
    lines = [header, sep] + [data_row] * (rows - 1)
    return "\n".join(lines)


def _build_latex_table(rows: int, cols: int) -> str:
    """Genera tabella LaTeX con booktabs e colonne 'l'."""
    col_spec = "l" * cols
    header_cells = " & ".join(f"Col {c+1}" for c in range(cols))
    empty_cells  = " & ".join("" for _ in range(cols))

    lines = [
        "\\begin{table}[htbp]",
        "    \\centering",
        f"    \\begin{{tabular}}{{{col_spec}}}",
        "        \\toprule",
        f"        {header_cells} \\\\",
        "        \\midrule",
    ]
    for _ in range(rows - 1):
        lines.append(f"        {empty_cells} \\\\")
    lines += [
        "        \\bottomrule",
        "    \\end{tabular}",
        "    \\caption{}",
        "    \\label{tab:}",
        "\\end{table}",
    ]
    return "\n".join(lines)


def _insert_code(editor: "EditorWidget", code: str) -> None:
    """Inserisce il codice nell'editor alla posizione corrente."""
    editor.beginUndoAction()
    if editor.hasSelectedText():
        editor.replaceSelectedText(code)
    else:
        line, col = editor.getCursorPosition()
        # Se la riga corrente non è vuota, vai a capo prima
        line_text = editor.text(line).rstrip('\n')
        if line_text.strip():
            editor.insert("\n" + code)
        else:
            editor.insert(code)
    editor.endUndoAction()
    editor.setFocus()


# ─── Entry point pubblico ─────────────────────────────────────────────────────

class TableGridPicker:
    """
    API pubblica: mostra il popup griglia vicino al widget chiamante.
    """

    @staticmethod
    def show_for_editor(
        editor: "EditorWidget",
        is_latex: bool,
        parent: Optional[QWidget] = None,
        pos: Optional[QPoint] = None,
    ) -> None:
        """
        Mostra il popup griglia.

        Args:
            editor:   editor in cui inserire il codice
            is_latex: True → genera LaTeX, False → genera Markdown
            parent:   widget genitore (usato per posizionare il popup)
            pos:      posizione globale esplicita (opzionale)
        """
        popup = _GridPopup(editor, is_latex, parent)

        if pos is not None:
            popup.move(pos)
        elif parent is not None:
            # Posiziona sotto il widget chiamante
            global_pos = parent.mapToGlobal(QPoint(0, parent.height()))
            popup.move(global_pos)

        popup.show()
        popup.activateWindow()

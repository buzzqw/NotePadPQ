"""Dialog opzioni di stampa con header e footer configurabili."""
import datetime
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QCheckBox, QComboBox, QLineEdit, QLabel, QFontComboBox,
    QSpinBox, QDialogButtonBox, QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPainter, QColor
from PyQt6.QtPrintSupport import QPrinter


# Token sostituiti a runtime nella stringa header/footer
_TOKENS = {
    "{file}":    "Nome file",
    "{path}":    "Percorso completo",
    "{date}":    "Data",
    "{time}":    "Ora",
    "{page}":    "Numero pagina",
    "{pages}":   "Totale pagine",
}

_PRESETS = [
    ("(vuoto)", "", "", ""),
    ("Nome file | Data | Pagina",
     "{file}", "{date}", "Pagina {page} di {pages}"),
    ("Solo pagina (centrata)",
     "", "Pagina {page} di {pages}", ""),
    ("Percorso a sinistra, ora a destra",
     "{path}", "", "{time}"),
]


class _HFRow(QFrame):
    """Riga con tre campi: sinistra, centro, destra per header o footer."""

    def __init__(self, label: str):
        super().__init__()
        hl = QHBoxLayout(self)
        hl.setContentsMargins(0, 0, 0, 0)
        self._left   = QLineEdit(); self._left.setPlaceholderText("Sinistra")
        self._center = QLineEdit(); self._center.setPlaceholderText("Centro")
        self._right  = QLineEdit(); self._right.setPlaceholderText("Destra")
        hl.addWidget(QLabel(f"{label}:"))
        hl.addWidget(self._left,   1)
        hl.addWidget(self._center, 1)
        hl.addWidget(self._right,  1)

    def set_values(self, left: str, center: str, right: str) -> None:
        self._left.setText(left)
        self._center.setText(center)
        self._right.setText(right)

    def get_values(self) -> tuple[str, str, str]:
        return self._left.text(), self._center.text(), self._right.text()


class PrintOptionsDialog(QDialog):
    def __init__(self, parent=None, file_path=None):
        super().__init__(parent)
        self._file_path = file_path
        self.setWindowTitle("Opzioni di stampa")
        self.resize(580, 400)

        vl = QVBoxLayout(self)

        # ── Preset ────────────────────────────────────────────────────────────
        hl_preset = QHBoxLayout()
        hl_preset.addWidget(QLabel("Preset:"))
        self._preset_combo = QComboBox()
        for name, *_ in _PRESETS:
            self._preset_combo.addItem(name)
        hl_preset.addWidget(self._preset_combo, 1)
        vl.addLayout(hl_preset)

        # ── Header ────────────────────────────────────────────────────────────
        grp_h = QGroupBox("Intestazione (header)")
        gh = QVBoxLayout(grp_h)
        self._hdr_enabled = QCheckBox("Abilita intestazione")
        self._hdr_enabled.setChecked(True)
        gh.addWidget(self._hdr_enabled)
        self._hdr_row = _HFRow("  Testo")
        gh.addWidget(self._hdr_row)
        self._hdr_line = QCheckBox("Linea separatrice sotto l'intestazione")
        self._hdr_line.setChecked(True)
        gh.addWidget(self._hdr_line)
        vl.addWidget(grp_h)

        # ── Footer ────────────────────────────────────────────────────────────
        grp_f = QGroupBox("Piè di pagina (footer)")
        gf = QVBoxLayout(grp_f)
        self._ftr_enabled = QCheckBox("Abilita piè di pagina")
        self._ftr_enabled.setChecked(True)
        gf.addWidget(self._ftr_enabled)
        self._ftr_row = _HFRow("  Testo")
        gf.addWidget(self._ftr_row)
        self._ftr_line = QCheckBox("Linea separatrice sopra il piè di pagina")
        self._ftr_line.setChecked(True)
        gf.addWidget(self._ftr_line)
        vl.addWidget(grp_f)

        # ── Font header/footer ────────────────────────────────────────────────
        fl = QFormLayout()
        self._hf_font = QFontComboBox()
        self._hf_font.setCurrentFont(QFont("Sans Serif"))
        self._hf_size = QSpinBox()
        self._hf_size.setRange(6, 24)
        self._hf_size.setValue(8)
        fl.addRow("Font h/f:", self._hf_font)
        fl.addRow("Dimensione:", self._hf_size)
        vl.addLayout(fl)

        # ── Token helper ──────────────────────────────────────────────────────
        tokens_str = "  ".join(f"{k} = {v}" for k, v in _TOKENS.items())
        lbl = QLabel(f"Token disponibili: {tokens_str}")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: gray; font-size: 9px;")
        vl.addWidget(lbl)

        # ── Bottoni ───────────────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        vl.addWidget(btns)

        # Preset defaults
        self._preset_combo.currentIndexChanged.connect(self._apply_preset)
        self._apply_preset(1)   # "Nome file | Data | Pagina"

    def _apply_preset(self, idx: int) -> None:
        if idx == 0:
            self._hdr_row.set_values("", "", "")
            self._ftr_row.set_values("", "", "")
            return
        _, hl, hc, hr = _PRESETS[idx]
        self._hdr_row.set_values(hl, hc, hr)
        self._ftr_row.set_values("", "Pagina {page} di {pages}", "")

    # ── Accessors ─────────────────────────────────────────────────────────────

    def header_enabled(self) -> bool:
        return self._hdr_enabled.isChecked()

    def footer_enabled(self) -> bool:
        return self._ftr_enabled.isChecked()

    def header_values(self) -> tuple[str, str, str]:
        return self._hdr_row.get_values()

    def footer_values(self) -> tuple[str, str, str]:
        return self._ftr_row.get_values()

    def header_line(self) -> bool:
        return self._hdr_line.isChecked()

    def footer_line(self) -> bool:
        return self._ftr_line.isChecked()

    def hf_font(self) -> QFont:
        f = self._hf_font.currentFont()
        f.setPointSize(self._hf_size.value())
        return f


# ── Funzioni di rendering ─────────────────────────────────────────────────────

def _resolve_tokens(text: str, page: int, total_pages: int, file_path) -> str:
    now = datetime.datetime.now()
    name = file_path.name if file_path else "senza_nome"
    path = str(file_path) if file_path else "senza_nome"
    return (text
            .replace("{file}",  name)
            .replace("{path}",  path)
            .replace("{date}",  now.strftime("%d/%m/%Y"))
            .replace("{time}",  now.strftime("%H:%M"))
            .replace("{page}",  str(page))
            .replace("{pages}", str(total_pages)))


def print_with_header_footer(printer: QPrinter, editor, options: PrintOptionsDialog) -> None:
    """Stampa il documento con header/footer. Usa QTextDocument per il corpo."""
    from PyQt6.QtGui import QTextDocument, QTextCursor, QFontMetrics
    from PyQt6.QtCore import QRectF, QSizeF

    hf_font = options.hf_font()
    fm = QFontMetrics(hf_font)
    hf_height = fm.height() + 4  # margine interno

    # Calcola area utile
    page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
    margin_top    = hf_height + 6 if options.header_enabled() else 0
    margin_bottom = hf_height + 6 if options.footer_enabled() else 0
    body_rect = QRectF(
        page_rect.left(),
        page_rect.top()    + margin_top,
        page_rect.width(),
        page_rect.height() - margin_top - margin_bottom,
    )

    # Costruisce QTextDocument dal testo dell'editor
    doc = QTextDocument()
    doc.setDefaultFont(editor.font())
    doc.setPlainText(editor.text())
    doc.setPageSize(QSizeF(body_rect.width(), body_rect.height()))

    total_pages = doc.pageCount()

    painter = QPainter(printer)
    painter.setFont(hf_font)

    for page_num in range(1, total_pages + 1):
        if page_num > 1:
            printer.newPage()

        # ── Disegna header ────────────────────────────────────────────────────
        if options.header_enabled():
            hl, hc, hr = options.header_values()
            hl = _resolve_tokens(hl, page_num, total_pages, options._file_path)
            hc = _resolve_tokens(hc, page_num, total_pages, options._file_path)
            hr = _resolve_tokens(hr, page_num, total_pages, options._file_path)
            y = int(page_rect.top())
            w = int(page_rect.width())
            painter.drawText(int(page_rect.left()), y, w, hf_height,
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, hl)
            painter.drawText(int(page_rect.left()), y, w, hf_height,
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, hc)
            painter.drawText(int(page_rect.left()), y, w, hf_height,
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, hr)
            if options.header_line():
                ly = int(page_rect.top() + hf_height + 2)
                painter.drawLine(int(page_rect.left()), ly, int(page_rect.right()), ly)

        # ── Disegna footer ────────────────────────────────────────────────────
        if options.footer_enabled():
            fl2, fc, fr = options.footer_values()
            fl2 = _resolve_tokens(fl2, page_num, total_pages, options._file_path)
            fc  = _resolve_tokens(fc,  page_num, total_pages, options._file_path)
            fr  = _resolve_tokens(fr,  page_num, total_pages, options._file_path)
            y   = int(page_rect.bottom() - hf_height)
            w   = int(page_rect.width())
            if options.footer_line():
                painter.drawLine(int(page_rect.left()), y - 2,
                                 int(page_rect.right()), y - 2)
            painter.drawText(int(page_rect.left()), y, w, hf_height,
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, fl2)
            painter.drawText(int(page_rect.left()), y, w, hf_height,
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, fc)
            painter.drawText(int(page_rect.left()), y, w, hf_height,
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, fr)

        # ── Disegna corpo pagina ───────────────────────────────────────────────
        painter.save()
        painter.translate(body_rect.left(),
                          body_rect.top() - (page_num - 1) * body_rect.height())
        clip = QRectF(0, (page_num - 1) * body_rect.height(),
                      body_rect.width(), body_rect.height())
        doc.drawContents(painter, clip)
        painter.restore()

    painter.end()

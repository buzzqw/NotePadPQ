"""Pannello dock con tabella Unicode per l'inserimento di caratteri speciali."""
import unicodedata
from PyQt6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QComboBox, QTableWidget, QTableWidgetItem,
    QLabel, QAbstractItemView, QSizePolicy,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont

from i18n.i18n import tr


# Categorie Unicode con range di code point da mostrare
# Le chiavi i18n vengono risolte a runtime in _build_categories()
_CATEGORY_KEYS = [
    ("character_panel.cat_latin_basic",   0x0020, 0x007E),
    ("character_panel.cat_latin_ext_a",   0x00C0, 0x017E),
    ("character_panel.cat_latin_ext_b",   0x0180, 0x024F),
    ("character_panel.cat_ipa",           0x0250, 0x02AF),
    ("character_panel.cat_diacritics",    0x0300, 0x036F),
    ("character_panel.cat_greek",         0x0370, 0x03FF),
    ("character_panel.cat_cyrillic",      0x0400, 0x04FF),
    ("character_panel.cat_hebrew",        0x05D0, 0x05EA),
    ("character_panel.cat_arabic",        0x0600, 0x06FF),
    ("character_panel.cat_punctuation",   0x2000, 0x206F),
    ("character_panel.cat_currency",      0x20A0, 0x20CF),
    ("character_panel.cat_letterlike",    0x2100, 0x214F),
    ("character_panel.cat_arrows",        0x2190, 0x21FF),
    ("character_panel.cat_math",          0x2200, 0x22FF),
    ("character_panel.cat_technical",     0x2300, 0x23FF),
    ("character_panel.cat_misc",          0x2600, 0x26FF),
    ("character_panel.cat_dingbats",      0x2700, 0x27BF),
    ("character_panel.cat_cjk",           0x4E00, 0x4EFF),
    ("character_panel.cat_emoji",         0x1F300, 0x1F5FF),
    ("character_panel.cat_emoji_people",  0x1F600, 0x1F64F),
]


def _build_categories():
    """Costruisce la lista categorie con i nomi tradotti."""
    return [(tr(key), start, end) for key, start, end in _CATEGORY_KEYS]

_CELL_SIZE = 28
_COLS      = 16


class CharacterPanel(QDockWidget):
    def __init__(self, main_window):
        super().__init__(tr("character_panel.dock_title"), main_window)
        self._mw = main_window
        self.setObjectName("CharacterPanel")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea |
            Qt.DockWidgetArea.BottomDockWidgetArea
        )

        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(4, 4, 4, 4)
        vl.setSpacing(4)

        # Barra superiore: combo categoria + filtro ricerca
        top = QHBoxLayout()
        self._categories = _build_categories()
        self._combo = QComboBox()
        for name, *_ in self._categories:
            self._combo.addItem(name)
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("character_panel.placeholder_search"))
        self._search.setClearButtonEnabled(True)
        top.addWidget(self._combo, 2)
        top.addWidget(self._search, 3)
        vl.addLayout(top)

        # Tabella griglia
        self._table = QTableWidget()
        self._table.setColumnCount(_COLS)
        self._table.horizontalHeader().setVisible(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(True)
        for c in range(_COLS):
            self._table.setColumnWidth(c, _CELL_SIZE)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        font = QFont()
        font.setPointSize(12)
        self._table.setFont(font)

        vl.addWidget(self._table, 1)

        # Info riga in fondo
        self._info = QLabel("")
        self._info.setAlignment(Qt.AlignmentFlag.AlignLeft)
        vl.addWidget(self._info)

        self.setWidget(w)

        self._combo.currentIndexChanged.connect(self._load_category)
        self._search.textChanged.connect(self._on_search)
        self._table.cellActivated.connect(self._insert_char)
        self._table.currentCellChanged.connect(self._update_info)

        self._load_category(0)

    # ── Caricamento dati ──────────────────────────────────────────────────────

    def _load_category(self, idx: int) -> None:
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        _, start, end = self._categories[idx]
        chars = []
        for cp in range(start, end + 1):
            try:
                ch = chr(cp)
                unicodedata.name(ch)  # esclude non assegnati
                chars.append(ch)
            except (ValueError, TypeError):
                pass
        self._fill_table(chars)

    def _on_search(self, text: str) -> None:
        text = text.strip()
        if not text:
            self._load_category(self._combo.currentIndex())
            return

        chars = []
        # Ricerca per code point U+XXXX
        if text.upper().startswith("U+"):
            try:
                cp = int(text[2:], 16)
                chars = [chr(cp)]
            except ValueError:
                pass
        else:
            kw = text.upper()
            for cp in range(0x0020, 0x1FFFF):
                try:
                    ch = chr(cp)
                    name = unicodedata.name(ch, "")
                    if kw in name:
                        chars.append(ch)
                        if len(chars) >= 512:
                            break
                except (ValueError, TypeError):
                    pass
        self._fill_table(chars)

    def _fill_table(self, chars: list) -> None:
        self._table.clearContents()
        rows = max(1, (len(chars) + _COLS - 1) // _COLS)
        self._table.setRowCount(rows)
        for r in range(rows):
            self._table.setRowHeight(r, _CELL_SIZE)
        for i, ch in enumerate(chars):
            r, c = divmod(i, _COLS)
            item = QTableWidgetItem(ch)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setData(Qt.ItemDataRole.UserRole, ch)
            self._table.setItem(r, c, item)

    # ── Interazione ───────────────────────────────────────────────────────────

    def _insert_char(self, row: int, col: int) -> None:
        item = self._table.item(row, col)
        if not item:
            return
        ch = item.data(Qt.ItemDataRole.UserRole)
        if not ch:
            return
        editor = self._mw._current_editor()
        if editor:
            editor.insert(ch)
            editor.setFocus()

    def _update_info(self, row: int, col: int, *_) -> None:
        item = self._table.item(row, col)
        if not item:
            self._info.setText("")
            return
        ch = item.data(Qt.ItemDataRole.UserRole)
        if not ch:
            self._info.setText("")
            return
        cp = ord(ch)
        name = unicodedata.name(ch, "?")
        self._info.setText(f"U+{cp:04X}  {name}")

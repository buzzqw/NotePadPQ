"""
ui/theme_editor.py — Editor Tema Custom
NotePadPQ

Dialog per modificare ogni colore e font di un tema.
Mostra una lista di token con swatch colore cliccabili.
Supporta import/export e anteprima live sull'editor corrente.
"""

from __future__ import annotations

import copy
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPixmap, QIcon
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter,
    QListWidget, QListWidgetItem, QFormLayout,
    QLabel, QPushButton, QCheckBox, QSpinBox,
    QColorDialog, QFontComboBox, QDialogButtonBox,
    QGroupBox, QWidget, QScrollArea, QInputDialog,
    QFileDialog,
)

from i18n.i18n import tr
from config.themes import ThemeManager, BUILTIN_THEMES

if TYPE_CHECKING:
    from ui.main_window import MainWindow

# Descrizioni leggibili per ogni token
TOKEN_LABELS: dict[str, str] = {
    "default":         "Testo predefinito",
    "comment":         "Commento riga",
    "comment_block":   "Commento blocco",
    "keyword":         "Parola chiave",
    "keyword2":        "Parola chiave 2",
    "string":          "Stringa",
    "string2":         "Stringa 2",
    "string_raw":      "Stringa raw",
    "number":          "Numero",
    "operator":        "Operatore",
    "identifier":      "Identificatore",
    "function":        "Funzione",
    "class_name":      "Classe",
    "builtin":         "Builtin",
    "decorator":       "Decoratore",
    "preprocessor":    "Preprocessore",
    "regex":           "Espressione regolare",
    "constant":        "Costante",
    "type":            "Tipo",
    "label":           "Label",
    "error":           "Errore",
    "unclosed_string": "Stringa non chiusa",
    "tag":             "Tag (HTML/XML)",
    "attribute":       "Attributo",
    "attribute_value": "Valore attributo",
    "entity":          "Entità",
    "command":         "Comando (LaTeX)",
    "math":            "Matematica (LaTeX)",
    "math_command":    "Comando matematico (LaTeX)",
    "environment":     "Ambiente (LaTeX)",
    "special_char":    "Carattere speciale",
}

UI_LABELS: dict[str, str] = {
    "editor_bg":      "Sfondo editor",
    "editor_fg":      "Testo predefinito",
    "margin_bg":      "Sfondo margine",
    "margin_fg":      "Testo margine",
    "caret_line_bg":  "Sfondo riga cursore",
    "caret_fg":       "Cursore",
    "selection_bg":   "Sfondo selezione",
    "brace_match_bg": "Sfondo parentesi corrispondente",
    "brace_match_fg": "Testo parentesi corrispondente",
    "brace_bad_bg":   "Sfondo parentesi errata",
    "brace_bad_fg":   "Testo parentesi errata",
    "find_indicator": "Indicatore Find",
    "whitespace_fg":  "Spazi visibili",
    "fold_fg":        "Simboli folding",
    "fold_bg":        "Sfondo folding",
}


def _color_swatch(color_str: Optional[str]) -> QIcon:
    """Crea un'icona quadrata con il colore dato."""
    px = QPixmap(16, 16)
    if color_str:
        px.fill(QColor(color_str))
    else:
        px.fill(QColor("#888888"))
    return QIcon(px)


class ThemeEditorDialog(QDialog):

    def __init__(self, main_window: "MainWindow",
                 theme_name: str = ""):
        super().__init__(main_window)
        self._mw = main_window
        self._tm = ThemeManager.instance()

        # Clona il tema da modificare
        source = theme_name or self._tm.active_name()
        original = self._tm.get_theme(source) or {}
        self._theme = copy.deepcopy(original)

        # Se è un built-in, chiede il nome per il clone
        if source in BUILTIN_THEMES and not theme_name:
            name, ok = QInputDialog.getText(
                self, "Nuovo tema",
                f"Nome per il nuovo tema (copia di {source}):"
            )
            if not ok or not name:
                self._theme["meta"]["name"] = f"{source} (copia)"
            else:
                self._theme["meta"]["name"] = name
        
        self.setWindowTitle(
            f"Editor tema — {self._theme.get('meta', {}).get('name', source)}"
        )
        self.resize(750, 560)
        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Lista token ───────────────────────────────────────────────────
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)

        self._tabs_list = QListWidget()
        self._tabs_list.currentItemChanged.connect(self._on_item_changed)

        # Sezione UI
        sep_ui = QListWidgetItem("── Colori UI ──")
        sep_ui.setFlags(Qt.ItemFlag.NoItemFlags)
        sep_ui.setForeground(QColor("#888"))
        self._tabs_list.addItem(sep_ui)
        for key, label in UI_LABELS.items():
            item = QListWidgetItem(_color_swatch(
                self._theme.get("ui", {}).get(key)), label
            )
            item.setData(Qt.ItemDataRole.UserRole, ("ui", key))
            self._tabs_list.addItem(item)

        # Sezione Token
        sep_tok = QListWidgetItem("── Token sintassi ──")
        sep_tok.setFlags(Qt.ItemFlag.NoItemFlags)
        sep_tok.setForeground(QColor("#888"))
        self._tabs_list.addItem(sep_tok)
        for key, label in TOKEN_LABELS.items():
            item = QListWidgetItem(_color_swatch(
                self._theme.get("tokens", {}).get(key, {}).get("fg")), label
            )
            item.setData(Qt.ItemDataRole.UserRole, ("tokens", key))
            self._tabs_list.addItem(item)

        ll.addWidget(self._tabs_list, 1)
        splitter.addWidget(left)

        # ── Pannello modifica ─────────────────────────────────────────────
        right = QScrollArea()
        right_inner = QWidget()
        self._right_layout = QVBoxLayout(right_inner)

        # Colori
        grp_colors = QGroupBox("Colori")
        self._color_form = QFormLayout(grp_colors)

        self._btn_fg = QPushButton("    ")
        self._btn_bg = QPushButton("    ")
        self._btn_fg.clicked.connect(lambda: self._pick_color("fg"))
        self._btn_bg.clicked.connect(lambda: self._pick_color("bg"))

        self._color_form.addRow("Testo (fg):", self._btn_fg)
        self._color_form.addRow("Sfondo (bg):", self._btn_bg)
        self._right_layout.addWidget(grp_colors)

        # Font (solo per token)
        self._grp_font = QGroupBox("Font")
        font_form = QFormLayout(self._grp_font)
        self._chk_bold   = QCheckBox("Grassetto")
        self._chk_italic = QCheckBox("Corsivo")
        self._chk_bold.stateChanged.connect(self._apply_font)
        self._chk_italic.stateChanged.connect(self._apply_font)
        font_form.addRow("", self._chk_bold)
        font_form.addRow("", self._chk_italic)
        self._right_layout.addWidget(self._grp_font)

        # Font globale
        grp_global = QGroupBox("Font editor globale")
        gf = QFormLayout(grp_global)
        self._font_combo = QFontComboBox()
        self._font_combo.setFontFilters(QFontComboBox.FontFilter.MonospacedFonts)
        self._font_size  = QSpinBox()
        self._font_size.setRange(6, 72)
        gf.addRow(tr("label.font"), self._font_combo)
        gf.addRow(tr("label.font_size"), self._font_size)
        btn_apply_font = QPushButton("Applica font")
        btn_apply_font.clicked.connect(self._apply_global_font)
        gf.addRow("", btn_apply_font)
        self._right_layout.addWidget(grp_global)

        self._right_layout.addStretch()
        right.setWidget(right_inner)
        right.setWidgetResizable(True)
        splitter.addWidget(right)
        splitter.setSizes([300, 450])

        layout.addWidget(splitter, 1)

        # ── Pulsanti ──────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_preview = QPushButton("Anteprima")
        btn_preview.clicked.connect(self._preview)
        btn_import  = QPushButton("Importa colori da...")
        btn_import.clicked.connect(self._import_colors)
        btn_row.addWidget(btn_preview)
        btn_row.addWidget(btn_import)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._current_section = ""
        self._current_key     = ""

    def _populate(self) -> None:
        """Carica i valori globali del font."""
        font_d = self._theme.get("font", {})
        if font_d.get("family"):
            self._font_combo.setCurrentFont(QFont(font_d["family"]))
        self._font_size.setValue(font_d.get("size", 11))

    def _on_item_changed(self, item: Optional[QListWidgetItem]) -> None:
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        section, key = data
        self._current_section = section
        self._current_key     = key

        is_token = (section == "tokens")
        self._grp_font.setVisible(is_token)

        if section == "ui":
            val = self._theme.get("ui", {}).get(key, "#000000")
            self._update_btn(self._btn_fg, val)
            self._btn_bg.setEnabled(False)
        else:
            tok = self._theme.get("tokens", {}).get(key, {})
            self._update_btn(self._btn_fg, tok.get("fg", "#d4d4d4"))
            self._update_btn(self._btn_bg, tok.get("bg"))
            self._btn_bg.setEnabled(True)
            self._chk_bold.setChecked(tok.get("bold", False))
            self._chk_italic.setChecked(tok.get("italic", False))

    def _update_btn(self, btn: QPushButton,
                    color_str: Optional[str]) -> None:
        if color_str:
            btn.setStyleSheet(
                f"background-color: {color_str}; color: {'#fff' if QColor(color_str).lightness() < 128 else '#000'};"
            )
            btn.setText(color_str)
            btn.setEnabled(True)
        else:
            btn.setStyleSheet("")
            btn.setText("(nessuno)")

    def _pick_color(self, component: str) -> None:
        current = ""
        if component == "fg":
            current = self._btn_fg.text() if self._btn_fg.text().startswith("#") else ""
        else:
            current = self._btn_bg.text() if self._btn_bg.text().startswith("#") else ""

        color = QColorDialog.getColor(
            QColor(current) if current else QColor("#ffffff"),
            self,
            "Scegli colore"
        )
        if not color.isValid():
            return

        hex_color = color.name()
        if self._current_section == "ui":
            self._theme.setdefault("ui", {})[self._current_key] = hex_color
            self._update_btn(self._btn_fg, hex_color)
        else:
            tok = self._theme.setdefault("tokens", {}).setdefault(
                self._current_key, {}
            )
            tok[component] = hex_color
            if component == "fg":
                self._update_btn(self._btn_fg, hex_color)
            else:
                self._update_btn(self._btn_bg, hex_color)

        # Aggiorna swatch nella lista
        self._refresh_swatch()

    def _apply_font(self) -> None:
        if self._current_section != "tokens":
            return
        tok = self._theme.setdefault("tokens", {}).setdefault(
            self._current_key, {}
        )
        if self._chk_bold.isChecked():
            tok["bold"] = True
        else:
            tok.pop("bold", None)
        if self._chk_italic.isChecked():
            tok["italic"] = True
        else:
            tok.pop("italic", None)

    def _apply_global_font(self) -> None:
        self._theme.setdefault("font", {})["family"] = \
            self._font_combo.currentFont().family()
        self._theme["font"]["size"] = self._font_size.value()

    def _refresh_swatch(self) -> None:
        """Aggiorna l'icona swatch dell'item corrente nella lista."""
        item = self._tabs_list.currentItem()
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        section, key = data
        if section == "ui":
            color = self._theme.get("ui", {}).get(key)
        else:
            color = self._theme.get("tokens", {}).get(key, {}).get("fg")
        item.setIcon(_color_swatch(color))

    def _preview(self) -> None:
        """Applica il tema corrente (non salvato) a tutti gli editor."""
        name = self._theme.get("meta", {}).get("name", "preview")
        self._tm._themes[name] = self._theme
        # _mw potrebbe essere PreferencesDialog: risale alla MainWindow reale
        mw = self._mw
        while mw is not None and not hasattr(mw, "_tab_manager"):
            mw = mw.parent()
        if mw is None:
            return
        for ed in mw._tab_manager.all_editors():
            self._tm.apply_to_editor(ed, name)

    def _import_colors(self) -> None:
        """Importa i colori da un tema esistente."""
        names = self._tm.available_themes()
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getItem(
            self, "Importa colori", "Da quale tema:",
            names, 0, False
        )
        if ok:
            source = self._tm.get_theme(name)
            if source:
                self._theme["ui"]     = copy.deepcopy(source.get("ui", {}))
                self._theme["tokens"] = copy.deepcopy(source.get("tokens", {}))
                # Refresh lista
                self._on_item_changed(self._tabs_list.currentItem())

    def _save(self) -> None:
        self._apply_global_font()
        if self._tm.save_user_theme(self._theme):
            name = self._theme.get("meta", {}).get("name", "")
            self._tm.set_active(name)
            self._preview()
            self.accept()

"""
ui/spell_check_dialog.py — Dialog avanzato Controllo Ortografico
NotePadPQ

Finestra di dialogo stile LibreOffice/Word per il controllo ortografico
interattivo: naviga gli errori uno alla volta, mostra suggerimenti, permette
di sostituire, ignorare o aggiungere al dizionario personale.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton,
    QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
    QGroupBox, QFrame, QComboBox,
)
from PyQt6.QtGui import QTextCursor, QTextCharFormat, QColor, QFont

from i18n.i18n import tr

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

# Regexp parole (stessa di editor_widget.py)
_RE_SPELL = re.compile(r"(?<![\\])\b[^\W\d_]+\b", re.UNICODE)


# Mappa lingua → etichetta
_LANG_LABELS: dict[str, str] = {
    "it": "Italiano",
    "en": "English",
    "de": "Deutsch",
    "fr": "Français",
    "es": "Español",
    "pl": "Polski",
}


class SpellCheckDialog(QDialog):
    """
    Dialog navigabile per il controllo ortografico.

    Funzionalità:
    - Naviga parola per parola tra gli errori nel documento
    - Mostra il contesto della parola errata evidenziata
    - Lista suggerimenti cliccabili
    - Azioni: Sostituisci, Sostituisci tutto, Ignora, Ignora tutto, Aggiungi
    - Cambio lingua dizionario al volo
    """

    def __init__(
        self,
        editor: "EditorWidget",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._editor = editor
        self._errors: list[tuple[int, int, str]] = []   # (start_pos, end_pos, word)
        self._current_idx: int = -1
        self._ignored: set[str] = set()
        self._replacements: dict[str, str] = {}          # Sostituisci tutto

        self.setWindowTitle(tr("dialog.spell_check_title"))
        self.setMinimumWidth(540)
        self.setMinimumHeight(500)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        self._build_ui()
        self._scan_errors()
        self._advance()

    # ── Costruzione UI ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # ── Riga lingua ───────────────────────────────────────────────────────
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel(tr("label.spell_language") + ":"))
        self._lang_combo = QComboBox()
        current_lang = getattr(self._editor, "_spell_lang", "it") or "it"
        for code, label in _LANG_LABELS.items():
            self._lang_combo.addItem(label, code)
        idx = list(_LANG_LABELS.keys()).index(current_lang) if current_lang in _LANG_LABELS else 0
        self._lang_combo.setCurrentIndex(idx)
        self._lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        lang_row.addWidget(self._lang_combo)
        lang_row.addStretch()
        root.addLayout(lang_row)

        # ── Parola non trovata ────────────────────────────────────────────────
        grp_word = QGroupBox(tr("label.spell_not_found"))
        grp_word_layout = QVBoxLayout(grp_word)
        self._word_label = QLabel("")
        font = self._word_label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        self._word_label.setFont(font)
        self._word_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        grp_word_layout.addWidget(self._word_label)
        root.addWidget(grp_word)

        # ── Contesto ─────────────────────────────────────────────────────────
        grp_ctx = QGroupBox(tr("label.spell_context"))
        grp_ctx_layout = QVBoxLayout(grp_ctx)
        self._context_edit = QTextEdit()
        self._context_edit.setReadOnly(True)
        self._context_edit.setMaximumHeight(70)
        self._context_edit.setFont(QFont("monospace"))
        grp_ctx_layout.addWidget(self._context_edit)
        root.addWidget(grp_ctx)

        # ── Sostituzione + suggerimenti ───────────────────────────────────────
        mid = QHBoxLayout()

        # Sinistra: campo sostituzione + lista suggerimenti
        left = QVBoxLayout()
        left.addWidget(QLabel(tr("label.spell_replace_with") + ":"))
        self._replace_edit = QTextEdit()
        self._replace_edit.setMaximumHeight(48)
        left.addWidget(self._replace_edit)
        left.addWidget(QLabel(tr("label.spell_suggestions") + ":"))
        self._sugg_list = QListWidget()
        self._sugg_list.itemClicked.connect(self._on_suggestion_clicked)
        self._sugg_list.itemDoubleClicked.connect(self._do_replace)
        left.addWidget(self._sugg_list)
        mid.addLayout(left, stretch=2)

        # Destra: bottoni azione
        btn_col = QVBoxLayout()
        btn_col.setSpacing(8)
        btn_col.setContentsMargins(4, 0, 0, 0)

        def _make_btn(label: str) -> QPushButton:
            b = QPushButton(label)
            b.setMinimumWidth(140)
            b.setMinimumHeight(30)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            return b

        self._btn_ignore = _make_btn(tr("button.spell_ignore"))
        self._btn_ignore.clicked.connect(self._do_ignore)
        btn_col.addWidget(self._btn_ignore)

        self._btn_ignore_all = _make_btn(tr("button.spell_ignore_all"))
        self._btn_ignore_all.clicked.connect(self._do_ignore_all)
        btn_col.addWidget(self._btn_ignore_all)

        btn_col.addWidget(_hline())

        self._btn_replace = _make_btn(tr("button.spell_replace"))
        self._btn_replace.setDefault(True)
        self._btn_replace.clicked.connect(self._do_replace)
        btn_col.addWidget(self._btn_replace)

        self._btn_replace_all = _make_btn(tr("button.spell_replace_all"))
        self._btn_replace_all.clicked.connect(self._do_replace_all)
        btn_col.addWidget(self._btn_replace_all)

        btn_col.addWidget(_hline())

        self._btn_add = _make_btn(tr("button.spell_add_dict"))
        self._btn_add.clicked.connect(self._do_add)
        btn_col.addWidget(self._btn_add)

        btn_col.addStretch()

        self._btn_close = _make_btn(tr("button.close"))
        self._btn_close.clicked.connect(self.accept)
        btn_col.addWidget(self._btn_close)

        mid.addLayout(btn_col, stretch=0)
        root.addLayout(mid)

        # ── Barra di stato ────────────────────────────────────────────────────
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: gray; font-style: italic;")
        root.addWidget(self._status_label)

    # ── Logica spell check ────────────────────────────────────────────────────

    def _get_checker(self):
        """Restituisce lo SpellChecker del documento (o None)."""
        return getattr(self._editor, "_spell_checker", None)

    def _scan_errors(self) -> None:
        """Rileva tutte le parole errate nel testo (posizioni assolute)."""
        checker = self._get_checker()
        if checker is None:
            self._errors = []
            return

        text = self._editor.text()
        positions: list[tuple[int, int, str]] = []
        seen: set[str] = set()
        word_list: list[str] = []

        for m in _RE_SPELL.finditer(text):
            word = m.group(0)
            if len(word) <= 2 or word.isupper():
                continue
            word_list.append(word)
            positions.append((m.start(), m.end(), word))
            seen.add(word)

        unknown = checker.unknown(word_list) if word_list else set()

        self._errors = [
            (s, e, w) for s, e, w in positions
            if w in unknown and w.lower() not in self._ignored
        ]
        self._current_idx = -1

    def _advance(self) -> None:
        """Avanza all'errore successivo. Mostra il messaggio di completamento se finiti."""
        self._current_idx += 1
        # Filtra gli ignorati (aggiornati in corsa)
        while self._current_idx < len(self._errors):
            _, _, w = self._errors[self._current_idx]
            if w.lower() not in self._ignored:
                break
            self._current_idx += 1

        if self._current_idx >= len(self._errors):
            self._show_complete()
            return

        _, _, word = self._errors[self._current_idx]
        self._show_error(word)

    def _show_error(self, word: str) -> None:
        """Mostra la parola errata corrente con contesto e suggerimenti."""
        start, end, w = self._errors[self._current_idx]
        checker = self._get_checker()

        self._word_label.setText(w)
        self._word_label.setStyleSheet("color: #cc0000;")

        # Contesto: 60 caratteri intorno alla parola
        text = self._editor.text()
        ctx_start = max(0, start - 40)
        ctx_end   = min(len(text), end + 40)
        context   = text[ctx_start:ctx_end].replace("\n", " ")

        self._context_edit.clear()
        cursor = self._context_edit.textCursor()

        # testo prima
        fmt_normal = QTextCharFormat()
        cursor.insertText(context[:start - ctx_start], fmt_normal)

        # parola evidenziata
        fmt_err = QTextCharFormat()
        fmt_err.setForeground(QColor("#cc0000"))
        fmt_err.setFontWeight(QFont.Weight.Bold)
        cursor.insertText(context[start - ctx_start:end - ctx_start], fmt_err)

        # testo dopo
        cursor.insertText(context[end - ctx_start:], fmt_normal)

        # Suggerimenti
        self._sugg_list.clear()
        if checker:
            candidates = checker.candidates(w) or set()
            suggestions = sorted(candidates - {w.lower()})[:10]
            for s in suggestions:
                self._sugg_list.addItem(QListWidgetItem(s))
            if suggestions:
                self._sugg_list.setCurrentRow(0)
                self._replace_edit.setPlainText(suggestions[0])
            else:
                self._replace_edit.setPlainText(w)
        else:
            self._replace_edit.setPlainText(w)

        remaining = len(self._errors) - self._current_idx
        self._status_label.setText(
            tr("label.spell_remaining", count=remaining)
        )

        self._btn_replace.setEnabled(True)
        self._btn_replace_all.setEnabled(True)
        self._btn_ignore.setEnabled(True)
        self._btn_ignore_all.setEnabled(True)
        self._btn_add.setEnabled(True)

    def _show_complete(self) -> None:
        """Mostra il messaggio di controllo completato."""
        self._word_label.setText(tr("label.spell_complete"))
        self._word_label.setStyleSheet("color: #007700;")
        self._context_edit.clear()
        self._sugg_list.clear()
        self._replace_edit.clear()
        self._status_label.setText("")
        self._btn_replace.setEnabled(False)
        self._btn_replace_all.setEnabled(False)
        self._btn_ignore.setEnabled(False)
        self._btn_ignore_all.setEnabled(False)
        self._btn_add.setEnabled(False)
        # Seleziona il bottone Chiudi come default
        self._btn_close.setDefault(True)
        self._btn_replace.setDefault(False)

    # ── Azioni bottoni ────────────────────────────────────────────────────────

    def _do_ignore(self) -> None:
        """Ignora questa occorrenza e passa alla successiva."""
        self._advance()

    def _do_ignore_all(self) -> None:
        """Ignora tutte le occorrenze di questa parola."""
        if self._current_idx < len(self._errors):
            _, _, word = self._errors[self._current_idx]
            self._ignored.add(word.lower())
            # Aggiungi anche al dizionario personale dell'editor per questa sessione
            self._editor._spell_add_to_personal(word)
        self._advance()

    def _do_replace(self, *_) -> None:
        """Sostituisce la parola corrente con il testo nel campo sostituzione."""
        if self._current_idx >= len(self._errors):
            return
        replacement = self._replace_edit.toPlainText().strip()
        if not replacement:
            return
        start, end, _ = self._errors[self._current_idx]
        # Calcola linea/colonna da posizione assoluta
        ls, cs, le, ce = self._abs_to_line_col(start, end)
        self._editor._spell_replace(ls, cs, le, ce, replacement)
        # Riesegui la scansione (il testo è cambiato)
        self._rescan_after_replace()
        self._advance()

    def _do_replace_all(self) -> None:
        """Sostituisce tutte le occorrenze della parola nel documento."""
        if self._current_idx >= len(self._errors):
            return
        replacement = self._replace_edit.toPlainText().strip()
        if not replacement:
            return
        _, _, word = self._errors[self._current_idx]
        # Itera le occorrenze dall'ultima alla prima (per non invalidare le posizioni)
        text = self._editor.text()
        matches = [(m.start(), m.end()) for m in _RE_SPELL.finditer(text) if m.group(0) == word]
        for start, end in reversed(matches):
            ls, cs, le, ce = self._abs_to_line_col(start, end)
            self._editor._spell_replace(ls, cs, le, ce, replacement)
        self._rescan_after_replace()
        self._advance()

    def _do_add(self) -> None:
        """Aggiunge la parola al dizionario personale dell'editor."""
        if self._current_idx >= len(self._errors):
            return
        _, _, word = self._errors[self._current_idx]
        self._editor._spell_add_to_personal(word)
        self._ignored.add(word.lower())
        self._advance()

    def _on_suggestion_clicked(self, item: QListWidgetItem) -> None:
        """Selezionando un suggerimento aggiorna il campo di sostituzione."""
        self._replace_edit.setPlainText(item.text())

    def _on_lang_changed(self, idx: int) -> None:
        """Cambia la lingua del dizionario al volo."""
        code = self._lang_combo.itemData(idx)
        if not code:
            return
        # Aggiorna l'editor
        if hasattr(self._editor, "set_spellcheck_enabled"):
            self._editor.set_spellcheck_enabled(True, code)
        # Aggiorna Settings globali
        try:
            from config.settings import Settings
            Settings.instance().set("spellcheck/language", code)
        except Exception:
            pass
        # Riscansiona
        self._scan_errors()
        self._current_idx = -1
        self._advance()

    # ── Utilità ───────────────────────────────────────────────────────────────

    def _abs_to_line_col(self, start: int, end: int) -> tuple[int, int, int, int]:
        """Converte posizioni assolute (caratteri) in (linea_s, col_s, linea_e, col_e)."""
        text = self._editor.text()
        lines = text[:start].split("\n")
        ls = len(lines) - 1
        cs = len(lines[-1])
        lines_e = text[:end].split("\n")
        le = len(lines_e) - 1
        ce = len(lines_e[-1])
        return ls, cs, le, ce

    def _rescan_after_replace(self) -> None:
        """Riscansiona il documento dopo una sostituzione."""
        self._scan_errors()
        self._current_idx -= 1   # _advance() farà +1

    def _get_current_replacement(self) -> str:
        return self._replace_edit.toPlainText().strip()


def _hline() -> QFrame:
    """Restituisce una linea orizzontale di separazione."""
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFrameShadow(QFrame.Shadow.Sunken)
    return f

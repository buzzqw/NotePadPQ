"""
ui/incremental_search.py — Barra di ricerca incrementale inline
NotePadPQ

Barra compatta che appare in fondo all'editor (sopra la statusbar)
quando l'utente preme Ctrl+F2 (o il tasto configurabile).
Cerca mentre si digita, senza aprire il dialog FindReplace.

Il dialog FindReplace esistente rimane intatto e accessibile con Ctrl+F.

Funzionalità:
  - Ricerca incrementale (search-as-you-type)
  - Evidenziazione dell'occorrenza corrente + tutte le altre
  - F3 / Shift+F3 per navigare avanti/indietro
  - Conta occorrenze in tempo reale ("3 di 17")
  - Match case / Regex toggle compatti
  - Escape per chiudere e riportare il focus all'editor
  - Colore campo rosso se nessun risultato trovato

Integrazione in MainWindow:
    # In _setup_dock_panels o _setup_central, dopo aver creato il layout:
    from ui.incremental_search import IncrementalSearchBar
    self._inc_search = IncrementalSearchBar(self)
    # La barra inserisce sé stessa nel layout della finestra principale
    IncrementalSearchBar.install(self)
"""

from __future__ import annotations

import re
from typing import Optional, List, TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QAction, QShortcut
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QCheckBox, QSizePolicy, QApplication,
)

if TYPE_CHECKING:
    from ui.main_window import MainWindow
    from editor.editor_widget import EditorWidget

# Indicatore QScintilla per la ricerca incrementale
_INC_INDICATOR     = 9    # occorrenze non correnti
_INC_CUR_INDICATOR = 10   # occorrenza corrente

_COLOR_MATCH   = QColor("#3a5a3a")   # sfondo verde scuro per tutte le occorrenze
_COLOR_CURRENT = QColor("#8a6000")   # sfondo arancione per occorrenza corrente
_COLOR_ERROR   = "#5a1a1a"           # sfondo campo testo quando nessun risultato


class IncrementalSearchBar(QWidget):
    """
    Barra di ricerca incrementale. Si inserisce come widget fisso
    tra l'area tab e la statusbar di MainWindow.
    Nasce nascosta e si mostra/nasconde con toggle().
    """

    closed = pyqtSignal()

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._mw = main_window
        self._matches: List[tuple] = []   # [(line_from, col_from, line_to, col_to)]
        self._current_idx = -1
        self._last_text   = ""

        self._build_ui()
        self.hide()

        # Timer per search-as-you-type (delay 120ms)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)
        self._search_timer.timeout.connect(self._do_search)

        # Aggiorna quando cambia editor
        main_window._tab_manager.current_editor_changed.connect(
            self._on_editor_changed
        )

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setFixedHeight(34)
        self.setStyleSheet(
            "QWidget { background: #2a2a2a; border-top: 1px solid #444; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)

        # Label
        lbl = QLabel("🔍")
        lbl.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(lbl)

        # Campo testo
        self._field = QLineEdit()
        self._field.setPlaceholderText("Ricerca incrementale…  (F3 succ.  Shift+F3 prec.  Esc chiudi)")
        self._field.setFixedHeight(24)
        self._field.setMinimumWidth(220)
        self._field.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._field.textChanged.connect(self._on_text_changed)
        self._field.returnPressed.connect(self._find_next)
        layout.addWidget(self._field)

        # Contatore occorrenze
        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet(
            "background: transparent; border: none; color: #888; font-size: 11px;"
        )
        self._count_lbl.setMinimumWidth(70)
        layout.addWidget(self._count_lbl)

        # Opzioni compatte
        self._cb_case  = QCheckBox("Aa")
        self._cb_case.setToolTip("Distingui maiuscole/minuscole")
        self._cb_case.setStyleSheet("background: transparent; border: none; color: #ccc;")
        self._cb_case.stateChanged.connect(self._on_text_changed)
        layout.addWidget(self._cb_case)

        self._cb_regex = QCheckBox(".*")
        self._cb_regex.setToolTip("Espressione regolare")
        self._cb_regex.setStyleSheet("background: transparent; border: none; color: #ccc;")
        self._cb_regex.stateChanged.connect(self._on_text_changed)
        layout.addWidget(self._cb_regex)

        self._cb_word  = QCheckBox("\\b")
        self._cb_word.setToolTip("Parola intera")
        self._cb_word.setStyleSheet("background: transparent; border: none; color: #ccc;")
        self._cb_word.stateChanged.connect(self._on_text_changed)
        layout.addWidget(self._cb_word)

        layout.addSpacing(8)

        # Pulsanti nav
        for label, tip, slot in [
            ("▲", "Precedente (Shift+F3)", self._find_prev),
            ("▼", "Successivo (F3)",       self._find_next),
        ]:
            btn = QPushButton(label)
            btn.setFixedSize(26, 24)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                "QPushButton{background:#3a3a3a;border:1px solid #555;"
                "color:#ccc;border-radius:3px;}"
                "QPushButton:hover{background:#4a4a4a;}"
            )
            btn.clicked.connect(slot)
            layout.addWidget(btn)

        # Chiudi
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(26, 24)
        btn_close.setToolTip("Chiudi (Esc)")
        btn_close.setStyleSheet(
            "QPushButton{background:#3a3a3a;border:1px solid #555;"
            "color:#888;border-radius:3px;}"
            "QPushButton:hover{background:#c0392b;color:#fff;}"
        )
        btn_close.clicked.connect(self.hide_bar)
        layout.addWidget(btn_close)

        # Shortcut
        QShortcut(QKeySequence("Escape"), self, self.hide_bar)
        QShortcut(QKeySequence("F3"),     self, self._find_next)
        QShortcut(QKeySequence("Shift+F3"), self, self._find_prev)

    # ── Toggle / Mostra / Nascondi ────────────────────────────────────────────

    def toggle(self) -> None:
        if self.isVisible():
            self.hide_bar()
        else:
            self.show_bar()

    def show_bar(self, prefill: str = "") -> None:
        """Mostra la barra, pre-riempie con testo selezionato o prefill."""
        if not self.isVisible():
            self.show()

        editor = self._current_editor()
        if editor and editor.hasSelectedText():
            sel = editor.selectedText()
            if "\n" not in sel:
                self._field.setText(sel)
        elif prefill:
            self._field.setText(prefill)

        self._field.setFocus()
        self._field.selectAll()
        self._do_search()

    def hide_bar(self) -> None:
        """Nasconde la barra e riporta il focus all'editor."""
        self._clear_highlights()
        self.hide()
        self.closed.emit()
        ed = self._current_editor()
        if ed:
            ed.setFocus()

    # ── Ricerca ───────────────────────────────────────────────────────────────

    def _on_text_changed(self) -> None:
        self._search_timer.start()

    def _do_search(self) -> None:
        """Esegue la ricerca e aggiorna tutti gli highlight."""
        editor = self._current_editor()
        if not editor:
            return

        text   = self._field.text()
        self._last_text = text
        self._clear_highlights()
        self._matches = []
        self._current_idx = -1

        if not text:
            self._count_lbl.setText("")
            self._set_field_color(None)
            return

        # Costruisce il pattern
        try:
            pattern = self._build_pattern(text)
        except re.error:
            self._set_field_color(_COLOR_ERROR)
            self._count_lbl.setText("regex ✗")
            return

        # Cerca tutte le occorrenze
        doc_text = editor.text()
        try:
            self._matches = []
            for m in re.finditer(pattern, doc_text):
                ls, cs = editor.lineIndexFromPosition(m.start())
                le, ce = editor.lineIndexFromPosition(m.end())
                self._matches.append((ls, cs, le, ce))
        except Exception:
            self._matches = []

        total = len(self._matches)

        if total == 0:
            self._set_field_color(_COLOR_ERROR)
            self._count_lbl.setText("nessuno")
            return

        self._set_field_color(None)

        # Evidenzia tutte le occorrenze
        self._setup_indicators(editor)
        for ls, cs, le, ce in self._matches:
            editor.fillIndicatorRange(ls, cs, le, ce, _INC_INDICATOR)

        # Vai all'occorrenza più vicina al cursore corrente
        cur_line, cur_col = editor.getCursorPosition()
        cur_pos = editor.positionFromLineIndex(cur_line, cur_col)
        doc_text_to_cursor = doc_text[:cur_pos]
        nearest = 0
        for i, m in enumerate(re.finditer(pattern, doc_text)):
            if m.start() >= cur_pos:
                break
            nearest = i
        self._goto(nearest)

        self._count_lbl.setText(f"{self._current_idx + 1} / {total}")

    def _build_pattern(self, text: str) -> str:
        """Costruisce il pattern regex dalle opzioni selezionate."""
        if not self._cb_regex.isChecked():
            text = re.escape(text)
        if self._cb_word.isChecked():
            text = r"\b" + text + r"\b"
        flags = 0 if self._cb_case.isChecked() else re.IGNORECASE
        # Valida che sia una regex valida
        re.compile(text, flags)
        return text

    def _find_next(self) -> None:
        if not self._matches:
            self._do_search()
            return
        self._goto((self._current_idx + 1) % len(self._matches))

    def _find_prev(self) -> None:
        if not self._matches:
            return
        self._goto((self._current_idx - 1) % len(self._matches))

    def _goto(self, idx: int) -> None:
        """Vai all'occorrenza idx e aggiorna l'highlight corrente."""
        editor = self._current_editor()
        if not editor or not self._matches:
            return

        total = len(self._matches)
        idx   = idx % total
        self._current_idx = idx

        ls, cs, le, ce = self._matches[idx]

        # Rimuove highlight corrente precedente
        editor.clearIndicatorRange(
            0, 0,
            editor.lines() - 1,
            len(editor.text(editor.lines() - 1)),
            _INC_CUR_INDICATOR
        )

        # Segna occorrenza corrente
        editor.fillIndicatorRange(ls, cs, le, ce, _INC_CUR_INDICATOR)

        # Naviga
        editor.setSelection(ls, cs, le, ce)
        editor.ensureLineVisible(ls)

        self._count_lbl.setText(f"{idx + 1} / {total}")

    # ── Highlight ─────────────────────────────────────────────────────────────

    def _setup_indicators(self, editor: "EditorWidget") -> None:
        editor.indicatorDefine(
            editor.IndicatorStyle.RoundBoxIndicator, _INC_INDICATOR
        )
        editor.setIndicatorForegroundColor(_COLOR_MATCH, _INC_INDICATOR)
        editor.setIndicatorDrawUnder(True, _INC_INDICATOR)

        editor.indicatorDefine(
            editor.IndicatorStyle.FullBoxIndicator, _INC_CUR_INDICATOR
        )
        editor.setIndicatorForegroundColor(_COLOR_CURRENT, _INC_CUR_INDICATOR)
        editor.setIndicatorDrawUnder(True, _INC_CUR_INDICATOR)

    def _clear_highlights(self) -> None:
        editor = self._current_editor()
        if not editor:
            return
        last_line = editor.lines() - 1
        last_col  = len(editor.text(last_line))
        for ind in (_INC_INDICATOR, _INC_CUR_INDICATOR):
            editor.clearIndicatorRange(0, 0, last_line, last_col, ind)

    # ── Utility ───────────────────────────────────────────────────────────────

    def _set_field_color(self, bg: Optional[str]) -> None:
        if bg:
            self._field.setStyleSheet(f"background: {bg}; color: #ffaaaa;")
        else:
            self._field.setStyleSheet("")

    def _current_editor(self) -> Optional["EditorWidget"]:
        return self._mw._tab_manager.current_editor()

    def _on_editor_changed(self, editor) -> None:
        self._matches = []
        self._current_idx = -1
        if self.isVisible():
            self._do_search()

    # ── Installazione in MainWindow ───────────────────────────────────────────

    @staticmethod
    def install(main_window: "MainWindow") -> "IncrementalSearchBar":
        """
        Crea la barra e la inserisce nel layout della MainWindow
        tra il widget centrale e la statusbar.

        Aggiunge anche la voce di menu e la shortcut Ctrl+F2.
        """
        bar = IncrementalSearchBar(main_window)

        # Inserisce la barra sopra la statusbar
        # La MainWindow usa un layout implicito — usiamo insertWidget sul
        # layout del centralWidget container, oppure il metodo Qt nativo.
        # Il modo più robusto è aggiungere la barra come widget permanente
        # SOTTO il central widget tramite un QWidget wrapper.
        try:
            # Crea un container che impila: central_widget + inc_search_bar
            from PyQt6.QtWidgets import QWidget, QVBoxLayout
            old_central = main_window.centralWidget()
            container   = QWidget(main_window)
            vl = QVBoxLayout(container)
            vl.setContentsMargins(0, 0, 0, 0)
            vl.setSpacing(0)
            vl.addWidget(old_central, 1)
            vl.addWidget(bar)
            main_window.setCentralWidget(container)
        except Exception as e:
            print(f"[IncrementalSearchBar] install error: {e}")

        # Menu Cerca → voce Ricerca incrementale
        search_menu = main_window._menus.get("search")
        if search_menu:
            act = QAction("🔍 Ricerca incrementale", main_window)
            act.setShortcut(QKeySequence("Ctrl+F2"))
            act.setCheckable(True)
            act.triggered.connect(lambda checked: bar.show_bar() if checked else bar.hide_bar())
            bar.closed.connect(lambda: act.setChecked(False))
            search_menu.insertAction(search_menu.actions()[0], act)
            search_menu.insertSeparator(search_menu.actions()[1])

        return bar

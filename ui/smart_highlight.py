"""
ui/smart_highlight.py — Smart Highlight e Mark con colori multipli
NotePadPQ

Due funzionalità distinte ma nello stesso modulo:

1. SmartHighlighter
   Evidenzia automaticamente tutte le occorrenze della parola
   sotto il cursore (stile Notepad++ "Smart Highlight").
   Si aggiorna con un delay di 300ms dopo ogni spostamento cursore.
   Usa l'indicatore QScintilla INDIC_ROUNDBOX con colore configurabile.

2. MultiMarkManager
   Gestisce 5 colori di mark indipendenti (Ctrl+1..5).
   Ogni colore ha il proprio indicatore e può essere attivato/rimosso
   singolarmente. "Segna tutto" su testo selezionato o parola corrente.
   Ctrl+0 rimuove tutti i mark.

Uso da MainWindow:
    from ui.smart_highlight import SmartHighlighter, MultiMarkManager

    # In _setup_connections:
    self._smart_hl = SmartHighlighter(self)
    self._mark_mgr = MultiMarkManager(self)

    # Collegare ai menu (già fatto da _install_into_main_window):
    MultiMarkManager.install_into_main_window(self)
"""

from __future__ import annotations

import re
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QIcon, QKeySequence, QAction, QPixmap
from PyQt6.QtWidgets import QApplication

if TYPE_CHECKING:
    from ui.main_window import MainWindow
    from editor.editor_widget import EditorWidget

# ─── Indicatori QScintilla riservati ─────────────────────────────────────────
# editor_widget.py usa:
#   0   → INDICATOR_FIND
#   1-4 → INDICATOR_MARK1..4
#   5   → INDICATOR_SMART_HL interno
#
# smart_highlight.py usa range separato per non collidere:
#  13   → SmartHighlight (parola sotto cursore)
#  14-18→ MultiMark 5 colori

_SMART_HL_INDICATOR_NUM = 13 # Must be an integer representing the indicator ID
_MARK_INDICATOR_BASE = 14   # 14, 15, 16, 17, 18

# Colori dei 5 mark (sfondo, stile INDIC_STRAIGHTBOX)
_MARK_COLORS = [
    QColor("#ff6347"),   # 1 → Tomato Red
    QColor("#3cb371"),   # 2 → Medium Sea Green
    QColor("#1e90ff"),   # 3 → Dodger Blue
    QColor("#ffa500"),   # 4 → Orange
    QColor("#da70d6"),   # 5 → Orchid
]

# We define the color separately from the indicator ID.
# Using a lighter, semi-transparent color for readability.
_SMART_HL_COLOR = QColor(150, 150, 0, 100) # R, G, B, Alpha (0-255)


# ─── SmartHighlighter ────────────────────────────────────────────────────────

class SmartHighlighter:
    """
    Evidenzia automaticamente tutte le occorrenze della parola sotto il cursore.
    Si attiva 300ms dopo l'ultimo spostamento cursore per non appesantire
    la digitazione. Viene disattivato se il cursore si sposta fuori dalla parola.
    """

    DELAY_MS  = 300
    MIN_LEN   = 2       # lunghezza minima parola per attivare l'highlight

    def __init__(self, main_window: "MainWindow"):
        self._mw       = main_window
        self._timer    = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.DELAY_MS)
        self._timer.timeout.connect(self._do_highlight)
        self._last_word = ""
        self._active_editor: Optional["EditorWidget"] = None

        # Collega al cambio editor
        main_window._tab_manager.current_editor_changed.connect(
            self._on_editor_changed
        )
        # Collega all'editor già aperto
        ed = main_window._tab_manager.current_editor()
        if ed:
            self._on_editor_changed(ed)

    def _on_editor_changed(self, editor: Optional["EditorWidget"]) -> None:
        if self._active_editor:
            try:
                self._active_editor.cursor_changed.disconnect(self._on_cursor_moved)
            except Exception:
                pass
        self._active_editor = editor
        self._last_word = ""  # nuovo editor = nessun highlight pregresso
        if editor:
            editor.cursor_changed.connect(self._on_cursor_moved)
            self._setup_indicator(editor)

    def _setup_indicator(self, editor: "EditorWidget") -> None:
        # Use StraightBoxIndicator (or BoxIndicator) for a less intrusive highlight
        # and pass the integer ID, not the color object.
        editor.indicatorDefine(
            editor.IndicatorStyle.StraightBoxIndicator, _SMART_HL_INDICATOR_NUM
        )
        editor.setIndicatorForegroundColor(_SMART_HL_COLOR, _SMART_HL_INDICATOR_NUM)
        editor.setIndicatorDrawUnder(True, _SMART_HL_INDICATOR_NUM)

    def _on_cursor_moved(self, line: int, col: int) -> None:
        self._timer.start()

    def _do_highlight(self) -> None:
        editor = self._active_editor
        if not editor:
            return

        word = self._word_at_cursor(editor)

        if not word or len(word) < self.MIN_LEN:
            if self._last_word:
                editor.clearIndicatorRange(
                    0, 0,
                    editor.lines() - 1, len(editor.text(editor.lines() - 1)),
                    _SMART_HL_INDICATOR_NUM
                )
                self._last_word = ""
            return

        if word == self._last_word:
            return

        self._last_word = word
        editor.clearIndicatorRange(
            0, 0,
            editor.lines() - 1, len(editor.text(editor.lines() - 1)),
            _SMART_HL_INDICATOR_NUM
        )
        self._highlight_all(editor, word)

    def _word_at_cursor(self, editor: "EditorWidget") -> str:
        r"""Restituisce la parola sotto il cursore (solo caratteri \w)."""
        line, col = editor.getCursorPosition()
        text = editor.text(line)
        if not text:
            return ""
        # Espandi a sinistra
        start = col
        while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
            start -= 1
        # Espandi a destra
        end = col
        while end < len(text) and (text[end].isalnum() or text[end] == "_"):
            end += 1
        return text[start:end]

    def _highlight_all(self, editor: "EditorWidget", word: str) -> None:
        """Evidenzia tutte le occorrenze. Una sola chiamata API per ottenere il testo."""
        pattern = r"\b" + re.escape(word) + r"\b"
        try:
            full_text = editor.text()
            for line_num, text in enumerate(full_text.split('\n')):
                for m in re.finditer(pattern, text):
                    # Calcola i byte esatti per QScintilla (evita sfasamenti con accenti)
                    byte_start = len(text[:m.start()].encode('utf-8'))
                    byte_end   = len(text[:m.end()].encode('utf-8'))
                    editor.fillIndicatorRange(
                        line_num, byte_start,
                        line_num, byte_end,
                        _SMART_HL_INDICATOR_NUM
                    )
        except Exception:
            pass

    def clear(self) -> None:
        """Rimuove tutti gli highlight smart."""
        if self._active_editor:
            ed = self._active_editor
            ed.clearIndicatorRange(
                0, 0,
                ed.lines() - 1, len(ed.text(ed.lines() - 1)),
                _SMART_HL_INDICATOR_NUM
            )


# ─── MultiMarkManager ────────────────────────────────────────────────────────

class MultiMarkManager:
    """
    Gestisce 5 colori di mark indipendenti stile Notepad++.
    Ctrl+1..5 → marca con il colore corrispondente
    Ctrl+0    → rimuove tutti i mark
    Ogni mark può essere applicato a: testo selezionato, parola sotto cursore.
    """

    def __init__(self, main_window: "MainWindow"):
        self._mw = main_window
        self._active_editor: Optional["EditorWidget"] = None

        main_window._tab_manager.current_editor_changed.connect(
            self._on_editor_changed
        )
        ed = main_window._tab_manager.current_editor()
        if ed:
            self._on_editor_changed(ed)

    def _on_editor_changed(self, editor: Optional["EditorWidget"]) -> None:
        self._active_editor = editor
        if editor:
            self._setup_indicators(editor)

    def _setup_indicators(self, editor: "EditorWidget") -> None:
        """Configura i 5 indicatori colore (indici 14-18, fuori dai range di editor_widget)."""
        for i, color in enumerate(_MARK_COLORS):
            idx = _MARK_INDICATOR_BASE + i
            # StraightBoxIndicator + DrawUnder=True: bordo colorato SOTTO il testo
            # Il testo rimane completamente leggibile
            editor.indicatorDefine(
                editor.IndicatorStyle.StraightBoxIndicator, idx
            )
            editor.setIndicatorForegroundColor(color, idx)
            editor.setIndicatorDrawUnder(True, idx)

    def mark(self, color_index: int) -> None:
        """
        Applica/rimuove il mark con il colore dato (0-based) sul testo
        selezionato o sulla parola corrente.
        """
        editor = self._active_editor
        if not editor or not (0 <= color_index <= 4):
            return

        real_idx = _MARK_INDICATOR_BASE + color_index
        if editor.hasSelectedText():
            sel = editor.getSelection()   # (line_from, col_from, line_to, col_to)
            self._toggle_mark(editor, real_idx, *sel)
        else:
            word, line_s, col_s, line_e, col_e = self._word_range(editor)
            if word:
                self._mark_all_occurrences(editor, real_idx, word)

    def _toggle_mark(self, editor: "EditorWidget", color_idx: int,
                     line_from: int, col_from: int,
                     line_to: int, col_to: int) -> None:
        """Attiva o disattiva il mark nel range dato."""
        # Controlla se l'indicatore è già presente nel range
        pos_start = editor.positionFromLineIndex(line_from, col_from)
        already   = editor.indicatorValueAt(color_idx, pos_start)
        if already:
            editor.clearIndicatorRange(line_from, col_from, line_to, col_to, color_idx)
        else:
            editor.fillIndicatorRange(line_from, col_from, line_to, col_to, color_idx)

    def _mark_all_occurrences(self, editor: "EditorWidget",
                              color_idx: int, word: str) -> None:
        """Marca tutte le occorrenze di word con il colore dato calcolando i byte esatti."""
        pattern = r"\b" + re.escape(word) + r"\b"
        count = 0
        try:
            for line in range(editor.lines()):
                text = editor.text(line)
                for m in re.finditer(pattern, text):
                    # Calcola i byte esatti per QScintilla (evita sfasamenti con accenti)
                    byte_start = len(text[:m.start()].encode('utf-8'))
                    byte_end   = len(text[:m.end()].encode('utf-8'))
                    editor.fillIndicatorRange(line, byte_start, line, byte_end, color_idx)
                    count += 1
        except Exception:
            pass
        color_num = color_idx - _MARK_INDICATOR_BASE + 1
        self._mw.statusBar().showMessage(
            f"🎨 Colore {color_num}: {count} occorrenze evidenziate", 3000
        )

    def clear_color(self, color_index: int) -> None:
        """Rimuove tutti i mark del colore dato (0-based)."""
        editor = self._active_editor
        if editor and 0 <= color_index <= 4:
            real_idx = _MARK_INDICATOR_BASE + color_index
            editor.clearIndicatorRange(
                0, 0,
                editor.lines() - 1,
                len(editor.text(editor.lines() - 1)),
                real_idx
            )

    def clear_all(self) -> None:
        """Rimuove tutti i mark di tutti i colori."""
        for i in range(5):
            self.clear_color(i)
        self._mw.statusBar().showMessage("🎨 Tutti i mark rimossi", 2000)

    def _word_range(self, editor: "EditorWidget"):
        """Restituisce (word, line_s, col_s, line_e, col_e) della parola al cursore."""
        line, col = editor.getCursorPosition()
        text = editor.text(line)
        if not text:
            return "", 0, 0, 0, 0
        start = col
        while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
            start -= 1
        end = col
        while end < len(text) and (text[end].isalnum() or text[end] == "_"):
            end += 1
        return text[start:end], line, start, line, end

    # ── Installazione shortcut in MainWindow ──────────────────────────────────

    @staticmethod
    def install_into_main_window(main_window: "MainWindow") -> "MultiMarkManager":
        """
        Crea il MultiMarkManager e installa le shortcut Ctrl+0..5
        nel menu Cerca di MainWindow.
        Chiamare da MainWindow._setup_connections() o simile.
        """
        mgr = MultiMarkManager(main_window)

        search_menu = main_window._menus.get("search")
        if search_menu:
            search_menu.addSeparator()

            color_names = ["Rosso", "Verde", "Blu", "Arancione", "Viola"]
            for i in range(1, 6):
                color = _MARK_COLORS[i - 1]
                pm = QPixmap(12, 12)
                pm.fill(color)
                icon = QIcon(pm)
                act = QAction(icon, f"Evidenzia in {color_names[i - 1]}  (Ctrl+{i})", main_window)
                act.setShortcut(QKeySequence(f"Ctrl+{i}"))
                act.triggered.connect(lambda checked, idx=i - 1: mgr.mark(idx))
                search_menu.addAction(act)

            act_clear = QAction("🎨 Rimuovi tutti i mark", main_window)
            act_clear.setShortcut(QKeySequence("Ctrl+0"))
            act_clear.triggered.connect(mgr.clear_all)
            search_menu.addAction(act_clear)

        return mgr
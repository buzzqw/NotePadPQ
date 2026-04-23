"""
editor/editor_widget.py — Wrapper QScintilla core
NotePadPQ

Widget editor principale basato su QScintilla. Gestisce:
- Configurazione base Scintilla (margini, font, colori, comportamento)
- Segnali verso il resto dell'applicazione
- Stato del documento (modificato, encoding, line ending, lexer attivo)
- Operazioni di testo di basso livello

NON gestisce: I/O file (→ core/file_manager.py),
              syntax highlighting avanzato (→ editor/lexers.py),
              folding (→ editor/folding.py),
              autocompletamento (→ editor/autocomplete.py)

Uso:
    from editor.editor_widget import EditorWidget
    editor = EditorWidget()
    editor.load_content("testo", encoding="utf-8", line_ending="LF")
"""

import sys
from enum import Enum
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont, QKeySequence
from PyQt6.QtWidgets import QWidget, QApplication

from PyQt6.Qsci import (
    QsciScintilla,
    QsciLexerPython,   # usato solo nel test standalone
)

from core.platform import get_preferred_monospace_font, IS_WINDOWS
from i18n.i18n import tr

# ─── Costanti ─────────────────────────────────────────────────────────────────

class LineEnding(Enum):
    LF   = "\n"       # Unix / Linux / FreeBSD
    CRLF = "\r\n"     # Windows
    CR   = "\r"       # vecchio Mac (raro)

    @classmethod
    def detect(cls, text: str) -> "LineEnding":
        if "\r\n" in text:
            return cls.CRLF
        if "\r" in text:
            return cls.CR
        return cls.LF

    def label(self) -> str:
        return {
            LineEnding.LF:   "LF",
            LineEnding.CRLF: "CRLF",
            LineEnding.CR:   "CR",
        }[self]

    def to_qsci(self) -> QsciScintilla.EolMode:
        return {
            LineEnding.LF:   QsciScintilla.EolMode.EolUnix,
            LineEnding.CRLF: QsciScintilla.EolMode.EolWindows,
            LineEnding.CR:   QsciScintilla.EolMode.EolMac,
        }[self]


# Margini Scintilla
MARGIN_LINE_NUMBERS = 0
MARGIN_FOLD         = 1
MARGIN_SYMBOLS      = 2

# Marker Scintilla per bookmark (sul margine simboli)
MARKER_BOOKMARK = 0   # indice marker — visualizzato come cerchio blu

# Indicatori di evidenziazione (Find/Replace usa 0-7)
INDICATOR_FIND      = 0
INDICATOR_MARK1     = 1
INDICATOR_MARK2     = 2
INDICATOR_MARK3     = 3
INDICATOR_MARK4     = 4
INDICATOR_SMART_HL  = 5   # Smart Highlight: parola sotto cursore
INDICATOR_SPELL     = 6   # Sottolineatura a zig-zag rossa per errori ortografici

# ─── EditorWidget ─────────────────────────────────────────────────────────────

class EditorWidget(QsciScintilla):
    """
    Widget editor principale. Emette segnali per aggiornare
    statusbar, tab title, e altri moduli.
    """

    # ── Segnali ──────────────────────────────────────────────────────────────
    modified_changed   = pyqtSignal(bool)        # documento modificato/salvato
    cursor_changed     = pyqtSignal(int, int)    # riga, colonna (1-based)
    encoding_changed   = pyqtSignal(str)         # es. "UTF-8"
    line_ending_changed = pyqtSignal(str)        # "LF" / "CRLF" / "CR"
    selection_changed_info = pyqtSignal(int, int) # chars selezionati, righe
    zoom_changed       = pyqtSignal(int)         # livello zoom corrente
    overwrite_changed  = pyqtSignal(bool)        # modalità inserimento/sovrascrittura
    language_changed   = pyqtSignal(str)         # es. "Python", "LaTeX"

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # Stato documento
        self._encoding: str    = "UTF-8"
        self._line_ending: LineEnding = LineEnding.LF
        self._file_path: Optional[Path] = None
        self._read_only_forced: bool = False
        self._zoom_level: int  = 0
        self._overwrite: bool  = False
        self._smart_highlight_enabled: bool = True
        self._smart_hl_timer: QTimer = QTimer(self)
        self._smart_hl_timer.setSingleShot(True)
        self._smart_hl_timer.setInterval(400)
        self._smart_hl_timer.timeout.connect(self._do_smart_highlight)

        # --- INIZIO TIMER SPELL CHECKER ---
        self._spell_checker = None
        self._spell_timer = QTimer(self)
        self._spell_timer.setSingleShot(True)
        self._spell_timer.setInterval(1000) # Aspetta 1 secondo di inattività prima di controllare
        self._spell_timer.timeout.connect(self._do_spell_check)
        self.textChanged.connect(self._spell_timer.start) # Si riavvia a ogni tasto premuto
        # --- FINE TIMER SPELL CHECKER ---
        

        self._setup_base()
        self._setup_margins()
        self._setup_indicators()
        self._setup_caret()
        self._setup_selection()
        self._setup_connections()

        # Font default da piattaforma
        self.set_font_family(get_preferred_monospace_font(), 11)

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _setup_base(self) -> None:
        """Configurazione base comportamento editor."""
        # Indentazione
        self.setIndentationsUseTabs(False)
        self.setTabWidth(4)
        self.setAutoIndent(True)
        self.setBackspaceUnindents(True)
        self.setTabIndents(True)
        self.setIndentationGuides(True)

        # Wrap
        self.setWrapMode(QsciScintilla.WrapMode.WrapNone)
        self.setWrapVisualFlags(
            QsciScintilla.WrapVisualFlag.WrapFlagByText,
            QsciScintilla.WrapVisualFlag.WrapFlagNone
        )

        # EOL
        self.setEolMode(LineEnding.LF.to_qsci())
        self.setEolVisibility(False)

        # Whitespace
        self.setWhitespaceVisibility(
            QsciScintilla.WhitespaceVisibility.WsInvisible
        )
        self.setWhitespaceSize(1)

        # Encoding interno Scintilla — sempre UTF-8, la conversione
        # a/da encoding del file è gestita da file_manager.py
        self.setUtf8(True)

        # Selezione rettangolare con Alt+Drag
        self.SendScintilla(
            QsciScintilla.SCI_SETMOUSESELECTIONRECTANGULARSWITCH, True
        )

        # Brace matching
        self.setBraceMatching(QsciScintilla.BraceMatch.SloppyBraceMatch)

        # Scroll beyond last line
        self.SendScintilla(QsciScintilla.SCI_SETENDATLASTLINE, False)

        # Autocompletamento (configurato da autocomplete.py)
        self.setAutoCompletionThreshold(2)
        self.setAutoCompletionCaseSensitivity(False)
        self.setAutoCompletionReplaceWord(False)
        self.setAutoCompletionUseSingle(
            QsciScintilla.AutoCompletionUseSingle.AcusNever
        )

    def _setup_margins(self) -> None:
        """Configura i margini: numeri di riga, fold, simboli."""
        # Margine numeri di riga
        self.setMarginType(MARGIN_LINE_NUMBERS,
                           QsciScintilla.MarginType.NumberMargin)
        self.setMarginWidth(MARGIN_LINE_NUMBERS, "00000")
        self.setMarginsForegroundColor(QColor("#858585"))
        self.setMarginsBackgroundColor(QColor("#1e1e1e"))

        # Margine fold (configurato da folding.py)
        self.setMarginType(MARGIN_FOLD,
                           QsciScintilla.MarginType.SymbolMarginDefaultForegroundColor)
        self.setMarginWidth(MARGIN_FOLD, 14)
        self.setMarginSensitivity(MARGIN_FOLD, True)
        self.setFolding(QsciScintilla.FoldStyle.PlainFoldStyle, MARGIN_FOLD)

        # Margine simboli (bookmark, errori build)
        self.setMarginType(MARGIN_SYMBOLS,
                           QsciScintilla.MarginType.SymbolMargin)
        self.setMarginWidth(MARGIN_SYMBOLS, 14)
        self.setMarginSensitivity(MARGIN_SYMBOLS, True)

        # Definisci marker bookmark: cerchio pieno blu
        self.markerDefine(QsciScintilla.MarkerSymbol.Circle, MARKER_BOOKMARK)
        self.setMarkerBackgroundColor(QColor("#4ec9b0"), MARKER_BOOKMARK)
        self.setMarkerForegroundColor(QColor("#1e1e1e"), MARKER_BOOKMARK)
        # Click sul margine simboli → toggle bookmark
        self.marginClicked.connect(self._on_margin_clicked)

    def _setup_indicators(self) -> None:
        """Configura gli indicatori per Find/Replace e Mark."""
        # REGOLA: DrawUnder=True su TUTTI gli indicatori — il testo rimane sempre leggibile.
        # DrawUnder=False (default) disegna sopra il testo coprendolo.

        # Indicatore find (arancione, box tratteggiato sotto il testo)
        self.indicatorDefine(
            QsciScintilla.IndicatorStyle.RoundBoxIndicator, INDICATOR_FIND
        )
        self.setIndicatorForegroundColor(QColor(255, 165, 0, 200), INDICATOR_FIND)
        self.setIndicatorDrawUnder(True, INDICATOR_FIND)

        # Indicatori Mark 1-4: StraightBox colorato SOTTO il testo
        mark_colors = [
            QColor(255, 220, 0, 180),   # giallo
            QColor(0, 200, 100, 180),   # verde
            QColor(100, 150, 255, 180), # blu
            QColor(255, 100, 100, 180), # rosso
        ]
        for i, color in enumerate(mark_colors):
            idx = INDICATOR_MARK1 + i
            self.indicatorDefine(
                QsciScintilla.IndicatorStyle.StraightBoxIndicator, idx
            )
            self.setIndicatorForegroundColor(color, idx)
            self.setIndicatorDrawUnder(True, idx)

        # Indicatore Smart Highlight: box arrotondato tenue sotto il testo
        self.indicatorDefine(
            QsciScintilla.IndicatorStyle.RoundBoxIndicator, INDICATOR_SMART_HL
        )
        self.setIndicatorForegroundColor(QColor(100, 180, 255, 100), INDICATOR_SMART_HL)
        self.setIndicatorDrawUnder(True, INDICATOR_SMART_HL)
        
        # Indicatore Smart Highlight: box arrotondato tenue sotto il testo
        self.indicatorDefine(
            QsciScintilla.IndicatorStyle.RoundBoxIndicator, INDICATOR_SMART_HL
        )
        self.setIndicatorForegroundColor(QColor(100, 180, 255, 100), INDICATOR_SMART_HL)
        self.setIndicatorDrawUnder(True, INDICATOR_SMART_HL)

        # --- INIZIO SPELL CHECKER ---
        # Indicatore errori ortografici (ondina rossa SOTTO il testo)
        self.indicatorDefine(
            QsciScintilla.IndicatorStyle.SquiggleIndicator, INDICATOR_SPELL
        )
        self.setIndicatorForegroundColor(QColor(255, 0, 0), INDICATOR_SPELL)
        self.setIndicatorDrawUnder(True, INDICATOR_SPELL)
        # --- FINE SPELL CHECKER ---

    def _setup_caret(self) -> None:
        """Configura il cursore (caret)."""
        self.setCaretLineVisible(True)
        self.setCaretLineBackgroundColor(QColor("#2a2d2e"))
        self.setCaretForegroundColor(QColor("#aeafad"))
        self.setCaretWidth(2)

    def _setup_selection(self) -> None:
        """Configura colori di selezione."""
        self.setSelectionBackgroundColor(QColor("#264f78"))
        self.setSelectionForegroundColor(QColor("#ffffff"))

    def _setup_connections(self) -> None:
        """Connette i segnali Scintilla ai segnali pubblici del widget."""
        self.modificationChanged.connect(self._on_modification_changed)
        self.cursorPositionChanged.connect(self._on_cursor_changed)
        self.selectionChanged.connect(self._on_selection_changed)
        self.SCN_ZOOM.connect(self._on_zoom_changed)

        # Aggiorna larghezza margine numeri di riga al cambio testo
        self.linesChanged.connect(self._update_line_number_margin)

        # Smart Highlight: avvia il timer ad ogni movimento cursore
        self.cursorPositionChanged.connect(
            lambda *_: self._smart_hl_timer.start()
        )
        
        self.userListActivated.connect(self._on_user_list_selection)

    # ── Slot interni ──────────────────────────────────────────────────────────

    def _on_modification_changed(self, modified: bool) -> None:
        self.modified_changed.emit(modified)

    def _on_cursor_changed(self, line: int, col: int) -> None:
        # Scintilla usa 0-based, emettiamo 1-based
        self.cursor_changed.emit(line + 1, col + 1)

    def _on_selection_changed(self) -> None:
        text = self.selectedText()
        lines = text.count("\n") + 1 if text else 0
        self.selection_changed_info.emit(len(text), lines if text else 0)

    def _on_zoom_changed(self) -> None:
        level = self.SendScintilla(QsciScintilla.SCI_GETZOOM)
        self._zoom_level = level
        self.zoom_changed.emit(level)

    def _update_line_number_margin(self) -> None:
        """Adatta la larghezza del margine al numero di righe."""
        lines = self.lines()
        digits = len(str(lines)) + 1
        self.setMarginWidth(MARGIN_LINE_NUMBERS, "0" * (digits + 1))

    def _do_smart_highlight(self) -> None:
        """Evidenzia tutte le occorrenze della parola sotto il cursore."""
        if not self._smart_highlight_enabled:
            return
        # Pulisce le evidenziazioni precedenti
        length = len(self.text())
        self.clearIndicatorRange(0, 0, self.lines(), 0, INDICATOR_SMART_HL)
        # Se c'è una selezione manuale, non sovrascrivere
        if self.hasSelectedText():
            return
        line, col = self.getCursorPosition()
        word = self.wordAtLineIndex(line, col)
        if not word or len(word) < 2:
            return
        # Cerca tutte le occorrenze nel testo
        text = self.text()
        import re
        pattern = r'\b' + re.escape(word) + r'\b'
        for m in re.finditer(pattern, text):
            start = m.start()
            end   = m.end()
            # Converti offset byte in (riga, col) per Scintilla
            line_s = text[:start].count('\n')
            col_s  = start - text[:start].rfind('\n') - 1
            line_e = text[:end].count('\n')
            col_e  = end - text[:end].rfind('\n') - 1
            self.fillIndicatorRange(line_s, col_s, line_e, col_e, INDICATOR_SMART_HL)

    def set_smart_highlight_enabled(self, enabled: bool) -> None:
        """Abilita/disabilita lo smart highlight."""
        self._smart_highlight_enabled = enabled
        if not enabled:
            self.clearIndicatorRange(0, 0, self.lines(), 0, INDICATOR_SMART_HL)

    # ── Proprietà documento ───────────────────────────────────────────────────

    @property
    def file_path(self) -> Optional[Path]:
        return self._file_path

    @file_path.setter
    def file_path(self, path: Optional[Path]) -> None:
        self._file_path = path

    @property
    def encoding(self) -> str:
        return self._encoding

    @property
    def line_ending(self) -> LineEnding:
        return self._line_ending

    @property
    def zoom_level(self) -> int:
        return self._zoom_level

    def is_modified(self) -> bool:
        return self.isModified()

    def is_read_only(self) -> bool:
        return self.isReadOnly()

    def set_read_only(self, value: bool) -> None:
        self._read_only_forced = value
        self.setReadOnly(value)

    # ── Contenuto ─────────────────────────────────────────────────────────────

    def load_content(self, text: str, encoding: str = "UTF-8",
                     line_ending: Optional[LineEnding] = None) -> None:
        """
        Carica il testo nell'editor. Rileva il line ending se non fornito.
        Resetta lo stato di modifica.
        """
        if line_ending is None:
            line_ending = LineEnding.detect(text)

        # Normalizza a LF internamente (Scintilla lavora con LF)
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")

        self._encoding = encoding
        self._line_ending = line_ending

        self.setEolMode(line_ending.to_qsci())

        # Blocca i segnali durante il caricamento per evitare falsi "modified"
        self.blockSignals(True)
        self.setText(normalized)
        self.setModified(False)
        self.blockSignals(False)

        # Posiziona il cursore all'inizio
        self.setCursorPosition(0, 0)

        self.encoding_changed.emit(encoding)
        self.line_ending_changed.emit(line_ending.label())
        self._update_line_number_margin()

    def get_content(self) -> str:
        """
        Restituisce il testo corrente con il line ending del documento.
        """
        text = self.text()
        # Scintilla restituisce sempre LF — convertiamo al line ending originale
        if self._line_ending == LineEnding.CRLF:
            text = text.replace("\n", "\r\n")
        elif self._line_ending == LineEnding.CR:
            text = text.replace("\n", "\r")
        return text

    def mark_saved(self) -> None:
        """Segna il documento come non modificato dopo il salvataggio."""
        self.setModified(False)

    # ── Font ──────────────────────────────────────────────────────────────────

    def set_font_family(self, family: str, size: int = 11) -> None:
        """
        Imposta il font per tutto l'editor (testo e margini).
        Il lexer attivo sovrascriverà questa impostazione per i token;
        questo font è il default per il testo non colorato.
        """
        font = QFont(family, size)
        font.setFixedPitch(True)

        self.setFont(font)
        self.setMarginsFont(font)

        # Aggiorna anche il lexer corrente se presente
        lexer = self.lexer()
        if lexer:
            lexer.setFont(font)
            lexer.setDefaultFont(font)

        self._update_line_number_margin()

    def get_font(self) -> QFont:
        return self.font()

    # ── Zoom ──────────────────────────────────────────────────────────────────

    def zoom_in(self) -> None:
        self.zoomIn()

    def zoom_out(self) -> None:
        self.zoomOut()

    def zoom_reset(self) -> None:
        self.zoomTo(0)

    # ── Visualizzazione ───────────────────────────────────────────────────────

    def set_show_whitespace(self, visible: bool) -> None:
        mode = (QsciScintilla.WhitespaceVisibility.WsVisible
                if visible else
                QsciScintilla.WhitespaceVisibility.WsInvisible)
        self.setWhitespaceVisibility(mode)

    def set_show_eol(self, visible: bool) -> None:
        self.setEolVisibility(visible)

    def set_word_wrap(self, enabled: bool) -> None:
        mode = (QsciScintilla.WrapMode.WrapWord
                if enabled else
                QsciScintilla.WrapMode.WrapNone)
        self.setWrapMode(mode)

    def set_show_indentation_guides(self, visible: bool) -> None:
        self.setIndentationGuides(visible)

    def set_show_line_numbers(self, visible: bool) -> None:
        if visible:            
            self._update_line_number_margin()
        else:
            self.setMarginWidth(MARGIN_LINE_NUMBERS, 0)

    def set_tab_width(self, width: int) -> None:
        self.setTabWidth(width)

    def set_use_tabs(self, use_tabs: bool) -> None:
        self.setIndentationsUseTabs(use_tabs)

    # ── Line ending ───────────────────────────────────────────────────────────

    def set_line_ending(self, le: LineEnding) -> None:
        """Cambia il line ending del documento (non converte il testo esistente)."""
        self._line_ending = le
        self.setEolMode(le.to_qsci())
        self.line_ending_changed.emit(le.label())

    def convert_line_endings(self, le: LineEnding) -> None:
        """Converte tutti i line ending nel documento al nuovo stile."""
        self._line_ending = le
        self.setEolMode(le.to_qsci())
        self.convertEols(le.to_qsci())
        self.line_ending_changed.emit(le.label())

    # ── Encoding ──────────────────────────────────────────────────────────────

    def set_encoding(self, encoding: str) -> None:
        """Aggiorna l'encoding registrato (la conversione è in file_manager.py)."""
        self._encoding = encoding
        self.encoding_changed.emit(encoding)

    # ── Selezione e cursore ───────────────────────────────────────────────────

    def get_cursor_position_1based(self) -> tuple[int, int]:
        """Restituisce (riga, colonna) con indici 1-based."""
        line, col = self.getCursorPosition()
        return line + 1, col + 1

    def go_to_line(self, line_1based: int, center: bool = True) -> None:
        """Sposta il cursore alla riga indicata (1-based)."""
        line_0 = max(0, min(line_1based - 1, self.lines() - 1))
        self.setCursorPosition(line_0, 0)
        if center:
            self.ensureLineVisible(line_0)
            self.SendScintilla(QsciScintilla.SCI_SCROLLCARET)

    def get_selected_text_info(self) -> dict:
        """Restituisce informazioni sulla selezione corrente."""
        text = self.selectedText()
        if not text:
            return {"text": "", "chars": 0, "lines": 0, "words": 0}
        words = len(text.split())
        lines = text.count("\n") + 1
        return {"text": text, "chars": len(text), "lines": lines, "words": words}

    # ── Operazioni testo ─────────────────────────────────────────────────────

    def duplicate_line(self) -> None:
        """Duplica la riga corrente o la selezione."""
        self.SendScintilla(QsciScintilla.SCI_LINEDUPLICATE)

    def delete_line(self) -> None:
        """Elimina la riga corrente."""
        self.SendScintilla(QsciScintilla.SCI_LINEDELETE)

    def move_line_up(self) -> None:
        """Sposta la riga corrente verso l'alto."""
        self.SendScintilla(QsciScintilla.SCI_MOVESELECTEDLINESUP)

    def move_line_down(self) -> None:
        """Sposta la riga corrente verso il basso."""
        self.SendScintilla(QsciScintilla.SCI_MOVESELECTEDLINESDOWN)

    def toggle_overwrite(self) -> None:
        """Alterna modalità inserimento / sovrascrittura."""
        self._overwrite = not self._overwrite
        self.SendScintilla(
            QsciScintilla.SCI_SETOVERTYPE, int(self._overwrite)
        )
        self.overwrite_changed.emit(self._overwrite)

    # ── Indicatori (Find/Replace) ─────────────────────────────────────────────

    def clear_indicator(self, indicator: int) -> None:
        """Rimuove tutti i marcatori di un indicatore."""
        self.clearIndicatorRange(
            0, 0,
            self.lines() - 1, self.lineLength(self.lines() - 1),
            indicator
        )

    def indicatorValueAt(self, indicator: int, pos: int) -> int:
        """
        Restituisce il valore dell'indicatore alla posizione assoluta pos.
        Wrappa SCI_INDICATORVALUEAT che QScintilla PyQt6 non espone direttamente.
        Restituisce 0 (assente) o 1 (presente).
        """
        return self.SendScintilla(
            QsciScintilla.SCI_INDICATORVALUEAT, indicator, pos
        )

    def set_autoclose_enabled(self, enabled: bool) -> None:
        """
        Abilita/disabilita la chiusura automatica delle parentesi.
        Richiede che AutoCloseBrackets sia installato nell'editor;
        se non presente il metodo è un no-op sicuro.
        """
        self._autoclose_enabled = enabled
        if hasattr(self, "_autoclose_brackets"):
            self._autoclose_brackets.setEnabled(enabled)

    def set_indicator_range(self, indicator: int,
                            start: int, length: int) -> None:
        """Applica un indicatore su un intervallo di caratteri (offset assoluto)."""
        line_s, col_s = self._offset_to_line_col(start)
        line_e, col_e = self._offset_to_line_col(start + length)
        self.fillIndicatorRange(line_s, col_s, line_e, col_e, indicator)

    def _offset_to_line_col(self, offset: int) -> tuple[int, int]:
        """Converte un offset assoluto in (riga, colonna) 0-based."""
        line = self.SendScintilla(QsciScintilla.SCI_LINEFROMPOSITION, offset)
        col  = offset - self.SendScintilla(
            QsciScintilla.SCI_POSITIONFROMLINE, line
        )
        return line, col

    # ── Tema / Colori base ────────────────────────────────────────────────────

    def apply_theme_colors(self, bg: str, fg: str,
                           caret_line: str, margin_bg: str,
                           margin_fg: str) -> None:
        """
        Applica i colori base del tema all'editor.
        I colori dei token sono gestiti da editor/lexers.py.
        """
        self.setPaper(QColor(bg))
        self.setColor(QColor(fg))
        self.setCaretLineBackgroundColor(QColor(caret_line))
        self.setMarginsBackgroundColor(QColor(margin_bg))
        self.setMarginsForegroundColor(QColor(margin_fg))

        # Aggiorna anche il lexer se presente
        lexer = self.lexer()
        if lexer:
            lexer.setPaper(QColor(bg))
            lexer.setColor(QColor(fg))

    # ── Override eventi ───────────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        """Intercetta Insert per toggle overwrite e registra macro."""
        if event.key() == Qt.Key.Key_Insert and not event.modifiers():
            self.toggle_overwrite()
            return
        # Registrazione macro: cattura tasti con testo stampabile
        try:
            from core.macro import MacroManager
            mm = MacroManager.instance()
            if mm.is_recording() and mm._current_editor is self:
                text = event.text()
                key  = event.key()
                mods = event.modifiers()
                if text and text.isprintable():
                    mm._actions.append({"type": "insert", "text": text})
                elif key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                    mm._actions.append({"type": "insert", "text": "\n"})
                elif key == Qt.Key.Key_Tab:
                    mm._actions.append({"type": "insert", "text": "\t"})
                elif key == Qt.Key.Key_Backspace:
                    mm._actions.append({"type": "backspace"})
                elif key == Qt.Key.Key_Delete:
                    mm._actions.append({"type": "delete"})
        # ... (codice macro esistente) ...
        except Exception:
            pass
        super().keyPressEvent(event)

        # --- INIZIO AUTOCOMPLETAMENTO BIBTEX ---
        if event.text() == '{':
            from editor.lexers import get_language_name
            lang = get_language_name(self).lower()
            if "latex" in lang or "tex" in lang:
                line, index = self.getCursorPosition()
                text_before = self.text(line)[:index]
                if text_before.endswith(r"\cite{"):
                    self._show_bibtex_autocomplete()
        # --- FINE AUTOCOMPLETAMENTO BIBTEX ---

    def wheelEvent(self, event) -> None:
        """Ctrl+Scroll → zoom."""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

    def dragEnterEvent(self, event) -> None:
        """Accetta il drag di file."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        """
        Drop di file: emette un segnale fake verso la MainWindow.
        Il drop di testo è gestito da QScintilla in modo nativo.
        """
        if event.mimeData().hasUrls():
            paths = [Path(u.toLocalFile())
                     for u in event.mimeData().urls()
                     if u.isLocalFile()]
            if paths:
                # Lascia che la MainWindow gestisca l'apertura via segnale Qt
                # Usiamo la proprietà parent per risalire alla finestra
                win = self.window()
                if hasattr(win, "open_files"):
                    win.open_files(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    # ── Bookmark ──────────────────────────────────────────────────────────────

    def _on_margin_clicked(self, margin: int, line: int, modifiers) -> None:
        """Toggle bookmark al click sul margine simboli."""
        if margin == MARGIN_SYMBOLS:
            self.toggle_bookmark(line)

    def toggle_bookmark(self, line: int = -1) -> None:
        """Toggle bookmark sulla riga indicata (0-based). -1 = riga corrente."""
        if line < 0:
            line, _ = self.getCursorPosition()
        mask = self.markersAtLine(line)
        if mask & (1 << MARKER_BOOKMARK):
            self.markerDelete(line, MARKER_BOOKMARK)
        else:
            self.markerAdd(line, MARKER_BOOKMARK)

    def next_bookmark(self) -> None:
        """Sposta il cursore al prossimo bookmark."""
        line, _ = self.getCursorPosition()
        next_line = self.markerFindNext(line + 1, 1 << MARKER_BOOKMARK)
        if next_line < 0:
            # Wrap-around dall'inizio
            next_line = self.markerFindNext(0, 1 << MARKER_BOOKMARK)
        if next_line >= 0:
            self.setCursorPosition(next_line, 0)
            self.ensureLineVisible(next_line)

    def prev_bookmark(self) -> None:
        """Sposta il cursore al bookmark precedente."""
        line, _ = self.getCursorPosition()
        prev_line = self.markerFindPrevious(line - 1, 1 << MARKER_BOOKMARK)
        if prev_line < 0:
            # Wrap-around dalla fine
            prev_line = self.markerFindPrevious(self.lines() - 1, 1 << MARKER_BOOKMARK)
        if prev_line >= 0:
            self.setCursorPosition(prev_line, 0)
            self.ensureLineVisible(prev_line)

    def clear_bookmarks(self) -> None:
        """Rimuove tutti i bookmark dal documento."""
        self.markerDeleteAll(MARKER_BOOKMARK)

    def get_bookmarks(self) -> list[int]:
        """Restituisce la lista delle righe (0-based) con bookmark."""
        bookmarks = []
        line = self.markerFindNext(0, 1 << MARKER_BOOKMARK)
        while line >= 0:
            bookmarks.append(line)
            line = self.markerFindNext(line + 1, 1 << MARKER_BOOKMARK)
        return bookmarks
        
    # ── Controllo Ortografico ──────────────────────────────────────────────────

    def set_spellcheck_enabled(self, enabled: bool, lang: str = "it") -> None:
        """Attiva o disattiva il controllo ortografico per questo editor."""
        if enabled:
            try:
                from spellchecker import SpellChecker
                # Carica il dizionario (ci mette una frazione di secondo)
                self._spell_checker = SpellChecker(language=lang)
                self._do_spell_check() # Fa un primo controllo immediato
            except ImportError:
                self._spell_checker = None
                print("[SpellCheck] Installa la libreria con: pip install pyspellchecker")
        else:
            self._spell_checker = None
            # Pulisce tutte le ondine rosse
            self.clearIndicatorRange(0, 0, self.lines(), 0, INDICATOR_SPELL)

    def _do_spell_check(self) -> None:
        """Trova le parole sconosciute e disegna l'ondina rossa."""
        if not self._spell_checker:
            return

        text = self.text()
        # Pulisce gli errori precedenti per non fare sovrapposizioni
        self.clearIndicatorRange(0, 0, self.lines(), 0, INDICATOR_SPELL)

        import re
        # Cerca parole di sole lettere, ignorando i comandi LaTeX che iniziano per "\"
        # Include lettere accentate italiane
        pattern = r'(?<!\\)\b[A-Za-zàèìòùé]+\b'

        words_found = []
        matches = []

        for m in re.finditer(pattern, text):
            word = m.group(0)
            # Filtra parole troppo corte o interamente maiuscole (sigle)
            if len(word) > 2 and not word.isupper():
                words_found.append(word)
                matches.append(m)

        # Chiede al dizionario quali di queste parole sono sbagliate (è molto veloce!)
        unknown = self._spell_checker.unknown(words_found)

        # Disegna l'ondina rossa sotto le parole sbagliate
        for m in matches:
            if m.group(0) in unknown:
                start = m.start()
                end = m.end()
                line_s, col_s = self._offset_to_line_col(start)
                line_e, col_e = self._offset_to_line_col(end)
                self.fillIndicatorRange(line_s, col_s, line_e, col_e, INDICATOR_SPELL)    
        
    # ── Autocompletamento BibTeX ──────────────────────────────────────────────

    def _show_bibtex_autocomplete(self) -> None:
        """Cerca file .bib nella cartella e mostra le chiavi nel menu a tendina."""
        if not self.file_path or not self.file_path.parent.exists():
            return
            
        import re
        bib_keys = []
        
        # Cerca tutti i file .bib nella cartella corrente
        for bib_file in self.file_path.parent.glob("*.bib"):
            try:
                content = bib_file.read_text(encoding="utf-8", errors="ignore")
                # Trova tutto ciò che assomiglia a @tipo{CHIAVE,
                matches = re.findall(r'@[a-zA-Z]+\s*\{\s*([^,]+),', content)
                bib_keys.extend(matches)
            except Exception:
                pass
        
        if bib_keys:
            # Rimuove i duplicati e ordina alfabeticamente
            bib_keys = sorted(list(set(bib_keys)))
            # Mostra la lista usando l'ID 1 (per distinguerlo da altri popup)
            self.showUserList(1, bib_keys)

    def _on_user_list_selection(self, list_id: int, text: str) -> None:
        """Inserisce la chiave selezionata nel testo."""
        if list_id == 1:
            self.insert(text)

    # ── Metodi per compatibilità ─────────────────────────────────────────────    

    # ── Metodi per compatibilità ─────────────────────────────────────────────

    def print(self, printer) -> None:
        """Stampa il contenuto dell'editor usando QPrinter."""
        from PyQt6.QtGui import QPainter, QTextDocument
        from PyQt6.QtCore import QRectF
        
        # Crea un documento di testo dal contenuto dell'editor
        doc = QTextDocument()
        doc.setPlainText(self.text())
        doc.setDefaultFont(self.font())
        
        # Stampa il documento
        doc.print(printer)



# ─── Test standalone ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    from PyQt6.QtWidgets import QMainWindow, QVBoxLayout, QLabel, QStatusBar

    app = QApplication(sys.argv)

    win = QMainWindow()
    win.setWindowTitle("EditorWidget — Test standalone")
    win.resize(900, 600)

    editor = EditorWidget()

    # Lexer Python di test
    lexer = QsciLexerPython()
    lexer.setDefaultFont(editor.font())
    editor.setLexer(lexer)

    # Carica testo di esempio
    sample = '''#!/usr/bin/env python3
"""Test NotePadPQ EditorWidget"""

from pathlib import Path
from i18n.i18n import tr

def saluta(nome: str) -> str:
    """Restituisce un saluto."""
    return f"Ciao, {nome}!"

if __name__ == "__main__":
    print(saluta("mondo"))
    print(tr("action.save"))
'''
    editor.load_content(sample, encoding="UTF-8", line_ending=LineEnding.LF)

    # Statusbar minimale
    sb = win.statusBar()
    info = QLabel("Riga 1, Col 1  |  UTF-8  |  LF")
    sb.addWidget(info)

    def update_cursor(line, col):
        enc  = editor.encoding
        le   = editor.line_ending.label()
        mod  = " [modificato]" if editor.is_modified() else ""
        info.setText(f"Riga {line}, Col {col}  |  {enc}  |  {le}{mod}")

    def update_modified(modified):
        update_cursor(*editor.get_cursor_position_1based())

    editor.cursor_changed.connect(update_cursor)
    editor.modified_changed.connect(update_modified)

    win.setCentralWidget(editor)
    win.show()

    print("=== EditorWidget test ===")
    print(f"Font:         {editor.font().family()} {editor.font().pointSize()}pt")
    print(f"Encoding:     {editor.encoding}")
    print(f"Line ending:  {editor.line_ending.label()}")
    print(f"Righe:        {editor.lines()}")
    print(f"Read-only:    {editor.is_read_only()}")

    sys.exit(app.exec())

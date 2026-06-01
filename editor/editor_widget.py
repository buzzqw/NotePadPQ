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

import re
import sys
from enum import Enum
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont, QKeySequence
from PyQt6.QtWidgets import QWidget, QApplication, QMenu

from PyQt6.Qsci import (
    QsciScintilla,
    QsciLexerPython,   # usato solo nel test standalone
)

from core.platform import get_preferred_monospace_font, IS_WINDOWS
from i18n.i18n import tr

# Dipendenze opzionali per hover preview — caricate in lazy loading al primo utilizzo
_fitz = None          # PyMuPDF — importato solo se richiesto
_HAS_FITZ: bool | None = None   # None = non ancora verificato
_plt = None           # matplotlib.pyplot — importato solo se richiesto
_HAS_MATPLOTLIB: bool | None = None

# Pattern per spell check — Unicode, copre IT/EN/DE/FR/ES e qualsiasi alfabeto latino esteso
_RE_SPELL = re.compile(r"(?<![\\])\b[^\W\d_]+\b", re.UNICODE)

# ─── Utilità conversione testo → tabella ──────────────────────────────────────

def _detect_table_delimiter(lines: list[str]) -> str | None:
    """Ritorna il delimitatore più probabile tra colonne, o None se il testo non è tabulare.

    TAB: bastano 2 righe con ≥2 colonne non-vuote dopo lo split (numero variabile di tab
    per riga è normale nell'allineamento visivo).

    Pipe/semicolon/comma: almeno 1/3 delle righe con conteggio coerente.

    Spazi multipli: almeno 1/3 delle righe con ≥1 gruppo di spazi coerente.
    """
    # TAB — soglia assoluta bassa: bastano 2 righe "tabulari"
    tab_lines = [l for l in lines if "\t" in l]
    if len(tab_lines) >= 2:
        cols_counts = [len([p for p in l.split("\t") if p.strip()]) for l in tab_lines]
        if all(c >= 2 for c in cols_counts):
            return "\t"

    min_lines = max(2, len(lines) // 3)

    for delim in ("|", ";", ","):
        counts = [line.count(delim) for line in lines]
        nonzero = [c for c in counts if c > 0]
        if len(nonzero) >= min_lines and min(nonzero) == max(nonzero):
            return delim

    counts = [len(re.findall(r"  +", line.rstrip())) for line in lines]
    nonzero = [c for c in counts if c > 0]
    if len(nonzero) >= min_lines and max(nonzero) - min(nonzero) <= 1:
        return "  "

    return None


def _parse_tabular_text(text: str):
    """
    Prova a interpretare il testo come tabella.
    Restituisce list[list[str]] (tutte le righe, già paddate a n_cols) o None.
    - Include TUTTE le righe non vuote (quelle senza delimitatore primario vengono
      trattate come riga a colonna singola + celle vuote, o tentano il fallback spazi).
    - Il chiamante decide quale riga usare come intestazione.
    """
    raw_lines = [l for l in text.splitlines() if l.strip()]
    if len(raw_lines) < 2:
        return None
    delim = _detect_table_delimiter(raw_lines)
    if delim is None:
        return None

    def split_line(line: str) -> list[str]:
        if delim == "\t":
            parts = [p.strip() for p in line.split("\t") if p.strip()]
            if len(parts) >= 2:
                return parts
            # fallback spazi per righe miste (es. allineate con spazi invece di tab)
            space_parts = [p.strip() for p in re.split(r"  +", line.strip()) if p.strip()]
            return space_parts if len(space_parts) >= 2 else [line.strip()]
        if delim == "  ":
            parts = [p.strip() for p in re.split(r"  +", line.strip()) if p.strip()]
            return parts if parts else [line.strip()]
        parts = [p.strip() for p in line.split(delim)]
        return [c for c in parts if c] if delim == "|" else parts

    rows = [split_line(l) for l in raw_lines]
    # Scarta righe separatore tipo |---|---|  o  ====  ---
    rows = [r for r in rows if not all(re.fullmatch(r"[-:=\s|]+", c) for c in r)]
    if not rows:
        return None
    n_cols = max(len(r) for r in rows)
    if n_cols < 2:
        return None
    # Padda righe con meno colonne (righe senza marcatore → cella vuota)
    rows = [r + [""] * (n_cols - len(r)) for r in rows]
    return rows


def _build_md_table(headers: list[str], data: list[list[str]]) -> str:
    def esc(s: str) -> str:
        return str(s).replace("|", "\\|").replace("\n", " ")

    widths = [max(3, len(esc(h))) for h in headers]
    for row in data:
        for i in range(len(headers)):
            widths[i] = max(widths[i], len(esc(row[i] if i < len(row) else "")))

    def pad(s: str, w: int) -> str:
        return esc(s).ljust(w)

    header_line = "| " + " | ".join(pad(h, widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line    = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    rows = ["| " + " | ".join(pad(row[i] if i < len(row) else "", widths[i])
                               for i in range(len(headers))) + " |"
            for row in data]
    return "\n".join([header_line, sep_line] + rows)


def _build_tabularx_table(headers: list[str], data: list[list[str]]) -> str:
    _TEX = str.maketrans({"&": "\\&", "%": "\\%", "$": "\\$", "#": "\\#",
                           "_": "\\_", "{": "\\{", "}": "\\}", "~": "\\textasciitilde{}",
                           "^": "\\textasciicircum{}", "\\": "\\textbackslash{}"})

    def esc(s: str) -> str:
        return str(s).translate(_TEX)

    n = len(headers)
    col_spec   = "X" * n if n else "X"
    header_row = " & ".join(f"\\textbf{{{esc(h)}}}" for h in headers) + " \\\\"
    rows_lines = [" & ".join(esc(row[i] if i < len(row) else "") for i in range(n)) + " \\\\"
                  for row in data]
    return "\n".join([
        "% Richiede: \\usepackage{tabularx,booktabs}",
        "\\begin{table}[htbp]",
        "\\centering",
        f"\\begin{{tabularx}}{{\\textwidth}}{{{col_spec}}}",
        "\\toprule",
        header_row,
        "\\midrule",
        *rows_lines,
        "\\bottomrule",
        "\\end{tabularx}",
        "\\caption{}",
        "\\label{tab:}",
        "\\end{table}",
    ])


def _split_rows_for_table(all_rows: list[list[str]], first_row_is_header: bool):
    """Restituisce (headers, data) a partire da tutte le righe parsed."""
    if first_row_is_header:
        return all_rows[0], all_rows[1:]
    n = max(len(r) for r in all_rows)
    headers = [str(i + 1) for i in range(n)]
    return headers, all_rows


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
MARGIN_GIT          = 3   # Git gutter (righe aggiunte/modificate/rimosse)

# Marker Scintilla
MARKER_BOOKMARK = 0   # cerchio blu per bookmark
MARKER_GIT_ADD  = 1   # rettangolo verde  — riga aggiunta vs HEAD
MARKER_GIT_MOD  = 2   # rettangolo arancione — riga modificata vs HEAD
MARKER_GIT_DEL  = 3   # rettangolo rosso  — riga rimossa vs HEAD

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
    selection_changed_info = pyqtSignal(int, int, int) # chars, righe, byte
    zoom_changed       = pyqtSignal(int)         # livello zoom corrente
    overwrite_changed  = pyqtSignal(bool)        # modalità inserimento/sovrascrittura
    language_changed   = pyqtSignal(str)         # es. "Python", "LaTeX"
    lsp_hover_requested  = pyqtSignal(int, int)  # line, col (0-based) — per hover LSP
    context_menu_requested = pyqtSignal(object)  # QMenu — plugin possono aggiungere voci

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # Stato documento
        self._encoding: str    = "UTF-8"
        self._line_ending: LineEnding = LineEnding.LF
        self._file_path: Optional[Path] = None
        self._read_only_forced: bool = False
        self._zoom_level: int  = 0
        self._overwrite: bool  = False
        self._show_line_numbers: bool = True
        from config.settings import Settings
        self._smart_highlight_enabled: bool = Settings.instance().get(
            "editor/smart_highlight_enabled", True
        )
        self._plain_text_mode: bool = False
        self._saved_language: str = ""
        self._auto_indent_paste: bool = False
        self._typewriter_mode: bool = False
        self._in_paste: bool = False         # True durante incolla: sopprime SCN_CHARADDED
        self._tabstops: list = []            # [(n, abs_pos, default_len)] navigazione snippet
        self._tabstop_index: int = 0
        self._smart_hl_word: str = ""           # cache: evita regex se parola invariata
        self._smart_hl_text_len: int = 0         # lunghezza testo all'ultimo highlight
        self._smart_hl_timer: QTimer = QTimer(self)
        self._smart_hl_timer.setSingleShot(True)
        self._smart_hl_timer.setInterval(600)    # 600ms: bilancia reattività e costo CPU
        self._smart_hl_timer.timeout.connect(self._do_smart_highlight)

        # --- SPELL CHECKER ---
        self._spell_checker = None
        self._spell_lang: str = ""
        self._spell_personal: set[str] = set()  # dizionario personale persistente per sessione
        self._spell_timer = QTimer(self)
        self._spell_timer.setSingleShot(True)
        self._spell_timer.setInterval(1000)
        self._spell_timer.timeout.connect(self._do_spell_check)
        self._spell_text_hash: int = 0
        self.textChanged.connect(self._spell_timer.start)
        # --- FINE SPELL CHECKER ---

        # Multi-cursore (Ctrl+D, Ctrl+Shift+D, Ctrl+Alt+↑/↓, …)
        from editor.multicursor import MultiCursorManager
        self._multicursor = MultiCursorManager(self)

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
        self.setWhitespaceSize(2)

        # Encoding interno Scintilla — sempre UTF-8, la conversione
        # a/da encoding del file è gestita da file_manager.py
        self.setUtf8(True)

        # Selezione rettangolare con Alt+Drag e Alt+Shift+frecce
        self.SendScintilla(
            QsciScintilla.SCI_SETMOUSESELECTIONRECTANGULARSWITCH, True
        )
        # SCVS_RECTANGULARSELECTION = 1 — abilita la selezione rettangolare
        # anche da tastiera (Alt+Shift+frecce), come in Notepad++ e TeXstudio
        self.SendScintilla(QsciScintilla.SCI_SETVIRTUALSPACEOPTIONS, 1)

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

        # Marker bookmark: cerchio pieno
        self.markerDefine(QsciScintilla.MarkerSymbol.Circle, MARKER_BOOKMARK)
        self.setMarkerBackgroundColor(QColor("#4ec9b0"), MARKER_BOOKMARK)
        self.setMarkerForegroundColor(QColor("#1e1e1e"), MARKER_BOOKMARK)
        self.marginClicked.connect(self._on_margin_clicked)

        # Margine Git Gutter (larghezza 4px, nascosto finché non ci sono diff)
        self.setMarginType(MARGIN_GIT, QsciScintilla.MarginType.SymbolMarginDefaultForegroundColor)
        self.setMarginWidth(MARGIN_GIT, 0)
        self.setMarginSensitivity(MARGIN_GIT, False)

        # Marker Git Gutter: rettangoli colorati a tutta altezza
        self.markerDefine(QsciScintilla.MarkerSymbol.FullRectangle, MARKER_GIT_ADD)
        self.setMarkerBackgroundColor(QColor("#2ea043"), MARKER_GIT_ADD)
        self.markerDefine(QsciScintilla.MarkerSymbol.FullRectangle, MARKER_GIT_MOD)
        self.setMarkerBackgroundColor(QColor("#d29922"), MARKER_GIT_MOD)
        self.markerDefine(QsciScintilla.MarkerSymbol.FullRectangle, MARKER_GIT_DEL)
        self.setMarkerBackgroundColor(QColor("#f85149"), MARKER_GIT_DEL)

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
        self.cursorPositionChanged.connect(self._apply_typewriter_scroll)
        self.selectionChanged.connect(self._on_selection_changed)
        self.SCN_ZOOM.connect(self._on_zoom_changed)

        # Aggiorna larghezza margine numeri di riga al cambio testo
        self.linesChanged.connect(self._update_line_number_margin)

        # Smart Highlight: avvia il timer ad ogni movimento cursore
        self.cursorPositionChanged.connect(
            lambda *_: self._smart_hl_timer.start()
        )

        self.userListActivated.connect(self._on_user_list_selection)

        # --- INIZIO HOVER IMMAGINI ---
        try:
            # Imposta quanto tempo il mouse deve stare fermo prima di attivarsi (400 ms)
            self.SendScintilla(self.SCI_SETMOUSEDWELLTIME, 400)
            self.SCN_DWELLSTART.connect(self._on_dwell_start)
            self.SCN_DWELLEND.connect(self._on_dwell_end)
        except Exception as e:
            print(f"[Editor] Hover immagini non attivato: {e}")
        # --- FINE HOVER IMMAGINI ---

    # ── Slot interni ──────────────────────────────────────────────────────────

    def _on_modification_changed(self, modified: bool) -> None:
        self.modified_changed.emit(modified)

    def _on_cursor_changed(self, line: int, col: int) -> None:
        # Scintilla usa 0-based, emettiamo 1-based
        self.cursor_changed.emit(line + 1, col + 1)

    def _on_selection_changed(self) -> None:
        # Ottimizzazione: selectedText() + encode() sono costosi; salta se non c'è selezione
        if not self.hasSelectedText():
            self.selection_changed_info.emit(0, 0, 0)
            return
        text = self.selectedText()
        lines = text.count("\n") + 1
        byte_count = len(text.encode(self.encoding or "utf-8", errors="replace"))
        self.selection_changed_info.emit(len(text), lines, byte_count)

    def _on_zoom_changed(self) -> None:
        level = self.SendScintilla(QsciScintilla.SCI_GETZOOM)
        self._zoom_level = level
        self.zoom_changed.emit(level)

    def _update_line_number_margin(self) -> None:
        """Adatta la larghezza del margine al numero di righe."""
        if not self._show_line_numbers:
            return
        lines = self.lines()
        digits = len(str(lines)) + 1
        # Ricalcola solo se il numero di cifre è effettivamente cambiato
        current_width = self.marginWidth(MARGIN_LINE_NUMBERS)
        needed_str = "0" * (digits + 1)
        # Stima approssimativa: evita setMarginWidth se la larghezza è già adeguata
        if hasattr(self, '_margin_digits') and self._margin_digits == digits:
            return
        self._margin_digits = digits
        self.setMarginWidth(MARGIN_LINE_NUMBERS, needed_str)

    def _do_smart_highlight(self) -> None:
        """Evidenzia tutte le occorrenze della parola sotto il cursore.

        Ottimizzazioni:
        - Skip su file > 200 KB (testo lungo rende la regex costosa)
        - La cache _smart_hl_word viene invalidata confrontando anche la lunghezza
          del testo, così modifiche al testo forzano il ricalcolo anche se la
          parola corrente è rimasta la stessa (es. si aggiunge un'altra occorrenza)
        """
        if not self._smart_highlight_enabled:
            return
        if self.hasSelectedText():
            if self._smart_hl_word:
                self.clearIndicatorRange(0, 0, self.lines(), 0, INDICATOR_SMART_HL)
                self._smart_hl_word = ""
                self._smart_hl_text_len = 0
            return
        line, col = self.getCursorPosition()
        word = self.wordAtLineIndex(line, col)
        if not word or len(word) < 2:
            if self._smart_hl_word:
                self.clearIndicatorRange(0, 0, self.lines(), 0, INDICATOR_SMART_HL)
                self._smart_hl_word = ""
                self._smart_hl_text_len = 0
            return

        # Non evidenziare se il cursore è sul bordo destro o sinistro della parola.
        line_text = self.text(line)
        char_right = line_text[col] if col < len(line_text) else ""
        char_left  = line_text[col - 1] if col > 0 else ""
        right_is_word = char_right.isalnum() or char_right == "_"
        left_is_word  = char_left.isalnum()  or char_left  == "_"
        if (left_is_word and not right_is_word) or (right_is_word and not left_is_word):
            if self._smart_hl_word:
                self.clearIndicatorRange(0, 0, self.lines(), 0, INDICATOR_SMART_HL)
                self._smart_hl_word = ""
                self._smart_hl_text_len = 0
            return

        text = self.text()
        text_len = len(text)

        # Skip su file grandi: > 200 KB la regex può bloccare il thread UI
        if text_len > 200_000:
            if self._smart_hl_word:
                self.clearIndicatorRange(0, 0, self.lines(), 0, INDICATOR_SMART_HL)
                self._smart_hl_word = ""
                self._smart_hl_text_len = 0
            return

        # Salta il ricalcolo se parola E lunghezza del testo sono invariate
        if word == self._smart_hl_word and text_len == self._smart_hl_text_len:
            return
        self._smart_hl_word = word
        self._smart_hl_text_len = text_len

        import bisect
        pattern = r'\b' + re.escape(word) + r'\b'

        # Costruisce la lista newline con str.find() — più veloce del list-comp char-by-char
        newlines: list[int] = []
        pos = text.find('\n')
        while pos != -1:
            newlines.append(pos)
            pos = text.find('\n', pos + 1)

        self.clearIndicatorRange(0, 0, self.lines(), 0, INDICATOR_SMART_HL)

        count = 0
        for m in re.finditer(pattern, text):
            start, end = m.start(), m.end()
            line_s = bisect.bisect_right(newlines, start)
            col_s  = start - (newlines[line_s - 1] + 1 if line_s > 0 else 0)
            line_e = bisect.bisect_right(newlines, end)
            col_e  = end - (newlines[line_e - 1] + 1 if line_e > 0 else 0)
            self.fillIndicatorRange(line_s, col_s, line_e, col_e, INDICATOR_SMART_HL)
            count += 1
            if count >= 500:  # parole troppo comuni rallentano tutto il rendering
                break

    def set_smart_highlight_enabled(self, enabled: bool) -> None:
        """Abilita/disabilita lo smart highlight."""
        self._smart_highlight_enabled = enabled
        if not enabled:
            self.clearIndicatorRange(0, 0, self.lines(), 0, INDICATOR_SMART_HL)

    def set_plain_text_mode(self, enabled: bool) -> None:
        """
        Modalità testo semplice: disabilita syntax highlight, brace matching,
        smart highlight e autocompletamento per questo tab.
        """
        if enabled == self._plain_text_mode:
            return
        self._plain_text_mode = enabled

        if enabled:
            # Salva il linguaggio corrente per poterlo ripristinare
            from editor.lexers import get_language_name
            self._saved_language = get_language_name(self)
            # Rimuovi lexer (niente syntax highlight)
            self.setLexer(None)
            # Riapplica i colori del tema: setLexer(None) resetta STYLE_DEFAULT
            from config.themes import ThemeManager
            ThemeManager.instance().apply_to_editor(self)
            # Niente brace matching
            self.setBraceMatching(QsciScintilla.BraceMatch.NoBraceMatch)
            # Niente smart highlight
            self.set_smart_highlight_enabled(False)
            # Niente autocompletamento
            self.setAutoCompletionSource(
                QsciScintilla.AutoCompletionSource.AcsNone
            )
        else:
            # Ripristina il lexer salvato
            lang = self._saved_language or "testo normale"
            from editor.lexers import set_lexer_by_name
            set_lexer_by_name(self, lang)
            # Ripristina brace matching
            self.setBraceMatching(QsciScintilla.BraceMatch.SloppyBraceMatch)
            # Ripristina smart highlight
            self.set_smart_highlight_enabled(True)
            # Ripristina autocompletamento (delega all'AutoCompleteManager)
            ac = getattr(self, "_autocomplete", None)
            if ac:
                ac._apply_levels()

    def _invalidate_hl_cache(self) -> None:
        """Invalida la cache smart-hl (chiamato esplicitamente, non su ogni textChanged)."""
        self._smart_hl_word = ""
        self._smart_hl_text_len = 0

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

    def set_typewriter_mode(self, enabled: bool) -> None:
        self._typewriter_mode = enabled

    def _apply_typewriter_scroll(self, line: int, _col: int) -> None:
        if not self._typewriter_mode:
            return
        visible = self.SendScintilla(self.SCI_LINESONSCREEN)
        target = max(0, line - visible // 2)
        self.setFirstVisibleLine(target)

    def set_word_wrap(self, enabled: bool) -> None:
        mode = (QsciScintilla.WrapMode.WrapWord
                if enabled else
                QsciScintilla.WrapMode.WrapNone)
        self.setWrapMode(mode)

    def set_show_indentation_guides(self, visible: bool) -> None:
        self.setIndentationGuides(visible)

    def set_edge_column(self, col: int) -> None:
        """Mostra/nasconde la riga guida verticale alla colonna indicata (0 = disabilitata)."""
        if col > 0:
            self.setEdgeMode(QsciScintilla.EdgeMode.EdgeLine)
            self.setEdgeColumn(col)
            self.setEdgeColor(QColor("#3a3a3a"))
        else:
            self.setEdgeMode(QsciScintilla.EdgeMode.EdgeNone)

    def update_git_gutter(self, added: set, modified: set, deleted: set) -> None:
        """Aggiorna i marker del git gutter. Tutti i set contengono indici riga 0-based."""
        self.markerDeleteAll(MARKER_GIT_ADD)
        self.markerDeleteAll(MARKER_GIT_MOD)
        self.markerDeleteAll(MARKER_GIT_DEL)
        for line in added:
            self.markerAdd(line, MARKER_GIT_ADD)
        for line in modified:
            self.markerAdd(line, MARKER_GIT_MOD)
        for line in deleted:
            self.markerAdd(line, MARKER_GIT_DEL)
        self.setMarginWidth(MARGIN_GIT, 4 if (added or modified or deleted) else 0)

    def set_show_line_numbers(self, visible: bool) -> None:
        self._show_line_numbers = visible
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

    # ── Navigazione tab-stop snippet ─────────────────────────────────────────

    def _jump_to_next_tabstop(self) -> None:
        """Avanza al prossimo tab-stop dello snippet attivo."""
        if self._tabstop_index >= len(self._tabstops):
            self._tabstops = []
            self._tabstop_index = 0
            return
        _n, abs_pos, default_len = self._tabstops[self._tabstop_index]
        self._tabstop_index += 1
        try:
            if default_len > 0:
                sl, sc = self.lineIndexFromPosition(abs_pos)
                el, ec = self.lineIndexFromPosition(abs_pos + default_len)
                self.setSelection(sl, sc, el, ec)
            else:
                tl, tc = self.lineIndexFromPosition(abs_pos)
                self.setCursorPosition(tl, tc)
        except Exception:
            self._tabstops = []
            self._tabstop_index = 0

    # ── Override eventi ───────────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        """Intercetta Insert per toggle overwrite e registra macro."""
        self._hide_hover_popup()

        # Navigazione tab-stop snippet: Tab avanza, Escape annulla
        if self._tabstops:
            if (event.key() == Qt.Key.Key_Tab
                    and not event.modifiers()
                    and not self.isListActive()):
                self._jump_to_next_tabstop()
                return
            if event.key() == Qt.Key.Key_Escape:
                self._tabstops = []
                self._tabstop_index = 0
                # non blocca Escape: lo gestisce anche super() (chiude popup)

        if event.key() == Qt.Key.Key_Insert and not event.modifiers():
            self.toggle_overwrite()
            return
        # Auto-indent su incolla (Ctrl+V)
        if (self._auto_indent_paste
                and event.key() == Qt.Key.Key_V
                and event.modifiers() == Qt.KeyboardModifier.ControlModifier):
            cb_text = QApplication.clipboard().text()
            if cb_text and "\n" in cb_text:
                # Applica il re-indent solo se il cursore è all'inizio di una
                # riga o su una riga vuota; se è nel mezzo di una riga con
                # testo prima del cursore il re-indent produce righe errate.
                if self.hasSelectedText():
                    cur_line, cur_col, _, _ = self.getSelection()
                else:
                    cur_line, cur_col = self.getCursorPosition()
                text_before_cursor = self.text(cur_line)[:cur_col]
                if text_before_cursor.strip() == "":
                    # Cursore su riga vuota o a inizio riga: re-indent sicuro
                    self._paste_with_indent(cb_text)
                    return
                # Altrimenti: paste nativo (sopprime SCN_CHARADDED via flag)
                self._in_paste = True
                try:
                    super().keyPressEvent(event)
                finally:
                    self._in_paste = False
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
        self._hide_hover_popup()
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

    # ── Auto-indent paste ─────────────────────────────────────────────────────

    def set_auto_indent_paste(self, enabled: bool) -> None:
        self._auto_indent_paste = enabled

    def paste(self) -> None:
        """Override paste nativo: sopprime SCN_CHARADDED durante l'operazione."""
        self._in_paste = True
        try:
            super().paste()
        finally:
            self._in_paste = False

    def _paste_with_indent(self, text: str) -> None:
        """Incolla testo riallineando l'indentazione al contesto corrente."""
        # Determina il punto di inserimento PRIMA di rimuovere la selezione
        if self.hasSelectedText():
            line, col, _, _ = self.getSelection()
        else:
            line, col = self.getCursorPosition()

        cur_line_text = self.text(line).rstrip("\r\n")   # rimuove il \n che QScintilla include
        cur_indent = len(cur_line_text) - len(cur_line_text.lstrip())
        cur_indent_text = cur_line_text[:cur_indent]

        lines = text.splitlines()
        if not lines:
            return

        def _leading(s):
            return len(s) - len(s.lstrip())

        non_empty = [ln for ln in lines if ln.strip()]
        min_indent = min((_leading(ln) for ln in non_empty), default=0)

        result_lines = []
        for i, ln in enumerate(lines):
            if i == 0:
                result_lines.append(ln.lstrip() if non_empty else ln)
            else:
                stripped = ln[min_indent:] if len(ln) >= min_indent else ln.lstrip()
                result_lines.append(cur_indent_text + stripped)

        self._in_paste = True
        self.beginUndoAction()
        if self.hasSelectedText():
            self.removeSelectedText()
        self.insert("\n".join(result_lines))
        new_line = line + len(result_lines) - 1
        new_col = (col + len(result_lines[0])) if len(result_lines) == 1 else len(result_lines[-1])
        self.setCursorPosition(new_line, new_col)
        self.endUndoAction()
        self._in_paste = False

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
                self._spell_lang = lang
                self._spell_checker = SpellChecker(language=lang)
                if self._spell_personal:
                    self._spell_checker.word_frequency.load_words(self._spell_personal)
                self._spell_text_hash = 0
                self._do_spell_check()
            except ImportError:
                self._spell_checker = None
                print("[SpellCheck] Installa con: pip install pyspellchecker")
        else:
            self._spell_checker = None
            self.clearIndicatorRange(0, 0, self.lines(), 0, INDICATOR_SPELL)

    def set_spell_language(self, lang: str) -> None:
        """Cambia la lingua del dizionario senza disabilitare lo spell check."""
        if self._spell_checker is None:
            return
        try:
            from spellchecker import SpellChecker
            self._spell_lang = lang
            self._spell_checker = SpellChecker(language=lang)
            if self._spell_personal:
                self._spell_checker.word_frequency.load_words(self._spell_personal)
            self._spell_text_hash = 0
            self._do_spell_check()
        except Exception:
            pass

    def _do_spell_check(self) -> None:
        """Trova le parole sconosciute e disegna l'ondina rossa.

        Ottimizzazioni applicate:
        - early-exit se il testo è vuoto o invariato (hash cache)
        - indice newline costruito con str.split() invece di enumerate()
        - unknown lookup deduplicato: ogni parola distinta è verificata una sola volta
        """
        if not self._spell_checker:
            return

        import bisect
        text = self.text()

        # Early-exit: testo vuoto
        if not text:
            self._spell_text_hash = 0
            return

        h = hash(text)
        if h == self._spell_text_hash:
            return
        self._spell_text_hash = h

        self.clearIndicatorRange(0, 0, self.lines(), 0, INDICATOR_SPELL)

        # Raccoglie tuple (start, end, word) invece di re.Match objects:
        # tuple leggere occupano meno RAM (~40% risparmio per elemento) e sono
        # sufficienti perché ci servono solo la posizione e il testo della parola.
        positions: list[tuple[int, int, str]] = []
        words_found: list[str] = []
        seen_words: set[str] = set()          # deduplicazione per il lookup
        for m in _RE_SPELL.finditer(text):
            word = m.group(0)
            # Salta: meno di 3 lettere, tutto maiuscolo (acronimi), sole cifre
            if len(word) > 2 and not word.isupper() and not word.isdigit():
                positions.append((m.start(), m.end(), word))
                if word not in seen_words:
                    seen_words.add(word)
                    words_found.append(word)

        if not words_found:
            return

        unknown = self._spell_checker.unknown(words_found)
        if not unknown:
            return

        # Offset delle newline per conversione posizione→(riga,col) in O(log n).
        # str.split() è implementato in C ed è più veloce di enumerate() su testi grandi.
        # NOTA: l'ultima entry viene scartata (non corrisponde a un '\n' reale).
        newlines: list[int] = []
        pos = 0
        lines_list = text.split('\n')
        last_idx = len(lines_list) - 1
        for i, line in enumerate(lines_list):
            pos += len(line)
            if i < last_idx:       # salta l'entry finale (non è un '\n' reale)
                newlines.append(pos)
            pos += 1               # salta il '\n' stesso

        for start, end, word in positions:
            if word not in unknown:
                continue
            line_s = bisect.bisect_right(newlines, start)
            col_s  = start - (newlines[line_s - 1] + 1 if line_s > 0 else 0)
            line_e = bisect.bisect_right(newlines, end)
            col_e  = end - (newlines[line_e - 1] + 1 if line_e > 0 else 0)
            self.fillIndicatorRange(line_s, col_s, line_e, col_e, INDICATOR_SPELL)

    def contextMenuEvent(self, event) -> None:
        """Menu contestuale: suggerimenti ortografici in cima, poi azioni standard."""
        menu = QMenu(self)

        if self._spell_checker is not None:
            result = self._spell_word_at_point(event.pos().x(), event.pos().y())
            if result is not None:
                word, ls, cs, le, ce = result
                if len(word) > 2 and not word.isupper() and self._spell_checker.unknown([word]):
                    candidates = self._spell_checker.candidates(word) or set()
                    suggestions = sorted(candidates - {word.lower()})[:8]
                    if suggestions:
                        for s in suggestions:
                            act = menu.addAction(s)
                            act.triggered.connect(
                                lambda _checked, s=s, ls=ls, cs=cs, le=le, ce=ce:
                                self._spell_replace(ls, cs, le, ce, s)
                            )
                    else:
                        na = menu.addAction(tr("label.spell_no_suggestions"))
                        na.setEnabled(False)
                    menu.addSeparator()
                    add_act = menu.addAction(tr("label.spell_add_dict"))
                    add_act.triggered.connect(lambda _checked, w=word: self._spell_add_to_personal(w))
                    ign_act = menu.addAction(tr("label.spell_ignore_all"))
                    ign_act.triggered.connect(lambda _checked, w=word: self._spell_add_to_personal(w))
                    menu.addSeparator()

        # Converti in tabella (visibile solo se la selezione è tabulare)
        if self.hasSelectedText():
            parsed = _parse_tabular_text(self.selectedText())
            if parsed is not None:
                conv_menu = menu.addMenu(tr("action.convert_table"))

                md_menu  = conv_menu.addMenu(tr("action.convert_table_md"))
                a = md_menu.addAction(tr("action.table_header_row"))
                a.triggered.connect(lambda _: self._convert_selection_to_table("markdown", True))
                a = md_menu.addAction(tr("action.table_data_rows"))
                a.triggered.connect(lambda _: self._convert_selection_to_table("markdown", False))

                tex_menu = conv_menu.addMenu(tr("action.convert_table_tex"))
                a = tex_menu.addAction(tr("action.table_header_row"))
                a.triggered.connect(lambda _: self._convert_selection_to_table("tabularx", True))
                a = tex_menu.addAction(tr("action.table_data_rows"))
                a.triggered.connect(lambda _: self._convert_selection_to_table("tabularx", False))

                menu.addSeparator()

        cut   = menu.addAction(tr("action.cut"))
        cut.triggered.connect(self.cut)
        cut.setEnabled(self.hasSelectedText())
        copy  = menu.addAction(tr("action.copy"))
        copy.triggered.connect(self.copy)
        copy.setEnabled(self.hasSelectedText())
        paste = menu.addAction(tr("action.paste"))
        paste.triggered.connect(self.paste)
        menu.addSeparator()
        sel   = menu.addAction(tr("action.select_all"))
        sel.triggered.connect(self.selectAll)

        # Permette ai plugin di aggiungere voci al menu contestuale
        self.context_menu_requested.emit(menu)

        menu.exec(event.globalPos())

    def _spell_word_at_point(self, x: int, y: int):
        """Restituisce (word, line_s, col_s, line_e, col_e) per la parola sotto (x,y)."""
        from PyQt6.QtCore import QPoint
        line = self.lineAt(QPoint(x, y))
        if line < 0:
            return None
        line_text = self.text(line)
        if not line_text:
            return None
        # Posizione Scintilla → indice nella riga
        scin_pos = self.SendScintilla(2023, x, y)  # SCI_POSITIONFROMPOINT = 2023
        _, col = self.lineIndexFromPosition(scin_pos)
        for m in _RE_SPELL.finditer(line_text):
            if m.start() <= col <= m.end():
                return m.group(0), line, m.start(), line, m.end()
        return None

    def _spell_replace(self, ls: int, cs: int, le: int, ce: int, replacement: str) -> None:
        self.setSelection(ls, cs, le, ce)
        self.replaceSelectedText(replacement)

    def _spell_add_to_personal(self, word: str) -> None:
        """Aggiunge la parola al dizionario personale (sessione corrente)."""
        w = word.lower()
        self._spell_personal.add(w)
        if self._spell_checker:
            self._spell_checker.word_frequency.load_words([w])
        self._spell_text_hash = 0
        self._do_spell_check()

    # ── Conversione selezione → tabella ──────────────────────────────────────

    def _convert_selection_to_table(self, fmt: str, first_row_is_header: bool) -> None:
        all_rows = _parse_tabular_text(self.selectedText())
        if all_rows is None:
            return
        headers, data = _split_rows_for_table(all_rows, first_row_is_header)
        if fmt == "markdown":
            table_text = _build_md_table(headers, data)
        else:
            table_text = _build_tabularx_table(headers, data)
        self.beginUndoAction()
        self.replaceSelectedText(table_text)
        self.endUndoAction()

    # ── Autocompletamento BibTeX ──────────────────────────────────────────────

    def _show_bibtex_autocomplete(self) -> None:
        """Cerca file .bib nella cartella e mostra le chiavi nel menu a tendina."""
        if not self.file_path or not self.file_path.parent.exists():
            return
            
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
        """Inserisce la voce selezionata nel testo."""
        if list_id == 1:
            self._insert_and_close_brace(text)
        elif list_id in (2, 4, 9):
            # Chiavi BibTeX (\citep/\citet/…), file paths, temi beamer
            # — rimpiazza il prefisso parziale digitato dopo {
            self._insert_replacing_partial_and_close_brace(text)
        elif list_id == 3:
            # Ambienti LaTeX da \begin{
            from editor.latex_support import LaTeXSupport
            LaTeXSupport.insert_environment(self, text)
        elif list_id == 5:
            key = text.split("  [")[0] if "  [" in text else text
            self._insert_and_close_brace(key)
        elif list_id == 6:
            self._insert_and_close_brace(text)
        elif list_id in (10, 11):
            # Opzioni comando/ambiente/pacchetto da [...] — inserisci senza chiudere
            self._insert_replacing_partial(text, delimiter='[')

    def _insert_replacing_partial(self, text: str, delimiter: str) -> None:
        """Sostituisce il prefisso parziale dopo delimiter con text."""
        line, col = self.getCursorPosition()
        line_text = self.text(line)
        text_before = line_text[:col]
        delim_pos = text_before.rfind(delimiter)
        partial = text_before[delim_pos + 1:] if delim_pos >= 0 else ""
        if partial:
            self.setSelection(line, col - len(partial), line, col)
            self.removeSelectedText()
            line, col = self.getCursorPosition()
        self.insert(text)
        self.setCursorPosition(line, col + len(text))

    def _insert_replacing_partial_and_close_brace(self, key: str) -> None:
        """Come _insert_replacing_partial ma usa { come delimitatore e chiude con }."""
        line, col = self.getCursorPosition()
        line_text = self.text(line)
        text_before = line_text[:col]
        brace_pos = text_before.rfind('{')
        partial = text_before[brace_pos + 1:] if brace_pos >= 0 else ""
        if partial:
            self.setSelection(line, col - len(partial), line, col)
            self.removeSelectedText()
            line, col = self.getCursorPosition()
        self.insert(key)
        new_col = col + len(key)
        line_text = self.text(line)
        if new_col < len(line_text) and line_text[new_col] == '}':
            self.setCursorPosition(line, new_col + 1)
        else:
            self.setCursorPosition(line, new_col)
            self.insert('}')
            self.setCursorPosition(line, new_col + 1)

    def _insert_and_close_brace(self, key: str) -> None:
        """Inserisce key alla posizione cursore, sposta il cursore dopo key
        e aggiunge } se non già presente (robustezza per testo digitato manualmente)."""
        line, col = self.getCursorPosition()
        self.insert(key)
        # insert() non sposta il cursore → calcoliamo la nuova posizione
        line_text = self.text(line)
        new_col = col + len(key)
        if new_col < len(line_text) and line_text[new_col] == "}":
            # } già presente (inserita automaticamente) — salta oltre
            self.setCursorPosition(line, new_col + 1)
        else:
            # } assente (testo scritto manualmente) — la aggiungiamo
            self.setCursorPosition(line, new_col)
            self.insert("}")
            self.setCursorPosition(line, new_col + 1)
            
    # ── Tooltip Immagini (Hover) ──────────────────────────────────────────────

    def _hide_hover_popup(self) -> None:
        """Distrugge il popup dell'immagine se esiste."""
        if hasattr(self, '_hover_popup') and self._hover_popup:
            self._hover_popup.hide()
            self._hover_popup.deleteLater()
            self._hover_popup = None

    def _on_dwell_end(self, position: int, x: int, y: int) -> None:
        """Il mouse si è spostato, nascondi l'immagine."""
        self._hide_hover_popup()

    def _on_dwell_start(self, position: int, x: int, y: int) -> None:
        """Il mouse è fermo su una posizione, mostra l'immagine o l'equazione renderizzata."""
        if position < 0:
            return

        self._hide_hover_popup()

        from PyQt6.QtCore import Qt, QPoint
        from PyQt6.QtGui import QPixmap, QImage
        from PyQt6.QtWidgets import QLabel
        from editor.lexers import get_language_name

        # Ottieni le informazioni sul testo e sulla posizione
        line_idx = self.SendScintilla(self.SCI_LINEFROMPOSITION, position)
        line_start = self.SendScintilla(self.SCI_POSITIONFROMLINE, line_idx)
        relative_pos = position - line_start
        text = self.text(line_idx)
        lang = get_language_name(self).lower()

        # ---------------------------------------------------------
        # PARTE 1: RICERCA IMMAGINI (File locali, inclusi PDF)
        # ---------------------------------------------------------
        img_patterns = [
            r'\\includegraphics(?:\[.*?\])?\{([^}]+)\}',  # LaTeX
            r'!\[.*?\]\((.*?)\)',                         # Markdown
            r'<img\s+[^>]*src="([^"]+)"'                  # HTML
        ]

        img_path_str = None
        for p in img_patterns:
            for m in re.finditer(p, text):
                if m.start(1) <= relative_pos <= m.end(1):
                    img_path_str = m.group(1)
                    break
            if img_path_str:
                break

        if img_path_str and self.file_path:
            base_dir = self.file_path.parent
            img_path = base_dir / img_path_str

            if not img_path.exists():
                for ext in ['.png', '.jpg', '.jpeg', '.pdf']:
                    if (base_dir / f"{img_path_str}{ext}").exists():
                        img_path = base_dir / f"{img_path_str}{ext}"
                        break

            if img_path.exists():
                pixmap = None
                if img_path.suffix.lower() == '.pdf':
                    try:
                        global _fitz, _HAS_FITZ
                        if _HAS_FITZ is None:
                            try:
                                import fitz as _fitz
                                _HAS_FITZ = True
                            except ImportError:
                                _fitz = None
                                _HAS_FITZ = False
                        if not _HAS_FITZ:
                            raise ImportError("PyMuPDF non installato")
                        doc = _fitz.open(str(img_path))
                        page = doc.load_page(0)
                        pix = page.get_pixmap(matrix=_fitz.Matrix(1.5, 1.5))
                        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
                        pixmap = QPixmap.fromImage(img)
                    except Exception as e:
                        print(f"[Hover] Errore lettura PDF: {e}")
                else:
                    pixmap = QPixmap(str(img_path))

                if pixmap and not pixmap.isNull():
                    if pixmap.width() > 350 or pixmap.height() > 250:
                        pixmap = pixmap.scaled(350, 250, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    
                    self._create_tooltip_popup(pixmap, x, y)
                    return

        # ---------------------------------------------------------
        # PARTE 2: RICERCA FORMULE MATEMATICHE (LaTeX Math)
        # ---------------------------------------------------------
        if not ("latex" in lang or "tex" in lang or "markdown" in lang):
            # Non LaTeX/Markdown: emetti hover LSP e termina
            self.lsp_hover_requested.emit(line_idx, relative_pos)
            return

        # Cerca formule in linea ($...$) e display equation ($$...$$ o \[...\])
        math_patterns = [
            r'\$\$([^\$]+)\$\$',         # $$...$$
            r'\\\[(.*?)\\\]',            # \[...\]
            r'\$([^\$]+)\$',             # $...$
            r'\\begin\{equation\}(.*?)\\end\{equation\}', # begin{equation}
        ]

        formula_text = None
        for p in math_patterns:
            for m in re.finditer(p, text):
                if m.start() <= relative_pos <= m.end():
                    formula_text = m.group(1).strip()
                    break
            if formula_text:
                break

        if formula_text:
            try:
                global _plt, _HAS_MATPLOTLIB
                if _HAS_MATPLOTLIB is None:
                    try:
                        import matplotlib as _mpl
                        _mpl.use('Agg')
                        import matplotlib.pyplot as _plt
                        _HAS_MATPLOTLIB = True
                    except ImportError:
                        _plt = None
                        _HAS_MATPLOTLIB = False
                if not _HAS_MATPLOTLIB:
                    raise ImportError("matplotlib non installato")
                import io
                formula_to_render = f"${formula_text}$"
                fig = _plt.figure(figsize=(0.01, 0.01))
                fig.text(0, 0, formula_to_render, fontsize=16, color='#e0e0e0', ha='center', va='center')
                buf = io.BytesIO()
                fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', pad_inches=0.1, transparent=True)
                _plt.close(fig)
                buf.seek(0)
                pixmap = QPixmap()
                pixmap.loadFromData(buf.read())
                if not pixmap.isNull():
                    self._create_tooltip_popup(pixmap, x, y)
                    return
            except Exception as e:
                print(f"[Math Hover] Impossibile renderizzare la formula: {e}")

        # ---------------------------------------------------------
        # PARTE 3: DOCUMENTAZIONE COMANDI LaTeX
        # ---------------------------------------------------------
        if "latex" in lang or "tex" in lang:
            from editor.latex_tooltips import get_latex_tooltip_html

            # Cerca \cmd sotto il cursore
            cmd_match = None
            for m in re.finditer(r'\\([a-zA-Z@]+\*?)', text):
                if m.start() <= relative_pos <= m.end():
                    cmd_match = m
                    break
            if cmd_match:
                cmd_name = cmd_match.group(1).rstrip('*')
                html = get_latex_tooltip_html(cmd_name)
                if not html:
                    html = get_latex_tooltip_html(cmd_match.group(1))
                if html:
                    self._create_html_tooltip_popup(html, x, y)
                    return

            # Cerca nome ambiente dentro \begin{...} o \end{...}
            for m in re.finditer(r'\\(?:begin|end)\{([a-zA-Z@*]+)\}', text):
                if m.start(1) <= relative_pos <= m.end(1):
                    html = get_latex_tooltip_html(m.group(1))
                    if html:
                        self._create_html_tooltip_popup(html, x, y)
                        return
                    break

        # Nessuna immagine/formula/comando trovato — chiedi LSP
        self.lsp_hover_requested.emit(line_idx, relative_pos)


    # -- Helper per creare il popup con immagine
    def _create_tooltip_popup(self, pixmap, x, y):
        from PyQt6.QtCore import Qt, QPoint
        from PyQt6.QtWidgets import QLabel
        self._hover_popup = QLabel(self, Qt.WindowType.ToolTip)
        self._hover_popup.setPixmap(pixmap)
        self._hover_popup.setStyleSheet("border: 2px solid #555; background-color: #1e1e1e; border-radius: 4px;")
        global_pos = self.mapToGlobal(QPoint(x, y))
        self._hover_popup.move(global_pos.x() + 15, global_pos.y() + 15)
        self._hover_popup.show()

    # -- Helper per creare il popup con HTML (documentazione comandi)
    def _create_html_tooltip_popup(self, html: str, x: int, y: int) -> None:
        from PyQt6.QtCore import Qt, QPoint
        from PyQt6.QtWidgets import QLabel, QApplication
        lbl = QLabel(self, Qt.WindowType.ToolTip)
        # Sfondo fisso crema: uguale alla cella <td> nell'HTML così Qt non
        # inserisce il background nero del tema tra il bordo e il contenuto
        lbl.setStyleSheet(
            "QLabel { background-color: #fdf6d8; color: #1a1a1a;"
            " border: 1px solid #c8ad00; border-radius: 6px;"
            " padding: 0; margin: 0; }"
        )
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setText(html)
        lbl.setWordWrap(True)
        lbl.setMaximumWidth(460)
        lbl.adjustSize()
        screen = QApplication.primaryScreen().availableGeometry()
        gp = self.mapToGlobal(QPoint(x + 16, y + 18))
        if gp.x() + lbl.width() > screen.right() - 10:
            gp.setX(screen.right() - lbl.width() - 10)
        if gp.y() + lbl.height() > screen.bottom() - 10:
            gp.setY(gp.y() - lbl.height() - 36)
        lbl.move(gp)
        lbl.show()
        self._hover_popup = lbl


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

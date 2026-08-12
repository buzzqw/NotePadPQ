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
from html import escape as _html_escape
from enum import Enum
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt6.QtGui import QColor, QFont, QKeySequence, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import QWidget, QApplication, QMenu

from PyQt6.Qsci import (
    QsciScintilla,
    QsciLexerPython,   # usato solo nel test standalone
)

from core.platform import get_data_dir, get_preferred_monospace_font, IS_WINDOWS
from i18n.i18n import tr

# Dipendenze opzionali per hover preview — caricate in lazy loading al primo utilizzo
_fitz = None          # PyMuPDF — importato solo se richiesto
_HAS_FITZ: bool | None = None   # None = non ancora verificato
_plt = None           # matplotlib.pyplot — importato solo se richiesto
_HAS_MATPLOTLIB: bool | None = None

# Pattern per spell check — Unicode, copre IT/EN/DE/FR/ES e qualsiasi alfabeto latino esteso
_RE_SPELL = re.compile(r"(?<![\\])\b[^\W\d_]+\b", re.UNICODE)
_SPELL_CONTEXT_LINES = 40


def _personal_dict_path(lang: str) -> Path:
    d = get_data_dir() / "spellcheck"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{lang or 'default'}.txt"


def _load_persisted_personal_words(lang: str) -> set[str]:
    """Dizionario personale permanente ("Aggiungi al dizionario"), un file
    di testo per lingua, una parola per riga. Distinto da _spell_personal,
    che resta anche il posto dove vivono le parole ignorate solo per la
    sessione corrente (mai scritte su disco)."""
    try:
        path = _personal_dict_path(lang)
        if not path.exists():
            return set()
        return {
            line.strip().lower()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    except OSError:
        return set()


def _persist_personal_word(lang: str, word: str) -> None:
    try:
        path = _personal_dict_path(lang)
        if word in _load_persisted_personal_words(lang):
            return
        with path.open("a", encoding="utf-8") as f:
            f.write(word + "\n")
    except OSError:
        pass
_SPELL_MAX_SNAPSHOT_BYTES = 256 * 1024


# Citation commands are deliberately parsed here rather than added to the
# support checker: this parser is only used for the local editor interaction
# and keeps source offsets intact (comments are masked, not removed).
_CITATION_COMMANDS = frozenset({
    "parencite", "parencites", "textcite", "textcites", "footcite",
    "footcites", "autocite", "autocites", "smartcite", "smartcites",
    "supercite", "supercites", "citeauthor", "citeyear", "citeyearpar",
    "citealp", "citealt", "citet", "citep", "cites", "nocite",
})
_OPAQUE_CITATION_GROUP_COMMANDS = frozenset({
    "url", "path", "nolinkurl", "texttt", "textsf", "textrm", "textit",
    "textbf", "textup", "textnormal", "emph", "mbox", "fbox",
})
_VERBATIM_CITATION_COMMANDS = frozenset({
    "verb", "Verb", "lstinline", "mintinline",
})


def _latex_scan_text(text: str) -> str:
    """Mask comments without changing any character offsets."""
    chars = list(text)
    in_comment = False
    for index, char in enumerate(text):
        if char == "\n":
            in_comment = False
        elif in_comment:
            chars[index] = " "
        elif char == "%" and not _latex_escaped(text, index):
            chars[index] = " "
            in_comment = True
    return "".join(chars)


def _latex_escaped(text: str, position: int) -> bool:
    slashes = 0
    position -= 1
    while position >= 0 and text[position] == "\\":
        slashes += 1
        position -= 1
    return bool(slashes % 2)


def _latex_balanced_group(text: str, start: int, opening: str = "{") -> tuple[int, int] | None:
    """Return the content span of one balanced local LaTeX group."""
    closing = "}" if opening == "{" else "]"
    if start >= len(text) or text[start] != opening:
        return None
    depth = 1
    index = start + 1
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text):
            index += 2
            continue
        if text[index] == opening:
            depth += 1
        elif text[index] == closing:
            depth -= 1
            if depth == 0:
                return start + 1, index
        index += 1
    return None


def extract_latex_citation_occurrences(text: str) -> list[dict]:
    """Return citation-key spans for common natbib/biblatex commands.

    The result has the same ``kind``, ``key``, ``start`` and ``end`` shape as
    ``LaTeXSupport.extract_label_reference_occurrences``.  It intentionally
    does not attempt to interpret arbitrary TeX macros.
    """
    scanned = _latex_scan_text(text)
    occurrences: list[dict] = []
    index = 0
    while index < len(scanned):
        if scanned[index] != "\\" or _latex_escaped(scanned, index):
            index += 1
            continue
        command_start = index
        index += 1
        name_start = index
        while index < len(scanned) and (scanned[index].isalpha() or scanned[index] == "@"):
            index += 1
        name = scanned[name_start:index]
        if name in _OPAQUE_CITATION_GROUP_COMMANDS:
            while index < len(scanned) and scanned[index].isspace():
                index += 1
            if index < len(scanned) and scanned[index] == "*":
                index += 1
                while index < len(scanned) and scanned[index].isspace():
                    index += 1
            group = _latex_balanced_group(scanned, index)
            index = len(scanned) if group is None else group[1] + 1
            continue
        if name in _VERBATIM_CITATION_COMMANDS:
            while index < len(scanned) and scanned[index].isspace():
                index += 1
            if index < len(scanned):
                delimiter = scanned[index]
                end = scanned.find(delimiter, index + 1)
                index = len(scanned) if end < 0 else end + 1
            continue
        if not name or (name not in _CITATION_COMMANDS and
                        not name.lower().startswith("cite")):
            continue
        if index < len(scanned) and scanned[index] == "*":
            index += 1

        # natbib/biblatex allow one or two optional note arguments.
        for _ in range(2):
            while index < len(scanned) and scanned[index].isspace():
                index += 1
            if index >= len(scanned) or scanned[index] != "[":
                break
            optional = _latex_balanced_group(scanned, index, "[")
            if optional is None:
                index = len(scanned)
                break
            index = optional[1] + 1

        while index < len(scanned) and scanned[index].isspace():
            index += 1
        group = _latex_balanced_group(scanned, index)
        if group is None:
            continue
        content_start, content_end = group
        part_start = content_start
        for position in range(content_start, content_end + 1):
            if position != content_end and scanned[position] != ",":
                continue
            key_start, key_end = part_start, position
            while key_start < key_end and scanned[key_start].isspace():
                key_start += 1
            while key_end > key_start and scanned[key_end - 1].isspace():
                key_end -= 1
            if key_start < key_end:
                occurrences.append({
                    "kind": "citation", "key": text[key_start:key_end],
                    "start": key_start, "end": key_end,
                    "command_start": command_start,
                    "line": text.count("\n", 0, key_start),
                    "column": key_start - text.rfind("\n", 0, key_start) - 1,
                })
            part_start = position + 1
        index = group[1] + 1
    return occurrences


class _SpellWorker(QThread):
    """Calcola le posizioni delle parole sconosciute in un thread separato."""

    done = pyqtSignal(int, list)   # (generation, list[tuple[int,int,int,int]])

    def __init__(self, text: str, spell_checker, personal: frozenset,
                 generation: int, base_line: int = 0):
        super().__init__(None)
        self._text       = text
        self._checker    = spell_checker
        self._personal   = personal
        self._generation = generation
        self._base_line  = base_line
        self._cancelled  = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        import bisect
        text = self._text

        positions: list[tuple[int, int, str]] = []
        words_found: list[str] = []
        seen_words: set[str] = set()
        for m in _RE_SPELL.finditer(text):
            if self._cancelled:
                return
            word = m.group(0)
            if len(word) > 2 and not word.isupper() and not word.isdigit():
                positions.append((m.start(), m.end(), word))
                if word not in seen_words:
                    seen_words.add(word)
                    words_found.append(word)

        if not words_found or self._cancelled:
            self.done.emit(self._generation, [])
            return

        check_list = [w for w in words_found if w not in self._personal]
        unknown = self._checker.unknown(check_list)
        if not unknown or self._cancelled:
            self.done.emit(self._generation, [])
            return

        newlines: list[int] = []
        pos = 0
        lines_list = text.split('\n')
        last_idx = len(lines_list) - 1
        for i, line in enumerate(lines_list):
            pos += len(line)
            if i < last_idx:
                newlines.append(pos)
            pos += 1

        result: list[tuple[int, int, int, int]] = []
        for start, end, word in positions:
            if self._cancelled:
                return
            if word not in unknown:
                continue
            line_s = bisect.bisect_right(newlines, start)
            col_s  = start - (newlines[line_s - 1] + 1 if line_s > 0 else 0)
            line_e = bisect.bisect_right(newlines, end)
            col_e  = end - (newlines[line_e - 1] + 1 if line_e > 0 else 0)
            result.append((line_s + self._base_line, col_s,
                           line_e + self._base_line, col_e))

        if not self._cancelled:
            self.done.emit(self._generation, result)


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
INDICATOR_FIND_LINE = 7   # Evidenziazione riga intera durante la navigazione risultati
INDICATOR_LATEX_COL = 8   # Warning colonne tabella LaTeX (squiggly ambra)

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
    paste_clipboard_image_requested = pyqtSignal()  # incolla immagine clipboard come LaTeX
    latex_image_drop_requested = pyqtSignal(object)  # file immagine trascinato su LaTeX

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
        self._paged_line_offset: Optional[int] = None
        from config.settings import Settings
        self._smart_highlight_enabled: bool = Settings.instance().get(
            "editor/smart_highlight_enabled", True
        )
        self._autoclose_enabled: bool = Settings.instance().get(
            "editor/autoclose", True
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

        # Durante il trascinamento della selezione selectedText() copia tutto
        # il testo scelto. Rimandiamo il conteggio per non farlo a ogni pixel.
        self._selection_info_timer = QTimer(self)
        self._selection_info_timer.setSingleShot(True)
        self._selection_info_timer.setInterval(100)
        self._selection_info_timer.timeout.connect(self._emit_selection_info)

        # Accessibilità - screen reader (NVDA/JAWS/Narrator)
        self.setAccessibleName("Editor — Nessun file")
        self.setAccessibleDescription("Editor di testo con syntax highlighting")

        # --- SPELL CHECKER ---
        self._spell_checker = None
        self._spell_lang: str = ""
        self._spell_personal: set[str] = set()  # parole accettate per questa sessione ("ignora tutto" + dizionario permanente ricaricato all'attivazione)
        self._spell_timer = QTimer(self)
        self._spell_timer.setSingleShot(True)
        self._spell_timer.setInterval(1000)
        self._spell_timer.timeout.connect(self._do_spell_check)
        self._spell_text_hash: int = 0
        self._spell_worker: Optional[_SpellWorker] = None
        self._spell_gen: int = 0
        self._spell_check_range: tuple[int, int] | None = None
        self._spell_marked_range: tuple[int, int] | None = None
        self._old_spell_workers: set = set()
        self.textChanged.connect(self._on_spell_text_changed)
        self.verticalScrollBar().valueChanged.connect(
            lambda _value: self._spell_timer.start() if self._spell_checker else None
        )
        # --- FINE SPELL CHECKER ---

        # --- HOVER POPUP: rete di sicurezza anti-persistenza ---
        # SCN_DWELLEND di Scintilla non scatta sempre (es. il mouse esce dal
        # widget senza un move interno, o la finestra perde il focus), quindi
        # il popup andrebbe chiuso comunque dopo un tempo massimo.
        self._hover_popup_timer = QTimer(self)
        self._hover_popup_timer.setSingleShot(True)
        self._hover_popup_timer.setInterval(8000)
        self._hover_popup_timer.timeout.connect(self._hide_hover_popup)

        # Multi-cursore (Ctrl+D, Ctrl+Shift+D, Ctrl+Alt+↑/↓, …)
        from editor.multicursor import MultiCursorManager
        self._multicursor = MultiCursorManager(self)

        # Sincronizzazione nome \begin{X}/\end{X}: quando il cursore lascia
        # l'argomento di uno dei due dopo averlo modificato, l'altro capo
        # della coppia viene rinominato di conseguenza. Vedi _on_cursor_env_rename.
        self._env_rename_watch: Optional[dict] = None
        self._env_rename_committing: bool = False

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
        # Senza una marker mask esplicita questo margine non mostra NESSUN
        # marker (mask di default = 0): Scintilla, non potendo disegnare
        # l'icona in alcun margine, ripiega colorando l'INTERA riga di testo
        # con lo sfondo del marker (es. i warning colonne tabella LaTeX
        # coloravano tutta la riga invece di un piccolo triangolo nel gutter).
        # Riserva a questo margine tutti i marker tranne quelli di fold
        # (bit 25-31, riservati da Scintilla) e quelli del Git Gutter.
        _fold_mask = 0xFE000000  # bit 25-31, usati da setFolding
        _git_mask  = (1 << MARKER_GIT_ADD) | (1 << MARKER_GIT_MOD) | (1 << MARKER_GIT_DEL)
        self.setMarginMarkerMask(MARGIN_SYMBOLS, ~(_fold_mask | _git_mask) & 0xFFFFFFFF)

        # Marker bookmark: cerchio pieno
        self.markerDefine(QsciScintilla.MarkerSymbol.Circle, MARKER_BOOKMARK)
        self.setMarkerBackgroundColor(QColor("#4ec9b0"), MARKER_BOOKMARK)
        self.setMarkerForegroundColor(QColor("#1e1e1e"), MARKER_BOOKMARK)
        self.marginClicked.connect(self._on_margin_clicked)

        # Margine Git Gutter (larghezza 4px, nascosto finché non ci sono diff)
        self.setMarginType(MARGIN_GIT, QsciScintilla.MarginType.SymbolMarginDefaultForegroundColor)
        self.setMarginWidth(MARGIN_GIT, 0)
        self.setMarginSensitivity(MARGIN_GIT, False)
        self.setMarginMarkerMask(MARGIN_GIT, _git_mask)

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

        # Indicatore find (arancione pieno e marcato sotto il testo).
        # FullBox + alpha alto: la parola trovata risalta molto più di un
        # RoundBox tratteggiato semitrasparente.
        self.indicatorDefine(
            QsciScintilla.IndicatorStyle.FullBoxIndicator, INDICATOR_FIND
        )
        self.setIndicatorForegroundColor(QColor(255, 150, 0, 230), INDICATOR_FIND)
        try:
            # Bordo del box ancora più definito (outline opaco).
            self.setIndicatorOutlineColor(QColor(255, 110, 0, 255), INDICATOR_FIND)
        except Exception:
            pass
        self.setIndicatorDrawUnder(True, INDICATOR_FIND)

        # INDICATOR_MARK1 è usato dal Trova per evidenziare TUTTE le occorrenze
        # (highlight "secondario"), come fanno gli editor PRO (VS Code, Sublime,
        # Notepad++): tutte le occorrenze sono marcate, ma il match corrente
        # (INDICATOR_FIND, arancione pieno marcato) deve restare ben distinto.
        # Per questo MARK1 è un giallo più tenue con bordo definito: leggibile su
        # temi chiari e scuri, ma chiaramente "secondario" rispetto al corrente.
        self.indicatorDefine(
            QsciScintilla.IndicatorStyle.StraightBoxIndicator, INDICATOR_MARK1
        )
        self.setIndicatorForegroundColor(QColor(255, 215, 70, 140), INDICATOR_MARK1)
        try:
            self.setIndicatorOutlineColor(QColor(210, 160, 0, 200), INDICATOR_MARK1)
        except Exception:
            pass
        self.setIndicatorDrawUnder(True, INDICATOR_MARK1)

        # Indicatori Mark 2-4: StraightBox colorato SOTTO il testo
        mark_colors = [
            QColor(0, 200, 100, 180),   # verde
            QColor(100, 150, 255, 180), # blu
            QColor(255, 100, 100, 180), # rosso
        ]
        for i, color in enumerate(mark_colors):
            idx = INDICATOR_MARK2 + i
            self.indicatorDefine(
                QsciScintilla.IndicatorStyle.StraightBoxIndicator, idx
            )
            self.setIndicatorForegroundColor(color, idx)
            self.setIndicatorDrawUnder(True, idx)

        # Indicatore Smart Highlight: box arrotondato tenue (azzurro) sotto il
        # testo. Colore volutamente diverso dal giallo/arancione del Trova così
        # da NON confondere l'evidenziazione della parola sotto il cursore con i
        # risultati di ricerca.
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

        # Indicatore "riga del risultato" — usato quando si naviga un risultato
        # dal pannello Trova. Evidenzia l'INTERA riga così la riga di destinazione
        # salta all'occhio anche quando il caret-line del tema è troppo leggero.
        # Il colore è neutro (bianco/nero traslucido, non ambra) e dipende dal
        # tema: una tinta ambra fissa, sommata al caret-line scuro, produceva un
        # marrone/oliva che abbassava il contrasto coi token sintattici gialli/
        # arancioni dei temi scuri. set_find_line_indicator_theme() viene
        # richiamato anche da ThemeManager.apply_to_editor() ad ogni cambio tema.
        self.indicatorDefine(
            QsciScintilla.IndicatorStyle.StraightBoxIndicator, INDICATOR_FIND_LINE
        )
        self.setIndicatorDrawUnder(True, INDICATOR_FIND_LINE)
        self.set_find_line_indicator_theme(True)

        # Indicatore colonne tabella LaTeX: squiggly ambra sotto il testo.
        # Simile allo spell checker ma giallo/ambra per differenziare i warning
        # di colonna (\"troppe/poche colonne nella tabella\") dagli errori rossi.
        self.indicatorDefine(
            QsciScintilla.IndicatorStyle.SquiggleIndicator, INDICATOR_LATEX_COL
        )
        self.setIndicatorForegroundColor(QColor(200, 160, 0), INDICATOR_LATEX_COL)
        self.setIndicatorDrawUnder(True, INDICATOR_LATEX_COL)

    def _setup_caret(self) -> None:
        """Configura il cursore (caret)."""
        self.setCaretLineVisible(True)
        self.setCaretLineBackgroundColor(QColor("#2a2d2e"))
        self.setCaretForegroundColor(QColor("#aeafad"))
        self.setCaretWidth(2)
        # Mantiene l'evidenziazione della riga corrente anche quando l'editor
        # NON ha il focus: così, navigando da un pannello risultati (Trova /
        # Search PQ), la riga di destinazione resta visibile mentre il focus è
        # ancora sull'albero dei risultati.
        try:
            self.SendScintilla(QsciScintilla.SCI_SETCARETLINEVISIBLEALWAYS, 1)
        except Exception:
            pass

    def _setup_selection(self) -> None:
        """Configura colori di selezione."""
        self.setSelectionBackgroundColor(QColor("#264f78"))
        self.setSelectionForegroundColor(QColor("#ffffff"))

    def _setup_connections(self) -> None:
        """Connette i segnali Scintilla ai segnali pubblici del widget."""
        self.modificationChanged.connect(self._on_modification_changed)
        self.cursorPositionChanged.connect(self._on_cursor_changed)
        self.cursorPositionChanged.connect(self._apply_typewriter_scroll)
        self.cursorPositionChanged.connect(self._on_cursor_env_rename)
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

    def _on_cursor_env_rename(self, line: int, col: int) -> None:
        """
        Se il cursore lascia l'argomento {nome} di un \\begin{...}/\\end{...}
        LaTeX che si stava modificando, sincronizza il nome sull'altro capo
        strutturale della coppia (es. modifichi \\begin{tabular} in
        \\begin{xltabular} e ci sposti via: \\end{tabular} diventa
        \\end{xltabular}). Attivo solo su file LaTeX e mentre non è già in
        corso un commit (altrimenti il riposizionamento del cursore dopo la
        sostituzione ritriggerebbe questa stessa logica)."""
        if self._env_rename_committing:
            return
        if getattr(self, "_current_language", "").lower() != "latex":
            self._env_rename_watch = None
            return

        try:
            from editor.latex_support import LaTeXSupport
            line_text = self.text(line)
            token = LaTeXSupport.env_token_at(line_text, col)
        except Exception:
            self._env_rename_watch = None
            return

        watch = self._env_rename_watch
        if (watch is not None and watch["line"] == line
                and token is not None and token["token_start"] == watch["token_start"]):
            return  # ancora dentro lo stesso argomento: niente da fare

        if watch is not None:
            self._commit_env_rename(watch)
            self._env_rename_watch = None

        if token is not None:
            self._env_rename_watch = {"line": line, **token}

    def _commit_env_rename(self, watch: dict) -> None:
        """Applica all'altro capo della coppia il nome corrente dell'argomento
        tracciato da `watch`, se è cambiato rispetto a quando il tracking è
        iniziato. Vedi _on_cursor_env_rename."""
        from editor.latex_support import LaTeXSupport
        line = watch["line"]
        try:
            current = LaTeXSupport.env_token_at(self.text(line), watch["name_start"])
        except Exception:
            return
        if current is None or current["token_start"] != watch["token_start"]:
            return  # la riga è cambiata: il token non è più quello tracciato

        new_name = current["name"]
        old_name = watch["name"]
        if new_name == old_name or not new_name.strip():
            return

        try:
            match = LaTeXSupport.find_structural_match(self.text(), line, watch["token_start"])
        except Exception:
            return
        if match is None:
            return
        m_line, m_start, m_end = match

        cur_line, cur_col = self.getCursorPosition()
        self._env_rename_committing = True
        try:
            self.beginUndoAction()
            self.setSelection(m_line, m_start, m_line, m_end)
            self.replaceSelectedText(new_name)
            self.endUndoAction()
        finally:
            # setSelection/replaceSelectedText spostano cursore e selezione
            # sull'altro capo della coppia: li ripristiniamo dove l'utente
            # li aveva lasciati (correggendo la colonna se la sostituzione
            # è avvenuta sulla stessa riga, prima della posizione corrente).
            if m_line == cur_line and m_start <= cur_col:
                cur_col = max(0, cur_col + len(new_name) - (m_end - m_start))
            self.setCursorPosition(cur_line, cur_col)
            self._env_rename_committing = False

    def _on_selection_changed(self) -> None:
        # selectedText() + encode() sono costosi per selezioni grandi: durante
        # il drag rimandiamo il calcolo finché la selezione non si stabilizza.
        if not self.hasSelectedText():
            self._selection_info_timer.stop()
            self.selection_changed_info.emit(0, 0, 0)
            return
        self._selection_info_timer.start()

    def _emit_selection_info(self) -> None:
        if not self.hasSelectedText():
            self.selection_changed_info.emit(0, 0, 0)
            return
        # Per selezioni grandi selectedText() duplica l'intero buffer scelto
        # solo per aggiornare la barra di stato. Le coordinate Scintilla sono
        # byte UTF-8 e permettono conteggi immediati; chars=-1 indica che il
        # numero esatto di caratteri non e' stato materializzato.
        start = self.SendScintilla(self.SCI_GETSELECTIONSTART)
        end = self.SendScintilla(self.SCI_GETSELECTIONEND)
        byte_count = abs(end - start)
        if byte_count > 1_000_000:
            line_from, _idx_from, line_to, _idx_to = self.getSelection()
            self.selection_changed_info.emit(-1, abs(line_to - line_from) + 1, byte_count)
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
        if self._paged_line_offset is not None:
            self._render_paged_line_numbers()
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

    def set_paged_line_offset(self, offset: Optional[int]) -> None:
        """Mostra numeri globali per la pagina corrente di un file paginato."""
        self._paged_line_offset = max(0, offset) if offset is not None else None
        if self._paged_line_offset is None:
            self.clearMarginText()
            self.setMarginType(
                MARGIN_LINE_NUMBERS, QsciScintilla.MarginType.NumberMargin
            )
            self._margin_digits = None
            self._update_line_number_margin()
            return
        self._render_paged_line_numbers()

    def _render_paged_line_numbers(self) -> None:
        """Renderizza il margine globale senza indicizzare l'intero file."""
        if not self._show_line_numbers:
            return
        line_count = self.lines()
        # Un file con una newline per byte renderebbe il margine piu costoso
        # della pagina stessa: in quel caso il pager mostra comunque la riga
        # globale iniziale e Scintilla mantiene la numerazione locale.
        if line_count > 200_000:
            self.clearMarginText()
            self.setMarginType(
                MARGIN_LINE_NUMBERS, QsciScintilla.MarginType.NumberMargin
            )
            self.setMarginWidth(MARGIN_LINE_NUMBERS, "000000")
            return

        self.setMarginType(
            MARGIN_LINE_NUMBERS, QsciScintilla.MarginType.TextMargin
        )
        self.clearMarginText()
        last_number = self._paged_line_offset + max(1, line_count)
        digits = len(str(last_number)) + 1
        self.setMarginWidth(MARGIN_LINE_NUMBERS, "0" * digits)
        for line in range(line_count):
            self.setMarginText(
                line, str(self._paged_line_offset + line + 1), 0
            )

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

        # Controlla lunghezza PRIMA di copiare il testo (SCI_GETLENGTH è O(1), self.text() è O(n))
        doc_len = self.SendScintilla(self.SCI_GETLENGTH)
        if doc_len > 200_000:
            if self._smart_hl_word:
                self.clearIndicatorRange(0, 0, self.lines(), 0, INDICATOR_SMART_HL)
                self._smart_hl_word = ""
                self._smart_hl_text_len = 0
            return

        text = self.text()
        text_len = len(text)

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
            # Rimuovi lexer e supporti del linguaggio precedente.
            from editor.lexers import _clear_lexer
            _clear_lexer(self)
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
        if path:
            self.setAccessibleName(f"Editor — {path.name}")
            self.setAccessibleDescription(
                f"File {path.name} in {str(path.parent)}")
        else:
            self.setAccessibleName("Editor — Nuovo file")
            self.setAccessibleDescription("Editor di testo senza file associato")

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
        if self._paged_line_offset is not None:
            self.set_paged_line_offset(None)
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

        # setText() ha i segnali bloccati: il lexer custom non ha ricevuto
        # textChanged e la cache byte può quindi contenere il documento prima
        # del caricamento.
        lexer = self.lexer()
        if hasattr(lexer, "recolor"):
            lexer.recolor()
        elif hasattr(lexer, "invalidate_cache"):
            lexer.invalidate_cache()
            self.SendScintilla(self.SCI_COLOURISE, 0, -1)

        self.refresh_language_support(force_check=True)

    def refresh_language_support(self, force_check: bool = False) -> None:
        """Aggiorna supporto linguaggio, API e checker dopo un load/append."""
        from editor.lexers import refresh_language_support
        refresh_language_support(self, force_check=force_check)

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
        if visible <= 0:
            return
        from config.settings import Settings
        dead_zone = max(0, Settings.instance().get("editor/typewriter_deadzone", 3))
        visual_line = self.SendScintilla(self.SCI_VISIBLEFROMDOCLINE, line)
        first_visual = self.SendScintilla(self.SCI_GETFIRSTVISIBLELINE)
        center_visual = first_visual + visible // 2
        if abs(visual_line - center_visual) > dead_zone:
            target = max(0, visual_line - visible // 2)
            self.SendScintilla(self.SCI_SETFIRSTVISIBLELINE, target)

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

    def go_to_matching(self, line: Optional[int] = None, col: Optional[int] = None) -> bool:
        """
        Salta all'estremo corrispondente della coppia su cui si trova
        (line, col) — il cursore corrente se non specificati.

        Per LaTeX prova prima l'ambiente \\begin{...}/\\end{...} (annidamento
        gestito correttamente), che il matching nativo di Scintilla non
        capisce essendo un costrutto multi-carattere; altrimenti ricade
        sulla parentesi/graffa standard via SCI_BRACEMATCH.

        Restituisce True se un match è stato trovato e il cursore spostato.
        """
        if line is None or col is None:
            line, col = self.getCursorPosition()

        if getattr(self, "_current_language", "").lower() == "latex":
            from editor.latex_support import LaTeXSupport
            match = LaTeXSupport.find_environment_match(self.text(), line, col)
            if match:
                m_line, m_col = match
                self.setCursorPosition(m_line, m_col)
                self.ensureLineVisible(m_line)
                self.SendScintilla(QsciScintilla.SCI_SCROLLCARET)
                return True

        pos = self.positionFromLineIndex(line, col)
        match_pos = self.SendScintilla(QsciScintilla.SCI_BRACEMATCH, pos, 0)
        if match_pos == -1 and pos > 0:
            match_pos = self.SendScintilla(QsciScintilla.SCI_BRACEMATCH, pos - 1, 0)
        if match_pos == -1:
            return False
        self.SendScintilla(QsciScintilla.SCI_SETCURRENTPOS, match_pos)
        self.SendScintilla(QsciScintilla.SCI_SETSEL, match_pos, match_pos)
        m_line = self.SendScintilla(QsciScintilla.SCI_LINEFROMPOSITION, match_pos)
        self.ensureLineVisible(m_line)
        return True

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
        """Abilita/disabilita la chiusura automatica di '}' e '$' letta da
        LaTeXSupport._handle_open_brace/_handle_dollar."""
        self._autoclose_enabled = enabled

    def set_indicator_range(self, indicator: int,
                            start: int, length: int) -> None:
        """Applica un indicatore su un intervallo di **caratteri** (offset
        assoluto sulla stringa Python, come restituito da `re`/`str`).

        IMPORTANTE: QScintilla lavora internamente con offset/colonne in **byte**
        UTF-8, non in caratteri. Su testo con accenti o caratteri non-ASCII
        (es. italiano: `città`, `può`, `perché`) un carattere occupa più byte e
        i due offset divergono. Passare l'offset di carattere direttamente a
        Scintilla sposta l'indicatore su una parola sbagliata. Per questo
        convertiamo qui gli offset di carattere in (riga, colonna-byte) corrette.
        """
        line_s, col_s = self._char_offset_to_line_bytecol(start)
        line_e, col_e = self._char_offset_to_line_bytecol(start + length)
        self.fillIndicatorRange(line_s, col_s, line_e, col_e, indicator)

    def _char_offset_to_line_bytecol(self, char_offset: int) -> tuple[int, int]:
        """Converte un offset di **carattere** (sulla stringa Python dell'intero
        documento) in `(riga, colonna_byte)` come richiesto da QScintilla.

        La colonna è espressa in byte UTF-8 dall'inizio della riga, così gli
        indicatori cadono sempre sulla porzione di testo corretta anche in
        presenza di caratteri multibyte.
        """
        text = self.text()
        char_offset = max(0, min(char_offset, len(text)))
        prefix = text[:char_offset]
        line = prefix.count("\n")
        last_nl = prefix.rfind("\n")
        line_start = last_nl + 1  # 0 se nessun newline
        col_bytes = len(text[line_start:char_offset].encode("utf-8"))
        return line, col_bytes

    def char_col_to_byte_col(self, line: int, char_col: int) -> int:
        """Converte una colonna espressa in **caratteri** (es. l'offset
        `re.match.start()` calcolato sulla stringa Python della riga) nella
        colonna in **byte** UTF-8 richiesta da QScintilla.

        Necessario per `highlight_find_match`, `setSelection`, ecc.: su righe con
        caratteri accentati/multibyte (italiano: `città`, `perché`…) la colonna
        in caratteri e quella in byte divergono, e usare quella in caratteri
        sposterebbe la selezione/indicatore sulla parola sbagliata.
        """
        try:
            line_text = self.text(line)
        except Exception:
            return char_col
        if char_col <= 0:
            return 0
        char_col = min(char_col, len(line_text))
        return len(line_text[:char_col].encode("utf-8"))

    def _offset_to_line_col(self, offset: int) -> tuple[int, int]:
        """Converte un offset **byte** assoluto Scintilla in (riga, colonna-byte)
        0-based. Usa le API native, che ragionano in byte."""
        line = self.SendScintilla(QsciScintilla.SCI_LINEFROMPOSITION, offset)
        col  = offset - self.SendScintilla(
            QsciScintilla.SCI_POSITIONFROMLINE, line
        )
        return line, col

    def set_find_line_indicator_theme(self, is_dark: bool) -> None:
        """Aggiorna il colore della fascia INDICATOR_FIND_LINE in base al tema.

        Usa un overlay neutro (bianco su temi scuri, nero su temi chiari) invece
        di una tinta colorata: schiarisce/scurisce lo sfondo della riga senza
        introdurre una tonalità che possa confliggere con i colori dei token
        sintattici del tema attivo (es. stringhe/numeri ambra/gialli nei temi
        scuri, che con una fascia ambra diventavano illeggibili).
        """
        if is_dark:
            fill, outline = QColor(255, 255, 255, 35), QColor(255, 255, 255, 80)
        else:
            fill, outline = QColor(0, 0, 0, 25), QColor(0, 0, 0, 70)
        self.setIndicatorForegroundColor(fill, INDICATOR_FIND_LINE)
        try:
            self.setIndicatorOutlineColor(outline, INDICATOR_FIND_LINE)
        except Exception:
            pass

    def highlight_find_match(self, line: int, start_col: int,
                             end_col: int) -> None:
        """Evidenzia in modo **visibile** un match di ricerca alla riga `line`
        (0-based), tra le colonne `start_col` e `end_col`.

        Usato dai pannelli risultati (Trova / Search PQ) quando l'utente clicca
        un risultato. Oltre a impostare la selezione (che però QScintilla disegna
        attenuata quando l'editor non ha il focus, perché il focus resta
        sull'albero dei risultati), applica l'indicatore persistente
        `INDICATOR_FIND` sulla parola: questo viene disegnato SOTTO il testo ed è
        sempre visibile indipendentemente dal focus. Centra inoltre la riga.
        """
        line = max(0, min(line, max(0, self.lines() - 1)))
        try:
            line_len = len(self.text(line).rstrip("\n").rstrip("\r"))
        except Exception:
            line_len = 0
        start_col = max(0, min(start_col, line_len))
        end_col   = max(start_col, min(end_col, line_len))

        # 1) Evidenziazione dell'INTERA riga (fascia ambra): rende la riga di
        #    destinazione immediatamente individuabile anche sui temi chiari, dove
        #    il caret-line del tema è spesso troppo tenue per essere notato.
        self.clear_indicator(INDICATOR_FIND_LINE)
        if line_len > 0:
            self.fillIndicatorRange(line, 0, line, line_len, INDICATOR_FIND_LINE)

        # 2) Indicatore persistente sulla PAROLA (visibile anche senza focus):
        #    box arancione pieno e marcato, ben distinto dalla fascia di riga.
        self.clear_indicator(INDICATOR_FIND)
        if end_col > start_col:
            self.fillIndicatorRange(line, start_col, line, end_col,
                                    INDICATOR_FIND)

        # Selezione (sposta anche il caret sulla riga del match).
        self.setSelection(line, start_col, line, end_col)

        # Centra la riga nello schermo invece di limitarsi a renderla visibile:
        # calcola la prima riga visibile in modo che il match finisca a metà
        # dell'area di testo. Usa le righe DOCUMENTO (SCI_LINESONSCREEN conta le
        # righe visibili tenendo conto di eventuale wrapping).
        try:
            self.ensureLineVisible(line)
            visible = self.SendScintilla(QsciScintilla.SCI_LINESONSCREEN)
            if visible > 0:
                # SCI_VISIBLEFROMDOCLINE gestisce code-folding/righe nascoste.
                doc_visible = self.SendScintilla(
                    QsciScintilla.SCI_VISIBLEFROMDOCLINE, line
                )
                first = max(0, doc_visible - visible // 2)
                self.SendScintilla(QsciScintilla.SCI_SETFIRSTVISIBLELINE, first)
            else:
                self.SendScintilla(QsciScintilla.SCI_SCROLLCARET)
        except Exception:
            try:
                self.SendScintilla(QsciScintilla.SCI_SCROLLCARET)
            except Exception:
                pass

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

    @staticmethod
    def _is_latex_image_drop(path: Path) -> bool:
        return path.suffix.lower() in {
            ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff",
            ".webp", ".svg", ".pdf", ".eps",
        }

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accetta immagini nel LaTeX editor per aprire l'assistente figura."""
        if event.mimeData().hasUrls():
            is_latex = (
                (self.file_path and self.file_path.suffix.lower() in {".tex", ".ltx", ".latex"})
                or getattr(self, "_current_language", "").lower() == "latex"
            )
            if is_latex and any(
                    url.isLocalFile() and self._is_latex_image_drop(Path(url.toLocalFile()))
                    for url in event.mimeData().urls()
            ):
                event.acceptProposedAction()
                return
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        """Passa file immagine locali all'assistente LaTeX senza aprirli come tab."""
        is_latex = (
            (self.file_path and self.file_path.suffix.lower() in {".tex", ".ltx", ".latex"})
            or getattr(self, "_current_language", "").lower() == "latex"
        )
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile() and self._is_latex_image_drop(Path(url.toLocalFile()))
        ]
        if is_latex and paths:
            for path in paths:
                self.latex_image_drop_requested.emit(path)
            event.acceptProposedAction()
            return
        if event.mimeData().hasUrls():
            paths = [
                Path(url.toLocalFile())
                for url in event.mimeData().urls()
                if url.isLocalFile()
            ]
            if paths:
                window = self.window()
                if hasattr(window, "open_files"):
                    window.open_files(paths)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

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
        elif (event.key() == Qt.Key.Key_Tab
                and not event.modifiers()
                and not self.isListActive()
                and not self.hasSelectedText()):
            # Trigger + Tab espande lo snippet (editor/snippets.py). Se il
            # testo prima del cursore non è un trigger noto, expand() non
            # tocca nulla e il Tab prosegue come indentazione normale.
            language = getattr(self, "_current_language", "")
            if language:
                from editor.snippets import SnippetManager
                if SnippetManager.instance().expand(self, language):
                    return

        if event.key() == Qt.Key.Key_Insert and not event.modifiers():
            self.toggle_overwrite()
            return
        # Ctrl+V in file LaTeX con immagine nella clipboard → procedura guidata
        if (event.key() == Qt.Key.Key_V
                and event.modifiers() == Qt.KeyboardModifier.ControlModifier):
            _is_latex = (
                (self.file_path and self.file_path.suffix.lower() == ".tex") or
                getattr(self, "_current_language", "").lower() == "latex"
            )
            if _is_latex and not QApplication.clipboard().image().isNull():
                self.paste_clipboard_image_requested.emit()
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

        # Wrap selezione con virgolette/parentesi/backtick
        # Seleziona "testo" e premi " → "testo" (come VS Code, Sublime)
        text = event.text()
        if text and self.hasSelectedText() and self.SendScintilla(
                QsciScintilla.SCI_GETSELECTIONS) <= 1:
            pair: str | None = None
            if text == '"':
                pair = '"'
            elif text == "'":
                pair = "'"
            elif text == '`':
                pair = '`'
            elif text == '(':
                pair = ')'
            elif text == '{':
                pair = '}'
            elif text == '[':
                pair = ']'
            elif text == '<':
                pair = '>'
            if pair is not None:
                sel = self.selectedText()
                self._in_paste = True
                try:
                    self.replaceSelectedText(f"{text}{sel}{pair}")
                finally:
                    self._in_paste = False
                return

        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        """Un click nell'editor chiude sempre il popup di hover."""
        self._hide_hover_popup()
        if (event.button() == Qt.MouseButton.LeftButton
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            position = self.SendScintilla(
                QsciScintilla.SCI_POSITIONFROMPOINTCLOSE,
                int(event.position().x()), int(event.position().y()),
            )
            token = self._latex_semantic_at_position(position)
            if token is not None and self._navigate_latex_semantic(token):
                event.accept()
                return
        super().mousePressEvent(event)

    def focusOutEvent(self, event) -> None:
        """Perdita del focus (cambio tab/finestra) chiude il popup di hover."""
        self._hide_hover_popup()
        super().focusOutEvent(event)

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

    # ── Auto-indent paste ─────────────────────────────────────────────────────

    def set_auto_indent_paste(self, enabled: bool) -> None:
        self._auto_indent_paste = enabled

    def _smart_paste(self) -> None:
        """Incolla: in file .tex con immagine nella clipboard apre la procedura guidata."""
        _is_latex = (
            (self.file_path and self.file_path.suffix.lower() == ".tex") or
            getattr(self, "_current_language", "").lower() == "latex"
        )
        if _is_latex and not QApplication.clipboard().image().isNull():
            self.paste_clipboard_image_requested.emit()
            return
        self.paste()

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
                self._spell_personal |= _load_persisted_personal_words(lang)
                if self._spell_personal:
                    self._spell_checker.word_frequency.load_words(self._spell_personal)
                self._spell_text_hash = 0
                self._do_spell_check()
            except ImportError:
                self._spell_checker = None
                print("[SpellCheck] Installa con: pip install pyspellchecker")
        else:
            self._spell_checker = None
            self._spell_timer.stop()
            self._spell_gen += 1
            if self._spell_worker is not None:
                try:
                    self._spell_worker.cancel()
                except RuntimeError:
                    pass
            self._spell_check_range = None
            self._spell_marked_range = None
            self.clearIndicatorRange(0, 0, self.lines(), 0, INDICATOR_SPELL)

    def set_spell_language(self, lang: str) -> None:
        """Cambia la lingua del dizionario senza disabilitare lo spell check."""
        if self._spell_checker is None:
            return
        try:
            from spellchecker import SpellChecker
            self._spell_lang = lang
            self._spell_checker = SpellChecker(language=lang)
            self._spell_personal |= _load_persisted_personal_words(lang)
            if self._spell_personal:
                self._spell_checker.word_frequency.load_words(self._spell_personal)
            self._spell_text_hash = 0
            self._do_spell_check()
        except Exception:
            pass

    def _do_spell_check(self) -> None:
        """Controlla in background solo il viewport e un piccolo contesto."""
        if not self._spell_checker:
            return

        first_visual = self.SendScintilla(self.SCI_GETFIRSTVISIBLELINE)
        visible_count = max(1, self.SendScintilla(self.SCI_LINESONSCREEN))
        first_line = self.SendScintilla(self.SCI_DOCLINEFROMVISIBLE, first_visual)
        last_line = self.SendScintilla(
            self.SCI_DOCLINEFROMVISIBLE, first_visual + visible_count
        )
        if last_line < first_line:
            last_line = self.lines() - 1
        start_line = max(0, first_line - _SPELL_CONTEXT_LINES)
        end_line = min(self.lines(), last_line + _SPELL_CONTEXT_LINES + 1)

        # Evita anche la copia di una singola riga patologicamente grande. Le
        # righe saltate restano rappresentate da una riga vuota, quindi gli
        # indici assoluti prodotti dal worker rimangono corretti.
        parts: list[str] = []
        used_bytes = 0
        actual_end = start_line
        for line in range(start_line, end_line):
            line_bytes = self.SendScintilla(self.SCI_LINELENGTH, line)
            if line_bytes > _SPELL_MAX_SNAPSHOT_BYTES:
                parts.append("")
            elif used_bytes + line_bytes > _SPELL_MAX_SNAPSHOT_BYTES:
                break
            else:
                part = self.text(line).rstrip("\r\n")
                parts.append(part)
                used_bytes += line_bytes
            actual_end = line + 1
        text = "\n".join(parts)
        if not text:
            self._spell_text_hash = 0
            if self._spell_marked_range:
                start, end = self._spell_marked_range
                self.clearIndicatorRange(start, 0, end, 0, INDICATOR_SPELL)
                self._spell_marked_range = None
            return

        h = hash((start_line, actual_end, text))
        if h == self._spell_text_hash:
            return
        self._spell_text_hash = h

        if self._spell_worker is not None:
            old = self._spell_worker
            try:
                old.cancel()
                self._old_spell_workers.add(old)
                old.finished.connect(lambda w=old: self._old_spell_workers.discard(w))
            except RuntimeError:
                # Il worker precedente è già stato eliminato (deleteLater) ma il
                # riferimento non era ancora stato azzerato: nulla da cancellare.
                pass
            self._spell_worker = None

        self._spell_gen += 1
        worker = _SpellWorker(
            text,
            self._spell_checker,
            frozenset(self._spell_personal),
            self._spell_gen,
            start_line,
        )
        worker.done.connect(self._on_spell_check_done)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda w=worker: self._clear_spell_worker(w))
        self._spell_worker = worker
        self._spell_check_range = (start_line, actual_end)
        worker.start()

    def _on_spell_text_changed(self) -> None:
        """Invalida subito risultati relativi a coordinate ormai superate."""
        self._spell_gen += 1
        if self._spell_worker is not None:
            try:
                self._spell_worker.cancel()
            except RuntimeError:
                pass
        self._spell_timer.start()

    def _clear_spell_worker(self, worker) -> None:
        if self._spell_worker is worker:
            self._spell_worker = None

    def _on_spell_check_done(self, gen: int, positions: list) -> None:
        if gen != self._spell_gen:
            return
        if self._spell_marked_range:
            start, end = self._spell_marked_range
            self.clearIndicatorRange(start, 0, end, 0, INDICATOR_SPELL)
        if self._spell_check_range:
            start, end = self._spell_check_range
            self.clearIndicatorRange(start, 0, end, 0, INDICATOR_SPELL)
            self._spell_marked_range = self._spell_check_range
        for line_s, col_s, line_e, col_e in positions:
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
                    add_act.triggered.connect(lambda _checked, w=word: self._spell_add_to_dictionary(w))
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

        # Submenu cambio lingua dizionario (mostrato solo se spell check attivo)
        if self._spell_checker is not None:
            menu.addSeparator()
            lang_menu = menu.addMenu(tr("action.spell_lang"))
            _current_lang = self._spell_lang or "it"
            from PyQt6.QtGui import QActionGroup as _LangAG
            _lang_ag = _LangAG(menu)
            _lang_ag.setExclusive(True)
            for _lcode, _llabel in [
                ("it", "Italiano"), ("en", "English"), ("de", "Deutsch"),
                ("fr", "Français"), ("es", "Español"), ("pl", "Polski"),
            ]:
                _la = lang_menu.addAction(_llabel)
                _la.setCheckable(True)
                _la.setChecked(_lcode == _current_lang)
                _la.triggered.connect(
                    lambda _checked, c=_lcode: self._change_spell_lang_from_context(c)
                )
                _lang_ag.addAction(_la)
            menu.addSeparator()

        cut   = menu.addAction(tr("action.cut"))
        cut.triggered.connect(self.cut)
        cut.setEnabled(self.hasSelectedText())
        copy  = menu.addAction(tr("action.copy"))
        copy.triggered.connect(self.copy)
        copy.setEnabled(self.hasSelectedText())
        paste = menu.addAction(tr("action.paste"))
        paste.triggered.connect(self._smart_paste)
        menu.addSeparator()

        # "Vai alla corrispondenza": stessa logica di Ctrl+] ma dal punto
        # cliccato invece che dal cursore — utile per saltare da un
        # \begin{ambiente}/graffa aperta direttamente al suo \end{}/graffa
        # di chiusura senza dover prima spostare il cursore lì.
        # SCI_POSITIONFROMPOINTCLOSE (a differenza di SCI_POSITIONFROMPOINT)
        # restituisce -1 se il punto non è vicino a un carattere, invece di
        # agganciarsi comunque alla posizione più vicina.
        click_pos = self.SendScintilla(QsciScintilla.SCI_POSITIONFROMPOINTCLOSE,
                                        event.pos().x(), event.pos().y())
        if click_pos != -1:
            click_line, click_col = self.lineIndexFromPosition(click_pos)
            goto_match = menu.addAction(tr("action.go_to_matching"))
            goto_match.triggered.connect(
                lambda _checked, l=click_line, c=click_col: self._context_go_to_matching(l, c)
            )
            menu.addSeparator()

            semantic = self._latex_semantic_at_position(click_pos)
            if semantic is not None:
                semantic_info = self._latex_semantic_info(semantic)
                if semantic_info is not None:
                    target_path, target_line, target_col, _description = semantic_info
                    action_label = {
                        "label": "Vai alla definizione dell'etichetta",
                        "reference": "Vai alla definizione del riferimento",
                        "citation": "Apri la voce BibTeX",
                    }.get(semantic["kind"], "Vai alla destinazione")
                    semantic_action = menu.addAction(
                        f"{action_label}: {semantic['key']}"
                    )
                    semantic_action.setEnabled(target_line is not None)
                    semantic_action.triggered.connect(
                        lambda _checked, token=semantic:
                        self._navigate_latex_semantic(token)
                    )
                    menu.addSeparator()

            documentation = self._latex_documentation_target(click_pos)
            if documentation is not None:
                target, package = documentation
                texdoc_action = menu.addAction(f"Apri texdoc: {target}")
                texdoc_action.triggered.connect(
                    lambda _checked, value=target: self._open_latex_texdoc(value)
                )
                ctan_action = menu.addAction(
                    f"Apri documentazione CTAN: {package or target}"
                )
                ctan_action.triggered.connect(
                    lambda _checked, value=package or target:
                    self._open_latex_ctan(value)
                )
                menu.addSeparator()

        sel   = menu.addAction(tr("action.select_all"))
        sel.triggered.connect(self.selectAll)

        # Permette ai plugin di aggiungere voci al menu contestuale
        self.context_menu_requested.emit(menu)

        menu.exec(event.globalPos())

    def _latex_semantic_at_position(self, position: int) -> dict | None:
        """Return the local semantic token under a Scintilla position."""
        if position < 0:
            return None
        path = self.file_path
        language = getattr(self, "_current_language", "").lower()
        if not ((path and path.suffix.lower() in {".tex", ".ltx", ".latex"})
                or language in {"latex", "tex", "plain tex", "plaintex"}):
            return None
        text = self.text()
        from editor.latex_support import LaTeXSupport
        occurrences = LaTeXSupport.extract_label_reference_occurrences(text)
        occurrences.extend(extract_latex_citation_occurrences(text))
        return next((item for item in occurrences
                     if item["command_start"] <= position < item["end"]), None)

    @staticmethod
    def _same_path(left: Optional[Path], right: Optional[Path]) -> bool:
        if left is None or right is None:
            return left is right
        try:
            return left.resolve() == right.resolve()
        except OSError:
            return left == right

    def _latex_text_for_path(self, path: Path) -> str:
        """Prefer open, possibly unsaved tabs when inspecting project files."""
        if self._same_path(self.file_path, path):
            return self.text()
        window = self.window()
        tab_manager = getattr(window, "_tab_manager", None)
        for editor in (tab_manager.all_editors() if tab_manager and
                       hasattr(tab_manager, "all_editors") else []):
            if self._same_path(getattr(editor, "file_path", None), path):
                return editor.text()
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeError):
            return ""

    def _bibtex_target(self, key: str) -> tuple[Path, int, int] | None:
        """Find a cited key in the BibTeX files referenced by this project."""
        if not self.file_path:
            return None
        from editor.latex_support import LaTeXSupport

        source_files = LaTeXSupport.collect_project_files(self.file_path)
        if not source_files:
            source_files = [self.file_path.resolve()]
        bib_files: list[Path] = []
        seen: set[Path] = set()
        resource_re = re.compile(
            r"\\(?:bibliography|addbibresource)\s*"
            r"(?:\[[^\]]*\]\s*)?\{([^{}]*)\}"
        )
        for source_path in source_files:
            source_text = self._latex_text_for_path(source_path)
            # Keep the public extractor as the authority for which keys belong
            # to a TeX source; this scan only supplies the source location.
            if key not in set(LaTeXSupport.extract_bibtex_keys(source_text, source_path)):
                continue
            for match in resource_re.finditer(_latex_scan_text(source_text)):
                for name in match.group(1).split(","):
                    resource = Path(name.strip())
                    candidates = [source_path.parent / resource]
                    if resource.suffix.lower() != ".bib":
                        candidates.append((source_path.parent / resource).with_suffix(".bib"))
                    for candidate in candidates:
                        try:
                            candidate = candidate.resolve()
                        except OSError:
                            continue
                        if candidate.is_file() and candidate not in seen:
                            seen.add(candidate)
                            bib_files.append(candidate)
                            break

        entry_re = re.compile(r"@[A-Za-z][\w-]*\s*[({]\s*([^,\s]+)\s*,")
        for bib_path in bib_files:
            bib_text = self._latex_text_for_path(bib_path)
            for match in entry_re.finditer(_latex_scan_text(bib_text)):
                if match.group(1) != key:
                    continue
                position = match.start(1)
                line = bib_text.count("\n", 0, position)
                line_start = bib_text.rfind("\n", 0, position)
                return bib_path, line, position - line_start - 1
        return None

    def _latex_semantic_info(
        self, token: dict
    ) -> tuple[Optional[Path], Optional[int], Optional[int], str] | None:
        """Resolve a token and create plain HTML-safe hover text."""
        key = token["key"]
        safe_key = _html_escape(key)
        if token["kind"] in {"label", "reference"}:
            from editor.latex_support import LaTeXSupport
            analysis = LaTeXSupport.analyze_label_references(
                self.text(), self.file_path
            )
            target = next((item for item in analysis["definitions"]
                           if item["key"] == key), None)
            if target is None:
                return None, None, None, f"<b>Label:</b> {safe_key}<br>Non definita"
            target_path = target.get("file")
            location = f"{target_path.name}: {target['line'] + 1}" if target_path else (
                f"riga {target['line'] + 1}"
            )
            description = f"<b>Label:</b> {safe_key}<br>{_html_escape(location)}"
            return target_path, target["line"], target["column"], description

        if token["kind"] == "citation":
            target = self._bibtex_target(key)
            if target is None:
                return None, None, None, f"<b>Citation:</b> {safe_key}<br>Non trovata"
            target_path, line, column = target
            description = (
                f"<b>Citation:</b> {safe_key}<br>"
                f"{_html_escape(target_path.name)}: {line + 1}"
            )
            return target_path, line, column, description
        return None

    def _navigate_latex_semantic(self, token: dict) -> bool:
        """Open and focus a local LaTeX label or BibTeX entry."""
        info = self._latex_semantic_info(token)
        if info is None:
            return False
        target_path, line, column, _description = info
        if line is None or column is None:
            return False
        if target_path is None or self._same_path(target_path, self.file_path):
            self.setCursorPosition(line, column)
            self.ensureLineVisible(line)
            self.SendScintilla(QsciScintilla.SCI_SCROLLCARET)
            return True

        window = self.window()
        tab_manager = getattr(window, "_tab_manager", None)
        if tab_manager is None:
            return False

        def find_editor():
            for editor in (tab_manager.all_editors()
                           if hasattr(tab_manager, "all_editors") else []):
                if self._same_path(getattr(editor, "file_path", None), target_path):
                    return editor
            return None

        def focus_target() -> None:
            editor = find_editor()
            if editor is None:
                return
            tab_manager.set_current_editor(editor)
            editor.setCursorPosition(line, column)
            editor.ensureLineVisible(line)
            editor.SendScintilla(QsciScintilla.SCI_SCROLLCARET)

        existing = find_editor()
        if existing is not None:
            tab_manager.set_current_editor(existing)
            loader = getattr(window, "_lazy_loaders", {}).get(existing)
            if loader is not None and hasattr(loader, "load_finished"):
                loader.load_finished.connect(focus_target)
            else:
                focus_target()
            return True

        opener = getattr(window, "open_files", None)
        if not callable(opener):
            return False
        try:
            opener([target_path])
        except (OSError, RuntimeError, ValueError):
            return False

        def prepare_target() -> None:
            editor = find_editor()
            if editor is None:
                return
            loader = getattr(window, "_lazy_loaders", {}).get(editor)
            if loader is not None and hasattr(loader, "load_finished"):
                loader.load_finished.connect(focus_target)
            else:
                focus_target()

        QTimer.singleShot(0, prepare_target)
        return True

    def _latex_documentation_target(self, position: int) -> tuple[str, str | None] | None:
        """Restituisce comando/pacchetto sotto il cursore per la documentazione."""
        language = getattr(self, "_current_language", "").lower()
        if "latex" not in language and "tex" not in language:
            return None
        line, column = self.lineIndexFromPosition(position)
        text = self.text(line)
        for match in re.finditer(r"\\usepackage(?:\[[^]]*\])?\{([^}]+)\}", text):
            if match.start(1) <= column <= match.end(1):
                package = match.group(1).split(",", 1)[0].strip()
                return package, package
        for match in re.finditer(r"\\([A-Za-z@]+)", text):
            if match.start() <= column <= match.end():
                return match.group(1), None
        return None

    @staticmethod
    def _open_latex_texdoc(target: str) -> None:
        from PyQt6.QtCore import QProcess
        if not QProcess.startDetached("texdoc", [target]):
            from core.external_open import open_url
            open_url(f"https://ctan.org/search?phrase={target}")

    @staticmethod
    def _open_latex_ctan(target: str) -> None:
        from core.external_open import open_url
        safe = re.sub(r"[^A-Za-z0-9_.+-]", "", target)
        open_url(f"https://ctan.org/pkg/{safe}" if safe else "https://ctan.org/")

    def _context_go_to_matching(self, line: int, col: int) -> None:
        """Handler della voce 'Vai alla corrispondenza' nel menu contestuale."""
        if not self.go_to_matching(line, col):
            mw = self.window()
            if hasattr(mw, "statusBar"):
                mw.statusBar().showMessage(tr("msg.no_matching_bracket"), 3000)

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
        """Ignora la parola per la sessione corrente (solo in memoria, non
        persistito): usato da "Ignora tutto" nel menu contestuale."""
        w = word.lower()
        self._spell_personal.add(w)
        if self._spell_checker:
            self._spell_checker.word_frequency.load_words([w])
        self._spell_text_hash = 0
        self._do_spell_check()

    def _spell_add_to_dictionary(self, word: str) -> None:
        """Aggiunge la parola al dizionario personale permanente: persistito
        su disco per lingua e riletto da ogni editor/sessione futura, a
        differenza di _spell_add_to_personal (solo sessione corrente)."""
        self._spell_add_to_personal(word)
        _persist_personal_word(self._spell_lang, word.lower())

    def _change_spell_lang_from_context(self, lang: str) -> None:
        """Cambia la lingua del dizionario dal context menu e aggiorna Settings."""
        self.set_spell_language(lang)
        try:
            from config.settings import Settings
            Settings.instance().set("spellcheck/language", lang)
        except Exception:
            pass

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

    def _on_user_list_selection(self, list_id: int, text: str) -> None:
        """Inserisce la voce selezionata nel testo."""
        if list_id in (2, 4, 9):
            # Chiavi BibTeX (\citep/\citet/…), file paths, temi beamer
            # — rimpiazza il prefisso parziale digitato dopo {
            self._insert_replacing_partial_and_close_brace(text)
        elif list_id == 3:
            # Ambienti LaTeX da \begin{ o \end{ (o da \begin/\end senza
            # ancora la { se il popup è partito subito dopo la parola)
            ac = getattr(self, "_autocomplete", None)
            if ac is not None and getattr(ac, "_env_popup_needs_brace", False):
                # Il popup e' partito da \be, \en, \beg... (parola ancora
                # incompleta): espande la parola parziale a "begin"/"end"
                # prima di aggiungere la { — altrimenti resterebbe \be{...}
                line, col = self.getCursorPosition()
                line_text = self.text(line)[:col]
                m = re.search(r'\\([a-zA-Z]*)$', line_text)
                if m:
                    word = m.group(1)
                    full = "begin" if "begin".startswith(word) else "end"
                    if word != full:
                        self.setSelection(line, col - len(word), line, col)
                        self.removeSelectedText()
                        self.insert(full)
                        col = col - len(word) + len(full)
                        self.setCursorPosition(line, col)
                self.insert("{")
                self.setCursorPosition(line, col + 1)
            line, col = self.getCursorPosition()
            text_before = self.text(line)[:col]
            brace_pos = text_before.rfind('{')
            cmd_before = text_before[:brace_pos] if brace_pos >= 0 else text_before
            if cmd_before.rstrip().endswith("\\end"):
                # \end{...}: nessuna coppia \begin/\end né argomenti obbligatori,
                # basta chiudere il nome dell'ambiente già digitato
                self._insert_replacing_partial_and_close_brace(text)
            else:
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
        self._hover_popup_timer.stop()
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
        # PARTE 3: RIFERIMENTI LOCALI E CITAZIONI
        # ---------------------------------------------------------
        semantic = self._latex_semantic_at_position(position)
        if semantic is not None:
            semantic_info = self._latex_semantic_info(semantic)
            if semantic_info is not None:
                self._create_html_tooltip_popup(
                    semantic_info[3], x, y
                )
                return

        # ---------------------------------------------------------
        # PARTE 4: DOCUMENTAZIONE COMANDI LaTeX
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
        self._hover_popup_timer.start()

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
        self._hover_popup_timer.start()


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

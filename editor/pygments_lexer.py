"""
editor/pygments_lexer.py — QsciLexerCustom basato su Pygments.
Usato come fallback per linguaggi non supportati nativamente da QScintilla
(Go, Rust, PHP, Swift, Kotlin, Scala, Dart, R, ...).

Per Go, Rust, Kotlin, Swift, Scala e Dart, se l'estensione opzionale
``core._code_native`` è compilata, lo styling è fatto in C++ (60-140x più
veloce di Pygments, con gli stessi colori) e applicato con un'unica
SCI_SETSTYLINGEX. Senza l'estensione si usa Pygments come sempre.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.Qsci import QsciLexerCustom
from PyQt6.QtGui import QColor, QFont

try:  # acceleratore opzionale, vedi native/code_native.cpp
    from core import _code_native
except ImportError:  # pragma: no cover - installazioni senza compilatore
    _code_native = None

NATIVE_LANGUAGES: frozenset[str] = (
    frozenset(_code_native.languages()) if _code_native is not None else frozenset()
)

if TYPE_CHECKING:
    pass

# ─── Stili ────────────────────────────────────────────────────────────────────

S_DEFAULT   = 0
S_KEYWORD   = 1
S_KWTYPE    = 2   # keyword di tipo (int, str, bool, ...)
S_BUILTIN   = 3   # nomi built-in
S_COMMENT   = 4
S_DOCSTR    = 5   # docstring / commento multiriga
S_STRING    = 6
S_NUMBER    = 7
S_OPERATOR  = 8
S_FUNCTION  = 9
S_CLASS     = 10
S_DECORATOR = 11
S_NAMESPACE = 12
S_PREPROC   = 13
S_ESCAPE    = 14  # caratteri di escape nelle stringhe
S_ERROR     = 15
# Commento di riga il cui token include il newline (Rust, Scala, PHP...).
# Stessi colori di S_COMMENT, ma distinto perché dopo di lui il lexer è di
# nuovo nello stato iniziale: è un punto di ripartenza sicuro, mentre un
# newline dentro un commento multiriga no.
S_COMMENT_LINE = 16

_STYLE_NAMES = {
    S_DEFAULT:   "Default",
    S_KEYWORD:   "Keyword",
    S_KWTYPE:    "Type",
    S_BUILTIN:   "Builtin",
    S_COMMENT:   "Comment",
    S_DOCSTR:    "Docstring",
    S_STRING:    "String",
    S_NUMBER:    "Number",
    S_OPERATOR:  "Operator",
    S_FUNCTION:  "Function",
    S_CLASS:     "Class",
    S_DECORATOR: "Decorator",
    S_NAMESPACE: "Namespace",
    S_PREPROC:   "Preprocessor",
    S_ESCAPE:    "Escape",
    S_ERROR:     "Error",
    S_COMMENT_LINE: "Line comment",
}

# Mappa stile → chiave token nel dizionario tema
_STYLE_TO_TOKEN_KEY = {
    S_DEFAULT:   "default",
    S_KEYWORD:   "keyword",
    S_KWTYPE:    "keyword2",
    S_BUILTIN:   "identifier",
    S_COMMENT:   "comment",
    S_DOCSTR:    "comment_block",
    S_STRING:    "string",
    S_NUMBER:    "number",
    S_OPERATOR:  "operator",
    S_FUNCTION:  "function",
    S_CLASS:     "class_name",
    S_DECORATOR: "decorator",
    S_NAMESPACE: "keyword",
    S_PREPROC:   "preprocessor",
    S_ESCAPE:    "string_raw",
    S_ERROR:     "unclosed_string",
    S_COMMENT_LINE: "comment",
}


# Cache tipo-token → stile. I tipi di token Pygments sono singleton, quindi
# la classificazione (una catena di ``ttype in X`` che risale la gerarchia)
# va fatta una sola volta per tipo: senza cache era oltre metà del tempo di
# styleText, con decine di milioni di chiamate a ``_TokenType.__contains__``.
_STYLE_CACHE: dict[object, int] = {}


def _classify_token(ttype) -> int:
    from pygments.token import Comment, Error, Keyword, Name, Number, Operator, String
    if ttype in Keyword.Type:
        return S_KWTYPE
    if ttype in Keyword:
        return S_KEYWORD
    if ttype in Comment.Preproc or ttype in Comment.PreprocFile:
        return S_PREPROC
    if ttype in Comment.Single:
        return S_COMMENT_LINE
    if ttype in Comment:
        return S_COMMENT
    if ttype in String.Doc:
        return S_DOCSTR
    if ttype in String.Escape:
        return S_ESCAPE
    if ttype in String:
        return S_STRING
    if ttype in Number:
        return S_NUMBER
    if ttype in Name.Class:
        return S_CLASS
    if ttype in Name.Function:
        return S_FUNCTION
    if ttype in Name.Decorator:
        return S_DECORATOR
    if ttype in Name.Namespace:
        return S_NAMESPACE
    if ttype in Name.Builtin:
        return S_BUILTIN
    if ttype in Operator:
        return S_OPERATOR
    if ttype is Error:
        return S_ERROR
    return S_DEFAULT


def _token_to_style(ttype) -> int:
    """Mappa un token Pygments al numero di stile QScintilla."""
    style = _STYLE_CACHE.get(ttype)
    if style is None:
        style = _STYLE_CACHE[ttype] = _classify_token(ttype)
    return style


class PygmentsLexer(QsciLexerCustom):
    """
    Lexer QScintilla generico basato su Pygments.
    Accetta qualsiasi alias Pygments valido (es. "go", "rust", "php").
    """

    def __init__(self, alias: str, lang_name: str, parent=None):
        super().__init__(parent)
        self._alias = alias
        self._lang_name = lang_name
        self._pygments_lexer = None
        # PHP: fuori da <?php ... ?> il testo è HTML. Ripartendo da metà
        # documento dentro un blocco PHP serve un lexer che parta già in
        # modalità codice.
        self._inline_lexer = None
        # Disattivabile (test, confronto con Pygments): resta comunque
        # necessario Pygments per ``_pygments_lexer``, usato come fallback.
        self._native_enabled = alias in NATIVE_LANGUAGES
        self._load_lexer()

    # Pygments non è incrementale e ristilare tutto il documento a ogni tasto
    # costava 60+ ms già su file da 30 KB. styleText riparte quindi da un
    # inizio riga "sicuro" vicino alla modifica e stila solo la finestra che
    # Scintilla chiede (di solito l'area visibile); il resto viene stilato
    # quando serve, perché Scintilla tiene traccia di endStyled.
    #
    # Una riga è un punto di ripartenza sicuro se il newline che la precede
    # ha stile default o di commento di riga: non siamo dentro un commento,
    # una stringa o un docstring multiriga, e il lexer può ripartire dallo
    # stato iniziale.
    _SAFE_RESTART_STYLES = frozenset({S_DEFAULT, S_COMMENT_LINE})
    # Limite alla risalita in cerca di un punto sicuro (commenti enormi).
    _MAX_RESTART_BACKTRACK_BYTES = 256 * 1024
    # Testo letto oltre la fine della finestra: un commento o una stringa
    # multiriga che inizia nella finestra viene riconosciuto fino alla
    # chiusura invece di essere spezzato (e mal colorato) al bordo.
    _LOOKAHEAD_BYTES = 256 * 1024

    def _load_lexer(self) -> None:
        try:
            from pygments.lexers import get_lexer_by_name
            options = dict(stripnl=False, stripall=False, ensurenl=False)
            self._pygments_lexer = get_lexer_by_name(self._alias, **options)
            if self._alias == "php":
                self._inline_lexer = get_lexer_by_name(
                    self._alias, startinline=True, **options)
        except Exception:
            self._pygments_lexer = None
            self._inline_lexer = None

    # ── Interfaccia QsciLexerCustom ───────────────────────────────────────────

    def language(self) -> str:
        return self._lang_name

    def description(self, style: int) -> str:
        return _STYLE_NAMES.get(style, "")

    def styleText(self, start: int, end: int) -> None:
        if not self._pygments_lexer:
            return
        editor = self.parent()
        if not editor:
            return
        try:
            total = editor.SendScintilla(editor.SCI_GETLENGTH)
        except Exception:
            return
        if total <= 0 or start >= total:
            return
        end = min(max(end, start + 1), total)
        restart = self._restart_position(editor, start)
        limit = self._line_end_after(editor, end, total)
        if limit <= restart:
            return
        read_end = min(total, limit + self._LOOKAHEAD_BYTES)
        source_bytes = self._read_range_bytes(editor, restart, read_end)
        if not source_bytes:
            return
        if self._native_enabled:
            styles = _code_native.style(self._alias, source_bytes, limit - restart)
            self.startStyling(restart)
            editor.SendScintilla(editor.SCI_SETSTYLINGEX, len(styles), styles)
            return
        lexer = self._lexer_for(editor, restart)
        self.startStyling(restart)
        for width, style in self._style_runs(lexer, source_bytes, limit - restart):
            self.setStyling(width, style)

    @staticmethod
    def _style_runs(lexer, source_bytes: bytes, span: int):
        """Genera ``(larghezza_in_byte, stile)`` per i primi ``span`` byte.

        Usa ``get_tokens_unprocessed`` invece di ``pygments.lex``: lex()
        pre-elabora il testo (``\r\n`` → ``\n``, tab, newline finale), e
        su file CRLF ogni riga perdeva un byte, facendo slittare gli stili.
        Gli indici restituiti si riferiscono al testo così com'è.
        """
        source = source_bytes.decode("utf-8", "replace")
        if not source.endswith("\n"):
            # Molte regex Pygments (commenti di riga) si aspettano il newline
            # finale che lex() aggiungeva con ensurenl; l'eccedenza è tagliata.
            source += "\n"
        ascii_only = source_bytes.isascii()
        cache_get = _STYLE_CACHE.get
        pos_b = 0   # byte già stilati
        pos_c = 0   # carattere corrispondente a pos_b
        for index, ttype, value in lexer.get_tokens_unprocessed(source):
            if pos_b >= span:
                break
            if index > pos_c:
                gap = source[pos_c:index]
                width = len(gap) if ascii_only else len(gap.encode("utf-8"))
                width = min(width, span - pos_b)
                yield width, S_DEFAULT
                pos_b += width
                pos_c = index
                if pos_b >= span:
                    break
            if not value:
                continue
            width = len(value) if ascii_only else len(value.encode("utf-8"))
            width = min(width, span - pos_b)
            style = cache_get(ttype)
            if style is None:
                style = _token_to_style(ttype)
            yield width, style
            pos_b += width
            pos_c = index + len(value)
        if pos_b < span:
            yield span - pos_b, S_DEFAULT

    def _restart_position(self, editor, start: int) -> int:
        """Inizio riga sicuro a monte di ``start`` da cui rilanciare Pygments."""
        send = editor.SendScintilla
        line = send(editor.SCI_LINEFROMPOSITION, start)
        pos = send(editor.SCI_POSITIONFROMLINE, line)
        floor = max(0, start - self._MAX_RESTART_BACKTRACK_BYTES)
        while pos > floor:
            if send(editor.SCI_GETSTYLEAT, pos - 1) in self._SAFE_RESTART_STYLES:
                return pos
            line -= 1
            pos = send(editor.SCI_POSITIONFROMLINE, line)
        # Nessun punto sicuro entro il limite: ripartiamo dal bordo (o da 0).
        return max(pos, 0)

    @staticmethod
    def _line_end_after(editor, end: int, total: int) -> int:
        """Estende ``end`` alla fine della sua riga (newline incluso)."""
        send = editor.SendScintilla
        line = send(editor.SCI_LINEFROMPOSITION, end)
        if send(editor.SCI_POSITIONFROMLINE, line) == end:
            return end
        nxt = send(editor.SCI_POSITIONFROMLINE, line + 1)
        return total if nxt < 0 or nxt > total else nxt

    def _lexer_for(self, editor, restart: int):
        """Per PHP, sceglie il lexer giusto per un punto interno al documento."""
        if self._inline_lexer is None or restart == 0:
            return self._pygments_lexer
        probe_start = max(0, restart - self._MAX_RESTART_BACKTRACK_BYTES)
        before = self._read_range_bytes(editor, probe_start, restart)
        opened = max(before.rfind(b"<?php"), before.rfind(b"<?="),
                     before.rfind(b"<?\n"), before.rfind(b"<? "))
        closed = before.rfind(b"?>")
        return self._inline_lexer if opened > closed else self._pygments_lexer

    @staticmethod
    def _read_range_bytes(editor, start: int, end: int) -> bytes:
        """Legge ``[start, end)`` byte dal documento senza copiarlo tutto."""
        if end <= start:
            return b""
        try:
            buf = bytearray(end - start + 1)
            editor.SendScintilla(editor.SCI_GETTEXTRANGE, start, end, buf)
            return bytes(buf[:end - start])
        except Exception:
            return b""

    # ── Colori dal tema ───────────────────────────────────────────────────────

    def set_colors(self, tokens: dict, font_family: str, font_size: int,
                   bg: QColor, fg: QColor) -> None:
        """Applica i colori del tema agli stili del lexer."""
        def_tok = tokens.get("default", {})
        def_fg = QColor(def_tok.get("fg", fg.name()))
        def_bg = QColor(def_tok.get("bg", bg.name()))

        base_font = QFont(font_family, font_size)
        base_font.setFixedPitch(True)

        self.setDefaultFont(base_font)
        self.setDefaultPaper(bg)
        self.setDefaultColor(fg)

        for style_num, tok_key in _STYLE_TO_TOKEN_KEY.items():
            tok = tokens.get(tok_key, {})
            sfg = QColor(tok["fg"]) if "fg" in tok else def_fg
            sbg = QColor(tok.get("bg", def_bg.name()))
            f = QFont(font_family, font_size)
            f.setFixedPitch(True)
            if tok.get("bold"):
                f.setBold(True)
            if tok.get("italic"):
                f.setItalic(True)
            self.setColor(sfg, style_num)
            self.setPaper(sbg, style_num)
            self.setFont(f, style_num)

"""
editor/pygments_lexer.py — QsciLexerCustom basato su Pygments.
Usato come fallback per linguaggi non supportati nativamente da QScintilla
(Go, Rust, PHP, Swift, Kotlin, Scala, Dart, R, ...).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.Qsci import QsciLexerCustom
from PyQt6.QtGui import QColor, QFont

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

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
}


def _token_to_style(ttype) -> int:
    """Mappa un token Pygments al numero di stile QScintilla."""
    from pygments.token import Keyword, Name, String, Number, Operator, Comment, Error
    if ttype in Keyword.Type:
        return S_KWTYPE
    if ttype in Keyword:
        return S_KEYWORD
    if ttype in Comment.Preproc or ttype in Comment.PreprocFile:
        return S_PREPROC
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
        self._last_text_id: int = -1  # evita ri-tokenizzazione inutile
        self._load_lexer()

    _LARGE_DOCUMENT_BYTES = 500_000
    _INCREMENTAL_STYLE_BYTES = 32_000

    def _load_lexer(self) -> None:
        try:
            from pygments.lexers import get_lexer_by_name
            self._pygments_lexer = get_lexer_by_name(
                self._alias, stripnl=False, stripall=False, ensurenl=False
            )
        except Exception:
            self._pygments_lexer = None

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
        text = editor.text()
        if not text:
            return

        encoded = text.encode("utf-8")
        if len(encoded) >= self._LARGE_DOCUMENT_BYTES:
            self._style_incremental(encoded, start, end)
            return

        # Salta se il testo non è cambiato dall'ultima tokenizzazione
        tid = id(text) ^ hash(text)
        if tid == self._last_text_id:
            return
        self._last_text_id = tid

        from pygments import lex

        # Ri-stila sempre dall'inizio: Pygments è context-sensitive
        self.startStyling(0)
        for ttype, value in lex(text, self._pygments_lexer):
            self.setStyling(len(value.encode("utf-8")), _token_to_style(ttype))

    def _style_incremental(self, encoded: bytes, start: int, end: int) -> None:
        """Style a bounded range for large files instead of retokenizing all text.

        Pygments is context-sensitive, so the scan starts at the previous line
        boundary. This keeps typing responsive while retaining useful context
        for multiline constructs in the common case.
        """
        if start >= len(encoded):
            return
        context_start = encoded.rfind(b"\n", 0, start) + 1
        limit = min(len(encoded), max(start + 1, end),
                    context_start + self._INCREMENTAL_STYLE_BYTES)
        if limit <= context_start:
            return
        source = encoded[context_start:limit].decode("utf-8", "replace")
        from pygments import lex

        self.startStyling(context_start)
        styled = 0
        for ttype, value in lex(source, self._pygments_lexer):
            width = len(value.encode("utf-8"))
            if width <= 0:
                continue
            remaining = limit - context_start - styled
            if remaining <= 0:
                break
            width = min(width, remaining)
            self.setStyling(width, _token_to_style(ttype))
            styled += width

    # ── Colori dal tema ───────────────────────────────────────────────────────

    def set_colors(self, tokens: dict, font_family: str, font_size: int,
                   bg: QColor, fg: QColor) -> None:
        """Applica i colori del tema ai 16 stili del lexer."""
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

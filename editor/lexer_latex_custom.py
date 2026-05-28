"""
editor/lexer_latex_custom.py — Custom LaTeX lexer stile TeXstudio.

Stili:
  S_DEFAULT   testo normale
  S_COMMAND   \\comando generico          → "command"   (ciano bold)
  S_STRUCTURE \\begin \\end \\section …   → "environment" (viola/magenta)
  S_REFERENCE \\label \\cite \\ref …      → "math_command" (teal)
  S_COMMENT   % commento fino a EOL       → "comment"   (verde corsivo)
  S_MATH      $…$ o $$…$$                 → "math"      (oro)
  S_BRACE     { }                         → "operator"
  S_OPTION    contenuto [...]             → "string2"
  S_REF_ARG   {contenuto} dopo ref-cmd   → "identifier" (evidenziato)

Implementazione note:
- styleText lavora in bytes UTF-8 (QScintilla usa byte offset, non char offset).
- I token vengono accumulati in un bytearray e applicati con una singola
  chiamata SCI_SETSTYLINGEX, riducendo le chiamate Python→C da ~181K a 1
  per un documento da 2 MB (da ~540ms a ~1ms di bridge overhead).
- I bytes UTF-8 multi-byte (> 127) non coincidono mai con caratteri speciali
  LaTeX (tutti ASCII), quindi la scansione in bytes è corretta.
"""
from __future__ import annotations

import re
from PyQt6.Qsci import QsciLexerCustom

# ── Numeri di stile ───────────────────────────────────────────────────────────

S_DEFAULT   = 0
S_COMMAND   = 1
S_STRUCTURE = 2
S_REFERENCE = 3
S_COMMENT   = 4
S_MATH      = 5
S_BRACE     = 6
S_OPTION    = 7
S_REF_ARG   = 8

_STYLE_NAMES = {
    S_DEFAULT:   "Default",
    S_COMMAND:   "Command",
    S_STRUCTURE: "Structure",
    S_REFERENCE: "Reference",
    S_COMMENT:   "Comment",
    S_MATH:      "Math",
    S_BRACE:     "Brace",
    S_OPTION:    "Option",
    S_REF_ARG:   "RefArg",
}

# Mappa stile → chiave token nel dizionario tema
STYLE_TOKEN = {
    S_DEFAULT:   "default",
    S_COMMAND:   "command",
    S_STRUCTURE: "environment",
    S_REFERENCE: "math_command",
    S_COMMENT:   "comment",
    S_MATH:      "math",
    S_BRACE:     "operator",
    S_OPTION:    "string2",
    S_REF_ARG:   "identifier",
}

# ── Insiemi di comandi ────────────────────────────────────────────────────────

_STRUCTURE_CMDS = frozenset([
    'begin', 'end',
    'chapter', 'section', 'subsection', 'subsubsection',
    'paragraph', 'subparagraph', 'part',
    'documentclass', 'usepackage', 'RequirePackage',
    'input', 'include', 'subfile', 'import',
    'newcommand', 'renewcommand', 'providecommand',
    'newenvironment', 'renewenvironment',
    'title', 'author', 'date', 'maketitle',
    'appendix', 'frontmatter', 'mainmatter', 'backmatter',
])

_REFERENCE_CMDS = frozenset([
    'label', 'ref', 'eqref', 'pageref', 'nameref', 'autoref',
    'cref', 'Cref', 'vref', 'fullref', 'hyperref',
    'cite', 'citep', 'citet', 'citealt', 'citealp', 'citenum',
    'nocite', 'footcite', 'parencite', 'textcite',
    'index', 'glossary', 'nomenclature',
    'href', 'url', 'nolinkurl',
    'footnote', 'footnotemark', 'footnotetext',
])

# Byte values ASCII dei caratteri speciali LaTeX (< 128 → mai in byte UTF-8 multi-byte)
_B_PERCENT   = ord('%')
_B_BACKSLASH = ord('\\')
_B_DOLLAR    = ord('$')
_B_LBRACE    = ord('{')
_B_RBRACE    = ord('}')
_B_LBRACKET  = ord('[')
_B_RBRACKET  = ord(']')
_B_NEWLINE   = ord('\n')

_RE_SPECIAL_BYTES = re.compile(rb'[%\\${}[\]]')


class LaTeXLexer(QsciLexerCustom):
    """Custom LaTeX lexer con highlighting stile TeXstudio."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bytes_cache: bytes | None = None
        # Invalida la cache solo quando il testo cambia.
        # Durante scroll/navigazione (testo invariato) la cache è riusata.
        if parent is not None:
            parent.textChanged.connect(self._on_text_changed)

    def _on_text_changed(self) -> None:
        self._bytes_cache = None

    def language(self) -> str:
        return "LaTeX"

    def description(self, style: int) -> str:
        return _STYLE_NAMES.get(style, "")

    # ── Motore di highlighting ────────────────────────────────────────────────

    def styleText(self, start: int, end: int) -> None:
        # Ottieni bytes (con cache): evita encode O(n) ad ogni chiamata.
        if self._bytes_cache is None:
            self._bytes_cache = self.parent().text().encode('utf-8')
        text_b = self._bytes_cache
        tlen = len(text_b)
        if tlen == 0 or start >= tlen:
            return

        # Ripartenza sicura: inizio della riga che contiene start.
        # % e $ inline sono sempre su riga singola → ripartire dall'inizio riga è corretto.
        nl = text_b.rfind(b'\n', 0, start)
        safe = 0 if nl == -1 else nl + 1
        end = min(end, tlen)
        if safe >= end:
            return

        region_len = end - safe
        # Bytearray di stili: ogni byte = stile per il byte corrispondente in text_b[safe:end].
        # S_DEFAULT = 0 = valore iniziale → le span di testo normale non richiedono fill.
        styles = bytearray(region_len)

        pos = safe
        last_cmd = ""

        while pos < end:
            b = text_b[pos]
            idx = pos - safe

            # ── % commento ────────────────────────────────────────────────────
            if b == _B_PERCENT:
                eol = text_b.find(b'\n', pos)
                n = (min(eol, end) - pos) if eol != -1 else (end - pos)
                if n > 0:
                    styles[idx:idx + n] = bytes([S_COMMENT]) * n
                pos += n if n > 0 else 1
                last_cmd = ""

            # ── \ comando ─────────────────────────────────────────────────────
            elif b == _B_BACKSLASH:
                i = pos + 1
                # Nomi comando LaTeX: solo ASCII (a-zA-Z @).
                # Il check < 128 evita che byte UTF-8 multi-byte vengano trattati come lettere.
                if i < tlen and text_b[i] < 128 and (
                    chr(text_b[i]).isalpha() or chr(text_b[i]) == '@'
                ):
                    while i < tlen and text_b[i] < 128 and (
                        chr(text_b[i]).isalpha() or chr(text_b[i]) in ('@', '*')
                    ):
                        i += 1
                    cmd = text_b[pos + 1:i].decode('ascii')
                    last_cmd = cmd
                    if cmd in _STRUCTURE_CMDS:
                        sty = S_STRUCTURE
                    elif cmd in _REFERENCE_CMDS:
                        sty = S_REFERENCE
                    else:
                        sty = S_COMMAND
                    n = min(i, end) - pos
                    if n > 0:
                        styles[idx:idx + n] = bytes([sty]) * n
                    pos = min(i, end)
                else:
                    # \\ \{ \} \$ \[ \] ecc. — simbolo escape singolo
                    n = min(2 if i < tlen else 1, end - pos)
                    if n > 0:
                        styles[idx:idx + n] = bytes([S_COMMAND]) * n
                    pos += n if n > 0 else 1
                    last_cmd = ""

            # ── $ math ────────────────────────────────────────────────────────
            elif b == _B_DOLLAR:
                if pos + 1 < tlen and text_b[pos + 1] == _B_DOLLAR:
                    end_m = text_b.find(b'$$', pos + 2)
                    n = (end_m + 2 - pos) if end_m != -1 else (tlen - pos)
                else:
                    i = pos + 1
                    while i < tlen and text_b[i] != _B_DOLLAR and text_b[i] != _B_NEWLINE:
                        if text_b[i] == _B_BACKSLASH:
                            i += 1
                        i += 1
                    n = (i + 1 - pos) if (i < tlen and text_b[i] == _B_DOLLAR) else 1
                n = min(n, end - pos)
                if n > 0:
                    styles[idx:idx + n] = bytes([S_MATH]) * n
                pos += n if n > 0 else 1
                last_cmd = ""

            # ── { graffa aperta ───────────────────────────────────────────────
            elif b == _B_LBRACE:
                styles[idx] = S_BRACE
                pos += 1
                # Colora l'argomento dopo \label \cite \ref ecc.
                if last_cmd in _REFERENCE_CMDS:
                    i, depth = pos, 1
                    while i < tlen and depth > 0:
                        bc = text_b[i]
                        if bc == _B_LBRACE:
                            depth += 1
                        elif bc == _B_RBRACE:
                            depth -= 1
                        elif bc == _B_BACKSLASH and i + 1 < tlen:
                            i += 1
                        i += 1
                    content = min(
                        (i - pos - 1) if depth == 0 else (i - pos),
                        end - pos
                    )
                    if content > 0:
                        ci = pos - safe
                        styles[ci:ci + content] = bytes([S_REF_ARG]) * content
                        pos += content
                    # la } di chiusura viene gestita al giro successivo
                last_cmd = ""

            # ── } graffa chiusa ───────────────────────────────────────────────
            elif b == _B_RBRACE:
                styles[idx] = S_BRACE
                pos += 1

            # ── [ opzione ─────────────────────────────────────────────────────
            elif b == _B_LBRACKET:
                styles[idx] = S_BRACE
                pos += 1
                # Cerca ] sulla stessa riga (opzioni LaTeX non span multi-riga)
                eol = text_b.find(b'\n', pos)
                line_end = eol if eol != -1 else tlen
                bracket_end = text_b.find(b']', pos, line_end)
                if bracket_end != -1:
                    content = min(bracket_end - pos, end - pos)
                    if content > 0:
                        ci = pos - safe
                        styles[ci:ci + content] = bytes([S_OPTION]) * content
                        pos += content
                # ] viene gestito al giro successivo

            # ── ] chiude opzione ──────────────────────────────────────────────
            elif b == _B_RBRACKET:
                styles[idx] = S_BRACE
                pos += 1

            # ── testo normale (incluse sequenze UTF-8 multi-byte) ─────────────
            else:
                # S_DEFAULT = 0: bytearray già a 0, basta avanzare pos.
                m = _RE_SPECIAL_BYTES.search(text_b, pos, end)
                next_pos = m.start() if m else end
                if next_pos <= pos:
                    next_pos = pos + 1
                pos = next_pos

        # Applica tutti gli stili con UNA SOLA chiamata Qt bridge
        # invece di ~181K chiamate setStyling() separate.
        self.startStyling(safe)
        self.parent().SendScintilla(
            self.parent().SCI_SETSTYLINGEX,
            region_len,
            bytes(styles),
        )

    # ── Applicazione tema ─────────────────────────────────────────────────────

    def set_colors(self, tokens: dict, font_family: str, font_size: int,
                   editor_bg, editor_fg) -> None:
        """Applica i colori dal dizionario tema ai propri stili."""
        from PyQt6.QtGui import QColor, QFont

        bg_name = editor_bg.name() if hasattr(editor_bg, 'name') else str(editor_bg)

        base = QFont(font_family, font_size)
        base.setFixedPitch(True)

        # Blocca i segnali per evitare che ogni setColor/setPaper/setFont
        # triggeri una recolourize() completa del documento (~75 chiamate
        # SCI_COLOURISE(0,-1) altrimenti). Un singolo update() alla fine
        # è sufficiente per ridisegnare con i nuovi colori.
        self.blockSignals(True)
        try:
            for sn in range(16):
                self.setColor(editor_fg, sn)
                self.setPaper(editor_bg, sn)
                self.setFont(base, sn)

            for style_num, tok_key in STYLE_TOKEN.items():
                tok = tokens.get(tok_key, {})
                if not tok:
                    continue
                fg = QColor(tok["fg"]) if "fg" in tok else editor_fg
                bg = QColor(tok.get("bg", bg_name))
                f = QFont(font_family, font_size)
                f.setFixedPitch(True)
                f.setBold(tok.get("bold", False))
                f.setItalic(tok.get("italic", False))
                self.setColor(fg, style_num)
                self.setPaper(bg, style_num)
                self.setFont(f, style_num)
        finally:
            self.blockSignals(False)

        # Un solo repaint per applicare i nuovi colori
        if self.parent():
            self.parent().update()

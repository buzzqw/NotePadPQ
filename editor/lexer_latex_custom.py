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

NOTA: styleText lavora interamente su bytes UTF-8 perché QScintilla passa
start/end come byte offset, non come char offset della stringa Python.
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

# Mappa stile → chiave token nel dizionario tema (tutti i temi li hanno già)
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

# Byte values dei caratteri speciali LaTeX (tutti ASCII → safe in UTF-8)
_B_PERCENT   = ord('%')
_B_BACKSLASH = ord('\\')
_B_DOLLAR    = ord('$')
_B_LBRACE    = ord('{')
_B_RBRACE    = ord('}')
_B_LBRACKET  = ord('[')
_B_RBRACKET  = ord(']')
_B_NEWLINE   = ord('\n')

# Tutti i caratteri speciali sono ASCII (< 128), quindi nei byte UTF-8 non
# compaiono mai come parte di sequenze multi-byte (che usano byte 0x80-0xFF).
_RE_SPECIAL_BYTES = re.compile(rb'[%\\${}[\]]')


class LaTeXLexer(QsciLexerCustom):
    """Custom LaTeX lexer con highlighting stile TeXstudio."""

    def __init__(self, parent=None):
        super().__init__(parent)

    def language(self) -> str:
        return "LaTeX"

    def description(self, style: int) -> str:
        return _STYLE_NAMES.get(style, "")

    # ── Motore di highlighting ────────────────────────────────────────────────

    def styleText(self, start: int, end: int) -> None:
        # QScintilla passa start/end come byte offset nel testo UTF-8 interno.
        # Codifichiamo il testo in UTF-8 e lavoriamo esclusivamente in bytes
        # per mantenere i conteggi allineati con quelli di QScintilla.
        text_b: bytes = self.parent().text().encode('utf-8')
        tlen = len(text_b)
        if tlen == 0 or start >= tlen:
            return

        # Ripartenza sicura: inizio della riga che contiene start (in byte).
        # Commenti (%) e math inline ($) sono sempre su riga singola,
        # quindi ripartire dall'inizio riga è sempre corretto.
        nl = text_b.rfind(b'\n', 0, start)
        safe = 0 if nl == -1 else nl + 1

        self.startStyling(safe)
        pos = safe
        last_cmd = ""  # ultimo comando visto (per colorare l'argomento dopo \ref_cmd{)

        while pos < end:
            b = text_b[pos]

            # ── % commento ────────────────────────────────────────────────────
            if b == _B_PERCENT:
                eol = text_b.find(b'\n', pos)
                n = (eol - pos) if eol != -1 else (tlen - pos)
                self.setStyling(n, S_COMMENT)
                pos += n
                last_cmd = ""

            # ── \ comando ─────────────────────────────────────────────────────
            elif b == _B_BACKSLASH:
                i = pos + 1
                # I nomi dei comandi LaTeX sono solo ASCII (a-zA-Z @).
                # Il controllo < 128 evita che byte UTF-8 multi-byte (≥ 0x80)
                # vengano erroneamente interpretati come lettere di comando.
                if i < tlen and text_b[i] < 128 and (chr(text_b[i]).isalpha() or chr(text_b[i]) == '@'):
                    while i < tlen and text_b[i] < 128 and (chr(text_b[i]).isalpha() or chr(text_b[i]) in ('@', '*')):
                        i += 1
                    cmd = text_b[pos + 1:i].decode('ascii')
                    last_cmd = cmd
                    if cmd in _STRUCTURE_CMDS:
                        style = S_STRUCTURE
                    elif cmd in _REFERENCE_CMDS:
                        style = S_REFERENCE
                    else:
                        style = S_COMMAND
                    self.setStyling(i - pos, style)
                    pos = i
                else:
                    # \\ \{ \} \$ \[ \] ecc. — simbolo di escape singolo
                    n = 2 if i < tlen else 1
                    self.setStyling(n, S_COMMAND)
                    pos += n
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
                self.setStyling(n, S_MATH)
                pos += n
                last_cmd = ""

            # ── { graffa aperta ───────────────────────────────────────────────
            elif b == _B_LBRACE:
                self.setStyling(1, S_BRACE)
                pos += 1
                # Colora il contenuto in giallo dopo \label \cite \ref ecc.
                if last_cmd in _REFERENCE_CMDS:
                    i, depth = pos, 1
                    while i < tlen and depth > 0:
                        bc = text_b[i]
                        if   bc == _B_LBRACE:    depth += 1
                        elif bc == _B_RBRACE:    depth -= 1
                        elif bc == _B_BACKSLASH and i + 1 < tlen: i += 1
                        i += 1
                    content = (i - pos - 1) if depth == 0 else (i - pos)
                    if content > 0:
                        self.setStyling(content, S_REF_ARG)
                        pos += content
                    # la } di chiusura viene gestita al giro successivo
                last_cmd = ""

            # ── } graffa chiusa ───────────────────────────────────────────────
            elif b == _B_RBRACE:
                self.setStyling(1, S_BRACE)
                pos += 1

            # ── [ opzione ─────────────────────────────────────────────────────
            elif b == _B_LBRACKET:
                self.setStyling(1, S_BRACE)
                pos += 1
                # Cerca il ] di chiusura sulla stessa riga (opzioni LaTeX non span)
                eol = text_b.find(b'\n', pos)
                line_end = eol if eol != -1 else tlen
                bracket_end = text_b.find(b']', pos, line_end)
                if bracket_end != -1:
                    content = bracket_end - pos
                    if content > 0:
                        self.setStyling(content, S_OPTION)
                        pos += content
                    # ] viene gestito al giro successivo

            # ── ] chiude opzione ──────────────────────────────────────────────
            elif b == _B_RBRACKET:
                self.setStyling(1, S_BRACE)
                pos += 1

            # ── testo normale (incluse sequenze UTF-8 multi-byte) ─────────────
            else:
                # I caratteri speciali sono tutti ASCII (< 128), quindi la
                # ricerca sui byte è equivalente a quella sul testo Unicode.
                m = _RE_SPECIAL_BYTES.search(text_b, pos, end)
                next_pos = m.start() if m else end
                if next_pos <= pos:
                    next_pos = pos + 1  # sicurezza: avanza almeno 1 byte
                self.setStyling(next_pos - pos, S_DEFAULT)
                pos = next_pos

    # ── Applicazione tema ─────────────────────────────────────────────────────

    def set_colors(self, tokens: dict, font_family: str, font_size: int,
                   editor_bg, editor_fg) -> None:
        """Applica i colori dal dizionario tema ai propri stili."""
        from PyQt6.QtGui import QColor, QFont
        bg_name = editor_bg.name() if hasattr(editor_bg, 'name') else str(editor_bg)

        base = QFont(font_family, font_size)
        base.setFixedPitch(True)
        # Sfondo uniforme per tutti gli stili (necessario per QsciLexerCustom)
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

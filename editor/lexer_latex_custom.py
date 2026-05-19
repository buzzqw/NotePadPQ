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

# Regex per trovare il prossimo carattere speciale (corre a velocità C)
_RE_SPECIAL = re.compile(r'[%\\${}[\]]')


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
        text: str = self.parent().text()
        tlen = len(text)
        if tlen == 0 or start >= tlen:
            return

        # Ripartenza sicura: inizio della riga che contiene start.
        # Commenti (%) e math inline ($) sono sempre su riga singola,
        # quindi ripartire dall'inizio riga è sempre corretto.
        nl = text.rfind('\n', 0, start)
        safe = 0 if nl == -1 else nl + 1

        self.startStyling(safe)
        pos = safe
        last_cmd = ""  # ultimo comando visto (per colorare l'argomento dopo \ref_cmd{)

        while pos < end:
            c = text[pos]

            # ── % commento ────────────────────────────────────────────────────
            if c == '%':
                eol = text.find('\n', pos)
                n = (eol - pos) if eol != -1 else (tlen - pos)
                self.setStyling(n, S_COMMENT)
                pos += n
                last_cmd = ""

            # ── \ comando ─────────────────────────────────────────────────────
            elif c == '\\':
                i = pos + 1
                if i < tlen and (text[i].isalpha() or text[i] == '@'):
                    while i < tlen and (text[i].isalpha() or text[i] in ('@', '*')):
                        i += 1
                    cmd = text[pos + 1:i]
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
            elif c == '$':
                if pos + 1 < tlen and text[pos + 1] == '$':
                    end_m = text.find('$$', pos + 2)
                    n = (end_m + 2 - pos) if end_m != -1 else (tlen - pos)
                else:
                    i = pos + 1
                    while i < tlen and text[i] != '$' and text[i] != '\n':
                        if text[i] == '\\':
                            i += 1
                        i += 1
                    n = (i + 1 - pos) if (i < tlen and text[i] == '$') else 1
                self.setStyling(n, S_MATH)
                pos += n
                last_cmd = ""

            # ── { graffa aperta ───────────────────────────────────────────────
            elif c == '{':
                self.setStyling(1, S_BRACE)
                pos += 1
                # Colora il contenuto in giallo dopo \label \cite \ref ecc.
                if last_cmd in _REFERENCE_CMDS:
                    i, depth = pos, 1
                    while i < tlen and depth > 0:
                        bc = text[i]
                        if   bc == '{': depth += 1
                        elif bc == '}': depth -= 1
                        elif bc == '\\' and i + 1 < tlen: i += 1
                        i += 1
                    content = (i - pos - 1) if depth == 0 else (i - pos)
                    if content > 0:
                        self.setStyling(content, S_REF_ARG)
                        pos += content
                    # la } di chiusura viene gestita al giro successivo
                last_cmd = ""

            # ── } graffa chiusa ───────────────────────────────────────────────
            elif c == '}':
                self.setStyling(1, S_BRACE)
                pos += 1

            # ── [ opzione ─────────────────────────────────────────────────────
            elif c == '[':
                self.setStyling(1, S_BRACE)
                pos += 1
                # Cerca il ] di chiusura sulla stessa riga (opzioni LaTeX non span)
                eol = text.find('\n', pos)
                line_end = eol if eol != -1 else tlen
                bracket_end = text.find(']', pos, line_end)
                if bracket_end != -1:
                    content = bracket_end - pos
                    if content > 0:
                        self.setStyling(content, S_OPTION)
                        pos += content
                    # ] viene gestito al giro successivo

            # ── ] chiude opzione ──────────────────────────────────────────────
            elif c == ']':
                self.setStyling(1, S_BRACE)
                pos += 1

            # ── testo normale ─────────────────────────────────────────────────
            else:
                # Salta velocemente al prossimo carattere speciale (regex C-speed)
                m = _RE_SPECIAL.search(text, pos, end)
                next_pos = m.start() if m else end
                self.setStyling(next_pos - pos, S_DEFAULT)
                pos = next_pos

    # ── Applicazione tema ─────────────────────────────────────────────────────

    def set_colors(self, tokens: dict, font_family: str, font_size: int,
                   editor_bg, editor_fg) -> None:
        """Applica i colori dal dizionario tema ai propri stili."""
        from PyQt6.QtGui import QColor, QFont
        bg_name = editor_bg.name() if hasattr(editor_bg, 'name') else str(editor_bg)
        fg_name = editor_fg.name() if hasattr(editor_fg, 'name') else str(editor_fg)

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

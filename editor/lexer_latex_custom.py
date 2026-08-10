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

# Bytes massimi per ogni singola chiamata styleText.
# Con SC_IDLESTYLING_TOVISIBLE, Scintilla chiama styleText per la zona visibile
# immediatamente, poi chiama di nuovo per il resto all'idle (main thread).
# Limitando ogni chiamata a _MAX_STYLE_BYTES, il lavoro idle si distribuisce
# in micro-step da ~10ms invece di un blocco unico da 1-2 secondi.
_MAX_STYLE_BYTES = 8000  # ~100 righe × 80 char


class LaTeXLexer(QsciLexerCustom):
    """Custom LaTeX lexer con highlighting stile TeXstudio."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bytes_cache: bytes | None = None
        self._state_cache: dict[int, tuple[str, tuple[str, ...]]] = {
            0: ("default", ())
        }
        # Invalida la cache solo quando il testo cambia.
        # Durante scroll/navigazione (testo invariato) la cache è riusata.
        if parent is not None:
            parent.textChanged.connect(self._on_text_changed)

    def _on_text_changed(self) -> None:
        self.invalidate_cache()

    def invalidate_cache(self) -> None:
        """Scarta lo snapshot byte del documento dell'editor padre."""
        self._bytes_cache = None
        self._state_cache = {0: ("default", ())}

    def recolor(self) -> None:
        """Invalida la cache e forza Scintilla a ristilizzare il documento."""
        self.invalidate_cache()
        parent = self.parent()
        if parent is not None:
            parent.SendScintilla(parent.SCI_COLOURISE, 0, -1)

    def language(self) -> str:
        return "LaTeX"

    def wordCharacters(self) -> str:
        # Includi '\' così QsciScintilla trova '\med', '\inc' ecc. nelle API
        return r"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_\@"

    def description(self, style: int) -> str:
        return _STYLE_NAMES.get(style, "")

    # ── Motore di highlighting ────────────────────────────────────────────────

    @staticmethod
    def _is_escaped(text_b: bytes, pos: int) -> bool:
        count = 0
        pos -= 1
        while pos >= 0 and text_b[pos] == _B_BACKSLASH:
            count += 1
            pos -= 1
        return bool(count % 2)

    @staticmethod
    def _command(text_b: bytes, pos: int) -> tuple[int, str] | None:
        i = pos + 1
        if i >= len(text_b) or text_b[i] >= 128:
            return None
        if not (chr(text_b[i]).isalpha() or text_b[i] == ord('@')):
            return None
        while i < len(text_b) and text_b[i] < 128 and (
                chr(text_b[i]).isalpha() or chr(text_b[i]) in ('@', '*')):
            i += 1
        return i, text_b[pos + 1:i].decode('ascii')

    @classmethod
    def _math_environment_token(cls, text_b: bytes, pos: int):
        command = cls._command(text_b, pos)
        if command is None or command[1] not in ('begin', 'end'):
            return None
        end, kind = command
        if end >= len(text_b) or text_b[end] != _B_LBRACE:
            return None
        close = text_b.find(b'}', end + 1)
        if close < 0:
            return None
        name = text_b[end + 1:close].decode('ascii', 'ignore').rstrip('*')
        if name not in {
            'equation', 'align', 'gather', 'multline', 'math', 'displaymath',
            'split', 'cases', 'alignat', 'flalign', 'subequations',
        }:
            return None
        return close + 1, kind, name

    def _state_at(self, text_b: bytes, offset: int):
        checkpoint = max((p for p in self._state_cache if p <= offset), default=0)
        mode, envs = self._state_cache[checkpoint]
        envs = list(envs)
        i = checkpoint
        while i < offset:
            if text_b[i] == _B_NEWLINE:
                i += 1
                self._state_cache[i] = (mode, tuple(envs))
                continue
            if text_b[i] == _B_PERCENT and not self._is_escaped(text_b, i):
                newline = text_b.find(b'\n', i, offset)
                i = offset if newline < 0 else newline
                continue
            if mode == 'default':
                if text_b[i] == _B_DOLLAR and not self._is_escaped(text_b, i):
                    width = 2 if text_b[i:i + 2] == b'$$' else 1
                    mode = 'double' if width == 2 else 'dollar'
                    i += width
                    continue
                if text_b[i:i + 2] in (b'\\(', b'\\['):
                    mode = 'paren' if text_b[i + 1] == ord('(') else 'bracket'
                    i += 2
                    continue
                token = self._math_environment_token(text_b, i)
                if token is not None and token[1] == 'begin':
                    mode = 'environment'
                    envs.append(token[2])
                    i = token[0]
                    continue
                i += 2 if text_b[i] == _B_BACKSLASH and i + 1 < offset else 1
                continue
            if mode == 'dollar' and text_b[i] == _B_DOLLAR and not self._is_escaped(text_b, i):
                mode = 'default'
                i += 1
                continue
            if mode == 'double' and text_b[i:i + 2] == b'$$' and not self._is_escaped(text_b, i):
                mode = 'default'
                i += 2
                continue
            if mode == 'paren' and text_b[i:i + 2] == b'\\)' and not self._is_escaped(text_b, i):
                mode = 'default'
                i += 2
                continue
            if mode == 'bracket' and text_b[i:i + 2] == b'\\]' and not self._is_escaped(text_b, i):
                mode = 'default'
                i += 2
                continue
            if mode == 'environment' and text_b[i] == _B_BACKSLASH:
                token = self._math_environment_token(text_b, i)
                if token is not None:
                    if token[1] == 'begin':
                        envs.append(token[2])
                    elif envs and envs[-1] == token[2]:
                        envs.pop()
                        if not envs:
                            mode = 'default'
                    i = token[0]
                    continue
            i += 1
        return mode, tuple(envs)

    def _style_with_state(self, start: int, end: int, text_b: bytes) -> None:
        tlen = len(text_b)
        nl = text_b.rfind(b'\n', 0, start)
        safe = 0 if nl < 0 else nl + 1
        end = min(end, tlen, safe + _MAX_STYLE_BYTES)
        if safe >= end:
            return
        styles = bytearray(end - safe)
        mode, envs = self._state_at(text_b, safe)
        envs = list(envs)
        last_cmd = ''

        def paint(pos: int, stop: int, style: int) -> None:
            lo = max(pos, safe) - safe
            hi = min(stop, end) - safe
            if hi > lo:
                styles[lo:hi] = bytes([style]) * (hi - lo)

        pos = safe
        while pos < end:
            b = text_b[pos]
            if b == _B_NEWLINE:
                self._state_cache[pos + 1] = (mode, tuple(envs))
                pos += 1
                last_cmd = ''
                continue
            if b == _B_PERCENT and not self._is_escaped(text_b, pos):
                stop = text_b.find(b'\n', pos, end)
                stop = end if stop < 0 else stop
                paint(pos, stop, S_COMMENT)
                pos = stop
                continue

            if mode == 'default':
                if b == _B_DOLLAR and not self._is_escaped(text_b, pos):
                    width = 2 if text_b[pos:pos + 2] == b'$$' else 1
                    paint(pos, pos + width, S_MATH)
                    mode = 'double' if width == 2 else 'dollar'
                    pos += width
                    continue
                if text_b[pos:pos + 2] in (b'\\(', b'\\['):
                    paint(pos, pos + 2, S_MATH)
                    mode = 'paren' if text_b[pos + 1] == ord('(') else 'bracket'
                    pos += 2
                    continue
                if b == _B_BACKSLASH:
                    token = self._math_environment_token(text_b, pos)
                    command = self._command(text_b, pos)
                    if token is not None and token[1] == 'begin':
                        paint(pos, token[0], S_MATH)
                        mode = 'environment'
                        envs.append(token[2])
                        pos = token[0]
                        continue
                    if command is not None:
                        stop, last_cmd = command
                        style = (S_STRUCTURE if last_cmd in _STRUCTURE_CMDS else
                                 S_REFERENCE if last_cmd in _REFERENCE_CMDS else S_COMMAND)
                        paint(pos, stop, style)
                        pos = stop
                        continue
                    paint(pos, pos + 2, S_COMMAND)
                    pos += 2 if pos + 1 < end else 1
                    last_cmd = ''
                    continue
                if b == _B_LBRACE:
                    paint(pos, pos + 1, S_BRACE)
                    pos += 1
                    if last_cmd in _REFERENCE_CMDS:
                        i, depth = pos, 1
                        while i < tlen and depth:
                            if text_b[i] == _B_BACKSLASH and i + 1 < tlen:
                                i += 2
                                continue
                            if text_b[i] == _B_LBRACE:
                                depth += 1
                            elif text_b[i] == _B_RBRACE:
                                depth -= 1
                            i += 1
                        content_end = i - 1 if depth == 0 else i
                        paint(pos, content_end, S_REF_ARG)
                        pos = min(content_end, end)
                    last_cmd = ''
                    continue
                if b == _B_LBRACKET:
                    paint(pos, pos + 1, S_BRACE)
                    close = text_b.find(b']', pos + 1, tlen)
                    newline = text_b.find(b'\n', pos + 1, tlen)
                    if close >= 0 and (newline < 0 or close < newline):
                        paint(pos + 1, close, S_OPTION)
                        pos = close
                    else:
                        pos += 1
                    continue
                if b in (_B_RBRACE, _B_RBRACKET):
                    paint(pos, pos + 1, S_BRACE)
                    pos += 1
                    continue
                special = _RE_SPECIAL_BYTES.search(text_b, pos, end)
                newline = text_b.find(b'\n', pos, end)
                stop = min((special.start() if special else end),
                           (newline if newline >= 0 else end))
                if stop > pos:
                    pos = stop
                    last_cmd = ''
                    continue
                last_cmd = ''
                pos += 1
                continue

            if mode == 'environment' and b == _B_BACKSLASH:
                token = self._math_environment_token(text_b, pos)
                if token is not None:
                    paint(pos, token[0], S_MATH)
                    if token[1] == 'begin':
                        envs.append(token[2])
                    elif envs and envs[-1] == token[2]:
                        envs.pop()
                        if not envs:
                            mode = 'default'
                    pos = token[0]
                    continue
            if mode == 'dollar' and b == _B_DOLLAR and not self._is_escaped(text_b, pos):
                paint(pos, pos + 1, S_MATH)
                mode, pos = 'default', pos + 1
                continue
            if mode == 'double' and text_b[pos:pos + 2] == b'$$' and not self._is_escaped(text_b, pos):
                paint(pos, pos + 2, S_MATH)
                mode, pos = 'default', pos + 2
                continue
            if mode == 'paren' and text_b[pos:pos + 2] == b'\\)' and not self._is_escaped(text_b, pos):
                paint(pos, pos + 2, S_MATH)
                mode, pos = 'default', pos + 2
                continue
            if mode == 'bracket' and text_b[pos:pos + 2] == b'\\]' and not self._is_escaped(text_b, pos):
                paint(pos, pos + 2, S_MATH)
                mode, pos = 'default', pos + 2
                continue
            special = _RE_SPECIAL_BYTES.search(text_b, pos, end)
            newline = text_b.find(b'\n', pos, end)
            stop = min((special.start() if special else end),
                       (newline if newline >= 0 else end))
            if stop > pos:
                paint(pos, stop, S_MATH)
                pos = stop
            else:
                paint(pos, pos + 1, S_MATH)
                pos += 1

        self.startStyling(safe)
        i = 0
        while i < len(styles):
            style = styles[i]
            j = i + 1
            while j < len(styles) and styles[j] == style:
                j += 1
            self.setStyling(j - i, style)
            i = j

    def styleText(self, start: int, end: int) -> None:
        # Ottieni bytes (con cache): evita encode O(n) ad ogni chiamata.
        if self._bytes_cache is None:
            p = self.parent()
            try:
                # Lettura diretta byte UTF-8 da Scintilla (evita str→encode, ~3-5ms vs ~18ms)
                n = p.SendScintilla(p.SCI_GETLENGTH)
                buf = bytearray(n + 1)
                p.SendScintilla(p.SCI_GETTEXT, n + 1, buf)
                self._bytes_cache = bytes(buf[:n])
            except Exception:
                self._bytes_cache = p.text().encode('utf-8')
        text_b = self._bytes_cache
        tlen = len(text_b)
        if tlen == 0 or start >= tlen:
            return
        self._style_with_state(start, end, text_b)

    # ── Applicazione tema ─────────────────────────────────────────────────────

    def set_colors(self, tokens: dict, font_family: str, font_size: int,
                   editor_bg, editor_fg) -> None:
        """Applica i colori dal dizionario tema ai propri stili."""
        p = self.parent()
        if not p:
            return
        from PyQt6.QtGui import QColor

        bg_name = editor_bg.name() if hasattr(editor_bg, 'name') else str(editor_bg)
        font_b  = font_family.encode()

        # Scrive i colori DIRETTAMENTE nelle tabelle Scintilla via SendScintilla,
        # bypassando il meccanismo segnali di QsciLexer.
        #
        # Il percorso normale: setColor() → colorChanged → handleStyleColorChange
        # → SCI_STYLESETFORE + recolourize(). Con blockSignals=True usato prima,
        # SCI_STYLESETFORE non veniva mai inviato → Scintilla usava la tabella
        # colori stale → nessun colore visibile.
        #
        # Qui inviamo SCI_STYLESETFORE/BACK/FONT/SIZE/BOLD/ITALIC per ogni stile
        # direttamente, poi un solo SCI_COLOURISE alla fine.

        for sn in range(16):
            p.SendScintilla(p.SCI_STYLESETFORE,   sn, editor_fg)
            p.SendScintilla(p.SCI_STYLESETBACK,   sn, editor_bg)
            p.SendScintilla(p.SCI_STYLESETFONT,   sn, font_b)
            p.SendScintilla(p.SCI_STYLESETSIZE,   sn, font_size)
            p.SendScintilla(p.SCI_STYLESETBOLD,   sn, 0)
            p.SendScintilla(p.SCI_STYLESETITALIC, sn, 0)

        for style_num, tok_key in STYLE_TOKEN.items():
            tok = tokens.get(tok_key, {})
            if not tok:
                continue
            fg = QColor(tok["fg"]) if "fg" in tok else editor_fg
            bg = QColor(tok.get("bg", bg_name))
            p.SendScintilla(p.SCI_STYLESETFORE,   style_num, fg)
            p.SendScintilla(p.SCI_STYLESETBACK,   style_num, bg)
            p.SendScintilla(p.SCI_STYLESETFONT,   style_num, font_b)
            p.SendScintilla(p.SCI_STYLESETSIZE,   style_num, font_size)
            p.SendScintilla(p.SCI_STYLESETBOLD,   style_num, 1 if tok.get("bold")   else 0)
            p.SendScintilla(p.SCI_STYLESETITALIC, style_num, 1 if tok.get("italic") else 0)

        p.SendScintilla(p.SCI_COLOURISE, 0, -1)

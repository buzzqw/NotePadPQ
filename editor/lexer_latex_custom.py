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

import bisect
import re
import string

from PyQt6.Qsci import QsciLexerCustom, QsciScintilla

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

# Ambienti il cui contenuto è testo letterale: LaTeX non lo interpreta affatto
# (comandi, $, % restano caratteri semplici) fino al \end corrispondente.
_VERBATIM_ENVS = frozenset([
    'verbatim', 'verbatim*', 'lstlisting', 'Verbatim', 'BVerbatim', 'minted',
])


def _char_table(chars: str) -> bytes:
    """Tabella di lookup a 256 voci (0/1): evita chr(byte).isalpha() per
    ogni singolo byte scansionato in _command(), che alloca una str Python
    ad ogni chiamata sul percorso più caldo del lexer (ogni backslash)."""
    table = bytearray(256)
    for ch in chars:
        table[ord(ch)] = 1
    return bytes(table)


# Primo carattere di un nome comando: lettere + '@' (LaTeX2e interno), niente '*'.
_CMD_FIRST_CHARS = _char_table(string.ascii_letters + '@')
# Caratteri successivi: come sopra più '*' (es. \section*).
_CMD_CONT_CHARS = _char_table(string.ascii_letters + '@*')

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

    # Bit di SCN_MODIFIED che indicano un vero inserimento/cancellazione di
    # testo (a differenza di SC_MOD_CHANGESTYLE, che è la nostra stessa
    # chiamata a setStyling() e va ignorata per non auto-invalidare la cache
    # ad ogni styleText()).
    _EDIT_MASK = QsciScintilla.SC_MOD_INSERTTEXT | QsciScintilla.SC_MOD_DELETETEXT

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bytes_cache: bytes | None = None
        self._state_cache: dict[int, tuple[str, tuple[str, ...]]] = {
            0: ("default", ())
        }
        # Chiavi di _state_cache in ordine crescente, per lookup O(log n)
        # via bisect invece di una scansione lineare di tutta la cache.
        self._state_cache_order: list[int] = [0]
        if parent is not None:
            # Il testo è cambiato: lo snapshot byte è comunque da rileggere.
            parent.textChanged.connect(self._on_text_changed)
            # Potatura precisa della cache di stato: solo le voci con
            # offset > position dell'edit sono invalidate (il testo prima
            # della modifica, e il suo stato, restano identici). Senza
            # questo, un singolo carattere digitato in fondo a un file da
            # 2-3 MB forzava una ri-scansione dell'intero documento da
            # zero ad ogni tasto premuto (centinaia di ms → secondi).
            parent.SCN_MODIFIED.connect(self._on_scn_modified)

    def _on_text_changed(self) -> None:
        self._bytes_cache = None

    def _on_scn_modified(self, position, modification_type, text, length,
                          lines_added, line, fold_now, fold_prev, token,
                          annotation_lines_added) -> None:
        if not (modification_type & self._EDIT_MASK):
            return
        self._invalidate_state_from(position)

    def _invalidate_state_from(self, position: int) -> None:
        """Scarta le voci di _state_cache con offset > position: dopo un
        insert/delete i byte a quelle posizioni sono shiftati e non più
        validi. Le voci precedenti restano corrette e vengono conservate."""
        order = self._state_cache_order
        idx = bisect.bisect_right(order, position)
        if idx < len(order):
            for key in order[idx:]:
                del self._state_cache[key]
            del order[idx:]

    def _cache_state(self, pos: int, mode: str, envs: tuple) -> None:
        if pos not in self._state_cache:
            bisect.insort(self._state_cache_order, pos)
        self._state_cache[pos] = (mode, envs)

    def invalidate_cache(self) -> None:
        """Scarta lo snapshot byte e l'intera cache di stato (usato per un
        re-highlight completo, es. cambio tema — non per ogni keystroke)."""
        self._bytes_cache = None
        self._state_cache = {0: ("default", ())}
        self._state_cache_order = [0]

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
        n = len(text_b)
        if i >= n or not _CMD_FIRST_CHARS[text_b[i]]:
            return None
        i += 1
        while i < n and _CMD_CONT_CHARS[text_b[i]]:
            i += 1
        return i, text_b[pos + 1:i].decode('ascii')

    @classmethod
    def _verbatim_environment_token(cls, text_b: bytes, pos: int):
        """Come _math_environment_token ma per \\begin/\\end di un ambiente
        verbatim-like (contenuto letterale, non interpretato)."""
        command = cls._command(text_b, pos)
        if command is None or command[1] not in ('begin', 'end'):
            return None
        end, kind = command
        if end >= len(text_b) or text_b[end] != _B_LBRACE:
            return None
        close = text_b.find(b'}', end + 1)
        if close < 0:
            return None
        name = text_b[end + 1:close].decode('ascii', 'ignore')
        if name not in _VERBATIM_ENVS:
            return None
        return close + 1, kind, name

    @staticmethod
    def _verb_inline_span(text_b: bytes, pos: int) -> int | None:
        """pos punta al backslash. Riconosce \\verb / \\verb* seguito da un
        delimitatore (qualunque carattere non lettera e non spazio) e ne
        cerca la chiusura sulla stessa riga. Ritorna l'offset subito dopo
        il delimitatore di chiusura, o None se pos non è l'inizio di un
        \\verb valido (es. è in realtà \\verbatim o \\verbose)."""
        n = len(text_b)
        if text_b[pos + 1:pos + 6] == b'verb*':
            i = pos + 6
        elif text_b[pos + 1:pos + 5] == b'verb':
            i = pos + 5
        else:
            return None
        if i >= n:
            return None
        delim = text_b[i]
        if delim == _B_BACKSLASH or delim == ord(' ') or (
                delim < 128 and chr(delim).isalpha()):
            return None
        newline = text_b.find(b'\n', i + 1, n)
        limit = newline if newline >= 0 else n
        close = text_b.find(bytes([delim]), i + 1, limit)
        return (close + 1) if close >= 0 else limit

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
        # Guardia economica: se qualcuno ha riassegnato _state_cache
        # direttamente (es. test white-box) senza passare da _cache_state/
        # _invalidate_state_from, la lista ordinata si disallinea. Un
        # confronto di lunghezza (O(1)) la ricostruisce solo in quel caso
        # raro — nel percorso caldo normale non costa nulla.
        if len(self._state_cache_order) != len(self._state_cache):
            self._state_cache_order = sorted(self._state_cache)
        idx = bisect.bisect_right(self._state_cache_order, offset) - 1
        checkpoint = self._state_cache_order[idx] if idx >= 0 else 0
        mode, envs = self._state_cache[checkpoint]
        envs = list(envs)
        i = checkpoint
        while i < offset:
            if text_b[i] == _B_NEWLINE:
                i += 1
                self._cache_state(i, mode, tuple(envs))
                continue
            if text_b[i] == _B_PERCENT and mode != 'verbatim' and not self._is_escaped(text_b, i):
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
                vtoken = self._verbatim_environment_token(text_b, i)
                if vtoken is not None and vtoken[1] == 'begin':
                    mode = 'verbatim'
                    envs.append(vtoken[2])
                    i = vtoken[0]
                    continue
                verb_end = self._verb_inline_span(text_b, i)
                if verb_end is not None:
                    i = verb_end
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
            if mode == 'verbatim':
                newline = text_b.find(b'\n', i, offset)
                backslash = text_b.find(b'\\', i, offset)
                candidates = [p for p in (newline, backslash) if p >= 0]
                stop = min(candidates) if candidates else offset
                if stop > i:
                    i = stop
                    continue
                vtoken = self._verbatim_environment_token(text_b, i)
                if vtoken is not None and vtoken[1] == 'end' and envs and envs[-1] == vtoken[2]:
                    envs.pop()
                    if not envs:
                        mode = 'default'
                    i = vtoken[0]
                else:
                    i += 1
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
                self._cache_state(pos + 1, mode, tuple(envs))
                pos += 1
                last_cmd = ''
                continue
            if b == _B_PERCENT and mode != 'verbatim' and not self._is_escaped(text_b, pos):
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
                    vtoken = self._verbatim_environment_token(text_b, pos)
                    if vtoken is not None and vtoken[1] == 'begin':
                        paint(pos, vtoken[0], S_STRUCTURE)
                        mode = 'verbatim'
                        envs.append(vtoken[2])
                        pos = vtoken[0]
                        continue
                    verb_end = self._verb_inline_span(text_b, pos)
                    if verb_end is not None:
                        paint(pos, verb_end, S_COMMAND)
                        pos = verb_end
                        last_cmd = ''
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
            if mode == 'verbatim':
                newline = text_b.find(b'\n', pos, end)
                backslash = text_b.find(b'\\', pos, end)
                candidates = [p for p in (newline, backslash) if p >= 0]
                stop = min(candidates) if candidates else end
                if stop > pos:
                    pos = stop
                    continue
                vtoken = self._verbatim_environment_token(text_b, pos)
                if vtoken is not None and vtoken[1] == 'end' and envs and envs[-1] == vtoken[2]:
                    paint(pos, vtoken[0], S_STRUCTURE)
                    envs.pop()
                    if not envs:
                        mode = 'default'
                    pos = vtoken[0]
                else:
                    pos += 1
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

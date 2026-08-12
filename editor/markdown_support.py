r"""
editor/markdown_support.py — Supporto avanzato Markdown
NotePadPQ

Fornisce:
- Auto-chiusura coppie di marcatori: ** → **, * → *, ` → `, ``` → ```
- Completamento automatico del blocco codice con suggerimento linguaggio
- Toggle checklist: [ ] ↔ [x] (Ctrl+Shift+L)
- YAML front matter highlight (blocco --- iniziale)
- Tipografia intelligente (virgolette, em dash, ellissi)
- Focus paragrafo (attenua il testo fuori dal paragrafo corrente)

Uso:
    MarkdownSupport.activate(editor)   # collega i segnali SCN_CHARADDED
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

# Indicatori riservati a MarkdownSupport (non collidono con editor_widget.py 0-6 e smart_highlight 13-18)
INDICATOR_YAML_FM      = 19   # FullBoxIndicator: sfondo sul blocco front matter YAML
INDICATOR_SENTENCE_DIM = 20   # TextColorIndicator: attenua testo fuori dal paragrafo


class MarkdownSupport:
    """
    Classe statica. Fornisce parsing e supporto Markdown avanzato.
    Attivata da editor/lexers.py quando il lexer Markdown viene impostato.
    """

    # ── Attivazione su EditorWidget ──────────────────────────────────────────

    @staticmethod
    def activate(editor: "EditorWidget") -> None:
        """
        Collega i segnali dell'editor per il supporto Markdown avanzato.
        Va chiamato quando il lexer Markdown viene impostato.
        """
        MarkdownSupport.deactivate(editor)

        def char_handler(char):
            MarkdownSupport._on_char_added(editor, char)

        editor._markdown_char_added_handler = char_handler
        editor.SCN_CHARADDED.connect(char_handler)

        # YAML front matter: applica subito e ogni volta che il testo cambia
        def _slot():
            MarkdownSupport._apply_yaml_fm(editor)

        editor._md_yaml_fm_slot = _slot
        editor.textChanged.connect(_slot)
        editor._md_yaml_fm_end_line = None
        MarkdownSupport._apply_yaml_fm(editor)

        # Inizializza indicatori se non già fatto
        MarkdownSupport._init_indicators(editor)
        editor._markdown_support_active = True

    @staticmethod
    def deactivate(editor: "EditorWidget") -> None:
        """Scollega gli handler Markdown e cancella il relativo stato visivo."""
        for signal_name, attr_name in (
                ("SCN_CHARADDED", "_markdown_char_added_handler"),
                ("textChanged", "_md_yaml_fm_slot")):
            handler = getattr(editor, attr_name, None)
            if handler is not None:
                try:
                    getattr(editor, signal_name).disconnect(handler)
                except (RuntimeError, TypeError):
                    pass
                setattr(editor, attr_name, None)
        try:
            for indicator in (INDICATOR_YAML_FM, INDICATOR_SENTENCE_DIM):
                editor.clearIndicatorRange(
                    0, 0, editor.lines(), 0, indicator
                )
        except (RuntimeError, TypeError):
            pass
        editor._md_yaml_fm_end_line = None
        editor._paragraph_focus_range = None
        editor._markdown_support_active = False

    @staticmethod
    def _yaml_fm_slot(editor: "EditorWidget"):
        return getattr(editor, "_md_yaml_fm_slot", None)

    @staticmethod
    def _init_indicators(editor: "EditorWidget") -> None:
        """Inizializza gli indicatori usati da MarkdownSupport sull'editor."""
        from PyQt6.Qsci import QsciScintilla
        from PyQt6.QtGui import QColor
        try:
            editor.indicatorDefine(
                QsciScintilla.IndicatorStyle.FullBoxIndicator, INDICATOR_YAML_FM
            )
            editor.setIndicatorForegroundColor(QColor(255, 200, 60, 35), INDICATOR_YAML_FM)
            editor.setIndicatorDrawUnder(True, INDICATOR_YAML_FM)
        except Exception:
            pass
        try:
            editor.indicatorDefine(
                QsciScintilla.IndicatorStyle.TextColorIndicator, INDICATOR_SENTENCE_DIM
            )
            # Il colore viene impostato in apply_paragraph_focus in base al tema
        except Exception:
            pass

    # ── SCN_CHARADDED ────────────────────────────────────────────────────────

    @staticmethod
    def _on_char_added(editor: "EditorWidget", char_int: int) -> None:
        """Gestisce i caratteri speciali Markdown."""
        if getattr(editor, "_in_paste", False):
            return
        char = chr(char_int)

        # Tipografia intelligente (opzionale, configurabile)
        try:
            from config.settings import Settings
            if Settings.instance().get("editor/smart_typography", False):
                MarkdownSupport._handle_smart_typo(editor, char)
        except Exception:
            pass

        if char == "*":
            MarkdownSupport._handle_asterisk(editor)
        elif char == "`":
            MarkdownSupport._handle_backtick(editor)
        elif char == "\n":
            MarkdownSupport._handle_newline(editor)

    # ── Toggle checklist ─────────────────────────────────────────────────────

    @staticmethod
    def toggle_checklist(editor: "EditorWidget") -> bool:
        """
        Alterna [ ] ↔ [x] sulla riga corrente.
        Ritorna True se ha modificato il testo, False se la riga non è una task list.
        """
        line, _ = editor.getCursorPosition()
        text = editor.text(line)
        stripped = text.rstrip("\n\r")

        # [ ] → [x]
        m = re.match(r"^(\s*[-*+]\s\[)( )(\].*)$", stripped)
        if m:
            editor.beginUndoAction()
            editor.setSelection(line, 0, line, len(stripped))
            editor.replaceSelectedText(m.group(1) + "x" + m.group(3))
            editor.endUndoAction()
            return True

        # [x] → [ ]
        m2 = re.match(r"^(\s*[-*+]\s\[)(x)(\].*)$", stripped)
        if m2:
            editor.beginUndoAction()
            editor.setSelection(line, 0, line, len(stripped))
            editor.replaceSelectedText(m2.group(1) + " " + m2.group(3))
            editor.endUndoAction()
            return True

        return False

    # ── YAML Front Matter highlight ──────────────────────────────────────────

    @staticmethod
    def _apply_yaml_fm(editor: "EditorWidget") -> None:
        """
        Evidenzia il blocco YAML front matter (--- ... ---) all'inizio del documento
        con uno sfondo tenue tramite INDICATOR_YAML_FM.
        """
        total = editor.lines()
        end_line = None
        if total >= 2 and editor.text(0).strip() == "---":
            for i in range(1, min(total, 100)):
                if editor.text(i).strip() == "---":
                    end_line = i
                    break

        old_end_line = getattr(editor, "_md_yaml_fm_end_line", None)
        if end_line == old_end_line:
            return
        # Il front matter e' confinato alle prime 100 righe: non cancellare
        # l'indicatore sull'intero documento a ogni carattere digitato.
        last_changed_line = max(
            end_line if end_line is not None else 0,
            old_end_line if old_end_line is not None else 0,
        )
        editor.clearIndicatorRange(0, 0, last_changed_line + 1, 0, INDICATOR_YAML_FM)
        editor._md_yaml_fm_end_line = end_line
        if end_line is not None:
            last_col = len(editor.text(end_line).rstrip("\n\r"))
            editor.fillIndicatorRange(0, 0, end_line, last_col, INDICATOR_YAML_FM)

    # ── Paragraph focus (Focus Mode) ─────────────────────────────────────────

    @staticmethod
    def apply_paragraph_focus(editor: "EditorWidget") -> None:
        """
        Attenua il testo fuori dal paragrafo corrente.
        Il paragrafo è delimitato da righe vuote (o inizio/fine documento).
        """
        from PyQt6.QtGui import QColor

        indicator = INDICATOR_SENTENCE_DIM
        total = editor.lines()
        line, _ = editor.getCursorPosition()

        # Colore di attenuazione: blend verso lo sfondo
        paper = editor.paper()
        lum = (0.299 * paper.red() + 0.587 * paper.green() + 0.114 * paper.blue()) / 255
        if lum < 0.5:
            dim_color = QColor(90, 90, 90)    # tema scuro: grigio medio
        else:
            dim_color = QColor(185, 185, 185)  # tema chiaro: grigio chiaro

        try:
            editor.setIndicatorForegroundColor(dim_color, indicator)
        except Exception:
            pass

        # Trova inizio paragrafo
        para_start = line
        while para_start > 0 and editor.text(para_start - 1).strip():
            para_start -= 1

        # Trova fine paragrafo
        para_end = line
        while para_end < total - 1 and editor.text(para_end).strip():
            para_end += 1

        current_range = (para_start, para_end)
        if current_range == getattr(editor, "_paragraph_focus_range", None):
            return
        editor._paragraph_focus_range = current_range

        # Cancella tutto e poi attenua fuori dal paragrafo
        editor.clearIndicatorRange(0, 0, total, 0, indicator)

        if para_start > 0:
            editor.fillIndicatorRange(0, 0, para_start, 0, indicator)

        if para_end < total - 1:
            last_len = len(editor.text(total - 1).rstrip("\n\r"))
            editor.fillIndicatorRange(para_end + 1, 0, total - 1, last_len, indicator)

    @staticmethod
    def clear_paragraph_focus(editor: "EditorWidget") -> None:
        """Rimuove la modalità focus paragrafo dall'editor."""
        editor.clearIndicatorRange(0, 0, editor.lines(), 0, INDICATOR_SENTENCE_DIM)
        editor._paragraph_focus_range = None

    # ── Tipografia intelligente ───────────────────────────────────────────────

    @staticmethod
    def _handle_smart_typo(editor: "EditorWidget", char: str) -> None:
        """
        Sostituisce caratteri tipografici "grezzi" con quelli corretti:
        "  →  " o "      '  →  ' o '      --  →  —      ...  →  …
        Non attiva in blocchi di codice (riga che inizia con ``` o con 4+ spazi).
        """
        line, col = editor.getCursorPosition()
        line_text = editor.text(line)
        before = line_text[:col]  # include il char appena digitato

        # Non attivare dentro blocchi codice
        stripped = line_text.lstrip()
        if stripped.startswith("```") or stripped.startswith("    ") or stripped.startswith("\t"):
            return

        if char == '"':
            # Heuristica: se il char precedente è alfanumerico/punteggiatura → chiusura
            prev = before[-2] if len(before) >= 2 else ""
            replacement = "”" if (prev.isalnum() or prev in ".!?,;'’") else "“"
            editor.beginUndoAction()
            editor.setSelection(line, col - 1, line, col)
            editor.replaceSelectedText(replacement)
            editor.endUndoAction()

        elif char == "'":
            prev = before[-2] if len(before) >= 2 else ""
            replacement = "’" if (prev.isalnum() or prev in ".!?,;”") else "‘"
            editor.beginUndoAction()
            editor.setSelection(line, col - 1, line, col)
            editor.replaceSelectedText(replacement)
            editor.endUndoAction()

        elif char == "-":
            # '--' → '—' (em dash)
            if len(before) >= 2 and before[-2] == "-":
                editor.beginUndoAction()
                editor.setSelection(line, col - 2, line, col)
                editor.replaceSelectedText("—")
                editor.endUndoAction()

        elif char == ".":
            # '...' → '…'
            if len(before) >= 3 and before[-3:-1] == "..":
                editor.beginUndoAction()
                editor.setSelection(line, col - 3, line, col)
                editor.replaceSelectedText("…")
                editor.endUndoAction()

    # ── Handlers originali ────────────────────────────────────────────────────

    @staticmethod
    def _handle_asterisk(editor: "EditorWidget") -> None:
        """
        Dopo '*': decide se inserire la chiusura automatica.
        - Se il carattere precedente è '*' (quindi digitato '**') → inserisce '**' di chiusura
        - Se il carattere precedente è uno spazio/inizio riga → inserisce '*' di chiusura
        Non chiude se siamo già dentro una coppia (euristica).
        """
        line, col = editor.getCursorPosition()
        line_text = editor.text(line)

        before = line_text[:col]

        # Caso '**': il penultimo char è anche '*'
        if len(before) >= 2 and before[-2] == "*":
            stripped = before[:-1]
            open_count = stripped.count("**")
            after = line_text[col:]
            if after.startswith("**"):
                return
            if open_count % 2 == 0:
                editor.beginUndoAction()
                editor.insert("**")
                editor.setCursorPosition(line, col)
                editor.endUndoAction()
            return

        # Caso '*' singolo
        after = line_text[col:]
        if after.startswith("*"):
            return

        prev_char = before[-2] if len(before) >= 2 else ""
        if prev_char in ("", " ", "\t", "(", "[", "{", ">", "~"):
            editor.beginUndoAction()
            editor.insert("*")
            editor.setCursorPosition(line, col)
            editor.endUndoAction()

    @staticmethod
    def _handle_backtick(editor: "EditorWidget") -> None:
        """
        Dopo '`':
        - Se è il terzo backtick consecutivo (``` ) → inserisce blocco codice completo
        - Altrimenti → inserisce '`' di chiusura inline
        """
        line, col = editor.getCursorPosition()
        line_text = editor.text(line)
        before = line_text[:col]

        if len(before) >= 3 and before[-3:] == "```":
            after = line_text[col:]
            if after.startswith("\n") or after.strip() == "":
                editor.beginUndoAction()
                editor.insert("\n\n```")
                editor.setCursorPosition(line, col)
                editor.endUndoAction()
            return

        after = line_text[col:]
        if after.startswith("`"):
            return

        single_ticks = before.count("`") - before.count("``") * 2
        if single_ticks % 2 == 0:
            editor.beginUndoAction()
            editor.insert("`")
            editor.setCursorPosition(line, col)
            editor.endUndoAction()

    @staticmethod
    def _handle_newline(editor: "EditorWidget") -> None:
        """
        Su invio dopo una riga che inizia con '- ', '* ', '1. ' ecc.:
        continua la lista automaticamente se la riga precedente non è vuota.
        """
        line, col = editor.getCursorPosition()
        if line < 1:
            return
        prev_line = editor.text(line - 1)

        # Rilevamento task list: '- [ ] ' o '- [x] '
        mt = re.match(r'^(\s*)([-*+])\s\[( |x)\]\s?', prev_line)
        if mt:
            indent = mt.group(1)
            marker = mt.group(2)
            task_prefix = f"{indent}{marker} [ ] "
            if prev_line.rstrip() in (
                f"{indent}{marker} [ ]",
                f"{indent}{marker} [ ] ",
                f"{indent}{marker} [x]",
                f"{indent}{marker} [x] ",
            ):
                editor.beginUndoAction()
                editor.setSelection(line - 1, 0, line - 1, len(prev_line.rstrip("\n")))
                editor.replaceSelectedText("")
                editor.endUndoAction()
            else:
                editor.beginUndoAction()
                current_line_text = editor.text(line)
                if not current_line_text.strip():
                    editor.insert(task_prefix)
                    editor.setCursorPosition(line, len(task_prefix))
                editor.endUndoAction()
            return

        # Lista non ordinata
        m = re.match(r'^(\s*)([-*+])\s', prev_line)
        if m:
            indent = m.group(1)
            marker = m.group(2)
            if prev_line.rstrip() in (f"{indent}{marker}", f"{indent}{marker} "):
                editor.beginUndoAction()
                editor.setSelection(line - 1, 0, line - 1, len(prev_line.rstrip("\n")))
                editor.replaceSelectedText("")
                editor.endUndoAction()
            else:
                editor.beginUndoAction()
                current_line_text = editor.text(line)
                if not current_line_text.strip():
                    editor.insert(f"{indent}{marker} ")
                    editor.setCursorPosition(line, len(indent) + 2)
                editor.endUndoAction()
            return

        # Lista ordinata
        m2 = re.match(r'^(\s*)(\d+)\.\s', prev_line)
        if m2:
            indent = m2.group(1)
            num = int(m2.group(2))
            if prev_line.rstrip() == f"{indent}{num}.":
                editor.beginUndoAction()
                editor.setSelection(line - 1, 0, line - 1, len(prev_line.rstrip("\n")))
                editor.replaceSelectedText("")
                editor.endUndoAction()
            else:
                editor.beginUndoAction()
                current_line_text = editor.text(line)
                if not current_line_text.strip():
                    editor.insert(f"{indent}{num + 1}. ")
                    editor.setCursorPosition(line, len(indent) + len(str(num + 1)) + 2)
                editor.endUndoAction()

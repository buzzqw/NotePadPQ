r"""
editor/markdown_support.py — Supporto avanzato Markdown
NotePadPQ

Fornisce:
- Auto-chiusura coppie di marcatori: ** → **, * → *, ` → `, ``` → ```
- Completamento automatico del blocco codice con suggerimento linguaggio
- Nessuna duplicazione: bold/italic/strike sono già in MainWindow._apply_markup()

Uso:
    MarkdownSupport.activate(editor)   # collega i segnali SCN_CHARADDED
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget


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
        try:
            editor.SCN_CHARADDED.disconnect(MarkdownSupport._on_char_added)
        except Exception:
            pass

        editor.SCN_CHARADDED.connect(
            lambda char: MarkdownSupport._on_char_added(editor, char)
        )

    @staticmethod
    def _on_char_added(editor: "EditorWidget", char_int: int) -> None:
        """Gestisce i caratteri speciali Markdown."""
        # Ignora durante operazioni di paste/insert programmatico
        if getattr(editor, "_in_paste", False):
            return
        char = chr(char_int)

        if char == "*":
            MarkdownSupport._handle_asterisk(editor)
        elif char == "`":
            MarkdownSupport._handle_backtick(editor)
        elif char == "\n":
            MarkdownSupport._handle_newline(editor)

    # ── Handlers ─────────────────────────────────────────────────────────────

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

        # Testo prima del cursore (escludendo l'* appena inserito che è già nella riga)
        before = line_text[:col]

        # Caso '**': il penultimo char è anche '*'
        if len(before) >= 2 and before[-2] == "*":
            # Conta le coppie '**' aperte prima del cursore
            stripped = before[:-1]  # senza l'ultimo *
            open_count = stripped.count("**")
            # Se dispari (cioè aperto senza chiusura), non aggiungere altra chiusura
            after = line_text[col:]
            if after.startswith("**"):
                return  # già c'è la chiusura
            if open_count % 2 == 0:
                # Apriamo una nuova coppia **
                editor.beginUndoAction()
                editor.insert("**")
                editor.setCursorPosition(line, col)
                editor.endUndoAction()
            return

        # Caso '*' singolo
        # Non chiudere se il carattere prima dell'* è un altro * (già gestito sopra)
        # Non chiudere se siamo dentro una parola (evita false auto-chiusure)
        after = line_text[col:]
        if after.startswith("*"):
            return  # c'è già

        # Inserisci solo se il carattere precedente all'* è spazio/inizio o punteggiatura
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

        # Controlla se abbiamo appena digitato ``` (tre backtick)
        if len(before) >= 3 and before[-3:] == "```":
            after = line_text[col:]
            # Già completato?
            if after.startswith("\n") or after.strip() == "":
                # Inserisce il blocco fenced code
                editor.beginUndoAction()
                editor.insert("\n\n```")
                editor.setCursorPosition(line, col)
                editor.endUndoAction()
            return

        # Backtick singolo: auto-chiude solo se non siamo già dentro un backtick
        after = line_text[col:]
        if after.startswith("`"):
            return  # c'è già la chiusura

        # Conta i backtick singoli aperti sulla riga
        single_ticks = before.count("`") - before.count("``") * 2
        if single_ticks % 2 == 0:
            # Apriamo un nuovo inline code
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

        # Rilevamento lista non ordinata: '- ', '* ', '+ '
        m = re.match(r'^(\s*)([-*+])\s', prev_line)
        if m:
            indent = m.group(1)
            marker = m.group(2)
            # Se la riga precedente è vuota (solo marker), rimuovi il marker (finisce la lista)
            if prev_line.rstrip() in (f"{indent}{marker}", f"{indent}{marker} "):
                editor.beginUndoAction()
                # Rimuovi la riga precedente del marker
                editor.setSelection(line - 1, 0, line - 1, len(prev_line.rstrip("\n")))
                editor.replaceSelectedText("")
                editor.endUndoAction()
            else:
                # Continua la lista
                editor.beginUndoAction()
                current_line_text = editor.text(line)
                if not current_line_text.strip():
                    editor.insert(f"{indent}{marker} ")
                    editor.setCursorPosition(line, len(indent) + 2)
                editor.endUndoAction()
            return

        # Rilevamento lista ordinata: '1. ', '2. ', ecc.
        m2 = re.match(r'^(\s*)(\d+)\.\s', prev_line)
        if m2:
            indent = m2.group(1)
            num = int(m2.group(2))
            if prev_line.rstrip() == f"{indent}{num}.":
                # Riga vuota: termina lista
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

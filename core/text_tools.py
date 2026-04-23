"""
core/text_tools.py — Operazioni sul testo
NotePadPQ

Funzioni pure su testo e funzioni che operano su un EditorWidget:
- Commenta/decommenta righe (sensibile al linguaggio)
- Indentazione intelligente
- Trasformazioni case (upper, lower, title, swap)
- Trim trailing whitespace
- Conversione tab/spazi
- Unisci righe / Riflusso
"""

from __future__ import annotations

import re
import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

# ─── Funzioni pure su stringa ─────────────────────────────────────────────────

def trim_trailing_whitespace(text: str) -> str:
    """Rimuove gli spazi finali da ogni riga."""
    return "\n".join(line.rstrip() for line in text.split("\n"))


def tabs_to_spaces(text: str, tab_width: int = 4) -> str:
    """Converte tutti i tab in spazi."""
    return text.expandtabs(tab_width)


def spaces_to_tabs(text: str, tab_width: int = 4) -> str:
    """Converte gruppi di spazi iniziali in tab."""
    lines = []
    for line in text.split("\n"):
        stripped = line.lstrip(" ")
        spaces = len(line) - len(stripped)
        tabs = spaces // tab_width
        remainder = spaces % tab_width
        lines.append("\t" * tabs + " " * remainder + stripped)
    return "\n".join(lines)


def join_lines(text: str) -> str:
    """Unisce le righe selezionate con uno spazio."""
    return " ".join(line.strip() for line in text.split("\n") if line.strip())


def wrap_lines(text: str, width: int = 80) -> str:
    """Riflusso del testo a N colonne."""
    paragraphs = re.split(r"\n{2,}", text)
    wrapped = []
    for para in paragraphs:
        lines = para.split("\n")
        joined = " ".join(l.strip() for l in lines if l.strip())
        if joined:
            wrapped.append(textwrap.fill(joined, width=width))
        else:
            wrapped.append("")
    return "\n\n".join(wrapped)


# ─── Operazioni su EditorWidget ───────────────────────────────────────────────

def toggle_comment(editor: "EditorWidget") -> None:
    """
    Commenta o decommenta le righe selezionate (o la riga corrente).
    Rileva automaticamente se commentare o decommentare in base alla
    prima riga selezionata.
    """
    from editor.lexers import get_comment_chars, get_language_name
    lang = get_language_name(editor)
    line_char, _ = get_comment_chars(lang)

    if editor.hasSelectedText():
        line_from, _, line_to, _ = editor.getSelection()
    else:
        line_from = line_to = editor.getCursorPosition()[0]

    # Determina se commentare o decommentare
    first_line = editor.text(line_from).lstrip()
    should_uncomment = first_line.startswith(line_char)

    editor.beginUndoAction()
    for line_num in range(line_from, line_to + 1):
        line_text = editor.text(line_num)
        if should_uncomment:
            # Rimuove il commento mantenendo l'indentazione
            stripped = line_text.lstrip()
            if stripped.startswith(line_char):
                indent = len(line_text) - len(stripped)
                new_text = line_text[:indent] + stripped[len(line_char):]
                # Rimuove uno spazio dopo il commento se presente
                if new_text[indent:].startswith(" "):
                    new_text = new_text[:indent] + new_text[indent+1:]
            else:
                new_text = line_text
        else:
            # Aggiunge il commento dopo l'indentazione
            stripped = line_text.lstrip()
            indent = len(line_text) - len(stripped)
            if stripped:
                new_text = line_text[:indent] + line_char + " " + stripped
            else:
                new_text = line_text  # riga vuota, non commentare

        # Sostituisce la riga
        _replace_line(editor, line_num, new_text)

    editor.endUndoAction()


def comment_lines(editor: "EditorWidget", uncomment: bool = False) -> None:
    """Commenta o decommenta esplicitamente le righe selezionate."""
    from editor.lexers import get_comment_chars, get_language_name
    lang = get_language_name(editor)
    line_char, _ = get_comment_chars(lang)

    if editor.hasSelectedText():
        line_from, _, line_to, _ = editor.getSelection()
    else:
        line_from = line_to = editor.getCursorPosition()[0]

    editor.beginUndoAction()
    for line_num in range(line_from, line_to + 1):
        line_text = editor.text(line_num)
        stripped = line_text.lstrip()
        indent = len(line_text) - len(stripped)

        if uncomment:
            if stripped.startswith(line_char):
                rest = stripped[len(line_char):]
                if rest.startswith(" "):
                    rest = rest[1:]
                new_text = line_text[:indent] + rest
            else:
                new_text = line_text
        else:
            if stripped:
                new_text = line_text[:indent] + line_char + " " + stripped
            else:
                new_text = line_text

        _replace_line(editor, line_num, new_text)
    editor.endUndoAction()


def _replace_line(editor: "EditorWidget", line_num: int, new_text: str) -> None:
    """Sostituisce il testo di una riga (senza il \\n finale)."""
    line_text = editor.text(line_num)
    # Mantieni il terminatore di riga originale
    eol = ""
    if line_text.endswith("\r\n"):
        eol = "\r\n"
        line_text = line_text[:-2]
    elif line_text.endswith("\n"):
        eol = "\n"
        line_text = line_text[:-1]
    elif line_text.endswith("\r"):
        eol = "\r"
        line_text = line_text[:-1]

    # Rimuove il newline da new_text se presente
    new_text_clean = new_text.rstrip("\r\n")

    editor.setSelection(line_num, 0, line_num, len(line_text))
    editor.replaceSelectedText(new_text_clean)


def smart_indent(editor: "EditorWidget") -> None:
    """
    Indentazione intelligente: adatta l'indentazione della riga corrente
    al contesto (apertura/chiusura blocchi).
    Delega a QScintilla se il lexer supporta l'auto-indent.
    """
    # QScintilla gestisce già l'auto-indent nativo
    # Qui implementiamo la logica aggiuntiva per linguaggi che ne hanno bisogno
    editor.autoIndent()


def duplicate_selection_or_line(editor: "EditorWidget") -> None:
    """Duplica la selezione corrente o la riga intera."""
    if editor.hasSelectedText():
        text = editor.selectedText()
        # Muove alla fine della selezione e inserisce
        _, _, line_to, col_to = editor.getSelection()
        editor.setCursorPosition(line_to, col_to)
        editor.insert(text)
    else:
        editor.duplicate_line()

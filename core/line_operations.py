"""
core/line_operations.py — Operazioni su righe
NotePadPQ

Tutte le operazioni del menu Line Operations:
sort, dedup, remove empty, keep unique, every-nth, ecc.
Operano sul testo completo del documento o sulla selezione.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget


# ─── Funzioni pure su lista di righe ─────────────────────────────────────────

def sort_lines_asc(lines: list[str]) -> list[str]:
    return sorted(lines, key=str.casefold)


def sort_lines_desc(lines: list[str]) -> list[str]:
    return sorted(lines, key=str.casefold, reverse=True)


def remove_duplicate_sorted(lines: list[str]) -> list[str]:
    """Rimuove duplicati dopo ordinamento (mantiene l'ordine originale dei primi)."""
    seen = set()
    result = []
    for line in lines:
        key = line.strip()
        if key not in seen:
            seen.add(key)
            result.append(line)
    return result


def remove_duplicate_ordered(lines: list[str]) -> list[str]:
    """Rimuove duplicati mantenendo solo la prima occorrenza."""
    return remove_duplicate_sorted(lines)


def remove_unique_lines(lines: list[str]) -> list[str]:
    """Rimuove le righe che appaiono una sola volta."""
    from collections import Counter
    counts = Counter(line.strip() for line in lines)
    return [l for l in lines if counts[l.strip()] > 1]


def keep_unique_lines(lines: list[str]) -> list[str]:
    """Mantiene solo le righe che appaiono una sola volta."""
    from collections import Counter
    counts = Counter(line.strip() for line in lines)
    return [l for l in lines if counts[l.strip()] == 1]


def remove_empty_lines(lines: list[str]) -> list[str]:
    return [l for l in lines if l.strip()]


def remove_whitespace_lines(lines: list[str]) -> list[str]:
    """Rimuove righe composte solo da spazi/tab."""
    return [l for l in lines if l.strip() or not l.replace("\t", "").replace(" ", "")]


def remove_every_nth(lines: list[str], n: int) -> list[str]:
    """Rimuove ogni N-esima riga (1-based)."""
    return [l for i, l in enumerate(lines, 1) if i % n != 0]


# ─── Operazioni su EditorWidget ───────────────────────────────────────────────

def _apply_line_op(editor: "EditorWidget", op) -> None:
    """
    Applica un'operazione sulle righe al testo selezionato o all'intero documento.
    Usa beginUndoAction/endUndoAction per mantenere la stack undo di Scintilla
    e replaceSelectedText invece di setText (che la azzererebbe).
    """
    editor.beginUndoAction()
    try:
        if editor.hasSelectedText():
            text = editor.selectedText()
            lines = text.split("\n")
            result = op(lines)
            editor.replaceSelectedText("\n".join(result))
        else:
            cursor = editor.getCursorPosition()
            text = editor.text()
            lines = text.split("\n")
            result = op(lines)
            new_text = "\n".join(result)
            # selectAll + replace preserva la undo stack; setText la azzera
            editor.selectAll()
            editor.replaceSelectedText(new_text)
            line = min(cursor[0], max(0, editor.lines() - 1))
            col  = min(cursor[1], len(editor.text(line)) if editor.lines() > line else 0)
            editor.setCursorPosition(line, col)
    finally:
        editor.endUndoAction()


def apply_sort_asc(editor: "EditorWidget") -> None:
    _apply_line_op(editor, sort_lines_asc)


def apply_sort_desc(editor: "EditorWidget") -> None:
    _apply_line_op(editor, sort_lines_desc)


def apply_remove_dup_sorted(editor: "EditorWidget") -> None:
    _apply_line_op(editor, remove_duplicate_sorted)


def apply_remove_dup_ordered(editor: "EditorWidget") -> None:
    _apply_line_op(editor, remove_duplicate_ordered)


def apply_remove_unique(editor: "EditorWidget") -> None:
    _apply_line_op(editor, remove_unique_lines)


def apply_keep_unique(editor: "EditorWidget") -> None:
    _apply_line_op(editor, keep_unique_lines)


def apply_remove_empty(editor: "EditorWidget") -> None:
    _apply_line_op(editor, remove_empty_lines)


def apply_remove_whitespace(editor: "EditorWidget") -> None:
    _apply_line_op(editor, remove_whitespace_lines)


def apply_remove_every_nth(editor: "EditorWidget", n: int) -> None:
    _apply_line_op(editor, lambda lines: remove_every_nth(lines, n))


def sort_lines_by_length(lines: list[str]) -> list[str]:
    return sorted(lines, key=lambda l: len(l))


def sort_lines_by_length_desc(lines: list[str]) -> list[str]:
    return sorted(lines, key=lambda l: len(l), reverse=True)


def sort_lines_random(lines: list[str]) -> list[str]:
    import random
    result = list(lines)
    random.shuffle(result)
    return result


def apply_sort_by_length(editor: "EditorWidget") -> None:
    _apply_line_op(editor, sort_lines_by_length)


def apply_sort_by_length_desc(editor: "EditorWidget") -> None:
    _apply_line_op(editor, sort_lines_by_length_desc)


def apply_sort_random(editor: "EditorWidget") -> None:
    _apply_line_op(editor, sort_lines_random)

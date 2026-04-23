"""
ui/bookmarks.py — Gestione bookmark
NotePadPQ

Bookmark visualizzati come simbolo (stellina blu) sul margine simboli.
Usa i marker nativi di QScintilla (markerDefine/markerAdd/markerDelete).

Uso:
    toggle_bookmark(editor)        # aggiunge/rimuove sul cursore corrente
    next_bookmark(editor)          # vai al prossimo bookmark
    prev_bookmark(editor)          # vai al precedente
    clear_all_bookmarks(editor)    # rimuove tutti
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from PyQt6.QtGui import QColor
from PyQt6.Qsci import QsciScintilla

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

# Numero marker QScintilla per i bookmark (0-31, evitiamo quelli usati altrove)
MARKER_BOOKMARK = 10

# Maschera per la ricerca (1 << MARKER_BOOKMARK)
MARKER_MASK = 1 << MARKER_BOOKMARK


def _ensure_marker_defined(editor: "EditorWidget") -> None:
    """
    Definisce il marker bookmark sull'editor se non ancora fatto.
    Chiamato lazy al primo uso.
    """
    if getattr(editor, "_bookmark_marker_defined", False):
        return

    # Usa Circle come simbolo bookmark — disponibile in tutte le versioni QScintilla
    # (RoundedRectangle non è esposto come enum in PyQt6-QScintilla)
    try:
        editor.markerDefine(QsciScintilla.MarkerSymbol.Circle, MARKER_BOOKMARK)
    except AttributeError:
        # Fallback al numero intero diretto (SC_MARK_CIRCLE = 0)
        editor.markerDefine(0, MARKER_BOOKMARK)

    # Colore azzurro vivace — ben visibile su tutti i temi
    editor.setMarkerBackgroundColor(QColor("#2196F3"), MARKER_BOOKMARK)
    editor.setMarkerForegroundColor(QColor("#ffffff"), MARKER_BOOKMARK)

    editor._bookmark_marker_defined = True


def toggle_bookmark(editor: "EditorWidget") -> None:
    """Aggiunge o rimuove il bookmark sulla riga corrente."""
    _ensure_marker_defined(editor)
    line, _ = editor.getCursorPosition()

    # Controlla se la riga ha già un bookmark
    markers_on_line = editor.markersAtLine(line)
    if markers_on_line & MARKER_MASK:
        # Rimuovi
        editor.markerDelete(line, MARKER_BOOKMARK)
    else:
        # Aggiungi
        editor.markerAdd(line, MARKER_BOOKMARK)


def next_bookmark(editor: "EditorWidget") -> None:
    """Sposta il cursore al prossimo bookmark."""
    _ensure_marker_defined(editor)
    line, _ = editor.getCursorPosition()

    # Cerca forward dalla riga successiva
    next_line = editor.markerFindNext(line + 1, MARKER_MASK)

    if next_line == -1:
        # Wrap: ricomincia dall'inizio
        next_line = editor.markerFindNext(0, MARKER_MASK)

    if next_line != -1 and next_line != line:
        editor.setCursorPosition(next_line, 0)
        editor.ensureLineVisible(next_line)
        editor.setFocus()


def prev_bookmark(editor: "EditorWidget") -> None:
    """Sposta il cursore al bookmark precedente."""
    _ensure_marker_defined(editor)
    line, _ = editor.getCursorPosition()

    # Cerca backward dalla riga precedente
    prev_line = editor.markerFindPrevious(line - 1, MARKER_MASK)

    if prev_line == -1:
        # Wrap: ricomincia dalla fine
        prev_line = editor.markerFindPrevious(editor.lines() - 1, MARKER_MASK)

    if prev_line != -1 and prev_line != line:
        editor.setCursorPosition(prev_line, 0)
        editor.ensureLineVisible(prev_line)
        editor.setFocus()


def clear_all_bookmarks(editor: "EditorWidget") -> None:
    """Rimuove tutti i bookmark dal documento."""
    _ensure_marker_defined(editor)
    editor.markerDeleteAll(MARKER_BOOKMARK)


def get_all_bookmarks(editor: "EditorWidget") -> list[int]:
    """Restituisce la lista delle righe con bookmark (0-based)."""
    _ensure_marker_defined(editor)
    bookmarks = []
    line = editor.markerFindNext(0, MARKER_MASK)
    while line != -1:
        bookmarks.append(line)
        line = editor.markerFindNext(line + 1, MARKER_MASK)
    return bookmarks

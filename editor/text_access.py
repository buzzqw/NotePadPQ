"""editor/text_access.py - Letture limitate dal buffer di Scintilla."""

from __future__ import annotations

_LONG_LINE_BYTES = 4096


def text_before_cursor(editor, line: int, col: int) -> str:
    """Testo della riga prima di ``col``, senza copiare le righe enormi.

    Il contesto di completamento guarda solo gli ultimi caratteri, ma
    ``editor.text(line)`` decodifica tutta la riga: su un file minificato sono
    megabyte a ogni tasto. Oltre la soglia si leggono solo gli ultimi KB.
    """
    try:
        if editor.SendScintilla(editor.SCI_LINELENGTH, line) > _LONG_LINE_BYTES:
            end = editor.positionFromLineIndex(line, col)
            start = max(editor.SendScintilla(editor.SCI_POSITIONFROMLINE, line),
                        end - _LONG_LINE_BYTES)
            buf = bytearray(end - start + 1)
            editor.SendScintilla(editor.SCI_GETTEXTRANGE, start, end, buf)
            return bytes(buf[:end - start]).decode("utf-8", "ignore")
    except (AttributeError, TypeError):
        pass  # editor di test con la sola API text()
    return editor.text(line)[:col]

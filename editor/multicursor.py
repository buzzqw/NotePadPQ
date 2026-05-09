"""
editor/multicursor.py — Multi-cursor / multiple-selection manager.

Usa le API native di Scintilla (SCI_SETMULTIPLESELECTION,
SCI_SETADDITIONALSELECTIONTYPING, SCI_MULTIPLESELECTADDNEXT, …)
per un multi-cursore reale: la digitazione, backspace, delete, ecc.
agiscono su tutti i cursori simultaneamente.

Collegamento: EditorWidget.__init__ crea self._multicursor = MultiCursorManager(self).
"""

from PyQt6.QtGui import QColor
from PyQt6.Qsci import QsciScintilla


class MultiCursorManager:
    """
    Gestisce il multi-cursore su un EditorWidget.

    Utilizzo tipico (già cablato in main_window.py):
        mc = editor._multicursor
        mc.select_next_occurrence()     # Ctrl+D
        mc.select_all_occurrences()     # Ctrl+Shift+D
        mc.add_cursor_above()           # Ctrl+Alt+Up
        mc.add_cursor_below()           # Ctrl+Alt+Down
        mc.insert_incremental_numbers() # Ctrl+Shift+Alt+C
        mc.clear_extra_cursors()        # Escape
    """

    def __init__(self, editor: QsciScintilla) -> None:
        self._ed = editor
        self._active = False

    # ── Attivazione / disattivazione ─────────────────────────────────────────

    def _activate(self) -> None:
        if self._active:
            return
        ed = self._ed
        ed.SendScintilla(QsciScintilla.SCI_SETMULTIPLESELECTION, 1)
        ed.SendScintilla(QsciScintilla.SCI_SETADDITIONALSELECTIONTYPING, 1)
        # Ogni selezione viene incollata separatamente (comportamento VS Code)
        ed.SendScintilla(QsciScintilla.SCI_SETMULTIPASTE,
                         QsciScintilla.SC_MULTIPASTE_EACH)
        # Colore selezioni aggiuntive: stessa tinta della principale, leggermente
        # più trasparente, così si distinguono visivamente
        ed.SendScintilla(QsciScintilla.SCI_SETADDITIONALSELALPHA, 120)
        ed.SendScintilla(QsciScintilla.SCI_SETADDITIONALSELBACK, 1,
                         QColor("#264f78"))
        ed.SendScintilla(QsciScintilla.SCI_SETADDITIONALCARETSVISIBLE, 1)
        self._active = True

    def _deactivate(self) -> None:
        if not self._active:
            return
        ed = self._ed
        ed.SendScintilla(QsciScintilla.SCI_SETMULTIPLESELECTION, 0)
        ed.SendScintilla(QsciScintilla.SCI_SETADDITIONALSELECTIONTYPING, 0)
        self._active = False

    # ── API pubblica ──────────────────────────────────────────────────────────

    def select_next_occurrence(self) -> None:
        """
        Ctrl+D — prima chiamata: seleziona la parola sotto il cursore.
        Chiamate successive: aggiunge la prossima occorrenza come selezione extra.
        """
        self._activate()
        self._ed.SendScintilla(QsciScintilla.SCI_MULTIPLESELECTADDNEXT)

    def select_all_occurrences(self) -> None:
        """
        Ctrl+Shift+D — seleziona tutte le occorrenze della parola/selezione corrente.
        """
        self._activate()
        self._ed.SendScintilla(QsciScintilla.SCI_MULTIPLESELECTADDEACH)

    def add_cursor_above(self) -> None:
        """Ctrl+Alt+Up — aggiunge un cursore sulla riga sopra il cursore più in alto."""
        self._add_cursor_vertical(-1)

    def add_cursor_below(self) -> None:
        """Ctrl+Alt+Down — aggiunge un cursore sulla riga sotto il cursore più in basso."""
        self._add_cursor_vertical(1)

    def insert_incremental_numbers(self) -> None:
        """
        Ctrl+Shift+Alt+C — sostituisce ogni selezione con un numero incrementale
        (1, 2, 3… in ordine dall'alto verso il basso).
        """
        ed = self._ed
        n_sel = ed.SendScintilla(QsciScintilla.SCI_GETSELECTIONS)
        if n_sel <= 1:
            return

        # Raccoglie (start, end) per ogni selezione, ordina dall'alto al basso
        ranges = []
        for i in range(n_sel):
            caret  = ed.SendScintilla(QsciScintilla.SCI_GETSELECTIONNCARET, i)
            anchor = ed.SendScintilla(QsciScintilla.SCI_GETSELECTIONNANCHOR, i)
            ranges.append((min(caret, anchor), max(caret, anchor)))
        ranges.sort()

        # Inserisce dal basso verso l'alto così le posizioni precedenti rimangono valide
        ed.beginUndoAction()
        try:
            for idx, (start, end) in enumerate(reversed(ranges)):
                number = str(len(ranges) - idx)
                lf, cf = ed.lineIndexFromPosition(start)
                lt, ct = ed.lineIndexFromPosition(end)
                ed.setSelection(lf, cf, lt, ct)
                ed.replaceSelectedText(number)
        finally:
            ed.endUndoAction()

        self.clear_extra_cursors()

    def clear_extra_cursors(self) -> None:
        """
        Escape — rimuove tutte le selezioni extra, mantiene solo quella principale.
        """
        ed = self._ed
        n_sel = ed.SendScintilla(QsciScintilla.SCI_GETSELECTIONS)
        if n_sel <= 1 and not self._active:
            return

        main_idx = ed.SendScintilla(QsciScintilla.SCI_GETMAINSELECTION)
        caret  = ed.SendScintilla(QsciScintilla.SCI_GETSELECTIONNCARET,  main_idx)
        anchor = ed.SendScintilla(QsciScintilla.SCI_GETSELECTIONNANCHOR, main_idx)
        # SCI_SETSELECTION sostituisce tutte le selezioni con una singola
        ed.SendScintilla(QsciScintilla.SCI_SETSELECTION, caret, anchor)
        self._deactivate()

    # ── Internals ─────────────────────────────────────────────────────────────

    def _add_cursor_vertical(self, delta: int) -> None:
        """Aggiunge un cursore sulla riga delta sopra/sotto il cursore di riferimento."""
        ed = self._ed
        n_sel = ed.SendScintilla(QsciScintilla.SCI_GETSELECTIONS)

        # Posizioni di tutti i carets attuali
        carets = [
            ed.SendScintilla(QsciScintilla.SCI_GETSELECTIONNCARET, i)
            for i in range(n_sel)
        ]

        # Riferimento: cursore più in alto per "sopra", più in basso per "sotto"
        ref_caret = min(carets) if delta < 0 else max(carets)
        line, col = ed.lineIndexFromPosition(ref_caret)
        new_line  = line + delta

        if new_line < 0 or new_line >= ed.lines():
            return

        # Tronca la colonna alla lunghezza reale della riga (senza newline)
        line_text = ed.text(new_line)
        eol_chars = 2 if line_text.endswith('\r\n') else (
                    1 if line_text.endswith(('\n', '\r')) else 0)
        max_col  = max(0, len(line_text) - eol_chars)
        new_col  = min(col, max_col)
        new_pos  = ed.positionFromLineIndex(new_line, new_col)

        self._activate()
        ed.SendScintilla(QsciScintilla.SCI_ADDSELECTION, new_pos, new_pos)

        # Il cursore appena aggiunto diventa quello principale per
        # poter continuare a premere il tasto nella stessa direzione
        ed.SendScintilla(QsciScintilla.SCI_SETMAINSELECTION, n_sel)
        ed.SendScintilla(QsciScintilla.SCI_SCROLLCARET)

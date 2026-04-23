"""
ui/line_operations_menu.py — Submenu Line Operations
NotePadPQ

Funzione helper che popola il submenu Strumenti → Line Operations.
Separato da main_window.py per tenere il file principale più leggero.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QInputDialog

from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


def build_line_ops_menu(menu: QMenu, main_window: "MainWindow") -> None:
    """Aggiunge tutte le voci Line Operations al menu dato."""

    def _act(label: str, slot) -> QAction:
        a = QAction(label, main_window)
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    def _editor():
        return main_window._tab_manager.current_editor()

    def _run(fn_name: str):
        """Restituisce uno slot che chiama fn_name(editor) da line_operations."""
        def slot():
            ed = _editor()
            if ed:
                import core.line_operations as lo
                getattr(lo, fn_name)(ed)
        return slot

    _act(tr("action.sort_asc"),          _run("apply_sort_asc"))
    _act(tr("action.sort_desc"),         _run("apply_sort_desc"))
    _act("Ordina per lunghezza (↑)",     _run("apply_sort_by_length"))
    _act("Ordina per lunghezza (↓)",     _run("apply_sort_by_length_desc"))
    _act("Ordina casualmente",           _run("apply_sort_random"))
    menu.addSeparator()
    _act(tr("action.remove_dup_sorted"), _run("apply_remove_dup_sorted"))
    _act(tr("action.remove_dup_ordered"),_run("apply_remove_dup_ordered"))
    _act(tr("action.remove_unique"),     _run("apply_remove_unique"))
    _act(tr("action.keep_unique"),       _run("apply_keep_unique"))
    menu.addSeparator()
    _act(tr("action.remove_empty"),      _run("apply_remove_empty"))
    _act(tr("action.remove_whitespace"), _run("apply_remove_whitespace"))
    menu.addSeparator()

    def remove_nth():
        ed = _editor()
        if not ed:
            return
        n, ok = QInputDialog.getInt(
            main_window, tr("action.remove_every_nth"),
            "Rimuovi ogni N-esima riga (N):", 2, 2, 100
        )
        if ok:
            import core.line_operations as lo
            lo.apply_remove_every_nth(ed, n)

    _act(tr("action.remove_every_nth"), remove_nth)

"""Liste risultati di Cerca/Sostituisci: snippet e pulsanti disegnati da
delegate invece che da un QLabel/QPushButton per riga."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QLabel, QPushButton, QTreeWidget, QTreeWidgetItem

from ui.find_replace import (
    _ROW_BUTTON_ROLE,
    _SNIPPET_HL_ROLE,
    FindReplaceDialog,
    _FindInFilesResult,
    _install_result_delegates,
    _results_stylesheet,
)

LINE = "Il mago lancia un incantesimo di protezione contro il drago"


def _tree_with_rows(qtbot, on_button, rows=3):
    tree = QTreeWidget()
    qtbot.addWidget(tree)
    tree.setColumnCount(3)
    tree.setStyleSheet(_results_stylesheet())
    _install_result_delegates(tree, snippet_column=1, button_column=2,
                              button_text="Replace", on_button=on_button)
    items = []
    for i in range(rows):
        item = QTreeWidgetItem([str(i + 1), LINE, ""])
        item.setData(1, _SNIPPET_HL_ROLE, (18, 29))
        item.setData(2, _ROW_BUTTON_ROLE, True)
        items.append(item)
    tree.addTopLevelItems(items)
    tree.resize(700, 200)
    tree.setColumnWidth(0, 40)
    tree.setColumnWidth(1, 500)
    tree.setColumnWidth(2, 90)
    tree.show()
    qtbot.waitExposed(tree)
    return tree, items


def test_drawn_button_runs_the_action_for_its_row_only(qtbot):
    calls = []
    tree, items = _tree_with_rows(qtbot, calls.append)
    button_cell = tree.visualItemRect(items[1])
    button_cell.setLeft(tree.header().sectionPosition(2))
    button_cell.setWidth(tree.header().sectionSize(2))
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=button_cell.center())
    assert calls == [items[1]]

    # Un click sul testo seleziona la riga ma non esegue la sostituzione.
    text_cell = tree.visualItemRect(items[2])
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton,
                     pos=QPoint(tree.header().sectionPosition(1) + 20, text_cell.center().y()))
    assert calls == [items[1]]
    assert tree.currentItem() is items[2]


def test_snippet_paints_the_match_highlight(qtbot):
    tree, items = _tree_with_rows(qtbot, lambda _item: None, rows=1)
    image = tree.viewport().grab().toImage()
    row = tree.visualItemRect(items[0])
    highlight = QColor("#ffd54f").rgb()
    hits = sum(
        1 for x in range(tree.header().sectionPosition(1), tree.header().sectionPosition(2))
        if image.pixel(x, row.center().y()) == highlight
    )
    assert hits > 20  # la parola "incantesimo" ha lo sfondo giallo


def _dialog_for_fif(tree: QTreeWidget) -> FindReplaceDialog:
    dialog = FindReplaceDialog.__new__(FindReplaceDialog)
    dialog._mw = None
    dialog._fif_total_matches = 0
    dialog._fif_results = tree
    return dialog


def test_find_in_files_rows_have_no_per_row_widgets_and_keep_their_text(qtbot):
    tree = QTreeWidget()
    qtbot.addWidget(tree)
    tree.setColumnCount(3)
    dialog = _dialog_for_fif(tree)
    entries = [_FindInFilesResult("a.tex", "/x/a.tex", i + 1, LINE, 18, 29) for i in range(500)]
    FindReplaceDialog._on_fif_file_result(dialog, "a.tex", "/x/a.tex", 500, entries)

    file_item = tree.topLevelItem(0)
    assert file_item.childCount() == 500
    # Solo il pulsante "sostituisci nel file" resta un widget vero.
    assert len(tree.findChildren(QPushButton)) == 1
    assert not tree.findChildren(QLabel)
    child = file_item.child(0)
    # Il testo è nell'item: il pannello risultati (child.text(1)) non lo
    # riceveva più vuoto come quando lo snippet stava in una QLabel.
    snippet = child.text(1)
    start, end = child.data(1, _SNIPPET_HL_ROLE)
    assert "incantesimo" in snippet and snippet[start:end] == "incantesimo"
    assert child.data(2, _ROW_BUTTON_ROLE) is True
    assert file_item.data(2, _ROW_BUTTON_ROLE) is None


def test_result_panel_receives_the_snippet_text(qtbot):
    tree = QTreeWidget()
    qtbot.addWidget(tree)
    tree.setColumnCount(3)
    dialog = _dialog_for_fif(tree)
    entries = [_FindInFilesResult("a.tex", "/x/a.tex", 7, LINE, 18, 29)]
    FindReplaceDialog._on_fif_file_result(dialog, "a.tex", "/x/a.tex", 1, entries)
    panel = mock.Mock()
    dialog._mw = SimpleNamespace(_find_result_panel=panel)
    FindReplaceDialog._send_to_result_panel(dialog, "incantesimo", tree)
    results = panel.method_calls[-1].args[1] if panel.method_calls else []
    assert results and "incantesimo" in results[0]["text"]

"""Regressioni delle ottimizzazioni: il comportamento deve restare identico."""

import sys
from unittest import mock

import pytest
from PyQt6.Qsci import QsciScintilla
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from core.latex_project import resolve_project_root
from core.lazy_import import LazyModule
from editor.autocomplete import _CompletionIndex
from editor.editor_widget import _FAST_TYPING_MIN_BYTES, EditorWidget
from editor.text_access import text_before_cursor

LARGE_TEXT = "alfa beta\n" * (_FAST_TYPING_MIN_BYTES // 10 + 10)


def test_empty_buffer_does_not_pick_unrelated_sibling_as_root(tmp_path):
    (tmp_path / "a_other.tex").write_text("\\documentclass{book}\n", encoding="utf-8")
    current = tmp_path / "z_current.tex"
    current.write_text("\\documentclass{article}\n", encoding="utf-8")
    assert resolve_project_root(current, "") == current.resolve()


def test_completion_index_keeps_source_order_and_strips_metadata():
    index = _CompletionIndex(["zeta", "Alfa?1", "alba\ndoc", "beta", "", "alfa"])
    assert index.matches("al") == [("alfa", "Alfa"), ("alba", "alba"), ("alfa", "alfa")]
    assert index.matches("x") == []


def test_lazy_module_defers_import_and_resolves_submodules():
    name = "colorsys"
    sys.modules.pop(name, None)
    lazy = LazyModule(name)
    assert name not in sys.modules
    assert lazy.rgb_to_hsv(0, 0, 0) == (0.0, 0.0, 0.0)
    assert LazyModule("urllib").parse.quote(" ") == "%20"
    with pytest.raises(AttributeError):
        _ = LazyModule("urllib").does_not_exist


def test_text_before_cursor_reads_only_the_tail_of_long_lines(qtbot):
    editor = QsciScintilla()
    qtbot.addWidget(editor)
    editor.setUtf8(True)
    editor.setText("é" * 10_000 + "fine resto")
    tail = text_before_cursor(editor, 0, 10_004)
    assert tail.endswith("éfine") and len(tail) < 5000
    editor.setText("corta")
    assert text_before_cursor(editor, 0, 3) == "cor"


@pytest.fixture
def large_editor(qtbot):
    editor = EditorWidget()
    qtbot.addWidget(editor)
    editor._fast_typing = True
    editor.load_content(LARGE_TEXT)
    editor.show()
    editor.setFocus()
    return editor


@pytest.mark.parametrize("key,delta", [("x", 1), (Qt.Key.Key_Backspace, -1)])
def test_fast_typing_notifies_once_and_restores_mask(large_editor, qtbot, key, delta):
    editor = large_editor
    mask = editor.SendScintilla(editor.SCI_GETMODEVENTMASK)
    editor.setCursorPosition(100, 3)
    before = editor.length()
    changed = []
    editor.textChanged.connect(lambda: changed.append(editor.length()))
    QTest.keyClick(editor, key)
    assert editor.length() == before + delta
    assert changed == [before + delta]
    assert editor.isModified()
    assert editor.SendScintilla(editor.SCI_GETMODEVENTMASK) == mask
    editor.undo()
    assert editor.length() == before


def test_fast_typing_reports_new_lines(large_editor):
    editor = large_editor
    lines = []
    editor.linesChanged.connect(lambda: lines.append(editor.lines()))
    total = editor.lines()
    editor.setCursorPosition(100, 3)
    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert editor.lines() == total + 1
    assert lines == [total + 1]


def test_fast_typing_skips_noop_and_read_only(large_editor):
    editor = large_editor
    changed = []
    editor.textChanged.connect(lambda: changed.append(1))
    editor.setCursorPosition(0, 0)
    QTest.keyClick(editor, Qt.Key.Key_Backspace)
    assert changed == []
    editor.setReadOnly(True)
    QTest.keyClick(editor, "x")
    assert changed == []


def test_char_added_slots_see_text_changed_already_emitted(large_editor):
    editor = large_editor
    events = []
    editor.textChanged.connect(lambda: events.append("text"))
    editor.SCN_CHARADDED.connect(lambda _c: events.append("char"))
    editor.setCursorPosition(100, 3)
    QTest.keyClick(editor, "x")
    assert events == ["text", "char"]


def test_bulk_edit_emits_single_change_and_restores_mask(large_editor):
    editor = large_editor
    mask = editor.SendScintilla(editor.SCI_GETMODEVENTMASK)
    changed = []
    editor.textChanged.connect(lambda: changed.append(1))
    with editor.bulk_edit():
        editor.insertAt("uno", 1, 0)
        editor.insertAt("due", 2, 0)
    assert changed == [1]
    assert editor.text(1).startswith("uno") and editor.text(2).startswith("due")
    assert editor.SendScintilla(editor.SCI_GETMODEVENTMASK) == mask


def test_latex_lexer_sees_new_text_after_silent_edit(qtbot):
    from editor.lexers import set_lexer_by_extension

    editor = EditorWidget()
    qtbot.addWidget(editor)
    editor._fast_typing = True
    set_lexer_by_extension(editor, ".tex")
    editor.load_content(LARGE_TEXT)
    editor.show()
    editor.setFocus()
    lexer = editor.lexer()
    lexer.styleText(0, 200)
    assert lexer._bytes_cache is not None
    editor.setCursorPosition(0, 0)
    QTest.keyClick(editor, "Z")
    lexer.styleText(0, 200)
    assert lexer._bytes_cache.startswith(b"Zalfa")


def test_pdf_document_pool_reuses_and_invalidates(tmp_path):
    from ui.preview_panel import _PdfDocumentPool

    path = tmp_path / "x.pdf"
    path.write_bytes(b"uno")
    docs = [mock.Mock(name="d1"), mock.Mock(name="d2")]
    pool = _PdfDocumentPool()
    with mock.patch("fitz.open", side_effect=docs) as opener:
        first, lease = pool.acquire(str(path))
        pool.release(first, lease)
        again, lease = pool.acquire(str(path))
        assert again is first and opener.call_count == 1
        pool.release(again, lease)
        path.write_bytes(b"due, ricompilato")
        fresh, lease = pool.acquire(str(path))
        assert fresh is docs[1]
        docs[0].close.assert_called_once()
        pool.clear()  # un documento in prestito si chiude alla restituzione
        pool.release(fresh, lease)
        docs[1].close.assert_called_once()


def test_virtual_pdf_pages_layout_and_clicks(qtbot):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QPixmap

    from ui.preview_panel import _PdfContContainer

    container = _PdfContContainer()
    qtbot.addWidget(container)
    container.resize(800, 400)
    pages = container.create_pages(3)
    for page in pages:
        page.setFixedSize(600, 1000)
    container.relayout()
    assert [page.y() for page in pages] == [8, 1025, 2042]
    assert container.minimumHeight() == 3050
    assert pages[0].x() == 100
    assert not container.findChildren(QPixmap)
    clicks = []
    container.on_page_clicked = lambda *args: clicks.append(args)
    QTest.mouseClick(container, Qt.MouseButton.LeftButton, pos=QPoint(150, 1035))
    QTest.mouseClick(container, Qt.MouseButton.LeftButton, pos=QPoint(150, 1015))  # spazio
    assert clicks == [(1, 50, 10)]
    pixmap = QPixmap(600, 1000)
    pages[1].setPixmap(pixmap)
    assert pages[1].pixmap() is pixmap
    pages[1].clear()
    assert pages[1].pixmap() is None
    container.grab()  # paintEvent senza errori

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import QApplication

from editor.editor_widget import _SpellWorker
from plugins.clipboard_history_plugin import MAX_ITEM_BYTES, _ClipboardPanel
from plugins.hex_viewer_plugin import SEARCH_CHUNK, _HexPanel, _HexSearchWorker
from plugins.search_results_plugin import (
    _FileReplaceWorker,
    _merge_search_results,
    _SearchResultsPanel,
)
from ui.preview_panel import PreviewPanel, _PdfRenderWorker


class _Checker:
    def unknown(self, words):
        return {word for word in words if word == "mispelled"}


class _TabManager:
    def __init__(self, editor):
        self._editor = editor

    def current_editor(self):
        return self._editor


class _MainWindow:
    def __init__(self, editor):
        self._tab_manager = _TabManager(editor)


class _Editor:
    def __init__(self, path):
        self.file_path = path


class _NoEncodeText(str):
    def encode(self, *args, **kwargs):
        raise AssertionError("encode non deve essere chiamato per testo certamente enorme")


class _CancellingPattern:
    def __init__(self):
        self.worker = None

    def subn(self, replacement, content):
        self.worker.cancel()
        return replacement, 1


class ResourceOptimizationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_spell_worker_preserves_snapshot_line_offset(self):
        emitted = []
        worker = _SpellWorker(
            "valid words\nmispelled word", _Checker(), frozenset(), 7, base_line=120
        )
        worker.done.connect(lambda generation, positions: emitted.append((generation, positions)))

        worker.run()

        self.assertEqual(emitted, [(7, [(121, 0, 121, 9)])])

    def test_clipboard_atomic_write_replaces_complete_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.enc"
            path.write_bytes(b"old")

            _ClipboardPanel._atomic_write(path, b"new encrypted value", mode=0o600)

            self.assertEqual(path.read_bytes(), b"new encrypted value")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_clipboard_rejects_certainly_huge_text_before_encoding(self):
        panel = mock.Mock()
        panel._history = []
        text = _NoEncodeText("x" * (MAX_ITEM_BYTES + 1))

        _ClipboardPanel._add_to_history(panel, text)

        self.assertEqual(panel._history, [])
        panel._refresh_list.assert_not_called()

    def test_hex_file_uses_mapping_and_releases_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.bin"
            path.write_bytes(bytes(range(64)))
            panel = _HexPanel(_MainWindow(_Editor(path)))

            panel.load_current()

            self.assertIsNone(panel._raw)
            self.assertIsNotNone(panel._mapped)
            self.assertEqual(panel._read_window(10, 4), bytes(range(10, 14)))

            panel.close_source()
            self.assertIsNone(panel._mapped)
            self.assertIsNone(panel._file)

    def test_hex_worker_finds_match_across_chunk_boundary(self):
        needle = b"needle"
        raw = b"x" * (SEARCH_CHUNK - 2) + needle + b"tail"
        emitted = []
        worker = _HexSearchWorker(raw, needle)
        worker.completed.connect(lambda pos, error: emitted.append((pos, error)))

        worker.run()

        self.assertEqual(emitted, [(SEARCH_CHUNK - 2, "")])

    def test_search_append_preserves_results_and_active_operations_scope(self):
        first = {"file": "one.txt", "line": 0, "text": "first"}
        second = {"file": "two.txt", "line": 1, "text": "second"}
        combined = _merge_search_results([], [first], False, 1)
        combined = _merge_search_results(combined, [second], True, 2)
        panel = mock.Mock()
        panel._all_results = combined
        panel._current_result_id = 2

        active = _SearchResultsPanel._current_results(panel)

        self.assertEqual(len(combined), 2)
        self.assertEqual(active, [dict(second, _search_id=2)])

    def test_replace_worker_rejects_files_over_safe_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.txt"
            path.write_text("unchanged", encoding="utf-8")
            statuses = []
            with mock.patch(
                    "plugins.search_results_plugin._FILE_REPLACE_MAX_BYTES", 4):
                worker = _FileReplaceWorker([str(path)], mock.Mock(), "new")
                worker.completed.connect(statuses.append)
                worker.run()

            self.assertEqual(path.read_text(encoding="utf-8"), "unchanged")
            self.assertEqual(statuses[0]["changed_files"], [])
            self.assertIn("safe replace limit", statuses[0]["errors"][0])

    def test_replace_worker_checks_cancellation_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cancel.txt"
            path.write_text("original", encoding="utf-8")
            pattern = _CancellingPattern()
            worker = _FileReplaceWorker([str(path)], pattern, "changed")
            pattern.worker = worker

            worker.run()

            self.assertEqual(path.read_text(encoding="utf-8"), "original")

    def test_pdf_worker_closes_document_when_render_fails(self):
        fitz = pytest.importorskip("fitz")
        doc = mock.MagicMock()
        page = mock.Mock()
        page.get_pixmap.side_effect = RuntimeError("render failed")
        doc.__getitem__.return_value = page
        worker = _PdfRenderWorker(
            "input.pdf", 0, 1.0, {"enabled": False}, None, None, False, 1
        )

        with mock.patch.object(fitz, "open", return_value=doc):
            worker.run()

        doc.close.assert_called_once_with()

    def test_preview_show_event_keeps_deferred_refresh_and_pdf_refresh(self):
        panel = PreviewPanel()
        panel._needs_refresh = True
        panel._mode = "pdf"
        panel._pdf_doc = mock.Mock()

        with mock.patch.object(panel._timer, "start") as start, mock.patch(
            "ui.preview_panel.QTimer.singleShot"
        ) as single_shot:
            panel.showEvent(QShowEvent())

        start.assert_called_once_with(panel._delay_ms)
        single_shot.assert_called_once_with(0, panel._pdf_refresh)
        panel.close()

    def test_latex_tree_includes_project_sources_and_navigates_to_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "main.tex"
            child = root / "chapter.tex"
            main_text = "\\documentclass{article}\n\\input{chapter}\n\\section{Main}\n"
            main.write_text(main_text, encoding="utf-8")
            child.write_text("\\section{Chapter}\n\\label{chapter}\n", encoding="utf-8")
            editor = _Editor(main)
            editor.text = lambda: main_text

            panel = PreviewPanel()
            panel._editor = editor
            panel._render_latex_tree(main_text)

            self.assertEqual(panel._tree.topLevelItemCount(), 2)
            chapter_file = panel._tree.topLevelItem(1)
            chapter_section = chapter_file.child(0)
            location = chapter_section.data(0, Qt.ItemDataRole.UserRole)
            self.assertEqual(location["file"], str(child.resolve()))
            self.assertEqual(location["line"], 0)

            with mock.patch.object(panel, "_goto_tex_line") as goto:
                panel._on_tree_item_clicked(chapter_section, 0)
            goto.assert_called_once_with(str(child.resolve()), 1)
            panel.close()

    def test_preview_switching_editor_cancels_pending_cursor_sync(self):
        panel = PreviewPanel()
        editor = _Editor(Path("/tmp/main.tex"))
        panel._editor = editor
        panel._on_cursor_changed(4, 9)

        panel.set_editor(None)

        self.assertFalse(panel._cursor_sync_timer.isActive())
        panel.close()

    def test_latex_preview_compiles_with_build_manager_and_loads_pdf(self):
        panel = PreviewPanel()
        editor = _Editor(Path("/tmp/main.tex"))
        editor.text = lambda: "\\documentclass{article}"
        panel._editor = editor
        manager = mock.Mock()
        manager.is_running.return_value = False
        manager.run.return_value = True

        with mock.patch("core.build_manager.BuildManager.instance", return_value=manager):
            panel._compile_latex_preview()

        self.assertTrue(panel._latex_compile_enabled)
        manager.run.assert_called_once()
        run_id = manager.run.call_args.kwargs["run_id"]
        pdf_path = Path("/tmp/main.pdf")
        with mock.patch("ui.preview_panel._tex_pdf_path", return_value=pdf_path), \
                mock.patch.object(panel, "set_pdf_path") as set_pdf:
            panel._on_latex_preview_build_done(run_id, True, "ok")

        set_pdf.assert_called_once_with(pdf_path, tex_path=Path("/tmp/main.tex"))
        self.assertFalse(panel._latex_compile_run_id)
        panel.close()

if __name__ == "__main__":
    unittest.main()

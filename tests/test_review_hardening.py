"""Regression tests for the fixes adopted from the agy.md code review.

- Character panel: debounced search over a cached Unicode name index
- AI chat: streamed chunks are batched instead of written per token
- InteractiveBuildWorker: thread-safe input queue (PTY and pipe modes)
- BasePlugin.on_unload really removes its actions from the menus
- SpreadsheetModel: numeric alignment without exception-driven flow
- SafeQThread: a worker survives its owner dropping it from a result slot
"""

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QMainWindow, QMenu


def _app():
    return QApplication.instance() or QApplication([])


class CharacterSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_search_by_name_and_codepoint(self):
        from ui.character_panel import search_unicode_names

        self.assertIn("α", search_unicode_names("greek small letter alpha"))
        self.assertEqual(search_unicode_names("U+00E9"), ["é"])
        self.assertEqual(search_unicode_names("U+ZZZ"), [])
        self.assertEqual(search_unicode_names("   "), [])
        self.assertEqual(len(search_unicode_names("LETTER", limit=7)), 7)

    def test_typing_is_debounced(self):
        from ui.character_panel import CharacterPanel

        mw = QMainWindow()
        panel = CharacterPanel(mw)
        with mock.patch.object(panel, "_on_search") as on_search:
            panel._search.setText("ARROW")
            panel._search.setText("ARROWS")
            on_search.assert_not_called()
            self.assertTrue(panel._search_timer.isActive())
            panel._search_timer.timeout.emit()
            on_search.assert_called_once_with("ARROWS")
        # Switching category cancels a pending search.
        panel._search.setText("X")
        panel._load_category(0)
        self.assertFalse(panel._search_timer.isActive())
        mw.deleteLater()


class _FakeAIPanel(QObject):
    from plugins.ai_plugin import _AIPanel as _P

    _on_stream_chunk = _P._on_stream_chunk
    _on_think_chunk = _P._on_think_chunk
    _flush_stream = _P._flush_stream
    _discard_stream = _P._discard_stream

    def __init__(self):
        super().__init__()
        self.writes = []
        self._has_streaming = False
        self._has_thinking = False
        self._gen_start = self._think_start = 0.0
        self._gen_chars = self._think_chars = 0
        self._think_text_acc = ""
        self._stream_pending = ""
        self._think_pending = ""
        self._stream_flush_timer = QTimer(self)
        self._stream_flush_timer.setSingleShot(True)
        self._stream_flush_timer.setInterval(1000)
        self._stream_flush_timer.timeout.connect(self._flush_stream)

    def _write_stream_chunk(self, chunk):
        self.writes.append(("text", chunk))

    def _write_think_chunk(self, chunk):
        self.writes.append(("think", chunk))


class AIStreamBatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_chunks_are_coalesced_until_flush(self):
        panel = _FakeAIPanel()
        for tok in ("Hel", "lo", " world"):
            panel._on_stream_chunk(tok)
        self.assertEqual(panel.writes, [])
        self.assertTrue(panel._stream_flush_timer.isActive())
        self.assertEqual(panel._gen_chars, len("Hello world"))
        panel._flush_stream()
        self.assertEqual(panel.writes, [("text", "Hello world")])
        self.assertFalse(panel._stream_flush_timer.isActive())

    def test_order_between_answer_and_thinking_is_preserved(self):
        panel = _FakeAIPanel()
        panel._on_stream_chunk("a")
        panel._on_think_chunk("t")
        panel._on_stream_chunk("b")
        panel._flush_stream()
        self.assertEqual(panel.writes, [("text", "a"), ("think", "t"), ("text", "b")])

    def test_discard_drops_pending_output(self):
        panel = _FakeAIPanel()
        panel._on_stream_chunk("x")
        panel._discard_stream()
        panel._flush_stream()
        self.assertEqual(panel.writes, [])


class InteractiveInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _run_echo(self, use_pty: bool):
        from core import build_manager
        from core.build_manager import BUILD_STATE_SUCCEEDED, InteractiveBuildWorker

        cmd = [sys.executable, "-c", "print('got:' + input())"]
        worker = InteractiveBuildWorker(cmd, ".", dict(os.environ), run_id="input")
        output = []
        worker.output_line.connect(output.append)
        worker.send_input("ping\n")
        with mock.patch.object(build_manager, "_has_pty", return_value=use_pty):
            worker.start()
            deadline_ok = worker.wait(10000)
        QApplication.processEvents()
        self.assertTrue(deadline_ok)
        self.assertEqual(worker.state, BUILD_STATE_SUCCEEDED)
        self.assertTrue(any("got:ping" in line for line in output), output)

    def test_pipe_mode_feeds_queued_input(self):
        self._run_echo(use_pty=False)

    @unittest.skipIf(sys.platform.startswith("win"), "PTY is POSIX-only")
    def test_pty_mode_feeds_queued_input(self):
        self._run_echo(use_pty=True)


class PluginUnloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_unload_removes_action_from_menu(self):
        from plugins.base_plugin import BasePlugin

        mw = QMainWindow()
        menu = QMenu("Tools", mw)
        mw._menus = {"tools": menu}
        mw._plugin_icon_actions = []
        plugin = BasePlugin()
        plugin.on_load(mw)
        action = plugin.add_menu_action(mw, "tools", "Do it", lambda: None)
        mw._plugin_icon_actions.append((action, "x"))
        self.assertIn(action, menu.actions())

        plugin.on_unload()

        self.assertNotIn(action, menu.actions())
        self.assertEqual(mw._plugin_icon_actions, [])
        self.assertEqual(plugin._menu_actions, [])
        mw.deleteLater()

    def test_unload_keeps_foreign_submenu_action_alive(self):
        from plugins.base_plugin import BasePlugin

        mw = QMainWindow()
        menu = QMenu("Tools", mw)
        sub = QMenu("Sub", menu)
        menu.addMenu(sub)
        plugin = BasePlugin()
        plugin.on_load(mw)
        plugin._menu_actions.append(sub.menuAction())

        plugin.on_unload()
        QApplication.processEvents()

        self.assertNotIn(sub.menuAction(), menu.actions())
        self.assertEqual(sub.menuAction().text(), "Sub")  # still a live object
        mw.deleteLater()


class SpreadsheetAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_numbers_right_text_left(self):
        from ui.spreadsheet_widget import SpreadsheetModel

        values = ["12", "-3,5", " 1e3 ", ".5", "abc", "", "1.2.3", "=1+1"]
        model = SpreadsheetModel(["A"] * len(values), [values])
        right = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        left = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        got = [
            model.data(model.index(0, c), Qt.ItemDataRole.TextAlignmentRole)
            for c in range(len(values))
        ]
        self.assertEqual(got, [right, right, right, right, left, left, left, right])


class SafeQThreadTests(unittest.TestCase):
    """The owner's slot drops the only reference while run() is still active.

    With a plain QThread this aborts the process ("QThread: Destroyed while
    thread is still running"), which is what LaTeXChecker._on_check_done did.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_dropping_worker_from_result_slot_is_safe(self):
        import time

        from PyQt6.QtCore import QEventLoop, pyqtSignal

        from core.qt_thread import SafeQThread, running_thread_count

        class Worker(SafeQThread):
            done = pyqtSignal()

            def run(self):
                self.done.emit()
                time.sleep(0.05)  # still inside run() when the slot fires

        class Owner:
            def __init__(self):
                self.worker = Worker()
                self.worker.done.connect(self.on_done)
                self.worker.finished.connect(self.worker.deleteLater)
                self.worker.start()

            def on_done(self):
                self.worker = None  # last Python reference

        base = running_thread_count()
        owners = [Owner() for _ in range(5)]
        loop = QEventLoop()
        QTimer.singleShot(400, loop.quit)
        loop.exec()
        self.assertTrue(all(o.worker is None for o in owners))
        self.assertEqual(running_thread_count(), base)


if __name__ == "__main__":
    unittest.main()

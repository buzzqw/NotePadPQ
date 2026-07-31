from pathlib import Path
import threading
import tempfile
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer

import ui.richtext_widget as richtext
from plugins.richtext_plugin import RichTextPlugin
from ui.tab_manager import TabManager
from ui.richtext_widget import RichTextIO, _JoditDownloadWorker, _RichTextIOWorker


class _Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self, callback=None):
        if callback is None:
            self.callbacks.clear()
        elif callback in self.callbacks:
            self.callbacks.remove(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class RichTextWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def _run_worker(self, worker):
        result = []
        loop = QEventLoop()
        worker.completed.connect(lambda *args: result.append(args))
        worker.finished.connect(loop.quit)
        QTimer.singleShot(3000, loop.quit)
        worker.start()
        loop.exec()
        worker.wait(1000)
        self.assertTrue(result, "il worker non ha prodotto un risultato")
        return result[0]

    def test_load_conversion_runs_outside_main_thread(self):
        main_thread = threading.get_ident()
        called_from = []

        def load(_path):
            called_from.append(threading.get_ident())
            return "<p>ok</p>", ""

        with patch.object(RichTextIO, "load_html", side_effect=load):
            result = self._run_worker(_RichTextIOWorker("load", Path("doc.docx")))

        self.assertNotEqual(called_from[0], main_thread)
        self.assertEqual(result, ("<p>ok</p>", "", False))

    def test_save_conversion_runs_outside_main_thread(self):
        main_thread = threading.get_ident()
        called_from = []

        def save(_html, _path):
            called_from.append(threading.get_ident())
            return ""

        with patch.object(RichTextIO, "save_html", side_effect=save):
            result = self._run_worker(
                _RichTextIOWorker("save", Path("doc.odt"), "<p>test</p>")
            )

        self.assertNotEqual(called_from[0], main_thread)
        self.assertEqual(result, ("", "", False))

    def test_cancel_before_start_skips_conversion(self):
        worker = _RichTextIOWorker("load", Path("doc.rtf"))
        worker.cancel()
        with patch.object(RichTextIO, "load_html") as load:
            result = self._run_worker(worker)
        load.assert_not_called()
        self.assertEqual(result, ("", "", True))

    def test_http_download_runs_outside_main_thread(self):
        main_thread = threading.get_ident()
        called_from = []

        class Response:
            headers = {"Content-Length": "4"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size):
                if hasattr(self, "sent"):
                    return b""
                self.sent = True
                return b"data"

        def urlopen(_request, timeout):
            self.assertEqual(timeout, 30)
            called_from.append(threading.get_ident())
            return Response()

        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            with (
                patch.object(richtext, "_ASSETS_DIR", assets),
                patch.object(richtext, "_JODIT_JS", assets / "jodit.min.js"),
                patch.object(richtext, "_JODIT_CSS", assets / "jodit.min.css"),
                patch.object(richtext.urllib.request, "urlopen", side_effect=urlopen),
            ):
                result = self._run_worker(_JoditDownloadWorker())
            self.assertEqual((assets / "jodit.min.js").read_bytes(), b"data")
            self.assertEqual((assets / "jodit.min.css").read_bytes(), b"data")

        self.assertEqual(len(called_from), 2)
        self.assertTrue(all(thread != main_thread for thread in called_from))
        self.assertEqual(result, (True, ""))


class RichTextTabCloseTests(unittest.TestCase):
    class Widget:
        def __init__(self, save_result=True, saving=False):
            self.save_finished = _Signal()
            self.save_result = save_result
            self.saving = saving
            self.cleaned = False
            self.closed = False

        def is_modified(self):
            return True

        def is_save_in_progress(self):
            return self.saving

        def save(self):
            self.saving = self.save_result
            return self.save_result

        def cleanup(self):
            self.cleaned = True

        def close(self):
            self.closed = True

    class Manager:
        _defer_custom_close = TabManager._defer_custom_close
        _cancel_deferred_custom_close = TabManager._cancel_deferred_custom_close
        _on_close_requested = TabManager._on_close_requested
        _close_tab_at = TabManager._close_tab_at

        def __init__(self, widget):
            self.current = widget
            self._custom_tabs = {widget: Path("doc.html")}
            self._pending_custom_closes = {}
            self._mru = []
            self._editors = {}
            self.closed = 0

        def widget(self, index):
            return self.current if index == 0 else None

        def editor_at(self, _index):
            return None

        def indexOf(self, widget):
            return 0 if widget is self.current else -1

        def removeTab(self, _index):
            self.closed += 1
            self.current = None

        def count(self):
            return 1

    def test_custom_tab_closes_only_after_successful_async_save(self):
        widget = self.Widget()
        manager = self.Manager(widget)
        with patch(
            "ui.tab_manager.QMessageBox.question",
            return_value=richtext.QMessageBox.StandardButton.Save,
        ):
            manager._on_close_requested(0)

        self.assertEqual(manager.closed, 0)
        widget.saving = False
        widget.save_finished.emit(True, Path("doc.html"))
        self.assertEqual(manager.closed, 1)
        self.assertTrue(widget.cleaned)
        self.assertTrue(widget.closed)

    def test_custom_tab_stays_open_after_save_error_or_cancel(self):
        for ok in (False, False):
            with self.subTest(ok=ok):
                widget = self.Widget(saving=True)
                manager = self.Manager(widget)
                manager._on_close_requested(0)
                widget.saving = False
                widget.save_finished.emit(ok, Path("doc.html"))
                self.assertEqual(manager.closed, 0)
                self.assertFalse(widget.cleaned)

    def test_direct_close_waits_for_save_and_cleanup_runs(self):
        widget = self.Widget(saving=True)
        manager = self.Manager(widget)
        manager._close_tab_at(0)
        self.assertEqual(manager.closed, 0)
        widget.saving = False
        widget.save_finished.emit(True, Path("doc.html"))
        self.assertEqual(manager.closed, 1)
        self.assertTrue(widget.cleaned)
        self.assertTrue(widget.closed)


class RichTextPluginUnloadTests(unittest.TestCase):
    def test_unload_cancels_download_and_drops_pending_callbacks(self):
        class Controller:
            def __init__(self):
                self.finished = _Signal()
                self.cancelled = False

            def cancel(self):
                self.cancelled = True

        class Window:
            pass

        controller = Controller()
        window = Window()
        plugin = RichTextPlugin()
        plugin._mw = window
        plugin._menu_actions = []
        plugin._unloading = False
        plugin._jodit_download = None
        plugin._jodit_callbacks = []
        plugin._jodit_notify = False
        window._richtext_plugin = plugin
        opened = []

        with patch("ui.richtext_widget.download_jodit", return_value=controller):
            plugin._start_jodit_download(False, lambda: opened.append(True))
        plugin.on_unload()
        controller.finished.emit(True)

        self.assertTrue(controller.cancelled)
        self.assertEqual(opened, [])
        self.assertFalse(hasattr(window, "_richtext_plugin"))


if __name__ == "__main__":
    unittest.main()

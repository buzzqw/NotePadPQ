import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QCheckBox, QDialog, QLabel, QTextEdit, QTreeWidget

from core.git_framework import GitFramework, _GitThread
from plugins import git_plugin
from plugins.git_plugin import _GitPanel


class _Worker:
    def __init__(self):
        self.cancelled = False
        self.deleted = False

    def cancel(self):
        self.cancelled = True

    def deleteLater(self):
        self.deleted = True


class _Signal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self._callbacks):
            callback(*args)


class _Thread(_Worker):
    def __init__(self):
        super().__init__()
        self.result_ready = _Signal()
        self.finished = _Signal()
        self.started = False

    def start(self):
        self.started = True


class GitFrameworkAsyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _capture_async(self, framework):
        calls = []

        def run_async(args, callback, timeout):
            worker = _Worker()
            calls.append((args, callback, timeout, worker))
            return worker

        framework._run_async = run_async
        return calls

    def test_status_log_and_diff_queries_use_async_dispatch_and_keep_results(self):
        framework = GitFramework(Path("repo"))
        calls = self._capture_async(framework)
        status = []
        log = []
        diff = []

        framework.status_async(status.append)
        framework.log_async(2, log.append)
        framework.diff_async("src/file.py", True, diff.append)

        self.assertEqual(calls[0][0], ["status", "--porcelain"])
        self.assertEqual(calls[1][0][:2], ["log", "-2"])
        self.assertEqual(calls[2][0], ["diff", "--cached", "--", "src/file.py"])

        calls[0][1](0, " M src/file.py\n?? new.txt", "")
        calls[1][1](0, "abc\x1fab\x1fAda\x1fada@example.com\x1f2026-01-02 03:04:05\x1fMessage", "")
        calls[2][1](0, "+added", "")

        self.assertEqual(status, [[("M", "src/file.py"), ("??", "new.txt")]])
        self.assertEqual(log[0][0]["subject"], "Message")
        self.assertEqual(diff, ["+added"])

    def test_commit_with_files_uses_explicit_pathspec(self):
        framework = GitFramework(Path("repo"))
        calls = self._capture_async(framework)
        framework.stage_files = lambda files: True

        framework.commit_async("message", files=["a.py", "b.py"])

        self.assertEqual(
            calls[0][0], ["commit", "-m", "message", "--", "a.py", "b.py"]
        )

    def test_detailed_status_keeps_porcelain_columns(self):
        parsed = GitFramework._parse_status_detailed(" M a.txt\n?? c.txt\n")
        self.assertEqual(parsed, [(" ", "M", "a.txt"), ("?", "?", "c.txt")])

    def test_parse_status_keeps_full_path_with_leading_space(self):
        parsed = GitFramework._parse_status(" M a.txt\n")
        self.assertEqual(parsed, [("M", "a.txt")])

    def test_changed_files_vs_remote_prefers_upstream_and_falls_back_to_head(self):
        framework = GitFramework(Path("repo"))
        calls = []

        def run_sync(args, timeout, strip_output=True):
            calls.append(list(args))
            if "@{upstream}" in args:
                return 1, "", "no upstream configured"
            return 0, "a.txt\nsub/b.txt\n", ""

        framework._run_sync = run_sync

        self.assertEqual(
            framework.changed_files_vs_remote(), ["a.txt", "sub/b.txt"]
        )
        self.assertEqual(calls, [
            ["diff", "--name-only", "@{upstream}"],
            ["diff", "--name-only", "HEAD"],
        ])

    def test_changed_files_vs_remote_uses_upstream_when_available(self):
        framework = GitFramework(Path("repo"))
        calls = []

        def run_sync(args, timeout, strip_output=True):
            calls.append(list(args))
            return 0, "only.txt\n", ""

        framework._run_sync = run_sync

        self.assertEqual(framework.changed_files_vs_remote(), ["only.txt"])
        self.assertEqual(calls, [["diff", "--name-only", "@{upstream}"]])

    def test_async_query_failures_preserve_empty_sync_fallbacks(self):
        framework = GitFramework(Path("repo"))
        calls = self._capture_async(framework)
        results = []

        framework.status_async(lambda value: results.append(value))
        framework.log_async(1, lambda value: results.append(value))
        framework.diff_async(None, False, lambda value: results.append(value))
        framework.show_async("deadbeef", lambda value: results.append(value))

        for _args, callback, _timeout, _worker in calls:
            callback(1, "partial output", "git error")

        self.assertEqual(results, [[], [], "", ""])

    def test_framework_retains_workers_until_their_finished_signal(self):
        framework = GitFramework(Path("repo"))
        thread = _Thread()
        received = []

        with patch("core.git_framework._GitThread", return_value=thread):
            operation = framework._run_async(["status", "--porcelain"], received.append)

        self.assertIs(operation, thread)
        self.assertTrue(thread.started)
        self.assertIn(thread, framework._workers)
        self.assertIn(thread, framework._handlers)

        framework.cancel_all()
        self.assertTrue(thread.cancelled)
        thread.finished.emit()

        self.assertNotIn(thread, framework._workers)
        self.assertNotIn(thread, framework._handlers)
        self.assertTrue(thread.deleted)
        self.assertEqual(received, [])

    def test_cancelling_an_active_worker_terminates_its_process(self):
        worker = _GitThread(Path("repo"), ["status", "--porcelain"])
        process = SimpleNamespace(poll=lambda: None, terminated=False)

        def terminate():
            process.terminated = True

        process.terminate = terminate
        with worker._lock:
            worker._process = process

        worker.cancel()

        self.assertTrue(worker.cancelled)
        self.assertTrue(process.terminated)


class _QueryFramework:
    def __init__(self):
        self.calls = []

    def status_async(self, callback):
        return self._queue("status", callback)

    def status_detailed_async(self, callback):
        return self._queue("status", callback)

    def log_async(self, count, callback):
        return self._queue("log", callback, count)

    def diff_async(self, path, staged, callback):
        return self._queue("diff", callback, path, staged)

    def _queue(self, name, callback, *args):
        worker = _Worker()
        self.calls.append((name, args, callback, worker))
        return worker


class GitPanelAsyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _panel(self, framework):
        return SimpleNamespace(
            _git=SimpleNamespace(
                status=lambda: self.fail("synchronous status called"),
                log=lambda _n: self.fail("synchronous log called"),
                diff=lambda *_args, **_kwargs: self.fail("synchronous diff called"),
            ),
            _git_fw=framework,
            _repo_dir=Path("repo"),
            _status_worker=None,
            _log_worker=None,
            _diff_worker=None,
            _status_generation=0,
            _log_generation=0,
            _diff_generation=0,
            _status_tree=QTreeWidget(),
            _status_summary=QLabel(),
            _status_entries=[],
            _populating_status=False,
            _selected_status_path=lambda: None,
            _log_list=QTreeWidget(),
            _diff_staged_cb=QCheckBox(),
            _diff_view=QTextEdit(),
            _diff_label=QLabel(),
            _mw=SimpleNamespace(_tab_manager=SimpleNamespace(current_editor=lambda: None)),
            _colorize_diff=lambda: None,
        )

    def test_panel_status_log_and_diff_do_not_call_synchronous_runner(self):
        framework = _QueryFramework()
        panel = self._panel(framework)

        _GitPanel._refresh_status(panel)
        _GitPanel._refresh_log(panel)
        _GitPanel._show_diff(panel)

        self.assertEqual([call[0] for call in framework.calls], ["status", "log", "diff"])
        self.assertEqual(framework.calls[1][1], (60,))
        self.assertEqual(framework.calls[2][1], (None, False))

        framework.calls[0][2]([("M", " ", "src/file.py")])
        framework.calls[1][2]([{
            "short": "abc", "date": "2026-01-02", "author": "Ada",
            "subject": "Message", "hash": "abcdef",
        }])
        framework.calls[2][2]("+added")

        self.assertEqual(panel._status_tree.topLevelItemCount(), 1)
        self.assertEqual(panel._log_list.topLevelItemCount(), 1)
        self.assertEqual(panel._diff_view.toPlainText(), "+added")

    def test_superseded_status_request_is_cancelled_and_cannot_update_the_panel(self):
        framework = _QueryFramework()
        panel = self._panel(framework)

        _GitPanel._refresh_status(panel)
        first = framework.calls[0]
        _GitPanel._refresh_status(panel)
        second = framework.calls[1]

        self.assertTrue(first[3].cancelled)
        first[2]([(" ", "M", "stale.py")])
        second[2]([("A", " ", "current.py")])

        self.assertEqual(panel._status_tree.topLevelItemCount(), 1)
        self.assertEqual(panel._status_tree.topLevelItem(0).text(1), "current.py")

    def _commit_panel(self, status_entries, remote_files):
        commits = []
        framework = SimpleNamespace(
            current_branch=lambda: "main",
            changed_files_vs_remote=lambda: list(remote_files),
            commit_async=lambda message, files=None, callback=None: commits.append(
                (message, list(files or []))
            ),
        )
        panel = SimpleNamespace(
            _git_fw=framework,
            _status_entries=list(status_entries),
            _log=lambda *_args, **_kwargs: None,
            _on_async_done=lambda *_args, **_kwargs: None,
        )
        return panel, commits

    def test_commit_preselects_only_files_changed_against_the_remote(self):
        class _FakeDialog:
            instances = []

            def __init__(self, files, branch, parent=None, preselected=None):
                self.files = list(files)
                self.preselected = list(preselected or [])
                _FakeDialog.instances.append(self)

            def exec(self):
                return QDialog.DialogCode.Accepted

            def values(self):
                return "message", list(self.preselected)

        panel, commits = self._commit_panel(
            [(" ", "M", "a.txt"), ("?", "?", "new.txt")],
            ["a.txt"],
        )

        with patch.object(git_plugin, "_CommitDialog", _FakeDialog):
            _GitPanel._commit(panel)

        self.assertEqual(_FakeDialog.instances[-1].preselected, ["a.txt"])
        self.assertEqual(commits, [("message", ["a.txt"])])

    def test_commit_keeps_explicitly_staged_files_preselected(self):
        class _FakeDialog:
            instances = []

            def __init__(self, files, branch, parent=None, preselected=None):
                self.preselected = list(preselected or [])
                _FakeDialog.instances.append(self)

            def exec(self):
                return QDialog.DialogCode.Accepted

            def values(self):
                return "message", list(self.preselected)

        panel, commits = self._commit_panel(
            [("M", " ", "b.txt"), (" ", "M", "a.txt")],
            ["a.txt", "b.txt"],
        )

        with patch.object(git_plugin, "_CommitDialog", _FakeDialog):
            _GitPanel._commit(panel)

        self.assertEqual(_FakeDialog.instances[-1].preselected, ["b.txt"])
        self.assertEqual(commits, [("message", ["b.txt"])])


if __name__ == "__main__":
    unittest.main()

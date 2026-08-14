import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication


class TestBuildReliability(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_profile_command_keeps_spaced_path_as_one_argv_item(self):
        from core.build_manager import BuildManager

        bm = BuildManager()
        path = Path("/tmp/a directory/file;not-a-command.py")
        argv = bm._expand_command("python3 ${FILE}", path, None)
        self.assertEqual(argv, ["python3", str(path)])

    def test_profile_command_uses_shell_only_for_shell_syntax(self):
        from core.build_manager import BuildManager

        bm = BuildManager()
        command = bm._expand_command("echo ${FILE} && echo done", Path("/tmp/a b"), None)
        self.assertEqual(command, 'echo "${NOTEPADPQ_FILE}" && echo done')

    @unittest.skipIf(os.name == "nt", "process-group assertion is POSIX-specific")
    def test_abort_stops_process_group(self):
        from core.build_manager import BuildWorker

        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "child-ran"
            command = [
                sys.executable,
                "-c",
                (
                    "import subprocess, sys, time; "
                    "subprocess.Popen([sys.executable, '-c', "
                    "'import time, pathlib; time.sleep(2); pathlib.Path(" + repr(str(marker)) + ").write_text(\"ran\")']); "
                    "time.sleep(10)"
                ),
            ]
            worker = BuildWorker(command, tmp, dict(os.environ))
            worker.start()
            time.sleep(0.15)
            worker.abort()
            self.assertTrue(worker.wait(4000))
            time.sleep(2.2)
            self.assertFalse(marker.exists())

    def test_completed_worker_is_removed_from_manager(self):
        from core.build_manager import BuildManager

        bm = BuildManager()
        bm.run_task(f'"{sys.executable}" -c "print(1)"', Path.cwd(), run_id="complete")
        deadline = time.monotonic() + 5
        while bm.is_running("complete") and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        self.assertNotIn("complete", bm._workers)


class _CompletingWorker(QObject):
    finished = pyqtSignal()

    def run(self):
        self.finished.emit()


class _FailingWorker(QObject):
    error = pyqtSignal(str)

    def run(self):
        self.error.emit("failed")


class TestManagedWorker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_completion_quits_and_releases_thread(self):
        from core.worker_pool import ManagedWorker

        managed = ManagedWorker(_CompletingWorker())
        managed.thread.started.connect(managed.worker.run)
        managed.start()
        deadline = time.monotonic() + 3
        while managed.thread is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertIsNone(managed.thread)
        self.assertIsNone(managed.worker)

    def test_error_quits_and_releases_thread(self):
        from core.worker_pool import ManagedWorker

        managed = ManagedWorker(_FailingWorker())
        managed.thread.started.connect(managed.worker.run)
        managed.start()
        deadline = time.monotonic() + 3
        while managed.thread is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertIsNone(managed.thread)
        self.assertIsNone(managed.worker)


class TestSingleInstancePayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_payload_validation(self):
        from core.single_instance import SingleInstance

        self.assertEqual(SingleInstance._decode_paths(b'{"paths":["/tmp/a"]}'), ["/tmp/a"])
        self.assertIsNone(SingleInstance._decode_paths(b'["/tmp/a"]'))
        self.assertIsNone(SingleInstance._decode_paths(b'{"paths":[1]}'))
        self.assertFalse(SingleInstance._valid_paths(["bad\x00path"]))

    def test_secondary_waits_for_primary_acknowledgement(self):
        from core.single_instance import SingleInstance

        name = f"NotePadPQ-reliability-{time.monotonic_ns()}"
        received = []
        primary = SingleInstance(name)
        self.assertTrue(primary.start_server(received.append))
        result = []
        sender = threading.Thread(
            target=lambda: result.append(SingleInstance(name).send_args_if_secondary(["/tmp/a"])),
        )
        sender.start()
        deadline = time.monotonic() + 5
        while sender.is_alive() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        sender.join(1)
        primary._server.close()
        self.assertEqual(result, [True])
        self.assertEqual(received, [["/tmp/a"]])


if __name__ == "__main__":
    unittest.main()

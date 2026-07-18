"""
core/worker_pool.py — Safe worker thread management
NotePadPQ

Eliminates the "old_workers" memory leak pattern used across the codebase.
"""

from typing import Optional
from PyQt6.QtCore import QObject, QThread, pyqtSignal


class ManagedWorker:
    """
    Wraps a QObject worker and its QThread with safe lifecycle management.
    
    Usage:
        worker = _SomeWorker(...)
        mw = ManagedWorker(worker)
        mw.start()
        # When done or on cancel:
        mw.stop()
    """

    def __init__(self, worker: QObject):
        self._worker = worker
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.finished.connect(self._thread.deleteLater)

    @property
    def thread(self) -> QThread:
        return self._thread

    @property
    def worker(self) -> QObject:
        return self._worker

    def start(self) -> None:
        if not self._thread.isRunning():
            self._thread.start()

    def stop(self, wait_ms: int = 500) -> None:
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(wait_ms)
            self._thread.deleteLater()
        self._thread = None
        self._worker = None


class OldWorkersCleanupMixin:
    """
    Mixin for QObject-based classes that manage background workers.
    Replaces the manual _old_workers list pattern with safe cleanup.
    
    Usage:
        class MyClass(QObject, OldWorkersCleanupMixin):
            def __init__(self):
                super().__init__()
                self._setup_cleanup_timer()
    
    Or use the static methods directly:
        OldWorkersCleanupMixin.safe_track(old_list, new_thread)
    """

    @staticmethod
    def safe_track(old_list: list, thread: QThread, worker: QObject,
                   max_workers: int = 4) -> None:
        """
        Track a thread+worker pair and prune stale entries.
        Call this when starting a new worker thread.
        """
        # Prune threads that are no longer running
        old_list[:] = [
            (t, w) for t, w in old_list
            if t.isRunning()
        ]
        old_list.append((thread, worker))
        # Keep only the most recent max_workers
        while len(old_list) > max_workers:
            stale_t, stale_w = old_list.pop(0)
            if stale_t.isRunning():
                stale_t.quit()
                stale_t.wait(200)
            stale_t.deleteLater()

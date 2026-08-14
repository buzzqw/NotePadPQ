"""
core/worker_pool.py — Safe worker thread lifecycle management
NotePadPQ
"""

from typing import Optional

from PyQt6.QtCore import QObject, QThread


class ManagedWorker:
    """
    Accoppia un QObject worker al suo QThread con lifecycle sicuro.

    Uso:
        worker = _SomeWorker(...)
        mw = ManagedWorker(worker)
        mw.thread.started.connect(worker.run)
        worker.some_signal.connect(slot)
        mw.start()
        # Per fermare:
        worker.cancel()
        mw.stop()
    """

    def __init__(self, worker: QObject) -> None:
        self._worker: Optional[QObject] = worker
        self._thread: Optional[QThread] = QThread()
        self._worker.moveToThread(self._thread)
        # A worker's normal completion must end the thread event loop. Without
        # this, a completed worker keeps a running QThread and its resources.
        for signal_name in ("finished", "error"):
            terminal_signal = getattr(self._worker, signal_name, None)
            if terminal_signal is not None:
                terminal_signal.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._release)
        self._thread.finished.connect(self._thread.deleteLater)

    @property
    def thread(self) -> Optional[QThread]:
        return self._thread

    @property
    def worker(self) -> Optional[QObject]:
        return self._worker

    def start(self) -> None:
        if self._thread is not None and not self._thread.isRunning():
            self._thread.start()

    def stop(self, wait_ms: int = 500) -> bool:
        """Request cancellation and retain ownership until the thread exits."""
        if self._worker is not None:
            cancel = getattr(self._worker, "cancel", None)
            if callable(cancel):
                cancel()
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(wait_ms)
        if self._thread is None or not self._thread.isRunning():
            self._release()
            return True
        # Do not drop references to a still-running QThread. Its finished
        # signal will release both objects once cooperative cancellation ends.
        return False

    def _release(self) -> None:
        self._thread = None
        self._worker = None

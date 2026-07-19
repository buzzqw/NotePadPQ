"""
core/worker_pool.py — Safe worker thread lifecycle management
NotePadPQ
"""

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
        if self._thread is not None and not self._thread.isRunning():
            self._thread.start()

    def stop(self, wait_ms: int = 500) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(wait_ms)
        self._thread = None
        self._worker = None

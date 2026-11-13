"""QThread base class that cannot be destroyed while it is still running.

Many workers emit their result signal (``done``, ``result_ready``…) as the
last statement of ``run()``. The slot receiving it on the GUI thread often
drops the owner's reference (``self._worker = None``). If that was the only
Python reference, sip deletes the C++ object immediately and
``QThread::~QThread`` runs while ``run()`` has not returned yet, which Qt
treats as fatal: ``QThread: Destroyed while thread is still running`` →
SIGABRT. The window is tiny, so the crash is rare and hard to reproduce.

``SafeQThread`` keeps a strong reference to itself from ``start()`` until
its ``finished`` signal is delivered on the thread it lives in (normally the
GUI thread). Signals queued from ``run()`` are delivered before
``finished``, so any slot may drop its reference safely. When the last
reference goes away at ``finished`` time Qt is already inside the thread's
finish sequence and ``~QThread`` simply waits for it to complete.
"""

from __future__ import annotations

from PyQt6.QtCore import QThread

_RUNNING: set[QThread] = set()


class SafeQThread(QThread):
    """Drop-in replacement for ``QThread`` subclasses that run in ``run()``."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Bound method: PyQt keeps only a weak reference to ``self`` here,
        # so the connection does not create an uncollectable cycle.
        self.finished.connect(self._release_running_ref)

    def start(self, *args, **kwargs) -> None:  # noqa: D401 - Qt signature
        _RUNNING.add(self)
        try:
            super().start(*args, **kwargs)
        except BaseException:
            _RUNNING.discard(self)
            raise

    def _release_running_ref(self) -> None:
        _RUNNING.discard(self)


def running_thread_count() -> int:
    """Number of SafeQThreads started and not yet finished (for tests)."""
    return len(_RUNNING)

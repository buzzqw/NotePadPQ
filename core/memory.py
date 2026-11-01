"""
core/memory.py - Restituzione al sistema della memoria libera dell'allocatore.

glibc trattiene le arene liberate dopo i picchi (indicizzazione LaTeX, rendering
PDF, chiusura di tab grandi): su documenti da 2-3 MB sono 15-25 MB di RSS senza
dati vivi. La chiamata gira su un thread a parte: ctypes rilascia il GIL e la GUI
non si ferma mentre glibc percorre le arene.
"""

from __future__ import annotations

import sys
import threading

_TRIM_DELAY_MS = 3000
_timer = None


def _malloc_trim() -> None:
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (ImportError, OSError, AttributeError):
        pass  # musl o libc non glibc: nessun equivalente, nulla da fare


def schedule_trim() -> None:
    """Accorpa le richieste ravvicinate in un unico trim differito (solo Linux)."""
    global _timer
    if not sys.platform.startswith("linux"):
        return
    from PyQt6.QtCore import QCoreApplication, QTimer

    app = QCoreApplication.instance()
    if app is None:
        return
    if _timer is None:
        _timer = QTimer(app)
        _timer.setSingleShot(True)
        _timer.setInterval(_TRIM_DELAY_MS)
        _timer.timeout.connect(
            lambda: threading.Thread(target=_malloc_trim, daemon=True).start()
        )
    _timer.start()

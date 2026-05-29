"""
core/webengine.py — Utility per creare QWebEngineView senza crash su sistemi senza GL.

Qt chiama qFatal() → abort() → SIGABRT se GLX/EGL non è disponibile durante
la prima costruzione di QWebEngineView. Intercettiamo SIGABRT e lo convertiamo
in una RuntimeError Python catturabile, così l'app non crasha.

Uso:
    from core.webengine import safe_webview
    self._view = safe_webview(self)   # None se GL non disponibile
"""
from __future__ import annotations

import signal
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWidgets import QWidget

_gl_available: Optional[bool] = None


def safe_webview(parent: "Optional[QWidget]" = None) -> "Optional[QWebEngineView]":
    """
    Crea QWebEngineView intercettando il SIGABRT che Qt emette se GL non è
    inizializzabile. Restituisce None invece di terminare il processo.

    Il risultato della prima chiamata viene memorizzato: se GL è assente, le
    chiamate successive restituiscono None immediatamente senza tentare di nuovo.
    """
    global _gl_available

    if _gl_available is False:
        return None

    from PyQt6.QtWebEngineWidgets import QWebEngineView

    def _abort(signum, frame):
        raise RuntimeError("Qt GL init failed (SIGABRT intercepted)")

    old = signal.signal(signal.SIGABRT, _abort)
    try:
        view = QWebEngineView(parent) if parent is not None else QWebEngineView()
        _gl_available = True
        return view
    except RuntimeError:
        _gl_available = False
        return None
    finally:
        signal.signal(signal.SIGABRT, old)


def gl_available() -> bool:
    """True se QWebEngineView può essere creato (GL funzionante)."""
    if _gl_available is None:
        v = safe_webview()
        if v is not None:
            v.deleteLater()
    return _gl_available is True

"""
core/webengine.py — Utility per creare QWebEngineView senza crash su sistemi senza GL.

Qt chiama qFatal() → abort() → SIGABRT se GLX non trova framebuffer config.
L'approccio SIGABRT via signal.signal() non funziona: dopo che il C-level
handler ritorna, abort() re-imposta SIG_DFL e rilancia SIGABRT uccidendo il
processo prima che Python possa eseguire il nostro handler.

Soluzione: probe GLX con ctypes prima di coinvolgere Qt. Se glXChooseFBConfig
non trova nessuna config RGBA, Qt fallirebbe nello stesso modo → restituiamo
None immediatamente, senza mai creare QWebEngineView.

Uso:
    from core.webengine import safe_webview
    self._view = safe_webview(self)   # None se GL non disponibile
"""
from __future__ import annotations

import os
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWidgets import QWidget

_gl_available: Optional[bool] = None


def _probe_glx() -> bool:
    """
    Testa GLX via ctypes senza coinvolgere Qt (niente qFatal/abort risk).
    Restituisce False se non esiste nessuna FBConfig RGBA utilizzabile,
    True in tutti gli altri casi (incluso Windows/Wayland/errori di probe).
    """
    if os.name == 'nt':
        return True  # Windows usa ANGLE, GLX non applicabile

    display = os.environ.get('DISPLAY', '')

    # Wayland puro senza XWayland: EGL gestisce tutto, non usiamo GLX
    if not display and os.environ.get('WAYLAND_DISPLAY'):
        return True

    if not display:
        return False  # nessun display X11 disponibile

    try:
        import ctypes
        import ctypes.util

        x11_name = ctypes.util.find_library('X11') or 'libX11.so.6'
        gl_name  = ctypes.util.find_library('GL')  or 'libGL.so.1'
        x11 = ctypes.CDLL(x11_name)
        gl  = ctypes.CDLL(gl_name)

        x11.XOpenDisplay.restype  = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XDefaultScreen.restype  = ctypes.c_int
        x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
        x11.XCloseDisplay.argtypes  = [ctypes.c_void_p]

        dpy = x11.XOpenDisplay(None)
        if not dpy:
            return False

        try:
            # Verifica presenza estensione GLX
            gl.glXQueryExtension.restype  = ctypes.c_int
            gl.glXQueryExtension.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int),
            ]
            err_b = ctypes.c_int()
            ev_b  = ctypes.c_int()
            if not gl.glXQueryExtension(ctypes.c_void_p(dpy),
                                        ctypes.byref(err_b), ctypes.byref(ev_b)):
                return False

            # Cerca una FBConfig minimale (RGBA, window-capable)
            # Costanti da <GL/glx.h>
            GLX_DRAWABLE_TYPE = 0x8010
            GLX_WINDOW_BIT    = 0x00000001
            GLX_RENDER_TYPE   = 0x8011
            GLX_RGBA_BIT      = 0x00000001
            GLX_RED_SIZE      = 8
            GLX_GREEN_SIZE    = 9
            GLX_BLUE_SIZE     = 10
            GLX_NONE          = 0

            attrs = (ctypes.c_int * 11)(
                GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
                GLX_RENDER_TYPE,   GLX_RGBA_BIT,
                GLX_RED_SIZE,      1,
                GLX_GREEN_SIZE,    1,
                GLX_BLUE_SIZE,     1,
                GLX_NONE,
            )
            n   = ctypes.c_int(0)
            scr = x11.XDefaultScreen(ctypes.c_void_p(dpy))

            gl.glXChooseFBConfig.restype  = ctypes.c_void_p
            gl.glXChooseFBConfig.argtypes = [
                ctypes.c_void_p, ctypes.c_int,
                ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ]
            gl.glXChooseFBConfig(ctypes.c_void_p(dpy), scr, attrs, ctypes.byref(n))
            return n.value > 0

        finally:
            x11.XCloseDisplay(ctypes.c_void_p(dpy))

    except Exception:
        return True  # Conservativo: se il probe fallisce, lasciamo che Qt tenti


def gl_available() -> bool:
    """True se QWebEngineView può essere creato (GL funzionante)."""
    global _gl_available
    if _gl_available is None:
        _gl_available = _probe_glx()
    return _gl_available


def safe_webview(parent: "Optional[QWidget]" = None) -> "Optional[QWebEngineView]":
    """
    Crea QWebEngineView solo se GL è disponibile (verificato via probe ctypes).
    Restituisce None se GL non è utilizzabile, senza crashare.
    """
    if not gl_available():
        return None
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    return QWebEngineView(parent) if parent is not None else QWebEngineView()

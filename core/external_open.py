"""
core/external_open.py — Apre file/URL in app di sistema con LD_LIBRARY_PATH pulito.

Quando l'app gira in un AppImage, AppRun prepende librerie Qt a LD_LIBRARY_PATH.
I processi figli (evince, browser, file manager) ereditano questa modifica e possono
trovare GLib/GStreamer bundled invece delle versioni native, causando crash.

Questo modulo ripristina il LD_LIBRARY_PATH originale (salvato da AppRun in
APPIMAGE_ORIG_LD_LIBRARY_PATH) per qualsiasi processo figlio che apre file/URL.
"""
from __future__ import annotations

import os
import subprocess
from typing import Union


def clean_subprocess_env() -> dict:
    """
    Restituisce una copia di os.environ con LD_LIBRARY_PATH ripristinato
    al valore pre-AppImage. Usare come `env=` in subprocess.Popen / QProcess
    per evitare che libstdc++/GLib bundled sovrascrivano le versioni di sistema.
    Fuori da AppImage restituisce os.environ.copy() invariato.
    """
    env = os.environ.copy()
    orig = os.environ.get('APPIMAGE_ORIG_LD_LIBRARY_PATH')
    if orig is not None:
        if orig:
            env['LD_LIBRARY_PATH'] = orig
        else:
            env.pop('LD_LIBRARY_PATH', None)
    return env


_clean_env = clean_subprocess_env  # alias interno


def open_url(url) -> bool:
    """
    Apre un QUrl o stringa con l'app di sistema predefinita.
    Se siamo in un AppImage usa xdg-open con LD_LIBRARY_PATH ripristinato;
    altrimenti deleghiamo a QDesktopServices.openUrl() normalmente.
    """
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices

    if isinstance(url, str):
        url = QUrl(url)

    # Fuori da AppImage: comportamento standard, nessun overhead
    if 'APPIMAGE_ORIG_LD_LIBRARY_PATH' not in os.environ:
        return QDesktopServices.openUrl(url)

    url_str = url.toString()
    if url.isLocalFile():
        target = url.toLocalFile()
    else:
        target = url_str

    try:
        subprocess.Popen(
            ['xdg-open', target],
            env=_clean_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return QDesktopServices.openUrl(url)

"""
core/single_instance.py — Gestione istanza singola
NotePadPQ

Garantisce che giri una sola istanza dell'applicazione.
Se viene avviata una seconda istanza con un file come argomento,
il file viene inviato alla prima istanza tramite socket locale Unix,
e la seconda istanza termina immediatamente.
"""

from __future__ import annotations

import json
import os
from typing import Callable, List, Optional

from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QTimer


class SingleInstance(QObject):
    """Gestisce la single-instance tramite QLocalServer/QLocalSocket."""

    files_received = pyqtSignal(list)

    def __init__(self, app_name: str = "NotePadPQ", parent: Optional[QObject] = None):
        super().__init__(parent)
        # Aggiungiamo l'UID per evitare conflitti se ci sono più utenti sullo stesso PC
        uid = os.getuid() if hasattr(os, "getuid") else 0
        self._app_name    = f"{app_name}_{uid}"
        self._server      = None
        self._callback: Optional[Callable[[List[str]], None]] = None

    def send_args_if_secondary(self, paths: List[str]) -> bool:
        """
        Tenta un'unica connessione al server principale.
        Se riesce, invia i path e restituisce True (siamo la seconda istanza).
        Se fallisce, restituisce False (siamo la prima istanza).
        """
        sock = QLocalSocket()
        sock.connectToServer(self._app_name)

        # Diamo 1 secondo pieno per la connessione (super stabile)
        if sock.waitForConnected(1000):
            payload = (json.dumps(paths) + "\n").encode("utf-8")
            sock.write(payload)
            sock.flush()
            sock.waitForBytesWritten(1000)
            sock.disconnectFromServer()
            sock.deleteLater()
            return True

        sock.deleteLater()
        return False

    def start_server(self, callback: Callable[[List[str]], None]) -> None:
        """Avvia il server locale sulla prima istanza."""
        self._callback = callback
        self.files_received.connect(callback)

        # Rimuovi eventuale socket orfano da un crash precedente
        QLocalServer.removeServer(self._app_name)

        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        
        if not self._server.listen(self._app_name):
            print(f"[SingleInstance] Impossibile avviare il server: {self._server.errorString()}")
            return

        self._server.newConnection.connect(self._on_new_connection)

    def _on_new_connection(self) -> None:
        conn = self._server.nextPendingConnection()
        if not conn:
            return
        # Accumula dati finché non arriva il terminatore '\n'
        conn.setProperty("buffer", b"")
        conn.readyRead.connect(lambda: self._on_ready_read(conn))
        conn.disconnected.connect(conn.deleteLater)

    def _on_ready_read(self, conn: QLocalSocket) -> None:
        buf: bytes = conn.property("buffer") or b""
        buf += bytes(conn.readAll())
        conn.setProperty("buffer", buf)

        if b"\n" in buf:
            line, _ = buf.split(b"\n", 1)
            try:
                paths: List[str] = json.loads(line.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                paths = []

            if paths:
                self.files_received.emit(paths)

            # Porta la finestra in primo piano anche se non ci sono file
            QTimer.singleShot(0, self._raise_window)

    def _raise_window(self) -> None:
        """Porta la finestra principale in primo piano e toglie il 'Riduci a icona'."""
        from PyQt6.QtWidgets import QApplication
        for w in QApplication.topLevelWidgets():
            if w.isVisible() and hasattr(w, "_tab_manager"):
                w.setWindowState(w.windowState() & ~Qt.WindowState.WindowMinimized)
                w.raise_()
                w.activateWindow()
                break
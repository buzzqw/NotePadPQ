"""
core/single_instance.py — Gestione istanza singola
NotePadPQ

Garantisce che giri una sola istanza dell'applicazione.
Se viene avviata una seconda istanza con un file come argomento,
il file viene inviato alla prima istanza tramite socket locale,
e la seconda istanza termina immediatamente.
"""

from __future__ import annotations

import json
import os
from typing import Callable, List, Optional

from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QTimer
from PyQt6 import sip


class SingleInstance(QObject):
    """Gestisce la single-instance tramite QLocalServer/QLocalSocket."""

    files_received = pyqtSignal(list)

    def __init__(self, app_name: str = "NotePadPQ", parent: Optional[QObject] = None):
        super().__init__(parent)
        uid = os.getuid() if hasattr(os, "getuid") else 0
        self._app_name = f"{app_name}_{uid}"
        self._server = None
        self._callback: Optional[Callable[[List[str]], None]] = None
        self._buffers: dict[int, bytes] = {}
        self._conn_seq: int = 0

    def send_args_if_secondary(self, paths: List[str]) -> bool:
        """
        Tenta un'unica connessione al server principale.
        Se riesce, invia i path e restituisce True (siamo la seconda istanza).
        Se fallisce, restituisce False (siamo la prima istanza).
        """
        sock = QLocalSocket()
        sock.connectToServer(self._app_name)

        # Aumentato a 2 secondi per PC lenti o dischi carichi
        if sock.waitForConnected(2000):
            payload = (json.dumps(paths) + "\n").encode("utf-8")
            sock.write(payload)
            sock.flush()
            sock.waitForBytesWritten(2000)
            sock.disconnectFromServer()
            sock.deleteLater()
            return True

        sock.deleteLater()
        return False

    def start_server(self, callback: Callable[[List[str]], None]) -> bool:
        """
        Avvia il server locale sulla prima istanza.
        Restituisce True se il server è stato avviato con successo (siamo
        davvero la prima istanza), False se esiste già un server vivo
        (siamo in realtà una seconda istanza arrivata qui per una race
        di avvio) o se l'avvio fallisce per un altro motivo.
        """
        self._callback = callback
        self.files_received.connect(callback)

        self._server = QLocalServer(self)

        # FIX IMPORTANTE: Ho rimosso "self._server.setSocketOptions(...)".
        # Su Windows questa opzione può bloccare totalmente la comunicazione
        # tra le istanze, causando l'apertura di finestre doppie.

        if not self._server.listen(self._app_name):
            # Il path del socket esiste già: prima di rimuoverlo verifichiamo
            # se appartiene a un server VIVO (siamo noi i secondi arrivati,
            # non dobbiamo rubare il socket) oppure è un residuo orfano di
            # un crash precedente (allora è sicuro rimuoverlo e riprovare).
            probe = QLocalSocket()
            probe.connectToServer(self._app_name)
            if probe.waitForConnected(500):
                probe.disconnectFromServer()
                probe.deleteLater()
                print("[SingleInstance] Server già attivo altrove: non avvio un secondo listener.")
                return False
            probe.deleteLater()

            QLocalServer.removeServer(self._app_name)
            if not self._server.listen(self._app_name):
                print(f"[SingleInstance] Impossibile avviare il server: {self._server.errorString()}")
                return False

        self._server.newConnection.connect(self._on_new_connection)
        return True

    def _on_new_connection(self) -> None:
        conn = self._server.nextPendingConnection()
        if not conn:
            return
        self._conn_seq += 1
        cid = self._conn_seq
        self._buffers[cid] = b""
        conn.readyRead.connect(lambda: self._on_ready_read(conn, cid))
        conn.disconnected.connect(lambda: self._cleanup_connection(conn, cid))

    def _cleanup_connection(self, conn: QLocalSocket, cid: int) -> None:
        self._buffers.pop(cid, None)
        # Disconnette entrambi i segnali prima di chiudere: previene callback
        # stale e double-free. Non chiamare deleteLater: nextPendingConnection()
        # parenta già il socket al server, che lo distruggerà a shutdown.
        try:
            conn.readyRead.disconnect()
            conn.disconnected.disconnect()
        except RuntimeError:
            pass
        try:
            conn.close()
        except RuntimeError:
            pass

    def _on_ready_read(self, conn: QLocalSocket, cid: int) -> None:
        # Esce subito se il C++ object è già stato distrutto (readyRead stale in coda)
        if sip.isdeleted(conn):
            return
        if cid not in self._buffers:
            return

        buf = self._buffers[cid]
        buf += bytes(conn.readAll())

        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            try:
                paths: List[str] = json.loads(line.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                paths = []

            if paths:
                self.files_received.emit(paths)

            QTimer.singleShot(0, self._raise_window)

        # Non tocca più conn dopo readAll(): scrive solo nel dict Python
        if cid in self._buffers:
            self._buffers[cid] = buf

    def _raise_window(self) -> None:
        """Porta la finestra principale in primo piano e toglie il 'Riduci a icona'."""
        from PyQt6.QtWidgets import QApplication
        for w in QApplication.topLevelWidgets():
            if w.isVisible() and hasattr(w, "_tab_manager"):
                w.setWindowState(w.windowState() & ~Qt.WindowState.WindowMinimized)
                w.raise_()
                w.activateWindow()
                break
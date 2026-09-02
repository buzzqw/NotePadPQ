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
    _MAX_PAYLOAD_BYTES = 64 * 1024
    _ACK_TIMEOUT_MS = 2000

    def __init__(self, app_name: str = "NotePadPQ", parent: Optional[QObject] = None):
        super().__init__(parent)
        uid = os.getuid() if hasattr(os, "getuid") else 0
        self._app_name = f"{app_name}_{uid}"
        self._server = None
        self._callback: Optional[Callable[[List[str]], None]] = None
        self._buffers: dict[int, bytes] = {}
        self._connection_slots: dict[int, tuple[Callable, Callable]] = {}
        self._conn_seq: int = 0

    def send_args_if_secondary(self, paths: List[str]) -> bool:
        """
        Tenta un'unica connessione al server principale.
        Se riesce, invia i path e restituisce True (siamo la seconda istanza).
        Se fallisce, restituisce False (siamo la prima istanza).
        """
        if not self._valid_paths(paths):
            return False

        sock = QLocalSocket()
        sock.connectToServer(self._app_name)

        # Aumentato a 2 secondi per PC lenti o dischi carichi
        if sock.waitForConnected(2000):
            payload = (json.dumps({"paths": paths}, separators=(",", ":")) + "\n").encode("utf-8")
            if sock.write(payload) != len(payload):
                sock.disconnectFromServer()
                sock.deleteLater()
                return False
            sock.flush()
            ack_data = bytes(sock.readAll())
            while b"\n" not in ack_data and sock.waitForReadyRead(self._ACK_TIMEOUT_MS):
                ack_data += bytes(sock.readAll())
            try:
                ack_line = ack_data.split(b"\n", 1)[0]
                ack = json.loads(ack_line.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                ack = {}
            sock.disconnectFromServer()
            sock.deleteLater()
            return ack == {"ok": True}

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
        ready_read = lambda c=conn, i=cid: self._on_ready_read(c, i)
        disconnected = lambda c=conn, i=cid: self._cleanup_connection(c, i)
        self._connection_slots[cid] = (ready_read, disconnected)
        conn.readyRead.connect(ready_read)
        conn.disconnected.connect(disconnected)

    def _cleanup_connection(self, conn: QLocalSocket, cid: int) -> None:
        self._buffers.pop(cid, None)
        slots = self._connection_slots.pop(cid, None)
        if not sip.isdeleted(conn) and slots is not None:
            # Disconnect only our handlers. A wildcard disconnect can touch
            # Qt's internal QNativeSocketEngine signals during notification.
            for signal, slot in ((conn.readyRead, slots[0]),
                                 (conn.disconnected, slots[1])):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        if not sip.isdeleted(conn):
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
        if len(buf) > self._MAX_PAYLOAD_BYTES:
            self._buffers.pop(cid, None)
            conn.disconnectFromServer()
            return

        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            paths = self._decode_paths(line)
            if paths is not None:
                self.files_received.emit(paths)
                conn.write(b'{"ok":true}\n')
                conn.flush()
                QTimer.singleShot(0, self._raise_window)

        # Non tocca più conn dopo readAll(): scrive solo nel dict Python
        if cid in self._buffers:
            self._buffers[cid] = buf

    @staticmethod
    def _valid_paths(paths: object) -> bool:
        return (isinstance(paths, list)
                and all(isinstance(path, str) and path and "\x00" not in path
                        for path in paths))

    @classmethod
    def _decode_paths(cls, line: bytes) -> Optional[List[str]]:
        try:
            payload = json.loads(line.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        paths = payload.get("paths")
        return paths if cls._valid_paths(paths) else None

    def _raise_window(self) -> None:
        """Porta la finestra principale in primo piano e toglie il 'Riduci a icona'."""
        from PyQt6.QtWidgets import QApplication
        for w in QApplication.topLevelWidgets():
            if w.isVisible() and hasattr(w, "_tab_manager"):
                w.setWindowState(w.windowState() & ~Qt.WindowState.WindowMinimized)
                w.raise_()
                w.activateWindow()
                break

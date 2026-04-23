"""
core/single_instance.py — Gestione istanza singola
NotePadPQ

Garantisce che giri una sola istanza dell'applicazione.
Se viene avviata una seconda istanza con un file come argomento,
il file viene inviato alla prima istanza tramite socket locale Unix,
e la seconda istanza termina immediatamente.

La prima istanza apre un QLocalServer; le successive usano QLocalSocket
per inviare i path e terminare.

Uso in main.py (vedi integrazione in fondo al file):
    si = SingleInstance("NotePadPQ")
    if si.is_secondary():
        si.send_files(sys.argv[1:])
        sys.exit(0)
    # ... avvia app normalmente ...
    si.start_server(callback=lambda paths: win.open_files([Path(p) for p in paths]))
"""

from __future__ import annotations

import json
from typing import Callable, List, Optional

from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtCore import QObject, pyqtSignal, QTimer


class SingleInstance(QObject):
    """
    Gestisce la single-instance tramite QLocalServer/QLocalSocket.

    Flusso:
      1. Prova a connettersi al server con il nome dell'app.
      2. Se riesce → siamo la seconda istanza (is_secondary() == True).
      3. Se fallisce → siamo la prima istanza; rimuovi il socket orfano
         (crash precedente) e avvia il server.
    """

    # Emesso quando arrivano path dalla seconda istanza
    files_received = pyqtSignal(list)

    def __init__(self, app_name: str = "NotePadPQ", parent: Optional[QObject] = None):
        super().__init__(parent)
        self._app_name    = app_name
        self._server      = None
        self._secondary   = False
        self._callback: Optional[Callable[[List[str]], None]] = None

        # Tenta connessione rapida per capire se c'è già un'istanza
        probe = QLocalSocket()
        probe.connectToServer(self._app_name)
        if probe.waitForConnected(300):          # 300 ms è sufficiente
            self._secondary = True
            probe.disconnectFromServer()
        probe.deleteLater()

    # ── API pubblica ──────────────────────────────────────────────────────────

    def is_secondary(self) -> bool:
        """True se esiste già un'istanza principale in esecuzione."""
        return self._secondary

    def send_files(self, paths: List[str]) -> bool:
        """
        Invia i path dei file alla prima istanza.
        Chiamare solo se is_secondary() == True.
        Restituisce True se l'invio è riuscito.
        """
        sock = QLocalSocket()
        sock.connectToServer(self._app_name)
        if not sock.waitForConnected(2000):
            return False

        # Protocollo: JSON con lista path + newline come terminatore
        payload = (json.dumps(paths) + "\n").encode("utf-8")
        sock.write(payload)
        sock.flush()
        sock.waitForBytesWritten(2000)
        sock.disconnectFromServer()
        sock.deleteLater()
        return True

    def start_server(self, callback: Callable[[List[str]], None]) -> None:
        """
        Avvia il server locale. Chiamare solo sulla prima istanza,
        dopo che la MainWindow è pronta a ricevere file.

        `callback` riceve una lista di stringhe (path assoluti).
        """
        self._callback = callback
        self.files_received.connect(callback)

        # Rimuovi eventuale socket orfano da un crash precedente
        QLocalServer.removeServer(self._app_name)

        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self._server.listen(self._app_name):
            print(f"[SingleInstance] Impossibile avviare il server: "
                  f"{self._server.errorString()}")
            return

        self._server.newConnection.connect(self._on_new_connection)

    # ── Internals ─────────────────────────────────────────────────────────────

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
                # Emette il segnale sul thread Qt principale
                self.files_received.emit(paths)

            # Porta la finestra in primo piano
            QTimer.singleShot(0, self._raise_window)

    def _raise_window(self) -> None:
        """Porta la finestra principale in primo piano."""
        from PyQt6.QtWidgets import QApplication
        for w in QApplication.topLevelWidgets():
            if w.isVisible() and hasattr(w, "_tab_manager"):
                w.setWindowState(
                    w.windowState() & ~__import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.WindowState.WindowMinimized
                )
                w.raise_()
                w.activateWindow()
                break

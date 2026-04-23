"""
editor/lsp_client.py — Client LSP opzionale
NotePadPQ

Integrazione con Language Server Protocol via subprocess.
Supporta: pylsp (Python), clangd (C/C++), rust-analyzer (Rust),
          typescript-language-server (JS/TS), texlab (LaTeX).

Attivato solo se il server è installato e LSP è abilitato nelle preferenze.
Non blocca mai l'UI — tutte le comunicazioni sono asincrone via QThread.
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Optional, Callable, TYPE_CHECKING

from PyQt6.QtCore import QObject, QThread, pyqtSignal

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

# ─── Server predefiniti per linguaggio ───────────────────────────────────────

LSP_SERVERS: dict[str, dict] = {
    "python":     {"cmd": ["pylsp"],              "available": None},
    "c/c++":      {"cmd": ["clangd"],             "available": None},
    "rust":       {"cmd": ["rust-analyzer"],      "available": None},
    "javascript": {"cmd": ["typescript-language-server", "--stdio"], "available": None},
    "typescript": {"cmd": ["typescript-language-server", "--stdio"], "available": None},
    "latex":      {"cmd": ["texlab"],             "available": None},
    "go":         {"cmd": ["gopls"],              "available": None},
}


def is_server_available(language: str) -> bool:
    """Controlla se il server LSP per il linguaggio è installato."""
    import shutil
    entry = LSP_SERVERS.get(language.lower())
    if not entry:
        return False
    if entry["available"] is None:
        cmd = entry["cmd"][0]
        entry["available"] = shutil.which(cmd) is not None
    return entry["available"]


def get_available_servers() -> dict[str, bool]:
    """Restituisce {linguaggio: disponibile} per tutti i server."""
    return {lang: is_server_available(lang) for lang in LSP_SERVERS}


# ─── Protocollo LSP (JSON-RPC su stdio) ──────────────────────────────────────

class LSPProtocol:
    """Gestisce la serializzazione/deserializzazione dei messaggi LSP."""

    def __init__(self):
        self._id = 0

    def next_id(self) -> int:
        self._id += 1
        return self._id

    def encode(self, msg: dict) -> bytes:
        body = json.dumps(msg, ensure_ascii=False)
        header = f"Content-Length: {len(body.encode())}\r\n\r\n"
        return (header + body).encode("utf-8")

    def decode_stream(self, data: bytes) -> Optional[dict]:
        """Legge un messaggio dallo stream. Restituisce None se incompleto."""
        try:
            header, _, body = data.partition(b"\r\n\r\n")
            length = int(header.split(b":")[1].strip())
            if len(body) >= length:
                return json.loads(body[:length])
        except Exception:
            pass
        return None

    def request(self, method: str, params: dict,
                req_id: Optional[int] = None) -> dict:
        msg: dict = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        if req_id is not None:
            msg["id"] = req_id
        return msg

    def notification(self, method: str, params: dict) -> dict:
        return {"jsonrpc": "2.0", "method": method, "params": params}


# ─── LSPWorker — thread di comunicazione ─────────────────────────────────────

class LSPWorker(QThread):
    """
    Thread che gestisce la comunicazione stdin/stdout con il server LSP.
    Emette segnali per le risposte ricevute.
    """

    response_received = pyqtSignal(dict)
    server_error      = pyqtSignal(str)

    def __init__(self, cmd: list[str], workspace: str):
        super().__init__()
        self._cmd       = cmd
        self._workspace = workspace
        self._proc: Optional[subprocess.Popen] = None
        self._proto     = LSPProtocol()
        self._buffer    = b""
        self._running   = False
        self._send_lock = threading.Lock()

    def run(self) -> None:
        try:
            self._proc = subprocess.Popen(
                self._cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            self._running = True

            # Inizializzazione LSP
            init_msg = self._proto.request("initialize", {
                "processId": None,
                "rootUri": f"file://{self._workspace}",
                "capabilities": {
                    "textDocument": {
                        "completion": {
                            "completionItem": {
                                "snippetSupport": False,
                                "documentationFormat": ["plaintext"],
                            }
                        },
                        "hover": {"contentFormat": ["plaintext"]},
                        "definition": {},
                        "publishDiagnostics": {},
                    }
                },
                "initializationOptions": {},
            }, req_id=self._proto.next_id())

            self._send(init_msg)

            # Loop lettura risposte
            while self._running and self._proc.poll() is None:
                chunk = self._proc.stdout.read(4096)
                if not chunk:
                    break
                self._buffer += chunk
                msg = self._proto.decode_stream(self._buffer)
                if msg:
                    self._buffer = b""
                    self.response_received.emit(msg)

        except Exception as e:
            self.server_error.emit(str(e))
        finally:
            self._running = False

    def send(self, msg: dict) -> None:
        """Invia un messaggio al server (thread-safe)."""
        with self._send_lock:
            self._send(msg)

    def _send(self, msg: dict) -> None:
        if self._proc and self._proc.stdin:
            try:
                self._proc.stdin.write(self._proto.encode(msg))
                self._proc.stdin.flush()
            except Exception:
                pass

    def stop(self) -> None:
        self._running = False
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass


# ─── LSPClient — interfaccia pubblica ────────────────────────────────────────

class LSPClient(QObject):
    """
    Client LSP per un linguaggio specifico.
    Un'istanza per linguaggio, condivisa tra tutti i tab dello stesso tipo.
    """

    completions_ready = pyqtSignal(list)    # lista di dict completion
    diagnostics_ready = pyqtSignal(str, list)  # uri, lista diagnostics
    hover_ready       = pyqtSignal(str)     # testo hover

    _instances: dict[str, "LSPClient"] = {}

    def __init__(self, language: str, workspace: str):
        super().__init__()
        self._language  = language
        self._workspace = workspace
        self._worker: Optional[LSPWorker] = None
        self._proto     = LSPProtocol()
        self._pending: dict[int, str] = {}   # id → tipo richiesta
        self._initialized = False
        self._open_files: set[str] = set()

    @classmethod
    def get(cls, language: str,
            workspace: str = "") -> Optional["LSPClient"]:
        """
        Restituisce (o crea) il client per il linguaggio dato.
        Restituisce None se il server non è disponibile.
        """
        if not is_server_available(language):
            return None
        key = f"{language}:{workspace}"
        if key not in cls._instances:
            client = cls(language, workspace or str(Path.home()))
            client._start()
            cls._instances[key] = client
        return cls._instances[key]

    def _start(self) -> None:
        cmd = LSP_SERVERS[self._language]["cmd"]
        self._worker = LSPWorker(cmd, self._workspace)
        self._worker.response_received.connect(self._handle_response)
        self._worker.server_error.connect(
            lambda e: print(f"[LSP:{self._language}] {e}")
        )
        self._worker.start()

    def _handle_response(self, msg: dict) -> None:
        method = msg.get("method", "")
        msg_id = msg.get("id")

        if method == "textDocument/publishDiagnostics":
            params = msg.get("params", {})
            uri    = params.get("uri", "")
            diags  = params.get("diagnostics", [])
            self.diagnostics_ready.emit(uri, diags)
            return

        if msg_id and msg_id in self._pending:
            req_type = self._pending.pop(msg_id)
            result   = msg.get("result", {})

            if req_type == "completion":
                items = result if isinstance(result, list) else result.get("items", [])
                completions = [
                    {
                        "label":  item.get("label", ""),
                        "detail": item.get("detail", ""),
                        "kind":   item.get("kind", 0),
                    }
                    for item in items[:50]   # limite ragionevole
                ]
                self.completions_ready.emit(completions)

            elif req_type == "hover":
                contents = result.get("contents", "") if result else ""
                if isinstance(contents, dict):
                    contents = contents.get("value", "")
                elif isinstance(contents, list):
                    contents = "\n".join(
                        c.get("value", c) if isinstance(c, dict) else str(c)
                        for c in contents
                    )
                self.hover_ready.emit(str(contents))

        elif msg_id == 1:
            # Risposta a initialize
            self._initialized = True
            if self._worker:
                self._worker.send(
                    self._proto.notification("initialized", {})
                )

    # ── API pubblica ──────────────────────────────────────────────────────────

    def open_file(self, path: Path, content: str, language_id: str) -> None:
        """Notifica l'apertura di un file al server."""
        if not self._initialized or not self._worker:
            return
        uri = path.as_uri()
        if uri in self._open_files:
            return
        self._open_files.add(uri)
        self._worker.send(self._proto.notification(
            "textDocument/didOpen", {
                "textDocument": {
                    "uri":        uri,
                    "languageId": language_id,
                    "version":    1,
                    "text":       content,
                }
            }
        ))

    def update_file(self, path: Path, content: str, version: int) -> None:
        """Notifica una modifica al file."""
        if not self._initialized or not self._worker:
            return
        self._worker.send(self._proto.notification(
            "textDocument/didChange", {
                "textDocument": {
                    "uri":     path.as_uri(),
                    "version": version,
                },
                "contentChanges": [{"text": content}],
            }
        ))

    def close_file(self, path: Path) -> None:
        """Notifica la chiusura di un file."""
        if not self._initialized or not self._worker:
            return
        uri = path.as_uri()
        self._open_files.discard(uri)
        self._worker.send(self._proto.notification(
            "textDocument/didClose",
            {"textDocument": {"uri": uri}}
        ))

    def request_completions(self, path: Path,
                             line: int, col: int) -> None:
        """Richiede completamenti alla posizione data (0-based)."""
        if not self._initialized or not self._worker:
            return
        req_id = self._proto.next_id()
        self._pending[req_id] = "completion"
        self._worker.send(self._proto.request(
            "textDocument/completion", {
                "textDocument": {"uri": path.as_uri()},
                "position":     {"line": line, "character": col},
            }, req_id=req_id
        ))

    def request_hover(self, path: Path, line: int, col: int) -> None:
        """Richiede informazioni hover alla posizione data."""
        if not self._initialized or not self._worker:
            return
        req_id = self._proto.next_id()
        self._pending[req_id] = "hover"
        self._worker.send(self._proto.request(
            "textDocument/hover", {
                "textDocument": {"uri": path.as_uri()},
                "position":     {"line": line, "character": col},
            }, req_id=req_id
        ))

    def stop(self) -> None:
        if self._worker:
            self._worker.stop()
            self._worker.wait(2000)

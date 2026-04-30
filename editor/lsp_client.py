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
from typing import Optional, TYPE_CHECKING

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

LANG_ID_MAP: dict[str, str] = {
    "python":     "python",
    "c/c++":      "cpp",
    "rust":       "rust",
    "javascript": "javascript",
    "typescript": "typescript",
    "latex":      "latex",
    "go":         "go",
}


def is_server_available(language: str) -> bool:
    import shutil
    entry = LSP_SERVERS.get(language.lower())
    if not entry:
        return False
    if entry["available"] is None:
        cmd = entry["cmd"][0]
        entry["available"] = shutil.which(cmd) is not None
    return entry["available"]


def get_available_servers() -> dict[str, bool]:
    return {lang: is_server_available(lang) for lang in LSP_SERVERS}


def lang_to_id(language: str) -> str:
    return LANG_ID_MAP.get(language.lower(), language.lower())


# ─── Protocollo LSP (JSON-RPC su stdio) ──────────────────────────────────────

class LSPProtocol:

    def __init__(self):
        self._id = 0

    def next_id(self) -> int:
        self._id += 1
        return self._id

    def encode(self, msg: dict) -> bytes:
        body = json.dumps(msg, ensure_ascii=False)
        header = f"Content-Length: {len(body.encode())}\r\n\r\n"
        return (header + body).encode("utf-8")

    def request(self, method: str, params: dict,
                req_id: Optional[int] = None) -> dict:
        msg: dict = {"jsonrpc": "2.0", "method": method, "params": params}
        if req_id is not None:
            msg["id"] = req_id
        return msg

    def notification(self, method: str, params: dict) -> dict:
        return {"jsonrpc": "2.0", "method": method, "params": params}


# ─── LSPWorker — thread di comunicazione ─────────────────────────────────────

class LSPWorker(QThread):
    """Thread che legge stdout del server LSP con parser corretto (Content-Length)."""

    response_received = pyqtSignal(dict)
    server_error      = pyqtSignal(str)

    def __init__(self, cmd: list[str], workspace: str):
        super().__init__()
        self._cmd       = cmd
        self._workspace = workspace
        self._proc: Optional[subprocess.Popen] = None
        self._proto     = LSPProtocol()
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

            self._send(self._proto.request("initialize", {
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
                        "hover":            {"contentFormat": ["plaintext"]},
                        "definition":       {},
                        "references":       {"includeDeclaration": True},
                        "formatting":       {},
                        "rename":           {},
                        "signatureHelp":    {
                            "signatureInformation": {
                                "documentationFormat": ["plaintext"]
                            }
                        },
                        "publishDiagnostics": {},
                    }
                },
                "initializationOptions": {},
            }, req_id=self._proto.next_id()))

            stdout = self._proc.stdout
            while self._running and self._proc.poll() is None:
                # Read header byte-by-byte until \r\n\r\n
                header_bytes = b""
                while True:
                    ch = stdout.read(1)
                    if not ch:
                        return
                    header_bytes += ch
                    if header_bytes.endswith(b"\r\n\r\n"):
                        break

                # Parse Content-Length
                length = 0
                for raw_line in header_bytes.split(b"\r\n"):
                    if raw_line.lower().startswith(b"content-length:"):
                        try:
                            length = int(raw_line.split(b":", 1)[1].strip())
                        except ValueError:
                            pass
                        break

                if length == 0:
                    continue

                # Read exactly `length` bytes for the body
                body = b""
                while len(body) < length:
                    chunk = stdout.read(length - len(body))
                    if not chunk:
                        return
                    body += chunk

                try:
                    msg = json.loads(body)
                    self.response_received.emit(msg)
                except Exception:
                    pass

        except Exception as e:
            self.server_error.emit(str(e))
        finally:
            self._running = False

    def send(self, msg: dict) -> None:
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
    """Client LSP per un linguaggio. Un'istanza per linguaggio+workspace."""

    completions_ready = pyqtSignal(list)
    diagnostics_ready = pyqtSignal(str, list)   # uri, lista diagnostics
    hover_ready       = pyqtSignal(str)
    definition_ready  = pyqtSignal(str, int, int)  # uri, line, col (0-based)
    references_ready  = pyqtSignal(list)            # [{uri, line, col}]
    formatting_ready  = pyqtSignal(list)            # list of TextEdit dicts
    rename_ready      = pyqtSignal(dict)            # WorkspaceEdit
    signature_ready   = pyqtSignal(str)             # label testo

    _instances: dict[str, "LSPClient"] = {}

    def __init__(self, language: str, workspace: str):
        super().__init__()
        self._language    = language
        self._workspace   = workspace
        self._worker: Optional[LSPWorker] = None
        self._proto       = LSPProtocol()
        self._pending: dict[int, str] = {}
        self._initialized = False
        self._open_files: set[str] = set()

    @classmethod
    def get(cls, language: str, workspace: str = "") -> Optional["LSPClient"]:
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
            self.diagnostics_ready.emit(params.get("uri", ""), params.get("diagnostics", []))
            return

        if msg_id and msg_id in self._pending:
            req_type = self._pending.pop(msg_id)
            result   = msg.get("result")

            if req_type == "completion":
                items = result if isinstance(result, list) else (result or {}).get("items", [])
                self.completions_ready.emit([
                    {"label": i.get("label", ""), "detail": i.get("detail", ""), "kind": i.get("kind", 0)}
                    for i in items[:50]
                ])

            elif req_type == "hover":
                contents = (result or {}).get("contents", "") if result else ""
                if isinstance(contents, dict):
                    contents = contents.get("value", "")
                elif isinstance(contents, list):
                    contents = "\n".join(
                        c.get("value", c) if isinstance(c, dict) else str(c)
                        for c in contents
                    )
                self.hover_ready.emit(str(contents))

            elif req_type == "definition":
                locs = result if isinstance(result, list) else ([result] if result else [])
                if locs:
                    first = locs[0]
                    uri   = first.get("uri", "")
                    start = first.get("range", {}).get("start", {})
                    self.definition_ready.emit(uri, start.get("line", 0), start.get("character", 0))

            elif req_type == "references":
                refs = []
                for r in (result or []):
                    start = r.get("range", {}).get("start", {})
                    refs.append({"uri": r.get("uri", ""), "line": start.get("line", 0), "col": start.get("character", 0)})
                self.references_ready.emit(refs)

            elif req_type == "formatting":
                self.formatting_ready.emit(result or [])

            elif req_type == "rename":
                self.rename_ready.emit(result or {})

            elif req_type == "signature":
                sigs  = (result or {}).get("signatures", [])
                label = sigs[0].get("label", "") if sigs else ""
                self.signature_ready.emit(label)

        elif msg_id == 1:
            self._initialized = True
            if self._worker:
                self._worker.send(self._proto.notification("initialized", {}))

    # ── API pubblica ──────────────────────────────────────────────────────────

    def open_file(self, path: Path, content: str, language_id: str) -> None:
        if not self._initialized or not self._worker:
            return
        uri = path.as_uri()
        if uri in self._open_files:
            return
        self._open_files.add(uri)
        self._worker.send(self._proto.notification("textDocument/didOpen", {
            "textDocument": {"uri": uri, "languageId": language_id, "version": 1, "text": content}
        }))

    def update_file(self, path: Path, content: str, version: int) -> None:
        if not self._initialized or not self._worker:
            return
        self._worker.send(self._proto.notification("textDocument/didChange", {
            "textDocument": {"uri": path.as_uri(), "version": version},
            "contentChanges": [{"text": content}],
        }))

    def close_file(self, path: Path) -> None:
        if not self._initialized or not self._worker:
            return
        uri = path.as_uri()
        self._open_files.discard(uri)
        self._worker.send(self._proto.notification("textDocument/didClose", {"textDocument": {"uri": uri}}))

    def request_completions(self, path: Path, line: int, col: int) -> None:
        if not self._initialized or not self._worker:
            return
        req_id = self._proto.next_id()
        self._pending[req_id] = "completion"
        self._worker.send(self._proto.request("textDocument/completion", {
            "textDocument": {"uri": path.as_uri()},
            "position":     {"line": line, "character": col},
        }, req_id=req_id))

    def request_hover(self, path: Path, line: int, col: int) -> None:
        if not self._initialized or not self._worker:
            return
        req_id = self._proto.next_id()
        self._pending[req_id] = "hover"
        self._worker.send(self._proto.request("textDocument/hover", {
            "textDocument": {"uri": path.as_uri()},
            "position":     {"line": line, "character": col},
        }, req_id=req_id))

    def request_definition(self, path: Path, line: int, col: int) -> None:
        if not self._initialized or not self._worker:
            return
        req_id = self._proto.next_id()
        self._pending[req_id] = "definition"
        self._worker.send(self._proto.request("textDocument/definition", {
            "textDocument": {"uri": path.as_uri()},
            "position":     {"line": line, "character": col},
        }, req_id=req_id))

    def request_references(self, path: Path, line: int, col: int) -> None:
        if not self._initialized or not self._worker:
            return
        req_id = self._proto.next_id()
        self._pending[req_id] = "references"
        self._worker.send(self._proto.request("textDocument/references", {
            "textDocument": {"uri": path.as_uri()},
            "position":     {"line": line, "character": col},
            "context":      {"includeDeclaration": True},
        }, req_id=req_id))

    def request_formatting(self, path: Path, tab_size: int = 4, insert_spaces: bool = True) -> None:
        if not self._initialized or not self._worker:
            return
        req_id = self._proto.next_id()
        self._pending[req_id] = "formatting"
        self._worker.send(self._proto.request("textDocument/formatting", {
            "textDocument": {"uri": path.as_uri()},
            "options":      {"tabSize": tab_size, "insertSpaces": insert_spaces},
        }, req_id=req_id))

    def request_rename(self, path: Path, line: int, col: int, new_name: str) -> None:
        if not self._initialized or not self._worker:
            return
        req_id = self._proto.next_id()
        self._pending[req_id] = "rename"
        self._worker.send(self._proto.request("textDocument/rename", {
            "textDocument": {"uri": path.as_uri()},
            "position":     {"line": line, "character": col},
            "newName":      new_name,
        }, req_id=req_id))

    def request_signature(self, path: Path, line: int, col: int) -> None:
        if not self._initialized or not self._worker:
            return
        req_id = self._proto.next_id()
        self._pending[req_id] = "signature"
        self._worker.send(self._proto.request("textDocument/signatureHelp", {
            "textDocument": {"uri": path.as_uri()},
            "position":     {"line": line, "character": col},
        }, req_id=req_id))

    def stop(self) -> None:
        if self._worker:
            self._worker.stop()
            self._worker.wait(2000)

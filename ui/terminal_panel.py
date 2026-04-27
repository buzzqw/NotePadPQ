"""
ui/terminal_panel.py — Terminale integrato (Basato su xterm.js)
NotePadPQ

Pannello terminale embedded basato su QWebEngineView e xterm.js.
Esegue una vera e propria sessione shell continua.
"""

import os
import json
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QUrl, Qt, QProcess, QProcessEnvironment, pyqtSignal, pyqtSlot, QObject, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QToolButton, QLabel, QMessageBox
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel


# ─── Bridge di comunicazione JS <-> Python ──────────────────────────────────

class TerminalBackend(QObject):
    """Gestisce la ricezione degli input digitati dall'utente in xterm.js"""
    input_received = pyqtSignal(str)

    @pyqtSlot(str)
    def receive_input(self, data: str):
        self.input_received.emit(data)


# ─── Codice HTML/JS del Terminale ──────────────────────────────────────────

XTERM_HTML = r"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <link rel="stylesheet" href="xterm.css" />
    <script src="xterm.js"></script>
    <script src="addon-fit.js"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <style>
        html, body { 
            margin: 0; padding: 0; height: 100%; width: 100%;
            background-color: #1e1e1e; overflow: hidden; 
        }
        #terminal { 
            height: 100%; width: 100%; 
            padding-top: 4px; padding-left: 4px;
        }
        /* Custom scrollbar matching VS Code style */
        .xterm-viewport::-webkit-scrollbar { width: 10px; }
        .xterm-viewport::-webkit-scrollbar-track { background: #1e1e1e; }
        .xterm-viewport::-webkit-scrollbar-thumb { background: #424242; }
        .xterm-viewport::-webkit-scrollbar-thumb:hover { background: #4f4f4f; }
    </style>
</head>
<body>
    <div id="terminal"></div>
    <script>
        window.onload = function() {
            const term = new Terminal({
                theme: { 
                    background: '#1e1e1e', 
                    foreground: '#d4d4d4',
                    cursor: '#ffffff'
                },
                cursorBlink: true,
                fontFamily: 'Monospace, Consolas, "Courier New"',
                fontSize: 13,
                convertEol: true,
                cols: 80, // Default sicuro
                rows: 24
            });

            const fitAddon = new FitAddon.FitAddon();
            term.loadAddon(fitAddon);
            term.open(document.getElementById('terminal'));
            term.write('\x1b[32m[ NotePadPQ Terminal Ready ]\x1b[0m\r\n');
            
            let shellStarted = false;

            // 🟢 FUNZIONE INTELLIGENTE: fa il fit SOLO se il tab è realmente visibile
            function safeFit() {
                const el = document.getElementById('terminal');
                if (el && el.clientWidth > 10) {
                    try { fitAddon.fit(); } catch(e) {}
                    return true;
                }
                return false;
            }

            const resizeObserver = new ResizeObserver(() => { safeFit(); });
            resizeObserver.observe(document.getElementById('terminal'));
            window.addEventListener('resize', safeFit);

            if (typeof qt !== 'undefined' && qt.webChannelTransport) {
                new QWebChannel(qt.webChannelTransport, function(channel) {
                    window.backend = channel.objects.backend;
                    
                    // 🟢 LOOP DI ATTESA: Controlla ogni 100ms se il pannello è stato mostrato a video
                    let checkInterval = setInterval(() => {
                        if (safeFit()) {
                            // Il pannello è finalmente visibile! Fermiamo il loop.
                            clearInterval(checkInterval);
                            term.focus();
                            
                            // Inviamo il finto Invio a Bash solo ora che lo schermo è largo il giusto
                            if (!shellStarted && window.backend) {
                                shellStarted = true;
                                window.backend.receive_input('\r'); 
                            }
                        }
                    }, 100);
                    
                    term.onData(data => {
                        if (window.backend) {
                            window.backend.receive_input(data);
                        }
                    });
                });
            } else {
                term.write('\r\n\x1b[31m[ Errore: Bridge QWebChannel non trovato ]\x1b[0m\r\n');
            }

            window.writeOutput = function(data) {
                term.write(data);
            };

            window.clearTerminal = function() {
                term.clear();
            };
        };
    </script>
</body>
</html>
"""

# ─── Widget Principale ──────────────────────────────────────────────────────

class TerminalPanel(QWidget):
    """
    Terminale integrato basato su QWebEngineView (xterm.js).
    Mantiene una sessione shell persistente.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cwd: Path = Path.home()
        self._process: Optional[QProcess] = None
        self._setup_ui()
        self._start_shell()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Barra superiore
        bar_widget = QWidget()
        bar_widget.setStyleSheet("background-color: #252526; border-bottom: 1px solid #3c3c3c;")
        bar = QHBoxLayout(bar_widget)
        bar.setContentsMargins(8, 2, 8, 2)
        bar.setSpacing(6)

        self._cwd_label = QLabel()
        self._cwd_label.setStyleSheet("color: #7ec8e3; font-size: 11px;")
        self._update_cwd_label()
        bar.addWidget(self._cwd_label)
        bar.addStretch()

        btn_clear = QToolButton()
        btn_clear.setText("🗑 Pulisci")
        btn_clear.setToolTip("Pulisci schermo")
        btn_clear.setStyleSheet("color: #d4d4d4; background: transparent; border: none;")
        btn_clear.clicked.connect(self.clear_output)
        bar.addWidget(btn_clear)

        btn_restart = QToolButton()
        btn_restart.setText("🔄 Riavvia")
        btn_restart.setToolTip("Riavvia la sessione terminale")
        btn_restart.setStyleSheet("color: #d4d4d4; background: transparent; border: none;")
        btn_restart.clicked.connect(self._restart_shell)
        bar.addWidget(btn_restart)

        btn_stop = QToolButton()
        btn_stop.setText("⏹ Stop")
        btn_stop.setStyleSheet("color: #f44747; background: transparent; border: none;")
        btn_stop.setToolTip("Termina processo")
        btn_stop.clicked.connect(self._kill_process)
        bar.addWidget(btn_stop)

        layout.addWidget(bar_widget)

        # ── Creazione e setup della WebEngineView ──
        self._webview = QWebEngineView()
        self._webview.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        
        # Setup QWebChannel
        self._channel = QWebChannel()
        self._backend = TerminalBackend()
        self._channel.registerObject("backend", self._backend)
        self._webview.page().setWebChannel(self._channel)
        
        # Collega l'input di xterm.js al processo
        self._backend.input_received.connect(self._write_to_process)

        # Carica l'HTML usando i file xterm locali come base URL
        assets_dir = Path(__file__).parent / "assets" / "xterm"
        base_url = QUrl.fromLocalFile(str(assets_dir) + "/")
        self._webview.setHtml(XTERM_HTML, base_url)
        layout.addWidget(self._webview, stretch=1)

    # ── Logica terminale ──────────────────────────────────────────────────────

    def _start_shell(self) -> None:
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            return

        self._process = QProcess(self)
        self._process.setWorkingDirectory(str(self._cwd))
        
        # Setup variabili d'ambiente
        env = QProcessEnvironment.systemEnvironment()
        env.insert("TERM", "xterm-256color")
        env.insert("COLORTERM", "truecolor")
        env.insert("PYTHONUNBUFFERED", "1")  # Cruciale per non bloccare l'output
        self._process.setProcessEnvironment(env)
        
        # Collegamento segnali
        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_finished)

        # Lancia la shell interattiva
        if os.name == "nt":
            self._process.start("cmd.exe")
            QTimer.singleShot(500, lambda: self._write_to_process("\r\n"))
        else:
            shell = os.environ.get("SHELL", "/bin/bash")
            self._process.start("python3", ["-c", f"import pty; pty.spawn('{shell}')"])            

    def _restart_shell(self) -> None:
        self.clear_output()
        self._kill_process()
        self._start_shell()

    def _kill_process(self) -> None:
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
            self._process.waitForFinished(500)
        
        self._write_to_js("\r\n\x1b[31m[Processo terminato]\x1b[0m\r\n")

    def _write_to_process(self, data: str) -> None:
        """Invia i tasti premuti in xterm.js al QProcess"""
        if self._process and self._process.state() == QProcess.ProcessState.Running:
            self._process.write(data.encode('utf-8'))

    def _on_stdout(self) -> None:
        if self._process:
            data = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
            self._write_to_js(data)

    def _on_stderr(self) -> None:
        if self._process:
            data = bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace")
            self._write_to_js(data)

    def _on_finished(self, exit_code: int, exit_status) -> None:
        msg = f"\r\n\x1b[31m[Processo terminato con codice {exit_code}]\x1b[0m\r\n"
        self._write_to_js(msg)

    def _write_to_js(self, data: str) -> None:
        """Invia l'output del processo alla console xterm.js"""
        # Siccome stiamo inviando stringhe raw a JS, dobbiamo farne l'escape corretto
        # json.dumps è il modo più sicuro per passare una stringa complessa a eval() JS
        js_code = f"if (window.writeOutput) window.writeOutput({json.dumps(data)});"
        self._webview.page().runJavaScript(js_code)

    def clear_output(self) -> None:
        """Svuota la console xterm.js"""
        self._webview.page().runJavaScript("if (window.clearTerminal) window.clearTerminal();")

    def _set_cwd(self, path: Path) -> None:
        self._cwd = path
        self._update_cwd_label()
        
    def _update_cwd_label(self) -> None:
        self._cwd_label.setText(f"📁 {self._cwd}")

    def set_cwd_from_file(self, file_path: Path) -> None:
        """Imposta la directory di lavoro alla cartella del file aperto."""
        self._set_cwd(file_path.parent)

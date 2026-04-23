"""
ui/terminal_panel.py — Terminale integrato
NotePadPQ

Pannello terminale embedded basato su QProcess.
Supporta: esecuzione comandi, output colorato ANSI, storia comandi (↑/↓),
          cambio directory, pulizia schermo.
"""

import os
import re
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QProcess, QProcessEnvironment, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeySequence, QTextCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QLineEdit, QToolButton, QLabel,
)


# Regex per strippare sequenze ANSI di colore
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


class TerminalPanel(QWidget):
    """
    Terminale integrato leggero basato su QProcess.
    Ogni comando viene eseguito in una shell separata.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cwd: Path = Path.home()
        self._history: list[str] = []
        self._history_idx: int = -1
        self._process: Optional[QProcess] = None
        self._setup_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # Barra superiore
        bar = QHBoxLayout()
        bar.setSpacing(4)

        self._cwd_label = QLabel()
        self._cwd_label.setStyleSheet("color: #7ec8e3; font-size: 11px;")
        self._update_cwd_label()
        bar.addWidget(self._cwd_label)
        bar.addStretch()

        btn_clear = QToolButton()
        btn_clear.setText("🗑 Pulisci")
        btn_clear.setToolTip("Pulisci output (Ctrl+L)")
        btn_clear.clicked.connect(self.clear_output)
        bar.addWidget(btn_clear)

        btn_stop = QToolButton()
        btn_stop.setText("⏹ Stop")
        btn_stop.setToolTip("Termina processo corrente")
        btn_stop.clicked.connect(self._kill_process)
        bar.addWidget(btn_stop)

        layout.addLayout(bar)

        # Area output
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumBlockCount(5000)
        font = QFont("Monospace", 10)
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        self._output.setFont(font)
        self._output.setStyleSheet(
            "QPlainTextEdit { background: #1e1e1e; color: #d4d4d4; border: none; }"
        )
        layout.addWidget(self._output, stretch=1)

        # Riga di input
        input_bar = QHBoxLayout()
        input_bar.setSpacing(4)

        prompt = QLabel("$")
        prompt.setStyleSheet("color: #7ec8e3; font-weight: bold; font-family: monospace;")
        input_bar.addWidget(prompt)

        self._input = QLineEdit()
        self._input.setFont(font)
        self._input.setStyleSheet(
            "QLineEdit { background: #252526; color: #d4d4d4; border: 1px solid #3c3c3c; "
            "padding: 2px 4px; }"
        )
        self._input.setPlaceholderText("Inserisci comando...")
        self._input.returnPressed.connect(self._run_command)
        self._input.installEventFilter(self)
        input_bar.addWidget(self._input)

        btn_run = QToolButton()
        btn_run.setText("▶")
        btn_run.setToolTip("Esegui (Invio)")
        btn_run.clicked.connect(self._run_command)
        input_bar.addWidget(btn_run)

        layout.addLayout(input_bar)

        self._print_welcome()

    # ── Logica terminale ──────────────────────────────────────────────────────

    def _print_welcome(self) -> None:
        self._append_output(
            "NotePadPQ — Terminale integrato\n"
            "Digita un comando e premi Invio. Usa ↑/↓ per la storia.\n"
            "─" * 50 + "\n",
            color="#7ec8e3"
        )

    def _run_command(self) -> None:
        cmd = self._input.text().strip()
        if not cmd:
            return

        # Aggiunge alla storia
        if not self._history or self._history[-1] != cmd:
            self._history.append(cmd)
        self._history_idx = -1
        self._input.clear()

        # Mostra il comando nell'output
        self._append_output(f"$ {cmd}\n", color="#7ec8e3")

        # Gestione comandi built-in
        if cmd in ("clear", "cls"):
            self.clear_output()
            return
        if cmd.startswith("cd "):
            self._builtin_cd(cmd[3:].strip())
            return
        if cmd == "cd":
            self._set_cwd(Path.home())
            return

        # Esegui tramite shell
        self._kill_process()
        self._process = QProcess(self)
        self._process.setWorkingDirectory(str(self._cwd))
        env = QProcessEnvironment.systemEnvironment()
        env.insert("TERM", "dumb")
        self._process.setProcessEnvironment(env)
        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_finished)

        shell = os.environ.get("SHELL", "/bin/bash")
        self._process.start(shell, ["-c", cmd])

    def _builtin_cd(self, path_str: str) -> None:
        target = Path(path_str).expanduser()
        if not target.is_absolute():
            target = self._cwd / target
        target = target.resolve()
        if target.is_dir():
            self._set_cwd(target)
        else:
            self._append_output(f"cd: {path_str}: cartella non trovata\n", color="#f44747")

    def _set_cwd(self, path: Path) -> None:
        self._cwd = path
        self._update_cwd_label()
        self._append_output(f"[{self._cwd}]\n", color="#608b4e")

    def _update_cwd_label(self) -> None:
        self._cwd_label.setText(f"📁 {self._cwd}")

    def _kill_process(self) -> None:
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
            self._process.waitForFinished(500)
        self._process = None

    def _on_stdout(self) -> None:
        if self._process:
            data = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
            self._append_output(_ANSI_RE.sub("", data))

    def _on_stderr(self) -> None:
        if self._process:
            data = bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace")
            self._append_output(_ANSI_RE.sub("", data), color="#f44747")

    def _on_finished(self, exit_code: int, exit_status) -> None:
        if exit_code != 0:
            self._append_output(f"[Processo terminato con codice {exit_code}]\n",
                                color="#f44747")
        self._process = None

    def _append_output(self, text: str, color: str = "") -> None:
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if color:
            fmt = cursor.charFormat()
            fmt.setForeground(QColor(color))
            cursor.setCharFormat(fmt)
            cursor.insertText(text)
            fmt.setForeground(QColor("#d4d4d4"))
            cursor.setCharFormat(fmt)
        else:
            cursor.insertText(text)
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    def clear_output(self) -> None:
        self._output.clear()

    def set_cwd_from_file(self, file_path: Path) -> None:
        """Imposta la directory di lavoro alla cartella del file aperto."""
        self._set_cwd(file_path.parent)

    # ── Storia comandi (↑/↓) ─────────────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        from PyQt6.QtCore import QEvent
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Up:
                self._history_navigate(-1)
                return True
            if key == Qt.Key.Key_Down:
                self._history_navigate(1)
                return True
            if key == Qt.Key.Key_L and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.clear_output()
                return True
        return super().eventFilter(obj, event)

    def _history_navigate(self, direction: int) -> None:
        if not self._history:
            return
        if self._history_idx == -1:
            self._history_idx = len(self._history)
        self._history_idx = max(0, min(len(self._history) - 1,
                                       self._history_idx + direction))
        self._input.setText(self._history[self._history_idx])
        self._input.end(False)

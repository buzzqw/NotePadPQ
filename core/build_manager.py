"""
core/build_manager.py — Gestione profili di compilazione
NotePadPQ

Profili configurabili per linguaggio con:
- Comandi shell (compile / run / build)
- Variabili: ${FILE}, ${DIR}, ${BASENAME}, ${EXT}, ${LINE}, ${COL}
- Variabili d'ambiente personalizzate per profilo
- Hook pre/post build
- Pipeline multi-step configurabili
- Supporto PTY per build interattive
- Build concorrenti (worker multipli)
- File .notepadpq-build.json per progetto
- Parsing errori (riga:colonna cliccabile)
- Task discovery estesa (Makefile, npm, Cargo, CMake, Gradle, Docker, justfile)
- Shell configurabile per piattaforma
- Salvataggio automatico prima della compilazione
- Limite output configurabile
"""

from __future__ import annotations

import json
import os
import queue
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING
from uuid import uuid4

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core.platform import get_default_shell, get_shell_exec_flag, IS_WINDOWS
from core.platform import get_config_dir
from core.latex_project import get_output_directory
from core.diagnostics import profile_operation
from i18n.i18n import tr

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget


def _log_warn(msg: str) -> None:
    """Log a warning to stderr — silent fallbacks should not hide real issues."""
    print(f"[build_manager] {msg}", file=sys.stderr)


BuildCommand = str | list[str]

BUILD_STATE_QUEUED = "queued"
BUILD_STATE_RUNNING = "running"
BUILD_STATE_SUCCEEDED = "succeeded"
BUILD_STATE_FAILED = "failed"
BUILD_STATE_CANCELLED = "cancelled"
BUILD_STATE_TIMED_OUT = "timed_out"


def _popen_process_group_kwargs() -> dict:
    """Create a separate process group so cancellation reaches child processes."""
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _terminate_process_tree(proc: subprocess.Popen, grace_seconds: float = 1.0) -> None:
    """Stop ``proc`` and every child it started, escalating after a short grace."""
    if proc.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            # terminate() only stops the shell wrapper on Windows; taskkill /T
            # also reaches compilers and commands it has started.
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            try:
                proc.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        try:
            proc.terminate()
        except OSError:
            pass


def _command_needs_shell(command: str) -> bool:
    """Keep shell execution only for profiles that explicitly use shell syntax."""
    placeholders = re.sub(r"\$\{[A-Z]+\}|\$\([A-Z]+\)", "__VALUE__", command)
    return bool(re.search(r"(?:&&|\|\||[|;<>`\n]|\$(?!\{)|[*?\[])", placeholders))

# ─── Profili predefiniti ──────────────────────────────────────────────────────

DEFAULT_PROFILES: dict[str, dict] = {
    "Python": {
        "extensions": [".py"],
        "compile":    "",
        "run":        "python3 ${FILE}",
        "build":      "",
        "error_regex": r'File "([^"]+)", line (\d+)',
        "error_file_group": 1,
        "error_line_group": 2,
    },
    "Python (uv)": {
        "extensions": [".py"],
        "compile":    "",
        "run":        "uv run ${FILE}",
        "build":      "",
        "error_regex": r'File "([^"]+)", line (\d+)',
        "error_file_group": 1,
        "error_line_group": 2,
    },
    "C (gcc)": {
        "extensions": [".c"],
        "compile":    "gcc -Wall -o ${DIR}/${BASENAME} ${FILE}",
        "run":        "${DIR}/${BASENAME}",
        "build":      "gcc -Wall -o ${DIR}/${BASENAME} ${FILE} && ${DIR}/${BASENAME}",
        "error_regex": r'([^:]+):(\d+):\d+: (?:error|warning): (.+)',
        "error_file_group": 1,
        "error_line_group": 2,
    },
    "C++ (g++)": {
        "extensions": [".cpp", ".cxx", ".cc", ".hpp", ".h"],
        "compile":    "g++ -std=c++17 -Wall -o ${DIR}/${BASENAME} ${FILE}",
        "run":        "${DIR}/${BASENAME}",
        "build":      "g++ -std=c++17 -Wall -o ${DIR}/${BASENAME} ${FILE} && ${DIR}/${BASENAME}",
        "error_regex": r'([^:]+):(\d+):\d+: (?:error|warning): (.+)',
        "error_file_group": 1,
        "error_line_group": 2,
    },
    "LaTeX (pdflatex)": {
        "extensions": [".tex", ".ltx", ".latex"],
        "compile":    "pdflatex -file-line-error -synctex=1 -interaction=nonstopmode -output-directory=${OUTDIR} ${FILE}",
        "run":        "pdflatex -file-line-error -synctex=1 -interaction=nonstopmode -output-directory=${OUTDIR} ${FILE}",
        "build":      "latexmk -pdf -file-line-error -synctex=1 -output-directory=${OUTDIR} ${FILE}",
        "error_parser": "latex",
        "bib_backend": "auto",
    },
    "LaTeX (xelatex)": {
        "extensions": [".tex", ".ltx", ".latex"],
        "compile":    "xelatex -file-line-error -synctex=1 -interaction=nonstopmode -output-directory=${OUTDIR} ${FILE}",
        "run":        "xelatex -file-line-error -synctex=1 -interaction=nonstopmode -output-directory=${OUTDIR} ${FILE}",
        "build":      "latexmk -xelatex -file-line-error -synctex=1 -output-directory=${OUTDIR} ${FILE}",
        "error_parser": "latex",
        "bib_backend": "auto",
    },
    "LaTeX (lualatex)": {
        "extensions": [".tex", ".ltx", ".latex"],
        "compile":    "lualatex -file-line-error -synctex=1 -interaction=nonstopmode -output-directory=${OUTDIR} ${FILE}",
        "run":        "lualatex -file-line-error -synctex=1 -interaction=nonstopmode -output-directory=${OUTDIR} ${FILE}",
        "build":      "latexmk -lualatex -file-line-error -synctex=1 -output-directory=${OUTDIR} ${FILE}",
        "error_parser": "latex",
        "bib_backend": "auto",
    },
    "Make": {
        "extensions": [],
        "compile":    "make",
        "run":        "make run",
        "build":      "make all",
        "error_regex": r'([^:]+):(\d+):\d+: (?:error|warning):',
        "error_file_group": 1,
        "error_line_group": 2,
    },
    "Bash": {
        "extensions": [".sh", ".bash"],
        "compile":    "bash -n ${FILE}",
        "run":        "bash ${FILE}",
        "build":      "bash ${FILE}",
        "error_regex": r'([^:]+): line (\d+):',
        "error_file_group": 1,
        "error_line_group": 2,
    },
    "JavaScript (node)": {
        "extensions": [".js", ".mjs"],
        "compile":    "",
        "run":        "node ${FILE}",
        "build":      "node ${FILE}",
        "error_regex": r'at .+ \(([^:]+):(\d+):\d+\)',
        "error_file_group": 1,
        "error_line_group": 2,
    },
    "Rust (cargo)": {
        "extensions": [".rs"],
        "compile":    "cargo build",
        "run":        "cargo run",
        "build":      "cargo build --release",
        "error_regex": r'--\> ([^:]+):(\d+):\d+',
        "error_file_group": 1,
        "error_line_group": 2,
    },
    "Go": {
        "extensions": [".go"],
        "compile":    "go build ${FILE}",
        "run":        "go run ${FILE}",
        "build":      "go build -o ${DIR}/${BASENAME} ${FILE}",
        "error_regex": r'([^:]+):(\d+):\d+: (.+)',
        "error_file_group": 1,
        "error_line_group": 2,
    },
}

# Regex per il parser errori LaTeX (riusate, non ricompilate per ogni build)
_RE_LATEX_FILE  = re.compile(r'\(([^\s()]+\.(?:tex|ltx|latex|sty|cls|def|cfg|fd|clo))\b')
_RE_LATEX_BANG  = re.compile(r'!\s*(.+)')
_RE_LATEX_LNUM  = re.compile(r'^l\.(\d+)')
_RE_LATEX_MODERN = re.compile(r'([^\s:]+\.(?:tex|ltx|latex|sty|cls|aux)):(\d+):\s*(.+)')
_RE_LATEX_WARN  = re.compile(r'(?:LaTeX|Package|Class)[\w\s]*Warning:\s*(.+)')


# ─── PTY helper ───────────────────────────────────────────────────────────────

def _has_pty() -> bool:
    try:
        import pty
        return True
    except ImportError:
        return False


# ─── BuildWorker ──────────────────────────────────────────────────────────────

class BuildWorker(QThread):
    """Thread che esegue il processo di build (non interattivo)."""

    output_line  = pyqtSignal(str)
    finished_ok  = pyqtSignal(float)
    finished_err = pyqtSignal(int)
    stopped      = pyqtSignal()
    state_changed = pyqtSignal(str)

    def __init__(self, command: BuildCommand, cwd: str, env: dict, run_id: str = "",
                 timeout: float | None = None):
        super().__init__()
        self._command = command
        self._cwd     = cwd
        self._env     = env
        self._run_id  = run_id
        self._timeout = timeout if timeout and timeout > 0 else None
        self._proc: Optional[subprocess.Popen] = None
        self._abort   = False
        self._outcome: tuple[str, float] | None = None
        self._state = BUILD_STATE_QUEUED

    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, state: str) -> None:
        if self._state != state:
            self._state = state
            self.state_changed.emit(state)

    @profile_operation("build.run")
    def run(self) -> None:
        start   = time.monotonic()
        lines: queue.Queue[str | None] = queue.Queue()

        try:
            self._set_state(BUILD_STATE_RUNNING)
            self._proc = subprocess.Popen(
                self._command if isinstance(self._command, list)
                else [get_default_shell(), get_shell_exec_flag(), self._command],
                cwd=self._cwd,
                env=self._env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                **_popen_process_group_kwargs(),
            )
            if self._abort:
                _terminate_process_tree(self._proc)
                self._outcome = ("stopped", 0)
                self._set_state(BUILD_STATE_CANCELLED)
                self.stopped.emit()
                return

            def _read_output() -> None:
                try:
                    for line in self._proc.stdout:
                        lines.put(line)
                finally:
                    lines.put(None)

            reader = threading.Thread(target=_read_output, daemon=True)
            reader.start()
            timed_out = False
            stream_closed = False
            while not stream_closed:
                if self._abort:
                    _terminate_process_tree(self._proc)
                    self._outcome = ("stopped", 0)
                    self._set_state(BUILD_STATE_CANCELLED)
                    self.stopped.emit()
                    return

                if self._timeout is not None and time.monotonic() - start >= self._timeout:
                    timed_out = True
                    _terminate_process_tree(self._proc)
                    self.output_line.emit(
                        tr("build.timeout", seconds=f"{self._timeout:g}",
                           default="Build timed out after {seconds}s.")
                    )
                    self._outcome = ("timeout", self._timeout)
                    self._set_state(BUILD_STATE_TIMED_OUT)
                    break

                try:
                    line = lines.get(timeout=0.05)
                except queue.Empty:
                    continue
                if line is None:
                    stream_closed = True
                else:
                    self.output_line.emit(line.rstrip())

            self._proc.wait()
            elapsed = time.monotonic() - start

            if timed_out:
                self._outcome = ("timeout", self._timeout or elapsed)
                self._set_state(BUILD_STATE_TIMED_OUT)
                self.finished_err.emit(-1)
            elif self._abort:
                self._outcome = ("stopped", 0)
                self._set_state(BUILD_STATE_CANCELLED)
                self.stopped.emit()
            elif self._proc.returncode == 0:
                self._outcome = ("ok", elapsed)
                self._set_state(BUILD_STATE_SUCCEEDED)
                self.finished_ok.emit(elapsed)
            else:
                self._outcome = ("error", float(self._proc.returncode))
                self._set_state(BUILD_STATE_FAILED)
                self.finished_err.emit(self._proc.returncode)

        except Exception as e:
            self.output_line.emit(tr("build.error_prefix", error=str(e)))
            self._outcome = ("error", -1)
            self._set_state(BUILD_STATE_FAILED)
            self.finished_err.emit(-1)

    def abort(self) -> None:
        self._abort = True
        if self._proc:
            _terminate_process_tree(self._proc)


class InteractiveBuildWorker(QThread):
    """Thread per build interattive con PTY (pseudo-terminale)."""

    output_line  = pyqtSignal(str)
    finished_ok  = pyqtSignal(float)
    finished_err = pyqtSignal(int)
    stopped      = pyqtSignal()
    state_changed = pyqtSignal(str)

    def __init__(self, command: BuildCommand, cwd: str, env: dict, run_id: str = "",
                 timeout: float | None = None):
        super().__init__()
        self._command = command
        self._cwd     = cwd
        self._env     = env
        self._run_id  = run_id
        self._timeout = timeout if timeout and timeout > 0 else None
        self._proc: Optional[subprocess.Popen] = None
        self._abort   = False
        self._input_queue: list[str] = []
        self._outcome: tuple[str, float] | None = None
        self._state = BUILD_STATE_QUEUED

    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, state: str) -> None:
        if self._state != state:
            self._state = state
            self.state_changed.emit(state)

    def send_input(self, text: str) -> None:
        self._input_queue.append(text)

    @profile_operation("build.run_interactive")
    def run(self) -> None:
        self._set_state(BUILD_STATE_RUNNING)
        if _has_pty() and not IS_WINDOWS:
            self._run_pty()
        else:
            self._run_pipe()

    def _run_pty(self) -> None:
        import codecs
        import errno
        import pty
        import select
        start = time.monotonic()
        master_fd = None
        master_w = None
        slave_fd = None

        try:
            master_fd, slave_fd = pty.openpty()
            try:
                self._proc = subprocess.Popen(
                    self._command if isinstance(self._command, list)
                    else [get_default_shell(), get_shell_exec_flag(), self._command],
                    cwd=self._cwd,
                    env=self._env,
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    preexec_fn=os.setsid,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                if self._abort:
                    _terminate_process_tree(self._proc)
                    self._outcome = ("stopped", 0)
                    self._set_state(BUILD_STATE_CANCELLED)
                    self.stopped.emit()
                    return
                os.close(slave_fd)
                slave_fd = None

                # Il writer deve usare un duplicato: due wrapper Python sullo
                # stesso fd chiuderebbero il descrittore due volte durante la
                # finalizzazione, producendo EBADF e possibili leak.
                master_w = os.fdopen(
                    os.dup(master_fd), "w", encoding="utf-8", errors="replace"
                )

                timeout = 0.05
                timed_out = False
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                pending_output = ""
                while True:
                    if self._abort:
                        _terminate_process_tree(self._proc)
                        self._outcome = ("stopped", 0)
                        self._set_state(BUILD_STATE_CANCELLED)
                        self.stopped.emit()
                        return
                    if self._timeout is not None and time.monotonic() - start >= self._timeout:
                        timed_out = True
                        _terminate_process_tree(self._proc)
                        if pending_output:
                            self.output_line.emit(pending_output.rstrip("\r\n"))
                            pending_output = ""
                        self.output_line.emit(
                            tr("build.timeout", seconds=f"{self._timeout:g}",
                               default="Build timed out after {seconds}s.")
                        )
                        break

                    while self._input_queue:
                        inp = self._input_queue.pop(0)
                        try:
                            master_w.write(inp)
                            master_w.flush()
                        except Exception:
                            pass

                    r, _, _ = select.select([master_fd], [], [], timeout)
                    if r:
                        try:
                            try:
                                chunk = os.read(master_fd, 4096)
                            except OSError as exc:
                                # Linux reports EIO when the PTY slave closes.
                                if exc.errno == errno.EIO:
                                    chunk = b""
                                else:
                                    raise
                            if not chunk:
                                pending_output += decoder.decode(b"", final=True)
                                if pending_output:
                                    self.output_line.emit(pending_output.rstrip("\r\n"))
                                    pending_output = ""
                                break
                            pending_output += decoder.decode(chunk)
                            while "\n" in pending_output:
                                line, pending_output = pending_output.split("\n", 1)
                                self.output_line.emit(line.rstrip("\r"))
                        except Exception:
                            break

                if pending_output and not timed_out:
                    # A process may exit after writing a final unterminated line.
                    self.output_line.emit(pending_output.rstrip("\r\n"))
                    pending_output = ""

                self._proc.wait()
                elapsed = time.monotonic() - start
                if timed_out:
                    self._outcome = ("timeout", self._timeout or elapsed)
                    self._set_state(BUILD_STATE_TIMED_OUT)
                    self.finished_err.emit(-1)
                elif self._abort:
                    self._outcome = ("stopped", 0)
                    self._set_state(BUILD_STATE_CANCELLED)
                    self.stopped.emit()
                elif self._proc.returncode == 0:
                    self._outcome = ("ok", elapsed)
                    self._set_state(BUILD_STATE_SUCCEEDED)
                    self.finished_ok.emit(elapsed)
                else:
                    self._outcome = ("error", float(self._proc.returncode))
                    self._set_state(BUILD_STATE_FAILED)
                    self.finished_err.emit(self._proc.returncode)

            finally:
                try:
                    if slave_fd is not None:
                        os.close(slave_fd)
                except Exception:
                    pass
                for stream in (master_w,):
                    try:
                        if stream is not None:
                            stream.close()
                    except Exception:
                        pass
                if master_fd is not None:
                    try:
                        os.close(master_fd)
                    except OSError:
                        pass

        except Exception as e:
            self.output_line.emit(tr("build.error_prefix", error=str(e)))
            self._outcome = ("error", -1)
            self._set_state(BUILD_STATE_FAILED)
            self.finished_err.emit(-1)

    def _run_pipe(self) -> None:
        """Fallback non-PTY per Windows (pipe standard)."""
        shell = get_default_shell()
        flag = get_shell_exec_flag()
        start = time.monotonic()

        try:
            self._proc = subprocess.Popen(
                self._command if isinstance(self._command, list)
                else [shell, flag, self._command],
                cwd=self._cwd,
                env=self._env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                **_popen_process_group_kwargs(),
            )
            if self._abort:
                _terminate_process_tree(self._proc)
                self._outcome = ("stopped", 0)
                self._set_state(BUILD_STATE_CANCELLED)
                self.stopped.emit()
                return
            import threading

            def _feed_input():
                while self._proc and self._proc.poll() is None:
                    while self._input_queue:
                        inp = self._input_queue.pop(0)
                        try:
                            self._proc.stdin.write(inp)
                            self._proc.stdin.flush()
                        except Exception:
                            return
                    time.sleep(0.05)

            threading.Thread(target=_feed_input, daemon=True).start()

            lines: queue.Queue[str | None] = queue.Queue()

            def _read_output() -> None:
                try:
                    for line in self._proc.stdout:
                        lines.put(line)
                finally:
                    lines.put(None)

            threading.Thread(target=_read_output, daemon=True).start()
            timed_out = False
            stream_closed = False
            while not stream_closed:
                if self._abort:
                    _terminate_process_tree(self._proc)
                    self._outcome = ("stopped", 0)
                    self._set_state(BUILD_STATE_CANCELLED)
                    self.stopped.emit()
                    return
                if self._timeout is not None and time.monotonic() - start >= self._timeout:
                    timed_out = True
                    _terminate_process_tree(self._proc)
                    self.output_line.emit(
                        tr("build.timeout", seconds=f"{self._timeout:g}",
                           default="Build timed out after {seconds}s.")
                    )
                    break
                try:
                    line = lines.get(timeout=0.05)
                except queue.Empty:
                    continue
                if line is None:
                    stream_closed = True
                else:
                    self.output_line.emit(line.rstrip())

            self._proc.wait()
            elapsed = time.monotonic() - start
            if timed_out:
                self._outcome = ("timeout", self._timeout or elapsed)
                self._set_state(BUILD_STATE_TIMED_OUT)
                self.finished_err.emit(-1)
            elif self._abort:
                self._outcome = ("stopped", 0)
                self._set_state(BUILD_STATE_CANCELLED)
                self.stopped.emit()
            elif self._proc.returncode == 0:
                self._outcome = ("ok", elapsed)
                self._set_state(BUILD_STATE_SUCCEEDED)
                self.finished_ok.emit(elapsed)
            else:
                self._outcome = ("error", float(self._proc.returncode))
                self._set_state(BUILD_STATE_FAILED)
                self.finished_err.emit(self._proc.returncode)

        except Exception as e:
            self.output_line.emit(tr("build.error_prefix", error=str(e)))
            self._outcome = ("error", -1)
            self._set_state(BUILD_STATE_FAILED)
            self.finished_err.emit(-1)

    def abort(self) -> None:
        self._abort = True
        if self._proc:
            _terminate_process_tree(self._proc)


# ─── Pulizia file ausiliari LaTeX ─────────────────────────────────────────────

AUX_EXTENSIONS: list[str] = [
    ".aux", ".log", ".out", ".toc", ".lof", ".lot",
    ".bbl", ".blg", ".bcf", ".run.xml",
    ".synctex.gz", ".fls", ".fdb_latexmk",
    ".nav", ".snm", ".vrb",
    ".idx", ".ind", ".ilg",
    ".glo", ".gls", ".glg",
    ".acn", ".acr", ".alg",
]


def clean_aux_files(base_path: Path, keep_synctex: bool = True,
                    extra_bases: list[Path] | None = None) -> list[str]:
    removed = []
    seen: set[Path] = set()
    for base in [base_path, *(extra_bases or [])]:
        for ext in AUX_EXTENSIONS:
            if keep_synctex and ext == ".synctex.gz":
                continue
            candidate = base.with_name(base.name + ext)
            if candidate in seen or not candidate.exists():
                continue
            seen.add(candidate)
            try:
                candidate.unlink()
                removed.append(candidate.name)
            except OSError as e:
                _log_warn(f"Could not remove aux file {candidate}: {e}")
    return removed


# ─── BuildManager ─────────────────────────────────────────────────────────────

class BuildManager(QObject):
    """
    Singleton. Gestisce i profili di compilazione e l'esecuzione dei build.
    Supporta build concorrenti (worker multipli), pipeline, PTY, project config.
    """

    build_started = pyqtSignal(str, str)
    build_output  = pyqtSignal(str, str)
    build_done    = pyqtSignal(str, bool, str)
    build_errors  = pyqtSignal(str, list)
    pipeline_step = pyqtSignal(str, int, int, str)
    build_state_changed = pyqtSignal(str, str)

    _instance: Optional["BuildManager"] = None
    _MAX_OUTPUT_LINES = 10000

    def __init__(self):
        super().__init__()
        self._profiles: dict[str, dict] = dict(DEFAULT_PROFILES)
        self._workers: dict[str, BuildWorker | InteractiveBuildWorker] = {}
        self._retired_workers: set[BuildWorker | InteractiveBuildWorker] = set()
        self._active_profile: str = ""
        self._profile_overrides: dict[str, str] = {}
        self._project_configs: dict[Path, tuple[int, dict]] = {}
        self._build_contexts: dict[str, object] = {}
        self._build_states: dict[str, str] = {}
        self._load_user_profiles()

    @classmethod
    def instance(cls) -> "BuildManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Profili ───────────────────────────────────────────────────────────────

    def _profiles_path(self) -> Path:
        return get_config_dir() / "build_profiles.json"

    def _load_user_profiles(self) -> None:
        path = self._profiles_path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                order = data.pop("__order__", None)
                overrides = data.pop("__overrides__", None)
                self._profiles.update(data)
                if order:
                    reordered = {}
                    for name in order:
                        if name in self._profiles:
                            reordered[name] = self._profiles[name]
                    for name, profile in self._profiles.items():
                        if name not in reordered:
                            reordered[name] = profile
                    self._profiles = reordered
                if overrides and isinstance(overrides, dict):
                    self._profile_overrides.update(overrides)
            except Exception as e:
                _log_warn(f"Failed to load build profiles from {path}: {e}")

    def save_profiles(self) -> None:
        profiles_to_save = {}
        for name, profile in self._profiles.items():
            if name not in DEFAULT_PROFILES:
                profiles_to_save[name] = profile
            elif profile != DEFAULT_PROFILES[name]:
                profiles_to_save[name] = profile
        profiles_to_save["__order__"] = list(self._profiles.keys())
        if self._profile_overrides:
            profiles_to_save["__overrides__"] = dict(self._profile_overrides)
        try:
            self._profiles_path().write_text(
                json.dumps(profiles_to_save, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            print(f"[build_manager] Errore salvataggio profili: {e}")

    def get_profiles(self) -> dict[str, dict]:
        return dict(self._profiles)

    def reorder_profiles(self, names: list) -> None:
        reordered = {}
        for name in names:
            if name in self._profiles:
                reordered[name] = self._profiles[name]
        for name, profile in self._profiles.items():
            if name not in reordered:
                reordered[name] = profile
        self._profiles = reordered
        self.save_profiles()

    def add_profile(self, name: str, profile: dict) -> None:
        self._profiles[name] = profile
        self.save_profiles()

    def remove_profile(self, name: str) -> None:
        if name not in DEFAULT_PROFILES:
            self._profiles.pop(name, None)
            self.save_profiles()

    def set_profile_override(self, ext: str, name: str) -> None:
        if ext:
            self._profile_overrides[ext] = name
        self._active_profile = name
        self.save_profiles()

    def clear_profile_override(self, ext: str) -> None:
        self._profile_overrides.pop(ext, None)
        self.save_profiles()

    def get_profile_for_file(self, path: Path) -> Optional[str]:
        ext = path.suffix.lower()
        latex_ext = ext in {".tex", ".ltx", ".latex"}
        override = self._profile_overrides.get(ext, "")
        if not override and latex_ext:
            override = self._profile_overrides.get(".tex", "")
        project_profiles = self.get_project_profiles(path)
        if override and (override in self._profiles or override in project_profiles):
            return override
        for name, profile in project_profiles.items():
            if isinstance(profile, dict) and ext in profile.get("extensions", []):
                return name
        for name, profile in self._profiles.items():
            if isinstance(profile, dict) and ext in profile.get("extensions", []):
                return name
        return None

    # ── Configurazione di progetto (.notepadpq-build.json) ─────────────────────

    def _find_project_config(self, file_path: Path) -> Optional[dict]:
        current = file_path.parent
        while True:
            cfg_path = current / ".notepadpq-build.json"
            if cfg_path.exists():
                try:
                    mtime_ns = cfg_path.stat().st_mtime_ns
                    cached = self._project_configs.get(cfg_path)
                    if cached and cached[0] == mtime_ns:
                        return cached[1]
                    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                    self._project_configs[cfg_path] = (mtime_ns, cfg)
                    return cfg
                except Exception as e:
                    _log_warn(f"Failed to parse {cfg_path}: {e}")
            parent = current.parent
            if parent == current:
                break
            current = parent
        return None

    def get_project_profiles(self, file_path: Path) -> dict[str, dict]:
        cfg = self._find_project_config(file_path)
        if cfg:
            profiles = cfg.get("profiles", {})
            return profiles if isinstance(profiles, dict) else {}
        return {}

    def get_project_tasks(self, file_path: Path) -> list[dict]:
        cfg = self._find_project_config(file_path)
        if cfg:
            tasks = cfg.get("tasks", [])
            return tasks if isinstance(tasks, list) else []
        return []

    @staticmethod
    def _latex_context(file_path: Path, content: str | None = None,
                       output_dir: str | Path | None = None):
        from core.latex_project import LatexProjectContext
        return LatexProjectContext(file_path, content, output_dir)

    def get_build_context(self, run_id: str):
        """Restituisce il contesto LaTeX associato a una build recente."""
        return self._build_contexts.get(run_id)

    def release_build_context(self, run_id: str) -> None:
        """Rilascia il testo completo conservato per una build terminata."""
        self._build_contexts.pop(run_id, None)

    # ── Esecuzione ────────────────────────────────────────────────────────────

    @staticmethod
    def _ramdisk_build_dir(root: Path) -> Optional[Path]:
        """Directory di build su tmpfs per ``root``, o None se non disponibile.

        Rispecchia il percorso assoluto della directory di progetto sotto
        ``$XDG_RUNTIME_DIR`` (di norma /run/user/<uid>, un tmpfs montato in
        RAM) così da ottenere una directory univoca per progetto senza dover
        calcolare hash. Non disponibile su Windows o se la sessione non
        espone XDG_RUNTIME_DIR (es. login non via systemd/logind).
        """
        if IS_WINDOWS:
            return None
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if not runtime_dir or not Path(runtime_dir).is_dir():
            return None
        parent = root.parent
        mirrored = Path(*parent.parts[1:]) if parent.is_absolute() else parent
        return Path(runtime_dir) / "notepadpq-latex" / mirrored

    def run(self, action: str, editor: Optional["EditorWidget"],
            run_id: str = "", interactive: bool = False) -> bool:
        if editor is None or editor.file_path is None:
            return False

        editor_file_path = editor.file_path
        file_path = editor_file_path
        if not run_id:
            run_id = f"build_{uuid4().hex[:8]}"

        from config.settings import Settings
        if Settings.instance().get("build/save_before", True):
            if editor.is_modified():
                from ui.main_window import MainWindow
                win = editor.window()
                if hasattr(win, "action_save"):
                    win.action_save()

        content = editor.get_content()
        latex_context = None
        if file_path.suffix.lower() in {".tex", ".ltx", ".latex"}:
            latex_context = self._latex_context(file_path, content)
            if latex_context.root != file_path.resolve():
                self.build_output.emit(
                    run_id,
                    tr("build.magic_comment_detected", root=latex_context.root.name),
                )
            file_path = latex_context.root
            self._build_contexts[run_id] = latex_context

        profile_name = self.get_profile_for_file(editor_file_path)
        if not profile_name:
            self.build_output.emit(run_id, tr("build.no_profile", suffix=file_path.suffix))
            self.release_build_context(run_id)
            return False

        project_profiles = self.get_project_profiles(editor_file_path)
        profile = project_profiles.get(profile_name) or self._profiles.get(profile_name)
        if not isinstance(profile, dict):
            self.build_output.emit(run_id, tr("build.no_profile", suffix=file_path.suffix))
            self.release_build_context(run_id)
            return False

        ramdisk_copy_cmd = ""
        if latex_context:
            output_ref = profile.get("output_directory", profile.get("output_dir"))
            if profile.get("ramdisk"):
                final_dir = get_output_directory(latex_context.root, output_ref)
                ramdisk_dir = self._ramdisk_build_dir(latex_context.root)
                if ramdisk_dir:
                    output_ref = str(ramdisk_dir)
                    dest = shlex.quote(str(final_dir))
                    ramdisk_copy_cmd = (
                        f'mkdir -p {dest} && '
                        f'cp -f "${{OUTDIR}}/${{BASENAME}}.pdf" '
                        f'"${{OUTDIR}}/${{BASENAME}}.synctex.gz" {dest}/ 2>/dev/null; true'
                    )
                else:
                    self.build_output.emit(run_id, tr(
                        "build.ramdisk_unavailable",
                        default="RAM disk not available (XDG_RUNTIME_DIR missing): "
                                "building in the normal directory instead."))
            if output_ref:
                latex_context = self._latex_context(
                    latex_context.current_file, latex_context.content, output_ref)
                self._build_contexts[run_id] = latex_context
            try:
                latex_context.output_directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self.build_output.emit(
                    run_id,
                    tr("build.output_dir_error", error=str(exc),
                       default="Cannot create LaTeX output directory: {error}"),
                )
                self.release_build_context(run_id)
                return False

        pipeline = profile.get("pipeline", [])
        if pipeline:
            if ramdisk_copy_cmd:
                pipeline = [*pipeline, {"name": "RAM disk → cartella predefinita",
                                        "cmd": ramdisk_copy_cmd, "stop_on_error": False}]
            return self._run_pipeline(
                run_id, pipeline, file_path, editor, profile, interactive,
                latex_context.output_directory if latex_context else None,
            )

        command = profile.get(action, "")
        if not command:
            self.build_output.emit(run_id, tr("build.no_command", action=action, profile=profile_name))
            self.release_build_context(run_id)
            return False

        command = self._configure_bibliography_command(
            command, profile, latex_context, editor.get_content())

        if file_path.suffix.lower() in {".tex", ".ltx", ".latex"} and Settings.instance().get("build/draft_mode", False):
            command = self._add_draftmode_flag(command)

        if (latex_context and action == "build"
                and Settings.instance().get("build/latex_auxiliary_auto", False)
                and not profile.get("pre_hook") and not profile.get("post_hook")):
            from core.latex_external_tools import (
                detect_latex_auxiliary_tools,
                makeglossaries_command,
                makeindex_command,
                nomencl_command,
            )
            from core.latex_external_tools import quote_command
            auxiliary = detect_latex_auxiliary_tools(editor.get_content())
            if auxiliary:
                output = latex_context.output_directory
                auxiliary_pipeline = [{"name": "LaTeX", "cmd": command,
                                       "stop_on_error": True}]
                for kind in auxiliary:
                    if kind == "makeindex":
                        argv = makeindex_command(output / f"{latex_context.root.stem}.idx")
                    elif kind == "makeglossaries":
                        argv = makeglossaries_command(output / latex_context.root.name)
                    else:
                        argv = nomencl_command(output / latex_context.root.name)
                    auxiliary_pipeline.append({
                        "name": kind,
                        "cmd": quote_command(argv),
                        "stop_on_error": True,
                    })
                auxiliary_pipeline.append({"name": "LaTeX finale", "cmd": command,
                                           "stop_on_error": True})
                if ramdisk_copy_cmd:
                    auxiliary_pipeline.append({"name": "RAM disk → cartella predefinita",
                                               "cmd": ramdisk_copy_cmd, "stop_on_error": False})
                return self._run_pipeline(
                    run_id, auxiliary_pipeline, file_path, editor, profile,
                    interactive, latex_context.output_directory,
                )

        env = self._build_env(
            file_path, profile,
            output_dir=latex_context.output_directory if latex_context else None,
            root_file=latex_context.root if latex_context else None,
        )
        if latex_context:
            backend = str(profile.get("bib_backend", "auto")).lower().strip()
            if backend == "auto":
                backend = self.detect_bibliography_backend(
                    latex_context.root, editor.get_content())
            env["NOTEPADPQ_BIB_BACKEND"] = backend

        post_hook = profile.get("post_hook", "")
        if ramdisk_copy_cmd:
            post_hook = f"{ramdisk_copy_cmd} && {post_hook}" if post_hook else ramdisk_copy_cmd

        command = self._expand_profile_command(
            command, file_path, editor,
            output_dir=latex_context.output_directory if latex_context else None,
            root_file=latex_context.root if latex_context else None,
        )

        started = self._do_run(
            run_id, command, str(file_path.parent), env,
            profile, file_path, editor, interactive,
            pre_hook=profile.get("pre_hook", ""),
            post_hook=post_hook,
            output_dir=latex_context.output_directory if latex_context else None)
        if not started:
            self.release_build_context(run_id)
        return started

    def run_task(self, cmd: str, cwd: Path, run_id: str = "",
                 interactive: bool = False) -> bool:
        if not run_id:
            run_id = f"task_{uuid4().hex[:8]}"
        env = {**os.environ}
        from core.external_open import clean_subprocess_env
        env = clean_subprocess_env()

        self.build_started.emit(run_id, "task")
        self.build_output.emit(run_id, tr("msg.build_started", command=cmd))

        self._spawn_worker(run_id, self._expand_command(cmd, None, None), str(cwd), env, interactive)
        return True

    @staticmethod
    def detect_bibliography_backend(root_file: Path,
                                   current_content: str = "") -> str:
        """Rileva il backend bibliografico usato da un progetto LaTeX."""
        from editor.latex_support import strip_latex_comments

        texts = [current_content]
        try:
            from core.latex_project import collect_included_files
            texts.extend(
                path.read_text(encoding="utf-8", errors="replace")
                for path in collect_included_files(root_file)
                if path != root_file and path.is_file()
            )
        except OSError:
            pass
        code = "\n".join(strip_latex_comments(text) for text in texts)
        biblatex = re.search(
            r"\\usepackage\s*(?:\[([^]]*)\])?\s*\{biblatex\}", code,
            re.IGNORECASE,
        )
        if biblatex:
            options = (biblatex.group(1) or "").lower()
            if re.search(r"backend\s*=\s*bibtex", options):
                return "bibtex"
            return "biber"
        if re.search(r"\\(?:bibliography|bibliographystyle)\b", code):
            return "bibtex"
        return "none"

    @classmethod
    def _configure_bibliography_command(cls, command: str, profile: dict,
                                         context, current_content: str) -> str:
        """Configura solo le opzioni latexmk realmente supportate.

        BibTeX può essere forzato con ``-bibtex``; Biber viene rilevato da
        latexmk dal file `.bcf` e non richiede un flag equivalente.
        """
        if "latexmk" not in command.lower() or not context:
            return command
        backend = str(profile.get("bib_backend", "auto")).lower().strip()
        if backend == "auto":
            backend = cls.detect_bibliography_backend(context.root, current_content)
        if backend == "bibtex" and "-bibtex" not in command:
            return re.sub(r"(\blatexmk\b)", r"\1 -bibtex", command,
                          count=1, flags=re.IGNORECASE)
        if backend == "none" and "-nobibtex" not in command:
            return re.sub(r"(\blatexmk\b)", r"\1 -nobibtex", command,
                          count=1, flags=re.IGNORECASE)
        return command

    def _run_pipeline(self, run_id: str, pipeline: list, file_path: Path,
                      editor, profile: dict, interactive: bool,
                      output_dir: Path | None = None) -> bool:
        command = self._expand_profile_command(
            pipeline[0].get("cmd", ""), file_path, editor, output_dir=output_dir)
        env = self._build_env(file_path, profile, output_dir=output_dir)

        self.build_started.emit(run_id, "pipeline")
        self.pipeline_step.emit(run_id, 1, len(pipeline), pipeline[0].get("name", "Step 1"))
        self.build_output.emit(run_id, tr("build.pipeline_started",
                                          step=pipeline[0].get("name", ""),
                                          total=len(pipeline),
                                          default="Pipeline [{step}/{total}] started"))

        def configure_worker(worker: BuildWorker | InteractiveBuildWorker) -> None:
            worker._pipeline_index = 0
            worker._pipeline = pipeline
            worker._pipeline_file_path = file_path
            worker._pipeline_editor = editor
            worker._pipeline_profile = profile
            worker._pipeline_interactive = interactive
            worker._pipeline_env = env
            worker._pipeline_output_dir = output_dir

        self._spawn_worker(run_id, command, str(file_path.parent), env, interactive,
                           setup=configure_worker)
        return True

    def _continue_pipeline(self, run_id: str,
                           worker: BuildWorker | InteractiveBuildWorker,
                           success: bool) -> None:
        if not hasattr(worker, "_pipeline_index"):
            return

        idx = getattr(worker, "_pipeline_index", 0)
        pipeline = getattr(worker, "_pipeline", [])
        step = pipeline[idx]

        timed_out = getattr(worker, "_outcome", (None,))[0] == "timeout"
        if (not success and (step.get("stop_on_error", True) or timed_out)):
            self.build_output.emit(run_id,
                tr("build.pipeline_step_failed", name=step.get("name", f"Step {idx+1}"),
                   default="Pipeline step failed: {name}"))
            message_key = "build.timeout" if timed_out else "build.pipeline_failed"
            message = tr(message_key,
                         seconds=f"{getattr(worker, '_outcome', ('timeout', 0))[1]:g}",
                         default="Build timed out after {seconds}s.") if timed_out else tr(
                             message_key, default="Pipeline stopped due to error")
            self.build_done.emit(run_id, False, message)
            self.release_build_context(run_id)
            return

        idx += 1
        if idx >= len(pipeline):
            self.build_output.emit(run_id, tr("build.pipeline_complete",
                default="Pipeline completed successfully"))
            self.build_done.emit(run_id, True, tr("build.pipeline_success",
                default="All pipeline steps passed"))
            self.release_build_context(run_id)
            return

        worker._pipeline_index = idx
        next_step = pipeline[idx]
        file_path = getattr(worker, "_pipeline_file_path", None)
        editor = getattr(worker, "_pipeline_editor", None)
        env = getattr(worker, "_pipeline_env", None)
        output_dir = getattr(worker, "_pipeline_output_dir", None)

        cmd = self._expand_profile_command(
            next_step.get("cmd", ""), file_path, editor, output_dir=output_dir)
        self.pipeline_step.emit(run_id, idx + 1, len(pipeline),
                                next_step.get("name", f"Step {idx+1}"))
        self.build_output.emit(run_id, tr("build.pipeline_step",
                                          num=idx+1, name=next_step.get("name", ""),
                                          default="[{num}] {name}"))

        interactive = getattr(worker, "_pipeline_interactive", False)
        def configure_next(next_worker: BuildWorker | InteractiveBuildWorker) -> None:
            next_worker._pipeline_index = idx
            next_worker._pipeline = pipeline
            next_worker._pipeline_file_path = file_path
            next_worker._pipeline_editor = editor
            next_worker._pipeline_profile = getattr(worker, "_pipeline_profile", {})
            next_worker._pipeline_interactive = interactive
            next_worker._pipeline_env = env
            next_worker._pipeline_output_dir = output_dir

        self._spawn_worker(run_id, cmd, str(file_path.parent) if file_path else ".",
                           env, interactive, setup=configure_next)

    def _build_env(self, file_path: Path, profile: dict,
                   output_dir: Path | None = None,
                   root_file: Path | None = None) -> dict:
        from core.external_open import clean_subprocess_env
        env = clean_subprocess_env()
        env["NOTEPADPQ_FILE"]     = str(file_path)
        env["NOTEPADPQ_DIR"]      = str(file_path.parent)
        env["NOTEPADPQ_BASENAME"] = file_path.stem
        env["NOTEPADPQ_BASEFILE"] = str(file_path.parent / file_path.stem)
        env["NOTEPADPQ_EXT"]      = file_path.suffix
        env["NOTEPADPQ_FILENAME"] = file_path.name
        env["NOTEPADPQ_ROOT"]     = str(root_file or file_path)
        env["NOTEPADPQ_OUTDIR"]   = str(output_dir or file_path.parent)

        profile_env = profile.get("env", {})
        if isinstance(profile_env, dict):
            env.update(profile_env)
        elif isinstance(profile_env, str) and profile_env.strip():
            for line in profile_env.strip().splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()

        if file_path.suffix.lower() not in {".tex", ".ltx", ".latex"}:
            # Profile variables may add tool-specific settings, but non-LaTeX
            # shell placeholders must always refer to this selected file.
            env["NOTEPADPQ_FILE"]     = str(file_path)
            env["NOTEPADPQ_DIR"]      = str(file_path.parent)
            env["NOTEPADPQ_BASENAME"] = file_path.stem
            env["NOTEPADPQ_BASEFILE"] = str(file_path.parent / file_path.stem)
            env["NOTEPADPQ_EXT"]      = file_path.suffix
            env["NOTEPADPQ_FILENAME"] = file_path.name
            env["NOTEPADPQ_ROOT"]     = str(root_file or file_path)
            env["NOTEPADPQ_OUTDIR"]   = str(output_dir or file_path.parent)

        return env

    def _do_run(self, run_id: str, command: BuildCommand, cwd: str, env: dict,
                profile: dict, file_path: Path, editor,
                interactive: bool, pre_hook: str = "", post_hook: str = "",
                output_dir: Path | None = None) -> bool:

        from config.settings import Settings
        self._set_build_state(run_id, BUILD_STATE_QUEUED)

        def _exec_command(cmd: BuildCommand) -> BuildWorker:
            if (isinstance(cmd, str) and file_path.suffix.lower() in {".tex", ".ltx", ".latex"}
                    and Settings.instance().get("build/draft_mode", False)):
                cmd = self._add_draftmode_flag(cmd)

            self.build_started.emit(run_id, "build")
            self.build_output.emit(run_id, tr("msg.build_started", command=cmd))

            if Settings.instance().get("build/clean_aux_before_compile", False):
                aux_base = (output_dir / file_path.stem
                            if output_dir else file_path.with_suffix(""))
                extra_bases = []
                context = self._build_contexts.get(run_id)
                if context is not None:
                    try:
                        for source in context.included_files():
                            extra_bases.extend((
                                source.with_suffix(""),
                                output_dir / source.stem if output_dir else source.with_suffix(""),
                            ))
                    except (OSError, RuntimeError):
                        pass
                removed = clean_aux_files(
                    aux_base,
                    keep_synctex=Settings.instance().get("build/keep_synctex", True),
                    extra_bases=extra_bases,
                )
                if removed:
                    self.build_output.emit(run_id,
                        tr("build_panel.aux_cleaned", n=len(removed), files=", ".join(removed)))

            def configure_main(worker: BuildWorker | InteractiveBuildWorker) -> None:
                if post_hook:
                    worker._post_hook = post_hook
                    worker._post_hook_file_path = file_path
                    worker._post_hook_editor = editor
                    worker._output_dir = output_dir

            return self._spawn_worker(run_id, cmd, cwd, env, interactive,
                                      setup=configure_main)

        if pre_hook and pre_hook.strip():
            hook_cmd = self._expand_profile_command(
                pre_hook.strip(), file_path, editor, output_dir=output_dir)
            self.build_output.emit(run_id, tr("build.pre_hook", cmd=hook_cmd,
                default="Pre-hook: {cmd}"))
            def configure_hook(worker: BuildWorker | InteractiveBuildWorker) -> None:
                worker._is_hook = "pre"
                worker._main_command = command
                worker._main_cwd = cwd
                worker._main_env = env
                worker._main_profile = profile
                worker._main_file_path = file_path
                worker._main_editor = editor
                worker._main_interactive = interactive
                worker._main_output_dir = output_dir
                worker._post_hook = post_hook
                worker._output_dir = output_dir

            self._spawn_worker(run_id + "_pre", hook_cmd, cwd, env, interactive,
                               setup=configure_hook)
            return True

        return _exec_command(command) is not None

    def _spawn_worker(self, run_id: str, command: BuildCommand, cwd: str, env: dict,
                      interactive: bool = False,
                      setup: Callable[[BuildWorker | InteractiveBuildWorker], None] | None = None
                      ) -> BuildWorker | InteractiveBuildWorker:
        old = self._workers.pop(run_id, None)
        if old:
            old.abort()
            self._retire_worker(old)

        cls = InteractiveBuildWorker if interactive else BuildWorker
        worker = cls(command, cwd, env, run_id, timeout=self.get_build_timeout())
        self._set_build_state(run_id, BUILD_STATE_QUEUED)
        worker.output_line.connect(lambda line, rid=run_id: self.build_output.emit(rid, line))
        if hasattr(worker, "state_changed"):
            worker.state_changed.connect(
                lambda state, rid=run_id: self._set_build_state(rid, state)
            )
        self._workers[run_id] = worker
        worker.finished.connect(
            lambda rid=run_id, w=worker: self._finalize_worker(rid, w)
        )
        if setup:
            setup(worker)

        worker.start()
        return worker

    def _retire_worker(self, worker: BuildWorker | InteractiveBuildWorker) -> None:
        """Retain a running QThread until Qt confirms it has stopped."""
        self._retired_workers.add(worker)
        if not worker.isRunning():
            self._delete_worker(worker)

    def _delete_worker(self, worker: BuildWorker | InteractiveBuildWorker) -> None:
        self._retired_workers.discard(worker)
        if not worker.isRunning():
            worker.deleteLater()

    def _finalize_worker(self, run_id: str,
                         worker: BuildWorker | InteractiveBuildWorker) -> None:
        if self._workers.get(run_id) is not worker:
            self._delete_worker(worker)
            return
        self._workers.pop(run_id, None)
        outcome = worker._outcome or ("error", -1)
        outcome_state = {
            "ok": BUILD_STATE_SUCCEEDED,
            "timeout": BUILD_STATE_TIMED_OUT,
            "stopped": BUILD_STATE_CANCELLED,
        }.get(outcome[0], BUILD_STATE_FAILED)
        self._set_build_state(run_id, outcome_state)
        target_run_id = run_id.replace("_pre", "") if hasattr(worker, "_is_hook") else run_id
        self._set_build_state(target_run_id, outcome_state)
        if outcome[0] == "stopped":
            self.build_done.emit(target_run_id, False, tr("build.interrupted"))
            self.release_build_context(target_run_id)
            self._delete_worker(worker)
            return
        self._on_worker_done(run_id, worker, outcome[0] == "ok", outcome[1])
        self._delete_worker(worker)

    def _on_worker_done(self, run_id: str, worker: BuildWorker | InteractiveBuildWorker,
                        ok: bool, secs: float) -> None:

        if hasattr(worker, "_is_hook") and worker._is_hook == "pre":
            if ok:
                main_cmd = getattr(worker, "_main_command", "")
                cwd = getattr(worker, "_main_cwd", ".")
                env = getattr(worker, "_main_env", {})
                interactive = getattr(worker, "_main_interactive", False)
                self._do_run(
                    run_id.replace("_pre", ""), main_cmd, cwd, env,
                    getattr(worker, "_main_profile", {}),
                    getattr(worker, "_main_file_path", None),
                    getattr(worker, "_main_editor", None),
                    interactive,
                    pre_hook="",
                    post_hook=getattr(worker, "_post_hook", ""),
                    output_dir=getattr(worker, "_main_output_dir", None),
                )
            else:
                self.build_done.emit(run_id.replace("_pre", ""),
                                     False, tr("build.pre_hook_failed",
                default="Pre-hook failed"))
            if not ok:
                self.release_build_context(run_id.replace("_pre", ""))
            return

        if hasattr(worker, "_main_command"):
            cmd = worker._main_command
            cwd = worker._main_cwd
            env = worker._main_env
            interactive = worker._main_interactive
            post_hook = getattr(worker, "_post_hook", "")
            file_path = getattr(worker, "_main_file_path", None)
            editor = getattr(worker, "_main_editor", None)
            output_dir = getattr(worker, "_main_output_dir", None)

            self._do_run(run_id, cmd, cwd, env, getattr(worker, "_main_profile", {}),
                        file_path, editor, interactive, pre_hook="", post_hook=post_hook,
                        output_dir=output_dir)
            return

        if hasattr(worker, "_pipeline"):
            self._continue_pipeline(run_id, worker, ok)
            return

        if ok:
            msg = tr("msg.build_finished_ok", seconds=f"{secs:.1f}")
        elif getattr(worker, "_outcome", (None,))[0] == "timeout":
            msg = tr("build.timeout", seconds=f"{secs:g}",
                     default="Build timed out after {seconds}s.")
        else:
            msg = tr("msg.build_finished_error", code=-1)
        self.build_done.emit(run_id, ok, msg)

        self.release_build_context(run_id)

        if ok and hasattr(worker, "_post_hook") and worker._post_hook:
            hook_cmd = self._expand_profile_command(
                worker._post_hook.strip(),
                getattr(worker, "_post_hook_file_path", None),
                getattr(worker, "_post_hook_editor", None),
                output_dir=getattr(worker, "_output_dir", None),
            )
            self.build_output.emit(run_id, tr("build.post_hook", cmd=hook_cmd,
                default="Post-hook: {cmd}"))
            env = {**os.environ}
            from core.external_open import clean_subprocess_env
            env = clean_subprocess_env()
            hook_rid = run_id + "_post"
            self._spawn_worker(hook_rid, hook_cmd, ".", env, False)


    def stop(self, run_id: str = "") -> None:
        if run_id:
            worker = self._workers.get(run_id)
            if worker:
                worker.abort()
        else:
            for w in self._workers.values():
                w.abort()

    def is_running(self, run_id: str = "") -> bool:
        if run_id:
            return run_id in self._workers and self._workers[run_id].isRunning()
        return any(w.isRunning() for w in self._workers.values())

    def send_input(self, run_id: str, text: str) -> None:
        worker = self._workers.get(run_id)
        if isinstance(worker, InteractiveBuildWorker):
            worker.send_input(text)

    def get_output_limit(self) -> int:
        from config.settings import Settings
        return Settings.instance().get("build/output_max_lines", self._MAX_OUTPUT_LINES)

    def get_build_timeout(self) -> float | None:
        """Return the build timeout in seconds, or ``None`` when disabled."""
        from config.settings import Settings
        try:
            value = float(Settings.instance().get("build/timeout_seconds", 300))
        except (TypeError, ValueError):
            value = 300.0
        return value if value > 0 else None

    def get_state(self, run_id: str) -> str | None:
        """Return the latest lifecycle state for a build run."""
        return self._build_states.get(run_id)

    def _set_build_state(self, run_id: str, state: str) -> None:
        if self._build_states.get(run_id) != state:
            self._build_states[run_id] = state
            self.build_state_changed.emit(run_id, state)

    # ── Espansione variabili ──────────────────────────────────────────────────

    def _expand_profile_command(self, command: str, path: Path | None,
                                editor: Optional["EditorWidget"],
                                output_dir: Path | None = None,
                                root_file: Path | None = None) -> BuildCommand:
        # LaTeX profiles retain their established shell behavior. The argv
        # conversion below is deliberately limited to non-LaTeX builds.
        if path and path.suffix.lower() in {".tex", ".ltx", ".latex"}:
            return self._expand_vars(command, path, editor, output_dir, root_file)
        return self._expand_command(command, path, editor, output_dir, root_file)

    def _expand_command(self, command: str, path: Path | None,
                        editor: Optional["EditorWidget"],
                        output_dir: Path | None = None,
                        root_file: Path | None = None) -> BuildCommand:
        """Expand a profile into argv unless it deliberately needs a shell.

        Tokens are split before substitutions, which keeps a substituted path
        with spaces as one argument and prevents filename characters from
        becoming shell syntax.
        """
        if _command_needs_shell(command):
            return self._expand_shell_vars(command, path, editor, output_dir, root_file)
        try:
            tokens = shlex.split(command, posix=True)
        except ValueError:
            # A malformed profile used to be executed by the shell; preserve
            # that useful error output instead of failing in the UI thread.
            return self._expand_shell_vars(command, path, editor, output_dir, root_file)
        return [
            self._expand_vars(token, path, editor, output_dir, root_file)
            for token in tokens
        ]

    def _expand_shell_vars(self, command: str, path: Path | None,
                           editor: Optional["EditorWidget"],
                           output_dir: Path | None = None,
                           root_file: Path | None = None) -> str:
        """Use environment expansion for shell profiles so values are not reparsed."""
        env_names = {
            "FILE": "NOTEPADPQ_FILE",
            "DIR": "NOTEPADPQ_DIR",
            "BASENAME": "NOTEPADPQ_BASENAME",
            "BASEFILE": "NOTEPADPQ_BASEFILE",
            "EXT": "NOTEPADPQ_EXT",
            "FILENAME": "NOTEPADPQ_FILENAME",
            "OUTDIR": "NOTEPADPQ_OUTDIR",
            "ROOT": "NOTEPADPQ_ROOT",
        }
        for name, env_name in env_names.items():
            value_ref = f'"%{env_name}%"' if IS_WINDOWS else f'"${{{env_name}}}"'
            command = command.replace(f"${{{name}}}", value_ref)
            command = command.replace(f"$({name})", value_ref)
        # Cursor positions are numeric and are not derived from a path.
        return self._expand_vars(command, path, editor, output_dir, root_file)

    def _expand_vars(self, command: str, path: Path | None,
                     editor: Optional["EditorWidget"],
                     output_dir: Path | None = None,
                     root_file: Path | None = None) -> str:
        line, col = (1, 1)
        if editor:
            line, col = editor.get_cursor_position_1based()

        vals = {
            "FILE":     str(path) if path else "",
            "DIR":      str(path.parent) if path else "",
            "BASENAME": path.stem if path else "",
            "BASEFILE": str(path.parent / path.stem) if path else "",
            "EXT":      path.suffix if path else "",
            "FILENAME": path.name if path else "",
            "LINE":     str(line),
            "COL":      str(col),
            "OUTDIR":   str(output_dir or (path.parent if path else "")),
            "ROOT":     str(root_file or path or ""),
        }
        for name, val in vals.items():
            command = command.replace(f"${{{name}}}", val)
            command = command.replace(f"$({name})", val)
        return command

    @staticmethod
    def _add_draftmode_flag(command: str) -> str:
        parts = command.split()
        for i, part in enumerate(parts):
            if part in ("pdflatex", "xelatex", "lualatex"):
                if "-draftmode" not in parts:
                    parts.insert(i + 1, "-draftmode")
                return " ".join(parts)
        return command

    # ── Parsing errori ────────────────────────────────────────────────────────

    @staticmethod
    def _merge_diagnostics(build_errors: list[dict],
                           lsp_diagnostics: list[dict]) -> list[dict]:
        seen = set()
        for err in build_errors:
            seen.add((err.get("file", ""), err.get("line", 0), err.get("message", "")))

        for diag in lsp_diagnostics:
            key = (diag.get("file", ""), diag.get("line", 0), diag.get("message", ""))
            if key not in seen:
                diag["source"] = "LSP"
                build_errors.append(diag)
                seen.add(key)

        return sorted(build_errors, key=lambda e: (e.get("file", ""), e.get("line", 0)))

    def parse_errors(self, output: str, profile_name: str,
                     source_file: Path | None = None,
                     lsp_diagnostics: list[dict] | None = None,
                     output_dir: Path | None = None) -> list[dict]:
        profile = self._profiles.get(profile_name, {})
        if not profile and source_file:
            profile = self.get_project_profiles(source_file).get(profile_name, {})
        if not isinstance(profile, dict):
            profile = {}

        if profile.get("error_parser") == "latex":
            errors = self._parse_latex_log(output, source_file, output_dir)
        elif output and (
            "! " in output[:3000]
            or re.search(r'\.(?:tex|ltx|latex):\d+:', output[:3000])
            or re.search(r'l\.\d+', output[:3000])
        ):
            errors = self._parse_latex_log(output, source_file, output_dir)
        else:
            pattern = profile.get("error_regex", "")
            if not pattern:
                errors = []
            else:
                file_grp = profile.get("error_file_group", 1)
                line_grp = profile.get("error_line_group", 2)
                errors = self._parse_with_regex(output, pattern, file_grp, line_grp)

        if lsp_diagnostics:
            errors = self._merge_diagnostics(errors, lsp_diagnostics)

        return errors

    @staticmethod
    def _parse_with_regex(output: str, pattern: str,
                          file_grp: int, line_grp: int) -> list[dict]:
        errors = []
        try:
            compiled = re.compile(pattern, re.MULTILINE)
            for m in compiled.finditer(output):
                groups = m.groups()
                try:
                    file_ref = groups[file_grp - 1] if file_grp > 0 else ""
                    line_ref = int(groups[line_grp - 1]) if line_grp > 0 else 0
                except (IndexError, ValueError):
                    file_ref, line_ref = "", 0
                errors.append({
                    "file":    file_ref,
                    "line":    line_ref,
                    "message": m.group(0),
                })
        except re.error:
            pass
        return errors

    @staticmethod
    def _parse_latex_log(output: str, source_file: Optional[Path] = None,
                         output_dir: Optional[Path] = None) -> list[dict]:
        errors: list[dict] = []
        seen: set[tuple] = set()
        fallback_file = str(source_file.name) if source_file else ""

        if source_file and source_file.exists():
            log_base = output_dir or source_file.parent
            log_path = Path(log_base) / f"{source_file.stem}.log"
            if log_path.exists():
                try:
                    log_content = log_path.read_text(errors="replace")
                    if log_content:
                        output = log_content
                except Exception as e:
                    _log_warn(f"Error reading LaTeX log file: {e}")
        file_stack: list[str] = []
        current_file: str = ""
        main_file: str = ""
        lines = output.splitlines()

        i = 0
        while i < len(lines):
            raw = lines[i]

            for fm in _RE_LATEX_FILE.finditer(raw):
                f = fm.group(1)
                if f.startswith("./"):
                    f = f[2:]
                file_stack.append(f)
                current_file = f
                if not main_file and f.lower().endswith((".tex", ".ltx", ".latex")):
                    main_file = f
            net_close = raw.count(')') - raw.count('(')
            if net_close > 0:
                for _ in range(min(net_close, len(file_stack))):
                    file_stack.pop()
                current_file = file_stack[-1] if file_stack else ""

            bm = _RE_LATEX_BANG.search(raw)
            if bm:
                msg = bm.group(1).strip()
                line_num = 0
                fm = _RE_LATEX_MODERN.search(raw)
                if fm:
                    current_file = fm.group(1)
                    line_num = int(fm.group(2))
                    msg = fm.group(3).strip()
                else:
                    for k in range(i + 1, min(i + 15, len(lines))):
                        lm = _RE_LATEX_LNUM.match(lines[k])
                        if lm:
                            line_num = int(lm.group(1))
                            break
                eff_file = current_file or main_file or fallback_file
                key = (eff_file, line_num, msg)
                if key not in seen:
                    seen.add(key)
                    errors.append({
                        "file": eff_file,
                        "line": line_num,
                        "message": msg,
                    })

            fm = _RE_LATEX_MODERN.search(raw)
            if fm and not _RE_LATEX_BANG.search(raw):
                f = fm.group(1)
                if f.startswith("./"):
                    f = f[2:]
                lnum = int(fm.group(2))
                msg  = fm.group(3).strip()
                key  = (f, lnum, msg)
                if key not in seen:
                    if f and f.lower().endswith((".tex", ".ltx", ".latex")):
                        current_file = f
                    seen.add(key)
                    errors.append({"file": f or current_file, "line": lnum, "message": msg})

            i += 1

        for m in _RE_LATEX_WARN.finditer(output):
            msg = m.group(1).strip()
            pos = m.start()
            before = output[:pos]
            lm = None
            for lm_match in re.finditer(r'l\.(\d+)', before):
                lm = lm_match
            line_num = int(lm.group(1)) if lm else 0
            eff_file = current_file or main_file or fallback_file
            key = (eff_file, line_num, msg[:120])
            if key not in seen:
                seen.add(key)
                errors.append({
                    "file": eff_file,
                    "line": line_num,
                    "message": f"Warning: {msg[:120]}",
                })

        return errors

    # ── Task discovery ────────────────────────────────────────────────────────

    @staticmethod
    def discover_tasks(directory: Path) -> list[dict]:
        tasks: list[dict] = []

        # Makefile targets
        makefile = directory / "Makefile"
        if not makefile.exists():
            makefile = directory / "makefile"
        if makefile.exists():
            try:
                for line in makefile.read_text(errors="replace").splitlines():
                    m = re.match(r"^([a-zA-Z0-9_\-]+)\s*:", line)
                    if m:
                        target = m.group(1)
                        if target not in ("all", "PHONY", ".PHONY"):
                            tasks.append({"name": f"make {target}", "cmd": f"make {target}", "source": "Makefile"})
            except Exception as e:
                _log_warn(f"Error reading Makefile: {e}")

        pkg = directory / "package.json"
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text())
                for name, cmd in data.get("scripts", {}).items():
                    tasks.append({"name": f"npm run {name}", "cmd": f"npm run {name}", "source": "package.json"})
            except Exception as e:
                _log_warn(f"Error reading package.json: {e}")

        pyproject = directory / "pyproject.toml"
        if pyproject.exists():
            try:
                text = pyproject.read_text()
                in_tasks = False
                for line in text.splitlines():
                    line = line.strip()
                    if line in ("[tool.taskipy.tasks]", "[tool.scripts]"):
                        in_tasks = True
                        continue
                    if line.startswith("[") and in_tasks:
                        in_tasks = False
                    if in_tasks and "=" in line:
                        parts = line.split("=", 1)
                        name = parts[0].strip().strip('"')
                        cmd_raw = parts[1].strip().strip('"').strip("'")
                        tasks.append({"name": name, "cmd": cmd_raw, "source": "pyproject.toml"})
            except Exception as e:
                _log_warn(f"Error reading pyproject.toml: {e}")

        cargo_toml = directory / "Cargo.toml"
        if cargo_toml.exists():
            tasks.extend([
                {"name": "cargo build",   "cmd": "cargo build",   "source": "Cargo.toml"},
                {"name": "cargo run",     "cmd": "cargo run",     "source": "Cargo.toml"},
                {"name": "cargo test",    "cmd": "cargo test",    "source": "Cargo.toml"},
                {"name": "cargo check",   "cmd": "cargo check",   "source": "Cargo.toml"},
                {"name": "cargo fmt",     "cmd": "cargo fmt",     "source": "Cargo.toml"},
                {"name": "cargo clippy",  "cmd": "cargo clippy",  "source": "Cargo.toml"},
                {"name": "cargo clean",   "cmd": "cargo clean",   "source": "Cargo.toml"},
            ])

        # CMakeLists.txt
        cmake_file = directory / "CMakeLists.txt"
        build_dir = directory / "build"
        if cmake_file.exists():
            cmds = [f"cmake -S . -B build", f"cmake --build build"]
            for c in cmds:
                tasks.append({"name": c, "cmd": c, "source": "CMake"})
            if build_dir.exists():
                tasks.append({"name": "cmake --build build --clean-first",
                              "cmd": "cmake --build build --clean-first",
                              "source": "CMake"})

        # Gradle (build.gradle or build.gradle.kts)
        g1 = directory / "build.gradle"
        g2 = directory / "build.gradle.kts"
        g3 = directory / "settings.gradle"
        g4 = directory / "settings.gradle.kts"
        if g1.exists() or g2.exists() or g3.exists() or g4.exists():
            # Use gradlew if available, else system gradle
            gradle_cmd = "./gradlew" if (directory / "gradlew").exists() else "gradle"
            tasks.extend([
                {"name": f"{gradle_cmd} build",  "cmd": f"{gradle_cmd} build",  "source": "Gradle"},
                {"name": f"{gradle_cmd} test",   "cmd": f"{gradle_cmd} test",   "source": "Gradle"},
                {"name": f"{gradle_cmd} run",    "cmd": f"{gradle_cmd} run",    "source": "Gradle"},
                {"name": f"{gradle_cmd} clean",  "cmd": f"{gradle_cmd} clean",  "source": "Gradle"},
                {"name": f"{gradle_cmd} assemble","cmd": f"{gradle_cmd} assemble","source": "Gradle"},
            ])

        # docker-compose.yml / compose.yml
        dc = directory / "docker-compose.yml"
        if not dc.exists():
            dc = directory / "compose.yml"
        if not dc.exists():
            dc = directory / "docker-compose.yaml"
        if not dc.exists():
            dc = directory / "compose.yaml"
        if dc.exists():
            tasks.extend([
                {"name": "docker compose up",      "cmd": "docker compose up",      "source": "Docker"},
                {"name": "docker compose up -d",   "cmd": "docker compose up -d",   "source": "Docker"},
                {"name": "docker compose down",    "cmd": "docker compose down",    "source": "Docker"},
                {"name": "docker compose build",   "cmd": "docker compose build",   "source": "Docker"},
                {"name": "docker compose restart",  "cmd": "docker compose restart", "source": "Docker"},
            ])

        # Dockerfile
        if (directory / "Dockerfile").exists():
            tasks.append({"name": "docker build -t app .",
                          "cmd": "docker build -t app .",
                          "source": "Docker"})

        # justfile / .justfile
        jf = directory / "justfile"
        if not jf.exists():
            jf = directory / ".justfile"
        if jf.exists():
            try:
                for line in jf.read_text(errors="replace").splitlines():
                    m = re.match(r"^([a-zA-Z0-9_\-]+)\s*:", line)
                    if m:
                        target = m.group(1)
                        tasks.append({"name": f"just {target}", "cmd": f"just {target}", "source": "justfile"})
            except Exception as e:
                _log_warn(f"Error reading justfile: {e}")

        return tasks

    def get_lsp_diagnostics(self, file_path: Path) -> list[dict]:
        """Recupera le diagnostiche LSP per un file specifico."""
        diagnostics = []
        try:
            from plugins.plugin_manager import PluginManager
            lsp_entry = PluginManager.instance().get_all().get("LSP Client", {})
            lsp_plugin = lsp_entry.get("instance")
            if lsp_plugin and hasattr(lsp_plugin, "diagnostics_for_file"):
                raw = lsp_plugin.diagnostics_for_file(str(file_path))
                if raw:
                    for d in raw:
                        diagnostics.append({
                            "file": str(file_path),
                            "line": d.get("line", 0) + 1,
                            "message": d.get("message", ""),
                            "severity": "LSP",
                            "source": "LSP",
                        })
        except Exception as e:
            _log_warn(f"Error getting LSP diagnostics: {e}")
        return diagnostics

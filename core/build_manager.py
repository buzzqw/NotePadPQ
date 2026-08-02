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
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, TYPE_CHECKING
from uuid import uuid4

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core.platform import get_default_shell, get_shell_exec_flag, IS_WINDOWS
from core.platform import get_config_dir
from i18n.i18n import tr

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget


def _log_warn(msg: str) -> None:
    """Log a warning to stderr — silent fallbacks should not hide real issues."""
    print(f"[build_manager] {msg}", file=sys.stderr)

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
        "extensions": [".tex"],
        "compile":    "pdflatex -file-line-error -synctex=1 -interaction=nonstopmode -output-directory=${DIR} ${FILE}",
        "run":        "pdflatex -file-line-error -synctex=1 -interaction=nonstopmode -output-directory=${DIR} ${FILE}",
        "build":      "latexmk -pdf -file-line-error -synctex=1 -output-directory=${DIR} ${FILE}",
        "error_parser": "latex",
    },
    "LaTeX (xelatex)": {
        "extensions": [".tex"],
        "compile":    "xelatex -file-line-error -synctex=1 -interaction=nonstopmode -output-directory=${DIR} ${FILE}",
        "run":        "xelatex -file-line-error -synctex=1 -interaction=nonstopmode -output-directory=${DIR} ${FILE}",
        "build":      "latexmk -xelatex -file-line-error -synctex=1 -output-directory=${DIR} ${FILE}",
        "error_parser": "latex",
    },
    "LaTeX (lualatex)": {
        "extensions": [".tex"],
        "compile":    "lualatex -file-line-error -synctex=1 -interaction=nonstopmode -output-directory=${DIR} ${FILE}",
        "run":        "lualatex -file-line-error -synctex=1 -interaction=nonstopmode -output-directory=${DIR} ${FILE}",
        "build":      "latexmk -lualatex -file-line-error -synctex=1 -output-directory=${DIR} ${FILE}",
        "error_parser": "latex",
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
_RE_LATEX_FILE  = re.compile(r'\(([^\s()]+\.(?:tex|sty|cls|def|cfg|fd|clo))\b')
_RE_LATEX_BANG  = re.compile(r'!\s*(.+)')
_RE_LATEX_LNUM  = re.compile(r'^l\.(\d+)')
_RE_LATEX_MODERN = re.compile(r'([^\s:]+\.(?:tex|sty|cls|aux)):(\d+):\s*(.+)')
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

    def __init__(self, command: str, cwd: str, env: dict, run_id: str = ""):
        super().__init__()
        self._command = command
        self._cwd     = cwd
        self._env     = env
        self._run_id  = run_id
        self._proc: Optional[subprocess.Popen] = None
        self._abort   = False

    def run(self) -> None:
        shell   = get_default_shell()
        flag    = get_shell_exec_flag()
        start   = time.monotonic()

        try:
            self._proc = subprocess.Popen(
                [shell, flag, self._command],
                cwd=self._cwd,
                env=self._env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for line in self._proc.stdout:
                if self._abort:
                    self._proc.terminate()
                    self.stopped.emit()
                    return
                self.output_line.emit(line.rstrip())

            self._proc.wait()
            elapsed = time.monotonic() - start

            if self._abort:
                self.stopped.emit()
            elif self._proc.returncode == 0:
                self.finished_ok.emit(elapsed)
            else:
                self.finished_err.emit(self._proc.returncode)

        except Exception as e:
            self.output_line.emit(tr("build.error_prefix", error=str(e)))
            self.finished_err.emit(-1)

    def abort(self) -> None:
        self._abort = True
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass


class InteractiveBuildWorker(QThread):
    """Thread per build interattive con PTY (pseudo-terminale)."""

    output_line  = pyqtSignal(str)
    finished_ok  = pyqtSignal(float)
    finished_err = pyqtSignal(int)
    stopped      = pyqtSignal()

    def __init__(self, command: str, cwd: str, env: dict, run_id: str = ""):
        super().__init__()
        self._command = command
        self._cwd     = cwd
        self._env     = env
        self._run_id  = run_id
        self._proc: Optional[subprocess.Popen] = None
        self._abort   = False
        self._input_queue: list[str] = []

    def send_input(self, text: str) -> None:
        self._input_queue.append(text)

    def run(self) -> None:
        if _has_pty() and not IS_WINDOWS:
            self._run_pty()
        else:
            self._run_pipe()

    def _run_pty(self) -> None:
        import pty
        import select
        start = time.monotonic()

        try:
            master_fd, slave_fd = pty.openpty()
            try:
                self._proc = subprocess.Popen(
                    self._command,
                    cwd=self._cwd,
                    env=self._env,
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    shell=True,
                    preexec_fn=os.setsid,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                os.close(slave_fd)

                master = os.fdopen(master_fd, "r", encoding="utf-8", errors="replace")
                master_w = open(master_fd, "w", encoding="utf-8", errors="replace")

                timeout = 0.05
                while True:
                    if self._abort:
                        try:
                            os.killpg(os.getpgid(self._proc.pid), 15)
                        except Exception:
                            self._proc.terminate()
                        self.stopped.emit()
                        return

                    while self._input_queue:
                        inp = self._input_queue.pop(0)
                        try:
                            master_w.write(inp)
                            master_w.flush()
                        except Exception:
                            pass

                    r, _, _ = select.select([master], [], [], timeout)
                    if r:
                        try:
                            line = master.readline()
                            if not line:
                                break
                            self.output_line.emit(line.rstrip("\n\r"))
                        except Exception:
                            break

                self._proc.wait()
                elapsed = time.monotonic() - start
                if self._abort:
                    self.stopped.emit()
                elif self._proc.returncode == 0:
                    self.finished_ok.emit(elapsed)
                else:
                    self.finished_err.emit(self._proc.returncode)

            finally:
                try:
                    os.close(master_fd)
                except Exception:
                    pass

        except Exception as e:
            self.output_line.emit(tr("build.error_prefix", error=str(e)))
            self.finished_err.emit(-1)

    def _run_pipe(self) -> None:
        """Fallback non-PTY per Windows (pipe standard)."""
        shell = get_default_shell()
        flag = get_shell_exec_flag()
        start = time.monotonic()

        try:
            self._proc = subprocess.Popen(
                [shell, flag, self._command],
                cwd=self._cwd,
                env=self._env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
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

            for line in self._proc.stdout:
                if self._abort:
                    self._proc.terminate()
                    self.stopped.emit()
                    return
                self.output_line.emit(line.rstrip())

            self._proc.wait()
            elapsed = time.monotonic() - start
            if self._abort:
                self.stopped.emit()
            elif self._proc.returncode == 0:
                self.finished_ok.emit(elapsed)
            else:
                self.finished_err.emit(self._proc.returncode)

        except Exception as e:
            self.output_line.emit(tr("build.error_prefix", error=str(e)))
            self.finished_err.emit(-1)

    def abort(self) -> None:
        self._abort = True
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass


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


def clean_aux_files(base_path: Path, keep_synctex: bool = True) -> list[str]:
    removed = []
    for ext in AUX_EXTENSIONS:
        if keep_synctex and ext == ".synctex.gz":
            continue
        candidate = base_path.with_name(base_path.name + ext)
        if candidate.exists():
            try:
                candidate.unlink()
                removed.append(candidate.name)
            except OSError as e:
                _log_warn(f"Could not remove aux file {candidate.name}: {e}")
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

    _instance: Optional["BuildManager"] = None
    _MAX_OUTPUT_LINES = 10000

    def __init__(self):
        super().__init__()
        self._profiles: dict[str, dict] = dict(DEFAULT_PROFILES)
        self._workers: dict[str, BuildWorker | InteractiveBuildWorker] = {}
        self._active_profile: str = ""
        self._profile_overrides: dict[str, str] = {}
        self._project_configs: dict[Path, dict] = {}
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
        override = self._profile_overrides.get(ext, "")
        if override and override in self._profiles:
            return override
        for name, profile in self._profiles.items():
            if ext in profile.get("extensions", []):
                return name
        return None

    # ── Configurazione di progetto (.notepadpq-build.json) ─────────────────────

    def _find_project_config(self, file_path: Path) -> Optional[dict]:
        current = file_path.parent
        while True:
            cfg_path = current / ".notepadpq-build.json"
            if cfg_path.exists():
                if cfg_path in self._project_configs:
                    return self._project_configs[cfg_path]
                try:
                    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                    self._project_configs[cfg_path] = cfg
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
            return cfg.get("profiles", {})
        return {}

    def get_project_tasks(self, file_path: Path) -> list[dict]:
        cfg = self._find_project_config(file_path)
        if cfg:
            return cfg.get("tasks", [])
        return []

    # ── Esecuzione ────────────────────────────────────────────────────────────

    def run(self, action: str, editor: Optional["EditorWidget"],
            run_id: str = "", interactive: bool = False) -> bool:
        if editor is None or editor.file_path is None:
            return False

        file_path = editor.file_path
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
        lines = content.splitlines()[:10]
        for line in lines:
            match = re.search(r'%\s*!TEX\s+root\s*=\s*(.+)', line)
            if match:
                root_file_str = match.group(1).strip()
                possible_root = file_path.parent / root_file_str
                if possible_root.exists():
                    self.build_output.emit(run_id, tr("build.magic_comment_detected", root=possible_root.name))
                    file_path = possible_root.resolve()
                else:
                    self.build_output.emit(run_id, tr("build.magic_comment_ignored", file=root_file_str, dir=str(file_path.parent)))
                break

        profile_name = self.get_profile_for_file(file_path)
        if not profile_name:
            self.build_output.emit(run_id, tr("build.no_profile", suffix=file_path.suffix))
            return False

        profile = self._profiles[profile_name]

        pipeline = profile.get("pipeline", [])
        if pipeline:
            return self._run_pipeline(run_id, pipeline, file_path, editor, profile, interactive)

        command = profile.get(action, "")
        if not command:
            self.build_output.emit(run_id, tr("build.no_command", action=action, profile=profile_name))
            return False

        command = self._expand_vars(command, file_path, editor)

        if file_path.suffix == ".tex" and Settings.instance().get("build/draft_mode", False):
            command = self._add_draftmode_flag(command)

        env = self._build_env(file_path, profile)

        return self._do_run(run_id, command, str(file_path.parent), env,
                           profile, file_path, editor, interactive,
                           pre_hook=profile.get("pre_hook", ""),
                           post_hook=profile.get("post_hook", ""))

    def run_task(self, cmd: str, cwd: Path, run_id: str = "",
                 interactive: bool = False) -> bool:
        if not run_id:
            run_id = f"task_{uuid4().hex[:8]}"
        env = {**os.environ}
        from core.external_open import clean_subprocess_env
        env = clean_subprocess_env()

        self.build_started.emit(run_id, "task")
        self.build_output.emit(run_id, tr("msg.build_started", command=cmd))

        self._spawn_worker(run_id, cmd, str(cwd), env, interactive)
        return True

    def _run_pipeline(self, run_id: str, pipeline: list, file_path: Path,
                      editor, profile: dict, interactive: bool) -> bool:
        command = self._expand_vars(pipeline[0].get("cmd", ""), file_path, editor)
        env = self._build_env(file_path, profile)

        self.build_started.emit(run_id, "pipeline")
        self.pipeline_step.emit(run_id, 1, len(pipeline), pipeline[0].get("name", "Step 1"))
        self.build_output.emit(run_id, tr("build.pipeline_started",
                                          step=pipeline[0].get("name", ""),
                                          total=len(pipeline),
                                          default="Pipeline [{step}/{total}] started"))

        worker = self._spawn_worker(run_id, command, str(file_path.parent), env, interactive)
        if worker:
            worker._pipeline_index = 0
            worker._pipeline = pipeline
            worker._pipeline_file_path = file_path
            worker._pipeline_editor = editor
            worker._pipeline_profile = profile
            worker._pipeline_interactive = interactive
            worker._pipeline_env = env
        return True

    def _continue_pipeline(self, run_id: str, success: bool) -> None:
        worker = self._workers.get(run_id)
        if not worker or not hasattr(worker, "_pipeline_index"):
            return

        idx = getattr(worker, "_pipeline_index", 0)
        pipeline = getattr(worker, "_pipeline", [])
        step = pipeline[idx]

        if not success and step.get("stop_on_error", True):
            self.build_output.emit(run_id,
                tr("build.pipeline_step_failed", name=step.get("name", f"Step {idx+1}"),
                   default="Pipeline step failed: {name}"))
            self.build_done.emit(run_id, False, tr("build.pipeline_failed",
                default="Pipeline stopped due to error"))
            return

        idx += 1
        if idx >= len(pipeline):
            self.build_output.emit(run_id, tr("build.pipeline_complete",
                default="Pipeline completed successfully"))
            self.build_done.emit(run_id, True, tr("build.pipeline_success",
                default="All pipeline steps passed"))
            return

        worker._pipeline_index = idx
        next_step = pipeline[idx]
        file_path = getattr(worker, "_pipeline_file_path", None)
        editor = getattr(worker, "_pipeline_editor", None)
        env = getattr(worker, "_pipeline_env", None)

        cmd = self._expand_vars(next_step.get("cmd", ""), file_path, editor)
        self.pipeline_step.emit(run_id, idx + 1, len(pipeline),
                                next_step.get("name", f"Step {idx+1}"))
        self.build_output.emit(run_id, tr("build.pipeline_step",
                                          num=idx+1, name=next_step.get("name", ""),
                                          default="[{num}] {name}"))

        interactive = getattr(worker, "_pipeline_interactive", False)
        self._spawn_worker(run_id, cmd, str(file_path.parent) if file_path else ".",
                          env, interactive)

    def _build_env(self, file_path: Path, profile: dict) -> dict:
        from core.external_open import clean_subprocess_env
        env = clean_subprocess_env()
        env["NOTEPADPQ_FILE"]     = str(file_path)
        env["NOTEPADPQ_DIR"]      = str(file_path.parent)
        env["NOTEPADPQ_BASENAME"] = file_path.stem

        profile_env = profile.get("env", {})
        if isinstance(profile_env, dict):
            env.update(profile_env)
        elif isinstance(profile_env, str) and profile_env.strip():
            for line in profile_env.strip().splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()

        return env

    def _do_run(self, run_id: str, command: str, cwd: str, env: dict,
                profile: dict, file_path: Path, editor,
                interactive: bool, pre_hook: str = "", post_hook: str = "") -> bool:

        from config.settings import Settings

        def _exec_command(cmd: str) -> BuildWorker:
            if file_path.suffix == ".tex" and Settings.instance().get("build/draft_mode", False):
                cmd = self._add_draftmode_flag(cmd)

            self.build_started.emit(run_id, "build")
            self.build_output.emit(run_id, tr("msg.build_started", command=cmd))

            if Settings.instance().get("build/clean_aux_before_compile", False):
                removed = clean_aux_files(
                    file_path.with_suffix(""),
                    keep_synctex=Settings.instance().get("build/keep_synctex", True),
                )
                if removed:
                    self.build_output.emit(run_id,
                        tr("build_panel.aux_cleaned", n=len(removed), files=", ".join(removed)))

            return self._spawn_worker(run_id, cmd, cwd, env, interactive)

        if pre_hook and pre_hook.strip():
            hook_cmd = self._expand_vars(pre_hook.strip(), file_path, editor)
            self.build_output.emit(run_id, tr("build.pre_hook", cmd=hook_cmd,
                default="Pre-hook: {cmd}"))
            hook_worker = self._spawn_worker(run_id + "_pre", hook_cmd, cwd, env, interactive)
            if hook_worker:
                hook_worker._is_hook = "pre"
                hook_worker._main_command = command
                hook_worker._main_cwd = cwd
                hook_worker._main_env = env
                hook_worker._main_profile = profile
                hook_worker._main_file_path = file_path
                hook_worker._main_editor = editor
                hook_worker._main_interactive = interactive
                hook_worker._post_hook = post_hook
            return True

        worker = _exec_command(command)
        if worker and post_hook:
            worker._post_hook = post_hook
            worker._post_hook_file_path = file_path
            worker._post_hook_editor = editor
        return worker is not None

    def _spawn_worker(self, run_id: str, command: str, cwd: str, env: dict,
                      interactive: bool = False) -> BuildWorker | InteractiveBuildWorker:
        old = self._workers.pop(run_id, None)
        if old and old.isRunning():
            old.output_line.disconnect()
            try:
                old.finished_ok.disconnect()
            except Exception:
                pass
            try:
                old.finished_err.disconnect()
            except Exception:
                pass
            try:
                old.stopped.disconnect()
            except Exception:
                pass
            old.abort()
            old.wait(2000)
            if old.isRunning():
                old.terminate()

        cls = InteractiveBuildWorker if interactive else BuildWorker
        worker = cls(command, cwd, env, run_id)
        worker.output_line.connect(lambda line, rid=run_id: self.build_output.emit(rid, line))
        self._workers[run_id] = worker

        if isinstance(worker, BuildWorker):
            worker.finished_ok.connect(
                lambda secs, rid=run_id: self._on_worker_done(rid, True, secs)
            )
            worker.finished_err.connect(
                lambda code, rid=run_id: self._on_worker_done(rid, False, 0)
            )
            worker.stopped.connect(
                lambda rid=run_id: self.build_done.emit(rid, False, tr("build.interrupted"))
            )
        else:
            worker.finished_ok.connect(
                lambda secs, rid=run_id: self._on_worker_done(rid, True, secs)
            )
            worker.finished_err.connect(
                lambda code, rid=run_id: self._on_worker_done(rid, False, 0)
            )
            worker.stopped.connect(
                lambda rid=run_id: self.build_done.emit(rid, False, tr("build.interrupted"))
            )

        worker.start()
        return worker

    def _on_worker_done(self, run_id: str, ok: bool, secs: float) -> None:
        worker = self._workers.get(run_id)

        if hasattr(worker, "_is_hook") and worker._is_hook == "pre":
            if ok:
                main_cmd = getattr(worker, "_main_command", "")
                cwd = getattr(worker, "_main_cwd", ".")
                env = getattr(worker, "_main_env", {})
                interactive = getattr(worker, "_main_interactive", False)
                self._spawn_worker(run_id.replace("_pre", ""), main_cmd, cwd, env, interactive)
            else:
                self.build_done.emit(run_id.replace("_pre", ""),
                                     False, tr("build.pre_hook_failed",
                default="Pre-hook failed"))
            self._workers.pop(run_id, None)
            return

        if hasattr(worker, "_main_command"):
            self._workers.pop(run_id, None)
            cmd = worker._main_command
            cwd = worker._main_cwd
            env = worker._main_env
            interactive = worker._main_interactive
            post_hook = getattr(worker, "_post_hook", "")
            file_path = getattr(worker, "_main_file_path", None)
            editor = getattr(worker, "_main_editor", None)

            self._do_run(run_id, cmd, cwd, env, getattr(worker, "_main_profile", {}),
                        file_path, editor, interactive, pre_hook="", post_hook=post_hook)
            return

        msg = tr("msg.build_finished_ok", seconds=f"{secs:.1f}") if ok else \
              tr("msg.build_finished_error", code=-1)
        self.build_done.emit(run_id, ok, msg)

        if ok and hasattr(worker, "_post_hook") and worker._post_hook:
            hook_cmd = self._expand_vars(worker._post_hook.strip(),
                                         getattr(worker, "_post_hook_file_path", None),
                                         getattr(worker, "_post_hook_editor", None))
            self.build_output.emit(run_id, tr("build.post_hook", cmd=hook_cmd,
                default="Post-hook: {cmd}"))
            env = {**os.environ}
            from core.external_open import clean_subprocess_env
            env = clean_subprocess_env()
            hook_rid = run_id + "_post"
            self._spawn_worker(hook_rid, hook_cmd, ".", env, False)

        if hasattr(worker, "_pipeline"):
            self._continue_pipeline(run_id, ok)

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

    # ── Espansione variabili ──────────────────────────────────────────────────

    def _expand_vars(self, command: str, path: Path,
                     editor: Optional["EditorWidget"]) -> str:
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
                     lsp_diagnostics: list[dict] | None = None) -> list[dict]:
        profile = self._profiles.get(profile_name, {})

        if profile.get("error_parser") == "latex":
            errors = self._parse_latex_log(output, source_file)
        elif output and (
            "! " in output[:3000]
            or re.search(r'\.tex:\d+:', output[:3000])
            or re.search(r'l\.\d+', output[:3000])
        ):
            errors = self._parse_latex_log(output, source_file)
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
    def _parse_latex_log(output: str, source_file: Optional[Path] = None) -> list[dict]:
        errors: list[dict] = []
        seen: set[tuple] = set()
        fallback_file = str(source_file.name) if source_file else ""

        if source_file and source_file.exists():
            log_path = source_file.with_suffix(".log")
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
                if not main_file and f.endswith(".tex"):
                    main_file = f
            net_close = raw.count(')') - raw.count('(')
            if net_close > 0:
                for _ in range(min(net_close, len(file_stack))):
                    file_stack.pop()
                current_file = file_stack[-1] if file_stack else current_file

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
                eff_file = current_file if _RE_LATEX_MODERN.search(raw) else (main_file or current_file or fallback_file)
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
                    if f and f.endswith(".tex"):
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
            eff_file = main_file or current_file or fallback_file
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

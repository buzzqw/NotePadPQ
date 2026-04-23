"""
core/build_manager.py — Gestione profili di compilazione
NotePadPQ

Profili configurabili per linguaggio con:
- Comandi shell (compile / run / build)
- Variabili: ${FILE}, ${DIR}, ${BASENAME}, ${EXT}, ${LINE}, ${COL}
- Parsing errori (riga:colonna cliccabile)
- Shell configurabile per piattaforma
- Salvataggio automatico prima della compilazione
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core.platform import get_default_shell, get_shell_exec_flag, IS_WINDOWS
from core.platform import get_config_dir

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

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
        "extensions": [".cpp", ".cxx", ".cc"],
        "compile":    "g++ -std=c++17 -Wall -o ${DIR}/${BASENAME} ${FILE}",
        "run":        "${DIR}/${BASENAME}",
        "build":      "g++ -std=c++17 -Wall -o ${DIR}/${BASENAME} ${FILE} && ${DIR}/${BASENAME}",
        "error_regex": r'([^:]+):(\d+):\d+: (?:error|warning): (.+)',
        "error_file_group": 1,
        "error_line_group": 2,
    },
    "LaTeX (pdflatex)": {
        "extensions": [".tex"],
        "compile":    "pdflatex -synctex=1 -interaction=nonstopmode -output-directory=${DIR} ${FILE}",
        "run":        "pdflatex -synctex=1 -interaction=nonstopmode -output-directory=${DIR} ${FILE}",
        "build":      "latexmk -pdf -synctex=1 -output-directory=${DIR} ${FILE}",
        "error_regex": r'l\.(\d+)',
        "error_file_group": 0,
        "error_line_group": 1,
    },
    "LaTeX (xelatex)": {
        "extensions": [".tex"],
        "compile":    "xelatex -synctex=1 -interaction=nonstopmode -output-directory=${DIR} ${FILE}",
        "run":        "xelatex -synctex=1 -interaction=nonstopmode -output-directory=${DIR} ${FILE}",
        "build":      "latexmk -xelatex -synctex=1 -output-directory=${DIR} ${FILE}",
        "error_regex": r'l\.(\d+)',
        "error_file_group": 0,
        "error_line_group": 1,
    },
    "LaTeX (lualatex)": {
        "extensions": [".tex"],
        "compile":    "lualatex -synctex=1 -interaction=nonstopmode -output-directory=${DIR} ${FILE}",
        "run":        "lualatex -synctex=1 -interaction=nonstopmode -output-directory=${DIR} ${FILE}",
        "build":      "latexmk -lualatex -synctex=1 -output-directory=${DIR} ${FILE}",
        "error_regex": r'l\.(\d+)',
        "error_file_group": 0,
        "error_line_group": 1,
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
        "compile":    "bash -n ${FILE}",   # syntax check
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

# ─── BuildWorker ──────────────────────────────────────────────────────────────

class BuildWorker(QThread):
    """Thread che esegue il processo di build."""

    output_line  = pyqtSignal(str)       # linea di output
    finished_ok  = pyqtSignal(float)     # secondi
    finished_err = pyqtSignal(int)       # exit code
    stopped      = pyqtSignal()

    def __init__(self, command: str, cwd: str, env: dict):
        super().__init__()
        self._command = command
        self._cwd     = cwd
        self._env     = env
        self._proc: Optional[subprocess.Popen] = None
        self._abort   = False

    def run(self) -> None:
        import time
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
            self.output_line.emit(f"[Errore] {e}")
            self.finished_err.emit(-1)

    def abort(self) -> None:
        self._abort = True
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass


# ─── BuildManager ─────────────────────────────────────────────────────────────

class BuildManager(QObject):
    """
    Singleton. Gestisce i profili di compilazione e l'esecuzione dei build.
    """

    build_output = pyqtSignal(str)          # linea output
    build_done   = pyqtSignal(bool, str)    # success, message
    build_errors = pyqtSignal(list)         # lista dict {file, line, msg}

    _instance: Optional["BuildManager"] = None

    def __init__(self):
        super().__init__()
        self._profiles: dict[str, dict] = dict(DEFAULT_PROFILES)
        self._worker: Optional[BuildWorker] = None
        self._active_profile: str = ""
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
                self._profiles.update(data)
            except Exception:
                pass

    def save_profiles(self) -> None:
        """
        Salva su disco tutti i profili che:
        - sono nuovi (non built-in), oppure
        - sono built-in ma modificati rispetto al default
        I profili built-in non modificati non vengono salvati (vengono
        ricaricati dai DEFAULT_PROFILES ad ogni avvio).
        """
        profiles_to_save = {}
        for name, profile in self._profiles.items():
            if name not in DEFAULT_PROFILES:
                # Profilo utente nuovo
                profiles_to_save[name] = profile
            elif profile != DEFAULT_PROFILES[name]:
                # Profilo built-in modificato — salvalo come override
                profiles_to_save[name] = profile
        try:
            self._profiles_path().write_text(
                json.dumps(profiles_to_save, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            print(f"[build_manager] Errore salvataggio profili: {e}")

    def get_profiles(self) -> dict[str, dict]:
        return dict(self._profiles)

    def add_profile(self, name: str, profile: dict) -> None:
        self._profiles[name] = profile
        self.save_profiles()

    def remove_profile(self, name: str) -> None:
        if name not in DEFAULT_PROFILES:
            self._profiles.pop(name, None)
            self.save_profiles()

    def get_profile_for_file(self, path: Path) -> Optional[str]:
        """Trova il profilo più adatto per un file.
        Se è stato impostato manualmente un profilo attivo, ha la precedenza."""
        if self._active_profile and self._active_profile in self._profiles:
            return self._active_profile
        ext = path.suffix.lower()
        for name, profile in self._profiles.items():
            if ext in profile.get("extensions", []):
                return name
        return None

    # ── Esecuzione ────────────────────────────────────────────────────────────

    def run(self, action: str, editor: Optional["EditorWidget"]) -> bool:
        """
        Esegue un'azione (compile/run/build) per l'editor corrente.
        action: "compile" | "run" | "build"
        """
        if self._worker and self._worker.isRunning():
            return False

        if editor is None or editor.file_path is None:
            return False

        file_path = editor.file_path

        # Salvataggio automatico
        from config.settings import Settings
        if Settings.instance().get("build/save_before", True):
            if editor.is_modified():
                from ui.main_window import MainWindow
                win = editor.window()
                if hasattr(win, "action_save"):
                    win.action_save()

        # Trova il profilo
        profile_name = self.get_profile_for_file(file_path)
        if not profile_name:
            self.build_output.emit(f"[Nessun profilo per {file_path.suffix}]")
            return False

        profile = self._profiles[profile_name]
        command = profile.get(action, "")
        if not command:
            self.build_output.emit(f"[Nessun comando '{action}' nel profilo {profile_name}]")
            return False

        # Espansione variabili
        command = self._expand_vars(command, file_path, editor)

        # Ambiente
        env = os.environ.copy()
        env["NOTEPADPQ_FILE"]     = str(file_path)
        env["NOTEPADPQ_DIR"]      = str(file_path.parent)
        env["NOTEPADPQ_BASENAME"] = file_path.stem

        # Log
        from i18n.i18n import tr
        self.build_output.emit(tr("msg.build_started", command=command))

        # Avvia worker
        self._worker = BuildWorker(command, str(file_path.parent), env)
        self._worker.output_line.connect(self.build_output)
        self._worker.finished_ok.connect(
            lambda secs: self._on_done(True, secs, profile)
        )
        self._worker.finished_err.connect(
            lambda code: self._on_error(code, profile)
        )
        self._worker.stopped.connect(
            lambda: self.build_done.emit(False, "Interrotto")
        )
        self._worker.start()
        return True

    def stop(self) -> None:
        if self._worker:
            self._worker.abort()

    def _on_done(self, ok: bool, secs: float, profile: dict) -> None:
        from i18n.i18n import tr
        msg = tr("msg.build_finished_ok", seconds=f"{secs:.1f}")
        self.build_done.emit(True, msg)

    def _on_error(self, code: int, profile: dict) -> None:
        from i18n.i18n import tr
        msg = tr("msg.build_finished_error", code=code)
        self.build_done.emit(False, msg)

    # ── Espansione variabili ──────────────────────────────────────────────────

    def _expand_vars(self, command: str, path: Path,
                     editor: Optional["EditorWidget"]) -> str:
        line, col = (1, 1)
        if editor:
            line, col = editor.get_cursor_position_1based()

        replacements = {
            "${FILE}":     str(path),
            "${DIR}":      str(path.parent),
            "${BASENAME}": path.stem,
            "${EXT}":      path.suffix,
            "${FILENAME}": path.name,
            "${LINE}":     str(line),
            "${COL}":      str(col),
        }
        for var, val in replacements.items():
            command = command.replace(var, val)
        return command

    # ── Parsing errori ────────────────────────────────────────────────────────

    def parse_errors(self, output: str, profile_name: str) -> list[dict]:
        """
        Analizza l'output del build e restituisce lista di errori
        con file e numero di riga.
        """
        profile = self._profiles.get(profile_name, {})
        pattern = profile.get("error_regex", "")
        if not pattern:
            return []

        file_grp = profile.get("error_file_group", 1)
        line_grp = profile.get("error_line_group", 2)

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

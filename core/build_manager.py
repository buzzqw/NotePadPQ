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
from i18n.i18n import tr

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
        "error_parser": "latex",
    },
    "LaTeX (xelatex)": {
        "extensions": [".tex"],
        "compile":    "xelatex -synctex=1 -interaction=nonstopmode -output-directory=${DIR} ${FILE}",
        "run":        "xelatex -synctex=1 -interaction=nonstopmode -output-directory=${DIR} ${FILE}",
        "build":      "latexmk -xelatex -synctex=1 -output-directory=${DIR} ${FILE}",
        "error_parser": "latex",
    },
    "LaTeX (lualatex)": {
        "extensions": [".tex"],
        "compile":    "lualatex -synctex=1 -interaction=nonstopmode -output-directory=${DIR} ${FILE}",
        "run":        "lualatex -synctex=1 -interaction=nonstopmode -output-directory=${DIR} ${FILE}",
        "build":      "latexmk -lualatex -synctex=1 -output-directory=${DIR} ${FILE}",
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

# Regex per il parser errori LaTeX (riusate, non ricompilate per ogni build)
# Il percorso non ha un prefisso fisso: pdflatex lo stampa relativo ("./file.tex")
# solo se invocato con un path relativo dalla sua stessa directory; i profili di
# build di questa app passano sempre ${FILE} assoluto, quindi il log riporta
# "(/percorso/assoluto/file.tex" — nessun prefisso "./" da richiedere qui.
_RE_LATEX_FILE  = re.compile(r'\(([^\s()]+\.(?:tex|sty|cls|def|cfg|fd|clo))\b')
_RE_LATEX_BANG  = re.compile(r'^! (.+)')
_RE_LATEX_LNUM  = re.compile(r'^l\.(\d+)')
_RE_LATEX_MODERN = re.compile(r'^([^\s:]+\.tex):(\d+): (.+)')

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
            self.output_line.emit(tr("build.error_prefix", error=str(e)))
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

    build_started = pyqtSignal(str)         # action ("compile"/"run"/"build"): una build sta per partire
    build_output  = pyqtSignal(str)         # linea output
    build_done    = pyqtSignal(bool, str)   # success, message
    build_errors  = pyqtSignal(list)        # lista dict {file, line, msg}

    _instance: Optional["BuildManager"] = None

    def __init__(self):
        super().__init__()
        self._profiles: dict[str, dict] = dict(DEFAULT_PROFILES)
        self._worker: Optional[BuildWorker] = None
        self._active_profile: str = ""  # mantenuto per compatibilità
        self._profile_overrides: dict[str, str] = {}  # ext → nome profilo (override per-estensione)
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
            except Exception:
                pass

    def save_profiles(self) -> None:
        """
        Salva su disco tutti i profili che:
        - sono nuovi (non built-in), oppure
        - sono built-in ma modificati rispetto al default
        I profili built-in non modificati non vengono salvati (vengono
        ricaricati dai DEFAULT_PROFILES ad ogni avvio).
        Salva sempre __order__ per ripristinare l'ordine personalizzato.
        """
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
        """Riordina i profili secondo la lista di nomi fornita, poi salva."""
        reordered = {}
        for name in names:
            if name in self._profiles:
                reordered[name] = self._profiles[name]
        # Aggiungi eventuali profili non presenti nella lista (safety)
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
        """Imposta un override esplicito per un'estensione (es. '.py' → 'Python (uv)')."""
        if ext:
            self._profile_overrides[ext] = name
        self._active_profile = name  # compat
        self.save_profiles()

    def clear_profile_override(self, ext: str) -> None:
        """Rimuove l'override per un'estensione, tornando all'auto-detect."""
        self._profile_overrides.pop(ext, None)
        self.save_profiles()

    def get_profile_for_file(self, path: Path) -> Optional[str]:
        """Trova il profilo più adatto per un file.
        Priorità: override per-estensione → auto-detect dalla lista profili."""
        ext = path.suffix.lower()
        # Override esplicito per questa estensione
        override = self._profile_overrides.get(ext, "")
        if override and override in self._profiles:
            return override
        # Auto-detect
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

        # --- INIZIO MAGIC COMMENTS (TeXstudio style) ---
        # Controlliamo le prime righe per trovare il file root
        content = editor.get_content()
        lines = content.splitlines()[:10]  # Analizza solo le prime 10 righe
        
        for line in lines:
            # Regex per cercare commenti stile TeXstudio: % !TEX root = nomefile.tex
            match = re.search(r'%\s*!TEX\s+root\s*=\s*(.+)', line)
            if match:
                root_file_str = match.group(1).strip()
                # Il percorso può essere assoluto o relativo al file corrente
                possible_root = file_path.parent / root_file_str
                if possible_root.exists():
                    self.build_output.emit(tr("build.magic_comment_detected", root=possible_root.name))
                    file_path = possible_root.resolve()
                else:
                    self.build_output.emit(tr("build.magic_comment_ignored", file=root_file_str, dir=str(file_path.parent)))
                break # Esce dal ciclo for dopo il primo hit
        # --- FINE MAGIC COMMENTS ---

        # Trova il profilo
        profile_name = self.get_profile_for_file(file_path)
        if not profile_name:
            self.build_output.emit(tr("build.no_profile", suffix=file_path.suffix))
            return False

        profile = self._profiles[profile_name]
        command = profile.get(action, "")
        if not command:
            self.build_output.emit(tr("build.no_command", action=action, profile=profile_name))
            return False

        # Espansione variabili
        command = self._expand_vars(command, file_path, editor)

        # Ambiente: ripristina LD_LIBRARY_PATH originale pre-AppImage per i tool
        # di sistema (xelatex, pdflatex, gcc, …) che altrimenti trovano
        # libstdc++/libglib bundled invece delle versioni native.
        from core.external_open import clean_subprocess_env
        env = clean_subprocess_env()
        env["NOTEPADPQ_FILE"]     = str(file_path)
        env["NOTEPADPQ_DIR"]      = str(file_path.parent)
        env["NOTEPADPQ_BASENAME"] = file_path.stem

        # Segnala l'avvio: la UI (BuildPanel) resetta qui log/errori/pulsanti,
        # indipendentemente dal fatto che la build sia partita dai pulsanti del
        # pannello o da una scorciatoia/menu che chiama run() direttamente.
        self.build_started.emit(action)

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
            lambda: self.build_done.emit(False, tr("build.interrupted"))
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

        vals = {
            "FILE":     str(path),
            "DIR":      str(path.parent),
            "BASENAME": path.stem,
            "BASEFILE": str(path.parent / path.stem),   # percorso completo senza estensione
            "EXT":      path.suffix,
            "FILENAME": path.name,
            "LINE":     str(line),
            "COL":      str(col),
        }
        # Supporta sia ${VAR} che $(VAR)
        for name, val in vals.items():
            command = command.replace(f"${{{name}}}", val)
            command = command.replace(f"$({name})", val)
        return command

    # ── Parsing errori ────────────────────────────────────────────────────────

    # ── Task discovery ────────────────────────────────────────────────────────

    @staticmethod
    def discover_tasks(directory: Path) -> list[dict]:
        """
        Cerca task eseguibili nel progetto: Makefile, package.json, pyproject.toml.
        Restituisce [{"name": str, "cmd": str, "source": str}].
        """
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
            except Exception:
                pass

        # package.json scripts
        pkg = directory / "package.json"
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text())
                for name, cmd in data.get("scripts", {}).items():
                    tasks.append({"name": f"npm run {name}", "cmd": f"npm run {name}", "source": "package.json"})
            except Exception:
                pass

        # pyproject.toml [tool.taskipy.tasks] or [tool.scripts]
        pyproject = directory / "pyproject.toml"
        if pyproject.exists():
            try:
                text = pyproject.read_text()
                # cerca [tool.taskipy.tasks] o [tool.scripts]
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
            except Exception:
                pass

        return tasks

    def run_task(self, cmd: str, cwd: Path) -> None:
        """Esegue un comando task arbitrario (come run/compile ma senza profilo)."""
        from core.platform import get_default_shell, get_shell_exec_flag
        shell = get_default_shell()
        flag  = get_shell_exec_flag()
        env   = {**os.environ}
        self._worker = BuildWorker(cmd, str(cwd), env)
        self._worker.output.connect(self.build_output)
        self._worker.finished.connect(lambda ok: self.build_done.emit(ok, tr("build.task_finished") if ok else tr("build.task_failed")))
        self._worker.start()

    def parse_errors(self, output: str, profile_name: str) -> list[dict]:
        """
        Analizza l'output del build e restituisce lista di errori
        con file e numero di riga.
        """
        profile = self._profiles.get(profile_name, {})

        if profile.get("error_parser") == "latex":
            return self._parse_latex_log(output)

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

    @staticmethod
    def _parse_latex_log(output: str) -> list[dict]:
        """
        Parser dedicato per log LaTeX/XeLaTeX/LuaLaTeX.

        Riconosce:
        - Errori TeX tradizionali: "! messaggio\\nl.N ..."
        - Package errors: "! Package X Error: messaggio"
        - Formato moderno: "./file.tex:N: messaggio"
        """
        errors: list[dict] = []
        seen: set[tuple] = set()

        # ── Pattern 1: errore TeX classico ───────────────────────────────
        # "! Undefined control sequence." poi "l.75 \includegraphics"
        # Scansione riga per riga per mantenere il contesto del file corrente.

        file_stack: list[str] = []
        current_file: str = ""
        lines = output.splitlines()

        i = 0
        while i < len(lines):
            raw = lines[i]

            # Aggiorna stack file (parentesi di apertura)
            for fm in _RE_LATEX_FILE.finditer(raw):
                # .lstrip("./") spoglierebbe anche la "/" iniziale di un path
                # assoluto (lstrip toglie un INSIEME di caratteri, non un prefisso):
                # rimuoviamo quindi solo l'eventuale prefisso letterale "./".
                f = fm.group(1)
                if f.startswith("./"):
                    f = f[2:]
                file_stack.append(f)
                current_file = f
            # Parentesi di chiusura (stima grezza)
            net_close = raw.count(')') - raw.count('(')
            if net_close > 0:
                for _ in range(min(net_close, len(file_stack))):
                    file_stack.pop()
                current_file = file_stack[-1] if file_stack else current_file

            bm = _RE_LATEX_BANG.match(raw)
            if bm:
                msg = bm.group(1).strip()
                # Cerca l.N nelle prossime 15 righe
                line_num = 0
                for k in range(i + 1, min(i + 15, len(lines))):
                    lm = _RE_LATEX_LNUM.match(lines[k])
                    if lm:
                        line_num = int(lm.group(1))
                        break
                key = (current_file, line_num, msg)
                if key not in seen:
                    seen.add(key)
                    errors.append({"file": current_file, "line": line_num, "message": msg})

            i += 1

        # ── Pattern 2: formato moderno "./file.tex:N: messaggio" ─────────
        for m in _RE_LATEX_MODERN.finditer(output):
            f = m.group(1)
            if f.startswith("./"):
                f = f[2:]
            lnum = int(m.group(2))
            msg  = m.group(3).strip()
            key  = (f, lnum, msg)
            if key not in seen:
                seen.add(key)
                errors.append({"file": f, "line": lnum, "message": msg})

        return errors

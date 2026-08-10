"""
plugins/code_formatter_plugin.py — Code Formatter
NotePadPQ

Formatta il documento (o la selezione) corrente invocando il formatter
esterno corretto per il linguaggio rilevato.

Formatter supportati:
  Python  → black  (pip install black)  oppure  ruff format  (pip install ruff)
  JS/TS   → prettier  (npm i -g prettier)
  C/C++   → clang-format  (apt/brew/choco install clang-format)
  Rust    → rustfmt  (rustup component add rustfmt)
  Go      → gofmt  (incluso nel toolchain Go)
   HTML    → prettier
   CSS     → prettier
   LaTeX   → latexindent (install latexindent through TeX Live)
   JSON    → python -m json.tool  (stdlib, sempre disponibile)
  XML     → xmllint  (libxml2-utils) oppure python minidom

Funzionamento "senza danni":
  - Il formatter viene chiamato in subprocess.
  - Solo se esce con codice 0 il testo nell'editor viene sostituito.
  - In caso di errore viene mostrato il messaggio di errore del formatter,
    ma il documento rimane invariato.
  - Se il formatter non è installato, viene mostrato un avviso chiaro.

Menu: Strumenti → 🎨 Format Document  (Ctrl+Alt+F)
      Strumenti → 🎨 Format Selection  (Ctrl+Alt+Shift+F)
      Strumenti → ⚙ Preferenze Formatter...
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.dom.minidom
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from plugins.base_plugin import BasePlugin
from i18n.i18n import tr
from editor.lexers import get_language_name
from ui.busy_indicator import show_busy, hide_busy

if TYPE_CHECKING:
    from ui.main_window import MainWindow


# ─── Ricerca eseguibili ──────────────────────────────────────────────────────

def _find_exe(name: str) -> Optional[str]:
    """
    Cerca l'eseguibile `name` in ordine:
      1. PATH di sistema  (shutil.which)
      2. ~/.local/bin     (pip install --user su Linux/macOS)
      3. <project>/.venv/bin/  (venv dedicato di NotePadPQ)
      4. stessa directory di sys.executable  (venv attivo o Python portatile)
    Ritorna il percorso assoluto trovato, oppure None.
    """
    # 1. PATH standard
    found = shutil.which(name)
    if found:
        return found

    extra_dirs: list[Path] = []

    # 2. ~/.local/bin  (pip install --user)
    local_bin = Path.home() / ".local" / "bin"
    if local_bin.is_dir():
        extra_dirs.append(local_bin)

    # 3. .venv del progetto (cartella del plugin → radice progetto)
    project_root = Path(__file__).resolve().parent.parent
    venv_bin = project_root / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")
    if venv_bin.is_dir():
        extra_dirs.append(venv_bin)

    # 4. directory di sys.executable (venv attivo o Python portatile)
    py_dir = Path(sys.executable).parent
    if py_dir not in extra_dirs:
        extra_dirs.append(py_dir)

    for d in extra_dirs:
        candidate = d / name
        # su Windows prova anche con .exe
        if sys.platform == "win32" and not candidate.suffix:
            candidate_exe = d / (name + ".exe")
            if candidate_exe.is_file():
                return str(candidate_exe)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    return None


# ─── Configurazione default dei formatter ─────────────────────────────────────

_DEFAULT_FORMATTERS: Dict[str, dict] = {
    "python": {
        "cmd":  ["black", "--quiet", "-"],
        "stdin": True,
        "desc": "black (pip install black)",
        "alt":  ["ruff", "format", "--quiet", "-"],
    },
    "javascript": {
        "cmd":  ["prettier", "--stdin-filepath", "file.js"],
        "stdin": True,
        "desc": "prettier (npm i -g prettier)",
    },
    "typescript": {
        "cmd":  ["prettier", "--stdin-filepath", "file.ts"],
        "stdin": True,
        "desc": "prettier (npm i -g prettier)",
    },
    "css": {
        "cmd":  ["prettier", "--stdin-filepath", "file.css"],
        "stdin": True,
        "desc": "prettier (npm i -g prettier)",
    },
    "html": {
        "cmd":  ["prettier", "--stdin-filepath", "file.html"],
        "stdin": True,
        "desc": "prettier (npm i -g prettier)",
    },
    "c": {
        "cmd":  ["clang-format"],
        "stdin": True,
        "desc": "clang-format (apt install clang-format)",
    },
    "cpp": {
        "cmd":  ["clang-format"],
        "stdin": True,
        "desc": "clang-format (apt install clang-format)",
    },
    "rust": {
        "cmd":  ["rustfmt"],
        "stdin": True,
        "desc": "rustfmt (rustup component add rustfmt)",
    },
    "go": {
        "cmd":  ["gofmt"],
        "stdin": True,
        "desc": "gofmt (incluso nel toolchain Go)",
    },
    "json": {
        "cmd":  None,           # gestito internamente con json.tool
        "stdin": True,
        "desc": "json.tool (stdlib Python — sempre disponibile)",
        "builtin": "json",
    },
    "xml": {
        "cmd":  None,
        "stdin": True,
        "desc": "minidom (stdlib Python — sempre disponibile)",
        "builtin": "xml",
    },
    "latex": {
        "cmd":  ["latexindent", "-"],
        "stdin": True,
        "desc": "latexindent (TeX Live / MiKTeX)",
    },
}

# mapping: nome linguaggio QScintilla/lexer → chiave in _DEFAULT_FORMATTERS
_LANG_MAP: Dict[str, str] = {
    "python":     "python",
    "javascript": "javascript",
    "typescript": "typescript",
    "css":        "css",
    "html":       "html",
    "c":          "c",
    "c++":        "cpp",
    "cpp":        "cpp",
    "rust":       "rust",
    "go":         "go",
    "json":       "json",
    "xml":        "xml",
    "latex":      "latex",
}


# ─── Formattazione built-in (JSON, XML) ──────────────────────────────────────

def _format_json(text: str) -> Tuple[bool, str]:
    try:
        obj    = json.loads(text)
        result = json.dumps(obj, indent=2, ensure_ascii=False)
        return True, result
    except Exception as exc:
        return False, str(exc)


def _format_xml(text: str) -> Tuple[bool, str]:
    try:
        dom    = xml.dom.minidom.parseString(text.encode("utf-8"))
        result = dom.toprettyxml(indent="  ", encoding=None)
        # rimuove la riga <?xml…?> ridondante se già presente nel testo originale
        lines  = result.splitlines()
        if lines and lines[0].startswith("<?xml") and not text.strip().startswith("<?xml"):
            lines = lines[1:]
        return True, "\n".join(lines)
    except Exception as exc:
        return False, str(exc)


# ─── Chiamata subprocess ─────────────────────────────────────────────────────

def _run_formatter(cmd: List[str], text: str,
                    register_proc: Optional[callable] = None) -> Tuple[bool, str, str]:
    """
    Esegue il formatter passando il testo via stdin.
    Ritorna (successo, stdout, stderr).

    Se fornita, register_proc(proc) viene chiamata subito dopo l'avvio del
    processo: permette al chiamante (su un altro thread) di annullare
    l'operazione con proc.terminate().
    """
    exe = cmd[0]
    exe_path = _find_exe(exe)
    if not exe_path:
        return False, "", f"Formatter '{exe}' non trovato nel PATH.\nInstallalo prima di usarlo."
    cmd = [exe_path] + cmd[1:]

    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if register_proc:
            register_proc(proc)
        stdout_b, stderr_b = proc.communicate(input=text.encode("utf-8"), timeout=30)
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        ok = proc.returncode == 0
        return ok, stdout, stderr
    except subprocess.TimeoutExpired:
        if proc is not None:
            proc.kill()
        return False, "", "Timeout: il formatter ha impiegato troppo tempo."
    except Exception as exc:
        return False, "", str(exc)
    finally:
        if register_proc:
            register_proc(None)


# ─── Dialog preferenze ───────────────────────────────────────────────────────

class _PrefsDialog(QDialog):
    """Dialog per configurare i comandi dei formatter."""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferenze Formatter")
        self.resize(580, 400)
        self._settings = dict(settings)
        self._edits: Dict[str, QLineEdit] = {}
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)

        info = QLabel(
            "Personalizza il comando del formatter per ogni linguaggio.\n"
            "Usa il placeholder <b>-</b> per indicare lo stdin. "
            "Lascia vuoto per usare il default."
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        tabs = QTabWidget()

        for lang, cfg in _DEFAULT_FORMATTERS.items():
            if cfg.get("builtin"):
                continue  # JSON/XML sono interni, non configurabili
            w   = QWidget()
            fl  = QFormLayout(w)
            cmd = cfg["cmd"]
            default_str = " ".join(cmd) if cmd else ""
            stored_str  = self._settings.get(f"cmd_{lang}", default_str)
            edit = QLineEdit(stored_str)
            edit.setPlaceholderText(default_str)
            edit.setToolTip(f"Formatter consigliato: {cfg['desc']}")
            fl.addRow("Comando:", edit)

            check_lbl = QLabel()
            exe = (stored_str or default_str).split()[0] if (stored_str or default_str) else ""
            if exe:
                found = _find_exe(exe)
                if found:
                    check_lbl.setText(
                        f'<span style="color:#4ec9b0;">✅ trovato: {found}</span>'
                    )
                else:
                    check_lbl.setText(
                        '<span style="color:#f44747;">❌ non trovato nel PATH</span>'
                    )
            fl.addRow("Stato:", check_lbl)
            fl.addRow("Note:", QLabel(cfg["desc"]))

            self._edits[lang] = edit
            tabs.addTab(w, lang)

        lay.addWidget(tabs)

        self._format_on_save = QCheckBox("Formatta automaticamente al salvataggio")
        self._format_on_save.setChecked(self._settings.get("format_on_save", False))
        lay.addWidget(self._format_on_save)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText(tr("button.ok", default="OK"))
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("button.cancel", default="Cancel"))

    def _on_ok(self):
        for lang, edit in self._edits.items():
            val = edit.text().strip()
            if val:
                self._settings[f"cmd_{lang}"] = val
            else:
                self._settings.pop(f"cmd_{lang}", None)
        self._settings["format_on_save"] = self._format_on_save.isChecked()
        self.accept()

    def result_settings(self) -> dict:
        return self._settings


# ─── Logica principale ────────────────────────────────────────────────────────

class _Formatter:
    """Raccoglie la logica di formattazione, separata dall'UI del plugin."""

    def __init__(self, settings: dict):
        self._settings = settings

    def _get_cmd(self, lang: str) -> Optional[List[str]]:
        cfg = _DEFAULT_FORMATTERS.get(lang)
        if not cfg:
            return None
        stored = self._settings.get(f"cmd_{lang}")
        if stored:
            return stored.split()
        return cfg.get("cmd")

    def format_text(self, text: str, lang: str,
                     register_proc: Optional[callable] = None) -> Tuple[bool, str, str]:
        """
        Formatta `text` per il linguaggio `lang`.
        Ritorna (successo, testo_formattato, messaggio_errore).
        """
        cfg = _DEFAULT_FORMATTERS.get(lang)
        if not cfg:
            return False, text, f"Nessun formatter configurato per '{lang}'."

        # formatter built-in
        if cfg.get("builtin") == "json":
            ok, result = _format_json(text)
            return ok, result if ok else text, result if not ok else ""
        if cfg.get("builtin") == "xml":
            ok, result = _format_xml(text)
            return ok, result if ok else text, result if not ok else ""

        # formatter esterno
        cmd = self._get_cmd(lang)
        if not cmd:
            return False, text, f"Nessun comando configurato per '{lang}'."

        ok, stdout, stderr = _run_formatter(cmd, text, register_proc=register_proc)
        if ok and stdout.strip():
            return True, stdout, ""
        if not ok:
            # prova alternativa (es. ruff se black non c'è)
            alt = cfg.get("alt")
            if alt and not _find_exe(cmd[0]):
                ok2, stdout2, stderr2 = _run_formatter(alt, text, register_proc=register_proc)
                if ok2 and stdout2.strip():
                    return True, stdout2, ""
                return False, text, stderr2 or stderr
            return False, text, stderr or f"Il formatter ha restituito codice di errore."
        # formatter che non scrive stdout (es. clang-format con file temporaneo)
        return True, stdout or text, ""


# ─── Worker per invocazione asincrona del formatter ──────────────────────────

class _FormatWorker(QThread):
    """Esegue _Formatter.format_text() in background (il formatter esterno
    può richiedere fino a 30s, o 60s con fallback su formatter alternativo)."""

    completed = pyqtSignal(bool, str, str, bool)  # ok, formatted, err, cancelled

    def __init__(self, formatter: "_Formatter", text: str, lang: str):
        super().__init__()
        self._formatter = formatter
        self._text = text
        self._lang = lang
        self._proc = None
        self._cancelled = False

    def _register_proc(self, proc) -> None:
        self._proc = proc

    def cancel(self) -> None:
        # Segna "annullato" solo se esiste davvero un subprocess da
        # terminare: i formatter built-in (JSON/XML) non ne avviano mai uno,
        # quindi il risultato va comunque applicato invece di essere
        # scartato come se fosse stato interrotto.
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                self._cancelled = True
            except Exception:
                pass

    def run(self) -> None:
        ok, formatted, err = self._formatter.format_text(
            self._text, self._lang, register_proc=self._register_proc)
        self.completed.emit(ok, formatted, err, self._cancelled)


# ─── Plugin ───────────────────────────────────────────────────────────────────

class CodeFormatterPlugin(BasePlugin):
    NAME        = "Code Formatter"
    VERSION     = "1.0"
    DESCRIPTION = "Formatta il documento corrente con black/prettier/clang-format/rustfmt/gofmt"
    AUTHOR      = "NotePadPQ"

    def on_load(self, main_window: "MainWindow") -> None:
        super().on_load(main_window)
        self._settings = self._load_settings()
        self._formatter = _Formatter(self._settings)
        self._active_worker: Optional[_FormatWorker] = None

        self.add_menu_action(
            main_window, "tools",
            "Format Document",
            self._format_document,
            shortcut="Ctrl+Alt+F",
            icon_key="tool_format_doc",
        )
        self.add_menu_action(
            main_window, "tools",
            "Format Selection",
            self._format_selection,
            shortcut="Ctrl+Alt+Shift+F",
            icon_key="tool_format_sel",
        )
        self.add_menu_action(
            main_window, "tools",
            "Preferenze Formatter…",
            self._open_prefs,
            icon_key="tool_formatter_prefs",
        )

    def on_unload(self) -> None:
        if getattr(self, "_active_worker", None) is not None:
            # cancel() termina il subprocess: _on_done scatterà comunque e
            # rimuoverà il BusyIndicator dalla status bar (altrimenti
            # resterebbe visibile per sempre se disconnessa qui).
            self._active_worker.cancel()
        super().on_unload()

    def on_file_saved(self, path) -> None:
        """Format on save, se abilitato nelle preferenze."""
        if self._settings.get("format_on_save"):
            self._format_document(silent=True)

    # ── Azioni ────────────────────────────────────────────────────────────────

    def _format_document(self, silent: bool = False):
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        lang = self._detect_lang(editor)
        if not lang:
            if not silent:
                QMessageBox.information(
                    self._mw, tr("plugin.code_formatter.title_doc"),
                    tr("plugin.code_formatter.no_lang")
                )
            return
        text = editor.text()
        self._run_format_async(editor, text, lang, selection=False, silent=silent)

    def _format_selection(self):
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        if not editor.hasSelectedText():
            QMessageBox.information(
                self._mw, tr("plugin.code_formatter.title_sel"),
                tr("plugin.code_formatter.no_selection")
            )
            return
        lang = self._detect_lang(editor)
        if not lang:
            QMessageBox.information(
                self._mw, tr("plugin.code_formatter.title_sel"),
                tr("plugin.code_formatter.no_lang")
            )
            return
        text = editor.selectedText()
        self._run_format_async(editor, text, lang, selection=True, silent=False)

    def _run_format_async(self, editor, text: str, lang: str,
                           selection: bool, silent: bool) -> None:
        """Avvia il formatter esterno su un thread dedicato (fino a 30-60s)."""
        if self._active_worker is not None and self._active_worker.isRunning():
            if not silent:
                self._mw.statusBar().showMessage(
                    tr("plugin.code_formatter.busy",
                       default="Formattazione già in corso…"), 3000)
            return

        worker = _FormatWorker(self._formatter, text, lang)

        busy = None if silent else show_busy(
            self._mw.statusBar(),
            tr("plugin.code_formatter.in_progress", default="Formattazione in corso…"),
            cancellable=True, on_cancel=worker.cancel,
        )

        def _on_done(ok: bool, formatted: str, err: str, cancelled: bool) -> None:
            if self._active_worker is worker:
                self._active_worker = None
            hide_busy(self._mw.statusBar(), busy)
            if cancelled:
                self._mw.statusBar().showMessage(
                    tr("plugin.code_formatter.cancelled", default="Formattazione annullata."), 3000)
                return
            self._apply_format_result(editor, text, formatted, ok, err, selection, silent)

        worker.completed.connect(_on_done)
        worker.finished.connect(worker.deleteLater)
        self._active_worker = worker
        worker.start()

    def _apply_format_result(self, editor, original_text: str, formatted: str,
                              ok: bool, err: str, selection: bool, silent: bool) -> None:
        title = tr("plugin.code_formatter.title_sel") if selection else tr("plugin.code_formatter.title_doc")
        try:
            current = editor.selectedText() if selection else editor.text()
        except RuntimeError:
            return  # il tab è stato chiuso mentre il formatter era in esecuzione

        if current != original_text:
            # Il documento è stato modificato mentre il formatter era in corso:
            # applicare il risultato sovrascriverebbe le modifiche dell'utente.
            if not silent:
                QMessageBox.warning(
                    self._mw, title,
                    tr("plugin.code_formatter.changed_during_format",
                       default="Il documento è stato modificato durante la "
                               "formattazione: risultato scartato.")
                )
            return

        if ok:
            if formatted != original_text:
                if selection:
                    editor.replaceSelectedText(formatted)
                else:
                    # sostituisce tutto il testo preservando la posizione del cursore
                    line, _col = editor.getCursorPosition()
                    editor.selectAll()
                    editor.replaceSelectedText(formatted)
                    total_lines = editor.lines()
                    line = min(line, total_lines - 1)
                    editor.setCursorPosition(line, 0)
        else:
            if not silent:
                unchanged_key = "plugin.code_formatter.sel_unchanged" if selection \
                    else "plugin.code_formatter.doc_unchanged"
                QMessageBox.warning(
                    self._mw, title,
                    tr("plugin.code_formatter.error", err=err) + "\n\n" +
                    tr(unchanged_key)
                )

    def _open_prefs(self):
        dlg = _PrefsDialog(self._settings, parent=self._mw)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._settings = dlg.result_settings()
            self._formatter = _Formatter(self._settings)
            self._save_settings()

    # ── Rilevamento linguaggio ────────────────────────────────────────────────

    def _detect_lang(self, editor) -> Optional[str]:
        """Rileva il linguaggio dall'editor e lo mappa alla chiave formatter."""
        # 1. Usa get_language_name() che legge _current_language (più preciso)
        lang_raw = None
        try:
            lang_raw = get_language_name(editor).lower()
        except Exception:
            pass

        # 2. Fallback dall'estensione del file
        if not lang_raw or lang_raw == "text":
            try:
                path = editor.file_path  # attributo Path|None, non metodo
                if path:
                    ext = Path(path).suffix.lower().lstrip(".")
                    _EXT_MAP = {
                        "py": "python", "pyw": "python",
                        "js": "javascript", "mjs": "javascript", "cjs": "javascript",
                        "ts": "typescript", "tsx": "typescript",
                        "css": "css", "scss": "css",
                        "html": "html", "htm": "html",
                        "c": "c", "h": "c",
                        "cpp": "c++", "cxx": "c++", "cc": "c++", "hpp": "c++",
                        "rs": "rust",
                        "go": "go",
                        "json": "json",
                        "xml": "xml", "xsl": "xml", "xsd": "xml",
                    }
                    lang_raw = _EXT_MAP.get(ext)
            except Exception:
                pass

        if not lang_raw:
            return None
        return _LANG_MAP.get(lang_raw)

    # ── Persistenza impostazioni ──────────────────────────────────────────────

    def _settings_path(self) -> Path:
        from core.platform import get_data_dir
        return get_data_dir() / "code_formatter_settings.json"

    def _load_settings(self) -> dict:
        try:
            p = self._settings_path()
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_settings(self):
        try:
            self._settings_path().write_text(
                json.dumps(self._settings, indent=2, ensure_ascii=False)
            )
        except Exception:
            pass

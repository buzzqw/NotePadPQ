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
import shutil
import subprocess
import tempfile
import xml.dom.minidom
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from plugins.base_plugin import BasePlugin
from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


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

def _run_formatter(cmd: List[str], text: str) -> Tuple[bool, str, str]:
    """
    Esegue il formatter passando il testo via stdin.
    Ritorna (successo, stdout, stderr).
    """
    exe = cmd[0]
    if not shutil.which(exe):
        return False, "", f"Formatter '{exe}' non trovato nel PATH.\nInstallalo prima di usarlo."

    try:
        result = subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")
        ok = result.returncode == 0
        return ok, stdout, stderr
    except subprocess.TimeoutExpired:
        return False, "", "Timeout: il formatter ha impiegato troppo tempo."
    except Exception as exc:
        return False, "", str(exc)


# ─── Dialog preferenze ───────────────────────────────────────────────────────

class _PrefsDialog(QDialog):
    """Dialog per configurare i comandi dei formatter."""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙ Preferenze Formatter")
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
                found = shutil.which(exe)
                check_lbl.setText(
                    f'<span style="color:{"#4ec9b0" if found else "#f44747"};">'
                    f'{"✅ trovato" if found else "❌ non trovato nel PATH"}</span>'
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

    def format_text(self, text: str, lang: str) -> Tuple[bool, str, str]:
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

        ok, stdout, stderr = _run_formatter(cmd, text)
        if ok and stdout.strip():
            return True, stdout, ""
        if not ok:
            # prova alternativa (es. ruff se black non c'è)
            alt = cfg.get("alt")
            if alt and not shutil.which(cmd[0]):
                ok2, stdout2, stderr2 = _run_formatter(alt, text)
                if ok2 and stdout2.strip():
                    return True, stdout2, ""
                return False, text, stderr2 or stderr
            return False, text, stderr or f"Il formatter ha restituito codice di errore."
        # formatter che non scrive stdout (es. clang-format con file temporaneo)
        return True, stdout or text, ""


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

        self.add_menu_action(
            main_window, "tools",
            "🎨 Format Document",
            self._format_document,
            shortcut="Ctrl+Alt+F",
        )
        self.add_menu_action(
            main_window, "tools",
            "🎨 Format Selection",
            self._format_selection,
            shortcut="Ctrl+Alt+Shift+F",
        )
        self.add_menu_action(
            main_window, "tools",
            "⚙ Preferenze Formatter…",
            self._open_prefs,
        )

    def on_unload(self) -> None:
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
                    self._mw, "Format Document",
                    "Linguaggio non riconosciuto o nessun formatter disponibile per questo file."
                )
            return

        text = editor.text()
        ok, formatted, err = self._formatter.format_text(text, lang)

        if ok:
            if formatted != text:
                # sostituisce tutto il testo preservando la posizione del cursore
                line, col = editor.getCursorPosition()
                editor.selectAll()
                editor.replaceSelectedText(formatted)
                # riposiziona il cursore (approssimativamente)
                total_lines = editor.lines()
                line = min(line, total_lines - 1)
                editor.setCursorPosition(line, 0)
        else:
            if not silent:
                QMessageBox.warning(
                    self._mw, "Format Document",
                    f"Il formatter ha segnalato un errore:\n\n{err}\n\n"
                    "Il documento non è stato modificato."
                )

    def _format_selection(self):
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        if not editor.hasSelectedText():
            QMessageBox.information(
                self._mw, "Format Selection",
                "Seleziona prima il testo da formattare."
            )
            return
        lang = self._detect_lang(editor)
        if not lang:
            QMessageBox.information(
                self._mw, "Format Selection",
                "Linguaggio non riconosciuto o nessun formatter disponibile per questo file."
            )
            return

        text = editor.selectedText()
        ok, formatted, err = self._formatter.format_text(text, lang)

        if ok:
            if formatted != text:
                editor.replaceSelectedText(formatted)
        else:
            QMessageBox.warning(
                self._mw, "Format Selection",
                f"Il formatter ha segnalato un errore:\n\n{err}\n\n"
                "La selezione non è stata modificata."
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
        # prova tramite il lexer dell'editor
        lang_raw = None
        try:
            lang_raw = editor.language().lower() if hasattr(editor, "language") else None
        except Exception:
            pass

        # prova dall'estensione del file
        if not lang_raw:
            try:
                path = editor.file_path()
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

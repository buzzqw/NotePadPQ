"""
plugins/language_tool_plugin.py - LanguageTool locale per NotePadPQ.

Il plugin usa il server HTTP locale di LanguageTool Standalone. Non viene
attivato automaticamente: l'utente deve selezionare esplicitamente
"Attiva controllo LanguageTool" dal menu Plugin.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from config.settings import Settings
from editor.editor_widget import INDICATOR_LANGUAGETOOL
from plugins.base_plugin import BasePlugin

if TYPE_CHECKING:
    from ui.main_window import MainWindow


_DEFAULT_ENDPOINT = "http://127.0.0.1:8081/v2/check"
_DEFAULT_COMMAND = "languagetool"
_DEFAULT_LANGUAGE = "it"
_CHECK_DELAY_MS = 900
_REQUEST_TIMEOUT = 20
_ORPHANED_WORKERS: set[QThread] = set()
_LATEX_EXTENSIONS = {".tex", ".latex", ".ltx", ".sty", ".cls", ".dtx", ".bib"}
_LATEX_LANGUAGES = {"latex", "tex", "plain tex", "plaintex", "bibtex"}
_LATEX_MATH_ENVIRONMENTS = (
    "equation", "equation*", "align", "align*", "alignat", "alignat*",
    "gather", "gather*", "multline", "multline*", "displaymath", "math",
)
_LATEX_STRUCTURAL_COMMANDS = {
    "begin", "end", "documentclass", "usepackage", "requirepackage",
    "label", "ref", "eqref", "pageref", "cite", "citet", "citep",
    "parencite", "textcite", "autocite", "include", "input", "includeonly",
    "bibliography", "bibliographystyle", "graphicspath", "href", "url", "path",
}
_LATEX_COMMAND_RE = re.compile(r"\\([A-Za-z@]+)(?:\*)?")
_LATEX_MATH_ENV_RE = re.compile(
    r"\\begin\s*\{(?:" + "|".join(re.escape(name) for name in _LATEX_MATH_ENVIRONMENTS)
    + r")\}.*?\\end\s*\{(?:" + "|".join(re.escape(name) for name in _LATEX_MATH_ENVIRONMENTS)
    + r")\}",
    re.IGNORECASE | re.DOTALL,
)


def _absolute_to_line_col(text: str, position: int) -> tuple[int, int]:
    """Converte un offset Python in coordinate line/col di QScintilla."""
    position = max(0, min(position, len(text)))
    line = text.count("\n", 0, position)
    line_start = text.rfind("\n", 0, position) + 1
    return line, position - line_start


def _line_col_to_absolute(text: str, line: int, column: int) -> int:
    """Converte coordinate line/col in un offset Python."""
    if line <= 0:
        return max(0, min(column, len(text)))
    start = 0
    for _ in range(line):
        next_break = text.find("\n", start)
        if next_break < 0:
            return len(text)
        start = next_break + 1
    return max(0, min(start + column, len(text)))


def _parse_matches(payload: object) -> list[dict]:
    """Normalizza la risposta JSON di LanguageTool in diagnostic semplici."""
    if not isinstance(payload, dict):
        return []
    matches = payload.get("matches", [])
    if not isinstance(matches, list):
        return []

    diagnostics: list[dict] = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        try:
            offset = int(match.get("offset", 0))
            length = int(match.get("length", 0))
        except (TypeError, ValueError):
            continue
        if offset < 0 or length <= 0:
            continue
        replacements = []
        raw_replacements = match.get("replacements", [])
        if isinstance(raw_replacements, list):
            for replacement in raw_replacements[:8]:
                if isinstance(replacement, dict) and replacement.get("value") is not None:
                    replacements.append(str(replacement["value"]))
        rule = match.get("rule", {})
        rule_id = rule.get("id", "") if isinstance(rule, dict) else ""
        category = rule.get("category", {}) if isinstance(rule, dict) else {}
        category_id = category.get("id", "") if isinstance(category, dict) else ""
        diagnostics.append({
            "offset": offset,
            "length": length,
            "message": str(match.get("message", "Possibile errore linguistico")),
            "short_message": str(match.get("shortMessage", "")),
            "rule_id": str(rule_id),
            "category": str(category_id),
            "replacements": replacements,
        })
    return diagnostics


def _is_latex_editor(editor) -> bool:
    """Riconosce LaTeX anche prima che il lexer o il percorso siano aggiornati."""
    language = str(getattr(editor, "_current_language", "")).strip().lower()
    if language in _LATEX_LANGUAGES or "latex" in language or language.startswith("tex"):
        return True

    path = getattr(editor, "file_path", None)
    suffix = str(getattr(path, "suffix", "")).lower()
    if suffix in _LATEX_EXTENSIONS:
        return True

    # Protezione per tab senza nome o lexer non ancora aggiornato.
    try:
        sample = editor.text()[:8000]
    except (AttributeError, RuntimeError):
        sample = ""
    latex_markers = re.compile(
        r"\\(?:documentclass|usepackage|begin|end|section|subsection|label|ref|cite)\b"
    )
    return bool(latex_markers.search(sample))


def _is_prose_editor(editor) -> bool:
    """Evita di inviare codice, lasciando passare LaTeX tramite il masking."""
    language = str(getattr(editor, "_current_language", "")).strip().lower()
    if _is_latex_editor(editor):
        return True
    excluded = {
        "python", "javascript", "typescript", "java", "c", "c++", "c/c++",
        "csharp", "c#", "rust", "go", "ruby", "php", "bash", "shell",
        "sql", "json", "yaml", "xml", "html", "css", "makefile", "diff", "binary",
    }
    return language not in excluded


def _mask_latex(text: str) -> tuple[str, list[bool]]:
    """Maschera il markup LaTeX senza cambiare offset o righe della sorgente."""
    chars = list(text)
    visible = [True] * len(text)

    def mask(start: int, end: int) -> None:
        for index in range(max(0, start), min(end, len(chars))):
            if chars[index] != "\n":
                chars[index] = " "
                visible[index] = False

    def matching_group(start: int, opening: str = "{", closing: str = "}") -> int | None:
        if start >= len(text) or text[start] != opening:
            return None
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "\\":
                continue
            if text[index] == opening:
                depth += 1
            elif text[index] == closing:
                depth -= 1
                if depth == 0:
                    return index
        return None

    # Commenti e formule non sono prosa. Le nuove righe restano intatte.
    index = 0
    while index < len(text):
        if text[index] == "%" and (index == 0 or text[index - 1] != "\\"):
            end = text.find("\n", index)
            mask(index, len(text) if end < 0 else end)
            index = len(text) if end < 0 else end
        else:
            index += 1
    for match in _LATEX_MATH_ENV_RE.finditer(text):
        mask(match.start(), match.end())

    for opening, closing in (("\\[", "\\]"), ("\\(", "\\)")):
        index = 0
        while True:
            start = text.find(opening, index)
            if start < 0:
                break
            end = text.find(closing, start + len(opening))
            if end < 0:
                break
            mask(start, end + len(closing))
            index = end + len(closing)

    # Gestisce $...$ e $$...$$, ignorando i dollari escapati.
    index = 0
    while index < len(text):
        if text[index] == "$" and (index == 0 or text[index - 1] != "\\"):
            delimiter = "$$" if text[index:index + 2] == "$$" else "$"
            end = text.find(delimiter, index + len(delimiter))
            if end >= 0:
                mask(index, end + len(delimiter))
                index = end + len(delimiter)
                continue
        index += 1

    for match in _LATEX_COMMAND_RE.finditer(text):
        command = match.group(1).lower()
        mask(match.start(), match.end())
        cursor = match.end()
        while cursor < len(text) and text[cursor] in " \t":
            cursor += 1
        if cursor < len(text) and text[cursor] == "[":
            optional_end = matching_group(cursor, "[", "]")
            if optional_end is not None:
                mask(cursor, optional_end + 1)
                cursor = optional_end + 1
        if cursor < len(text) and text[cursor] == "{":
            group_end = matching_group(cursor)
            if group_end is not None:
                if command in _LATEX_STRUCTURAL_COMMANDS:
                    mask(cursor, group_end + 1)
                else:
                    mask(cursor, cursor + 1)
                    mask(group_end, group_end + 1)

    # Comandi a simbolo (\\%, \\&, \\_, ...) e interruzioni di riga.
    for match in re.finditer(r"\\(?:[^A-Za-z\s]|\\\\)", text):
        mask(match.start(), match.end())

    return "".join(chars), visible


class _LanguageToolWorker(QThread):
    """Invia un testo a LanguageTool senza bloccare il thread Qt principale."""

    completed = pyqtSignal(int, object, str)  # generazione, match, errore

    def __init__(self, generation: int, endpoint: str, language: str, text: str):
        super().__init__()
        self._generation = generation
        self._endpoint = endpoint
        self._language = language
        self._text = text

    def run(self) -> None:
        data = urllib.parse.urlencode({
            "language": self._language,
            "text": self._text,
        }).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint,
            data=data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "User-Agent": "NotePadPQ LanguageTool plugin",
            },
            method="POST",
        )
        last_error = ""
        # Il wrapper Java puo' richiedere alcuni secondi per inizializzare i
        # modelli dopo l'avvio automatico del server.
        for attempt in range(8):
            try:
                with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.completed.emit(self._generation, _parse_matches(payload), "")
                return
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                last_error = str(exc)
                if attempt < 7:
                    self.msleep(min(1500, 500 * (attempt + 1)))
            except Exception as exc:
                last_error = str(exc)
                break
        self.completed.emit(self._generation, [], last_error or "risposta non valida")


def _release_orphan(worker: QThread) -> None:
    """Mantiene vivo un worker oltre la chiusura del plugin, se necessario."""
    _ORPHANED_WORKERS.discard(worker)
    worker.deleteLater()


def _terminate_server_process(process: subprocess.Popen | None) -> None:
    """Termina il server avviato dal plugin, inclusi eventuali processi figli."""
    if process is None or process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=2)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        pass


class _LanguageToolPanel(QWidget):
    """Dock con stato e lista dei suggerimenti dell'editor corrente."""

    diagnostic_activated = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self._status = QLabel("LanguageTool non attivo")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._list = QListWidget()
        self._list.itemActivated.connect(self._on_item_activated)
        layout.addWidget(self._list, 1)
        hint = QLabel("Doppio clic su un risultato per raggiungerlo nel testo.")
        hint.setStyleSheet("color: gray; font-size: 10px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(index, int):
            self.diagnostic_activated.emit(index)

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def set_diagnostics(self, text: str, diagnostics: list[dict]) -> None:
        self._list.clear()
        for index, diagnostic in enumerate(diagnostics):
            line, column = _absolute_to_line_col(
                text, diagnostic.get("absolute_start", diagnostic.get("offset", 0))
            )
            short = diagnostic.get("short_message", "")
            message = diagnostic.get("message", "")
            label = f"{line + 1}:{column + 1} - {short or message}"
            if short and message and short != message:
                label += f" - {message}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, index)
            self._list.addItem(item)

    def clear_diagnostics(self) -> None:
        self._list.clear()


class _SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LanguageTool locale - Impostazioni")
        self.setMinimumWidth(620)
        settings = Settings.instance()
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._endpoint = QLineEdit(settings.get("languagetool/endpoint", _DEFAULT_ENDPOINT))
        self._endpoint.setToolTip("Endpoint HTTP del server LanguageTool, normalmente su localhost.")
        form.addRow("Endpoint:", self._endpoint)

        self._command = QLineEdit(settings.get("languagetool/command", _DEFAULT_COMMAND))
        self._command.setToolTip("Comando per avviare LanguageTool, ad esempio languagetool.")
        form.addRow("Comando:", self._command)

        self._language = QLineEdit(settings.get("languagetool/language", _DEFAULT_LANGUAGE))
        self._language.setPlaceholderText("it, en-US, de-DE oppure auto")
        form.addRow("Lingua:", self._language)

        self._auto_start = QCheckBox("Avvia automaticamente il server se non e' gia' attivo")
        self._auto_start.setChecked(settings.get("languagetool/auto_start", True))
        form.addRow("Server:", self._auto_start)

        self._max_chars = QLineEdit(str(settings.get("languagetool/max_chars", 100000)))
        form.addRow("Limite caratteri:", self._max_chars)
        layout.addLayout(form)

        note = QLabel(
            "Il plugin usa LanguageTool Standalone in locale. Per evitare di inviare "
            "dati fuori dal computer, usare un endpoint 127.0.0.1 o localhost."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        endpoint = self._endpoint.text().strip()
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            QMessageBox.warning(self, "LanguageTool", "Endpoint HTTP non valido.")
            return
        try:
            max_chars = max(1000, min(1_000_000, int(self._max_chars.text().strip())))
        except ValueError:
            QMessageBox.warning(self, "LanguageTool", "Il limite caratteri deve essere numerico.")
            return
        settings = Settings.instance()
        settings.set("languagetool/endpoint", endpoint)
        settings.set("languagetool/command", self._command.text().strip())
        settings.set("languagetool/language", self._language.text().strip() or _DEFAULT_LANGUAGE)
        settings.set("languagetool/auto_start", self._auto_start.isChecked())
        settings.set("languagetool/max_chars", max_chars)
        self.accept()


class LanguageToolPlugin(BasePlugin):
    NAME = "LanguageTool locale"
    VERSION = "1.0"
    DESCRIPTION = "Controllo grammaticale locale con LanguageTool Standalone."
    AUTHOR = "NotePadPQ"

    def on_load(self, main_window: MainWindow) -> None:
        super().on_load(main_window)
        self._current_editor = None
        self._worker: _LanguageToolWorker | None = None
        self._old_workers: list[_LanguageToolWorker] = []
        self._generation = 0
        self._pending_check = False
        self._diagnostics: list[dict] = []
        self._snapshot = ""
        self._prose_mask: list[bool] | None = None
        self._source_base = 0
        self._server_process: subprocess.Popen | None = None

        self._panel = _LanguageToolPanel(main_window)
        self._panel.diagnostic_activated.connect(self._select_diagnostic)
        self._dock = QDockWidget("LanguageTool", main_window)
        self._dock.setObjectName("LanguageToolDock")
        self._dock.setWidget(self._panel)
        self._dock.setMinimumWidth(360)
        self._dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock)
        self._dock.hide()

        # BasePlugin non e' un QObject: il timer deve appartenere alla finestra.
        self._timer = QTimer(main_window)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_CHECK_DELAY_MS)
        self._timer.timeout.connect(self._check_current_editor)

        plugins_menu = main_window._menus.get("plugins")
        if plugins_menu is not None:
            from PyQt6.QtWidgets import QMenu
            submenu = QMenu("LanguageTool locale", plugins_menu)
            self._action_enabled = QAction("Attiva controllo LanguageTool", submenu)
            self._action_enabled.setCheckable(True)
            self._action_enabled.setChecked(Settings.instance().get("languagetool/enabled", False))
            self._action_enabled.triggered.connect(self._toggle_enabled)
            submenu.addAction(self._action_enabled)

            self._action_check = QAction("Controlla documento corrente", submenu)
            self._action_check.triggered.connect(self._manual_check)
            submenu.addAction(self._action_check)

            self._action_settings = QAction("Impostazioni...", submenu)
            self._action_settings.triggered.connect(self._open_settings)
            submenu.addAction(self._action_settings)

            self._submenu_action = plugins_menu.addMenu(submenu)
            self._menu_actions.append(self._submenu_action)

        main_window._tab_manager.current_editor_changed.connect(self._on_editor_changed)
        self._on_editor_changed(main_window._tab_manager.current_editor())
        if self._action_enabled.isChecked():
            self._schedule_check()

    def on_unload(self) -> None:
        self._timer.stop()
        self._pending_check = False
        if self._current_editor is not None:
            self._disconnect_editor(self._current_editor)
        workers = [worker for worker in [self._worker, *self._old_workers] if worker is not None]
        self._worker = None
        self._old_workers.clear()
        for worker in workers:
            if worker is not None:
                try:
                    worker.requestInterruption()
                    worker.completed.disconnect(self._on_check_completed)
                except (RuntimeError, TypeError):
                    pass
        for worker in workers:
            if worker.isRunning() and not worker.wait(2000):
                _ORPHANED_WORKERS.add(worker)
                worker.finished.connect(lambda w=worker: _release_orphan(w))
            else:
                worker.deleteLater()
        _terminate_server_process(self._server_process)
        self._server_process = None
        if hasattr(self, "_dock"):
            self._dock.deleteLater()
        super().on_unload()

    def on_editor_changed(self, editor) -> None:
        self._on_editor_changed(editor)

    def _disconnect_editor(self, editor) -> None:
        try:
            editor.textChanged.disconnect(self._on_editor_text_changed)
            editor.context_menu_requested.disconnect(self._inject_context_menu)
        except (RuntimeError, TypeError):
            pass
        if hasattr(editor, "language_changed"):
            try:
                editor.language_changed.disconnect(self._on_editor_language_changed)
            except (RuntimeError, TypeError):
                pass
        try:
            editor.clearIndicatorRange(0, 0, editor.lines(), 0, INDICATOR_LANGUAGETOOL)
        except (RuntimeError, TypeError):
            pass

    def _on_editor_changed(self, editor) -> None:
        if self._current_editor is editor:
            return
        self._generation += 1
        if self._current_editor is not None:
            self._disconnect_editor(self._current_editor)
        self._current_editor = editor
        self._diagnostics = []
        self._snapshot = ""
        self._prose_mask = None
        self._panel.clear_diagnostics()
        if editor is None:
            self._panel.set_status("Nessun documento aperto")
            return
        editor.textChanged.connect(self._on_editor_text_changed)
        editor.context_menu_requested.connect(self._inject_context_menu)
        if hasattr(editor, "language_changed"):
            editor.language_changed.connect(self._on_editor_language_changed)
        if self._action_enabled.isChecked():
            self._schedule_check()

    def _on_editor_text_changed(self) -> None:
        if self._action_enabled.isChecked():
            self._schedule_check()

    def _on_editor_language_changed(self, _language: str) -> None:
        """Rivaluta subito il tab quando cambia lexer o tipo documento."""
        if self._action_enabled.isChecked():
            self._schedule_check()

    def _schedule_check(self) -> None:
        self._generation += 1
        self._timer.start()

    def _toggle_enabled(self, enabled: bool) -> None:
        Settings.instance().set("languagetool/enabled", enabled)
        if not enabled:
            self._generation += 1
            self._timer.stop()
            self._diagnostics = []
            self._snapshot = ""
            self._clear_indicator()
            self._panel.clear_diagnostics()
            self._panel.set_status("LanguageTool disattivato")
            self._dock.hide()
            return
        self._dock.show()
        self._panel.set_status("LanguageTool attivo; controllo in preparazione...")
        self._schedule_check()

    def _manual_check(self) -> None:
        if not self._action_enabled.isChecked():
            self._action_enabled.setChecked(True)
            self._toggle_enabled(True)
        else:
            self._dock.show()
            self._schedule_check()

    def _open_settings(self) -> None:
        if _SettingsDialog(self._mw).exec() == QDialog.DialogCode.Accepted:
            if self._action_enabled.isChecked():
                self._schedule_check()

    def _endpoint(self) -> str:
        return str(Settings.instance().get("languagetool/endpoint", _DEFAULT_ENDPOINT)).strip()

    def _start_server_if_needed(self) -> None:
        if not Settings.instance().get("languagetool/auto_start", True):
            return
        if self._server_process is not None and self._server_process.poll() is None:
            return
        parsed = urllib.parse.urlparse(self._endpoint())
        host = (parsed.hostname or "").lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return
        command = str(Settings.instance().get("languagetool/command", _DEFAULT_COMMAND)).strip()
        if not command:
            return
        try:
            args = shlex.split(command, posix=(os.name != "nt"))
        except ValueError:
            return
        if not args:
            return
        executable = shutil.which(args[0]) or args[0]
        port = parsed.port or 8081
        command_text = " ".join(args).lower()
        if "--http" not in command_text and "httpserver" not in command_text:
            args.append("--http")
        if "--port" not in command_text:
            args.extend(["--port", str(port)])
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self._server_process = subprocess.Popen(
                [executable, *args[1:]],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                start_new_session=(os.name != "nt"),
            )
        except (OSError, ValueError):
            self._server_process = None

    def _check_current_editor(self) -> None:
        if not self._action_enabled.isChecked() or self._current_editor is None:
            return
        if self._worker is not None and self._worker.isRunning():
            self._pending_check = True
            return
        editor = self._current_editor
        if getattr(editor, "_paged_doc", None) is not None:
            self._panel.set_status("LanguageTool non disponibile per file in modalita paginata")
            self._clear_indicator()
            self._panel.clear_diagnostics()
            return
        if not _is_prose_editor(editor):
            self._panel.set_status("Controllo LanguageTool saltato: documento non di prosa")
            self._clear_indicator()
            self._panel.clear_diagnostics()
            return
        text = editor.text()
        request_text = text
        self._prose_mask = None
        if _is_latex_editor(editor):
            request_text, self._prose_mask = _mask_latex(text)
            if not request_text.strip():
                self._panel.set_status("Nessuna prosa da controllare nel documento LaTeX")
                self._clear_indicator()
                self._panel.clear_diagnostics()
                return
        max_chars = int(Settings.instance().get("languagetool/max_chars", 100000))
        if len(text) > max_chars:
            self._panel.set_status(f"Documento troppo grande per LanguageTool ({len(text):,} > {max_chars:,} caratteri)")
            self._clear_indicator()
            self._panel.clear_diagnostics()
            return
        if not text.strip():
            self._panel.set_status("Documento vuoto")
            self._clear_indicator()
            self._panel.clear_diagnostics()
            return

        self._start_server_if_needed()
        self._generation += 1
        generation = self._generation
        self._snapshot = text
        self._source_base = 0
        language = str(Settings.instance().get("languagetool/language", _DEFAULT_LANGUAGE)).strip() or _DEFAULT_LANGUAGE
        endpoint = self._endpoint()
        self._panel.set_status("LanguageTool sta controllando il documento...")
        worker = _LanguageToolWorker(generation, endpoint, language, request_text)
        worker.completed.connect(self._on_check_completed)
        worker.finished.connect(lambda w=worker: self._worker_finished(w))
        self._worker = worker
        worker.start()

    def _worker_finished(self, worker: _LanguageToolWorker) -> None:
        if worker in self._old_workers:
            self._old_workers.remove(worker)
        if self._worker is worker:
            self._worker = None
        worker.deleteLater()
        if self._pending_check:
            self._pending_check = False
            self._timer.start(100)

    def _on_check_completed(self, generation: int, diagnostics: list[dict], error: str) -> None:
        if generation != self._generation or self._current_editor is None:
            return
        if error:
            self._panel.set_status(
                "LanguageTool non raggiungibile. Avvia il server o controlla le impostazioni."
            )
            self._clear_indicator()
            self._panel.clear_diagnostics()
            return
        for diagnostic in diagnostics:
            diagnostic["absolute_start"] = self._source_base + diagnostic["offset"]
            diagnostic["absolute_end"] = diagnostic["absolute_start"] + diagnostic["length"]
        if self._prose_mask is not None:
            diagnostics = [
                diagnostic for diagnostic in diagnostics
                if 0 <= diagnostic["offset"]
                and diagnostic["offset"] + diagnostic["length"] <= len(self._prose_mask)
                and all(self._prose_mask[diagnostic["offset"]:diagnostic["offset"] + diagnostic["length"]])
            ]
        self._diagnostics = diagnostics
        count = len(diagnostics)
        self._panel.set_status("Nessun problema rilevato" if not count else f"{count} suggerimenti LanguageTool")
        self._panel.set_diagnostics(self._snapshot, diagnostics)
        self._render_indicators()

    def _clear_indicator(self) -> None:
        editor = self._current_editor
        if editor is None:
            return
        try:
            editor.clearIndicatorRange(0, 0, editor.lines(), 0, INDICATOR_LANGUAGETOOL)
        except (RuntimeError, TypeError):
            pass

    def _render_indicators(self) -> None:
        editor = self._current_editor
        if editor is None:
            return
        self._clear_indicator()
        for diagnostic in self._diagnostics:
            start = diagnostic.get("absolute_start", -1)
            end = diagnostic.get("absolute_end", -1)
            if start < 0 or end <= start:
                continue
            line_s, col_s = _absolute_to_line_col(self._snapshot, start)
            line_e, col_e = _absolute_to_line_col(self._snapshot, end)
            try:
                editor.fillIndicatorRange(
                    line_s, col_s, line_e, col_e, INDICATOR_LANGUAGETOOL
                )
            except (RuntimeError, TypeError):
                pass

    def _select_diagnostic(self, index: int) -> None:
        if index < 0 or index >= len(self._diagnostics):
            return
        diagnostic = self._diagnostics[index]
        editor = self._current_editor
        if editor is None or editor.text() != self._snapshot:
            return
        start = diagnostic["absolute_start"]
        end = diagnostic["absolute_end"]
        line_s, col_s = _absolute_to_line_col(self._snapshot, start)
        line_e, col_e = _absolute_to_line_col(self._snapshot, end)
        editor.setSelection(line_s, col_s, line_e, col_e)
        editor.setFocus()

    def _replace_diagnostic(self, index: int, replacement: str) -> None:
        if index < 0 or index >= len(self._diagnostics):
            return
        editor = self._current_editor
        if editor is None or editor.text() != self._snapshot:
            self._panel.set_status("Il documento e' cambiato: controllo nuovamente il testo.")
            return
        diagnostic = self._diagnostics[index]
        line_s, col_s = _absolute_to_line_col(self._snapshot, diagnostic["absolute_start"])
        line_e, col_e = _absolute_to_line_col(self._snapshot, diagnostic["absolute_end"])
        editor.beginUndoAction()
        try:
            editor.setSelection(line_s, col_s, line_e, col_e)
            editor.replaceSelectedText(replacement)
        finally:
            editor.endUndoAction()

    def _inject_context_menu(self, menu) -> None:
        if not self._action_enabled.isChecked() or self._current_editor is None:
            return
        editor = self._current_editor
        if editor.text() != self._snapshot:
            return
        line, column = editor.getCursorPosition()
        cursor_abs = _line_col_to_absolute(editor.text(), line, column)
        index = next(
            (
                i for i, diagnostic in enumerate(self._diagnostics)
                if diagnostic["absolute_start"] <= cursor_abs < diagnostic["absolute_end"]
            ),
            None,
        )
        if index is None:
            return
        diagnostic = self._diagnostics[index]
        submenu = menu.addMenu("LanguageTool")
        explain = submenu.addAction(diagnostic.get("message", "Possibile errore linguistico"))
        explain.setEnabled(False)
        replacements = diagnostic.get("replacements", [])
        if replacements:
            submenu.addSeparator()
            for replacement in replacements:
                action = submenu.addAction(f"Sostituisci con: {replacement}")
                action.triggered.connect(
                    lambda _checked=False, i=index, value=replacement:
                    self._replace_diagnostic(i, value)
                )
        go = submenu.addAction("Seleziona nel documento")
        go.triggered.connect(lambda _checked=False, i=index: self._select_diagnostic(i))

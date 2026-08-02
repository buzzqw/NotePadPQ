"""
ui/build_panel.py — Pannello output compilazione
NotePadPQ

Panel con output del build, lista errori cliccabili,
dialog configurazione profili con env/hook/pipeline,
unified errors (LSP + build), pipeline progress.

Nuove feature:
- Variabili d'ambiente per profilo (campo env)
- Hook pre/post build per profilo
- Pipeline multi-step configurabili
- Error regex capture group configurabili da UI
- Build interattive con input inline
- Output limit configurabile
- Unified errors (LSP + build)
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSlot, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QAction, QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QTreeWidget, QTreeWidgetItem, QToolBar,
    QLabel, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QLineEdit, QPushButton, QSplitter,
    QGroupBox, QListWidget, QListWidgetItem, QMessageBox,
    QStatusBar, QFrame, QTextEdit, QSpinBox, QTabWidget,
    QProgressBar, QCheckBox, QScrollArea, QSizePolicy,
    QInputDialog,
)
from PyQt6.QtCore import Qt as QtCoreQt

from i18n.i18n import tr
from core.build_manager import BuildManager, DEFAULT_PROFILES

if TYPE_CHECKING:
    from ui.main_window import MainWindow
    from editor.editor_widget import EditorWidget


class _AIAnalyzeDialog(QDialog):
    _ollama_ready    = pyqtSignal(object)
    _anthropic_ready = pyqtSignal(object)
    _MAX_PREVIEW     = 3000

    def __init__(self, log_text: str, providers: dict, parent=None):
        super().__init__(parent)
        self._log_text  = log_text
        self._providers = providers
        self._ollama_ready.connect(self._set_ollama_models)
        self._anthropic_ready.connect(self._set_anthropic_models)
        self.setWindowTitle(tr("action.build_analyze_ai"))
        self.setMinimumWidth(560)
        self.setMinimumHeight(460)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 8)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("label.ai_provider")))
        self._provider_combo = QComboBox()
        self._provider_combo.addItems(list(self._providers.keys()))
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        row.addWidget(self._provider_combo, 1)

        row.addWidget(QLabel(tr("label.ai_model")))
        self._model_combo = QComboBox()
        self._model_combo.setMinimumWidth(160)
        row.addWidget(self._model_combo, 1)

        self._btn_refresh = QPushButton("\u21bb")
        self._btn_refresh.setFixedWidth(28)
        self._btn_refresh.setToolTip(tr("tooltip.build_reload_tasks"))
        self._btn_refresh.clicked.connect(self._manual_refresh)
        row.addWidget(self._btn_refresh)
        root.addLayout(row)

        root.addWidget(QLabel(tr("label.ai_instruction")))
        self._instruction = QLineEdit()
        self._instruction.setText(tr("msg.build_ai_default_prompt"))
        root.addWidget(self._instruction)

        root.addWidget(QLabel(tr("label.build_log_preview")))
        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setFont(QFont("Monospace", 9))
        self._preview.setStyleSheet(
            "background:#1e1e1e; color:#d4d4d4; border:1px solid #3c3c3c;"
        )
        preview_text = self._log_text[-self._MAX_PREVIEW:]
        self._preview.setPlainText(preview_text)
        root.addWidget(self._preview)
        if len(self._log_text) > self._MAX_PREVIEW:
            note = QLabel(tr("msg.build_log_truncated"))
            note.setStyleSheet("color: gray; font-size: 11px;")
            root.addWidget(note)

        bbox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bbox.button(QDialogButtonBox.StandardButton.Ok).setText(
            tr("action.build_analyze_ai_send")
        )
        bbox.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("button.cancel", default="Cancel"))
        bbox.accepted.connect(self.accept)
        bbox.rejected.connect(self.reject)
        root.addWidget(bbox)

        from config.settings import Settings
        s = Settings.instance()
        last_p = s.get("build/ai_provider", "")
        last_m = s.get("build/ai_model",    "")
        if last_p:
            idx = self._provider_combo.findText(last_p)
            if idx >= 0:
                self._provider_combo.setCurrentIndex(idx)
                if last_m:
                    self._model_combo.setCurrentText(last_m)
                return
        self._on_provider_changed()
        if last_m:
            self._model_combo.setCurrentText(last_m)

    def _on_provider_changed(self) -> None:
        name = self._provider_combo.currentText()
        info = self._providers.get(name, {})
        pid  = info.get("id", "")

        self._model_combo.clear()
        self._model_combo.addItems(info.get("models", []))
        default = info.get("default", "")
        if default:
            self._model_combo.setCurrentText(default)

        self._btn_refresh.setVisible(pid in ("ollama", "anthropic"))

        if pid == "ollama":
            self._refresh_ollama()
        elif pid == "anthropic":
            self._refresh_anthropic()

    def _manual_refresh(self) -> None:
        pid = self._providers.get(self._provider_combo.currentText(), {}).get("id", "")
        if pid == "ollama":
            self._refresh_ollama()
        elif pid == "anthropic":
            self._refresh_anthropic()

    def _refresh_ollama(self) -> None:
        import threading, urllib.request, json as _json
        from config.settings import Settings
        url_base = Settings.instance().get("ai/ollama_key", "") or "http://localhost:11434"
        self._model_combo.setEnabled(False)

        def _fetch():
            try:
                req = urllib.request.Request(
                    f"{url_base.rstrip('/')}/api/tags", method="GET"
                )
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = _json.loads(resp.read())
                models = [m["name"] for m in data.get("models", [])]
                self._ollama_ready.emit(models or [])
            except Exception:
                self._ollama_ready.emit(None)

        threading.Thread(target=_fetch, daemon=True).start()

    def _set_ollama_models(self, models) -> None:
        if self._providers.get(self._provider_combo.currentText(), {}).get("id") != "ollama":
            return
        self._model_combo.clear()
        if models is None:
            self._model_combo.addItem(tr("msg.ollama_unreachable", default="\u26a0 ollama non raggiungibile"))
            self._model_combo.setEnabled(False)
            return
        self._model_combo.setEnabled(True)
        for m in models:
            self._model_combo.addItem(m)

    def _refresh_anthropic(self) -> None:
        import threading, urllib.request, json as _json
        from config.settings import Settings
        api_key = Settings.instance().get("ai/anthropic_key", "").strip()
        if not api_key:
            return
        self._btn_refresh.setEnabled(False)
        self._btn_refresh.setText("\u2026")

        def _fetch():
            try:
                req = urllib.request.Request(
                    "https://api.anthropic.com/v1/models",
                    method="GET",
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = _json.loads(resp.read())
                model_ids = [
                    m["id"] for m in data.get("data", [])
                    if m.get("id", "").startswith("claude-")
                ]
                static  = self._providers["Anthropic (Claude)"]["models"]
                known   = [m for m in static   if m in model_ids]
                extra   = [m for m in model_ids if m not in static]
                self._anthropic_ready.emit((known + extra) or None)
            except Exception:
                self._anthropic_ready.emit(None)

        threading.Thread(target=_fetch, daemon=True).start()

    def _set_anthropic_models(self, models) -> None:
        self._btn_refresh.setEnabled(True)
        self._btn_refresh.setText("\u21bb")
        if self._providers.get(self._provider_combo.currentText(), {}).get("id") != "anthropic":
            return
        if not models:
            return
        current = self._model_combo.currentText()
        self._model_combo.clear()
        for m in models:
            self._model_combo.addItem(m)
        idx = self._model_combo.findText(current)
        self._model_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def selected_provider(self) -> str:
        return self._provider_combo.currentText()

    def selected_model(self) -> str:
        return self._model_combo.currentText()

    def prompt(self) -> str:
        instruction = self._instruction.text().strip()
        log = self._log_text
        if len(log) > 12000:
            log = "...[log troncato, parte finale]\n" + log[-12000:]
        return f"{instruction}\n\n---LOG---\n{log}\n---"

    def accept(self) -> None:
        from config.settings import Settings
        s = Settings.instance()
        s.set("build/ai_provider", self.selected_provider())
        s.set("build/ai_model",    self.selected_model())
        super().accept()


class BuildPanel(QWidget):
    error_count_changed = pyqtSignal(int)

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self._mw = main_window
        self._bm = BuildManager.instance()
        self._current_profile: str = ""
        self._current_run_id: str = ""
        self._current_error_idx: int = -1
        self._full_log: list[str] = []
        self._running_workers: dict[str, bool] = {}

        self._build_ui()
        self._connect_signals()
        QTimer.singleShot(0, self._sync_profile_to_editor)

    def _build_ui(self) -> None:
        self.setMinimumHeight(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tb = QToolBar()
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toolbar = tb

        self._lbl_profile = QLabel()
        self._lbl_profile.setStyleSheet(
            "font-weight: bold; padding: 2px 6px; "
            "background: #264f78; color: #9cdcfe; border-radius: 3px;"
        )
        self._lbl_profile.setToolTip(tr("tooltip.build_profile_label"))

        self._profile_combo = QComboBox()
        self._profile_combo.setToolTip(tr("tooltip.build_profile_combo"))
        self._profile_combo.addItem(tr("build_panel.auto_profile"), userData=None)
        for name in self._bm.get_profiles():
            self._profile_combo.addItem(name, userData=name)
        self._profile_combo.currentIndexChanged.connect(self._on_combo_changed)

        tb.addWidget(QLabel(tr("build_panel.profile_label")))
        tb.addWidget(self._lbl_profile)
        tb.addWidget(QLabel(tr("build_panel.override_label")))
        tb.addWidget(self._profile_combo)
        tb.addSeparator()

        self._btn_compile = QPushButton(tr("action.compile", default="Compila"))
        self._btn_run     = QPushButton(tr("action.run",     default="Esegui"))
        self._btn_build   = QPushButton(tr("action.build",   default="Build"))
        self._btn_stop    = QPushButton(tr("action.stop_build", default="Stop"))
        self._btn_clear   = QPushButton(tr("button.clear",   default="Pulisci"))

        self._btn_stop.setEnabled(False)
        self._btn_stop.setStyleSheet("color: #f44747;")

        for btn in [self._btn_compile, self._btn_run,
                    self._btn_build, self._btn_stop, self._btn_clear]:
            tb.addWidget(btn)

        tb.setIconSize(QSize(16, 16))
        self._btn_prev_error = QAction("\u25b2", self)
        self._btn_next_error = QAction("\u25bc", self)
        self._btn_prev_error.setToolTip(tr("tooltip.build_prev_error"))
        self._btn_next_error.setToolTip(tr("tooltip.build_next_error"))
        self._btn_prev_error.setEnabled(False)
        self._btn_next_error.setEnabled(False)

        self._btn_analyze_ai = QAction(tr("action.build_analyze_ai"), self)
        self._btn_analyze_ai.setToolTip(tr("tooltip.build_analyze_ai"))
        self._btn_analyze_ai.setEnabled(False)
        self._set_analyze_ai_icon()

        self._btn_interactive = QAction("PTY", self)
        self._btn_interactive.setToolTip(tr("tooltip.build_interactive"))
        self._btn_interactive.setCheckable(True)

        tb.addAction(self._btn_prev_error)
        tb.addAction(self._btn_next_error)
        tb.addAction(self._btn_analyze_ai)
        tb.addAction(self._btn_interactive)

        layout.addWidget(tb)

        self._pipeline_bar = QProgressBar()
        self._pipeline_bar.setMaximumHeight(16)
        self._pipeline_bar.setVisible(False)
        self._pipeline_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #3c3c3c; background: #1e1e1e; text-align: center; }
            QProgressBar::chunk { background: #264f78; }
        """)
        layout.addWidget(self._pipeline_bar)

        self._output = QPlainTextEdit()
        self._output.setMinimumHeight(0)
        self._output.setReadOnly(True)
        self._output.setFont(QFont("Monospace", 10))
        self._output.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: none;
                selection-background-color: #264f78;
            }
        """)
        layout.addWidget(self._output, 1)

        self._input_row = QHBoxLayout()
        self._input_row.setContentsMargins(4, 2, 4, 4)
        self._input_edit = QLineEdit()
        self._input_edit.setPlaceholderText(tr("build_panel.task_input_placeholder", default="Scrivi input per il processo..."))
        self._input_edit.setStyleSheet("background:#1e1e1e; color:#d4d4d4; border:1px solid #3c3c3c; padding:2px 4px;")
        self._input_edit.returnPressed.connect(self._send_input)
        self._input_send_btn = QPushButton(tr("button.send", default="Invia"))
        self._input_send_btn.clicked.connect(self._send_input)
        self._input_row.addWidget(self._input_edit, 1)
        self._input_row.addWidget(self._input_send_btn)
        input_container = QWidget()
        input_container.setLayout(self._input_row)
        input_container.setVisible(False)
        self._input_container = input_container
        layout.addWidget(input_container)

        self._status_bar = QLabel()
        self._status_bar.setStyleSheet(
            "padding: 2px 8px; font-size: 11px; "
            "background: #252526; color: #858585; border-top: 1px solid #3c3c3c;"
        )
        self._status_bar.setText(tr("msg.ready", default="Pronto."))
        layout.addWidget(self._status_bar)

        self._error_tree = QTreeWidget()
        self._error_tree.setMinimumHeight(0)
        self._error_tree.setStyleSheet("""
            QTreeWidget {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: none;
                alternate-background-color: #252526;
                selection-background-color: #264f78;
            }
            QHeaderView::section {
                background-color: #2d2d2d;
                color: #cccccc;
                border: 1px solid #3c3c3c;
                padding: 3px;
            }
        """)
        self._error_tree.setAlternatingRowColors(True)
        self._error_tree.setHeaderLabels([
            tr("label.file", default="File"),
            tr("label.line", default="Riga"),
            tr("label.message", default="Messaggio"),
            tr("label.source", default="Origine"),
        ])
        self._error_tree.setColumnWidth(0, 200)
        self._error_tree.setColumnWidth(1, 50)
        self._error_tree.setColumnWidth(2, 250)
        self._error_tree.setColumnWidth(3, 60)
        self._error_tree.itemDoubleClicked.connect(self._on_error_clicked)

        self._task_widget = _TaskTab(self._mw)
        QTimer.singleShot(0, self._refresh_button_labels)

    def _connect_signals(self) -> None:
        bm = self._bm
        bm.build_started.connect(self._on_build_started)
        bm.build_output.connect(self._append_output)
        bm.build_done.connect(self._on_build_done)
        bm.build_errors.connect(self._show_errors)
        bm.pipeline_step.connect(self._on_pipeline_step)

        self._btn_compile.clicked.connect(lambda: self._run_action("compile"))
        self._btn_run.clicked.connect(    lambda: self._run_action("run"))
        self._btn_build.clicked.connect(  lambda: self._run_action("build"))
        self._btn_stop.clicked.connect(self._stop_current)
        self._btn_clear.clicked.connect(self._clear_output)
        self._btn_analyze_ai.triggered.connect(self._analyze_with_ai)
        self._btn_next_error.triggered.connect(self.goto_next_error)
        self._btn_prev_error.triggered.connect(self.goto_prev_error)

        try:
            self._mw._tab_manager.current_editor_changed.connect(
                self._sync_profile_to_editor
            )
        except Exception:
            pass

    def _refresh_button_labels(self) -> None:
        actions = getattr(self._mw, "_actions", {})
        mapping = {
            self._btn_compile: ("compile", tr("action.compile", default="Compila")),
            self._btn_run:     ("run",     tr("action.run",     default="Esegui")),
            self._btn_build:   ("build",   tr("action.build",   default="Build")),
        }
        for btn, (key, label) in mapping.items():
            action = actions.get(key)
            if action:
                sc = action.shortcut().toString()
                btn.setText(f"{label}  {sc}" if sc else label)
            else:
                btn.setText(label)

        tip_mapping = {
            self._btn_next_error: ("build_next_error", tr("tooltip.build_next_error")),
            self._btn_prev_error: ("build_prev_error", tr("tooltip.build_prev_error")),
        }
        for btn, (key, tip) in tip_mapping.items():
            action = actions.get(key)
            sc = action.shortcut().toString() if action else ""
            btn.setToolTip(f"{tip}  ({sc})" if sc else tip)

    def _set_analyze_ai_icon(self) -> None:
        from pathlib import Path
        from PyQt6.QtGui import QPalette, QPixmap, QIcon
        icons_dir = Path(__file__).parent.parent / "icons" / "lucide"
        icon_path = icons_dir / "sparkles.svg"
        if not icon_path.exists():
            return
        color = self.palette().color(QPalette.ColorRole.WindowText).name()
        try:
            svg_data = icon_path.read_bytes().replace(b"currentColor", color.encode())
            pm = QPixmap()
            if pm.loadFromData(svg_data, "SVG") and not pm.isNull():
                self._btn_analyze_ai.setIcon(QIcon(pm))
        except Exception:
            pass

    def _sync_profile_to_editor(self) -> None:
        editor = self._mw._tab_manager.current_editor()
        if editor is None:
            self._profile_combo.blockSignals(True)
            self._profile_combo.setCurrentIndex(0)
            self._profile_combo.blockSignals(False)
            self._set_active_profile("")
            return

        path = getattr(editor, "file_path", None) or getattr(editor, "_file_path", None)
        if path is None:
            self._profile_combo.blockSignals(True)
            self._profile_combo.setCurrentIndex(0)
            self._profile_combo.blockSignals(False)
            self._set_active_profile("")
            return

        ext = path.suffix.lower()
        override = self._bm._profile_overrides.get(ext, "")

        if override and override in self._bm.get_profiles():
            idx = self._profile_combo.findData(override)
            self._profile_combo.blockSignals(True)
            self._profile_combo.setCurrentIndex(idx if idx > 0 else 0)
            self._profile_combo.blockSignals(False)
            self._set_active_profile(override)
        else:
            self._profile_combo.blockSignals(True)
            self._profile_combo.setCurrentIndex(0)
            self._profile_combo.blockSignals(False)
            name = self._bm.get_profile_for_file(path)
            self._set_active_profile(name or "")

    def _on_combo_changed(self, index: int) -> None:
        editor = self._mw._tab_manager.current_editor() if hasattr(self._mw, "_tab_manager") else None
        path = getattr(editor, "file_path", None) if editor else None
        ext = path.suffix.lower() if path else ""

        if index == 0:
            if ext:
                self._bm.clear_profile_override(ext)
            self._sync_profile_to_editor()
        else:
            name = self._profile_combo.itemData(index) or ""
            if name:
                if ext:
                    self._bm.set_profile_override(ext, name)
                self._set_active_profile(name)

    def _set_active_profile(self, name: str) -> None:
        self._current_profile = name

        if name:
            self._lbl_profile.setText(f"  {name}  ")
            self._lbl_profile.setStyleSheet(
                "font-weight: bold; padding: 2px 8px; "
                "background: #264f78; color: #9cdcfe; border-radius: 3px;"
            )
        else:
            self._lbl_profile.setText(tr("build_panel.no_profile"))
            self._lbl_profile.setStyleSheet(
                "font-weight: bold; padding: 2px 8px; "
                "background: #3c3c3c; color: #858585; border-radius: 3px;"
            )

        self._update_button_states(name)

    def _update_button_states(self, profile_name: str) -> None:
        profile = self._bm.get_profiles().get(profile_name, {})

        compile_cmd = profile.get("compile", "")
        run_cmd     = profile.get("run",     "")
        build_cmd   = profile.get("build",   "")
        has_pipeline = bool(profile.get("pipeline"))

        self._btn_compile.setEnabled(bool(compile_cmd) or has_pipeline)
        self._btn_run.setEnabled(    bool(run_cmd)     or has_pipeline)
        self._btn_build.setEnabled(  bool(build_cmd)   or has_pipeline)

        self._btn_compile.setToolTip(compile_cmd or "(pipeline)")
        self._btn_run.setToolTip(    run_cmd     or "(pipeline)")
        self._btn_build.setToolTip(  build_cmd   or "(pipeline)")

        if not profile_name:
            for btn in [self._btn_compile, self._btn_run, self._btn_build]:
                btn.setEnabled(False)
                btn.setToolTip(tr("tooltip.build_no_file"))

    def _run_action(self, action: str) -> None:
        editor = self._mw._tab_manager.current_editor()
        if editor is None:
            return

        interactive = self._btn_interactive.isChecked()
        from uuid import uuid4
        self._current_run_id = f"build_{uuid4().hex[:8]}"
        self._bm.run(action, editor, run_id=self._current_run_id, interactive=interactive)

    def _stop_current(self) -> None:
        self._bm.stop(self._current_run_id)

    def _send_input(self) -> None:
        text = self._input_edit.text()
        if text:
            self._bm.send_input(self._current_run_id, text + "\n")
            self._input_edit.clear()

    @pyqtSlot(str, str)
    def _on_build_started(self, run_id: str, action: str) -> None:
        if run_id != self._current_run_id:
            return
        self._output.clear()
        self._full_log.clear()
        self._error_tree.clear()
        self._current_error_idx = -1
        self._btn_next_error.setEnabled(False)
        self._btn_prev_error.setEnabled(False)
        self.error_count_changed.emit(0)
        self._btn_analyze_ai.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._btn_compile.setEnabled(False)
        self._btn_run.setEnabled(False)
        self._btn_build.setEnabled(False)
        self._running_workers[run_id] = True
        self._input_container.setVisible(self._btn_interactive.isChecked())
        self._status_bar.setText(
            tr("build_panel.in_progress", action=action.capitalize(), profile=self._current_profile)
        )
        self._status_bar.setStyleSheet(
            "padding: 2px 8px; font-size: 11px; "
            "background: #1e3a1e; color: #4caf50; border-top: 1px solid #3c3c3c;"
        )

    @pyqtSlot(str, int, int, str)
    def _on_pipeline_step(self, run_id: str, step: int, total: int, name: str) -> None:
        if run_id != self._current_run_id:
            return
        self._pipeline_bar.setVisible(True)
        self._pipeline_bar.setMaximum(total)
        self._pipeline_bar.setValue(step)
        self._pipeline_bar.setFormat(f"Pipeline: {step}/{total} — {name}")

    @pyqtSlot(str, str)
    def _append_output(self, run_id: str, line: str) -> None:
        if run_id != self._current_run_id:
            return
        max_lines = self._bm.get_output_limit()
        if max_lines > 0 and len(self._full_log) >= max_lines:
            removed = self._full_log[max_lines // 2:]
            self._full_log = self._full_log[:max_lines // 2]
            self._full_log.append(f"... [{len(removed)} righe troncate] ...")

        self._full_log.append(line)

        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        lower = line.lower()
        if "error" in lower or line.startswith("!"):
            fmt.setForeground(QColor("#f44747"))
        elif "warning" in lower:
            fmt.setForeground(QColor("#ffcc00"))
        elif line.startswith("[") or line.startswith("Pipeline"):
            fmt.setForeground(QColor("#9cdcfe"))
        elif "hook" in lower:
            fmt.setForeground(QColor("#ce9178"))
        else:
            fmt.setForeground(QColor("#d4d4d4"))

        cursor.insertText(line + "\n", fmt)
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    @pyqtSlot(str, bool, str)
    def _on_build_done(self, run_id: str, success: bool, message: str) -> None:
        if run_id != self._current_run_id:
            return

        self._btn_stop.setEnabled(False)
        self._update_button_states(self._current_profile)
        self._pipeline_bar.setVisible(False)
        self._input_container.setVisible(False)
        self._running_workers.pop(run_id, None)

        color_bg  = "#1e3a1e" if success else "#3a1e1e"
        color_fg  = "#4caf50" if success else "#f44747"
        icon      = "\u2713" if success else "\u2717"

        self._output.appendHtml(
            f'<span style="color:{color_fg}"><b>{icon} {message}</b></span>'
        )
        self._status_bar.setText(f"{icon} {message}  \u2014 {self._current_profile}")
        self._status_bar.setStyleSheet(
            f"padding: 2px 8px; font-size: 11px; "
            f"background: {color_bg}; color: {color_fg}; border-top: 1px solid #3c3c3c;"
        )

        if success:
            pdf_path = self._find_generated_pdf()
            if pdf_path:
                mw = self.window()
                if hasattr(mw, "_preview_panel_dock"):
                    mw._preview_panel_dock.set_pdf_path(pdf_path)

                from config.settings import Settings
                if Settings.instance().get("build/clean_aux_after_compile", False):
                    self._clean_aux_files(pdf_path)

        self._btn_analyze_ai.setEnabled(True)

        n = 0
        if self._current_profile:
            output_text = "\n".join(self._full_log)
            source = None
            editor = self._mw._tab_manager.current_editor() if hasattr(self._mw, "_tab_manager") else None
            if editor:
                source = getattr(editor, "file_path", None)

            from config.settings import Settings
            lsp_diags = None
            if Settings.instance().get("build/unified_errors", True) and source:
                lsp_diags = self._bm.get_lsp_diagnostics(source)

            errors = self._bm.parse_errors(output_text, self._current_profile, source, lsp_diags)
            self._show_errors(run_id, errors)
            n = len(errors)
        self.error_count_changed.emit(n)

    def _find_generated_pdf(self):
        from pathlib import Path
        mw = self.window()
        editor = None
        if hasattr(mw, "_tab_manager"):
            editor = mw._tab_manager.current_editor()
        if not editor:
            return None
        path = getattr(editor, "file_path", None)
        if not path:
            return None
        pdf = Path(str(path)).with_suffix(".pdf")
        return pdf if pdf.exists() else None

    def _clean_aux_files(self, pdf_path) -> None:
        from config.settings import Settings
        from core.build_manager import clean_aux_files
        keep_synctex = Settings.instance().get("build/keep_synctex", True)
        base = pdf_path.with_suffix("")
        removed = clean_aux_files(base, keep_synctex=keep_synctex)
        if removed:
            self._output.appendHtml(
                '<span style="color:#858585">\U0001f9f9 '
                f'{tr("build_panel.aux_cleaned", n=len(removed), files=", ".join(removed))}'
                '</span>'
            )

    def _clear_output(self) -> None:
        self._output.clear()
        self._full_log.clear()
        self._btn_analyze_ai.setEnabled(False)

    def _analyze_with_ai(self) -> None:
        log_text = self._output.toPlainText().strip()
        if not log_text:
            return

        try:
            from plugins.ai_plugin import PROVIDERS
        except ImportError:
            QMessageBox.warning(self.window(), "AI",
                                "Plugin AI non disponibile.")
            return

        dlg = _AIAnalyzeDialog(log_text, PROVIDERS, self.window())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        provider_name = dlg.selected_provider()
        model_name    = dlg.selected_model()
        prompt        = dlg.prompt()

        try:
            from plugins.plugin_manager import PluginManager
            ai_entry  = PluginManager.instance().get_all().get("AI Assistant", {})
            ai_plugin = ai_entry.get("instance")
            if ai_plugin is None:
                raise RuntimeError("Plugin non caricato")
            panel = ai_plugin._panel
            dock  = ai_plugin._dock
        except Exception as exc:
            QMessageBox.warning(self.window(), "AI",
                                f"Impossibile accedere al plugin AI:\n{exc}")
            return

        idx = panel._provider_combo.findText(provider_name)
        if idx >= 0:
            panel._provider_combo.setCurrentIndex(idx)

        pid = PROVIDERS.get(provider_name, {}).get("id", "")

        def _launch():
            panel._model_combo.setCurrentText(model_name)
            dock.show()
            panel._input.setPlainText(prompt)
            panel._send()

        if pid == "ollama" and panel._model_combo.findText(model_name) < 0:
            _fired = [False]
            def _on_ready(_models):
                if _fired[0]:
                    return
                _fired[0] = True
                try:
                    panel._ollama_ready.disconnect(_on_ready)
                except Exception:
                    pass
                _launch()
            panel._ollama_ready.connect(_on_ready)
        else:
            _launch()

    @pyqtSlot(str, list)
    def _show_errors(self, run_id: str, errors: list) -> None:
        if run_id != self._current_run_id:
            return
        self._error_tree.clear()
        for err in errors:
            source = err.get("source", err.get("severity", "Build"))
            item = QTreeWidgetItem(self._error_tree, [
                str(err.get("file", "")),
                str(err.get("line", "")),
                err.get("message", "")[:200],
                source,
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, err)
            if "error" in err.get("message", "").lower():
                item.setForeground(0, QColor("#f44747"))
                item.setForeground(2, QColor("#f44747"))
            elif "warn" in err.get("message", "").lower():
                item.setForeground(0, QColor("#ffcc00"))
                item.setForeground(2, QColor("#ffcc00"))
            if source == "LSP":
                item.setForeground(3, QColor("#9cdcfe"))
                item.setToolTip(3, "LSP Diagnostic")

        self._current_error_idx = -1
        has_errors = self._error_tree.topLevelItemCount() > 0
        self._btn_next_error.setEnabled(has_errors)
        self._btn_prev_error.setEnabled(has_errors)

    def goto_next_error(self) -> None:
        self._goto_error(+1)

    def goto_prev_error(self) -> None:
        self._goto_error(-1)

    def _goto_error(self, step: int) -> None:
        n = self._error_tree.topLevelItemCount()
        if n == 0:
            self._status_bar.setText(tr("build_panel.no_errors", default="Nessun errore da mostrare."))
            return
        self._current_error_idx = (self._current_error_idx + step) % n
        item = self._error_tree.topLevelItem(self._current_error_idx)
        self._error_tree.setCurrentItem(item)
        self._error_tree.scrollToItem(item)
        self._on_error_clicked(item)
        self._status_bar.setText(
            f"\u26a0  Errore {self._current_error_idx + 1}/{n}: {item.text(2)}"
        )
        self._status_bar.setStyleSheet(
            "padding: 2px 8px; font-size: 11px; "
            "background: #3a1e1e; color: #f44747; border-top: 1px solid #3c3c3c;"
        )

    def _on_error_clicked(self, item: QTreeWidgetItem) -> None:
        err = item.data(0, Qt.ItemDataRole.UserRole)
        if not err:
            return
        line     = err.get("line", 0)
        file_ref = err.get("file", "")

        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return

        if file_ref:
            from pathlib import Path
            p = Path(file_ref)
            if not p.is_absolute() and getattr(editor, "file_path", None):
                p = editor.file_path.parent / p
            if p.exists() and (
                not editor.file_path or p.resolve() != editor.file_path.resolve()
            ):
                self._mw.open_files([p])
                editor = self._mw._tab_manager.current_editor()

        if editor and line > 0:
            editor.go_to_line(line)
            editor.setFocus()


# ─── Task rapido ─────────────────────────────────────────────────────────────

class _TaskTab(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self._mw = main_window
        self._worker = None
        self._bm = BuildManager.instance()
        self._run_id = ""
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        row = QHBoxLayout()
        self._cmd_edit = QLineEdit()
        self._cmd_edit.setPlaceholderText(tr("build_panel.task_cmd_placeholder"))
        self._cmd_edit.setStyleSheet("background:#1e1e1e; color:#d4d4d4; border:1px solid #3c3c3c; padding:2px 4px;")
        self._cmd_edit.returnPressed.connect(self._run_command)
        self._btn_run  = QPushButton(tr("build_panel.task_run_btn"))
        self._btn_run.setFixedWidth(80)
        self._btn_run.clicked.connect(self._run_command)
        self._btn_stop = QPushButton(tr("build_panel.task_stop_btn"))
        self._btn_stop.setFixedWidth(60)
        self._btn_stop.setEnabled(False)
        self._btn_stop.setStyleSheet("color:#f44747;")
        self._btn_stop.clicked.connect(self._stop)
        self._btn_refresh = QPushButton("\u21ba")
        self._btn_refresh.setFixedWidth(30)
        self._btn_refresh.setToolTip(tr("tooltip.build_reload_tasks"))
        self._btn_refresh.clicked.connect(self._discover)
        self._btn_interactive = QPushButton("PTY")
        self._btn_interactive.setFixedWidth(36)
        self._btn_interactive.setCheckable(True)
        self._btn_interactive.setToolTip(tr("tooltip.build_interactive"))
        row.addWidget(self._cmd_edit, 1)
        row.addWidget(self._btn_run)
        row.addWidget(self._btn_stop)
        row.addWidget(self._btn_interactive)
        row.addWidget(self._btn_refresh)
        layout.addLayout(row)

        self._task_list = QListWidget()
        self._task_list.setStyleSheet("""
            QListWidget {
                background:#1e1e1e; color:#d4d4d4; border:1px solid #3c3c3c;
            }
            QListWidget::item:selected { background:#264f78; }
        """)
        self._task_list.setMaximumHeight(130)
        self._task_list.itemDoubleClicked.connect(self._on_task_double_clicked)
        self._task_list.itemClicked.connect(
            lambda item: self._cmd_edit.setText(item.data(Qt.ItemDataRole.UserRole) or "")
        )
        layout.addWidget(self._task_list)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QFont("Monospace", 10))
        self._output.setMaximumBlockCount(2000)
        self._output.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e; color: #d4d4d4;
                border: none; selection-background-color: #264f78;
            }
        """)
        layout.addWidget(self._output, 1)

        self._input_edit = QLineEdit()
        self._input_edit.setPlaceholderText(tr("build_panel.task_input_placeholder", default="Scrivi input..."))
        self._input_edit.setStyleSheet("background:#1e1e1e; color:#d4d4d4; border:1px solid #3c3c3c; padding:2px 4px;")
        self._input_edit.returnPressed.connect(self._send_input)
        self._input_edit.setVisible(False)
        layout.addWidget(self._input_edit)

        QTimer.singleShot(500, self._discover)

    def _discover(self) -> None:
        self._task_list.clear()
        editor = self._mw._tab_manager.current_editor() if hasattr(self._mw, "_tab_manager") else None
        path = getattr(editor, "file_path", None) if editor else None
        directory = path.parent if path else None
        if not directory:
            self._task_list.addItem(tr("build_panel.task_open_file"))
            return
        tasks = self._bm.discover_tasks(directory)
        if not tasks:
            self._task_list.addItem(tr("build_panel.no_task", dir=directory.name))
            return
        for t in tasks:
            item = QListWidgetItem(f"[{t['source']}]  {t['name']}")
            item.setData(Qt.ItemDataRole.UserRole, t["cmd"])
            self._task_list.addItem(item)

    def _on_task_double_clicked(self, item: QListWidgetItem) -> None:
        self._cmd_edit.setText(item.data(Qt.ItemDataRole.UserRole) or "")
        self._run_command()

    def _run_command(self) -> None:
        cmd = self._cmd_edit.text().strip()
        if not cmd:
            return
        editor = self._mw._tab_manager.current_editor() if hasattr(self._mw, "_tab_manager") else None
        path   = getattr(editor, "file_path", None) if editor else None
        cwd    = path.parent if path else Path.cwd()
        self._output.clear()
        self._output.appendPlainText(f"$ {cmd}\n")
        self._btn_run.setEnabled(False)
        self._btn_stop.setEnabled(True)

        interactive = self._btn_interactive.isChecked()
        self._input_edit.setVisible(interactive)

        self._run_id = f"task_{id(self)}"

        # Scollega segnali precedenti per evitare accumulo
        try:
            self._bm.build_output.disconnect(self._on_output)
            self._bm.build_done.disconnect(self._on_done)
        except TypeError:
            pass

        self._bm.run_task(cmd, cwd, run_id=self._run_id, interactive=interactive)

        self._bm.build_output.connect(self._on_output)
        self._bm.build_done.connect(self._on_done)

    def _stop(self) -> None:
        self._bm.stop(self._run_id)

    def _send_input(self) -> None:
        text = self._input_edit.text()
        if text:
            self._bm.send_input(self._run_id, text + "\n")
            self._input_edit.clear()

    def _on_output(self, run_id: str, line: str) -> None:
        if run_id != self._run_id:
            return
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        lower = line.lower()
        if "error" in lower:
            fmt.setForeground(QColor("#f44747"))
        elif "warning" in lower:
            fmt.setForeground(QColor("#ffcc00"))
        else:
            fmt.setForeground(QColor("#d4d4d4"))
        cursor.insertText(line + "\n", fmt)
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    def _on_done(self, run_id: str, ok: bool, msg: str) -> None:
        if run_id != self._run_id:
            return
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._input_edit.setVisible(False)
        try:
            self._bm.build_output.disconnect(self._on_output)
            self._bm.build_done.disconnect(self._on_done)
        except Exception:
            pass
        color = "#4caf50" if ok else "#f44747"
        icon  = "\u2713" if ok else "\u2717"
        self._output.appendHtml(f'<span style="color:{color}"><b>{icon} {tr("build_panel.task_done_ok") if ok else tr("build_panel.task_done_fail")}</b></span>')


# ─── Dialog configurazione profili ───────────────────────────────────────────

class BuildProfilesDialog(QDialog):
    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._mw = main_window
        self._bm = BuildManager.instance()
        self._dirty = False

        self._active_profile_name: str = ""
        editor = main_window._tab_manager.current_editor() if hasattr(main_window, '_tab_manager') else None
        if editor and getattr(editor, 'file_path', None):
            self._active_profile_name = self._bm.get_profile_for_file(editor.file_path) or ""

        self.setWindowTitle(tr("action.build_profiles", default="Profili di compilazione"))
        self.resize(860, 620)
        self._build_ui()
        self._load_profiles()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        main = QHBoxLayout()
        outer.addLayout(main, 1)

        left = QVBoxLayout()

        lbl = QLabel(tr("build_panel.available_profiles"))
        lbl.setStyleSheet("font-weight: bold;")
        left.addWidget(lbl)

        if self._active_profile_name:
            self._active_banner = QLabel(
                tr("build_panel.active_profile_banner", name=self._active_profile_name)
            )
            self._active_banner.setTextFormat(Qt.TextFormat.RichText)
            self._active_banner.setStyleSheet(
                "background: #264f78; color: #9cdcfe; "
                "font-size: 12px; padding: 4px 6px; border-radius: 3px;"
            )
            self._active_banner.setToolTip(tr("tooltip.build_auto_banner"))
        else:
            self._active_banner = QLabel(tr("build_panel.no_file_banner"))
            self._active_banner.setStyleSheet(
                "color: #858585; font-size: 11px; padding: 4px 6px;"
            )
        left.addWidget(self._active_banner)

        list_row = QHBoxLayout()

        self._profile_list = QListWidget()
        self._profile_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._profile_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._profile_list.currentItemChanged.connect(self._on_profile_item_changed)
        self._profile_list.model().rowsMoved.connect(self._on_profile_order_changed)
        list_row.addWidget(self._profile_list, 1)

        move_col = QVBoxLayout()
        self._btn_up = QPushButton("\u25b2")
        self._btn_down = QPushButton("\u25bc")
        self._btn_up.setFixedSize(24, 24)
        self._btn_down.setFixedSize(24, 24)
        self._btn_up.setToolTip(tr("tooltip.build_profile_move_up"))
        self._btn_down.setToolTip(tr("tooltip.build_profile_move_down"))
        self._btn_up.clicked.connect(self._move_profile_up)
        self._btn_down.clicked.connect(self._move_profile_down)
        move_col.addWidget(self._btn_up)
        move_col.addWidget(self._btn_down)
        move_col.addStretch()
        list_row.addLayout(move_col)

        left.addLayout(list_row, 1)

        btn_row = QHBoxLayout()
        self._btn_new = QPushButton(tr("button.add", default="Nuovo"))
        self._btn_del = QPushButton(tr("button.remove", default="Elimina"))
        self._btn_new.clicked.connect(self._new_profile)
        self._btn_del.clicked.connect(self._delete_profile)
        btn_row.addWidget(self._btn_new)
        btn_row.addWidget(self._btn_del)
        left.addLayout(btn_row)

        self._btn_set_active = QPushButton("\u25b6  " + tr("button.set_active"))
        self._btn_set_active.setToolTip(tr("tooltip.build_set_active"))
        self._btn_set_active.setStyleSheet(
            "font-weight: bold; padding: 4px 8px; "
            "background: #264f78; color: #9cdcfe; border: 1px solid #9cdcfe;"
        )
        self._btn_set_active.clicked.connect(self._set_as_active)
        left.addWidget(self._btn_set_active)

        main.addLayout(left, 1)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        main.addWidget(sep)

        right_outer = QVBoxLayout()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_widget = QWidget()
        right = QVBoxLayout(right_widget)

        self._grp_core = QGroupBox(tr("build_panel.profile_config_title"))
        form = QFormLayout(self._grp_core)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._name_edit    = QLineEdit()
        self._ext_edit     = QLineEdit()
        self._ext_edit.setPlaceholderText(".py  .pyw  (separati da spazio o ;)")
        self._compile_edit = QLineEdit()
        self._compile_edit.setPlaceholderText(tr("build_panel.cmd_placeholder_empty"))
        self._run_edit     = QLineEdit()
        self._run_edit.setPlaceholderText(tr("build_panel.cmd_placeholder_empty"))
        self._build_edit   = QLineEdit()
        self._build_edit.setPlaceholderText(tr("build_panel.cmd_placeholder_empty"))
        self._regex_edit = QLineEdit()
        self._regex_edit.setPlaceholderText(r'es. File "([^"]+)", line (\d+)')
        self._regex_edit.setToolTip(tr("tooltip.build_error_regex"))
        self._regex_edit.textChanged.connect(self._on_regex_changed)

        self._regex_preview = QLabel("")
        self._regex_preview.setStyleSheet(
            "font-family: monospace; font-size: 10px; "
            "background: #1e1e1e; color: #4caf50; "
            "padding: 2px 4px; border-radius: 2px; min-height: 18px;"
        )
        self._regex_preview.setWordWrap(True)

        # Sample di output per il test live della regex
        self._regex_sample_output = (
            'File "/home/user/test.py", line 42, in <module>\n'
            'File "/home/user/main.py", line 15\n'
            'src/app.rs:100:5: error: expected token\n'
        )

        form.addRow(tr("build_panel.profile_name_label"),    self._name_edit)
        form.addRow(tr("build_panel.extensions_label"),       self._ext_edit)
        form.addRow(tr("action.compile", default="Compila") + " \u2192", self._compile_edit)
        form.addRow(tr("action.run",     default="Esegui")  + " \u2192", self._run_edit)
        form.addRow(tr("action.build",   default="Build")   + " \u2192", self._build_edit)
        form.addRow(tr("build_panel.error_regex_label"),     self._regex_edit)
        form.addRow("", self._regex_preview)

        regex_row = QHBoxLayout()
        regex_row.addWidget(QLabel(tr("build_panel.regex_file_group", default="File grp:")))
        self._file_grp_spin = QSpinBox()
        self._file_grp_spin.setRange(0, 9)
        self._file_grp_spin.setValue(1)
        self._file_grp_spin.setToolTip(tr("tooltip.build_regex_file_group", default="Gruppo regex per il file"))
        regex_row.addWidget(self._file_grp_spin)
        regex_row.addWidget(QLabel(tr("build_panel.regex_line_group", default="Line grp:")))
        self._line_grp_spin = QSpinBox()
        self._line_grp_spin.setRange(0, 9)
        self._line_grp_spin.setValue(2)
        self._line_grp_spin.setToolTip(tr("tooltip.build_regex_line_group", default="Gruppo regex per la riga"))
        regex_row.addWidget(self._line_grp_spin)
        regex_row.addStretch()
        form.addRow("", QWidget())
        form.addRow("", QWidget())

        var_lbl = QLabel(
            f"<small><b>{tr('build_panel.vars_title')}</b> (<code>${{VAR}}</code> {tr('build_panel.vars_or')} <code>$(VAR)</code>):<br>"
            "<table cellspacing='2'>"
            f"<tr><td><code>${{FILE}}</code></td><td>\u2014 {tr('build_panel.var_file_desc')}&nbsp;&nbsp;</td>"
            "<td><i>es. /home/user/doc/main.py</i></td></tr>"
            f"<tr><td><code>${{DIR}}</code></td><td>\u2014 {tr('build_panel.var_dir_desc')}</td>"
            "<td><i>es. /home/user/doc</i></td></tr>"
            f"<tr><td><code>${{FILENAME}}</code></td><td>\u2014 {tr('build_panel.var_filename_desc')}</td>"
            "<td><i>es. main.py</i></td></tr>"
            f"<tr><td><code>${{BASENAME}}</code></td><td>\u2014 {tr('build_panel.var_basename_desc')}</td>"
            "<td><i>es. main</i></td></tr>"
            f"<tr><td><code>${{BASEFILE}}</code></td><td>\u2014 {tr('build_panel.var_basefile_desc')}</td>"
            "<td><i>es. /home/user/doc/main</i></td></tr>"
            f"<tr><td><code>${{EXT}}</code></td><td>\u2014 {tr('build_panel.var_ext_desc')}</td>"
            "<td><i>es. .py</i></td></tr>"
            f"<tr><td><code>${{LINE}}</code></td><td>\u2014 {tr('build_panel.var_line_desc')}</td>"
            "<td><i>es. 42</i></td></tr>"
            f"<tr><td><code>${{COL}}</code></td><td>\u2014 {tr('build_panel.var_col_desc')}</td>"
            "<td><i>es. 7</i></td></tr>"
            "</table></small>"
        )
        var_lbl.setTextFormat(Qt.TextFormat.RichText)
        var_lbl.setWordWrap(True)
        form.addRow("", var_lbl)

        right.addWidget(self._grp_core)

        self._grp_env = QGroupBox(tr("build_panel.env_group", default="Variabili d'ambiente"))
        env_layout = QVBoxLayout(self._grp_env)
        env_layout.addWidget(QLabel(tr("build_panel.env_hint",
            default="Formato: UNA_VARIABILE=valore, una per riga. Riga vuota = ignora.")))
        self._env_edit = QPlainTextEdit()
        self._env_edit.setMaximumHeight(80)
        self._env_edit.setPlaceholderText("PATH=/custom/bin:$PATH\nMY_VAR=hello")
        self._env_edit.setStyleSheet("background:#1e1e1e; color:#d4d4d4; border:1px solid #3c3c3c; font-family: monospace;")
        env_layout.addWidget(self._env_edit)
        right.addWidget(self._grp_env)

        self._grp_hooks = QGroupBox(tr("build_panel.hooks_group", default="Hook pre/post build"))
        hooks_form = QFormLayout(self._grp_hooks)
        hooks_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._pre_hook_edit = QLineEdit()
        self._pre_hook_edit.setPlaceholderText(tr("build_panel.pre_hook_placeholder", default="source venv/bin/activate"))
        self._post_hook_edit = QLineEdit()
        self._post_hook_edit.setPlaceholderText(tr("build_panel.post_hook_placeholder", default="./cleanup.sh"))
        hooks_form.addRow(tr("build_panel.pre_hook"), self._pre_hook_edit)
        hooks_form.addRow(tr("build_panel.post_hook"), self._post_hook_edit)
        right.addWidget(self._grp_hooks)

        self._grp_pipeline = QGroupBox(tr("build_panel.pipeline_group", default="Pipeline (multi-step)"))
        pipe_layout = QVBoxLayout(self._grp_pipeline)
        pipe_layout.addWidget(QLabel(tr("build_panel.pipeline_hint",
            default="Se configurata, la pipeline sostituisce compile/run/build.\nUn passo per riga: nome | comando | stop_on_error (true/false)")))
        self._pipeline_edit = QPlainTextEdit()
        self._pipeline_edit.setMaximumHeight(100)
        self._pipeline_edit.setPlaceholderText("Lint | ruff check ${FILE} | true\nCompile | gcc -Wall -o ${DIR}/${BASENAME} ${FILE} | true\nRun | ${DIR}/${BASENAME} | false")
        self._pipeline_edit.setStyleSheet("background:#1e1e1e; color:#d4d4d4; border:1px solid #3c3c3c; font-family: monospace;")
        pipe_layout.addWidget(self._pipeline_edit)
        right.addWidget(self._grp_pipeline)

        self._grp_regex = QGroupBox(tr("build_panel.regex_group", default="Gruppi regex errori"))
        regex_form = QFormLayout(self._grp_regex)
        regex_form.addRow(QLabel(tr("build_panel.regex_capture_note",
            default="I gruppi di cattura devono corrispondere a file e numero di riga.")))
        regex_form.addRow("", regex_row.itemAt(0).widget())
        w = QWidget()
        w.setLayout(regex_row)
        regex_form.addRow(w)
        right.addWidget(self._grp_regex)

        right.addStretch()

        scroll.setWidget(right_widget)
        right_outer.addWidget(scroll, 1)

        for w in [self._name_edit, self._ext_edit, self._compile_edit,
                   self._run_edit, self._build_edit, self._regex_edit,
                   self._pre_hook_edit, self._post_hook_edit]:
            w.textChanged.connect(self._mark_dirty)
        self._env_edit.textChanged.connect(self._mark_dirty)
        self._pipeline_edit.textChanged.connect(self._mark_dirty)
        self._file_grp_spin.valueChanged.connect(self._mark_dirty)
        self._line_grp_spin.valueChanged.connect(self._mark_dirty)

        self._save_status = QLabel("")
        self._save_status.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_outer.addWidget(self._save_status)

        save_row = QHBoxLayout()
        save_row.addStretch()
        self._btn_save = QPushButton("\U0001f4be  " + tr("button.save", default="Salva profilo"))
        self._btn_save.setMinimumWidth(160)
        self._btn_save.setStyleSheet("font-weight: bold; padding: 4px 12px;")
        self._btn_save.clicked.connect(self._save_current)
        save_row.addWidget(self._btn_save)
        right_outer.addLayout(save_row)

        self._note_builtin = QLabel(tr("build_panel.save_prompt"))
        self._note_builtin.setStyleSheet("color: #858585; font-size: 11px;")
        self._note_builtin.setWordWrap(True)
        self._note_builtin.setVisible(False)
        right_outer.addWidget(self._note_builtin)

        main.addLayout(right_outer, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self._on_close)
        outer.addWidget(buttons)

    def _load_profiles(self) -> None:
        self._profile_list.clear()
        profiles = self._bm.get_profiles()
        active_row = 0
        for i, name in enumerate(profiles):
            is_active = (name == self._active_profile_name)
            label = f"\u25b6  {name}" if is_active else f"    {name}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)
            if is_active:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setForeground(QColor("#9cdcfe"))
                item.setBackground(QColor("#1e3a5f"))
                active_row = i
            self._profile_list.addItem(item)

        if self._profile_list.count() > 0:
            self._profile_list.setCurrentRow(active_row)

    def _on_profile_item_changed(self, item, _prev) -> None:
        if item is None:
            return
        name = item.data(Qt.ItemDataRole.UserRole) or ""
        if not name:
            return
        self._on_profile_selected(name)

    def _on_profile_selected(self, name: str) -> None:
        if not name:
            return
        profile = self._bm.get_profiles().get(name, {})

        self._dirty = False
        self._name_edit.setText(name)
        exts = profile.get("extensions", [])
        self._ext_edit.setText("  ".join(exts))
        self._compile_edit.setText(profile.get("compile", ""))
        self._run_edit.setText(    profile.get("run",     ""))
        self._build_edit.setText(  profile.get("build",   ""))
        self._regex_edit.setText(  profile.get("error_regex", ""))

        self._file_grp_spin.setValue(profile.get("error_file_group", 1))
        self._line_grp_spin.setValue(profile.get("error_line_group", 2))

        env_val = profile.get("env", {})
        if isinstance(env_val, dict):
            self._env_edit.setPlainText("\n".join(f"{k}={v}" for k, v in env_val.items()))
        elif isinstance(env_val, str):
            self._env_edit.setPlainText(env_val)

        self._pre_hook_edit.setText(profile.get("pre_hook", ""))
        self._post_hook_edit.setText(profile.get("post_hook", ""))

        pipeline = profile.get("pipeline", [])
        if pipeline:
            lines = []
            for step in pipeline:
                name_s = step.get("name", "")
                cmd_s = step.get("cmd", "")
                stop_e = str(step.get("stop_on_error", True)).lower()
                lines.append(f"{name_s} | {cmd_s} | {stop_e}")
            self._pipeline_edit.setPlainText("\n".join(lines))
        else:
            self._pipeline_edit.setPlainText("")

        self._dirty = False

        is_builtin = name in DEFAULT_PROFILES
        self._note_builtin.setVisible(is_builtin)
        self._btn_del.setEnabled(not is_builtin)

        self._save_status.setText("")
        self._btn_save.setStyleSheet("font-weight: bold; padding: 4px 12px;")

    def _mark_dirty(self) -> None:
        if self._dirty:
            return
        self._dirty = True
        self._save_status.setText(tr("build_panel.unsaved_changes"))
        self._save_status.setStyleSheet("color: #ffcc00; font-size: 11px;")
        self._btn_save.setStyleSheet(
            "font-weight: bold; padding: 4px 12px; "
            "background: #264f78; color: #ffffff; border: 1px solid #9cdcfe;"
        )

    def _on_regex_changed(self, text: str) -> None:
        if not text.strip():
            self._regex_preview.setText("")
            return
        import re
        file_grp = self._file_grp_spin.value()
        line_grp = self._line_grp_spin.value()
        try:
            compiled = re.compile(text, re.MULTILINE)
            matches = list(compiled.finditer(self._regex_sample_output))
            if matches:
                parts = []
                for m in matches[:3]:
                    groups = m.groups()
                    f = groups[file_grp - 1] if file_grp > 0 and file_grp <= len(groups) else "?"
                    l = groups[line_grp - 1] if line_grp > 0 and line_grp <= len(groups) else "?"
                    parts.append(f"File: {f}, Line: {l}")
                more = f" +{len(matches)-3}" if len(matches) > 3 else ""
                self._regex_preview.setText(f"\u2713  {len(matches)} match: {'  |  '.join(parts)}{more}")
                self._regex_preview.setStyleSheet(
                    "font-family: monospace; font-size: 10px; "
                    "background: #1e3a1e; color: #4caf50; "
                    "padding: 2px 4px; border-radius: 2px; min-height: 18px;"
                )
            elif len(matches) == 0:
                self._regex_preview.setText("\u26a0  No match on sample output")
                self._regex_preview.setStyleSheet(
                    "font-family: monospace; font-size: 10px; "
                    "background: #3a1e1e; color: #ffcc00; "
                    "padding: 2px 4px; border-radius: 2px; min-height: 18px;"
                )
        except re.error as e:
            self._regex_preview.setText(f"\u2717  Invalid regex: {e}")
            self._regex_preview.setStyleSheet(
                "font-family: monospace; font-size: 10px; "
                "background: #3a1e1e; color: #f44747; "
                "padding: 2px 4px; border-radius: 2px; min-height: 18px;"
            )

    def _set_as_active(self) -> None:
        current = self._profile_list.currentItem()
        if not current:
            return
        name = current.data(Qt.ItemDataRole.UserRole) or ""
        if not name:
            return
        editor = self._mw._tab_manager.current_editor() if hasattr(self._mw, "_tab_manager") else None
        path = getattr(editor, "file_path", None) if editor else None
        ext = path.suffix.lower() if path else ""
        if ext:
            self._bm.set_profile_override(ext, name)
        else:
            self._bm._active_profile = name
        self._active_profile_name = name

        self._active_banner.setText(tr("build_panel.active_profile_banner", name=name))
        self._active_banner.setStyleSheet(
            "background: #264f78; color: #9cdcfe; "
            "font-size: 12px; padding: 4px 6px; border-radius: 3px;"
        )

        for i in range(self._profile_list.count()):
            item = self._profile_list.item(i)
            iname = item.data(Qt.ItemDataRole.UserRole) or ""
            is_active = (iname == name)
            font = item.font()
            font.setBold(is_active)
            item.setFont(font)
            if is_active:
                item.setText(f"\u25b6  {iname}")
                item.setForeground(QColor("#9cdcfe"))
                item.setBackground(QColor("#1e3a5f"))
                item.setToolTip(tr("tooltip.build_profile_active_manual"))
            else:
                item.setText(f"    {iname}")
                item.setBackground(QColor(0, 0, 0, 0))
                item.setForeground(self._profile_list.palette().color(
                    self._profile_list.palette().ColorRole.WindowText))

        if hasattr(self._mw, '_build_panel') and self._mw._build_panel:
            bp = self._mw._build_panel
            if hasattr(bp, '_set_active_profile'):
                bp._set_active_profile(name)

    def _save_current(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            self._save_status.setText(tr("build_panel.save_name_error"))
            self._save_status.setStyleSheet("color: #f44747; font-size: 11px;")
            return

        raw_exts = self._ext_edit.text().replace(";", " ").replace(",", " ").split()
        exts = []
        for e in raw_exts:
            e = e.strip()
            if e and not e.startswith("."):
                e = "." + e
            if e:
                exts.append(e.lower())

        env_dict = {}
        env_text = self._env_edit.toPlainText().strip()
        if env_text:
            for line in env_text.splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env_dict[k.strip()] = v.strip()

        pipeline = []
        pipe_text = self._pipeline_edit.toPlainText().strip()
        if pipe_text:
            for line in pipe_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split("|", 2)
                if len(parts) >= 2:
                    p_name = parts[0].strip()
                    p_cmd = parts[1].strip()
                    p_stop = parts[2].strip().lower() != "false" if len(parts) >= 3 else True
                    pipeline.append({"name": p_name, "cmd": p_cmd, "stop_on_error": p_stop})

        profile = {
            "extensions":         exts,
            "compile":            self._compile_edit.text().strip(),
            "run":                self._run_edit.text().strip(),
            "build":              self._build_edit.text().strip(),
            "error_regex":        self._regex_edit.text().strip(),
            "error_file_group":   self._file_grp_spin.value(),
            "error_line_group":   self._line_grp_spin.value(),
            "env":                env_dict,
            "pre_hook":           self._pre_hook_edit.text().strip(),
            "post_hook":          self._post_hook_edit.text().strip(),
            "pipeline":           pipeline,
        }

        existing_parser = self._bm.get_profiles().get(name, {}).get("error_parser")
        if existing_parser:
            profile["error_parser"] = existing_parser
        self._bm.add_profile(name, profile)

        existing = self._find_item_by_name(name)
        if existing is None:
            label = f"\u25b6  {name}" if name == self._active_profile_name else f"    {name}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(tr("tooltip.build_profile_user"))
            self._profile_list.addItem(item)
            self._profile_list.setCurrentItem(item)
        else:
            existing.setForeground(self._profile_list.palette().color(
                self._profile_list.palette().ColorRole.WindowText))

        self._dirty = False
        if name in DEFAULT_PROFILES:
            self._save_status.setText(tr("build_panel.save_override_ok"))
        else:
            self._save_status.setText(tr("build_panel.save_ok"))
        self._save_status.setStyleSheet("color: #4caf50; font-size: 11px;")
        self._btn_save.setStyleSheet("font-weight: bold; padding: 4px 12px;")
        self._note_builtin.setVisible(False)

        QTimer.singleShot(3000, lambda: self._save_status.setText(""))

    def _new_profile(self) -> None:
        name, ok = QInputDialog.getText(
            self, tr("build_panel.new_profile_title"), tr("build_panel.new_profile_prompt")
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        empty = {
            "extensions": [], "compile": "", "run": "", "build": "",
            "error_regex": "", "error_file_group": 1, "error_line_group": 2,
            "env": {}, "pre_hook": "", "post_hook": "", "pipeline": [],
        }
        self._bm.add_profile(name, empty)
        item = QListWidgetItem(f"    {name}")
        item.setData(Qt.ItemDataRole.UserRole, name)
        item.setToolTip(tr("tooltip.build_profile_user"))
        self._profile_list.addItem(item)
        self._profile_list.setCurrentItem(item)

    def _find_item_by_name(self, name: str):
        for i in range(self._profile_list.count()):
            item = self._profile_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == name:
                return item
        return None

    def _delete_profile(self) -> None:
        current = self._profile_list.currentItem()
        if not current:
            return
        name = current.data(Qt.ItemDataRole.UserRole) or current.text()
        if name in DEFAULT_PROFILES:
            QMessageBox.information(
                self, tr("build_panel.delete_title"),
                tr("build_panel.builtin_delete_error", name=name)
            )
            return
        reply = QMessageBox.question(
            self, tr("build_panel.delete_title"),
            tr("build_panel.delete_confirm", name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._bm.remove_profile(name)
            self._profile_list.takeItem(self._profile_list.currentRow())

    def _current_profile_order(self) -> list:
        return [
            self._profile_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._profile_list.count())
        ]

    def _on_profile_order_changed(self) -> None:
        self._bm.reorder_profiles(self._current_profile_order())

    def _move_profile_up(self) -> None:
        row = self._profile_list.currentRow()
        if row <= 0:
            return
        item = self._profile_list.takeItem(row)
        self._profile_list.insertItem(row - 1, item)
        self._profile_list.setCurrentRow(row - 1)
        self._bm.reorder_profiles(self._current_profile_order())

    def _move_profile_down(self) -> None:
        row = self._profile_list.currentRow()
        if row < 0 or row >= self._profile_list.count() - 1:
            return
        item = self._profile_list.takeItem(row)
        self._profile_list.insertItem(row + 1, item)
        self._profile_list.setCurrentRow(row + 1)
        self._bm.reorder_profiles(self._current_profile_order())

    def _on_close(self) -> None:
        if self._dirty:
            reply = QMessageBox.question(
                self, tr("build_panel.close_unsaved_title"),
                tr("build_panel.close_unsaved_msg"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        self.accept()

"""
ui/build_panel.py — Pannello output compilazione
NotePadPQ

Panel con output del build, lista errori cliccabili e
dialog configurazione profili.

Fix rispetto alla versione precedente:
- Il profilo attivo è sempre visibile e sincronizzato con il file corrente
- I pulsanti mostrano il comando che verrà eseguito nel tooltip
- Salva profilo con feedback visivo (colore + messaggio)
- Il combo del pannello e il BuildManager sono sempre allineati
- Pulsanti Compile/Run/Build disabilitati se il comando è vuoto per quel profilo
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
    QStatusBar, QFrame, QTextEdit,
)

from i18n.i18n import tr
from core.build_manager import BuildManager, DEFAULT_PROFILES

if TYPE_CHECKING:
    from ui.main_window import MainWindow
    from editor.editor_widget import EditorWidget


class _AIAnalyzeDialog(QDialog):
    """
    Dialogo di conferma per 'Analizza con AI'.
    Recupera i modelli Ollama/Anthropic live, esattamente come fa il plugin AI.
    """

    _ollama_ready    = pyqtSignal(object)   # list[str] | None
    _anthropic_ready = pyqtSignal(object)   # list[str] | None
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

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 8)

        # Provider + modello + pulsante refresh
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

        self._btn_refresh = QPushButton("↻")
        self._btn_refresh.setFixedWidth(28)
        self._btn_refresh.setToolTip(tr("tooltip.build_reload_tasks"))
        self._btn_refresh.clicked.connect(self._manual_refresh)
        row.addWidget(self._btn_refresh)
        root.addLayout(row)

        # Istruzione
        root.addWidget(QLabel(tr("label.ai_instruction")))
        self._instruction = QLineEdit()
        self._instruction.setText(tr("msg.build_ai_default_prompt"))
        root.addWidget(self._instruction)

        # Anteprima log
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

        # Bottoni
        bbox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bbox.button(QDialogButtonBox.StandardButton.Ok).setText(
            tr("action.build_analyze_ai_send")
        )
        bbox.accepted.connect(self.accept)
        bbox.rejected.connect(self.reject)
        root.addWidget(bbox)

        # Ripristina ultima scelta poi triggera il refresh
        from config.settings import Settings
        s = Settings.instance()
        last_p = s.get("build/ai_provider", "")
        last_m = s.get("build/ai_model",    "")
        if last_p:
            idx = self._provider_combo.findText(last_p)
            if idx >= 0:
                self._provider_combo.setCurrentIndex(idx)
                # _on_provider_changed già chiamato dal setCurrentIndex → non richiamare
                if last_m:
                    self._model_combo.setCurrentText(last_m)
                return
        self._on_provider_changed()
        if last_m:
            self._model_combo.setCurrentText(last_m)

    # ── Provider / modello ────────────────────────────────────────────────────

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

    # ── Ollama — identico al plugin AI ───────────────────────────────────────

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
            self._model_combo.addItem(tr("msg.ollama_unreachable", default="⚠ ollama non raggiungibile"))
            self._model_combo.setEnabled(False)
            return
        self._model_combo.setEnabled(True)
        for m in models:
            self._model_combo.addItem(m)

    # ── Anthropic — identico al plugin AI ────────────────────────────────────

    def _refresh_anthropic(self) -> None:
        import threading, urllib.request, json as _json
        from config.settings import Settings
        api_key = Settings.instance().get("ai/anthropic_key", "").strip()
        if not api_key:
            return  # nessuna chiave — lascia i modelli statici
        self._btn_refresh.setEnabled(False)
        self._btn_refresh.setText("…")

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
        self._btn_refresh.setText("↻")
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

    # ── Dati finali ───────────────────────────────────────────────────────────

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
    """
    Widget pannello build. Viene aggiunto come dock o widget inferiore
    dalla MainWindow quando viene avviata una compilazione.

    Contiene solo la toolbar (profilo/azioni) e il log grezzo di
    compilazione. La lista errori (`_error_tree`) e il tab task
    (`_task_widget`) sono creati qui ma vengono montati dalla MainWindow
    come tab di pari livello del pannello inferiore (accanto a
    "Diagnostics"), non annidati in un secondo QTabWidget: un secondo
    livello di tab dietro una toolbar-corner-widget lasciava le linguette
    inaccessibili (nessuno scrolling) quando lo spazio era stretto.
    """

    error_count_changed = pyqtSignal(int)

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self._mw = main_window
        self._bm = BuildManager.instance()
        self._current_profile: str = ""
        self._current_error_idx: int = -1
        # Log completo per il parsing errori: self._output non ha limiti di
        # righe, ma leggere migliaia di righe da un QPlainTextEdit ad ogni
        # fine-build (per estrarre gli errori) è più lento e più fragile
        # (richiede toPlainText()) che tenerle già pronte in una lista Python.
        # parse_errors() lavora quindi su questa lista, non sul widget.
        self._full_log: list[str] = []

        self._build_ui()
        self._connect_signals()
        # Sincronizza il profilo con il tab corrente dopo l'avvio
        QTimer.singleShot(0, self._sync_profile_to_editor)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setMinimumHeight(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Barra superiore: profilo attivo + azioni ──────────────────────────
        # Vera QToolBar (non corner-widget di un QTabWidget): se lo spazio
        # manca, Qt mostra automaticamente una freccia "»" di overflow invece
        # di nascondere i pulsanti/tab senza alcun modo di raggiungerli.
        tb = QToolBar()
        tb.setMovable(False)
        # Di default QToolBar mostra solo l'icona per le QAction: le nostre
        # (▲ ▼ e "Analizza con AI") hanno anche testo che deve restare visibile.
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toolbar = tb

        # Etichetta profilo attivo — colorata e visibile
        self._lbl_profile = QLabel()
        self._lbl_profile.setStyleSheet(
            "font-weight: bold; padding: 2px 6px; "
            "background: #264f78; color: #9cdcfe; border-radius: 3px;"
        )
        self._lbl_profile.setToolTip(tr("tooltip.build_profile_label"))

        # Combo override manuale
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

        # Pulsanti azione — le etichette includono la shortcut reale, letta dinamicamente
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

        # Azioni secondarie come QAction (non QPushButton via addWidget): se lo
        # spazio manca e finiscono nel menu "»" di overflow di QToolBar, solo
        # le QAction restano cliccabili li' dentro — i widget custom aggiunti
        # con addWidget() nell'overflow smettono di rispondere ai click.
        tb.setIconSize(QSize(16, 16))
        self._btn_prev_error = QAction("▲", self)
        self._btn_next_error = QAction("▼", self)
        self._btn_prev_error.setToolTip(tr("tooltip.build_prev_error"))
        self._btn_next_error.setToolTip(tr("tooltip.build_next_error"))
        self._btn_prev_error.setEnabled(False)
        self._btn_next_error.setEnabled(False)

        self._btn_analyze_ai = QAction(tr("action.build_analyze_ai"), self)
        self._btn_analyze_ai.setToolTip(tr("tooltip.build_analyze_ai"))
        self._btn_analyze_ai.setEnabled(False)
        self._set_analyze_ai_icon()

        tb.addAction(self._btn_prev_error)
        tb.addAction(self._btn_next_error)
        tb.addAction(self._btn_analyze_ai)

        layout.addWidget(tb)

        # ── Log grezzo di compilazione ────────────────────────────────────────
        # Resta sempre il contenuto di questo pannello: non c'è più uno switch
        # automatico verso un'altra tab in caso di errore, così il log con
        # l'errore reale del compilatore non sparisce mai dalla vista.
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

        # ── Barra stato build ─────────────────────────────────────────────────
        self._status_bar = QLabel()
        self._status_bar.setStyleSheet(
            "padding: 2px 8px; font-size: 11px; "
            "background: #252526; color: #858585; border-top: 1px solid #3c3c3c;"
        )
        self._status_bar.setText(tr("msg.ready", default="Pronto."))
        layout.addWidget(self._status_bar)

        # ── Errori (montato dalla MainWindow come tab a parte) ────────────────
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
            tr("label.file", default="File"), tr("label.line", default="Riga"),
            tr("label.message", default="Messaggio")
        ])
        self._error_tree.setColumnWidth(0, 220)
        self._error_tree.setColumnWidth(1, 60)
        self._error_tree.itemDoubleClicked.connect(self._on_error_clicked)

        # ── Task rapido (montato dalla MainWindow come tab a parte) ───────────
        self._task_widget = _TaskTab(self._mw)

        QTimer.singleShot(0, self._refresh_button_labels)

    def _connect_signals(self) -> None:
        bm = self._bm
        bm.build_started.connect(self._on_build_started)
        bm.build_output.connect(self._append_output)
        bm.build_done.connect(self._on_build_done)
        bm.build_errors.connect(self._show_errors)

        self._btn_compile.clicked.connect(lambda: self._run_action("compile"))
        self._btn_run.clicked.connect(    lambda: self._run_action("run"))
        self._btn_build.clicked.connect(  lambda: self._run_action("build"))
        self._btn_stop.clicked.connect(bm.stop)
        self._btn_clear.clicked.connect(self._clear_output)
        self._btn_analyze_ai.triggered.connect(self._analyze_with_ai)
        self._btn_next_error.triggered.connect(self.goto_next_error)
        self._btn_prev_error.triggered.connect(self.goto_prev_error)

        # Sincronizza il profilo quando cambia il tab nell'editor
        try:
            self._mw._tab_manager.current_editor_changed.connect(
                self._sync_profile_to_editor
            )
        except Exception:
            pass

    def _refresh_button_labels(self) -> None:
        """Aggiorna le etichette dei pulsanti con la shortcut attuale letta da _actions."""
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
            icon_path = Path(__file__).parent.parent / "icons" / "lucide" / "sparkles.svg"
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

    # ── Gestione profilo attivo ───────────────────────────────────────────────

    def _sync_profile_to_editor(self) -> None:
        """
        Aggiorna profilo attivo e combo in base al file corrente.
        Se esiste un override per-estensione lo mostra nel combo, altrimenti usa auto-detect.
        """
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
            # Estensione ha override esplicito → mostralo nel combo
            idx = self._profile_combo.findData(override)
            self._profile_combo.blockSignals(True)
            self._profile_combo.setCurrentIndex(idx if idx > 0 else 0)
            self._profile_combo.blockSignals(False)
            self._set_active_profile(override)
        else:
            # Auto-detect
            self._profile_combo.blockSignals(True)
            self._profile_combo.setCurrentIndex(0)
            self._profile_combo.blockSignals(False)
            name = self._bm.get_profile_for_file(path)
            self._set_active_profile(name or "")

    def _on_combo_changed(self, index: int) -> None:
        """L'utente ha scelto un profilo manuale (o resettato ad automatico)."""
        editor = self._mw._tab_manager.current_editor() if hasattr(self._mw, "_tab_manager") else None
        path = getattr(editor, "file_path", None) if editor else None
        ext = path.suffix.lower() if path else ""

        if index == 0:
            # Auto: rimuovi override per questa estensione e risincronizza
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
        """Imposta il profilo attivo e aggiorna tutti gli elementi UI."""
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

        # Aggiorna tooltip e stato enabled dei pulsanti
        self._update_button_states(name)

    def _update_button_states(self, profile_name: str) -> None:
        """Abilita/disabilita i pulsanti e aggiorna i tooltip con i comandi."""
        profile = self._bm.get_profiles().get(profile_name, {})

        compile_cmd = profile.get("compile", "")
        run_cmd     = profile.get("run",     "")
        build_cmd   = profile.get("build",   "")

        self._btn_compile.setEnabled(bool(compile_cmd))
        self._btn_run.setEnabled(    bool(run_cmd))
        self._btn_build.setEnabled(  bool(build_cmd))

        self._btn_compile.setToolTip(compile_cmd or tr("build_panel.no_compile_cmd"))
        self._btn_run.setToolTip(    run_cmd     or tr("build_panel.no_run_cmd"))
        self._btn_build.setToolTip(  build_cmd   or tr("build_panel.no_build_cmd"))

        if not profile_name:
            for btn in [self._btn_compile, self._btn_run, self._btn_build]:
                btn.setEnabled(False)
                btn.setToolTip(tr("tooltip.build_no_file"))

    # ── Esecuzione ────────────────────────────────────────────────────────────

    def _run_action(self, action: str) -> None:
        """Lancia compile/run/build usando il profilo attivo."""
        editor = self._mw._tab_manager.current_editor()
        if editor is None:
            return

        self._bm.run(action, editor)

    @pyqtSlot(str)
    def _on_build_started(self, action: str) -> None:
        """Reset di log/errori/pulsanti a inizio build. Agganciato al segnale
        BuildManager.build_started invece che al solo click sui pulsanti del
        pannello, così lo stato si azzera anche quando la build parte da una
        scorciatoia/menu che chiama BuildManager.run() direttamente (altrimenti
        il log e gli errori della build precedente restavano visibili/misti a
        quelli nuovi)."""
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
        self._status_bar.setText(
            tr("build_panel.in_progress", action=action.capitalize(), profile=self._current_profile)
        )
        self._status_bar.setStyleSheet(
            "padding: 2px 8px; font-size: 11px; "
            "background: #1e3a1e; color: #4caf50; border-top: 1px solid #3c3c3c;"
        )

    # ── Output ────────────────────────────────────────────────────────────────

    @pyqtSlot(str)
    def _append_output(self, line: str) -> None:
        self._full_log.append(line)

        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        lower = line.lower()
        if "error" in lower or line.startswith("!"):
            fmt.setForeground(QColor("#f44747"))
        elif "warning" in lower:
            fmt.setForeground(QColor("#ffcc00"))
        elif line.startswith("["):
            fmt.setForeground(QColor("#9cdcfe"))
        else:
            fmt.setForeground(QColor("#d4d4d4"))

        cursor.insertText(line + "\n", fmt)
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    @pyqtSlot(bool, str)
    def _on_build_done(self, success: bool, message: str) -> None:
        # Ripristina pulsanti
        self._btn_stop.setEnabled(False)
        self._update_button_states(self._current_profile)

        color_bg  = "#1e3a1e" if success else "#3a1e1e"
        color_fg  = "#4caf50" if success else "#f44747"
        icon      = "✓" if success else "✗"

        self._output.appendHtml(
            f'<span style="color:{color_fg}"><b>{icon} {message}</b></span>'
        )
        self._status_bar.setText(f"{icon} {message}  — {self._current_profile}")
        self._status_bar.setStyleSheet(
            f"padding: 2px 8px; font-size: 11px; "
            f"background: {color_bg}; color: {color_fg}; border-top: 1px solid #3c3c3c;"
        )

        # Se il build è riuscito e ha generato un PDF, aggiorna l'anteprima.
        # Non condizionato a mw._preview_dock.isVisible(): se il dock
        # Anteprima è tabificato con quello di Build (comune, dato che li
        # apriamo entrambi durante una compilazione), isVisible() è False
        # ogni volta che la tab in primo piano è quella di Build — quindi la
        # condizione saltava l'aggiornamento quasi sempre, lasciando
        # l'anteprima sul PDF pre-compilazione (o vuota) finché l'utente non
        # forzava un refresh riselezionando manualmente il file .tex.
        # set_pdf_path() non ha bisogno che il pannello sia visibile: prepara
        # comunque il contenuto corretto, pronto non appena l'utente
        # riporta in primo piano quella tab.
        if success:
            pdf_path = self._find_generated_pdf()
            if pdf_path:
                mw = self.window()
                if hasattr(mw, "_preview_panel_dock"):
                    mw._preview_panel_dock.set_pdf_path(pdf_path)

                from config.settings import Settings
                if Settings.instance().get("build/clean_aux_after_compile", False):
                    self._clean_aux_files(pdf_path)

        # Abilita "Analizza con AI" — utile sia in caso di errore sia di successo
        self._btn_analyze_ai.setEnabled(True)

        # Parsing errori automatico — il log resta comunque la vista attiva:
        # la tab "Errori compilazione" si limita a mostrare un badge col
        # conteggio, senza sostituire la vista sul log grezzo.
        #
        # Non ci basiamo sul solo `success` (exit code): strumenti come
        # latexmk possono terminare con codice 0 anche quando pdflatex ha
        # riportato errori TeX nel log (es. "! Undefined control sequence"),
        # perché considerano "successo" l'aver comunque prodotto un PDF.
        # Analizziamo quindi sempre l'output quando c'è un parser configurato.
        n = 0
        if self._current_profile:
            output_text = "\n".join(self._full_log)
            source = None
            editor = self._mw._tab_manager.current_editor() if hasattr(self._mw, "_tab_manager") else None
            if editor:
                source = getattr(editor, "file_path", None)
            errors = self._bm.parse_errors(output_text, self._current_profile, source)
            self._show_errors(errors)
            n = len(errors)
        self.error_count_changed.emit(n)

    def _find_generated_pdf(self):
        """Trova il PDF generato dal file corrente (stesso nome, stessa directory)."""
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
        """
        Elimina i file ausiliari accanto al PDF appena generato (stesso nome,
        stessa cartella). Chiamata solo dopo una compilazione riuscita e solo
        se l'opzione è attiva — il PDF stesso non è mai toccato.
        Se "build/keep_synctex" è attivo, .synctex.gz è escluso dalla pulizia
        perché serve alla sincronizzazione sorgente↔PDF anche dopo il build.
        """
        from config.settings import Settings
        from core.build_manager import clean_aux_files
        keep_synctex = Settings.instance().get("build/keep_synctex", True)
        base = pdf_path.with_suffix("")
        removed = clean_aux_files(base, keep_synctex=keep_synctex)
        if removed:
            self._output.appendHtml(
                '<span style="color:#858585">🧹 '
                f'{tr("build_panel.aux_cleaned", n=len(removed), files=", ".join(removed))}'
                '</span>'
            )

    def _clear_output(self) -> None:
        self._output.clear()
        self._full_log.clear()
        self._btn_analyze_ai.setEnabled(False)

    def _analyze_with_ai(self) -> None:
        """Apre il dialogo di conferma e invia il log all'AI selezionata."""
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

        # Recupera il pannello AI dal plugin manager
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

        # Imposta provider
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
            # Il provider change ha avviato un fetch asincrono; aspettiamo il segnale.
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

    @pyqtSlot(list)
    def _show_errors(self, errors: list) -> None:
        self._error_tree.clear()
        for err in errors:
            item = QTreeWidgetItem(self._error_tree, [
                str(err.get("file", "")),
                str(err.get("line", "")),
                err.get("message", "")[:200],
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, err)
            if "error" in err.get("message", "").lower():
                item.setForeground(0, QColor("#f44747"))
                item.setForeground(2, QColor("#f44747"))

        self._current_error_idx = -1
        has_errors = self._error_tree.topLevelItemCount() > 0
        self._btn_next_error.setEnabled(has_errors)
        self._btn_prev_error.setEnabled(has_errors)

    # ── Navigazione errori (stile TeXstudio F4) ─────────────────────────────────

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
            f"⚠  Errore {self._current_error_idx + 1}/{n}: {item.text(2)}"
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
    """Tab per eseguire task arbitrari (Makefile, npm, pyproject, comando libero)."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self._mw = main_window
        self._worker = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Riga: input + pulsanti
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
        self._btn_refresh = QPushButton("↺")
        self._btn_refresh.setFixedWidth(30)
        self._btn_refresh.setToolTip(tr("tooltip.build_reload_tasks"))
        self._btn_refresh.clicked.connect(self._discover)
        row.addWidget(self._cmd_edit, 1)
        row.addWidget(self._btn_run)
        row.addWidget(self._btn_stop)
        row.addWidget(self._btn_refresh)
        layout.addLayout(row)

        # Lista task scoperti
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

        # Output
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

        QTimer.singleShot(500, self._discover)

    def _discover(self) -> None:
        self._task_list.clear()
        editor = self._mw._tab_manager.current_editor() if hasattr(self._mw, "_tab_manager") else None
        path = getattr(editor, "file_path", None) if editor else None
        directory = path.parent if path else None
        if not directory:
            self._task_list.addItem(tr("build_panel.task_open_file"))
            return
        from core.build_manager import BuildManager
        tasks = BuildManager.discover_tasks(directory)
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
        cwd    = str(path.parent) if path else "."
        self._output.clear()
        self._output.appendPlainText(f"$ {cmd}\n")
        self._btn_run.setEnabled(False)
        self._btn_stop.setEnabled(True)

        from core.build_manager import BuildWorker
        import os
        self._worker = BuildWorker(cmd, cwd, dict(os.environ))
        self._worker.output_line.connect(self._on_output)
        self._worker.finished_ok.connect(lambda _secs: self._on_done(True))
        self._worker.finished_err.connect(lambda _code: self._on_done(False))
        self._worker.stopped.connect(lambda: self._on_done(False))
        self._worker.start()

    def _stop(self) -> None:
        if self._worker:
            self._worker.abort()

    def _on_output(self, line: str) -> None:
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        if "error" in line.lower():
            fmt.setForeground(QColor("#f44747"))
        elif "warning" in line.lower():
            fmt.setForeground(QColor("#ffcc00"))
        else:
            fmt.setForeground(QColor("#d4d4d4"))
        cursor.insertText(line + "\n", fmt)
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    def _on_done(self, ok: bool) -> None:
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        color = "#4caf50" if ok else "#f44747"
        icon  = "✓" if ok else "✗"
        self._output.appendHtml(f'<span style="color:{color}"><b>{icon} {tr("build_panel.task_done_ok") if ok else tr("build_panel.task_done_fail")}</b></span>')


# ─── Dialog configurazione profili ───────────────────────────────────────────

class BuildProfilesDialog(QDialog):
    """Dialog per creare/modificare/eliminare i profili di compilazione."""

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._mw = main_window
        self._bm = BuildManager.instance()
        self._dirty = False   # profilo corrente modificato ma non salvato

        # Determina il profilo attivo per il file corrente
        self._active_profile_name: str = ""
        editor = main_window._tab_manager.current_editor() if hasattr(main_window, '_tab_manager') else None
        if editor and getattr(editor, 'file_path', None):
            self._active_profile_name = self._bm.get_profile_for_file(editor.file_path) or ""

        self.setWindowTitle(tr("action.build_profiles", default="Profili di compilazione"))
        self.resize(800, 520)
        self._build_ui()
        self._load_profiles()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        main = QHBoxLayout()
        outer.addLayout(main, 1)

        # ── Colonna sinistra: lista profili ───────────────────────────────────
        left = QVBoxLayout()

        lbl = QLabel(tr("build_panel.available_profiles"))
        lbl.setStyleSheet("font-weight: bold;")
        left.addWidget(lbl)

        # Banner profilo attivo
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

        # Pulsanti ▲/▼ a fianco della lista
        move_col = QVBoxLayout()
        self._btn_up = QPushButton("▲")
        self._btn_down = QPushButton("▼")
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

        self._btn_set_active = QPushButton("▶  " + tr("button.set_active"))
        self._btn_set_active.setToolTip(tr("tooltip.build_set_active"))
        self._btn_set_active.setStyleSheet(
            "font-weight: bold; padding: 4px 8px; "
            "background: #264f78; color: #9cdcfe; border: 1px solid #9cdcfe;"
        )
        self._btn_set_active.clicked.connect(self._set_as_active)
        left.addWidget(self._btn_set_active)

        main.addLayout(left, 1)

        # Separatore verticale
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        main.addWidget(sep)

        # ── Colonna destra: form dettaglio ────────────────────────────────────
        right = QVBoxLayout()

        self._grp = QGroupBox(tr("build_panel.profile_config_title"))
        form = QFormLayout(self._grp)
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
        self._regex_edit   = QLineEdit()
        self._regex_edit.setPlaceholderText(r'es. File "([^"]+)", line (\d+)')
        self._regex_edit.setToolTip(tr("tooltip.build_error_regex"))

        form.addRow(tr("build_panel.profile_name_label"),    self._name_edit)
        form.addRow(tr("build_panel.extensions_label"),       self._ext_edit)
        form.addRow(tr("action.compile", default="Compila") + " →", self._compile_edit)
        form.addRow(tr("action.run",     default="Esegui")  + " →", self._run_edit)
        form.addRow(tr("action.build",   default="Build")   + " →", self._build_edit)
        form.addRow(tr("build_panel.error_regex_label"),     self._regex_edit)

        _vs = tr("build_panel.vars_syntax")
        var_lbl = QLabel(
            f"<small><b>{tr('build_panel.vars_title')}</b> ({_vs} <code>${{VAR}}</code> {tr('build_panel.vars_or')} <code>$(VAR)</code>):<br>"
            "<table cellspacing='2'>"
            f"<tr><td><code>${{FILE}}</code></td><td>— {tr('build_panel.var_file_desc')}&nbsp;&nbsp;</td>"
            "<td><i>es. /home/user/doc/main.py</i></td></tr>"
            f"<tr><td><code>${{DIR}}</code></td><td>— {tr('build_panel.var_dir_desc')}</td>"
            "<td><i>es. /home/user/doc</i></td></tr>"
            f"<tr><td><code>${{FILENAME}}</code></td><td>— {tr('build_panel.var_filename_desc')}</td>"
            "<td><i>es. main.py</i></td></tr>"
            f"<tr><td><code>${{BASENAME}}</code></td><td>— {tr('build_panel.var_basename_desc')}</td>"
            "<td><i>es. main</i></td></tr>"
            f"<tr><td><code>${{BASEFILE}}</code></td><td>— {tr('build_panel.var_basefile_desc')}</td>"
            "<td><i>es. /home/user/doc/main</i></td></tr>"
            f"<tr><td><code>${{EXT}}</code></td><td>— {tr('build_panel.var_ext_desc')}</td>"
            "<td><i>es. .py</i></td></tr>"
            f"<tr><td><code>${{LINE}}</code></td><td>— {tr('build_panel.var_line_desc')}</td>"
            "<td><i>es. 42</i></td></tr>"
            f"<tr><td><code>${{COL}}</code></td><td>— {tr('build_panel.var_col_desc')}</td>"
            "<td><i>es. 7</i></td></tr>"
            "</table></small>"
        )
        var_lbl.setTextFormat(Qt.TextFormat.RichText)
        var_lbl.setWordWrap(True)
        form.addRow("", var_lbl)

        right.addWidget(self._grp, 1)

        # Collega i campi al flag dirty
        for w in [self._name_edit, self._ext_edit, self._compile_edit,
                  self._run_edit, self._build_edit, self._regex_edit]:
            w.textChanged.connect(self._mark_dirty)

        # Barra stato salvataggio
        self._save_status = QLabel("")
        self._save_status.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(self._save_status)

        # Pulsante salva
        save_row = QHBoxLayout()
        save_row.addStretch()
        self._btn_save = QPushButton("💾  " + tr("button.save", default="Salva profilo"))
        self._btn_save.setMinimumWidth(160)
        self._btn_save.setStyleSheet("font-weight: bold; padding: 4px 12px;")
        self._btn_save.clicked.connect(self._save_current)
        save_row.addWidget(self._btn_save)
        right.addLayout(save_row)

        # Nota built-in
        self._note_builtin = QLabel(
            tr("build_panel.save_prompt")
        )
        self._note_builtin.setStyleSheet("color: #858585; font-size: 11px;")
        self._note_builtin.setWordWrap(True)
        self._note_builtin.setVisible(False)
        right.addWidget(self._note_builtin)

        main.addLayout(right, 2)

        # ── Pulsante Chiudi ───────────────────────────────────────────────────
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self._on_close)
        outer.addWidget(buttons)

    # ── Caricamento lista ─────────────────────────────────────────────────────

    def _load_profiles(self) -> None:
        self._profile_list.clear()
        profiles = self._bm.get_profiles()
        active_row = 0
        for i, name in enumerate(profiles):
            is_active = (name == self._active_profile_name)
            label = f"▶  {name}" if is_active else f"    {name}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)  # nome reale senza prefisso
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

        # Blocca il segnale dirty durante il caricamento
        self._dirty = False
        self._name_edit.setText(name)
        exts = profile.get("extensions", [])
        self._ext_edit.setText("  ".join(exts))
        self._compile_edit.setText(profile.get("compile", ""))
        self._run_edit.setText(    profile.get("run",     ""))
        self._build_edit.setText(  profile.get("build",   ""))
        self._regex_edit.setText(  profile.get("error_regex", ""))
        self._dirty = False

        # Mostra nota built-in
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

    def _set_as_active(self) -> None:
        """Forza il profilo selezionato come attivo per l'estensione del file corrente."""
        current = self._profile_list.currentItem()
        if not current:
            return
        name = current.data(Qt.ItemDataRole.UserRole) or ""
        if not name:
            return
        # Override per-estensione (se disponibile)
        editor = self._mw._tab_manager.current_editor() if hasattr(self._mw, "_tab_manager") else None
        path = getattr(editor, "file_path", None) if editor else None
        ext = path.suffix.lower() if path else ""
        if ext:
            self._bm.set_profile_override(ext, name)
        else:
            self._bm._active_profile = name
        self._active_profile_name = name

        # Aggiorna banner
        self._active_banner.setText(tr("build_panel.active_profile_banner", name=name))
        self._active_banner.setStyleSheet(
            "background: #264f78; color: #9cdcfe; "
            "font-size: 12px; padding: 4px 6px; border-radius: 3px;"
        )

        # Aggiorna lista (grassetto/colore sul profilo attivo)
        for i in range(self._profile_list.count()):
            item = self._profile_list.item(i)
            iname = item.data(Qt.ItemDataRole.UserRole) or ""
            is_active = (iname == name)
            font = item.font()
            font.setBold(is_active)
            item.setFont(font)
            if is_active:
                item.setText(f"▶  {iname}")
                item.setForeground(QColor("#9cdcfe"))
                item.setBackground(QColor("#1e3a5f"))
                item.setToolTip(tr("tooltip.build_profile_active_manual"))
            else:
                item.setText(f"    {iname}")
                item.setBackground(QColor(0, 0, 0, 0))
                item.setForeground(self._profile_list.palette().color(
                    self._profile_list.palette().ColorRole.WindowText))

        # Notifica nel pannello build se aperto
        if hasattr(self._mw, '_build_panel') and self._mw._build_panel:
            bp = self._mw._build_panel
            if hasattr(bp, '_set_active_profile'):
                bp._set_active_profile(name)

    # ── Salvataggio ───────────────────────────────────────────────────────────

    def _save_current(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            self._save_status.setText(tr("build_panel.save_name_error"))
            self._save_status.setStyleSheet("color: #f44747; font-size: 11px;")
            return

        # Parse estensioni (accetta spazio, ; o ,)
        raw_exts = self._ext_edit.text().replace(";", " ").replace(",", " ").split()
        exts = []
        for e in raw_exts:
            e = e.strip()
            if e and not e.startswith("."):
                e = "." + e
            if e:
                exts.append(e.lower())

        profile = {
            "extensions":         exts,
            "compile":            self._compile_edit.text().strip(),
            "run":                self._run_edit.text().strip(),
            "build":              self._build_edit.text().strip(),
            "error_regex":        self._regex_edit.text().strip(),
            "error_file_group":   1,
            "error_line_group":   2,
        }
        self._bm.add_profile(name, profile)

        # Aggiorna lista se è un nome nuovo
        existing = self._find_item_by_name(name)
        if existing is None:
            label = f"▶  {name}" if name == self._active_profile_name else f"    {name}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(tr("tooltip.build_profile_user"))
            self._profile_list.addItem(item)
            self._profile_list.setCurrentItem(item)
        else:
            existing.setForeground(self._profile_list.palette().color(
                self._profile_list.palette().ColorRole.WindowText))

        self._dirty = False
        from core.build_manager import DEFAULT_PROFILES
        if name in DEFAULT_PROFILES:
            self._save_status.setText(tr("build_panel.save_override_ok"))
        else:
            self._save_status.setText(tr("build_panel.save_ok"))
        self._save_status.setStyleSheet("color: #4caf50; font-size: 11px;")
        # Aggiorna nota built-in (ora è un override, ma teniamo la nota informativa)
        self._note_builtin.setVisible(False)
        self._save_status.setStyleSheet("color: #4caf50; font-size: 11px;")
        self._btn_save.setStyleSheet("font-weight: bold; padding: 4px 12px;")
        self._note_builtin.setVisible(False)

        # Resetta il messaggio dopo 3 secondi
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(3000, lambda: self._save_status.setText(""))

    # ── Nuovo / Elimina ───────────────────────────────────────────────────────

    def _new_profile(self) -> None:
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, tr("build_panel.new_profile_title"), tr("build_panel.new_profile_prompt")
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        empty = {
            "extensions": [], "compile": "", "run": "", "build": "",
            "error_regex": "", "error_file_group": 1, "error_line_group": 2,
        }
        self._bm.add_profile(name, empty)
        item = QListWidgetItem(f"    {name}")
        item.setData(Qt.ItemDataRole.UserRole, name)
        item.setToolTip(tr("tooltip.build_profile_user"))
        self._profile_list.addItem(item)
        self._profile_list.setCurrentItem(item)

    def _find_item_by_name(self, name: str):
        """Trova un QListWidgetItem per nome reale (UserRole)."""
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
        """Chiamato dopo drag-and-drop: salva il nuovo ordine."""
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

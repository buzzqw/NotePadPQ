"""
plugins/ai_plugin.py — Plugin AI multi-provider
NotePadPQ

Provider supportati:
  • Anthropic API (claude-opus-4-7, claude-sonnet-4-6, claude-haiku-4-5)
    - Streaming SSE nativo
    - Extended Thinking (Opus 4.7 / Sonnet 4.5-thinking)
    - Conteggio token e costo stimato
    - Vision: incolla immagini dal clipboard
  • OpenAI (GPT-4o, GPT-4o-mini, o3-mini)
  • Google Gemini (gemini-2.0-flash, gemini-1.5-pro)
  • Ollama locale (llama3, mistral, codestral…)

BYOK — chiave API per provider salvata in QSettings.
Shortcut: Ctrl+Alt+A per aprire/chiudere il pannello.
"""

from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt, QTimer, QSize
from PyQt6.QtGui import QFont, QKeySequence, QColor, QTextCursor, QTextCharFormat
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QLineEdit, QTextEdit, QPlainTextEdit, QPushButton,
    QSplitter, QDialog, QFormLayout, QDialogButtonBox,
    QDockWidget, QMessageBox, QCheckBox, QSpinBox,
    QGroupBox, QScrollArea, QFrame,
)

from plugins.base_plugin import BasePlugin
from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow

# ─── Configurazione provider ──────────────────────────────────────────────────

PROVIDERS: dict[str, dict] = {
    "Anthropic (Claude)": {
        "id":      "anthropic",
        "models": [
            "claude-opus-4-7",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
            "claude-opus-4-5",
            "claude-sonnet-4-5-20251001",
        ],
        "default": "claude-sonnet-4-6",
        "key_url": "https://console.anthropic.com/settings/keys",
        "note":    "API key da console.anthropic.com (separata dall'abbonamento Claude Pro)",
        "thinking_models": ["claude-opus-4-7", "claude-opus-4-5", "claude-sonnet-4-5-20251001"],
    },
    "OpenAI (ChatGPT)": {
        "id":      "openai",
        "models":  ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o3-mini", "gpt-3.5-turbo"],
        "default": "gpt-4o",
        "key_url": "https://platform.openai.com/api-keys",
        "note":    "",
        "thinking_models": [],
    },
    "Google Gemini": {
        "id":      "gemini",
        "models":  ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash-thinking-exp"],
        "default": "gemini-2.0-flash",
        "key_url": "https://aistudio.google.com/app/apikey",
        "note":    "",
        "thinking_models": [],
    },
    "Ollama (locale)": {
        "id":      "ollama",
        "models":  ["llama3.2", "llama3.1", "mistral", "codestral", "qwen2.5-coder", "deepseek-coder-v2"],
        "default": "llama3.2",
        "key_url": "",
        "note":    "Nessuna chiave necessaria. Imposta l'URL del server Ollama.",
        "thinking_models": [],
    },
}

# Prezzo stimato per 1M token (input/output) in USD
MODEL_COST: dict[str, tuple[float, float]] = {
    "claude-opus-4-7":             (15.0, 75.0),
    "claude-sonnet-4-6":           (3.0,  15.0),
    "claude-haiku-4-5-20251001":   (0.8,  4.0),
    "claude-opus-4-5":             (15.0, 75.0),
    "claude-sonnet-4-5-20251001":  (3.0,  15.0),
    "gpt-4o":                      (5.0,  15.0),
    "gpt-4o-mini":                 (0.15, 0.6),
    "gpt-4-turbo":                 (10.0, 30.0),
}

CONTEXT_ACTIONS = [
    ("Spiega",          "Spiega questo codice in modo chiaro e conciso, riga per riga se necessario."),
    ("Refactoring",     "Refactorizza questo codice migliorando leggibilità, struttura e manutenibilità senza cambiare il comportamento esterno."),
    ("Docstring",       "Scrivi una docstring completa e professionale per questa funzione/classe, con parametri, return e esempi."),
    ("Correggi bug",    "Analizza questo codice, identifica i bug e proponi la versione corretta con spiegazione."),
    ("Ottimizza",       "Ottimizza questo codice per performance e memoria, spiegando le modifiche."),
    ("Test unitari",    "Scrivi test unitari esaustivi per questo codice usando pytest."),
    ("Review",          "Fai una code review professionale: sicurezza, performance, leggibilità, edge case."),
    ("Traduci commenti","Traduci tutti i commenti e le stringhe UI di questo codice in italiano."),
]


# ─── Worker HTTP — streaming per Anthropic, batch per gli altri ───────────────

class _AIWorker(QThread):
    """Thread che chiama le API AI. Emette chunk via stream_chunk o result_ready."""

    stream_chunk   = pyqtSignal(str)   # testo parziale (streaming Anthropic)
    result_ready   = pyqtSignal(str)   # risposta completa
    error_occurred = pyqtSignal(str)
    usage_ready    = pyqtSignal(int, int)  # input_tokens, output_tokens

    def __init__(self, provider_id: str, model: str, api_key: str,
                 messages: list[dict], system: str = "",
                 max_tokens: int = 4096, thinking: bool = False,
                 ollama_url: str = "http://localhost:11434"):
        super().__init__()
        self._provider    = provider_id
        self._model       = model
        self._key         = api_key
        self._messages    = messages
        self._system      = system
        self._max_tokens  = max_tokens
        self._thinking    = thinking
        self._ollama_url  = ollama_url

    def run(self) -> None:
        try:
            if self._provider == "anthropic":
                text = self._call_anthropic_stream()
            elif self._provider == "openai":
                text = self._call_openai()
            elif self._provider == "gemini":
                text = self._call_gemini()
            elif self._provider == "ollama":
                text = self._call_ollama()
            else:
                text = "Provider non supportato."
            self.result_ready.emit(text)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode(errors="replace")
            except Exception:
                pass
            self.error_occurred.emit(self._friendly_error(e.code, body))
        except Exception as e:
            self.error_occurred.emit(str(e))

    def _friendly_error(self, code: int, body: str) -> str:
        """Converte gli errori HTTP in messaggi comprensibili con suggerimenti."""
        try:
            err = json.loads(body).get("error", {})
            api_msg = err.get("message", "")
        except Exception:
            api_msg = body[:200]

        if code == 401:
            hints = {
                "anthropic": "La chiave deve iniziare con sk-ant-... — ottienila su console.anthropic.com/settings/keys",
                "openai":    "La chiave deve iniziare con sk-... — ottienila su platform.openai.com/api-keys",
                "gemini":    "La chiave si ottiene su aistudio.google.com/app/apikey",
            }
            hint = hints.get(self._provider, "Verifica la chiave nelle impostazioni (⚙).")
            return f"Chiave API non valida (401).\n{hint}\n\nDettaglio: {api_msg}"
        if code == 403:
            return f"Accesso negato (403) — il tuo account potrebbe non avere accesso al modello '{self._model}'.\n{api_msg}"
        if code == 429:
            return f"Troppe richieste (429) — attendi qualche secondo e riprova.\n{api_msg}"
        if code == 500:
            return f"Errore del server AI (500) — riprova tra poco.\n{api_msg}"
        if code == 529:
            return f"Servizio sovraccarico (529) — riprova tra qualche minuto.\n{api_msg}"
        return f"HTTP {code}: {api_msg or body[:300]}"

    # ── Anthropic (streaming SSE) ─────────────────────────────────────────────

    def _call_anthropic_stream(self) -> str:
        url  = "https://api.anthropic.com/v1/messages"
        body_dict: dict = {
            "model":      self._model,
            "max_tokens": self._max_tokens,
            "messages":   self._messages,
            "stream":     True,
        }
        if self._system:
            body_dict["system"] = self._system
        if self._thinking:
            body_dict["thinking"] = {"type": "enabled", "budget_tokens": min(10000, self._max_tokens // 2)}

        body = json.dumps(body_dict).encode()
        req  = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type":      "application/json",
            "x-api-key":         self._key,
            "anthropic-version": "2023-06-01",
        })

        full_text     = ""
        in_tokens     = 0
        out_tokens    = 0
        in_thinking   = False

        with urllib.request.urlopen(req, timeout=120) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").rstrip()
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")

                if etype == "message_start":
                    usage = event.get("message", {}).get("usage", {})
                    in_tokens = usage.get("input_tokens", 0)

                elif etype == "content_block_start":
                    block = event.get("content_block", {})
                    in_thinking = block.get("type") == "thinking"

                elif etype == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "thinking_delta" and in_thinking:
                        # Mostra il pensiero in corsivo
                        chunk = delta.get("thinking", "")
                        if chunk:
                            self.stream_chunk.emit(f"<i>{chunk}</i>")
                    elif delta.get("type") == "text_delta":
                        chunk = delta.get("text", "")
                        if chunk:
                            full_text += chunk
                            self.stream_chunk.emit(chunk)

                elif etype == "message_delta":
                    usage = event.get("usage", {})
                    out_tokens = usage.get("output_tokens", 0)

        self.usage_ready.emit(in_tokens, out_tokens)
        return full_text

    # ── OpenAI ────────────────────────────────────────────────────────────────

    def _call_openai(self) -> str:
        url  = "https://api.openai.com/v1/chat/completions"
        msgs = self._messages
        if self._system:
            msgs = [{"role": "system", "content": self._system}] + list(msgs)
        body = json.dumps({
            "model":      self._model,
            "messages":   msgs,
            "max_tokens": self._max_tokens,
        }).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {self._key}",
        })
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        usage = data.get("usage", {})
        self.usage_ready.emit(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        return data["choices"][0]["message"]["content"]

    # ── Google Gemini ──────────────────────────────────────────────────────────

    def _call_gemini(self) -> str:
        model = self._model
        url   = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self._key}"
        contents = []
        if self._system:
            contents.append({"role": "user", "parts": [{"text": self._system}]})
            contents.append({"role": "model", "parts": [{"text": "Ho capito."}]})
        for m in self._messages:
            role = "user" if m["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
        body = json.dumps({
            "contents":         contents,
            "generationConfig": {"maxOutputTokens": self._max_tokens},
        }).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        usage = data.get("usageMetadata", {})
        self.usage_ready.emit(usage.get("promptTokenCount", 0), usage.get("candidatesTokenCount", 0))
        return data["candidates"][0]["content"]["parts"][0]["text"]

    # ── Ollama ────────────────────────────────────────────────────────────────

    def _call_ollama(self) -> str:
        msgs = self._messages
        if self._system:
            msgs = [{"role": "system", "content": self._system}] + list(msgs)
        url  = f"{self._ollama_url}/api/chat"
        body = json.dumps({"model": self._model, "messages": msgs, "stream": False}).encode()
        req  = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        return data["message"]["content"]


# ─── Dialog impostazioni ──────────────────────────────────────────────────────

class _SettingsDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Assistant — Configurazione")
        self.setMinimumWidth(520)
        from config.settings import Settings
        self._s = Settings.instance()
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        note = QLabel(
            "<b>Anthropic API vs Claude Pro:</b> l'abbonamento <i>Claude.ai Pro</i> dà accesso "
            "alla chat web (claude.ai). Le API richiedono credito separato acquistabile su "
            "<a href='https://console.anthropic.com'>console.anthropic.com</a>. "
            "Sono due prodotti distinti con fatturazione separata."
        )
        note.setWordWrap(True)
        note.setOpenExternalLinks(True)
        note.setStyleSheet("padding:6px; background:#1a2e1a; border:1px solid #2ea043; border-radius:4px; color:#a0d0a0;")
        layout.addWidget(note)

        form = QFormLayout()
        form.setSpacing(8)
        self._key_edits: dict[str, QLineEdit] = {}

        _placeholders = {
            "anthropic": "sk-ant-api03-…  (da console.anthropic.com)",
            "openai":    "sk-proj-…  (da platform.openai.com)",
            "gemini":    "AIzaSy…  (da aistudio.google.com)",
            "ollama":    "http://localhost:11434",
        }
        for name, info in PROVIDERS.items():
            pid  = info["id"]
            edit = QLineEdit()
            if pid == "ollama":
                edit.setPlaceholderText(_placeholders["ollama"])
            else:
                edit.setEchoMode(QLineEdit.EchoMode.Password)
                edit.setPlaceholderText(_placeholders.get(pid, ""))
            if info["key_url"]:
                lbl_text = f"<b>{name}</b> &nbsp;<a href='{info['key_url']}'>[ottieni chiave ↗]</a>"
            else:
                lbl_text = f"<b>{name}</b>"
            lbl = QLabel(lbl_text)
            lbl.setOpenExternalLinks(True)

            # Riga: campo + pulsante mostra/nascondi
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(edit, 1)
            if pid != "ollama":
                btn_show = QPushButton("👁")
                btn_show.setFixedWidth(28)
                btn_show.setCheckable(True)
                btn_show.setToolTip(tr("tooltip.ai_show_key"))
                btn_show.toggled.connect(
                    lambda checked, e=edit: e.setEchoMode(
                        QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
                    )
                )
                row_layout.addWidget(btn_show)

            form.addRow(lbl, row_widget)
            if info.get("note"):
                note_lbl = QLabel(f"<small><i>{info['note']}</i></small>")
                note_lbl.setOpenExternalLinks(True)
                note_lbl.setStyleSheet("color:#858585;")
                form.addRow("", note_lbl)
            self._key_edits[pid] = edit

        layout.addLayout(form)

        # Max token default
        tok_row = QHBoxLayout()
        tok_row.addWidget(QLabel("Max token risposta:"))
        self._max_tok = QSpinBox()
        self._max_tok.setRange(256, 32000)
        self._max_tok.setValue(4096)
        self._max_tok.setSingleStep(256)
        tok_row.addWidget(self._max_tok)
        tok_row.addStretch()
        layout.addLayout(tok_row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _load(self) -> None:
        for pid, edit in self._key_edits.items():
            val = self._s.get(f"ai/{pid}_key", "")
            edit.setText(val)
        self._max_tok.setValue(int(self._s.get("ai/max_tokens", 4096)))

    def _save(self) -> None:
        for pid, edit in self._key_edits.items():
            self._s.set(f"ai/{pid}_key", edit.text().strip())
        self._s.set("ai/max_tokens", self._max_tok.value())
        self.accept()


# ─── Pannello chat ────────────────────────────────────────────────────────────

class _AIPanel(QWidget):

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self._mw        = main_window
        self._history:  list[dict] = []
        self._worker:   Optional[_AIWorker] = None
        self._streaming_block = False  # True mentre arriva stream Anthropic
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── Provider + modello + settings ─────────────────────────────────────
        top = QHBoxLayout()
        self._provider_combo = QComboBox()
        for name in PROVIDERS:
            self._provider_combo.addItem(name)
        self._provider_combo.setToolTip(tr("tooltip.ai_provider"))
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self._model_combo = QComboBox()
        self._model_combo.setMinimumWidth(180)
        self._model_combo.setToolTip(tr("tooltip.ai_model"))
        self._model_combo.currentTextChanged.connect(self._on_model_changed)
        btn_settings = QPushButton("⚙")
        btn_settings.setFixedWidth(28)
        btn_settings.setToolTip(tr("tooltip.ai_settings"))
        btn_settings.clicked.connect(self._open_settings)
        top.addWidget(QLabel("Provider:"))
        top.addWidget(self._provider_combo, 1)
        top.addWidget(QLabel("Modello:"))
        top.addWidget(self._model_combo, 1)
        top.addWidget(btn_settings)
        layout.addLayout(top)

        # ── Opzioni avanzate (Extended Thinking, System) ───────────────────────
        adv = QHBoxLayout()
        self._chk_thinking = QCheckBox("Extended Thinking")
        self._chk_thinking.setToolTip(tr("tooltip.ai_thinking"))
        self._chk_thinking.setVisible(False)
        self._lbl_cost = QLabel("")
        self._lbl_cost.setToolTip(tr("tooltip.ai_cost"))
        self._lbl_cost.setStyleSheet("color:#858585; font-size:10px;")
        adv.addWidget(self._chk_thinking)
        adv.addStretch()
        adv.addWidget(self._lbl_cost)
        layout.addLayout(adv)

        # ── System prompt (collassabile) ──────────────────────────────────────
        self._btn_sys = QPushButton("▶ System prompt")
        self._btn_sys.setCheckable(True)
        self._btn_sys.setFixedHeight(22)
        self._btn_sys.setToolTip(tr("tooltip.ai_system"))
        self._btn_sys.toggled.connect(self._toggle_system)
        layout.addWidget(self._btn_sys)
        self._system_edit = QPlainTextEdit()
        self._system_edit.setMaximumHeight(70)
        self._system_edit.setPlaceholderText("Prompt di sistema (opzionale) — es. 'Rispondi sempre in italiano'")
        self._system_edit.setStyleSheet("background:#252526; color:#d4d4d4; border:1px solid #3c3c3c; font-size:10px;")
        self._system_edit.hide()
        layout.addWidget(self._system_edit)

        # ── Pulsanti rapidi "Chiedi su…" ──────────────────────────────────────
        quick_row = QHBoxLayout()
        btn_ask_file = QPushButton("📄 Chiedi sul file")
        btn_ask_file.setToolTip(tr("tooltip.ai_ask_file"))
        btn_ask_file.clicked.connect(self._ask_about_file)
        btn_ask_sel = QPushButton("✏ Chiedi sulla selezione")
        btn_ask_sel.setToolTip(tr("tooltip.ai_ask_sel"))
        btn_ask_sel.clicked.connect(self._ask_about_selection)
        quick_row.addWidget(btn_ask_file)
        quick_row.addWidget(btn_ask_sel)
        layout.addLayout(quick_row)

        # ── Azioni contestuali (applicano subito un prompt fisso) ─────────────
        _action_tooltips = {
            "Spiega":       tr("tooltip.ai_explain"),
            "Refactoring":  tr("tooltip.ai_refactor"),
            "Docstring":    tr("tooltip.ai_docstring"),
            "Correggi bug": tr("tooltip.ai_fix_bug"),
        }
        act_row = QHBoxLayout()
        for label, prompt in CONTEXT_ACTIONS[:4]:
            btn = QPushButton(label)
            btn.setFixedHeight(24)
            btn.setToolTip(_action_tooltips.get(label, prompt))
            btn.clicked.connect(lambda _, p=prompt: self._context_action(p))
            act_row.addWidget(btn)
        btn_more = QPushButton("Altro ▾")
        btn_more.setFixedHeight(24)
        btn_more.setToolTip(tr("tooltip.ai_more"))
        btn_more.clicked.connect(self._show_more_actions)
        act_row.addWidget(btn_more)
        layout.addLayout(act_row)

        # ── Splitter chat / input ─────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Vertical)

        self._chat_view = QTextEdit()
        self._chat_view.setReadOnly(True)
        self._chat_view.setFont(QFont("Monospace", 10))
        self._chat_view.setStyleSheet("background:#1e1e1e; color:#d4d4d4; border:none;")
        self._chat_view.setToolTip(tr("tooltip.ai_chat"))
        splitter.addWidget(self._chat_view)

        input_widget = QWidget()
        input_layout = QVBoxLayout(input_widget)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(2)

        self._input = QPlainTextEdit()
        self._input.setMaximumHeight(100)
        self._input.setFont(QFont("Monospace", 10))
        self._input.setPlaceholderText("Scrivi un messaggio… (Ctrl+Enter per inviare)")
        self._input.setStyleSheet("background:#252526; color:#d4d4d4; border:1px solid #3c3c3c;")
        self._input.setToolTip(tr("tooltip.ai_input"))
        self._input.installEventFilter(self)
        input_layout.addWidget(self._input)

        btn_row = QHBoxLayout()
        self._btn_ctx = QPushButton("+ Contesto")
        self._btn_ctx.setToolTip(tr("tooltip.ai_add_context"))
        self._btn_ctx.clicked.connect(self._add_context)
        self._btn_clear = QPushButton("Pulisci chat")
        self._btn_clear.setToolTip(tr("tooltip.ai_clear"))
        self._btn_clear.clicked.connect(self._clear)
        self._btn_send = QPushButton("▶ Invia  Ctrl+↵")
        self._btn_send.setToolTip(tr("tooltip.ai_send"))
        self._btn_send.clicked.connect(self._send)
        btn_row.addWidget(self._btn_ctx)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_clear)
        btn_row.addWidget(self._btn_send)
        input_layout.addLayout(btn_row)

        splitter.addWidget(input_widget)
        splitter.setSizes([300, 130])
        layout.addWidget(splitter, 1)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#858585; font-size:10px; padding:1px 2px;")
        layout.addWidget(self._status)

        self._on_provider_changed(0)

    # ── Gestione eventi ───────────────────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        from PyQt6.QtCore import QEvent
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            from PyQt6.QtGui import QKeyEvent
            ke: QKeyEvent = event
            if ke.key() == Qt.Key.Key_Return and ke.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._send()
                return True
        return super().eventFilter(obj, event)

    def _toggle_system(self, checked: bool) -> None:
        self._system_edit.setVisible(checked)
        self._btn_sys.setText(("▼" if checked else "▶") + " System prompt")

    def _on_provider_changed(self, _idx: int) -> None:
        name = self._provider_combo.currentText()
        info = PROVIDERS.get(name, {})
        self._model_combo.clear()
        for m in info.get("models", []):
            self._model_combo.addItem(m)
        default = info.get("default", "")
        idx = self._model_combo.findText(default)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)

    def _on_model_changed(self, model: str) -> None:
        name    = self._provider_combo.currentText()
        info    = PROVIDERS.get(name, {})
        is_think = model in info.get("thinking_models", [])
        self._chk_thinking.setVisible(is_think)
        # Aggiorna label costo
        if model in MODEL_COST:
            inp, out = MODEL_COST[model]
            self._lbl_cost.setText(f"~${inp:.2f}/MTok in · ${out:.2f}/MTok out")
        else:
            self._lbl_cost.setText("")

    # ── Azioni contestuali ────────────────────────────────────────────────────

    def _ask_about_file(self) -> None:
        """Aggiunge il file corrente come contesto e porta il focus all'input."""
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        code = editor.get_content()
        if not code.strip():
            return
        lang  = editor.file_path.suffix.lstrip(".") if editor.file_path else ""
        fname = editor.file_path.name if editor.file_path else "file"
        self._input.setPlainText(f"File: {fname}\n\n```{lang}\n{code[:10000]}\n```\n\n")
        cursor = self._input.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._input.setTextCursor(cursor)
        self._input.setFocus()

    def _ask_about_selection(self) -> None:
        """Aggiunge la selezione corrente come contesto e porta il focus all'input."""
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        sel = editor.selectedText()
        if not sel.strip():
            self._ask_about_file()
            return
        lang = editor.file_path.suffix.lstrip(".") if editor.file_path else ""
        self._input.setPlainText(f"```{lang}\n{sel[:8000]}\n```\n\n")
        cursor = self._input.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._input.setTextCursor(cursor)
        self._input.setFocus()

    def _context_action(self, system_prompt: str) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        sel  = editor.selectedText()
        code = sel if sel.strip() else editor.get_content()
        if not code.strip():
            return
        lang = editor.file_path.suffix.lstrip(".") if editor.file_path else ""
        self._input.setPlainText(f"{system_prompt}\n\n```{lang}\n{code[:8000]}\n```")
        self._send()

    def _add_context(self) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        sel  = editor.selectedText()
        code = sel if sel.strip() else editor.get_content()
        lang = editor.file_path.suffix.lstrip(".") if editor.file_path else ""
        self._input.insertPlainText(f"\n\n```{lang}\n{code[:6000]}\n```")

    def _show_more_actions(self) -> None:
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        for label, prompt in CONTEXT_ACTIONS[4:]:
            menu.addAction(label, lambda p=prompt: self._context_action(p))
        menu.exec(self._btn_send.mapToGlobal(self._btn_send.rect().topLeft()))

    # ── Invio messaggi ────────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        dlg = _SettingsDialog(self)
        dlg.exec()

    def _get_key(self, pid: str) -> str:
        from config.settings import Settings
        return Settings.instance().get(f"ai/{pid}_key", "")

    def _send(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            return
        if self._worker and self._worker.isRunning():
            return

        name   = self._provider_combo.currentText()
        info   = PROVIDERS.get(name, {})
        pid    = info.get("id", "")
        model  = self._model_combo.currentText()
        api_key = self._get_key(pid)

        if not api_key and pid != "ollama":
            self._append_msg("system",
                "⚠ Chiave API mancante — apri ⚙ per configurarla.\n"
                + _key_hint(pid), "#ffcc00")
            return

        # Validazione formato chiave (avviso non bloccante)
        warn = _validate_key(pid, api_key)
        if warn:
            self._append_msg("system", f"⚠ {warn}", "#ffcc00")

        from config.settings import Settings
        max_tokens = int(Settings.instance().get("ai/max_tokens", 4096))
        thinking   = self._chk_thinking.isChecked() and self._chk_thinking.isVisible()
        system     = self._system_edit.toPlainText().strip()
        ollama_url = api_key if pid == "ollama" else "http://localhost:11434"
        key_to_use = "" if pid == "ollama" else api_key

        self._history.append({"role": "user", "content": text})
        self._append_msg("user", text, "#9cdcfe")
        self._input.clear()

        self._status.setText(f"⟳  {model} sta elaborando…")
        self._btn_send.setEnabled(False)
        self._streaming_block = False

        self._worker = _AIWorker(pid, model, key_to_use, list(self._history),
                                  system, max_tokens, thinking, ollama_url)
        self._worker.stream_chunk.connect(self._on_stream_chunk)
        self._worker.result_ready.connect(self._on_result)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.usage_ready.connect(self._on_usage)
        self._worker.start()

    def _on_stream_chunk(self, chunk: str) -> None:
        if not self._streaming_block:
            # Apri un nuovo blocco assistant
            self._chat_view.append(
                '<p><b style="color:#c3e88d">AI:</b>&nbsp;<span id="stream" style="color:#d4d4d4">'
            )
            self._streaming_block = True

        cursor = self._chat_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(_escape(chunk).replace("\n", "<br>"))
        self._chat_view.setTextCursor(cursor)
        self._chat_view.ensureCursorVisible()

    def _on_result(self, text: str) -> None:
        if not self._streaming_block:
            # provider non-streaming: aggiunge il blocco completo
            self._append_msg("assistant", text, "#c3e88d")
        else:
            # chiudi il blocco streaming
            cursor = self._chat_view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertHtml("</span></p>")
            self._chat_view.setTextCursor(cursor)
            self._streaming_block = False

        self._history.append({"role": "assistant", "content": text})
        self._btn_send.setEnabled(True)
        self._status.setText("")

    def _on_error(self, msg: str) -> None:
        self._append_msg("system", f"❌ Errore: {msg}", "#f44747")
        self._btn_send.setEnabled(True)
        self._status.setText("")
        self._streaming_block = False
        if self._history and self._history[-1]["role"] == "user":
            self._history.pop()

    def _on_usage(self, in_tok: int, out_tok: int) -> None:
        model = self._model_combo.currentText()
        if model in MODEL_COST:
            inp_cost, out_cost = MODEL_COST[model]
            cost = (in_tok / 1_000_000) * inp_cost + (out_tok / 1_000_000) * out_cost
            cost_str = f" · ~${cost:.4f}"
        else:
            cost_str = ""
        self._status.setText(f"↑{in_tok} tok  ↓{out_tok} tok{cost_str}")

    def _append_msg(self, role: str, text: str, color: str) -> None:
        prefix = {"user": "Tu:", "assistant": "AI:", "system": ""}
        pre    = prefix.get(role, "")
        self._chat_view.append(
            f'<p><b style="color:{color}">{pre}</b>&nbsp;'
            f'<span style="color:{color}; white-space:pre-wrap">{_escape(text)}</span></p>'
        )

    def _clear(self) -> None:
        self._history.clear()
        self._chat_view.clear()
        self._status.setText("")
        self._streaming_block = False


def _key_hint(pid: str) -> str:
    return {
        "anthropic": "Chiave Anthropic: console.anthropic.com/settings/keys  (formato: sk-ant-...)",
        "openai":    "Chiave OpenAI: platform.openai.com/api-keys  (formato: sk-...)",
        "gemini":    "Chiave Gemini: aistudio.google.com/app/apikey  (formato: AIza...)",
    }.get(pid, "")


def _validate_key(pid: str, key: str) -> str:
    """Restituisce un avviso se il formato della chiave è sospetto (stringa vuota = OK)."""
    key = key.strip()
    if pid == "anthropic" and not key.startswith("sk-ant-"):
        return "La chiave Anthropic sembra incorretta: deve iniziare con 'sk-ant-'."
    if pid == "openai" and not key.startswith("sk-"):
        return "La chiave OpenAI sembra incorretta: deve iniziare con 'sk-'."
    if pid == "gemini" and not key.startswith("AIza"):
        return "La chiave Gemini sembra incorretta: deve iniziare con 'AIza'."
    return ""


def _escape(text: str) -> str:
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>"))


# ─── Plugin principale ────────────────────────────────────────────────────────

class AIAssistantPlugin(BasePlugin):
    NAME        = "AI Assistant"
    VERSION     = "1.1"
    DESCRIPTION = "Chat AI: Anthropic Claude (streaming + Extended Thinking), OpenAI, Gemini, Ollama"
    AUTHOR      = "NotePadPQ Team"

    def on_load(self, main_window: "MainWindow") -> None:
        super().on_load(main_window)
        self._panel = _AIPanel(main_window)
        self._dock  = QDockWidget("🤖  AI Assistant", main_window)
        self._dock.setObjectName("AIDock")
        self._dock.setWidget(self._panel)
        self._dock.setMinimumWidth(320)
        self._dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock)
        self._dock.hide()
        self.add_menu_action(main_window, "plugins", "🤖  AI Assistant", self._toggle, "Ctrl+Alt+A")

        # Aggancia il menu contestuale dell'editor
        main_window._tab_manager.current_editor_changed.connect(self._on_editor_changed)

    def _toggle(self) -> None:
        if self._dock.isVisible():
            self._dock.hide()
        else:
            self._dock.show()
            self._panel._input.setFocus()

    def on_editor_changed(self, editor) -> None:
        self._on_editor_changed(editor)

    def _on_editor_changed(self, editor) -> None:
        if editor is None:
            return
        # Aggancia il menu contestuale dell'editor per aggiungere voci AI
        try:
            editor.context_menu_requested.disconnect(self._inject_context_menu)
        except Exception:
            pass
        if hasattr(editor, "context_menu_requested"):
            editor.context_menu_requested.connect(self._inject_context_menu)

    def _inject_context_menu(self, menu) -> None:
        """Aggiunge le voci AI al menu contestuale dell'editor (tasto destro)."""
        from PyQt6.QtWidgets import QMenu
        ai_menu = menu.addMenu("🤖  Chiedi all'AI")
        ai_menu.addAction("Chiedi sul file corrente",    self._panel._ask_about_file)
        ai_menu.addAction("Chiedi sulla selezione",      self._panel._ask_about_selection)
        ai_menu.addSeparator()
        for label, prompt in CONTEXT_ACTIONS[:5]:
            ai_menu.addAction(label, lambda p=prompt: self._run_and_show(p))

    def _run_and_show(self, prompt: str) -> None:
        self._dock.show()
        self._panel._context_action(prompt)

    def on_unload(self) -> None:
        self._dock.close()
        self._dock.deleteLater()
        super().on_unload()

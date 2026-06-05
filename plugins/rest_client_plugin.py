"""
plugins/rest_client_plugin.py — REST / HTTP Client
NotePadPQ

Pannello dock per comporre ed eseguire richieste HTTP/REST.
Funzionalità:
  - Wizard step-by-step per costruire la richiesta
  - Metodi: GET POST PUT PATCH DELETE HEAD OPTIONS  (colori per metodo)
  - Headers personalizzati, autenticazione Bearer/Basic/API-Key
  - Body: nessuno, JSON, form-data, XML, testo libero
  - Variabili d'ambiente (profili: dev / staging / prod / custom)
  - Pretty-print JSON/XML nella risposta con syntax highlight
  - Salvataggio e caricamento collection in file .http (formato VS Code)
  - Cronologia delle ultime N richieste
  - UI ispirata a Insomnia / Thunder Client: splitter verticale, badge
    colorati per metodo HTTP, status badge, dimensione risposta in KB

Dipendenze: urllib (stdlib) — nessuna dipendenza esterna obbligatoria.
Opzionale: requests (pip install requests) per funzionalità avanzate
           e migliore gestione SSL/timeout.

Menu: Plugin → 🌐 REST Client  (Ctrl+Alt+R)
"""

from __future__ import annotations

import base64
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.dom.minidom
from typing import Dict, List, Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QColor, QFont, QKeySequence, QSyntaxHighlighter, QTextCharFormat
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QDockWidget,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QPushButton, QSizePolicy, QSplitter, QStackedWidget, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
    QWizard, QWizardPage, QSpinBox, QCheckBox, QInputDialog, QProgressBar,
)

from plugins.base_plugin import BasePlugin
from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


# ─── Costanti ────────────────────────────────────────────────────────────────

_HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
_AUTH_TYPES   = ["Nessuna", "Bearer Token", "Basic (user:pass)", "API Key (header)"]
_BODY_TYPES   = ["Nessuno", "JSON", "XML", "Form (x-www-form-urlencoded)", "Testo libero"]
_HISTORY_MAX  = 50

_CONTENT_TYPE_MAP = {
    "JSON":                          "application/json",
    "XML":                           "application/xml",
    "Form (x-www-form-urlencoded)":  "application/x-www-form-urlencoded",
    "Testo libero":                  "text/plain",
}

# Colori per metodo HTTP (ispirazione Insomnia / Thunder Client)
_METHOD_COLORS = {
    "GET":     "#61affe",   # blu chiaro
    "POST":    "#49cc90",   # verde
    "PUT":     "#fca130",   # arancione
    "PATCH":   "#50e3c2",   # teal
    "DELETE":  "#f93e3e",   # rosso
    "HEAD":    "#9012fe",   # viola
    "OPTIONS": "#0d5aa7",   # blu scuro
}

# Stile dark per le text area di codice
_CODE_AREA_STYLE = (
    "QTextEdit {"
    "  background: #1e1e1e;"
    "  color: #d4d4d4;"
    "  border: 1px solid #3c3c3c;"
    "  border-radius: 4px;"
    "  font-family: 'Cascadia Code', 'Fira Code', 'Courier New', monospace;"
    "  font-size: 11px;"
    "}"
)

# Stile per il pannello sinistra (collection/cronologia)
_SIDEBAR_STYLE = (
    "QListWidget {"
    "  background: #252526;"
    "  color: #cccccc;"
    "  border: none;"
    "  border-radius: 4px;"
    "  outline: none;"
    "}"
    "QListWidget::item { padding: 5px 8px; border-radius: 3px; }"
    "QListWidget::item:selected { background: #094771; color: #ffffff; }"
    "QListWidget::item:hover { background: #2a2d2e; }"
)


def _method_style(method: str) -> str:
    """Restituisce lo stylesheet per il ComboBox/label del metodo HTTP."""
    color = _METHOD_COLORS.get(method, "#888888")
    return (
        f"QComboBox {{ color: {color}; font-weight: bold; font-size: 12px;"
        f"  border: 2px solid {color}; border-radius: 4px;"
        f"  padding: 3px 6px; background: #1e1e1e; }}"
        f"QComboBox::drop-down {{ border: none; }}"
        f"QComboBox QAbstractItemView {{ color: #cccccc; background: #252526; }}"
    )


# ─── Modello dati ─────────────────────────────────────────────────────────────

class HttpRequest:
    """Dati di una singola richiesta HTTP."""

    def __init__(self):
        self.name: str = "Nuova richiesta"
        self.method: str = "GET"
        self.url: str = ""
        self.headers: Dict[str, str] = {}
        self.auth_type: str = "Nessuna"
        self.auth_value: str = ""          # token / user:pass / api-key
        self.auth_header: str = "X-Api-Key"
        self.body_type: str = "Nessuno"
        self.body: str = ""
        self.env_profile: str = "dev"

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "method":      self.method,
            "url":         self.url,
            "headers":     self.headers,
            "auth_type":   self.auth_type,
            "auth_value":  self.auth_value,
            "auth_header": self.auth_header,
            "body_type":   self.body_type,
            "body":        self.body,
            "env_profile": self.env_profile,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HttpRequest":
        r = cls()
        for k, v in d.items():
            if hasattr(r, k):
                setattr(r, k, v)
        return r

    def to_http_file_block(self) -> str:
        """Serializza nel formato .http compatibile VS Code REST Client."""
        lines = [f"# {self.name}", f"{self.method} {self.url}"]
        # auth header
        if self.auth_type == "Bearer Token" and self.auth_value:
            lines.append(f"Authorization: Bearer {self.auth_value}")
        elif self.auth_type == "Basic (user:pass)" and self.auth_value:
            encoded = base64.b64encode(self.auth_value.encode()).decode()
            lines.append(f"Authorization: Basic {encoded}")
        elif self.auth_type == "API Key (header)" and self.auth_value:
            lines.append(f"{self.auth_header}: {self.auth_value}")
        # custom headers
        for k, v in self.headers.items():
            lines.append(f"{k}: {v}")
        # content-type
        ct = _CONTENT_TYPE_MAP.get(self.body_type)
        if ct:
            lines.append(f"Content-Type: {ct}")
        # body
        if self.body_type != "Nessuno" and self.body:
            lines.append("")
            lines.append(self.body)
        return "\n".join(lines)


class EnvProfile:
    """Profilo variabili d'ambiente per un ambiente (dev/staging/prod)."""

    def __init__(self, name: str = "dev", variables: Optional[Dict[str, str]] = None):
        self.name      = name
        self.variables = variables or {}

    def resolve(self, text: str) -> str:
        """Sostituisce {{VAR}} nel testo con i valori del profilo."""
        def replacer(m):
            return self.variables.get(m.group(1), m.group(0))
        return re.sub(r"\{\{(\w+)\}\}", replacer, text)

    def to_dict(self) -> dict:
        return {"name": self.name, "variables": self.variables}

    @classmethod
    def from_dict(cls, d: dict) -> "EnvProfile":
        return cls(d.get("name", "dev"), d.get("variables", {}))


# ─── Syntax Highlighter minimalista per JSON / XML ───────────────────────────

class _JsonHighlighter(QSyntaxHighlighter):
    """Evidenzia chiavi, stringhe, numeri e letterali JSON."""

    def __init__(self, parent):
        super().__init__(parent)
        self._rules: List[tuple] = []

        def fmt(color, bold=False):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(700)
            return f

        self._rules = [
            (re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"\s*:'),  fmt("#4fc1ff", bold=True)),  # chiave
            (re.compile(r':\s*"[^"\\]*(?:\\.[^"\\]*)*"'),  fmt("#ce9178")),             # stringa val
            (re.compile(r'\b-?\d+\.?\d*([eE][+-]?\d+)?\b'), fmt("#b5cea8")),            # numeri
            (re.compile(r'\b(true|false|null)\b'),           fmt("#569cd6")),            # literali
        ]

    def highlightBlock(self, text: str):
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ─── Wizard per costruire la richiesta ───────────────────────────────────────

class _RequestWizard(QWizard):
    """Wizard 4-step per costruire una richiesta HTTP guidata."""

    def __init__(self, request: HttpRequest, envs: List[EnvProfile], parent=None):
        super().__init__(parent)
        self.setWindowTitle("🧙 Wizard nuova richiesta HTTP")
        self.resize(620, 480)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)

        self._req  = request
        self._envs = envs

        self.addPage(self._page_method())
        self.addPage(self._page_auth())
        self.addPage(self._page_body())
        self.addPage(self._page_headers())

    # ── Pagina 1: Metodo + URL ────────────────────────────────────────────────

    def _page_method(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("Passo 1 — Metodo e URL")
        page.setSubTitle(
            "Scegli il metodo HTTP e inserisci l'URL della risorsa.\n"
            "Usa {{VARIABILE}} per inserire valori dall'ambiente (es. {{base_url}})."
        )
        lay = QFormLayout(page)

        self._w_name = QLineEdit(self._req.name)
        lay.addRow("Nome richiesta:", self._w_name)

        self._w_method = QComboBox()
        self._w_method.addItems(_HTTP_METHODS)
        self._w_method.setCurrentText(self._req.method)
        lay.addRow("Metodo HTTP:", self._w_method)

        self._w_url = QLineEdit(self._req.url)
        self._w_url.setPlaceholderText("https://api.esempio.com/v1/utenti  oppure  {{base_url}}/endpoint")
        lay.addRow("URL:", self._w_url)

        self._w_env = QComboBox()
        for e in self._envs:
            self._w_env.addItem(e.name)
        idx = next((i for i, e in enumerate(self._envs) if e.name == self._req.env_profile), 0)
        self._w_env.setCurrentIndex(idx)
        lay.addRow("Profilo ambiente:", self._w_env)

        page.registerField("url*", self._w_url)   # obbligatorio
        return page

    # ── Pagina 2: Autenticazione ──────────────────────────────────────────────

    def _page_auth(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("Passo 2 — Autenticazione")
        page.setSubTitle(
            "Seleziona il tipo di autenticazione da usare.\n"
            "Lascia 'Nessuna' se l'API è pubblica."
        )
        lay = QFormLayout(page)

        self._w_auth_type = QComboBox()
        self._w_auth_type.addItems(_AUTH_TYPES)
        self._w_auth_type.setCurrentText(self._req.auth_type)
        lay.addRow("Tipo auth:", self._w_auth_type)

        self._w_auth_val = QLineEdit(self._req.auth_value)
        self._w_auth_val.setPlaceholderText("Token / user:password / API key")
        self._w_auth_val.setEchoMode(QLineEdit.EchoMode.Normal)
        lay.addRow("Valore:", self._w_auth_val)

        self._w_auth_hdr = QLineEdit(self._req.auth_header)
        self._w_auth_hdr.setPlaceholderText("X-Api-Key")
        self._w_auth_hdr.setEnabled(self._req.auth_type == "API Key (header)")
        lay.addRow("Header name (API Key):", self._w_auth_hdr)

        def _toggle(t):
            self._w_auth_val.setEnabled(t != "Nessuna")
            self._w_auth_hdr.setEnabled(t == "API Key (header)")
        self._w_auth_type.currentTextChanged.connect(_toggle)
        _toggle(self._req.auth_type)

        return page

    # ── Pagina 3: Body ────────────────────────────────────────────────────────

    def _page_body(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("Passo 3 — Body")
        page.setSubTitle(
            "Inserisci il corpo della richiesta (solo per POST/PUT/PATCH).\n"
            "Per GET/DELETE/HEAD puoi lasciare 'Nessuno'."
        )
        lay = QVBoxLayout(page)

        row = QHBoxLayout()
        row.addWidget(QLabel("Tipo body:"))
        self._w_body_type = QComboBox()
        self._w_body_type.addItems(_BODY_TYPES)
        self._w_body_type.setCurrentText(self._req.body_type)
        row.addWidget(self._w_body_type)
        row.addStretch()
        lay.addLayout(row)

        self._w_body = QTextEdit()
        self._w_body.setPlaceholderText(
            '{\n  "chiave": "valore"\n}\n\n'
            'Oppure lascia vuoto se il body non serve.'
        )
        self._w_body.setPlainText(self._req.body)
        self._w_body.setFont(QFont("Monospace", 10))
        _JsonHighlighter(self._w_body.document())
        lay.addWidget(self._w_body)

        # tasto per inserire template JSON
        btn_tpl = QPushButton("📋 Inserisci template JSON")
        btn_tpl.clicked.connect(lambda: self._w_body.setPlainText('{\n  "chiave": "valore"\n}'))
        lay.addWidget(btn_tpl)

        return page

    # ── Pagina 4: Headers extra ───────────────────────────────────────────────

    def _page_headers(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("Passo 4 — Headers aggiuntivi")
        page.setSubTitle(
            "Aggiungi eventuali header personalizzati (es. Accept, X-Request-Id).\n"
            "Content-Type viene aggiunto automaticamente in base al body scelto."
        )
        lay = QVBoxLayout(page)

        self._w_headers = QTableWidget(0, 2)
        self._w_headers.setHorizontalHeaderLabels(["Nome header", "Valore"])
        self._w_headers.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        # pre-popola
        for k, v in self._req.headers.items():
            self._add_header_row(k, v)
        lay.addWidget(self._w_headers)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("➕ Aggiungi header")
        btn_add.clicked.connect(lambda: self._add_header_row("", ""))
        btn_del = QPushButton("🗑 Rimuovi selezionato")
        btn_del.clicked.connect(self._remove_selected_header)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        return page

    def _add_header_row(self, name: str, value: str):
        r = self._w_headers.rowCount()
        self._w_headers.insertRow(r)
        self._w_headers.setItem(r, 0, QTableWidgetItem(name))
        self._w_headers.setItem(r, 1, QTableWidgetItem(value))

    def _remove_selected_header(self):
        rows = sorted({i.row() for i in self._w_headers.selectedItems()}, reverse=True)
        for r in rows:
            self._w_headers.removeRow(r)

    # ── Raccolta risultato ────────────────────────────────────────────────────

    def collect(self) -> HttpRequest:
        """Popola e restituisce il request con i valori inseriti nel wizard."""
        r = self._req
        r.name       = self._w_name.text().strip() or "Richiesta"
        r.method     = self._w_method.currentText()
        r.url        = self._w_url.text().strip()
        r.env_profile = self._w_env.currentText()
        r.auth_type  = self._w_auth_type.currentText()
        r.auth_value = self._w_auth_val.text().strip()
        r.auth_header = self._w_auth_hdr.text().strip() or "X-Api-Key"
        r.body_type  = self._w_body_type.currentText()
        r.body       = self._w_body.toPlainText().strip()
        r.headers    = {}
        for row in range(self._w_headers.rowCount()):
            k_item = self._w_headers.item(row, 0)
            v_item = self._w_headers.item(row, 1)
            k = (k_item.text().strip() if k_item else "")
            v = (v_item.text().strip() if v_item else "")
            if k:
                r.headers[k] = v
        return r


# ─── Dialog gestione variabili d'ambiente ────────────────────────────────────

class _EnvDialog(QDialog):

    def __init__(self, envs: List[EnvProfile], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Variabili d'ambiente")
        self.resize(540, 400)
        self._envs = [EnvProfile(e.name, dict(e.variables)) for e in envs]
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        self._env_list = QComboBox()
        for e in self._envs:
            self._env_list.addItem(e.name)
        self._env_list.currentIndexChanged.connect(self._load_env)
        top.addWidget(QLabel("Ambiente:"))
        top.addWidget(self._env_list)
        btn_new = QPushButton("➕ Nuovo")
        btn_new.clicked.connect(self._new_env)
        btn_del = QPushButton("🗑 Elimina")
        btn_del.clicked.connect(self._del_env)
        top.addWidget(btn_new)
        top.addWidget(btn_del)
        lay.addLayout(top)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Variabile  (es. base_url)", "Valore"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self._table)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("➕ Aggiungi variabile")
        btn_add.clicked.connect(lambda: self._add_var("", ""))
        btn_rem = QPushButton("🗑 Rimuovi variabile")
        btn_rem.clicked.connect(self._remove_var)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_rem)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        if self._envs:
            self._load_env(0)

    def _load_env(self, idx: int):
        self._table.setRowCount(0)
        if 0 <= idx < len(self._envs):
            for k, v in self._envs[idx].variables.items():
                self._add_var(k, v)

    def _save_current(self):
        idx = self._env_list.currentIndex()
        if 0 <= idx < len(self._envs):
            d = {}
            for r in range(self._table.rowCount()):
                ki = self._table.item(r, 0)
                vi = self._table.item(r, 1)
                k = ki.text().strip() if ki else ""
                v = vi.text().strip() if vi else ""
                if k:
                    d[k] = v
            self._envs[idx].variables = d

    def _new_env(self):
        self._save_current()
        name, ok = QInputDialog.getText(self, "Nuovo ambiente", "Nome ambiente:")
        if ok and name.strip():
            self._envs.append(EnvProfile(name.strip()))
            self._env_list.addItem(name.strip())
            self._env_list.setCurrentIndex(len(self._envs) - 1)

    def _del_env(self):
        idx = self._env_list.currentIndex()
        if idx < 0 or len(self._envs) <= 1:
            QMessageBox.warning(self, "Attenzione", "Deve esistere almeno un ambiente.")
            return
        self._save_current()
        self._envs.pop(idx)
        self._env_list.removeItem(idx)

    def _add_var(self, k: str, v: str):
        r = self._table.rowCount()
        self._table.insertRow(r)
        self._table.setItem(r, 0, QTableWidgetItem(k))
        self._table.setItem(r, 1, QTableWidgetItem(v))

    def _remove_var(self):
        rows = sorted({i.row() for i in self._table.selectedItems()}, reverse=True)
        for r in rows:
            self._table.removeRow(r)

    def _on_ok(self):
        self._save_current()
        self.accept()

    def result_envs(self) -> List[EnvProfile]:
        return self._envs


# ─── Worker thread per esecuzione richiesta ───────────────────────────────────

class _RequestWorker(QObject):
    finished = pyqtSignal(dict)   # risultato: status, headers, body, elapsed
    error    = pyqtSignal(str)

    def __init__(self, req: HttpRequest, resolved_env: EnvProfile):
        super().__init__()
        self._req = req
        self._env = resolved_env

    def run(self):
        req  = self._req
        env  = self._env
        try:
            url = env.resolve(req.url)

            # costruzione headers
            headers = {}
            if req.auth_type == "Bearer Token" and req.auth_value:
                headers["Authorization"] = f"Bearer {env.resolve(req.auth_value)}"
            elif req.auth_type == "Basic (user:pass)" and req.auth_value:
                encoded = base64.b64encode(env.resolve(req.auth_value).encode()).decode()
                headers["Authorization"] = f"Basic {encoded}"
            elif req.auth_type == "API Key (header)" and req.auth_value:
                hdr = req.auth_header or "X-Api-Key"
                headers[hdr] = env.resolve(req.auth_value)
            for k, v in req.headers.items():
                headers[env.resolve(k)] = env.resolve(v)

            # body
            body_bytes = None
            if req.body_type != "Nessuno" and req.body:
                body_text = env.resolve(req.body)
                if req.body_type == "Form (x-www-form-urlencoded)":
                    body_bytes = urllib.parse.urlencode(
                        dict(p.split("=", 1) for p in body_text.splitlines() if "=" in p)
                    ).encode()
                    headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
                else:
                    body_bytes = body_text.encode("utf-8")
                    ct = _CONTENT_TYPE_MAP.get(req.body_type, "text/plain")
                    headers.setdefault("Content-Type", ct)

            # richiesta
            http_req = urllib.request.Request(
                url, data=body_bytes, headers=headers, method=req.method
            )
            t0 = time.perf_counter()
            try:
                with urllib.request.urlopen(http_req, timeout=30) as resp:
                    elapsed = time.perf_counter() - t0
                    raw_body = resp.read()
                    resp_headers = dict(resp.getheaders())
                    status = resp.status
            except urllib.error.HTTPError as e:
                elapsed = time.perf_counter() - t0
                raw_body = e.read()
                resp_headers = dict(e.headers)
                status = e.code

            # decodifica body
            charset = "utf-8"
            ct_hdr = resp_headers.get("Content-Type", "")
            m = re.search(r"charset=([^\s;]+)", ct_hdr)
            if m:
                charset = m.group(1)
            try:
                body_str = raw_body.decode(charset, errors="replace")
            except Exception:
                body_str = raw_body.decode("utf-8", errors="replace")

            self.finished.emit({
                "status":  status,
                "headers": resp_headers,
                "body":    body_str,
                "elapsed": elapsed,
                "content_type": ct_hdr,
            })
        except Exception as exc:
            self.error.emit(str(exc))


# ─── Pannello principale ──────────────────────────────────────────────────────

class _RestPanel(QWidget):
    """Widget principale del REST Client."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._collection: List[HttpRequest] = []
        self._history:    List[HttpRequest] = []
        self._envs:       List[EnvProfile]  = [
            EnvProfile("dev",     {"base_url": "http://localhost:8000"}),
            EnvProfile("staging", {"base_url": "https://staging.esempio.com"}),
            EnvProfile("prod",    {"base_url": "https://api.esempio.com"}),
        ]
        self._current_req: HttpRequest = HttpRequest()
        self._worker: Optional[_RequestWorker] = None
        self._thread: Optional[threading.Thread] = None
        self._build_ui()
        self._load_data()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # ── toolbar superiore ─────────────────────────────────────────────────
        toolbar = QHBoxLayout()

        self._btn_wizard = QPushButton("🧙 Wizard")
        self._btn_wizard.setToolTip("Apri il wizard guidato per costruire la richiesta")
        self._btn_wizard.clicked.connect(self._open_wizard)
        toolbar.addWidget(self._btn_wizard)

        self._btn_new = QPushButton("➕ Nuova")
        self._btn_new.clicked.connect(self._new_request)
        toolbar.addWidget(self._btn_new)

        self._btn_save_coll = QPushButton("💾 Salva collection")
        self._btn_save_coll.setToolTip("Salva tutte le richieste in un file .http")
        self._btn_save_coll.clicked.connect(self._save_collection)
        toolbar.addWidget(self._btn_save_coll)

        self._btn_load_coll = QPushButton("📂 Carica collection")
        self._btn_load_coll.setToolTip("Carica richieste da file .http")
        self._btn_load_coll.clicked.connect(self._load_collection)
        toolbar.addWidget(self._btn_load_coll)

        self._btn_env = QPushButton("🌍 Ambienti")
        self._btn_env.setToolTip("Gestisci variabili d'ambiente")
        self._btn_env.clicked.connect(self._manage_envs)
        toolbar.addWidget(self._btn_env)

        toolbar.addStretch()
        root.addLayout(toolbar)

        # ── splitter orizzontale: lista sx + dettaglio dx ─────────────────────
        hsplit = QSplitter(Qt.Orientation.Horizontal)

        # lista sinistra: Collection + Cronologia
        left_tabs = QTabWidget()
        left_tabs.setMaximumWidth(240)
        left_tabs.setMinimumWidth(160)

        # tab Collection
        coll_w = QWidget()
        coll_lay = QVBoxLayout(coll_w)
        coll_lay.setContentsMargins(2, 2, 2, 2)
        self._coll_list = QListWidget()
        self._coll_list.itemDoubleClicked.connect(self._load_from_collection)
        self._coll_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._coll_list.customContextMenuRequested.connect(self._coll_context_menu)
        coll_lay.addWidget(self._coll_list)
        left_tabs.addTab(coll_w, "📁 Collection")

        # tab Cronologia
        hist_w = QWidget()
        hist_lay = QVBoxLayout(hist_w)
        hist_lay.setContentsMargins(2, 2, 2, 2)
        self._hist_list = QListWidget()
        self._hist_list.itemDoubleClicked.connect(self._load_from_history)
        hist_lay.addWidget(self._hist_list)
        left_tabs.addTab(hist_w, "🕐 Cronologia")

        hsplit.addWidget(left_tabs)

        # dettaglio destra
        right_w = QWidget()
        right_lay = QVBoxLayout(right_w)
        right_lay.setContentsMargins(2, 2, 2, 2)
        right_lay.setSpacing(4)

        # barra metodo + URL + invia
        req_bar = QHBoxLayout()
        self._method_cb = QComboBox()
        self._method_cb.addItems(_HTTP_METHODS)
        self._method_cb.setFixedWidth(90)
        req_bar.addWidget(self._method_cb)

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://api.esempio.com/endpoint  oppure  {{base_url}}/path")
        req_bar.addWidget(self._url_edit, stretch=1)

        self._env_cb = QComboBox()
        for e in self._envs:
            self._env_cb.addItem(e.name)
        self._env_cb.setFixedWidth(90)
        req_bar.addWidget(self._env_cb)

        self._btn_send = QPushButton("▶ Invia")
        self._btn_send.setFixedWidth(80)
        self._btn_send.clicked.connect(self._send_request)
        req_bar.addWidget(self._btn_send)

        right_lay.addLayout(req_bar)

        # tab request: Auth / Body / Headers
        self._req_tabs = QTabWidget()

        # Auth
        auth_w = QWidget()
        auth_lay = QFormLayout(auth_w)
        self._auth_type_cb = QComboBox()
        self._auth_type_cb.addItems(_AUTH_TYPES)
        self._auth_type_cb.currentTextChanged.connect(self._auth_type_changed)
        auth_lay.addRow("Tipo:", self._auth_type_cb)
        self._auth_val_edit = QLineEdit()
        self._auth_val_edit.setPlaceholderText("Token / user:pass / API-key")
        auth_lay.addRow("Valore:", self._auth_val_edit)
        self._auth_hdr_edit = QLineEdit("X-Api-Key")
        self._auth_hdr_edit.setPlaceholderText("Nome header (solo API Key)")
        self._auth_hdr_edit.setEnabled(False)
        auth_lay.addRow("Header (API Key):", self._auth_hdr_edit)
        self._req_tabs.addTab(auth_w, "🔒 Auth")

        # Body
        body_w = QWidget()
        body_lay = QVBoxLayout(body_w)
        body_bar = QHBoxLayout()
        body_bar.addWidget(QLabel("Tipo:"))
        self._body_type_cb = QComboBox()
        self._body_type_cb.addItems(_BODY_TYPES)
        body_bar.addWidget(self._body_type_cb)
        body_bar.addStretch()
        body_lay.addLayout(body_bar)
        self._body_edit = QTextEdit()
        self._body_edit.setFont(QFont("Monospace", 10))
        self._body_edit.setPlaceholderText('{\n  "chiave": "valore"\n}')
        _JsonHighlighter(self._body_edit.document())
        body_lay.addWidget(self._body_edit)
        self._req_tabs.addTab(body_w, "📄 Body")

        # Headers
        hdr_w = QWidget()
        hdr_lay = QVBoxLayout(hdr_w)
        self._hdr_table = QTableWidget(0, 2)
        self._hdr_table.setHorizontalHeaderLabels(["Header", "Valore"])
        self._hdr_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hdr_lay.addWidget(self._hdr_table)
        hdr_btn = QHBoxLayout()
        hdr_btn.addWidget(self._make_btn("➕ Aggiungi", lambda: self._add_header_row("", "")))
        hdr_btn.addWidget(self._make_btn("🗑 Rimuovi", self._remove_header_row))
        hdr_btn.addStretch()
        hdr_lay.addLayout(hdr_btn)
        self._req_tabs.addTab(hdr_w, "📋 Headers")

        right_lay.addWidget(self._req_tabs)

        # progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(6)
        self._progress.setVisible(False)
        right_lay.addWidget(self._progress)

        # ── risposta ──────────────────────────────────────────────────────────
        resp_group = QGroupBox("Risposta")
        resp_lay = QVBoxLayout(resp_group)

        self._status_lbl = QLabel("—")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        resp_lay.addWidget(self._status_lbl)

        resp_tabs = QTabWidget()

        # Body risposta
        body_resp_w = QWidget()
        body_resp_lay = QVBoxLayout(body_resp_w)
        resp_btn_bar = QHBoxLayout()
        self._btn_copy_resp = QPushButton("📋 Copia")
        self._btn_copy_resp.clicked.connect(self._copy_response)
        self._btn_insert_resp = QPushButton("📥 Inserisci in editor")
        self._btn_insert_resp.clicked.connect(self._insert_response)
        resp_btn_bar.addWidget(self._btn_copy_resp)
        resp_btn_bar.addWidget(self._btn_insert_resp)
        resp_btn_bar.addStretch()
        body_resp_lay.addLayout(resp_btn_bar)
        self._resp_body = QTextEdit()
        self._resp_body.setReadOnly(True)
        self._resp_body.setFont(QFont("Monospace", 10))
        _JsonHighlighter(self._resp_body.document())
        body_resp_lay.addWidget(self._resp_body)
        resp_tabs.addTab(body_resp_w, "📄 Body")

        # Headers risposta
        hdr_resp_w = QWidget()
        hdr_resp_lay = QVBoxLayout(hdr_resp_w)
        self._resp_hdr_table = QTableWidget(0, 2)
        self._resp_hdr_table.setHorizontalHeaderLabels(["Header", "Valore"])
        self._resp_hdr_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._resp_hdr_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        hdr_resp_lay.addWidget(self._resp_hdr_table)
        resp_tabs.addTab(hdr_resp_w, "📋 Headers")

        resp_lay.addWidget(resp_tabs)
        right_lay.addWidget(resp_group, stretch=1)

        hsplit.addWidget(right_w)
        hsplit.setSizes([200, 600])
        root.addWidget(hsplit, stretch=1)

    def _make_btn(self, text: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.clicked.connect(slot)
        return b

    # ── Helpers UI ────────────────────────────────────────────────────────────

    def _auth_type_changed(self, t: str):
        self._auth_val_edit.setEnabled(t != "Nessuna")
        self._auth_hdr_edit.setEnabled(t == "API Key (header)")

    def _add_header_row(self, k: str, v: str):
        r = self._hdr_table.rowCount()
        self._hdr_table.insertRow(r)
        self._hdr_table.setItem(r, 0, QTableWidgetItem(k))
        self._hdr_table.setItem(r, 1, QTableWidgetItem(v))

    def _remove_header_row(self):
        rows = sorted({i.row() for i in self._hdr_table.selectedItems()}, reverse=True)
        for r in rows:
            self._hdr_table.removeRow(r)

    # ── Wizard ────────────────────────────────────────────────────────────────

    def _open_wizard(self):
        req = self._collect_current()
        wiz = _RequestWizard(req, self._envs, parent=self)
        if wiz.exec() == QWizard.DialogCode.Accepted:
            filled = wiz.collect()
            self._apply_request(filled)

    def _new_request(self):
        self._apply_request(HttpRequest())

    # ── Collection ────────────────────────────────────────────────────────────

    def _coll_context_menu(self, pos):
        item = self._coll_list.itemAt(pos)
        menu = QMenu(self)
        if item:
            menu.addAction("📂 Carica", lambda: self._load_from_collection(item))
            menu.addAction("💾 Aggiorna con corrente", lambda: self._update_in_collection(item))
            menu.addAction("🗑 Rimuovi", lambda: self._remove_from_collection(item))
        menu.addAction("➕ Salva corrente nella collection", self._add_to_collection)
        menu.exec(self._coll_list.mapToGlobal(pos))

    def _add_to_collection(self):
        req = self._collect_current()
        name, ok = QInputDialog.getText(self, "Salva nella collection", "Nome richiesta:", text=req.name)
        if ok and name.strip():
            req.name = name.strip()
            self._collection.append(req)
            self._coll_list.addItem(req.name)
            self._save_data()

    def _update_in_collection(self, item: QListWidgetItem):
        idx = self._coll_list.row(item)
        if 0 <= idx < len(self._collection):
            req = self._collect_current()
            req.name = self._collection[idx].name
            self._collection[idx] = req
            self._save_data()

    def _remove_from_collection(self, item: QListWidgetItem):
        idx = self._coll_list.row(item)
        if 0 <= idx < len(self._collection):
            self._collection.pop(idx)
            self._coll_list.takeItem(idx)
            self._save_data()

    def _load_from_collection(self, item: QListWidgetItem):
        idx = self._coll_list.row(item)
        if 0 <= idx < len(self._collection):
            self._apply_request(self._collection[idx])

    def _load_from_history(self, item: QListWidgetItem):
        idx = self._hist_list.row(item)
        if 0 <= idx < len(self._history):
            self._apply_request(self._history[idx])

    # ── Serializzazione ───────────────────────────────────────────────────────

    def _save_collection(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Salva collection", "", "HTTP Files (*.http);;JSON (*.json)"
        )
        if not path:
            return
        if path.endswith(".json"):
            data = {"requests": [r.to_dict() for r in self._collection],
                    "envs": [e.to_dict() for e in self._envs]}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        else:
            blocks = [r.to_http_file_block() for r in self._collection]
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n\n###\n\n".join(blocks))
        QMessageBox.information(self, "Salvato", f"Collection salvata in:\n{path}")

    def _load_collection(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Carica collection", "", "HTTP Files (*.http);;JSON (*.json);;All (*)"
        )
        if not path:
            return
        try:
            if path.endswith(".json"):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._collection = [HttpRequest.from_dict(d) for d in data.get("requests", [])]
                if "envs" in data:
                    self._envs = [EnvProfile.from_dict(d) for d in data["envs"]]
                    self._env_cb.clear()
                    for e in self._envs:
                        self._env_cb.addItem(e.name)
            else:
                self._collection = self._parse_http_file(path)
            self._refresh_collection_ui()
            QMessageBox.information(self, "Caricato", f"{len(self._collection)} richieste caricate.")
        except Exception as exc:
            QMessageBox.critical(self, "Errore", f"Impossibile caricare:\n{exc}")

    def _parse_http_file(self, path: str) -> List[HttpRequest]:
        """Parser minimale per file .http (formato VS Code REST Client)."""
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        blocks = re.split(r"\n###\n", content)
        requests = []
        for block in blocks:
            lines = block.strip().splitlines()
            if not lines:
                continue
            req = HttpRequest()
            # prima riga non-commento con METHOD URL
            for i, line in enumerate(lines):
                m = re.match(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(\S+)", line.strip())
                if m:
                    req.method = m.group(1)
                    req.url    = m.group(2)
                    # headers tra la riga metodo e una riga vuota
                    j = i + 1
                    while j < len(lines) and lines[j].strip():
                        hm = re.match(r"^([\w-]+):\s*(.+)$", lines[j].strip())
                        if hm:
                            req.headers[hm.group(1)] = hm.group(2)
                        j += 1
                    # body dopo la riga vuota
                    body_lines = lines[j+1:]
                    if body_lines:
                        req.body      = "\n".join(body_lines).strip()
                        req.body_type = "JSON" if req.body.startswith("{") else "Testo libero"
                    break
            # nome dalla riga # commento
            for line in lines:
                if line.startswith("#"):
                    req.name = line.lstrip("# ").strip()
                    break
            if req.url:
                requests.append(req)
        return requests

    def _refresh_collection_ui(self):
        self._coll_list.clear()
        for r in self._collection:
            self._coll_list.addItem(r.name)

    # ── Ambienti ──────────────────────────────────────────────────────────────

    def _manage_envs(self):
        dlg = _EnvDialog(self._envs, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._envs = dlg.result_envs()
            current = self._env_cb.currentText()
            self._env_cb.clear()
            for e in self._envs:
                self._env_cb.addItem(e.name)
            idx = next((i for i, e in enumerate(self._envs) if e.name == current), 0)
            self._env_cb.setCurrentIndex(idx)
            self._save_data()

    # ── Raccolta / applicazione stato ─────────────────────────────────────────

    def _collect_current(self) -> HttpRequest:
        r = HttpRequest()
        r.method     = self._method_cb.currentText()
        r.url        = self._url_edit.text().strip()
        r.env_profile = self._env_cb.currentText()
        r.auth_type  = self._auth_type_cb.currentText()
        r.auth_value = self._auth_val_edit.text().strip()
        r.auth_header = self._auth_hdr_edit.text().strip() or "X-Api-Key"
        r.body_type  = self._body_type_cb.currentText()
        r.body       = self._body_edit.toPlainText().strip()
        for row in range(self._hdr_table.rowCount()):
            ki = self._hdr_table.item(row, 0)
            vi = self._hdr_table.item(row, 1)
            k = ki.text().strip() if ki else ""
            v = vi.text().strip() if vi else ""
            if k:
                r.headers[k] = v
        return r

    def _apply_request(self, r: HttpRequest):
        self._current_req = r
        self._method_cb.setCurrentText(r.method)
        self._url_edit.setText(r.url)
        idx = next((i for i, e in enumerate(self._envs) if e.name == r.env_profile), 0)
        self._env_cb.setCurrentIndex(idx)
        self._auth_type_cb.setCurrentText(r.auth_type)
        self._auth_val_edit.setText(r.auth_value)
        self._auth_hdr_edit.setText(r.auth_header)
        self._body_type_cb.setCurrentText(r.body_type)
        self._body_edit.setPlainText(r.body)
        self._hdr_table.setRowCount(0)
        for k, v in r.headers.items():
            self._add_header_row(k, v)

    # ── Invio richiesta ───────────────────────────────────────────────────────

    def _send_request(self):
        req = self._collect_current()
        if not req.url:
            QMessageBox.warning(self, "Attenzione", "Inserisci un URL prima di inviare.")
            return

        env_name = self._env_cb.currentText()
        env = next((e for e in self._envs if e.name == env_name), EnvProfile())

        self._btn_send.setEnabled(False)
        self._progress.setVisible(True)
        self._status_lbl.setText("⏳ In attesa...")
        self._resp_body.clear()

        # aggiungi a cronologia
        self._history.insert(0, req)
        if len(self._history) > _HISTORY_MAX:
            self._history = self._history[:_HISTORY_MAX]
        self._hist_list.insertItem(0, f"{req.method} {req.url}")
        if self._hist_list.count() > _HISTORY_MAX:
            self._hist_list.takeItem(_HISTORY_MAX)

        # esegui in thread
        worker = _RequestWorker(req, env)
        worker.finished.connect(self._on_response)
        worker.error.connect(self._on_error)

        def _run():
            worker.run()

        self._worker = worker
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def _on_response(self, result: dict):
        self._btn_send.setEnabled(True)
        self._progress.setVisible(False)

        status  = result["status"]
        elapsed = result["elapsed"]
        body    = result["body"]
        headers = result["headers"]
        ct      = result.get("content_type", "")

        color = "#4ec9b0" if status < 300 else ("#dcdcaa" if status < 400 else "#f44747")
        self._status_lbl.setText(
            f'<span style="color:{color};font-weight:bold;">HTTP {status}</span>'
            f'&nbsp;&nbsp;{elapsed*1000:.0f} ms'
        )

        # pretty-print body
        pretty = body
        if "json" in ct:
            try:
                pretty = json.dumps(json.loads(body), indent=2, ensure_ascii=False)
            except Exception:
                pass
        elif "xml" in ct:
            try:
                pretty = xml.dom.minidom.parseString(body.encode()).toprettyxml(indent="  ")
            except Exception:
                pass
        self._resp_body.setPlainText(pretty)

        # headers risposta
        self._resp_hdr_table.setRowCount(0)
        for k, v in headers.items():
            r = self._resp_hdr_table.rowCount()
            self._resp_hdr_table.insertRow(r)
            self._resp_hdr_table.setItem(r, 0, QTableWidgetItem(k))
            self._resp_hdr_table.setItem(r, 1, QTableWidgetItem(str(v)))

        self._save_data()

    def _on_error(self, msg: str):
        self._btn_send.setEnabled(True)
        self._progress.setVisible(False)
        self._status_lbl.setText(f'<span style="color:#f44747;">❌ Errore: {msg}</span>')
        self._resp_body.setPlainText(f"Errore di rete:\n{msg}")

    # ── Copia / inserimento ───────────────────────────────────────────────────

    def _copy_response(self):
        QApplication.clipboard().setText(self._resp_body.toPlainText())

    def _insert_response(self):
        """Inserisce il body della risposta nell'editor attivo."""
        try:
            mw = self.parent()
            while mw and not hasattr(mw, "_tab_manager"):
                mw = mw.parent()
            if mw:
                editor = mw._tab_manager.current_editor()
                if editor:
                    editor.insert(self._resp_body.toPlainText())
        except Exception:
            pass

    # ── Persistenza ───────────────────────────────────────────────────────────

    def _data_path(self):
        from core.platform import get_data_dir
        return get_data_dir() / "rest_client_data.json"

    def _save_data(self):
        try:
            data = {
                "collection": [r.to_dict() for r in self._collection],
                "envs":       [e.to_dict() for e in self._envs],
                "history":    [r.to_dict() for r in self._history[:_HISTORY_MAX]],
            }
            self._data_path().write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception:
            pass

    def _load_data(self):
        try:
            path = self._data_path()
            if not path.exists():
                return
            data = json.loads(path.read_text(encoding="utf-8"))
            self._collection = [HttpRequest.from_dict(d) for d in data.get("collection", [])]
            if "envs" in data:
                self._envs = [EnvProfile.from_dict(d) for d in data["envs"]]
                self._env_cb.clear()
                for e in self._envs:
                    self._env_cb.addItem(e.name)
            self._history = [HttpRequest.from_dict(d) for d in data.get("history", [])]
            self._refresh_collection_ui()
            for r in self._history:
                self._hist_list.addItem(f"{r.method} {r.url}")
        except Exception:
            pass


# ─── Plugin entry point ───────────────────────────────────────────────────────

class RestClientPlugin(BasePlugin):
    NAME        = "REST Client"
    VERSION     = "1.0"
    DESCRIPTION = "Client HTTP/REST integrato con wizard, collection e variabili ambiente"
    AUTHOR      = "NotePadPQ"

    def on_load(self, main_window: "MainWindow") -> None:
        super().on_load(main_window)

        self._panel = _RestPanel()
        self._dock  = QDockWidget("🌐 REST Client", main_window)
        self._dock.setObjectName("RestClientDock")
        self._dock.setWidget(self._panel)
        main_window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._dock)
        self._dock.hide()

        self.add_menu_action(
            main_window, "plugins",
            "REST Client",
            self._toggle_dock,
            shortcut="Ctrl+Alt+R",
            icon_key="plugin_rest",
        )

    def _toggle_dock(self):
        self._dock.setVisible(not self._dock.isVisible())

    def on_unload(self) -> None:
        if hasattr(self, "_dock"):
            self._dock.setParent(None)
            self._dock.deleteLater()
        super().on_unload()

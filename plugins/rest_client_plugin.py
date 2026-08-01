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
import os
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
    QTreeWidget, QTreeWidgetItem, QAbstractItemView, QFrame,
)

from plugins.base_plugin import BasePlugin
from i18n.i18n import tr

try:
    import requests as _requests_lib
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

if TYPE_CHECKING:
    from ui.main_window import MainWindow


# ─── Costanti ────────────────────────────────────────────────────────────────

_HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
_AUTH_TYPES   = ["Nessuna", "Bearer Token", "Basic (user:pass)", "API Key (header)", "OAuth 2.0"]
_BODY_TYPES   = ["Nessuno", "JSON", "XML", "Form (x-www-form-urlencoded)", "Multipart (form-data)", "Testo libero"]
_HISTORY_MAX  = 50

_CONTENT_TYPE_MAP = {
    "JSON":                          "application/json",
    "XML":                           "application/xml",
    "Form (x-www-form-urlencoded)":  "application/x-www-form-urlencoded",
    "Multipart (form-data)":         "multipart/form-data",
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

# ─── Palette temi (dark / light) ─────────────────────────────────────────────
# Dizionari con chiavi semantiche usati da _make_styles() per generare
# tutti gli stylesheet in modo coerente col tema corrente dell'app.

_DARK_P = {
    # sfondi principali
    "bg_base":       "#0d1117",   # sfondo globale widget
    "bg_panel":      "#161b22",   # pannelli / tab inattive
    "bg_panel2":     "#1c2128",   # tab pane, code area
    "bg_toolbar":    "#21262d",   # toolbar, header tabelle
    "bg_sidebar":    "#1e2128",   # sidebar sinistra
    "bg_input":      "#21262d",   # QLineEdit, QComboBox
    "bg_input_url":  "#161b22",   # URL bar (leggermente più scuro)
    "bg_code":       "#1c2128",   # text area codice
    "bg_alt_row":    "#1c2128",   # righe alterne tabelle
    # testi
    "fg_primary":    "#e6edf3",   # testo principale
    "fg_secondary":  "#c9d1d9",   # testo secondario input
    "fg_muted":      "#8b949e",   # testo attenuato (label, hint)
    "fg_disabled":   "#484f58",   # testo disabilitato
    # bordi
    "border":        "#30363d",   # bordo standard
    "border_input":  "#30363d",   # bordo input
    "border_focus":  "#58a6ff",   # bordo focus
    # accenti
    "accent":        "#58a6ff",   # link / accento principale
    "accent_sel":    "#1f6feb",   # selezione
    "accent_sel_fg": "#ffffff",   # testo su selezione
    "btn_hover":     "#444c56",   # hover toolbar button
    "btn_pressed":   "#2d333b",   # pressed toolbar button
    # send button (sempre verde — colore azione)
    "send_bg":       "#238636",
    "send_bg_hover": "#2ea043",
    "send_bg_press": "#1a6329",
    "send_border":   "#2ea043",
    "send_hover_b":  "#3fb950",
    "send_dis_bg":   "#21262d",
    "send_dis_fg":   "#484f58",
    "send_dis_brd":  "#30363d",
    # open-in-editor button
    "oie_bg":        "#1f6feb",
    "oie_bg_hover":  "#388bfd",
    "oie_border":    "#388bfd",
    # progress bar
    "progress_chunk":"#388bfd",
    # separatori
    "sep_color":     "#30363d",
}

_LIGHT_P = {
    # sfondi principali
    "bg_base":       "#ffffff",
    "bg_panel":      "#f6f8fa",
    "bg_panel2":     "#ffffff",
    "bg_toolbar":    "#f6f8fa",
    "bg_sidebar":    "#f6f8fa",
    "bg_input":      "#ffffff",
    "bg_input_url":  "#ffffff",
    "bg_code":       "#ffffff",
    "bg_alt_row":    "#f6f8fa",
    # testi
    "fg_primary":    "#24292f",
    "fg_secondary":  "#32383f",
    "fg_muted":      "#57606a",
    "fg_disabled":   "#8c959f",
    # bordi
    "border":        "#d0d7de",
    "border_input":  "#d0d7de",
    "border_focus":  "#0969da",
    # accenti
    "accent":        "#0969da",
    "accent_sel":    "#0969da",
    "accent_sel_fg": "#ffffff",
    "btn_hover":     "#eaeef2",
    "btn_pressed":   "#d0d7de",
    # send button
    "send_bg":       "#1a7f37",
    "send_bg_hover": "#1f8b3c",
    "send_bg_press": "#116329",
    "send_border":   "#1f8b3c",
    "send_hover_b":  "#28a745",
    "send_dis_bg":   "#f6f8fa",
    "send_dis_fg":   "#8c959f",
    "send_dis_brd":  "#d0d7de",
    # open-in-editor button
    "oie_bg":        "#0969da",
    "oie_bg_hover":  "#1f7ae0",
    "oie_border":    "#1f7ae0",
    # progress bar
    "progress_chunk":"#0969da",
    # separatori
    "sep_color":     "#d0d7de",
}


def _get_palette() -> dict:
    """Restituisce la palette corrente in base al tema attivo dell'applicazione."""
    try:
        from config.themes import ThemeManager
        return _DARK_P if ThemeManager.instance().is_dark() else _LIGHT_P
    except Exception:
        return _DARK_P


def _make_styles(p: dict) -> dict:
    """Costruisce tutti gli stylesheet del REST Client dalla palette p."""
    bg       = p["bg_base"]
    bg2      = p["bg_panel"]
    bg3      = p["bg_panel2"]
    tb       = p["bg_toolbar"]
    sidebar  = p["bg_sidebar"]
    inp      = p["bg_input"]
    inp_url  = p["bg_input_url"]
    code     = p["bg_code"]
    alt_row  = p["bg_alt_row"]
    fg       = p["fg_primary"]
    fg2      = p["fg_secondary"]
    muted    = p["fg_muted"]
    disabled = p["fg_disabled"]
    border   = p["border"]
    brd_in   = p["border_input"]
    brd_foc  = p["border_focus"]
    sel      = p["accent_sel"]
    sel_fg   = p["accent_sel_fg"]
    btn_hov  = p["btn_hover"]
    btn_prs  = p["btn_pressed"]

    code_area = (
        "QTextEdit {"
        f"  background: {code};"
        f"  color: {fg};"
        f"  border: 1px solid {border};"
        "  border-radius: 4px;"
        "  font-family: 'Cascadia Code', 'Fira Code', 'Courier New', monospace;"
        "  font-size: 11px;"
        "}"
        f"QTextEdit:focus {{ border-color: {brd_foc}; }}"
    )

    sidebar_style = (
        "QTreeWidget, QListWidget {"
        f"  background: {sidebar};"
        f"  color: {fg};"
        "  border: none;"
        "  outline: none;"
        "}"
        f"QTreeWidget::item, QListWidget::item {{ padding: 5px 8px; border-radius: 3px; }}"
        f"QTreeWidget::item:selected, QListWidget::item:selected {{ background: {sel}; color: {sel_fg}; }}"
        f"QTreeWidget::item:hover, QListWidget::item:hover {{ background: {btn_hov}; }}"
        f"QTreeWidget::branch {{ background: {sidebar}; }}"
        "QTreeWidget::branch:has-siblings:!adjoins-item { border-image: none; }"
        f"QTreeWidget::branch:open:has-children {{ color: {brd_foc}; }}"
    )

    toolbar_btn = (
        f"QPushButton {{ background: {inp}; color: {fg}; border: 1px solid {border};"
        "  border-radius: 4px; padding: 3px 10px; font-size: 11px; }"
        f"QPushButton:hover {{ background: {btn_hov}; border-color: {brd_foc}; }}"
        f"QPushButton:pressed {{ background: {btn_prs}; }}"
    )

    send_btn = (
        f"QPushButton {{ background: {p['send_bg']}; color: white; border: 1px solid {p['send_border']};"
        "  border-radius: 5px; padding: 6px 18px; font-weight: bold; font-size: 12px; }"
        f"QPushButton:hover {{ background: {p['send_bg_hover']}; border-color: {p['send_hover_b']}; }}"
        f"QPushButton:pressed {{ background: {p['send_bg_press']}; }}"
        f"QPushButton:disabled {{ background: {p['send_dis_bg']}; color: {p['send_dis_fg']}; border-color: {p['send_dis_brd']}; }}"
    )

    tab_style = (
        f"QTabWidget::pane {{ border: 1px solid {border}; border-radius: 0px;"
        f"  background: {bg3}; }}"
        f"QTabBar::tab {{ background: {bg2}; color: {muted}; padding: 6px 14px;"
        f"  border: 1px solid {border}; border-bottom: none;"
        "  border-top-left-radius: 4px; border-top-right-radius: 4px;"
        "  margin-right: 2px; font-size: 11px; }"
        f"QTabBar::tab:selected {{ background: {bg3}; color: {fg}; border-bottom-color: {bg3};"
        f"  border-top: 2px solid {brd_foc}; }}"
        f"QTabBar::tab:hover {{ background: {tb}; color: {fg2}; }}"
    )

    table_style = (
        f"QTableWidget {{ background: {bg2}; alternate-background-color: {alt_row}; color: {fg};"
        f"  gridline-color: {tb}; border: none; selection-background-color: {sel}; }}"
        f"QHeaderView::section {{ background: {tb}; color: {muted}; border: none;"
        f"  padding: 5px; border-bottom: 1px solid {border}; font-size: 11px; }}"
        "QTableWidget::item { padding: 3px 6px; }"
    )

    lineedit_style = (
        f"QLineEdit {{ background: {inp}; color: {fg2}; border: 1px solid {brd_in};"
        "  border-radius: 4px; padding: 3px 8px; font-size: 11px; }"
        f"QLineEdit:focus {{ border-color: {brd_foc}; color: {fg}; }}"
    )

    url_edit_style = (
        f"QLineEdit {{ background: {inp_url}; color: {fg};"
        f"  border: 1px solid {brd_in}; border-radius: 5px; padding: 6px 12px;"
        "  font-size: 12px; font-family: 'Cascadia Code', monospace; }"
        f"QLineEdit:focus {{ border-color: {brd_foc}; }}"
    )

    combo_style = (
        f"QComboBox {{ background: {inp}; color: {fg2}; border: 1px solid {brd_in};"
        "  border-radius: 4px; padding: 2px 8px; font-size: 11px; }"
        f"QComboBox QAbstractItemView {{ background: {bg2}; color: {fg};"
        f"  border: 1px solid {border}; selection-background-color: {sel}; }}"
    )

    auth_lineedit_style = (
        f"QLineEdit {{ background: {inp}; color: {fg2}; border: 1px solid {brd_in};"
        "  border-radius: 4px; padding: 4px 10px; }"
        f"QLineEdit:focus {{ border-color: {brd_foc}; }}"
        f"QLineEdit:disabled {{ color: {disabled}; background: {bg2}; }}"
    )

    icon_btn_style = (
        f"QPushButton {{ background: transparent; color: {muted}; border: none; font-size: 14px; }}"
        f"QPushButton:hover {{ color: {fg}; }}"
    )

    save_btn_style = (
        f"QPushButton {{ background: transparent; color: {muted}; border: 1px solid {border};"
        "  border-radius: 4px; padding: 3px 10px; font-size: 11px; }"
        f"QPushButton:hover {{ color: {fg}; border-color: {muted}; }}"
    )

    oie_btn_style = (
        f"QPushButton {{ background: {p['oie_bg']}; color: white; border: 1px solid {p['oie_border']};"
        "  border-radius: 4px; padding: 3px 10px; font-size: 11px; }"
        f"QPushButton:hover {{ background: {p['oie_bg_hover']}; }}"
    )

    splitter_style = f"QSplitter::handle {{ background: {border}; }}"

    sep_style = f"color: {p['sep_color']}; background: {p['sep_color']}; max-height: 1px;"

    progress_style = (
        "QProgressBar { border: none; background: transparent; margin: 0; }"
        f"QProgressBar::chunk {{ background: {p['progress_chunk']}; }}"
    )

    sidebar_btn_style = (
        f"QPushButton {{ background: transparent; color: {muted}; border: none; font-size: 14px; }}"
        f"QPushButton:hover {{ color: {fg}; }}"
    )

    resp_view_combo_style = (
        f"QComboBox {{ background: {inp}; color: {fg2}; border: 1px solid {border};"
        "  border-radius: 4px; padding: 2px 6px; font-size: 11px; }"
        f"QComboBox QAbstractItemView {{ background: {bg2}; color: {fg};"
        f"  border: 1px solid {border}; selection-background-color: {sel}; }}"
    )

    return {
        "code_area":        code_area,
        "sidebar":          sidebar_style,
        "toolbar_btn":      toolbar_btn,
        "send_btn":         send_btn,
        "tab":              tab_style,
        "table":            table_style,
        "lineedit":         lineedit_style,
        "url_edit":         url_edit_style,
        "combo":            combo_style,
        "auth_lineedit":    auth_lineedit_style,
        "icon_btn":         icon_btn_style,
        "save_btn":         save_btn_style,
        "oie_btn":          oie_btn_style,
        "splitter":         splitter_style,
        "sep":              sep_style,
        "progress":         progress_style,
        "sidebar_btn":      sidebar_btn_style,
        "resp_view_combo":  resp_view_combo_style,
        # valori singoli usati per setStyleSheet inline
        "bg_base":          bg,
        "bg_toolbar":       tb,
        "bg_sidebar":       sidebar,
        "fg_primary":       fg,
        "fg_muted":         muted,
        "border":           border,
        "border_focus":     brd_foc,
        "accent_sel":       sel,
    }


# Stili di default (dark) — usati come fallback prima che _apply_styles() venga chiamato
_DEFAULT_STYLES = _make_styles(_DARK_P)
_CODE_AREA_STYLE   = _DEFAULT_STYLES["code_area"]
_SIDEBAR_STYLE     = _DEFAULT_STYLES["sidebar"]
_TOOLBAR_BTN_STYLE = _DEFAULT_STYLES["toolbar_btn"]
_SEND_BTN_STYLE    = _DEFAULT_STYLES["send_btn"]
_TAB_STYLE         = _DEFAULT_STYLES["tab"]


def _method_style(method: str, p: Optional[dict] = None) -> str:
    """Restituisce lo stylesheet per il ComboBox/label del metodo HTTP."""
    if p is None:
        p = _get_palette()
    color = _METHOD_COLORS.get(method, p["fg_muted"])
    return (
        f"QComboBox {{ color: {color}; font-weight: bold; font-size: 12px;"
        f"  border: 2px solid {color}; border-radius: 5px;"
        f"  padding: 4px 8px; background: {p['bg_toolbar']}; }}"
        f"QComboBox::drop-down {{ border: none; width: 0px; }}"
        f"QComboBox QAbstractItemView {{ color: {p['fg_primary']}; background: {p['bg_panel']};"
        f"  border: 1px solid {p['border']}; selection-background-color: {p['accent_sel']}; }}"
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
        self.timeout: int = 30
        self.verify_ssl: bool = True
        self.allow_redirects: bool = True
        self.multipart_fields: List[dict] = []
        self.oauth2_client_id: str = ""
        self.oauth2_client_secret: str = ""
        self.oauth2_token_url: str = ""
        self.oauth2_scope: str = ""
        self.pre_script: str = ""
        self.post_tests: str = ""

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
            "timeout":     self.timeout,
            "verify_ssl":  self.verify_ssl,
            "allow_redirects": self.allow_redirects,
            "multipart_fields": self.multipart_fields,
            "oauth2_client_id": self.oauth2_client_id,
            "oauth2_client_secret": self.oauth2_client_secret,
            "oauth2_token_url": self.oauth2_token_url,
            "oauth2_scope": self.oauth2_scope,
            "pre_script": self.pre_script,
            "post_tests": self.post_tests,
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
        self.setWindowTitle("Wizard nuova richiesta HTTP")
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
        btn_tpl = QPushButton("Inserisci template JSON")
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
        btn_add = QPushButton("+ Aggiungi header")
        btn_add.clicked.connect(lambda: self._add_header_row("", ""))
        btn_del = QPushButton("- Rimuovi selezionato")
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
        btn_new = QPushButton("+ Nuovo")
        btn_new.clicked.connect(self._new_env)
        btn_del = QPushButton("- Elimina")
        btn_del.clicked.connect(self._del_env)
        top.addWidget(btn_new)
        top.addWidget(btn_del)
        lay.addLayout(top)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Variabile  (es. base_url)", "Valore"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self._table)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Aggiungi variabile")
        btn_add.clicked.connect(lambda: self._add_var("", ""))
        btn_rem = QPushButton("- Rimuovi variabile")
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
        btns.button(QDialogButtonBox.StandardButton.Ok).setText(tr("button.ok", default="OK"))
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("button.cancel", default="Cancel"))

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
        self._cancel_flag = threading.Event()

    def cancel(self):
        self._cancel_flag.set()

    def _resolve_auth(self, headers: dict) -> Optional[str]:
        req = self._req
        env = self._env
        if req.auth_type == "Bearer Token" and req.auth_value:
            headers["Authorization"] = f"Bearer {env.resolve(req.auth_value)}"
        elif req.auth_type == "Basic (user:pass)" and req.auth_value:
            encoded = base64.b64encode(env.resolve(req.auth_value).encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        elif req.auth_type == "API Key (header)" and req.auth_value:
            hdr = req.auth_header or "X-Api-Key"
            headers[hdr] = env.resolve(req.auth_value)
        elif req.auth_type == "OAuth 2.0":
            token = self._do_oauth2_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
            else:
                return "OAuth 2.0 token request failed"
        return None

    def _do_oauth2_token(self) -> str:
        req = self._req
        env = self._env
        token_url = env.resolve(req.oauth2_token_url)
        client_id = env.resolve(req.oauth2_client_id)
        client_secret = env.resolve(req.oauth2_client_secret)
        scope = env.resolve(req.oauth2_scope)
        if not token_url or not client_id:
            return ""
        try:
            data = {"grant_type": "client_credentials"}
            if scope:
                data["scope"] = scope
            auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            hdrs = {"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"}
            if _HAS_REQUESTS:
                r = _requests_lib.post(token_url, data=data, headers=hdrs, timeout=req.timeout, verify=req.verify_ssl)
                if r.status_code == 200:
                    return r.json().get("access_token", "")
            else:
                body = urllib.parse.urlencode(data).encode()
                http_req = urllib.request.Request(token_url, data=body, headers=hdrs, method="POST")
                with urllib.request.urlopen(http_req, timeout=req.timeout) as resp:
                    return json.loads(resp.read()).get("access_token", "")
        except Exception:
            return ""

    def run(self):
        req = self._req
        env = self._env
        try:
            url = env.resolve(req.url)
            if self._cancel_flag.is_set():
                return

            headers = {}
            auth_err = self._resolve_auth(headers)
            if auth_err:
                self.error.emit(auth_err)
                return

            for k, v in req.headers.items():
                headers[env.resolve(k)] = env.resolve(v)

            if self._cancel_flag.is_set():
                return

            if _HAS_REQUESTS:
                self._run_requests(url, headers)
            else:
                self._run_urllib(url, headers)

        except Exception as exc:
            self.error.emit(str(exc))

    def _run_requests(self, url: str, headers: dict):
        req = self._req
        env = self._env
        session = _requests_lib.Session()
        session.verify = req.verify_ssl

        body_kwargs = self._build_body_requests(env)
        if self._cancel_flag.is_set():
            return

        t0 = time.perf_counter()
        resp = session.request(
            method=req.method,
            url=url,
            headers=headers,
            timeout=req.timeout,
            allow_redirects=req.allow_redirects,
            **body_kwargs,
        )
        elapsed = time.perf_counter() - t0
        ct = resp.headers.get("Content-Type", "")
        body_str = resp.text

        self.finished.emit({
            "status": resp.status_code,
            "headers": dict(resp.headers),
            "body": body_str,
            "elapsed": elapsed,
            "content_type": ct,
        })

    def _run_urllib(self, url: str, headers: dict):
        req = self._req
        env = self._env
        body_bytes = self._build_body_urllib(env)
        if self._cancel_flag.is_set():
            return

        http_req = urllib.request.Request(url, data=body_bytes, headers=headers, method=req.method)
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(http_req, timeout=req.timeout) as resp:
                elapsed = time.perf_counter() - t0
                raw_body = resp.read()
                resp_headers = dict(resp.getheaders())
                status = resp.status
        except urllib.error.HTTPError as e:
            elapsed = time.perf_counter() - t0
            raw_body = e.read()
            resp_headers = dict(e.headers)
            status = e.code

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
            "status": status,
            "headers": resp_headers,
            "body": body_str,
            "elapsed": elapsed,
            "content_type": ct_hdr,
        })

    def _build_body_requests(self, env) -> dict:
        req = self._req
        if req.body_type == "Nessuno" or not req.body:
            return {}
        body_text = env.resolve(req.body)
        if req.body_type == "JSON":
            return {"json": json.loads(body_text)}
        elif req.body_type == "Form (x-www-form-urlencoded)":
            data = {}
            for line in body_text.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    data[k.strip()] = v.strip()
            return {"data": data}
        elif req.body_type == "Multipart (form-data)":
            files = {}
            for f in req.multipart_fields:
                name = f.get("name", "")
                path = f.get("path", "")
                if name and path and os.path.isfile(path):
                    files[name] = (os.path.basename(path), open(path, "rb"))
            data = {}
            for line in body_text.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    data[k.strip()] = v.strip()
            kw = {}
            if files:
                kw["files"] = files
            if data:
                kw["data"] = data
            return kw
        else:
            ct = _CONTENT_TYPE_MAP.get(req.body_type, "text/plain")
            if "headers" not in req.headers:
                pass
            return {"data": body_text.encode("utf-8")}

    def _build_body_urllib(self, env):
        req = self._req
        if req.body_type == "Nessuno" or not req.body:
            return None
        body_text = env.resolve(req.body)
        if req.body_type == "Form (x-www-form-urlencoded)":
            return urllib.parse.urlencode(
                dict(p.split("=", 1) for p in body_text.splitlines() if "=" in p)
            ).encode()
        return body_text.encode("utf-8")


# ─── Pannello principale ──────────────────────────────────────────────────────

class _RestPanel(QWidget):
    """Widget principale del REST Client."""

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self._mw = main_window
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
        self._last_response_body: str = ""
        self._build_ui()
        self._load_data()
        # Applica il tema corretto subito dopo la costruzione della UI
        self._apply_styles()
        # Connette al signal theme_changed per aggiornare gli stili al cambio tema
        try:
            from config.themes import ThemeManager
            ThemeManager.instance().theme_changed.connect(
                lambda _: self._apply_styles()
            )
        except Exception:
            pass

    # ── Tema dinamico ─────────────────────────────────────────────────────────

    def _apply_styles(self):
        """Ricalcola e riapplica tutti gli stylesheet in base al tema attivo."""
        p  = _get_palette()
        st = _make_styles(p)

        # Widget contenitore
        self._sidebar_w.setStyleSheet(f"background: {p['bg_sidebar']};")
        self._right_w.setStyleSheet(f"background: {p['bg_base']};")
        self._toolbar_w.setStyleSheet(
            f"background: {p['bg_toolbar']}; border-bottom: 1px solid {p['border']};"
        )
        self._req_panel.setStyleSheet(f"background: {p['bg_base']};")
        self._resp_panel.setStyleSheet(f"background: {p['bg_base']};")

        # Splitter
        self._hsplit.setStyleSheet(st["splitter"])
        self._vsplit.setStyleSheet(st["splitter"])

        # Separatori
        for sep in self._separators:
            sep.setStyleSheet(st["sep"])

        # Sidebar tree/list
        self._coll_tree.setStyleSheet(st["sidebar"])
        self._hist_list.setStyleSheet(st["sidebar"])

        # Label sidebar
        self._lbl_coll.setStyleSheet(
            f"color: {p['fg_muted']}; font-size: 10px; font-weight: bold; letter-spacing: 1px;"
        )
        self._lbl_hist.setStyleSheet(
            f"color: {p['fg_muted']}; font-size: 10px; font-weight: bold;"
            f" letter-spacing: 1px; padding: 6px 6px 2px;"
            f" background: {p['bg_sidebar']};"
        )

        # Bottoni sidebar (icona)
        for btn in self._sidebar_icon_btns:
            btn.setStyleSheet(st["sidebar_btn"])

        # Bottoni toolbar principale
        for btn in self._toolbar_btns:
            btn.setStyleSheet(st["toolbar_btn"])

        # Name / URL
        self._req_name_edit.setStyleSheet(st["lineedit"])
        self._url_edit.setStyleSheet(st["url_edit"])
        self._env_cb.setStyleSheet(st["combo"])
        self._lbl_env.setStyleSheet(f"color: {p['fg_muted']}; font-size: 11px;")

        # Metodo HTTP ComboBox
        self._method_cb.setStyleSheet(_method_style(self._method_cb.currentText(), p))

        # Pulsante Invia
        self._btn_send.setStyleSheet(st["send_btn"])

        # Progress bar
        self._progress.setStyleSheet(st["progress"])

        # Tab richiesta / risposta
        self._req_tabs.setStyleSheet(st["tab"])
        self._resp_tabs.setStyleSheet(st["tab"])

        # Tabelle
        for tbl in self._styled_tables:
            tbl.setStyleSheet(st["table"])

        # Auth
        self._auth_w.setStyleSheet(
            f"background: {p['bg_base']}; QLabel {{ color: {p['fg_secondary']}; }}"
        )
        self._lbl_auth_title.setStyleSheet(
            f"color: {p['fg_primary']}; font-weight: bold; font-size: 12px; margin-bottom: 4px;"
        )
        self._auth_type_cb.setStyleSheet(st["combo"])
        self._auth_val_edit.setStyleSheet(st["auth_lineedit"])
        self._auth_show_chk.setStyleSheet(f"color: {p['fg_muted']};")
        self._auth_hdr_edit.setStyleSheet(st["auth_lineedit"])

        # Body
        self._lbl_body_type.setStyleSheet(f"color: {p['fg_muted']}; font-size: 11px;")
        self._body_type_cb.setStyleSheet(st["combo"])
        self._body_edit.setStyleSheet(st["code_area"])
        self._btn_prettify.setStyleSheet(st["toolbar_btn"])

        # Pre-request
        self._lbl_pre.setStyleSheet(f"color: {p['fg_muted']}; font-size: 11px; margin-bottom: 4px;")
        self._pre_req_edit.setStyleSheet(st["code_area"])

        # Risposta — status bar
        self._lbl_resp.setStyleSheet(f"font-weight: bold; color: {p['fg_primary']}; font-size: 11px;")
        self._status_lbl.setStyleSheet(f"color: {p['fg_muted']}; font-size: 11px;")
        self._resp_view_cb.setStyleSheet(st["resp_view_combo"])
        self._btn_copy_resp.setStyleSheet(st["icon_btn"])
        self._btn_open_in_editor.setStyleSheet(st["oie_btn"])
        self._btn_save_resp.setStyleSheet(st["save_btn"])

        # Risposta — body / raw
        self._resp_body.setStyleSheet(st["code_area"])
        self._resp_raw.setStyleSheet(st["code_area"])

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Liste di widget da ri-stilare al cambio tema
        self._toolbar_btns: list = []
        self._sidebar_icon_btns: list = []
        self._styled_tables: list = []
        self._separators: list = []

        # ── splitter orizzontale: sidebar sx + area principale dx ─────────────
        self._hsplit = QSplitter(Qt.Orientation.Horizontal)
        self._hsplit.setChildrenCollapsible(False)
        self._hsplit.setHandleWidth(1)
        hsplit = self._hsplit  # alias locale per compatibilità codice successivo

        # ═══════════════════════════════════════════════════════════════════════
        # PANNELLO SINISTRO — Sidebar (Collection tree + Cronologia)
        # ═══════════════════════════════════════════════════════════════════════
        sidebar_w = QWidget()
        self._sidebar_w = sidebar_w
        sidebar_lay = QVBoxLayout(sidebar_w)
        sidebar_lay.setContentsMargins(0, 0, 0, 0)
        sidebar_lay.setSpacing(0)

        # toolbar sidebar
        sidebar_toolbar = QHBoxLayout()
        sidebar_toolbar.setContentsMargins(6, 6, 6, 4)
        sidebar_toolbar.setSpacing(4)
        lbl_coll = QLabel("Collection")
        self._lbl_coll = lbl_coll
        sidebar_toolbar.addWidget(lbl_coll)
        sidebar_toolbar.addStretch()
        btn_add_folder = QPushButton("+dir")
        btn_add_folder.setToolTip("Nuova cartella")
        btn_add_folder.setFixedSize(26, 22)
        btn_add_folder.clicked.connect(self._add_folder)
        self._sidebar_icon_btns.append(btn_add_folder)
        sidebar_toolbar.addWidget(btn_add_folder)
        btn_add_req = QPushButton("+")
        btn_add_req.setToolTip("Salva richiesta corrente nella collection")
        btn_add_req.setFixedSize(26, 22)
        btn_add_req.clicked.connect(self._add_to_collection)
        self._sidebar_icon_btns.append(btn_add_req)
        sidebar_toolbar.addWidget(btn_add_req)
        sidebar_lay.addLayout(sidebar_toolbar)

        # Separatore
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        self._separators.append(sep)
        sidebar_lay.addWidget(sep)

        # QTreeWidget per la collection (con folder e request)
        self._coll_tree = QTreeWidget()
        self._coll_tree.setHeaderHidden(True)
        self._coll_tree.setStyleSheet(_SIDEBAR_STYLE)
        self._coll_tree.setIndentation(16)
        self._coll_tree.setAnimated(True)
        self._coll_tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._coll_tree.itemDoubleClicked.connect(self._tree_item_activated)
        self._coll_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._coll_tree.customContextMenuRequested.connect(self._coll_context_menu)
        sidebar_lay.addWidget(self._coll_tree, stretch=3)

        # Separatore
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        self._separators.append(sep2)
        sidebar_lay.addWidget(sep2)

        # Label cronologia
        lbl_hist = QLabel("Cronologia")
        self._lbl_hist = lbl_hist
        sidebar_lay.addWidget(lbl_hist)

        # Lista cronologia
        self._hist_list = QListWidget()
        self._hist_list.setStyleSheet(_SIDEBAR_STYLE)
        self._hist_list.setMaximumHeight(140)
        self._hist_list.itemDoubleClicked.connect(self._load_from_history)
        self._hist_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._hist_list.customContextMenuRequested.connect(self._hist_context_menu)
        sidebar_lay.addWidget(self._hist_list, stretch=1)

        sidebar_w.setMinimumWidth(160)
        sidebar_w.setMaximumWidth(260)
        hsplit.addWidget(sidebar_w)

        # ═══════════════════════════════════════════════════════════════════════
        # PANNELLO DESTRO — Request editor + Response viewer
        # ═══════════════════════════════════════════════════════════════════════
        right_w = QWidget()
        self._right_w = right_w
        right_lay = QVBoxLayout(right_w)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        # ── toolbar superiore ─────────────────────────────────────────────────
        toolbar_w = QWidget()
        self._toolbar_w = toolbar_w
        toolbar = QHBoxLayout(toolbar_w)
        toolbar.setContentsMargins(6, 4, 6, 4)
        toolbar.setSpacing(4)

        for text, tip, slot in [
            ("+ Nuova",         "Nuova richiesta",                          self._new_request),
            ("Wizard",          "Wizard guidato passo dopo passo",           self._open_wizard),
            ("Importa cURL",    "Importa da cURL (clipboard o incolla)",     self._import_curl),
            ("Salva",           "Salva collection in file .http",            self._save_collection),
            ("Carica",          "Carica collection da file .http",           self._load_collection),
            ("Ambienti",        "Gestisci variabili d'ambiente ({{VAR}})",   self._manage_envs),
            ("\u25b6 Runner",    "Esegui tutte le richieste in sequenza",     self._open_runner),
            ("Snippets",        "Genera codice (cURL / Python / JS)",        self._show_code_snippets),
        ]:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            self._toolbar_btns.append(b)
            toolbar.addWidget(b)
            if text in ("+ Nuova", "Importa cURL", "Carica"):
                setattr(self, {
                    "+ Nuova": "_btn_new",
                    "Importa cURL": "_btn_curl",
                    "Carica": "_btn_load_coll",
                }[text], b)
            elif text == "Salva":
                self._btn_save_coll = b
            elif text == "Ambienti":
                self._btn_env = b
            elif text == "Wizard":
                self._btn_wizard = b

        toolbar.addStretch()
        right_lay.addWidget(toolbar_w)

        # ── splitter verticale: request (su) + response (giù) ─────────────────
        self._vsplit = QSplitter(Qt.Orientation.Vertical)
        self._vsplit.setChildrenCollapsible(False)
        self._vsplit.setHandleWidth(2)
        vsplit = self._vsplit  # alias locale

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # SEZIONE RICHIESTA
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        req_panel = QWidget()
        self._req_panel = req_panel
        req_panel_lay = QVBoxLayout(req_panel)
        req_panel_lay.setContentsMargins(8, 8, 8, 4)
        req_panel_lay.setSpacing(4)

        # ── Name bar (nome richiesta + ambiente) ──────────────────────────────
        name_bar = QHBoxLayout()
        name_bar.setSpacing(6)
        self._req_name_edit = QLineEdit()
        self._req_name_edit.setPlaceholderText("Nome richiesta (opzionale)")
        name_bar.addWidget(self._req_name_edit, stretch=1)

        lbl_env = QLabel("Ambiente:")
        self._lbl_env = lbl_env
        name_bar.addWidget(lbl_env)
        self._env_cb = QComboBox()
        for e in self._envs:
            self._env_cb.addItem(e.name)
        self._env_cb.setFixedWidth(90)
        name_bar.addWidget(self._env_cb)
        req_panel_lay.addLayout(name_bar)

        # ── URL bar (metodo + URL + invia) ────────────────────────────────────
        req_bar = QHBoxLayout()
        req_bar.setSpacing(4)

        self._method_cb = QComboBox()
        self._method_cb.addItems(_HTTP_METHODS)
        self._method_cb.setFixedWidth(95)
        self._method_cb.currentTextChanged.connect(
            lambda m: self._method_cb.setStyleSheet(_method_style(m, _get_palette()))
        )
        req_bar.addWidget(self._method_cb)

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://api.esempio.com/endpoint  oppure  {{base_url}}/path")
        req_bar.addWidget(self._url_edit, stretch=1)

        self._btn_send = QPushButton("Invia")
        self._btn_send.setFixedWidth(80)
        self._btn_send.clicked.connect(self._send_request)
        req_bar.addWidget(self._btn_send)

        self._btn_abort = QPushButton("Stop")
        self._btn_abort.setFixedWidth(45)
        self._btn_abort.setEnabled(False)
        self._btn_abort.setStyleSheet("color: #f44747;")
        self._btn_abort.clicked.connect(self._abort_request)
        req_bar.addWidget(self._btn_abort)

        req_panel_lay.addLayout(req_bar)

        # ── Options bar (timeout, SSL, redirect) ────────────────────────────────
        opts_bar = QHBoxLayout()
        opts_bar.setSpacing(6)

        opts_bar.addWidget(QLabel("Timeout:"))
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(1, 300)
        self._timeout_spin.setValue(30)
        self._timeout_spin.setSuffix(" s")
        self._timeout_spin.setFixedWidth(65)
        opts_bar.addWidget(self._timeout_spin)

        self._ssl_chk = QCheckBox("SSL verify")
        self._ssl_chk.setChecked(True)
        opts_bar.addWidget(self._ssl_chk)

        self._redirect_chk = QCheckBox("Redirect")
        self._redirect_chk.setChecked(True)
        opts_bar.addWidget(self._redirect_chk)

        opts_bar.addStretch()
        req_panel_lay.addLayout(opts_bar)

        # progress bar (thin, come VS Code)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(3)
        self._progress.setVisible(False)
        req_panel_lay.addWidget(self._progress)

        # ── Tab richiesta: Params / Auth / Body / Headers / Pre-request ───────
        self._req_tabs = QTabWidget()
        self._req_tabs.setStyleSheet(_TAB_STYLE)

        # ─ Params ─────────────────────────────────────────────────────────────
        params_w = QWidget()
        params_lay = QVBoxLayout(params_w)
        params_lay.setContentsMargins(4, 4, 4, 4)
        self._params_table = QTableWidget(0, 3)
        self._params_table.setHorizontalHeaderLabels(["✔", "Chiave", "Valore"])
        self._params_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._params_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._params_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._params_table.setColumnWidth(0, 28)
        self._params_table.setAlternatingRowColors(True)
        self._styled_tables.append(self._params_table)
        params_lay.addWidget(self._params_table)
        params_btn = QHBoxLayout()
        params_btn.addWidget(self._make_btn("➕ Aggiungi", lambda: self._add_param_row("", "")))
        params_btn.addWidget(self._make_btn("🗑 Rimuovi", self._remove_param_row))
        params_btn.addStretch()
        params_lay.addLayout(params_btn)
        self._req_tabs.addTab(params_w, "Params")

        # ─ Auth ───────────────────────────────────────────────────────────────
        auth_w = QWidget()
        self._auth_w = auth_w
        auth_lay = QFormLayout(auth_w)
        auth_lay.setContentsMargins(16, 14, 16, 14)
        auth_lay.setSpacing(10)
        lbl_auth_title = QLabel("Autenticazione")
        self._lbl_auth_title = lbl_auth_title
        auth_lay.addRow(lbl_auth_title)
        self._auth_type_cb = QComboBox()
        self._auth_type_cb.addItems(_AUTH_TYPES)
        self._auth_type_cb.currentTextChanged.connect(self._auth_type_changed)
        auth_lay.addRow("Tipo:", self._auth_type_cb)
        self._auth_val_edit = QLineEdit()
        self._auth_val_edit.setPlaceholderText("Token / user:pass / API-key")
        self._auth_val_edit.setEchoMode(QLineEdit.EchoMode.Password)
        auth_lay.addRow("Valore:", self._auth_val_edit)
        # checkbox mostra/nascondi token
        self._auth_show_chk = QCheckBox("Mostra valore")
        self._auth_show_chk.toggled.connect(
            lambda on: self._auth_val_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        auth_lay.addRow("", self._auth_show_chk)
        self._auth_hdr_edit = QLineEdit("X-Api-Key")
        self._auth_hdr_edit.setPlaceholderText("Nome header (solo API Key)")
        self._auth_hdr_edit.setEnabled(False)
        auth_lay.addRow("Header (API Key):", self._auth_hdr_edit)

        # OAuth 2.0 fields
        self._oauth2_widget = QWidget()
        oauth2_lay = QFormLayout(self._oauth2_widget)
        oauth2_lay.setContentsMargins(0, 0, 0, 0)
        self._oauth2_token_url = QLineEdit()
        self._oauth2_token_url.setPlaceholderText("https://auth.server/oauth/token")
        oauth2_lay.addRow("Token URL:", self._oauth2_token_url)
        self._oauth2_client_id = QLineEdit()
        self._oauth2_client_id.setPlaceholderText("client_id")
        oauth2_lay.addRow("Client ID:", self._oauth2_client_id)
        self._oauth2_client_secret = QLineEdit()
        self._oauth2_client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self._oauth2_client_secret.setPlaceholderText("client_secret")
        oauth2_lay.addRow("Client Secret:", self._oauth2_client_secret)
        self._oauth2_scope = QLineEdit()
        self._oauth2_scope.setPlaceholderText("read write (opzionale)")
        oauth2_lay.addRow("Scope:", self._oauth2_scope)
        self._oauth2_widget.setVisible(False)
        auth_lay.addRow(self._oauth2_widget)

        self._req_tabs.addTab(auth_w, "Auth")

        # ─ Body ───────────────────────────────────────────────────────────────
        body_w = QWidget()
        body_lay = QVBoxLayout(body_w)
        body_lay.setContentsMargins(4, 4, 4, 4)
        body_lay.setSpacing(4)
        body_bar = QHBoxLayout()
        lbl_body_type = QLabel("Tipo:")
        self._lbl_body_type = lbl_body_type
        body_bar.addWidget(lbl_body_type)
        self._body_type_cb = QComboBox()
        self._body_type_cb.addItems(_BODY_TYPES)
        body_bar.addWidget(self._body_type_cb)
        body_bar.addStretch()
        btn_prettify_body = QPushButton("Formatta")
        btn_prettify_body.setToolTip("Formatta il body JSON")
        btn_prettify_body.clicked.connect(self._prettify_body)
        self._btn_prettify = btn_prettify_body
        body_bar.addWidget(btn_prettify_body)
        body_lay.addLayout(body_bar)
        self._body_edit = QTextEdit()
        self._body_edit.setFont(QFont("Monospace", 10))
        self._body_edit.setPlaceholderText('{\n  "chiave": "valore"\n}')
        _JsonHighlighter(self._body_edit.document())
        body_lay.addWidget(self._body_edit)

        # Multipart file upload
        self._multipart_widget = QWidget()
        mp_lay = QVBoxLayout(self._multipart_widget)
        mp_lay.setContentsMargins(0, 4, 0, 0)
        mp_lay.addWidget(QLabel("File upload (per multipart):"))
        self._mp_table = QTableWidget(0, 3)
        self._mp_table.setHorizontalHeaderLabels(["Nome campo", "Percorso file", ""])
        self._mp_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._mp_table.setColumnWidth(0, 120)
        self._mp_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._mp_table.setColumnWidth(2, 28)
        self._mp_table.setMaximumHeight(100)
        mp_lay.addWidget(self._mp_table)
        mp_btn = QHBoxLayout()
        mp_btn.addWidget(self._make_btn("➕ Aggiungi file", self._add_multipart_row))
        mp_btn.addWidget(self._make_btn("🗑 Rimuovi", self._remove_multipart_row))
        mp_btn.addStretch()
        mp_lay.addLayout(mp_btn)
        self._multipart_widget.setVisible(False)
        body_lay.addWidget(self._multipart_widget)

        self._body_type_cb.currentTextChanged.connect(self._body_type_changed)
        self._req_tabs.addTab(body_w, "Body")

        # ─ Headers ────────────────────────────────────────────────────────────
        hdr_w = QWidget()
        hdr_lay = QVBoxLayout(hdr_w)
        hdr_lay.setContentsMargins(4, 4, 4, 4)
        self._hdr_table = QTableWidget(0, 2)
        self._hdr_table.setHorizontalHeaderLabels(["Header", "Valore"])
        self._hdr_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._hdr_table.setAlternatingRowColors(True)
        self._styled_tables.append(self._hdr_table)
        hdr_lay.addWidget(self._hdr_table)
        hdr_btn = QHBoxLayout()
        hdr_btn.addWidget(self._make_btn("➕ Aggiungi", lambda: self._add_header_row("", "")))
        hdr_btn.addWidget(self._make_btn("🗑 Rimuovi", self._remove_header_row))
        hdr_btn.addStretch()
        hdr_lay.addLayout(hdr_btn)
        self._req_tabs.addTab(hdr_w, "Headers")

        # ─ Pre-request ────────────────────────────────────────────────────────
        pre_w = QWidget()
        pre_lay = QVBoxLayout(pre_w)
        pre_lay.setContentsMargins(4, 4, 4, 4)
        lbl_pre = QLabel("Script eseguito prima dell'invio — usa pm.variables['NOME'] per estrarre valori:")
        self._lbl_pre = lbl_pre
        pre_lay.addWidget(lbl_pre)
        self._pre_req_edit = QTextEdit()
        self._pre_req_edit.setFont(QFont("Monospace", 10))
        self._pre_req_edit.setPlaceholderText(
            "# Estrai un token dalla risposta precedente e usalo nella prossima richiesta:\n"
            "# pm.variables['TOKEN'] = pm.last_response_body.get('access_token', '')\n\n"
            "# Oppure imposta variabili d'ambiente:\n"
            "# pm.variables['USER_ID'] = '12345'"
        )
        pre_lay.addWidget(self._pre_req_edit)
        self._req_tabs.addTab(pre_w, "Pre-request")

        req_panel_lay.addWidget(self._req_tabs, stretch=1)

        vsplit.addWidget(req_panel)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # SEZIONE RISPOSTA
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        resp_panel = QWidget()
        self._resp_panel = resp_panel
        resp_panel_lay = QVBoxLayout(resp_panel)
        resp_panel_lay.setContentsMargins(8, 6, 8, 8)
        resp_panel_lay.setSpacing(4)

        # status bar risposta (status badge + time + size + pulsanti)
        resp_status_bar = QHBoxLayout()
        resp_status_bar.setSpacing(8)
        lbl_resp = QLabel("Risposta")
        self._lbl_resp = lbl_resp
        resp_status_bar.addWidget(lbl_resp)
        self._status_lbl = QLabel("—")
        resp_status_bar.addWidget(self._status_lbl)
        resp_status_bar.addStretch()

        # pulsanti area risposta
        self._resp_view_cb = QComboBox()
        self._resp_view_cb.addItems(["Pretty", "Raw"])
        self._resp_view_cb.setFixedWidth(72)
        self._resp_view_cb.currentTextChanged.connect(self._toggle_resp_view)
        resp_status_bar.addWidget(self._resp_view_cb)

        self._btn_copy_resp = QPushButton("Copia")
        self._btn_copy_resp.setToolTip("Copia risposta negli appunti")
        self._btn_copy_resp.setFixedSize(26, 22)
        self._btn_copy_resp.clicked.connect(self._copy_response)
        resp_status_bar.addWidget(self._btn_copy_resp)

        self._btn_open_in_editor = QPushButton("Apri in editor")
        self._btn_open_in_editor.setToolTip("Apri la risposta in un nuovo tab dell'editor")
        self._btn_open_in_editor.clicked.connect(self._open_response_in_editor)
        resp_status_bar.addWidget(self._btn_open_in_editor)

        self._btn_save_resp = QPushButton("Salva")
        self._btn_save_resp.setToolTip("Salva la risposta su file")
        self._btn_save_resp.clicked.connect(self._save_response)
        resp_status_bar.addWidget(self._btn_save_resp)

        resp_panel_lay.addLayout(resp_status_bar)

        # ─ Tab risposta: Body / Headers / Cookies / Raw ────────────────────────
        self._resp_tabs = QTabWidget()
        resp_tabs = self._resp_tabs  # alias locale

        # Body (Pretty)
        body_resp_w = QWidget()
        body_resp_lay = QVBoxLayout(body_resp_w)
        body_resp_lay.setContentsMargins(0, 0, 0, 0)
        self._resp_body = QTextEdit()
        self._resp_body.setReadOnly(True)
        self._resp_body.setFont(QFont("Monospace", 10))
        _JsonHighlighter(self._resp_body.document())
        body_resp_lay.addWidget(self._resp_body)
        resp_tabs.addTab(body_resp_w, "Body")

        # Headers risposta
        hdr_resp_w = QWidget()
        hdr_resp_lay = QVBoxLayout(hdr_resp_w)
        hdr_resp_lay.setContentsMargins(4, 4, 4, 4)
        self._resp_hdr_table = QTableWidget(0, 2)
        self._resp_hdr_table.setHorizontalHeaderLabels(["Header", "Valore"])
        self._resp_hdr_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._resp_hdr_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._resp_hdr_table.setAlternatingRowColors(True)
        self._styled_tables.append(self._resp_hdr_table)
        hdr_resp_lay.addWidget(self._resp_hdr_table)
        resp_tabs.addTab(hdr_resp_w, "Headers")

        # Cookies risposta
        cookies_resp_w = QWidget()
        cookies_resp_lay = QVBoxLayout(cookies_resp_w)
        cookies_resp_lay.setContentsMargins(4, 4, 4, 4)
        self._resp_cookies_table = QTableWidget(0, 4)
        self._resp_cookies_table.setHorizontalHeaderLabels(["Nome", "Valore", "Domain", "Path"])
        self._resp_cookies_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._resp_cookies_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._resp_cookies_table.setAlternatingRowColors(True)
        self._styled_tables.append(self._resp_cookies_table)
        cookies_resp_lay.addWidget(self._resp_cookies_table)
        resp_tabs.addTab(cookies_resp_w, "Cookies")

        # Raw (testo grezzo)
        raw_resp_w = QWidget()
        raw_resp_lay = QVBoxLayout(raw_resp_w)
        raw_resp_lay.setContentsMargins(0, 0, 0, 0)
        self._resp_raw = QTextEdit()
        self._resp_raw.setReadOnly(True)
        self._resp_raw.setFont(QFont("Monospace", 9))
        raw_resp_lay.addWidget(self._resp_raw)
        resp_tabs.addTab(raw_resp_w, "Raw")

        # ─ Tests ────────────────────────────────────────────────────────────────
        tests_w = QWidget()
        tests_lay = QVBoxLayout(tests_w)
        tests_lay.setContentsMargins(4, 4, 4, 4)
        self._tests_edit = QTextEdit()
        self._tests_edit.setFont(QFont("Monospace", 10))
        self._tests_edit.setPlaceholderText(
            "# pm.test('Status is 200', pm.response.status == 200)\n"
            "# pm.test('Body contains id', 'id' in pm.response.text)\n"
            "# pm.test('Response time < 1s', pm.response.elapsed < 1)\n"
            "# pm.test('JSON has key', pm.response.json.get('key') is not None)\n"
        )
        tests_lay.addWidget(self._tests_edit)
        self._tests_results = QTextEdit()
        self._tests_results.setReadOnly(True)
        self._tests_results.setFont(QFont("Monospace", 9))
        self._tests_results.setMaximumHeight(130)
        tests_lay.addWidget(self._tests_results)
        resp_tabs.addTab(tests_w, "Tests")
        self._resp_raw.setFont(QFont("Monospace", 9))
        raw_resp_lay.addWidget(self._resp_raw)
        resp_tabs.addTab(raw_resp_w, "Raw")

        resp_panel_lay.addWidget(resp_tabs, stretch=1)

        # pulsante inserisci (nascosto nella status bar, spostato qui sotto)
        self._btn_insert_resp = QPushButton("Inserisci nel cursore")
        self._btn_insert_resp.setToolTip("Inserisce il body della risposta nella posizione del cursore nell'editor attivo")
        self._btn_insert_resp.clicked.connect(self._insert_response)
        # (non aggiunto al layout, disponibile via context menu / menu azione)

        vsplit.addWidget(resp_panel)
        vsplit.setSizes([350, 350])

        right_lay.addWidget(vsplit, stretch=1)

        hsplit.addWidget(right_w)
        hsplit.setSizes([210, 790])
        root.addWidget(hsplit, stretch=1)

    def _make_btn(self, text: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.clicked.connect(slot)
        return b

    # ── Helpers UI ────────────────────────────────────────────────────────────

    def _auth_type_changed(self, t: str):
        self._auth_val_edit.setEnabled(t != "Nessuna")
        self._auth_hdr_edit.setEnabled(t == "API Key (header)")
        # OAuth 2.0
        is_oauth = (t == "OAuth 2.0")
        self._auth_val_edit.setVisible(not is_oauth)
        self._auth_show_chk.setVisible(not is_oauth)
        self._auth_hdr_edit.setVisible(not is_oauth)
        self._oauth2_widget.setVisible(is_oauth)

    def _body_type_changed(self, t: str):
        is_multipart = (t == "Multipart (form-data)")
        self._multipart_widget.setVisible(is_multipart)
        if is_multipart:
            self._body_edit.setPlaceholderText("key=value (una per riga)")
        elif t == "JSON":
            self._body_edit.setPlaceholderText('{\n  "chiave": "valore"\n}')
        elif t == "XML":
            self._body_edit.setPlaceholderText('<?xml version="1.0"?>\n<root>\n</root>')
        elif t == "Nessuno":
            self._body_edit.setPlaceholderText("")
        else:
            self._body_edit.setPlaceholderText("key=value (una per riga)")

    def _add_multipart_row(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Seleziona file", "", "Tutti i file (*)")
        if not path:
            return
        name = os.path.basename(path).split(".")[0]
        r = self._mp_table.rowCount()
        self._mp_table.insertRow(r)
        self._mp_table.setItem(r, 0, QTableWidgetItem(name))
        self._mp_table.setItem(r, 1, QTableWidgetItem(path))
        btn = QPushButton("✕")
        btn.setFixedSize(22, 22)
        btn.clicked.connect(lambda: self._remove_multipart_row())
        self._mp_table.setCellWidget(r, 2, btn)

    def _remove_multipart_row(self):
        rows = sorted({i.row() for i in self._mp_table.selectedItems()}, reverse=True)
        if not rows:
            return
        for r in rows:
            self._mp_table.removeRow(r)

    def _add_header_row(self, k: str, v: str):
        r = self._hdr_table.rowCount()
        self._hdr_table.insertRow(r)
        self._hdr_table.setItem(r, 0, QTableWidgetItem(k))
        self._hdr_table.setItem(r, 1, QTableWidgetItem(v))

    def _remove_header_row(self):
        rows = sorted({i.row() for i in self._hdr_table.selectedItems()}, reverse=True)
        for r in rows:
            self._hdr_table.removeRow(r)

    def _add_param_row(self, k: str, v: str):
        from PyQt6.QtWidgets import QCheckBox as _QCB
        from PyQt6.QtWidgets import QTableWidgetItem as _TWI
        r = self._params_table.rowCount()
        self._params_table.insertRow(r)
        chk_widget = QWidget()
        chk_lay = QHBoxLayout(chk_widget)
        chk_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chk_lay.setContentsMargins(0, 0, 0, 0)
        chk = QCheckBox()
        chk.setChecked(True)
        chk_lay.addWidget(chk)
        self._params_table.setCellWidget(r, 0, chk_widget)
        self._params_table.setItem(r, 1, QTableWidgetItem(k))
        self._params_table.setItem(r, 2, QTableWidgetItem(v))
        # aggiorna URL quando il valore cambia
        chk.stateChanged.connect(self._sync_params_to_url)
        self._params_table.itemChanged.connect(self._sync_params_to_url)

    def _remove_param_row(self):
        rows = sorted({i.row() for i in self._params_table.selectedItems()}, reverse=True)
        for r in rows:
            self._params_table.removeRow(r)
        self._sync_params_to_url()

    def _sync_params_to_url(self, *_):
        """Aggiorna la URL aggiungendo i query params dalla tabella Params."""
        try:
            base_url = self._url_edit.text().split("?")[0]
            params = []
            for row in range(self._params_table.rowCount()):
                chk_w = self._params_table.cellWidget(row, 0)
                chk = chk_w.findChild(QCheckBox) if chk_w else None
                if chk and not chk.isChecked():
                    continue
                ki = self._params_table.item(row, 1)
                vi = self._params_table.item(row, 2)
                k = ki.text().strip() if ki else ""
                v = vi.text().strip() if vi else ""
                if k:
                    params.append((k, v))
            if params:
                qs = urllib.parse.urlencode(params)
                self._url_edit.blockSignals(True)
                self._url_edit.setText(f"{base_url}?{qs}")
                self._url_edit.blockSignals(False)
            elif "?" in self._url_edit.text():
                self._url_edit.blockSignals(True)
                self._url_edit.setText(base_url)
                self._url_edit.blockSignals(False)
        except Exception:
            pass

    def _import_curl(self):
        """Importa una richiesta da un comando cURL (legge dal clipboard o chiede input)."""
        clip = QApplication.clipboard().text().strip()
        if not clip.startswith("curl"):
            clip, ok = QInputDialog.getMultiLineText(
                self, "Importa cURL",
                "Incolla il comando cURL da importare:",
                clip
            )
            if not ok or not clip.strip().startswith("curl"):
                return

        curl = clip.replace("\\\n", " ").replace("\\\r\n", " ")
        req = HttpRequest()
        # metodo
        m = re.search(r"-X\s+([A-Z]+)", curl)
        if m:
            req.method = m.group(1)
        else:
            req.method = "POST" if re.search(r"--data|--data-raw|-d\s", curl) else "GET"
        # URL (prende il primo token che sembra un URL)
        url_m = re.findall(r"['\"]?(https?://[^\s'\"]+)['\"]?", curl)
        if url_m:
            req.url = url_m[0]
        # headers
        for hm in re.finditer(r"-H\s+['\"]([^'\"]+)['\"]", curl):
            hdr = hm.group(1)
            if ":" in hdr:
                k, v = hdr.split(":", 1)
                k, v = k.strip(), v.strip()
                if k.lower() == "authorization":
                    if v.lower().startswith("bearer "):
                        req.auth_type = "Bearer Token"
                        req.auth_value = v[7:]
                    elif v.lower().startswith("basic "):
                        req.auth_type = "Basic (user:pass)"
                        try:
                            req.auth_value = base64.b64decode(v[6:]).decode()
                        except Exception:
                            req.auth_value = v[6:]
                    else:
                        req.headers[k] = v
                elif k.lower() == "content-type":
                    for bt, ct in _CONTENT_TYPE_MAP.items():
                        if ct in v:
                            req.body_type = bt
                            break
                else:
                    req.headers[k] = v
        # body
        body_m = re.search(r"(?:--data(?:-raw)?|-d)\s+['\"](.+?)['\"](?:\s|$)", curl, re.DOTALL)
        if body_m:
            req.body = body_m.group(1)
            if req.body_type == "Nessuno":
                req.body_type = "JSON" if req.body.strip().startswith("{") else "Testo libero"
            if req.method == "GET":
                req.method = "POST"
        self._apply_request(req)
        QMessageBox.information(self, "cURL importato",
            f"Richiesta importata:\n  {req.method} {req.url}")

    # ── Wizard ────────────────────────────────────────────────────────────────

    def _open_wizard(self):
        req = self._collect_current()
        wiz = _RequestWizard(req, self._envs, parent=self)
        if wiz.exec() == QWizard.DialogCode.Accepted:
            filled = wiz.collect()
            self._apply_request(filled)

    def _new_request(self):
        self._apply_request(HttpRequest())

    # ── Collection (QTreeWidget) ──────────────────────────────────────────────

    def _coll_context_menu(self, pos):
        item = self._coll_tree.itemAt(pos)
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #2d2d2d; color: #d4d4d4; border: 1px solid #555; }"
            "QMenu::item:selected { background: #094771; }"
        )
        if item:
            is_folder = item.data(0, Qt.ItemDataRole.UserRole) == "folder"
            if not is_folder:
                menu.addAction("Apri",    lambda: self._tree_item_activated(item, 0))
                menu.addAction("Aggiorna", lambda: self._update_tree_item(item))
                menu.addSeparator()
                menu.addAction("Rinomina", lambda: self._rename_tree_item(item))
                menu.addAction("Elimina",  lambda: self._delete_tree_item(item))
            else:
                menu.addAction("Rinomina cartella", lambda: self._rename_tree_item(item))
                menu.addAction("Aggiungi richiesta", lambda: self._add_to_folder(item))
                menu.addSeparator()
                menu.addAction("Elimina cartella",  lambda: self._delete_tree_item(item))
        menu.addSeparator()
        menu.addAction("+ Nuova richiesta",  self._add_to_collection)
        menu.addAction("+ Nuova cartella",   self._add_folder)
        menu.exec(self._coll_tree.viewport().mapToGlobal(pos))

    def _tree_item_activated(self, item: QTreeWidgetItem, _col: int):
        """Carica la richiesta associata all'item del tree."""
        if item.data(0, Qt.ItemDataRole.UserRole) == "folder":
            item.setExpanded(not item.isExpanded())
            return
        req_idx = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if req_idx is not None and 0 <= req_idx < len(self._collection):
            self._apply_request(self._collection[req_idx])

    def _add_folder(self):
        name, ok = QInputDialog.getText(self, "Nuova cartella", "Nome cartella:")
        if ok and name.strip():
            folder_item = QTreeWidgetItem(self._coll_tree)
            folder_item.setText(0, f"[dir] {name.strip()}")
            folder_item.setData(0, Qt.ItemDataRole.UserRole, "folder")
            folder_item.setExpanded(True)
            self._coll_tree.addTopLevelItem(folder_item)
            self._save_data()

    def _add_to_collection(self):
        req = self._collect_current()
        name, ok = QInputDialog.getText(
            self, "Salva richiesta", "Nome richiesta:",
            text=self._req_name_edit.text().strip() or req.name
        )
        if not ok or not name.strip():
            return
        req.name = name.strip()
        self._req_name_edit.setText(req.name)
        req_idx = len(self._collection)
        self._collection.append(req)
        # scegli parent: cartella selezionata o root
        sel = self._coll_tree.currentItem()
        if sel and sel.data(0, Qt.ItemDataRole.UserRole) == "folder":
            parent = sel
        elif sel and sel.parent():
            parent = sel.parent()
        else:
            parent = None
        item = QTreeWidgetItem()
        method_color = _METHOD_COLORS.get(req.method, "#888")
        item.setText(0, f"{req.name}")
        item.setForeground(0, QColor("#d4d4d4"))
        item.setData(0, Qt.ItemDataRole.UserRole, "request")
        item.setData(0, Qt.ItemDataRole.UserRole + 1, req_idx)
        item.setToolTip(0, f"{req.method}  {req.url}")
        if parent:
            parent.addChild(item)
            parent.setExpanded(True)
        else:
            self._coll_tree.addTopLevelItem(item)
        self._save_data()

    def _add_to_folder(self, folder_item: QTreeWidgetItem):
        """Salva la richiesta corrente come figlio di una cartella specifica."""
        self._coll_tree.setCurrentItem(folder_item)
        self._add_to_collection()

    def _update_tree_item(self, item: QTreeWidgetItem):
        req_idx = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if req_idx is not None and 0 <= req_idx < len(self._collection):
            req = self._collect_current()
            req.name = self._collection[req_idx].name
            self._collection[req_idx] = req
            item.setToolTip(0, f"{req.method}  {req.url}")
            self._save_data()

    def _rename_tree_item(self, item: QTreeWidgetItem):
        old = item.text(0).lstrip("[dir] ").strip()
        name, ok = QInputDialog.getText(self, "Rinomina", "Nuovo nome:", text=old)
        if ok and name.strip():
            is_folder = item.data(0, Qt.ItemDataRole.UserRole) == "folder"
            if is_folder:
                item.setText(0, f"[dir] {name.strip()}")
            else:
                item.setText(0, name.strip())
                req_idx = item.data(0, Qt.ItemDataRole.UserRole + 1)
                if req_idx is not None and 0 <= req_idx < len(self._collection):
                    self._collection[req_idx].name = name.strip()
            self._save_data()

    def _delete_tree_item(self, item: QTreeWidgetItem):
        is_folder = item.data(0, Qt.ItemDataRole.UserRole) == "folder"
        label = "la cartella e tutte le sue richieste" if is_folder else "questa richiesta"
        if QMessageBox.question(
            self, "Elimina", f"Eliminare {label}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        # rimuovi le request dalla lista se è un item richiesta
        if not is_folder:
            req_idx = item.data(0, Qt.ItemDataRole.UserRole + 1)
            # non rimuovere dalla lista self._collection per semplicità;
            # la ricostruiamo al prossimo _refresh_collection_ui
            pass
        parent = item.parent() or self._coll_tree.invisibleRootItem()
        parent.removeChild(item)
        # ricostruiamo self._collection dall'albero
        self._rebuild_collection_from_tree()
        self._save_data()

    def _rebuild_collection_from_tree(self):
        """Ricostruisce self._collection percorrendo l'albero (elimina buchi)."""
        new_coll: List[HttpRequest] = []
        def _visit(node):
            for i in range(node.childCount()):
                child = node.child(i)
                if child.data(0, Qt.ItemDataRole.UserRole) == "folder":
                    _visit(child)
                else:
                    old_idx = child.data(0, Qt.ItemDataRole.UserRole + 1)
                    if old_idx is not None and 0 <= old_idx < len(self._collection):
                        new_idx = len(new_coll)
                        new_coll.append(self._collection[old_idx])
                        child.setData(0, Qt.ItemDataRole.UserRole + 1, new_idx)
        _visit(self._coll_tree.invisibleRootItem())
        self._collection = new_coll

    def _load_from_history(self, item: QListWidgetItem):
        idx = self._hist_list.row(item)
        if 0 <= idx < len(self._history):
            self._apply_request(self._history[idx])

    def _hist_context_menu(self, pos):
        item = self._hist_list.itemAt(pos)
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #2d2d2d; color: #d4d4d4; border: 1px solid #555; }"
            "QMenu::item:selected { background: #094771; }"
        )
        if item:
            menu.addAction("Apri", lambda: self._load_from_history(item))
            menu.addAction("Salva in collection", lambda: self._save_history_item(item))
        menu.addAction("Svuota cronologia", self._clear_history)
        menu.exec(self._hist_list.viewport().mapToGlobal(pos))

    def _save_history_item(self, item: QListWidgetItem):
        idx = self._hist_list.row(item)
        if 0 <= idx < len(self._history):
            old = self._current_req
            self._apply_request(self._history[idx])
            self._add_to_collection()
            self._apply_request(old)

    def _clear_history(self):
        self._history.clear()
        self._hist_list.clear()
        self._save_data()

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
        """Ricostruisce il QTreeWidget della collection dalla lista self._collection."""
        self._coll_tree.clear()
        for idx, r in enumerate(self._collection):
            item = QTreeWidgetItem(self._coll_tree)
            item.setText(0, r.name)
            item.setData(0, Qt.ItemDataRole.UserRole, "request")
            item.setData(0, Qt.ItemDataRole.UserRole + 1, idx)
            item.setToolTip(0, f"{r.method}  {r.url}")
            item.setForeground(0, QColor("#d4d4d4"))

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
        r.name       = self._req_name_edit.text().strip() or "Nuova richiesta"
        r.method     = self._method_cb.currentText()
        r.url        = self._url_edit.text().strip()
        r.env_profile = self._env_cb.currentText()
        r.auth_type  = self._auth_type_cb.currentText()
        r.auth_value = self._auth_val_edit.text().strip()
        r.auth_header = self._auth_hdr_edit.text().strip() or "X-Api-Key"
        r.body_type  = self._body_type_cb.currentText()
        r.body       = self._body_edit.toPlainText().strip()
        r.timeout    = self._timeout_spin.value()
        r.verify_ssl = self._ssl_chk.isChecked()
        r.allow_redirects = self._redirect_chk.isChecked()
        r.pre_script = self._pre_req_edit.toPlainText().strip()
        r.post_tests = self._tests_edit.toPlainText().strip()
        # OAuth2
        if r.auth_type == "OAuth 2.0":
            r.oauth2_token_url = self._oauth2_token_url.text().strip()
            r.oauth2_client_id = self._oauth2_client_id.text().strip()
            r.oauth2_client_secret = self._oauth2_client_secret.text().strip()
            r.oauth2_scope = self._oauth2_scope.text().strip()
        # Multipart
        r.multipart_fields = []
        for row in range(self._mp_table.rowCount()):
            n = self._mp_table.item(row, 0)
            p = self._mp_table.item(row, 1)
            if n and p:
                r.multipart_fields.append({"name": n.text().strip(), "path": p.text().strip()})
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
        self._req_name_edit.setText(r.name if r.name != "Nuova richiesta" else "")
        self._method_cb.setCurrentText(r.method)
        self._url_edit.setText(r.url)
        idx = next((i for i, e in enumerate(self._envs) if e.name == r.env_profile), 0)
        self._env_cb.setCurrentIndex(idx)
        self._auth_type_cb.setCurrentText(r.auth_type)
        self._auth_val_edit.setText(r.auth_value)
        self._auth_hdr_edit.setText(r.auth_header)
        self._body_type_cb.setCurrentText(r.body_type)
        self._body_edit.setPlainText(r.body)
        self._timeout_spin.setValue(r.timeout)
        self._ssl_chk.setChecked(r.verify_ssl)
        self._redirect_chk.setChecked(r.allow_redirects)
        self._pre_req_edit.setPlainText(r.pre_script)
        self._tests_edit.setPlainText(r.post_tests)
        # OAuth2
        self._oauth2_token_url.setText(r.oauth2_token_url)
        self._oauth2_client_id.setText(r.oauth2_client_id)
        self._oauth2_client_secret.setText(r.oauth2_client_secret)
        self._oauth2_scope.setText(r.oauth2_scope)
        # Multipart
        self._mp_table.setRowCount(0)
        for f in r.multipart_fields:
            row = self._mp_table.rowCount()
            self._mp_table.insertRow(row)
            self._mp_table.setItem(row, 0, QTableWidgetItem(f.get("name", "")))
            self._mp_table.setItem(row, 1, QTableWidgetItem(f.get("path", "")))
        self._hdr_table.setRowCount(0)
        for k, v in r.headers.items():
            self._add_header_row(k, v)
        # reset risposta
        self._resp_body.clear()
        self._resp_raw.clear()
        self._resp_hdr_table.setRowCount(0)
        self._resp_cookies_table.setRowCount(0)
        self._status_lbl.setText("—")

    # ── Invio richiesta ───────────────────────────────────────────────────────

    def _send_request(self):
        req = self._collect_current()
        if not req.url:
            QMessageBox.warning(self, "Attenzione", "Inserisci un URL prima di inviare.")
            return

        env_name = self._env_cb.currentText()
        env = next((e for e in self._envs if e.name == env_name), EnvProfile())

        # Esegui script pre-request
        pre_script = req.pre_script
        if pre_script:
            try:
                pm = {"variables": {}, "last_response_body": None}
                if self._last_response_body:
                    try:
                        pm["last_response_body"] = json.loads(self._last_response_body)
                    except Exception:
                        pm["last_response_body"] = self._last_response_body
                exec(pre_script, {"pm": pm, "json": json, "re": re})
                # Merge extracted variables into env for this request
                for k, v in pm.get("variables", {}).items():
                    env.variables[k] = str(v)
            except Exception as e:
                QMessageBox.warning(self, "Script pre-request",
                                    f"Errore nello script pre-request:\n{e}")
                return

        self._btn_send.setEnabled(False)
        self._btn_abort.setEnabled(True)
        self._progress.setVisible(True)
        self._status_lbl.setText("\u23f3 In attesa...")
        self._resp_body.clear()

        # aggiungi a cronologia
        self._history.insert(0, req)
        if len(self._history) > _HISTORY_MAX:
            self._history = self._history[:_HISTORY_MAX]
        self._hist_list.insertItem(0, f"{req.method} {req.url}")
        if self._hist_list.count() > _HISTORY_MAX:
            self._hist_list.takeItem(_HISTORY_MAX)

        worker = _RequestWorker(req, env)
        worker.finished.connect(self._on_response)
        worker.error.connect(self._on_error)

        def _run():
            worker.run()

        self._worker = worker
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def _abort_request(self):
        if self._worker:
            self._worker.cancel()
            self._btn_send.setEnabled(True)
            self._btn_abort.setEnabled(False)
            self._progress.setVisible(False)
            self._status_lbl.setText("\u26a0 Richiesta annullata")

    def _show_code_snippets(self):
        req = self._collect_current()
        env_name = self._env_cb.currentText()
        env = next((e for e in self._envs if e.name == env_name), EnvProfile())
        url = env.resolve(req.url)
        c = _CONTENT_TYPE_MAP.get(req.body_type, "")

        curl = f"curl -X {req.method} '{url}'"
        if req.auth_type == "Bearer Token":
            curl += f" \\\n  -H 'Authorization: Bearer {req.auth_value}'"
        elif req.auth_type == "Basic (user:pass)":
            curl += f" \\\n  -H 'Authorization: Basic {base64.b64encode(req.auth_value.encode()).decode()}'"
        for k, v in req.headers.items():
            curl += f" \\\n  -H '{k}: {v}'"
        if c and req.body:
            curl += f" \\\n  -H 'Content-Type: {c}'"
            body_escaped = req.body.replace("'", "'\"'\"'")
            curl += f" \\\n  -d '{body_escaped}'"

        python = f"import requests\n\nresp = requests.{req.method.lower()}('{url}'"
        if req.body:
            python += f",\n    json={req.body}" if req.body_type == "JSON" else f",\n    data='{req.body}'"
        if req.headers:
            python += f",\n    headers={json.dumps(req.headers)}"
        python += "\n)\nprint(resp.status_code, resp.text[:500])"

        js = f"fetch('{url}', {{\n  method: '{req.method}'"
        if req.body_type == "JSON":
            js += f",\n  headers: {{'Content-Type': 'application/json'}},\n  body: JSON.stringify({req.body})"
        js += "\n}).then(r => r.json()).then(console.log)"

        msg = f"<b>cURL:</b><br><pre>{curl}</pre><br><b>Python:</b><br><pre>{python}</pre><br><b>JavaScript:</b><br><pre>{js}</pre>"
        box = QMessageBox(self)
        box.setWindowTitle("Code snippets")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(msg)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def _on_response(self, result: dict):
        self._btn_send.setEnabled(True)
        self._btn_abort.setEnabled(False)
        self._progress.setVisible(False)

        status  = result["status"]
        elapsed = result["elapsed"]
        body    = result["body"]
        headers = result["headers"]
        ct      = result.get("content_type", "")

        self._last_content_type = ct
        self._last_response_body = body

        color = "#4ec9b0" if status < 300 else ("#dcdcaa" if status < 400 else "#f44747")
        size_kb = len(body.encode("utf-8", errors="replace")) / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb >= 1 else f"{len(body.encode())} B"
        status_text = (
            f'<span style="background:{color};color:#111;font-weight:bold;'
            f'  border-radius:3px;padding:1px 6px;">HTTP {status}</span>'
            f'&nbsp;&nbsp;<span style="color:#aaa;">{elapsed*1000:.0f} ms</span>'
            f'&nbsp;&nbsp;<span style="color:#888;">{size_str}</span>'
        )
        self._status_lbl.setText(status_text)

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

        # raw view (status line + headers + blank + body)
        raw_lines = [f"HTTP/1.1 {status}"]
        for k, v in headers.items():
            raw_lines.append(f"{k}: {v}")
        raw_lines.append("")
        raw_lines.append(body)
        self._resp_raw.setPlainText("\n".join(raw_lines))

        # headers risposta
        self._resp_hdr_table.setRowCount(0)
        for k, v in headers.items():
            r = self._resp_hdr_table.rowCount()
            self._resp_hdr_table.insertRow(r)
            self._resp_hdr_table.setItem(r, 0, QTableWidgetItem(k))
            self._resp_hdr_table.setItem(r, 1, QTableWidgetItem(str(v)))

        # cookies: parse Set-Cookie headers
        self._resp_cookies_table.setRowCount(0)
        for k, v in headers.items():
            if k.lower() == "set-cookie":
                self._parse_set_cookie(str(v))

        self._save_data()

        # Esegui test post-response
        post_tests = self._current_req.post_tests if self._current_req else ""
        if not post_tests:
            post_tests = self._tests_edit.toPlainText().strip()
        if post_tests:
            self._run_tests(post_tests, result)

    def _run_tests(self, script: str, result: dict):
        html = '<div style="font-family: monospace; font-size: 11px; line-height: 1.6;">'
        passed = 0
        failed = 0
        results_list = []

        def test_fn(name, condition):
            nonlocal passed, failed
            ok = bool(condition)
            if ok:
                passed += 1
                status = f'<span style="color:#4caf50;">\u2713 PASS</span>'
            else:
                failed += 1
                status = f'<span style="color:#f44747;">\u2717 FAIL</span>'
            results_list.append(f"{status}  {name}")

        body = result["body"]
        try:
            response_json = json.loads(body) if body else {}
        except Exception:
            response_json = None

        pm = {
            "response": {
                "status": result["status"],
                "headers": result["headers"],
                "text": body,
                "json": response_json,
                "elapsed": result["elapsed"],
            },
            "test": test_fn,
        }

        try:
            exec(script, {"pm": pm, "json": json, "re": re})
        except Exception as e:
            failed += 1
            results_list.append(
                f'<span style="color:#f44747;">\u2717 ERROR</span>  {str(e)[:200]}'
            )

        total = passed + failed
        if total > 0:
            bar_color = "#4caf50" if failed == 0 else "#f44747" if passed == 0 else "#ffcc00"
            html += (
                f'<div style="margin-bottom:4px;">'
                f'<span style="color:{bar_color};font-weight:bold;">'
                f'{passed}/{total} passed</span>'
                f'</div>'
            )
        for line in results_list:
            html += f'<div style="margin:1px 0;">{line}</div>'
        html += "</div>"
        self._tests_results.setHtml(html)

    def _parse_set_cookie(self, cookie_str: str):
        """Parsa una riga Set-Cookie e aggiunge una riga alla tabella cookies."""
        parts = [p.strip() for p in cookie_str.split(";")]
        name = val = domain = path = ""
        if parts and "=" in parts[0]:
            name, val = parts[0].split("=", 1)
        for part in parts[1:]:
            pl = part.lower()
            if pl.startswith("domain="):
                domain = part.split("=", 1)[1]
            elif pl.startswith("path="):
                path = part.split("=", 1)[1]
        r = self._resp_cookies_table.rowCount()
        self._resp_cookies_table.insertRow(r)
        self._resp_cookies_table.setItem(r, 0, QTableWidgetItem(name))
        self._resp_cookies_table.setItem(r, 1, QTableWidgetItem(val))
        self._resp_cookies_table.setItem(r, 2, QTableWidgetItem(domain))
        self._resp_cookies_table.setItem(r, 3, QTableWidgetItem(path))

    def _on_error(self, msg: str):
        self._btn_send.setEnabled(True)
        self._btn_abort.setEnabled(False)
        self._progress.setVisible(False)
        self._status_lbl.setText(
            f'<span style="background:#f44747;color:#fff;font-weight:bold;'
            f'  border-radius:3px;padding:1px 6px;">❌ Errore</span>'
            f'&nbsp;&nbsp;<span style="color:#f88;">{msg}</span>'
        )
        self._last_response_body = ""
        self._resp_body.setPlainText(f"Errore di rete:\n{msg}")
        self._resp_raw.setPlainText(f"Errore:\n{msg}")

    # ── Copia / inserimento / salvataggio ────────────────────────────────────

    def _prettify_body(self):
        """Formatta il body JSON nell'editor richiesta."""
        text = self._body_edit.toPlainText().strip()
        if not text:
            return
        try:
            pretty = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
            self._body_edit.setPlainText(pretty)
        except Exception:
            try:
                pretty = xml.dom.minidom.parseString(text.encode()).toprettyxml(indent="  ")
                self._body_edit.setPlainText(pretty)
            except Exception:
                QMessageBox.information(self, "Formatta", "Non è possibile formattare il testo (non è JSON/XML valido).")

    def _toggle_resp_view(self, mode: str):
        """Cambia la visualizzazione della risposta: Pretty o Raw."""
        # Viene gestita automaticamente dalla tab Raw, qui aggiorniamo solo la tab Body
        if mode == "Raw":
            self._resp_body.setFont(QFont("Monospace", 9))
        else:
            self._resp_body.setFont(QFont("Monospace", 10))

    def _save_response(self):
        """Salva la risposta corrente su file."""
        body = self._resp_body.toPlainText()
        if not body:
            QMessageBox.information(self, "REST Client", "Nessuna risposta da salvare.")
            return
        ct = getattr(self, "_last_content_type", "")
        if "json" in ct:
            ext = "JSON (*.json);;Testo (*.txt);;Tutti (*)"
            default = "risposta.json"
        elif "xml" in ct:
            ext = "XML (*.xml);;Testo (*.txt);;Tutti (*)"
            default = "risposta.xml"
        elif "html" in ct:
            ext = "HTML (*.html);;Testo (*.txt);;Tutti (*)"
            default = "risposta.html"
        else:
            ext = "Testo (*.txt);;Tutti (*)"
            default = "risposta.txt"
        path, _ = QFileDialog.getSaveFileName(self, "Salva risposta", default, ext)
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(body)
                QMessageBox.information(self, "Salvato", f"Risposta salvata in:\n{path}")
            except Exception as exc:
                QMessageBox.critical(self, "Errore", f"Impossibile salvare:\n{exc}")

    def _copy_response(self):
        QApplication.clipboard().setText(self._resp_body.toPlainText())

    def _open_response_in_editor(self):
        """Apre il body della risposta in un nuovo tab dell'editor con la sintassi corretta."""
        body = self._resp_body.toPlainText()
        if not body:
            QMessageBox.information(self, "REST Client", "Nessuna risposta da aprire.")
            return
        try:
            mw = self._mw
            if mw is None:
                mw = self.parent()
                while mw and not hasattr(mw, "_tab_manager"):
                    mw = mw.parent()
            if mw and hasattr(mw, "_tab_manager"):
                tab = mw._tab_manager.new_tab(path=None)
                from editor.editor_widget import LineEnding
                tab.load_content(body, "UTF-8", LineEnding.LF)
                # imposta linguaggio in base al content-type
                ct = getattr(self, "_last_content_type", "")
                if hasattr(tab, "set_language"):
                    if "json" in ct:
                        tab.set_language("json")
                    elif "xml" in ct:
                        tab.set_language("xml")
                    elif "html" in ct:
                        tab.set_language("html")
            else:
                QMessageBox.warning(self, "REST Client",
                    "Impossibile aprire un nuovo tab: editor non trovato.")
        except Exception as exc:
            QMessageBox.warning(self, "REST Client", f"Errore apertura tab:\n{exc}")

    def _insert_response(self):
        """Inserisce il body della risposta nell'editor attivo al cursore."""
        try:
            mw = self._mw
            if mw is None:
                mw = self.parent()
                while mw and not hasattr(mw, "_tab_manager"):
                    mw = mw.parent()
            if mw and hasattr(mw, "_tab_manager"):
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

    # ── Collection Runner ──────────────────────────────────────────────────────

    def _open_runner(self):
        dlg = _CollectionRunnerDialog(self._collection, self._envs, self._mw, self)
        dlg.exec()

# ─── Collection Runner ─────────────────────────────────────────────────────────

class _CollectionRunnerDialog(QDialog):
    """Esegue tutte le richieste della collection in sequenza e mostra risultati."""

    def __init__(self, collection, envs, mw, parent=None):
        super().__init__(parent)
        self._collection = collection
        self._envs = envs
        self._mw = mw
        self._abort = False
        self.setWindowTitle("Collection Runner")
        self.resize(700, 500)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)

        # Selezione ambiente
        env_row = QHBoxLayout()
        env_row.addWidget(QLabel("Profilo ambiente:"))
        self._env_cb = QComboBox()
        for e in self._envs:
            self._env_cb.addItem(e.name)
        env_row.addWidget(self._env_cb)
        env_row.addStretch()

        self._delay_spin = QSpinBox()
        self._delay_spin.setRange(0, 5000)
        self._delay_spin.setValue(200)
        self._delay_spin.setSuffix(" ms delay")
        self._delay_spin.setToolTip("Ritardo tra una richiesta e l'altra")
        env_row.addWidget(QLabel("Delay:"))
        env_row.addWidget(self._delay_spin)
        lay.addLayout(env_row)

        # Lista richieste
        self._list = QTreeWidget()
        self._list.setHeaderLabels(["", "Richiesta", "Metodo", "URL"])
        self._list.setColumnWidth(0, 28)
        self._list.setColumnWidth(1, 150)
        self._list.setColumnWidth(2, 70)
        self._list.setAlternatingRowColors(True)
        self._list.setStyleSheet("QTreeWidget { background:#1e1e1e; color:#d4d4d4; border:1px solid #3c3c3c; }")
        for req in self._collection:
            item = QTreeWidgetItem(self._list)
            item.setCheckState(0, Qt.CheckState.Checked)
            item.setText(1, req.name)
            item.setText(2, req.method)
            item.setText(3, req.url)
            item.setData(0, Qt.ItemDataRole.UserRole, req)
        lay.addWidget(self._list)

        # Pulsanti
        btn_row = QHBoxLayout()
        self._btn_run = QPushButton("\u25b6 Esegui")
        self._btn_run.setStyleSheet("font-weight:bold; padding:6px 16px; background:#238636; color:white; border-radius:4px;")
        self._btn_run.clicked.connect(self._run)
        btn_row.addWidget(self._btn_run)

        self._btn_stop = QPushButton("\u25a0 Stop")
        self._btn_stop.setEnabled(False)
        self._btn_stop.setStyleSheet("color:#f44747; padding:6px 16px;")
        self._btn_stop.clicked.connect(lambda: setattr(self, '_abort', True))
        btn_row.addWidget(self._btn_stop)

        btn_row.addStretch()
        lay.addLayout(btn_row)

        # Risultati
        self._results = QTextEdit()
        self._results.setReadOnly(True)
        self._results.setFont(QFont("Monospace", 10))
        self._results.setStyleSheet("background:#1e1e1e; color:#d4d4d4; border:1px solid #3c3c3c;")
        lay.addWidget(self._results)

    def _run(self):
        self._btn_run.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._results.clear()
        self._abort = False

        env_name = self._env_cb.currentText()
        env_base = next((e for e in self._envs if e.name == env_name), EnvProfile())
        delay = self._delay_spin.value() / 1000.0

        total = 0
        passed = 0
        failed = 0
        self._results.append(f"<b style='color:#9cdcfe;'>Collection Runner</b> — {self._list.topLevelItemCount()} requests\n")

        for i in range(self._list.topLevelItemCount()):
            if self._abort:
                self._results.append("<span style='color:#ffcc00;'>\u26a0 Interrotto</span>")
                break

            item = self._list.topLevelItem(i)
            if item.checkState(0) != Qt.CheckState.Checked:
                continue

            req = item.data(0, Qt.ItemDataRole.UserRole)
            env = EnvProfile(env_base.name, dict(env_base.variables))
            total += 1

            self._results.append(f"\n<b>{req.method}</b> {req.url} ...")
            item.setText(0, "\u23f3")

            worker = _RequestWorker(req, env)
            result_holder = [None]
            error_holder = [None]

            def _on_finish(rdict):
                result_holder[0] = rdict

            def _on_error(msg):
                error_holder[0] = msg

            worker.finished.connect(_on_finish)
            worker.error.connect(_on_error)

            t = threading.Thread(target=worker.run, daemon=True)
            t.start()
            t.join(timeout=60)

            if worker.isRunning():
                worker.cancel()
                t.join(timeout=2)

            if error_holder[0]:
                failed += 1
                item.setText(0, "\u2717")
                item.setForeground(0, QColor("#f44747"))
                self._results.append(f"  <span style='color:#f44747;'>\u2717 ERROR: {error_holder[0][:150]}</span>")
            elif result_holder[0]:
                rd = result_holder[0]
                status = rd["status"]
                elapsed = rd["elapsed"]
                if 200 <= status < 300:
                    passed += 1
                    item.setText(0, "\u2713")
                    item.setForeground(0, QColor("#4caf50"))
                    self._results.append(f"  <span style='color:#4caf50;'>\u2713 {status}</span>  {elapsed*1000:.0f}ms")
                else:
                    failed += 1
                    item.setText(0, "\u2717")
                    item.setForeground(0, QColor("#f44747"))
                    self._results.append(f"  <span style='color:#f44747;'>\u2717 {status}</span>  {elapsed*1000:.0f}ms")
            else:
                failed += 1
                item.setText(0, "\u2717")

            if delay > 0 and i < self._list.topLevelItemCount() - 1:
                time.sleep(delay)

        # Summary
        color = "#4caf50" if failed == 0 else "#f44747" if passed == 0 else "#ffcc00"
        self._results.append(
            f"\n<hr><b style='color:{color};'>Results: {passed}/{total} passed"
            + (f", {failed} failed" if failed else "")
            + "</b>"
        )

        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)


# ─── Plugin entry point ───────────────────────────────────────────────────────

class RestClientPlugin(BasePlugin):
    NAME        = "REST Client"
    VERSION     = "1.0"
    DESCRIPTION = "Client HTTP/REST integrato con wizard, collection e variabili ambiente"
    AUTHOR      = "NotePadPQ"

    def on_load(self, main_window: "MainWindow") -> None:
        super().on_load(main_window)

        self._panel = _RestPanel(main_window=main_window)
        self._dock  = QDockWidget("REST Client", main_window)
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

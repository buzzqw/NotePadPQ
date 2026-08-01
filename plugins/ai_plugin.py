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
  • LlamaCPP locale — llama-server (OpenAI-compatible, porta 8080)

BYOK — chiave API per provider salvata in QSettings.
Shortcut: Ctrl+Alt+A per aprire/chiudere il pannello.
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.request
import urllib.error
import urllib.parse
import secrets
import hashlib
import base64
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt, QTimer, QSize
from PyQt6.QtGui import QFont, QKeySequence, QColor, QTextCursor, QTextCharFormat
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QLineEdit, QTextEdit, QPlainTextEdit, QPushButton,
    QSplitter, QDialog, QFormLayout, QDialogButtonBox,
    QDockWidget, QMessageBox, QCheckBox, QSpinBox,
    QGroupBox, QScrollArea, QFrame, QFileDialog,
)

from plugins.base_plugin import BasePlugin
from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


def _make_ssl_ctx() -> ssl.SSLContext:
    """SSL context configurabile: rispetta l'impostazione ai/verify_ssl."""
    try:
        from config.settings import Settings
        verify = Settings.instance().get("ai/verify_ssl", True)
    except Exception:
        verify = True
    if verify:
        return ssl.create_default_context()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ─── Configurazione provider ──────────────────────────────────────────────────

# ── JetBrains AI — disabilitato, codice conservato ────────────────────────────
#
# Perché è disabilitato:
#   L'API JetBrains AI (https://api.jetbrains.ai, versioni v8/v9) è un servizio
#   privato non documentato pubblicamente. L'analisi dell'estensione VSCode ufficiale
#   (jetbrains.jetbrains-ai-assistant) ha rivelato che:
#     • non usa OAuth2 standard: l'autenticazione è gestita da un server Java locale
#       (server-0.0.1.jar) che parla con il backend Grazie tramite un protocollo
#       proprietario — non accessibile dall'esterno;
#     • il client_id "notepadpq-ai-assistant" nell'URL OAuth restituisce HTTP 400
#       perché nessuna app esterna è registrata con JetBrains senza partnership ufficiale;
#     • il formato della request/response è proprietario (non OpenAI-compatibile).
#
# Cosa è implementato e pronto:
#   • Flusso OAuth PKCE completo con server di callback locale (_JetBrainsOAuth)
#   • Chiamata API con refresh automatico del token (_AIWorker._call_jetbrains)
#   • UI nel dialog impostazioni con pulsante OAuth e campo token manuale
#
# Come riabilitare in futuro:
#   Se JetBrains pubblica API ufficiali per terze parti, spostare la voce
#   "JetBrains AI" da _JETBRAINS_PROVIDER_RESERVED in PROVIDERS qui sotto,
#   aggiornare client_id e l'endpoint in _call_jetbrains(), e testare il flusso.
_JETBRAINS_PROVIDER_RESERVED: dict = {
    "JetBrains AI": {
        "id":      "jetbrains",
        "models":  ["claude-3-5-sonnet", "gpt-4o", "gpt-4o-mini", "gemini-1.5-pro"],
        "default": "claude-3-5-sonnet",
        "key_url": "",
        "note":    "Accedi con il tuo account JetBrains per verificare la licenza AI",
        "thinking_models": [],
        "auth_type": "oauth",
        "oauth_config": {
            "auth_url":    "https://account.jetbrains.com/oauth2/auth",
            "token_url":   "https://account.jetbrains.com/oauth2/token",
            "client_id":   "notepadpq-ai-assistant",
            "scope":       "profile ai_assistant",
            "redirect_uri":"http://localhost:8080/oauth/callback",
        },
    }
}

PROVIDERS: dict[str, dict] = {
    "Anthropic (Claude)": {
        "id":      "anthropic",
        "models": [
            "claude-opus-4-8",
            "claude-sonnet-5",
            "claude-haiku-4-5-20251001",
            "claude-fable-5",
        ],
        "default": "claude-sonnet-5",
        "key_url": "https://console.anthropic.com/settings/keys",
        "note":    "API key da console.anthropic.com (separata dall'abbonamento Claude Pro)",
        "thinking_models": ["claude-opus-4-8", "claude-sonnet-5"],
    },
    "OpenAI (ChatGPT)": {
        "id":      "openai",
        "models":  ["gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4o", "o3", "o3-mini"],
        "default": "gpt-5",
        "key_url": "https://platform.openai.com/api-keys",
        "note":    "",
        "thinking_models": [],
    },
    "Google Gemini": {
        "id":      "gemini",
        "models":  ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"],
        "default": "gemini-2.5-flash",
        "key_url": "https://aistudio.google.com/app/apikey",
        "note":    "",
        "thinking_models": [],
    },
    "DeepSeek": {
        "id":      "deepseek",
        "models":  ["deepseek-v4-pro", "deepseek-v4-flash"],
        "default": "deepseek-v4-pro",
        "key_url": "https://platform.deepseek.com/api_keys",
        "note":    "deepseek-v4-pro espone la catena di ragionamento (thinking).",
        "thinking_models": ["deepseek-v4-pro"],
    },
    "Ollama (locale)": {
        "id":      "ollama",
        "models":  ["llama3.2", "llama3.1", "mistral", "codestral", "qwen2.5-coder", "deepseek-coder-v2"],
        "default": "llama3.2",
        "key_url": "",
        "note":    "Nessuna chiave necessaria. Imposta l'URL del server Ollama.",
        "thinking_models": [],
    },
    "LlamaCPP (locale)": {
        "id":      "llamacpp",
        "models":  ["llama-3.2", "llama-3.1", "mistral-7b", "codestral"],
        "default": "llama-3.2",
        "key_url": "",
        "note":    "Nessuna chiave necessaria. Imposta l'URL del server llama-server (default: http://localhost:8080).",
        "thinking_models": [],
    },
}

# Default max token risposta (regolabile senza tetto pratico nelle impostazioni)
_DEFAULT_MAX_TOKENS = 65000

# Limite di caratteri per singolo file allegato via "Allega file"
_ATTACH_MAX_CHARS = 200_000

# Estensioni immagine supportate per "Allega immagine" (vision) -> media type
_IMAGE_MEDIA_TYPES: dict[str, str] = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".webp": "image/webp",
}
# Limite prudente per immagine (Anthropic/Gemini accettano file più grandi, ma
# restano comunque soggetti a limiti sulla dimensione totale della richiesta)
_IMAGE_MAX_BYTES = 5_000_000

# Provider che supportano l'invio di immagini (vision) nei messaggi
_VISION_PROVIDERS = ("anthropic", "gemini")

# Prezzo stimato per 1M token (input/output) in USD
MODEL_COST: dict[str, tuple[float, float]] = {
    "claude-opus-4-8":             (15.0, 75.0),
    "claude-sonnet-5":             (3.0,  15.0),
    "claude-haiku-4-5-20251001":   (0.8,  4.0),
    "gpt-4o":                      (5.0,  15.0),
    "gpt-4o-mini":                 (0.15, 0.6),
    "deepseek-chat":               (0.27, 1.10),
    "deepseek-reasoner":           (0.55, 2.19),
}

CONTEXT_ACTIONS = [
    ("action.ai_explain",            "Spiega questo codice in modo chiaro e conciso, riga per riga se necessario."),
    ("action.ai_refactor",           "Refactorizza questo codice migliorando leggibilità, struttura e manutenibilità senza cambiare il comportamento esterno."),
    ("action.ai_docstring",          "Scrivi una docstring completa e professionale per questa funzione/classe, con parametri, return e esempi."),
    ("action.ai_fix_bug",            "Analizza questo codice, identifica i bug e proponi la versione corretta con spiegazione."),
    ("action.ai_optimize",           "Ottimizza questo codice per performance e memoria, spiegando le modifiche."),
    ("action.ai_unit_tests",         "Scrivi test unitari esaustivi per questo codice usando pytest."),
    ("action.ai_review",             "Fai una code review professionale: sicurezza, performance, leggibilità, edge case."),
    ("action.ai_translate_comments", "Traduci tutti i commenti e le stringhe UI di questo codice in italiano."),
]


# ─── OAuth JetBrains ───────────────────────────────────────────────────────────

class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handler per il callback OAuth di JetBrains"""
    
    def do_GET(self):
        """Gestisce la richiesta GET del callback OAuth"""
        parsed_url = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        
        if 'code' in query_params:
            # Successo: salva il codice di autorizzazione
            self.server.auth_code = query_params['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'''
                <html><body>
                <h2>Autenticazione JetBrains completata!</h2>
                <p>Puoi chiudere questa finestra e tornare a NotePadPQ.</p>
                <script>window.close();</script>
                </body></html>
            ''')
        elif 'error' in query_params:
            # Errore: salva l'errore
            self.server.auth_error = query_params.get('error_description', ['Errore sconosciuto'])[0]
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(f'''
                <html><body>
                <h2>Errore di autenticazione</h2>
                <p>{self.server.auth_error}</p>
                <p>Puoi chiudere questa finestra e riprovare.</p>
                </body></html>
            '''.encode())
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<html><body><h2>Richiesta non valida</h2></body></html>')
    
    def log_message(self, format, *args):
        """Disabilita i log del server HTTP"""
        pass


class _JetBrainsOAuth(QObject):
    """Gestisce l'autenticazione OAuth con JetBrains"""
    
    auth_completed = pyqtSignal(str)  # access_token
    auth_failed = pyqtSignal(str)     # error_message
    
    def __init__(self):
        super().__init__()
        self._server = None
        self._server_thread = None
        
    def start_auth_flow(self, oauth_config: dict) -> None:
        """Avvia il flusso di autenticazione OAuth"""
        try:
            # Genera state e code_verifier per PKCE
            state = secrets.token_urlsafe(32)
            code_verifier = secrets.token_urlsafe(32)
            code_challenge = base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode()).digest()
            ).decode().rstrip('=')
            
            # Salva i parametri per il token exchange
            self._oauth_config = oauth_config
            self._state = state
            self._code_verifier = code_verifier
            
            # Avvia il server locale per il callback
            self._start_callback_server()
            
            # Costruisce l'URL di autorizzazione
            auth_params = {
                'response_type': 'code',
                'client_id': oauth_config['client_id'],
                'redirect_uri': oauth_config['redirect_uri'],
                'scope': oauth_config['scope'],
                'state': state,
                'code_challenge': code_challenge,
                'code_challenge_method': 'S256'
            }
            
            auth_url = f"{oauth_config['auth_url']}?{urllib.parse.urlencode(auth_params)}"
            
            # Apre il browser per l'autenticazione
            import webbrowser
            webbrowser.open(auth_url)
            
        except Exception as e:
            self.auth_failed.emit(f"Errore nell'avvio dell'autenticazione: {str(e)}")
    
    def _start_callback_server(self) -> None:
        """Avvia il server HTTP locale per ricevere il callback"""
        try:
            # Estrae porta dall'URL di redirect
            redirect_url = urllib.parse.urlparse(self._oauth_config['redirect_uri'])
            port = redirect_url.port or 8080
            
            # Crea e avvia il server
            self._server = HTTPServer(('localhost', port), _OAuthCallbackHandler)
            self._server.auth_code = None
            self._server.auth_error = None
            
            # Avvia il server in un thread separato
            self._server_thread = threading.Thread(target=self._run_server, daemon=True)
            self._server_thread.start()
            
            # Avvia il timer per controllare il callback
            self._callback_timer = QTimer()
            self._callback_timer.timeout.connect(self._check_callback)
            self._callback_timer.start(1000)  # Controlla ogni secondo
            
        except Exception as e:
            self.auth_failed.emit(f"Errore nell'avvio del server callback: {str(e)}")
    
    def _run_server(self) -> None:
        """Esegue il server HTTP in un thread separato"""
        try:
            self._server.handle_request()  # Gestisce una sola richiesta
        except Exception as e:
            print(f"Errore nel server callback: {e}")
    
    def _check_callback(self) -> None:
        """Controlla se il callback è stato ricevuto"""
        if not self._server:
            return
            
        if hasattr(self._server, 'auth_code') and self._server.auth_code:
            # Callback ricevuto con successo
            self._callback_timer.stop()
            auth_code = self._server.auth_code
            self._cleanup_server()
            self._exchange_code_for_token(auth_code)
            
        elif hasattr(self._server, 'auth_error') and self._server.auth_error:
            # Callback ricevuto con errore
            self._callback_timer.stop()
            error = self._server.auth_error
            self._cleanup_server()
            self.auth_failed.emit(f"Errore di autorizzazione: {error}")
    
    def _cleanup_server(self) -> None:
        """Pulisce il server HTTP"""
        if self._server:
            try:
                self._server.server_close()
            except Exception:
                pass
            self._server = None
        
        if hasattr(self, '_callback_timer'):
            self._callback_timer.stop()
    
    def _exchange_code_for_token(self, auth_code: str) -> None:
        """Scambia il codice di autorizzazione con un access token"""
        try:
            token_data = {
                'grant_type': 'authorization_code',
                'client_id': self._oauth_config['client_id'],
                'code': auth_code,
                'redirect_uri': self._oauth_config['redirect_uri'],
                'code_verifier': self._code_verifier
            }
            
            # Effettua la richiesta per il token
            data = urllib.parse.urlencode(token_data).encode()
            req = urllib.request.Request(
                self._oauth_config['token_url'],
                data=data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            with urllib.request.urlopen(req, timeout=30, context=_make_ssl_ctx()) as response:
                token_response = json.loads(response.read().decode())
            
            if 'access_token' in token_response:
                access_token   = token_response['access_token']
                refresh_token  = token_response.get('refresh_token', '')
                expires_in     = int(token_response.get('expires_in', 3600))
                if refresh_token:
                    from config.settings import Settings
                    s = Settings.instance()
                    s.set("ai/jetbrains_refresh_token", refresh_token)
                    s.set("ai/jetbrains_token_expires", int(time.time()) + expires_in - 60)
                self._verify_ai_license(access_token)
            else:
                self.auth_failed.emit("Token di accesso non ricevuto")
                
        except urllib.error.HTTPError as e:
            try:
                error_body = e.read().decode()
                error_data = json.loads(error_body)
                error_msg = error_data.get('error_description', f'HTTP {e.code}')
            except Exception:
                error_msg = f'HTTP {e.code}'
            self.auth_failed.emit(f"Errore nel token exchange: {error_msg}")
        except Exception as e:
            self.auth_failed.emit(f"Errore nel token exchange: {str(e)}")
    
    def _verify_ai_license(self, access_token: str) -> None:
        """Verifica la licenza AI; se l'endpoint non è raggiungibile assume licenza valida."""
        try:
            license_url = "https://account.jetbrains.com/api/v1/licenses/ai"
            req = urllib.request.Request(
                license_url,
                headers={'Authorization': f'Bearer {access_token}'}
            )
            with urllib.request.urlopen(req, timeout=10, context=_make_ssl_ctx()) as response:
                license_data = json.loads(response.read().decode())
            has_ai_license = license_data.get('ai_license_active', False)
            if not has_ai_license:
                self.auth_failed.emit(
                    "Il tuo account JetBrains non ha una licenza AI attiva.\n"
                    "Acquista una licenza JetBrains AI per utilizzare questa funzionalità."
                )
                return
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self.auth_failed.emit("Token di accesso non valido")
                return
            elif e.code == 403:
                self.auth_failed.emit("Accesso negato — verifica le tue licenze JetBrains")
                return
            # Altro errore HTTP (es. 404 = endpoint non ancora disponibile): procedi
        except Exception:
            # Endpoint non raggiungibile: procedi comunque
            pass

        from config.settings import Settings
        Settings.instance().set("ai/jetbrains_token", access_token)
        self.auth_completed.emit(access_token)


# ─── Worker HTTP — streaming per Anthropic, batch per gli altri ───────────────

class _AIWorker(QThread):
    """Thread che chiama le API AI. Emette chunk via stream_chunk o result_ready."""

    stream_chunk   = pyqtSignal(str)        # testo parziale risposta
    think_chunk    = pyqtSignal(str)        # pensieri (Anthropic thinking, <think> Ollama)
    result_ready   = pyqtSignal(str)        # risposta completa
    error_occurred = pyqtSignal(str)
    usage_ready    = pyqtSignal(int, int)   # input_tokens, output_tokens
    speed_ready    = pyqtSignal(float, int) # tok/s generazione, output_tokens (modelli locali)

    def __init__(self, provider_id: str, model: str, api_key: str,
                 messages: list[dict], system: str = "",
                 max_tokens: int = 4096, thinking: bool = False,
                 ollama_url: str = "http://localhost:11434",
                 llamacpp_url: str = "http://localhost:8080"):
        super().__init__()
        self._provider    = provider_id
        self._model       = model
        self._key         = api_key
        self._messages    = messages
        self._system      = system
        self._max_tokens  = max_tokens
        self._thinking    = thinking
        self._ollama_url  = ollama_url
        self._llamacpp_url = llamacpp_url
        self._stop_event    = threading.Event()
        self._current_resp  = None  # risposta HTTP corrente, per chiusura forzata

    def stop(self) -> None:
        self._stop_event.set()
        resp = self._current_resp
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    def run(self) -> None:
        try:
            if self._provider == "anthropic":
                text = self._call_anthropic_stream()
            elif self._provider == "openai":
                text = self._call_openai()
            elif self._provider == "gemini":
                text = self._call_gemini()
            elif self._provider == "deepseek":
                text = self._call_deepseek()
            elif self._provider == "ollama":
                text = self._call_ollama()
            elif self._provider == "llamacpp":
                text = self._call_llamacpp()
            elif self._provider == "jetbrains":
                text = self._call_jetbrains()
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
                "deepseek":  "La chiave si ottiene su platform.deepseek.com/api_keys",
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

    @staticmethod
    def _strip_images(messages: list[dict]) -> list[dict]:
        """Ricostruisce i messaggi come {role, content} puri, scartando la
        chiave 'images' — usato dai provider che non supportano la vision."""
        return [{"role": m["role"], "content": m["content"]} for m in messages]

    @staticmethod
    def _anthropic_messages(messages: list[dict]) -> list[dict]:
        """Converte 'images' (lista di {name, media_type, data}) nei blocchi
        content Anthropic (image + text); i messaggi senza immagini restano
        content=stringa, invariati rispetto al formato precedente."""
        out = []
        for m in messages:
            imgs = m.get("images") or []
            if not imgs:
                out.append({"role": m["role"], "content": m["content"]})
                continue
            content = [
                {"type": "image", "source": {"type": "base64", "media_type": img["media_type"], "data": img["data"]}}
                for img in imgs
            ]
            if m["content"].strip():
                content.append({"type": "text", "text": m["content"]})
            out.append({"role": m["role"], "content": content})
        return out

    def _call_anthropic_stream(self) -> str:
        url  = "https://api.anthropic.com/v1/messages"
        body_dict: dict = {
            "model":      self._model,
            "max_tokens": self._max_tokens,
            "messages":   self._anthropic_messages(self._messages),
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

        with urllib.request.urlopen(req, timeout=120, context=_make_ssl_ctx()) as resp:
            for raw_line in resp:
                if self._stop_event.is_set():
                    break
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
                        chunk = delta.get("thinking", "")
                        if chunk:
                            self.think_chunk.emit(chunk)
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
        msgs = self._strip_images(self._messages)
        if self._system:
            msgs = [{"role": "system", "content": self._system}] + list(msgs)
        body = json.dumps({
            "model":      self._model,
            "messages":   msgs,
            "max_tokens": self._max_tokens,
            "stream":     True,
        }).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {self._key}",
        })
        with urllib.request.urlopen(req, timeout=120, context=_make_ssl_ctx()) as resp:
            self._current_resp = resp
            result = ""
            in_tokens = out_tokens = 0
            for line in resp:
                if self._stop_event.is_set():
                    break
                line = line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        result += content
                        self.stream_chunk.emit(content)
                    if "usage" in chunk:
                        u = chunk["usage"]
                        in_tokens = u.get("prompt_tokens", 0)
                        out_tokens = u.get("completion_tokens", 0)
                except Exception:
                    continue
        self.usage_ready.emit(in_tokens, out_tokens)
        return result

    # ── DeepSeek (API compatibile OpenAI) ────────────────────────────────────

    def _call_deepseek(self) -> str:
        url  = "https://api.deepseek.com/chat/completions"
        msgs = self._strip_images(self._messages)
        if self._system:
            msgs = [{"role": "system", "content": self._system}] + list(msgs)
        body = json.dumps({
            "model":      self._model,
            "messages":   msgs,
            "max_tokens": self._max_tokens,
            "stream":     True,
        }).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {self._key}",
        })
        with urllib.request.urlopen(req, timeout=120, context=_make_ssl_ctx()) as resp:
            self._current_resp = resp
            result = ""
            in_tokens = out_tokens = 0
            thinking_acc = ""
            for line in resp:
                if self._stop_event.is_set():
                    break
                line = line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    reasoning = delta.get("reasoning_content", "")
                    if reasoning:
                        thinking_acc += reasoning
                        self.think_chunk.emit(reasoning)
                    if content:
                        result += content
                        self.stream_chunk.emit(content)
                    if "usage" in chunk:
                        u = chunk["usage"]
                        in_tokens = u.get("prompt_tokens", 0)
                        out_tokens = u.get("completion_tokens", 0)
                except Exception:
                    continue
        self.usage_ready.emit(in_tokens, out_tokens)
        return result

    # ── Google Gemini ──────────────────────────────────────────────────────────

    def _call_gemini(self) -> str:
        model = self._model
        url   = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse&key={self._key}"
        contents = []
        if self._system:
            contents.append({"role": "user", "parts": [{"text": self._system}]})
            contents.append({"role": "model", "parts": [{"text": "Ho capito."}]})
        for m in self._messages:
            role  = "user" if m["role"] == "user" else "model"
            parts = [
                {"inlineData": {"mimeType": img["media_type"], "data": img["data"]}}
                for img in (m.get("images") or [])
            ]
            if m["content"].strip() or not parts:
                parts.append({"text": m["content"]})
            contents.append({"role": role, "parts": parts})
        body = json.dumps({
            "contents":         contents,
            "generationConfig": {"maxOutputTokens": self._max_tokens},
        }).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120, context=_make_ssl_ctx()) as resp:
            self._current_resp = resp
            result = ""
            in_tokens = out_tokens = 0
            for line in resp:
                if self._stop_event.is_set():
                    break
                line = line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                try:
                    chunk = json.loads(data_str)
                    candidates = chunk.get("candidates", [])
                    if candidates:
                        parts_list = candidates[0].get("content", {}).get("parts", [])
                        for p in parts_list:
                            if "text" in p:
                                result += p["text"]
                                self.stream_chunk.emit(p["text"])
                    usage = chunk.get("usageMetadata", {})
                    in_tokens = usage.get("promptTokenCount", 0)
                    out_tokens = usage.get("candidatesTokenCount", 0)
                except Exception:
                    continue
        self.usage_ready.emit(in_tokens, out_tokens)
        return result

    # ── Ollama ────────────────────────────────────────────────────────────────

    def _call_ollama(self) -> str:
        msgs = self._strip_images(self._messages)
        if self._system:
            msgs = [{"role": "system", "content": self._system}] + list(msgs)
        url  = f"{self._ollama_url}/api/chat"
        payload: dict = {"model": self._model, "messages": msgs, "stream": True}
        # Il campo "think" è supportato solo da alcuni modelli (DeepSeek, Qwen…).
        # Lo inviamo solo quando l'utente ha esplicitamente attivato il "thinking".
        if self._thinking:
            payload["think"] = True
        body = json.dumps(payload).encode()
        req  = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
        full_text = ""
        in_think  = False
        buf       = ""
        _OPEN     = "<think>"
        _CLOSE    = "</think>"

        def _flush_normal(text: str) -> None:
            nonlocal full_text
            if text:
                full_text += text
                self.stream_chunk.emit(text)

        try:
            with urllib.request.urlopen(req, timeout=600, context=_make_ssl_ctx()) as resp:
                self._current_resp = resp
                for raw_line in resp:
                    if self._stop_event.is_set():
                        break
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = event.get("message", {})
                    # pensieri nativi Ollama (campo "thinking", modelli DeepSeek/Qwen/etc.)
                    native_think = msg.get("thinking", "")
                    if native_think:
                        self.think_chunk.emit(native_think)
                    chunk = msg.get("content", "")
                    if chunk:
                        buf += chunk
                        # smista il buffer su think_chunk / stream_chunk
                        while buf:
                            if in_think:
                                end = buf.find(_CLOSE)
                                if end >= 0:
                                    self.think_chunk.emit(buf[:end])
                                    buf = buf[end + len(_CLOSE):]
                                    in_think = False
                                else:
                                    self.think_chunk.emit(buf)
                                    buf = ""
                            else:
                                start = buf.find(_OPEN)
                                if start >= 0:
                                    _flush_normal(buf[:start])
                                    buf = buf[start + len(_OPEN):]
                                    in_think = True
                                else:
                                    # trattieni eventuale prefisso parziale di <think> a fine buffer
                                    hold = 0
                                    for i in range(min(len(_OPEN) - 1, len(buf)), 0, -1):
                                        if buf.endswith(_OPEN[:i]):
                                            hold = i
                                            break
                                    _flush_normal(buf[:-hold] if hold else buf)
                                    buf = buf[-hold:] if hold else ""
                                    break
                    if event.get("done", False):
                        if buf and not in_think:
                            _flush_normal(buf)
                        # Metriche di velocità: eval_count token generati in
                        # eval_duration nanosecondi → token/secondo.
                        eval_count = event.get("eval_count")
                        eval_dur   = event.get("eval_duration")  # nanosecondi
                        if eval_count and eval_dur:
                            tps = eval_count / (eval_dur / 1e9)
                            self.speed_ready.emit(float(tps), int(eval_count))
                        break
        except urllib.error.HTTPError as e:
            # Errore HTTP (es. 400 Bad Request se il modello non accetta "think")
            body_err = ""
            try:
                body_err = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            raise RuntimeError(f"Ollama HTTP {e.code}: {body_err or e.reason}") from e
        except OSError:
            # resp.close() chiamato da stop() — uscita pulita
            pass
        finally:
            self._current_resp = None
        return full_text

    # ── LlamaCPP (llama-server, OpenAI-compatible) ────────────────────────────

    def _call_llamacpp(self) -> str:
        msgs = self._strip_images(self._messages)
        if self._system:
            msgs = [{"role": "system", "content": self._system}] + list(msgs)
        url  = f"{self._llamacpp_url.rstrip('/')}/v1/chat/completions"
        body = json.dumps({
            "model":      self._model,
            "messages":   msgs,
            "max_tokens": self._max_tokens,
            "stream":     True,
            # Chiede a llama-server di includere l'oggetto "timings" nei chunk SSE
            # (token/secondo). Ignorato dai server che non lo supportano.
            "timings_per_token": True,
        }).encode()
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        full_text = ""
        in_think  = False
        buf       = ""
        last_tps  = None   # ultimo predicted_per_second visto nei timings
        last_n    = 0      # ultimo predicted_n (token generati)
        _OPEN     = "<think>"
        _CLOSE    = "</think>"

        def _flush_normal(text: str) -> None:
            nonlocal full_text
            if text:
                full_text += text
                self.stream_chunk.emit(text)

        try:
            with urllib.request.urlopen(req, timeout=600, context=_make_ssl_ctx()) as resp:
                self._current_resp = resp
                for raw_line in resp:
                    if self._stop_event.is_set():
                        break
                    line = raw_line.decode("utf-8").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        if buf and not in_think:
                            _flush_normal(buf)
                        break
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    # Metriche di velocità (token/secondo) — llama-server le invia
                    # nei chunk quando "timings_per_token" è abilitato.
                    timings = event.get("timings")
                    if isinstance(timings, dict):
                        tps = timings.get("predicted_per_second")
                        if tps:
                            last_tps = float(tps)
                            last_n   = int(timings.get("predicted_n") or last_n)
                    choices = event.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    # reasoning_content (llama-server --reasoning-format) o thinking (alcune varianti)
                    native_think = delta.get("reasoning_content") or delta.get("thinking") or ""
                    if native_think:
                        self.think_chunk.emit(native_think)
                    chunk = delta.get("content") or ""
                    if chunk:
                        buf += chunk
                        # smista il buffer su think_chunk / stream_chunk
                        while buf:
                            if in_think:
                                end = buf.find(_CLOSE)
                                if end >= 0:
                                    self.think_chunk.emit(buf[:end])
                                    buf = buf[end + len(_CLOSE):]
                                    in_think = False
                                else:
                                    self.think_chunk.emit(buf)
                                    buf = ""
                            else:
                                start = buf.find(_OPEN)
                                if start >= 0:
                                    _flush_normal(buf[:start])
                                    buf = buf[start + len(_OPEN):]
                                    in_think = True
                                else:
                                    hold = 0
                                    for i in range(min(len(_OPEN) - 1, len(buf)), 0, -1):
                                        if buf.endswith(_OPEN[:i]):
                                            hold = i
                                            break
                                    _flush_normal(buf[:-hold] if hold else buf)
                                    buf = buf[-hold:] if hold else ""
                                    break
        except Exception:
            # resp.close() da stop() può sollevare OSError, IncompleteRead o altri
            # errori di socket a seconda del server; se lo stop era intenzionale
            # ignoriamo l'eccezione, altrimenti la rilanciamo.
            if not self._stop_event.is_set():
                raise
        finally:
            self._current_resp = None
        if last_tps:
            self.speed_ready.emit(last_tps, last_n)
        return full_text

    # ── JetBrains AI ──────────────────────────────────────────────────────────

    def _refresh_jetbrains_token(self, refresh_token: str, oauth_config: dict) -> str:
        """Tenta il refresh del token OAuth; restituisce il nuovo access_token o ''."""
        try:
            data = urllib.parse.urlencode({
                'grant_type':    'refresh_token',
                'client_id':     oauth_config.get('client_id', ''),
                'refresh_token': refresh_token,
            }).encode()
            req = urllib.request.Request(
                oauth_config.get('token_url', ''),
                data=data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            with urllib.request.urlopen(req, timeout=30, context=_make_ssl_ctx()) as resp:
                r = json.loads(resp.read().decode())
            access_token  = r.get('access_token', '')
            new_refresh   = r.get('refresh_token', refresh_token)
            expires_in    = int(r.get('expires_in', 3600))
            if access_token:
                from config.settings import Settings
                s = Settings.instance()
                s.set("ai/jetbrains_token", access_token)
                s.set("ai/jetbrains_refresh_token", new_refresh)
                s.set("ai/jetbrains_token_expires", int(time.time()) + expires_in - 60)
            return access_token
        except Exception:
            return ""

    def _call_jetbrains(self) -> str:
        """Chiama l'API JetBrains AI usando il token OAuth salvato"""
        from config.settings import Settings
        s = Settings.instance()

        access_token = s.get("ai/jetbrains_token", "")
        if not access_token:
            raise Exception("Token JetBrains AI non trovato. Effettua l'autenticazione OAuth dalle impostazioni.")

        # Refresh automatico se il token è scaduto
        expires_at = float(s.get("ai/jetbrains_token_expires", 0) or 0)
        if expires_at > 0 and time.time() > expires_at:
            refresh_token = s.get("ai/jetbrains_refresh_token", "")
            oauth_config  = PROVIDERS.get("JetBrains AI", {}).get("oauth_config", {})
            if refresh_token and oauth_config:
                access_token = self._refresh_jetbrains_token(refresh_token, oauth_config)
            if not access_token:
                raise Exception("Token JetBrains AI scaduto. Rieffettua l'autenticazione OAuth dalle impostazioni.")
        
        # Endpoint JetBrains AI per chat completions
        url = "https://api.jetbrains.com/v1/chat/completions"
        
        # Prepara i messaggi nel formato OpenAI-compatibile
        msgs = self._strip_images(self._messages)
        if self._system:
            msgs = [{"role": "system", "content": self._system}] + list(msgs)
        
        # Corpo della richiesta
        body = json.dumps({
            "model": self._model,
            "messages": msgs,
            "max_tokens": self._max_tokens,
            "temperature": 0.7
        }).encode()
        
        # Headers con autenticazione Bearer
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "NotePadPQ-AI-Assistant/1.1"
        }
        
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        
        try:
            with urllib.request.urlopen(req, timeout=60, context=_make_ssl_ctx()) as resp:
                data = json.loads(resp.read())
            
            # Estrae la risposta e i token usage se disponibili
            if "choices" in data and len(data["choices"]) > 0:
                content = data["choices"][0]["message"]["content"]
                
                # Emette usage se disponibile
                if "usage" in data:
                    usage = data["usage"]
                    self.usage_ready.emit(
                        usage.get("prompt_tokens", 0), 
                        usage.get("completion_tokens", 0)
                    )
                
                return content
            else:
                raise Exception("Risposta non valida dall'API JetBrains AI")
                
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise Exception("Token JetBrains AI scaduto o non valido. Rieffettua l'autenticazione OAuth.")
            elif e.code == 403:
                raise Exception("Accesso negato. Verifica che la tua licenza JetBrains AI sia attiva.")
            elif e.code == 429:
                raise Exception("Limite di richieste raggiunto. Riprova tra qualche minuto.")
            else:
                # Prova a leggere il messaggio di errore dal corpo della risposta
                try:
                    error_body = e.read().decode()
                    error_data = json.loads(error_body)
                    error_msg = error_data.get("error", {}).get("message", f"HTTP {e.code}")
                except Exception:
                    error_msg = f"HTTP {e.code}"
                raise Exception(f"Errore API JetBrains AI: {error_msg}")


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
        self._oauth_buttons: dict[str, QPushButton] = {}
        self._oauth_status: dict[str, QLabel] = {}
        self._oauth_disconnect: dict[str, QPushButton] = {}

        _placeholders = {
            "anthropic": "sk-ant-api03-…  (da console.anthropic.com)",
            "openai":    "sk-proj-…  (da platform.openai.com)",
            "gemini":    "AIzaSy…  (da aistudio.google.com)",
            "deepseek":  "sk-…  (da platform.deepseek.com)",
            "ollama":    "http://localhost:11434",
            "llamacpp":  "http://localhost:8080",
        }
        for name, info in PROVIDERS.items():
            pid  = info["id"]
            auth_type = info.get("auth_type", "api_key")
            
            if info["key_url"]:
                lbl_text = f"<b>{name}</b> &nbsp;<a href='{info['key_url']}'>[ottieni chiave ↗]</a>"
            else:
                lbl_text = f"<b>{name}</b>"
            lbl = QLabel(lbl_text)
            lbl.setOpenExternalLinks(True)

            if auth_type == "oauth":
                outer = QVBoxLayout()
                outer.setSpacing(4)
                outer.setContentsMargins(0, 0, 0, 0)

                # ── riga pulsanti OAuth ──
                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)

                btn_oauth = QPushButton("🔐 Accedi con JetBrains")
                btn_oauth.setMinimumHeight(28)
                btn_oauth.setToolTip("Avvia il flusso OAuth nel browser (richiede client_id registrato con JetBrains)")
                btn_oauth.clicked.connect(lambda _, p=pid: self._start_oauth_login(p))
                row_layout.addWidget(btn_oauth, 1)

                btn_disc = QPushButton("Disconnetti")
                btn_disc.setMinimumHeight(28)
                btn_disc.setFixedWidth(90)
                btn_disc.setStyleSheet("color:#f44747;")
                btn_disc.clicked.connect(lambda _, p=pid: self._disconnect_oauth(p))
                btn_disc.hide()
                row_layout.addWidget(btn_disc)

                status_lbl = QLabel("")
                status_lbl.setStyleSheet("color:#858585; font-size:10px;")
                row_layout.addWidget(status_lbl)
                outer.addWidget(row_widget)

                # ── riga token manuale ──
                token_row = QWidget()
                token_layout = QHBoxLayout(token_row)
                token_layout.setContentsMargins(0, 0, 0, 0)
                token_lbl = QLabel("Bearer token:")
                token_lbl.setStyleSheet("color:#858585; font-size:10px;")
                token_edit = QLineEdit()
                token_edit.setEchoMode(QLineEdit.EchoMode.Password)
                token_edit.setPlaceholderText("Incolla il token Bearer dalle richieste AI del tuo IDE JetBrains")
                token_edit.setStyleSheet("font-size:10px;")
                token_edit.setToolTip(
                    "Alternativa all'OAuth: copia il Bearer token dall'header Authorization\n"
                    "che il tuo IDE JetBrains (PyCharm/IntelliJ) invia a api.grazie.ai"
                )
                btn_tok_show = QPushButton("👁")
                btn_tok_show.setFixedWidth(24)
                btn_tok_show.setCheckable(True)
                btn_tok_show.toggled.connect(
                    lambda checked, e=token_edit: e.setEchoMode(
                        QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
                    )
                )
                token_layout.addWidget(token_lbl)
                token_layout.addWidget(token_edit, 1)
                token_layout.addWidget(btn_tok_show)
                outer.addWidget(token_row)

                outer_w = QWidget()
                outer_w.setLayout(outer)

                self._oauth_buttons[pid] = btn_oauth
                self._oauth_disconnect[pid] = btn_disc
                self._oauth_status[pid] = status_lbl
                self._key_edits[pid] = token_edit   # riusa lo stesso meccanismo save/load

                form.addRow(lbl, outer_w)
                
            else:
                # Provider con API key tradizionale
                edit = QLineEdit()
                if pid in ("ollama", "llamacpp"):
                    edit.setPlaceholderText(_placeholders[pid])
                else:
                    edit.setEchoMode(QLineEdit.EchoMode.Password)
                    edit.setPlaceholderText(_placeholders.get(pid, ""))

                # Riga: campo + pulsante mostra/nascondi
                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.addWidget(edit, 1)
                if pid not in ("ollama", "llamacpp"):
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
                self._key_edits[pid] = edit
            
            if info.get("note"):
                note_lbl = QLabel(f"<small><i>{info['note']}</i></small>")
                note_lbl.setOpenExternalLinks(True)
                note_lbl.setStyleSheet("color:#858585;")
                form.addRow("", note_lbl)

        layout.addLayout(form)

        # Max token default
        tok_row = QHBoxLayout()
        tok_row.addWidget(QLabel("Max token risposta:"))
        self._max_tok = QSpinBox()
        # Nessun tetto client-side realistico: il vero limite lo impone il
        # provider (es. Anthropic consente output molto elevati con alcuni
        # modelli/beta header). Il valore qui è solo il default richiesto al provider.
        self._max_tok.setRange(256, 1_000_000)
        self._max_tok.setValue(_DEFAULT_MAX_TOKENS)
        self._max_tok.setSingleStep(1024)
        tok_row.addWidget(self._max_tok)
        tok_row.addStretch()
        layout.addLayout(tok_row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText(tr("button.ok", default="OK"))
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("button.cancel", default="Cancel"))

    def _load(self) -> None:
        for pid, edit in self._key_edits.items():
            key = _settings_key(pid)
            edit.setText(self._s.get(key, ""))
        self._max_tok.setValue(int(self._s.get("ai/max_tokens", _DEFAULT_MAX_TOKENS)))
        self._update_oauth_status()

    def _save(self) -> None:
        for pid, edit in self._key_edits.items():
            val = edit.text().strip()
            key = _settings_key(pid)
            self._s.set(key, val)
        self._s.set("ai/max_tokens", self._max_tok.value())
        self.accept()
    
    def _update_oauth_status(self) -> None:
        """Aggiorna lo stato di autenticazione OAuth per i provider che lo supportano"""
        for pid, status_lbl in self._oauth_status.items():
            token = self._s.get(f"ai/{pid}_token", "")
            disc_btn = self._oauth_disconnect.get(pid)
            if token:
                status_lbl.setText("✅ Autenticato")
                status_lbl.setStyleSheet("color:#2ea043; font-size:10px;")
                self._oauth_buttons[pid].setText("🔐 Riautentica")
                if disc_btn:
                    disc_btn.show()
            else:
                status_lbl.setText("❌ Non autenticato")
                status_lbl.setStyleSheet("color:#f44747; font-size:10px;")
                self._oauth_buttons[pid].setText("🔐 Accedi con JetBrains")
                if disc_btn:
                    disc_btn.hide()
    
    def _start_oauth_login(self, provider_id: str) -> None:
        """Avvia il flusso di autenticazione OAuth per il provider specificato"""
        if provider_id != "jetbrains":
            return
            
        # Ottieni la configurazione OAuth per JetBrains
        provider_info = PROVIDERS.get("JetBrains AI", {})
        oauth_config = provider_info.get("oauth_config", {})
        
        if not oauth_config:
            QMessageBox.warning(self, "Errore", "Configurazione OAuth non trovata per JetBrains AI")
            return
        
        # Aggiorna UI
        self._oauth_buttons[provider_id].setEnabled(False)
        self._oauth_buttons[provider_id].setText("🔄 Autenticazione in corso...")
        self._oauth_status[provider_id].setText("🔄 Apertura browser...")
        self._oauth_status[provider_id].setStyleSheet("color:#ffcc00; font-size:10px;")
        
        # Crea e configura l'handler OAuth
        self._oauth_handler = _JetBrainsOAuth()
        self._oauth_handler.auth_completed.connect(self._on_oauth_success)
        self._oauth_handler.auth_failed.connect(self._on_oauth_error)
        
        # Avvia il flusso OAuth
        self._oauth_handler.start_auth_flow(oauth_config)
    
    def _on_oauth_success(self, access_token: str) -> None:
        """Gestisce il successo dell'autenticazione OAuth"""
        # Aggiorna UI
        self._oauth_status["jetbrains"].setText("✅ Autenticazione completata!")
        self._oauth_status["jetbrains"].setStyleSheet("color:#2ea043; font-size:10px;")
        self._oauth_buttons["jetbrains"].setText("🔐 Riautentica")
        self._oauth_buttons["jetbrains"].setEnabled(True)
        
        # Mostra messaggio di successo
        QMessageBox.information(
            self, 
            "Autenticazione completata", 
            "Autenticazione JetBrains AI completata con successo!\n"
            "Ora puoi utilizzare JetBrains AI nel pannello chat."
        )
        
        # Pulisce l'handler
        self._oauth_handler = None
    
    def _on_oauth_error(self, error_message: str) -> None:
        """Gestisce gli errori di autenticazione OAuth"""
        # Ripristina UI
        self._oauth_status["jetbrains"].setText("❌ Errore di autenticazione")
        self._oauth_status["jetbrains"].setStyleSheet("color:#f44747; font-size:10px;")
        self._oauth_buttons["jetbrains"].setText("🔐 Accedi con JetBrains")
        self._oauth_buttons["jetbrains"].setEnabled(True)
        
        # Mostra messaggio di errore
        QMessageBox.warning(
            self, 
            "Errore di autenticazione", 
            f"Errore durante l'autenticazione JetBrains AI:\n\n{error_message}"
        )
        
        # Pulisce l'handler
        self._oauth_handler = None

    def _disconnect_oauth(self, provider_id: str) -> None:
        """Rimuove il token OAuth salvato per il provider indicato."""
        self._s.set(f"ai/{provider_id}_token", "")
        self._s.set(f"ai/{provider_id}_refresh_token", "")
        self._s.set(f"ai/{provider_id}_token_expires", "")
        self._update_oauth_status()


# ─── Pannello chat ────────────────────────────────────────────────────────────

class _AIPanel(QWidget):

    _ollama_ready     = pyqtSignal(object)  # list[str] | None — thread-safe
    _anthropic_ready  = pyqtSignal(object)  # list[str] | None — thread-safe
    _openai_ready     = pyqtSignal(object)  # list[str] | None — thread-safe
    _gemini_ready     = pyqtSignal(object)  # list[str] | None — thread-safe
    _deepseek_ready   = pyqtSignal(object)  # list[str] | None — thread-safe
    _llamacpp_ready   = pyqtSignal(object)  # list[str] | None — thread-safe

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self._mw        = main_window
        self._history:  list[dict] = []
        self._worker:      Optional[_AIWorker] = None
        self._old_workers: list[_AIWorker]     = []
        self._streaming_block = False
        self._stream_acc = ""
        self._speed_status = ""   # riga di stato tok/s dei modelli locali
        self._gen_start    = 0.0  # istante del primo chunk di testo (inizio generazione)
        self._gen_chars    = 0    # caratteri di sola risposta generati (no pensieri)
        self._think_start  = 0.0  # istante del primo chunk di pensiero (inizio ragionamento)
        self._think_chars  = 0    # caratteri di soli pensieri generati
        self._local_model  = False  # True se il provider è Ollama/llama.cpp (stima tok/s live)
        self._inline_selection: Optional[tuple] = None  # (lf, cf, lt, ct) o None = intero file
        self._pending_images: list[dict] = []  # immagini in coda, allegate al prossimo invio
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._elapsed_start  = 0.0
        self._has_thinking   = False
        self._has_streaming  = False
        self._think_text_acc = ""
        self._ollama_ready.connect(self._set_ollama_models)
        self._anthropic_ready.connect(self._set_anthropic_models)
        self._openai_ready.connect(self._set_openai_models)
        self._gemini_ready.connect(self._set_gemini_models)
        self._deepseek_ready.connect(self._set_deepseek_models)
        self._llamacpp_ready.connect(self._set_llamacpp_models)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── Provider + modello + settings ─────────────────────────────────────
        top = QHBoxLayout()
        self._provider_combo = QComboBox()
        cloud_done = False
        for name in PROVIDERS:
            pid = PROVIDERS[name].get("id", "")
            if pid in ("ollama", "llamacpp") and not cloud_done:
                self._provider_combo.insertSeparator(self._provider_combo.count())
                cloud_done = True
            self._provider_combo.addItem(name)
        self._provider_combo.setToolTip(tr("tooltip.ai_provider"))
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self._model_combo = QComboBox()
        self._model_combo.setMinimumWidth(180)
        self._model_combo.setToolTip(tr("tooltip.ai_model"))
        self._model_combo.currentTextChanged.connect(self._on_model_changed)
        self._btn_refresh_models = QPushButton("↻")
        self._btn_refresh_models.setFixedWidth(26)
        self._btn_refresh_models.setToolTip("Ricarica la lista modelli disponibili")
        self._btn_refresh_models.clicked.connect(self._manual_refresh_models)
        self._btn_refresh_models.setVisible(False)
        btn_settings = QPushButton("⚙")
        btn_settings.setFixedWidth(28)
        btn_settings.setToolTip(tr("tooltip.ai_settings"))
        btn_settings.clicked.connect(self._open_settings)
        top.addWidget(QLabel("Provider:"))
        top.addWidget(self._provider_combo, 1)
        top.addWidget(QLabel("Modello:"))
        top.addWidget(self._model_combo, 1)
        top.addWidget(self._btn_refresh_models)
        top.addWidget(btn_settings)
        layout.addLayout(top)

        # ── Opzioni avanzate (Extended Thinking, Inline edit, costo) ─────────
        adv = QHBoxLayout()
        self._chk_thinking = QCheckBox("Extended Thinking")
        self._chk_thinking.setToolTip(tr("tooltip.ai_thinking"))
        self._chk_thinking.setVisible(False)
        self._chk_inline = QCheckBox("✏ Inline edit")
        self._chk_inline.setToolTip(tr("tooltip.ai_inline"))
        self._chk_inline.toggled.connect(self._on_inline_toggled)
        self._lbl_cost = QLabel("")
        self._lbl_cost.setToolTip(tr("tooltip.ai_cost"))
        self._lbl_cost.setStyleSheet("color:#858585; font-size:10px;")
        adv.addWidget(self._chk_thinking)
        adv.addWidget(self._chk_inline)
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
        btn_ask_file = QPushButton(tr("action.ai_ask_file_btn"))
        btn_ask_file.setToolTip(tr("tooltip.ai_ask_file"))
        btn_ask_file.clicked.connect(self._ask_about_file)
        btn_ask_sel = QPushButton(tr("action.ai_ask_sel_btn"))
        btn_ask_sel.setToolTip(tr("tooltip.ai_ask_sel"))
        btn_ask_sel.clicked.connect(self._ask_about_selection)
        quick_row.addWidget(btn_ask_file)
        quick_row.addWidget(btn_ask_sel)
        layout.addLayout(quick_row)

        # ── Azioni contestuali (applicano subito un prompt fisso) ─────────────
        _action_tooltips = {
            "action.ai_explain":   tr("tooltip.ai_explain"),
            "action.ai_refactor":  tr("tooltip.ai_refactor"),
            "action.ai_docstring": tr("tooltip.ai_docstring"),
            "action.ai_fix_bug":   tr("tooltip.ai_fix_bug"),
        }
        act_row = QHBoxLayout()
        for label, prompt in CONTEXT_ACTIONS[:4]:
            btn = QPushButton(tr(label))
            btn.setFixedHeight(24)
            btn.setToolTip(_action_tooltips.get(label, prompt))
            btn.clicked.connect(lambda _, p=prompt: self._context_action(p))
            act_row.addWidget(btn)
        btn_more = QPushButton(tr("action.ai_more"))
        btn_more.setFixedHeight(24)
        btn_more.setToolTip(tr("tooltip.ai_more"))
        btn_more.clicked.connect(self._show_more_actions)
        act_row.addWidget(btn_more)
        layout.addLayout(act_row)

        # ── Splitter chat / pensieri / input ─────────────────────────────────
        self._splitter = QSplitter(Qt.Orientation.Vertical)

        self._pal = _chat_palette()
        self._chat_view = QTextEdit()
        self._chat_view.setReadOnly(True)
        # Font di default dell'UI per il testo discorsivo (il monospace viene
        # applicato solo ai blocchi di codice via stile inline).
        self._chat_view.setStyleSheet(
            f"background:{self._pal['base_bg']}; color:{self._pal['base_fg']}; "
            f"border:none; padding:2px;"
        )
        self._chat_view.setToolTip(tr("tooltip.ai_chat"))
        self._splitter.addWidget(self._chat_view)

        # ── Pannello pensieri (pane centrale nello splitter) ─────────────────
        think_widget = QWidget()
        think_widget.setStyleSheet("background:#111827;")
        think_layout = QVBoxLayout(think_widget)
        think_layout.setContentsMargins(0, 0, 0, 0)
        think_layout.setSpacing(0)

        self._think_btn = QPushButton("▶ Pensieri")
        self._think_btn.setCheckable(True)
        self._think_btn.setFixedHeight(22)
        self._think_btn.setStyleSheet(
            "text-align:left; padding-left:8px; font-size:10px;"
            "background:#1a1a2e; color:#6b7280; border:none;"
            "border-top:1px solid #3c3c3c; border-bottom:1px solid #3c3c3c;"
        )
        self._think_btn.toggled.connect(self._toggle_think)
        think_layout.addWidget(self._think_btn)

        self._think_box = QPlainTextEdit()
        self._think_box.setReadOnly(True)
        self._think_box.setFont(QFont("Monospace", 9))
        self._think_box.setStyleSheet("background:#111827; color:#6b7280; border:none;")
        self._think_box.hide()  # collassato finché non arrivano pensieri / espansione manuale
        think_layout.addWidget(self._think_box, 1)

        self._think_widget = think_widget
        self._think_widget.hide()
        self._splitter.addWidget(think_widget)

        input_widget = QWidget()
        input_layout = QVBoxLayout(input_widget)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(2)

        self._input = QPlainTextEdit()
        self._input.setMinimumHeight(60)
        self._input.setFont(QFont("Monospace", 10))
        self._input.setPlaceholderText("Scrivi un messaggio…  (/explain /fix /refactor /file)  Ctrl+Enter per inviare, Ctrl+L per nuova riga")
        self._input.setStyleSheet("background:#252526; color:#d4d4d4; border:1px solid #3c3c3c;")
        self._input.setToolTip(tr("tooltip.ai_input"))
        self._input.installEventFilter(self)
        self._input.textChanged.connect(self._update_token_estimate)
        input_layout.addWidget(self._input, stretch=1)

        btn_row = QHBoxLayout()
        self._btn_ctx = QPushButton("+ Contesto")
        self._btn_ctx.setToolTip(tr("tooltip.ai_add_context"))
        self._btn_ctx.clicked.connect(self._add_context)
        self._btn_attach = QPushButton("📎 Allega file")
        self._btn_attach.setToolTip(tr("tooltip.ai_attach_file",
            default="Seleziona uno o più file dal disco: il tipo viene riconosciuto automaticamente.\n"
                    "Testo/codice → aggiunto come contesto nel campo di input.\n"
                    "Immagini (PNG/JPEG/GIF/WEBP) → messe in coda per l'invio come vision\n"
                    "(solo provider Anthropic e Google Gemini)."))
        self._btn_attach.clicked.connect(self._attach_file)
        self._lbl_pending_images = QLabel("")
        self._lbl_pending_images.setStyleSheet("color:#858585; font-size:10px;")
        self._btn_clear_images = QPushButton("✕")
        self._btn_clear_images.setFixedWidth(20)
        self._btn_clear_images.setToolTip("Rimuove le immagini in coda")
        self._btn_clear_images.clicked.connect(self._clear_pending_images)
        self._btn_clear_images.hide()
        self._btn_apply = QPushButton("⬇ Al file")
        self._btn_apply.setToolTip(tr("tooltip.ai_apply"))
        self._btn_apply.clicked.connect(self._apply_to_file)
        self._btn_apply.setEnabled(False)
        self._btn_diff = QPushButton("↔ Diff")
        self._btn_diff.setToolTip(tr("tooltip.ai_diff", default="Mostra le modifiche prima di applicarle al file"))
        self._btn_diff.clicked.connect(self._show_diff)
        self._btn_diff.setEnabled(False)
        self._btn_new_tab = QPushButton("📄 Nuovo tab")
        self._btn_new_tab.setToolTip(tr("tooltip.ai_new_tab"))
        self._btn_new_tab.clicked.connect(self._open_in_new_tab)
        self._btn_new_tab.setEnabled(False)
        self._btn_regenerate = QPushButton("↻ Rigenera")
        self._btn_regenerate.setToolTip(tr("tooltip.ai_regenerate", default="Rigenera l'ultima risposta"))
        self._btn_regenerate.clicked.connect(self._regenerate)
        self._btn_regenerate.setEnabled(False)
        self._btn_clear = QPushButton("Pulisci chat")
        self._btn_clear.setToolTip(tr("tooltip.ai_clear"))
        self._btn_clear.clicked.connect(self._clear)
        self._btn_send = QPushButton("▶ Invia")
        self._btn_send.setToolTip(tr("tooltip.ai_send"))
        self._btn_send.clicked.connect(self._on_send_btn)
        self._lbl_tokens = QLabel("")
        self._lbl_tokens.setStyleSheet("color:#858585; font-size:10px; padding: 0 6px;")
        btn_row.addWidget(self._btn_ctx)
        btn_row.addWidget(self._btn_attach)
        btn_row.addWidget(self._lbl_pending_images)
        btn_row.addWidget(self._btn_clear_images)
        btn_row.addWidget(self._lbl_tokens)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_diff)
        btn_row.addWidget(self._btn_apply)
        btn_row.addWidget(self._btn_new_tab)
        btn_row.addWidget(self._btn_regenerate)
        btn_row.addWidget(self._btn_clear)
        btn_row.addWidget(self._btn_send)
        input_layout.addLayout(btn_row)

        # Lo splitter gestisce SOLO chat + pensieri (2 pane). L'input resta un
        # blocco fisso sotto lo splitter: così trascinando l'handle dei Pensieri
        # non si sposta più la casella di scrittura del messaggio.
        self._splitter.setSizes([300, 0])
        self._splitter.setCollapsible(0, False)
        # Pane Pensieri non collassabile a 0 dallo splitter: quando è visibile
        # deve mostrare almeno la barra "▶ Pensieri" (il box interno si
        # mostra/nasconde separatamente via _expand_think/_collapse_think).
        self._splitter.setCollapsible(1, False)
        layout.addWidget(self._splitter, 1)
        layout.addWidget(input_widget)

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
        pid  = info.get("id", "")
        self._model_combo.setEnabled(True)
        self._model_combo.clear()
        for m in info.get("models", []):
            self._model_combo.addItem(m)
        default = info.get("default", "")
        idx = self._model_combo.findText(default)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)
        self._btn_refresh_models.setVisible(pid in ("anthropic", "ollama", "openai", "gemini", "llamacpp", "deepseek"))
        if pid == "ollama":
            self._refresh_ollama_models()
        elif pid == "anthropic":
            self._refresh_anthropic_models()
        elif pid == "openai":
            self._refresh_openai_models()
        elif pid == "gemini":
            self._refresh_gemini_models()
        elif pid == "llamacpp":
            self._refresh_llamacpp_models()
        elif pid == "deepseek":
            self._refresh_deepseek_models()

    def _on_model_changed(self, model: str) -> None:
        name    = self._provider_combo.currentText()
        info    = PROVIDERS.get(name, {})
        is_think = model in info.get("thinking_models", [])
        self._chk_thinking.setVisible(is_think)
        if model in MODEL_COST:
            inp, out = MODEL_COST[model]
            self._lbl_cost.setText(f"~${inp:.2f}/MTok in · ${out:.2f}/MTok out")
        else:
            self._lbl_cost.setText("")

    def _refresh_ollama_models(self) -> None:
        """Interroga Ollama /api/tags in background e aggiorna il combo con i modelli installati."""
        import threading
        from config.settings import Settings
        ollama_url = Settings.instance().get("ai/ollama_key", "") or "http://localhost:11434"

        def _fetch():
            try:
                url = f"{ollama_url.rstrip('/')}/api/tags"
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=3, context=_make_ssl_ctx()) as resp:
                    data = json.loads(resp.read())
                models = [m["name"] for m in data.get("models", [])]
                self._ollama_ready.emit(models or [])
            except Exception:
                self._ollama_ready.emit(None)

        threading.Thread(target=_fetch, daemon=True).start()

    def _set_ollama_models(self, models: Optional[list[str]]) -> None:
        """Popola il combo modelli con i modelli Ollama installati (chiamato nel thread principale)."""
        if PROVIDERS.get(self._provider_combo.currentText(), {}).get("id") != "ollama":
            return
        # Salva la selezione corrente PRIMA di svuotare il combo
        current = self._model_combo.currentText()
        self._model_combo.clear()
        if models is None:
            self._model_combo.addItem("⚠ ollama non raggiungibile")
            self._model_combo.setEnabled(False)
            return
        self._model_combo.setEnabled(True)
        for m in models:
            self._model_combo.addItem(m)
        idx = self._model_combo.findText(current)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)

    def _refresh_anthropic_models(self) -> None:
        """Interroga /v1/models Anthropic in background e aggiorna il combo."""
        import threading
        from config.settings import Settings
        api_key = Settings.instance().get("ai/anthropic_key", "").strip()
        if not api_key:
            return  # nessuna chiave — lascia i modelli statici

        self._btn_refresh_models.setEnabled(False)
        self._btn_refresh_models.setText("…")

        def _fetch():
            try:
                req = urllib.request.Request(
                    "https://api.anthropic.com/v1/models",
                    method="GET",
                    headers={
                        "x-api-key":         api_key,
                        "anthropic-version": "2023-06-01",
                    }
                )
                with urllib.request.urlopen(req, timeout=8, context=_make_ssl_ctx()) as resp:
                    data = json.loads(resp.read())
                model_ids = [
                    m["id"] for m in data.get("data", [])
                    if m.get("id", "").startswith("claude-")
                ]
                # Ordina: metti prima i modelli già nella lista statica
                static = PROVIDERS["Anthropic (Claude)"]["models"]
                known   = [m for m in static   if m in model_ids]
                extra   = [m for m in model_ids if m not in static]
                self._anthropic_ready.emit(known + extra if (known or extra) else None)
            except Exception:
                self._anthropic_ready.emit(None)

        threading.Thread(target=_fetch, daemon=True).start()

    def _set_anthropic_models(self, models: Optional[list[str]]) -> None:
        """Popola il combo con i modelli Anthropic effettivamente disponibili."""
        self._btn_refresh_models.setEnabled(True)
        self._btn_refresh_models.setText("↻")
        if PROVIDERS.get(self._provider_combo.currentText(), {}).get("id") != "anthropic":
            return
        if not models:
            return  # errore rete — lascia quelli statici già nel combo
        current = self._model_combo.currentText()
        self._model_combo.clear()
        for m in models:
            self._model_combo.addItem(m)
        # Riseleziona il modello precedente se ancora disponibile
        idx = self._model_combo.findText(current)
        default_idx = self._model_combo.findText(PROVIDERS["Anthropic (Claude)"]["default"])
        self._model_combo.setCurrentIndex(idx if idx >= 0 else max(default_idx, 0))

    def _refresh_openai_models(self) -> None:
        """Interroga /v1/models OpenAI in background e aggiorna il combo con i modelli chat."""
        import threading
        from config.settings import Settings
        api_key = Settings.instance().get("ai/openai_key", "").strip()
        if not api_key:
            return

        self._btn_refresh_models.setEnabled(False)
        self._btn_refresh_models.setText("…")

        def _fetch():
            try:
                req = urllib.request.Request(
                    "https://api.openai.com/v1/models",
                    method="GET",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                with urllib.request.urlopen(req, timeout=8, context=_make_ssl_ctx()) as resp:
                    data = json.loads(resp.read())
                _EXCL = ("embedding", "dall-e", "whisper", "tts", "text-", "babbage",
                         "davinci", "curie", "ada-", "realtime", "audio", "transcribe")
                _INCL = ("gpt-", "o1", "o3", "o4")
                models = sorted(
                    [m["id"] for m in data.get("data", [])
                     if any(m["id"].startswith(p) for p in _INCL)
                     and not any(ex in m["id"] for ex in _EXCL)],
                    reverse=True
                )
                static = PROVIDERS["OpenAI (ChatGPT)"]["models"]
                known = [m for m in static if m in models]
                extra = [m for m in models if m not in static]
                self._openai_ready.emit(known + extra if (known or extra) else None)
            except Exception:
                self._openai_ready.emit(None)

        threading.Thread(target=_fetch, daemon=True).start()

    def _set_openai_models(self, models) -> None:
        """Popola il combo con i modelli OpenAI effettivamente disponibili."""
        self._btn_refresh_models.setEnabled(True)
        self._btn_refresh_models.setText("↻")
        if PROVIDERS.get(self._provider_combo.currentText(), {}).get("id") != "openai":
            return
        if not models:
            return
        current = self._model_combo.currentText()
        self._model_combo.clear()
        for m in models:
            self._model_combo.addItem(m)
        idx = self._model_combo.findText(current)
        default_idx = self._model_combo.findText(PROVIDERS["OpenAI (ChatGPT)"]["default"])
        self._model_combo.setCurrentIndex(idx if idx >= 0 else max(default_idx, 0))

    def _refresh_gemini_models(self) -> None:
        """Interroga /v1beta/models Gemini in background e aggiorna il combo."""
        import threading
        from config.settings import Settings
        api_key = Settings.instance().get("ai/gemini_key", "").strip()
        if not api_key:
            return

        self._btn_refresh_models.setEnabled(False)
        self._btn_refresh_models.setText("…")

        def _fetch():
            try:
                req = urllib.request.Request(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=8, context=_make_ssl_ctx()) as resp:
                    data = json.loads(resp.read())
                models = [
                    m["name"].split("/")[-1]
                    for m in data.get("models", [])
                    if m.get("name", "").startswith("models/gemini")
                    and "generateContent" in m.get("supportedGenerationMethods", [])
                ]
                static = PROVIDERS["Google Gemini"]["models"]
                known = [m for m in static if m in models]
                extra = [m for m in models if m not in static]
                self._gemini_ready.emit(known + extra if (known or extra) else None)
            except Exception:
                self._gemini_ready.emit(None)

        threading.Thread(target=_fetch, daemon=True).start()

    def _set_gemini_models(self, models) -> None:
        """Popola il combo con i modelli Gemini effettivamente disponibili."""
        self._btn_refresh_models.setEnabled(True)
        self._btn_refresh_models.setText("↻")
        if PROVIDERS.get(self._provider_combo.currentText(), {}).get("id") != "gemini":
            return
        if not models:
            return
        current = self._model_combo.currentText()
        self._model_combo.clear()
        for m in models:
            self._model_combo.addItem(m)
        idx = self._model_combo.findText(current)
        default_idx = self._model_combo.findText(PROVIDERS["Google Gemini"]["default"])
        self._model_combo.setCurrentIndex(idx if idx >= 0 else max(default_idx, 0))

    def _refresh_deepseek_models(self) -> None:
        """Interroga /v1/models DeepSeek (API compatibile OpenAI) in background."""
        import threading
        from config.settings import Settings
        api_key = Settings.instance().get("ai/deepseek_key", "").strip()
        if not api_key:
            return

        self._btn_refresh_models.setEnabled(False)
        self._btn_refresh_models.setText("…")

        def _fetch():
            try:
                req = urllib.request.Request(
                    "https://api.deepseek.com/v1/models",
                    method="GET",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                with urllib.request.urlopen(req, timeout=8, context=_make_ssl_ctx()) as resp:
                    data = json.loads(resp.read())
                models = sorted(
                    [m["id"] for m in data.get("data", [])
                     if m.get("id", "").startswith("deepseek")],
                    reverse=True
                )
                static = PROVIDERS["DeepSeek"]["models"]
                known = [m for m in static if m in models]
                extra = [m for m in models if m not in static]
                self._deepseek_ready.emit(known + extra if (known or extra) else None)
            except Exception:
                self._deepseek_ready.emit(None)

        threading.Thread(target=_fetch, daemon=True).start()

    def _set_deepseek_models(self, models) -> None:
        """Popola il combo con i modelli DeepSeek effettivamente disponibili."""
        self._btn_refresh_models.setEnabled(True)
        self._btn_refresh_models.setText("↻")
        if PROVIDERS.get(self._provider_combo.currentText(), {}).get("id") != "deepseek":
            return
        if not models:
            return
        current = self._model_combo.currentText()
        self._model_combo.clear()
        for m in models:
            self._model_combo.addItem(m)
        idx = self._model_combo.findText(current)
        default_idx = self._model_combo.findText(PROVIDERS["DeepSeek"]["default"])
        self._model_combo.setCurrentIndex(idx if idx >= 0 else max(default_idx, 0))

    def _refresh_llamacpp_models(self) -> None:
        """Interroga llama-server /v1/models in background e aggiorna il combo."""
        import threading
        from config.settings import Settings
        llamacpp_url = Settings.instance().get("ai/llamacpp_key", "") or "http://localhost:8080"

        def _fetch():
            try:
                url = f"{llamacpp_url.rstrip('/')}/v1/models"
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=3, context=_make_ssl_ctx()) as resp:
                    data = json.loads(resp.read())
                models = [m["id"] for m in data.get("data", [])]
                self._llamacpp_ready.emit(models or [])
            except Exception:
                self._llamacpp_ready.emit(None)

        threading.Thread(target=_fetch, daemon=True).start()

    def _set_llamacpp_models(self, models: Optional[list[str]]) -> None:
        """Popola il combo con i modelli LlamaCPP disponibili (chiamato nel thread principale)."""
        if PROVIDERS.get(self._provider_combo.currentText(), {}).get("id") != "llamacpp":
            return
        self._model_combo.clear()
        if models is None:
            self._model_combo.addItem("⚠ llama-server non raggiungibile")
            self._model_combo.setEnabled(False)
            return
        self._model_combo.setEnabled(True)
        current = self._model_combo.currentText()
        for m in models:
            self._model_combo.addItem(m)
        idx = self._model_combo.findText(current)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)

    def _manual_refresh_models(self) -> None:
        """Bottone ↻ — forza il ricaricamento indipendentemente dal provider."""
        pid = PROVIDERS.get(self._provider_combo.currentText(), {}).get("id", "")
        if pid == "anthropic":
            self._refresh_anthropic_models()
        elif pid == "ollama":
            self._refresh_ollama_models()
        elif pid == "openai":
            self._refresh_openai_models()
        elif pid == "gemini":
            self._refresh_gemini_models()
        elif pid == "llamacpp":
            self._refresh_llamacpp_models()

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

    def _attach_file(self) -> None:
        """Apre un file dialog e allega i file scelti (da disco, non necessariamente
        aperti come tab), riconoscendo automaticamente il tipo: le immagini
        (PNG/JPEG/GIF/WEBP) vengono messe in coda per l'invio come vision,
        tutto il resto viene trattato come testo/codice e inserito nell'input."""
        dialog_title = tr("dialog.ai_attach_file", default="Allega file")
        paths, _ = QFileDialog.getOpenFileNames(self, dialog_title, "", "Tutti i file (*)")
        if not paths:
            return
        any_image = False
        for path_str in paths:
            path = Path(path_str)
            if path.suffix.lower() in _IMAGE_MEDIA_TYPES:
                self._attach_single_image(path)
                any_image = True
            else:
                self._attach_single_file(path)
        if any_image:
            self._update_pending_images_label()
        cursor = self._input.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._input.setTextCursor(cursor)
        self._input.setFocus()

    def _attach_single_file(self, path: Path) -> None:
        try:
            raw = path.read_bytes()
        except OSError as e:
            self._append_msg("system", f"⚠ Impossibile leggere {path.name}: {e}", "#ffcc00")
            return
        # Decodifica UTF-8 rigorosa: dati binari (immagini, video, PDF, eseguibili…)
        # falliscono quasi sempre, a differenza del solo controllo dei byte nulli
        # che alcuni formati binari (es. certi JPEG) possono eludere.
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            self._append_msg("system",
                f"⚠ {path.name} non è un file di testo — non allegato.\n"
                "Le immagini (PNG/JPEG/GIF/WEBP) sono riconosciute automaticamente; "
                "altri formati binari (video, PDF, eseguibili…) non sono supportati.",
                "#ffcc00")
            return
        truncated = len(text) > _ATTACH_MAX_CHARS
        if truncated:
            text = text[:_ATTACH_MAX_CHARS]
        lang = path.suffix.lstrip(".")
        self._input.insertPlainText(f"\n\nFile: {path.name}\n\n```{lang}\n{text}\n```\n")
        if truncated:
            self._append_msg("system",
                f"⚠ {path.name} troncato ai primi {_ATTACH_MAX_CHARS} caratteri.", "#ffcc00")

    def _attach_single_image(self, path: Path) -> None:
        media_type = _IMAGE_MEDIA_TYPES.get(path.suffix.lower())
        if not media_type:
            self._append_msg("system",
                f"⚠ {path.name}: formato non supportato (solo PNG/JPEG/GIF/WEBP).", "#ffcc00")
            return
        try:
            raw = path.read_bytes()
        except OSError as e:
            self._append_msg("system", f"⚠ Impossibile leggere {path.name}: {e}", "#ffcc00")
            return
        if len(raw) > _IMAGE_MAX_BYTES:
            self._append_msg("system",
                f"⚠ {path.name} troppo grande ({len(raw) // 1_000_000} MB, "
                f"limite {_IMAGE_MAX_BYTES // 1_000_000} MB) — non allegata.", "#ffcc00")
            return
        self._pending_images.append({
            "name":       path.name,
            "media_type": media_type,
            "data":       base64.b64encode(raw).decode("ascii"),
        })
        self._append_msg("system",
            f"🖼 {path.name} allegata ({len(raw) // 1024} KB) — verrà inviata con il prossimo messaggio "
            "(solo provider Anthropic/Gemini).", "#2ea043")

    def _clear_pending_images(self) -> None:
        self._pending_images.clear()
        self._update_pending_images_label()

    def _update_pending_images_label(self) -> None:
        n = len(self._pending_images)
        if n == 0:
            self._lbl_pending_images.setText("")
            self._lbl_pending_images.setToolTip("")
            self._btn_clear_images.hide()
        else:
            names = ", ".join(img["name"] for img in self._pending_images)
            self._lbl_pending_images.setText(f"🖼 {n} in coda")
            self._lbl_pending_images.setToolTip(names)
            self._btn_clear_images.show()

    def _show_more_actions(self) -> None:
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        for label, prompt in CONTEXT_ACTIONS[4:]:
            menu.addAction(tr(label), lambda p=prompt: self._context_action(p))
        menu.exec(self._btn_send.mapToGlobal(self._btn_send.rect().topLeft()))

    # ── Invio messaggi ────────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        dlg = _SettingsDialog(self)
        dlg.exec()
        # Dopo il salvataggio ricarica i modelli del provider corrente
        pid = PROVIDERS.get(self._provider_combo.currentText(), {}).get("id", "")
        if pid == "anthropic":
            self._refresh_anthropic_models()
        elif pid == "ollama":
            self._refresh_ollama_models()
        elif pid == "openai":
            self._refresh_openai_models()
        elif pid == "gemini":
            self._refresh_gemini_models()
        elif pid == "llamacpp":
            self._refresh_llamacpp_models()

    def _get_key(self, pid: str) -> str:
        from config.settings import Settings
        return Settings.instance().get(f"ai/{pid}_key", "")

    def _regenerate(self) -> None:
        """Rimuove l'ultima risposta AI e reinvia l'ultimo messaggio utente."""
        if not self._history:
            return
        # Rimuovi l'ultima risposta assistant
        if self._history and self._history[-1].get("role") == "assistant":
            self._history.pop()
        # Trova l'ultimo messaggio utente
        last_user = None
        for m in reversed(self._history):
            if m.get("role") == "user":
                last_user = m
                break
        if last_user is None:
            return
        # Ricostruisci la chat visiva
        self._rebuild_chat()
        text = last_user.get("content", "")
        self._input.setPlainText(text)
        # Reinvio
        self._send()

    def _show_diff(self) -> None:
        """Mostra un diff delle modifiche prima di applicarle al file."""
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        original = editor.text()
        if not self._last_text:
            return
        modified = self._last_text
        if original == modified:
            QMessageBox.information(self, "Diff", "Nessuna modifica rilevata.")
            return

        try:
            import tempfile
            original_path = Path(tempfile.mktemp(suffix=".original"))
            modified_path = Path(tempfile.mktemp(suffix=".modified"))
            original_path.write_text(original, encoding="utf-8")
            modified_path.write_text(modified, encoding="utf-8")

            from plugins.compare_merge_plugin import CompareMergePlugin
            # Apri il compare tool
            self._mw.open_files([original_path, modified_path])
            # Sovrascrivi il secondo file con la versione modificata
            modified_path.write_text(modified, encoding="utf-8")
            self._mw.open_files([original_path, modified_path])
        except ImportError:
            # Fallback semplice
            msg = QMessageBox(self)
            msg.setWindowTitle("Diff")
            msg.setText("Preview delle modifiche:\n\nFile originale → Nuova versione")
            msg.setDetailedText(f"--- ORIGINALE ---\n{original[:2000]}\n\n--- MODIFICATO ---\n{modified[:2000]}")
            msg.exec()

    def _handle_slash_command(self, text: str) -> Optional[str]:
        """Gestisce i comandi slash. Ritorna il prompt trasformato o None."""
        cmd = text.strip()
        editor = self._mw._tab_manager.current_editor()
        code = ""
        if editor:
            code = editor.selectedText() or editor.text()[:8000]
        lang = getattr(editor, '_current_language', '') or ''

        mapping = {
            "/explain": f"Spiega questo codice in modo chiaro e conciso, riga per riga se necessario:\n\n```{lang}\n{code}\n```",
            "/fix": f"Trova e correggi tutti i bug in questo codice. Mostra il codice corretto:\n\n```{lang}\n{code}\n```",
            "/refactor": f"Refactorizza questo codice migliorando leggibilità e manutenibilità senza cambiare il comportamento:\n\n```{lang}\n{code}\n```",
            "/doc": f"Scrivi una docstring completa per questo codice con parametri, return type ed esempi:\n\n```{lang}\n{code}\n```",
            "/test": f"Scrivi test unitari completi per questo codice usando pytest:\n\n```{lang}\n{code}\n```",
            "/review": f"Fai una code review professionale: sicurezza, performance, leggibilità, edge case:\n\n```{lang}\n{code}\n```",
            "/optimize": f"Ottimizza questo codice per performance e memoria, spiegando le modifiche:\n\n```{lang}\n{code}\n```",
            "/file": None,  # handled by attach
        }

        for prefix, prompt in mapping.items():
            if cmd.startswith(prefix):
                if prompt is None:
                    self._attach_file()
                    return ""
                return prompt

        return None

    def _update_token_estimate(self) -> None:
        """Aggiorna la stima token/costo nell'etichetta prima dell'invio."""
        text = self._input.toPlainText().strip()
        if not text:
            self._lbl_tokens.setText("")
            return
        chars = len(text)
        est_tokens = max(1, int(chars * 0.4))
        name = self._provider_combo.currentText()
        info = PROVIDERS.get(name, {})
        costs = MODEL_COST.get(self._model_combo.currentText(), (0, 0))
        if costs[1]:
            cost = est_tokens * costs[1] / 1_000_000
            self._lbl_tokens.setText(f"~{est_tokens} tok  ~${cost:.4f}")
        else:
            self._lbl_tokens.setText(f"~{est_tokens} tok")

    def _send(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            return
        # Slash command
        if text.startswith("/"):
            processed = self._handle_slash_command(text)
            if processed is not None:
                if processed:
                    self._input.setPlainText(processed)
                    self._send()
                return
            # Non riconosciuto — procedi come testo normale
            text = self._input.toPlainText().strip()
        if self._worker and self._worker.isRunning():
            return

        name      = self._provider_combo.currentText()
        info      = PROVIDERS.get(name, {})
        pid       = info.get("id", "")
        model     = self._model_combo.currentText()
        auth_type = info.get("auth_type", "api_key")

        from config.settings import Settings
        s = Settings.instance()

        if auth_type == "oauth":
            token = s.get(f"ai/{pid}_token", "")
            if not token:
                self._append_msg("system",
                    "⚠ Non autenticato — apri ⚙ e usa 'Accedi con JetBrains'.", "#ffcc00")
                return
            api_key    = ""   # _call_jetbrains() legge il token da Settings
            key_to_use = ""
        else:
            api_key = self._get_key(pid)
            if not api_key and pid != "ollama":
                self._append_msg("system",
                    "⚠ Chiave API mancante — apri ⚙ per configurarla.\n"
                    + _key_hint(pid), "#ffcc00")
                return
            warn = _validate_key(pid, api_key)
            if warn:
                self._append_msg("system", f"⚠ {warn}", "#ffcc00")
            key_to_use = "" if pid in ("ollama", "llamacpp") else api_key

        max_tokens   = int(s.get("ai/max_tokens", _DEFAULT_MAX_TOKENS))
        thinking     = self._chk_thinking.isChecked() and self._chk_thinking.isVisible()
        system       = self._system_edit.toPlainText().strip()
        ollama_url   = (api_key or "http://localhost:11434") if pid == "ollama" else "http://localhost:11434"
        llamacpp_url = (api_key or "http://localhost:8080")  if pid == "llamacpp" else "http://localhost:8080"

        if self._pending_images and pid not in _VISION_PROVIDERS:
            self._append_msg("system",
                f"⚠ Le immagini in coda non sono supportate dal provider '{name}' "
                "(solo Anthropic e Google Gemini). Cambia provider o rimuovile con «✕» prima di inviare.",
                "#ffcc00")
            return

        # Cattura selezione prima di inviare (usata da inline edit in _on_result)
        if self._chk_inline.isChecked():
            editor = self._mw._tab_manager.current_editor()
            if editor and editor.hasSelectedText():
                self._inline_selection = editor.getSelection()
            else:
                self._inline_selection = None  # None = intero file

        entry: dict = {"role": "user", "content": text}
        display_text = text
        if self._pending_images:
            entry["images"] = self._pending_images
            names = ", ".join(img["name"] for img in self._pending_images)
            display_text += f"\n\n🖼 Allegate: {names}"
        self._history.append(entry)
        self._append_msg("user", display_text)
        self._input.clear()
        self._pending_images = []
        self._update_pending_images_label()

        self._elapsed_start = time.time()
        self._has_thinking  = False
        self._has_streaming = False
        self._think_text_acc = ""
        self._speed_status   = ""
        self._gen_start      = 0.0
        self._gen_chars      = 0
        self._think_start    = 0.0
        self._think_chars    = 0
        # Stima tok/s live solo per i modelli locali (Ollama/llama.cpp), che a
        # fine risposta forniscono comunque il dato esatto via speed_ready.
        self._local_model    = pid in ("ollama", "llamacpp")
        self._elapsed_timer.start(1000)
        self._btn_send.setText("⏹ Ferma")
        self._streaming_block = False
        self._think_box.clear()
        self._think_box.hide()
        self._think_widget.hide()
        self._splitter.setSizes([sum(self._splitter.sizes()), 0])
        self._status.setToolTip("")
        self._status.setText(f"⟳ {model} sta elaborando… (0s)")

        self._worker = _AIWorker(pid, model, key_to_use, list(self._history),
                                  system, max_tokens, thinking, ollama_url, llamacpp_url)
        self._worker.stream_chunk.connect(self._on_stream_chunk)
        self._worker.think_chunk.connect(self._on_think_chunk)
        self._worker.result_ready.connect(self._on_result)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.usage_ready.connect(self._on_usage)
        self._worker.speed_ready.connect(self._on_speed)
        self._worker.start()

    def _on_stream_chunk(self, chunk: str) -> None:
        self._has_streaming = True
        # Inizio della generazione vera (primo chunk di sola risposta): da qui
        # parte il conteggio per la stima tok/s live (i pensieri sono esclusi
        # perché arrivano su _on_think_chunk).
        if self._gen_start == 0.0:
            self._gen_start = time.time()
        self._gen_chars += len(chunk)
        cursor = self._chat_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        if not self._streaming_block:
            # Intestazione della bolla AI in grassetto (testo grezzo durante lo
            # streaming; alla fine la chat viene ricostruita con Markdown).
            self._stream_acc = ""
            cursor.insertBlock()
            lbl = QTextCharFormat()
            lbl.setForeground(QColor(self._pal["ai_hdr"]))
            lbl.setFontWeight(700)
            header = self._model_combo.currentText() or "AI"
            cursor.insertText(header + "\n", lbl)
            self._streaming_block = True

        # Testo plain — preserva spazi e a capo senza collasso HTML
        self._stream_acc += chunk
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self._pal["base_fg"]))
        cursor.insertText(chunk, fmt)
        self._chat_view.setTextCursor(cursor)
        self._chat_view.ensureCursorVisible()

    def _rebuild_chat(self) -> None:
        """Ricostruisce l'intera vista chat dallo storico, con Markdown per l'AI."""
        self._chat_view.clear()
        for m in self._history:
            role = m.get("role", "")
            if role not in ("user", "assistant"):
                continue
            self._append_msg(role, str(m.get("content", "")))

    def _on_result(self, text: str) -> None:
        self._history.append({"role": "assistant", "content": text})
        # Sia in streaming (testo grezzo già mostrato) sia senza streaming,
        # ricostruiamo la chat per ottenere il rendering Markdown delle risposte.
        self._streaming_block = False
        self._rebuild_chat()
        self._elapsed_timer.stop()
        self._btn_send.setText("▶ Invia")
        self._btn_apply.setEnabled(True)
        self._btn_diff.setEnabled(True)
        self._btn_new_tab.setEnabled(True)
        self._btn_regenerate.setEnabled(True)
        self._last_text = text
        # Per i modelli locali _on_speed ha già scritto i tok/s: non sovrascriverli.
        self._status.setText(self._speed_status)
        if self._think_text_acc:
            self._status.setToolTip(self._think_text_acc[-500:].strip())
            self._status.setToolTipDuration(15000)
            # Finito il ragionamento: collassa il pannello Pensieri restituendo
            # spazio alla chat, ma lascia il pulsante "▶ Pensieri" per riaprirlo.
            self._collapse_think()

        if self._chk_inline.isChecked():
            self._apply_inline(text)

    def _on_error(self, msg: str) -> None:
        self._append_msg("system", f"\u274c Errore: {msg}")
        self._elapsed_timer.stop()
        self._btn_send.setText("\u25b6 Invia")
        self._btn_regenerate.setEnabled(True)
        self._status.setText("")
        self._streaming_block = False
        self._inline_selection = None
        if self._history and self._history[-1]["role"] == "user":
            self._history.pop()

    def _on_send_btn(self) -> None:
        if self._worker and self._worker.isRunning():
            self._stop_generation()
        else:
            self._send()

    def _stop_generation(self) -> None:
        if self._worker:
            self._worker.stop()
            try:
                self._worker.stream_chunk.disconnect()
                self._worker.think_chunk.disconnect()
                self._worker.result_ready.disconnect()
                self._worker.error_occurred.disconnect()
                self._worker.usage_ready.disconnect()
                self._worker.speed_ready.disconnect()
            except Exception:
                pass
            # Tieni il worker vivo finché il thread non termina (stesso pattern di PreviewPanel).
            # Impostare self._worker = None direttamente può distruggere il QThread mentre
            # è ancora in esecuzione → SIGABRT "QThread: Destroyed while thread is still running".
            w = self._worker
            self._old_workers.append(w)
            w.finished.connect(lambda: self._old_workers.remove(w) if w in self._old_workers else None)
            self._worker = None
        self._elapsed_timer.stop()
        self._btn_send.setText("▶ Invia")
        self._status.setText("⏹ Generazione interrotta")
        self._streaming_block = False

    def _tick_elapsed(self) -> None:
        elapsed = int(time.time() - self._elapsed_start)
        model   = self._model_combo.currentText()
        if self._has_thinking and not self._has_streaming:
            # tok/s live anche durante il ragionamento (stima sui caratteri dei pensieri).
            self._status.setText(f"💭 {model} sta ragionando… ({elapsed}s)"
                                 f"{self._live_speed_suffix(self._think_start, self._think_chars)}")
        elif self._has_streaming:
            self._status.setText(f"⟳ {model} sta generando… ({elapsed}s)"
                                 f"{self._live_speed_suffix(self._gen_start, self._gen_chars)}")
        else:
            self._status.setText(f"⟳ {model} sta elaborando… ({elapsed}s)")

    def _live_speed_suffix(self, start: float, chars: int) -> str:
        """Stima live dei tok/s per i modelli locali, da mostrare durante le fasi
        di ragionamento e generazione. È una stima (≈ 4 caratteri per token)
        finché non arriva il dato esatto da Ollama/llama.cpp a fine risposta
        (_on_speed). `start` e `chars` sono l'istante d'inizio e i caratteri
        prodotti nella fase corrente (pensieri o risposta).
        """
        if not self._local_model or start == 0.0 or not chars:
            return ""
        dt = time.time() - start
        if dt < 0.5:
            return ""
        est_tok = chars / 4.0   # ~4 char/token, euristica robusta
        tps = est_tok / dt
        return f" · ~{tps:.1f} tok/s"

    def _on_usage(self, in_tok: int, out_tok: int) -> None:
        model = self._model_combo.currentText()
        if model in MODEL_COST:
            inp_cost, out_cost = MODEL_COST[model]
            cost = (in_tok / 1_000_000) * inp_cost + (out_tok / 1_000_000) * out_cost
            cost_str = f" · ~${cost:.4f}"
        else:
            cost_str = ""
        self._status.setText(f"↑{in_tok} tok  ↓{out_tok} tok{cost_str}")

    def _on_speed(self, tok_per_sec: float, out_tok: int) -> None:
        """Mostra la velocità di generazione (tok/s) dei modelli locali.

        Ollama e llama.cpp non emettono `usage_ready`, quindi questo slot
        compone direttamente la riga di stato con i token generati e i tok/s.
        """
        if out_tok:
            self._speed_status = f"↓{out_tok} tok · {tok_per_sec:.1f} tok/s"
        else:
            self._speed_status = f"{tok_per_sec:.1f} tok/s"
        self._status.setText(self._speed_status)

    def _on_think_chunk(self, chunk: str) -> None:
        self._has_thinking = True
        # Inizio del ragionamento (primo chunk di pensiero): da qui parte il
        # conteggio per la stima tok/s live durante la fase "sta ragionando…".
        if self._think_start == 0.0:
            self._think_start = time.time()
        self._think_chars += len(chunk)
        self._think_text_acc += chunk
        if not self._think_widget.isVisible():
            self._think_widget.show()
        # Durante il ragionamento mostra il box espanso (il pulsante resta
        # sempre visibile come barra del pane Pensieri).
        if not self._think_box.isVisible():
            self._expand_think()
        cursor = self._think_box.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._think_box.setTextCursor(cursor)
        self._think_box.insertPlainText(chunk)
        self._think_box.ensureCursorVisible()
        # tooltip sulla status label
        self._status.setToolTip(self._think_text_acc[-500:].strip())
        self._status.setToolTipDuration(8000)

    def _expand_think(self) -> None:
        """Mostra il box dei pensieri espanso (pane ~30%, resto alla chat)."""
        self._think_box.show()
        self._think_btn.blockSignals(True)
        self._think_btn.setChecked(True)
        self._think_btn.setText("▼ Pensieri")
        self._think_btn.blockSignals(False)
        # Usa l'altezza effettiva dello splitter (più affidabile della somma dei
        # sizes correnti, che subito dopo show() può essere ancora [tutto, 0]).
        total = self._splitter.height() or (sum(self._splitter.sizes()) or 400)
        think_h = max(120, total // 3)
        chat_h  = max(80, total - think_h)
        self._splitter.setSizes([chat_h, think_h])

    def _collapse_think(self) -> None:
        """Riduce il pannello Pensieri al solo pulsante, restituendo lo spazio
        alla chat. La barra "▶ Pensieri" resta visibile per riespandere il box
        in qualsiasi momento dopo la risposta.
        """
        self._think_box.hide()
        self._think_btn.blockSignals(True)
        self._think_btn.setChecked(False)
        self._think_btn.setText("▶ Pensieri")
        self._think_btn.blockSignals(False)
        # Pane ridotto all'altezza del solo pulsante; tutto il resto alla chat.
        sizes = self._splitter.sizes()
        total = sum(sizes)
        bar_h = self._think_btn.height() or 24
        self._splitter.setSizes([max(80, total - bar_h), bar_h])

    def _toggle_think(self, checked: bool) -> None:
        if checked:
            self._expand_think()
        else:
            self._collapse_think()

    def _bubble_html(self, role: str, body_html: str, accent: str = "") -> str:
        """Costruisce l'HTML di una bolla messaggio coerente col tema corrente."""
        pal = self._pal
        body_fg = pal["base_fg"]
        if role == "user":
            bg, hdr_fg = pal["user_bg"], pal["user_hdr"]
            header = tr("label.ai_role_user")
        elif role == "assistant":
            bg, hdr_fg = pal["ai_bg"], pal["ai_hdr"]
            header = self._model_combo.currentText() or "AI"
        else:  # system / warning / error
            bg = pal["base_bg"]
            hdr_fg = accent or pal["error_fg"]
            body_fg = accent or pal["error_fg"]
            header = ""

        hdr_html = (
            f'<div style="color:{hdr_fg}; font-weight:bold; font-size:11px; '
            f'margin-bottom:2px;">{_escape(header)}</div>' if header else ""
        )
        # Tabella usata come contenitore: QTextEdit renderizza in modo affidabile
        # background+padding sulle celle di tabella (i <div> con background non
        # sempre rispettano padding/border-radius nel motore Qt).
        return (
            f'<table width="100%" cellspacing="0" cellpadding="8" '
            f'style="margin:4px 0;"><tr>'
            f'<td style="background:{bg}; border:1px solid {pal["border"]};">'
            f'{hdr_html}'
            f'<div style="color:{body_fg};">{body_html}</div>'
            f'</td></tr></table>'
        )

    def _append_msg(self, role: str, text: str, color: str = "") -> None:
        if role == "assistant":
            body = _render_markdown_to_html(text, self._pal)
        else:
            body = f'<span style="white-space:pre-wrap">{_escape(text)}</span>'
        self._chat_view.append(self._bubble_html(role, body, accent=color))
        self._chat_view.ensureCursorVisible()

    def _clear(self) -> None:
        self._history.clear()
        self._chat_view.clear()
        self._elapsed_timer.stop()
        self._btn_send.setText("▶ Invia")
        self._status.setText("")
        self._streaming_block = False
        self._btn_apply.setEnabled(False)
        self._btn_new_tab.setEnabled(False)
        self._think_btn.blockSignals(True)
        self._think_btn.setChecked(False)
        self._think_btn.setText("▶ Pensieri")
        self._think_btn.blockSignals(False)
        self._think_box.hide()
        self._think_box.clear()
        self._think_widget.hide()
        self._splitter.setSizes([sum(self._splitter.sizes()), 0])

    # ── Inline edit / Applica / Nuovo tab ─────────────────────────────────────

    def _on_inline_toggled(self, checked: bool) -> None:
        if checked:
            self._status.setText("⚡ Inline edit attivo — la risposta sovrascriverà l'editor")
        else:
            self._status.setText("")
            self._inline_selection = None

    def _apply_inline(self, text: str) -> None:
        """Sostituisce la selezione salvata (o l'intero file) con la risposta AI."""
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            self._inline_selection = None
            return
        extracted = _extract_code_block(text)
        sel = self._inline_selection
        self._inline_selection = None
        if sel is not None:
            lf, cf, lt, ct = sel
            editor.setSelection(lf, cf, lt, ct)
            editor.replaceSelectedText(extracted)
        else:
            editor.selectAll()
            editor.replaceSelectedText(extracted)

    def _apply_to_file(self) -> None:
        """Sostituisce il contenuto dell'editor attivo con l'ultima risposta AI."""
        last = next((m["content"] for m in reversed(self._history) if m["role"] == "assistant"), None)
        if not last:
            return
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        extracted = _extract_code_block(last)
        editor.selectAll()
        editor.replaceSelectedText(extracted)

    def _open_in_new_tab(self) -> None:
        """Apre l'ultima risposta AI in un nuovo tab vuoto."""
        last = next((m["content"] for m in reversed(self._history) if m["role"] == "assistant"), None)
        if not last:
            return
        new_editor = self._mw._tab_manager.new_tab()
        new_editor.load_content(last)


def _settings_key(pid: str) -> str:
    """Restituisce la chiave QSettings per il token/API key del provider."""
    info = next((v for v in PROVIDERS.values() if v["id"] == pid), {})
    if info.get("auth_type") == "oauth":
        return f"ai/{pid}_token"
    return f"ai/{pid}_key"


def _key_hint(pid: str) -> str:
    return {
        "anthropic": "Chiave Anthropic: console.anthropic.com/settings/keys  (formato: sk-ant-...)",
        "openai":    "Chiave OpenAI: platform.openai.com/api-keys  (formato: sk-...)",
        "gemini":    "Chiave Gemini: aistudio.google.com/app/apikey  (formato: AIza...)",
        "deepseek":  "Chiave DeepSeek: platform.deepseek.com/api_keys  (formato: sk-...)",
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
    if pid == "deepseek" and not key.startswith("sk-"):
        return "La chiave DeepSeek sembra incorretta: deve iniziare con 'sk-'."
    return ""


def _escape(text: str) -> str:
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>"))


def _extract_code_block(text: str) -> str:
    """Se la risposta contiene esattamente un blocco ```...```, lo restituisce; altrimenti il testo intero."""
    matches = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
    if len(matches) == 1:
        return matches[0].rstrip("\n")
    return text


def _chat_palette() -> dict:
    """Restituisce i colori del tema attivo usati per le bolle della chat.

    Legge la palette dal ThemeManager corrente in modo che il pannello AI resti
    leggibile con tutti i 40+ temi (chiari e scuri), invece di usare colori
    hardcoded. Tutti i valori hanno un fallback sensato.
    """
    try:
        from config.themes import ThemeManager
        tm    = ThemeManager.instance()
        theme = tm.get_theme(tm._active_name) or {}
        ui     = theme.get("ui", {}) or {}
        tokens = theme.get("tokens", {}) or {}
        is_dark = bool(theme.get("meta", {}).get("dark", True))
    except Exception:
        ui, tokens, is_dark = {}, {}, True

    def _tok(name: str, default: str) -> str:
        v = tokens.get(name, {})
        return (v.get("fg") if isinstance(v, dict) else None) or default

    base_bg = ui.get("editor_bg") or ("#1e1e1e" if is_dark else "#ffffff")
    base_fg = ui.get("editor_fg") or ("#d4d4d4" if is_dark else "#1e1e1e")

    if is_dark:
        user_bg = "#2a3f54"   # blu-grigio per l'utente
        ai_bg   = "#2a2d2e"   # grigio neutro per l'AI
        code_bg = "#1a1a1a"
        border  = "#3c3c3c"
    else:
        user_bg = "#dbeafe"   # azzurro chiaro per l'utente
        ai_bg   = "#f1f3f5"   # grigio chiarissimo per l'AI
        code_bg = "#f5f5f5"
        border  = "#d0d0d0"

    return {
        "is_dark":   is_dark,
        "base_bg":   base_bg,
        "base_fg":   base_fg,
        "user_bg":   user_bg,
        "user_hdr":  _tok("identifier", "#4fa3e0"),
        "ai_bg":     ai_bg,
        "ai_hdr":    _tok("function", "#7bb86f"),
        "code_bg":   code_bg,
        "border":    border,
        "error_fg":  _tok("error", "#f44747"),
        "muted_fg":  ui.get("margin_fg") or "#858585",
    }


# python-markdown opzionale (riuso della stessa libreria di ui/preview_panel.py)
try:
    import markdown as _md_lib
    _HAS_MD = True
except Exception:
    _md_lib = None
    _HAS_MD = False


def _render_markdown_to_html(text: str, pal: dict) -> str:
    """Converte il Markdown della risposta AI in HTML formattato.

    Se python-markdown non è installato, esegue un fallback che almeno mostra i
    blocchi di codice ``` in <pre> e preserva gli a capo. I blocchi/inline code
    ricevono uno sfondo coerente col tema.
    """
    if _HAS_MD:
        try:
            body = _md_lib.markdown(
                text,
                extensions=["tables", "fenced_code", "sane_lists", "nl2br"],
            )
        except Exception:
            body = "<p>" + _escape(text) + "</p>"
    else:
        # Fallback senza libreria: estrai i blocchi ``` e fai escape del resto.
        parts = re.split(r"```(?:\w+)?\n(.*?)```", text, flags=re.DOTALL)
        chunks = []
        for i, part in enumerate(parts):
            if i % 2 == 1:
                chunks.append(
                    f'<pre><code>{_html_escape(part)}</code></pre>'
                )
            elif part:
                chunks.append("<p>" + _escape(part) + "</p>")
        body = "".join(chunks) or ("<p>" + _escape(text) + "</p>")

    # Styling inline dei blocchi/inline code (QTextEdit non applica fogli di stile
    # esterni in modo affidabile, quindi gli stili vanno inline).
    code_bg = pal["code_bg"]
    body = body.replace(
        "<pre>",
        f'<pre style="background:{code_bg}; padding:6px 8px; '
        f'border-radius:4px; font-family:Monospace; white-space:pre-wrap;">',
    )
    body = body.replace(
        "<code>",
        f'<code style="background:{code_bg}; border-radius:3px; '
        f'padding:0 3px; font-family:Monospace;">',
    )
    return body


def _html_escape(text: str) -> str:
    import html as _html
    return _html.escape(text)


# ─── Plugin principale ────────────────────────────────────────────────────────

class AIAssistantPlugin(BasePlugin):
    NAME        = "AI Assistant"
    VERSION     = "1.1"
    DESCRIPTION = "Chat AI: Anthropic Claude (streaming + Extended Thinking), OpenAI, Gemini, Ollama, LlamaCPP"
    AUTHOR      = "NotePadPQ Team"

    def on_load(self, main_window: "MainWindow") -> None:
        super().on_load(main_window)
        self._panel = _AIPanel(main_window)
        self._dock  = QDockWidget("AI Assistant", main_window)
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
        self.add_menu_action(main_window, "plugins", "AI Assistant", self._toggle, "Ctrl+Alt+A", icon_key="plugin_ai")

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
        ai_menu = menu.addMenu(tr("action.context_ai"))
        ai_menu.addAction(tr("action.context_ai_ask_file"), self._panel._ask_about_file)
        ai_menu.addAction(tr("action.context_ai_ask_sel"),  self._panel._ask_about_selection)
        ai_menu.addSeparator()
        for label, prompt in CONTEXT_ACTIONS[:5]:
            ai_menu.addAction(tr(label), lambda p=prompt: self._run_and_show(p))

    def _run_and_show(self, prompt: str) -> None:
        self._dock.show()
        self._panel._context_action(prompt)

    def on_unload(self) -> None:
        self._dock.close()
        self._dock.deleteLater()
        super().on_unload()

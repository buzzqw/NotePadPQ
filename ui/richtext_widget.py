"""
ui/richtext_widget.py — Editor Rich Text (Jodit + QWebEngineView)
NotePadPQ

Editor WYSIWYG completo basato su Jodit (https://jodit-editor.com),
incorporato in QWebEngineView con comunicazione bidirezionale via QWebChannel.

Formati supportati:
  Lettura : .docx (mammoth), .odt/.rtf (pandoc), .html/.htm (nativo)
  Scrittura: .html (nativo), .docx (htmldocx/python-docx), .pdf (Qt print),
             .odt/.rtf (pandoc)

Dipendenze opzionali (degradano gracefully):
  PyQt6-WebEngine  — obbligatoria per il widget
  mammoth          — lettura DOCX
  htmldocx         — scrittura DOCX
  python-docx      — fallback scrittura DOCX
  pypandoc         — ODT/RTF conversione
"""
from __future__ import annotations

import json
import tempfile
import shutil
import urllib.request
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import (
    Qt, QObject, QTimer, QEventLoop, QUrl, pyqtSignal, pyqtSlot
)
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QToolBar, QToolButton,
    QComboBox, QLabel, QFileDialog, QMessageBox, QProgressDialog,
    QApplication, QSizePolicy
)

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import (
        QWebEngineSettings, QWebEngineScript, QWebEnginePage
    )
    from PyQt6.QtWebChannel import QWebChannel
    WEBENGINE_OK = True
except ImportError:
    WEBENGINE_OK = False

from i18n.i18n import tr

# ── Asset Jodit ───────────────────────────────────────────────────────────────

_ASSETS_DIR = Path(__file__).parent / "assets" / "jodit"

# Jodit 4 — MIT licence, no dependencies, single-file distribution
# URL senza versione: jsdelivr risolve sempre all'ultima stabile
_JODIT_JS_URL  = "https://cdn.jsdelivr.net/npm/jodit/es2021/jodit.min.js"
_JODIT_CSS_URL = "https://cdn.jsdelivr.net/npm/jodit/es2021/jodit.min.css"

_JODIT_JS  = _ASSETS_DIR / "jodit.min.js"
_JODIT_CSS = _ASSETS_DIR / "jodit.min.css"


def _download_jodit(parent: Optional[QWidget] = None) -> bool:
    """Scarica i file Jodit nella cache. Ritorna True se tutto ok."""
    _ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    dlg = QProgressDialog(
        tr("richtext.downloading_jodit"),
        tr("button.cancel"),
        0, 100, parent
    )
    dlg.setWindowTitle("NotePadPQ")
    dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
    dlg.setMinimumDuration(0)
    dlg.setValue(0)
    dlg.show()
    QApplication.processEvents()

    files = [(_JODIT_JS_URL, _JODIT_JS), (_JODIT_CSS_URL, _JODIT_CSS)]
    try:
        for i, (url, dest) in enumerate(files):
            if dlg.wasCanceled():
                return False
            dlg.setLabelText(f"Download {dest.name}…")
            dlg.setValue(i * 45)
            QApplication.processEvents()

            # Scarica con progress reale; gestisce redirect automaticamente
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "NotePadPQ/1.0 (richtext downloader)"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 32768
                with open(dest, "wb") as f:
                    while True:
                        if dlg.wasCanceled():
                            dest.unlink(missing_ok=True)
                            return False
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = i * 45 + int(downloaded / total * 45)
                            dlg.setValue(pct)
                            QApplication.processEvents()

            dlg.setValue(i * 45 + 45)
            QApplication.processEvents()

        dlg.setValue(100)
        return True
    except Exception as exc:
        dlg.close()
        for _, dest in files:
            dest.unlink(missing_ok=True)
        QMessageBox.critical(
            parent, "NotePadPQ",
            tr("richtext.download_failed", exc=exc)
        )
        return False


def ensure_jodit(parent: Optional[QWidget] = None) -> bool:
    """Verifica/scarica gli asset Jodit. Ritorna True se pronti."""
    if _JODIT_JS.exists() and _JODIT_CSS.exists():
        return True
    return _download_jodit(parent)


# ── Conversione formati ───────────────────────────────────────────────────────

class RichTextIO:
    """Conversione bidirezionale tra HTML interno e formati file."""

    @staticmethod
    def load_html(path: Path) -> tuple[str, str]:
        """Legge un file e ritorna (html_content, error_message)."""
        ext = path.suffix.lower()

        if ext in (".html", ".htm"):
            try:
                return path.read_text(encoding="utf-8", errors="replace"), ""
            except Exception as e:
                return "", str(e)

        if ext == ".docx":
            return RichTextIO._docx_to_html(path)

        if ext in (".odt", ".rtf"):
            return RichTextIO._pandoc_to_html(path)

        try:
            return path.read_text(encoding="utf-8", errors="replace"), ""
        except Exception as e:
            return "", str(e)

    @staticmethod
    def _docx_to_html(path: Path) -> tuple[str, str]:
        try:
            import mammoth
            with open(path, "rb") as f:
                result = mammoth.convert_to_html(f)
            html = result.value
            if result.messages:
                # Log warnings but don't fail
                pass
            return html, ""
        except ImportError:
            return RichTextIO._pandoc_to_html(path)
        except Exception as e:
            return "", str(e)

    @staticmethod
    def _pandoc_to_html(path: Path) -> tuple[str, str]:
        try:
            import pypandoc
            html = pypandoc.convert_file(str(path), "html", extra_args=["--self-contained"])
            return html, ""
        except ImportError:
            pass
        # Fallback: pandoc subprocess
        import subprocess
        try:
            result = subprocess.run(
                ["pandoc", "-f", path.suffix.lstrip("."), "-t", "html", str(path)],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return result.stdout, ""
            return "", result.stderr
        except FileNotFoundError:
            return "", tr("richtext.pandoc_missing")
        except Exception as e:
            return "", str(e)

    @staticmethod
    def save_html(html: str, path: Path) -> str:
        """Salva HTML nel formato del file. Ritorna stringa errore o ''."""
        ext = path.suffix.lower()

        if ext in (".html", ".htm"):
            try:
                path.write_text(RichTextIO._full_html(html), encoding="utf-8")
                return ""
            except Exception as e:
                return str(e)

        if ext == ".docx":
            return RichTextIO._html_to_docx(html, path)

        if ext in (".odt", ".rtf"):
            return RichTextIO._html_to_pandoc(html, path)

        try:
            path.write_text(html, encoding="utf-8")
            return ""
        except Exception as e:
            return str(e)

    @staticmethod
    def _html_to_docx(html: str, path: Path) -> str:
        # Preferisce htmldocx, fallback python-docx + BeautifulSoup
        try:
            from htmldocx import HtmlToDocx
            parser = HtmlToDocx()
            doc = parser.parse_html_string(html)
            doc.save(str(path))
            return ""
        except ImportError:
            pass
        try:
            from docx import Document
            doc = Document()
            # Inserisce il testo come plain text (degraded)
            from html.parser import HTMLParser

            class _TextExtractor(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.text = []
                def handle_data(self, data):
                    self.text.append(data)

            ex = _TextExtractor()
            ex.feed(html)
            for chunk in " ".join(ex.text).split("\n"):
                if chunk.strip():
                    doc.add_paragraph(chunk.strip())
            doc.save(str(path))
            return ""
        except ImportError:
            return tr("richtext.docx_lib_missing")
        except Exception as e:
            return str(e)

    @staticmethod
    def _html_to_pandoc(html: str, path: Path) -> str:
        import subprocess
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w",
                                         encoding="utf-8") as f:
            f.write(RichTextIO._full_html(html))
            tmp = f.name
        try:
            fmt = path.suffix.lstrip(".")
            result = subprocess.run(
                ["pandoc", "-f", "html", "-t", fmt, tmp, "-o", str(path)],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                return result.stderr
            return ""
        except FileNotFoundError:
            return tr("richtext.pandoc_missing")
        except Exception as e:
            return str(e)
        finally:
            Path(tmp).unlink(missing_ok=True)

    @staticmethod
    def _full_html(body: str) -> str:
        return (
            "<!DOCTYPE html><html><head>"
            '<meta charset="utf-8">'
            "<style>body{font-family:serif;font-size:12pt;line-height:1.5;"
            "max-width:860px;margin:40px auto;padding:0 20px}</style>"
            f"</head><body>{body}</body></html>"
        )


# ── QWebChannel bridge ────────────────────────────────────────────────────────

class _EditorBridge(QObject):
    """Oggetto esposto a JavaScript via QWebChannel."""

    content_changed = pyqtSignal()
    js_ready        = pyqtSignal()

    def __init__(self, widget: "RichTextWidget"):
        super().__init__()
        self._widget = widget

    @pyqtSlot()
    def ready(self):
        """Chiamato da JS quando Jodit è inizializzato."""
        self.js_ready.emit()

    @pyqtSlot()
    def contentChanged(self):
        """Chiamato da JS ad ogni modifica dell'utente."""
        self._widget._set_modified(True)
        self.content_changed.emit()

    @pyqtSlot(str)
    def log(self, msg: str):
        pass  # debug hook


# ── Template HTML ─────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="jodit.min.css">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ height:100%; background:#f0f0f0; }}
  .jodit-container {{ height:100% !important; }}
  .jodit-wysiwyg {{ min-height:calc(100vh - 80px) !important; }}
  #editor {{ width:100%; height:100%; }}
</style>
</head>
<body>
<textarea id="editor"></textarea>
<script src="qwebchannel.js"></script>
<script src="jodit.min.js"></script>
<script>
"use strict";

var bridge  = null;
var jodit   = null;
var _pendingContent = null;
var _changing = false;

// ── Jodit config ──────────────────────────────────────────────────────────────
var JODIT_CONFIG = {{
  height: "100%",
  minHeight: 400,
  autofocus: false,
  spellcheck: true,
  language: "{lang}",
  toolbarAdaptive: false,
  toolbarSticky: true,
  showCharsCounter: false,
  showWordsCounter: true,
  showXPathInStatusbar: false,
  allowResizeY: false,
  iframe: false,
  useAceEditor: false,
  uploader: {{ insertImageAsBase64URI: true }},
  buttons: [
    "bold","italic","underline","strikethrough","eraser","|",
    "superscript","subscript","|",
    "ul","ol","|",
    "outdent","indent","|",
    "font","fontsize","paragraph","brush","|",
    "align","|",
    "table","image","link","|",
    "undo","redo","|",
    "hr","copyformat","|",
    "find","|",
    "source","fullsize","print"
  ],
  extraButtons: [],
  controls: {{
    paragraph: {{
      list: {{
        p:  "Normale",
        h1: "Titolo 1",
        h2: "Titolo 2",
        h3: "Titolo 3",
        h4: "Titolo 4",
        blockquote: "Citazione",
        pre: "Codice"
      }}
    }}
  }}
}};

// ── Funzioni esposte a Python ─────────────────────────────────────────────────
window.setContent = function(html) {{
  if (jodit) {{
    jodit.value = html;
    jodit.history.clear();
  }} else {{
    _pendingContent = html;
  }}
}};

window.getContent = function() {{
  return jodit ? jodit.value : "";
}};

window.setReadOnly = function(ro) {{
  if (jodit) jodit.setReadOnly(ro);
}};

window.execCommand = function(cmd, val) {{
  if (jodit) jodit.execCommand(cmd, false, val || "");
}};

// ── Inizializzazione ──────────────────────────────────────────────────────────
new QWebChannel(qt.webChannelTransport, function(channel) {{
  bridge = channel.objects.bridge;

  jodit = Jodit.make("#editor", JODIT_CONFIG);

  if (_pendingContent !== null) {{
    jodit.value = _pendingContent;
    jodit.history.clear();
    _pendingContent = null;
  }}

  jodit.events.on("change", function() {{
    if (!_changing && bridge) bridge.contentChanged();
  }});

  bridge.ready();
}});
</script>
</body>
</html>
"""


# ── Widget principale ─────────────────────────────────────────────────────────

_SAVE_FILTER = (
    "Documento Word (*.docx);;"
    "HTML (*.html *.htm);;"
    "PDF (*.pdf);;"
    "OpenDocument Text (*.odt);;"
    "RTF (*.rtf);;"
    "Tutti i file (*)"
)


class RichTextWidget(QWidget):
    """
    Tab widget per l'editor rich text WYSIWYG.
    Implementa l'interfaccia attesa da TabManager.add_spreadsheet_tab:
      - file_path      : Path | None
      - modified_changed signal
      - is_modified()
      - save()
    """

    modified_changed = pyqtSignal(bool)
    convert_to_text  = pyqtSignal(str, str)   # (content, suggested_name)

    def __init__(self, path: Optional[Path] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.file_path: Optional[Path] = path
        self._modified   = False
        self._js_ready   = False
        self._pending_html: Optional[str] = None
        self._tmpdir: Optional[Path] = None

        self._build_ui()
        self._load_jodit_page()

    # ── Costruzione UI ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar superiore
        self._toolbar = self._make_toolbar()
        layout.addWidget(self._toolbar)

        if not WEBENGINE_OK:
            lbl = QLabel(
                "⚠ PyQt6-WebEngine non installato.\n"
                "pip install PyQt6-WebEngine"
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)
            return

        # WebEngineView
        self._view = QWebEngineView(self)
        self._view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        # Abilita Javascript e accesso file locali
        settings = self._view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        layout.addWidget(self._view)

        # Status bar
        self._statusbar = self._make_statusbar()
        layout.addWidget(self._statusbar)

        # Shortcut salvataggio
        QShortcut(QKeySequence("Ctrl+S"), self, self.save)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, self.save_as)

    def _make_toolbar(self) -> QWidget:
        bar = QToolBar(self)
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setIconSize(__import__("PyQt6.QtCore", fromlist=["QSize"]).QSize(18, 18))

        def btn(text: str, tip: str, slot) -> QToolButton:
            b = QToolButton(bar)
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            bar.addWidget(b)
            return b

        btn("💾 " + tr("action.save"),
            tr("action.save") + "  Ctrl+S",
            self.save)
        btn("📁 " + tr("richtext.save_as"),
            tr("richtext.save_as") + "  Ctrl+Shift+S",
            self.save_as)
        bar.addSeparator()
        btn("📄 " + tr("richtext.export_pdf"),
            tr("richtext.export_pdf"),
            self._export_pdf)
        bar.addSeparator()
        btn("✎ " + tr("richtext.open_as_text"),
            tr("richtext.open_as_text"),
            self._open_as_text)

        # Word count label a destra
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        self._wc_label = QLabel("", bar)
        self._wc_label.setStyleSheet("padding: 0 8px; color: gray;")
        bar.addWidget(self._wc_label)

        return bar

    def _make_statusbar(self) -> QWidget:
        w = QWidget(self)
        w.setFixedHeight(22)
        w.setStyleSheet(
            "QWidget { background: palette(window); border-top: 1px solid palette(mid); }"
            "QLabel  { padding: 0 6px; color: gray; font-size: 11px; }"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self._status_lbl = QLabel("", w)
        h.addWidget(self._status_lbl)
        h.addStretch()
        self._mod_lbl = QLabel("", w)
        h.addWidget(self._mod_lbl)
        return w

    # ── Caricamento pagina Jodit ──────────────────────────────────────────────

    def _load_jodit_page(self) -> None:
        if not WEBENGINE_OK:
            return

        # Crea tmpdir con gli asset di Jodit
        self._tmpdir = Path(tempfile.mkdtemp(prefix="npq_rt_"))
        js_src  = _JODIT_JS
        css_src = _JODIT_CSS

        if not (js_src.exists() and css_src.exists()):
            self._status_lbl.setText(tr("richtext.jodit_not_ready"))
            return

        shutil.copy(js_src,  self._tmpdir / "jodit.min.js")
        shutil.copy(css_src, self._tmpdir / "jodit.min.css")

        # Ottieni qwebchannel.js dal sistema Qt
        qwc_js = self._get_qwebchannel_js()
        (self._tmpdir / "qwebchannel.js").write_text(qwc_js, encoding="utf-8")

        # Genera la pagina HTML
        from i18n.i18n import I18n
        lang = I18n.instance().current_language() if hasattr(I18n.instance(), "current_language") else "it"
        jodit_lang = {"it": "it", "en": "en", "de": "de", "fr": "fr", "es": "es"}.get(lang, "en")

        html_content = _HTML_TEMPLATE.format(lang=jodit_lang)
        html_path = self._tmpdir / "editor.html"
        html_path.write_text(html_content, encoding="utf-8")

        # Configura QWebChannel
        self._bridge  = _EditorBridge(self)
        self._channel = QWebChannel(self._view.page())
        self._channel.registerObject("bridge", self._bridge)
        self._view.page().setWebChannel(self._channel)

        self._bridge.js_ready.connect(self._on_js_ready)
        self._bridge.content_changed.connect(self._on_content_changed)

        self._view.setUrl(QUrl.fromLocalFile(str(html_path)))

    def _get_qwebchannel_js(self) -> str:
        from PyQt6.QtCore import QFile, QIODevice
        f = QFile(":/qtwebchannel/qwebchannel.js")
        if f.open(QIODevice.OpenModeFlag.ReadOnly):
            data = bytes(f.readAll()).decode("utf-8")
            f.close()
            return data
        # Fallback: scarica da CDN
        try:
            with urllib.request.urlopen(
                "https://raw.githubusercontent.com/qt/qtwebchannel/dev/src/webchannel/qwebchannel.js",
                timeout=5
            ) as r:
                return r.read().decode()
        except Exception:
            return ""

    # ── Slot ──────────────────────────────────────────────────────────────────

    def _on_js_ready(self) -> None:
        self._js_ready = True
        if self._pending_html is not None:
            self._js_set_content(self._pending_html)
            self._pending_html = None
        self._update_status()

    def _on_content_changed(self) -> None:
        # Aggiorna word count ogni 2s per non appesantire
        if not hasattr(self, "_wc_timer"):
            self._wc_timer = QTimer(self)
            self._wc_timer.setSingleShot(True)
            self._wc_timer.timeout.connect(self._refresh_word_count)
        self._wc_timer.start(2000)

    # ── API pubblica ──────────────────────────────────────────────────────────

    def load_document(self, path: Path) -> bool:
        """Carica il documento dal path. Ritorna True se ok."""
        html, err = RichTextIO.load_html(path)
        if err:
            QMessageBox.critical(self, "NotePadPQ", tr("richtext.load_error", err=err))
            return False
        self.file_path = path
        self.set_html(html)
        self._set_modified(False)
        self._update_status()
        return True

    def set_html(self, html: str) -> None:
        """Imposta il contenuto HTML nell'editor."""
        if self._js_ready:
            self._js_set_content(html)
        else:
            self._pending_html = html

    def get_html(self) -> str:
        """Legge il contenuto HTML corrente dall'editor (sincrono)."""
        if not WEBENGINE_OK or not self._js_ready:
            return ""
        result: list[Optional[str]] = [None]
        loop = QEventLoop()

        def cb(val: str):
            result[0] = val
            loop.quit()

        self._view.page().runJavaScript("window.getContent()", cb)
        loop.exec()
        return result[0] or ""

    def is_modified(self) -> bool:
        return self._modified

    def save(self) -> bool:
        """Salva nel formato originale. Ritorna True se riuscito."""
        if self.file_path is None:
            return self.save_as()
        html = self.get_html()
        err  = RichTextIO.save_html(html, self.file_path)
        if err:
            QMessageBox.critical(self, "NotePadPQ", tr("richtext.save_error", err=err))
            return False
        self._set_modified(False)
        self._update_status()
        return True

    def save_as(self) -> bool:
        default = str(self.file_path or Path.home() / "documento.html")
        path, _ = QFileDialog.getSaveFileName(
            self, tr("richtext.save_as"),
            default, _SAVE_FILTER
        )
        if not path:
            return False
        p = Path(path)
        if p.suffix.lower() == ".pdf":
            return self._export_pdf(p)
        html = self.get_html()
        err  = RichTextIO.save_html(html, p)
        if err:
            QMessageBox.critical(self, "NotePadPQ", tr("richtext.save_error", err=err))
            return False
        self.file_path = p
        self._set_modified(False)
        self._update_status()
        return True

    def _export_pdf(self, path: Optional[Path] = None) -> bool:
        if path is None:
            default = str(
                (self.file_path.with_suffix(".pdf") if self.file_path
                 else Path.home() / "documento.pdf")
            )
            dest, _ = QFileDialog.getSaveFileName(
                self, tr("richtext.export_pdf"),
                default, "PDF (*.pdf)"
            )
            if not dest:
                return False
            path = Path(dest)
        if not WEBENGINE_OK:
            return False
        done: list[bool] = [False]
        loop = QEventLoop()

        def cb(ok: bool):
            done[0] = ok
            loop.quit()

        self._view.page().printToPdf(str(path), cb if hasattr(self._view.page(), "printToPdf") else None)
        # In Qt6 printToPdf può non avere callback in tutte le versioni
        try:
            self._view.page().printToPdf(str(path))
            return True
        except TypeError:
            pass
        return True

    # ── Helpers interni ───────────────────────────────────────────────────────

    def _js_set_content(self, html: str) -> None:
        escaped = json.dumps(html)
        self._view.page().runJavaScript(f"window.setContent({escaped})")

    def _set_modified(self, mod: bool) -> None:
        if mod != self._modified:
            self._modified = mod
            self.modified_changed.emit(mod)
            self._mod_lbl.setText(
                ("● " + tr("label.modified")) if mod else ""
            )

    def _update_status(self) -> None:
        if self.file_path:
            self._status_lbl.setText(str(self.file_path))

    def _refresh_word_count(self) -> None:
        if not WEBENGINE_OK or not self._js_ready:
            return

        def cb(html: str):
            if not html:
                return
            import re
            text = re.sub(r"<[^>]+>", " ", html)
            words = len(text.split())
            self._wc_label.setText(
                tr("richtext.word_count", count=words)
            )

        self._view.page().runJavaScript("window.getContent()", cb)

    def _open_as_text(self) -> None:
        html = self.get_html()
        name = (self.file_path.stem + ".html") if self.file_path else "documento.html"
        self.convert_to_text.emit(html, name)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._tmpdir and self._tmpdir.exists():
            shutil.rmtree(self._tmpdir, ignore_errors=True)
        super().closeEvent(event)

    def __del__(self):
        if self._tmpdir and self._tmpdir.exists():
            shutil.rmtree(self._tmpdir, ignore_errors=True)

"""
ui/preview_panel.py — Pannello anteprima laterale
NotePadPQ

Split view opzionale affiancata all'editor. Supporta:
  - Markdown  → HTML renderizzato (via python-markdown)
  - HTML      → preview diretta nel QWebEngineView
  - LaTeX     → struttura ad albero navigabile (sezioni/label, no compilazione)
  - reStructuredText → HTML via docutils (se installato)

Il pannello si attiva per documento (F12 o menu Visualizza).
L'aggiornamento avviene con un delay configurabile (default 500 ms)
per non appesantire la digitazione.

Integrazione con tab_manager:
    tab_manager.toggle_preview(True/False)
    → crea/mostra/nasconde un PreviewPanel affiancato all'editor corrente.

Il pannello non dipende da compilatori LaTeX esterni.
"""

from __future__ import annotations

import bisect
import re
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QThread, QEvent, pyqtSlot, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QToolBar, QToolButton, QSplitter, QSizePolicy,
    QTreeWidget, QTreeWidgetItem, QStackedWidget,
    QTextBrowser,
)
from PyQt6.QtGui import QIcon, QAction

from core.external_open import open_url as _open_url
from i18n.i18n import tr
from config.settings import Settings

# QWebEngineView è opzionale: se non installato si usa QTextBrowser come fallback
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    _HAS_WEBENGINE = True
except ImportError:
    _HAS_WEBENGINE = False

# python-markdown opzionale
try:
    import markdown as _markdown_lib
    _HAS_MARKDOWN = True
except ImportError:
    _HAS_MARKDOWN = False

import re as _re

def _fix_img_percent_dimensions(html: str, viewport_width: int = 800) -> str:
    """
    QTextBrowser non supporta width/height percentuali sulle immagini.
    Converte i valori percentuali in pixel usando la larghezza del viewport.
    Lascia invariati i valori già in pixel.
    Chiamare nel thread principale dove viewport_width è noto.
    """
    def _rewrite(m: "re.Match") -> str:
        tag = m.group(0)
        changed = False
        for attr in ("width", "height"):
            pat = _re.compile(rf'\b({attr})=["\']?(\d+(?:\.\d+)?)%["\']?', _re.IGNORECASE)
            hit = pat.search(tag)
            if hit:
                pct = float(hit.group(2))
                px = max(1, int(viewport_width * pct / 100))
                tag = pat.sub(rf'{attr}="{px}"', tag)
                changed = True
        return tag if changed else m.group(0)

    return _re.sub(r'<img\b[^>]*>', _rewrite, html, flags=_re.IGNORECASE)

# docutils opzionale
try:
    from docutils.core import publish_parts as _rst_publish
    _HAS_DOCUTILS = True
except ImportError:
    _HAS_DOCUTILS = False

# PyMuPDF opzionale — caricato in lazy loading al primo utilizzo
_fitz = None
_HAS_PYMUPDF: bool | None = None   # None = non ancora verificato

def _get_fitz():
    """Carica PyMuPDF (fitz) al primo utilizzo e ne memorizza l'esito."""
    global _fitz, _HAS_PYMUPDF
    if _HAS_PYMUPDF is None:
        try:
            import fitz as _fitz_mod
            _fitz = _fitz_mod
            _HAS_PYMUPDF = True
        except ImportError:
            _fitz = None
            _HAS_PYMUPDF = False
    return _HAS_PYMUPDF


# ─── Costanti ────────────────────────────────────────────────────────────────

_SUPPORTED_MODES = {"markdown", "html", "latex", "rst", "text", "pdf"}

_CSS_BASE = """
body {
    font-family: -apple-system, 'Segoe UI', sans-serif;
    font-size: 14px;
    line-height: 1.6;
    max-width: 900px;
    margin: 0 auto;
    padding: 1em 1.5em;
    color: #ddd;
    background: #1e1e1e;
}
h1,h2,h3,h4,h5,h6 { color: #9cdcfe; }
code { background: #2d2d2d; border-radius: 3px; padding: 2px 4px; }
pre code { display: block; padding: 0.8em; overflow-x: auto; }
a { color: #4fc1ff; }
blockquote { border-left: 3px solid #555; margin-left: 0; padding-left: 1em; color: #aaa; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #444; padding: 6px 10px; }
th { background: #2d2d2d; }
"""


class _ClickableLabel(QLabel):
    """QLabel che emette clicked(x, y) quando viene cliccato."""
    from PyQt6.QtCore import pyqtSignal as _sig
    clicked = _sig(int, int)

    def mousePressEvent(self, event):
        from PyQt6.QtCore import Qt as _Qt
        if event.button() == _Qt.MouseButton.LeftButton:
            self.clicked.emit(int(event.position().x()), int(event.position().y()))
        super().mousePressEvent(event)


# ─── Preprocessore Markdown per sync bidirezionale ───────────────────────────

def _inject_md_line_anchors(text: str):
    """
    Pre-processa il sorgente Markdown iniettando ancoraggi HTML prima di ogni
    blocco significativo (titoli, capoversi, blocchi di codice, blockquote, ecc.).
    Ritorna (modified_text, sorted_anchor_lines) dove anchor_lines è la lista
    ordinata dei numeri di riga (1-based) per cui è stato inserito un ancoraggio.
    """
    lines = text.split('\n')
    result = []
    anchor_lines = []
    prev_empty = True
    in_fence = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        is_empty = not stripped
        if stripped.startswith('```') or stripped.startswith('~~~'):
            in_fence = not in_fence
        if not is_empty and not in_fence:
            if prev_empty or stripped.startswith('#'):
                lineno = i + 1
                if not prev_empty:
                    result.append('')   # riga vuota prima dell'ancora se non c'è già
                result.append(f'<a name="line-{lineno}"></a>')
                result.append('')       # riga vuota dopo l'ancora per separare il blocco
                anchor_lines.append(lineno)
        result.append(line)
        prev_empty = is_empty

    return '\n'.join(result), anchor_lines


# ─── Worker thread per rendering Markdown ────────────────────────────────────────

class _MarkdownWorker(QThread):
    """
    Esegue il rendering Markdown in un thread separato.
    Il thread principale non viene mai bloccato, indipendentemente
    dalla dimensione del documento.
    """
    result_ready = pyqtSignal(str, list, bool)  # (html, anchor_lines, needs_js)

    def __init__(self, text: str):
        super().__init__()
        self._text = text

    def run(self) -> None:
        try:
            import re as _re
            preprocessed, anchor_lines = _inject_md_line_anchors(self._text)
            if _HAS_MARKDOWN:
                body = _markdown_lib.markdown(
                    preprocessed,
                    extensions=["tables", "fenced_code", "toc"],
                )
            else:
                import html as _html
                body = "<pre>" + _html.escape(self._text) + "</pre>"
                anchor_lines = []

            has_math = bool(
                "$" in self._text and _re.search(r'\$[\s\S]+?\$', self._text)
            )

            # Mermaid: rileva blocchi ```mermaid e converti per il renderer JS
            from config.settings import Settings as _S
            mermaid_enabled = _S.instance().get("preview/mermaid", True)
            has_mermaid = mermaid_enabled and bool(
                _re.search(r'```\s*mermaid', self._text)
            )
            if has_mermaid:
                # fenced_code produce <pre><code class="language-mermaid">...</code></pre>
                # mermaid.js si aspetta <div class="mermaid">...</div>
                body = _re.sub(
                    r'<pre><code class="language-mermaid">(.*?)</code></pre>',
                    lambda m: '<div class="mermaid">' + m.group(1) + '</div>',
                    body,
                    flags=_re.DOTALL,
                )

            needs_js = has_math or has_mermaid
            self.result_ready.emit(
                _wrap_html(body, math=has_math, mermaid=has_mermaid),
                anchor_lines,
                needs_js,
            )
        except Exception as e:
            import html as _html
            self.result_ready.emit(
                _wrap_html(f"<pre>Errore rendering: {_html.escape(str(e))}</pre>"),
                [],
                False,
            )


# ─── PreviewPanel ─────────────────────────────────────────────────────────────

class PreviewPanel(QWidget):
    """
    Pannello di anteprima laterale.
    Si collega a un EditorWidget tramite set_editor().
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._editor = None
        self._mode: str = "text"
        self._delay_ms: int = Settings.instance().get("preview/delay_ms", 500)
        self._sync_cursor: bool = Settings.instance().get("preview/sync_cursor", True)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._update_preview)
        self._last_hash: int = 0   # evita re-render se il testo non è cambiato

        # Debounce cursor sync: evita un SyncTeX subprocess o tree-walk
        # per ogni singolo tasto freccia. Aggiorna solo dopo 200ms di quiete.
        self._cursor_sync_timer = QTimer(self)
        self._cursor_sync_timer.setSingleShot(True)
        self._cursor_sync_timer.setInterval(200)
        self._cursor_sync_timer.timeout.connect(self._do_cursor_sync)
        self._cursor_sync_line: int = 0

        # Debounce selection sync: evidenzia nel PDF il testo selezionato nel .tex
        self._selection_sync_timer = QTimer(self)
        self._selection_sync_timer.setSingleShot(True)
        self._selection_sync_timer.setInterval(300)
        self._selection_sync_timer.timeout.connect(self._do_selection_sync)
        # (page_0based, y0_pt, y1_pt) in PDF points, o None
        self._pdf_selection_highlight: Optional[tuple] = None

        self._md_worker = None             # thread markdown corrente
        self._md_old_workers: list = []    # worker superati: tenuti vivi fino al termine
        self._needs_refresh: bool = False  # aggiornamento pendente mentre nascosto
        self._md_anchor_lines: list = []   # righe sorgente con ancoraggio (1-based, ordinata)
        self._md_anchor_pos_map: list = [] # [(doc_pos, line_no), ...] per backward sync

        self._build_ui()
        self._web_fallback.viewport().installEventFilter(self)
        self.setMinimumWidth(200)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # Barra strumenti interna
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setFloatable(False)

        self._lbl_mode = QLabel("  ")
        toolbar.addWidget(self._lbl_mode)

        toolbar.addSeparator()

        btn_refresh = QToolButton()
        btn_refresh.setText("↺")
        btn_refresh.setToolTip(tr("preview.refresh"))
        btn_refresh.clicked.connect(self._update_preview)
        toolbar.addWidget(btn_refresh)

        vl.addWidget(toolbar)

        # Stack: viewer web + tree LaTeX + fallback testo
        self._stack = QStackedWidget()

        # Pagina 0 — QTextBrowser per MD/RST/testo (sempre presente, istantaneo)
        self._web_fallback = QTextBrowser()
        self._web_fallback.setOpenExternalLinks(True)
        self._stack.addWidget(self._web_fallback)    # indice 0 FISSO

        # QWebEngineView lazy: creato solo per HTML puro, aggiunto alla fine
        self._web: Optional[object] = None

        # Pagina 1 — albero struttura LaTeX
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.itemClicked.connect(self._on_tree_item_clicked)
        self._stack.addWidget(self._tree)

        # Pagina 2 — testo grezzo fallback
        self._text_fallback = QTextBrowser()
        self._stack.addWidget(self._text_fallback)

        # Pagina 3 — anteprima PDF con PyMuPDF + SyncTeX
        self._pdf_widget = QWidget()
        pdf_vl = QVBoxLayout(self._pdf_widget)
        pdf_vl.setContentsMargins(0, 0, 0, 0)
        pdf_vl.setSpacing(2)

        pdf_nav = QHBoxLayout()
        self._pdf_btn_prev = QToolButton()
        self._pdf_btn_prev.setText("◀")
        self._pdf_btn_prev.setToolTip(tr("tooltip.preview_prev"))
        self._pdf_btn_prev.clicked.connect(self._pdf_prev_page)
        self._pdf_btn_next = QToolButton()
        self._pdf_btn_next.setText("▶")
        self._pdf_btn_next.setToolTip(tr("tooltip.preview_next"))
        self._pdf_btn_next.clicked.connect(self._pdf_next_page)
        self._pdf_lbl_page = QLabel("  —  ")
        self._pdf_lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pdf_lbl_page.setMinimumWidth(80)
        self._pdf_zoom_in  = QToolButton()
        self._pdf_zoom_in.setText("🔍+")
        self._pdf_zoom_in.setToolTip(tr("tooltip.preview_zoom_in"))
        self._pdf_zoom_in.clicked.connect(self._pdf_zoom_in_action)
        self._pdf_zoom_out = QToolButton()
        self._pdf_zoom_out.setText("🔍−")
        self._pdf_zoom_out.setToolTip(tr("tooltip.preview_zoom_out"))
        self._pdf_zoom_out.clicked.connect(self._pdf_zoom_out_action)
        self._pdf_lbl_synctex = QLabel("")
        self._pdf_lbl_synctex.setStyleSheet("color: #4caf50; font-size: 10px; padding: 0 4px;")

        # Pulsanti fit
        self._pdf_btn_fit_width = QToolButton()
        self._pdf_btn_fit_width.setText("↔")
        self._pdf_btn_fit_width.setToolTip(tr("tooltip.preview_fit_width"))
        self._pdf_btn_fit_width.clicked.connect(self._pdf_fit_width)

        self._pdf_btn_fit_page = QToolButton()
        self._pdf_btn_fit_page.setText("⛶")
        self._pdf_btn_fit_page.setToolTip(tr("tooltip.preview_fit_page"))
        self._pdf_btn_fit_page.clicked.connect(self._pdf_fit_page)
        
        self._pdf_btn_crop = QToolButton()
        self._pdf_btn_crop.setText("✂")
        self._pdf_btn_crop.setToolTip(tr("tooltip.preview_crop"))
        self._pdf_btn_crop.setCheckable(True)
        self._pdf_btn_crop.clicked.connect(self._pdf_toggle_crop)

        self._pdf_btn_zoom_reset = QToolButton()
        self._pdf_btn_zoom_reset.setText("1:1")
        self._pdf_btn_zoom_reset.setToolTip(tr("tooltip.preview_zoom_reset"))
        self._pdf_btn_zoom_reset.clicked.connect(self._pdf_zoom_reset)

        self._pdf_btn_open_external = QToolButton()
        self._pdf_btn_open_external.setText("↗")
        self._pdf_btn_open_external.setToolTip(tr("tooltip.preview_open_external"))
        self._pdf_btn_open_external.clicked.connect(self._pdf_open_external)

        self._pdf_btn_sync = QToolButton()
        self._pdf_btn_sync.setText("⇄")
        self._pdf_btn_sync.setCheckable(True)
        self._pdf_btn_sync.setChecked(self._sync_cursor)
        self._pdf_btn_sync.setToolTip(tr("tooltip.preview_sync_toggle"))
        self._pdf_btn_sync.toggled.connect(self._toggle_sync)

        self._pdf_btn_links = QToolButton()
        self._pdf_btn_links.setText("🔗")
        self._pdf_btn_links.setCheckable(True)
        self._pdf_btn_links.setChecked(True)
        self._pdf_btn_links.setToolTip(tr("tooltip.preview_links_toggle",
                                         default="Mostra/nascondi hyperlink nel PDF"))
        self._pdf_btn_links.toggled.connect(self._pdf_toggle_links)

        # toggle scroll continuo / pagina singola
        self._pdf_btn_continuous = QToolButton()
        self._pdf_btn_continuous.setText("↕")
        self._pdf_btn_continuous.setCheckable(True)
        self._pdf_btn_continuous.setChecked(False)  # default: pagina singola
        self._pdf_btn_continuous.setToolTip(tr("tooltip.preview_continuous"))
        self._pdf_btn_continuous.toggled.connect(self._pdf_toggle_continuous)

        for w2 in [self._pdf_btn_continuous,
                   self._pdf_btn_prev, self._pdf_lbl_page, self._pdf_btn_next,
                   self._pdf_zoom_out, self._pdf_zoom_in,
                   self._pdf_btn_zoom_reset, self._pdf_btn_fit_width,
                   self._pdf_btn_fit_page, self._pdf_btn_crop,
                   self._pdf_btn_links, self._pdf_btn_sync,
                   self._pdf_btn_open_external, self._pdf_lbl_synctex]:
            pdf_nav.addWidget(w2)
        for btn in [self._pdf_btn_continuous,
                    self._pdf_btn_prev, self._pdf_btn_next,
                    self._pdf_zoom_out, self._pdf_zoom_in,
                    self._pdf_btn_zoom_reset, self._pdf_btn_fit_width,
                    self._pdf_btn_fit_page, self._pdf_btn_crop,
                    self._pdf_btn_links, self._pdf_btn_sync,
                    self._pdf_btn_open_external]:
            btn.setFixedSize(26, 26)
        
        # (Questa è la riga che abbiamo aggiunto prima)
        pdf_vl.addLayout(pdf_nav)

        # --- INIZIO AGGIUNTA CONTATORI TAGLIO ---
        from PyQt6.QtWidgets import QSpinBox, QWidget as _QWidget, QHBoxLayout as _QHBoxLayout
        self._crop_widget = _QWidget()
        crop_layout = _QHBoxLayout(self._crop_widget)
        crop_layout.setContentsMargins(4, 0, 4, 2)
        crop_layout.setSpacing(6)

        self._crop_t = QSpinBox(); self._crop_t.setToolTip(tr("tooltip.preview_crop_top"))
        self._crop_b = QSpinBox(); self._crop_b.setToolTip(tr("tooltip.preview_crop_bottom"))
        self._crop_l = QSpinBox(); self._crop_l.setToolTip(tr("tooltip.preview_crop_left"))
        self._crop_r = QSpinBox(); self._crop_r.setToolTip(tr("tooltip.preview_crop_right"))

        crop_layout.addStretch() # Spinge i contatori al centro
        for label, sp in [(tr("preview.crop_top"), self._crop_t),
                          (tr("preview.crop_bottom"), self._crop_b),
                          (tr("preview.crop_left"), self._crop_l),
                          (tr("preview.crop_right"), self._crop_r)]:
            sp.setRange(0, 500)  # Fino a 500 punti di taglio
            sp.setValue(0)
            sp.setFixedWidth(50)
            # Quando cambi il numero, aggiorna il PDF in tempo reale!
            sp.valueChanged.connect(lambda: self._pdf_refresh())
            crop_layout.addWidget(QLabel(label))
            crop_layout.addWidget(sp)
        crop_layout.addStretch()

        self._crop_widget.hide() # Nascondi la barra di default
        pdf_vl.addWidget(self._crop_widget)
        # --- FINE AGGIUNTA CONTATORI TAGLIO ---

        from PyQt6.QtWidgets import QScrollArea, QVBoxLayout as _QVBoxLayout2
        self._pdf_scroll = QScrollArea()
        self._pdf_scroll.setWidgetResizable(True)
        self._pdf_scroll.setStyleSheet("background: #404040; border: none;")
        self._pdf_lbl_img = _ClickableLabel()
        self._pdf_lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pdf_lbl_img.setStyleSheet("background: #404040;")
        self._pdf_lbl_img.clicked.connect(self._on_pdf_clicked)
        self._pdf_scroll.setWidget(self._pdf_lbl_img)
        pdf_vl.addWidget(self._pdf_scroll, 1)

        # Scroll area per la modalità continua (tutte le pagine impilate)
        self._pdf_scroll_cont = QScrollArea()
        self._pdf_scroll_cont.setWidgetResizable(True)
        self._pdf_scroll_cont.setStyleSheet("background: #404040; border: none;")
        self._pdf_scroll_cont.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._pdf_cont_container = QWidget()
        self._pdf_cont_layout = _QVBoxLayout2(self._pdf_cont_container)
        self._pdf_cont_layout.setContentsMargins(8, 8, 8, 8)
        self._pdf_cont_layout.setSpacing(8)
        self._pdf_scroll_cont.setWidget(self._pdf_cont_container)
        self._pdf_scroll_cont.verticalScrollBar().valueChanged.connect(
            self._pdf_on_cont_scroll)
        pdf_vl.addWidget(self._pdf_scroll_cont, 1)
        self._pdf_scroll_cont.setVisible(False)

        self._stack.addWidget(self._pdf_widget)

        # Stato PDF
        self._pdf_doc        = None
        self._pdf_path       = None
        self._pdf_page_num   = 0
        self._pdf_zoom       = 1.5
        self._pdf_page_size  = (595.0, 842.0)  # punti A4 default
        self._pdf_show_links = True
        self._pdf_links: list = []
        self._pdf_cursor_highlight: Optional[tuple] = None  # (page_0based, y_pt, h_pt, W_pt)
        self._pdf_continuous  = False   # True = scroll continuo
        self._pdf_cont_page_labels: list = []   # _ClickableLabel per ogni pagina in modo continuo
        self._pdf_cont_clip_rects: list = []    # fitz.Rect clip per ogni pagina (coordinate conversion)

        vl.addWidget(self._stack)

    def _get_web_view(self):
        """
        Lazy-init di QWebEngineView: creato solo alla prima richiesta per HTML puro.
        Viene aggiunto in fondo allo stack (indice dinamico).
        Stack fisso: 0=TextBrowser, 1=LaTeX tree, 2=testo grezzo, 3=PDF, 4+=WebEngine
        """
        if self._web is None and _HAS_WEBENGINE:
            from core.webengine import safe_webview
            self._web = safe_webview()
            if self._web is not None:
                self._web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
                self._stack.addWidget(self._web)   # aggiunto in fondo, indice >= 4
        return self._web

    # ── Collegamento editor ───────────────────────────────────────────────────

    def set_editor(self, editor) -> None:
        """Collega il pannello a un EditorWidget."""
        if self._editor is not None:
            try:
                self._editor.textChanged.disconnect(self._on_text_changed)
            except Exception:
                pass
            try:
                self._editor.cursorPositionChanged.disconnect(self._on_cursor_changed)
            except Exception:
                pass
            try:
                self._editor.selectionChanged.disconnect(self._on_selection_changed)
            except Exception:
                pass

        self._editor = editor
        self._pdf_cursor_highlight = None

        # FIX: Forza il re-render invalidando la memoria dell'ultimo testo
        self._last_hash = 0
        
        if editor is None:
            self._set_mode("text")
            return

        # 1. RIPRISTINIAMO la definizione di 'path' perché serve per i PDF
        path = getattr(editor, "file_path", None)
        
        # 2. Ma passiamo l'intero 'editor' a _detect_mode come avevamo detto
        mode = _detect_mode(editor)
        self._set_mode(mode)

        if mode == "pdf":
            # Se l'editor ha un .tex, punta al PDF corrispondente
            pdf_path = _tex_pdf_path(editor) or path
            new_path = str(pdf_path) if pdf_path else None
            if new_path != self._pdf_path:
                if self._pdf_doc is not None:
                    try:
                        self._pdf_doc.close()
                    except Exception:
                        pass
                    self._pdf_doc = None
                self._pdf_path     = None
                self._pdf_page_num = 0
            self._update_synctex_label(pdf_path)

        # Connetti segnali
        # USA textChanged (1 segnale/keystroke) invece di SCN_MODIFIED
        # (che può sparare 4+ volte per singolo carattere)
        try:
            editor.textChanged.connect(
                self._on_text_changed,
                Qt.ConnectionType.UniqueConnection,
            )
        except Exception:
            pass
        if self._sync_cursor:
            try:
                editor.cursorPositionChanged.connect(
                    self._on_cursor_changed,
                    Qt.ConnectionType.UniqueConnection,
                )
            except Exception:
                pass
            try:
                editor.selectionChanged.connect(
                    self._on_selection_changed,
                    Qt.ConnectionType.UniqueConnection,
                )
            except Exception:
                pass

        self._schedule_update()

    def set_pdf_path(self, pdf_path) -> None:
        """
        Carica direttamente un PDF nel pannello senza passare per un EditorWidget.
        Usato da BuildPanel dopo la compilazione LaTeX.
        """
        from pathlib import Path as _Path
        path = _Path(str(pdf_path))
        path_str = str(path)

        # Imposta modalità pdf
        self._set_mode("pdf")
        self._update_synctex_label(path)

        if not _get_fitz():
            self._stack.setCurrentIndex(2)
            self._text_fallback.setPlainText("PyMuPDF non installato. Esegui: pip install pymupdf")
            return

        # Chiudi sempre il documento corrente prima di riaprire: è necessario
        # anche quando il path è identico, perché dopo una ricompilazione LaTeX
        # il file su disco è cambiato ma fitz ha ancora in cache il vecchio PDF.
        same_path = getattr(self, "_pdf_path", None) == path_str
        doc = getattr(self, "_pdf_doc", None)
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
            self._pdf_doc = None

        try:
            self._pdf_doc  = _fitz.open(path_str)
            self._pdf_path = path_str
            if not same_path:
                self._pdf_page_num = 0
        except Exception as e:
            self._pdf_doc  = None
            self._pdf_path = None
            self._stack.setCurrentIndex(2)
            self._text_fallback.setPlainText("Errore apertura PDF: " + str(e))
            return

        # Il documento è aperto e valido — mostra la pagina
        self._pdf_refresh()

    def detach_editor(self) -> None:
        self.set_editor(None)

    # ── Modalità ─────────────────────────────────────────────────────────────

    def _set_mode(self, mode: str) -> None:
        if mode != "pdf":
            self._pdf_selection_highlight = None
        self._mode = mode if mode in _SUPPORTED_MODES else "text"
        labels = {
            "markdown": "Markdown",
            "html":     "HTML",
            "latex":    "LaTeX",
            "rst":      "reStructuredText",
            "pdf":      "PDF",
            "text":     tr("preview.plain_text", default="Testo"),
        }
        self._lbl_mode.setText(f"  {labels.get(self._mode, self._mode)}")

    # ── Segnali editor ────────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_text_changed(self) -> None:
        if self.isVisible():
            self._timer.start(self._delay_ms)
        else:
            self._needs_refresh = True

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._needs_refresh:
            self._needs_refresh = False
            self._timer.start(self._delay_ms)

    @pyqtSlot(bool)
    def _toggle_sync(self, enabled: bool) -> None:
        self._sync_cursor = enabled
        Settings.instance().set("preview/sync_cursor", enabled)
        if self._editor is not None:
            if enabled:
                try:
                    self._editor.cursorPositionChanged.connect(
                        self._on_cursor_changed,
                        Qt.ConnectionType.UniqueConnection,
                    )
                except Exception:
                    pass
                try:
                    self._editor.selectionChanged.connect(
                        self._on_selection_changed,
                        Qt.ConnectionType.UniqueConnection,
                    )
                except Exception:
                    pass
            else:
                try:
                    self._editor.cursorPositionChanged.disconnect(self._on_cursor_changed)
                except Exception:
                    pass
                try:
                    self._editor.selectionChanged.disconnect(self._on_selection_changed)
                except Exception:
                    pass
                # Rimuovi l'eventuale highlight residuo
                self._pdf_selection_highlight = None
                self._pdf_refresh()

    @pyqtSlot(int, int)
    def _on_cursor_changed(self, line: int, col: int) -> None:
        if not self._sync_cursor:
            return
        # Debounce: accumulate rapid movements (arrow key held down) and
        # only sync after 200ms of inactivity. Avoids a SyncTeX subprocess
        # (or tree walk) on every single keystroke.
        self._cursor_sync_line = line
        self._cursor_sync_timer.start()

    def _do_cursor_sync(self) -> None:
        line = self._cursor_sync_line
        if self._mode == "latex":
            self._highlight_tree_item(line)
        elif self._mode == "pdf":
            self.go_to_pdf_page_for_line(line + 1)
        elif self._mode == "markdown":
            self._scroll_preview_to_line(line + 1)

    @pyqtSlot()
    def _on_selection_changed(self) -> None:
        if self._mode == "pdf" and self._sync_cursor:
            self._selection_sync_timer.start()

    def _do_selection_sync(self) -> None:
        """Evidenzia nel PDF la regione corrispondente al testo selezionato nel .tex."""
        if not self._editor or not self._pdf_path:
            return
        try:
            line_from, _idx_from, line_to, _idx_to = self._editor.getSelection()
        except Exception:
            return

        if line_from < 0:
            if self._pdf_selection_highlight is not None:
                old_sel_page = self._pdf_selection_highlight[0]
                self._pdf_selection_highlight = None
                if self._pdf_continuous:
                    self._pdf_update_cont_highlight(None, old_sel_page)
                else:
                    self._pdf_show_page()
            return

        try:
            from editor.synctex import SyncTeX
            from pathlib import Path as _Path
            pdf_p = _Path(self._pdf_path)
            tex_p = self._editor.file_path
            if not tex_p:
                return
            sx = SyncTeX(tex_p, pdf_p)

            r_start = sx.tex_to_pdf(line_from + 1, col=1)
            if not r_start:
                self._pdf_selection_highlight = None
                self._pdf_refresh()
                return

            page = r_start["page"] - 1  # 0-based
            y_start = r_start["y"]

            # Prendi la coordinata y della riga finale solo se è sulla stessa pagina
            r_end = sx.tex_to_pdf(line_to + 1, col=1) if line_to != line_from else None
            if r_end and r_end.get("page") == r_start["page"]:
                y_end = r_end["y"]
            else:
                y_end = y_start

            y0 = min(y_start, y_end) - 12.0   # spazio sopra la prima riga
            y1 = max(y_start, y_end) + 5.0    # spazio sotto l'ultima riga

            # Calcola x da h/W di SyncTeX per rispettare la colonna in layout multi-colonna.
            # h = bordo sinistro del nodo; W = larghezza del nodo (tipicamente = larghezza riga).
            # Se W è piccolo (nodo parola, non riga), estendiamo a un minimo di 180pt.
            h = r_start.get("h")
            W = r_start.get("W")
            if h is not None:
                x0_pt = max(0.0, h - 8.0)
                if W is not None and W > 10.0:
                    x1_pt = h + W + 8.0
                else:
                    x1_pt = h + 250.0   # larghezza minima se W non disponibile
            else:
                x0_pt = None   # segnale: usa larghezza pagina intera
                x1_pt = None

            self._pdf_selection_highlight = (page, y0, y1, x0_pt, x1_pt)

            old_page = self._pdf_page_num
            if page != self._pdf_page_num:
                self._pdf_page_num = page
            if self._pdf_continuous:
                self._pdf_update_cont_highlight(page, old_page if old_page != page else None)
                QTimer.singleShot(0, lambda p=page: self._scroll_cont_to_page(p))
            else:
                self._pdf_show_page()
        except Exception:
            pass

    # ── Aggiornamento contenuto ───────────────────────────────────────────────

    def _schedule_update(self) -> None:
        self._timer.start(300)   # delay iniziale (era 100, troppo aggressivo)

    @pyqtSlot()
    def _update_preview(self) -> None:
        if self._editor is None:
            return
            
        try:
            text = self._editor.text()
        except Exception:
            return
            
        # Skip se il testo non è cambiato dall'ultimo render
        h = hash(text)
        if h == self._last_hash and self._mode not in ("pdf",):
            return
        self._last_hash = h

        if self._mode == "pdf":
            self._render_pdf()
            return
        if self._mode == "markdown":
            self._render_markdown(text)
        elif self._mode == "html":
            self._render_html(text)
        elif self._mode == "latex":
            self._render_latex_tree(text)
        elif self._mode == "rst":
            self._render_rst(text)
        else:
            self._render_plain(text)

    # ── Renderer ──────────────────────────────────────────────────────────────

    def _render_markdown(self, text: str) -> None:
        """Rendering MD in un QThread separato per non bloccare l'UI."""
        if not text.strip():
            self._web_fallback.setPlainText("")
            return

        if self._md_worker is not None:
            # Disconnetti il risultato del vecchio worker: lo ignoreremo.
            # NON chiamare deleteLater/quit: il thread è ancora in esecuzione.
            # Lo teniamo vivo in _md_old_workers finché non termina da solo.
            try:
                self._md_worker.result_ready.disconnect()
            except Exception:
                pass
            old = self._md_worker
            self._md_old_workers.append(old)
            def _cleanup(w=old):
                try:
                    self._md_old_workers.remove(w)
                except ValueError:
                    pass
            old.finished.connect(_cleanup)
            self._md_worker = None

        self._md_worker = _MarkdownWorker(text)
        self._md_worker.result_ready.connect(self._on_markdown_ready)
        self._md_worker.start()

    def _on_markdown_ready(self, html: str, anchor_lines: list, needs_js: bool = False) -> None:
        """Slot chiamato dal thread MD quando il rendering è pronto."""
        if self.sender() is self._md_worker and self._md_worker is not None:
            old = self._md_worker
            self._md_old_workers.append(old)
            def _cleanup(w=old):
                try:
                    self._md_old_workers.remove(w)
                except ValueError:
                    pass
            old.finished.connect(_cleanup)
            self._md_worker = None
        if self._mode == "markdown":
            self._md_anchor_lines = anchor_lines
            vp_w = self._web_fallback.viewport().width() or 800
            html = _fix_img_percent_dimensions(html, vp_w)
            # MathJax e Mermaid richiedono WebEngine (JS); QTextBrowser non esegue JS
            self._show_html(html, force_webengine=needs_js)
            if not needs_js:
                self._build_anchor_pos_map()

   

    def _render_html(self, text: str) -> None:
        # HTML puro: usa WebEngine se disponibile (supporta JS e CSS complessi)
        self._show_html(text, force_webengine=True)

    def _render_rst(self, text: str) -> None:
        import html as _html
        if _HAS_DOCUTILS:
            try:
                parts = _rst_publish(text, writer_name="html")
                body  = parts.get("html_body", "")
                self._show_html(_wrap_html(body), force_webengine=False)
                return
            except Exception:
                pass
        self._show_html(_wrap_html("<pre>" + _html.escape(text) + "</pre>"),
                        force_webengine=False)

    def _render_plain(self, text: str) -> None:
        import html as _html
        self._show_html(_wrap_html("<pre>" + _html.escape(text) + "</pre>"),
                        force_webengine=False)

    def _render_latex_tree(self, text: str) -> None:
        """Costruisce l'albero struttura LaTeX via regex (no compilazione)."""
        self._stack.setCurrentIndex(1)
        self._tree.clear()

        # Pattern: \chapter, \section, \subsection, \subsubsection, \label
        SECT_PAT = re.compile(
            r"^[^%]*\\(chapter|section|subsection|subsubsection|paragraph)"
            r"\*?\s*\{([^}]*)\}",
            re.MULTILINE
        )
        LABEL_PAT = re.compile(r"\\label\{([^}]+)\}", re.MULTILINE)
        FIG_PAT   = re.compile(r"\\begin\{figure\}", re.MULTILINE)
        TAB_PAT   = re.compile(r"\\begin\{table\}", re.MULTILINE)

        level_map = {
            "chapter":        0,
            "section":        1,
            "subsection":     2,
            "subsubsection":  3,
            "paragraph":      4,
        }

        root = self._tree.invisibleRootItem()
        stack: list[QTreeWidgetItem] = []  # stack per gerarchia
        lines = text.split("\n")

        for lineno, line in enumerate(lines):
            m = SECT_PAT.match(line)
            if m:
                cmd, title = m.group(1), m.group(2)
                level = level_map.get(cmd, 1)
                item = QTreeWidgetItem([f"{_sect_prefix(cmd)} {title}"])
                item.setData(0, Qt.ItemDataRole.UserRole, lineno)
                item.setToolTip(0, f"Riga {lineno + 1}")
                # Posiziona nell'albero
                while stack and _item_level(stack[-1]) >= level:
                    stack.pop()
                parent = stack[-1] if stack else root
                parent.addChild(item)
                stack.append(item)
                continue

            # Label
            for lm in LABEL_PAT.finditer(line):
                lbl = QTreeWidgetItem([f"🏷 {lm.group(1)}"])
                lbl.setData(0, Qt.ItemDataRole.UserRole, lineno)
                lbl.setToolTip(0, f"\\label  riga {lineno + 1}")
                parent = stack[-1] if stack else root
                parent.addChild(lbl)

        # Figure e tabelle (contatore semplice)
        fig_count = len(FIG_PAT.findall(text))
        tab_count = len(TAB_PAT.findall(text))
        if fig_count:
            QTreeWidgetItem(root, [f"📷 Figure ({fig_count})"])
        if tab_count:
            QTreeWidgetItem(root, [f"📊 Tabelle ({tab_count})"])

        self._tree.expandAll()

    # ── Helpers visualizzazione ───────────────────────────────────────────────

    def _show_html(self, html: str, force_webengine: bool = False) -> None:
        """
        Mostra HTML nel viewer appropriato.
        Stack fisso: 0=QTextBrowser, 1=LaTeX tree, 2=testo grezzo, 3=PDF, 4+=WebEngine
        - force_webengine=True  → WebEngine (indice dinamico, solo HTML puro)
        - force_webengine=False → QTextBrowser all'indice 0 (istantaneo)
        """
        if force_webengine and _HAS_WEBENGINE:
            view = self._get_web_view()
            if view is not None:
                idx = self._stack.indexOf(view)
                self._stack.setCurrentIndex(idx)
                view.setHtml(html)
                return
        # QTextBrowser è sempre all'indice 0
        self._web_fallback.setHtml(html)
        self._stack.setCurrentIndex(0)

    def _highlight_tree_item(self, line: int) -> None:
        """Evidenzia nell'albero la sezione più vicina alla riga corrente."""
        best: Optional[QTreeWidgetItem] = None
        best_line = -1

        def _walk(item: QTreeWidgetItem) -> None:
            nonlocal best, best_line
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data is not None and data <= line and data > best_line:
                best = item
                best_line = data
            for i in range(item.childCount()):
                _walk(item.child(i))

        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            _walk(root.child(i))

        if best:
            self._tree.setCurrentItem(best)
            self._tree.scrollToItem(best)

    @pyqtSlot(QTreeWidgetItem, int)
    def _on_tree_item_clicked(self, item: QTreeWidgetItem, col: int) -> None:
        """Navigazione: click sull'albero → salta alla riga nell'editor."""
        if self._editor is None:
            return
        lineno = item.data(0, Qt.ItemDataRole.UserRole)
        if lineno is not None:
            try:
                self._editor.setCursorPosition(lineno, 0)
                self._editor.setFocus()
                self._editor.ensureLineVisible(lineno)
            except Exception:
                pass

    # ── Sync bidirezionale Markdown ───────────────────────────────────────────

    def _scroll_preview_to_line(self, line_1based: int) -> None:
        """Forward sync: scorri l'anteprima Markdown alla riga sorgente indicata."""
        if not self._md_anchor_lines:
            return
        idx = bisect.bisect_right(self._md_anchor_lines, line_1based) - 1
        if idx >= 0:
            self._web_fallback.scrollToAnchor(f"line-{self._md_anchor_lines[idx]}")

    def _build_anchor_pos_map(self) -> None:
        """
        Dopo setHtml(), itera il QTextDocument per costruire la mappa
        posizione-documento → numero-riga-sorgente usata dal backward sync.
        """
        self._md_anchor_pos_map = []
        doc = self._web_fallback.document()
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                if fragment.isValid():
                    fmt = fragment.charFormat()
                    names = fmt.anchorNames()
                    if names:
                        for name in names:
                            if name.startswith('line-'):
                                try:
                                    self._md_anchor_pos_map.append(
                                        (fragment.position(), int(name[5:]))
                                    )
                                except ValueError:
                                    pass
                it += 1
            block = block.next()
        self._md_anchor_pos_map.sort()

    def _line_for_doc_pos(self, pos: int) -> Optional[int]:
        """Ritorna il numero di riga sorgente (1-based) più vicino alla posizione pos nel documento."""
        if not self._md_anchor_pos_map:
            return None
        lo, hi, result = 0, len(self._md_anchor_pos_map) - 1, None
        while lo <= hi:
            mid = (lo + hi) // 2
            if self._md_anchor_pos_map[mid][0] <= pos:
                result = self._md_anchor_pos_map[mid][1]
                lo = mid + 1
            else:
                hi = mid - 1
        return result

    def eventFilter(self, obj, event) -> bool:
        """Backward sync: click nell'anteprima Markdown → salta alla riga nell'editor."""
        if (obj is self._web_fallback.viewport()
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and self._mode == "markdown"
                and self._sync_cursor
                and self._editor is not None):
            cursor = self._web_fallback.cursorForPosition(event.pos())
            line = self._line_for_doc_pos(cursor.position())
            if line is not None:
                try:
                    self._editor.setCursorPosition(line - 1, 0)
                    self._editor.ensureLineVisible(line - 1)
                    self._editor.setFocus()
                except Exception:
                    pass
        return super().eventFilter(obj, event)

    # ── Aggiornamento impostazioni ────────────────────────────────────────────

    # ── PDF rendering ────────────────────────────────────────────────────────

    def _render_pdf(self) -> None:
        """Apre/renderizza il PDF dal path corrente usando PyMuPDF."""
        if not _get_fitz():
            self._stack.setCurrentIndex(2)
            self._text_fallback.setPlainText("PyMuPDF non installato. Esegui: pip install pymupdf")
            return
        path = getattr(self._editor, "file_path", None) if self._editor else None
        if path is None:
            self._stack.setCurrentIndex(2)
            self._text_fallback.setPlainText("Nessun file PDF.")
            return
        # Se l'editor ha un .tex, usa il PDF corrispondente
        path = _tex_pdf_path(self._editor) or path
        path_str = str(path)
        if self._pdf_path != path_str:
            try:
                if self._pdf_doc is not None:
                    self._pdf_doc.close()
                self._pdf_doc  = _fitz.open(path_str)
                self._pdf_path = path_str
                self._pdf_page_num = 0
            except Exception as e:
                self._stack.setCurrentIndex(2)
                self._text_fallback.setPlainText("Errore apertura PDF: " + str(e))
                return
        self._pdf_refresh()

    def _pdf_toggle_crop(self, checked: bool) -> None:
        """Attiva o disattiva il taglio dei margini e aggiorna la vista."""
        self._pdf_crop_margins = checked
        if hasattr(self, "_crop_widget"):
            self._crop_widget.setVisible(checked)
        self._pdf_refresh()

    def _render_page_pixmap(self, page_idx: int):
        """Rasterizza la pagina page_idx con crop, highlight cursore, selezione e link overlay.
        Ritorna (QPixmap, clip_rect) oppure (None, None) in caso di errore."""
        if self._pdf_doc is None or not _get_fitz():
            return None, None
        if not (0 <= page_idx < len(self._pdf_doc)):
            return None, None
        try:
            page = self._pdf_doc[page_idx]
            clip_rect = page.rect
            if getattr(self, "_pdf_crop_margins", False):
                c_t = self._crop_t.value(); c_b = self._crop_b.value()
                c_l = self._crop_l.value(); c_r = self._crop_r.value()
                if c_t == 0 and c_b == 0 and c_l == 0 and c_r == 0:
                    blocks = page.get_text("blocks")
                    if blocks:
                        x0 = min(b[0] for b in blocks); y0 = min(b[1] for b in blocks)
                        x1 = max(b[2] for b in blocks); y1 = max(b[3] for b in blocks)
                        clip_rect = _fitz.Rect(
                            max(0, x0-15), max(0, y0-15),
                            min(page.rect.width, x1+15), min(page.rect.height, y1+15))
                else:
                    clip_rect = _fitz.Rect(
                        page.rect.x0+c_l, page.rect.y0+c_t,
                        page.rect.x1-c_r, page.rect.y1-c_b)

            mat = _fitz.Matrix(self._pdf_zoom, self._pdf_zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False, clip=clip_rect)
            from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen, QBrush, QColor
            img = QImage(pix.samples, pix.width, pix.height,
                         pix.stride, QImage.Format.Format_RGB888)
            pm = QPixmap.fromImage(img)
            ox, oy, z = clip_rect.x0, clip_rect.y0, self._pdf_zoom

            # Cursor indicator (forward SyncTeX)
            if self._pdf_cursor_highlight is not None:
                c_page, c_y, c_h, c_W = self._pdf_cursor_highlight
                if c_page == page_idx and c_y is not None:
                    cy = int((c_y - oy) * z)
                    if c_h is not None and c_W is not None and c_W > 2:
                        cx0 = max(0, int((c_h - ox) * z))
                        cw  = max(4, int(c_W * z))
                    else:
                        cx0, cw = 0, pm.width()
                    p = QPainter(pm)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    p.setPen(QPen(QColor(255, 80, 0, 180), 2))
                    p.setBrush(QBrush(QColor(255, 120, 0, 30)))
                    p.drawRect(cx0, max(0, cy-9), cw, 18)
                    p.end()

            # Selection highlight
            if self._pdf_selection_highlight is not None:
                h_page, h_y0, h_y1, h_x0_pt, h_x1_pt = self._pdf_selection_highlight
                if h_page == page_idx:
                    ry0 = int((h_y0 - oy) * z)
                    ry1 = int((h_y1 - oy) * z)
                    band_h = max(4, ry1 - ry0)
                    if h_x0_pt is not None and h_x1_pt is not None:
                        rx0   = int((h_x0_pt - ox) * z)
                        band_w = max(4, int((h_x1_pt - ox) * z) - rx0)
                    else:
                        rx0, band_w = 0, pm.width()
                    p = QPainter(pm)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    p.setPen(QPen(QColor(255, 200, 0, 200), 1))
                    p.setBrush(QBrush(QColor(255, 220, 0, 70)))
                    p.drawRect(rx0, ry0, band_w, band_h)
                    p.end()

            # Links overlay
            pdf_links = page.get_links()
            if self._pdf_show_links and pdf_links:
                p = QPainter(pm)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                for lnk in pdf_links:
                    r = lnk["from"]
                    px0 = (r.x0 - ox) * z; py0 = (r.y0 - oy) * z
                    pw2 = (r.x1 - r.x0) * z; ph2 = (r.y1 - r.y0) * z
                    if pw2 < 2 or ph2 < 2:
                        continue
                    p.setPen(QPen(QColor(30, 120, 255, 210), 1))
                    p.setBrush(QBrush(QColor(30, 120, 255, 40)))
                    p.drawRoundedRect(int(px0), int(py0), int(pw2), int(ph2), 2, 2)
                p.end()

            return pm, clip_rect
        except Exception:
            return None, None

    def _pdf_show_page(self) -> None:
        """Rasterizza e mostra la pagina corrente, applicando eventuali ritagli."""
        if self._pdf_doc is None:
            return
        try:
            _ = self._pdf_doc.page_count
        except (ValueError, AttributeError):
            if getattr(self, "_pdf_path", None):
                try:
                    self._pdf_doc = _fitz.open(self._pdf_path)
                except Exception as e:
                    self._stack.setCurrentIndex(2)
                    self._text_fallback.setPlainText("Errore riapertura PDF: " + str(e))
                    self._pdf_doc = None
                    return
            else:
                self._pdf_doc = None
                return

        total = len(self._pdf_doc)
        self._pdf_page_num = max(0, min(self._pdf_page_num, total - 1))
        self._pdf_lbl_page.setText(f"  {self._pdf_page_num + 1} / {total}  ")
        self._pdf_btn_prev.setEnabled(self._pdf_page_num > 0)
        self._pdf_btn_next.setEnabled(self._pdf_page_num < total - 1)

        pm, clip_rect = self._render_page_pixmap(self._pdf_page_num)
        if pm is None:
            self._stack.setCurrentIndex(2)
            self._text_fallback.setPlainText("Errore rendering pagina")
            return

        self._pdf_page_size    = (clip_rect.width, clip_rect.height)
        self._pdf_current_clip = clip_rect
        self._pdf_links        = self._pdf_doc[self._pdf_page_num].get_links()
        self._pdf_lbl_img.setPixmap(pm)
        self._stack.setCurrentIndex(3)

    

    def _pdf_prev_page(self) -> None:
        if self._pdf_doc is not None and self._pdf_page_num > 0:
            self._pdf_page_num -= 1
            self._pdf_show_page()

    def _pdf_next_page(self) -> None:
        if self._pdf_doc is not None and self._pdf_page_num < len(self._pdf_doc) - 1:
            self._pdf_page_num += 1
            self._pdf_show_page()

    def _pdf_zoom_in_action(self) -> None:
        self._pdf_zoom = min(4.0, self._pdf_zoom + 0.25)
        self._pdf_refresh()

    def _pdf_zoom_out_action(self) -> None:
        self._pdf_zoom = max(0.5, self._pdf_zoom - 0.25)
        self._pdf_refresh()

    def _pdf_zoom_reset(self) -> None:
        """Zoom 100% (1 punto PDF = 1 pixel × devicePixelRatio)."""
        self._pdf_zoom = 1.0
        self._pdf_refresh()

    def _pdf_fit_width(self) -> None:
        """Adatta lo zoom alla larghezza del pannello."""
        if self._pdf_doc is None:
            return
        # Rimuoviamo 20 pixel per far respirare i bordi e la scrollbar
        panel_w = self._pdf_scroll.viewport().width() - 20
        pw, ph = self._pdf_page_size
        if pw <= 0:
            return

        # In PyMuPDF, 1 punto con zoom 1.0 genera 1 pixel.
        # Quindi lo zoom esatto è: (pixel desiderati) / (punti della pagina)
        self._pdf_zoom = max(0.25, min(4.0, panel_w / pw))
        self._pdf_refresh()

    def _pdf_fit_page(self) -> None:
        """Adatta lo zoom per mostrare l'intera pagina nel pannello."""
        if self._pdf_doc is None:
            return
        vp = self._pdf_scroll.viewport()
        # Togliamo 20 pixel per non appiccicare il foglio ai bordi del pannello
        panel_w = vp.width() - 20
        panel_h = vp.height() - 20
        pw, ph = self._pdf_page_size
        if pw <= 0 or ph <= 0:
            return

        zoom_w = panel_w / pw
        zoom_h = panel_h / ph
        self._pdf_zoom = max(0.25, min(4.0, min(zoom_w, zoom_h)))
        self._pdf_refresh()

    def _pdf_open_external(self) -> None:
        """Apre il PDF corrente con il visualizzatore esterno predefinito."""
        if not self._pdf_path:
            return
        from PyQt6.QtCore import QUrl
        _open_url(QUrl.fromLocalFile(self._pdf_path))

    def _pdf_toggle_links(self, checked: bool) -> None:
        self._pdf_show_links = checked
        self._pdf_refresh()

    def _pdf_toggle_continuous(self, checked: bool) -> None:
        """Alterna tra scroll continuo e modalità pagina singola nell'anteprima TeX."""
        self._pdf_continuous = checked
        self._pdf_btn_prev.setVisible(not checked)
        self._pdf_btn_next.setVisible(not checked)
        self._pdf_lbl_page.setVisible(not checked)
        if checked:
            page_to_restore = self._pdf_page_num
            y_pt_restore = (
                self._pdf_cursor_highlight[1]
                if self._pdf_cursor_highlight and
                   self._pdf_cursor_highlight[0] == page_to_restore
                else None
            )
            # Costruisce le pagine mentre _pdf_scroll_cont è ancora nascosto
            self._pdf_show_all_pages()
            # Forza il calcolo del layout prima di rendere visibile la scroll area
            self._pdf_cont_layout.activate()
            # Rende visibile la scroll continua: Qt aggiorna il range della scrollbar
            self._pdf_scroll_cont.setVisible(True)
            # Posiziona subito alla pagina corretta — prima che avvenga qualsiasi repaint
            if y_pt_restore is not None:
                self._scroll_cont_to_page_y(page_to_restore, y_pt_restore)
            else:
                self._scroll_cont_to_page(page_to_restore)
            # Nasconde la vista pagina singola solo ora (nessun flash visibile)
            self._pdf_scroll.setVisible(False)
        else:
            self._pdf_scroll_cont.setVisible(False)
            self._pdf_scroll.setVisible(True)
            self._update_synctex_label(self._pdf_path if self._pdf_path else None)
            self._pdf_show_page()

    def _pdf_show_all_pages(self) -> None:
        """Renderizza tutte le pagine PDF e le impila verticalmente nel contenitore continuo."""
        if self._pdf_doc is None or not _get_fitz():
            return
        while self._pdf_cont_layout.count():
            item = self._pdf_cont_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
        self._pdf_cont_page_labels = []
        self._pdf_cont_clip_rects  = []

        from PyQt6.QtWidgets import QFrame as _QF
        total = len(self._pdf_doc)
        for i in range(total):
            pm, clip_rect = self._render_page_pixmap(i)
            if pm is None:
                continue
            lbl = _ClickableLabel()
            lbl.setPixmap(pm)
            lbl.setFixedSize(pm.size())
            lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            lbl.setStyleSheet("background: white; margin: 0;")
            lbl.clicked.connect(lambda x, y, idx=i: self._pdf_cont_clicked(idx, x, y))
            if i > 0:
                sep = _QF()
                sep.setFrameShape(_QF.Shape.HLine)
                sep.setStyleSheet("color: #555; margin: 0 8px;")
                self._pdf_cont_layout.addWidget(sep)
            self._pdf_cont_layout.addWidget(lbl)
            self._pdf_cont_page_labels.append(lbl)
            self._pdf_cont_clip_rects.append(clip_rect)
        self._stack.setCurrentIndex(3)

    def _pdf_refresh(self) -> None:
        """Aggiorna la vista PDF nella modalità corrente."""
        if self._pdf_continuous:
            self._pdf_show_all_pages()
        else:
            self._pdf_show_page()

    def _pdf_update_cont_highlight(self, new_page, old_page) -> None:
        """Re-renderizza le pagine interessate dall'aggiornamento dell'highlight nel modo continuo."""
        if not _get_fitz() or not self._pdf_cont_page_labels:
            return
        pages = set()
        if old_page is not None and old_page != new_page:
            pages.add(old_page)
        if new_page is not None:
            pages.add(new_page)
        for idx in pages:
            if idx < len(self._pdf_cont_page_labels):
                pm, clip_rect = self._render_page_pixmap(idx)
                if pm is not None:
                    self._pdf_cont_page_labels[idx].setPixmap(pm)
                    if idx < len(self._pdf_cont_clip_rects):
                        self._pdf_cont_clip_rects[idx] = clip_rect

    def _scroll_cont_to_page(self, page_idx: int) -> None:
        """In modalità continua, scrolla alla pagina indicata."""
        if page_idx >= len(self._pdf_cont_page_labels):
            return
        lbl = self._pdf_cont_page_labels[page_idx]
        y = lbl.pos().y()
        self._pdf_scroll_cont.verticalScrollBar().setValue(max(0, y - 8))

    def _scroll_cont_to_page_y(self, page_idx: int, y_pt: float) -> None:
        """In modalità continua, scrolla alla posizione y_pt (punti PDF) sulla pagina page_idx."""
        if page_idx >= len(self._pdf_cont_page_labels):
            return
        lbl      = self._pdf_cont_page_labels[page_idx]
        clip_rect = (self._pdf_cont_clip_rects[page_idx]
                     if page_idx < len(self._pdf_cont_clip_rects) else None)
        oy        = clip_rect.y0 if clip_rect else 0.0
        page_top  = lbl.pos().y()
        cy        = int((y_pt - oy) * self._pdf_zoom)
        target    = page_top + cy
        vbar      = self._pdf_scroll_cont.verticalScrollBar()
        vbar.setValue(max(0, target - self._pdf_scroll_cont.viewport().height() // 2))

    def _pdf_cont_clicked(self, page_idx: int, x: int, y: int) -> None:
        """Click su una pagina in modalità scroll continuo: gestisce link e backward SyncTeX."""
        if self._pdf_doc is None or not self._pdf_path:
            return
        if page_idx >= len(self._pdf_cont_page_labels):
            return
        lbl       = self._pdf_cont_page_labels[page_idx]
        clip_rect = (self._pdf_cont_clip_rects[page_idx]
                     if page_idx < len(self._pdf_cont_clip_rects) else None)
        pm        = lbl.pixmap()
        pix_w     = pm.width()  if pm else 1
        pix_h     = pm.height() if pm else 1
        ox        = clip_rect.x0     if clip_rect else 0.0
        oy        = clip_rect.y0     if clip_rect else 0.0
        pw        = clip_rect.width  if clip_rect else pix_w / self._pdf_zoom
        ph        = clip_rect.height if clip_rect else pix_h / self._pdf_zoom
        pdf_x     = ox + (x / pix_w) * pw
        pdf_y     = oy + (y / pix_h) * ph

        # Link click
        if self._pdf_show_links and _get_fitz():
            try:
                page = self._pdf_doc[page_idx]
                pt   = _fitz.Point(pdf_x, pdf_y)
                for lnk in page.get_links():
                    if pt in lnk["from"]:
                        uri = lnk.get("uri", "")
                        if uri:
                            from PyQt6.QtCore import QUrl
                            _open_url(QUrl(uri))
                            return
                        link_page = lnk.get("page", -1)
                        if link_page >= 0:
                            QTimer.singleShot(0, lambda p=link_page: self._scroll_cont_to_page(p))
                            return
            except Exception:
                pass

        # Backward SyncTeX
        if not self._sync_cursor:
            return
        try:
            from editor.synctex import SyncTeX
            from pathlib import Path as _Path
            pdf_p  = _Path(self._pdf_path)
            sx     = SyncTeX(pdf_p.with_suffix(".tex"), pdf_p)
            result = sx.pdf_to_tex(page_idx + 1, pdf_x, pdf_y)
            if result and "line" in result:
                self._goto_tex_line(result.get("file"), result["line"])
        except Exception:
            pass

    def _pdf_on_cont_scroll(self, _value: int = 0) -> None:
        """Aggiorna l'indicatore di pagina corrente durante lo scroll continuo."""
        if not self._pdf_doc or not self._pdf_continuous:
            return
        # calcola quale pagina ha la maggiore sovrapposizione col viewport
        vp_h = self._pdf_scroll_cont.viewport().height()
        vp_top = self._pdf_scroll_cont.verticalScrollBar().value()
        vp_bot = vp_top + vp_h
        best_idx = 0
        best_overlap = -1
        # le label delle pagine sono nei widget del layout (a indici pari: 0,2,4,...
        # perché i separatori occupano gli indici dispari)
        page_idx = 0
        for j in range(self._pdf_cont_layout.count()):
            item = self._pdf_cont_layout.itemAt(j)
            w = item.widget() if item else None
            if w is None:
                continue
            # i separatori QFrame non sono pagine
            from PyQt6.QtWidgets import QFrame as _QF2
            if isinstance(w, _QF2):
                continue
            lbl_top = w.pos().y()
            lbl_bot = lbl_top + w.height()
            overlap = max(0, min(lbl_bot, vp_bot) - max(lbl_top, vp_top))
            if overlap > best_overlap:
                best_overlap = overlap
                best_idx = page_idx
            page_idx += 1
        total = len(self._pdf_doc)
        self._pdf_lbl_page.setText(f"  {best_idx + 1} / {total}  ")
        self._pdf_page_num = best_idx

    # ── SyncTeX ───────────────────────────────────────────────────────────────

    def _update_synctex_label(self, pdf_path) -> None:
        """Aggiorna la label SyncTeX in base alla disponibilità del file .synctex.gz."""
        if not hasattr(self, "_pdf_lbl_synctex"):
            return
        if pdf_path is None:
            self._pdf_lbl_synctex.setText("")
            return
        from pathlib import Path as _Path
        sz = _Path(str(pdf_path)).with_suffix(".synctex.gz")
        s  = _Path(str(pdf_path)).with_suffix(".synctex")
        if sz.exists() or s.exists():
            self._pdf_lbl_synctex.setText("⟷ SyncTeX")
            self._pdf_lbl_synctex.setToolTip(tr("tooltip.preview_synctex"))
        else:
            self._pdf_lbl_synctex.setText("")

    def _on_pdf_clicked(self, x: int, y: int) -> None:
        """
        Click sul PDF: prima controlla se è su un hyperlink, poi usa SyncTeX.
        x, y sono coordinate pixel sull'immagine.
        """
        if self._pdf_doc is None or not self._pdf_path:
            return

        # Converti pixel → punti PDF
        pix_w = self._pdf_lbl_img.pixmap().width()  if self._pdf_lbl_img.pixmap() else 1
        pix_h = self._pdf_lbl_img.pixmap().height() if self._pdf_lbl_img.pixmap() else 1
        pw, ph = self._pdf_page_size

        # --- COMPENSAZIONE RITAGLIO ---
        offset_x = 0
        offset_y = 0
        if getattr(self, "_pdf_crop_margins", False) and hasattr(self, "_pdf_current_clip"):
            offset_x = self._pdf_current_clip.x0
            offset_y = self._pdf_current_clip.y0

        pdf_x = offset_x + (x / pix_w) * pw
        pdf_y = offset_y + (y / pix_h) * ph

        # --- LINK CLICK ---
        if self._pdf_show_links and self._pdf_links and _get_fitz():
            pt = _fitz.Point(pdf_x, pdf_y)
            for lnk in self._pdf_links:
                if pt in lnk["from"]:
                    uri = lnk.get("uri", "")
                    if uri:
                        from PyQt6.QtCore import QUrl
                        _open_url(QUrl(uri))
                        return
                    page_num = lnk.get("page", -1)
                    if page_num >= 0:
                        self._pdf_page_num = page_num
                        self._pdf_show_page()
                        return

        # --- SYNCTEX ---
        if not self._sync_cursor:
            return
        try:
            from editor.synctex import SyncTeX
            from pathlib import Path as _Path
            pdf_p = _Path(self._pdf_path)
            sx = SyncTeX(pdf_p.with_suffix(".tex"), pdf_p)
            result = sx.pdf_to_tex(self._pdf_page_num + 1, pdf_x, pdf_y)
            if result and "line" in result:
                self._goto_tex_line(result.get("file"), result["line"])
        except Exception:
            pass

    def _goto_tex_line(self, tex_file: str, line: int) -> None:
        """Naviga all'editor del file .tex e alla riga indicata."""
        from pathlib import Path as _Path
        mw = self.window()
        if not hasattr(mw, "_tab_manager"):
            return
        # Cerca se il file è già aperto
        target = _Path(tex_file) if tex_file else None
        editor = None
        if target:
            for ed in mw._tab_manager.all_editors():
                if ed.file_path and ed.file_path.resolve() == target.resolve():
                    mw._tab_manager.set_current_editor(ed)
                    editor = ed
                    break
        if editor is None:
            editor = mw._tab_manager.current_editor()
        if editor:
            editor.go_to_line(line)
            editor.setFocus()

    def go_to_pdf_page_for_line(self, line: int) -> None:
        """
        Pubblico: dato una riga nel .tex, scrolla il PDF alla pagina e posizione corrispondente.
        Chiamato dall'editor quando il cursore si sposta (integrazione tex->pdf).
        """
        if self._mode != "pdf" or not self._pdf_path:
            return
        editor = self._editor
        if not editor or not getattr(editor, "file_path", None):
            return
        try:
            from editor.synctex import SyncTeX
            from pathlib import Path as _Path
            pdf_p  = _Path(self._pdf_path)
            tex_p  = editor.file_path
            sx     = SyncTeX(tex_p, pdf_p)
            result = sx.tex_to_pdf(line, col=1)
            if result and "page" in result:
                new_page = result["page"] - 1
                y_pt     = result.get("y") or result.get("v")
                h_pt     = result.get("h")
                W_pt     = result.get("W")
                old_page = self._pdf_cursor_highlight[0] if self._pdf_cursor_highlight else None
                self._pdf_cursor_highlight = (new_page, y_pt, h_pt, W_pt)
                self._pdf_page_num = new_page
                if self._pdf_continuous:
                    self._pdf_update_cont_highlight(new_page, old_page)
                    if y_pt is not None:
                        QTimer.singleShot(0, lambda: self._scroll_cont_to_page_y(new_page, y_pt))
                else:
                    self._pdf_show_page()
                    if y_pt is not None:
                        def _scroll():
                            oy_val = self._pdf_current_clip.y0 if hasattr(self, "_pdf_current_clip") else 0.0
                            cy   = int((y_pt - oy_val) * self._pdf_zoom)
                            vbar = self._pdf_scroll.verticalScrollBar()
                            vbar.setValue(max(0, cy - self._pdf_scroll.viewport().height() // 2))
                        QTimer.singleShot(0, _scroll)
            else:
                if self._pdf_cursor_highlight is not None:
                    old_page = self._pdf_cursor_highlight[0]
                    self._pdf_cursor_highlight = None
                    if self._pdf_continuous:
                        self._pdf_update_cont_highlight(None, old_page)
                    else:
                        self._pdf_show_page()
        except Exception:
            pass
            
    def wheelEvent(self, event) -> None:
        """Gestisce lo scroll con la rotella: cambio pagina e zoom."""
        if self._mode != "pdf" or self._pdf_doc is None:
            super().wheelEvent(event)
            return

        # --- 1. ZOOM CON CTRL + ROTELLA ---
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self._pdf_zoom_in_action()
            else:
                self._pdf_zoom_out_action()
            event.accept()
            return

        # --- 2. CAMBIO PAGINA INTELLIGENTE ---
        # Recuperiamo la barra di scorrimento verticale
        v_bar = self._pdf_scroll.verticalScrollBar()
        delta = event.angleDelta().y()

        # Se giriamo la rotella verso l'alto e siamo già in cima alla pagina
        if delta > 0 and v_bar.value() == v_bar.minimum():
            if self._pdf_page_num > 0:
                self._pdf_prev_page()
                # Dopo il cambio pagina, ci posizioniamo in fondo alla pagina precedente
                QTimer.singleShot(10, lambda: v_bar.setValue(v_bar.maximum()))
                event.accept()
                return

        # Se giriamo la rotella verso il basso e siamo già in fondo alla pagina
        elif delta < 0 and v_bar.value() == v_bar.maximum():
            if self._pdf_page_num < len(self._pdf_doc) - 1:
                self._pdf_next_page()
                # Dopo il cambio pagina, ci posizioniamo in cima alla pagina nuova
                QTimer.singleShot(10, lambda: v_bar.setValue(v_bar.minimum()))
                event.accept()
                return

        # Altrimenti, lascia che lo scroll funzioni normalmente dentro la pagina
        super().wheelEvent(event)        

    def closeEvent(self, event) -> None:
        # Attendi i vecchi worker ancora in esecuzione
        for w in list(self._md_old_workers):
            try:
                w.wait(300)
            except Exception:
                pass
        self._md_old_workers.clear()
        # Termina thread MD corrente se attivo
        if self._md_worker is not None:
            try:
                self._md_worker.result_ready.disconnect()
                self._md_worker.quit()
                self._md_worker.wait(500)
            except Exception:
                pass
            self._md_worker = None
        # Chiudi documento PDF
        if self._pdf_doc is not None:
            try:
                self._pdf_doc.close()
            except Exception:
                pass
        # Disconnetti dall'editor
        self.set_editor(None)
        super().closeEvent(event)

    def update_settings(self) -> None:
        s = Settings.instance()
        self._delay_ms    = s.get("preview/delay_ms",   500)
        self._sync_cursor = s.get("preview/sync_cursor", True)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _tex_pdf_path(editor):
    """Ritorna il Path del PDF corrispondente al .tex dell'editor, o None."""
    from pathlib import Path as _Path
    path = getattr(editor, "file_path", None)
    if path is None:
        return None
    p = _Path(str(path))
    if p.suffix.lower() != ".tex":
        return None
    pdf = p.with_suffix(".pdf")
    return pdf if pdf.exists() else None


def _detect_mode(editor) -> str:
    """Determina la modalità preview dall'estensione o dal lexer."""
    if editor is None:
        return "text"

    # 1. Prova dall'estensione del file
    path = getattr(editor, "file_path", None)
    if path:
        ext = str(path).rsplit(".", 1)[-1].lower() if "." in str(path) else ""
        # Per .tex: se esiste il PDF corrispondente, mostra quello direttamente
        if ext == "tex":
            return "pdf" if _tex_pdf_path(editor) else "latex"
        ext_map = {
            "md": "markdown", "markdown": "markdown",
            "html": "html", "htm": "html",
            "rst": "rst", "pdf": "pdf"
        }
        if ext in ext_map:
            return ext_map[ext]

    # 2. Prova dal lexer (utile per i file Nuovi/Non salvati)
    try:
        lexer = editor.lexer()
        if lexer:
            lang = lexer.language().lower()
            if "markdown" in lang: return "markdown"
            if "html" in lang: return "html"
            if "tex" in lang or "latex" in lang: return "latex"
    except Exception:
        pass

    return "text"


def _wrap_html(body: str, math: bool = False, mermaid: bool = False) -> str:
    mathjax_tag = (
        "<script>MathJax={tex:{inlineMath:[['$','$'],['\\\\(','\\\\)']]},"
        "svg:{fontCache:'global'}};</script>"
        "<script src='https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js'"
        " async></script>"
    ) if math else ""
    mermaid_tag = (
        "<script src='https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js'></script>"
        "<script>mermaid.initialize({startOnLoad:true,theme:'neutral'});</script>"
    ) if mermaid else ""
    return (
        f"<!DOCTYPE html><html><head>"
        f"<meta charset='utf-8'>"
        f"<style>{_CSS_BASE}</style>"
        f"{mathjax_tag}"
        f"{mermaid_tag}"
        f"</head><body>{body}</body></html>"
    )


def _sect_prefix(cmd: str) -> str:
    return {
        "chapter":       "◆",
        "section":       "●",
        "subsection":    "○",
        "subsubsection": "·",
        "paragraph":     "▸",
    }.get(cmd, "•")


def _item_level(item: QTreeWidgetItem) -> int:
    """Ricava il livello gerarchico di un item dall'indentazione nell'albero."""
    level = 0
    p = item.parent()
    while p is not None:
        level += 1
        p = p.parent()
    return level

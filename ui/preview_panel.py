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

import re
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSlot, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QToolBar, QToolButton, QSplitter, QSizePolicy,
    QTreeWidget, QTreeWidgetItem, QStackedWidget,
    QTextBrowser,
)
from PyQt6.QtGui import QIcon, QAction

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

# docutils opzionale
try:
    from docutils.core import publish_parts as _rst_publish
    _HAS_DOCUTILS = True
except ImportError:
    _HAS_DOCUTILS = False

# PyMuPDF opzionale — per anteprima PDF
try:
    import fitz as _fitz
    _HAS_PYMUPDF = True
except ImportError:
    _HAS_PYMUPDF = False


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


# ─── Worker thread per rendering Markdown ────────────────────────────────────────

class _MarkdownWorker(QThread):
    """
    Esegue il rendering Markdown in un thread separato.
    Il thread principale non viene mai bloccato, indipendentemente
    dalla dimensione del documento.
    """
    result_ready = pyqtSignal(str)

    def __init__(self, text: str):
        super().__init__()
        self._text = text

    def run(self) -> None:
        try:
            if _HAS_MARKDOWN:
                body = _markdown_lib.markdown(
                    self._text,
                    extensions=["tables", "fenced_code", "toc"],
                )
            else:
                import html as _html
                body = "<pre>" + _html.escape(self._text) + "</pre>"
            self.result_ready.emit(_wrap_html(body))
        except Exception as e:
            import html as _html
            self.result_ready.emit(
                _wrap_html(f"<pre>Errore rendering: {_html.escape(str(e))}</pre>")
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
        self._md_worker = None             # thread markdown
        self._needs_refresh: bool = False  # aggiornamento pendente mentre nascosto

        self._build_ui()
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
        btn_refresh.setToolTip(tr("preview.refresh", default="Aggiorna"))
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
        self._pdf_btn_prev.setToolTip("Pagina precedente  [PgUp]")
        self._pdf_btn_prev.clicked.connect(self._pdf_prev_page)
        self._pdf_btn_next = QToolButton()
        self._pdf_btn_next.setText("▶")
        self._pdf_btn_next.setToolTip("Pagina successiva  [PgDn]")
        self._pdf_btn_next.clicked.connect(self._pdf_next_page)
        self._pdf_lbl_page = QLabel("  —  ")
        self._pdf_lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pdf_lbl_page.setMinimumWidth(80)
        self._pdf_zoom_in  = QToolButton()
        self._pdf_zoom_in.setText("🔍+")
        self._pdf_zoom_in.setToolTip("Zoom avanti  [Ctrl++]")
        self._pdf_zoom_in.clicked.connect(self._pdf_zoom_in_action)
        self._pdf_zoom_out = QToolButton()
        self._pdf_zoom_out.setText("🔍−")
        self._pdf_zoom_out.setToolTip("Zoom indietro  [Ctrl+-]")
        self._pdf_zoom_out.clicked.connect(self._pdf_zoom_out_action)
        self._pdf_lbl_synctex = QLabel("")
        self._pdf_lbl_synctex.setStyleSheet("color: #4caf50; font-size: 10px; padding: 0 4px;")

        # Pulsanti fit
        self._pdf_btn_fit_width = QToolButton()
        self._pdf_btn_fit_width.setText("↔")
        self._pdf_btn_fit_width.setToolTip("Adatta alla larghezza")
        self._pdf_btn_fit_width.clicked.connect(self._pdf_fit_width)

        self._pdf_btn_fit_page = QToolButton()
        self._pdf_btn_fit_page.setText("⛶")
        self._pdf_btn_fit_page.setToolTip("Adatta alla pagina intera")
        self._pdf_btn_fit_page.clicked.connect(self._pdf_fit_page)
        
        self._pdf_btn_crop = QToolButton()
        self._pdf_btn_crop.setText("✂")
        self._pdf_btn_crop.setToolTip("Taglia margini bianchi")
        self._pdf_btn_crop.setCheckable(True)
        self._pdf_btn_crop.clicked.connect(self._pdf_toggle_crop)

        self._pdf_btn_zoom_reset = QToolButton()
        self._pdf_btn_zoom_reset.setText("1:1")
        self._pdf_btn_zoom_reset.setToolTip("Zoom 100%")
        self._pdf_btn_zoom_reset.clicked.connect(self._pdf_zoom_reset)

        for w2 in [self._pdf_btn_prev, self._pdf_lbl_page, self._pdf_btn_next,
                   self._pdf_zoom_out, self._pdf_zoom_in,
                   self._pdf_btn_zoom_reset, self._pdf_btn_fit_width,
                   self._pdf_btn_fit_page, self._pdf_btn_crop, self._pdf_lbl_synctex]:
            pdf_nav.addWidget(w2)
        
        # (Questa è la riga che abbiamo aggiunto prima)
        pdf_vl.addLayout(pdf_nav)

        # --- INIZIO AGGIUNTA CONTATORI TAGLIO ---
        from PyQt6.QtWidgets import QSpinBox, QWidget as _QWidget, QHBoxLayout as _QHBoxLayout
        self._crop_widget = _QWidget()
        crop_layout = _QHBoxLayout(self._crop_widget)
        crop_layout.setContentsMargins(4, 0, 4, 2)
        crop_layout.setSpacing(6)

        self._crop_t = QSpinBox(); self._crop_t.setToolTip("Taglio in Alto (Top)")
        self._crop_b = QSpinBox(); self._crop_b.setToolTip("Taglio in Basso (Bottom)")
        self._crop_l = QSpinBox(); self._crop_l.setToolTip("Taglio a Sinistra (Left)")
        self._crop_r = QSpinBox(); self._crop_r.setToolTip("Taglio a Destra (Right)")

        crop_layout.addStretch() # Spinge i contatori al centro
        for label, sp in [("Su:", self._crop_t), ("Giù:", self._crop_b),
                          ("Sinistra:", self._crop_l), ("Destra:", self._crop_r)]:
            sp.setRange(0, 500)  # Fino a 500 punti di taglio
            sp.setValue(0)
            sp.setFixedWidth(50)
            # Quando cambi il numero, aggiorna il PDF in tempo reale!
            sp.valueChanged.connect(lambda: self._pdf_show_page()) 
            crop_layout.addWidget(QLabel(label))
            crop_layout.addWidget(sp)
        crop_layout.addStretch()

        self._crop_widget.hide() # Nascondi la barra di default
        pdf_vl.addWidget(self._crop_widget)
        # --- FINE AGGIUNTA CONTATORI TAGLIO ---

        from PyQt6.QtWidgets import QScrollArea
        self._pdf_scroll = QScrollArea()
        self._pdf_scroll.setWidgetResizable(True)
        self._pdf_scroll.setStyleSheet("background: #404040; border: none;")
        self._pdf_lbl_img = _ClickableLabel()
        self._pdf_lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pdf_lbl_img.setStyleSheet("background: #404040;")
        self._pdf_lbl_img.clicked.connect(self._on_pdf_clicked)
        self._pdf_scroll.setWidget(self._pdf_lbl_img)
        pdf_vl.addWidget(self._pdf_scroll, 1)
        self._stack.addWidget(self._pdf_widget)

        # Stato PDF
        self._pdf_doc       = None
        self._pdf_path      = None
        self._pdf_page_num  = 0
        self._pdf_zoom      = 1.5
        self._pdf_page_size = (595.0, 842.0)  # punti A4 default

        vl.addWidget(self._stack)

    def _get_web_view(self):
        """
        Lazy-init di QWebEngineView: creato solo alla prima richiesta per HTML puro.
        Viene aggiunto in fondo allo stack (indice dinamico).
        Stack fisso: 0=TextBrowser, 1=LaTeX tree, 2=testo grezzo, 3=PDF, 4+=WebEngine
        """
        if self._web is None and _HAS_WEBENGINE:
            from PyQt6.QtWebEngineWidgets import QWebEngineView
            self._web = QWebEngineView()
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

        self._editor = editor
        
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
            new_path = str(path) if path else None
            if new_path != self._pdf_path:
                if self._pdf_doc is not None:
                    try:
                        self._pdf_doc.close()
                    except Exception:
                        pass
                    self._pdf_doc = None
                self._pdf_path     = None
                self._pdf_page_num = 0
            self._update_synctex_label(path)

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

        if not _HAS_PYMUPDF:
            self._stack.setCurrentIndex(2)
            self._text_fallback.setPlainText("PyMuPDF non installato. Esegui: pip install pymupdf")
            return

        # Apri il documento se il path è cambiato OPPURE se il doc è stato chiuso
        doc = getattr(self, "_pdf_doc", None)
        doc_is_closed = doc is None
        if not doc_is_closed:
            try:
                _ = doc.page_count  # lancia ValueError se closed
            except (ValueError, AttributeError):
                doc_is_closed = True

        if getattr(self, "_pdf_path", None) != path_str or doc_is_closed:
            # Chiudi il documento precedente se ancora aperto
            if doc is not None and not doc_is_closed:
                try:
                    doc.close()
                except Exception:
                    pass
            try:
                self._pdf_doc      = _fitz.open(path_str)
                self._pdf_path     = path_str
                self._pdf_page_num = 0
            except Exception as e:
                self._pdf_doc  = None
                self._pdf_path = None
                self._stack.setCurrentIndex(2)
                self._text_fallback.setPlainText("Errore apertura PDF: " + str(e))
                return

        # Il documento è aperto e valido — mostra la pagina
        self._pdf_show_page()

    def detach_editor(self) -> None:
        self.set_editor(None)

    # ── Modalità ─────────────────────────────────────────────────────────────

    def _set_mode(self, mode: str) -> None:
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

    @pyqtSlot(int, int)
    def _on_cursor_changed(self, line: int, col: int) -> None:
        # Se la sincronizzazione è disattivata nelle impostazioni, fermati
        if not self._sync_cursor:
            return
            
        # Se stiamo guardando la struttura ad albero del LaTeX
        if self._mode == "latex":
            self._highlight_tree_item(line)
        # Se stiamo guardando il PDF compilato (SyncTeX in azione!)
        elif self._mode == "pdf":
            self.go_to_pdf_page_for_line(line + 1)

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
        """
        Rendering MD in un QThread separato per non bloccare l'UI.
        """
        if not text.strip():
            self._web_fallback.setPlainText("")
            return
            
        # FIX: Disconnessione e distruzione sicura del thread precedente
        if getattr(self, "_md_worker", None) is not None:
            try:
                self._md_worker.result_ready.disconnect()
            except Exception:
                pass
            self._md_worker.deleteLater()
            
        self._md_worker = _MarkdownWorker(text)
        self._md_worker.result_ready.connect(self._on_markdown_ready)
        self._md_worker.start()

    def _on_markdown_ready(self, html: str) -> None:
        """Slot chiamato dal thread MD quando il rendering è pronto."""
        # FIX: Accetta il risultato solo se proviene dal thread corrente
        if self.sender() == self._md_worker:
            self._md_worker = None
            
        if self._mode == "markdown":
            self._show_html(html, force_webengine=False)

   

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

    # ── Aggiornamento impostazioni ────────────────────────────────────────────

    # ── PDF rendering ────────────────────────────────────────────────────────

    def _render_pdf(self) -> None:
        """Apre/renderizza il PDF dal path corrente usando PyMuPDF."""
        if not _HAS_PYMUPDF:
            self._stack.setCurrentIndex(2)
            self._text_fallback.setPlainText("PyMuPDF non installato. Esegui: pip install pymupdf")
            return
        path = getattr(self._editor, "file_path", None) if self._editor else None
        if path is None:
            self._stack.setCurrentIndex(2)
            self._text_fallback.setPlainText("Nessun file PDF.")
            return
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
        self._pdf_show_page()
        
    def _pdf_toggle_crop(self, checked: bool) -> None:
        """Attiva o disattiva il taglio dei margini e aggiorna la vista."""
        self._pdf_crop_margins = checked
        if hasattr(self, "_crop_widget"):
            self._crop_widget.setVisible(checked)
        self._pdf_show_page()

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
        
        try:
            page = self._pdf_doc[self._pdf_page_num]

            # --- LOGICA INTELLIGENTE DI RITAGLIO MARGINI ---
            clip_rect = page.rect
            if getattr(self, "_pdf_crop_margins", False):
                # Leggiamo i valori dei 4 contatori
                c_t = self._crop_t.value()
                c_b = self._crop_b.value()
                c_l = self._crop_l.value()
                c_r = self._crop_r.value()

                # Se tutti i contatori sono a zero, usa il taglio automatico
                if c_t == 0 and c_b == 0 and c_l == 0 and c_r == 0:
                    blocks = page.get_text("blocks")
                    if blocks:
                        x0 = min(b[0] for b in blocks)
                        y0 = min(b[1] for b in blocks)
                        x1 = max(b[2] for b in blocks)
                        y1 = max(b[3] for b in blocks)
                        clip_rect = _fitz.Rect(
                            max(0, x0 - 15), max(0, y0 - 15),
                            min(page.rect.width, x1 + 15), min(page.rect.height, y1 + 15)
                        )
                else:
                    # Taglio manuale: rimpicciolisce la pagina in base ai valori inseriti
                    clip_rect = _fitz.Rect(
                        page.rect.x0 + c_l,
                        page.rect.y0 + c_t,
                        page.rect.x1 - c_r,
                        page.rect.y1 - c_b
                    )
            # ------------------------------------------------
            
            # Salviamo le dimensioni e le coordinate del ritaglio per SyncTeX
            self._pdf_page_size = (clip_rect.width, clip_rect.height)
            self._pdf_current_clip = clip_rect
            
            mat = _fitz.Matrix(self._pdf_zoom, self._pdf_zoom)
            
            # Passiamo "clip=clip_rect" alla libreria per farle disegnare solo l'area utile
            pix = page.get_pixmap(matrix=mat, alpha=False, clip=clip_rect)
            
            from PyQt6.QtGui import QImage, QPixmap
            img = QImage(pix.samples, pix.width, pix.height,
                         pix.stride, QImage.Format.Format_RGB888)
            self._pdf_lbl_img.setPixmap(QPixmap.fromImage(img))
            self._stack.setCurrentIndex(3)
        except Exception as e:
            self._stack.setCurrentIndex(2)
            self._text_fallback.setPlainText("Errore rendering: " + str(e))    

    

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
        self._pdf_show_page()

    def _pdf_zoom_out_action(self) -> None:
        self._pdf_zoom = max(0.5, self._pdf_zoom - 0.25)
        self._pdf_show_page()

    def _pdf_zoom_reset(self) -> None:
        """Zoom 100% (1 punto PDF = 1 pixel × devicePixelRatio)."""
        self._pdf_zoom = 1.0
        self._pdf_show_page()

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
        self._pdf_show_page()

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
        self._pdf_show_page()

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
            self._pdf_lbl_synctex.setToolTip(
                "SyncTeX attivo: clicca sul PDF per andare alla riga nel sorgente"
            )
        else:
            self._pdf_lbl_synctex.setText("")

    def _on_pdf_clicked(self, x: int, y: int) -> None:
        """
        Click sul PDF: usa SyncTeX per trovare la riga nel .tex e navigarci.
        x, y sono coordinate pixel sull'immagine.
        """
        if self._pdf_doc is None or not self._pdf_path:
            return
            
        # Converti pixel → punti PDF
        pix_w = self._pdf_lbl_img.pixmap().width()  if self._pdf_lbl_img.pixmap() else 1
        pix_h = self._pdf_lbl_img.pixmap().height() if self._pdf_lbl_img.pixmap() else 1
        pw, ph = self._pdf_page_size
        
        # --- COMPENSAZIONE RITAGLIO ---
        # Se abbiamo tagliato i margini, dobbiamo aggiungere lo spostamento (offset)
        offset_x = 0
        offset_y = 0
        if getattr(self, "_pdf_crop_margins", False) and hasattr(self, "_pdf_current_clip"):
            offset_x = self._pdf_current_clip.x0
            offset_y = self._pdf_current_clip.y0

        pdf_x = offset_x + (x / pix_w) * pw
        pdf_y = offset_y + (y / pix_h) * ph

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
        Pubblico: dato una riga nel .tex, scrolla il PDF alla pagina corrispondente.
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
            pdf_p = _Path(self._pdf_path)
            tex_p = editor.file_path
            sx = SyncTeX(tex_p, pdf_p)
            result = sx.tex_to_pdf(line, col=1)
            if result and "page" in result:
                new_page = result["page"] - 1  # 0-based
                if new_page != self._pdf_page_num:
                    self._pdf_page_num = new_page
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
        # Termina thread MD se attivo
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

def _detect_mode(editor) -> str:
    """Determina la modalità preview dall'estensione o dal lexer."""
    if editor is None:
        return "text"
        
    # 1. Prova dall'estensione del file
    path = getattr(editor, "file_path", None)
    if path:
        ext = str(path).rsplit(".", 1)[-1].lower() if "." in str(path) else ""
        ext_map = {
            "md": "markdown", "markdown": "markdown",
            "html": "html", "htm": "html",
            "tex": "latex", "rst": "rst", "pdf": "pdf"
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


def _wrap_html(body: str) -> str:
    return (
        f"<!DOCTYPE html><html><head>"
        f"<meta charset='utf-8'>"
        f"<style>{_CSS_BASE}</style>"
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

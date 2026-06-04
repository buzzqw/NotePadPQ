"""
ui/language_toolbar.py — Toolbar contestuale LaTeX / Markdown
NotePadPQ

Toolbar icon-only (stile Jodit) che appare automaticamente quando il documento
corrente è LaTeX o Markdown. Utilizza le icone Lucide già presenti nell'app,
caricandole con la stessa tecnica di _rebuild_toolbar() (currentColor → colore
testo palette). Degrada a testo breve se le icone non sono ancora scaricate.

Markdown: H1 H2 H3 | B I U S | Quote Code CodeBlock | UL OL Task HR | Table Link Image | AlignL C R | AlignTable Preview Struttura Parole
LaTeX:    B I S | Table WrapEnv AlignTable | AlignL C R | Begin End | Compile Run Build Stop
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QKeySequence, QCursor, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QToolButton, QFrame, QMenu,
    QInputDialog, QApplication, QSizePolicy,
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
)

from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow
    from editor.editor_widget import EditorWidget


# Mappa chiave → nome file SVG Lucide per i bottoni custom della language toolbar.
# Le icone già presenti in _ICON_MAP (bold, italic, ecc.) non vanno qui.
_MD_ICON_FILES: dict[str, str] = {
    "md_h1":          "heading-1.svg",
    "md_h2":          "heading-2.svg",
    "md_h3":          "heading-3.svg",
    "md_underline":   "underline.svg",
    "md_code":        "code.svg",
    "md_code_block":  "code-2.svg",
    "md_quote":       "quote.svg",
    "md_ul":          "list.svg",
    "md_ol":          "list-ordered.svg",
    "md_task":        "list-checks.svg",
    "md_hr":          "separator-horizontal.svg",
    "md_table":       "table-2.svg",
    "md_link":        "link.svg",
    "md_image":       "image.svg",
    "md_align_left":  "align-left.svg",
    "md_align_center":"align-center.svg",
    "md_align_right": "align-right.svg",
    "md_export_pdf":  "file-pdf.svg",
    "md_export_html": "file-code.svg",
    "md_structure":   "list-tree.svg",
    "latex_env":      "braces.svg",
    "latex_align_l":  "align-left.svg",
    "latex_align_c":  "align-center.svg",
    "latex_align_r":  "align-right.svg",
    "latex_image":    "image.svg",
    "latex_footnote": "type.svg",
    "latex_label":    "bookmark.svg",
    "latex_ref":      "link.svg",
    "latex_math":          "sigma.svg",
    "latex_table":         "table.svg",
    "latex_chevron_down":  "chevron-down.svg",
}

_ICON_SIZE = QSize(20, 20)

# Testo fallback per i bottoni tabella (usato se la generazione icone fallisce)
_TABLE_BTN_TEXT: dict[str, str] = {
    "row_above": "+↑",
    "row_below": "+↓",
    "col_left":  "←+",
    "col_right": "+→",
    "del_row":   "−↕",
    "del_col":   "−↔",
}


def _get_latex_sections() -> list[tuple[str, str]]:
    def s(key: str) -> str:
        return tr(f"latex_toolbar.{key}")
    return [
        (s("part"),                        r"\part"),
        (s("chapter"),                     r"\chapter"),
        (s("section"),                     r"\section"),
        (s("subsection"),                  r"\subsection"),
        (s("subsubsection"),               r"\subsubsection"),
        (s("paragraph"),                   r"\paragraph"),
        (s("subparagraph"),                r"\subparagraph"),
        (s("part")          + "*",         r"\part*"),
        (s("chapter")       + "*",         r"\chapter*"),
        (s("section")       + "*",         r"\section*"),
        (s("subsection")    + "*",         r"\subsection*"),
        (s("subsubsection") + "*",         r"\subsubsection*"),
        (s("paragraph")     + "*",         r"\paragraph*"),
        (s("subparagraph")  + "*",         r"\subparagraph*"),
    ]


def _get_latex_font_sizes() -> list[tuple[str, str]]:
    return [
        ("tiny",                                    r"\tiny"),
        ("scriptsize",                              r"\scriptsize"),
        ("footnotesize",                            r"\footnotesize"),
        (tr("latex_toolbar.size_small"),            r"\small"),
        ("normalsize",                              r"\normalsize"),
        ("large",                                   r"\large"),
        ("Large",                                   r"\Large"),
        ("LARGE",                                   r"\LARGE"),
        ("huge",                                    r"\huge"),
        ("Huge",                                    r"\Huge"),
    ]

_LATEX_CITE_ITEMS: list[tuple[str, str]] = [
    (r"\cite{}",              "cite"),
    (r"\citet{}",             "citet"),
    (r"\citep{}",             "citep"),
    (r"\nocite{*}",           "nocite_all"),
    (r"\bibliography{}",      "bibliography"),
    (r"\bibliographystyle{}", "bibliographystyle"),
]



def _make_table_icon(key: str, mw: "MainWindow") -> QIcon:
    """
    Genera un'icona 20×20 stile TeXstudio: griglia 3×3 con la riga/colonna
    interessata evidenziata in verde (inserimento) o arancione (cancellazione).
    """
    from PyQt6.QtGui import QPalette
    size   = 20
    cell   = 5    # dimensione cella griglia
    gap    = 1    # spazio tra celle
    rows   = 3
    cols   = 3

    # Colori
    pal        = mw.palette()
    bg_color   = pal.color(QPalette.ColorRole.Window)
    grid_color = pal.color(QPalette.ColorRole.Mid)
    hi_green   = QColor("#4caf50")
    hi_orange  = QColor("#ff9800")

    # Determina quale riga/colonna evidenziare e con quale colore
    # key: row_above → riga 0 verde; row_below → riga 2 verde
    #       col_left → col 0 verde; col_right → col 2 verde
    #       del_row  → riga 1 arancione; del_col → col 1 arancione
    hi_row = hi_col = -1
    hi_color = hi_green
    if key == "row_above":
        hi_row, hi_color = 0, hi_green
    elif key == "row_below":
        hi_row, hi_color = 2, hi_green
    elif key == "col_left":
        hi_col, hi_color = 0, hi_green
    elif key == "col_right":
        hi_col, hi_color = 2, hi_green
    elif key == "del_row":
        hi_row, hi_color = 1, hi_orange
    elif key == "del_col":
        hi_col, hi_color = 1, hi_orange

    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    # Offset per centrare la griglia (3 celle da 5px + 2 gap da 1px = 17px)
    ox = (size - (cols * cell + (cols - 1) * gap)) // 2
    oy = (size - (rows * cell + (rows - 1) * gap)) // 2

    for r in range(rows):
        for c in range(cols):
            x = ox + c * (cell + gap)
            y = oy + r * (cell + gap)
            if r == hi_row or c == hi_col:
                color = hi_color
            else:
                color = grid_color
            p.fillRect(x, y, cell, cell, color)

    p.end()
    return QIcon(pm)


def _make_math_icon(mw: "MainWindow") -> QIcon:
    """Genera un'icona 20×20 con il simbolo Σ per il bottone matematica."""
    from PyQt6.QtGui import QPalette, QFont
    size = 20
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = mw.palette().color(QPalette.ColorRole.WindowText)
    p.setPen(color)
    font = QFont()
    font.setPointSize(12)
    font.setBold(True)
    p.setFont(font)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "Σ")
    p.end()
    return QIcon(pm)


def render_svg_icon(icon_path: Path, color: str) -> QPixmap:
    """Renders an SVG icon replacing currentColor with color.
    For Lucide-style icons (stroke-only, fill=none) boosts stroke-width 2→2.5
    so thin outlines are clearly visible at toolbar size."""
    raw = icon_path.read_bytes()
    svg_data = raw.replace(b"currentColor", color.encode())
    if b'stroke-width="2"' in raw and b'fill="none"' in raw:
        svg_data = svg_data.replace(b'stroke-width="2"', b'stroke-width="2.5"')
    pm = QPixmap()
    pm.loadFromData(svg_data, "SVG")
    return pm


def _load_icon(icon_key: str, mw: "MainWindow") -> QIcon:
    """Carica un'icona Lucide (o del set attivo) sostituendo currentColor con il
    colore testo corrente della palette, identico a _rebuild_toolbar()."""
    from PyQt6.QtGui import QPalette

    icon_file = _MD_ICON_FILES.get(icon_key, "")
    if not icon_file:
        return QIcon()

    icon_path = Path(__file__).parent.parent / "icons" / "lucide" / icon_file

    if not icon_path.exists():
        return QIcon()

    color = mw.palette().color(QPalette.ColorRole.WindowText).name()
    try:
        pm = render_svg_icon(icon_path, color)
        if not pm.isNull():
            return QIcon(pm)
    except Exception:
        pass
    return QIcon()


# ─── Toolbar ──────────────────────────────────────────────────────────────────

class LanguageToolbar:
    @staticmethod
    def install(main_window: "MainWindow") -> None:
        tb = _LanguageToolbarWidget(main_window)
        main_window._lang_toolbar = tb

        central = main_window.centralWidget()
        if central is not None and central.layout() is not None:
            central.layout().insertWidget(0, tb)
        else:
            from PyQt6.QtWidgets import QVBoxLayout
            old_central = main_window.centralWidget()
            container = QWidget(main_window)
            vbox = QVBoxLayout(container)
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.setSpacing(0)
            vbox.addWidget(tb)
            if old_central is not None:
                old_central.setParent(container)
                vbox.addWidget(old_central)
            main_window.setCentralWidget(container)

        main_window._tab_manager.current_editor_changed.connect(tb._on_editor_changed)

        from config.settings import Settings
        tb._user_hidden = not Settings.instance().get("view/lang_toolbar", False)

        editor = main_window._tab_manager.current_editor()
        tb._on_editor_changed(editor)


# ─── Widget toolbar ───────────────────────────────────────────────────────────

class _LanguageToolbarWidget(QWidget):
    visibilityChanged = pyqtSignal(bool)

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._mw = main_window
        self._current_lang: str = ""
        self._user_hidden: bool = False
        self._fl_conn = None
        self._lang_editor = None  # editor di cui stiamo ascoltando language_changed

        self.setObjectName("LanguageToolbar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 2, 4, 2)
        self._layout.setSpacing(2)

        self.setStyleSheet(self._make_stylesheet())

        self._layout.addStretch(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setVisible(False)

    def _make_stylesheet(self) -> str:
        return (
            "QWidget#LanguageToolbar {"
            "  background: palette(button);"
            "  border-bottom: 1px solid palette(mid);"
            "}"
            "QToolButton {"
            "  padding: 3px 5px;"
            "  border: none;"
            "  border-radius: 3px;"
            "}"
            "QToolButton:hover {"
            "  background-color: rgba(128, 128, 128, 50);"
            "}"
            "QToolButton:pressed {"
            "  background-color: rgba(0, 0, 0, 70);"
            "}"
            "QToolButton:checked {"
            "  background-color: rgba(128, 128, 128, 120);"
            "  border-radius: 3px;"
            "  font-weight: bold;"
            "}"
            "QToolButton::menu-button {"
            "  border-left: 1px solid rgba(128, 128, 128, 80);"
            "  width: 16px;"
            "}"
            "QToolButton::menu-indicator { image: none; }"
        )

    # ── setVisible ────────────────────────────────────────────────────────────

    def setVisible(self, visible: bool) -> None:
        super().setVisible(visible)
        self.visibilityChanged.emit(visible)

    # ── Visibilità ────────────────────────────────────────────────────────────

    def _on_menu_toggled(self, checked: bool) -> None:
        self._user_hidden = not checked
        if self._user_hidden:
            self.setVisible(False)
        else:
            editor = self._mw._tab_manager.current_editor()
            self._on_editor_changed(editor)

    def _on_editor_changed(self, editor: Optional["EditorWidget"]) -> None:
        # Disconnetti language_changed dal vecchio editor
        if self._lang_editor is not None:
            try:
                self._lang_editor.language_changed.disconnect(self._on_language_changed)
            except (RuntimeError, TypeError):
                pass
            self._lang_editor = None

        # Connetti language_changed al nuovo editor così la toolbar si aggiorna
        # anche quando il linguaggio cambia senza cambiare tab (es. nuovo file .md)
        if editor is not None:
            try:
                editor.language_changed.connect(self._on_language_changed)
                self._lang_editor = editor
            except Exception:
                pass

        self._update_for_editor(editor)

    def _on_language_changed(self, _lang: str) -> None:
        editor = self._mw._tab_manager.current_editor()
        self._update_for_editor(editor)

    def _update_for_editor(self, editor: Optional["EditorWidget"]) -> None:
        lang = ""
        if editor is not None:
            try:
                from editor.lexers import get_language_name
                lang = get_language_name(editor).lower()
            except Exception:
                pass

        self._current_lang = lang
        is_md  = "markdown" in lang
        _lw    = set(lang.split())
        is_tex = "latex" in lang or bool(_lw & {"tex", "bibtex", "plaintex"})

        if self._user_hidden or (not is_md and not is_tex):
            self.setVisible(False)
        else:
            self._rebuild(is_md=is_md, is_tex=is_tex)
            self.setVisible(True)

    # ── Costruzione ───────────────────────────────────────────────────────────

    def _add_separator(self) -> None:
        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setFixedWidth(6)
        self._layout.insertWidget(self._layout.count() - 1, sep)

    def _add_action_button(self, action: QAction) -> QToolButton:
        """Bottone da QAction esistente — sempre icon-only con tooltip automatico."""
        btn = QToolButton(self)
        btn.setDefaultAction(action)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        btn.setIconSize(_ICON_SIZE)
        self._layout.insertWidget(self._layout.count() - 1, btn)
        return btn

    def _add_icon_btn(self, icon_key: str, fallback_text: str,
                      tooltip: str, checkable: bool = False) -> QToolButton:
        """Bottone standalone con icona Lucide. Degrada a testo se icona assente."""
        btn = QToolButton(self)
        btn.setCheckable(checkable)
        btn.setToolTip(tooltip)
        btn.setIconSize(_ICON_SIZE)
        icon = _load_icon(icon_key, self._mw)
        if not icon.isNull():
            btn.setIcon(icon)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        else:
            btn.setText(fallback_text)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._layout.insertWidget(self._layout.count() - 1, btn)
        return btn

    def _clear_buttons(self) -> None:
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item and item.widget():
                w = item.widget()
                w.setParent(None)   # distrugge subito invece di schedulare

    def _rebuild(self, is_md: bool, is_tex: bool) -> None:
        if getattr(self, "_rebuilding", False):
            return
        self._rebuilding = True
        try:
            self._rebuild_inner(is_md=is_md, is_tex=is_tex)
        finally:
            self._rebuilding = False

    def _rebuild_inner(self, is_md: bool, is_tex: bool) -> None:
        if self._fl_conn is not None:
            try:
                self._mw._function_list_dock.visibilityChanged.disconnect(self._fl_conn)
            except (RuntimeError, TypeError):
                pass
            self._fl_conn = None
        self.setStyleSheet(self._make_stylesheet())
        self._clear_buttons()
        acts = self._mw._actions

        if is_md:
            self._add_md_actions(acts)
        elif is_tex:
            self._add_latex_actions(acts)

        self._add_separator()

        # Azioni comuni finali
        if "preview_toggle" in acts:
            self._add_action_button(acts["preview_toggle"])

        if hasattr(self._mw, "_function_list_dock"):
            tip = tr("action.lang_toolbar_structure", default="Struttura")
            btn_fl = self._add_icon_btn("md_structure", "𝑓", tip, checkable=True)
            btn_fl.setChecked(self._mw._function_list_dock.isVisible())
            btn_fl.toggled.connect(self._mw._function_list_dock.setVisible)
            self._fl_conn = lambda v, b=btn_fl: b.setChecked(v)
            self._mw._function_list_dock.visibilityChanged.connect(self._fl_conn)

        if "word_count" in acts:
            self._add_action_button(acts["word_count"])

        self.update()

    # ── Markdown ──────────────────────────────────────────────────────────────

    def _add_md_actions(self, acts: dict) -> None:
        # Intestazioni
        for level in (1, 2, 3):
            tip = tr(f"tooltip.lang_toolbar_h{level}", default=f"Heading {level}")
            btn = self._add_icon_btn(f"md_h{level}", f"H{level}", tip)
            btn.clicked.connect(lambda c, l=level: self._insert_md_heading(l))
        self._add_separator()

        # Formattazione inline
        for key in ("markup_bold", "markup_italic"):
            if key in acts:
                self._add_action_button(acts[key])
        tip = tr("tooltip.lang_toolbar_underline", default="Sottolineato")
        btn_u = self._add_icon_btn("md_underline", "U", tip)
        btn_u.clicked.connect(self._insert_md_underline)
        if "markup_strike" in acts:
            self._add_action_button(acts["markup_strike"])
        self._add_separator()

        # Blocchi
        tip = tr("tooltip.lang_toolbar_quote", default="Citazione")
        btn_q = self._add_icon_btn("md_quote", ">", tip)
        btn_q.clicked.connect(self._insert_md_quote)

        tip = tr("tooltip.lang_toolbar_code", default="Codice inline")
        btn_c = self._add_icon_btn("md_code", "`", tip)
        btn_c.clicked.connect(self._insert_md_code)

        tip = tr("tooltip.lang_toolbar_code_block", default="Blocco di codice")
        btn_cb = self._add_icon_btn("md_code_block", "```", tip)
        btn_cb.clicked.connect(self._insert_md_code_block)
        self._add_separator()

        # Liste
        tip = tr("tooltip.lang_toolbar_ul", default="Lista puntata")
        btn_ul = self._add_icon_btn("md_ul", "•", tip)
        btn_ul.clicked.connect(self._insert_md_ul)

        tip = tr("tooltip.lang_toolbar_ol", default="Lista numerata")
        btn_ol = self._add_icon_btn("md_ol", "1.", tip)
        btn_ol.clicked.connect(self._insert_md_ol)

        tip = tr("tooltip.lang_toolbar_task", default="Lista attività")
        btn_task = self._add_icon_btn("md_task", "☐", tip)
        btn_task.clicked.connect(self._insert_md_task)

        tip = tr("tooltip.lang_toolbar_hr", default="Linea orizzontale")
        btn_hr = self._add_icon_btn("md_hr", "—", tip)
        btn_hr.clicked.connect(self._insert_md_hr)
        self._add_separator()

        # Inserimenti
        self._add_md_table_menu_btn()

        tip = tr("action.lang_toolbar_link", default="Link") + "  Ctrl+Shift+K"
        btn_link = self._add_icon_btn("md_link", "🔗", tip)
        btn_link.clicked.connect(self._insert_md_link)
        btn_link.setShortcut(QKeySequence("Ctrl+Shift+K"))

        tip = tr("action.lang_toolbar_image", default="Immagine")
        btn_img = self._add_icon_btn("md_image", "🖼", tip)
        btn_img.clicked.connect(self._insert_md_image)
        self._add_separator()

        # Allineamento (HTML div)
        for key, fallback, tr_key, default, align in [
            ("md_align_left",   "▬▬▬", "action.lang_toolbar_align_left",   "Allinea a sinistra", "left"),
            ("md_align_center", "▬◀▬", "action.lang_toolbar_align_center",  "Centra",             "center"),
            ("md_align_right",  "▬▶", "action.lang_toolbar_align_right",   "Allinea a destra",   "right"),
        ]:
            tip = tr(tr_key, default=default)
            btn = self._add_icon_btn(key, fallback, tip)
            btn.clicked.connect(lambda c, a=align: self._insert_md_align(a))
        self._add_separator()

        # Allinea tabella
        if "align_table" in acts:
            self._add_action_button(acts["align_table"])
        self._add_separator()

        # Esporta
        tip = tr("action.lang_toolbar_export_pdf", default="Esporta come PDF")
        btn_pdf = self._add_icon_btn("md_export_pdf", "PDF", tip)
        btn_pdf.clicked.connect(self._export_pdf)

        tip = tr("action.lang_toolbar_export_html", default="Esporta come HTML")
        btn_html = self._add_icon_btn("md_export_html", "HTML", tip)
        btn_html.clicked.connect(self._export_html)

    # ── LaTeX ─────────────────────────────────────────────────────────────────

    def _add_latex_actions(self, acts: dict) -> None:
        # ── 1. Struttura documento ────────────────────────────────────────────
        self._add_latex_menu_btn(
            _get_latex_sections(), 2,
            tr("tooltip.latex_section_combo", default="Struttura sezione"),
            self._insert_latex_section,
        )
        self._add_latex_menu_btn(
            _get_latex_font_sizes(), 4,
            tr("tooltip.latex_size_combo", default="Dimensione testo"),
            self._insert_latex_fontsize,
        )
        self._add_separator()

        # ── 2. Formattazione inline ───────────────────────────────────────────
        for key in ("markup_bold", "markup_italic", "markup_strike"):
            if key in acts:
                self._add_action_button(acts[key])
        self._add_separator()

        # ── 3. Matematica ─────────────────────────────────────────────────────
        self._add_latex_math_menu_btn()
        self._add_separator()

        # ── 4. Inserimenti: immagine, tabella ─────────────────────────────────
        tip = tr("tooltip.latex_insert_image", default="Inserisci immagine")
        btn_img = self._add_icon_btn("latex_image", "🖼", tip)
        btn_img.clicked.connect(self._show_latex_insert_image)

        self._add_latex_table_menu_btn()
        if "align_table" in acts:
            self._add_action_button(acts["align_table"])
        self._add_separator()

        # ── 5. Avvolgi in ambiente ────────────────────────────────────────────
        self._add_latex_wrap_menu_btn()
        self._add_separator()

        # ── 6. Riferimenti: label, ref, nota, citazioni ───────────────────────
        tip = tr("tooltip.latex_label", default="\\label{}")
        btn_lbl = self._add_icon_btn("latex_label", "\\label", tip)
        btn_lbl.clicked.connect(self._insert_latex_label)

        tip = tr("tooltip.latex_ref", default="\\ref{}")
        btn_ref = self._add_icon_btn("latex_ref", "\\ref", tip)
        btn_ref.clicked.connect(self._insert_latex_ref)

        tip = tr("tooltip.latex_footnote", default="Nota a piè di pagina  \\footnote{}")
        btn_fn = self._add_icon_btn("latex_footnote", "FN", tip)
        btn_fn.clicked.connect(self._insert_latex_footnote)

        self._add_latex_cite_btn()
        self._add_separator()

        # ── 7. Build ──────────────────────────────────────────────────────────
        for key in ("compile", "run", "stop_build"):
            if key in acts:
                self._add_action_button(acts[key])

    # ── Helper menu-button LaTeX ──────────────────────────────────────────────

    def _add_latex_menu_btn(self, items: list[tuple[str, str]], default_idx: int,
                             tooltip: str, handler) -> QToolButton:
        """Split-button: bottone testo (azione corrente) + freccia separata (apre menu)."""
        container = QWidget(self)
        container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        hbox = QHBoxLayout(container)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(0)

        idx = default_idx if 0 <= default_idx < len(items) else 0
        _current = [items[idx][1]] if items else [""]

        # Bottone principale: mostra il nome dell'elemento corrente
        main_btn = QToolButton(container)
        main_btn.setToolTip(tooltip)
        main_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        main_btn.setText(items[idx][0] if items else "")
        main_btn.clicked.connect(lambda: handler(_current[0]))

        # Separatore visibile tra testo e freccia
        sep = QFrame(container)
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setFixedWidth(1)
        sep.setStyleSheet("QFrame { background: palette(mid); margin: 3px 0; }")

        # Bottone freccia: apre il menu di selezione
        arrow_btn = QToolButton(container)
        arrow_btn.setToolTip(tooltip)
        arrow_btn.setFixedWidth(16)
        arrow_icon = _load_icon("latex_chevron_down", self._mw)
        if not arrow_icon.isNull():
            arrow_btn.setIcon(arrow_icon)
            arrow_btn.setIconSize(QSize(10, 10))
            arrow_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        else:
            arrow_btn.setText("▾")
            arrow_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        arrow_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        def _on_select(lbl: str, cmd: str) -> None:
            main_btn.setText(lbl)
            _current[0] = cmd
            handler(cmd)

        menu = QMenu(arrow_btn)
        for label, cmd in items:
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False, _l=label, _c=cmd: _on_select(_l, _c))
        arrow_btn.setMenu(menu)

        hbox.addWidget(main_btn)
        hbox.addWidget(sep)
        hbox.addWidget(arrow_btn)
        self._layout.insertWidget(self._layout.count() - 1, container)
        return main_btn

    def _add_latex_cite_btn(self) -> QToolButton:
        """MenuButtonPopup: click principale = \\cite{}, freccia = varianti e bibliography."""
        label = tr("tooltip.latex_cite_combo", default="Cite / Bib")
        btn = QToolButton(self)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        btn.setToolTip(label)
        btn.setFixedWidth(95)
        btn.setText(label)
        btn.clicked.connect(lambda: self._dispatch_cite("cite"))

        menu = QMenu(btn)
        cite_entries = [
            (r"\cite{}",              "cite"),
            (r"\citet{}",             "citet"),
            (r"\citep{}",             "citep"),
            (r"\nocite{*}",           "nocite_all"),
            (r"\bibliography{}",      "bibliography"),
            (r"\bibliographystyle{}", "bibliographystyle"),
        ]
        for item_label, key in cite_entries:
            action = menu.addAction(item_label)
            action.triggered.connect(lambda checked=False, k=key: self._dispatch_cite(k))
        btn.setMenu(menu)
        self._layout.insertWidget(self._layout.count() - 1, btn)
        return btn

    def _add_latex_math_menu_btn(self) -> QToolButton:
        """MenuButtonPopup: click principale = inline math, freccia = altri modi."""
        btn = QToolButton(self)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        btn.setToolTip(tr("tooltip.latex_inline_math", default="Matematica inline  $…$"))
        icon = _load_icon("latex_math", self._mw)
        if icon.isNull():
            icon = _make_math_icon(self._mw)
        btn.setIcon(icon)
        btn.setIconSize(_ICON_SIZE)
        btn.setText("$")
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        btn.clicked.connect(self._insert_latex_inline_math)

        menu = QMenu(btn)
        menu.addAction(tr("action.latex_math_inline",   default="$…$  (inline)"),
                       self._insert_latex_inline_math)
        menu.addAction(tr("action.latex_math_display",  default="\\[…\\]  (blocco)"),
                       self._insert_latex_display_math)
        menu.addSeparator()
        menu.addAction(tr("action.latex_math_equation", default="\\begin{equation}"),
                       lambda: self._wrap_latex_env("equation"))
        menu.addAction(tr("action.latex_math_align",    default="\\begin{align}"),
                       lambda: self._wrap_latex_env("align"))
        menu.addAction(tr("action.latex_math_gather",   default="\\begin{gather}"),
                       lambda: self._wrap_latex_env("gather"))
        btn.setMenu(menu)
        self._layout.insertWidget(self._layout.count() - 1, btn)
        return btn

    def _add_latex_table_menu_btn(self) -> QToolButton:
        """MenuButtonPopup: click principale = inserisci tabella, freccia = modifica."""
        btn = QToolButton(self)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        btn.setText("Table")
        btn.setToolTip(tr("action.lang_toolbar_table", default="Tabella"))
        icon = _load_icon("latex_table", self._mw)
        if icon.isNull():
            icon = _load_icon("md_table", self._mw)
        if not icon.isNull():
            btn.setIcon(icon)
            btn.setIconSize(_ICON_SIZE)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        else:
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        btn.clicked.connect(self._show_latex_table_picker)

        menu = QMenu(btn)
        menu.addAction(tr("action.latex_insert_table", default="Inserisci tabella…"),
                       self._show_latex_table_picker)
        menu.addSeparator()
        for label, action, where in [
            (tr("tooltip.table_row_above",  default="Riga sopra"),          "row", "above"),
            (tr("tooltip.table_row_below",  default="Riga sotto"),          "row", "below"),
            (tr("tooltip.table_col_left",   default="Colonna sinistra"),    "col", "left"),
            (tr("tooltip.table_col_right",  default="Colonna destra"),      "col", "right"),
        ]:
            menu.addAction(label, lambda a=action, w=where: self._table_edit(a, w))
        menu.addSeparator()
        menu.addAction(tr("tooltip.table_delete_row", default="Elimina riga"),
                       lambda: self._table_edit("del_row", None))
        menu.addAction(tr("tooltip.table_delete_col", default="Elimina colonna"),
                       lambda: self._table_edit("del_col", None))
        btn.setMenu(menu)
        self._layout.insertWidget(self._layout.count() - 1, btn)
        return btn

    def _add_md_table_menu_btn(self) -> QToolButton:
        """MenuButtonPopup per Markdown: click = inserisci, freccia = modifica."""
        btn = QToolButton(self)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        btn.setText("Table")
        btn.setToolTip(tr("action.lang_toolbar_table", default="Tabella"))
        icon = _load_icon("md_table", self._mw)
        if not icon.isNull():
            btn.setIcon(icon)
            btn.setIconSize(_ICON_SIZE)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        else:
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        btn.clicked.connect(self._show_md_table_picker)

        menu = QMenu(btn)
        menu.addAction(tr("action.latex_insert_table", default="Inserisci tabella…"),
                       self._show_md_table_picker)
        menu.addSeparator()
        for label, action, where in [
            (tr("tooltip.table_row_above",  default="Riga sopra"),          "row", "above"),
            (tr("tooltip.table_row_below",  default="Riga sotto"),          "row", "below"),
            (tr("tooltip.table_col_left",   default="Colonna sinistra"),    "col", "left"),
            (tr("tooltip.table_col_right",  default="Colonna destra"),      "col", "right"),
        ]:
            menu.addAction(label, lambda a=action, w=where: self._table_edit(a, w))
        menu.addSeparator()
        menu.addAction(tr("tooltip.table_delete_row", default="Elimina riga"),
                       lambda: self._table_edit("del_row", None))
        menu.addAction(tr("tooltip.table_delete_col", default="Elimina colonna"),
                       lambda: self._table_edit("del_col", None))
        btn.setMenu(menu)
        self._layout.insertWidget(self._layout.count() - 1, btn)
        return btn

    def _add_latex_wrap_menu_btn(self) -> QToolButton:
        """MenuButtonPopup: click principale = avvolgi con l'ultimo ambiente usato, freccia = scegli."""
        btn = QToolButton(self)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        btn.setText(tr("tooltip.latex_wrap_menu", default="Wrap in environment"))
        btn.setToolTip(tr("tooltip.latex_wrap_menu", default="Avvolgi in ambiente"))
        _last_env = ["center"]
        btn.clicked.connect(lambda: self._wrap_latex_env(_last_env[0]))

        def _wrap(env: str) -> None:
            _last_env[0] = env
            self._wrap_latex_env(env)

        menu = QMenu(btn)
        menu.addAction("center  (↔)",      lambda: _wrap("center"))
        menu.addAction("flushleft  (←)",   lambda: _wrap("flushleft"))
        menu.addAction("flushright  (→)",  lambda: _wrap("flushright"))
        menu.addSeparator()
        menu.addAction("figure",           lambda: _wrap("figure"))
        menu.addAction("table",            lambda: _wrap("table"))
        menu.addAction("minipage",         lambda: _wrap("minipage"))
        menu.addAction("multicols",        lambda: _wrap("multicols"))
        menu.addSeparator()
        menu.addAction("framed",           lambda: _wrap("framed"))
        menu.addAction("verbatim",         lambda: _wrap("verbatim"))
        menu.addSeparator()
        menu.addAction(tr("action.latex_wrap_custom", default="Personalizzato…"),
                       self._latex_wrap_custom)
        btn.setMenu(menu)
        self._layout.insertWidget(self._layout.count() - 1, btn)
        return btn

    def _dispatch_cite(self, key: str) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        if key == "cite":
            self._latex_cite_dialog(editor, r"\cite")
        elif key == "citet":
            self._latex_cite_dialog(editor, r"\citet")
        elif key == "citep":
            self._latex_cite_dialog(editor, r"\citep")
        elif key == "nocite_all":
            self._latex_insert_raw(editor, r"\nocite{*}")
        elif key == "bibliography":
            self._latex_bibliography_dialog(editor)
        elif key == "bibliographystyle":
            self._latex_bibliographystyle_dialog(editor)
        editor.setFocus()

    # ── Handler LaTeX — sezioni ───────────────────────────────────────────────

    def _insert_latex_section(self, cmd: str) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        sel = editor.selectedText()
        editor.beginUndoAction()
        if sel:
            editor.replaceSelectedText(f"{cmd}{{{sel}}}")
        else:
            line, col = editor.getCursorPosition()
            editor.insert(f"{cmd}{{}}")
            editor.setCursorPosition(line, col + len(cmd) + 1)
        editor.endUndoAction()
        editor.setFocus()

    # ── Handler LaTeX — matematica ───────────────────────────────────────────

    def _insert_latex_inline_math(self) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        sel = editor.selectedText()
        editor.beginUndoAction()
        if sel:
            editor.replaceSelectedText(f"${sel}$")
        else:
            line, col = editor.getCursorPosition()
            editor.insert("$$")
            editor.setCursorPosition(line, col + 1)
        editor.endUndoAction()
        editor.setFocus()

    def _insert_latex_display_math(self) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        sel = editor.selectedText()
        editor.beginUndoAction()
        if sel:
            editor.replaceSelectedText(f"\\[\n    {sel}\n\\]")
        else:
            line, _ = editor.getCursorPosition()
            editor.insert("\\[\n    \n\\]")
            editor.setCursorPosition(line + 1, 4)
        editor.endUndoAction()
        editor.setFocus()

    # ── Handler LaTeX — riferimenti ───────────────────────────────────────────

    def _insert_latex_label(self) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        key, ok = QInputDialog.getText(
            self._mw,
            tr("tooltip.latex_label", default="\\label{}"),
            tr("action.lang_toolbar_label_key", default="Chiave label:"),
        )
        if not ok:
            return
        self._latex_insert_raw(editor, f"\\label{{{key.strip()}}}")
        editor.setFocus()

    def _insert_latex_ref(self) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        key, ok = QInputDialog.getText(
            self._mw,
            tr("tooltip.latex_ref", default="\\ref{}"),
            tr("action.lang_toolbar_ref_key", default="Chiave di riferimento:"),
        )
        if not ok:
            return
        self._latex_insert_raw(editor, f"\\ref{{{key.strip()}}}")
        editor.setFocus()

    def _latex_wrap_custom(self) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        env, ok = QInputDialog.getText(
            self._mw,
            tr("action.lang_toolbar_begin_env", default="Inizio ambiente"),
            tr("action.lang_toolbar_env_name",  default="Nome ambiente:"),
        )
        if ok and env.strip():
            self._wrap_latex_env(env.strip())
        editor.setFocus()

    # ── Handler LaTeX — dimensione testo ──────────────────────────────────────

    def _insert_latex_fontsize(self, cmd: str) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        sel = editor.selectedText()
        editor.beginUndoAction()
        if sel:
            editor.replaceSelectedText(f"{{{cmd} {sel}}}")
        else:
            line, col = editor.getCursorPosition()
            snippet = f"{{{cmd} }}"
            editor.insert(snippet)
            editor.setCursorPosition(line, col + len(cmd) + 2)
        editor.endUndoAction()
        editor.setFocus()

    # ── Handler LaTeX — nota e citazioni ──────────────────────────────────────

    def _insert_latex_footnote(self) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        sel = editor.selectedText()
        editor.beginUndoAction()
        if sel:
            editor.replaceSelectedText(f"\\footnote{{{sel}}}")
        else:
            line, col = editor.getCursorPosition()
            editor.insert(r"\footnote{}")
            editor.setCursorPosition(line, col + len(r"\footnote{"))
        editor.endUndoAction()
        editor.setFocus()

    def _latex_cite_dialog(self, editor, cmd: str) -> None:
        key, ok = QInputDialog.getText(
            self._mw,
            tr("tooltip.latex_cite_combo", default="Cita / Bib"),
            tr("action.lang_toolbar_cite_key", default="Chiave di citazione:"),
        )
        if not ok or not key.strip():
            return
        sel = editor.selectedText()
        editor.beginUndoAction()
        if sel:
            editor.replaceSelectedText(f"{cmd}[{sel}]{{{key.strip()}}}")
        else:
            line, col = editor.getCursorPosition()
            snippet = f"{cmd}{{{key.strip()}}}"
            editor.insert(snippet)
            editor.setCursorPosition(line, col + len(snippet))
        editor.endUndoAction()

    def _latex_bibliography_dialog(self, editor) -> None:
        name, ok = QInputDialog.getText(
            self._mw,
            tr("action.lang_toolbar_bibliography", default="Bibliografia"),
            tr("action.lang_toolbar_bib_file", default="Nome file .bib (senza estensione):"),
        )
        if not ok or not name.strip():
            return
        self._latex_insert_raw(editor, f"\\bibliography{{{name.strip()}}}")

    def _latex_bibliographystyle_dialog(self, editor) -> None:
        from PyQt6.QtWidgets import QInputDialog
        styles = ["plain", "alpha", "abbrv", "unsrt", "apalike", "ieeetr", "acm", "siam"]
        style, ok = QInputDialog.getItem(
            self._mw,
            tr("action.lang_toolbar_bibliographystyle", default="Stile bibliografia"),
            tr("action.lang_toolbar_bib_style", default="Stile:"),
            styles, 0, True,
        )
        if not ok or not style.strip():
            return
        self._latex_insert_raw(editor, f"\\bibliographystyle{{{style.strip()}}}")

    def _latex_insert_raw(self, editor, snippet: str) -> None:
        editor.beginUndoAction()
        line, col = editor.getCursorPosition()
        editor.insert(snippet)
        editor.setCursorPosition(line, col + len(snippet))
        editor.endUndoAction()

    # ── Handler Markdown — intestazioni ──────────────────────────────────────

    def _insert_md_heading(self, level: int) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        import re
        line, col = editor.getCursorPosition()
        line_text = editor.text(line)
        m = re.match(r'^(#{1,6})\s+(.*)', line_text.rstrip('\n'))
        prefix = '#' * level + ' '
        if m:
            content = m.group(2)
            new_line = content if len(m.group(1)) == level else prefix + content
        else:
            new_line = prefix + line_text.rstrip('\n')
        editor.beginUndoAction()
        editor.setSelection(line, 0, line, len(line_text.rstrip('\n')))
        editor.replaceSelectedText(new_line)
        editor.setCursorPosition(line, min(col, len(new_line)))
        editor.endUndoAction()
        editor.setFocus()

    # ── Handler Markdown — formattazione inline ───────────────────────────────

    def _insert_md_underline(self) -> None:
        self._wrap_md_inline("<u>", "</u>")

    def _insert_md_code(self) -> None:
        self._wrap_md_inline("`", "`")

    def _wrap_md_inline(self, open_: str, close_: str) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        sel = editor.selectedText()
        if sel:
            editor.replaceSelectedText(f"{open_}{sel}{close_}")
        else:
            line, col = editor.getCursorPosition()
            editor.insert(f"{open_}{close_}")
            editor.setCursorPosition(line, col + len(open_))
        editor.setFocus()

    # ── Handler Markdown — blocchi ────────────────────────────────────────────

    def _insert_md_code_block(self) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        sel = editor.selectedText()
        editor.beginUndoAction()
        if sel:
            editor.replaceSelectedText(f"```\n{sel}\n```")
        else:
            line, _ = editor.getCursorPosition()
            editor.insert("```\n\n```")
            editor.setCursorPosition(line + 1, 0)
        editor.endUndoAction()
        editor.setFocus()

    def _insert_md_quote(self) -> None:
        self._prefix_lines("> ")

    # ── Handler Markdown — liste ──────────────────────────────────────────────

    def _insert_md_ul(self) -> None:
        self._prefix_lines("- ")

    def _insert_md_ol(self) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        sel = editor.selectedText()
        editor.beginUndoAction()
        if sel:
            lines = sel.split('\n')
            editor.replaceSelectedText('\n'.join(f"{i+1}. {l}" for i, l in enumerate(lines)))
        else:
            line, col = editor.getCursorPosition()
            txt = editor.text(line).rstrip('\n')
            editor.setSelection(line, 0, line, len(txt))
            editor.replaceSelectedText(f"1. {txt}")
            editor.setCursorPosition(line, col + 3)
        editor.endUndoAction()
        editor.setFocus()

    def _insert_md_task(self) -> None:
        self._prefix_lines("- [ ] ")

    def _insert_md_hr(self) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        line, _ = editor.getCursorPosition()
        editor.beginUndoAction()
        editor.setSelection(line, 0, line, len(editor.text(line).rstrip('\n')))
        editor.replaceSelectedText("\n---\n")
        editor.setCursorPosition(line + 2, 0)
        editor.endUndoAction()
        editor.setFocus()

    def _prefix_lines(self, prefix: str) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        sel = editor.selectedText()
        editor.beginUndoAction()
        if sel:
            lines = sel.split('\n')
            editor.replaceSelectedText('\n'.join(prefix + l for l in lines))
        else:
            line, col = editor.getCursorPosition()
            txt = editor.text(line).rstrip('\n')
            editor.setSelection(line, 0, line, len(txt))
            editor.replaceSelectedText(f"{prefix}{txt}")
            editor.setCursorPosition(line, col + len(prefix))
        editor.endUndoAction()
        editor.setFocus()

    # ── Handler Markdown — link e immagine ────────────────────────────────────

    def _insert_md_link(self) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        sel = editor.selectedText()
        url, ok = QInputDialog.getText(
            self._mw,
            tr("action.lang_toolbar_insert_link", default="Inserisci link"),
            tr("action.lang_toolbar_url", default="URL:"),
            text="https://"
        )
        if not ok or not url.strip():
            return
        if sel:
            editor.replaceSelectedText(f"[{sel}]({url.strip()})")
        else:
            text_label, ok2 = QInputDialog.getText(
                self._mw,
                tr("action.lang_toolbar_insert_link", default="Inserisci link"),
                tr("action.lang_toolbar_link_text", default="Testo del link:"),
                text=tr("action.lang_toolbar_link_default", default="link")
            )
            if not ok2:
                return
            line, col = editor.getCursorPosition()
            editor.insert(f"[{text_label}]({url.strip()})")
            editor.setCursorPosition(line, col + len(text_label) + 4 + len(url.strip()))
        editor.setFocus()

    def _insert_md_image(self) -> None:
        from PyQt6.QtWidgets import QFileDialog, QCheckBox
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        path, _ = QFileDialog.getOpenFileName(
            self._mw,
            tr("action.lang_toolbar_select_image", default="Seleziona immagine"),
            "",
            tr("action.lang_toolbar_image_filter",
               default="Immagini (*.png *.jpg *.jpeg *.gif *.svg *.webp);;Tutti i file (*)")
        )
        if not path:
            return
        try:
            if editor.file_path:
                rel = Path(path).relative_to(editor.file_path.parent)
                path = str(rel)
        except ValueError:
            pass

        sel = editor.selectedText()
        default_alt = sel if sel else tr("action.lang_toolbar_image_alt", default="immagine")

        # Dialog dimensioni
        dlg = QDialog(self._mw)
        dlg.setWindowTitle(tr("action.lang_toolbar_image_options", default="Inserisci immagine"))
        dlg.setMinimumWidth(340)
        form = QFormLayout(dlg)
        form.setContentsMargins(12, 12, 12, 8)
        form.setSpacing(8)

        _path_lbl = QLabel(Path(path).name)
        _path_lbl.setStyleSheet("color: gray; font-size: 11px;")
        form.addRow("File:", _path_lbl)

        _alt = QLineEdit(default_alt)
        form.addRow(tr("action.lang_toolbar_image_alt_label", default="Testo alt:"), _alt)

        _width = QLineEdit()
        _width.setPlaceholderText(tr("action.lang_toolbar_image_size_hint", default="es. 400 oppure 80%"))
        form.addRow(tr("action.lang_toolbar_image_width", default="Larghezza:"), _width)

        _prop = QCheckBox(tr("action.lang_toolbar_image_proportional",
                             default="Mantieni proporzioni (altezza automatica)"))
        _prop.setChecked(True)
        form.addRow("", _prop)

        _height_label = QLabel(tr("action.lang_toolbar_image_height", default="Altezza:"))
        _height = QLineEdit()
        _height.setPlaceholderText(tr("action.lang_toolbar_image_size_hint", default="es. 400 oppure 80%"))
        _height_label.setVisible(False)
        _height.setVisible(False)
        form.addRow(_height_label, _height)

        def _on_prop_toggled(checked: bool) -> None:
            _height_label.setVisible(not checked)
            _height.setVisible(not checked)
            dlg.adjustSize()

        _prop.toggled.connect(_on_prop_toggled)

        _note = QLabel(tr("action.lang_toolbar_image_size_note",
                          default="⚠ Con dimensioni specificate viene inserito HTML (<img>): "
                                  "non tutti i renderer Markdown supportano questo formato."))
        _note.setStyleSheet("color: gray; font-size: 11px;")
        _note.setWordWrap(True)
        form.addRow("", _note)

        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        bbox.accepted.connect(dlg.accept)
        bbox.rejected.connect(dlg.reject)
        form.addRow(bbox)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            editor.setFocus()
            return

        alt   = _alt.text().strip() or default_alt
        width = _width.text().strip()
        proportional = _prop.isChecked()
        height = "" if proportional else _height.text().strip()

        if width or height:
            w_attr = f' width="{width}"'   if width  else ""
            h_attr = f' height="{height}"' if height else ""
            snippet = f'<img src="{path}" alt="{alt}"{w_attr}{h_attr}>'
        else:
            snippet = f"![{alt}]({path})"

        if sel:
            editor.replaceSelectedText(snippet)
        else:
            line, col = editor.getCursorPosition()
            editor.insert(snippet)
            editor.setCursorPosition(line, col + len(snippet))
        editor.setFocus()

    # ── Handler Markdown — allineamento ──────────────────────────────────────

    def _insert_md_align(self, align: str) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        sel = editor.selectedText()
        if sel:
            editor.replaceSelectedText(f'<div align="{align}">{sel}</div>')
        else:
            line, col = editor.getCursorPosition()
            tag = f'<div align="{align}"></div>'
            editor.insert(tag)
            editor.setCursorPosition(line, col + len(tag) - len("</div>"))
        editor.setFocus()

    # ── Handler picker tabella ────────────────────────────────────────────────

    def _show_md_table_picker(self) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        from ui.table_grid_picker import TableGridPicker
        TableGridPicker.show_for_editor(editor, is_latex=False, parent=self._mw, pos=QCursor.pos())

    def _show_latex_table_picker(self) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        from ui.table_grid_picker import TableGridPicker
        TableGridPicker.show_for_editor(editor, is_latex=True, parent=self._mw, pos=QCursor.pos())

    # ── Handler Markdown — export ──────────────────────────────────────────

    def _export_html(self) -> None:
        """Esporta il documento Markdown corrente in HTML."""
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        try:
            import markdown as md_lib
        except ImportError:
            QMessageBox.warning(
                self._mw,
                tr("action.lang_toolbar_export_html", default="Esporta come HTML"),
                tr("error.markdown_missing",
                   default="Libreria 'markdown' non installata.\nInstalla con: pip install markdown")
            )
            return
        default_name = ""
        if editor.file_path:
            default_name = str(editor.file_path.with_suffix(".html"))
        path, _ = QFileDialog.getSaveFileName(
            self._mw,
            tr("action.lang_toolbar_export_html", default="Esporta come HTML"),
            default_name,
            "HTML (*.html *.htm);;Tutti i file (*)"
        )
        if not path:
            return
        content = editor.text()
        html_body = md_lib.markdown(
            content,
            extensions=["tables", "fenced_code", "toc", "nl2br"]
        )
        html_full = (
            "<!DOCTYPE html>\n"
            "<html lang=\"it\">\n"
            "<head>\n"
            "  <meta charset=\"UTF-8\">\n"
            "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"  <title>{Path(path).stem}</title>\n"
            "  <style>\n"
            "    body { font-family: sans-serif; max-width: 860px; margin: 2em auto;"
            " padding: 0 1em; line-height: 1.6; }\n"
            "    pre { background: #f4f4f4; padding: 1em; overflow-x: auto; }\n"
            "    code { background: #f4f4f4; padding: .15em .3em; border-radius: 3px; }\n"
            "    blockquote { border-left: 4px solid #ccc; margin-left: 0; padding-left: 1em; color: #555; }\n"
            "    table { border-collapse: collapse; } td, th { border: 1px solid #ccc; padding: .4em .8em; }\n"
            "  </style>\n"
            "</head>\n"
            "<body>\n"
            f"{html_body}\n"
            "</body>\n"
            "</html>\n"
        )
        try:
            Path(path).write_text(html_full, encoding="utf-8")
        except Exception as exc:
            QMessageBox.critical(
                self._mw,
                tr("action.lang_toolbar_export_html", default="Esporta come HTML"),
                str(exc)
            )

    def _export_pdf(self) -> None:
        """Esporta il documento Markdown corrente in PDF tramite QPrinter."""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        try:
            self._export_pdf_impl()
        except Exception as _top_exc:
            import traceback
            QMessageBox.critical(
                self._mw,
                "Esporta come PDF – errore interno",
                traceback.format_exc()
            )

    def _export_pdf_impl(self) -> None:
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            QMessageBox.warning(
                self._mw,
                "Esporta come PDF",
                "Nessun documento aperto.\n\n(Nota: se sei su un tab spreadsheet o richtext, usa il pulsante 'Esporta PDF' di quel tab)"
            )
            return
        try:
            import markdown as md_lib
        except ImportError:
            QMessageBox.warning(
                self._mw,
                tr("action.lang_toolbar_export_pdf", default="Esporta come PDF"),
                tr("error.markdown_missing",
                   default="Libreria 'markdown' non installata.\nInstalla con: pip install markdown")
            )
            return
        from pathlib import Path as _Path
        if editor.file_path:
            default_name = str(editor.file_path.with_suffix(""))
        else:
            default_name = str(_Path.home() / "documento")
        path, _ = QFileDialog.getSaveFileName(
            self._mw,
            tr("action.lang_toolbar_export_pdf", default="Esporta come PDF"),
            default_name,
            "PDF (*.pdf);;Tutti i file (*)"
        )
        if not path:
            return
        # Aggiunge .pdf se l'utente non ha specificato un'estensione
        _p = _Path(path)
        if _p.suffix.lower() != ".pdf":
            path = str(_p.with_suffix(".pdf"))
        content = editor.text()
        _base_dir = editor.file_path.parent if editor.file_path else _Path.home()
        import re as _re

        # Risolvi percorsi relativi → assoluti e converti width/height % in style CSS
        # (percentuali come style= funzionano correttamente in WebEngine;
        #  per il fallback QTextDocument verranno convertite in px separatamente)
        def _fix_img_paths(tag):
            src_m = _re.search(r'src=["\']([^"\']+)["\']', tag)
            if src_m:
                src = src_m.group(1)
                if not src.startswith(('http://', 'https://', 'data:', '/')):
                    abs_src = str((_base_dir / src).resolve())
                    tag = tag[:src_m.start(1)] + abs_src + tag[src_m.end(1):]
            return tag

        def _fix_img_pct_to_style(tag):
            styles = []
            for attr in ('width', 'height'):
                pat = _re.compile(rf'\b{attr}=["\']?(\d+(?:\.\d+)?)%["\']?', _re.IGNORECASE)
                hit = pat.search(tag)
                if hit:
                    styles.append(f'{attr}:{hit.group(1)}%')
                    tag = pat.sub('', tag)
            if styles:
                existing = _re.search(r'style=["\']([^"\']*)["\']', tag)
                if existing:
                    merged = existing.group(1).rstrip(';') + ';' + ';'.join(styles)
                    tag = _re.sub(r'style=["\']([^"\']*)["\']', f'style="{merged}"', tag)
                else:
                    tag = tag.rstrip('>').rstrip('/') + ' style="' + ';'.join(styles) + '">'
            return tag

        def _fix_img_pct_to_px(tag, page_px):
            for attr in ('width', 'height'):
                pat = _re.compile(rf'\b{attr}=["\']?(\d+(?:\.\d+)?)%["\']?', _re.IGNORECASE)
                hit = pat.search(tag)
                if hit:
                    px = max(1, int(page_px * float(hit.group(1)) / 100))
                    tag = pat.sub(f'{attr}="{px}"', tag)
            return tag

        # HTML per WebEngine: percorsi assoluti + % come style CSS
        def _make_html(body):
            return (
                "<!DOCTYPE html><html><head>"
                "<meta charset=\"UTF-8\">"
                "<style>"
                "body{font-family:sans-serif;font-size:11pt;line-height:1.6;margin:0;}"
                "img{max-width:100%;height:auto;}"
                "pre{background:#f4f4f4;padding:.8em;overflow-x:auto;}"
                "code{background:#f4f4f4;padding:.1em .3em;border-radius:3px;}"
                "blockquote{border-left:4px solid #ccc;margin-left:0;padding-left:1em;color:#555;}"
                "table{border-collapse:collapse;}td,th{border:1px solid #ccc;padding:.3em .6em;}"
                "</style></head><body>"
                f"{body}"
                "</body></html>"
            )

        from PyQt6.QtGui import QPageLayout as _QPageLayout
        from PyQt6.QtCore import QMarginsF as _QMarginsF
        _page_layout = self._mw._printer.pageLayout()
        # Margini estratti in mm dal page setup; minimo 20mm se non configurati
        _m = _page_layout.margins(_QPageLayout.Unit.Millimeter)
        _D = 20.0
        _mt = _m.top()    if _m.top()    > 5 else _D
        _mr = _m.right()  if _m.right()  > 5 else _D
        _mb = _m.bottom() if _m.bottom() > 5 else _D
        _ml = _m.left()   if _m.left()   > 5 else _D
        # QPageLayout con i margini effettivi — passato direttamente a printToPdf
        _effective_layout = _QPageLayout(
            _page_layout.pageSize(),
            _page_layout.orientation(),
            _QMarginsF(_ml, _mt, _mr, _mb),
            _QPageLayout.Unit.Millimeter,
        )

        # Pre-stash raw HTML <img> tags prima della conversione markdown: python-markdown
        # può escaparle (convertendo < in &lt;) se non le riconosce come blocco HTML.
        _img_stash: list[str] = []

        def _stash_img(m: '_re.Match[str]') -> str:
            _img_stash.append(m.group(0))
            return f'<!-- __npq_img_{len(_img_stash) - 1}__ -->'

        content_stashed = _re.sub(r'<img\b[^>]*>', _stash_img, content, flags=_re.IGNORECASE)

        html_body = md_lib.markdown(
            content_stashed,
            extensions=["tables", "fenced_code", "toc", "nl2br"]
        )

        # Ripristina le <img> stashate con percorsi assoluti (solo path, non style).
        # La conversione width%→style/px viene fatta dai _re.sub successivi,
        # così sia il path WebEngine che il fallback QTextDocument la ricevono corretta.
        for _si, _stag in enumerate(_img_stash):
            html_body = html_body.replace(
                f'<!-- __npq_img_{_si}__ -->',
                _fix_img_paths(_stag)
            )

        # Applica le fix anche alle <img> generate da sintassi markdown ![](src)
        html_body_fixed = _re.sub(
            r'<img\b[^>]*>',
            lambda m: _fix_img_pct_to_style(_fix_img_paths(m.group(0))),
            html_body, flags=_re.IGNORECASE
        )
        html_full = _make_html(html_body_fixed)

        _exported = False
        _err_msg = ""
        _pandoc_args = [
            "-V", f"geometry:top={_mt}mm,bottom={_mb}mm,left={_ml}mm,right={_mr}mm",
        ]

        # Primario: QWebEngineView — preserva nl2br e formattazione HTML del Markdown
        if not _exported:
            try:
                from PyQt6.QtWebEngineWidgets import QWebEngineView
                from PyQt6.QtCore import QUrl, QEventLoop
                _we_ok = [False]
                from core.webengine import safe_webview as _swv
                view = _swv()
                if view is None:
                    raise RuntimeError("GL not available")
                base_url = QUrl.fromLocalFile(str(_base_dir) + "/")
                view.setHtml(html_full, base_url)

                def _on_load(ok):
                    if ok:
                        loop2 = QEventLoop()
                        def _pdf_done(pdf_data):
                            if pdf_data:
                                try:
                                    _Path(path).write_bytes(bytes(pdf_data))
                                    _we_ok[0] = True
                                except Exception:
                                    pass
                            loop2.quit()
                        view.page().printToPdf(_pdf_done, _effective_layout)
                        loop2.exec()
                    view.deleteLater()

                loop = QEventLoop()
                view.loadFinished.connect(_on_load)
                view.loadFinished.connect(lambda _: loop.quit())
                loop.exec()
                _exported = _we_ok[0]
            except Exception as exc:
                _err_msg = str(exc)

        if not _exported:
            # Fallback 2: QTextDocument
            try:
                from PyQt6.QtPrintSupport import QPrinter
                from PyQt6.QtGui import QTextDocument
                from PyQt6.QtCore import QUrl
                _pl_mm = _page_layout.paintRect(_QPageLayout.Unit.Millimeter).width()
                _usable_px = max(200, int(_pl_mm * 96 / 25.4))
                html_body_px = _re.sub(
                    r'<img\b[^>]*>',
                    lambda m: _fix_img_pct_to_px(_fix_img_paths(m.group(0)), _usable_px),
                    html_body, flags=_re.IGNORECASE
                )
                printer = QPrinter(QPrinter.PrinterMode.HighResolution)
                printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
                printer.setOutputFileName(path)
                printer.setPageLayout(_effective_layout)
                doc = QTextDocument()
                doc.setBaseUrl(QUrl.fromLocalFile(str(_base_dir) + "/"))
                doc.setHtml(_make_html(html_body_px))
                doc.print(printer)
                _exported = True
            except Exception as _e:
                _err_msg = str(_e)

        if not _exported:
            # Fallback 3: pandoc (via pypandoc o subprocess)
            try:
                import pypandoc as _pypandoc
                _pypandoc.convert_text(
                    content, "pdf", format="markdown+hard_line_breaks",
                    outputfile=path, extra_args=_pandoc_args
                )
                _exported = True
            except Exception:
                pass
        if not _exported:
            import subprocess as _sp, shutil as _sh
            if _sh.which("pandoc"):
                try:
                    import tempfile as _tf, os as _os2
                    with _tf.NamedTemporaryFile(suffix=".md", delete=False,
                                               mode="w", encoding="utf-8") as _tf_md:
                        _tf_md.write(content)
                        _tf_md_path = _tf_md.name
                    try:
                        _r = _sp.run(
                            ["pandoc", _tf_md_path, "-o", path,
                             "--from=markdown+hard_line_breaks"] + _pandoc_args,
                            capture_output=True, text=True
                        )
                        if _r.returncode == 0:
                            _exported = True
                        else:
                            _err_msg = _r.stderr.strip()
                    finally:
                        _os2.unlink(_tf_md_path)
                except Exception as _e:
                    _err_msg = str(_e)

        if _exported:
            import os as _os
            if _os.path.exists(path) and _os.path.getsize(path) > 0:
                QMessageBox.information(
                    self._mw,
                    tr("action.lang_toolbar_export_pdf"),
                    tr("msg.export_pdf_ok", path=path)
                )
            else:
                QMessageBox.warning(
                    self._mw,
                    tr("action.lang_toolbar_export_pdf"),
                    tr("msg.export_pdf_empty", path=path)
                )
        else:
            QMessageBox.critical(
                self._mw,
                tr("action.lang_toolbar_export_pdf"),
                _err_msg or tr("msg.export_pdf_failed")
            )

    # ── Handler LaTeX ─────────────────────────────────────────────────────────

    def _wrap_latex_env(self, env: str) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        editor.beginUndoAction()
        if editor.hasSelectedText():
            text = editor.selectedText()
            indented = "\n".join("    " + l for l in text.split("\n"))
            editor.replaceSelectedText(f"\\begin{{{env}}}\n{indented}\n\\end{{{env}}}")
        else:
            line, _ = editor.getCursorPosition()
            editor.insert(f"\\begin{{{env}}}\n    \n\\end{{{env}}}")
            editor.setCursorPosition(line + 1, 4)
        editor.endUndoAction()
        editor.setFocus()

    def _latex_begin(self) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        env, ok = QInputDialog.getText(
            self._mw,
            tr("action.lang_toolbar_begin_env", default="Inizio ambiente"),
            tr("action.lang_toolbar_env_name", default="Nome ambiente:")
        )
        if ok and env.strip():
            editor.insert(f"\\begin{{{env.strip()}}}")
        editor.setFocus()

    def _latex_end(self) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        env, ok = QInputDialog.getText(
            self._mw,
            tr("action.lang_toolbar_end_env", default="Fine ambiente"),
            tr("action.lang_toolbar_env_name", default="Nome ambiente:")
        )
        if ok and env.strip():
            editor.insert(f"\\end{{{env.strip()}}}")
        editor.setFocus()

    def _show_latex_insert_image(self) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        from ui.latex_insert_image_dialog import LatexInsertImageDialog
        base_dir = editor.file_path.parent if editor.file_path else None
        dlg = LatexInsertImageDialog(parent=self._mw, base_dir=base_dir)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            editor.setFocus()
            return
        code = dlg.get_latex_code()
        if not code:
            editor.setFocus()
            return

        self._ensure_latex_package(editor, "graphicx")

        if editor.hasSelectedText():
            editor.replaceSelectedText(code)
        else:
            line, col = editor.getCursorPosition()
            editor.insert(code)
            editor.setCursorPosition(line, col + len(code.split("\n")[0]))
        editor.setFocus()

    # ── Bottoni editing tabella ───────────────────────────────────────────────

    def _add_table_edit_buttons(self) -> None:
        """Aggiunge i 6 bottoni griglia-stile-TeXstudio per editing tabelle."""
        actions = [
            ("row_above", tr("tooltip.table_row_above",   default="Inserisci riga sopra"),    "above", "row"),
            ("row_below", tr("tooltip.table_row_below",   default="Inserisci riga sotto"),     "below", "row"),
            ("col_left",  tr("tooltip.table_col_left",    default="Inserisci colonna sinistra"), "left",  "col"),
            ("col_right", tr("tooltip.table_col_right",   default="Inserisci colonna destra"),  "right", "col"),
            ("del_row",   tr("tooltip.table_delete_row",  default="Elimina riga"),              None,    "del_row"),
            ("del_col",   tr("tooltip.table_delete_col",  default="Elimina colonna"),           None,    "del_col"),
        ]
        for key, tip, where, action in actions:
            btn = QToolButton(self)
            btn.setToolTip(tip)
            btn.setIconSize(_ICON_SIZE)
            icon = _make_table_icon(key, self._mw)
            if not icon.isNull():
                btn.setIcon(icon)
                btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            else:
                btn.setText(_TABLE_BTN_TEXT[key])
                btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            btn.clicked.connect(lambda c, w=where, a=action: self._table_edit(a, w))
            self._layout.insertWidget(self._layout.count() - 1, btn)

    def _table_edit(self, action: str, where: Optional[str]) -> None:
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        from editor import table_editor as te
        if action == "row":
            ok = te.add_row(editor, where)
        elif action == "col":
            ok = te.add_column(editor, where)
        elif action == "del_row":
            ok = te.delete_row(editor)
        else:
            ok = te.delete_column(editor)
        if not ok:
            if hasattr(self._mw, "statusBar"):
                self._mw.statusBar().showMessage(
                    tr("msg.cursor_not_in_table", default="Posiziona il cursore all'interno di una tabella"), 3000
                )
        editor.setFocus()

    @staticmethod
    def _ensure_latex_package(editor: "EditorWidget", package: str) -> None:
        """Inserisce \\usepackage{package} nel preambolo se non già presente."""
        import re
        text = editor.text()
        if re.search(r'\\usepackage\s*(?:\[[^\]]*\]\s*)?\{' + re.escape(package) + r'\}', text):
            return
        # Cerca l'ultima riga \usepackage nel preambolo; fallback: prima di \begin{document}
        insert_pos = -1
        for m in re.finditer(r'\\usepackage\s*(?:\[[^\]]*\]\s*)?\{[^}]+\}', text):
            insert_pos = m.end()
        if insert_pos == -1:
            m = re.search(r'\\begin\s*\{document\}', text)
            if m:
                insert_pos = m.start()
        if insert_pos == -1:
            return
        line, col = editor.lineIndexFromPosition(insert_pos)
        editor.beginUndoAction()
        editor.setCursorPosition(line, col)
        editor.insert(f"\n\\usepackage{{{package}}}")
        editor.endUndoAction()

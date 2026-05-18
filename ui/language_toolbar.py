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
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QCursor, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QToolButton, QFrame,
    QInputDialog, QApplication, QSizePolicy,
)

from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow
    from editor.editor_widget import EditorWidget


# Mappa chiave → nome file SVG Lucide per i bottoni custom della language toolbar.
# Le icone già presenti in _ICON_MAPS (bold, italic, ecc.) non vanno qui.
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
    "md_export_pdf":  "printer.svg",
    "md_export_html": "file-code.svg",
    "md_structure":   "list-tree.svg",
    "latex_env":      "braces.svg",
    "latex_align_l":  "align-left.svg",
    "latex_align_c":  "align-center.svg",
    "latex_align_r":  "align-right.svg",
    "latex_begin":    "chevron-right.svg",
    "latex_end":      "chevron-left.svg",
}

_ICON_SIZE = QSize(20, 20)


def _load_icon(icon_key: str, mw: "MainWindow") -> QIcon:
    """Carica un'icona Lucide (o del set attivo) sostituendo currentColor con il
    colore testo corrente della palette, identico a _rebuild_toolbar()."""
    from config.settings import Settings
    from PyQt6.QtGui import QPalette

    icon_file = _MD_ICON_FILES.get(icon_key, "")
    if not icon_file:
        return QIcon()

    icon_set  = Settings.instance().get("ui/icon_set", "lucide")
    icons_dir = Path(__file__).parent.parent / "icons" / icon_set
    icon_path = icons_dir / icon_file

    if not icon_path.exists():
        return QIcon()

    color = mw.palette().color(QPalette.ColorRole.WindowText).name()
    try:
        svg_data = icon_path.read_bytes().replace(b"currentColor", color.encode())
        pm = QPixmap()
        if pm.loadFromData(svg_data, "SVG") and not pm.isNull():
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

        self.setStyleSheet(
            "QWidget#LanguageToolbar {"
            "  background: palette(window);"
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
            "  background: palette(midlight);"
            "}"
        )

        self._layout.addStretch(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setVisible(False)

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
        tip = tr("action.lang_toolbar_table", default="Tabella")
        btn_tbl = self._add_icon_btn("md_table", "▦", tip)
        btn_tbl.clicked.connect(self._show_md_table_picker)

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
        # Formattazione inline
        for key in ("markup_bold", "markup_italic", "markup_strike"):
            if key in acts:
                self._add_action_button(acts[key])
        self._add_separator()

        # Tabella
        tip = tr("action.lang_toolbar_table", default="Tabella")
        btn_tbl = self._add_icon_btn("md_table", "▦", tip)
        btn_tbl.clicked.connect(self._show_latex_table_picker)

        # Avvolgi ambiente
        if "wrap_env" in acts:
            self._add_action_button(acts["wrap_env"])

        # Allinea tabella
        if "align_table" in acts:
            self._add_action_button(acts["align_table"])
        self._add_separator()

        # Allineamento LaTeX
        for key, env, tr_key, default, fallback in [
            ("latex_align_l", "flushleft",  "action.lang_toolbar_align_left",  "Allinea a sinistra", "⬅"),
            ("latex_align_c", "center",     "action.lang_toolbar_align_center", "Centra",             "↔"),
            ("latex_align_r", "flushright", "action.lang_toolbar_align_right",  "Allinea a destra",   "➡"),
        ]:
            tip = tr(tr_key, default=default)
            btn = self._add_icon_btn(key, fallback, tip)
            btn.clicked.connect(lambda c, e=env: self._wrap_latex_env(e))
        self._add_separator()

        # Begin / End ambiente
        tip_begin = tr("action.lang_toolbar_begin_env", default="Inizio ambiente")
        btn_begin = self._add_icon_btn("latex_begin", r"\begin{}", tip_begin)
        btn_begin.clicked.connect(self._latex_begin)

        tip_end = tr("action.lang_toolbar_end_env", default="Fine ambiente")
        btn_end = self._add_icon_btn("latex_end", r"\end{}", tip_end)
        btn_end.clicked.connect(self._latex_end)
        self._add_separator()

        # Build
        for key in ("compile", "run", "build", "stop_build"):
            if key in acts:
                self._add_action_button(acts[key])

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
        from PyQt6.QtWidgets import QFileDialog
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
        alt = sel if sel else tr("action.lang_toolbar_image_alt", default="immagine")
        if sel:
            editor.replaceSelectedText(f"![{alt}]({path})")
        else:
            line, col = editor.getCursorPosition()
            editor.insert(f"![{alt}]({path})")
            editor.setCursorPosition(line, col + len(f"![{alt}]({path})"))
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
        html_body = md_lib.markdown(
            content,
            extensions=["tables", "fenced_code", "toc", "nl2br"]
        )
        html_full = (
            "<!DOCTYPE html><html><head>"
            "<meta charset=\"UTF-8\">"
            "<style>"
            "body{font-family:sans-serif;font-size:11pt;line-height:1.6;margin:2cm;}"
            "pre{background:#f4f4f4;padding:.8em;overflow-x:auto;}"
            "code{background:#f4f4f4;padding:.1em .3em;border-radius:3px;}"
            "blockquote{border-left:4px solid #ccc;margin-left:0;padding-left:1em;color:#555;}"
            "table{border-collapse:collapse;}td,th{border:1px solid #ccc;padding:.3em .6em;}"
            "</style></head><body>"
            f"{html_body}"
            "</body></html>"
        )
        # Prima prova: QTextDocument (disponibile sempre in PyQt6)
        _exported = False
        _err_msg = ""
        try:
            from PyQt6.QtPrintSupport import QPrinter
            from PyQt6.QtGui import QTextDocument
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(path)
            doc = QTextDocument()
            doc.setHtml(html_full)
            doc.print(printer)
            _exported = True
        except Exception as _e:
            _err_msg = str(_e)

        if not _exported:
            # Fallback: QWebEngineView con printToPdf (non sincrono ma più fedele)
            try:
                from PyQt6.QtWebEngineWidgets import QWebEngineView
                from PyQt6.QtCore import QUrl, QEventLoop
                view = QWebEngineView()
                view.setHtml(html_full, QUrl("about:blank"))

                def _on_load(ok):
                    if ok:
                        loop2 = QEventLoop()
                        def _pdf_done(ok2):
                            loop2.quit()
                        try:
                            view.page().printToPdf(path, _pdf_done)
                            loop2.exec()
                        except TypeError:
                            view.page().printToPdf(path)
                    view.deleteLater()

                loop = QEventLoop()
                view.loadFinished.connect(_on_load)
                view.loadFinished.connect(lambda _: loop.quit())
                loop.exec()
                _exported = True
            except Exception as exc:
                _err_msg = str(exc)

        if _exported:
            import os as _os
            if _os.path.exists(path) and _os.path.getsize(path) > 0:
                QMessageBox.information(
                    self._mw,
                    tr("action.lang_toolbar_export_pdf", default="Esporta come PDF"),
                    tr("msg.export_pdf_ok", default=f"PDF esportato con successo:\n{path}")
                )
            else:
                QMessageBox.warning(
                    self._mw,
                    tr("action.lang_toolbar_export_pdf", default="Esporta come PDF"),
                    tr("msg.export_pdf_empty", default=f"Il file PDF sembra vuoto o non è stato creato:\n{path}")
                )
        else:
            QMessageBox.critical(
                self._mw,
                tr("action.lang_toolbar_export_pdf", default="Esporta come PDF"),
                _err_msg or tr("msg.export_pdf_failed", default="Esportazione PDF fallita.")
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

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
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
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
    "md_export_pdf":  "file-pdf.svg",
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
                "body{font-family:sans-serif;font-size:11pt;line-height:1.6;margin:2cm;}"
                "img{max-width:100%;height:auto;}"
                "pre{background:#f4f4f4;padding:.8em;overflow-x:auto;}"
                "code{background:#f4f4f4;padding:.1em .3em;border-radius:3px;}"
                "blockquote{border-left:4px solid #ccc;margin-left:0;padding-left:1em;color:#555;}"
                "table{border-collapse:collapse;}td,th{border:1px solid #ccc;padding:.3em .6em;}"
                "</style></head><body>"
                f"{body}"
                "</body></html>"
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

        # Primario: QWebEngineView — CSS completo, gestisce % correttamente
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView
            from PyQt6.QtCore import QUrl, QEventLoop
            _we_ok = [False]
            view = QWebEngineView()
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
                    view.page().printToPdf(_pdf_done)
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
            # Fallback: QTextDocument — % convertite in px (718px = larghezza utile A4)
            try:
                from PyQt6.QtPrintSupport import QPrinter
                from PyQt6.QtGui import QTextDocument
                from PyQt6.QtCore import QUrl
                html_body_px = _re.sub(
                    r'<img\b[^>]*>',
                    lambda m: _fix_img_pct_to_px(_fix_img_paths(m.group(0)), 718),
                    html_body, flags=_re.IGNORECASE
                )
                printer = QPrinter(QPrinter.PrinterMode.HighResolution)
                printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
                printer.setOutputFileName(path)
                doc = QTextDocument()
                doc.setBaseUrl(QUrl.fromLocalFile(str(_base_dir) + "/"))
                doc.setHtml(_make_html(html_body_px))
                doc.print(printer)
                _exported = True
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

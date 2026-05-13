"""
ui/language_toolbar.py — Toolbar contestuale LaTeX / Markdown
NotePadPQ

Toolbar attivabile che appare automaticamente (o su richiesta) quando
il documento corrente è LaTeX o Markdown. Raggruppa le azioni già
registrate in MainWindow._actions (nessun duplicato) più un set di
bottoni specifici non presenti nella toolbar principale.

Uso:
    LanguageToolbar.install(main_window)
    → aggiunge il widget nel layout del centralWidget
    → si mostra/nasconde al cambio tab in base al linguaggio

Sezioni della toolbar:
    -- Markdown --
    [B]  [I]  [~~]  [Tabella]  [Link]  [Immagine]  [# Intestazione]  |  [Anteprima]
    -- LaTeX --
    [B]  [I]  [~~]  [Tabella]  [Env]  [Allinea]  |  [Compila F6]  [Esegui F5]  [Build F7]
    -- Comuni --
    [Anteprima]  [Struttura (Function List)]  [Conteggio parole]

Nota: il widget è inserito direttamente nel QVBoxLayout del centralWidget
(container), NON come QToolBar di Qt — così la riga è garantita SOTTO
la toolbar principale, indipendentemente dalle aree toolbar di Qt.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QCursor
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QToolButton, QFrame,
    QInputDialog, QApplication, QSizePolicy,
)

from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow
    from editor.editor_widget import EditorWidget


# ─── Toolbar ──────────────────────────────────────────────────────────────────

class LanguageToolbar:
    """
    Gestisce la toolbar contestuale LaTeX/Markdown.
    Il widget è inserito nel layout del centralWidget (sopra il tab manager).
    """

    @staticmethod
    def install(main_window: "MainWindow") -> None:
        """
        Crea il widget toolbar e lo inserisce nel layout del centralWidget.
        La voce menu Visualizza viene aggiunta da main_window._build_menu_view()
        tramite _act("view_lang_toolbar", ..., self._toggle_lang_toolbar).
        """
        tb = _LanguageToolbarWidget(main_window)
        main_window._lang_toolbar = tb

        # Inserisci come PRIMA riga nel layout del centralWidget
        central = main_window.centralWidget()
        if central is not None and central.layout() is not None:
            central.layout().insertWidget(0, tb)
        else:
            # Fallback: wrappa il centralWidget in un container
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

        # Collega il cambio tab per mostrare/nascondere la toolbar
        main_window._tab_manager.current_editor_changed.connect(
            tb._on_editor_changed
        )

        # Leggi preferenza salvata
        from config.settings import Settings
        user_hidden = not Settings.instance().get("view/lang_toolbar", False)
        tb._user_hidden = user_hidden

        # Aggiorna subito per il documento corrente
        editor = main_window._tab_manager.current_editor()
        tb._on_editor_changed(editor)


# ─── Widget toolbar ───────────────────────────────────────────────────────────

class _LanguageToolbarWidget(QWidget):
    """
    Widget-toolbar interno. Si nasconde automaticamente per i linguaggi
    diversi da LaTeX e Markdown.
    Implementato come QWidget con QHBoxLayout (non QToolBar) per garantire
    il posizionamento sulla seconda riga sotto la toolbar principale.
    """

    # Segnale per compatibilità con il codice che usa visibilityChanged
    visibilityChanged = pyqtSignal(bool)

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._mw = main_window
        self._current_lang: str = ""
        self._user_hidden: bool = False
        self._fl_conn = None  # connessione visibilityChanged del function-list dock

        self.setObjectName("LanguageToolbar")
        # Necessario perché QWidget non è una QToolBar: senza questo attributo
        # il repaint dei QToolButton:hover causa un refresh del parent con
        # background non inizializzato (appare tutto bianco su certi temi/WM).
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # Layout orizzontale stile toolbar
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 2, 4, 2)
        self._layout.setSpacing(2)

        # Stile visivo uguale alla toolbar principale.
        # Hover: rgba semi-trasparente invece di palette(highlight) per evitare
        # che temi con highlighted-text=bianco rendano il testo invisibile.
        self.setStyleSheet(
            "QWidget#LanguageToolbar {"
            "  background: palette(window);"
            "  border-bottom: 1px solid palette(mid);"
            "}"
            "QToolButton {"
            "  padding: 3px 6px;"
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

        # Stretcher finale per spingere i bottoni a sinistra
        self._layout.addStretch(1)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setVisible(False)

    # ── Override setVisible per emettere visibilityChanged ────────────────────

    def setVisible(self, visible: bool) -> None:
        super().setVisible(visible)
        self.visibilityChanged.emit(visible)

    # ── Visibilità ────────────────────────────────────────────────────────────

    def _on_menu_toggled(self, checked: bool) -> None:
        """Chiamato dalla voce menu Visualizza → toolbar linguaggio (legacy)."""
        self._user_hidden = not checked
        if self._user_hidden:
            self.setVisible(False)
        else:
            editor = self._mw._tab_manager.current_editor()
            self._on_editor_changed(editor)

    def _on_editor_changed(self, editor: Optional["EditorWidget"]) -> None:
        """Aggiorna il contenuto e la visibilità al cambio tab."""
        lang = ""
        if editor is not None:
            try:
                from editor.lexers import get_language_name
                lang = get_language_name(editor).lower()
            except Exception:
                pass

        self._current_lang = lang
        is_md  = "markdown" in lang
        # Confronto a parole intere: "tex" in "plain text" darebbe True per falso positivo
        _lw    = set(lang.split())
        is_tex = "latex" in lang or bool(_lw & {"tex", "bibtex", "plaintex"})

        if self._user_hidden or (not is_md and not is_tex):
            self.setVisible(False)
        else:
            self._rebuild(is_md=is_md, is_tex=is_tex)
            self.setVisible(True)

    # ── Costruzione ───────────────────────────────────────────────────────────

    def _add_separator(self) -> None:
        """Aggiunge un separatore verticale stile toolbar."""
        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setFixedWidth(6)
        # Inserisci prima dello stretcher finale
        self._layout.insertWidget(self._layout.count() - 1, sep)

    def _add_action_button(self, action: QAction) -> QToolButton:
        """Crea un QToolButton dall'azione e lo aggiunge al layout."""
        btn = QToolButton(self)
        btn.setDefaultAction(action)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        btn.setIconSize(QSize(20, 20))
        # Inserisci prima dello stretcher finale
        self._layout.insertWidget(self._layout.count() - 1, btn)
        return btn

    def _add_new_button(self, text: str, tooltip: str = "",
                        checkable: bool = False) -> QToolButton:
        """Crea un QToolButton standalone (senza QAction registrata)."""
        btn = QToolButton(self)
        btn.setText(text)
        if tooltip:
            btn.setToolTip(tooltip)
        btn.setCheckable(checkable)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        btn.setIconSize(QSize(20, 20))
        self._layout.insertWidget(self._layout.count() - 1, btn)
        return btn

    def _clear_buttons(self) -> None:
        """Rimuove tutti i bottoni e separatori (tranne lo stretcher finale)."""
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def _rebuild(self, is_md: bool, is_tex: bool) -> None:
        """Ricostruisce i bottoni in base al linguaggio corrente."""
        # Disconnetti il collegamento precedente al dock Struttura (se esiste)
        # per evitare che la lambda catturi un QToolButton già eliminato.
        if self._fl_conn is not None:
            try:
                self._mw._function_list_dock.visibilityChanged.disconnect(self._fl_conn)
            except (RuntimeError, TypeError):
                pass
            self._fl_conn = None
        self._clear_buttons()
        acts = self._mw._actions  # dizionario azioni già registrate

        # ── Formattazione testo (riusa azioni esistenti) ───────────────────
        for key in ("markup_bold", "markup_italic", "markup_strike"):
            if key in acts:
                self._add_action_button(acts[key])
        self._add_separator()

        # ── Blocchi specifici per linguaggio ──────────────────────────────
        if is_md:
            self._add_md_actions(acts)
        elif is_tex:
            self._add_latex_actions(acts)

        self._add_separator()

        # ── Azioni comuni ─────────────────────────────────────────────────
        # Anteprima (F12)
        if "preview_toggle" in acts:
            self._add_action_button(acts["preview_toggle"])

        # Function List / Struttura documento
        if hasattr(self._mw, "_function_list_dock"):
            label = "𝑓 " + tr("action.lang_toolbar_structure", default="Struttura")
            tip   = tr("action.lang_toolbar_structure", default="Struttura")
            btn_fl = self._add_new_button(label, tip, checkable=True)
            btn_fl.setChecked(self._mw._function_list_dock.isVisible())
            btn_fl.toggled.connect(self._mw._function_list_dock.setVisible)
            self._fl_conn = lambda v, b=btn_fl: b.setChecked(v)
            self._mw._function_list_dock.visibilityChanged.connect(self._fl_conn)

        # Conteggio parole
        if "word_count" in acts:
            self._add_action_button(acts["word_count"])

        self.update()

    def _add_md_actions(self, acts: dict) -> None:
        """Bottoni specifici per Markdown."""
        # Tabella con griglia picker
        label = "▦ " + tr("action.lang_toolbar_table", default="Tabella")
        tip   = tr("action.lang_toolbar_table", default="Tabella")
        btn_tbl = self._add_new_button(label, tip)
        btn_tbl.clicked.connect(self._show_md_table_picker)

        # Allinea tabella (riusa azione esistente)
        if "align_table" in acts:
            self._add_action_button(acts["align_table"])

        self._add_separator()

        # Link
        label = "🔗 " + tr("action.lang_toolbar_link", default="Link")
        tip   = tr("action.lang_toolbar_link", default="Link") + "  Ctrl+Shift+K"
        btn_link = self._add_new_button(label, tip)
        btn_link.clicked.connect(self._insert_md_link)
        btn_link.setShortcut(QKeySequence("Ctrl+Shift+K"))

        # Immagine
        label = "🖼 " + tr("action.lang_toolbar_image", default="Immagine")
        tip   = tr("action.lang_toolbar_image", default="Immagine")
        btn_img = self._add_new_button(label, tip)
        btn_img.clicked.connect(self._insert_md_image)

        self._add_separator()

        # Intestazioni
        label = "# " + tr("action.lang_toolbar_heading", default="Intestazione")
        tip   = tr("action.lang_toolbar_heading", default="Intestazione")
        btn_h = self._add_new_button(label, tip)
        btn_h.clicked.connect(self._cycle_md_heading)

        self._add_separator()

        # Allineamento testo
        for symbol, key, default in [
            ("⬅", "lang_toolbar_align_left",   "Allinea a sinistra"),
            ("↔", "lang_toolbar_align_center",  "Centra"),
            ("➡", "lang_toolbar_align_right",   "Allinea a destra"),
        ]:
            tip = tr(f"action.{key}", default=default)
            btn = self._add_new_button(symbol, tip)
            align = default.split()[-1].lower()  # left / center / destra→right
            # Mappa italiano→HTML
            align_map = {"sinistra": "left", "center": "center",
                         "centra": "center", "destra": "right"}
            html_align = align_map.get(align, align)
            btn.clicked.connect(lambda checked, a=html_align: self._insert_md_align(a))

    def _add_latex_actions(self, acts: dict) -> None:
        """Bottoni specifici per LaTeX."""
        # Tabella con griglia picker
        label = "▦ " + tr("action.lang_toolbar_table", default="Tabella")
        tip   = tr("action.lang_toolbar_table", default="Tabella")
        btn_tbl = self._add_new_button(label, tip)
        btn_tbl.clicked.connect(self._show_latex_table_picker)

        # Avvolgi ambiente (riusa azione esistente)
        if "wrap_env" in acts:
            self._add_action_button(acts["wrap_env"])

        # Allinea tabella (riusa azione esistente)
        if "align_table" in acts:
            self._add_action_button(acts["align_table"])

        self._add_separator()

        # Allineamento testo LaTeX
        for symbol, env, key, default in [
            ("⬅", "flushleft",  "lang_toolbar_align_left",   "Allinea a sinistra"),
            ("↔", "center",     "lang_toolbar_align_center",  "Centra"),
            ("➡", "flushright", "lang_toolbar_align_right",   "Allinea a destra"),
        ]:
            tip = tr(f"action.{key}", default=default)
            btn = self._add_new_button(symbol, tip)
            btn.clicked.connect(lambda checked, e=env: self._wrap_latex_env(e))

        self._add_separator()

        # Begin / End ambiente
        tip_begin = tr("action.lang_toolbar_begin_env", default="Inizio ambiente")
        btn_begin = self._add_new_button(r"\begin{}", tip_begin)
        btn_begin.clicked.connect(self._latex_begin)

        tip_end = tr("action.lang_toolbar_end_env", default="Fine ambiente")
        btn_end = self._add_new_button(r"\end{}", tip_end)
        btn_end.clicked.connect(self._latex_end)

        self._add_separator()

        # Build/Compile/Run (riusa azioni esistenti)
        for key in ("compile", "run", "build", "stop_build"):
            if key in acts:
                self._add_action_button(acts[key])

    # ── Handler azioni MD ─────────────────────────────────────────────────────

    def _insert_md_link(self) -> None:
        """Inserisce [testo selezionato](url) o apre dialog."""
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
        """Inserisce ![alt](percorso) con file picker."""
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

        from pathlib import Path
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

    def _cycle_md_heading(self) -> None:
        """
        Cicla il livello di intestazione sulla riga corrente:
        nessuno → # → ## → ### → nessuno
        """
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return

        line, col = editor.getCursorPosition()
        line_text = editor.text(line)

        import re
        m = re.match(r'^(#{1,6})\s+(.*)', line_text.rstrip('\n'))
        if m:
            level = len(m.group(1))
            content = m.group(2)
            if level >= 3:
                new_line = content
            else:
                new_line = "#" * (level + 1) + " " + content
        else:
            content = line_text.rstrip('\n')
            new_line = "# " + content

        editor.beginUndoAction()
        editor.setSelection(line, 0, line, len(line_text.rstrip('\n')))
        editor.replaceSelectedText(new_line)
        editor.setCursorPosition(line, min(col, len(new_line)))
        editor.endUndoAction()
        editor.setFocus()

    # ── Handler allineamento ─────────────────────────────────────────────────

    def _insert_md_align(self, align: str) -> None:
        """Avvolge la selezione (o inserisce) un div HTML con text-align."""
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

    def _wrap_latex_env(self, env: str) -> None:
        """Avvolge la selezione (o crea vuoto) in un ambiente LaTeX."""
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        if editor.hasSelectedText():
            text = editor.selectedText()
            indented = "\n".join("    " + l for l in text.split("\n"))
            editor.replaceSelectedText(
                f"\\begin{{{env}}}\n{indented}\n\\end{{{env}}}"
            )
        else:
            line, col = editor.getCursorPosition()
            editor.insert(f"\\begin{{{env}}}\n    \n\\end{{{env}}}")
            editor.setCursorPosition(line + 1, 4)
        editor.setFocus()

    def _latex_begin(self) -> None:
        """Inserisce \\begin{nome} alla posizione del cursore."""
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        prompt = tr("action.lang_toolbar_env_name", default="Nome ambiente:")
        env, ok = QInputDialog.getText(self._mw,
                                       tr("action.lang_toolbar_begin_env", default="Inizio ambiente"),
                                       prompt)
        if ok and env.strip():
            editor.insert(f"\\begin{{{env.strip()}}}")
        editor.setFocus()

    def _latex_end(self) -> None:
        """Inserisce \\end{nome} alla posizione del cursore."""
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        prompt = tr("action.lang_toolbar_env_name", default="Nome ambiente:")
        env, ok = QInputDialog.getText(self._mw,
                                       tr("action.lang_toolbar_end_env", default="Fine ambiente"),
                                       prompt)
        if ok and env.strip():
            editor.insert(f"\\end{{{env.strip()}}}")
        editor.setFocus()

    # ── Handler picker tabella ────────────────────────────────────────────────

    def _show_md_table_picker(self) -> None:
        """Apre il popup griglia per inserire una tabella Markdown."""
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        from ui.table_grid_picker import TableGridPicker
        TableGridPicker.show_for_editor(
            editor, is_latex=False,
            parent=self._mw,
            pos=QCursor.pos(),
        )

    def _show_latex_table_picker(self) -> None:
        """Apre il popup griglia per inserire una tabella LaTeX."""
        editor = self._mw._tab_manager.current_editor()
        if not editor:
            return
        from ui.table_grid_picker import TableGridPicker
        TableGridPicker.show_for_editor(
            editor, is_latex=True,
            parent=self._mw,
            pos=QCursor.pos(),
        )

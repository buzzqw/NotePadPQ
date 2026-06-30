"""
ui/latex_menu.py — Menu LaTeX dinamico
NotePadPQ

Appare nella barra dei menu solo quando il tab attivo è un file .tex.

NOTA ARCHITETTURALE: _rebuild_menus() in main_window.py chiama mb.clear(),
che rimuove tutti i menu aggiuntivi. LatexMenuManager._attach() viene
chiamato alla fine di _rebuild_menus() per re-inserire il menu ogni volta.
"""

from __future__ import annotations

import re
from typing import Optional, TYPE_CHECKING

from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QMenu

from i18n.i18n import tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow
    from editor.editor_widget import EditorWidget


class LatexMenuManager:
    """Installa e gestisce il menu LaTeX nella barra dei menu principale."""

    @staticmethod
    def install(main_window: "MainWindow") -> None:
        mgr = LatexMenuManager(main_window)
        main_window._latex_menu_mgr = mgr
        main_window._tab_manager.current_editor_changed.connect(mgr._on_editor_changed)
        # Non chiamiamo _attach() qui: lo farà _rebuild_menus() in _setup_i18n()

    def __init__(self, mw: "MainWindow") -> None:
        self._mw = mw
        self._menu = QMenu(tr("latex_menu.title", default="La&TeX"), mw)
        self._build_menu()

    # ── Attach / detach dalla menubar ─────────────────────────────────────────

    def _attach(self) -> None:
        """(Re-)aggiunge il menu alla menubar prima di Aiuto dopo un mb.clear()."""
        mb = self._mw.menuBar()
        help_menu = getattr(self._mw, "_menus", {}).get("help")
        if help_menu:
            mb.insertMenu(help_menu.menuAction(), self._menu)
        else:
            mb.addMenu(self._menu)
        self._on_editor_changed(self._mw._tab_manager.current_editor())

    # ── Visibilità ────────────────────────────────────────────────────────────

    def _on_editor_changed(self, editor: Optional["EditorWidget"]) -> None:
        self._menu.menuAction().setVisible(self._is_latex(editor))

    @staticmethod
    def _is_latex(editor: Optional["EditorWidget"]) -> bool:
        if editor is None:
            return False
        if editor.file_path and editor.file_path.suffix.lower() == ".tex":
            return True
        return getattr(editor, "_current_language", "").lower() == "latex"

    # ── Editor corrente ───────────────────────────────────────────────────────

    def _ed(self) -> Optional["EditorWidget"]:
        return self._mw._tab_manager.current_editor()

    # ── Helpers inserimento ───────────────────────────────────────────────────

    def _insert(self, text: str) -> None:
        ed = self._ed()
        if not ed:
            return
        ed.beginUndoAction()
        if ed.hasSelectedText():
            ed.replaceSelectedText(text)
        else:
            ed.insert(text)
        ed.endUndoAction()
        ed.setFocus()

    def _insert_cmd(self, cmd: str) -> None:
        r"""\cmd{selezione} oppure \cmd{} con cursore dentro le graffe."""
        ed = self._ed()
        if not ed:
            return
        ed.beginUndoAction()
        if ed.hasSelectedText():
            sel = ed.selectedText()
            ed.replaceSelectedText(f"{cmd}{{{sel}}}")
        else:
            line, col = ed.getCursorPosition()
            ed.insert(f"{cmd}{{}}")
            ed.setCursorPosition(line, col + len(cmd) + 1)
        ed.endUndoAction()
        ed.setFocus()

    def _insert_env(self, env: str, options: str = "") -> None:
        r"""\begin{env}...\end{env}."""
        ed = self._ed()
        if not ed:
            return
        ed.beginUndoAction()
        if ed.hasSelectedText():
            sel = ed.selectedText()
            ed.replaceSelectedText(f"\\begin{{{env}}}{options}\n{sel}\n\\end{{{env}}}")
        else:
            line, _ = ed.getCursorPosition()
            ed.insert(f"\\begin{{{env}}}{options}\n    \n\\end{{{env}}}")
            ed.setCursorPosition(line + 1, 4)
        ed.endUndoAction()
        ed.setFocus()

    # ── Helper azione ─────────────────────────────────────────────────────────

    def _act(self, parent: QMenu, label: str, callback,
             shortcut: str = "") -> QAction:
        a = QAction(label, parent)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(lambda: callback())
        parent.addAction(a)
        return a

    def _sub(self, label: str) -> QMenu:
        """Crea un QMenu figlio (senza aggiungerlo al genitore — lo fa _build_menu)."""
        return QMenu(label, self._menu)

    # ── Costruzione menu principale ───────────────────────────────────────────

    def _build_menu(self) -> None:
        m = self._menu
        m.clear()

        # Preambolo
        self._act(m, "\\documentclass", self._insert_documentclass)
        self._act(m, "\\usepackage{}", lambda: self._insert_cmd("\\usepackage"))
        self._act(m, tr("latex_menu.ams_packages", default="Pacchetti AMS"),
                  lambda: self._insert(
                      "\\usepackage{amsmath}\n\\usepackage{amsthm}\n\\usepackage{amssymb}\n"
                  ))
        self._act(m, "\\begin{document}", self._insert_begin_document)
        m.addSeparator()

        # Metadati documento
        self._act(m, "\\title{}", lambda: self._insert_cmd("\\title"))
        self._act(m, "\\author{}", lambda: self._insert_cmd("\\author"))
        self._act(m, "\\date{}", lambda: self._insert_cmd("\\date"))
        self._act(m, "\\maketitle", lambda: self._insert("\\maketitle\n"))
        self._act(m, "\\tableofcontents", lambda: self._insert("\\tableofcontents\n"))
        m.addSeparator()

        # Azioni rapide di inserimento
        self._act(m, tr("latex_menu.insert_image", default="Inserisci immagine…"),
                  self._open_image_dialog)
        self._act(m, tr("latex_menu.insert_table_quick", default="Inserisci tabella…"),
                  self._insert_table_env)
        m.addSeparator()

        # Submenus — ogni _build_X() restituisce un QMenu già pronto
        m.addMenu(self._build_sezionamento())
        m.addMenu(self._build_ambienti())
        m.addMenu(self._build_ambienti_lista())
        m.addMenu(self._build_scatole())
        m.addMenu(self._build_stili_carattere())
        m.addMenu(self._build_dimensione_font())
        m.addMenu(self._build_ambienti_tabella())
        m.addMenu(self._build_spazio_orizzontale())
        m.addMenu(self._build_spaziatura_verticale())
        m.addMenu(self._build_accenti())
        m.addMenu(self._build_inserisci_file())
        m.addSeparator()
        m.addMenu(self._build_commenti_revisione())
        m.addMenu(self._build_riferimenti())
        m.addMenu(self._build_bibliografia())
        m.addSeparator()

        self._act(m,
            tr("latex_menu.ref_next",
               default="Inserisci riferimento all'etichetta successiva"),
            self._insert_ref_next, "Ctrl+Alt+R")
        self._act(m,
            tr("latex_menu.ref_prev",
               default="Inserisci riferimento all'etichetta precedente"),
            self._insert_ref_prev)
        m.addSeparator()

        m.addMenu(self._build_modifica_tabelle())
        m.addMenu(self._build_commenti_magici())

    # ── Submenus ──────────────────────────────────────────────────────────────

    def _build_sezionamento(self) -> QMenu:
        s = self._sub(tr("latex_menu.sectioning", default="Sezionamento"))
        for cmd in ["part", "chapter", "section", "subsection",
                    "subsubsection", "paragraph", "subparagraph"]:
            self._act(s, f"\\{cmd}{{}}", lambda c=cmd: self._insert_cmd(f"\\{c}"))
        s.addSeparator()
        for cmd in ["part", "chapter", "section", "subsection", "subsubsection"]:
            self._act(s, f"\\{cmd}*{{}}", lambda c=cmd: self._insert_cmd(f"\\{c}*"))
        return s

    def _build_ambienti(self) -> QMenu:
        s = self._sub(tr("latex_menu.environments", default="Ambienti"))
        for env in ["abstract", "center", "flushleft", "flushright",
                    "verbatim", "verbatim*", "quote", "quotation", "verse"]:
            self._act(s, f"\\begin{{{env}}}", lambda e=env: self._insert_env(e))
        s.addSeparator()
        self._act(s, "\\begin{minipage}",
                  lambda: self._insert_env("minipage", "{\\linewidth}"))
        self._act(s, "\\begin{figure}", self._insert_figure)
        self._act(s, "\\begin{equation}", lambda: self._insert_env("equation"))
        self._act(s, "\\begin{align}", lambda: self._insert_env("align"))
        self._act(s, "\\begin{align*}", lambda: self._insert_env("align*"))
        return s

    def _build_ambienti_lista(self) -> QMenu:
        s = self._sub(tr("latex_menu.list_envs", default="Ambienti lista"))
        self._act(s, "\\begin{itemize}",
                  lambda: self._insert_list("itemize"))
        self._act(s, "\\begin{enumerate}",
                  lambda: self._insert_list("enumerate"))
        self._act(s, "\\begin{description}",
                  lambda: self._insert_list("description", item="\\item[]"))
        s.addSeparator()
        self._act(s, "\\item", lambda: self._insert("\\item "))
        self._act(s, "\\item[]", lambda: self._insert("\\item[] "))
        return s

    def _build_scatole(self) -> QMenu:
        s = self._sub(tr("latex_menu.boxes", default="Scatole"))
        self._act(s, "\\mbox{}", lambda: self._insert_cmd("\\mbox"))
        self._act(s, "\\fbox{}", lambda: self._insert_cmd("\\fbox"))
        self._act(s, "\\makebox[]{}", self._insert_makebox)
        self._act(s, "\\framebox[]{}", self._insert_framebox)
        self._act(s, "\\parbox{}{}", lambda: self._insert("\\parbox{}{}"))
        self._act(s, "\\raisebox{}{}", lambda: self._insert("\\raisebox{}{}"))
        self._act(s, "\\rule{}{}", lambda: self._insert("\\rule{}{}"))
        return s

    def _build_stili_carattere(self) -> QMenu:
        s = self._sub(tr("latex_menu.char_styles", default="Stili di carattere"))
        for label, cmd in [
            ("\\textbf{}",    "\\textbf"),
            ("\\textit{}",    "\\textit"),
            ("\\texttt{}",    "\\texttt"),
            ("\\textrm{}",    "\\textrm"),
            ("\\textsf{}",    "\\textsf"),
            ("\\textsc{}",    "\\textsc"),
            ("\\textsl{}",    "\\textsl"),
            ("\\emph{}",      "\\emph"),
            ("\\underline{}", "\\underline"),
            ("\\textnormal{}","\\textnormal"),
        ]:
            self._act(s, label, lambda c=cmd: self._insert_cmd(c))
        return s

    def _build_dimensione_font(self) -> QMenu:
        s = self._sub(tr("latex_menu.font_sizes", default="Dimensione font"))
        for sz in ["tiny", "scriptsize", "footnotesize", "small", "normalsize",
                   "large", "Large", "LARGE", "huge", "Huge"]:
            self._act(s, f"\\{sz}", lambda z=sz: self._insert(f"\\{z} "))
        return s

    def _build_ambienti_tabella(self) -> QMenu:
        s = self._sub(tr("latex_menu.table_envs", default="Ambienti tabella"))
        self._act(s, "\\begin{table}", self._insert_table_env)
        self._act(s, "\\begin{tabular}",
                  lambda: self._insert_tabular("tabular"))
        self._act(s, "\\begin{tabularx}",
                  lambda: self._insert_tabular("tabularx"))
        self._act(s, "\\begin{longtable}",
                  lambda: self._insert_tabular("longtable"))
        self._act(s, "\\begin{array}",
                  lambda: self._insert_tabular("array"))
        return s

    def _build_spazio_orizzontale(self) -> QMenu:
        s = self._sub(tr("latex_menu.hspace", default="Spazio Orizzontale"))
        self._act(s, "\\hspace{}", lambda: self._insert_cmd("\\hspace"))
        self._act(s, "\\hspace*{}", lambda: self._insert_cmd("\\hspace*"))
        self._act(s, "\\hfill", lambda: self._insert("\\hfill"))
        self._act(s, "\\hrulefill", lambda: self._insert("\\hrulefill"))
        self._act(s, "\\dotfill", lambda: self._insert("\\dotfill"))
        s.addSeparator()
        self._act(s, "\\quad", lambda: self._insert("\\quad"))
        self._act(s, "\\qquad", lambda: self._insert("\\qquad"))
        self._act(s, "\\enspace", lambda: self._insert("\\enspace"))
        self._act(s, "\\,  (spazio sottile)", lambda: self._insert("\\,"))
        self._act(s, "\\:  (spazio medio)", lambda: self._insert("\\:"))
        self._act(s, "\\;  (spazio spesso)", lambda: self._insert("\\;"))
        self._act(s, "\\ (spazio forzato)", lambda: self._insert("\\ "))
        s.addSeparator()
        self._act(s, "\\noindent", lambda: self._insert("\\noindent "))
        self._act(s, "\\indent", lambda: self._insert("\\indent "))
        return s

    def _build_spaziatura_verticale(self) -> QMenu:
        s = self._sub(tr("latex_menu.vspace", default="Spaziatura verticale"))
        self._act(s, "\\vspace{}", lambda: self._insert_cmd("\\vspace"))
        self._act(s, "\\vspace*{}", lambda: self._insert_cmd("\\vspace*"))
        self._act(s, "\\vfill", lambda: self._insert("\\vfill"))
        s.addSeparator()
        self._act(s, "\\smallskip", lambda: self._insert("\\smallskip"))
        self._act(s, "\\medskip", lambda: self._insert("\\medskip"))
        self._act(s, "\\bigskip", lambda: self._insert("\\bigskip"))
        s.addSeparator()
        self._act(s, "\\\\ (a capo)", lambda: self._insert("\\\\"))
        self._act(s, "\\\\[] (a capo con spazio)", lambda: self._insert("\\\\[]"))
        self._act(s, "\\newline", lambda: self._insert("\\newline"))
        self._act(s, "\\newpage", lambda: self._insert("\\newpage"))
        self._act(s, "\\clearpage", lambda: self._insert("\\clearpage"))
        self._act(s, "\\cleardoublepage", lambda: self._insert("\\cleardoublepage"))
        return s

    def _build_accenti(self) -> QMenu:
        s = self._sub(tr("latex_menu.accents", default="Accenti internazionali"))
        accents = [
            ("\\'{} — acuto (á é)",       "\\'{}"),
            ("\\`{} — grave (à è)",        "\\`{}"),
            ("\\^{} — circonflesso (â ê)", "\\^{}"),
            ("\\\"{}  — dieresi (ä ë)",    "\\\"{}"),
            ("\\~{} — tilde (ã ñ)",        "\\~{}"),
            ("\\={} — macron (ā ē)",       "\\={}"),
            ("\\.{} — punto (ḃ ċ)",        "\\.{}"),
            ("\\u{} — breve (ă ĕ)",        "\\u{}"),
            ("\\v{} — caron (č š)",        "\\v{}"),
            ("\\c{} — cediglia (ç)",       "\\c{}"),
            ("\\H{} — doppio acuto (ő)",   "\\H{}"),
            ("\\d{} — punto sotto (ạ)",    "\\d{}"),
            ("\\b{} — barra sotto (ḇ)",    "\\b{}"),
        ]
        for label, cmd in accents:
            self._act(s, label, lambda c=cmd: self._insert_accent(c))
        return s

    def _build_inserisci_file(self) -> QMenu:
        s = self._sub(tr("latex_menu.insert_file", default="Inserisci/includi File"))
        self._act(s, "\\input{}", lambda: self._insert_cmd("\\input"))
        self._act(s, "\\include{}", lambda: self._insert_cmd("\\include"))
        self._act(s, "\\includeonly{}", lambda: self._insert_cmd("\\includeonly"))
        s.addSeparator()
        self._act(s, tr("latex_menu.insert_image", default="Inserisci immagine…"),
                  self._open_image_dialog)
        s.addSeparator()
        self._act(s, "\\bibliography{}", lambda: self._insert_cmd("\\bibliography"))
        self._act(s, "\\bibliographystyle{}", lambda: self._insert_cmd("\\bibliographystyle"))
        return s

    def _build_commenti_revisione(self) -> QMenu:
        s = self._sub(tr("latex_menu.changes",
                         default="Commenti di revisione (changes)"))
        self._act(s, "\\added{}", lambda: self._insert_cmd("\\added"))
        self._act(s, "\\deleted{}", lambda: self._insert_cmd("\\deleted"))
        self._act(s, "\\replaced{}{}", lambda: self._insert("\\replaced{}{}"))
        self._act(s, "\\comment{}", lambda: self._insert_cmd("\\comment"))
        s.addSeparator()
        self._act(s, "\\usepackage[final]{changes}",
                  lambda: self._insert("\\usepackage[final]{changes}\n"))
        return s

    def _build_riferimenti(self) -> QMenu:
        s = self._sub(tr("latex_menu.cross_ref", default="Riferimenti incrociati"))
        self._act(s, "\\label{}", lambda: self._insert_cmd("\\label"))
        self._act(s, "\\ref{}", lambda: self._insert_cmd("\\ref"))
        self._act(s, "\\pageref{}", lambda: self._insert_cmd("\\pageref"))
        self._act(s, "\\eqref{}", lambda: self._insert_cmd("\\eqref"))
        s.addSeparator()
        self._act(s, "\\cite{}", lambda: self._insert_cmd("\\cite"))
        self._act(s, "\\cite[]{}", self._insert_cite_opt)
        self._act(s, "\\nocite{}", lambda: self._insert_cmd("\\nocite"))
        s.addSeparator()
        self._act(s, "\\footnote{}", lambda: self._insert_cmd("\\footnote"))
        self._act(s, "\\endnote{}", lambda: self._insert_cmd("\\endnote"))
        return s

    def _build_bibliografia(self) -> QMenu:
        s = self._sub(tr("latex_menu.bibliography", default="Bibliografia"))
        entries = [
            ("@article",
             "@article{key,\n    author  = {},\n    title   = {},\n"
             "    journal = {},\n    year    = {},\n    volume  = {},\n    pages   = {}\n}"),
            ("@book",
             "@book{key,\n    author    = {},\n    title     = {},\n"
             "    publisher = {},\n    year      = {},\n    address   = {}\n}"),
            ("@inproceedings",
             "@inproceedings{key,\n    author    = {},\n    title     = {},\n"
             "    booktitle = {},\n    year      = {},\n    pages     = {}\n}"),
            ("@incollection",
             "@incollection{key,\n    author    = {},\n    title     = {},\n"
             "    booktitle = {},\n    publisher = {},\n    year      = {},\n"
             "    pages     = {}\n}"),
            ("@misc",
             "@misc{key,\n    author = {},\n    title  = {},\n"
             "    year   = {},\n    note   = {}\n}"),
            ("@phdthesis",
             "@phdthesis{key,\n    author = {},\n    title  = {},\n"
             "    school = {},\n    year   = {}\n}"),
            ("@techreport",
             "@techreport{key,\n    author      = {},\n    title       = {},\n"
             "    institution = {},\n    year        = {}\n}"),
            ("@unpublished",
             "@unpublished{key,\n    author = {},\n    title  = {},\n"
             "    note   = {},\n    year   = {}\n}"),
        ]
        for label, text in entries:
            self._act(s, label, lambda t=text: self._insert(t))
        return s

    def _build_modifica_tabelle(self) -> QMenu:
        s = self._sub(tr("latex_menu.edit_tables", default="Modifica tabelle"))
        ops = [
            (tr("tooltip.table_row_above", default="Inserisci riga sopra"),
             "row", "above"),
            (tr("tooltip.table_row_below", default="Inserisci riga sotto"),
             "row", "below"),
            (tr("tooltip.table_col_left",  default="Inserisci colonna sinistra"),
             "col", "left"),
            (tr("tooltip.table_col_right", default="Inserisci colonna destra"),
             "col", "right"),
        ]
        for label, act, where in ops:
            self._act(s, label, lambda a=act, w=where: self._table_op(a, w))
        s.addSeparator()
        self._act(s, tr("tooltip.table_delete_row", default="Elimina riga"),
                  lambda: self._table_op("del_row", None))
        self._act(s, tr("tooltip.table_delete_col", default="Elimina colonna"),
                  lambda: self._table_op("del_col", None))
        return s

    def _build_commenti_magici(self) -> QMenu:
        s = self._sub(tr("latex_menu.magic_comments",
                         default="Aggiungi commenti magici…"))
        items = [
            ("% !TEX root =",             "% !TEX root = "),
            ("% !TEX program = pdflatex", "% !TEX program = pdflatex\n"),
            ("% !TEX program = lualatex", "% !TEX program = lualatex\n"),
            ("% !TEX program = xelatex",  "% !TEX program = xelatex\n"),
            ("% !TEX encoding = UTF-8",   "% !TEX encoding = UTF-8\n"),
            ("% !TEX spellcheck = it_IT", "% !TEX spellcheck = it_IT\n"),
            ("% !TEX spellcheck = en_US", "% !TEX spellcheck = en_US\n"),
            ("% !BIB program = bibtex",   "% !BIB program = bibtex\n"),
            ("% !BIB program = biber",    "% !BIB program = biber\n"),
        ]
        for label, text in items:
            self._act(s, label, lambda t=text: self._insert_magic_comment(t))
        return s

    # ── Implementazioni specifiche ────────────────────────────────────────────

    def _insert_documentclass(self) -> None:
        ed = self._ed()
        if not ed:
            return
        line, col = ed.getCursorPosition()
        ed.insert("\\documentclass[]{article}")
        ed.setCursorPosition(line, col + len("\\documentclass["))

    def _insert_begin_document(self) -> None:
        ed = self._ed()
        if not ed:
            return
        line, _ = ed.getCursorPosition()
        ed.insert("\\begin{document}\n\n\\end{document}")
        ed.setCursorPosition(line + 1, 0)

    def _insert_figure(self) -> None:
        ed = self._ed()
        if not ed:
            return
        line, _ = ed.getCursorPosition()
        text = ("\\begin{figure}[htbp]\n"
                "    \\centering\n"
                "    \\includegraphics[width=0.8\\linewidth]{}\n"
                "    \\caption{}\n"
                "    \\label{fig:}\n"
                "\\end{figure}")
        ed.beginUndoAction()
        ed.insert(text)
        ed.setCursorPosition(line + 2,
                             len("    \\includegraphics[width=0.8\\linewidth]{"))
        ed.endUndoAction()
        ed.setFocus()

    def _insert_list(self, env: str, item: str = "\\item") -> None:
        ed = self._ed()
        if not ed:
            return
        ed.beginUndoAction()
        line, _ = ed.getCursorPosition()
        text = f"\\begin{{{env}}}\n    {item} \n\\end{{{env}}}"
        ed.insert(text)
        ed.setCursorPosition(line + 1, len(f"    {item} "))
        ed.endUndoAction()
        ed.setFocus()

    def _insert_table_env(self) -> None:
        ed = self._ed()
        if not ed:
            return
        ed.beginUndoAction()
        line, _ = ed.getCursorPosition()
        text = ("\\begin{table}[htbp]\n"
                "    \\centering\n"
                "    \\caption{}\n"
                "    \\label{tab:}\n"
                "    \\begin{tabular}{cc}\n"
                "        A & B \\\\\n"
                "    \\end{tabular}\n"
                "\\end{table}")
        ed.insert(text)
        ed.setCursorPosition(line + 2, len("    \\caption{"))
        ed.endUndoAction()
        ed.setFocus()

    def _insert_tabular(self, env: str) -> None:
        ed = self._ed()
        if not ed:
            return
        ed.beginUndoAction()
        line, col = ed.getCursorPosition()
        if env == "tabularx":
            header = f"\\begin{{{env}}}{{\\textwidth}}{{}}"
            cursor_col = col + len(f"\\begin{{{env}}}{{\\textwidth}}{{")
        else:
            header = f"\\begin{{{env}}}{{}}"
            cursor_col = col + len(f"\\begin{{{env}}}{{")
        text = f"{header}\n    \n\\end{{{env}}}"
        ed.insert(text)
        ed.setCursorPosition(line, cursor_col)
        ed.endUndoAction()
        ed.setFocus()

    def _insert_makebox(self) -> None:
        ed = self._ed()
        if not ed:
            return
        line, col = ed.getCursorPosition()
        ed.insert("\\makebox[]{}")
        ed.setCursorPosition(line, col + len("\\makebox["))

    def _insert_framebox(self) -> None:
        ed = self._ed()
        if not ed:
            return
        line, col = ed.getCursorPosition()
        ed.insert("\\framebox[]{}")
        ed.setCursorPosition(line, col + len("\\framebox["))

    def _insert_cite_opt(self) -> None:
        ed = self._ed()
        if not ed:
            return
        line, col = ed.getCursorPosition()
        ed.insert("\\cite[]{}")
        ed.setCursorPosition(line, col + len("\\cite["))

    def _insert_accent(self, cmd: str) -> None:
        ed = self._ed()
        if not ed:
            return
        ed.beginUndoAction()
        if ed.hasSelectedText():
            sel = ed.selectedText()
            ed.replaceSelectedText(cmd.replace("{}", f"{{{sel}}}"))
        else:
            line, col = ed.getCursorPosition()
            ed.insert(cmd)
            brace = cmd.index("{}")
            ed.setCursorPosition(line, col + brace + 1)
        ed.endUndoAction()
        ed.setFocus()

    def _open_image_dialog(self) -> None:
        ed = self._ed()
        if not ed:
            return
        from PyQt6.QtWidgets import QDialog
        from ui.latex_insert_image_dialog import LatexInsertImageDialog
        base_dir = ed.file_path.parent if ed.file_path else None
        dlg = LatexInsertImageDialog(parent=self._mw, base_dir=base_dir)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            ed.setFocus()
            return
        code = dlg.get_latex_code()
        if code:
            toolbar = getattr(self._mw, "_lang_toolbar", None)
            if toolbar and hasattr(toolbar, "_ensure_latex_package"):
                toolbar._ensure_latex_package(ed, "graphicx")
            self._insert(code)

    def _insert_magic_comment(self, text: str) -> None:
        """Inserisce il commento magico all'inizio del file."""
        ed = self._ed()
        if not ed:
            return
        ed.beginUndoAction()
        saved_line, saved_col = ed.getCursorPosition()
        ed.setCursorPosition(0, 0)
        ed.insert(text if text.endswith("\n") else text + "\n")
        ed.setCursorPosition(saved_line + 1, saved_col)
        ed.endUndoAction()
        ed.setFocus()

    # ── Navigazione etichette ─────────────────────────────────────────────────

    def _collect_labels(self, ed: "EditorWidget") -> list[tuple[int, int, str]]:
        """Restituisce [(line, col, key)] per ogni \\label{key} nel documento."""
        result = []
        for i in range(ed.lines()):
            for m in re.finditer(r"\\label\{([^}]+)\}", ed.text(i)):
                result.append((i, m.start(), m.group(1)))
        return result

    def _insert_ref_next(self) -> None:
        ed = self._ed()
        if not ed:
            return
        labels = self._collect_labels(ed)
        if not labels:
            return
        cur = ed.getCursorPosition()
        key = next((k for (l, c, k) in labels if (l, c) > cur), labels[0][2])
        ed.beginUndoAction()
        ed.insert(f"\\ref{{{key}}}")
        ed.endUndoAction()
        ed.setFocus()

    def _insert_ref_prev(self) -> None:
        ed = self._ed()
        if not ed:
            return
        labels = self._collect_labels(ed)
        if not labels:
            return
        cur = ed.getCursorPosition()
        key = next((k for (l, c, k) in reversed(labels) if (l, c) < cur),
                   labels[-1][2])
        ed.beginUndoAction()
        ed.insert(f"\\ref{{{key}}}")
        ed.endUndoAction()
        ed.setFocus()

    # ── Modifica tabelle (delega alla toolbar) ────────────────────────────────

    def _table_op(self, action: str, where: Optional[str]) -> None:
        toolbar = getattr(self._mw, "_lang_toolbar", None)
        if toolbar and hasattr(toolbar, "_table_edit"):
            toolbar._table_edit(action, where)

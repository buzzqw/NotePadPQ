"""
ui/tab_manager.py — Gestione tab multi-documento
NotePadPQ

Gestisce:
- QTabWidget custom con drag&drop, riordino, context menu
- Creazione/chiusura tab con controllo modifiche
- Accesso all'editor corrente e a tutti gli editor
- Integrazione con preview panel (split view)
- Indicatore di modifica nel titolo tab
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, List
from functools import partial

from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QFileSystemWatcher
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QTabWidget, QTabBar, QWidget, QVBoxLayout,
    QSplitter, QMenu, QApplication, QMessageBox,
)

from editor.editor_widget import EditorWidget, LineEnding
from i18n.i18n import tr

# ─── TabContainer ─────────────────────────────────────────────────────────────

class TabContainer(QWidget):
    """
    Container per un tab dell'editor.
    Gestisce il layout tra Editor, Minimap e PreviewPanel.
    Reagisce ai cambiamenti di impostazioni e linguaggio dell'editor.
    """

    def __init__(self, editor: EditorWidget, tab_manager: "TabManager"):
        super().__init__()
        self._editor = editor
        self._tab_manager = tab_manager
        self._minimap: Optional[QWidget] = None
        self._preview: Optional[QWidget] = None
        
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        
        # Splitter inizializzati a None, verranno creati in _setup_ui
        self._main_splitter = None
        self._editor_splitter = None
        
        self._setup_ui()
        
        # Connessioni
        self._editor.language_changed.connect(self._on_language_changed)

    def _setup_ui(self) -> None:
        """Costruisce il layout: editor + minimap opzionale.
        La preview è ora un dock spostabile in MainWindow, non uno split inline.
        """
        from config.settings import Settings
        settings = Settings.instance()

        show_minimap = settings.get("editor/show_minimap", False)

        # Pulisci layout
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        # Splitter editor + minimap
        self._editor_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._editor_splitter.addWidget(self._editor)

        if show_minimap:
            self._minimap = self._create_minimap()
            if self._minimap:
                minimap_side = settings.get("editor/minimap_side", "right")
                if minimap_side == "left":
                    self._editor_splitter.insertWidget(0, self._minimap)
                    self._editor_splitter.setSizes([100, 800])
                else:
                    self._editor_splitter.addWidget(self._minimap)
                    self._editor_splitter.setSizes([800, 100])

        self._layout.addWidget(self._editor_splitter)

    def _create_minimap(self) -> Optional[QWidget]:
        """Crea la minimap appropriata per l'editor (normale o LaTeX)."""
        try:
            # Determina se è LaTeX
            is_latex = False
            path = self._editor.file_path
            if path:
                ext = path.suffix.lower()
                is_latex = ext in ['.tex', '.sty', '.cls']
            
            # Se non dal path, guarda il lexer
            if not is_latex:
                lexer = self._editor.lexer()
                if lexer and hasattr(lexer, 'language'):
                    is_latex = lexer.language().lower() in ['latex', 'tex']
            
            if is_latex:
                from ui.latex_minimap import LaTeXMinimapWidget
                return LaTeXMinimapWidget(self._editor)
            else:
                from ui.minimap import MinimapWidget
                return MinimapWidget(self._editor)
        except Exception:
            try:
                from ui.minimap import MinimapWidget
                return MinimapWidget(self._editor)
            except Exception:
                return None

    def _on_language_changed(self, lang: str) -> None:
        """Aggiorna la minimap se il linguaggio cambia a/da LaTeX."""
        from config.settings import Settings
        if not Settings.instance().get("editor/show_minimap", False):
            return
            
        is_latex = lang.lower() in ["latex", "tex"]
        
        # Se abbiamo già una minimap LaTeX e il nuovo lang è LaTeX, non fare nulla
        try:
            from ui.latex_minimap import LaTeXMinimapWidget
            if is_latex and isinstance(self._minimap, LaTeXMinimapWidget):
                return
        except ImportError:
            pass
            
        # Altrimenti se abbiamo una minimap normale e il nuovo lang NON è LaTeX, non fare nulla
        from ui.minimap import MinimapWidget
        if not is_latex and isinstance(self._minimap, MinimapWidget):
            # Assicurati che non sia una sottoclasse (LaTeXMinimapWidget)
            try:
                from ui.latex_minimap import LaTeXMinimapWidget
                if not isinstance(self._minimap, LaTeXMinimapWidget):
                    return
            except ImportError:
                return
            
        # Ricostruisci UI per cambiare tipo minimap
        self._refresh()

    def _refresh(self) -> None:
        """Ricarica i componenti del tab conservando lo stato se possibile."""
        # Salva stato splitter
        e_sizes = self._editor_splitter.sizes() if self._editor_splitter else None
        m_sizes = self._main_splitter.sizes() if self._main_splitter else None
        
        # Rimuovi vecchi widget dal layout
        if self._minimap:
            self._minimap.deleteLater()
            self._minimap = None
        # preview è gestita dal dock in MainWindow
            
        self._setup_ui()
        
        # Ripristina dimensioni se possibile
        if e_sizes and self._editor_splitter:
            self._editor_splitter.setSizes(e_sizes)
        if m_sizes and self._main_splitter:
            self._main_splitter.setSizes(m_sizes)

    def editor(self) -> EditorWidget:
        return self._editor


# ─── TabBar ───────────────────────────────────────────────────────────────────

class TabBar(QTabBar):
    """QTabBar con doppio click per nuovo tab e middle click per chiudere."""

    new_tab_requested    = pyqtSignal()
    close_tab_requested  = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setExpanding(False)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.tabAt(event.pos()) == -1:
                self.new_tab_requested.emit()
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            idx = self.tabAt(event.pos())
            if idx >= 0:
                self.close_tab_requested.emit(idx)
        super().mousePressEvent(event)


class TabManager(QTabWidget):
    """
    Gestore principale dei tab. Ogni tab contiene un EditorWidget
    opzionalmente affiancato da un PreviewPanel in un QSplitter.
    """

    current_editor_changed  = pyqtSignal(object)   # EditorWidget | None
    tab_modified_changed    = pyqtSignal(object, bool)  # editor, modified
    tab_closed              = pyqtSignal(object)    # editor

    def __init__(self, parent=None):
        super().__init__(parent)

        self._tab_bar = TabBar(self)
        self.setTabBar(self._tab_bar)
        self.setDocumentMode(True)
        self.setMovable(True)

        # Mappa widget_tab → EditorWidget
        self._editors: dict[QWidget, EditorWidget] = {}
        # Mappa EditorWidget → container widget (splitter o editor stesso)
        self._containers: dict[EditorWidget, QWidget] = {}
        # Preview panel attivo
        self._preview_enabled = False

        self._setup_connections()

    def _setup_connections(self):
        self._tab_bar.new_tab_requested.connect(lambda: self.new_tab())
        self._tab_bar.close_tab_requested.connect(self._on_close_requested)
        self._tab_bar.tabCloseRequested.connect(self._on_close_requested)
        self.currentChanged.connect(self._on_current_changed)
        self._tab_bar.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._tab_bar.customContextMenuRequested.connect(
            self._show_tab_context_menu
        )

    # ── Creazione tab ─────────────────────────────────────────────────────────

    def new_tab(self, path: Optional[Path] = None,
                template_ext: str = "") -> EditorWidget:
        """
        Crea un nuovo tab con un EditorWidget.
        Se path è fornito, imposta il file_path ma non carica il contenuto
        (il caricamento è responsabilità di MainWindow.open_files).
        Se template_ext è fornito, inserisce un template base per quel tipo.
        Restituisce l'EditorWidget creato.
        """
        editor = EditorWidget()

        # Applica il tema corrente
        try:
            from config.themes import ThemeManager
            ThemeManager.instance().apply_to_editor(editor)
        except Exception:
            pass

        # Applica le impostazioni di visualizzazione salvate
        try:
            from config.settings import Settings
            from editor.editor_widget import MARGIN_FOLD
            s = Settings.instance()
            editor.set_show_line_numbers(s.get("editor/show_line_numbers", True))
            editor.setMarginWidth(MARGIN_FOLD, 14 if s.get("editor/show_fold_margin", True) else 0)
            editor.set_show_whitespace(s.get("editor/show_whitespace", False))
            editor.set_show_eol(s.get("editor/show_eol", False))
            editor.set_word_wrap(s.get("editor/word_wrap", False))
        except Exception:
            pass

        # Imposta il lexer in base al path o all'estensione template
        ext = ""
        if path:
            editor.file_path = path
            ext = path.suffix.lower()
        elif template_ext:
            ext = template_ext if template_ext.startswith(".") else f".{template_ext}"

        if ext:
            try:
                from editor.lexers import set_lexer_by_extension
                set_lexer_by_extension(editor, ext)
            except Exception:
                pass

        # Autocompletamento
        try:
            from editor.autocomplete import AutoCompleteManager
            ac = AutoCompleteManager(editor)
            ac.set_tab_manager(self)
            editor._autocomplete = ac
        except Exception:
            pass

        # Template base
        if template_ext and not path:
            content = self._get_template(template_ext)
            if content:
                editor.load_content(content)

        # Container (splitter se preview attivo, altrimenti editor diretto)
        container = self._make_container(editor)

        # Titolo tab
        name = path.name if path else tr("label.untitled")
        idx = self.addTab(container, name)
        self.setCurrentIndex(idx)

        self._editors[container] = editor
        self._containers[editor] = container

        # Connette segnali modifica
        editor.modified_changed.connect(
            lambda mod, ed=editor: self._on_editor_modified(ed, mod)
        )

        editor.setFocus()
        
        # --- MONITORAGGIO FILE ESTERNO ---
        # Creiamo una "sentinella" per questo file
        editor._watcher = QFileSystemWatcher(self)
        if path:
            # Diciamo alla sentinella di guardare il percorso del file
            editor._watcher.addPath(str(path))
            # Se la sentinella vede un cambiamento, avvisa la finestra principale
            # Usiamo partial invece di lambda per evitare bug di binding!
            editor._watcher.fileChanged.connect(partial(self.window()._on_file_changed_externally, editor))
        
        return editor

    def _make_container(self, editor: EditorWidget) -> TabContainer:
        """Crea il widget container per il tab."""
        return TabContainer(editor, self)

    def _create_minimap(self, editor: EditorWidget) -> Optional[QWidget]:
        # Logica spostata in TabContainer
        return None

    def _get_template(self, ext: str) -> str:
        """Restituisce il contenuto template per un'estensione."""
        templates = {
            ".py": '#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n\n\ndef main():\n    pass\n\n\nif __name__ == "__main__":\n    main()\n',
            ".html": '<!DOCTYPE html>\n<html lang="it">\n<head>\n    <meta charset="UTF-8">\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <title>Documento</title>\n</head>\n<body>\n\n</body>\n</html>\n',
            ".tex": '\\documentclass[a4paper,12pt]{article}\n\\usepackage[utf8]{inputenc}\n\\usepackage[T1]{fontenc}\n\\usepackage[italian]{babel}\n\\usepackage{amsmath,amssymb}\n\\usepackage{hyperref}\n\n\\title{Titolo}\n\\author{Autore}\n\\date{\\today}\n\n\\begin{document}\n\\maketitle\n\n\\section{Introduzione}\n\n\\end{document}\n',
            ".md": '# Titolo\n\n## Sezione\n\nTesto del documento.\n',
            ".sh": '#!/bin/bash\n# -*- coding: utf-8 -*-\n\nset -euo pipefail\n\nmain() {\n    echo "Hello, world!"\n}\n\nmain "$@"\n',
            ".c": '#include <stdio.h>\n#include <stdlib.h>\n\nint main(int argc, char *argv[]) {\n    printf("Hello, world!\\n");\n    return 0;\n}\n',
            ".js": '"use strict";\n\n/**\n * @description\n */\nfunction main() {\n\n}\n\nmain();\n',
        }
        return templates.get(ext.lower() if ext.startswith(".") else f".{ext}", "")

    # ── Accesso editor ────────────────────────────────────────────────────────

    def current_editor(self) -> Optional[EditorWidget]:
        """Restituisce l'EditorWidget del tab corrente."""
        container = self.currentWidget()
        if container is None:
            return None
        return self._editors.get(container)

    def editor_at(self, index: int) -> Optional[EditorWidget]:
        container = self.widget(index)
        return self._editors.get(container) if container else None

    def all_editors(self) -> List[EditorWidget]:
        return list(self._editors.values())

    def set_current_editor(self, editor: EditorWidget) -> None:
        container = self._containers.get(editor)
        if container:
            idx = self.indexOf(container)
            if idx >= 0:
                self.setCurrentIndex(idx)

    def set_current_index(self, index: int) -> None:
        self.setCurrentIndex(index)

    def find_tab_by_path(self, path: Path) -> Optional[int]:
        """Restituisce l'indice del tab con il file dato, o None."""
        for i in range(self.count()):
            ed = self.editor_at(i)
            if ed and ed.file_path and ed.file_path.resolve() == path.resolve():
                return i
        return None

    # ── Chiusura tab ─────────────────────────────────────────────────────────

    def _on_close_requested(self, index: int) -> None:
        editor = self.editor_at(index)
        if editor and editor.is_modified():
            name = (editor.file_path.name if editor.file_path
                    else tr("label.untitled"))
            reply = QMessageBox.question(
                self, "NotePadPQ",
                tr("msg.unsaved_changes", name=name),
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            elif reply == QMessageBox.StandardButton.Save:
                win = self.window()
                if hasattr(win, "action_save"):
                    self.set_current_editor(editor)
                    if not win.action_save():
                        return

        self._close_tab_at(index)

    def _close_tab_at(self, index: int) -> None:
        container = self.widget(index)
        editor = self._editors.pop(container, None)
        if editor:
            self._containers.pop(editor, None)
            self.tab_closed.emit(editor)
        self.removeTab(index)
        if self.count() == 0:
            self.new_tab()

    def close_current_tab(self) -> None:
        self._on_close_requested(self.currentIndex())

    def close_other_tabs(self) -> None:
        current = self.currentIndex()
        for i in range(self.count() - 1, -1, -1):
            if i != current:
                self._close_tab_at(i)

    def close_all_tabs(self) -> bool:
        """Chiude tutti i tab. Restituisce False se l'utente annulla."""
        for i in range(self.count() - 1, -1, -1):
            editor = self.editor_at(i)
            if editor and editor.is_modified():
                self.setCurrentIndex(i)
                self._on_close_requested(i)
                if self.count() > 0 and self.editor_at(
                    min(i, self.count()-1)
                ) == editor:
                    return False
        return True

    # ── Titolo tab ────────────────────────────────────────────────────────────

    def _on_editor_modified(self, editor: EditorWidget, modified: bool) -> None:
        container = self._containers.get(editor)
        if container is None:
            return
        idx = self.indexOf(container)
        if idx < 0:
            return
            
        # Controllo se il file proviene dall'FTP
        if hasattr(editor, "_ftp_remote_path") and editor._ftp_remote_path:
            # Estrae solo il nome del file dalla stringa del percorso (es: mio_file.txt)
            name = str(editor._ftp_remote_path).split('/')[-1]
        else:
            # File locale normale
            path = editor.file_path
            name = path.name if path else tr("label.untitled")
            
        prefix = "* " if modified else ""
        self.setTabText(idx, f"{prefix}{name}")
        self.tab_modified_changed.emit(editor, modified)

    # ── Slot cambio tab ───────────────────────────────────────────────────────

    def _on_current_changed(self, index: int) -> None:
        editor = self.editor_at(index)
        self.current_editor_changed.emit(editor)
        if editor:
            editor.setFocus()

    # ── Preview panel ─────────────────────────────────────────────────────────

    def toggle_preview(self, enabled: bool) -> None:
        """
        Attiva/disattiva la preview. La preview è ora un dock in MainWindow:
        questo metodo aggiorna solo il setting, la visibilità è gestita da MainWindow.
        """
        self._preview_enabled = enabled
        try:
            from config.settings import Settings
            Settings.instance().set("editor/show_preview", enabled)
        except Exception:
            pass
        # Non ricicrea i container — la preview è un dock esterno

    def toggle_minimap(self, enabled: bool) -> None:
        """
        Attiva/disattiva la minimap per tutti i tab.
        I tab esistenti vengono ricreati con/senza minimap.
        """
        from config.settings import Settings
        Settings.instance().set("editor/show_minimap", enabled)
        self._recreate_all_containers()

    def toggle_minimap_side(self) -> None:
        """Sposta la minimap dall'altro lato (sinistra ↔ destra)."""
        from config.settings import Settings
        s = Settings.instance()
        current = s.get("editor/minimap_side", "right")
        new_side = "left" if current == "right" else "right"
        s.set("editor/minimap_side", new_side)
        self._recreate_all_containers()

    def _recreate_all_containers(self) -> None:
        """Ricrea tutti i container dei tab per applicare le nuove impostazioni."""
        for i in range(self.count()):
            editor = self.editor_at(i)
            if not editor:
                continue
            old_container = self._containers.get(editor)
            if old_container is None:
                continue

            # Rimuove temporaneamente l'editor dal vecchio container
            editor.setParent(None)

            new_container = self._make_container(editor)
            self.removeTab(i)

            path = editor.file_path
            name = path.name if path else tr("label.untitled")
            mod  = "* " if editor.is_modified() else ""
            self.insertTab(i, new_container, f"{mod}{name}")

            # Aggiorna le mappe
            if old_container in self._editors:
                del self._editors[old_container]
            self._editors[new_container] = editor
            self._containers[editor] = new_container

        self.setCurrentIndex(min(self.currentIndex(), self.count()-1))

    # ── Context menu tab ──────────────────────────────────────────────────────

    def _show_tab_context_menu(self, pos: QPoint) -> None:
        idx = self._tab_bar.tabAt(pos)
        if idx < 0:
            return
        editor = self.editor_at(idx)
        if not editor:
            return

        menu = QMenu(self)

        act_close = menu.addAction(tr("action.close"))
        act_close.triggered.connect(lambda: self._on_close_requested(idx))

        act_others = menu.addAction(tr("action.close_others"))
        act_others.triggered.connect(lambda: (
            self.setCurrentIndex(idx), self.close_other_tabs()
        ))

        act_all = menu.addAction(tr("action.close_all"))
        act_all.triggered.connect(self.close_all_tabs)

        menu.addSeparator()

        act_copy_path = menu.addAction(tr("action.copy_path"))
        act_copy_path.setEnabled(editor.file_path is not None)
        act_copy_path.triggered.connect(
            lambda: QApplication.clipboard().setText(
                str(editor.file_path) if editor.file_path else ""
            )
        )

        act_open_dir = menu.addAction(tr("action.open_containing_dir"))
        act_open_dir.setEnabled(editor.file_path is not None)
        act_open_dir.triggered.connect(
            lambda: self._open_containing_dir(editor)
        )

        menu.addSeparator()

        act_clone = menu.addAction(tr("action.clone_document"))
        act_clone.triggered.connect(
            lambda: self._clone_tab(editor)
        )

        menu.exec(self._tab_bar.mapToGlobal(pos))

    def _open_containing_dir(self, editor: EditorWidget) -> None:
        if editor.file_path:
            from core.platform import open_path_in_filemanager
            open_path_in_filemanager(editor.file_path)

    def _clone_tab(self, editor: EditorWidget) -> None:
        content  = editor.get_content()
        encoding = editor.encoding
        le       = editor.line_ending
        new_ed   = self.new_tab()
        new_ed.load_content(content, encoding, le)

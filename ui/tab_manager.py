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
    Gestisce il layout tra Editor e PreviewPanel.
    """

    def __init__(self, editor: EditorWidget, tab_manager: "TabManager"):
        super().__init__()
        self._editor = editor
        self._tab_manager = tab_manager
        self._preview: Optional[QWidget] = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Splitter inizializzati a None, verranno creati in _setup_ui
        self._main_splitter = None
        self._editor_splitter = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Costruisce il layout: editor.
        La preview e la minimap sono dock spostabili in MainWindow.
        """
        # Pulisci layout
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        # Splitter editor
        self._editor_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._editor_splitter.addWidget(self._editor)

        self._layout.addWidget(self._editor_splitter)

    def _refresh(self) -> None:
        """Ricarica i componenti del tab."""
        self._setup_ui()

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
        # Tab custom non-editor (es. SpreadsheetWidget): widget → path opzionale
        self._custom_tabs: dict[QWidget, Optional[Path]] = {}
        # Preview panel attivo
        self._preview_enabled = False
        # Ordine di ultimo utilizzo dei tab (widget container), usato dal
        # popup Ctrl+Tab: indice 0 = tab corrente, poi in ordine di recenza.
        self._mru: List[QWidget] = []

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
            # Il lexer è già impostato prima di questa riga: propaga la lingua all'AC
            lang = getattr(editor, "_current_language", "")
            if lang:
                ac.set_language(lang.lower())
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

        # Popola le mappe PRIMA di addTab: quando currentChanged scatta,
        # editor_at() deve già trovare il container in _editors.
        self._editors[container] = editor
        self._containers[editor] = container

        idx = self.addTab(container, name)
        if path:
            self.setTabToolTip(idx, str(path))
        self.setCurrentIndex(idx)

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

    def all_custom_tabs(self) -> list:
        """Restituisce [(widget, path), ...] per tutti i tab custom aperti."""
        return list(self._custom_tabs.items())

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
        resolved = path.resolve()
        for i in range(self.count()):
            ed = self.editor_at(i)
            if ed and ed.file_path and ed.file_path.resolve() == resolved:
                return i
            # Tab custom (spreadsheet, ecc.)
            widget = self.widget(i)
            if widget in self._custom_tabs:
                p = self._custom_tabs[widget]
                if p and p.resolve() == resolved:
                    return i
        return None

    def add_spreadsheet_tab(self, widget: QWidget, title: str,
                            path: Optional[Path] = None) -> int:
        """Aggiunge un widget custom (es. SpreadsheetWidget) come nuovo tab."""
        self._custom_tabs[widget] = path
        idx = self.addTab(widget, title)
        if path:
            self.setTabToolTip(idx, str(path))
        # Aggiorna il titolo del tab direttamente da qui quando il widget
        # segnala una modifica — TabManager è un QTabWidget e ha setTabText.
        if hasattr(widget, "modified_changed"):
            widget.modified_changed.connect(
                lambda mod, w=widget: self._on_custom_tab_modified(w, mod)
            )
        self.setCurrentIndex(idx)
        return idx

    def _on_custom_tab_modified(self, widget: QWidget, modified: bool) -> None:
        idx = self.indexOf(widget)
        if idx < 0:
            return
        fp = getattr(widget, "file_path", None)
        name = fp.name if fp else self.tabText(idx).rstrip(" *")
        self.setTabText(idx, name + (" *" if modified else ""))

    def current_custom_path(self) -> Optional[Path]:
        """Se il tab corrente è un tab custom, restituisce il path; altrimenti None."""
        w = self.currentWidget()
        return self._custom_tabs.get(w) if w else None

    def current_custom_widget(self) -> Optional[QWidget]:
        """Se il tab corrente è un tab custom, restituisce il widget; altrimenti None."""
        w = self.currentWidget()
        return w if (w is not None and w in self._custom_tabs) else None

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
        elif editor is None:
            # Potrebbe essere un tab custom (spreadsheet) con modifiche non salvate
            widget = self.widget(index)
            if widget in self._custom_tabs and hasattr(widget, "is_modified") and widget.is_modified():
                path = self._custom_tabs.get(widget)
                name = path.name if path else "foglio di calcolo"
                reply = QMessageBox.question(
                    self, "NotePadPQ",
                    tr("tab_manager.save_before_close", name=name),
                    QMessageBox.StandardButton.Save |
                    QMessageBox.StandardButton.Discard |
                    QMessageBox.StandardButton.Cancel
                )
                if reply == QMessageBox.StandardButton.Cancel:
                    return
                elif reply == QMessageBox.StandardButton.Save:
                    if hasattr(widget, "save"):
                        if not widget.save():
                            return

        self._close_tab_at(index)

    def _close_tab_at(self, index: int) -> None:
        container = self.widget(index)
        if container in self._mru:
            self._mru.remove(container)
        editor = self._editors.pop(container, None)
        if editor:
            self._containers.pop(editor, None)
            watcher = getattr(editor, "_watcher", None)
            if watcher is not None:
                watcher.blockSignals(True)
                for p in watcher.files():
                    watcher.removePath(p)
            self.tab_closed.emit(editor)
        # Pulizia tab custom
        self._custom_tabs.pop(container, None)
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
        if not (hasattr(editor, "_ftp_remote_path") and editor._ftp_remote_path):
            path = editor.file_path
            self.setTabToolTip(idx, str(path) if path else "")
        self.tab_modified_changed.emit(editor, modified)

    # ── Slot cambio tab ───────────────────────────────────────────────────────

    def _on_current_changed(self, index: int) -> None:
        editor = self.editor_at(index)
        self.current_editor_changed.emit(editor)
        if editor:
            editor.setFocus()

        widget = self.widget(index) if index >= 0 else None
        if widget is not None:
            if widget in self._mru:
                self._mru.remove(widget)
            self._mru.insert(0, widget)

    def mru_widgets(self) -> List[QWidget]:
        """Container dei tab in ordine di ultimo utilizzo (indice 0 = corrente),
        usato dal popup di switch rapido Ctrl+Tab. Include eventuali tab
        aperti ma mai ancora messi a fuoco, in coda, nell'ordine delle tab."""
        seen = set(self._mru)
        rest = [self.widget(i) for i in range(self.count()) if self.widget(i) not in seen]
        return [w for w in self._mru if w is not None] + rest

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

        act_open_terminal = menu.addAction(tr("action.open_terminal"))
        act_open_terminal.setEnabled(editor.file_path is not None)
        act_open_terminal.triggered.connect(
            lambda: self._open_terminal_here(editor)
        )

        menu.addSeparator()

        act_clone = menu.addAction(tr("action.clone_document"))
        act_clone.triggered.connect(
            lambda: self._clone_tab(editor)
        )

        # FTP upload — only for local files (files opened from FTP use the panel's own upload)
        try:
            from plugins.plugin_manager import PluginManager
            ftp_entry = PluginManager.instance().get_all().get("FTP Browser")
            if ftp_entry and ftp_entry.get("enabled"):
                ftp_panel = ftp_entry["instance"]._panel
                is_ftp_file = bool(getattr(editor, "_ftp_remote_path", None))
                has_connection = ftp_panel._conn is not None
                has_current_dir = bool(ftp_panel._current_dir)
                if (not is_ftp_file) and has_connection and has_current_dir and editor.file_path:
                    menu.addSeparator()
                    dest = ftp_panel._current_dir.rstrip("/") + "/" + editor.file_path.name
                    act_ftp = menu.addAction(tr("action.ftp_upload_tab", default="Upload to FTP"))
                    act_ftp.setToolTip(dest)
                    act_ftp.triggered.connect(lambda: ftp_panel.upload_editor(editor))
        except Exception:
            pass

        menu.exec(self._tab_bar.mapToGlobal(pos))

    def _open_containing_dir(self, editor: EditorWidget) -> None:
        if editor.file_path:
            from core.platform import open_path_in_filemanager
            open_path_in_filemanager(editor.file_path)

    def _open_terminal_here(self, editor: EditorWidget) -> None:
        from core.platform import open_terminal_in_folder
        from pathlib import Path
        if editor.file_path:
            folder = str(editor.file_path.parent)
        else:
            folder = str(Path(__file__).parent.parent)
        if not open_terminal_in_folder(folder):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "NotePadPQ",
                tr("msg.no_terminal_supported")
            )

    def _clone_tab(self, editor: EditorWidget) -> None:
        content  = editor.get_content()
        encoding = editor.encoding
        le       = editor.line_ending
        new_ed   = self.new_tab()
        new_ed.load_content(content, encoding, le)

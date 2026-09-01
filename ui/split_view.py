"""
ui/split_view.py — Split View orizzontale/verticale stile Notepad++
NotePadPQ

Wrap del TabManager primario in un QSplitter che può ospitare un secondo
TabManager affiancato (side-by-side) o sovrapposto (top-bottom).

Uso da MainWindow:
    self._split_view = SplitViewManager(self)
    self.setCentralWidget(self._split_view)
    # _split_view espone la stessa API di TabManager verso MainWindow

Costanti split:
    SplitViewManager.SPLIT_SIDE_BY_SIDE  (L/R, default)
    SplitViewManager.SPLIT_TOP_BOTTOM    (T/B)

Funzionalità:
    split(orientation, clone_current)   → attiva split
    unsplit()                           → rimuove pannello secondario
    rotate_split()                      → alterna L/R ↔ T/B
    move_to_other_panel()               → sposta tab corrente nell'altro pannello
    set_sync_cursor(bool)               → sincronizza cursore tra i pannelli
    is_split()                          → True se in modalità split
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QLabel, QToolButton,
)

from i18n.i18n import tr


# ─── _PanelCorner ─────────────────────────────────────────────────────────────

class _PanelCorner(QWidget):
    """Corner widget del pannello secondario: etichetta + chiudi (stessa riga dei tab)."""

    close_requested = pyqtSignal()

    def __init__(self, label: str, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 2, 0)
        layout.setSpacing(4)

        lbl = QLabel(label)
        lbl.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(lbl)

        btn = QToolButton()
        btn.setText("✕")
        btn.setFixedSize(18, 18)
        btn.setToolTip(tr("tooltip.split_close"))
        btn.setStyleSheet(
            "QToolButton{border:none;color:#888;font-size:11px;}"
            "QToolButton:hover{color:#fff;background:#c0392b;border-radius:2px;}"
        )
        btn.clicked.connect(self.close_requested)
        layout.addWidget(btn)


# ─── _SplitPanel ──────────────────────────────────────────────────────────────

class _SplitPanel(QWidget):
    """Un pannello dello split: corner widget opzionale nel TabManager + TabManager."""

    def __init__(self, tab_manager, label: str, show_header: bool = False, parent=None):
        super().__init__(parent)
        self.tab_manager = tab_manager

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(tab_manager, 1)

        # Il corner widget viene aggiunto al QTabWidget per stare sulla stessa riga dei tab
        self._corner: Optional[_PanelCorner] = None
        if show_header:
            self._corner = _PanelCorner(label)
            tab_manager.setCornerWidget(self._corner, Qt.Corner.TopRightCorner)

    def set_header_visible(self, visible: bool) -> None:
        if self._corner is not None:
            self._corner.setVisible(visible)

    def header(self) -> Optional[_PanelCorner]:
        return self._corner


# ─── SplitViewManager ─────────────────────────────────────────────────────────

class SplitViewManager(QWidget):
    """
    Widget centrale di MainWindow. Gestisce uno o due pannelli TabManager
    in un QSplitter configurabile come verticale (side-by-side) o
    orizzontale (top-bottom), esattamente come Notepad++.

    Espone la stessa API pubblica di TabManager in modo che MainWindow
    non debba distinguere tra modalità split e non-split.
    """

    # Segnali identici a TabManager (MainWindow si connette qui)
    current_editor_changed = pyqtSignal(object)   # EditorWidget | None
    tab_modified_changed   = pyqtSignal(object, bool)
    tab_closed             = pyqtSignal(object)

    # Costanti orientamento
    SPLIT_SIDE_BY_SIDE = Qt.Orientation.Horizontal
    SPLIT_TOP_BOTTOM   = Qt.Orientation.Vertical

    def __init__(self, parent=None):
        super().__init__(parent)

        from ui.tab_manager import TabManager

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(5)
        layout.addWidget(self._splitter)

        # Pannello primario (sempre presente)
        self._primary = _SplitPanel(TabManager(self), tr("split_view.panel1"), show_header=False)
        self._splitter.addWidget(self._primary)

        self._secondary: Optional[_SplitPanel] = None
        self._active: _SplitPanel = self._primary
        self._sync_cursor: bool = False
        self._sync_zoom: bool = False
        self._sync_zoom_guard: bool = False

        self._connect_panel(self._primary)

    # ── Proxy API → compatibile con MainWindow che usava TabManager ───────────

    def current_editor(self):
        return self._active.tab_manager.current_editor()

    def active_tab_manager(self):
        """TabManager del pannello attualmente attivo (usato dal popup Ctrl+Tab)."""
        return self._active.tab_manager

    def notify_editor_focus(self, editor) -> None:
        """
        Aggiorna il pannello attivo quando un editor riceve il focus, anche
        senza cambiare tab (es. click diretto nell'editor del pannello
        secondario in split view). Senza questo, azioni come "chiudi tab
        corrente", "sposta nell'altro pannello" o il popup Ctrl+Tab restano
        agganciate all'ultimo pannello che ha cambiato tab, non a quello
        realmente a fuoco. Chiamata da MainWindow.eventFilter su FocusIn.
        """
        if self._secondary is None:
            return  # vista singola: non c'è ambiguità da risolvere
        for panel in self._panels():
            if editor in panel.tab_manager.all_editors():
                self._active = panel
                return

    def new_tab(self, **kwargs):
        return self._active.tab_manager.new_tab(**kwargs)

    def open_files(self, paths: list) -> None:
        """Apre i file nel pannello attivo (chiamato da MainWindow.open_files)."""
        # Non usato direttamente — MainWindow chiama open_files che usa self._tab_manager
        pass

    def all_editors(self) -> list:
        eds = list(self._primary.tab_manager.all_editors())
        if self._secondary:
            eds += list(self._secondary.tab_manager.all_editors())
        return eds

    def all_custom_tabs(self) -> list:
        """Restituisce [(widget, path), ...] da tutti i pannelli."""
        result = []
        for panel in self._panels():
            result.extend(panel.tab_manager.all_custom_tabs())
        return result

    def find_tab_by_path(self, path: Path) -> Optional[int]:
        idx = self._primary.tab_manager.find_tab_by_path(path)
        if idx is not None:
            return idx
        if self._secondary:
            return self._secondary.tab_manager.find_tab_by_path(path)
        return None

    def set_current_index(self, idx: int) -> None:
        self._active.tab_manager.set_current_index(idx)

    def set_current_editor(self, editor) -> None:
        for panel in self._panels():
            if editor in panel.tab_manager.all_editors():
                self._active = panel
                panel.tab_manager.set_current_editor(editor)
                return

    def close_current_tab(self) -> None:
        self._active.tab_manager.close_current_tab()

    def close_other_tabs(self) -> None:
        self._active.tab_manager.close_other_tabs()

    def close_all_tabs(self) -> bool:
        ok = self._primary.tab_manager.close_all_tabs()
        if self._secondary:
            ok = self._secondary.tab_manager.close_all_tabs() and ok
        return ok

    def tab_manager_for(self, editor):
        """Restituisce il TabManager che contiene editor, o None."""
        for panel in self._panels():
            if editor in panel.tab_manager._containers:
                return panel.tab_manager
        return None

    def currentIndex(self) -> int:
        return self._active.tab_manager.currentIndex()

    def count(self) -> int:
        n = self._primary.tab_manager.count()
        if self._secondary:
            n += self._secondary.tab_manager.count()
        return n

    def indexOf(self, widget) -> int:
        """Cerca il widget tra tutti i pannelli; restituisce -1 se non trovato."""
        for panel in self._panels():
            idx = panel.tab_manager.indexOf(widget)
            if idx >= 0:
                return idx
        return -1

    def set_tab_text_for_widget(self, widget, text: str) -> None:
        """Imposta il testo del tab che contiene widget, cercando in tutti i pannelli."""
        for panel in self._panels():
            idx = panel.tab_manager.indexOf(widget)
            if idx >= 0:
                panel.tab_manager.setTabText(idx, text)
                return

    def setTabText(self, index: int, text: str) -> None:
        """Proxy difensivo: delega al pannello attivo (compatibilità con vecchio codice)."""
        try:
            self._active.tab_manager.setTabText(index, text)
        except Exception:
            pass

    def add_spreadsheet_tab(self, widget, title: str, path=None) -> int:
        """Aggiunge un tab spreadsheet nel pannello attivo."""
        return self._active.tab_manager.add_spreadsheet_tab(widget, title, path)

    def current_custom_path(self):
        """Path del tab custom attivo, o None."""
        return self._active.tab_manager.current_custom_path()

    def current_custom_widget(self):
        """Widget custom del tab attivo (es. SpreadsheetWidget), o None se è un editor."""
        tm = self._active.tab_manager
        w = tm.currentWidget()
        if w is not None and w in tm._custom_tabs:
            return w
        return None

    # ── Split / Unsplit ───────────────────────────────────────────────────────

    def split(self, orientation: Qt.Orientation = SPLIT_SIDE_BY_SIDE,
              clone_current: bool = True) -> None:
        """
        Attiva la split view. Se già attiva cambia solo l'orientamento.

        orientation : SPLIT_SIDE_BY_SIDE (L/R) o SPLIT_TOP_BOTTOM (T/B)
        clone_current: se True clona il file corrente nel secondo pannello
        """
        from ui.tab_manager import TabManager

        self._splitter.setOrientation(orientation)

        if self._secondary is None:
            secondary_tm = TabManager(self)
            self._secondary = _SplitPanel(secondary_tm, tr("split_view.panel2"), show_header=True)
            self._secondary.header().close_requested.connect(self.unsplit)
            self._splitter.addWidget(self._secondary)
            self._connect_panel(self._secondary)

            # Clona il tab corrente o apri tab vuoto
            editor = self._primary.tab_manager.current_editor()
            if clone_current and editor:
                new_ed = secondary_tm.new_tab(path=editor.file_path)
                new_ed.load_content(
                    editor.get_content(),
                    editor.encoding,
                    editor.line_ending,
                )
                line, col = editor.getCursorPosition()
                new_ed.setCursorPosition(line, col)
                new_ed.ensureLineVisible(line)
            else:
                secondary_tm.new_tab()

            if self._sync_zoom:
                self.set_sync_zoom(True)

        # Distribuzione equa
        total = (self._splitter.width()
                 if orientation == Qt.Orientation.Horizontal
                 else self._splitter.height())
        half = max(200, total // 2)
        self._splitter.setSizes([half, half])
        self._secondary.show()

    def unsplit(self) -> None:
        """Rimuove il pannello secondario e torna alla vista singola."""
        if self._secondary is None:
            return

        # Chiudi tab del secondario silenziosamente
        tm = self._secondary.tab_manager
        for i in range(tm.count() - 1, -1, -1):
            container = tm.widget(i)
            editor = tm._editors.pop(container, None)
            if editor:
                tm._containers.pop(editor, None)
                self.tab_closed.emit(editor)
            tm.removeTab(i)

        self._secondary.setParent(None)
        self._secondary.deleteLater()
        self._secondary = None
        self._active = self._primary

        ed = self._primary.tab_manager.current_editor()
        if ed:
            ed.setFocus()

    def rotate_split(self) -> None:
        """Alterna tra split L/R e T/B."""
        if self._secondary is None:
            return
        cur = self._splitter.orientation()
        new_ori = (Qt.Orientation.Vertical
                   if cur == Qt.Orientation.Horizontal
                   else Qt.Orientation.Horizontal)
        self._splitter.setOrientation(new_ori)

    def is_split(self) -> bool:
        return self._secondary is not None

    def split_orientation(self) -> Qt.Orientation:
        return self._splitter.orientation()

    # ── Sposta tab tra pannelli ───────────────────────────────────────────────

    def move_to_other_panel(self) -> None:
        """
        Sposta il tab corrente dal pannello attivo all'altro.
        Se non c'è split, lo attiva prima (senza clonare).
        """
        if self._secondary is None:
            self.split(clone_current=False)

        src = self._active
        dst = self._secondary if src is self._primary else self._primary

        editor = src.tab_manager.current_editor()
        if not editor:
            return

        # Salva stato
        content  = editor.get_content()
        encoding = editor.encoding
        le       = editor.line_ending
        path     = editor.file_path
        line, col = editor.getCursorPosition()

        # Chiudi sorgente senza dialog
        idx = src.tab_manager.currentIndex()
        src.tab_manager._close_tab_at(idx)

        # Apri nel pannello destinazione
        new_ed = dst.tab_manager.new_tab(path=path)
        new_ed.load_content(content, encoding, le)
        new_ed.setCursorPosition(line, col)
        new_ed.ensureLineVisible(line)
        self._active = dst

    # ── Sincronizzazione cursore ──────────────────────────────────────────────

    def set_sync_cursor(self, enabled: bool) -> None:
        """
        Sincronizza cursore e scroll tra i due pannelli.
        Quando un pannello sposta il cursore o scorre, l'altro si allinea.
        """
        self._sync_cursor = enabled
        self._sync_scroll_guard = False

        # Disconnetti connessioni precedenti
        for ed, slots in getattr(self, "_sync_connections", {}).items():
            cursor_slot, scroll_slot = slots
            try:
                ed.cursor_changed.disconnect(cursor_slot)
            except Exception:
                pass
            try:
                ed.verticalScrollBar().valueChanged.disconnect(scroll_slot)
            except Exception:
                pass
        self._sync_connections: dict = {}

        if not enabled:
            return

        for panel in self._panels():
            for ed in panel.tab_manager.all_editors():
                cursor_slot = lambda ln, col, e=ed: self._on_sync_cursor_from(e, ln, col)
                scroll_slot = lambda val, e=ed: self._on_sync_scroll_from(e, val)
                ed.cursor_changed.connect(cursor_slot)
                ed.verticalScrollBar().valueChanged.connect(scroll_slot)
                self._sync_connections[ed] = (cursor_slot, scroll_slot)

    def set_sync_zoom(self, enabled: bool) -> None:
        """Sincronizza il livello di zoom tra gli editor dei due pannelli."""
        self._sync_zoom = enabled
        self._sync_zoom_guard = False

        for ed, slot in getattr(self, "_sync_zoom_connections", {}).items():
            try:
                ed.zoom_changed.disconnect(slot)
            except Exception:
                pass
        self._sync_zoom_connections: dict = {}

        if not enabled:
            return

        for panel in self._panels():
            for ed in panel.tab_manager.all_editors():
                slot = lambda level, e=ed: self._on_sync_zoom_from(e, level)
                ed.zoom_changed.connect(slot)
                self._sync_zoom_connections[ed] = slot

        primary_ed = self._primary.tab_manager.current_editor()
        secondary_ed = (self._secondary.tab_manager.current_editor()
                        if self._secondary is not None else None)
        if primary_ed is not None and secondary_ed is not None:
            self._on_sync_zoom_from(primary_ed, primary_ed.zoom_level)

    def _on_sync_zoom_from(self, sender_ed, level: int) -> None:
        if self._sync_zoom_guard:
            return
        in_primary = sender_ed in self._primary.tab_manager.all_editors()
        other = self._secondary if in_primary else self._primary
        if other is None:
            return
        other_ed = other.tab_manager.current_editor()
        if other_ed is None or other_ed is sender_ed:
            return
        self._sync_zoom_guard = True
        try:
            other_ed.zoomTo(level)
        finally:
            self._sync_zoom_guard = False

    def _on_sync_cursor_from(self, sender_ed, line: int, col: int) -> None:
        """line e col sono 1-based (da cursor_changed); converti a 0-based per QScintilla."""
        in_primary = sender_ed in self._primary.tab_manager.all_editors()
        other = self._secondary if in_primary else self._primary
        if other is None:
            return
        other_ed = other.tab_manager.current_editor()
        if other_ed and other_ed is not sender_ed:
            line0 = max(0, min(line - 1, other_ed.lines() - 1))
            col0  = max(0, col - 1)
            other_ed.blockSignals(True)
            other_ed.setCursorPosition(line0, col0)
            other_ed.ensureLineVisible(line0)
            other_ed.blockSignals(False)

    def _on_sync_scroll_from(self, sender_ed, value: int) -> None:
        """Sincronizza la posizione verticale dello scroll nell'altro pannello."""
        if getattr(self, "_sync_scroll_guard", False):
            return
        in_primary = sender_ed in self._primary.tab_manager.all_editors()
        other = self._secondary if in_primary else self._primary
        if other is None:
            return
        other_ed = other.tab_manager.current_editor()
        if other_ed and other_ed is not sender_ed:
            self._sync_scroll_guard = True
            other_ed.verticalScrollBar().setValue(value)
            self._sync_scroll_guard = False

    # ── Connessioni segnali pannello ──────────────────────────────────────────

    def _connect_panel(self, panel: _SplitPanel) -> None:
        tm = panel.tab_manager
        tm.current_editor_changed.connect(
            lambda ed, p=panel: self._on_panel_editor_changed(ed, p)
        )
        tm.tab_modified_changed.connect(self.tab_modified_changed)
        tm.tab_closed.connect(self.tab_closed)

    def _on_panel_editor_changed(self, editor, panel: _SplitPanel) -> None:
        # Il pannello che emette il segnale diventa attivo
        self._active = panel
        if self._sync_zoom:
            self.set_sync_zoom(True)
        self.current_editor_changed.emit(editor)

    # ── Utility ───────────────────────────────────────────────────────────────

    def _panels(self) -> List[_SplitPanel]:
        result = [self._primary]
        if self._secondary:
            result.append(self._secondary)
        return result

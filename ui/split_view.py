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
    QLabel, QToolButton, QFrame,
)

from i18n.i18n import tr


# ─── _PanelHeader ─────────────────────────────────────────────────────────────

class _PanelHeader(QWidget):
    """Intestazione compatta per il pannello secondario: etichetta + chiudi."""

    close_requested = pyqtSignal()

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 2, 0)
        layout.setSpacing(4)

        lbl = QLabel(label)
        lbl.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(lbl)
        layout.addStretch()

        btn = QToolButton()
        btn.setText("✕")
        btn.setFixedSize(18, 18)
        btn.setToolTip("Chiudi split view")
        btn.setStyleSheet(
            "QToolButton{border:none;color:#888;font-size:11px;}"
            "QToolButton:hover{color:#fff;background:#c0392b;border-radius:2px;}"
        )
        btn.clicked.connect(self.close_requested)
        layout.addWidget(btn)


# ─── _SplitPanel ──────────────────────────────────────────────────────────────

class _SplitPanel(QWidget):
    """Un pannello dello split: header opzionale + TabManager."""

    def __init__(self, tab_manager, label: str, show_header: bool = False, parent=None):
        super().__init__(parent)
        self.tab_manager = tab_manager

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = _PanelHeader(label)
        self._header.setVisible(show_header)
        layout.addWidget(self._header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #3a3a3a;")
        sep.setVisible(show_header)
        self._sep = sep
        layout.addWidget(sep)

        layout.addWidget(tab_manager, 1)

    def set_header_visible(self, visible: bool) -> None:
        self._header.setVisible(visible)
        self._sep.setVisible(visible)

    def header(self) -> _PanelHeader:
        return self._header


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
        self._primary = _SplitPanel(TabManager(self), "① Pannello 1", show_header=False)
        self._splitter.addWidget(self._primary)

        self._secondary: Optional[_SplitPanel] = None
        self._active: _SplitPanel = self._primary
        self._sync_cursor: bool = False

        self._connect_panel(self._primary)

    # ── Proxy API → compatibile con MainWindow che usava TabManager ───────────

    def current_editor(self):
        return self._active.tab_manager.current_editor()

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

    def toggle_minimap(self, enabled: bool) -> None:
        for p in self._panels():
            p.tab_manager.toggle_minimap(enabled)

    def toggle_minimap_side(self) -> None:
        for p in self._panels():
            p.tab_manager.toggle_minimap_side()

    def currentIndex(self) -> int:
        return self._active.tab_manager.currentIndex()

    def count(self) -> int:
        n = self._primary.tab_manager.count()
        if self._secondary:
            n += self._secondary.tab_manager.count()
        return n

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
            self._secondary = _SplitPanel(secondary_tm, "② Pannello 2", show_header=True)
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
        Sincronizza il cursore tra i due pannelli.
        Quando un pannello scorre, l'altro si posiziona alla stessa riga.
        """
        self._sync_cursor = enabled
        for panel in self._panels():
            for ed in panel.tab_manager.all_editors():
                try:
                    ed.cursor_changed.disconnect(self._on_sync_cursor)
                except Exception:
                    pass
                if enabled:
                    ed.cursor_changed.connect(self._on_sync_cursor)

    def _on_sync_cursor(self, line: int, col: int) -> None:
        """Handler sync: muove il cursore nell'altro pannello."""
        sender_ed = self.sender()
        if sender_ed is None:
            return

        # Trova il pannello opposto
        in_primary = sender_ed in self._primary.tab_manager.all_editors()
        other = (self._secondary if in_primary else self._primary)
        if other is None:
            return

        other_ed = other.tab_manager.current_editor()
        if other_ed and other_ed is not sender_ed:
            other_ed.blockSignals(True)
            other_ed.setCursorPosition(line, col)
            other_ed.ensureLineVisible(line)
            other_ed.blockSignals(False)

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
        self.current_editor_changed.emit(editor)

    # ── Utility ───────────────────────────────────────────────────────────────

    def _panels(self) -> List[_SplitPanel]:
        result = [self._primary]
        if self._secondary:
            result.append(self._secondary)
        return result

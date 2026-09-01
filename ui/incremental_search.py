"""
ui/incremental_search.py — Barra di ricerca incrementale inline
NotePadPQ

Barra compatta che appare in fondo all'editor (sopra la statusbar)
quando l'utente preme Ctrl+F2 (o il tasto configurabile).
Cerca mentre si digita, senza aprire il dialog FindReplace.

Il dialog FindReplace esistente rimane intatto e accessibile con Ctrl+F.

Funzionalità:
  - Ricerca incrementale (search-as-you-type)
  - Evidenziazione dell'occorrenza corrente + tutte le altre
  - F3 / Shift+F3 per navigare avanti/indietro
  - Conta occorrenze in tempo reale ("3 di 17")
  - Match case / Regex toggle compatti
  - Escape per chiudere e riportare il focus all'editor
  - Colore campo rosso se nessun risultato trovato

Integrazione in MainWindow:
    # In _setup_dock_panels o _setup_central, dopo aver creato il layout:
    from ui.incremental_search import IncrementalSearchBar
    self._inc_search = IncrementalSearchBar(self)
    # La barra inserisce sé stessa nel layout della finestra principale
    IncrementalSearchBar.install(self)
"""

from __future__ import annotations

import re
import threading
from typing import Optional, List, TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QKeySequence, QAction, QShortcut, QPalette
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QCheckBox, QSizePolicy, QApplication,
)

from i18n.i18n import tr
from core.worker_pool import ManagedWorker

if TYPE_CHECKING:
    from ui.main_window import MainWindow
    from editor.editor_widget import EditorWidget

# Indicatore QScintilla per la ricerca incrementale
_INC_INDICATOR     = 9    # occorrenze non correnti
_INC_CUR_INDICATOR = 10   # occorrenza corrente


class _IncrementalSearchWorker(QObject):
    """Calcola i match su uno snapshot senza accedere a QScintilla."""

    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, text: str, pattern: re.Pattern):
        super().__init__()
        self._text = text
        self._pattern = pattern
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        matches = []
        try:
            for match in self._pattern.finditer(self._text):
                if self._cancelled.is_set():
                    return
                matches.append((match.start(), match.end()))
            self.finished.emit(matches)
        except Exception as exc:
            self.error.emit(str(exc))


class IncrementalSearchBar(QWidget):
    """
    Barra di ricerca incrementale. Si inserisce come widget fisso
    tra l'area tab e la statusbar di MainWindow.
    Nasce nascosta e si mostra/nasconde con toggle().
    """

    closed = pyqtSignal()

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self._mw = main_window
        self._matches: List[tuple] = []   # [(line_from, col_from, line_to, col_to)]
        self._current_idx = -1
        self._last_text   = ""
        self._search_generation = 0
        self._search_worker: Optional[ManagedWorker] = None
        self._search_workers: list[ManagedWorker] = []
        self._observed_editor = None

        self._build_ui()
        self.hide()

        # Timer per search-as-you-type (delay 120ms)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)
        self._search_timer.timeout.connect(self._do_search)

        # Aggiorna quando cambia editor
        main_window._tab_manager.current_editor_changed.connect(
            self._on_editor_changed
        )
        self._on_editor_changed(self._current_editor())

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setFixedHeight(34)
        self.setAccessibleName(tr("action.incremental_search"))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)

        # Label
        lbl = QLabel("🔍")
        lbl.setAccessibleName(tr("action.incremental_search"))
        layout.addWidget(lbl)

        # Campo testo
        self._field = QLineEdit()
        self._field.setPlaceholderText(tr("incremental_search.placeholder", default="Ricerca incrementale…  (F3 succ.  Shift+F3 prec.  Esc chiudi)"))
        self._field.setAccessibleName(tr("action.incremental_search"))
        self._field.setFixedHeight(24)
        self._field.setMinimumWidth(220)
        self._field.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._field_base_palette = self._field.palette()
        self._field.textChanged.connect(self._on_text_changed)
        self._field.returnPressed.connect(self._find_next)
        layout.addWidget(self._field)

        # Contatore occorrenze
        self._count_lbl = QLabel("")
        self._count_lbl.setAccessibleName(tr("search.no_matches", default="Search results"))
        self._count_lbl.setMinimumWidth(70)
        layout.addWidget(self._count_lbl)

        # Opzioni compatte
        self._cb_case  = QCheckBox("Aa")
        self._cb_case.setToolTip(tr("tooltip.search_case"))
        self._cb_case.setAccessibleName(tr("tooltip.search_case"))
        self._cb_case.stateChanged.connect(self._on_text_changed)
        layout.addWidget(self._cb_case)

        self._cb_regex = QCheckBox(".*")
        self._cb_regex.setToolTip(tr("tooltip.search_regex"))
        self._cb_regex.setAccessibleName(tr("tooltip.search_regex"))
        self._cb_regex.stateChanged.connect(self._on_text_changed)
        layout.addWidget(self._cb_regex)

        self._cb_word  = QCheckBox("\\b")
        self._cb_word.setToolTip(tr("tooltip.search_word"))
        self._cb_word.setAccessibleName(tr("tooltip.search_word"))
        self._cb_word.stateChanged.connect(self._on_text_changed)
        layout.addWidget(self._cb_word)

        layout.addSpacing(8)

        # Pulsanti nav
        for label, tip, slot in [
            ("▲", tr("tooltip.search_prev"), self._find_prev),
            ("▼", tr("tooltip.search_next"), self._find_next),
        ]:
            btn = QPushButton(label)
            btn.setFixedSize(26, 24)
            btn.setToolTip(tip)
            btn.setAccessibleName(tip)
            btn.clicked.connect(slot)
            layout.addWidget(btn)

        # Chiudi
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(26, 24)
        btn_close.setToolTip(tr("tooltip.search_close"))
        btn_close.setAccessibleName(tr("tooltip.search_close"))
        btn_close.clicked.connect(self.hide_bar)
        layout.addWidget(btn_close)

        # Shortcut
        QShortcut(QKeySequence("Escape"), self, self.hide_bar)
        QShortcut(QKeySequence("F3"),     self, self._find_next)
        QShortcut(QKeySequence("Shift+F3"), self, self._find_prev)

    # ── Toggle / Mostra / Nascondi ────────────────────────────────────────────

    def toggle(self) -> None:
        if self.isVisible():
            self.hide_bar()
        else:
            self.show_bar()

    def show_bar(self, prefill: str = "") -> None:
        """Mostra la barra, pre-riempie con testo selezionato o prefill."""
        if not self.isVisible():
            self.show()

        editor = self._current_editor()
        if editor and editor.hasSelectedText():
            sel = editor.selectedText()
            if "\n" not in sel:
                self._field.setText(sel)
        elif prefill:
            self._field.setText(prefill)

        self._field.setFocus()
        self._field.selectAll()
        self._do_search()

    def hide_bar(self) -> None:
        """Nasconde la barra e riporta il focus all'editor."""
        self._invalidate_search()
        self._clear_highlights()
        self.hide()
        self.closed.emit()
        ed = self._current_editor()
        if ed:
            ed.setFocus()

    # ── Ricerca ───────────────────────────────────────────────────────────────

    def _on_text_changed(self) -> None:
        self._invalidate_search()
        self._search_timer.start()

    def _on_editor_text_changed(self) -> None:
        if not self.isVisible():
            return
        self._invalidate_search()
        self._search_timer.start()

    def _invalidate_search(self) -> None:
        self._search_generation += 1
        worker = self._search_worker
        if worker is not None and worker.worker is not None:
            worker.worker.cancel()
            if worker.thread is not None and worker.thread.isRunning():
                worker.stop()
        self._search_worker = None
        self._search_workers = [item for item in self._search_workers
                                if item.thread is not None]

    def _do_search(self) -> None:
        """Avvia la ricerca su uno snapshot e aggiorna gli highlight al termine."""
        editor = self._current_editor()
        if not editor:
            return

        text   = self._field.text()
        self._last_text = text
        self._invalidate_search()
        self._clear_highlights()
        self._matches = []
        self._current_idx = -1

        if not text:
            self._count_lbl.setText("")
            self._set_field_color(False)
            return

        # Costruisce il pattern
        try:
            pattern = self._build_pattern(text)
        except re.error:
            self._set_field_color(True)
            self._count_lbl.setText("regex ✗")
            return

        doc_text = editor.text()
        generation = self._search_generation
        worker = _IncrementalSearchWorker(doc_text, pattern)
        managed = ManagedWorker(worker)
        self._search_worker = managed
        self._search_workers.append(managed)
        managed.thread.started.connect(worker.run)
        worker.finished.connect(
            lambda matches, gen=generation, ed=editor, snapshot=doc_text:
            self._apply_search_results(gen, ed, snapshot, matches)
        )
        worker.error.connect(
            lambda error, gen=generation: self._search_error(gen, error)
        )
        managed.start()

    def _search_error(self, generation: int, error: str) -> None:
        if generation != self._search_generation:
            return
        self._set_field_color(True)
        self._count_lbl.setText(error or tr("search.no_matches", default="nessuno"))

    def _apply_search_results(self, generation: int, editor,
                              doc_text: str, char_matches: list[tuple[int, int]]) -> None:
        """Converte gli offset dello snapshot in coordinate native Scintilla."""
        if generation != self._search_generation or editor is not self._current_editor():
            return
        if editor.text() != doc_text:
            return

        line_starts = [0]
        line_starts.extend(i + 1 for i, char in enumerate(doc_text) if char == "\n")

        def char_to_line_col(offset: int) -> tuple[int, int]:
            import bisect
            offset = max(0, min(offset, len(doc_text)))
            line = bisect.bisect_right(line_starts, offset) - 1
            return line, len(doc_text[line_starts[line]:offset].encode("utf-8"))

        self._matches = [
            (*char_to_line_col(start), *char_to_line_col(end))
            for start, end in char_matches
        ]
        total = len(self._matches)
        if total == 0:
            self._set_field_color(True)
            self._count_lbl.setText(tr("search.no_matches", default="nessuno"))
            return

        self._set_field_color(False)
        self._setup_indicators(editor)
        for ls, cs, le, ce in self._matches:
            editor.fillIndicatorRange(ls, cs, le, ce, _INC_INDICATOR)

        cur_line, cur_col = editor.getCursorPosition()
        cur_byte = editor.positionFromLineIndex(cur_line, cur_col)
        cur_pos = len(doc_text.encode("utf-8")[:cur_byte].decode("utf-8", "ignore"))
        nearest = 0
        for i, (start, _end) in enumerate(char_matches):
            if start >= cur_pos:
                break
            nearest = i
        self._goto(nearest)
        self._count_lbl.setText(f"{self._current_idx + 1} / {total}")

    def _build_pattern(self, text: str) -> re.Pattern:
        """Costruisce il pattern regex dalle opzioni selezionate."""
        if not self._cb_regex.isChecked():
            text = re.escape(text)
        if self._cb_word.isChecked():
            text = r"\b" + text + r"\b"
        flags = 0 if self._cb_case.isChecked() else re.IGNORECASE
        # Valida che sia una regex valida
        return re.compile(text, flags)

    def _find_next(self) -> None:
        if not self._matches:
            self._do_search()
            return
        self._goto((self._current_idx + 1) % len(self._matches))

    def _find_prev(self) -> None:
        if not self._matches:
            return
        self._goto((self._current_idx - 1) % len(self._matches))

    def _goto(self, idx: int) -> None:
        """Vai all'occorrenza idx e aggiorna l'highlight corrente."""
        editor = self._current_editor()
        if not editor or not self._matches:
            return

        total = len(self._matches)
        idx   = idx % total
        self._current_idx = idx

        ls, cs, le, ce = self._matches[idx]

        # Rimuove highlight corrente precedente
        editor.clearIndicatorRange(
            0, 0,
            editor.lines() - 1,
            len(editor.text(editor.lines() - 1)),
            _INC_CUR_INDICATOR
        )

        # Segna occorrenza corrente
        editor.fillIndicatorRange(ls, cs, le, ce, _INC_CUR_INDICATOR)

        # Naviga
        editor.setSelection(ls, cs, le, ce)
        editor.ensureLineVisible(ls)

        self._count_lbl.setText(f"{idx + 1} / {total}")

    # ── Highlight ─────────────────────────────────────────────────────────────

    def _setup_indicators(self, editor: "EditorWidget") -> None:
        editor.indicatorDefine(
            editor.IndicatorStyle.RoundBoxIndicator, _INC_INDICATOR
        )
        editor.setIndicatorForegroundColor(
            editor.palette().color(QPalette.ColorRole.AlternateBase), _INC_INDICATOR
        )
        editor.setIndicatorDrawUnder(True, _INC_INDICATOR)

        editor.indicatorDefine(
            editor.IndicatorStyle.FullBoxIndicator, _INC_CUR_INDICATOR
        )
        editor.setIndicatorForegroundColor(
            editor.palette().color(QPalette.ColorRole.Highlight), _INC_CUR_INDICATOR
        )
        editor.setIndicatorDrawUnder(True, _INC_CUR_INDICATOR)

    def _clear_highlights(self) -> None:
        editor = self._current_editor()
        if not editor:
            return
        last_line = editor.lines() - 1
        last_col  = len(editor.text(last_line))
        for ind in (_INC_INDICATOR, _INC_CUR_INDICATOR):
            editor.clearIndicatorRange(0, 0, last_line, last_col, ind)

    # ── Utility ───────────────────────────────────────────────────────────────

    def _set_field_color(self, has_error: bool) -> None:
        palette = QPalette(self._field_base_palette)
        if has_error:
            palette.setColor(QPalette.ColorRole.Base, palette.color(QPalette.ColorRole.Highlight))
            palette.setColor(QPalette.ColorRole.Text, palette.color(QPalette.ColorRole.HighlightedText))
        self._field.setPalette(palette)

    def _current_editor(self) -> Optional["EditorWidget"]:
        return self._mw._tab_manager.current_editor()

    def _on_editor_changed(self, editor) -> None:
        if self._observed_editor is not editor:
            if self._observed_editor is not None:
                try:
                    self._observed_editor.textChanged.disconnect(self._on_editor_text_changed)
                except (RuntimeError, TypeError):
                    pass
            self._observed_editor = editor
            if editor is not None:
                editor.textChanged.connect(self._on_editor_text_changed)
        self._invalidate_search()
        self._matches = []
        self._current_idx = -1
        if self.isVisible():
            self._do_search()

    # ── Installazione in MainWindow ───────────────────────────────────────────

    @staticmethod
    def install(main_window: "MainWindow") -> "IncrementalSearchBar":
        """
        Crea la barra e la inserisce nel layout della MainWindow
        tra il widget centrale e la statusbar.

        Aggiunge anche la voce di menu e la shortcut Ctrl+F2.
        """
        bar = IncrementalSearchBar(main_window)

        # Inserisce la barra sopra la statusbar
        # La MainWindow usa un layout implicito — usiamo insertWidget sul
        # layout del centralWidget container, oppure il metodo Qt nativo.
        # Il modo più robusto è aggiungere la barra come widget permanente
        # SOTTO il central widget tramite un QWidget wrapper.
        try:
            # Crea un container che impila: central_widget + inc_search_bar
            from PyQt6.QtWidgets import QWidget, QVBoxLayout
            old_central = main_window.centralWidget()
            container   = QWidget(main_window)
            vl = QVBoxLayout(container)
            vl.setContentsMargins(0, 0, 0, 0)
            vl.setSpacing(0)
            vl.addWidget(old_central, 1)
            vl.addWidget(bar)
            main_window.setCentralWidget(container)
        except Exception as e:
            print(f"[IncrementalSearchBar] install error: {e}")

        # Menu Cerca → voce Ricerca incrementale
        search_menu = main_window._menus.get("search")
        if search_menu:
            act = QAction(tr("action.incremental_search"), main_window)
            act.setShortcut(QKeySequence("Ctrl+Shift+F2"))
            act.setCheckable(True)
            act.triggered.connect(lambda checked: bar.show_bar() if checked else bar.hide_bar())
            bar.closed.connect(lambda: act.setChecked(False))
            search_menu.insertAction(search_menu.actions()[0], act)
            search_menu.insertSeparator(search_menu.actions()[1])
            main_window._actions["incremental_search"] = act

        return bar

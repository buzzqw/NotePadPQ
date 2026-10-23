"""
ui/toolbar_quick_search.py — Mini barra di ricerca rapida nella toolbar
NotePadPQ

Campo di ricerca compatto che può essere mostrato nella toolbar principale
(disattivato per default, si attiva da Visualizza ▸ Barra di ricerca rapida).
Mentre si scrive compare un elenco sotto il campo; Invio porta al risultato
selezionato.

Stessi prefissi di "Vai a..." (ui/goto_anything.py):
  (niente)  → tab aperti (nome/percorso) e testo contenuto nei file aperti
  >testo    → comandi
  :N        → riga N del file corrente
  @testo    → simboli (def/class/function...) del file corrente
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtWidgets import QLineEdit, QListWidget, QListWidgetItem

from core.text_search import fold_typography, literal_search_pattern
from i18n.i18n import I18n, tr

if TYPE_CHECKING:
    from ui.main_window import MainWindow


_MAX_ROWS = 40          # risultati massimi conservati nell'elenco
_VISIBLE_ROWS = 8       # righe visibili prima dello scroll
_MIN_POPUP_WIDTH = 460
_FAILED_LOOKUP = 0
_SEARCH_DELAY = 120     # ms di debounce mentre si digita
_MIN_CONTENT_QUERY = 3  # sotto questa lunghezza niente ricerca nel testo
_MAX_CONTENT_ROWS = 25  # risultati di testo totali
_MAX_MATCHES_PER_FILE = 5
# Budget complessivo per la ricerca nel testo: evita di copiare e scansionare
# centinaia di MB quando ci sono molti tab grandi aperti.
_MAX_CONTENT_SCAN_BYTES = 8_000_000
_SNIPPET_CHARS = 90


def _match_score(needle: str, haystack: str) -> int:
    """Punteggio fuzzy (0 = nessuna corrispondenza, più alto = migliore)."""
    needle = fold_typography(needle.strip().lower())
    haystack = fold_typography(haystack.lower())
    if not needle:
        return 1
    if haystack.startswith(needle):
        return 100
    idx = haystack.find(needle)
    if idx >= 0:
        return 80 - min(idx, 50)
    # Sottosequenza: "anl" trova "analisi"
    pos = -1
    gaps = 0
    for ch in needle:
        nxt = haystack.find(ch, pos + 1)
        if nxt < 0:
            return _FAILED_LOOKUP
        gaps += nxt - pos - 1
        pos = nxt
    return max(5, 50 - gaps)


def _snippet(line_text: str, match_start: int) -> str:
    """Ritaglia una riga lunga attorno alla corrispondenza."""
    stripped = line_text.strip()
    if len(stripped) <= _SNIPPET_CHARS:
        return stripped
    lead = len(line_text) - len(line_text.lstrip())
    start = max(0, match_start - lead)
    begin = max(0, start - 30)
    end = min(len(stripped), begin + _SNIPPET_CHARS)
    begin = max(0, end - _SNIPPET_CHARS)
    prefix = "…" if begin > 0 else ""
    suffix = "…" if end < len(stripped) else ""
    return f"{prefix}{stripped[begin:end]}{suffix}"


class ToolbarQuickSearch(QLineEdit):
    """Campo di ricerca con elenco a comparsa, da inserire nella toolbar."""

    def __init__(self, main_window: MainWindow) -> None:
        super().__init__(main_window)
        self._mw = main_window

        self.setClearButtonEnabled(True)
        self.setFixedWidth(250)
        self.setObjectName("ToolbarQuickSearch")
        self._retranslate()
        self.textChanged.connect(self._refresh)
        self.returnPressed.connect(self._execute_current)

        # La ricerca nel testo dei file può essere costosa su documenti
        # grandi: la popup viene aggiornata solo dopo una breve pausa.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(_SEARCH_DELAY)
        self._refresh_timer.timeout.connect(self._refresh_now)

        self._popup = QListWidget(main_window)
        self._popup.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self._popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._popup.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._popup.setUniformItemSizes(True)
        self._popup.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._popup.itemClicked.connect(self._on_item_clicked)

        I18n.instance().language_changed.connect(self._retranslate)

    # ── Traduzioni ────────────────────────────────────────────────────────────

    def _retranslate(self, _lang: str = "") -> None:
        placeholder = tr(
            "toolbar_quick_search.placeholder",
            default="Cerca… (>comandi  :riga  @simbolo)",
        )
        self.setPlaceholderText(placeholder)
        self.setAccessibleName(placeholder)
        self.setToolTip(tr(
            "toolbar_quick_search.tooltip",
            default=(
                "Ricerca rapida: trova tab aperti per nome o cerca nel loro "
                "testo, poi premi Invio.\n"
                "Prefissi: > comandi, : riga, @ simboli."
            ),
        ))

    # ── Costruzione risultati ─────────────────────────────────────────────────

    def _file_rows(self, query: str) -> list[tuple[str, str, object]]:
        rows = []
        tm = getattr(self._mw, "_tab_manager", None)
        editors = tm.all_editors() if tm is not None else []
        for editor in editors:
            path = getattr(editor, "file_path", None)
            name = path.name if path else tr(
                "toolbar_quick_search.untitled", default="Senza titolo")
            full = str(path) if path else ""
            name_score = _match_score(query, name)
            if name_score:
                score = name_score + 40       # il nome del file ha priorità
            elif full:
                score = _match_score(query, full)
            else:
                continue
            if score > 0:
                label = f"{name}    {full}" if full else name
                rows.append((score, label, ("file", editor)))
        rows.sort(key=lambda r: (-r[0], r[1].lower()))
        return [(label, kind, payload) for _score, label, (kind, payload) in rows]

    def _content_rows(self, query: str) -> list[tuple[str, str, object]]:
        """Cerca la stringa nel testo dei file aperti (tab non differiti)."""
        needle = query.strip()
        if len(needle) < _MIN_CONTENT_QUERY:
            return []
        # Apostrofi/virgolette/trattini tipografici e accenti NFC/NFD devono
        # corrispondere alle rispettive varianti ASCII senza spostare gli offset.
        pattern = literal_search_pattern(needle)

        rows: list[tuple[str, str, object]] = []
        remaining = _MAX_CONTENT_ROWS
        remaining_bytes = _MAX_CONTENT_SCAN_BYTES
        tm = getattr(self._mw, "_tab_manager", None)
        editors = tm.all_editors() if tm is not None else []

        for editor in editors:
            if remaining <= 0 or remaining_bytes <= 0:
                break
            # I tab di sessione non ancora caricati non hanno testo in memoria.
            if getattr(editor, "_deferred_load", False):
                continue
            try:
                doc_bytes = editor.SendScintilla(editor.SCI_GETLENGTH)
            except Exception:
                doc_bytes = None
            if doc_bytes is None:
                # Editor di test/alternativi senza API Scintilla.
                try:
                    text = editor.text()
                except Exception:
                    continue
                text_bytes = len(text.encode("utf-8"))
                take = min(text_bytes, remaining_bytes)
                if take < text_bytes:
                    text = text[:take]
                remaining_bytes -= take
            else:
                if doc_bytes <= 0:
                    continue
                take = min(doc_bytes, remaining_bytes)
                try:
                    if take < doc_bytes:
                        getter = getattr(editor, "text_prefix", None)
                        text = (getter(take) if getter is not None
                                else editor.text()[:take])
                    else:
                        text = editor.text()
                except Exception:
                    continue
                remaining_bytes -= take
            if not text:
                continue

            path = getattr(editor, "file_path", None)
            name = path.name if path else tr(
                "toolbar_quick_search.untitled", default="Senza titolo")

            found = 0
            line = 0
            last_pos = 0
            for match in pattern.finditer(text):
                line += text.count("\n", last_pos, match.start())
                last_pos = match.start()
                line_start = text.rfind("\n", 0, match.start()) + 1
                line_end = text.find("\n", match.start())
                if line_end < 0:
                    line_end = len(text)
                snippet = _snippet(
                    text[line_start:line_end], match.start() - line_start)
                label = tr(
                    "toolbar_quick_search.content_result",
                    default="{name}:{line} — {snippet}",
                    name=name,
                    line=line + 1,
                    snippet=snippet,
                )
                # Colonna in CARATTERI: setSelection usa i caratteri, non i
                # byte. La conversione serve solo agli indicatori.
                col_start = match.start() - line_start
                col_end = col_start + len(match.group(0))
                rows.append((
                    label,
                    "content",
                    (editor, line, col_start, col_end),
                ))
                found += 1
                remaining -= 1
                if found >= _MAX_MATCHES_PER_FILE or remaining <= 0:
                    break

        return rows

    def _command_rows(self, query: str) -> list[tuple[str, str, object]]:
        rows = []
        for action in getattr(self._mw, "_actions", {}).values():
            text = action.text().replace("&", "").strip()
            if not text:
                continue
            score = _match_score(query, text)
            if not score:
                continue
            shortcut = action.shortcut().toString()
            label = f"{text}    [{shortcut}]" if shortcut else text
            rows.append((score, label, ("command", action)))
        rows.sort(key=lambda r: (-r[0], r[1].lower()))
        return [(label, kind, payload) for _score, label, (kind, payload) in rows]

    def _symbol_rows(self, query: str) -> list[tuple[str, str, object]]:
        from ui.goto_anything import _SYMBOL_RE

        rows = []
        editor = self._mw._current_editor() if hasattr(self._mw, "_current_editor") else None
        if editor is None:
            return []
        for lineno, line in enumerate(editor.text().splitlines(), start=1):
            match = _SYMBOL_RE.match(line)
            if not match:
                continue
            symbol = match.group(1)
            score = _match_score(query, symbol)
            if not score:
                continue
            label = tr(
                "toolbar_quick_search.symbol_result",
                default="{symbol} — riga {line}",
                symbol=symbol,
                line=lineno,
            )
            rows.append((score, label, ("symbol", lineno)))
        rows.sort(key=lambda r: (-r[0], r[1].lower()))
        return [(label, kind, payload) for _score, label, (kind, payload) in rows]

    def _line_rows(self, query: str) -> list[tuple[str, str, object]]:
        try:
            lineno = int(query)
        except (TypeError, ValueError):
            return []
        if lineno < 1:
            return []
        label = tr(
            "toolbar_quick_search.line_result",
            default="Vai alla riga {line}",
            line=lineno,
        )
        return [(label, "line", lineno)]

    def _rows_for_query(self, text: str) -> list[tuple[str, str, object]]:
        if text.startswith(">"):
            return self._command_rows(text[1:].strip())
        if text.startswith(":"):
            return self._line_rows(text[1:].strip())
        if text.startswith("@"):
            return self._symbol_rows(text[1:].strip())
        rows = self._file_rows(text.strip())
        rows.extend(self._content_rows(text.strip()))
        return rows

    # ── Elenco a comparsa ─────────────────────────────────────────────────────

    def _refresh(self, text: str) -> None:
        """Programma l'aggiornamento della popup (debounce)."""
        query = text.strip()
        if not query or not self.hasFocus():
            self._refresh_timer.stop()
            self._popup.hide()
            return
        self._refresh_timer.start()

    def _refresh_now(self) -> None:
        query = self.text().strip()
        if not query or not self.hasFocus():
            self._popup.hide()
            return

        rows = self._rows_for_query(query)[:_MAX_ROWS]
        if not rows:
            self._popup.hide()
            return

        self._popup.clear()
        for label, kind, payload in rows:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, (kind, payload))
            item.setToolTip(label)
            self._popup.addItem(item)

        self._popup.setCurrentRow(0)
        self._position_popup()
        self._popup.show()
        self._popup.raise_()

    def _position_popup(self) -> None:
        popup = self._popup
        popup.setFixedWidth(max(self.width(), _MIN_POPUP_WIDTH))

        row_height = popup.sizeHintForRow(0)
        if row_height <= 0:
            row_height = 22
        height = min(popup.count(), _VISIBLE_ROWS) * row_height + 4
        popup.setFixedHeight(height)

        pos = self.mapToGlobal(QPoint(0, self.height()))
        screen = self.screen()
        if screen is not None:
            area = screen.availableGeometry()
            if pos.x() + popup.width() > area.right():
                pos.setX(max(area.left(), area.right() - popup.width()))
            if pos.y() + height > area.bottom():
                pos.setY(self.mapToGlobal(QPoint(0, 0)).y() - height)
        popup.move(pos)

    def hide_popup(self) -> None:
        self._popup.hide()

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self._run(*data)

    # ── Esecuzione ────────────────────────────────────────────────────────────

    def _execute_current(self) -> None:
        # Se l'aggiornamento è ancora in attesa (debounce), completa subito la
        # ricerca: altrimenti Invio eseguirebbe un risultato della query vecchia.
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()
            self._refresh_now()

        item = self._popup.currentItem()
        if item is None and self._popup.count():
            item = self._popup.item(0)
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self._run(*data)

    def _run(self, kind: str, payload: object) -> None:
        self._popup.hide()
        self.clear()

        if kind == "file":
            self._activate_editor(payload)
        elif kind == "command":
            payload.trigger()
        elif kind in ("line", "symbol"):
            self._goto_line(int(payload))
        elif kind == "content":
            self._goto_content(*payload)

    def _activate_editor(self, editor) -> None:
        tm = getattr(self._mw, "_tab_manager", None)
        if tm is not None and hasattr(tm, "set_current_editor"):
            tm.set_current_editor(editor)
        else:
            container = getattr(tm, "_containers", {}).get(editor)
            if container is not None:
                index = tm.indexOf(container)
                if index >= 0:
                    tm.setCurrentIndex(index)
        editor.setFocus()

    def _goto_line(self, lineno: int) -> None:
        editor = self._mw._current_editor() if hasattr(self._mw, "_current_editor") else None
        if editor is None:
            return
        line = max(0, lineno - 1)
        editor.setCursorPosition(line, 0)
        editor.ensureLineVisible(line)
        editor.setFocus()

    def _goto_content(self, editor, line: int, col_start: int, col_end: int) -> None:
        """Apre il tab del match e seleziona il testo trovato."""
        self._activate_editor(editor)
        if hasattr(editor, "setSelection"):
            editor.setSelection(line, col_start, line, col_end)
        else:
            editor.setCursorPosition(line, col_start)
        editor.ensureLineVisible(line)
        editor.setFocus()

    # ── Eventi ────────────────────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        key = event.key()
        count = self._popup.count()

        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self._popup.isVisible():
            row = self._popup.currentRow()
            if key == Qt.Key.Key_Down:
                row = (row + 1) % count if count else 0
            else:
                row = (row - 1) % count if count else 0
            self._popup.setCurrentRow(row)
            return

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._execute_current()
            return

        if key == Qt.Key.Key_Escape:
            self._refresh_timer.stop()
            if self._popup.isVisible():
                self._popup.hide()
            else:
                self.clear()
            return

        super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        if self.text().strip():
            self._refresh(self.text())

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        QTimer.singleShot(0, self._hide_popup_if_unfocused)

    def _hide_popup_if_unfocused(self) -> None:
        if not self.hasFocus() and not self._popup.underMouse():
            self._popup.hide()

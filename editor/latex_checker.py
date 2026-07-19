"""
editor/latex_checker.py — Controllo sintattico LaTeX in tempo reale
NotePadPQ

Rileva in background:
  - Ambienti \\begin{}/\\end{} sbilanciati
  - Riferimenti \\ref{} a label non definite
  - Citazioni \\cite{} a chiavi non trovate

Segnala gli errori tramite marcatori nel margine (gutter) e una lista
accessibile dalla MainWindow.

Uso:
    checker = LaTeXChecker(editor)
    checker.start()
    checker.check_requested.connect(my_slot)   # slot(list[dict])
"""

from __future__ import annotations

import re
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal, Qt
from PyQt6.QtGui import QColor
from PyQt6.Qsci import QsciScintilla

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

# Numero del marcatore gutter usato da questo checker (1-31, evita conflitti)
_MARKER_ERROR   = 22
_MARKER_WARNING = 23

# Simbolo nel margine: cerchio rosso per errori, triangolo giallo per warning
_MARKER_ERROR_SYM   = QsciScintilla.MarkerSymbol.Circle
_MARKER_WARNING_SYM = QsciScintilla.MarkerSymbol.RightTriangle

_RE_COMMENT  = re.compile(r'(?<!\\)%.*')
_RE_REF      = re.compile(r'\\(?:ref|eqref|pageref|cref|Cref|autoref|nameref|vref)\{([^}]+)\}')
_RE_CITE     = re.compile(r'\\(?:cite[a-zA-Z]*|parencite|footcite|textcite|autocite)\{([^}]+)\}')
_RE_BEGIN_ENV = re.compile(r'\\begin\{([^}]+)\}')
_RE_END_ENV   = re.compile(r'\\end\{([^}]+)\}')
_RE_MULTICOL  = re.compile(r'\\multicolumn\{(\d+)\}')
_COL_CHARS    = frozenset("lcrpLCRX")

# Ambienti tabellari LaTeX con specifica colonne
_TABULAR_ENVS = frozenset({
    "tabular", "tabular*", "tabularx", "tabulary",
    "array", "longtable", "supertabular", "xltabular",
})


class _CheckWorker(QThread):
    """Esegue i tre controlli LaTeX in un thread separato per non bloccare la UI."""

    done = pyqtSignal(int, list)   # (generation, list[dict])

    def __init__(self, text: str, file_path, generation: int):
        super().__init__(None)
        self._text       = text
        self._file_path  = file_path
        self._generation = generation
        self._cancelled  = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        issues: list[dict] = []
        if self._cancelled:
            return
        issues.extend(self._check_balance())
        if self._cancelled:
            return
        issues.extend(self._check_undefined_labels())
        if self._cancelled:
            return
        issues.extend(self._check_undefined_citations())
        if self._cancelled:
            return
        issues.extend(self._check_tabular_columns())
        if not self._cancelled:
            self.done.emit(self._generation, issues)

    def _check_balance(self) -> list[dict]:
        from editor.latex_support import LaTeXSupport
        raw = LaTeXSupport.check_environment_balance(self._text)
        return [
            {"line": e["line"], "severity": "error", "msg": e["msg"]}
            for e in raw
        ]

    def _check_undefined_labels(self) -> list[dict]:
        from editor.latex_support import LaTeXSupport
        fp = self._file_path
        if fp:
            defined = set(LaTeXSupport.extract_labels_multifile(fp))
        else:
            defined = set(LaTeXSupport.extract_labels(self._text))

        issues: list[dict] = []
        for lineno, line in enumerate(self._text.split("\n")):
            if self._cancelled:
                return []
            stripped = _RE_COMMENT.sub('', line)
            for m in _RE_REF.finditer(stripped):
                key = m.group(1).strip()
                if key and key not in defined:
                    issues.append({
                        "line":     lineno,
                        "severity": "warning",
                        "msg":      f"Undefined label: '{key}'",
                    })
        return issues

    def _check_undefined_citations(self) -> list[dict]:
        from editor.latex_support import LaTeXSupport
        fp = self._file_path
        if fp:
            known = set(LaTeXSupport.extract_bibtex_keys_multifile(fp))
        else:
            known = set(LaTeXSupport.extract_bibtex_keys(self._text, fp))

        if not known:
            return []

        issues: list[dict] = []
        for lineno, line in enumerate(self._text.split("\n")):
            if self._cancelled:
                return []
            stripped = _RE_COMMENT.sub('', line)
            for m in _RE_CITE.finditer(stripped):
                for key in m.group(1).split(","):
                    key = key.strip()
                    if key and key not in known:
                        issues.append({
                            "line":     lineno,
                            "severity": "warning",
                            "msg":      f"BibTeX key not found: '{key}'",
                        })
        return issues

    def _check_tabular_columns(self) -> list[dict]:
        """Controlla che le righe del corpo tabella abbiano lo stesso numero
        di colonne dichiarato nella specifica colonne (es. {llX})."""
        issues: list[dict] = []
        lines = self._text.split("\n")
        i = 0
        while i < len(lines):
            if self._cancelled:
                return issues
            stripped = _RE_COMMENT.sub('', lines[i])
            bm = _RE_BEGIN_ENV.search(stripped)
            if not bm or bm.group(1) not in _TABULAR_ENVS:
                i += 1
                continue

            env_name = bm.group(1)
            after_begin = stripped[bm.end():]
            col_spec, spec_start, spec_end = self._extract_col_spec(
                after_begin, bm.end(), env_name)
            if col_spec is None:
                i += 1
                continue
            declared = self._count_tabular_cols(col_spec)

            # Cerca il corrispondente \end{env}
            depth = 1
            end_line = i
            for j in range(i + 1, len(lines)):
                if self._cancelled:
                    return issues
                s = _RE_COMMENT.sub('', lines[j])
                depth += len(_RE_BEGIN_ENV.findall(s))
                depth -= len(_RE_END_ENV.findall(s))
                if depth <= 0:
                    end_line = j
                    break
            else:
                end_line = len(lines) - 1

            any_mismatch = False
            max_actual = 0
            for row in range(i + 1, end_line):
                if self._cancelled:
                    return issues
                rs = _RE_COMMENT.sub('', lines[row])
                if not rs.strip():
                    continue
                if re.match(r'^\s*\\(?:hline|toprule|midrule|bottomrule|cline)\b', rs):
                    continue
                if _RE_BEGIN_ENV.search(rs) or _RE_END_ENV.search(rs):
                    continue
                if '&' not in rs and not any(c in _COL_CHARS for c in rs):
                    continue
                actual = self._count_row_cols(rs)
                if actual > max_actual:
                    max_actual = actual
                if actual > 0 and actual != declared:
                    any_mismatch = True
                    # Se la riga ha più colonne del dichiarato, evidenzia
                    # da dopo la colonna declared-esima (l'& di troppo + resto)
                    hl_start = -1
                    if actual > declared:
                        amp_pos = self._nth_ampersand_pos(rs, declared)
                        if amp_pos >= 0:
                            hl_start = amp_pos  # posizione dell'& di troppo
                    issues.append({
                        "line":     row,
                        "severity": "warning",
                        "msg":      f"Colonne: {actual} nella riga, {declared} dichiarate "
                                    f"in \\begin{{{env_name}}}{{{col_spec}}}",
                        "col_line": i,
                        "col_start": spec_start,
                        "col_end":   spec_end,
                        "highlight_start": hl_start,
                        "highlight_end": len(rs) if hl_start >= 0 else -1,
                    })

            if any_mismatch:
                if declared > max_actual > 0:
                    # Troppe colonne dichiarate: evidenzia solo quelle in eccesso
                    excess = self._excess_col_positions(
                        col_spec, spec_start + 1,
                        excess_count=declared - max_actual)
                    issue_msg = (f"Scheda colonne '{col_spec}' ({declared} col) ha "
                                 f"{declared - max_actual} colonna/e di troppo "
                                 f"(le righe ne usano al massimo {max_actual})")
                else:
                    excess = []
                    issue_msg = (f"Scheda colonne '{col_spec}' ({declared} col) "
                                 f"non corrisponde alle righe della tabella")
                issues.append({
                    "line":     i,
                    "severity": "warning",
                    "msg":      issue_msg,
                    "col_line": i,
                    "col_start": spec_start,
                    "col_end":   spec_end,
                    "excess_positions": excess,
                })

            i = end_line + 1

        return issues

    @staticmethod
    def _extract_col_spec(after_begin: str, offset: int, env_name: str = ""):
        """Estrae la specifica colonne dal testo dopo \\begin{env}.
        Per tabular*/tabularx/tabulary il secondo gruppo e' la column spec
        (il primo e' la width); per gli altri ambienti e' il primo.
        Ritorna (col_spec, start, end) oppure (None, -1, -1)."""
        _TWO_ARG = frozenset({"tabular*", "tabularx", "tabulary", "xltabular"})
        target_group = 2 if env_name in _TWO_ARG else 1

        brace_depth = 0
        groups_found = 0
        start = -1
        for idx, ch in enumerate(after_begin):
            if ch == '{':
                if brace_depth == 0:
                    groups_found += 1
                    start = idx
                brace_depth += 1
            elif ch == '}':
                brace_depth -= 1
                if brace_depth == 0:
                    spec = after_begin[start + 1:idx]
                    if groups_found == target_group:
                        return spec, offset + start, offset + idx + 1
        return None, -1, -1

    @staticmethod
    def _excess_col_positions(col_spec: str, line_offset: int, excess_count: int = 0):
        """Ritorna le posizioni assolute dei caratteri colonna in eccesso.
        Se excess_count è 0, calcola le posizioni di TUTTI i caratteri colonna."""
        positions = []
        for c_idx, c in enumerate(col_spec):
            if c in _COL_CHARS:
                positions.append(line_offset + c_idx)
        if excess_count > 0 and len(positions) > excess_count:
            return positions[-excess_count:]  # ultimi N
        return positions

    @staticmethod
    def _nth_ampersand_pos(row: str, n: int) -> int:
        """Posizione (offset caratteri) dell'n-esimo & (1-based) in una riga
        tabella. Ritorna -1 se non trovato."""
        count = 0
        for i, ch in enumerate(row):
            if ch == '&':
                count += 1
                if count == n:
                    return i
        return -1

    @staticmethod
    def _count_tabular_cols(col_spec: str) -> int:
        """Conta le colonne in una specifica tabellare. Es. '|l|c|r|' → 3."""
        count = sum(1 for c in col_spec if c in _COL_CHARS)
        return max(1, count)

    @staticmethod
    def _count_row_cols(row: str) -> int:
        """Conta le colonne effettive di una riga tabella, tenendo conto
        che \\multicolumn{N}{...}{...} occupa N colonne ma conta come 1 entry."""
        multicols = _RE_MULTICOL.findall(row)
        extra_cols = sum(int(n) - 1 for n in multicols)
        cleaned = _RE_MULTICOL.sub('', row)
        return max(1, cleaned.count('&') + 1 + extra_cols)


class LaTeXChecker(QObject):
    """
    Checker LaTeX asincrono per un EditorWidget.
    Emette `issues_found` con la lista dei problemi rilevati.
    """

    issues_found = pyqtSignal(list)   # list[dict{line, severity, msg}]

    def __init__(self, editor: "EditorWidget", parent: QObject = None):
        super().__init__(parent)
        self._editor  = editor
        self._enabled = True
        self._worker: Optional[_CheckWorker] = None
        self._gen: int = 0

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(1500)  # debounce: 1.5 secondi dopo l'ultima modifica
        self._timer.timeout.connect(self._run_check)

        self._setup_markers()

    # ── Setup marcatori gutter ────────────────────────────────────────────────

    def _setup_markers(self) -> None:
        ed = self._editor
        ed.markerDefine(_MARKER_ERROR_SYM,   _MARKER_ERROR)
        ed.markerDefine(_MARKER_WARNING_SYM, _MARKER_WARNING)
        ed.setMarkerBackgroundColor(QColor("#ff4444"), _MARKER_ERROR)
        ed.setMarkerForegroundColor(QColor("#ffffff"), _MARKER_ERROR)
        ed.setMarkerBackgroundColor(QColor("#ffcc00"), _MARKER_WARNING)
        ed.setMarkerForegroundColor(QColor("#000000"), _MARKER_WARNING)

    # ── Attivazione ───────────────────────────────────────────────────────────

    def start(self) -> None:
        """Collega il checker all'editor."""
        self._editor.textChanged.connect(self._on_text_changed)

    def stop(self) -> None:
        """Scollega il checker."""
        try:
            self._editor.textChanged.disconnect(self._on_text_changed)
        except Exception:
            pass
        self._timer.stop()
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None
        self._clear_markers()
        self._clear_tabular_indicators()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self._clear_markers()
            self._clear_tabular_indicators()
            self.issues_found.emit([])

    # ── Trigger ───────────────────────────────────────────────────────────────

    def _on_text_changed(self) -> None:
        if self._enabled:
            self._timer.start()

    def force_check(self) -> None:
        """Esegui subito il controllo (es. su salvataggio file)."""
        self._timer.stop()
        self._run_check()

    # ── Controllo (asincrono) ──────────────────────────────────────────────────

    def _run_check(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

        self._gen += 1
        text = self._editor.text()
        fp   = getattr(self._editor, "file_path", None)

        worker = _CheckWorker(text, fp, self._gen)
        worker.done.connect(self._on_check_done)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _on_check_done(self, gen: int, issues: list[dict]) -> None:
        if gen != self._gen:
            return
        self._worker = None
        self._apply_markers(issues)
        self._apply_tabular_indicators(issues)
        self.issues_found.emit(issues)

    # ── Marcatori gutter ─────────────────────────────────────────────────────

    def _clear_markers(self) -> None:
        self._editor.markerDeleteAll(_MARKER_ERROR)
        self._editor.markerDeleteAll(_MARKER_WARNING)

    def _apply_markers(self, issues: list[dict]) -> None:
        self._clear_markers()
        for issue in issues:
            line = issue.get("line", 0)
            marker = (_MARKER_ERROR
                      if issue.get("severity") == "error"
                      else _MARKER_WARNING)
            self._editor.markerAdd(line, marker)

    # ── Indicatori colonne tabella ──────────────────────────────────────────

    def _clear_tabular_indicators(self) -> None:
        """Rimuove gli indicatori colonne tabella dall'editor."""
        from editor.editor_widget import INDICATOR_LATEX_COL
        ed = self._editor
        last_line = ed.lines() - 1
        if last_line < 0:
            return
        ed.clearIndicatorRange(0, 0, last_line,
                               ed.lineLength(last_line), INDICATOR_LATEX_COL)

    def _apply_tabular_indicators(self, issues: list[dict]) -> None:
        """Sottolinea con squiggly ambra: (a) & di troppo nelle righe del corpo
        tabella, (b) X in eccesso nella column spec della riga \\begin."""
        from editor.editor_widget import INDICATOR_LATEX_COL
        self._clear_tabular_indicators()
        seen = set()
        for issue in issues:
            # (a) Body row: highlight from excess & to end of line
            hs = issue.get("highlight_start")
            he = issue.get("highlight_end")
            line = issue.get("line", 0)
            if hs is not None and hs >= 0 and he is not None and he > hs:
                key = (line, hs)
                if key in seen:
                    continue
                seen.add(key)
                self._editor.fillIndicatorRange(
                    line, hs, line, he, INDICATOR_LATEX_COL
                )
                continue

            # (b) Column spec: highlight only excess column chars (if any)
            excess = issue.get("excess_positions")
            cl = issue.get("col_line")
            if excess and cl is not None:
                for pos in excess:
                    key = (cl, pos)
                    if key in seen:
                        continue
                    seen.add(key)
                    self._editor.fillIndicatorRange(
                        cl, pos, cl, pos + 1, INDICATOR_LATEX_COL
                    )

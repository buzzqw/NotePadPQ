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
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal, Qt
from PyQt6.QtGui import QColor
from PyQt6.Qsci import QsciScintilla
from editor.latex_support import strip_latex_comments

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

# Numero del marcatore gutter usato da questo checker (1-31, evita conflitti)
_MARKER_ERROR   = 22
_MARKER_WARNING = 23

# Simbolo nel margine: cerchio rosso per errori, triangolo giallo per warning
_MARKER_ERROR_SYM   = QsciScintilla.MarkerSymbol.Circle
_MARKER_WARNING_SYM = QsciScintilla.MarkerSymbol.RightTriangle

_RE_REF      = re.compile(r'\\(?:ref|eqref|pageref|cref|Cref|autoref|nameref|vref)\{([^}]+)\}')
_RE_CITE     = re.compile(r'\\(?:cite[a-zA-Z]*|parencite|footcite|textcite|autocite)\{([^}]+)\}')
_RE_BEGIN_ENV = re.compile(r'\\begin\{([^}]+)\}')
_RE_END_ENV   = re.compile(r'\\end\{([^}]+)\}')
_RE_BEGIN_END  = re.compile(r'\\(begin|end)\{([^}]+)\}')
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
        issues.extend(self._check_label_consistency())
        if self._cancelled:
            return
        issues.extend(self._check_undefined_citations())
        if self._cancelled:
            return
        issues.extend(self._check_tabular_columns())
        if not self._cancelled:
            self.done.emit(self._generation, issues)

    def _project_sources(self):
        """Restituisce i sorgenti del progetto con il testo corrente in memoria."""
        if not self._file_path:
            return [(None, self._text)]
        from editor.latex_support import LaTeXSupport
        current = Path(self._file_path).resolve()
        sources = []
        for path in LaTeXSupport.collect_project_files(current):
            try:
                source_text = (self._text if path.resolve() == current
                               else path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            sources.append((path, source_text))
        return sources or [(current, self._text)]

    def _check_balance(self) -> list[dict]:
        from editor.latex_support import LaTeXSupport
        issues = []
        for path, source in self._project_sources():
            for error in LaTeXSupport.check_environment_balance(source):
                issue = {"line": error["line"], "severity": "error",
                         "msg": error["msg"]}
                if path is not None:
                    issue["file"] = path
                issues.append(issue)
        return issues

    def _check_undefined_labels(self) -> list[dict]:
        from editor.latex_support import LaTeXSupport
        fp = self._file_path
        analysis = LaTeXSupport.analyze_label_references(self._text, fp)
        defined = {item["key"] for item in analysis["definitions"]}
        defined.update(LaTeXSupport.extract_labels(self._text))

        issues: list[dict] = []
        for occurrence in LaTeXSupport.extract_label_reference_occurrences(self._text):
            if self._cancelled:
                return []
            if occurrence["kind"] != "reference":
                continue
            key = occurrence["key"]
            if key and key not in defined:
                issues.append({
                    "line":     occurrence["line"],
                    "severity": "warning",
                    "msg":      f"Undefined label: '{key}'",
                })
        return issues

    def _check_label_consistency(self) -> list[dict]:
        """Check duplicate definitions and labels never referenced.

        Cross-file issues retain ``file`` for a future editor/navigation
        integration.  Current marker rendering deliberately handles only the
        open file, so no UI files are required by this checker refactor.
        """
        from editor.latex_support import LaTeXSupport
        analysis = LaTeXSupport.analyze_label_references(
            self._text, self._file_path,
        )
        issues: list[dict] = []
        for item in analysis["duplicates"]:
            issue = {
                "line": item["line"],
                "severity": "error",
                "msg": f"Duplicate label: '{item['key']}'",
                "label": item["key"],
            }
            if item.get("file") is not None:
                issue["file"] = item["file"]
            issues.append(issue)
        for item in analysis["unused"]:
            issue = {
                "line": item["line"],
                "severity": "warning",
                "msg": f"Unused label: '{item['key']}'",
                "label": item["key"],
            }
            if item.get("file") is not None:
                issue["file"] = item["file"]
            issues.append(issue)
        return issues

    def _check_undefined_citations(self) -> list[dict]:
        from editor.latex_support import LaTeXSupport
        fp = self._file_path
        if fp:
            known = set(LaTeXSupport.extract_bibtex_keys_multifile(fp))
            known.update(LaTeXSupport.extract_bibtex_keys(self._text, fp))
        else:
            known = set(LaTeXSupport.extract_bibtex_keys(self._text, fp))

        if not known:
            return []

        issues: list[dict] = []
        for lineno, line in enumerate(self._text.split("\n")):
            if self._cancelled:
                return []
            stripped = strip_latex_comments(line)
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
        if not self._file_path:
            return self._check_tabular_columns_single()
        issues = []
        for path, source in self._project_sources():
            worker = _CheckWorker(source, path, self._generation)
            worker._cancelled = self._cancelled
            for issue in worker._check_tabular_columns_single():
                if path is not None:
                    issue["file"] = path
                issues.append(issue)
        return issues

    def _check_tabular_columns_single(self) -> list[dict]:
        """Controlla che le righe del corpo tabella abbiano lo stesso numero
        di colonne dichiarato nella specifica colonne (es. {llX})."""
        issues: list[dict] = []
        lines = self._text.split("\n")
        i = 0
        while i < len(lines):
            if self._cancelled:
                return issues
            stripped = strip_latex_comments(lines[i])
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
                s = strip_latex_comments(lines[j])
                for match in _RE_BEGIN_END.finditer(s):
                    depth += 1 if match.group(1) == "begin" else -1
                    if depth <= 0:
                        end_line = j
                        break
                if end_line == j:
                    break
            else:
                end_line = len(lines) - 1

            any_mismatch = False
            max_actual = 0
            row_issues: list[dict] = []
            for row in range(i + 1, end_line):
                if self._cancelled:
                    return issues
                rs = strip_latex_comments(lines[row])
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
                    row_issues.append({
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
                    # Troppe colonne dichiarate (nessuna riga usa così tante
                    # colonne): evidenzia solo le X/l/c in eccesso nella
                    # colspec, senza marcare ogni singola riga del corpo.
                    excess = self._excess_col_positions(
                        col_spec, spec_start + 1,
                        excess_count=declared - max_actual)
                    issue_msg = (f"Scheda colonne '{col_spec}' ({declared} col) ha "
                                 f"{declared - max_actual} colonna/e di troppo "
                                 f"(le righe ne usano al massimo {max_actual})")
                else:
                    # Righe con colonne in eccesso rispetto al dichiarato:
                    # marca ogni riga incoerente (già evidenzia solo la
                    # parte in eccesso, dall'& di troppo in poi).
                    issues.extend(row_issues)
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

    _RE_LENGTH_MACRO = re.compile(r'^\\[A-Za-z]+$')
    _RE_LENGTH_UNIT  = re.compile(
        r'^[0-9]+(\.[0-9]+)?\s*(pt|mm|cm|in|em|ex|bp|sp|pc|dd|cc|mu|\\[A-Za-z]+)$')
    _RE_LENGTH_FRAC  = re.compile(r'^[0-9.]+\\[A-Za-z]+$')

    @classmethod
    def _looks_like_length(cls, spec: str) -> bool:
        """True se 'spec' sembra un argomento di larghezza (es. \\linewidth,
        0.5\\textwidth, 5cm) piuttosto che una column spec."""
        s = spec.strip()
        return bool(
            cls._RE_LENGTH_MACRO.match(s)
            or cls._RE_LENGTH_UNIT.match(s)
            or cls._RE_LENGTH_FRAC.match(s)
        )

    @classmethod
    def _extract_col_spec(cls, after_begin: str, offset: int, env_name: str = ""):
        """Estrae la specifica colonne dal testo dopo \\begin{env}.
        Per tabular*/tabularx/tabulary il secondo gruppo e' la column spec
        (il primo e' la width); per gli altri ambienti e' il primo. Se il
        gruppo atteso sembra invece un argomento di larghezza (es. quando
        \\tabular viene usato per errore con due gruppi), si usa l'altro
        gruppo disponibile. Ritorna (col_spec, start, end) oppure (None, -1, -1)."""
        _TWO_ARG = frozenset({"tabular*", "tabularx", "tabulary", "xltabular"})

        brace_depth = 0
        groups_found = 0
        start = -1
        groups: list[tuple[str, int, int]] = []
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
                    groups.append((spec, offset + start, offset + idx + 1))
                    if groups_found == 2:
                        break

        if not groups:
            return None, -1, -1
        if len(groups) == 1:
            return groups[0]

        preferred_idx = 1 if env_name in _TWO_ARG else 0
        other_idx = 0 if preferred_idx == 1 else 1
        preferred_is_length = cls._looks_like_length(groups[preferred_idx][0])
        other_is_length = cls._looks_like_length(groups[other_idx][0])
        if preferred_is_length and not other_is_length:
            return groups[other_idx]
        return groups[preferred_idx]

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
        positions = _CheckWorker._separator_positions(row)
        return positions[n - 1] if 0 < n <= len(positions) else -1

    @staticmethod
    def _separator_positions(row: str) -> list[int]:
        """Return unescaped, top-level column separators in a table row."""
        positions: list[int] = []
        depth = 0
        i = 0
        while i < len(row):
            ch = row[i]
            if ch == "\\" and i + 1 < len(row):
                i += 2
                continue
            if ch == "{":
                depth += 1
            elif ch == "}" and depth:
                depth -= 1
            elif ch == "&" and depth == 0:
                positions.append(i)
            i += 1
        return positions

    @staticmethod
    def _read_group(text: str, start: int) -> tuple[str, int] | None:
        if start >= len(text) or text[start] != "{":
            return None
        depth = 1
        i = start + 1
        while i < len(text):
            if text[i] == "\\" and i + 1 < len(text):
                i += 2
                continue
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start + 1:i], i + 1
            i += 1
        return None

    @classmethod
    def _multicolumn_counts(cls, row: str) -> list[int]:
        counts: list[int] = []
        for match in re.finditer(r"\\multicolumn\s*\{", row):
            group = cls._read_group(row, match.end() - 1)
            if group is None:
                continue
            try:
                counts.append(int(group[0].strip()))
            except ValueError:
                pass
        return counts

    @staticmethod
    def _count_tabular_cols(col_spec: str) -> int:
        """Conta le colonne in una specifica tabellare. Es. '|l|c|r|' → 3."""
        def count_spec(spec: str) -> int:
            count = 0
            i = 0
            while i < len(spec):
                ch = spec[i]
                if ch == "\\":
                    i += 1
                    while i < len(spec) and (spec[i].isalpha() or spec[i] == "@"):
                        i += 1
                    continue
                if ch == "*":
                    j = i + 1
                    while j < len(spec) and spec[j].isspace():
                        j += 1
                    number = _CheckWorker._read_group(spec, j)
                    if number is not None:
                        k = number[1]
                        repeated = _CheckWorker._read_group(spec, k)
                        if repeated is not None:
                            try:
                                count += int(number[0].strip()) * count_spec(repeated[0])
                                i = repeated[1]
                                continue
                            except ValueError:
                                pass
                if ch in _COL_CHARS:
                    count += 1
                    i += 1
                    if ch in "pmb" and i < len(spec) and spec[i] == "{":
                        group = _CheckWorker._read_group(spec, i)
                        if group is not None:
                            i = group[1]
                    continue
                if ch in "><!@" and i + 1 < len(spec):
                    group = _CheckWorker._read_group(spec, i + 1)
                    if group is not None:
                        i = group[1]
                        continue
                i += 1
            return count

        return max(1, count_spec(col_spec))

    @staticmethod
    def _count_row_cols(row: str) -> int:
        """Conta le colonne effettive di una riga tabella, tenendo conto
        che \\multicolumn{N}{...}{...} occupa N colonne ma conta come 1 entry."""
        extra_cols = sum(max(0, n - 1) for n in _CheckWorker._multicolumn_counts(row))
        return max(1, len(_CheckWorker._separator_positions(row)) + 1 + extra_cols)


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
        self._old_workers: set[_CheckWorker] = set()
        self._gen: int = 0
        self._started = False
        self._last_issues: list[dict] = []

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(1500)  # debounce: 1.5 secondi dopo l'ultima modifica
        self._timer.timeout.connect(self._run_check)
        editor.destroyed.connect(self.stop)

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
        if self._started:
            return
        self._editor.textChanged.connect(self._on_text_changed)
        self._started = True

    def stop(self) -> None:
        """Scollega il checker."""
        if self._started:
            try:
                self._editor.textChanged.disconnect(self._on_text_changed)
            except (RuntimeError, TypeError):
                pass
            self._started = False
        self._timer.stop()
        self._gen += 1
        self._last_issues = []
        workers = set(self._old_workers)
        self._old_workers.clear()
        if self._worker is not None:
            workers.add(self._worker)
            self._worker = None
        for worker in workers:
            try:
                worker.finished.connect(self._forget_finished_workers)
            except RuntimeError:
                pass
            if not self._retire_worker(worker):
                self._old_workers.add(worker)
        self._clear_markers()
        self._clear_tabular_indicators()
        try:
            self.issues_found.emit([])
        except RuntimeError:
            pass

    def _retire_worker(self, worker: _CheckWorker) -> bool:
        """Cancella e attende un worker senza lasciarlo vivere oltre l'editor."""
        try:
            worker.cancel()
            if worker.isRunning():
                worker.wait(1000)
            if not worker.isRunning():
                worker.deleteLater()
                return True
        except RuntimeError:
            return True
        return False

    def _forget_finished_workers(self) -> None:
        self._old_workers = {
            worker for worker in self._old_workers if worker.isRunning()
        }

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self._last_issues = []
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
        if not self._enabled or not self._started:
            return
        if self._worker is not None:
            self._worker.cancel()
            old = self._worker
            self._old_workers.add(old)
            old.finished.connect(self._forget_finished_workers)

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
        self._last_issues = list(issues)
        self._apply_markers(issues)
        self._apply_tabular_indicators(issues)
        self.issues_found.emit(issues)

    # ── Marcatori gutter ─────────────────────────────────────────────────────

    def _clear_markers(self) -> None:
        try:
            self._editor.markerDeleteAll(_MARKER_ERROR)
            self._editor.markerDeleteAll(_MARKER_WARNING)
        except RuntimeError:
            pass

    def _apply_markers(self, issues: list[dict]) -> None:
        self._clear_markers()
        current_file = getattr(self._editor, "file_path", None)
        if current_file is not None:
            try:
                current_file = Path(current_file).resolve()
            except (OSError, TypeError, ValueError):
                current_file = None
        for issue in issues:
            issue_file = issue.get("file")
            if issue_file is not None and current_file is None:
                continue
            if issue_file is not None and current_file is not None:
                try:
                    if Path(issue_file).resolve() != current_file:
                        continue
                except (OSError, TypeError, ValueError):
                    continue
            line = issue.get("line", 0)
            marker = (_MARKER_ERROR
                      if issue.get("severity") == "error"
                      else _MARKER_WARNING)
            self._editor.markerAdd(line, marker)

    # ── Indicatori colonne tabella ──────────────────────────────────────────

    def _clear_tabular_indicators(self) -> None:
        """Rimuove gli indicatori colonne tabella dall'editor."""
        try:
            from editor.editor_widget import INDICATOR_LATEX_COL
            ed = self._editor
            last_line = ed.lines() - 1
            if last_line < 0:
                return
            ed.clearIndicatorRange(0, 0, last_line,
                                   ed.lineLength(last_line), INDICATOR_LATEX_COL)
        except RuntimeError:
            pass

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

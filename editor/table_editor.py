"""
editor/table_editor.py — Editing strutturale di tabelle Markdown e LaTeX
NotePadPQ

API pubblica:
    detect_table(editor)  → dict con info tabella o None
    add_row(editor, where="below"|"above")
    add_column(editor, where="right"|"left")
    delete_row(editor)
    delete_column(editor)
"""

from __future__ import annotations

import re
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget


# ═══════════════════════════════════════════════════════════════════════════════
# Markdown
# ═══════════════════════════════════════════════════════════════════════════════

def _is_md_row(line: str) -> bool:
    s = line.strip()
    return bool(s) and s.startswith("|") and s.endswith("|")

def _is_md_sep(line: str) -> bool:
    return bool(re.match(r"^\s*\|[-:| ]+\|\s*$", line))

def _md_split(line: str) -> list[str]:
    inner = line.strip()[1:-1]  # rimuovi | iniziale e finale
    return inner.split("|")

def _md_join(cells: list[str]) -> str:
    return "|" + "|".join(cells) + "|"


def _detect_md(editor: "EditorWidget") -> Optional[dict]:
    cur_line, cur_col = editor.getCursorPosition()
    if not _is_md_row(editor.text(cur_line)):
        return None

    total = editor.lines()
    start = cur_line
    while start > 0 and _is_md_row(editor.text(start - 1)):
        start -= 1
    end = cur_line
    while end < total - 1 and _is_md_row(editor.text(end + 1)):
        end += 1

    header = editor.text(start).strip()
    col_count = header.count("|") - 1

    sep_line = -1
    for r in range(start, end + 1):
        if _is_md_sep(editor.text(r)):
            sep_line = r
            break

    cursor_col = editor.text(cur_line)[:cur_col].count("|") - 1
    cursor_col = max(0, min(cursor_col, col_count - 1))

    return {
        "type":       "markdown",
        "start":      start,
        "end":        end,
        "cur_line":   cur_line,
        "sep_line":   sep_line,
        "col_count":  col_count,
        "cursor_col": cursor_col,
    }


def _md_add_row(editor: "EditorWidget", where: str) -> bool:
    info = _detect_md(editor)
    if not info:
        return False

    n    = info["col_count"]
    sep  = info["sep_line"]
    cur  = info["cur_line"]
    new_row = _md_join([" " * 3 for _ in range(n)])

    editor.beginUndoAction()
    if where == "below":
        after = cur
        # se siamo sul separatore, la riga successiva è la prima data
        line_text = editor.text(after).rstrip("\n")
        editor.setCursorPosition(after, len(line_text))
        editor.insert(f"\n{new_row}")
        editor.setCursorPosition(after + 1, 2)
    else:
        # sopra: non salire oltre l'header
        before = max(info["start"], cur)
        if before == sep:
            before = sep + 1  # inserisci dopo il separatore
        line_text = editor.text(before).rstrip("\n")
        editor.setCursorPosition(before, 0)
        editor.insert(f"{new_row}\n")
        editor.setCursorPosition(before, 2)
    editor.endUndoAction()
    return True


def _md_add_column(editor: "EditorWidget", where: str) -> bool:
    info = _detect_md(editor)
    if not info:
        return False

    insert_pos = info["cursor_col"] + (1 if where == "right" else 0)
    start = info["start"]
    end   = info["end"]
    sep   = info["sep_line"]

    editor.beginUndoAction()
    for row in range(end, start - 1, -1):
        line = editor.text(row).rstrip("\n")
        if not _is_md_row(line):
            continue
        cells = _md_split(line)
        new_cell = "---" if row == sep else "   "
        cells.insert(insert_pos, new_cell)
        editor.setSelection(row, 0, row, len(line))
        editor.replaceSelectedText(_md_join(cells))
    editor.endUndoAction()
    return True


def _md_delete_row(editor: "EditorWidget") -> bool:
    info = _detect_md(editor)
    if not info:
        return False
    cur = info["cur_line"]
    # Non cancellare header o separatore
    if cur == info["start"] or cur == info["sep_line"]:
        return False
    editor.beginUndoAction()
    line_text = editor.text(cur)
    prev_len  = len(editor.text(cur - 1).rstrip("\n"))
    editor.setSelection(cur - 1, prev_len, cur, len(line_text.rstrip("\n")))
    editor.replaceSelectedText("")
    editor.endUndoAction()
    return True


def _md_delete_column(editor: "EditorWidget") -> bool:
    info = _detect_md(editor)
    if not info:
        return False
    if info["col_count"] <= 1:
        return False

    del_pos = info["cursor_col"]
    start = info["start"]
    end   = info["end"]

    editor.beginUndoAction()
    for row in range(end, start - 1, -1):
        line = editor.text(row).rstrip("\n")
        if not _is_md_row(line):
            continue
        cells = _md_split(line)
        if del_pos < len(cells):
            cells.pop(del_pos)
        editor.setSelection(row, 0, row, len(line))
        editor.replaceSelectedText(_md_join(cells))
    editor.endUndoAction()
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# LaTeX
# ═══════════════════════════════════════════════════════════════════════════════

_TABULAR_ENVS = frozenset({
    "tabular", "tabular*", "tabularx", "tabulary",
    "array", "longtable", "supertabular",
})
_RE_BEGIN  = re.compile(r"\\begin\{(" + "|".join(_TABULAR_ENVS) + r")\}")
_RE_END    = re.compile(r"\\end\{(" + "|".join(_TABULAR_ENVS) + r")\}")
_RE_HLINE  = re.compile(r"^\\(hline|toprule|midrule|bottomrule|cline)\b")
_COL_CHARS = frozenset("lcrpLCRX")


def _col_spec_from_line(line: str) -> str:
    """Estrae la column spec (es. '|l|c|r|') dalla riga \\begin{tabular}."""
    # Trova tutti i gruppi {...} e prendi l'ultimo che contiene caratteri colonna
    groups = re.findall(r"\{([^}]*)\}", line)
    for g in reversed(groups):
        if any(c in _COL_CHARS for c in g):
            return g
    return ""


def _count_cols(col_spec: str) -> int:
    return max(1, sum(1 for c in col_spec if c in _COL_CHARS))


def _detect_latex(editor: "EditorWidget") -> Optional[dict]:
    cur_line, cur_col = editor.getCursorPosition()
    total = editor.lines()

    # Cerca \begin{tabular...} sopra il cursore
    start_line = -1
    env_name   = ""
    for r in range(cur_line, max(-1, cur_line - 300), -1):
        line = editor.text(r)
        bm = _RE_BEGIN.search(line)
        if bm:
            start_line = r
            env_name   = bm.group(1)
            break
        if _RE_END.search(line) and r < cur_line:
            return None  # attraversato un \end prima di trovare \begin

    if start_line == -1:
        return None

    # Cerca \end{tabular...} sotto
    end_line = -1
    for r in range(cur_line, min(total, cur_line + 300)):
        if _RE_END.search(editor.text(r)):
            end_line = r
            break

    if end_line == -1:
        return None

    col_spec  = _col_spec_from_line(editor.text(start_line))
    col_count = _count_cols(col_spec)

    # Colonna cursore = numero di & prima del cursore nella riga corrente
    cursor_col = editor.text(cur_line)[:cur_col].count("&")

    return {
        "type":       "latex",
        "start":      start_line,
        "end":        end_line,
        "env_name":   env_name,
        "col_spec":   col_spec,
        "col_count":  col_count,
        "cur_line":   cur_line,
        "cursor_col": cursor_col,
    }


def _latex_add_row(editor: "EditorWidget", where: str) -> bool:
    info = _detect_latex(editor)
    if not info:
        return False

    n        = info["col_count"]
    cur      = info["cur_line"]
    new_row  = " & ".join([""] * n) + " \\\\"

    editor.beginUndoAction()
    if where == "below":
        # Trova la riga con \\ (può essere cur o la successiva)
        after = cur
        for r in range(cur, min(info["end"], cur + 5)):
            if "\\\\" in editor.text(r):
                after = r
                break
        line_text = editor.text(after).rstrip("\n")
        editor.setCursorPosition(after, len(line_text))
        editor.insert(f"\n{new_row}")
        editor.setCursorPosition(after + 1, 0)
    else:
        editor.setCursorPosition(cur, 0)
        editor.insert(f"{new_row}\n")
        editor.setCursorPosition(cur, 0)
    editor.endUndoAction()
    return True


def _latex_add_column(editor: "EditorWidget", where: str) -> bool:
    info = _detect_latex(editor)
    if not info:
        return False

    cursor_col = info["cursor_col"]
    insert_pos = cursor_col + (1 if where == "right" else 0)
    start      = info["start"]
    end        = info["end"]
    col_spec   = info["col_spec"]

    editor.beginUndoAction()

    # 1. Aggiorna col_spec nella riga \begin
    if col_spec:
        col_positions = [i for i, c in enumerate(col_spec) if c in _COL_CHARS]
        if insert_pos < len(col_positions):
            idx = col_positions[insert_pos]
        else:
            idx = len(col_spec)
        new_spec   = col_spec[:idx] + "c" + col_spec[idx:]
        header_txt = editor.text(start).rstrip("\n")
        new_header = header_txt.replace(
            "{" + col_spec + "}", "{" + new_spec + "}", 1
        )
        editor.setSelection(start, 0, start, len(header_txt))
        editor.replaceSelectedText(new_header)

    # 2. Aggiungi & a ogni riga dati (dal basso verso l'alto)
    for row in range(end - 1, start, -1):
        line     = editor.text(row).rstrip("\n")
        stripped = line.strip()
        if not stripped or _RE_HLINE.match(stripped):
            continue

        # Separa contenuto da \\ finale
        if "\\\\" in line:
            content, tail = line.rsplit("\\\\", 1)
            suffix = "\\\\" + tail
        else:
            content = line
            suffix  = ""

        cells = content.split("&")
        cells.insert(insert_pos, " ")
        new_line = "&".join(cells) + suffix

        editor.setSelection(row, 0, row, len(line))
        editor.replaceSelectedText(new_line)

    editor.endUndoAction()
    return True


def _latex_delete_row(editor: "EditorWidget") -> bool:
    info = _detect_latex(editor)
    if not info:
        return False
    cur = info["cur_line"]
    if cur == info["start"] or cur == info["end"]:
        return False
    editor.beginUndoAction()
    line_text = editor.text(cur)
    prev_len  = len(editor.text(cur - 1).rstrip("\n"))
    editor.setSelection(cur - 1, prev_len, cur, len(line_text.rstrip("\n")))
    editor.replaceSelectedText("")
    editor.endUndoAction()
    return True


def _latex_delete_column(editor: "EditorWidget") -> bool:
    info = _detect_latex(editor)
    if not info:
        return False
    if info["col_count"] <= 1:
        return False

    del_pos  = info["cursor_col"]
    start    = info["start"]
    end      = info["end"]
    col_spec = info["col_spec"]

    editor.beginUndoAction()

    # 1. Rimuovi il carattere colonna dalla spec
    if col_spec:
        col_positions = [i for i, c in enumerate(col_spec) if c in _COL_CHARS]
        if del_pos < len(col_positions):
            idx      = col_positions[del_pos]
            new_spec = col_spec[:idx] + col_spec[idx + 1:]
            # Rimuovi anche un eventuale separatore | adiacente
            if idx < len(new_spec) and new_spec[idx] == "|":
                new_spec = new_spec[:idx] + new_spec[idx + 1:]
            elif idx > 0 and new_spec[idx - 1] == "|":
                new_spec = new_spec[:idx - 1] + new_spec[idx:]
            header_txt = editor.text(start).rstrip("\n")
            new_header = header_txt.replace(
                "{" + col_spec + "}", "{" + new_spec + "}", 1
            )
            editor.setSelection(start, 0, start, len(header_txt))
            editor.replaceSelectedText(new_header)

    # 2. Rimuovi la cella dalla ogni riga dati
    for row in range(end - 1, start, -1):
        line     = editor.text(row).rstrip("\n")
        stripped = line.strip()
        if not stripped or _RE_HLINE.match(stripped):
            continue

        if "\\\\" in line:
            content, tail = line.rsplit("\\\\", 1)
            suffix = "\\\\" + tail
        else:
            content = line
            suffix  = ""

        cells = content.split("&")
        if del_pos < len(cells):
            cells.pop(del_pos)
        new_line = "&".join(cells) + suffix

        editor.setSelection(row, 0, row, len(line))
        editor.replaceSelectedText(new_line)

    editor.endUndoAction()
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# API pubblica
# ═══════════════════════════════════════════════════════════════════════════════

def detect_table(editor: "EditorWidget") -> Optional[dict]:
    """Restituisce info tabella (type, start, end, cur_line, col_count, cursor_col) o None."""
    return _detect_md(editor) or _detect_latex(editor)


def add_row(editor: "EditorWidget", where: str = "below") -> bool:
    """Aggiunge una riga vuota sopra/sotto quella corrente. Ritorna False se non in tabella."""
    return _md_add_row(editor, where) or _latex_add_row(editor, where)


def add_column(editor: "EditorWidget", where: str = "right") -> bool:
    """Aggiunge una colonna a destra/sinistra di quella corrente."""
    return _md_add_column(editor, where) or _latex_add_column(editor, where)


def delete_row(editor: "EditorWidget") -> bool:
    """Cancella la riga corrente (non cancella header/separatore)."""
    return _md_delete_row(editor) or _latex_delete_row(editor)


def delete_column(editor: "EditorWidget") -> bool:
    """Cancella la colonna corrente."""
    return _md_delete_column(editor) or _latex_delete_column(editor)

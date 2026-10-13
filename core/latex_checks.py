"""Pure LaTeX structural checks, free of Qt and of any editor dependency.

The real-time checker used to own this logic as methods of a ``QThread``
subclass, so the pure algorithms could only be reached by instantiating a
worker.  They live here instead and are consumed by:

* ``editor.latex_checker`` (which keeps only the threading/orchestration), and
* ``core.latex_index`` (which publishes a shared balance snapshot).

Everything takes plain text and returns plain data (``dict``/dataclass) so it
can run in a worker thread and be unit-tested without a QApplication.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

# ── Environment balance ───────────────────────────────────────────────────────

_BEGIN_END_RE = re.compile(r"\\(begin|end)\{([^}]+)\}")


@dataclass(frozen=True, slots=True)
class BalanceIssue:
    """One unbalanced ``\\begin``/``\\end`` occurrence, located by offset.

    ``kind`` is one of:

    * ``"unmatched_end"`` — an ``\\end`` with no open environment;
    * ``"mismatch"``      — an ``\\end`` that closes a different environment;
    * ``"unclosed"``      — a ``\\begin`` left open at end of source.
    """

    kind: str
    environment: str
    offset: int
    open_environment: str | None = None
    open_offset: int | None = None


def environment_balance(code: str) -> list[BalanceIssue]:
    """Return ``\\begin``/``\\end`` problems in ``code``.

    ``code`` must already be comment-masked (offsets preserved).  A mismatch
    does not pop the stack, matching the historical checker/support behaviour:
    ``\\begin{a}\\begin{b}\\end{a}\\end{b}`` yields two issues rather than a
    silent cascade.
    """
    stack: list[tuple[str, int]] = []
    issues: list[BalanceIssue] = []
    for match in _BEGIN_END_RE.finditer(code):
        kind, environment = match.group(1), match.group(2)
        if kind == "begin":
            stack.append((environment, match.start()))
            continue
        if not stack:
            issues.append(BalanceIssue("unmatched_end", environment, match.start()))
            continue
        top_environment, top_offset = stack[-1]
        if top_environment == environment:
            stack.pop()
            continue
        issues.append(BalanceIssue(
            "mismatch", environment, match.start(), top_environment, top_offset,
        ))
    for environment, offset in reversed(stack):
        issues.append(BalanceIssue("unclosed", environment, offset))
    return issues


def format_balance_issue(
    issue: BalanceIssue,
    line: int,
    open_line: int | None = None,
) -> dict:
    """Render one :class:`BalanceIssue` using the shared checker wording."""
    if issue.kind == "unmatched_end":
        msg = f"\\end{{{issue.environment}}} without matching \\begin"
    elif issue.kind == "mismatch":
        msg = (f"\\end{{{issue.environment}}} closes "
               f"'{issue.open_environment}' opened at line {(open_line or 0) + 1}")
    else:
        msg = f"\\begin{{{issue.environment}}} not closed"
    return {
        "line": line,
        "env": issue.environment,
        "severity": "error",
        "msg": msg,
    }


# ── Tabular column checks ─────────────────────────────────────────────────────

_COL_CHARS = frozenset("lcrpLCRX")

# LaTeX tabular environments with a column specification.
_TABULAR_ENVS = frozenset({
    "tabular", "tabular*", "tabularx", "tabulary",
    "array", "longtable", "supertabular", "xltabular",
})

_RE_BEGIN_ENV = re.compile(r"\\begin\{([^}]+)\}")
_RE_END_ENV = re.compile(r"\\end\{([^}]+)\}")
_RE_RULE = re.compile(r"^\s*\\(?:hline|toprule|midrule|bottomrule|cline)\b")
_ROW_SPECIAL_RE = re.compile(r"[\\{}&]")

_RE_LENGTH_MACRO = re.compile(r"^\\[A-Za-z]+$")
_RE_LENGTH_UNIT = re.compile(
    r"^[0-9]+(\.[0-9]+)?\s*(pt|mm|cm|in|em|ex|bp|sp|pc|dd|cc|mu|\\[A-Za-z]+)$")
_RE_LENGTH_FRAC = re.compile(r"^[0-9.]+\\[A-Za-z]+$")
_MULTICOLUMN_RE = re.compile(r"\\multicolumn\s*\{")


def read_group(text: str, start: int) -> tuple[str, int] | None:
    """Return ``(content, end)`` of the ``{...}`` group at ``start``."""
    if start >= len(text) or text[start] != "{":
        return None
    depth = 1
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:index], index + 1
        index += 1
    return None


def looks_like_length(spec: str) -> bool:
    """True when ``spec`` is a width argument rather than a column spec."""
    stripped = spec.strip()
    return bool(
        _RE_LENGTH_MACRO.match(stripped)
        or _RE_LENGTH_UNIT.match(stripped)
        or _RE_LENGTH_FRAC.match(stripped)
    )


def separator_positions(row: str) -> list[int]:
    """Return unescaped, top-level ``&`` positions in a table row.

    Scans only the special characters (``\\``, ``{``, ``}``, ``&``) in one C
    regex pass instead of iterating every character in Python.
    """
    positions: list[int] = []
    depth = 0
    skip_until = -1
    for match in _ROW_SPECIAL_RE.finditer(row):
        index = match.start()
        if index < skip_until:
            continue
        char = row[index]
        if char == "\\":
            skip_until = index + 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            if depth:
                depth -= 1
        elif char == "&" and depth == 0:
            positions.append(index)
    return positions


def multicolumn_counts(row: str) -> list[int]:
    if "\\multicolumn" not in row:
        return []
    counts: list[int] = []
    for match in _MULTICOLUMN_RE.finditer(row):
        group = read_group(row, match.end() - 1)
        if group is None:
            continue
        try:
            counts.append(int(group[0].strip()))
        except ValueError:
            pass
    return counts


def count_tabular_cols(col_spec: str) -> int:
    """Count columns in a tabular column spec. ``|l|c|r|`` → 3."""
    def count_spec(spec: str) -> int:
        count = 0
        index = 0
        while index < len(spec):
            char = spec[index]
            if char == "\\":
                index += 1
                while index < len(spec) and (spec[index].isalpha() or spec[index] == "@"):
                    index += 1
                continue
            if char == "*":
                cursor = index + 1
                while cursor < len(spec) and spec[cursor].isspace():
                    cursor += 1
                number = read_group(spec, cursor)
                if number is not None:
                    repeated = read_group(spec, number[1])
                    if repeated is not None:
                        try:
                            count += int(number[0].strip()) * count_spec(repeated[0])
                            index = repeated[1]
                            continue
                        except ValueError:
                            pass
            if char in _COL_CHARS:
                count += 1
                index += 1
                if char in "pmb" and index < len(spec) and spec[index] == "{":
                    group = read_group(spec, index)
                    if group is not None:
                        index = group[1]
                continue
            if char in "><!@" and index + 1 < len(spec):
                group = read_group(spec, index + 1)
                if group is not None:
                    index = group[1]
                    continue
            index += 1
        return count

    return max(1, count_spec(col_spec))


def count_row_cols(row: str) -> int:
    """Count effective columns of a table row, honouring ``\\multicolumn``."""
    extra_cols = sum(max(0, n - 1) for n in multicolumn_counts(row))
    return max(1, len(separator_positions(row)) + 1 + extra_cols)


def nth_ampersand_pos(row: str, n: int) -> int:
    """Offset of the n-th (1-based) ``&`` in ``row``, or ``-1``."""
    positions = separator_positions(row)
    return positions[n - 1] if 0 < n <= len(positions) else -1


def extract_col_spec(after_begin: str, offset: int, env_name: str = ""):
    """Column spec from the text following ``\\begin{env}``.

    For ``tabular*``/``tabularx``/``tabulary`` the second group is the spec
    (the first is the width); for the others it is the first.  If the expected
    group looks like a width argument the other group is used.  Returns
    ``(col_spec, start, end)`` or ``(None, -1, -1)``.
    """
    two_arg = frozenset({"tabular*", "tabularx", "tabulary", "xltabular"})

    brace_depth = 0
    groups_found = 0
    start = -1
    groups: list[tuple[str, int, int]] = []
    for index, char in enumerate(after_begin):
        if char == "{":
            if brace_depth == 0:
                groups_found += 1
                start = index
            brace_depth += 1
        elif char == "}":
            brace_depth -= 1
            if brace_depth == 0:
                spec = after_begin[start + 1:index]
                groups.append((spec, offset + start, offset + index + 1))
                if groups_found == 2:
                    break

    if not groups:
        return None, -1, -1
    if len(groups) == 1:
        return groups[0]

    preferred_idx = 1 if env_name in two_arg else 0
    other_idx = 0 if preferred_idx == 1 else 1
    if (looks_like_length(groups[preferred_idx][0])
            and not looks_like_length(groups[other_idx][0])):
        return groups[other_idx]
    return groups[preferred_idx]


def excess_col_positions(col_spec: str, line_offset: int, excess_count: int = 0):
    """Absolute offsets of column characters.

    With ``excess_count == 0`` returns all positions; otherwise only the last
    ``excess_count`` ones (the excess at the end of the spec).
    """
    positions = [line_offset + index for index, char in enumerate(col_spec)
                 if char in _COL_CHARS]
    if excess_count > 0 and len(positions) > excess_count:
        return positions[-excess_count:]
    return positions


def tabular_column_issues(
    text: str,
    already_stripped: bool = False,
    cancelled: Callable[[], bool] | None = None,
) -> list[dict]:
    """Warn when table rows disagree with their declared column count."""
    from core.latex_parser import strip_latex_comments

    issues: list[dict] = []
    lines = text.split("\n")
    index = 0
    while index < len(lines):
        if cancelled is not None and cancelled():
            return issues
        stripped = lines[index] if already_stripped else strip_latex_comments(lines[index])
        # Cheap substring pre-check: avoids a regex over every line.
        if "\\begin" not in stripped:
            index += 1
            continue
        begin_match = _RE_BEGIN_ENV.search(stripped)
        if not begin_match or begin_match.group(1) not in _TABULAR_ENVS:
            index += 1
            continue

        env_name = begin_match.group(1)
        after_begin = stripped[begin_match.end():]
        col_spec, spec_start, spec_end = extract_col_spec(
            after_begin, begin_match.end(), env_name)
        if col_spec is None:
            index += 1
            continue
        declared = count_tabular_cols(col_spec)

        depth = 1
        end_line = index
        for row_index in range(index + 1, len(lines)):
            if cancelled is not None and cancelled():
                return issues
            scan = lines[row_index] if already_stripped else strip_latex_comments(lines[row_index])
            if "\\begin" in scan or "\\end" in scan:
                for match in _BEGIN_END_RE.finditer(scan):
                    depth += 1 if match.group(1) == "begin" else -1
                    if depth <= 0:
                        end_line = row_index
                        break
            if end_line == row_index:
                break
        else:
            end_line = len(lines) - 1

        any_mismatch = False
        max_actual = 0
        row_issues: list[dict] = []
        for row in range(index + 1, end_line):
            if cancelled is not None and cancelled():
                return issues
            row_text = lines[row] if already_stripped else strip_latex_comments(lines[row])
            if not row_text.strip():
                continue
            if _RE_RULE.match(row_text):
                continue
            if ("\\begin" in row_text or "\\end" in row_text) and (
                    _RE_BEGIN_ENV.search(row_text) or _RE_END_ENV.search(row_text)):
                continue
            if "&" not in row_text and not any(c in _COL_CHARS for c in row_text):
                continue
            actual = count_row_cols(row_text)
            if actual > max_actual:
                max_actual = actual
            if actual > 0 and actual != declared:
                any_mismatch = True
                highlight_start = -1
                if actual > declared:
                    amp_pos = nth_ampersand_pos(row_text, declared)
                    if amp_pos >= 0:
                        highlight_start = amp_pos
                row_issues.append({
                    "line":     row,
                    "severity": "warning",
                    "msg":      f"Colonne: {actual} nella riga, {declared} dichiarate "
                                f"in \\begin{{{env_name}}}{{{col_spec}}}",
                    "col_line": index,
                    "col_start": spec_start,
                    "col_end":   spec_end,
                    "highlight_start": highlight_start,
                    "highlight_end": len(row_text) if highlight_start >= 0 else -1,
                })

        if any_mismatch:
            if declared > max_actual > 0:
                excess = excess_col_positions(
                    col_spec, spec_start + 1,
                    excess_count=declared - max_actual)
                issue_msg = (f"Scheda colonne '{col_spec}' ({declared} col) ha "
                             f"{declared - max_actual} colonna/e di troppo "
                             f"(le righe ne usano al massimo {max_actual})")
            else:
                issues.extend(row_issues)
                excess = []
                issue_msg = (f"Scheda colonne '{col_spec}' ({declared} col) "
                             f"non corrisponde alle righe della tabella")
            issues.append({
                "line":     index,
                "severity": "warning",
                "msg":      issue_msg,
                "col_line": index,
                "col_start": spec_start,
                "col_end":   spec_end,
                "excess_positions": excess,
            })

        index = end_line + 1

    return issues


# ── TikZ semicolon checks ─────────────────────────────────────────────────────

_RE_TIKZ_COMMAND = re.compile(
    r'\\(?:draw|path|fill|filldraw|shade|shadedraw|clip|useasboundingbox|'
    r'node|coordinate|matrix|graph|pic|foreach)\b'
)


def tikz_semicolon_issues(
    text: str,
    already_stripped: bool = False,
) -> list[dict]:
    """Warn when a TikZ drawing command is not terminated by ``;``."""
    from core.latex_parser import strip_latex_comments

    code = text if already_stripped else strip_latex_comments(text)
    events = []
    for match in _BEGIN_END_RE.finditer(code):
        if match.group(2).strip().rstrip("*") == "tikzpicture":
            events.append((match.start(),
                           "end" if match.group(1) == "end" else "begin"))
    events.extend((match.start(),
                   "foreach" if match.group(0).startswith(r"\foreach") else "command")
                  for match in _RE_TIKZ_COMMAND.finditer(code))
    events.sort(key=lambda event: event[0])

    # For each event retain the next command boundary: the old nested search
    # made this O(number_of_events²) on large TikZ drawings.
    next_boundaries = [len(code)] * len(events)
    next_boundary = len(code)
    for event_index in range(len(events) - 1, -1, -1):
        next_boundaries[event_index] = next_boundary
        if events[event_index][1] in {"command", "foreach", "end"}:
            next_boundary = events[event_index][0]

    issues: list[dict] = []
    tikz_depth = 0
    for index, (position, event_type) in enumerate(events):
        if event_type == "begin":
            tikz_depth += 1
            continue
        if event_type == "end":
            tikz_depth = max(0, tikz_depth - 1)
            continue
        if event_type == "foreach":
            continue
        if tikz_depth <= 0:
            continue
        boundary = next_boundaries[index]
        if code.find(";", position, boundary) >= 0:
            continue
        issues.append({
            "line": code.count("\n", 0, position),
            "severity": "warning",
            "msg": "TikZ command is missing a terminating ';'",
        })
    return issues


__all__ = [
    "BalanceIssue",
    "count_row_cols",
    "count_tabular_cols",
    "environment_balance",
    "excess_col_positions",
    "extract_col_spec",
    "format_balance_issue",
    "looks_like_length",
    "multicolumn_counts",
    "nth_ampersand_pos",
    "read_group",
    "separator_positions",
    "tabular_column_issues",
    "tikz_semicolon_issues",
]

r"""
editor/latex_support.py - Supporto avanzato LaTeX
NotePadPQ

Ispirato a TeXstudio. Fornisce:
- Parser struttura documento (sezioni, label, \newcommand, ambienti)
- Estrazione label, chiavi BibTeX, ambienti custom
- Auto-chiusura \begin{env} → \end{env}
- Rilevamento pacchetti \usepackage{} per completamento contestuale
- API estesa per autocompletamento per pacchetto
- Indentazione intelligente LaTeX

Uso:
    LaTeXSupport.activate(editor)   # collega i segnali
    labels = LaTeXSupport.extract_labels(text)
    keys   = LaTeXSupport.extract_bibtex_keys(text, path)
"""

from __future__ import annotations

import re
import threading
import bisect
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QTimer

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget


# ─── Regex compilate a livello modulo (usa frequente: ~100-10k chiamate/sessione)

_RE_BEGIN_END       = re.compile(r'\\(begin|end)\{([^}]+)\}')
_RE_INCLUDE_INPUT   = re.compile(
    r'\\(?:input|include|subfile)\*?\s*\{([^}]+)\}'
    r'|\\(?:import|subimport|includefrom|subinputfrom)\*?\s*'
    r'\{([^}]*)\}\s*\{([^}]+)\}'
)
_MATH_ENV_NAMES = frozenset({
    "equation", "align", "gather", "multline", "math", "displaymath",
    "split", "cases", "alignat", "flalign", "subequations",
})

# ─── Cache file per progetti multi-file ────────────────────────────────────────
#
# Il checker LaTeX live (editor/latex_checker.py, ogni 1.5s) e il rebuild
# dell'autocompletamento (editor/autocomplete.py, ogni 2-3s) chiamano più
# volte per ciclo le funzioni *_multifile qui sotto, ciascuna delle quali
# percorre l'intero albero \input/\include e rilegge ogni file coinvolto.
# Senza cache, un progetto con N file inclusi genera ~8-10×N letture da
# disco ad ogni pausa di battitura — molto pesante su cartelle sincronizzate
# (Dropbox, unità di rete). Questa cache, basata su mtime e condivisa da
# tutte le funzioni sotto, elimina la rilettura dei file non modificati.
# I due worker girano su QThread separati: il lock evita corse sulla cache.

_MAX_CACHE_SIZE = 128

_file_cache_lock = threading.Lock()
_file_cache: dict[Path, tuple[float, str]] = {}
_cache_keys: list[Path] = []


def _is_escaped(text: str, pos: int) -> bool:
    """Return whether the character at ``pos`` has an odd slash prefix."""
    slashes = 0
    pos -= 1
    while pos >= 0 and text[pos] == "\\":
        slashes += 1
        pos -= 1
    return bool(slashes % 2)


def strip_latex_comments(text: str) -> str:
    """Remove TeX comments while respecting odd/even backslash escaping."""
    out: list[str] = []
    in_comment = False
    for ch in text:
        if ch == "\n":
            in_comment = False
            out.append(ch)
        elif in_comment:
            continue
        elif ch == "%":
            slash_count = 0
            idx = len(out) - 1
            while idx >= 0 and out[idx] == "\\":
                slash_count += 1
                idx -= 1
            if slash_count % 2 == 0:
                in_comment = True
            else:
                out.append(ch)
        else:
            out.append(ch)
    return "".join(out)


_LABEL_COMMANDS = frozenset({"label"})
_REFERENCE_COMMANDS = frozenset({
    "ref", "eqref", "pageref", "cref", "Cref", "autoref", "nameref",
    "vref", "vpageref", "cpageref", "labelcref", "namecref", "nameCref",
    "namecrefs", "lcnamecref", "crefrange", "fullref", "hyperref",
})
_MULTI_REFERENCE_COMMANDS = frozenset({"crefrange"})
_OPAQUE_GROUP_COMMANDS = frozenset({
    "url", "path", "nolinkurl", "texttt", "textsf", "textrm", "textit",
    "textbf", "textrup", "textnormal", "emph", "mbox", "fbox",
})
_VERBATIM_COMMANDS = frozenset({"verb", "Verb", "lstinline", "mintinline"})
_OPAQUE_ENVIRONMENTS = frozenset({
    "verbatim", "verbatim*", "Verbatim", "BVerbatim", "lstlisting",
    "minted", "comment",
})


def _read_latex_group(text: str, start: int) -> Optional[tuple[int, int]]:
    """Return the content span of a balanced group starting at ``start``."""
    if start >= len(text) or text[start] != "{":
        return None
    depth = 1
    i = start + 1
    while i < len(text):
        if text[i] == "%" and not _is_escaped(text, i):
            newline = text.find("\n", i)
            i = len(text) if newline < 0 else newline + 1
            continue
        if text[i] == "\\" and i + 1 < len(text):
            i += 2
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return start + 1, i
        i += 1
    return None


def _skip_latex_space(text: str, start: int) -> int:
    """Skip whitespace and comments between a command and its argument."""
    i = start
    while i < len(text):
        if text[i].isspace():
            i += 1
        elif text[i] == "%" and not _is_escaped(text, i):
            newline = text.find("\n", i)
            i = len(text) if newline < 0 else newline + 1
        else:
            break
    return i


def _skip_latex_bracket_group(text: str, start: int) -> int:
    """Skip one simple optional ``[...]`` argument, returning its end."""
    if start >= len(text) or text[start] != "[":
        return start
    depth = 1
    i = start + 1
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            i += 2
            continue
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def _skip_latex_opaque_command(text: str, name: str, start: int) -> int:
    """Skip verbatim/string-like command content."""
    i = _skip_latex_space(text, start)
    if i < len(text) and text[i] == "*":
        i = _skip_latex_space(text, i + 1)
    if name == "mintinline":
        i = _skip_latex_bracket_group(text, i)
        i = _skip_latex_space(text, i)
        language = _read_latex_group(text, i)
        if language is not None:
            i = language[1] + 1
        i = _skip_latex_space(text, i)
    elif name == "lstinline":
        i = _skip_latex_bracket_group(text, i)
        i = _skip_latex_space(text, i)
    if i >= len(text):
        return i
    delimiter = text[i]
    end = text.find(delimiter, i + 1)
    return len(text) if end < 0 else end + 1


def _skip_latex_opaque_environment(text: str, start: int, name: str) -> int:
    """Skip a verbatim-like environment, including its matching end token."""
    i = start
    while i < len(text):
        if text[i] == "%" and not _is_escaped(text, i):
            newline = text.find("\n", i)
            i = len(text) if newline < 0 else newline + 1
            continue
        if text[i] != "\\":
            i += 1
            continue
        command_start = i
        i += 1
        if not text.startswith("end", i) or (
                i + 3 < len(text) and
                (text[i + 3].isalpha() or text[i + 3] == "@")):
            continue
        group = _read_latex_group(text, _skip_latex_space(text, i + 3))
        if group is not None and text[group[0]:group[1]].strip() == name:
            return group[1] + 1
        i = max(i, command_start + 1)
    return len(text)


def _label_reference_tokens(text: str) -> list[dict]:
    """Scan exact label/reference commands outside comments and string content."""
    tokens: list[dict] = []
    i = 0
    while i < len(text):
        if text[i] == "%" and not _is_escaped(text, i):
            newline = text.find("\n", i)
            i = len(text) if newline < 0 else newline + 1
            continue
        if text[i] != "\\":
            i += 1
            continue

        command_start = i
        i += 1
        if i >= len(text):
            break
        if not text[i].isalpha() and text[i] != "@":
            i += 1
            continue
        name_start = i
        while i < len(text) and (text[i].isalpha() or text[i] == "@"):
            i += 1
        name = text[name_start:i]

        if name in _VERBATIM_COMMANDS:
            i = _skip_latex_opaque_command(text, name, i)
            continue
        if name in _OPAQUE_GROUP_COMMANDS:
            group_start = _skip_latex_space(text, i)
            group = _read_latex_group(text, group_start)
            i = len(text) if group is None else group[1] + 1
            continue
        if name == "begin":
            group = _read_latex_group(text, _skip_latex_space(text, i))
            if group is not None:
                environment = text[group[0]:group[1]].strip()
                if environment in _OPAQUE_ENVIRONMENTS:
                    i = _skip_latex_opaque_environment(text, group[1] + 1, environment)
                    continue
        if name not in _LABEL_COMMANDS and name not in _REFERENCE_COMMANDS:
            continue

        argument_start = _skip_latex_space(text, i + (text[i:i + 1] == "*"))
        groups: list[tuple[int, int]] = []
        group_limit = 1 if name not in _MULTI_REFERENCE_COMMANDS else 2
        while len(groups) < group_limit:
            group = _read_latex_group(text, argument_start)
            if group is None:
                break
            groups.append(group)
            argument_start = _skip_latex_space(text, group[1] + 1)

        if name == "hyperref":
            # hyperref uses an optional label argument, unlike the commands above.
            bracket_start = _skip_latex_space(text, i)
            if bracket_start < len(text) and text[bracket_start] == "[":
                bracket_end = _skip_latex_bracket_group(text, bracket_start)
                content_start = bracket_start + 1
                content_end = max(content_start, bracket_end - 1)
                if bracket_end > content_start:
                    tokens.extend(_split_reference_argument(
                        text, content_start, content_end, command_start,
                    ))
                i = bracket_end
            continue

        if name == "label" and groups:
            content_start, content_end = groups[0]
            key = text[content_start:content_end].strip()
            if key:
                key_start = content_start + (len(text[content_start:content_end]) -
                                             len(text[content_start:content_end].lstrip()))
                tokens.append({
                    "kind": "label", "key": key,
                    "start": key_start, "end": key_start + len(key),
                    "command_start": command_start,
                })
        elif name in _REFERENCE_COMMANDS:
            for content_start, content_end in groups:
                tokens.extend(_split_reference_argument(
                    text, content_start, content_end, command_start,
                ))
        i = max(i, argument_start)
    return tokens


def _split_reference_argument(text: str, start: int, end: int,
                               command_start: int) -> list[dict]:
    tokens: list[dict] = []
    part_start = start
    for pos in range(start, end + 1):
        if pos != end and text[pos] != ",":
            continue
        raw_start, raw_end = part_start, pos
        while raw_start < raw_end and text[raw_start].isspace():
            raw_start += 1
        while raw_end > raw_start and text[raw_end - 1].isspace():
            raw_end -= 1
        if raw_start < raw_end:
            tokens.append({
                "kind": "reference", "key": text[raw_start:raw_end],
                "start": raw_start, "end": raw_end,
                "command_start": command_start,
            })
        part_start = pos + 1
    return tokens


def _cached_read_text(path: Path) -> str:
    """Legge `path` riusando il contenuto in cache se l'mtime non è cambiato."""
    mtime = path.stat().st_mtime
    with _file_cache_lock:
        cached = _file_cache.get(path)
        if cached is not None and cached[0] == mtime:
            if path in _cache_keys:
                _cache_keys.remove(path)
            _cache_keys.append(path)
            return cached[1]
        while len(_cache_keys) >= _MAX_CACHE_SIZE:
            old = _cache_keys.pop(0)
            _file_cache.pop(old, None)
    text = path.read_text(encoding="utf-8", errors="replace")
    with _file_cache_lock:
        _file_cache[path] = (mtime, text)
        if path in _cache_keys:
            _cache_keys.remove(path)
        _cache_keys.append(path)
    return text


_stripped_cache_lock = threading.Lock()
_stripped_cache: dict[Path, tuple[float, str]] = {}
_stripped_cache_keys: list[Path] = []


def _cached_read_text_stripped(path: Path) -> str:
    """Come `_cached_read_text`, ma restituisce il testo già privato dei
    commenti (`strip_latex_comments`), cachato per path+mtime.

    `strip_latex_comments` è uno scan carattere per carattere in puro
    Python: economico su un singolo file, ma le funzioni `*_multifile`
    (ambienti custom, pacchetti, `collect_project_files`) lo richiamano
    ciascuna sullo stesso file invariato a ogni trigger di completamento
    LaTeX — su documenti grandi la somma di queste ripetizioni diventava
    uno stallo percettibile a ogni `\\beg`/`\\end` digitato.
    """
    mtime = path.stat().st_mtime
    with _stripped_cache_lock:
        cached = _stripped_cache.get(path)
        if cached is not None and cached[0] == mtime:
            if path in _stripped_cache_keys:
                _stripped_cache_keys.remove(path)
            _stripped_cache_keys.append(path)
            return cached[1]
        while len(_stripped_cache_keys) >= _MAX_CACHE_SIZE:
            old = _stripped_cache_keys.pop(0)
            _stripped_cache.pop(old, None)
    stripped = strip_latex_comments(_cached_read_text(path))
    with _stripped_cache_lock:
        _stripped_cache[path] = (mtime, stripped)
        if path in _stripped_cache_keys:
            _stripped_cache_keys.remove(path)
        _stripped_cache_keys.append(path)
    return stripped


def _invalidate_cached_text(path: Path) -> None:
    with _stripped_cache_lock:
        _stripped_cache.pop(path, None)
        if path in _stripped_cache_keys:
            _stripped_cache_keys.remove(path)
    with _file_cache_lock:
        _file_cache.pop(path, None)
        if path in _cache_keys:
            _cache_keys.remove(path)


# ─── Ambienti LaTeX standard ─────────────────────────────────────────────────

STANDARD_ENVIRONMENTS: list[str] = sorted([
    # documento
    "document", "abstract",
    # testo
    "center", "flushleft", "flushright", "quote", "quotation", "verse",
    "verbatim", "verbatim*", "alltt",
    # liste
    "itemize", "enumerate", "description", "list",
    # matematica
    "equation", "equation*", "align", "align*", "alignat", "alignat*",
    "gather", "gather*", "multline", "multline*", "split", "cases",
    "flalign", "flalign*", "subequations",
    "math", "displaymath", "array",
    # figure e tabelle
    "figure", "figure*", "table", "table*",
    "tabular", "tabular*", "tabularx", "tabulary", "longtable",
    "supertabular", "xltabular", "sidewaystable", "sidewaysfigure",
    # box e layout
    "minipage", "lrbox", "picture",
    "multicols", "multicols*",
    "wrapfigure", "wraptable",
    # teoremi
    "theorem", "lemma", "corollary", "proposition", "definition",
    "remark", "example", "proof", "conjecture", "claim",
    # listing e codice
    "lstlisting", "minted", "verbatimtab", "BVerbatim",
    # colori e box
    "tcolorbox", "tcblisting", "mdframed", "framed", "shaded",
    # tikz
    "tikzpicture", "pgfpicture", "scope", "axis",
    # algoritmi
    "algorithm", "algorithm2e", "algorithmic", "algorithmicx",
    "lstlisting",
    # beamer
    "frame", "block", "alertblock", "exampleblock", "columns", "column",
    "overlayarea", "overprint",
    # altri
    "appendix", "filecontents", "filecontents*",
    "thebibliography", "theindex",
])

# ─── Ambienti aggiuntivi per pacchetto ───────────────────────────────────────
# Ambienti NON già presenti in STANDARD_ENVIRONMENTS, attivati dal \usepackage

PACKAGE_ENVIRONMENTS: dict[str, list[str]] = {
    "tasks":        ["tasks"],
    "cases":        ["numcases", "subnumcases"],
    "empheq":       ["empheq"],
    "tabularray":   ["tblr", "longtblr", "talltblr"],
    "tabu":         ["tabu", "longtabu"],
    "xltabular":    ["xltabular"],
    "pgfplots":     ["semilogxaxis", "semilogyaxis", "loglogaxis", "groupplot",
                     "polaraxis"],
    "tikz-cd":      ["tikzcd"],
    "subcaption":   ["subfigure", "subtable"],
    "verbatim":     ["comment"],
    "comment":      ["comment"],
    "beamer":       ["onlyenv", "visibleenv", "actionenv", "beamercolorbox",
                     "beamertab", "semiverbatim"],
    "csquotes":     ["displayquote", "displayblockquote"],
    "forest":       ["forest"],
    "circuitikz":   ["circuitikz"],
    "standalone":   ["standalone"],
    "rotating":     ["turn", "rotate"],
    "spreadtab":    ["spreadtab"],
    "quoting":      ["quoting"],
    "listings":   ["lstlisting"],
    "minted":       ["listing"],
    "tcolorbox":    ["tcbitemize", "tcbeamer", "tcbverbatimwrite",
                     "tcblisting", "tcolorbox"],
    "framed":       ["oframed", "leftbar", "snugshade"],
    "mdframed":     ["mdframed"],
    "enumitem":     ["enumerate*", "itemize*", "description*"],
    "multicol":     ["multicols", "multicols*"],
}

# ─── Comandi LaTeX per pacchetto (usati per completamento contestuale) ────────

PACKAGE_COMMANDS: dict[str, list[str]] = {
    "amsmath": [
        "\\text{}", "\\intertext{}", "\\shortintertext{}",
        "\\underbrace{}", "\\overbrace{}", "\\underbracket{}", "\\overbracket{}",
        "\\xleftarrow{}", "\\xrightarrow{}",
        "\\overset{}{}", "\\underset{}{}",
        "\\dfrac{}{}", "\\tfrac{}{}", "\\cfrac{}{}",
        "\\binom{}{}", "\\dbinom{}{}", "\\tbinom{}{}",
        "\\operatorname{}", "\\operatorname*{}",
        "\\boldsymbol{}", "\\pmb{}",
        "\\DeclareMathOperator{}{}", "\\DeclareMathOperator*{}{}",
        "\\numberwithin{}{}",
        "\\tag{}", "\\tag*{}", "\\notag",
        "\\shoveleft{}", "\\shoveright{}",
    ],
    "amssymb": [
        "\\mathbb{}", "\\mathfrak{}", "\\mathscr{}",
        "\\varnothing", "\\emptyset", "\\complement",
        "\\therefore", "\\because", "\\checkmark",
        "\\vartriangle", "\\blacktriangle", "\\triangledown",
        "\\square", "\\blacksquare", "\\lozenge", "\\blacklozenge",
        "\\circledast", "\\circledcirc", "\\circleddash",
        "\\boxplus", "\\boxminus", "\\boxtimes", "\\boxdot",
        "\\lessdot", "\\gtrdot", "\\lll", "\\ggg",
        "\\lessgtr", "\\gtrless", "\\lesseqgtr", "\\gtreqless",
        "\\Subset", "\\Supset", "\\Cap", "\\Cup",
    ],
    "graphicx": [
        "\\includegraphics[]{}", "\\includegraphics[width=\\textwidth]{}",
        "\\includegraphics[height=\\textheight]{}",
        "\\includegraphics[scale=]{}",
        "\\graphicspath{{}}", "\\DeclareGraphicsExtensions{}",
        "\\rotatebox{}{}", "\\scalebox{}{}",
        "\\reflectbox{}", "\\resizebox{}{}{}",
    ],
    "hyperref": [
        "\\href{}{}", "\\url{}", "\\nolinkurl{}",
        "\\hyperref[]{}", "\\autoref{}", "\\nameref{}",
        "\\hyperlink{}{}", "\\hypertarget{}{}",
        "\\texorpdfstring{}{}",
        "\\pdfbookmark[]{}{}", "\\phantomsection",
        "\\hypersetup{}",
    ],
    "xcolor": [
        "\\textcolor{}{}", "\\color{}", "\\colorbox{}{}",
        "\\fcolorbox{}{}{}", "\\pagecolor{}",
        "\\definecolor{}{}{}", "\\colorlet{}{}",
        "\\rowcolor{}", "\\cellcolor{}",
    ],
    "tikz": [
        "\\tikz{}", "\\tikzset{}",
        "\\draw", "\\fill", "\\filldraw", "\\shade", "\\shadedraw",
        "\\path", "\\node", "\\coordinate", "\\pic",
        "\\foreach", "\\clip", "\\useasboundingbox",
        "\\usetikzlibrary{}",
        "\\tikzstyle{}",
    ],
    "pgfplots": [
        "\\begin{axis}", "\\end{axis}",
        "\\addplot", "\\addplot+", "\\addplot3",
        "\\legend{}", "\\addlegendentry{}",
        "\\pgfplotsset{}", "\\usepgfplotslibrary{}",
    ],
    "listings": [
        "\\lstset{}", "\\lstinputlisting{}",
        "\\lstinline{}",
        "\\lstnewenvironment{}{}{}",
        "\\lstdefinestyle{}{}",
        "\\lstdefinelanguage{}{}",
    ],
    "minted": [
        "\\mint{}{}", "\\mintinline{}{}",
        "\\inputminted{}{}",
        "\\setminted{}", "\\usemintedstyle{}",
        "\\newminted{}{}", "\\newmintinline{}{}",
    ],
    "biblatex": [
        "\\addbibresource{}", "\\printbibliography",
        "\\printbibliography[heading=bibintoc]",
        "\\cite{}", "\\parencite{}", "\\footcite{}", "\\textcite{}",
        "\\autocite{}", "\\citeauthor{}", "\\citeyear{}",
        "\\citetitle{}", "\\fullcite{}", "\\footfullcite{}",
        "\\DeclareFieldFormat{}{}", "\\DeclareBibliographyCategory{}",
    ],
    "natbib": [
        "\\citep{}", "\\citet{}", "\\citealt{}", "\\citealp{}",
        "\\citeauthor{}", "\\citeyear{}", "\\citefullauthor{}",
        "\\bibpunct{}{}{}{}{}{}",
        "\\bibliographystyle{}", "\\bibliography{}",
    ],
    "geometry": [
        "\\geometry{}",
        "\\newgeometry{}", "\\restoregeometry",
        "\\savegeometry{}", "\\loadgeometry{}",
    ],
    "fancyhdr": [
        "\\pagestyle{fancy}", "\\fancyhf{}",
        "\\fancyhead[]{}", "\\fancyfoot[]{}",
        "\\fancyhead[L]{}", "\\fancyhead[C]{}", "\\fancyhead[R]{}",
        "\\fancyfoot[L]{}", "\\fancyfoot[C]{}", "\\fancyfoot[R]{}",
        "\\renewcommand{\\headrulewidth}{}",
        "\\renewcommand{\\footrulewidth}{}",
        "\\thispagestyle{}", "\\markboth{}{}",
    ],
    "titlesec": [
        "\\titleformat{}{}{}{}{}", "\\titleformat*{}{}",
        "\\titlespacing{}{}{}{}", "\\titlespacing*{}{}{}{}",
        "\\titlelabel{}", "\\titleclass{}{}",
        "\\chaptertitlename",
    ],
    "enumitem": [
        "\\setlist{}", "\\setlist[itemize]{}",
        "\\setlist[enumerate]{}", "\\setlist[description]{}",
        "\\newlist{}{}{}", "\\setlist[,]{}",
        "\\begin{itemize}[label=]",
        "\\begin{enumerate}[label=]",
    ],
    "caption": [
        "\\captionsetup{}", "\\captionsetup[]{}",
        "\\captionof{}{}", "\\caption*{}",
        "\\DeclareCaptionStyle{}{}",
        "\\DeclareCaptionLabelFormat{}{}",
    ],
    "subcaption": [
        "\\subcaptionbox{}{}", "\\subcaption{}",
        "\\begin{subfigure}", "\\end{subfigure}",
        "\\begin{subtable}", "\\end{subtable}",
    ],
    "booktabs": [
        "\\toprule", "\\midrule", "\\bottomrule",
        "\\cmidrule{}", "\\cmidrule(lr){}",
        "\\addlinespace", "\\addlinespace[]",
        "\\specialrule{}{}{}",
    ],
    "multirow": [
        "\\multirow{}{}{}", "\\multirow[]{}{}{}", "\\multicolumn{}{}{}",
        "\\multirowcell{}{}", "\\thead{}",
    ],
    "siunitx": [
        "\\SI{}{}", "\\si{}", "\\num{}", "\\ang{}",
        "\\SIrange{}{}{}", "\\SIlist{}{}",
        "\\numrange{}{}", "\\numlist{}",
        "\\sisetup{}",
        "\\DeclareSIUnit{}{}",
        "\\tablenum{}",
    ],
    "tcolorbox": [
        "\\tcbset{}", "\\tcbuselibrary{}",
        "\\newtcolorbox{}{}{}", "\\newtcblisting{}{}{}",
        "\\tcboxfit{}", "\\tcbox{}",
        "\\begin{tcolorbox}", "\\end{tcolorbox}",
        "\\begin{tcblisting}", "\\end{tcblisting}",
    ],
    "algorithm2e": [
        "\\KwIn{}", "\\KwOut{}", "\\KwData{}", "\\KwResult{}",
        "\\KwTo", "\\KwRet{}", "\\Return{}",
        "\\If{}{}", "\\ElseIf{}{}", "\\Else{}",
        "\\For{}{}", "\\ForEach{}{}", "\\While{}{}",
        "\\Repeat{}{}", "\\Until{}",
        "\\SetAlgoLined", "\\DontPrintSemicolon",
        "\\SetKwComment{}{}{}",
    ],
    "inputenc": ["\\inputencoding{}"],
    "fontenc": ["\\fontencoding{}", "\\selectfont"],
    "babel": [
        "\\selectlanguage{}", "\\foreignlanguage{}{}",
        "\\otherlanguage{}", "\\babelfont{}{}",
        "\\begin{otherlanguage}", "\\end{otherlanguage}",
    ],
    "microtype": [
        "\\microtypesetup{}", "\\textls{}",
        "\\lsstyle", "\\MakeUppercase{}",
    ],
    "csquotes": [
        "\\enquote{}", "\\enquote*{}", "\\textquote{}",
        "\\blockquote{}", "\\foreignquote{}{}",
        "\\MakeOuterQuote{}", "\\ExecuteQuoteOptions{}",
    ],
    "cleveref": [
        "\\cref{}", "\\Cref{}", "\\crefrange{}{}",
        "\\cpageref{}", "\\namecref{}", "\\labelcref{}",
        "\\crefformat{}{}",
    ],
    "imakeidx": [
        "\\makeindex", "\\makeindex[]",
        "\\index{}", "\\index[]{}", "\\indexprologue{}",
        "\\printindex", "\\printindex[]",
        "\\indexsetup{}", "\\indexspace",
    ],
    "glossaries": [
        "\\makeglossaries", "\\printglossaries",
        "\\printglossary", "\\printacronyms",
        "\\newglossaryentry{}{}", "\\newacronym{}{}{}",
        "\\gls{}", "\\Gls{}", "\\GLS{}", "\\glspl{}",
        "\\glsentrytext{}", "\\acrlong{}", "\\acrshort{}",
    ],
    "todonotes": [
        "\\todo{}", "\\todo[inline]{}", "\\todo[color=]{}",
        "\\missingfigure{}", "\\listoftodos",
        "\\todosetup{}",
    ],
    "parskip": [],
    "setspace": [
        "\\singlespacing", "\\onehalfspacing", "\\doublespacing",
        "\\setstretch{}", "\\begin{singlespace}", "\\begin{doublespace}",
    ],
    # ── Presentazioni ─────────────────────────────────────────────────────────
    "beamer": [
        "\\begin{frame}", "\\end{frame}", "\\frametitle{}", "\\framesubtitle{}",
        "\\begin{block}{}", "\\end{block}",
        "\\begin{alertblock}{}", "\\end{alertblock}",
        "\\begin{exampleblock}{}", "\\end{exampleblock}",
        "\\begin{columns}", "\\end{columns}",
        "\\begin{column}{}", "\\end{column}",
        "\\begin{overlayarea}{}{}", "\\end{overlayarea}",
        "\\usetheme{}", "\\usecolortheme{}", "\\usefonttheme{}",
        "\\useinnertheme{}", "\\useoutertheme{}",
        "\\only<>{}", "\\onslide<>{}", "\\visible<>{}",
        "\\uncover<>{}", "\\alt<>{}{}",
        "\\pause", "\\setbeamertemplate{}", "\\setbeamercovered{transparent}",
        "\\alert{}", "\\structure{}",
        "\\titlepage", "\\tableofcontents",
        "\\AtBeginSection[]{}",
        "\\institute{}", "\\titlegraphic{}", "\\logo{}",
    ],
    # ── Fisica e matematica avanzata ──────────────────────────────────────────
    "physics": [
        "\\abs{}", "\\norm{}", "\\eval{}", "\\order{}",
        "\\qty{}", "\\pqty{}", "\\bqty{}", "\\vqty{}",
        "\\dd{}", "\\dv{}{}", "\\pdv{}{}", "\\fdv{}{}",
        "\\grad", "\\div", "\\curl", "\\laplacian",
        "\\ket{}", "\\bra{}", "\\braket{}{}", "\\ketbra{}{}",
        "\\expval{}", "\\mel{}{}{}",
        "\\comm{}{}", "\\acomm{}{}",
        "\\tr", "\\Tr", "\\rank", "\\erf",
        "\\vb{}", "\\vb*{}", "\\va{}", "\\vu{}", "\\vdot", "\\cross",
        "\\mqty{}", "\\pmqty{}", "\\bmqty{}", "\\vmqty{}",
        "\\imat{}", "\\xmat{}{}{}",
    ],
    "empheq": [
        "\\begin{empheq}[left=\\empheqlbrace]{align}", "\\end{empheq}",
        "\\begin{empheq}[box=\\fbox]{equation}", "\\end{empheq}",
    ],
    "cancel": [
        "\\cancel{}", "\\bcancel{}", "\\xcancel{}", "\\cancelto{}{}",
    ],
    "mathtools": [
        "\\coloneqq", "\\Coloneqq", "\\eqqcolon",
        "\\prescript{}{}{}", "\\mathclap{}", "\\mathllap{}", "\\mathrlap{}",
        "\\smashoperator{}", "\\adjustlimits{}{}",
        "\\shortintertext{}",
        "\\begin{pmatrix*}", "\\begin{bmatrix*}", "\\begin{vmatrix*}",
        "\\begin{matrix*}", "\\begin{Bmatrix*}",
    ],
    "braket": [
        "\\bra{}", "\\ket{}", "\\braket{}", "\\Braket{}",
        "\\set{}", "\\Set{}", "\\mean{}",
    ],
    "commath": [
        "\\od{}{}", "\\pd{}{}", "\\dif", "\\Dif",
        "\\abs{}", "\\norm{}", "\\cbr{}", "\\sbr{}", "\\eval{}",
    ],
    "tensor": [
        "\\tensor{}{}", "\\indices{}", "\\tensor[]{}{}",
    ],
    # ── Font e codifica ───────────────────────────────────────────────────────
    "fontspec": [
        "\\setmainfont{}", "\\setsansfont{}", "\\setmonofont{}",
        "\\setmathfont{}", "\\newfontfamily{}{}", "\\newfontface{}{}",
        "\\addfontfeatures{}", "\\fontspec{}",
    ],
    "unicode-math": [
        "\\setmathfont{}", "\\setmathfont[]{}",
        "\\symbb{}", "\\symbf{}", "\\symit{}", "\\symrm{}",
        "\\symsf{}", "\\symscr{}", "\\symfrak{}", "\\symup{}",
    ],
    "polyglossia": [
        "\\setmainlanguage{}", "\\setotherlanguage{}",
        "\\setmainlanguage[]{}", "\\setotherlanguage[]{}",
        "\\textlang{}{}", "\\begin{otherlanguage*}", "\\end{otherlanguage*}",
    ],
    "lmodern": [], "fontawesome5": [
        "\\faIcon{}", "\\faGithub", "\\faLinkedin",
        "\\faEnvelope", "\\faPhone", "\\faHome", "\\faFile",
    ],
    "pifont": [
        "\\ding{}", "\\dingline{}", "\\dingfill{}",
        "\\begin{dinglist}{}", "\\end{dinglist}",
    ],
    # ── Layout e inserimento ──────────────────────────────────────────────────
    "appendix": [
        "\\begin{appendices}", "\\end{appendices}",
        "\\appendix", "\\appendixpage", "\\addappheadtotoc",
    ],
    "pdfpages": [
        "\\includepdf{}", "\\includepdf[pages=-]{}",
        "\\includepdf[pages=1]{}", "\\includepdf[nup=2x1]{}",
        "\\includepdf[fitpaper=true]{}",
    ],
    "afterpage": [
        "\\afterpage{}", "\\afterpage{\\clearpage}",
    ],
    "placeins": ["\\FloatBarrier"],
    "float": [
        "\\floatstyle{}", "\\floatname{}{}",
        "\\newfloat{}{}{}", "\\listof{}{}",
    ],
    "rotating": [
        "\\begin{sidewaysfigure}", "\\end{sidewaysfigure}",
        "\\begin{sidewaystable}", "\\end{sidewaystable}",
        "\\begin{turn}", "\\end{turn}", "\\rotatebox{}{}",
    ],
    "wrapfig": [
        "\\begin{wrapfigure}{}{}", "\\end{wrapfigure}",
        "\\begin{wraptable}{}{}", "\\end{wraptable}",
    ],
    "varioref": [
        "\\vref{}", "\\vpageref{}", "\\vrefrange{}{}", "\\fullref{}", "\\Vref{}",
    ],
    "subfig": [
        "\\subfloat[][]{}", "\\subfloat[]{}", "\\subref{}",
    ],
    "standalone": [
        "\\documentclass{standalone}", "\\standaloneconfig{}",
    ],
    "svg": [
        "\\includesvg{}", "\\includesvg[width=\\textwidth]{}",
    ],
    # ── Tabelle avanzate ──────────────────────────────────────────────────────
    "multicol": [
        "\\begin{multicols}{}", "\\end{multicols}",
        "\\begin{multicols*}{}", "\\end{multicols*}",
        "\\columnbreak", "\\newcolumn",
        "\\setlength{\\columnsep}{}", "\\setlength{\\columnseprule}{}",
        "\\setlength{\\multicolsep}{}", "\\premulticols{}",
        "\\columnfraction{}",
    ],
    "tabularx": [
        "\\begin{tabularx}{\\textwidth}{X}", "\\end{tabularx}",
        "\\begin{tabularx}{\\textwidth}{lX}", "\\begin{tabularx}{\\textwidth}{lXr}",
        "\\newcolumntype{Y}{>{\\centering\\arraybackslash}X}",
        "\\tabularxcolumn{}",
    ],
    "tabulary": [
        "\\begin{tabulary}{\\textwidth}{L}", "\\end{tabulary}",
        "\\begin{tabulary}{\\textwidth}{LCR}", "\\begin{tabulary}{\\textwidth}{LLCR}",
        "\\newcolumntype{L}{>{\\raggedright\\arraybackslash}X}",
        "\\newcolumntype{C}{>{\\centering\\arraybackslash}X}",
        "\\newcolumntype{R}{>{\\raggedleft\\arraybackslash}X}",
    ],
    "longtable": [
        "\\begin{longtable}{}", "\\end{longtable}",
        "\\endhead", "\\endfirsthead", "\\endfoot", "\\endlastfoot",
        "\\caption{}", "\\caption[]{}",
        "\\kill", "\\pagebreak[0]", "\\nopagebreak",
        "\\setlength{\\LTleft}{}", "\\setlength{\\LTright}{}",
        "\\setlength{\\LTpre}{}", "\\setlength{\\LTpost}{}",
        "\\setlength{\\LTcapwidth}{}",
    ],
    "xltabular": [
        "\\begin{xltabular}{\\textwidth}{X}", "\\end{xltabular}",
        "\\begin{xltabular}{\\textwidth}{lX}", "\\begin{xltabular}{\\textwidth}{lXr}",
        "\\endhead", "\\endfirsthead", "\\endfoot", "\\endlastfoot",
        "\\caption{}", "\\caption[]{}",
    ],
    "tabularray": [
        "\\begin{tblr}", "\\end{tblr}",
        "\\begin{longtblr}", "\\end{longtblr}",
        "\\SetTblrStyle{}{}", "\\hline[]", "\\cline{}",
    ],
    "array": [
        "\\newcolumntype{}{}", "\\extrarowheight",
        "\\arraybackslash", "\\centering\\arraybackslash",
    ],
    "makecell": [
        "\\makecell{}", "\\makecell[]{}", "\\thead{}",
        "\\makegapedcells",
    ],
    # ── Nomenclatura, glossari, indici ────────────────────────────────────────
    "acro": [
        "\\ac{}", "\\acl{}", "\\acs{}", "\\acf{}",
        "\\Ac{}", "\\acsp{}", "\\DeclareAcronym{}{}", "\\printacronyms",
    ],
    "nomencl": [
        "\\nomenclature{}{}", "\\printnomenclature", "\\makenomenclature",
    ],
    # ── Codice esteso ─────────────────────────────────────────────────────────
    "verbatim": [
        "\\begin{verbatim}", "\\end{verbatim}",
        "\\begin{verbatim*}", "\\end{verbatim*}",
        "\\begin{comment}", "\\end{comment}",
        "\\verbatiminput{}",
    ],
    "fancyvrb": [
        "\\begin{Verbatim}", "\\end{Verbatim}",
        "\\begin{Verbatim}[numbers=left]", "\\end{Verbatim}",
        "\\VerbatimInput{}", "\\VerbatimInput[]{}",
        "\\fvset{}",
    ],
    # ── Utilità ───────────────────────────────────────────────────────────────
    "xparse": [
        "\\NewDocumentCommand{}{}{}", "\\RenewDocumentCommand{}{}{}",
        "\\NewDocumentEnvironment{}{}{}{}", "\\RenewDocumentEnvironment{}{}{}{}",
        "\\NewExpandableDocumentCommand{}{}{}",
    ],
    "etoolbox": [
        "\\AtBeginDocument{}", "\\AtEndDocument{}",
        "\\apptocmd{}{}{}{}", "\\pretocmd{}{}{}{}",
        "\\patchcmd{}{}{}{}{}", "\\providetoggle{}",
        "\\toggletrue{}", "\\togglefalse{}", "\\iftoggle{}{}{}",
    ],
    "calc": [
        "\\setlength{}{\\textwidth - 2cm}",
        "\\setcounter{}{\\value{} + 1}",
        "\\widthof{}", "\\heightof{}", "\\depthof{}",
    ],
    "ifthen": [
        "\\ifthenelse{}{}{}", "\\whiledo{}{}",
        "\\equal{}{}", "\\NOT{}", "\\AND{}{}", "\\OR{}{}",
        "\\isodd{}", "\\lengthtest{}",
    ],
    "lastpage": ["\\pageref{LastPage}"],
    "ulem": [
        "\\uline{}", "\\uuline{}", "\\uwave{}",
        "\\sout{}", "\\xout{}", "\\dashuline{}", "\\dotuline{}", "\\normalem",
    ],
    "soul": [
        "\\so{}", "\\caps{}", "\\hl{}", "\\st{}", "\\ul{}", "\\sethlcolor{}",
    ],
    "changes": [
        "\\added{}", "\\deleted{}", "\\replaced{}{}",
        "\\added[id=]{}", "\\listofchanges",
    ],
    # ── Chimica ───────────────────────────────────────────────────────────────
    "mhchem": ["\\ce{}", "\\cee{}", "\\cf{}"],
    "chemformula": ["\\ch{}", "\\chname{}"],
    # ── Circuiti ──────────────────────────────────────────────────────────────
    "circuitikz": [
        "\\begin{circuitikz}", "\\end{circuitikz}",
        "to[R=]", "to[C=]", "to[L=]", "to[battery=]",
        "to[short]", "to[open]",
    ],
    # ── Referenze ─────────────────────────────────────────────────────────────
    "doi": ["\\doi{}", "\\doitext{}"],
    "url": ["\\url{}", "\\urlstyle{}", "\\urldef{}{}{}"],
    "lineno": [
        "\\linenumbers", "\\nolinenumbers",
        "\\modulolinenumbers{}", "\\linenumberfont",
    ],
    # ── Simboli extra ─────────────────────────────────────────────────────────
    "stmaryrd": [
        "\\llbracket", "\\rrbracket", "\\bigsqcap", "\\lightning",
    ],
    "wasysym": [
        "\\square", "\\hexagon", "\\circle", "\\male", "\\female", "\\phone",
    ],
    "bbm": ["\\mathbbm{1}", "\\mathbbm{N}", "\\mathbbm{R}"],
    "dsfont": ["\\mathds{1}", "\\mathds{R}"],
    "mathrsfs": ["\\mathscr{A}", "\\mathscr{L}"],
    "eufrak": ["\\mathfrak{A}", "\\mathfrak{g}"],
    "pgfplotstable": [
        "\\pgfplotstableread{}{}", "\\pgfplotstabletypeset{}",
        "\\pgfplotstablecreatecol[]{}{}",
    ],
    "mdframed": [
        "\\begin{mdframed}", "\\end{mdframed}",
        "\\newmdenv{}{}", "\\newmdtheoremenv{}{}", "\\mdfsetup{}",
    ],
    "framed": [
        "\\begin{framed}", "\\end{framed}",
        "\\begin{shaded}", "\\end{shaded}",
        "\\begin{leftbar}", "\\end{leftbar}",
    ],
}

# ─── Opzioni per comandi con argomento opzionale [...] ───────────────────────

COMMAND_OPTIONS: dict[str, list[str]] = {
    "documentclass": [
        "10pt", "11pt", "12pt", "14pt",
        "a4paper", "letterpaper", "a5paper", "b5paper",
        "twoside", "oneside", "twocolumn", "onecolumn",
        "landscape", "portrait", "draft", "final",
        "titlepage", "notitlepage",
        "openright", "openany", "fleqn", "leqno",
    ],
    "includegraphics": [
        "width=\\textwidth", "width=0.8\\textwidth", "width=0.5\\textwidth",
        "width=\\linewidth", "width=\\columnwidth",
        "height=\\textheight", "height=5cm", "height=3cm",
        "scale=0.5", "scale=0.7", "scale=0.8", "scale=1.0",
        "angle=90", "angle=180", "angle=270",
        "clip=true", "trim=0 0 0 0", "keepaspectratio",
        "page=1", "draft=true",
    ],
    "figure":     ["h", "t", "b", "p", "H", "htbp", "!htbp", "!h", "!t"],
    "table":      ["h", "t", "b", "p", "H", "htbp", "!htbp"],
    "wrapfigure": ["l", "r", "L", "R", "i", "o"],
    "minipage":   ["t", "b", "c", "T", "B"],
    "tabular":    ["t", "b", "c"],
    "tabularx":   ["t", "b", "c"],
    "longtable":  ["t", "b", "c", "h", "H"],
    "lstlisting": [
        "language=Python", "language=C", "language=C++", "language=Java",
        "language=bash", "language=SQL", "language=HTML", "language=TeX",
        "language=Matlab", "language=R",
        "label=lst:", "caption=", "captionpos=b", "captionpos=t",
        "numbers=left", "numbers=right", "numbers=none",
        "numberstyle=\\tiny", "stepnumber=1", "numbersep=5pt",
        "basicstyle=\\small\\ttfamily", "basicstyle=\\footnotesize\\ttfamily",
        "keywordstyle=\\color{blue}\\bfseries",
        "commentstyle=\\color{gray}\\itshape",
        "stringstyle=\\color{red}",
        "frame=single", "frame=lines", "frame=none", "frame=tb",
        "breaklines=true", "breakatwhitespace=true",
        "tabsize=4", "showtabs=false", "showspaces=false",
    ],
    "minted": [
        "linenos=true", "linenos=false", "breaklines=true",
        "bgcolor=lightgray", "fontsize=\\small", "fontsize=\\footnotesize",
        "frame=lines", "framesep=2mm", "firstnumber=1",
    ],
    "geometry": [
        "margin=2cm", "margin=2.5cm", "margin=1in",
        "left=3cm", "right=2cm", "top=2.5cm", "bottom=2.5cm",
        "inner=3cm", "outer=2cm",
        "textwidth=16cm", "textheight=24cm",
        "paper=a4paper", "paper=letterpaper", "landscape",
        "headheight=14pt", "headsep=10pt", "footskip=25pt",
        "includeheadfoot", "includefoot", "includehead", "bindingoffset=1cm",
    ],
    "hyperref": [
        "colorlinks=true", "colorlinks=false",
        "linkcolor=blue", "citecolor=green", "urlcolor=cyan",
        "linkcolor=black", "citecolor=black", "urlcolor=black",
        "hidelinks", "breaklinks=true",
        "pdftitle=", "pdfauthor=", "pdfsubject=", "pdfkeywords=",
        "unicode=true", "bookmarks=true", "bookmarksnumbered=true",
        "pdfstartview=FitH", "linktoc=all",
    ],
    "babel": [
        "italian", "english", "german", "ngerman", "french",
        "spanish", "portuguese", "dutch", "russian",
        "american", "british", "greek", "latin",
    ],
    "inputenc": ["utf8", "latin1", "latin9", "ansinew"],
    "fontenc":  ["T1", "OT1", "T2A", "LGR"],
    "xcolor":   ["dvipsnames", "svgnames", "x11names", "table", "xcdraw"],
    "enumitem": [
        "label=\\arabic*.", "label=\\alph*)", "label=\\roman*.",
        "label=\\Alph*.", "label=\\Roman*.",
        "label=•", "label=--", "label=◦",
        "leftmargin=*", "leftmargin=1cm", "leftmargin=0pt",
        "itemsep=0pt", "itemsep=5pt", "topsep=0pt", "parsep=0pt",
        "resume", "resume*", "nosep", "wide", "noitemsep",
    ],
    "caption": [
        "font=small", "font=footnotesize", "labelfont=bf", "labelfont=it",
        "format=plain", "format=hang", "justification=centering",
        "justification=raggedright", "width=0.8\\textwidth",
        "labelsep=colon", "labelsep=period", "skip=5pt",
    ],
    "tcolorbox": [
        "colback=white", "colback=yellow!10", "colback=blue!10",
        "colframe=black", "colframe=blue", "colframe=red",
        "title=", "fonttitle=\\bfseries", "arc=5pt", "arc=0pt",
        "boxrule=0.5pt", "drop shadow", "enhanced", "breakable",
    ],
    "columns":   ["t", "T", "c", "b"],
    "column":    [],
    "cmidrule":  ["lr", "l", "r"],
    "multirow":  ["*", "="],
    "makecell":  ["t", "b", "c", "l", "r"],
    "algorithm2e": ["H", "h", "t", "b", "htbp"],
    "usetheme":  [
        "Berlin", "Warsaw", "Madrid", "AnnArbor", "Antibes",
        "Bergen", "Berkeley", "Boadilla", "CambridgeUS",
        "Copenhagen", "Darmstadt", "default", "Dresden", "Frankfurt",
        "Goettingen", "Ilmenau", "Luebeck", "Malmoe", "Marburg",
        "Montpellier", "PaloAlto", "Pittsburgh", "Rochester",
        "Singapore", "Szeged",
    ],
    "usecolortheme": [
        "default", "albatross", "beaver", "beetle", "crane",
        "dolphin", "dove", "fly", "lily", "monarca",
        "orchid", "rose", "seagull", "seahorse", "spruce",
        "whale", "wolverine",
    ],
}

# ─── Opzioni valide per \\begin{env}[...] ─────────────────────────────────────

ENVIRONMENT_OPTIONS: dict[str, list[str]] = {
    "figure":         ["h", "t", "b", "p", "H", "htbp", "!htbp"],
    "figure*":        ["h", "t", "b", "p", "H", "htbp", "!htbp"],
    "table":          ["h", "t", "b", "p", "H", "htbp", "!htbp"],
    "table*":         ["h", "t", "b", "p", "H", "htbp", "!htbp"],
    "sidewaysfigure": ["h", "t", "b", "p", "htbp"],
    "sidewaystable":  ["h", "t", "b", "p", "htbp"],
    "minipage":       ["t", "b", "c", "T", "B"],
    "tabular":        ["t", "b", "c"],
    "tabular*":       ["t", "b", "c"],
    "tabularx":       ["t", "b", "c"],
    "tabulary":       ["t", "b", "c"],
    "longtable":      ["t", "b", "c", "l", "r"],
    "wrapfigure":     ["l", "r", "L", "R", "i", "o"],
    "wraptable":      ["l", "r", "L", "R"],
    "lstlisting":     [
        "language=Python", "language=C", "language=C++",
        "label=lst:", "caption=", "numbers=left", "frame=single",
        "breaklines=true",
    ],
    "minted":         ["linenos", "breaklines", "fontsize=\\small"],
    "tcolorbox":      ["colback=white", "colframe=black", "title=", "breakable"],
    "frame":          [],
    "columns":        ["t", "T", "c", "b"],
    "column":         [],
    "block":          [],
    "alertblock":     [],
    "exampleblock":   [],
    "algorithm":      ["H", "h", "t", "b"],
    "algorithm2e":    ["H", "h", "t", "b"],
    "itemize":        ["label=", "leftmargin=", "itemsep=0pt", "nosep"],
    "enumerate":      ["label=\\arabic*.", "label=\\alph*)", "resume"],
    "description":    ["leftmargin=", "style=nextline"],
    "multicols":      ["2", "3", "4", "5"],
    "multicols*":     ["2", "3", "4", "5"],
    "subfigure":      ["t", "b", "c"],
    "subtable":       ["t", "b", "c"],
    "axis": [
        "xlabel=", "ylabel=", "title=",
        "xmin=", "xmax=", "ymin=", "ymax=",
        "legend pos=north east", "legend pos=south east",
        "grid=major", "grid=minor", "grid=both",
        "width=\\textwidth", "height=8cm",
        "xmode=log", "ymode=log",
    ],
}

# ─── Argomenti obbligatori dopo \\begin{envname} ─────────────────────────────
#
# Ogni voce mappa un nome ambiente → lista di argomenti obbligatori (template).
# Quando l'utente chiude \\begin{multicols}, il sistema inserisce automaticamente
# {2} con il cursore selezionato, pronto per la modifica.
# Tab naviga all'argomento successivo se ce ne sono più di uno.

ENV_MANDATORY_ARGS: dict[str, list[str]] = {
    # Più colonne
    "multicols":  ["{2}"],
    "multicols*": ["{2}"],
    # Tabelle — specifica colonne obbligatoria
    "tabular":    ["{|l|l|l|}"],
    "tabular*":   ["{\\textwidth}", "{|l|l|l|}"],
    "tabularx":   ["{\\textwidth}", "{|X|X|}"],
    "tabulary":   ["{\\textwidth}", "{|L|L|}"],
    "array":      ["{|c|c|c|}"],
    "longtable":  ["{|l|l|l|}"],
    "xltabular":  ["{\\textwidth}", "{|X|X|}"],
    # Box e figure — posizione/dimensione obbligatorie
    "minipage":   ["{0.9\\textwidth}"],
    "wrapfigure": ["{r}", "{0.5\\textwidth}"],
    "wraptable":  ["{r}", "{0.5\\textwidth}"],
    # Codice — linguaggio obbligatorio
    "minted":     ["{python}"],
    # Matematica — numero coppie di allineamento
    "alignat":    ["{2}"],
    "alignat*":   ["{2}"],
    # Beamer
    "column":     ["{0.5\\textwidth}"],
    # Box avanzati
    "adjustbox":  ["{max width=\\textwidth}"],
}

# ─── Opzioni per \\usepackage[...]{pacchetto} ─────────────────────────────────

PACKAGE_OPTIONS: dict[str, list[str]] = {
    "geometry":    ["margin=2cm", "a4paper", "left=3cm", "right=2cm",
                    "top=2.5cm", "bottom=2.5cm", "landscape"],
    "hyperref":    ["colorlinks=true", "hidelinks", "pdftitle=",
                    "bookmarks=true", "unicode=true"],
    "babel":       ["italian", "english", "german", "french", "spanish"],
    "inputenc":    ["utf8", "latin1"],
    "fontenc":     ["T1", "OT1"],
    "xcolor":      ["dvipsnames", "svgnames", "x11names", "table"],
    "enumitem":    ["shortlabels", "inline"],
    "caption":     ["font=small", "labelfont=bf"],
    "microtype":   ["protrusion=true", "expansion=true", "final"],
    "cleveref":    ["capitalise", "nameinlink", "noabbrev"],
    "biblatex":    [
        "backend=biber", "backend=bibtex",
        "style=numeric", "style=authoryear", "style=alphabetic",
        "style=ieee", "sorting=none", "sorting=nyt",
        "maxbibnames=10", "maxcitenames=2",
        "doi=false", "url=false", "isbn=false",
    ],
    "natbib":      ["round", "square", "colon", "comma",
                    "authoryear", "numbers", "super", "sort"],
    "minted":      ["cache=false"],
    "tcolorbox":   ["most", "skins", "theorems", "breakable"],
    "pgfplots":    ["compat=newest", "compat=1.18"],
    "siunitx":     ["locale=IT", "locale=DE", "locale=UK"],
    "algorithm2e": ["ruled", "vlined", "linesnumbered", "boxed",
                    "italiano", "english"],
    "fontspec":    ["no-math"],
    "unicode-math":["math-style=ISO", "bold-style=ISO"],
    "appendix":    ["toc", "titletoc", "title"],
    "glossaries":  ["acronym", "toc", "nonumberlist", "nopostdot"],
    "todonotes":   ["disable", "colorinlistoftodos"],
    "ulem":        ["normalem"],
    "csquotes":    ["style=italian", "style=german", "style=english"],
    "listings":    ["final"],
}

# ─── LaTeXSupport: parser e connessioni ──────────────────────────────────────

class LaTeXSupport:
    """
    Classe statica. Fornisce parsing e supporto LaTeX avanzato.
    """

    # ── Attivazione su EditorWidget ──────────────────────────────────────────

    @staticmethod
    def activate(editor: "EditorWidget") -> None:
        """
        Collega i segnali dell'editor per il supporto LaTeX avanzato.
        Va chiamato quando il lexer LaTeX viene impostato.
        """
        LaTeXSupport.deactivate(editor)

        def char_handler(char):
            LaTeXSupport._on_char_added(editor, char)

        editor._latex_char_added_handler = char_handler
        editor.SCN_CHARADDED.connect(char_handler)

        # SCN_AUTOCCOMPLETED: aggiunge {} dopo comandi LaTeX completati da API
        def handler(sel, pos, ch, method):
            LaTeXSupport._on_autocomplete_done(editor, sel, pos, ch, method)

        editor._latex_ac_done_handler = handler
        editor.SCN_AUTOCCOMPLETED.connect(handler)
        editor._latex_support_active = True

    @staticmethod
    def deactivate(editor: "EditorWidget") -> None:
        """Scollega tutti gli handler LaTeX installati su `editor`."""
        for signal_name, attr_name in (
                ("SCN_CHARADDED", "_latex_char_added_handler"),
                ("SCN_AUTOCCOMPLETED", "_latex_ac_done_handler")):
            handler = getattr(editor, attr_name, None)
            if handler is not None:
                try:
                    getattr(editor, signal_name).disconnect(handler)
                except (RuntimeError, TypeError):
                    pass
                setattr(editor, attr_name, None)
        editor._latex_support_active = False

    @staticmethod
    def _on_autocomplete_done(editor: "EditorWidget", selection, position: int,
                               ch: int, method: int) -> None:
        """
        Dopo la selezione di un'API LaTeX con {}, posiziona il cursore dentro
        le graffe e attiva il popup contestuale.

        Gestisce due casi a seconda della versione QScintilla:
        - A) {} già inserite (cursore dopo }) → sposta cursore dentro
        - B) {} non inserite (cursore dopo \\cmd) → le inserisce poi sposta
        """
        # SCN_AUTOCCOMPLETED espone la selezione come 'const char*' (QScintilla
        # C++): PyQt la consegna come bytes, non str — va decodificata prima
        # di poterla confrontare con stringhe Python.
        sel = selection or b""
        if isinstance(sel, (bytes, bytearray)):
            sel = sel.decode("utf-8", "replace")
        if "{}" not in sel:
            return

        line, col = editor.getCursorPosition()
        line_text = editor.text(line)
        text_before = line_text[:col]
        ac = getattr(editor, "_autocomplete", None)

        if text_before.endswith("{}"):
            # Caso A: {} già presenti — sposta cursore dentro
            editor.setCursorPosition(line, col - 1)
            if ac:
                ac.handle_latex_special("{")

        elif re.search(r'\\[a-zA-Z]+$', text_before):
            # Caso B: solo il comando, senza {} — le aggiungiamo
            if col >= len(line_text) or line_text[col] != "{":
                editor._in_paste = True
                try:
                    editor.insert("{}")
                    editor.setCursorPosition(line, col + 1)
                finally:
                    editor._in_paste = False
                if ac:
                    ac.handle_latex_special("{")

    @staticmethod
    def _on_char_added(editor: "EditorWidget", char_int: int) -> None:
        """Gestisce i caratteri speciali LaTeX."""
        # Ignora durante operazioni di paste/insert programmatico
        if getattr(editor, "_in_paste", False):
            return
        char = chr(char_int)

        if char == "\n":
            LaTeXSupport._handle_newline(editor)
        elif char == "{":
            LaTeXSupport._handle_open_brace(editor)
        elif char == "}":
            LaTeXSupport._handle_close_brace(editor)
        elif char == "[":
            LaTeXSupport._handle_open_bracket(editor)
        elif char == "$":
            LaTeXSupport._handle_dollar(editor)
        elif char == "\\":
            pass  # il completamento parte dall'autocomplete standard
        elif char.isalpha() or char == "*":
            LaTeXSupport._handle_env_prefix(editor)
            LaTeXSupport._handle_env_word(editor)

    @staticmethod
    def _handle_newline(editor: "EditorWidget") -> None:
        """
        Su invio in ambiente LaTeX:
        - dopo \\item con testo: inserisce nuovo \\item sulla riga successiva
        - dopo \\item vuoto: rimuove il \\item e lascia cursore prima di \\end
        - dopo \\begin{env}: inserisce \\end{env} (con \\item se env e' list)
        """
        line, col = editor.getCursorPosition()
        if line < 1:
            return
        prev_line = editor.text(line - 1)
        current_line_text = editor.text(line)

        # ── \item continuation ──────────────────────────────────────────────
        item_m = re.match(r'^(\s*)\\item(.*)', prev_line.rstrip('\n\r'))
        if item_m:
            indent_str = item_m.group(1)
            item_content = item_m.group(2).strip()
            if not item_content:
                # Empty \item → remove the \item line, leave cursor on current line
                editor.beginUndoAction()
                editor.setSelection(line - 1, 0, line, 0)
                editor.removeSelectedText()
                editor.setCursorPosition(line - 1, 0)
                editor.endUndoAction()
            elif not current_line_text.strip():
                # \item with content → insert new \item on current empty line
                new_item = f"{indent_str}\\item "
                editor.beginUndoAction()
                editor.setCursorPosition(line, 0)
                editor.insert(new_item)
                editor.setCursorPosition(line, len(new_item))
                editor.endUndoAction()
            return

        # ── \begin{env} → \end{env} ─────────────────────────────────────────
        m = re.search(r'\\begin\{([^}]+)\}', prev_line)
        if not m:
            return
        env = m.group(1)
        indent = len(prev_line) - len(prev_line.lstrip())
        indent_str = prev_line[:indent]
        inner_indent = indent_str + "    "
        end_cmd = f"{indent_str}\\end{{{env}}}"

        # Se più sotto c'è già un \end{env} che chiude questo ambiente
        # (es. un \end{multicols} preesistente senza il suo \begin), non
        # aggiungiamo un secondo \end: creerebbe una coppia spuria segnalata
        # dal checker di bilanciamento.
        already_closed = LaTeXSupport._has_matching_end_below(editor, line - 1, env)

        if not current_line_text.strip():
            editor.beginUndoAction()
            # L'auto-indent di Scintilla ha già potenzialmente copiato
            # l'indentazione di \begin sulla riga vuota (autoIndent() e'
            # True di default): la sostituiamo per intero invece di provare
            # a "completarla" con la sola differenza, cosi' il risultato è
            # corretto sia con auto-indent Scintilla attivo che disattivo.
            line_end_col = len(current_line_text.rstrip("\n"))
            editor.setSelection(line, 0, line, line_end_col)
            editor.removeSelectedText()
            editor.setCursorPosition(line, 0)
            if already_closed:
                # Lascia solo la riga del body indentata, senza \end.
                editor.insert(inner_indent)
                editor.setCursorPosition(line, len(inner_indent))
            elif env in LaTeXSupport._LIST_ENVIRONMENTS:
                editor.insert(f"{inner_indent}\\item \n{end_cmd}")
                editor.setCursorPosition(line, len(inner_indent) + 6)
            else:
                # Un'unica insert(): QsciScintilla.insert() NON avanza il
                # cursore, quindi due chiamate separate finiscono per
                # inserirsi nello stesso punto in ordine inverso (LIFO)
                # invece di concatenarsi come atteso.
                editor.insert(f"{inner_indent}\n{end_cmd}")
                editor.setCursorPosition(line, len(inner_indent))
            editor.endUndoAction()

    @staticmethod
    def _handle_open_brace(editor: "EditorWidget") -> None:
        """
        Dopo '{': attiva completamento contestuale; se nessun caso speciale,
        auto-chiude } per pattern \\cmd{.
        """
        ac = getattr(editor, "_autocomplete", None)
        handled = ac.handle_latex_special("{") if ac else False
        if not handled and getattr(editor, "_autoclose_enabled", True):
            LaTeXSupport._auto_close_generic_brace(editor)

    # Pattern compilato una volta sola (nessun costo per keystroke)
    _BEGIN_END_PREFIX = re.compile(r'\\(?:begin|end)\{([\w*]*)$')

    @staticmethod
    def _handle_env_prefix(editor: "EditorWidget") -> None:
        """
        Dopo ogni lettera/asterisco: se il cursore è dentro \\begin{prefix} o
        \\end{prefix}, aggiorna il popup degli ambienti filtrandolo per prefix.
        Solo una list-comprehension su cache in-memory — nessun I/O.
        """
        ac = getattr(editor, "_autocomplete", None)
        if not ac or not ac._env_cache:
            return
        line, col = editor.getCursorPosition()
        text_before = editor.text(line)[:col]
        m = LaTeXSupport._BEGIN_END_PREFIX.search(text_before)
        if m:
            ac.refresh_env_popup(m.group(1))

    # Parola dopo \ ancora incompleta (per riconoscere un prefisso di begin/end)
    _CMD_WORD = re.compile(r'\\([a-zA-Z]*)$')

    @staticmethod
    def _handle_env_word(editor: "EditorWidget") -> None:
        """
        Appena la parola dopo \\ e' un prefisso valido di "begin"/"end" di
        almeno 2 lettere (stessa soglia dell'autocompletamento standard, es.
        \\be, \\beg, \\begi...), mostra subito il popup ambienti ordinato per
        uso/nidificazione: non serve arrivare a scrivere la parola intera ne'
        la {. Si richiude da sola senza toccare il testo se la parola diverge
        da begin/end (es. \\begingroup, \\begins).
        """
        ac = getattr(editor, "_autocomplete", None)
        if not ac:
            return
        line, col = editor.getCursorPosition()
        text_before = editor.text(line)[:col]
        m = LaTeXSupport._CMD_WORD.search(text_before)
        word = m.group(1) if m else ""

        is_begin = bool(word) and "begin".startswith(word)
        is_end = bool(word) and "end".startswith(word)

        if (is_begin or is_end) and len(word) >= 2:
            # Ricalcola/riapre solo al primo carattere che rende la parola un
            # prefisso valido: sulle lettere successive (beg→begi→begin) il
            # popup resta quello già mostrato, senza rifare la scansione del
            # documento ad ogni tasto — la scrittura non deve rallentare.
            if not getattr(ac, "_env_popup_needs_brace", False):
                ac.complete_environments_from_word(is_end=is_end)
            elif word in ("begin", "end"):
                # Il popup API nativo, alfabetico, puo' aprirsi dopo quello
                # personalizzato quando il comando e' completato velocemente.
                # Rimettiamo in coda il popup dalla cache gia' ordinata.
                QTimer.singleShot(0, lambda w=word: ac.restore_env_word_popup(w))
        else:
            ac.cancel_env_word_popup()

    @staticmethod
    def _auto_close_generic_brace(editor: "EditorWidget") -> None:
        """Auto-inserisce } dopo \\cmd{ se il cursore e' immediatamente dopo la {."""
        line, col = editor.getCursorPosition()
        line_text = editor.text(line)
        text_before = line_text[:col]
        if not re.search(r'\\[a-zA-Z]+\{$', text_before):
            return
        if line_text[col:col + 1] == '}':
            return
        editor._in_paste = True
        try:
            editor.insert('}')
        finally:
            editor._in_paste = False

    # ─── Inserimento ambiente da popup ───────────────────────────────────────

    _LIST_ENVIRONMENTS: frozenset = frozenset({
        "itemize", "enumerate", "description", "list",
        "thebibliography", "compactitem", "compactenum",
        "itemize*", "enumerate*", "description*", "tasks",
    })

    @staticmethod
    def insert_environment(editor: "EditorWidget", env_name: str) -> None:
        """
        Inserisce l'ambiente completo dopo la selezione dal popup \\begin{.
        - Cancella il prefisso parziale gia' digitato
        - Aggiunge \\end{env} con indentazione corretta
        - Per ambienti lista aggiunge anche il primo \\item
        """
        line, col = editor.getCursorPosition()
        line_text = editor.text(line)

        # Trova il prefisso parziale digitato dopo l'ultimo {
        text_before = line_text[:col]
        brace_pos = text_before.rfind('{')
        partial = text_before[brace_pos + 1:] if brace_pos >= 0 else ""

        # Indentazione della riga corrente
        indent_str = line_text[:len(line_text) - len(line_text.lstrip())]
        inner_indent = indent_str + "    "

        # Cancella prefisso parziale
        if partial:
            editor.setSelection(line, col - len(partial), line, col)
            editor.removeSelectedText()
            line, col = editor.getCursorPosition()

        LaTeXSupport.track_env_usage(env_name)

        # Argomenti obbligatori dell'ambiente (testo statico)
        extra_args = ENV_MANDATORY_ARGS.get(env_name, [])
        mandatory_str = "".join(extra_args)

        # Se più sotto c'è già un \end{env_name} che chiude questo ambiente
        # (es. si è riscritta solo la riga \begin{...} lasciando l'\end
        # preesistente), non ne aggiungiamo un secondo: creerebbe una
        # coppia begin/end spuria segnalata come errore.
        already_closed = LaTeXSupport._has_matching_end_below(editor, line, env_name)

        if already_closed:
            if env_name in LaTeXSupport._LIST_ENVIRONMENTS:
                insert_text = f"{env_name}}}{mandatory_str}\n{inner_indent}\\item "
                cursor_line, cursor_col = line + 1, len(inner_indent) + 6
            else:
                insert_text = f"{env_name}}}{mandatory_str}"
                cursor_line, cursor_col = line, col + len(insert_text)
            editor._in_paste = True
            try:
                editor.beginUndoAction()
                editor.insert(insert_text)
                editor.endUndoAction()
            finally:
                editor._in_paste = False
            editor.setCursorPosition(cursor_line, cursor_col)
            return

        if env_name in LaTeXSupport._LIST_ENVIRONMENTS:
            insert_text = (
                f"{env_name}}}{mandatory_str}\n"
                f"{inner_indent}\\item \n"
                f"{indent_str}\\end{{{env_name}}}"
            )
            cursor_col = len(inner_indent) + 6   # dopo \item + spazio
        else:
            insert_text = (
                f"{env_name}}}{mandatory_str}\n"
                f"{inner_indent}\n"
                f"{indent_str}\\end{{{env_name}}}"
            )
            cursor_col = len(inner_indent)

        editor._in_paste = True
        try:
            editor.beginUndoAction()
            editor.insert(insert_text)
            editor.endUndoAction()
        finally:
            editor._in_paste = False

        editor.setCursorPosition(line + 1, cursor_col)

    @staticmethod
    def _has_matching_end_below(editor: "EditorWidget", line: int, env_name: str,
                                 max_lines: int = 300) -> bool:
        """
        Cerca nelle righe successive un \\end{env_name} che chiuda esattamente
        l'ambiente che si sta per aprire (tenendo conto di ambienti annidati
        nel mezzo). Se lo trova, insert_environment evita di aggiungere un
        secondo \\end duplicato.
        """
        stack: list[str] = []
        last_line = min(editor.lines(), line + 1 + max_lines)
        for row in range(line + 1, last_line):
            raw_line = editor.text(row)
            code = strip_latex_comments(raw_line)
            for m in _RE_BEGIN_END.finditer(code):
                kind, env = m.group(1), m.group(2)
                if kind == "begin":
                    stack.append(env)
                elif stack:
                    stack.pop()
                else:
                    return env == env_name
        return False

    @staticmethod
    def _handle_close_brace(editor: "EditorWidget") -> None:
        """
        Dopo '}': se chiude \\begin{envname}, sincronizza il \\end{envname}
        corrispondente e inserisce gli argomenti obbligatori dell'ambiente
        (es. multicols → {2}). Usa i tab-stop per navigare tra argomenti.
        """
        line, col = editor.getCursorPosition()
        line_text = editor.text(line)[:col]

        m = re.search(r'\\begin\{([^}]+)\}$', line_text)
        if not m:
            return

        env = m.group(1)
        LaTeXSupport.track_env_usage(env)

        # Sincronizza \end{env} corrispondente se diverso
        LaTeXSupport._sync_end_environment(editor, env, line)

        extra_args = ENV_MANDATORY_ARGS.get(env)
        if not extra_args:
            return

        # Costruisce corpo snippet con tab-stop per ogni argomento
        # es. ['{2}'] → '{${1:2}}$0'
        # es. ['{\\textwidth}', '{|l|l|l|}'] → '{${1:\\textwidth}}{${2:|l|l|l|}}$0'
        body_parts = []
        for i, arg in enumerate(extra_args, 1):
            inner = arg[1:-1]  # rimuove { }
            body_parts.append('{' + '${' + str(i) + ':' + inner + '}}')
        body_parts.append('$0')
        body = ''.join(body_parts)

        try:
            from editor.snippets import _process_tabstops
        except ImportError:
            return

        expanded, stops = _process_tabstops(body)
        insert_pos = editor.positionFromLineIndex(line, col)

        # Sopprime SCN_CHARADDED durante l'insert per evitare loop
        editor._in_paste = True
        try:
            editor.beginUndoAction()
            editor.insert(expanded)
            editor.endUndoAction()
        finally:
            editor._in_paste = False

        if stops:
            editor._tabstops = [(n, insert_pos + off, dlen)
                                for n, off, dlen in stops]
            editor._tabstop_index = 0
            editor._jump_to_next_tabstop()

    # ─── Sincronizzazione \end ambiente ──────────────────────────────────────

    @staticmethod
    def _sync_end_environment(editor: "EditorWidget", env: str, begin_line: int) -> None:
        """Trova il \\end{...} corrispondente al \\begin{env} sulla riga
        begin_line e, se il nome dell'ambiente è diverso, lo aggiorna."""
        depth = 0
        total = editor.lines()
        end_line = -1
        end_col_start = -1
        end_col_end = -1
        old_env = ""

        for r in range(begin_line, total):
            # strip_latex_comments rimuove solo la coda della riga dopo un
            # '%' non escaped: un \begin/\end che appare prima di un
            # eventuale commento sulla stessa riga mantiene lo stesso
            # offset, quindi bm.start()/bm.end() restano validi anche sul
            # testo originale (vedi anche _has_matching_end_below, che usa
            # lo stesso approccio per lo stesso motivo).
            line_text = strip_latex_comments(editor.text(r))
            # Conta \begin e \end su questa riga
            for bm in re.finditer(r'\\(begin|end)\{([^}]+)\}', line_text):
                cmd, name = bm.group(1), bm.group(2)
                if cmd == "begin":
                    depth += 1
                else:  # end
                    depth -= 1
                    if depth == 0:
                        end_line = r
                        # Colonna inizio del nome ambiente dentro \end{...}
                        end_col_start = bm.start() + len(r'\end{')
                        end_col_end   = end_col_start + len(name)
                        old_env       = name
                        break
            if end_line != -1:
                break

        if end_line == -1 or old_env == env:
            return

        # Sostituisci solo il nome dell'ambiente dentro \end{...}
        editor.beginUndoAction()
        editor.setSelection(end_line, end_col_start,
                            end_line, end_col_end)
        editor.replaceSelectedText(env)
        editor.endUndoAction()

    @staticmethod
    def _handle_open_bracket(editor: "EditorWidget") -> None:
        """Dopo '[': suggerisce opzioni contestuali per il comando/ambiente."""
        ac = getattr(editor, "_autocomplete", None)
        if ac:
            ac.handle_latex_option("[")

    @staticmethod
    def _handle_dollar(editor: "EditorWidget") -> None:
        """
        Dopo '$': auto-inserisce il '$' di chiusura se non già presente.
        """
        if not getattr(editor, "_autoclose_enabled", True):
            return
        line, col = editor.getCursorPosition()
        line_text = editor.text(line)
        dollar_pos = col - 1
        if dollar_pos < 0 or _is_escaped(line_text, dollar_pos):
            return
        if line_text[col:col + 1] == "$":
            return

        before = line_text[:dollar_pos]
        dollar_count = sum(
            1 for idx, char in enumerate(before)
            if char == "$" and not _is_escaped(before, idx)
        )
        if dollar_count % 2 == 0:
            editor.beginUndoAction()
            editor.insert("$")
            editor.setCursorPosition(line, col)
            editor.endUndoAction()

    # ── Estrazione struttura documento ───────────────────────────────────────

    # ── Mappe per rilevamento tipo label ─────────────────────────────────────
    _LABEL_PREFIX_MAP: dict[str, str] = {
        "fig": "figura",    "figure": "figura",
        "tab": "tabella",   "tbl": "tabella",   "table": "tabella",
        "eq":  "equazione", "eqn": "equazione",
        "sec": "sezione",   "sect": "sezione",  "section": "sezione",
        "sub": "sottosezione", "subsec": "sottosezione",
        "ch":  "capitolo",  "chap": "capitolo",
        "alg": "algoritmo", "algo": "algoritmo",
        "lst": "codice",    "listing": "codice", "code": "codice",
        "thm": "teorema",   "theorem": "teorema",
        "lem": "lemma",
        "prop": "proposizione",
        "cor": "corollario",
        "def": "definizione",
        "app": "appendice",
    }

    _ENV_TYPE_MAP: dict[str, str] = {
        "figure": "figura",     "figure*": "figura",    "subfigure": "figura",
        "table":  "tabella",    "table*": "tabella",
        "equation": "equazione","equation*": "equazione",
        "align":    "equazione","align*": "equazione",
        "gather":   "equazione","gather*": "equazione",
        "eqnarray": "equazione","eqnarray*": "equazione",
        "multline": "equazione","multline*": "equazione",
        "flalign":  "equazione","flalign*": "equazione",
        "algorithm": "algoritmo", "algorithm2e": "algoritmo",
        "lstlisting": "codice", "verbatim": "codice", "minted": "codice",
        "theorem": "teorema",   "thm": "teorema",
        "lemma":   "lemma",     "lem": "lemma",
        "proposition": "proposizione",
        "corollary": "corollario",
        "definition": "definizione", "defn": "definizione",
        "proof": "dimostrazione",
        "frame": "slide",
    }

    _SECTION_CMD_MAP: dict[str, str] = {
        "part": "parte",            "chapter": "capitolo",
        "section": "sezione",       "subsection": "sottosezione",
        "subsubsection": "sottosottosezione",
        "paragraph": "paragrafo",   "subparagraph": "sottoparagrafo",
    }

    @staticmethod
    def extract_label_reference_occurrences(text: str) -> list[dict]:
        """Return exact label/ref occurrences outside comments and strings."""
        occurrences: list[dict] = []
        newline_positions = [match.start() for match in re.finditer("\n", text)]
        for token in _label_reference_tokens(text):
            occurrence = dict(token)
            position = occurrence["start"]
            line = bisect.bisect_left(newline_positions, position)
            occurrence["line"] = line
            previous_newline = newline_positions[line - 1] if line else -1
            occurrence["column"] = position if previous_newline < 0 else position - previous_newline - 1
            occurrences.append(occurrence)
        return occurrences

    @staticmethod
    def _label_reference_sources(text: str,
                                 tex_path: Optional[Path]) -> list[tuple[Optional[Path], str]]:
        if tex_path is None:
            return [(None, text)]
        current = Path(tex_path).resolve()
        try:
            from core.latex_project import resolve_project_root
            root = resolve_project_root(current, text)
        except (OSError, RuntimeError, ValueError):
            root = current
        files = LaTeXSupport.collect_project_files(root)
        if not files:
            return [(current, text)]
        sources: list[tuple[Optional[Path], str]] = []
        for path in files:
            try:
                source_text = text if path == current else _cached_read_text(path)
            except (OSError, UnicodeError):
                continue
            sources.append((path, source_text))
        return sources

    @staticmethod
    def analyze_label_references(text: str,
                                 tex_path: Optional[Path] = None) -> dict:
        """Analyze labels and references in one document or its include tree."""
        definitions: list[dict] = []
        references: list[dict] = []
        for source, source_text in LaTeXSupport._label_reference_sources(text, tex_path):
            for occurrence in LaTeXSupport.extract_label_reference_occurrences(source_text):
                item = dict(occurrence)
                if source is not None:
                    item["file"] = source
                if item["kind"] == "label":
                    definitions.append(item)
                else:
                    references.append(item)

        by_key: dict[str, list[dict]] = {}
        for definition in definitions:
            by_key.setdefault(definition["key"], []).append(definition)
        defined_keys = set(by_key)
        referenced_keys = {reference["key"] for reference in references}
        duplicates = [definition for values in by_key.values() for definition in values[1:]]
        unused = [values[0] for key, values in by_key.items()
                  if key not in referenced_keys]
        undefined = [reference for reference in references
                     if reference["key"] not in defined_keys]
        return {
            "definitions": definitions,
            "references": references,
            "duplicates": duplicates,
            "unused": unused,
            "undefined": undefined,
        }

    @staticmethod
    def find_duplicate_labels(text: str,
                              tex_path: Optional[Path] = None) -> list[dict]:
        """Return duplicate label definitions after the first occurrence."""
        return LaTeXSupport.analyze_label_references(text, tex_path)["duplicates"]

    @staticmethod
    def find_unused_labels(text: str,
                           tex_path: Optional[Path] = None) -> list[dict]:
        """Return labels which have no matching reference anywhere in scope."""
        return LaTeXSupport.analyze_label_references(text, tex_path)["unused"]

    @staticmethod
    def find_unused_references(text: str,
                               tex_path: Optional[Path] = None) -> list[dict]:
        """Return unused labels using the checker terminology."""
        return LaTeXSupport.find_unused_labels(text, tex_path)

    @staticmethod
    def rename_label_multifile(tex_path: Path, old_label: str,
                               new_label: str) -> list[Path]:
        """Safely rename a label and exact references in the include tree."""
        old_label = old_label.strip()
        new_label = new_label.strip()
        if not old_label or not new_label:
            raise ValueError("Label names must not be empty")
        if any(char in old_label + new_label for char in "{}\\\n\r"):
            raise ValueError("Label names must not contain braces, backslashes or newlines")
        if old_label == new_label:
            return []

        root = Path(tex_path).resolve()
        files = LaTeXSupport.collect_project_files(root)
        if not files:
            raise ValueError("The LaTeX project root or its include tree was not found")
        contents: dict[Path, str] = {}
        definitions: list[dict] = []
        for path in files:
            source_text = _cached_read_text(path)
            contents[path] = source_text
            definitions.extend(token for token in _label_reference_tokens(source_text)
                               if token["kind"] == "label")
        labels = {definition["key"] for definition in definitions}
        if old_label not in labels:
            raise ValueError(f"Label not found: {old_label}")
        if new_label in labels:
            raise ValueError(f"Label already exists: {new_label}")

        updates: dict[Path, str] = {}
        for path, source_text in contents.items():
            replacements = [(token["start"], token["end"], new_label)
                            for token in _label_reference_tokens(source_text)
                            if token["key"] == old_label]
            if not replacements:
                continue
            updated = source_text
            for start, end, replacement in reversed(replacements):
                updated = updated[:start] + replacement + updated[end:]
            updates[path] = updated

        for path, updated in updates.items():
            path.write_text(updated, encoding="utf-8")
            _invalidate_cached_text(path)
        return list(updates)

    rename_label_across_files = rename_label_multifile

    @staticmethod
    def extract_labels(text: str) -> list[str]:
        """Estrae tutte le \\label{} dal documento."""
        return sorted({token["key"] for token in _label_reference_tokens(text)
                       if token["kind"] == "label"})

    @staticmethod
    def extract_labels_with_context(text: str) -> list[tuple[str, str]]:
        """Restituisce [(chiave_label, tipo_rilevato), ...].

        Il tipo viene rilevato:
        1. Dal prefisso della chiave (fig:, tab:, eq:, sec:, ...)
        2. Scansionando l'ambiente o il comando di sezionamento più vicino
           nei ~600 caratteri precedenti la \\label.
        """
        pm  = LaTeXSupport._LABEL_PREFIX_MAP
        em  = LaTeXSupport._ENV_TYPE_MAP
        sm  = LaTeXSupport._SECTION_CMD_MAP
        sec_re = re.compile(
            r'\\(' + '|'.join(re.escape(k) for k in sm) + r')\*?(?:\[.*?\])?\{',
            re.DOTALL,
        )
        results: list[tuple[str, str]] = []
        seen: set[str] = set()

        for token in _label_reference_tokens(text):
            if token["kind"] != "label":
                continue
            key = token["key"]
            if key in seen:
                continue
            seen.add(key)

            # 1. Prefisso
            prefix = key.split(":")[0].lower() if ":" in key else ""
            if prefix in pm:
                results.append((key, pm[prefix]))
                continue

            # 2. Contesto
            context = strip_latex_comments(
                text[max(0, token["command_start"] - 600): token["command_start"]]
            )
            type_hint = ""

            sec_m = list(sec_re.finditer(context))
            env_m = list(re.finditer(r'\\begin\{([^}]+)\}', context))

            sec_pos = sec_m[-1].start() if sec_m else -1
            env_pos = env_m[-1].start() if env_m else -1

            if sec_pos >= env_pos and sec_m:
                type_hint = sm.get(sec_m[-1].group(1), "sezione")
            elif env_m:
                env_name = env_m[-1].group(1).lower().rstrip("*")
                type_hint = em.get(env_name, "")

            results.append((key, type_hint or "label"))

        return sorted(results, key=lambda x: x[0])

    @staticmethod
    def extract_labels_with_context_multifile(
        tex_path: Optional[Path],
    ) -> list[tuple[str, str]]:
        """Versione multi-file di extract_labels_with_context."""
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for fpath in LaTeXSupport.collect_project_files(tex_path):
            try:
                text = _cached_read_text(fpath)
                for key, hint in LaTeXSupport.extract_labels_with_context(text):
                    if key not in seen:
                        seen.add(key)
                        out.append((key, hint))
            except Exception:
                pass
        return sorted(out, key=lambda x: x[0])

    _REF_KEY_RE = re.compile(
        r'\\(?:ref|pageref|eqref|autoref|cref|Cref|nameref|namecrefs?|lcnamecref|'
        r'vref|vpageref|cpageref|labelcref|crefrange)\{([^}]+)\}'
        r'|\\hyperref\[([^\]]+)\]',
    )

    @staticmethod
    def extract_ref_keys(text: str) -> list[str]:
        """Chiavi usate in comandi \\ref{}, \\pageref{}, \\hyperref[], ecc."""
        return sorted({token["key"] for token in _label_reference_tokens(text)
                       if token["kind"] == "reference"})

    @staticmethod
    def extract_ref_keys_multifile(tex_path: Optional[Path]) -> list[str]:
        """Versione multi-file di extract_ref_keys."""
        keys: set[str] = set()
        for fpath in LaTeXSupport.collect_project_files(tex_path):
            try:
                text = _cached_read_text(fpath)
                keys.update(LaTeXSupport.extract_ref_keys(text))
            except Exception:
                pass
        return sorted(keys)

    @staticmethod
    def extract_hypertargets(text: str) -> list[str]:
        """Estrae i nomi definiti con \\hypertarget{nome}{...}."""
        return sorted(set(re.findall(r'\\hypertarget\{([^}]+)\}', strip_latex_comments(text))))

    @staticmethod
    def extract_hypertargets_multifile(tex_path: Optional[Path]) -> list[str]:
        """Versione multi-file di extract_hypertargets."""
        names: list[str] = []
        for fpath in LaTeXSupport.collect_project_files(tex_path):
            try:
                text = _cached_read_text(fpath)
                names.extend(LaTeXSupport.extract_hypertargets(text))
            except Exception:
                pass
        return sorted(set(names))

    @staticmethod
    def extract_bibtex_keys(text: str,
                             tex_path: Optional[Path] = None) -> list[str]:
        """
        Estrae le chiavi BibTeX dal testo corrente e dai file .bib referenziati.
        """
        code = strip_latex_comments(text)
        entry_re = re.compile(r'@[A-Za-z][\w-]*\s*[({]\s*([^,\s]+)\s*,')
        keys: set[str] = set(entry_re.findall(code))

        # Trova i file .bib referenziati
        bib_files: set[str] = set()
        for m in re.finditer(
            r'\\(?:bibliography|addbibresource)\s*(?:\[[^]]*\])?\s*\{([^}]+)\}',
            code,
        ):
            for f in m.group(1).split(","):
                if f.strip():
                    bib_files.add(f.strip())

        if not bib_files or tex_path is None:
            return sorted(keys)

        base_dir = Path(tex_path).parent
        for bib_name in bib_files:
            bib_path = base_dir / bib_name
            candidates = [bib_path]
            if bib_path.suffix.lower() != ".bib":
                candidates.extend((bib_path.with_suffix(bib_path.suffix + ".bib"),
                                   bib_path.with_suffix(".bib")))
            for candidate in candidates:
                if not candidate.exists():
                    continue
                try:
                    keys.update(entry_re.findall(_cached_read_text(candidate)))
                except Exception:
                    pass
                break

        return sorted(keys)

    @staticmethod
    def extract_custom_commands(text: str) -> list[str]:
        """
        Estrae i comandi definiti con \\newcommand, \\renewcommand,
        \\DeclareMathOperator nel documento.
        """
        cmds: list[str] = []
        text = strip_latex_comments(text)
        patterns = [
            r'\\(?:new|renew|provide)command\*?\{(\\[a-zA-Z]+)\}',
            r'\\DeclareMathOperator\*?\{(\\[a-zA-Z]+)\}',
            r'\\def\s*(\\[a-zA-Z]+)',
            r'\\let\s*(\\[a-zA-Z]+)',
        ]
        for pat in patterns:
            cmds.extend(re.findall(pat, text))
        return sorted(set(cmds))

    @staticmethod
    def _custom_environments_from_stripped(stripped_text: str) -> set[str]:
        return set(re.findall(
            r'\\(?:new|renew)environment\*?\{([^}]+)\}', stripped_text
        ))

    @staticmethod
    def extract_custom_environments(text: str) -> list[str]:
        """Estrae gli ambienti definiti con \\newenvironment."""
        return sorted(LaTeXSupport._custom_environments_from_stripped(
            strip_latex_comments(text)))

    @staticmethod
    def extract_custom_environments_multifile(
            tex_path: Optional[Path]) -> list[str]:
        """Estrae gli ambienti custom da tutti i sorgenti inclusi."""
        names: set[str] = set()
        for fpath in LaTeXSupport.collect_project_files(tex_path):
            try:
                names.update(LaTeXSupport._custom_environments_from_stripped(
                    _cached_read_text_stripped(fpath)))
            except Exception:
                pass
        return sorted(names)

    @staticmethod
    def _used_packages_from_stripped(stripped_text: str) -> set[str]:
        pkgs: set[str] = set()
        for m in re.finditer(
                r'\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}', stripped_text):
            for p in m.group(1).split(","):
                pkgs.add(p.strip())
        return pkgs

    @staticmethod
    def extract_used_packages(text: str) -> list[str]:
        """Estrae i pacchetti caricati con \\usepackage{}."""
        return sorted(LaTeXSupport._used_packages_from_stripped(
            strip_latex_comments(text)))

    @staticmethod
    def extract_used_packages_multifile(
            tex_path: Optional[Path]) -> list[str]:
        """Raccoglie i pacchetti dichiarati nell'intero progetto."""
        packages: set[str] = set()
        for fpath in LaTeXSupport.collect_project_files(tex_path):
            try:
                packages.update(LaTeXSupport._used_packages_from_stripped(
                    _cached_read_text_stripped(fpath)))
            except Exception:
                pass
        return sorted(packages)

    @staticmethod
    def extract_sections(text: str) -> list[tuple[str, str, int]]:
        """
        Estrae la struttura del documento.
        Restituisce lista di (tipo, titolo, riga_0based).
        """
        sections: list[tuple[str, str, int]] = []
        text = strip_latex_comments(text)
        _cmds = [
            "part", "chapter", "section", "subsection",
            "subsubsection", "paragraph", "subparagraph",
        ]
        pattern = re.compile(
            r'\\(' + '|'.join(_cmds) + r')\*?\{([^}]*)\}'
        )
        for i, line in enumerate(text.split("\n")):
            for m in pattern.finditer(line):
                sections.append((m.group(1), m.group(2), i))
        return sections

    @staticmethod
    def get_package_commands(packages: list[str],
                             tex_path: Optional[Path] = None,
                             include_cwl: bool = True) -> list[str]:
        """
        Restituisce i comandi aggiuntivi per i pacchetti caricati.
        Le voci CWL configurate vengono aggiunte solo quando richieste.
        """
        cmds: list[str] = []
        for pkg in packages:
            pkg_cmds = PACKAGE_COMMANDS.get(pkg.lower(), [])
            cmds.extend(pkg_cmds)
        if include_cwl:
            try:
                model = LaTeXSupport.get_cwl_model(tex_path)
                cmds.extend(command.as_api_term()
                             for command in model.commands_for(packages))
            except Exception:
                pass
        return cmds

    @staticmethod
    def get_cwl_model(tex_path: Optional[Path] = None):
        """Load configured CWL data lazily for this document/project."""
        from editor.cwl import load_cwl_for_project
        return load_cwl_for_project(tex_path)

    @staticmethod
    def get_all_environments(text: str,
                             tex_path: Optional[Path] = None) -> list[str]:
        """
        Restituisce tutti gli ambienti disponibili:
        standard + custom dal documento + ambienti dei pacchetti caricati.
        """
        if tex_path:
            custom = LaTeXSupport.extract_custom_environments_multifile(tex_path)
            pkgs = LaTeXSupport.extract_used_packages_multifile(tex_path)
        else:
            custom = LaTeXSupport.extract_custom_environments(text)
            pkgs = LaTeXSupport.extract_used_packages(text)
        pkg_envs: list[str] = []
        for pkg in pkgs:
            pkg_envs.extend(PACKAGE_ENVIRONMENTS.get(pkg.lower(), []))
        try:
            cwl = LaTeXSupport.get_cwl_model(tex_path)
            pkg_envs.extend(environment.name for environment in cwl.environments_for(pkgs))
        except Exception:
            pass
        return sorted(set(STANDARD_ENVIRONMENTS + custom + pkg_envs))

    # ── Frequenza d'uso ambienti (per ordinare il popup \begin{) ─────────────

    @staticmethod
    def _get_env_usage_counts() -> dict:
        import json
        from config.settings import Settings
        raw = Settings.instance().get("latex/env_usage_counts", "{}")
        try:
            return json.loads(raw) if isinstance(raw, str) else dict(raw)
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def track_env_usage(env_name: str) -> None:
        """Incrementa il contatore d'uso di env_name (persistito), usato per
        ordinare il popup \\begin{ con gli ambienti più usati in cima."""
        import json
        from config.settings import Settings
        counts = LaTeXSupport._get_env_usage_counts()
        counts[env_name] = counts.get(env_name, 0) + 1
        Settings.instance().set("latex/env_usage_counts", json.dumps(counts))

    @staticmethod
    def find_open_environments(text: str, line: int, col: int) -> list[str]:
        """
        Scandisce il testo fino a (line, col) e restituisce gli ambienti
        \\begin{...} ancora aperti (senza \\end{...} corrispondente), dal più
        interno (aperto più di recente) al più esterno. Ignora i commenti.
        Usato per suggerire l'ambiente giusto dopo \\end{.
        """
        all_lines = text.split("\n")
        lines = all_lines[:line]
        if line < len(all_lines):
            last = all_lines[line][:col] if col <= len(all_lines[line]) else all_lines[line]
        else:
            last = ""
        lines.append(last)

        stack: list[str] = []
        for raw_line in lines:
            code = strip_latex_comments(raw_line)
            for m in _RE_BEGIN_END.finditer(code):
                kind, env = m.group(1), m.group(2)
                if kind == "begin":
                    stack.append(env)
                else:
                    for i in range(len(stack) - 1, -1, -1):
                        if stack[i] == env:
                            del stack[i]
                            break
        return list(reversed(stack))

    @staticmethod
    def find_open_environments_in_editor(editor: "EditorWidget", line: int, col: int) -> list[str]:
        """Versione lazy per il popup ``\\end``: legge solo le righe utili.

        Evita ``editor.text()`` (copia del documento completo) per un'azione
        che deve soltanto conoscere gli ambienti aperti prima del cursore.
        """
        stack: list[str] = []
        for row in range(min(line + 1, editor.lines())):
            raw_line = editor.text(row)
            code = strip_latex_comments(raw_line[:col] if row == line else raw_line)
            for match in _RE_BEGIN_END.finditer(code):
                kind, env = match.group(1), match.group(2)
                if kind == "begin":
                    stack.append(env)
                else:
                    for index in range(len(stack) - 1, -1, -1):
                        if stack[index] == env:
                            del stack[index]
                            break
        return list(reversed(stack))

    @staticmethod
    def sort_environments_by_usage(envs) -> list[str]:
        """Ordina gli ambienti per frequenza d'uso, poi alfabeticamente."""
        counts = LaTeXSupport._get_env_usage_counts()
        return sorted(set(envs), key=lambda env: (-counts.get(env, 0), env.casefold()))

    # ── Indentazione intelligente ─────────────────────────────────────────────

    @staticmethod
    def compute_indent(line_text: str, prev_indent: str) -> str:
        """
        Calcola l'indentazione per la riga successiva.
        Aumenta dopo \\begin{}, diminuisce dopo \\end{}.
        """
        stripped = line_text.strip()
        if re.search(r'\\begin\{[^}]+\}', stripped):
            return prev_indent + "    "
        if re.search(r'\\end\{[^}]+\}', stripped):
            if len(prev_indent) >= 4:
                return prev_indent[:-4]
        return prev_indent

    # ── Opzioni contestuali ───────────────────────────────────────────────────

    @staticmethod
    def get_command_options(cmd: str) -> list[str]:
        """Opzioni per il comando (da usare dopo '[')."""
        return COMMAND_OPTIONS.get(cmd, [])

    @staticmethod
    def get_environment_options(env: str) -> list[str]:
        """Opzioni per l'ambiente (da usare dopo '\\begin{env}[')."""
        return ENVIRONMENT_OPTIONS.get(env, [])

    @staticmethod
    def get_package_options(pkg: str) -> list[str]:
        """Opzioni per \\usepackage[...]{pkg}."""
        return PACKAGE_OPTIONS.get(pkg.lower(), [])

    # ── Supporto multi-file ───────────────────────────────────────────────────

    @staticmethod
    def collect_project_files(tex_path: Optional[Path],
                               max_depth: int = 5) -> list[Path]:
        """
        Trova ricorsivamente i file sorgente inclusi, anche con i comandi a due
        argomenti \\import, \\subimport, \\includefrom e \\subinputfrom.
        """
        if not tex_path or not tex_path.exists():
            return []
        try:
            from core.latex_project import resolve_project_root
            resolved = Path(tex_path).resolve()
            root = resolve_project_root(resolved)
            if root.is_file():
                tex_path = root
        except (OSError, RuntimeError, ValueError):
            pass
        visited: set[Path] = set()
        result: list[Path] = []

        def _resolve_include(base_dir: Path, ref: str) -> Optional[Path]:
            candidate = base_dir / ref.strip()
            options = [candidate]
            if candidate.suffix == "":
                options.extend(candidate.with_suffix(ext)
                               for ext in (".tex", ".ltx", ".latex"))
            for option in options:
                try:
                    resolved = option.resolve()
                except OSError:
                    continue
                if resolved.is_file():
                    return resolved
            return None

        def _collect(path: Path, depth: int) -> None:
            if depth > max_depth or path in visited:
                return
            visited.add(path)
            result.append(path)
            try:
                stripped_text = _cached_read_text_stripped(path)
            except Exception:
                return
            for m in _RE_INCLUDE_INPUT.finditer(stripped_text):
                if m.group(1) is not None:
                    include_dir, ref = path.parent, m.group(1)
                else:
                    include_dir = path.parent / m.group(2).strip()
                    ref = m.group(3)
                ref_path = _resolve_include(include_dir, ref)
                if ref_path is not None:
                    _collect(ref_path, depth + 1)

        _collect(Path(tex_path).resolve(), 0)
        return result

    @staticmethod
    def extract_labels_multifile(tex_path: Optional[Path]) -> list[str]:
        """Estrae tutte le \\label{} dall'intero progetto multi-file."""
        labels: list[str] = []
        for fpath in LaTeXSupport.collect_project_files(tex_path):
            try:
                text = _cached_read_text(fpath)
                labels.extend(LaTeXSupport.extract_labels(text))
            except Exception:
                pass
        return sorted(set(labels))

    @staticmethod
    def extract_bibtex_keys_multifile(tex_path: Optional[Path]) -> list[str]:
        """Estrae le chiavi BibTeX considerando tutti i file del progetto."""
        keys: list[str] = []
        for fpath in LaTeXSupport.collect_project_files(tex_path):
            try:
                text = _cached_read_text(fpath)
                keys.extend(LaTeXSupport.extract_bibtex_keys(text, fpath))
            except Exception:
                pass
        return sorted(set(keys))

    @staticmethod
    def extract_custom_commands_multifile(tex_path: Optional[Path]) -> list[str]:
        """Raccoglie \\newcommand da tutti i file del progetto."""
        cmds: list[str] = []
        for fpath in LaTeXSupport.collect_project_files(tex_path):
            try:
                text = _cached_read_text(fpath)
                cmds.extend(LaTeXSupport.extract_custom_commands(text))
            except Exception:
                pass
        return sorted(set(cmds))

    @staticmethod
    def build_dynamic_api(text: str,
                           tex_path: Optional[Path] = None,
                           include_cwl: bool = True) -> list[str]:
        """
        Costruisce la lista API dinamica dal documento e dal progetto:
        - Comandi custom (\\newcommand) da tutti i file collegati
        - Ambienti custom (\\newenvironment)
        - Comandi dai pacchetti caricati
        """
        api: list[str] = []

        # Comandi custom dal documento corrente + file inclusi
        if tex_path:
            all_cmds = set(LaTeXSupport.extract_custom_commands_multifile(tex_path))
            all_cmds.update(LaTeXSupport.extract_custom_commands(text))
        else:
            all_cmds = set(LaTeXSupport.extract_custom_commands(text))
        api.extend(sorted(all_cmds))

        # Ambienti custom e pacchetti: includi tutti i sorgenti del progetto,
        # non solo il file attualmente aperto.
        if tex_path:
            custom_envs = set(LaTeXSupport.extract_custom_environments_multifile(tex_path))
            custom_envs.update(LaTeXSupport.extract_custom_environments(text))
            packages = set(LaTeXSupport.extract_used_packages_multifile(tex_path))
            packages.update(LaTeXSupport.extract_used_packages(text))
        else:
            custom_envs = LaTeXSupport.extract_custom_environments(text)
            packages = LaTeXSupport.extract_used_packages(text)

        for env in sorted(custom_envs):
            api.append(f"\\begin{{{env}}}")
            api.append(f"\\end{{{env}}}")

        # Comandi dai pacchetti
        if include_cwl:
            api.extend(LaTeXSupport.get_package_commands(sorted(packages), tex_path))
        else:
            api.extend(LaTeXSupport.get_package_commands(
                sorted(packages), include_cwl=False
            ))

        return api

    # ── Controllo errori in tempo reale ──────────────────────────────────────

    @staticmethod
    def check_environment_balance(text: str) -> list[dict]:
        """
        Controlla il bilanciamento \\begin{}...\\end{}.
        Restituisce lista di {line, env, msg} per ambienti sbilanciati.
        """
        errors: list[dict] = []
        stack: list[tuple[str, int]] = []  # (env_name, lineno)

        for lineno, line in enumerate(text.split("\n")):
            stripped = strip_latex_comments(line)
            for m in _RE_BEGIN_END.finditer(stripped):
                kind, env_name = m.group(1), m.group(2)
                if kind == "begin":
                    stack.append((env_name, lineno))
                    continue
                if not stack:
                    errors.append({
                        "line": lineno, "env": env_name,
                        "msg": f"\\end{{{env_name}}} without matching \\begin",
                    })
                else:
                    top_env, top_line = stack[-1]
                    if top_env == env_name:
                        stack.pop()
                    else:
                        errors.append({
                            "line": lineno, "env": env_name,
                            "msg": (
                                f"\\end{{{env_name}}} closes '{top_env}' "
                                f"opened at line {top_line + 1}"
                            ),
                        })

        for env_name, lineno in stack:
            errors.append({
                "line": lineno, "env": env_name,
                "msg": f"\\begin{{{env_name}}} not closed",
            })

        return errors

    @staticmethod
    def find_environment_match(text: str, line: int, col: int) -> Optional[tuple[int, int]]:
        """
        Se (line, col) cade su un token \\begin{env} o \\end{env}, restituisce
        (line, col) dell'inizio dell'occorrenza corrispondente — l'altro
        capo della coppia — gestendo correttamente l'annidamento di
        ambienti con lo stesso nome (stesso principio di
        check_environment_balance, ma per la navigazione: cerca in avanti
        da un \\begin, all'indietro da un \\end, tenendo un contatore di
        profondità per saltare le coppie annidate).
        Restituisce None se la posizione non è su un \\begin/\\end o se
        manca la corrispondenza (ambiente sbilanciato).

        Invece di tokenizzare tutto il documento, esegue una scansione
        bidirezionale incrementale dal cursore (O(n) solo sulla zona
        effettivamente percorsa, non sull'intero testo).
        """
        lines = text.split("\n")
        nlines = len(lines)

        # ── Determina se il cursore è su un \begin{env} o \end{env} ─────────
        raw = lines[line]
        stripped = strip_latex_comments(raw)
        kind = name = None
        for m in _RE_BEGIN_END.finditer(stripped):
            if m.start() <= col <= m.end():
                kind = m.group(1)
                name = m.group(2)
                break
        if kind is None:
            return None

        if kind == "begin":
            # Scansione in avanti: cerca \end{name} con depth=0
            def _iter_after():
                depth = 0
                for ln in range(line, nlines):
                    row = strip_latex_comments(lines[ln])
                    for m2 in _RE_BEGIN_END.finditer(row):
                        if m2.group(2) != name:
                            continue
                        if m2.group(1) == "begin":
                            depth += 1
                        else:
                            depth -= 1
                            if depth == 0:
                                return (ln, m2.start())
                return None
            return _iter_after()
        else:
            # Scansione all'indietro: cerca \begin{name} con depth=0
            def _iter_before():
                depth = 0
                for ln in range(line, -1, -1):
                    row = strip_latex_comments(lines[ln])
                    for m2 in reversed(list(_RE_BEGIN_END.finditer(row))):
                        if m2.group(2) != name:
                            continue
                        if m2.group(1) == "end":
                            depth += 1
                        else:
                            depth -= 1
                            if depth == 0:
                                return (ln, m2.start())
                return None
            return _iter_before()

    # ── Sincronizzazione nome \begin{X}/\end{X} ──────────────────────────────

    @staticmethod
    def env_token_at(line_text: str, col: int) -> Optional[dict]:
        """
        Se col cade dentro l'argomento {nome} di un \\begin{nome} o
        \\end{nome} sulla riga data, ritorna un dict con kind ("begin"/"end"),
        token_start (colonna del backslash), name_start/name_end (span
        dell'argomento {nome}, escluse le graffe) e name. Altrimenti None.
        Usato per rilevare quando il cursore sta modificando il nome di un
        ambiente, per poi sincronizzare l'altro capo della coppia.
        """
        stripped = strip_latex_comments(line_text)
        for m in _RE_BEGIN_END.finditer(stripped):
            if m.start(2) <= col <= m.end(2):
                return {
                    "kind":       m.group(1),
                    "token_start": m.start(),
                    "name_start":  m.start(2),
                    "name_end":    m.end(2),
                    "name":        m.group(2),
                }
        return None

    @staticmethod
    def find_structural_match(text: str, line: int, token_start: int) -> Optional[tuple[int, int, int]]:
        """
        Come find_environment_match, ma trova l'altro capo della coppia
        \\begin/\\end per struttura (annidamento), non per nome: usata per
        sincronizzare il nome durante una rinomina, quando i due nomi sono
        temporaneamente diversi (es. \\begin{xltabular} non ancora
        rispecchiato in \\end{tabular}) e il filtro per nome di
        find_environment_match non troverebbe corrispondenza.

        token_start è la colonna del backslash del token di partenza sulla
        riga `line`. Ritorna (line, name_start, name_end) dell'argomento
        {nome} dell'altro capo, o None se non trovato/sbilanciato.
        """
        lines = text.split("\n")
        nlines = len(lines)
        raw = lines[line]
        stripped = strip_latex_comments(raw)
        anchor = None
        for m in _RE_BEGIN_END.finditer(stripped):
            if m.start() == token_start:
                anchor = m
                break
        if anchor is None:
            return None
        kind = anchor.group(1)

        if kind == "begin":
            depth = 0
            for ln in range(line, nlines):
                row = strip_latex_comments(lines[ln])
                for m2 in _RE_BEGIN_END.finditer(row):
                    if ln == line and m2.start() < token_start:
                        continue
                    if m2.group(1) == "begin":
                        depth += 1
                    else:
                        depth -= 1
                        if depth == 0:
                            return (ln, m2.start(2), m2.end(2))
            return None
        else:
            depth = 0
            for ln in range(line, -1, -1):
                row = strip_latex_comments(lines[ln])
                matches = list(_RE_BEGIN_END.finditer(row))
                if ln == line:
                    matches = [mm for mm in matches if mm.start() <= token_start]
                for m2 in reversed(matches):
                    if m2.group(1) == "end":
                        depth += 1
                    else:
                        depth -= 1
                        if depth == 0:
                            return (ln, m2.start(2), m2.end(2))
            return None

    # ── Conteggio parole ─────────────────────────────────────────────────────

    @staticmethod
    def count_words(text: str) -> dict:
        """
        Conta parole (corpo documento, escluso preambolo e comandi LaTeX).
        Restituisce {words, chars, chars_nospace, lines, paragraphs}.
        """
        text_nc = strip_latex_comments(text)
        m = re.search(r'\\begin\{document\}', text_nc)
        body = text_nc[m.end():] if m else text_nc
        m2 = re.search(r'\\end\{document\}', body)
        body = body[:m2.start()] if m2 else body

        body_clean = re.sub(
            r'\\[a-zA-Z]+\*?\s*(\[[^\]]*\])?\s*\{([^}]*)\}', r'\2', body
        )
        body_clean = re.sub(r'\\[a-zA-Z]+\*?\s*(\[[^\]]*\])?', ' ', body_clean)
        body_clean = re.sub(r'[{}]', ' ', body_clean)

        return {
            "words":         len(re.findall(r'\b\w+\b', body_clean)),
            "chars":         len(text),
            "chars_nospace": len(re.sub(r'\s', '', text)),
            "lines":         text.count("\n") + 1,
            "paragraphs":    len(re.findall(r'\n\s*\n', body)) + 1,
        }

    # ── Rilevamento math mode ─────────────────────────────────────────────────

    @staticmethod
    def is_in_math_mode(text: str, pos: int) -> bool:
        """
        True se la posizione è all'interno di un delimitatore matematico o
        ambiente matematico noto.
        """
        limit = max(0, min(pos, len(text)))
        i = 0
        dollar_delim: Optional[str] = None
        paired_delim: Optional[str] = None
        env_stack: list[str] = []

        while i < limit:
            if text[i] == "%" and not _is_escaped(text, i):
                newline = text.find("\n", i, limit)
                i = limit if newline < 0 else newline + 1
                continue

            if env_stack:
                match = re.match(r'\\(begin|end)\{([^}]+)\}', text[i:limit])
                if match:
                    name = match.group(2).rstrip("*")
                    if match.group(1) == "begin" and name in _MATH_ENV_NAMES:
                        env_stack.append(name)
                    elif (match.group(1) == "end" and
                          env_stack[-1] == name):
                        env_stack.pop()
                    i += match.end()
                    continue
                i += 1
                continue

            if dollar_delim:
                if text.startswith(dollar_delim, i) and not _is_escaped(text, i):
                    i += len(dollar_delim)
                    dollar_delim = None
                else:
                    i += 1
                continue
            if paired_delim:
                closer = "\\)" if paired_delim == "\\(" else "\\]"
                if text.startswith(closer, i) and not _is_escaped(text, i):
                    i += 2
                    paired_delim = None
                else:
                    i += 1
                continue

            if text.startswith("\\(", i) or text.startswith("\\[", i):
                paired_delim = text[i:i + 2]
                i += 2
                continue
            if text.startswith("$$", i) and not _is_escaped(text, i):
                dollar_delim = "$$"
                i += 2
                continue
            if text[i] == "$" and not _is_escaped(text, i):
                dollar_delim = "$"
                i += 1
                continue
            match = re.match(r'\\begin\{([^}]+)\}', text[i:limit])
            if match and match.group(1).rstrip("*") in _MATH_ENV_NAMES:
                env_stack.append(match.group(1).rstrip("*"))
                i += match.end()
                continue
            i += 2 if text[i] == "\\" and i + 1 < limit else 1

        return bool(dollar_delim or paired_delim or env_stack)


# ─── Funzione standalone extract_structure (wrap di extract_sections) ──────────
# Usata dalla minimap (ui/latex_minimap.py) per ottenere la struttura documento
# in formato [{depth, type, title, line}, ...].

_SECTION_DEPTH = {
    "part": 0, "chapter": 1, "section": 2, "subsection": 3,
    "subsubsection": 4, "paragraph": 5, "subparagraph": 6,
}


def extract_structure(text: str) -> list[dict]:
    """Restituisce la struttura del documento come lista di dizionari
    con chiavi depth, type, title, line (1-based)."""
    return [
        {"depth": _SECTION_DEPTH.get(typ, 0), "type": typ,
         "title": title, "line": line + 1}
        for typ, title, line in LaTeXSupport.extract_sections(text)
    ]

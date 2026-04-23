"""
editor/autocomplete.py — Motore autocompletamento multilivello
NotePadPQ

Livelli di autocompletamento:
  1. Parole nel documento corrente      (sempre attivo, QScintilla nativo)
  2. Parole in tutti i tab aperti       (opzionale)
  3. Snippet per linguaggio             (opzionale, → editor/snippets.py)
  4. Dizionari API statici per linguaggio (opzionale)
  5. LSP (Language Server Protocol)     (opzionale, → editor/lsp_client.py)

Uso:
    from editor.autocomplete import AutoCompleteManager
    ac = AutoCompleteManager(editor)
    ac.set_language("python")
    ac.set_level(AutoCompleteLevel.API_DICT, True)
"""

from __future__ import annotations

import re
from enum import IntFlag, auto
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.Qsci import QsciScintilla, QsciAPIs

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget

# ─── Livelli autocompletamento ────────────────────────────────────────────────

class AutoCompleteLevel(IntFlag):
    NONE        = 0
    DOCUMENT    = auto()   # parole nel documento corrente
    ALL_DOCS    = auto()   # parole in tutti i tab
    SNIPPETS    = auto()   # snippet per linguaggio
    API_DICT    = auto()   # dizionari statici per linguaggio
    LSP         = auto()   # Language Server Protocol
    ALL         = DOCUMENT | ALL_DOCS | SNIPPETS | API_DICT

# ─── Dizionari API statici ────────────────────────────────────────────────────
# Ogni voce: "nome?N\ndoc" dove N = tipo icona QScintilla (0-8)
# oppure semplicemente "nome" per voci senza tipo

_API_PYTHON: list[str] = [
    # builtins
    "print()?3\nStampa sullo stdout",
    "len()?3\nRestituisce la lunghezza di un oggetto",
    "range()?3\nGeneratore di sequenze intere",
    "type()?3\nRestituisce il tipo dell'oggetto",
    "isinstance()?3\nVerifica se un oggetto è istanza di una classe",
    "str()?3", "int()?3", "float()?3", "bool()?3", "list()?3",
    "dict()?3", "set()?3", "tuple()?3", "bytes()?3", "bytearray()?3",
    "enumerate()?3", "zip()?3", "map()?3", "filter()?3", "sorted()?3",
    "reversed()?3", "sum()?3", "min()?3", "max()?3", "abs()?3",
    "round()?3", "open()?3", "input()?3", "super()?3", "property()?3",
    "staticmethod()?3", "classmethod()?3", "hasattr()?3", "getattr()?3",
    "setattr()?3", "delattr()?3", "vars()?3", "dir()?3", "id()?3",
    "hash()?3", "repr()?3", "iter()?3", "next()?3", "callable()?3",
    # keywords e costrutti
    "def?1", "class?1", "import?1", "from?1", "return?1", "yield?1",
    "async?1", "await?1", "with?1", "as?1", "pass?1", "raise?1",
    "try?1", "except?1", "finally?1", "if?1", "elif?1", "else?1",
    "for?1", "while?1", "break?1", "continue?1", "lambda?1",
    "and?1", "or?1", "not?1", "in?1", "is?1", "None?1", "True?1",
    "False?1", "global?1", "nonlocal?1", "del?1", "assert?1",
    # decoratori comuni
    "@property", "@staticmethod", "@classmethod", "@abstractmethod",
    "@dataclass", "@functools.wraps",
    # typing
    "Optional?2", "List?2", "Dict?2", "Tuple?2", "Set?2", "Union?2",
    "Any?2", "Callable?2", "Generator?2", "Iterator?2", "TypeVar?2",
    "Protocol?2", "dataclass?2", "field?2",
    # pathlib
    "Path?0", "Path.home()?3", "Path.cwd()?3",
]

_API_LATEX: list[str] = [
    # struttura documento
    "\\documentclass{}", "\\usepackage{}", "\\begin{}", "\\end{}",
    "\\title{}", "\\author{}", "\\date{}", "\\maketitle",
    # sezionamento
    "\\part{}", "\\chapter{}", "\\section{}", "\\subsection{}",
    "\\subsubsection{}", "\\paragraph{}", "\\subparagraph{}",
    "\\section*{}", "\\subsection*{}", "\\subsubsection*{}",
    # ambienti comuni
    "\\begin{document}", "\\end{document}",
    "\\begin{figure}", "\\end{figure}",
    "\\begin{table}", "\\end{table}",
    "\\begin{tabular}", "\\end{tabular}",
    "\\begin{equation}", "\\end{equation}",
    "\\begin{align}", "\\end{align}",
    "\\begin{align*}", "\\end{align*}",
    "\\begin{itemize}", "\\end{itemize}",
    "\\begin{enumerate}", "\\end{enumerate}",
    "\\begin{description}", "\\end{description}",
    "\\begin{verbatim}", "\\end{verbatim}",
    "\\begin{abstract}", "\\end{abstract}",
    "\\begin{center}", "\\end{center}",
    "\\begin{minipage}", "\\end{minipage}",
    "\\begin{multicols}", "\\end{multicols}",
    "\\begin{lstlisting}", "\\end{lstlisting}",
    "\\begin{tcolorbox}", "\\end{tcolorbox}",
    "\\begin{tikzpicture}", "\\end{tikzpicture}",
    # cross-reference
    "\\label{}", "\\ref{}", "\\eqref{}", "\\pageref{}", "\\cite{}",
    "\\citep{}", "\\citet{}", "\\citeauthor{}", "\\citeyear{}",
    # formattazione testo
    "\\textbf{}", "\\textit{}", "\\texttt{}", "\\textrm{}", "\\textsf{}",
    "\\emph{}", "\\underline{}", "\\textsc{}", "\\textsl{}",
    "\\footnote{}", "\\marginpar{}", "\\index{}", "\\glossary{}",
    # matematica
    "\\frac{}{}", "\\sqrt{}", "\\sum", "\\prod", "\\int", "\\oint",
    "\\partial", "\\nabla", "\\infty", "\\forall", "\\exists",
    "\\alpha", "\\beta", "\\gamma", "\\delta", "\\epsilon", "\\zeta",
    "\\eta", "\\theta", "\\iota", "\\kappa", "\\lambda", "\\mu",
    "\\nu", "\\xi", "\\pi", "\\rho", "\\sigma", "\\tau", "\\upsilon",
    "\\phi", "\\chi", "\\psi", "\\omega",
    "\\Alpha", "\\Beta", "\\Gamma", "\\Delta", "\\Theta", "\\Lambda",
    "\\Pi", "\\Sigma", "\\Phi", "\\Psi", "\\Omega",
    "\\left(", "\\right)", "\\left[", "\\right]", "\\left\\{", "\\right\\}",
    "\\cdot", "\\times", "\\div", "\\pm", "\\mp", "\\leq", "\\geq",
    "\\neq", "\\approx", "\\equiv", "\\sim", "\\simeq", "\\propto",
    "\\to", "\\rightarrow", "\\leftarrow", "\\Rightarrow", "\\Leftrightarrow",
    "\\ldots", "\\cdots", "\\vdots", "\\ddots",
    "\\hat{}", "\\bar{}", "\\vec{}", "\\dot{}", "\\ddot{}", "\\tilde{}",
    "\\overline{}", "\\underline{}", "\\overbrace{}", "\\underbrace{}",
    "\\mathbf{}", "\\mathit{}", "\\mathrm{}", "\\mathcal{}", "\\mathbb{}",
    # include e grafica
    "\\input{}", "\\include{}", "\\includeonly{}",
    "\\includegraphics{}", "\\includegraphics[width=\\textwidth]{}",
    "\\graphicspath{{}}",
    # tabelle
    "\\hline", "\\cline{}", "\\multicolumn{}{}{}", "\\multirow{}{}{}",
    "\\toprule", "\\midrule", "\\bottomrule", "\\addlinespace",
    # lunghezze e spazi
    "\\textwidth", "\\linewidth", "\\columnwidth", "\\paperwidth",
    "\\textheight", "\\paperheight",
    "\\hspace{}", "\\vspace{}", "\\hfill", "\\vfill",
    "\\smallskip", "\\medskip", "\\bigskip", "\\noindent",
    "\\newline", "\\newpage", "\\clearpage", "\\cleardoublepage",
    # pacchetti comuni (completamento dopo \usepackage{)
    "geometry", "hyperref", "graphicx", "amsmath", "amssymb", "amsthm",
    "booktabs", "tabularx", "longtable", "multirow", "array",
    "xcolor", "color", "tikz", "pgfplots",
    "babel", "inputenc", "fontenc", "lmodern", "microtype",
    "listings", "minted", "verbatim",
    "natbib", "biblatex", "cite",
    "fancyhdr", "titlesec", "tocloft",
    "caption", "subcaption", "float", "wrapfig",
    "enumitem", "mdframed", "tcolorbox",
    "siunitx", "mathtools", "physics",
    "algorithm", "algorithmicx", "algpseudocode",
    "index", "makeidx", "imakeidx",
]

_API_HTML: list[str] = [
    # tag struttura
    "<!DOCTYPE html>", "<html>", "<head>", "<body>", "<title>",
    "<meta>", "<link>", "<script>", "<style>",
    # tag semantici
    "<header>", "<footer>", "<main>", "<nav>", "<aside>",
    "<section>", "<article>", "<figure>", "<figcaption>",
    # tag testo
    "<h1>", "<h2>", "<h3>", "<h4>", "<h5>", "<h6>",
    "<p>", "<span>", "<div>", "<pre>", "<code>",
    "<strong>", "<em>", "<b>", "<i>", "<u>", "<s>",
    "<blockquote>", "<q>", "<cite>", "<abbr>", "<mark>",
    # tag lista
    "<ul>", "<ol>", "<li>", "<dl>", "<dt>", "<dd>",
    # tag tabella
    "<table>", "<thead>", "<tbody>", "<tfoot>",
    "<tr>", "<th>", "<td>", "<caption>", "<colgroup>", "<col>",
    # tag form
    "<form>", "<input>", "<button>", "<select>", "<option>",
    "<textarea>", "<label>", "<fieldset>", "<legend>",
    # tag media
    "<img>", "<video>", "<audio>", "<source>", "<picture>",
    "<canvas>", "<svg>", "<iframe>",
    # attributi comuni
    "class=\"\"", "id=\"\"", "style=\"\"", "href=\"\"", "src=\"\"",
    "alt=\"\"", "title=\"\"", "type=\"\"", "name=\"\"", "value=\"\"",
    "placeholder=\"\"", "required", "disabled", "readonly",
    "data-", "aria-label=\"\"", "role=\"\"",
]

_API_CSS: list[str] = [
    # layout
    "display:", "position:", "float:", "clear:", "overflow:", "visibility:",
    "flex:", "flex-direction:", "flex-wrap:", "justify-content:", "align-items:",
    "align-self:", "grid:", "grid-template-columns:", "grid-template-rows:",
    "grid-column:", "grid-row:", "gap:",
    # box model
    "width:", "height:", "min-width:", "max-width:", "min-height:", "max-height:",
    "margin:", "margin-top:", "margin-right:", "margin-bottom:", "margin-left:",
    "padding:", "padding-top:", "padding-right:", "padding-bottom:", "padding-left:",
    "border:", "border-radius:", "border-top:", "border-right:", "border-bottom:", "border-left:",
    "box-sizing:", "box-shadow:",
    # testo
    "color:", "font-family:", "font-size:", "font-weight:", "font-style:",
    "line-height:", "letter-spacing:", "text-align:", "text-decoration:",
    "text-transform:", "white-space:", "word-break:", "text-overflow:",
    # background
    "background:", "background-color:", "background-image:", "background-size:",
    "background-position:", "background-repeat:", "background-attachment:",
    # animazione
    "transition:", "animation:", "transform:", "opacity:",
    # valori comuni
    "none", "auto", "inherit", "initial", "unset",
    "flex", "block", "inline", "inline-block", "grid",
    "relative", "absolute", "fixed", "sticky",
    "100%", "100vw", "100vh",
    "rgba()", "hsl()", "var(--)",
]

_API_SQL: list[str] = [
    "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "LIKE",
    "BETWEEN", "IS NULL", "IS NOT NULL", "ORDER BY", "GROUP BY",
    "HAVING", "LIMIT", "OFFSET", "DISTINCT", "AS",
    "JOIN", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN", "FULL OUTER JOIN",
    "ON", "USING", "NATURAL JOIN", "CROSS JOIN",
    "INSERT INTO", "VALUES", "UPDATE", "SET", "DELETE FROM",
    "CREATE TABLE", "ALTER TABLE", "DROP TABLE", "TRUNCATE",
    "CREATE INDEX", "DROP INDEX", "CREATE VIEW", "DROP VIEW",
    "PRIMARY KEY", "FOREIGN KEY", "REFERENCES", "UNIQUE", "NOT NULL",
    "DEFAULT", "CHECK", "CONSTRAINT",
    "COUNT()", "SUM()", "AVG()", "MIN()", "MAX()", "COALESCE()",
    "CASE WHEN", "THEN", "ELSE", "END",
    "ROUND()", "CAST()", "CONVERT()", "SUBSTRING()", "TRIM()",
    "UPPER()", "LOWER()", "LENGTH()", "CONCAT()",
    "NOW()", "CURRENT_DATE", "CURRENT_TIMESTAMP",
    "WITH", "UNION", "UNION ALL", "INTERSECT", "EXCEPT",
    "EXPLAIN", "ANALYZE", "VACUUM", "BEGIN", "COMMIT", "ROLLBACK",
]

_API_BASH: list[str] = [
    # builtin
    "echo", "printf", "read", "exit", "return", "source", "export",
    "local", "declare", "typeset", "readonly", "unset",
    "if", "then", "elif", "else", "fi", "case", "esac",
    "for", "in", "do", "done", "while", "until", "break", "continue",
    "function", "shift", "getopts",
    "test", "[[", "]]", "((", "))",
    # comandi sistema comuni
    "ls", "cd", "pwd", "mkdir", "rmdir", "rm", "cp", "mv", "touch",
    "cat", "less", "more", "head", "tail", "grep", "sed", "awk",
    "cut", "sort", "uniq", "wc", "tr", "xargs",
    "find", "locate", "which", "whereis", "file", "stat",
    "chmod", "chown", "chgrp", "ln", "readlink",
    "tar", "gzip", "gunzip", "zip", "unzip", "bzip2",
    "ssh", "scp", "rsync", "curl", "wget",
    "ps", "top", "kill", "killall", "jobs", "bg", "fg",
    "sudo", "su", "id", "whoami", "who",
    "date", "time", "sleep", "wait",
    "pipe (|)", "redirect (>)", "append (>>)", "input (<)", "here-doc (<<EOF)",
    "${VAR}", "${VAR:-default}", "${#VAR}", "${VAR/pattern/replacement}",
    "$?", "$!", "$$", "$0", "$@", "$*", "$#",
]

_API_JAVASCRIPT: list[str] = [
    # keywords
    "const", "let", "var", "function", "class", "extends", "import",
    "export", "default", "return", "async", "await", "new", "this",
    "super", "typeof", "instanceof", "void", "delete",
    "if", "else", "for", "while", "do", "switch", "case", "break",
    "continue", "try", "catch", "finally", "throw",
    # built-in globali
    "console.log()", "console.error()", "console.warn()", "console.table()",
    "setTimeout()", "setInterval()", "clearTimeout()", "clearInterval()",
    "fetch()", "Promise", "Promise.all()", "Promise.resolve()",
    "JSON.stringify()", "JSON.parse()",
    "parseInt()", "parseFloat()", "isNaN()", "isFinite()",
    "encodeURIComponent()", "decodeURIComponent()",
    "Math.floor()", "Math.ceil()", "Math.round()", "Math.random()",
    "Math.max()", "Math.min()", "Math.abs()", "Math.pow()", "Math.sqrt()",
    "Array.from()", "Array.isArray()", "Object.keys()", "Object.values()",
    "Object.entries()", "Object.assign()", "Object.freeze()",
    # Array methods
    ".map()", ".filter()", ".reduce()", ".forEach()", ".find()",
    ".findIndex()", ".some()", ".every()", ".includes()", ".indexOf()",
    ".push()", ".pop()", ".shift()", ".unshift()", ".splice()", ".slice()",
    ".join()", ".concat()", ".flat()", ".flatMap()", ".sort()", ".reverse()",
    # String methods
    ".trim()", ".trimStart()", ".trimEnd()", ".split()", ".replace()",
    ".replaceAll()", ".startsWith()", ".endsWith()", ".includes()",
    ".padStart()", ".padEnd()", ".repeat()", ".at()",
    # DOM
    "document.getElementById()", "document.querySelector()",
    "document.querySelectorAll()", "document.createElement()",
    "element.addEventListener()", "element.removeEventListener()",
    "element.classList.add()", "element.classList.remove()",
    "element.classList.toggle()", "element.setAttribute()",
    "element.getAttribute()", "element.innerHTML", "element.textContent",
]


_API_CPP: list[str] = [
    # preprocessore
    "#include?1", "#define?1", "#ifdef?1", "#ifndef?1", "#endif?1",
    "#pragma?1", "#undef?1", "#if?1", "#else?1", "#elif?1",
    # tipi base
    "int?1", "long?1", "short?1", "char?1", "unsigned?1", "signed?1",
    "float?1", "double?1", "bool?1", "void?1", "auto?1", "size_t?1",
    "int8_t?1", "int16_t?1", "int32_t?1", "int64_t?1",
    "uint8_t?1", "uint16_t?1", "uint32_t?1", "uint64_t?1",
    "nullptr?1", "NULL?1", "true?1", "false?1",
    # keywords C++
    "class?1", "struct?1", "enum?1", "union?1", "namespace?1",
    "template?1", "typename?1", "typedef?1", "using?1",
    "public?1", "private?1", "protected?1", "virtual?1",
    "override?1", "final?1", "explicit?1", "inline?1",
    "static?1", "const?1", "constexpr?1", "consteval?1", "constinit?1",
    "mutable?1", "volatile?1", "extern?1", "register?1",
    "new?1", "delete?1", "this?1", "operator?1",
    "try?1", "catch?1", "throw?1", "noexcept?1",
    "if?1", "else?1", "for?1", "while?1", "do?1", "switch?1",
    "case?1", "break?1", "continue?1", "return?1", "goto?1",
    "sizeof?1", "alignof?1", "typeid?1", "decltype?1",
    # STL containers
    "std::vector?2", "std::list?2", "std::map?2", "std::unordered_map?2",
    "std::set?2", "std::unordered_set?2", "std::array?2", "std::deque?2",
    "std::queue?2", "std::stack?2", "std::pair?2", "std::tuple?2",
    "std::string?2", "std::wstring?2", "std::string_view?2",
    # STL algoritmi
    "std::sort?2", "std::find?2", "std::for_each?2", "std::transform?2",
    "std::copy?2", "std::move?2", "std::swap?2", "std::min?2", "std::max?2",
    "std::begin?2", "std::end?2", "std::size?2", "std::empty?2",
    "std::make_pair?2", "std::make_tuple?2", "std::make_shared?2",
    "std::make_unique?2",
    # smart pointers
    "std::unique_ptr?2", "std::shared_ptr?2", "std::weak_ptr?2",
    # stream
    "std::cout?2", "std::cin?2", "std::cerr?2", "std::endl?2",
    "std::ifstream?2", "std::ofstream?2", "std::stringstream?2",
    # utility
    "std::optional?2", "std::variant?2", "std::any?2", "std::span?2",
    "std::function?2", "std::bind?2", "std::thread?2", "std::mutex?2",
    "std::lock_guard?2", "std::unique_lock?2", "std::atomic?2",
    "std::chrono?2", "std::filesystem?2",
    # printf / C stdio
    "printf()?3", "scanf()?3", "sprintf()?3", "snprintf()?3",
    "malloc()?3", "calloc()?3", "realloc()?3", "free()?3",
    "memset()?3", "memcpy()?3", "memmove()?3", "strlen()?3",
    "strcmp()?3", "strncmp()?3", "strcpy()?3", "strncpy()?3",
]

_API_MARKDOWN: list[str] = [
    "# Titolo 1", "## Titolo 2", "### Titolo 3",
    "**grassetto**", "*corsivo*", "~~barrato~~", "`codice inline`",
    "```python", "```bash", "```cpp", "```latex", "```",
    "[testo](url)", "![alt](url)", "> citazione",
    "- elemento lista", "1. elemento numerato",
    "| colonna | colonna |", "|---|---|",
    "---", "***",
]

_API_YAML: list[str] = [
    "true", "false", "null", "~",
    "---", "...",
]

_API_JSON_KW: list[str] = [
    "true", "false", "null",
]

# Mappa linguaggio → lista API
_LANGUAGE_APIS: dict[str, list[str]] = {
    "python":     _API_PYTHON,
    "latex":      _API_LATEX,
    "bibtex":     _API_LATEX,
    "html":       _API_HTML,
    "css":        _API_CSS,
    "sql":        _API_SQL,
    "bash":       _API_BASH,
    "shell":      _API_BASH,
    "dockerfile": _API_BASH,
    "javascript": _API_JAVASCRIPT,
    "typescript": _API_JAVASCRIPT,
    "c/c++":      _API_CPP,
    "c":          _API_CPP,
    "c++":        _API_CPP,
    "cpp":        _API_CPP,
    "c#":         _API_CPP,   # subset ragionevole come fallback
    "java":       _API_CPP,   # idem
    "markdown":   _API_MARKDOWN,
    "yaml":       _API_YAML,
    "json":       _API_JSON_KW,
}

# ─── AutoCompleteManager ──────────────────────────────────────────────────────

class AutoCompleteManager(QObject):
    """
    Gestisce i livelli di autocompletamento per un EditorWidget.
    Un'istanza per tab.
    """

    def __init__(self, editor: "EditorWidget", parent: QObject = None):
        super().__init__(parent)

        self._editor   = editor
        self._language = ""
        self._levels   = AutoCompleteLevel.DOCUMENT | AutoCompleteLevel.API_DICT
        self._api: Optional[QsciAPIs] = None
        self._tab_manager_ref = None   # impostato da TabManager

        # Timer per aggiornamento cross-tab (evita refresh ad ogni keystroke)
        self._cross_tab_timer = QTimer(self)
        self._cross_tab_timer.setSingleShot(True)
        self._cross_tab_timer.setInterval(1500)
        self._cross_tab_timer.timeout.connect(self._rebuild_all_docs_words)

        self._setup_base()

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _setup_base(self) -> None:
        """Configurazione base QScintilla per autocompletamento."""
        ed = self._editor
        ed.setAutoCompletionSource(QsciScintilla.AutoCompletionSource.AcsAll)
        ed.setAutoCompletionThreshold(2)
        ed.setAutoCompletionCaseSensitivity(False)
        ed.setAutoCompletionReplaceWord(False)
        ed.setAutoCompletionUseSingle(
            QsciScintilla.AutoCompletionUseSingle.AcusNever
        )
        # Call tips
        ed.setCallTipsStyle(QsciScintilla.CallTipsStyle.CallTipsContext)
        ed.setCallTipsVisible(5)
        ed.setCallTipsBackgroundColor(QColor("#ffffd0"))
        ed.setCallTipsForegroundColor(QColor("#000000"))
        ed.setCallTipsHighlightColor(QColor("#0000ff"))

    # ── Livelli ───────────────────────────────────────────────────────────────

    def set_level(self, level: AutoCompleteLevel, enabled: bool) -> None:
        if enabled:
            self._levels |= level
        else:
            self._levels &= ~level
        self._apply_levels()

    def get_levels(self) -> AutoCompleteLevel:
        return self._levels

    def _apply_levels(self) -> None:
        """Aggiorna la sorgente QScintilla in base ai livelli attivi."""
        ed = self._editor
        if self._levels & AutoCompleteLevel.API_DICT:
            # AcsAll = documento + API list
            ed.setAutoCompletionSource(
                QsciScintilla.AutoCompletionSource.AcsAll
            )
        elif self._levels & AutoCompleteLevel.DOCUMENT:
            ed.setAutoCompletionSource(
                QsciScintilla.AutoCompletionSource.AcsDocument
            )
        else:
            ed.setAutoCompletionSource(
                QsciScintilla.AutoCompletionSource.AcsNone
            )

    # ── Linguaggio ────────────────────────────────────────────────────────────

    def set_language(self, language: str) -> None:
        """
        Imposta il linguaggio e ricarica il dizionario API appropriato.
        language: stringa lowercase es. "python", "latex", "html"
        """
        self._language = language.lower()
        self._rebuild_api()

    def _rebuild_api(self) -> None:
        """Ricostruisce il QsciAPIs con i termini del linguaggio corrente."""
        lexer = self._editor.lexer()
        if lexer is None:
            # Lexer non ancora impostato: riprova tra poco
            # (accade quando set_language viene chiamato prima del lexer)
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, self._rebuild_api)
            return

        self._api = QsciAPIs(lexer)

        # Dizionario API statici
        if self._levels & AutoCompleteLevel.API_DICT:
            api_list = _LANGUAGE_APIS.get(self._language, [])
            for term in api_list:
                self._api.add(term)

        # Snippet (delegato a snippets.py)
        if self._levels & AutoCompleteLevel.SNIPPETS:
            self._add_snippet_triggers()

        # Parole cross-tab
        if self._levels & AutoCompleteLevel.ALL_DOCS:
            self._add_all_docs_words()

        # Per LaTeX: aggiungi API dinamica dal documento corrente
        # (comandi custom, ambienti custom, comandi dei pacchetti caricati)
        if self._language in ("latex", "bibtex"):
            try:
                from editor.latex_support import LaTeXSupport
                dynamic = LaTeXSupport.build_dynamic_api(
                    self._editor.text(),
                    getattr(self._editor, "file_path", None)
                )
                for term in dynamic:
                    self._api.add(term)
            except Exception:
                pass

        self._api.prepare()
        lexer.setAPIs(self._api)

    def _add_snippet_triggers(self) -> None:
        """Aggiunge i trigger degli snippet al dizionario."""
        try:
            from editor.snippets import SnippetManager
            triggers = SnippetManager.instance().get_triggers(self._language)
            for trigger, description in triggers.items():
                self._api.add(f"{trigger}?5\n{description}")
        except Exception:
            pass

    # ── Cross-tab ─────────────────────────────────────────────────────────────

    def set_tab_manager(self, tab_manager) -> None:
        """Collega il tab manager per il completamento cross-documento."""
        self._tab_manager_ref = tab_manager
        if self._tab_manager_ref:
            # Quando un altro editor cambia, scheduliamo il rebuild
            self._editor.textChanged.connect(
                lambda: self._cross_tab_timer.start()
            )

    def _add_all_docs_words(self) -> None:
        """Aggiunge al dizionario le parole da tutti i tab aperti."""
        if not self._tab_manager_ref:
            return
        seen = set()
        for editor in self._tab_manager_ref.all_editors():
            if editor is self._editor:
                continue
            text = editor.text()
            words = re.findall(r'\b[a-zA-Z_]\w{2,}\b', text)
            for w in words:
                if w not in seen:
                    seen.add(w)
                    self._api.add(w)

    def _rebuild_all_docs_words(self) -> None:
        """Ricostruisce il dizionario includendo parole aggiornate degli altri tab."""
        if self._levels & AutoCompleteLevel.ALL_DOCS:
            self._rebuild_api()

    # ── Completamento manuale ─────────────────────────────────────────────────

    def trigger_manual(self) -> None:
        """Forza la visualizzazione del popup (Ctrl+Space)."""
        self._editor.autoCompleteFromAll()

    # ── Completamento speciale per LaTeX ──────────────────────────────────────

    def handle_latex_special(self, char: str) -> bool:
        """
        Gestisce completamenti speciali LaTeX:
        - dopo '{' in \\ref{, \\cite{, \\begin{: completa con label/cite/ambienti
        Restituisce True se ha gestito il carattere.
        """
        if self._language != "latex" or char != "{":
            return False

        ed = self._editor
        line, col = ed.getCursorPosition()
        line_text = ed.text(line)[:col]

        # Controlla il comando precedente la {
        match = re.search(r'\\(\w+)\{$', line_text)
        if not match:
            return False

        cmd = match.group(1)

        if cmd in ("ref", "eqref", "pageref", "autoref", "cref", "Cref",
                       "nameref", "hyperref", "vref", "cpageref"):
            self._complete_labels()
            return True
        elif cmd in ("cite", "citep", "citet", "citeauthor", "citeyear",
                     "parencite", "footcite", "textcite", "autocite",
                     "fullcite", "citetitle", "citealt", "citealp"):
            self._complete_cite_keys()
            return True
        elif cmd in ("begin", "end"):
            self._complete_environments()
            return True
        elif cmd in ("input", "include", "subfile", "subinputfrom"):
            self._complete_file_paths("tex")
            return True
        elif cmd == "includegraphics":
            self._complete_file_paths("includegraphics")
            return True
        elif cmd == "usepackage":
            self._complete_packages()
            return True
        elif cmd == "documentclass":
            self._complete_documentclasses()
            return True
        elif cmd in ("bibliography", "addbibresource"):
            self._complete_file_paths("bib")
            return True

        return False

    def _complete_labels(self) -> None:
        """Popup con tutte le \\label{} del documento."""
        from editor.latex_support import LaTeXSupport
        labels = LaTeXSupport.extract_labels(self._editor.text())
        if labels:
            self._editor.showUserList(1, labels)

    def _complete_cite_keys(self) -> None:
        """Popup con le chiavi BibTeX dai .bib referenziati."""
        from editor.latex_support import LaTeXSupport
        keys = LaTeXSupport.extract_bibtex_keys(
            self._editor.text(),
            self._editor.file_path
        )
        if keys:
            self._editor.showUserList(2, keys)

    def _complete_environments(self) -> None:
        """Popup con tutti gli ambienti LaTeX: standard + custom del documento."""
        try:
            from editor.latex_support import LaTeXSupport
            envs = LaTeXSupport.get_all_environments(self._editor.text())
        except Exception:
            from editor.latex_support import STANDARD_ENVIRONMENTS
            envs = STANDARD_ENVIRONMENTS
        self._editor.showUserList(3, sorted(envs))

    def _complete_file_paths(self, cmd: str) -> None:
        """Popup con i file nella directory del documento corrente."""
        from pathlib import Path
        ed = self._editor
        if not ed.file_path:
            return

        base_dir = ed.file_path.parent
        if cmd == "includegraphics":
            exts = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg"}
        else:
            exts = {".tex", ".sty", ".cls"}

        files = [
            f.name for f in base_dir.iterdir()
            if f.is_file() and f.suffix.lower() in exts
        ]
        if files:
            self._editor.showUserList(4, sorted(files))

    def _complete_packages(self) -> None:
        """Popup con i pacchetti LaTeX più comuni (per \\usepackage{)."""
        from editor.latex_support import PACKAGE_COMMANDS
        # Pacchetti noti + aggiunge quelli comuni non nel dict
        known = list(PACKAGE_COMMANDS.keys())
        extra = [
            "amsmath", "amssymb", "amsthm", "mathtools",
            "inputenc", "fontenc", "babel", "polyglossia",
            "lmodern", "fontawesome5", "microtype",
            "geometry", "layout", "fullpage", "a4wide",
            "graphicx", "graphics", "epsfig", "wrapfig",
            "xcolor", "color", "colortbl", "soul",
            "hyperref", "url", "cleveref", "varioref",
            "natbib", "biblatex", "cite",
            "booktabs", "tabularx", "tabulary", "longtable",
            "multirow", "array", "dcolumn", "hhline",
            "fancyhdr", "titlesec", "tocloft", "tocbibind",
            "caption", "subcaption", "float", "placeins",
            "listings", "minted", "verbatim", "fancyvrb",
            "tikz", "pgf", "pgfplots", "pgfplotstable",
            "algorithm2e", "algorithmicx", "algpseudocode",
            "siunitx", "physics", "braket", "tensor",
            "tcolorbox", "mdframed", "framed", "shadethm",
            "enumitem", "paralist", "tasks",
            "imakeidx", "makeidx", "index",
            "glossaries", "nomencl", "acronym",
            "todonotes", "changes", "ulem", "soulpos",
            "parskip", "setspace", "leading",
            "csquotes", "epigraph",
            "pdfpages", "pdflscape", "rotating",
            "datetime2", "datenumber",
            "xparse", "expl3", "l3keys2e",
            "etoolbox", "ifthen", "calc",
        ]
        all_pkgs = sorted(set(known + extra))
        self._editor.showUserList(5, all_pkgs)

    def _complete_documentclasses(self) -> None:
        """Popup con le document class LaTeX standard."""
        classes = sorted([
            "article", "book", "report", "letter", "slides",
            "beamer", "memoir", "scrartcl", "scrbook", "scrreprt",
            "IEEEtran", "acmart", "llncs", "revtex4-2",
            "amsart", "amsproc", "amsbook",
            "standalone", "subfiles",
            "tufte-book", "tufte-handout",
            "extarticle", "extbook", "extreport",
        ])
        self._editor.showUserList(6, classes)

    # ── Rebuild su modifica documento (pacchetti/label cambiano) ─────────────

    def on_document_changed(self) -> None:
        """
        Chiamato dopo una modifica al documento LaTeX.
        Pianifica un rebuild dell'API per aggiornare label/comandi custom.
        Solo per LaTeX: usa un timer per non rallentare la digitazione.
        """
        if self._language in ("latex", "bibtex"):
            if not hasattr(self, "_doc_change_timer"):
                from PyQt6.QtCore import QTimer
                self._doc_change_timer = QTimer(self)
                self._doc_change_timer.setSingleShot(True)
                self._doc_change_timer.setInterval(2000)
                self._doc_change_timer.timeout.connect(self._rebuild_api)
            self._doc_change_timer.start()

    # ── Soglia e trigger ──────────────────────────────────────────────────────

    def set_threshold(self, chars: int) -> None:
        """Numero minimo di caratteri per attivare il popup automatico."""
        self._editor.setAutoCompletionThreshold(chars)

    def set_case_sensitive(self, sensitive: bool) -> None:
        self._editor.setAutoCompletionCaseSensitivity(sensitive)

    def refresh(self) -> None:
        """Forza il rebuild del dizionario API (es. dopo cambio tema/lingua)."""
        self._rebuild_api()

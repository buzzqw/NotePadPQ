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

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
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
    # ── Struttura documento ────────────────────────────────────────────────────
    "\\documentclass{}?1\nScegli la classe documento",
    "\\documentclass[]{}", "\\usepackage{}", "\\usepackage[]{}",
    "\\begin{}", "\\end{}",
    "\\title{}", "\\author{}", "\\date{}", "\\date{\\today}",
    "\\maketitle", "\\makeatletter", "\\makeatother",
    "\\tableofcontents", "\\listoffigures", "\\listoftables",
    "\\appendix", "\\frontmatter", "\\mainmatter", "\\backmatter",
    "\\newpage", "\\clearpage", "\\cleardoublepage",
    "\\pagebreak", "\\pagebreak[4]", "\\nopagebreak", "\\nopagebreak[4]",
    "\\linebreak", "\\nolinebreak", "\\newline",
    "\\thispagestyle{}", "\\pagestyle{}",
    "\\pagenumbering{arabic}", "\\pagenumbering{roman}",
    "\\setcounter{}{}", "\\addtocounter{}{}", "\\value{}",
    "\\stepcounter{}", "\\refstepcounter{}",
    "\\centering", "\\raggedright", "\\raggedleft",
    "\\par", "\\samepage",
    # ── Sezionamento ──────────────────────────────────────────────────────────
    "\\part{}", "\\part*{}", "\\chapter{}", "\\chapter*{}",
    "\\section{}", "\\section*{}", "\\subsection{}", "\\subsection*{}",
    "\\subsubsection{}", "\\subsubsection*{}",
    "\\paragraph{}", "\\subparagraph{}",
    # ── Ambienti documento ────────────────────────────────────────────────────
    "\\begin{document}", "\\end{document}",
    "\\begin{abstract}", "\\end{abstract}",
    "\\begin{figure}", "\\end{figure}",
    "\\begin{figure*}", "\\end{figure*}",
    "\\begin{table}", "\\end{table}",
    "\\begin{table*}", "\\end{table*}",
    "\\begin{tabular}", "\\end{tabular}",
    "\\begin{tabular*}", "\\end{tabular*}",
    "\\begin{tabularx}", "\\end{tabularx}",
    "\\begin{longtable}", "\\end{longtable}",
    "\\begin{equation}", "\\end{equation}",
    "\\begin{equation*}", "\\end{equation*}",
    "\\begin{align}", "\\end{align}",
    "\\begin{align*}", "\\end{align*}",
    "\\begin{alignat}", "\\end{alignat}",
    "\\begin{alignat*}", "\\end{alignat*}",
    "\\begin{gather}", "\\end{gather}",
    "\\begin{gather*}", "\\end{gather*}",
    "\\begin{multline}", "\\end{multline}",
    "\\begin{multline*}", "\\end{multline*}",
    "\\begin{split}", "\\end{split}",
    "\\begin{cases}", "\\end{cases}",
    "\\begin{subequations}", "\\end{subequations}",
    "\\begin{array}", "\\end{array}",
    "\\begin{matrix}", "\\end{matrix}",
    "\\begin{pmatrix}", "\\end{pmatrix}",
    "\\begin{bmatrix}", "\\end{bmatrix}",
    "\\begin{vmatrix}", "\\end{vmatrix}",
    "\\begin{Vmatrix}", "\\end{Vmatrix}",
    "\\begin{Bmatrix}", "\\end{Bmatrix}",
    "\\begin{itemize}", "\\end{itemize}",
    "\\begin{enumerate}", "\\end{enumerate}",
    "\\begin{description}", "\\end{description}",
    "\\begin{verbatim}", "\\end{verbatim}",
    "\\begin{verbatim*}", "\\end{verbatim*}",
    "\\begin{abstract}", "\\end{abstract}",
    "\\begin{center}", "\\end{center}",
    "\\begin{flushleft}", "\\end{flushleft}",
    "\\begin{flushright}", "\\end{flushright}",
    "\\begin{minipage}", "\\end{minipage}",
    "\\begin{multicols}", "\\end{multicols}",
    "\\begin{quote}", "\\end{quote}",
    "\\begin{quotation}", "\\end{quotation}",
    "\\begin{verse}", "\\end{verse}",
    "\\begin{lstlisting}", "\\end{lstlisting}",
    "\\begin{minted}", "\\end{minted}",
    "\\begin{tcolorbox}", "\\end{tcolorbox}",
    "\\begin{tikzpicture}", "\\end{tikzpicture}",
    "\\begin{scope}", "\\end{scope}",
    "\\begin{axis}", "\\end{axis}",
    "\\begin{theorem}", "\\end{theorem}",
    "\\begin{lemma}", "\\end{lemma}",
    "\\begin{corollary}", "\\end{corollary}",
    "\\begin{proposition}", "\\end{proposition}",
    "\\begin{definition}", "\\end{definition}",
    "\\begin{remark}", "\\end{remark}",
    "\\begin{example}", "\\end{example}",
    "\\begin{proof}", "\\end{proof}",
    "\\begin{frame}", "\\end{frame}",
    "\\begin{block}{}", "\\end{block}",
    "\\begin{alertblock}{}", "\\end{alertblock}",
    "\\begin{exampleblock}{}", "\\end{exampleblock}",
    "\\begin{columns}", "\\end{columns}",
    "\\begin{column}", "\\end{column}",
    "\\begin{algorithm}", "\\end{algorithm}",
    "\\begin{algorithm2e}", "\\end{algorithm2e}",
    "\\begin{algorithmic}", "\\end{algorithmic}",
    # ── Cross-reference ───────────────────────────────────────────────────────
    "\\label{}", "\\ref{}", "\\eqref{}", "\\pageref{}",
    "\\cite{}", "\\citep{}", "\\citet{}", "\\citeauthor{}", "\\citeyear{}",
    "\\citealt{}", "\\citealp{}", "\\citefullauthor{}",
    "\\parencite{}", "\\footcite{}", "\\textcite{}", "\\autocite{}",
    "\\fullcite{}", "\\citetitle{}",
    "\\cref{}", "\\Cref{}", "\\crefrange{}{}",
    "\\autoref{}", "\\nameref{}", "\\vref{}",
    "\\hyperref[]{}", "\\href{}{}", "\\url{}", "\\nolinkurl{}",
    # ── Formattazione testo ───────────────────────────────────────────────────
    "\\textbf{}", "\\textit{}", "\\texttt{}", "\\textrm{}", "\\textsf{}",
    "\\emph{}", "\\underline{}", "\\textsc{}", "\\textsl{}", "\\textup{}",
    "\\textnormal{}", "\\textmd{}", "\\text{}",
    "\\footnote{}", "\\footnotemark", "\\footnotetext{}",
    "\\marginpar{}", "\\index{}", "\\glossary{}",
    "\\uppercase{}", "\\lowercase{}", "\\MakeUppercase{}", "\\MakeLowercase{}",
    "\\mbox{}", "\\makebox[]{}", "\\fbox{}", "\\framebox[]{}",
    "\\parbox[]{}{}", "\\raisebox{}{}",
    "\\phantom{}", "\\hphantom{}", "\\vphantom{}",
    # ── Dimensioni font ───────────────────────────────────────────────────────
    "\\tiny", "\\scriptsize", "\\footnotesize", "\\small", "\\normalsize",
    "\\large", "\\Large", "\\LARGE", "\\huge", "\\Huge",
    # ── Font shape/series/family ──────────────────────────────────────────────
    "\\normalfont", "\\itshape", "\\bfseries", "\\upshape",
    "\\scshape", "\\slshape", "\\mdseries",
    "\\rmfamily", "\\sffamily", "\\ttfamily",
    # ── Colori (xcolor / color) ───────────────────────────────────────────────
    "\\color{}", "\\textcolor{}{}", "\\colorbox{}{}",
    "\\fcolorbox{}{}{}", "\\definecolor{}{}{}", "\\pagecolor{}",
    # ── Didascalie ────────────────────────────────────────────────────────────
    "\\caption{}", "\\caption[]{}",
    "\\captionof{}{}", "\\subcaption{}",
    "\\listoflistings",
    "\\addcontentsline{}{}{}",
    # ── Include avanzato ─────────────────────────────────────────────────────
    "\\import{}{}", "\\subimport{}{}", "\\inputfrom{}{}",
    # ── Bibliografia ─────────────────────────────────────────────────────────
    "\\nocite{}", "\\nocite{*}",
    "\\bibliographystyle{}", "\\bibliography{}",
    "\\printbibliography", "\\printbibliography[heading=bibintoc]",
    "\\addbibresource{}",
    # ── Spazi e lunghezze ─────────────────────────────────────────────────────
    "\\hspace{}", "\\hspace*{}", "\\vspace{}", "\\vspace*{}",
    "\\hfill", "\\vfill", "\\hfil", "\\vfil",
    "\\smallskip", "\\medskip", "\\bigskip", "\\noindent",
    "\\quad", "\\qquad", "\\,", "\\;", "\\:",
    "\\textwidth", "\\linewidth", "\\columnwidth", "\\paperwidth",
    "\\textheight", "\\paperheight",
    "\\parindent", "\\parskip", "\\baselineskip",
    "\\setlength{}{}", "\\addtolength{}{}",
    "\\stretch{}", "\\fill",
    # ── Matematica — operatori e struttura ────────────────────────────────────
    "\\frac{}{}", "\\dfrac{}{}", "\\tfrac{}{}", "\\cfrac{}{}",
    "\\binom{}{}", "\\dbinom{}{}", "\\tbinom{}{}",
    "\\sqrt{}", "\\sqrt[n]{}",
    "\\sum", "\\sum_{i=1}^{n}", "\\prod", "\\prod_{i=1}^{n}",
    "\\int", "\\int_{a}^{b}", "\\iint", "\\iiint", "\\oint",
    "\\partial", "\\nabla", "\\infty", "\\forall", "\\exists", "\\nexists",
    "\\lim", "\\lim_{x \\to 0}", "\\lim_{n \\to \\infty}",
    "\\sup", "\\inf", "\\max", "\\min", "\\arg", "\\det",
    "\\sin", "\\cos", "\\tan", "\\cot", "\\sec", "\\csc",
    "\\arcsin", "\\arccos", "\\arctan",
    "\\sinh", "\\cosh", "\\tanh",
    "\\log", "\\ln", "\\exp",
    "\\operatorname{}", "\\operatorname*{}",
    "\\text{}", "\\intertext{}", "\\shortintertext{}",
    # ── Matematica — delimitatori ─────────────────────────────────────────────
    "\\left(", "\\right)", "\\left[", "\\right]",
    "\\left\\{", "\\right\\}", "\\left|", "\\right|",
    "\\left\\|", "\\right\\|", "\\left.", "\\right.",
    "\\left\\langle", "\\right\\rangle",
    "\\bigl(", "\\bigr)", "\\Bigl(", "\\Bigr)",
    "\\biggl(", "\\biggr)", "\\Biggl(", "\\Biggr)",
    "\\langle", "\\rangle", "\\lfloor", "\\rfloor",
    "\\lceil", "\\rceil",
    # ── Matematica — lettere greche minuscole ─────────────────────────────────
    "\\alpha", "\\beta", "\\gamma", "\\delta", "\\epsilon",
    "\\varepsilon", "\\zeta", "\\eta", "\\theta", "\\vartheta",
    "\\iota", "\\kappa", "\\lambda", "\\mu", "\\nu", "\\xi",
    "\\pi", "\\varpi", "\\rho", "\\varrho", "\\sigma", "\\varsigma",
    "\\tau", "\\upsilon", "\\phi", "\\varphi", "\\chi", "\\psi", "\\omega",
    # ── Matematica — lettere greche maiuscole ─────────────────────────────────
    "\\Gamma", "\\Delta", "\\Theta", "\\Lambda", "\\Xi",
    "\\Pi", "\\Sigma", "\\Upsilon", "\\Phi", "\\Psi", "\\Omega",
    # ── Matematica — frecce ───────────────────────────────────────────────────
    "\\to", "\\rightarrow", "\\leftarrow", "\\Rightarrow", "\\Leftarrow",
    "\\Leftrightarrow", "\\leftrightarrow", "\\longrightarrow",
    "\\longleftarrow", "\\Longrightarrow", "\\Longleftarrow",
    "\\mapsto", "\\longmapsto", "\\hookrightarrow", "\\hookleftarrow",
    "\\uparrow", "\\downarrow", "\\Uparrow", "\\Downarrow",
    "\\updownarrow", "\\Updownarrow", "\\nearrow", "\\searrow",
    "\\swarrow", "\\nwarrow",
    "\\xleftarrow{}", "\\xrightarrow{}",
    # ── Matematica — operatori binari ─────────────────────────────────────────
    "\\cdot", "\\times", "\\div", "\\pm", "\\mp",
    "\\oplus", "\\ominus", "\\otimes", "\\oslash", "\\odot",
    "\\cup", "\\cap", "\\setminus", "\\sqcup", "\\sqcap",
    "\\vee", "\\wedge", "\\lor", "\\land",
    "\\circ", "\\bullet", "\\star", "\\ast",
    "\\dagger", "\\ddagger",
    # ── Matematica — relazioni ────────────────────────────────────────────────
    "\\leq", "\\geq", "\\neq", "\\approx", "\\equiv",
    "\\sim", "\\simeq", "\\cong", "\\propto",
    "\\ll", "\\gg", "\\lll", "\\ggg",
    "\\subset", "\\supset", "\\subseteq", "\\supseteq",
    "\\in", "\\notin", "\\ni", "\\not\\in",
    "\\perp", "\\parallel", "\\mid", "\\nmid",
    "\\prec", "\\succ", "\\preceq", "\\succeq",
    # ── Matematica — puntini e simboli ────────────────────────────────────────
    "\\ldots", "\\cdots", "\\vdots", "\\ddots", "\\iddots",
    "\\colon", "\\because", "\\therefore",
    "\\checkmark", "\\hbar", "\\ell",
    "\\aleph", "\\wp", "\\Re", "\\Im",
    "\\top", "\\bot", "\\angle", "\\triangle",
    "\\square", "\\blacksquare", "\\lozenge",
    "\\emptyset", "\\varnothing",
    # ── Matematica — accenti e decorazioni ────────────────────────────────────
    "\\hat{}", "\\bar{}", "\\vec{}", "\\dot{}", "\\ddot{}", "\\tilde{}",
    "\\grave{}", "\\acute{}", "\\breve{}", "\\check{}", "\\mathring{}",
    "\\widehat{}", "\\widetilde{}", "\\overrightarrow{}", "\\overleftarrow{}",
    "\\overline{}", "\\underline{}", "\\overbrace{}", "\\underbrace{}",
    "\\overset{}{}", "\\underset{}{}", "\\stackrel{}{}",
    "\\xrightarrow{}", "\\xleftarrow{}",
    # ── Matematica — font ─────────────────────────────────────────────────────
    "\\mathbf{}", "\\mathit{}", "\\mathrm{}", "\\mathcal{}", "\\mathbb{}",
    "\\mathfrak{}", "\\mathscr{}", "\\mathtt{}", "\\mathsf{}",
    "\\boldsymbol{}", "\\pmb{}", "\\bm{}",
    # ── Matrici ───────────────────────────────────────────────────────────────
    "\\begin{pmatrix}\\end{pmatrix}",
    "\\begin{bmatrix}\\end{bmatrix}",
    "\\begin{vmatrix}\\end{vmatrix}",
    "\\begin{Vmatrix}\\end{Vmatrix}",
    "\\begin{matrix}\\end{matrix}",
    # ── Grafica e figure ──────────────────────────────────────────────────────
    "\\input{}", "\\include{}", "\\includeonly{}", "\\subfile{}",
    "\\includegraphics{}", "\\includegraphics[width=\\textwidth]{}",
    "\\includegraphics[scale=0.5]{}",
    "\\graphicspath{{}}", "\\DeclareGraphicsExtensions{}",
    # ── Tabelle ───────────────────────────────────────────────────────────────
    "\\hline", "\\cline{}", "\\multicolumn{}{}{}", "\\multirow{}{}{}",
    "\\toprule", "\\midrule", "\\bottomrule",
    "\\cmidrule{}", "\\cmidrule(lr){}", "\\addlinespace",
    "\\specialrule{}{}{}", "\\arrayrulewidth",
    "\\newcolumntype{}{}", "\\extrarowheight",
    # ── longtable ─────────────────────────────────────────────────────────────
    "\\endhead", "\\endfirsthead", "\\endfoot", "\\endlastfoot",
    # ── multicol ──────────────────────────────────────────────────────────────
    "\\columnbreak", "\\newcolumn",
    "\\setlength{\\columnsep}{}", "\\setlength{\\columnseprule}{}",
    # ── Comandi di nuova definizione ──────────────────────────────────────────
    "\\newcommand{}{}", "\\newcommand[]{}{}", "\\renewcommand{}{}",
    "\\newenvironment{}{}{}", "\\renewenvironment{}{}{}",
    "\\DeclareMathOperator{}{}", "\\DeclareMathOperator*{}{}",
    "\\newtheorem{}{}", "\\newtheorem*{}{}",
    "\\theoremstyle{}", "\\qedhere",
    # ── TikZ ──────────────────────────────────────────────────────────────────
    "\\tikz{}", "\\tikzset{}", "\\usetikzlibrary{}",
    "\\draw", "\\fill", "\\filldraw", "\\shade", "\\shadedraw",
    "\\path", "\\node", "\\coordinate", "\\pic",
    "\\foreach", "\\clip",
    # ── Beamer ────────────────────────────────────────────────────────────────
    "\\frametitle{}", "\\framesubtitle{}", "\\pause",
    "\\only<>{}", "\\onslide<>{}", "\\visible<>{}",
    "\\uncover<>{}", "\\alert{}", "\\structure{}",
    "\\usetheme{}", "\\usecolortheme{}",
    "\\titlepage",
    # ── Algoritmi ─────────────────────────────────────────────────────────────
    "\\KwIn{}", "\\KwOut{}", "\\KwData{}", "\\KwResult{}",
    "\\KwTo", "\\KwRet{}", "\\Return{}",
    "\\If{}{}", "\\ElseIf{}{}", "\\Else{}",
    "\\For{}{}", "\\ForEach{}{}", "\\While{}{}",
    "\\Repeat{}{}", "\\Until{}", "\\SetAlgoLined",
    # Nota: i nomi dei pacchetti LaTeX (geometry, hyperref, multicol, …) NON vanno
    # qui: sono bare words senza '\' e matcherebbero qualsiasi prefisso dentro
    # \begin{…}, \end{…} e altri contesti errati.
    # Il completamento dopo \usepackage{ è gestito da _complete_packages() → showUserList.
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

# ─── Worker asincrono per il rebuild delle API ────────────────────────────────

class _ApiRebuildWorker(QThread):
    """Calcola i termini di autocompletamento in background per non bloccare la UI.
    L'I/O su disco (build_dynamic_api → multifile) e il parsing regex vengono
    eseguiti qui; solo api.prepare() rimane sul main thread."""

    done        = pyqtSignal(list)         # list[str] — termini autocomplete
    latex_cache = pyqtSignal(list, list, list)  # (label_pairs, bibtex_keys, hypertarget_names)

    def __init__(self, language: str, levels, text: str, file_path,
                 all_docs_words: list, generation: int):
        super().__init__(None)
        self._language       = language
        self._levels         = levels
        self._text           = text
        self._file_path      = file_path
        self._all_docs_words = all_docs_words
        self._gen            = generation
        self._cancelled      = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        terms: list[str] = []

        if self._levels & AutoCompleteLevel.API_DICT:
            terms.extend(_LANGUAGE_APIS.get(self._language, []))

        if self._cancelled:
            return

        if self._levels & AutoCompleteLevel.SNIPPETS:
            try:
                from editor.snippets import SnippetManager
                triggers = SnippetManager.instance().get_triggers(self._language)
                for trigger, description in triggers.items():
                    terms.append(f"{trigger}?5\n{description}")
            except Exception:
                pass

        if self._cancelled:
            return

        if self._levels & AutoCompleteLevel.ALL_DOCS:
            terms.extend(self._all_docs_words)

        if self._cancelled:
            return

        # I/O su disco — parte lenta (legge tutti i file \input{} collegati)
        if self._language in ("latex", "bibtex"):
            try:
                from editor.latex_support import LaTeXSupport
                dynamic = LaTeXSupport.build_dynamic_api(self._text, self._file_path)
                terms.extend(dynamic)
            except Exception:
                pass

        if self._cancelled:
            return

        # Per LaTeX: pre-calcola label/bibtex/hypertarget in background così i popup
        # su '{' sono istantanei (usano la cache invece di fare I/O sul main thread).
        if self._language == "latex":
            labels = bibtex = hypertargets = []
            try:
                from editor.latex_support import LaTeXSupport
                if self._file_path:
                    labels = LaTeXSupport.extract_labels_with_context_multifile(self._file_path)
                else:
                    labels = LaTeXSupport.extract_labels_with_context(self._text)
            except Exception:
                pass
            if not self._cancelled:
                try:
                    from editor.latex_support import LaTeXSupport
                    if self._file_path:
                        bibtex = LaTeXSupport.extract_bibtex_keys_multifile(self._file_path)
                    else:
                        bibtex = LaTeXSupport.extract_bibtex_keys(self._text, None)
                except Exception:
                    pass
            if not self._cancelled:
                try:
                    from editor.latex_support import LaTeXSupport
                    if self._file_path:
                        hypertargets = LaTeXSupport.extract_hypertargets_multifile(self._file_path)
                    else:
                        hypertargets = LaTeXSupport.extract_hypertargets(self._text)
                except Exception:
                    pass
            if not self._cancelled:
                self.latex_cache.emit(labels, bibtex, hypertargets)

        if not self._cancelled:
            self.done.emit(terms)


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

        self._api_worker: Optional[_ApiRebuildWorker] = None
        self._old_api_workers: list = []
        self._api_gen: int = 0

        # Cache label/bibtex/hypertarget precalcolate in background dal worker.
        # Usate dai popup '{' per evitare I/O sincrono su Dropbox.
        self._labels_cache:      list = []
        self._bibtex_cache:      list = []
        self._hypertargets_cache: list = []
        self._env_cache:         list = []   # cache ambienti per refresh_env_popup
        self._env_popup_needs_brace: bool = False  # True se il popup e' partito da \begin/\end senza { ancora digitata

        # Timer per aggiornamento cross-tab (evita refresh ad ogni keystroke)
        self._cross_tab_timer = QTimer(self)
        self._cross_tab_timer.setSingleShot(True)
        self._cross_tab_timer.setInterval(1500)
        self._cross_tab_timer.timeout.connect(self._rebuild_all_docs_words)

        # Timer per rebuild API su modifica documento LaTeX
        self._doc_change_timer = QTimer(self)
        self._doc_change_timer.setSingleShot(True)
        self._doc_change_timer.setInterval(2000)
        self._doc_change_timer.timeout.connect(self._rebuild_api)

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
            if self._language in ("latex", "bibtex"):
                # Per LaTeX usa solo la lista API: i comandi custom sono già
                # estratti da build_dynamic_api e aggiunti all'API list.
                # AcsAll includerebbe anche le parole del documento (nomi propri,
                # numeri, parole italiane) generando suggerimenti non-LaTeX.
                ed.setAutoCompletionSource(
                    QsciScintilla.AutoCompletionSource.AcsAPIs
                )
            else:
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
        # Per LaTeX, \ deve essere un word-character in modo che \label{},
        # \pageref{} ecc. vengano abbinati quando si digita \la…, \pa…
        # (senza questa impostazione \ non è word-char e le voci API con \cmd{}
        # non vengono mai proposte dall'autocomplete)
        from PyQt6.Qsci import QsciScintilla as _QSci
        if self._language in ("latex", "bibtex"):
            self._editor.SendScintilla(
                _QSci.SCI_SETWORDCHARS,
                b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_\\"
            )
        else:
            self._editor.SendScintilla(
                _QSci.SCI_SETWORDCHARS,
                b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
            )
        self._editor.setAutoCompletionWordSeparators([])
        # Per LaTeX/BibTeX: carica subito l'API statica (735 comandi in memoria)
        # senza aspettare il worker I/O. L'API dinamica (comandi custom, pacchetti)
        # viene aggiunta quando il worker asincrono finisce.
        if self._language in ("latex", "bibtex"):
            self._load_static_api_now()
            # LaTeX: rebuild più raro (I/O Dropbox pesante) — cache label/bibtex inclusa
            self._doc_change_timer.setInterval(3000)
            # Invalida la cache del cambio linguaggio precedente
            self._labels_cache = []
            self._bibtex_cache = []
            self._hypertargets_cache = []
        else:
            self._doc_change_timer.setInterval(2000)
        # Aggiorna subito la sorgente QScintilla (AcsAPIs per LaTeX, AcsAll per gli altri).
        # _setup_base() imposta AcsAll come default; senza questa chiamata la sorgente
        # resterebe AcsAll anche per LaTeX, causando la comparsa di parole del documento.
        self._apply_levels()
        self._rebuild_api()

    def _load_static_api_now(self) -> None:
        """Carica immediatamente l'API statica del linguaggio corrente sul main thread.
        Usato per LaTeX/BibTeX: rende disponibili i 735 comandi istantaneamente,
        senza aspettare che il worker asincrono finisca il I/O su disco."""
        lexer = self._editor.lexer()
        if lexer is None:
            return
        terms: list[str] = list(_LANGUAGE_APIS.get(self._language, []))
        try:
            from editor.snippets import SnippetManager
            triggers = SnippetManager.instance().get_triggers(self._language)
            for trigger, description in triggers.items():
                terms.append(f"{trigger}?5\n{description}")
        except Exception:
            pass
        if not terms:
            return
        api = QsciAPIs(lexer)
        for term in terms:
            api.add(term)
        api.prepare()
        lexer.setAPIs(api)
        self._api = api

    def _rebuild_api(self) -> None:
        """Avvia un worker asincrono per ricostruire le API di autocompletamento.
        Snapshot di testo e parole cross-tab presi qui sul main thread;
        il parsing I/O (build_dynamic_api) gira in background."""
        lexer = self._editor.lexer()
        if lexer is None:
            QTimer.singleShot(100, self._rebuild_api)
            return

        # Elimina worker precedenti non più in esecuzione
        self._old_api_workers[:] = [
            w for w in self._old_api_workers if w.isRunning()
        ]

        # Snapshot sul main thread (QScintilla non è thread-safe)
        text = self._editor.text()
        fp   = getattr(self._editor, "file_path", None)
        all_docs_words = self._collect_all_docs_words()

        if self._api_worker is not None:
            self._api_worker.cancel()
            self._old_api_workers.append(self._api_worker)
            self._api_worker = None

        self._api_gen += 1
        gen    = self._api_gen
        worker = _ApiRebuildWorker(
            self._language, self._levels, text, fp, all_docs_words, gen
        )
        worker.done.connect(lambda terms, g=gen: self._on_api_ready(terms, g))
        worker.latex_cache.connect(
            lambda lbl, bib, ht, g=gen: self._on_latex_cache(lbl, bib, ht, g)
        )
        self._api_worker = worker
        self._old_api_workers.append(worker)
        worker.start()

    def _on_api_ready(self, terms: list, gen: int) -> None:
        """Chiamato dal worker quando i termini sono pronti. Esegue solo le
        operazioni Qt (add + prepare) che devono stare sul main thread."""
        if gen != self._api_gen:
            return
        self._api_worker = None
        lexer = self._editor.lexer()
        if lexer is None:
            return
        api = QsciAPIs(lexer)
        for term in terms:
            api.add(term)
        api.prepare()
        lexer.setAPIs(api)
        self._api = api

    def _on_latex_cache(self, labels: list, bibtex: list, hypertargets: list, gen: int) -> None:
        """Aggiorna la cache label/bibtex/hypertarget precalcolata dal worker."""
        if gen != self._api_gen:
            return
        self._labels_cache       = labels
        self._bibtex_cache       = bibtex
        self._hypertargets_cache = hypertargets

    def _collect_all_docs_words(self) -> list:
        """Estrae le parole da tutti gli altri tab (main thread, snapshot)."""
        if not (self._levels & AutoCompleteLevel.ALL_DOCS) or not self._tab_manager_ref:
            return []
        seen:  set[str]  = set()
        words: list[str] = []
        for editor in self._tab_manager_ref.all_editors():
            if editor is self._editor:
                continue
            for w in re.findall(r'\b[a-zA-Z_]\w{2,}\b', editor.text()):
                if w not in seen:
                    seen.add(w)
                    words.append(w)
        return words

    # ── Cross-tab ─────────────────────────────────────────────────────────────

    def set_tab_manager(self, tab_manager) -> None:
        """Collega il tab manager per il completamento cross-documento."""
        self._tab_manager_ref = tab_manager
        if self._tab_manager_ref:
            self._editor.textChanged.connect(self._cross_tab_timer.start)

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
        Completamenti contestuali dopo '{': label, cite, ambienti, file, pacchetti.
        Restituisce True se ha gestito il carattere.
        """
        if self._language != "latex" or char != "{":
            return False

        ed = self._editor
        line, col = ed.getCursorPosition()
        line_text = ed.text(line)[:col]

        match = re.search(r'\\(\w+)\{$', line_text)
        if not match:
            return False

        cmd = match.group(1)

        if cmd in ("ref", "eqref", "pageref", "autoref",
                   "cref", "Cref", "crefrange",
                   "nameref", "namecrefs", "lcnamecref",
                   "vref", "vpageref", "cpageref", "labelcref"):
            self._complete_labels()
            return True
        elif cmd == "hyperref":
            # \hyperref[label]{text} — il label va fra [ ], non { }
            # ma intercettiamo anche \hyperref{ come fallback
            self._complete_labels()
            return True
        elif cmd in ("hyperlink",):
            self._complete_hypertargets()
            return True
        elif cmd in ("hypertarget",):
            # mostra i target esistenti per evitare duplicati
            self._complete_hypertargets()
            return True
        elif cmd in ("cite", "citep", "citet", "citeauthor", "citeyear",
                     "parencite", "footcite", "textcite", "autocite",
                     "fullcite", "citetitle", "citealt", "citealp",
                     "footfullcite", "citenum"):
            self._complete_cite_keys()
            return True
        elif cmd in ("begin", "end"):
            self._complete_environments(is_end=(cmd == "end"))
            return True
        elif cmd in ("input", "include", "subfile", "subinputfrom",
                     "includefrom", "subimport"):
            self._complete_file_paths("tex")
            return True
        elif cmd == "includegraphics":
            self._complete_file_paths("includegraphics")
            return True
        elif cmd in ("includesvg", "includeinkscape"):
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
        elif cmd in ("usetheme", "usecolortheme", "useinnertheme",
                     "useoutertheme", "usefonttheme"):
            self._complete_beamer_themes(cmd)
            return True
        elif cmd in ("newtheorem", "newtheorem*"):
            pass  # lasciamo al completamento standard
        elif cmd in ("gls", "Gls", "GLS", "glspl", "acrlong", "acrshort", "ac",
                     "acl", "acs", "acf"):
            pass  # glossary/acronym completamento futuro

        return False

    def handle_latex_option(self, bracket: str) -> bool:
        """
        Completamento contestuale dopo '[': suggerisce opzioni valide per
        il comando o ambiente che precede la parentesi.
        Restituisce True se ha gestito il carattere.
        """
        if self._language != "latex" or bracket != "[":
            return False

        ed = self._editor
        line, col = ed.getCursorPosition()
        line_text = ed.text(line)[:col]

        # \\hyperref[  →  label del progetto (il label di hyperref è fra [ ])
        if re.search(r'\\hyperref\[$', line_text):
            self._complete_labels()
            return True

        # \\begin{env}[  →  opzioni ambiente
        m = re.search(r'\\begin\{([^}]+)\}\[$', line_text)
        if m:
            options = self._get_environment_options(m.group(1))
            if options:
                self._editor.showUserList(10, options)
                return True

        # \\usepackage[  →  opzioni pacchetto (cerca il nome dopo)
        m_pkg_bracket = re.search(r'\\usepackage\[$', line_text)
        if m_pkg_bracket:
            # Tenta di leggere il nome del pacchetto dalla riga completa
            rest = ed.text(line)[col:]
            m_pkg_name = re.search(r'^\s*\{([^}]+)\}', rest)
            if m_pkg_name:
                options = self._get_package_options(m_pkg_name.group(1))
                if options:
                    self._editor.showUserList(11, options)
                    return True

        # \\includegraphics[
        if re.search(r'\\includegraphics\[$', line_text):
            from editor.latex_support import COMMAND_OPTIONS
            opts = COMMAND_OPTIONS.get("includegraphics", [])
            if opts:
                self._editor.showUserList(10, opts)
                return True

        # \\documentclass[
        if re.search(r'\\documentclass\[$', line_text):
            from editor.latex_support import COMMAND_OPTIONS
            opts = COMMAND_OPTIONS.get("documentclass", [])
            if opts:
                self._editor.showUserList(10, opts)
                return True

        # \\lstset[ o \\begin{lstlisting}[
        if re.search(r'(?:\\lstset|\\begin\{lstlisting\})\[$', line_text):
            from editor.latex_support import COMMAND_OPTIONS
            opts = COMMAND_OPTIONS.get("lstlisting", [])
            if opts:
                self._editor.showUserList(10, opts)
                return True

        # \\usetheme[ , \\usecolortheme[  etc
        m_theme = re.search(r'\\(usetheme|usecolortheme|useinnertheme|useoutertheme)\[$', line_text)
        if m_theme:
            from editor.latex_support import COMMAND_OPTIONS
            opts = COMMAND_OPTIONS.get(m_theme.group(1), [])
            if opts:
                self._editor.showUserList(10, opts)
                return True

        # Comando generico \\cmd[
        m_cmd = re.search(r'\\(\w+)\[$', line_text)
        if m_cmd:
            from editor.latex_support import COMMAND_OPTIONS
            opts = COMMAND_OPTIONS.get(m_cmd.group(1), [])
            if opts:
                self._editor.showUserList(10, opts)
                return True

        return False

    def _get_environment_options(self, env: str) -> list[str]:
        try:
            from editor.latex_support import ENVIRONMENT_OPTIONS
            return ENVIRONMENT_OPTIONS.get(env, [])
        except Exception:
            return []

    def _get_package_options(self, pkg: str) -> list[str]:
        try:
            from editor.latex_support import PACKAGE_OPTIONS
            return PACKAGE_OPTIONS.get(pkg.strip().lower(), [])
        except Exception:
            return []

    def _complete_labels(self) -> None:
        """Popup con tutte le \\label{} del progetto con tipo rilevato.
        Usa la cache precalcolata dal worker in background (nessun I/O sul main thread)."""
        pairs = self._labels_cache
        if pairs:
            items = [f"{key}  [{hint}]" if hint and hint != "label" else key
                     for key, hint in pairs]
            self._editor.showUserList(5, sorted(items))

    def _complete_hypertargets(self) -> None:
        """Popup con i nomi \\hypertarget definiti nel progetto (da cache background)."""
        names = self._hypertargets_cache
        if names:
            self._editor.showUserList(6, names)

    def _complete_cite_keys(self) -> None:
        """Popup con le chiavi BibTeX (da cache background, nessun I/O sul main thread)."""
        keys = self._bibtex_cache
        if keys:
            self._editor.showUserList(2, keys)

    def _complete_beamer_themes(self, cmd: str) -> None:
        """Popup con i temi beamer disponibili."""
        from editor.latex_support import COMMAND_OPTIONS
        themes = COMMAND_OPTIONS.get(cmd, [])
        if themes:
            self._editor.showUserList(9, themes)

    def complete_environments_from_word(self, is_end: bool) -> None:
        """
        Mostra subito il popup ambienti non appena la parola dopo \\ è un
        prefisso di "begin"/"end" (es. \\beg), prima ancora di finire di
        scrivere la parola e la {. Cancella l'eventuale popup nativo QsciAPIs
        (ordinato alfabeticamente) per non sovrapporlo. Chiamato ad ogni
        lettera finché la parola resta un prefisso valido — vedi
        cancel_env_word_popup per la chiusura quando diverge.
        """
        try:
            from PyQt6.Qsci import QsciScintilla as _QSci
            self._editor.SendScintilla(_QSci.SCI_AUTOCCANCEL)
        except Exception:
            pass
        self._complete_environments(is_end=is_end, needs_brace=True)

    def cancel_env_word_popup(self) -> None:
        """
        Chiude il popup ambienti aperto da complete_environments_from_word
        se la parola digitata non è più un prefisso di begin/end (es.
        \\begingroup, \\begins) — non tocca il testo, no-op se non era aperto.
        """
        if not self._env_popup_needs_brace:
            return
        self._env_popup_needs_brace = False
        try:
            from PyQt6.Qsci import QsciScintilla as _QSci
            self._editor.SendScintilla(_QSci.SCI_AUTOCCANCEL)
        except Exception:
            pass

    def _complete_environments(self, is_end: bool = False, needs_brace: bool = False) -> None:
        """Popup con tutti gli ambienti LaTeX: standard + custom del documento."""
        self._env_popup_needs_brace = needs_brace
        try:
            from editor.latex_support import LaTeXSupport
            envs = LaTeXSupport.get_all_environments(self._editor.text())
        except Exception:
            from editor.latex_support import STANDARD_ENVIRONMENTS
            envs = STANDARD_ENVIRONMENTS

        if is_end:
            # \end{: propone prima gli ambienti ancora aperti (il più interno
            # per primo, es. multicols, small, center...), poi il resto come fallback.
            from editor.latex_support import LaTeXSupport
            line, col = self._editor.getCursorPosition()
            open_envs = LaTeXSupport.find_open_environments(self._editor.text(), line, col)
            seen = set()
            open_envs = [e for e in open_envs if not (e in seen or seen.add(e))]
            rest = [e for e in sorted(set(envs)) if e not in seen]
            self._env_cache = open_envs + rest   # usato da refresh_env_popup
        else:
            # Ambienti già usati (alfabetico) in cima, poi tutti gli altri (alfabetico)
            self._env_cache = LaTeXSupport.sort_environments_by_usage(envs)   # usato da refresh_env_popup
        self._editor.showUserList(3, self._env_cache)

    def refresh_env_popup(self, prefix: str) -> None:
        """Aggiorna il popup ambienti filtrando per prefix (chiamato su ogni keystroke)."""
        if not self._env_cache:
            return
        lp = prefix.lower()
        filtered = [e for e in self._env_cache if e.lower().startswith(lp)]
        if filtered:
            self._editor.showUserList(3, filtered)
        else:
            try:
                from PyQt6.Qsci import QsciScintilla as _QSci
                self._editor.SendScintilla(_QSci.SCI_AUTOCCANCEL)
            except Exception:
                pass

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
            "multirow", "multicol", "array", "dcolumn", "hhline",
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

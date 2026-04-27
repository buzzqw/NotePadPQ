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
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget


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
    "supertabular", "sidewaystable", "sidewaysfigure",
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
    "mathtools": [
        "\\coloneqq", "\\Coloneqq", "\\eqqcolon",
        "\\prescript{}{}{}", "\\mathclap{}", "\\mathllap{}", "\\mathrlap{}",
        "\\smashoperator{}", "\\adjustlimits{}{}",
        "\\shortintertext{}",
        "\\begin{pmatrix*}", "\\begin{bmatrix*}", "\\begin{vmatrix*}",
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
    "multicols":      [],
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
        # Disconnetti eventuali connessioni precedenti
        try:
            editor.SCN_CHARADDED.disconnect(LaTeXSupport._on_char_added)
        except Exception:
            pass

        editor.SCN_CHARADDED.connect(
            lambda char: LaTeXSupport._on_char_added(editor, char)
        )

    @staticmethod
    def _on_char_added(editor: "EditorWidget", char_int: int) -> None:
        """Gestisce i caratteri speciali LaTeX."""
        char = chr(char_int)

        if char == "\n":
            LaTeXSupport._handle_newline(editor)
        elif char == "{":
            LaTeXSupport._handle_open_brace(editor)
        elif char == "[":
            LaTeXSupport._handle_open_bracket(editor)
        elif char == "$":
            LaTeXSupport._handle_dollar(editor)
        elif char == "\\":
            pass  # il completamento parte dall'autocomplete standard

    @staticmethod
    def _handle_newline(editor: "EditorWidget") -> None:
        """
        Su invio dopo \\begin{env}: inserisce automaticamente \\end{env}.
        Funziona per QUALSIASI ambiente, come TeXstudio.
        """
        line, col = editor.getCursorPosition()
        if line < 1:
            return
        prev_line = editor.text(line - 1)

        # Cerca \begin{qualcosa} sulla riga precedente
        m = re.search(r'\\begin\{([^}]+)\}', prev_line)
        if not m:
            return
        env = m.group(1)

        # Calcola indentazione della riga precedente
        indent = len(prev_line) - len(prev_line.lstrip())
        indent_str = prev_line[:indent]

        # Inserisce una riga vuota indentata + \end{env}
        # Il cursore si posiziona sulla riga vuota (dentro l'ambiente)
        current_line_text = editor.text(line)

        end_cmd = f"{indent_str}\\end{{{env}}}"

        # Se la riga corrente è vuota o solo spazi, inserisci \end dopo
        if not current_line_text.strip():
            editor.beginUndoAction()
            # Posizionati alla fine della riga corrente
            editor.setCursorPosition(line, len(current_line_text.rstrip("\n")))
            inner_indent = indent_str + "    "
            # Inserisci indentazione interna sulla riga corrente
            if not current_line_text.strip():
                editor.insert(inner_indent.lstrip(indent_str) if indent_str else "    ")
            # Inserisci una nuova riga con \end{env}
            editor.insert(f"\n{end_cmd}")
            # Torna alla riga interna
            editor.setCursorPosition(line, len(inner_indent))
            editor.endUndoAction()

    @staticmethod
    def _handle_open_brace(editor: "EditorWidget") -> None:
        """
        Dopo '{': controlla il comando precedente e
        attiva completamento contestuale via autocomplete.
        """
        ac = getattr(editor, "_autocomplete", None)
        if ac:
            ac.handle_latex_special("{")

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
        line, col = editor.getCursorPosition()
        line_text = editor.text(line)

        # Conta i $ nella riga per determinare se siamo in math mode
        # (euristica semplice: se dispari, inserisci il chiusura)
        dollar_count = line_text[:col - 1].count("$") - line_text[:col - 1].count("\\$")
        # Se è un $ di apertura (conta pari prima di questo)
        if dollar_count % 2 == 0:
            # Inserisci $ di chiusura e riposiziona cursore
            editor.beginUndoAction()
            editor.insert("$")
            editor.setCursorPosition(line, col)
            editor.endUndoAction()

    # ── Estrazione struttura documento ───────────────────────────────────────

    @staticmethod
    def extract_labels(text: str) -> list[str]:
        """Estrae tutte le \\label{} dal documento."""
        return sorted(set(re.findall(r'\\label\{([^}]+)\}', text)))

    @staticmethod
    def extract_bibtex_keys(text: str,
                             tex_path: Optional[Path] = None) -> list[str]:
        """
        Estrae le chiavi BibTeX dai file .bib referenziati con
        \\bibliography{} o \\addbibresource{}.
        """
        keys: list[str] = []

        # Trova i file .bib referenziati
        bib_files: list[str] = []
        for m in re.finditer(
            r'\\(?:bibliography|addbibresource)\{([^}]+)\}', text
        ):
            for f in m.group(1).split(","):
                bib_files.append(f.strip())

        if not bib_files or tex_path is None:
            return keys

        base_dir = tex_path.parent
        for bib_name in bib_files:
            if not bib_name.endswith(".bib"):
                bib_name += ".bib"
            bib_path = base_dir / bib_name
            if bib_path.exists():
                try:
                    bib_text = bib_path.read_text(encoding="utf-8", errors="replace")
                    keys.extend(re.findall(r'@\w+\{([^,\s]+)\s*,', bib_text))
                except Exception:
                    pass

        return sorted(set(keys))

    @staticmethod
    def extract_custom_commands(text: str) -> list[str]:
        """
        Estrae i comandi definiti con \\newcommand, \\renewcommand,
        \\DeclareMathOperator nel documento.
        """
        cmds: list[str] = []
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
    def extract_custom_environments(text: str) -> list[str]:
        """Estrae gli ambienti definiti con \\newenvironment."""
        return sorted(set(re.findall(
            r'\\(?:new|renew)environment\*?\{([^}]+)\}', text
        )))

    @staticmethod
    def extract_used_packages(text: str) -> list[str]:
        """Estrae i pacchetti caricati con \\usepackage{}."""
        pkgs: list[str] = []
        for m in re.finditer(r'\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}', text):
            for p in m.group(1).split(","):
                pkgs.append(p.strip())
        return sorted(set(pkgs))

    @staticmethod
    def extract_sections(text: str) -> list[tuple[str, str, int]]:
        """
        Estrae la struttura del documento.
        Restituisce lista di (tipo, titolo, riga_0based).
        """
        sections: list[tuple[str, str, int]] = []
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
    def get_package_commands(packages: list[str]) -> list[str]:
        """
        Restituisce i comandi aggiuntivi per i pacchetti caricati.
        """
        cmds: list[str] = []
        for pkg in packages:
            pkg_cmds = PACKAGE_COMMANDS.get(pkg.lower(), [])
            cmds.extend(pkg_cmds)
        return cmds

    @staticmethod
    def get_all_environments(text: str) -> list[str]:
        """
        Restituisce tutti gli ambienti disponibili:
        standard + custom dal documento.
        """
        custom = LaTeXSupport.extract_custom_environments(text)
        return sorted(set(STANDARD_ENVIRONMENTS + custom))

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
        Trova ricorsivamente tutti i .tex inclusi via \\input{}, \\include{},
        \\subfile{} a partire dal file radice.
        """
        if not tex_path or not tex_path.exists():
            return []
        visited: set[Path] = set()
        result: list[Path] = []

        def _collect(path: Path, depth: int) -> None:
            if depth > max_depth or path in visited:
                return
            visited.add(path)
            result.append(path)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return
            for m in re.finditer(
                r'\\(?:input|include|subfile|subinputfrom)\*?\{([^}]+)\}', text
            ):
                ref = m.group(1).strip()
                if not ref.endswith(".tex"):
                    ref += ".tex"
                ref_path = (path.parent / ref).resolve()
                if ref_path.exists():
                    _collect(ref_path, depth + 1)

        _collect(tex_path, 0)
        return result

    @staticmethod
    def extract_labels_multifile(tex_path: Optional[Path]) -> list[str]:
        """Estrae tutte le \\label{} dall'intero progetto multi-file."""
        labels: list[str] = []
        for fpath in LaTeXSupport.collect_project_files(tex_path):
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
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
                text = fpath.read_text(encoding="utf-8", errors="replace")
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
                text = fpath.read_text(encoding="utf-8", errors="replace")
                cmds.extend(LaTeXSupport.extract_custom_commands(text))
            except Exception:
                pass
        return sorted(set(cmds))

    @staticmethod
    def build_dynamic_api(text: str,
                           tex_path: Optional[Path] = None) -> list[str]:
        """
        Costruisce la lista API dinamica dal documento e dal progetto:
        - Comandi custom (\\newcommand) da tutti i file collegati
        - Ambienti custom (\\newenvironment)
        - Comandi dai pacchetti caricati
        """
        api: list[str] = []

        # Comandi custom dal documento corrente + file inclusi
        if tex_path:
            all_cmds = LaTeXSupport.extract_custom_commands_multifile(tex_path)
        else:
            all_cmds = LaTeXSupport.extract_custom_commands(text)
        api.extend(all_cmds)

        # Ambienti custom
        for env in LaTeXSupport.extract_custom_environments(text):
            api.append(f"\\begin{{{env}}}")
            api.append(f"\\end{{{env}}}")

        # Comandi dai pacchetti
        packages = LaTeXSupport.extract_used_packages(text)
        api.extend(LaTeXSupport.get_package_commands(packages))

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
            # Rimuovi la parte commentata (% non escapata)
            stripped = re.sub(r'(?<!\\)%.*', '', line)

            for m in re.finditer(r'\\begin\{([^}]+)\}', stripped):
                stack.append((m.group(1), lineno))

            for m in re.finditer(r'\\end\{([^}]+)\}', stripped):
                env_name = m.group(1)
                if not stack:
                    errors.append({
                        "line": lineno, "env": env_name,
                        "msg": f"\\end{{{env_name}}} senza \\begin corrispondente",
                    })
                else:
                    top_env, top_line = stack[-1]
                    if top_env == env_name:
                        stack.pop()
                    else:
                        errors.append({
                            "line": lineno, "env": env_name,
                            "msg": (
                                f"\\end{{{env_name}}} chiude '{top_env}' "
                                f"aperto a riga {top_line + 1}"
                            ),
                        })
                        stack.pop()

        for env_name, lineno in stack:
            errors.append({
                "line": lineno, "env": env_name,
                "msg": f"\\begin{{{env_name}}} non chiuso",
            })

        return errors

    # ── Conteggio parole ─────────────────────────────────────────────────────

    @staticmethod
    def count_words(text: str) -> dict:
        """
        Conta parole (corpo documento, escluso preambolo e comandi LaTeX).
        Restituisce {words, chars, chars_nospace, lines, paragraphs}.
        """
        text_nc = re.sub(r'(?<!\\)%[^\n]*', '', text)
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
        Euristica: True se la posizione è all'interno di un ambiente matematico.
        """
        before = text[:pos]
        dollar_count = len(re.findall(r'(?<!\\)\$', before))
        if dollar_count % 2 == 1:
            return True
        math_envs = (
            "equation", "align", "gather", "multline",
            "math", "displaymath", "split", "cases",
            "alignat", "flalign", "subequations",
        )
        env_pat = r'\\begin\{(' + '|'.join(math_envs) + r'\*?)\}'
        end_pat = r'\\end\{('  + '|'.join(math_envs) + r'\*?)\}'
        opens  = len(re.findall(env_pat, before))
        closes = len(re.findall(end_pat, before))
        return opens > closes

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
    def build_dynamic_api(text: str,
                           tex_path: Optional[Path] = None) -> list[str]:
        """
        Costruisce la lista API dinamica dal documento corrente:
        - Comandi custom (\newcommand)
        - Ambienti custom (\newenvironment)
        - Comandi dai pacchetti caricati
        Usata da AutoCompleteManager._rebuild_api per arricchire il completamento.
        """
        api: list[str] = []

        # Comandi custom definiti nel documento
        for cmd in LaTeXSupport.extract_custom_commands(text):
            api.append(f"{cmd}")

        # Ambienti custom
        for env in LaTeXSupport.extract_custom_environments(text):
            api.append(f"\\begin{{{env}}}")
            api.append(f"\\end{{{env}}}")

        # Comandi dai pacchetti
        packages = LaTeXSupport.extract_used_packages(text)
        api.extend(LaTeXSupport.get_package_commands(packages))

        return api

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
            # Togli un livello se presente
            if len(prev_indent) >= 4:
                return prev_indent[:-4]
        return prev_indent

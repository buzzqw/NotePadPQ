"""
editor/latex_tooltips.py  –  Documentazione comandi LaTeX per hover tooltip.

Ogni voce: (firma, descrizione, pacchetto, esempio)
  firma       – sintassi completa con argomenti
  descrizione – 1-2 frasi sul comportamento
  pacchetto   – "LaTeX base" oppure nome pacchetto richiesto
  esempio     – riga d'uso concreta, oppure stringa vuota
"""

from __future__ import annotations

# tupla: (firma, descrizione, pacchetto, esempio)
LATEX_CMD_DOCS: dict[str, tuple[str, str, str, str]] = {

    # ── Struttura documento ───────────────────────────────────────────────────
    "documentclass": (
        r"\documentclass[opzioni]{classe}",
        "Dichiara la classe del documento. Le classi standard sono <b>article</b>, "
        "<b>report</b>, <b>book</b>, <b>letter</b>, <b>beamer</b>. "
        "Le opzioni più comuni sono la dimensione del font (10pt, 11pt, 12pt) e il formato carta.",
        "LaTeX base",
        r"\documentclass[12pt,a4paper]{article}",
    ),
    "usepackage": (
        r"\usepackage[opzioni]{pacchetto}",
        "Carica un pacchetto LaTeX nel preambolo. Più pacchetti possono essere "
        "elencati separati da virgola. Le opzioni variano per pacchetto.",
        "LaTeX base",
        r"\usepackage[utf8]{inputenc}",
    ),
    "begin": (
        r"\begin{ambiente}",
        "Apre un ambiente LaTeX. Deve essere chiuso con \\end{ambiente} "
        "corrispondente. Gli ambienti strutturano il contenuto (liste, figure, tabelle, matematica, ecc.).",
        "LaTeX base",
        r"\begin{itemize} ... \end{itemize}",
    ),
    "end": (
        r"\end{ambiente}",
        "Chiude l'ambiente aperto da \\begin{ambiente}. "
        "Ogni \\begin deve avere il corrispondente \\end con lo stesso nome.",
        "LaTeX base",
        r"\end{document}",
    ),
    "title": (
        r"\title{testo}",
        "Imposta il titolo del documento, usato da \\maketitle. "
        "Può contenere \\thanks{} per note a piè di pagina.",
        "LaTeX base",
        r"\title{Introduzione alla Fisica}",
    ),
    "author": (
        r"\author{nome}",
        "Imposta l'autore del documento, usato da \\maketitle. "
        "Più autori si separano con \\and; \\thanks{} aggiunge affiliazioni.",
        "LaTeX base",
        r"\author{Mario Rossi \and Luigi Verdi}",
    ),
    "date": (
        r"\date{data}",
        "Imposta la data del documento, usata da \\maketitle. "
        "Usa \\today per la data corrente, o stringa vuota {} per non mostrare la data.",
        "LaTeX base",
        r"\date{\today}",
    ),
    "maketitle": (
        r"\maketitle",
        "Genera il titolo con autore e data definiti da \\title, \\author, \\date. "
        "Nelle classi book/report crea una pagina separata; in article compone in linea.",
        "LaTeX base",
        r"\maketitle",
    ),
    "tableofcontents": (
        r"\tableofcontents",
        "Genera automaticamente l'indice con i titoli delle sezioni. "
        "Richiede due compilazioni per essere aggiornato.",
        "LaTeX base",
        r"\tableofcontents",
    ),
    "listoffigures": (
        r"\listoffigures",
        "Genera l'elenco delle figure con le relative didascalie. "
        "Richiede che le figure usino \\caption{} all'interno dell'ambiente figure.",
        "LaTeX base",
        r"\listoffigures",
    ),
    "listoftables": (
        r"\listoftables",
        "Genera l'elenco delle tabelle con le relative didascalie. "
        "Richiede che le tabelle usino \\caption{} all'interno dell'ambiente table.",
        "LaTeX base",
        r"\listoftables",
    ),
    "appendix": (
        r"\appendix",
        "Segna l'inizio della sezione appendici. I capitoli/sezioni successivi "
        "vengono numerati con lettere (A, B, C…) invece che con numeri.",
        "LaTeX base",
        r"\appendix  \chapter{Dati sperimentali}",
    ),
    "newpage": (
        r"\newpage",
        "Termina la pagina corrente e va a capo. Nelle classi a doppia colonna, "
        "termina la colonna corrente. Usa \\clearpage per forzare anche lo scarico delle figure in attesa.",
        "LaTeX base",
        r"\newpage",
    ),
    "clearpage": (
        r"\clearpage",
        "Termina la pagina corrente e forza la composizione di tutte le figure e tabelle "
        "in attesa (float) prima di continuare sulla nuova pagina.",
        "LaTeX base",
        r"\clearpage",
    ),
    "cleardoublepage": (
        r"\cleardoublepage",
        "Come \\clearpage ma assicura che il contenuto successivo inizi sempre su una "
        "pagina destra (dispari). Usato comunemente prima di nuovi capitoli nei libri.",
        "LaTeX base",
        r"\cleardoublepage",
    ),
    "input": (
        r"\input{file}",
        "Include il contenuto di un altro file .tex come se fosse inserito qui. "
        "Non può essere nidificato condizionalmente con \\includeonly. "
        "L'estensione .tex è opzionale.",
        "LaTeX base",
        r"\input{capitoli/introduzione}",
    ),
    "include": (
        r"\include{file}",
        "Include un file .tex con \\clearpage automatico prima e dopo. "
        "Compatibile con \\includeonly per compilazione parziale. "
        "Non ammette nidificazione di altri \\include.",
        "LaTeX base",
        r"\include{capitoli/cap1}",
    ),
    "includeonly": (
        r"\includeonly{file1,file2,...}",
        "Limita la compilazione ai soli file elencati tra quelli inclusi con \\include. "
        "I riferimenti cross-file rimangono corretti se i file .aux esistono.",
        "LaTeX base",
        r"\includeonly{cap1,cap2}",
    ),
    "subfile": (
        r"\subfile{file}",
        "Include un sottofile compilabile autonomamente. "
        "Richiede il pacchetto <b>subfiles</b>. Il file incluso usa \\documentclass[main]{subfiles}.",
        "subfiles",
        r"\subfile{cap1/capitolo1}",
    ),

    # ── Sezionamento ──────────────────────────────────────────────────────────
    "part": (
        r"\part[titolo breve]{titolo}",
        "Crea una divisione di primo livello (Parte I, II…). "
        "L'argomento opzionale appare nell'indice; quello obbligatorio nella pagina del titolo di parte.",
        "LaTeX base",
        r"\part{Fondamenti teorici}",
    ),
    "chapter": (
        r"\chapter[titolo breve]{titolo}",
        "Crea un capitolo (solo nelle classi book e report). "
        "La versione stellata \\chapter*{} non è numerata e non appare nell'indice.",
        "LaTeX base",
        r"\chapter{Introduzione}",
    ),
    "section": (
        r"\section[titolo breve]{titolo}",
        "Crea una sezione numerata. L'argomento opzionale è usato nell'indice e nelle intestazioni "
        "se è più corto del titolo completo. \\section*{} non è numerata.",
        "LaTeX base",
        r"\section{Metodi sperimentali}",
    ),
    "subsection": (
        r"\subsection[titolo breve]{titolo}",
        "Crea una sottosezione numerata. \\subsection*{} non è numerata e non appare nell'indice.",
        "LaTeX base",
        r"\subsection{Raccolta dati}",
    ),
    "subsubsection": (
        r"\subsubsection[titolo breve]{titolo}",
        "Crea una sotto-sottosezione. Non numerata per default in article; "
        "può essere abilitata con \\setcounter{secnumdepth}{3}.",
        "LaTeX base",
        r"\subsubsection{Analisi statistica}",
    ),
    "paragraph": (
        r"\paragraph{titolo}",
        "Crea un paragrafo con titolo inline non numerato (quarto livello). "
        "Il titolo appare in grassetto seguito dal testo sullo stesso rigo.",
        "LaTeX base",
        r"\paragraph{Osservazione.} Il risultato segue dalla teoria.",
    ),
    "subparagraph": (
        r"\subparagraph{titolo}",
        "Crea un sotto-paragrafo con titolo inline (quinto livello). "
        "Raramente usato; spesso si preferisce \\paragraph.",
        "LaTeX base",
        r"\subparagraph{Nota.}",
    ),

    # ── Cross-reference ───────────────────────────────────────────────────────
    "label": (
        r"\label{chiave}",
        "Associa un'etichetta alla posizione corrente (sezione, figura, tabella, equazione). "
        "Convenzione: fig:nome, tab:nome, eq:nome, sec:nome. "
        "Usata da \\ref, \\pageref, \\eqref.",
        "LaTeX base",
        r"\label{fig:schema_circuito}",
    ),
    "ref": (
        r"\ref{chiave}",
        "Produce il numero della sezione, figura, tabella o equazione etichettata "
        "con \\label{chiave}. Richiede due compilazioni per aggiornarsi.",
        "LaTeX base",
        r"come mostrato in figura~\ref{fig:schema}",
    ),
    "eqref": (
        r"\eqref{chiave}",
        "Come \\ref ma racchiude il numero tra parentesi: (3). "
        "Usato specificamente per i riferimenti a equazioni.",
        "amsmath",
        r"come in~\eqref{eq:energia}",
    ),
    "pageref": (
        r"\pageref{chiave}",
        "Produce il numero di pagina dove si trova il \\label{chiave} corrispondente.",
        "LaTeX base",
        r"vedi pagina~\pageref{tab:risultati}",
    ),
    "cite": (
        r"\cite[nota]{chiave}",
        "Inserisce una citazione bibliografica. La chiave corrisponde a una voce nel file .bib. "
        "L'argomento opzionale aggiunge una nota (es. numero di pagina).",
        "LaTeX base",
        r"\cite[p.~45]{knuth1984}",
    ),
    "citep": (
        r"\citep[prenota][postnota]{chiave}",
        "Citazione parentetica: produce (Autore, Anno). "
        "Richiede il pacchetto <b>natbib</b>.",
        "natbib",
        r"\citep{einstein1905}  →  (Einstein, 1905)",
    ),
    "citet": (
        r"\citet[postnota]{chiave}",
        "Citazione testuale: produce Autore (Anno). "
        "Richiede il pacchetto <b>natbib</b>.",
        "natbib",
        r"\citet{einstein1905}  →  Einstein (1905)",
    ),
    "parencite": (
        r"\parencite[prenota][postnota]{chiave}",
        "Citazione parentetica nel sistema biblatex: produce (Autore, Anno). "
        "Richiede il pacchetto <b>biblatex</b>.",
        "biblatex",
        r"\parencite[p.~12]{autore2020}",
    ),
    "textcite": (
        r"\textcite[postnota]{chiave}",
        "Citazione testuale nel sistema biblatex: Autore (Anno). "
        "Richiede il pacchetto <b>biblatex</b>.",
        "biblatex",
        r"\textcite{autore2020} dimostra che…",
    ),
    "autocite": (
        r"\autocite[postnota]{chiave}",
        "Citazione automatica che si adatta allo stile biblatex attivo (numerica, autore-anno, ecc.). "
        "Richiede il pacchetto <b>biblatex</b>.",
        "biblatex",
        r"\autocite{autore2020}",
    ),
    "footnote": (
        r"\footnote[numero]{testo}",
        "Inserisce una nota a piè di pagina. Il numero è opzionale (assegnato automaticamente). "
        "Non usabile all'interno di minipage o tabular senza \\footnotemark/\\footnotetext.",
        "LaTeX base",
        r"\footnote{Questo risultato è stato dimostrato da Gauss nel 1801.}",
    ),
    "footnotemark": (
        r"\footnotemark[numero]",
        "Inserisce solo il marcatore della nota a piè di pagina (il numero superscript) "
        "senza il testo. Il testo va inserito con \\footnotetext{}.",
        "LaTeX base",
        r"\footnotemark  ... \footnotetext{Testo nota.}",
    ),
    "footnotetext": (
        r"\footnotetext[numero]{testo}",
        "Inserisce il testo della nota corrispondente a \\footnotemark. "
        "Utile all'interno di minipage o tabular.",
        "LaTeX base",
        r"\footnotetext{Dati ricavati da misure dirette.}",
    ),
    "marginpar": (
        r"\marginpar[testo sinistra]{testo}",
        "Inserisce una nota marginale. In documenti fronte-retro l'argomento opzionale "
        "appare nel margine sinistro, quello obbligatorio in quello destro.",
        "LaTeX base",
        r"\marginpar{Vedi appendice A}",
    ),
    "hyperref": (
        r"\hyperref[chiave]{testo}",
        "Crea un collegamento interno al \\label{chiave} mostrando il testo indicato. "
        "A differenza di \\ref, il testo è libero. Richiede il pacchetto <b>hyperref</b>.",
        "hyperref",
        r"\hyperref[sec:metodi]{la sezione metodologica}",
    ),
    "href": (
        r"\href{URL}{testo}",
        "Crea un collegamento ipertestuale esterno con il testo indicato come etichetta. "
        "Richiede il pacchetto <b>hyperref</b>.",
        "hyperref",
        r'\href{https://ctan.org}{CTAN}',
    ),
    "url": (
        r"\url{URL}",
        "Compone un URL in font monospaziato e lo rende cliccabile se è caricato il pacchetto "
        "<b>hyperref</b>. Gestisce automaticamente gli a-capo negli URL lunghi.",
        "hyperref",
        r"\url{https://www.latex-project.org}",
    ),
    "hypertarget": (
        r"\hypertarget{nome}{testo}",
        "Crea una destinazione (anchor) interna identificata da <i>nome</i>. "
        "Il <i>testo</i> viene composto normalmente. "
        "Usato con \\hyperlink per navigazione interna senza \\label. "
        "Richiede il pacchetto <b>hyperref</b>.",
        "hyperref",
        r"\hypertarget{appendice-a}{Appendice A}",
    ),
    "hyperlink": (
        r"\hyperlink{nome}{testo}",
        "Crea un link interno verso la destinazione definita da \\hypertarget{nome}{}. "
        "Il testo del link è completamente libero. "
        "Richiede il pacchetto <b>hyperref</b>.",
        "hyperref",
        r"\hyperlink{appendice-a}{vai all'Appendice A}",
    ),
    "autoref": (
        r"\autoref{chiave}",
        "Produce un riferimento completo con il nome dell'oggetto automaticamente "
        "(es. «Figura 3», «Sezione 2.1»). Richiede il pacchetto <b>hyperref</b>.",
        "hyperref",
        r"\autoref{fig:risultati}  →  Figura 3",
    ),
    "nameref": (
        r"\nameref{chiave}",
        "Produce il titolo della sezione, figura o tabella etichettata con \\label{chiave}, "
        "invece del numero. Richiede il pacchetto <b>hyperref</b>.",
        "hyperref",
        r"\nameref{sec:metodi}  →  «Metodi sperimentali»",
    ),
    "cref": (
        r"\cref{chiave}",
        "Riferimento intelligente che aggiunge automaticamente il nome del tipo "
        "(Figura, Tabella, Equazione…). Richiede il pacchetto <b>cleveref</b>. "
        "\\Cref produce la versione con iniziale maiuscola.",
        "cleveref",
        r"\cref{fig:mappa,tab:dati}  →  figure 1 e 2",
    ),
    "vref": (
        r"\vref{chiave}",
        "Come \\ref ma aggiunge automaticamente il riferimento alla pagina "
        "quando l'oggetto non è sulla stessa pagina (es. «figura 3 a pagina 12»). "
        "Richiede il pacchetto <b>varioref</b>.",
        "varioref",
        r"\vref{fig:schema}",
    ),
    "nolinkurl": (
        r"\nolinkurl{URL}",
        "Come \\url ma non crea un collegamento cliccabile. "
        "Utile quando si vuole mostrare l'URL in monospaziato senza che sia attivo.",
        "hyperref",
        r"\nolinkurl{https://esempio.it}",
    ),
    "index": (
        r"\index{voce}",
        "Aggiunge una voce all'indice analitico. Sintassi avanzata: "
        "\\index{voce!sottovoce} per gerarchie, \\index{chiave@testo} per ordinamento personalizzato. "
        "Richiede makeindex o xindy.",
        "LaTeX base",
        r"\index{equazione!differenziale}",
    ),

    # ── Formattazione testo ───────────────────────────────────────────────────
    "textbf": (
        r"\textbf{testo}",
        "Compone il testo in <b>grassetto</b>. "
        "Per uso semantico preferire \\bfseries o \\textbf limitato all'interno di un gruppo.",
        "LaTeX base",
        r"\textbf{Attenzione:} controllare i valori.",
    ),
    "textit": (
        r"\textit{testo}",
        "Compone il testo in <i>corsivo</i>. "
        "Differisce da \\emph: \\textit applica sempre il corsivo, \\emph lo toglie se già presente.",
        "LaTeX base",
        r"\textit{Homo sapiens}",
    ),
    "texttt": (
        r"\texttt{testo}",
        "Compone il testo in <tt>font monospaziato</tt> (typewriter). "
        "Usato per codice inline, nomi di file e comandi.",
        "LaTeX base",
        r"Il file \texttt{main.tex} è il punto di ingresso.",
    ),
    "textrm": (
        r"\textrm{testo}",
        "Compone il testo in font romano (serif), indipendentemente dal font corrente. "
        "Utile per ripristinare il font normale all'interno di ambienti math o sans-serif.",
        "LaTeX base",
        r"\textrm{valore}",
    ),
    "textsf": (
        r"\textsf{testo}",
        "Compone il testo in font sans-serif. "
        "Comunemente usato per intestazioni, nomi di software e titoli.",
        "LaTeX base",
        r"\textsf{NotePadPQ}",
    ),
    "emph": (
        r"\emph{testo}",
        "Enfatizza il testo: applica il corsivo se il testo circostante è in roman, "
        "oppure il roman se il testo circostante è già in corsivo. "
        "Semanticamente preferibile a \\textit.",
        "LaTeX base",
        r"Il concetto di \emph{entropia} è fondamentale.",
    ),
    "underline": (
        r"\underline{testo}",
        "Sottolinea il testo. Non va a capo automaticamente sulle righe multiple; "
        "per testo lungo usare \\uline{} del pacchetto <b>ulem</b>.",
        "LaTeX base",
        r"\underline{termine importante}",
    ),
    "textsc": (
        r"\textsc{testo}",
        "Compone il testo in <span style='font-variant:small-caps'>MAIUSCOLETTO</span> (small caps). "
        "Usato per nomi propri, acronimi, sigle.",
        "LaTeX base",
        r"\textsc{NASA}, \textsc{Lngs}",
    ),
    "textsl": (
        r"\textsl{testo}",
        "Compone il testo in font inclinato (slanted). Differisce dal corsivo: "
        "è una versione obliqua del font normale, non un vero italico.",
        "LaTeX base",
        r"\textsl{nota a margine}",
    ),
    "textnormal": (
        r"\textnormal{testo}",
        "Ripristina il font di default del documento, indipendentemente da qualsiasi "
        "dichiarazione di font circostante. Equivale a {\\normalfont testo}.",
        "LaTeX base",
        r"\textnormal{testo normale}",
    ),
    "mbox": (
        r"\mbox{testo}",
        "Produce una scatola orizzontale non separabile: il testo al suo interno "
        "non verrà mai spezzato a fine riga. Usato per abbreviazioni e unità di misura.",
        "LaTeX base",
        r"temperatura di \mbox{300 K}",
    ),
    "fbox": (
        r"\fbox{testo}",
        "Come \\mbox ma disegna un bordo rettangolare attorno al testo. "
        "Per controllare margine e spessore usare \\fboxsep e \\fboxrule.",
        "LaTeX base",
        r"\fbox{testo incorniciato}",
    ),
    "parbox": (
        r"\parbox[pos]{larghezza}{testo}",
        "Crea una mini-pagina di testo a larghezza fissa in modalità testo (non float). "
        "La posizione verticale può essere t (top), b (bottom) o c (center).",
        "LaTeX base",
        r"\parbox[t]{5cm}{Testo su più righe in un box.}",
    ),
    "raisebox": (
        r"\raisebox{sollevamento}[altezza][profondità]{testo}",
        "Sposta il testo verticalmente di <i>sollevamento</i> rispetto alla linea base. "
        "Valori positivi alzano, negativi abbassano.",
        "LaTeX base",
        r"\raisebox{2pt}{$^{(*)}$}",
    ),
    "phantom": (
        r"\phantom{testo}",
        "Riserva lo spazio orizzontale e verticale come se il testo fosse presente, "
        "ma non lo stampa. Usato per allineamenti in formule e tabelle.",
        "LaTeX base",
        r"\phantom{x+y}",
    ),
    "hphantom": (
        r"\hphantom{testo}",
        "Riserva solo lo spazio orizzontale (larghezza) del testo, "
        "senza occupare spazio verticale.",
        "LaTeX base",
        r"\hphantom{=}",
    ),
    "vphantom": (
        r"\vphantom{testo}",
        "Riserva solo lo spazio verticale (altezza + profondità) del testo, "
        "senza occupare spazio orizzontale.",
        "LaTeX base",
        r"\vphantom{A}",
    ),
    "uppercase": (
        r"\uppercase{testo}",
        "Converte il testo in maiuscolo. Funziona solo sui caratteri ASCII; "
        "per lingue con accenti preferire \\MakeUppercase{}.",
        "LaTeX base",
        r"\uppercase{nota bene}",
    ),
    "MakeUppercase": (
        r"\MakeUppercase{testo}",
        "Converte il testo in maiuscolo gestendo correttamente le codifiche dei font "
        "e gli accenti. Versione moderna e raccomandata rispetto a \\uppercase.",
        "LaTeX base",
        r"\MakeUppercase{nota bene}",
    ),
    "MakeLowercase": (
        r"\MakeLowercase{testo}",
        "Converte il testo in minuscolo. Versione moderna e raccomandata rispetto "
        "a \\lowercase, gestisce le codifiche dei font.",
        "LaTeX base",
        r"\MakeLowercase{IMPORTANTE}",
    ),

    # ── Spazi e lunghezze ─────────────────────────────────────────────────────
    "hspace": (
        r"\hspace{lunghezza}",
        "Inserisce uno spazio orizzontale di larghezza fissa. "
        "La versione \\hspace*{} non viene eliminata a inizio riga o fine riga.",
        "LaTeX base",
        r"\hspace{2cm}",
    ),
    "vspace": (
        r"\vspace{lunghezza}",
        "Inserisce spazio verticale tra paragrafi. "
        "La versione \\vspace*{} non viene eliminata a inizio o fine pagina.",
        "LaTeX base",
        r"\vspace{1em}",
    ),
    "hfill": (
        r"\hfill",
        "Spazio elastico orizzontale che si espande per riempire lo spazio disponibile. "
        "Usato per allineare testo a destra: testo sinistra \\hfill testo destra.",
        "LaTeX base",
        r"Nome \hfill Data: \underline{\hspace{3cm}}",
    ),
    "vfill": (
        r"\vfill",
        "Spazio elastico verticale che si espande per riempire la pagina. "
        "Usato per spingere il contenuto verso il fondo pagina.",
        "LaTeX base",
        r"Titolo \vfill Data: \today",
    ),
    "noindent": (
        r"\noindent",
        "Sopprime il rientro del primo rigo del paragrafo corrente. "
        "Usato all'inizio di un paragrafo o dopo ambienti che non devono essere seguiti da rientro.",
        "LaTeX base",
        r"\noindent Il testo inizia senza rientro.",
    ),
    "setlength": (
        r"\setlength{comando}{lunghezza}",
        "Imposta il valore di un parametro di lunghezza. "
        "I parametri comuni sono \\parindent, \\parskip, \\baselineskip, \\textwidth.",
        "LaTeX base",
        r"\setlength{\parskip}{6pt}",
    ),
    "addtolength": (
        r"\addtolength{comando}{lunghezza}",
        "Incrementa (o decrementa con valore negativo) un parametro di lunghezza. "
        "Alternativa a \\setlength quando si vuole modificare il valore corrente.",
        "LaTeX base",
        r"\addtolength{\textwidth}{2cm}",
    ),
    "newlength": (
        r"\newlength{\comando}",
        "Dichiara una nuova variabile di lunghezza. "
        "Deve essere inizializzata con \\setlength prima dell'uso.",
        "LaTeX base",
        r"\newlength{\margineCustom}  \setlength{\margineCustom}{1.5cm}",
    ),
    "setcounter": (
        r"\setcounter{contatore}{valore}",
        "Imposta il valore di un contatore LaTeX. "
        "Contatori comuni: page, section, figure, table, equation, footnote.",
        "LaTeX base",
        r"\setcounter{page}{1}",
    ),
    "addtocounter": (
        r"\addtocounter{contatore}{valore}",
        "Incrementa (o decrementa con valore negativo) il valore di un contatore LaTeX.",
        "LaTeX base",
        r"\addtocounter{footnote}{-1}",
    ),
    "stepcounter": (
        r"\stepcounter{contatore}",
        "Incrementa di 1 il contatore specificato e azzera tutti i contatori subordinati.",
        "LaTeX base",
        r"\stepcounter{section}",
    ),

    # ── Pagine e layout ───────────────────────────────────────────────────────
    "pagestyle": (
        r"\pagestyle{stile}",
        "Imposta lo stile di intestazione/piè di pagina per il documento. "
        "Stili predefiniti: <b>plain</b> (solo numero), <b>empty</b> (niente), "
        "<b>headings</b> (titolo sezione), <b>myheadings</b> (personalizzato).",
        "LaTeX base",
        r"\pagestyle{headings}",
    ),
    "thispagestyle": (
        r"\thispagestyle{stile}",
        "Cambia lo stile di intestazione/piè di pagina solo per la pagina corrente. "
        "Spesso usato dopo \\maketitle per sopprimere le intestazioni sulla prima pagina.",
        "LaTeX base",
        r"\thispagestyle{empty}",
    ),
    "pagenumbering": (
        r"\pagenumbering{stile}",
        "Cambia lo stile di numerazione delle pagine e azzera il contatore. "
        "Stili disponibili: <b>arabic</b>, <b>roman</b>, <b>Roman</b>, <b>alph</b>, <b>Alph</b>.",
        "LaTeX base",
        r"\pagenumbering{roman}  % per il preambolo",
    ),
    "markboth": (
        r"\markboth{sinistra}{destra}",
        "Imposta manualmente il testo delle intestazioni sinistra e destra "
        "per lo stile myheadings.",
        "LaTeX base",
        r"\markboth{Capitolo 3}{Metodi}",
    ),

    # ── Figure e tabelle ──────────────────────────────────────────────────────
    "includegraphics": (
        r"\includegraphics[opzioni]{file}",
        "Include un'immagine nel documento. Il file può essere .png, .jpg, .pdf, .eps. "
        "Opzioni comuni: <b>width=</b>, <b>height=</b>, <b>scale=</b>, <b>angle=</b>, "
        "<b>keepaspectratio</b>. Richiede il pacchetto <b>graphicx</b>.",
        "graphicx",
        r"\includegraphics[width=0.8\textwidth]{schema.pdf}",
    ),
    "graphicspath": (
        r"\graphicspath{{cartella1/}{cartella2/}}",
        "Imposta le directory in cui cercare i file immagine. "
        "Le doppie parentesi graffe sono necessarie. "
        "Richiede il pacchetto <b>graphicx</b>.",
        "graphicx",
        r"\graphicspath{{img/}{fig/}}",
    ),
    "caption": (
        r"\caption[didascalia breve]{didascalia}",
        "Aggiunge una didascalia a una figura o tabella. "
        "L'argomento opzionale appare nell'elenco figure/tabelle; "
        "quello obbligatorio sotto l'immagine. Deve essere all'interno di un ambiente float.",
        "LaTeX base",
        r"\caption[Schema circuito]{Schema del circuito RC serie.}",
    ),
    "captionof": (
        r"\captionof{tipo}{didascalia}",
        "Aggiunge una didascalia fuori da un ambiente float. "
        "Il tipo è «figure» o «table». Richiede il pacchetto <b>caption</b>.",
        "caption",
        r"\captionof{figure}{Diagramma di flusso.}",
    ),
    "subcaption": (
        r"\subcaptionbox{didascalia}[larghezza]{contenuto}",
        "Crea una sotto-figura/tabella con propria didascalia all'interno di un float. "
        "Richiede il pacchetto <b>subcaption</b>.",
        "subcaption",
        r"\subcaptionbox{Risultati}{...}",
    ),
    "hline": (
        r"\hline",
        "Disegna una riga orizzontale che si estende per tutta la larghezza della tabella. "
        "Va usata tra righe (non all'interno). Per tabelle di qualità usare \\toprule/\\midrule/\\bottomrule.",
        "LaTeX base",
        r"\hline  A & B \\ \hline",
    ),
    "cline": (
        r"\cline{i-j}",
        "Disegna una riga orizzontale parziale che va dalla colonna <i>i</i> alla colonna <i>j</i>.",
        "LaTeX base",
        r"\cline{2-4}",
    ),
    "multicolumn": (
        r"\multicolumn{n}{allineamento}{testo}",
        "Fonde <i>n</i> celle in orizzontale in una tabella. "
        "L'allineamento specifica l'allineamento e i bordi della cella risultante: "
        "l, c, r, con | per i bordi.",
        "LaTeX base",
        r"\multicolumn{3}{c}{Intestazione unificata}",
    ),
    "multirow": (
        r"\multirow{n}{larghezza}{testo}",
        "Fonde <i>n</i> celle in verticale in una tabella. "
        "Usa * come larghezza per l'adattamento automatico. "
        "Richiede il pacchetto <b>multirow</b>.",
        "multirow",
        r"\multirow{3}{*}{Valore}",
    ),
    "toprule": (
        r"\toprule",
        "Riga orizzontale superiore in una tabella stile <b>booktabs</b>: "
        "più spessa delle righe interne. Non va combinato con \\hline. "
        "Richiede il pacchetto <b>booktabs</b>.",
        "booktabs",
        r"\toprule  Col A & Col B \\ \midrule ... \\ \bottomrule",
    ),
    "midrule": (
        r"\midrule",
        "Riga orizzontale interna in una tabella stile booktabs. "
        "Aggiunge automaticamente spazio verticale prima e dopo. "
        "Richiede il pacchetto <b>booktabs</b>.",
        "booktabs",
        r"A & B \\ \midrule  C & D \\",
    ),
    "bottomrule": (
        r"\bottomrule",
        "Riga orizzontale inferiore in una tabella stile booktabs. "
        "Come \\toprule, è più spessa delle righe interne. "
        "Richiede il pacchetto <b>booktabs</b>.",
        "booktabs",
        r"... \\ \bottomrule",
    ),
    "cmidrule": (
        r"\cmidrule(rifiniture){i-j}",
        "Riga orizzontale parziale in tabelle booktabs, dalla colonna i alla j. "
        "Le rifiniture (r), (l), (rl), (lr) accorciano le estremità per estetica. "
        "Richiede il pacchetto <b>booktabs</b>.",
        "booktabs",
        r"\cmidrule(lr){2-4}",
    ),
    "addlinespace": (
        r"\addlinespace[spazio]",
        "Aggiunge spazio verticale extra tra righe in una tabella booktabs. "
        "Spazio predefinito: 3pt. Richiede il pacchetto <b>booktabs</b>.",
        "booktabs",
        r"\addlinespace[2pt]",
    ),
    # ── Ambienti tabella ──────────────────────────────────────────────────────
    "tabular": (
        r"\begin{tabular}[pos]{specifiche colonne}",
        "Ambiente tabella di base. Le <b>specifiche colonne</b> combinano:<br>"
        "<b>l c r</b> — cella allineata a sinistra / centro / destra<br>"
        "<b>p{larg}</b> — cella paragrafo (testo a capo, allineato in alto)<br>"
        "<b>m{larg}</b> — come p ma centrato verticalmente (pacchetto <b>array</b>)<br>"
        "<b>b{larg}</b> — come p ma allineato in basso (pacchetto <b>array</b>)<br>"
        "<b>X</b> — si espande per riempire la larghezza (pacchetto <b>tabularx</b>)<br>"
        "<b>|</b> — linea verticale tra colonne<br>"
        "<b>@{testo}</b> — sostituisce lo spazio inter-colonna con <i>testo</i><br>"
        "<b>&gt;{cmd}</b> / <b>&lt;{cmd}</b> — preambolo/postambolo di cella (pacchetto <b>array</b>)<br>"
        "Celle separate da <b>&amp;</b>, righe chiuse con <b>\\\\</b>.<br>"
        "Per qualità professionale: pacchetto <b>booktabs</b> (\\toprule, \\midrule, \\bottomrule).",
        "LaTeX base",
        "\\begin{tabular}{|l|c|r|}\n  \\hline\n  Nome & Età & Città \\\\\n  \\hline\n  Mario & 30 & Roma \\\\\n  \\hline\n\\end{tabular}",
    ),
    "tabularx": (
        r"\begin{tabularx}{larghezza}{specifiche}",
        "Come <b>tabular</b> ma con larghezza totale fissa.<br>"
        "Il tipo di colonna <b>X</b> si espande per riempire lo spazio disponibile; "
        "più colonne X si dividono equamente la larghezza residua.<br>"
        "Combinazioni utili con il pacchetto <b>array</b>:<br>"
        "<code>&gt;{\\centering\\arraybackslash}X</code> — X centrata<br>"
        "<code>&gt;{\\raggedright\\arraybackslash}X</code> — X allineata a sinistra<br>"
        "<code>&gt;{\\raggedleft\\arraybackslash}X</code> — X allineata a destra<br>"
        "Definire il tipo con \\newcolumntype per riutilizzarlo.<br>"
        "Richiede il pacchetto <b>tabularx</b>.",
        "tabularx",
        "\\begin{tabularx}{\\textwidth}{l>{\\raggedright\\arraybackslash}Xr}\n  ID & Descrizione & Valore \\\\\n  1 & Testo lungo che va a capo automaticamente & 42 \\\\\n\\end{tabularx}",
    ),
    "tabulary": (
        r"\begin{tabulary}{larghezza}{specifiche}",
        "Come <b>tabularx</b> ma la larghezza delle colonne espandibili viene "
        "bilanciata proporzionalmente al contenuto.<br>"
        "Tipi di colonna propri: "
        "<b>L</b> (sinistra), <b>C</b> (centro), <b>R</b> (destra), <b>J</b> (giustificato).<br>"
        "A differenza di X, le colonne J/L/C/R non si dividono equamente ma in base "
        "al contenuto effettivo. Richiede il pacchetto <b>tabulary</b>.",
        "tabulary",
        "\\begin{tabulary}{\\textwidth}{LCJR}\n  Breve & Centro & Testo molto lungo che si adatta & Destra \\\\\n\\end{tabulary}",
    ),
    "longtable": (
        r"\begin{longtable}[pos]{specifiche}",
        "Tabella che si estende automaticamente su più pagine.<br>"
        "Sezioni speciali (ognuna terminata dalla parola chiave):<br>"
        "<b>\\endfirsthead</b> — intestazione della prima pagina<br>"
        "<b>\\endhead</b> — intestazione ripetuta da seconda pagina in poi<br>"
        "<b>\\endfoot</b> — piè ripetuto su ogni pagina tranne l'ultima<br>"
        "<b>\\endlastfoot</b> — piè dell'ultima pagina<br>"
        "<b>pos</b>: <b>l</b> / <b>c</b> / <b>r</b> allinea la tabella nella pagina.<br>"
        "Richiede il pacchetto <b>longtable</b>.",
        "longtable",
        "\\begin{longtable}[c]{|l|c|}\n  \\hline Col A & Col B \\\\ \\hline \\endfirsthead\n  \\hline Col A & Col B \\\\ \\hline \\endhead\n  \\hline \\endfoot\n  Riga 1 & Dati \\\\\n  Riga 2 & Dati \\\\\n\\end{longtable}",
    ),
    "array": (
        r"\begin{array}[pos]{specifiche}",
        "Ambiente tabella per uso <b>matematico</b> (da usare in modalità math: $...$ o \\[...\\]). "
        "Stesse specifiche colonne di <b>tabular</b> — con il pacchetto <b>array</b> "
        "anche i tipi estesi m{}, b{}, &gt;{} e &lt;{}.<br>"
        "Per matrici con delimitatori usare \\left[ ... \\right] oppure gli ambienti "
        "<b>pmatrix</b>, <b>bmatrix</b>, <b>vmatrix</b> del pacchetto <b>amsmath</b>.",
        "LaTeX base",
        "$\\begin{array}{|c|c|c|}\n  \\hline\n  a & b & c \\\\\n  d & e & f \\\\\n  \\hline\n\\end{array}$",
    ),
    "tabular*": (
        r"\begin{tabular*}{larghezza}[pos]{specifiche}",
        "Tabella a larghezza fissa con spazio distribuito tra le colonne. "
        "Per distribuire lo spazio extra aggiungere <b>@{\\extracolsep{\\fill}}</b> "
        "nelle specifiche di colonna. "
        "Per risultati più prevedibili e semplici preferire <b>tabularx</b>.",
        "LaTeX base",
        "\\begin{tabular*}{\\textwidth}{@{\\extracolsep{\\fill}}lll}\n  Col A & Col B & Col C \\\\\n\\end{tabular*}",
    ),
    "xltabular": (
        r"\begin{xltabular}{larghezza}{specifiche}",
        "Combina <b>tabularx</b> (colonne <b>X</b> espandibili) con <b>longtable</b> "
        "(tabella multi-pagina). Ideale per tabelle larghe \\textwidth che superano una pagina.<br>"
        "Supporta \\endfirsthead, \\endhead, \\endfoot, \\endlastfoot come longtable.<br>"
        "Richiede il pacchetto <b>xltabular</b>.",
        "xltabular",
        "\\begin{xltabular}{\\textwidth}{lXr}\n  \\hline ID & Descrizione & Val \\\\ \\hline \\endfirsthead\n  \\hline ID & Descrizione & Val \\\\ \\hline \\endhead\n  \\hline \\endfoot\n  1 & Testo lungo che va a capo & 42 \\\\\n\\end{xltabular}",
    ),
    "supertabular": (
        r"\begin{supertabular}{specifiche} ... \end{supertabular}",
        "Tabella multi-pagina alternativa a <b>longtable</b>. "
        "Compatibile con ambienti multi-colonna (multicols). "
        "Intestazione e piè si definiscono con <b>\\tablehead{}</b> e <b>\\tabletail{}</b> "
        "prima dell'ambiente. Richiede il pacchetto <b>supertabular</b>.",
        "supertabular",
        "\\tablehead{\\hline Col A & Col B \\\\ \\hline}\n\\tabletail{\\hline}\n\\begin{supertabular}{|l|c|}\n  Riga 1 & Dato \\\\\n\\end{supertabular}",
    ),
    "tblr": (
        r"\begin{tblr}{opzioni} ... \end{tblr}",
        "Ambiente tabella moderno del pacchetto <b>tabularray</b>. "
        "Separa nettamente contenuto e stile tramite le opzioni:<br>"
        "<b>colspec</b> — specifica colonne (lXr, Q[c]Q[l]…)<br>"
        "<b>hlines / vlines</b> — aggiunge linee orizzontali / verticali ovunque<br>"
        "<b>rows={ht=6mm}</b> — altezza minima di ogni riga<br>"
        "<b>cell{r}{c}={cmd}</b> — formattazione di una cella specifica<br>"
        "<b>column{N}={font=\\bfseries}</b> — stile di una colonna<br>"
        "Compatibile con \\toprule, \\midrule, \\bottomrule (booktabs). "
        "Richiede il pacchetto <b>tabularray</b>.",
        "tabularray",
        "\\begin{tblr}{colspec={lXr}, hlines, vlines,\n  row{1}={bg=blue!20, font=\\bfseries}}\n  Nome & Descrizione & Valore \\\\\n  Mario & Test lungo & 42 \\\\\n\\end{tblr}",
    ),
    "longtblr": (
        r"\begin{longtblr}{opzioni} ... \end{longtblr}",
        "Come <b>tblr</b> ma si estende su più pagine. "
        "Intestazioni e piè si definiscono con le opzioni <b>head</b> e <b>foot</b> "
        "oppure colorando le prime/ultime righe con row{1}={...}. "
        "Richiede il pacchetto <b>tabularray</b>.",
        "tabularray",
        "\\begin{longtblr}{\n  colspec={lXr}, hlines,\n  head = normal,\n  row{1}={bg=gray!20, font=\\bfseries}}\n  ID & Descrizione & Val \\\\\n  1 & Primo elemento & 10 \\\\\n\\end{longtblr}",
    ),
    "newcolumntype": (
        r"\newcolumntype{lettera}{definizione}",
        "Definisce un nuovo tipo di colonna riutilizzabile per tabular/tabularx. "
        "Esempi utili:<br>"
        "<code>\\newcolumntype{C}{&gt;{\\centering\\arraybackslash}X}</code> — X centrata<br>"
        "<code>\\newcolumntype{L}{&gt;{\\raggedright\\arraybackslash}X}</code> — X a sinistra<br>"
        "<code>\\newcolumntype{R}{&gt;{\\raggedleft\\arraybackslash}X}</code> — X a destra<br>"
        "<code>\\newcolumntype{N}{&gt;{\\small}r}</code> — r in corpo piccolo<br>"
        "Richiede il pacchetto <b>array</b>.",
        "array",
        "\\newcolumntype{C}{>{\\centering\\arraybackslash}X}\n\\begin{tabularx}{\\textwidth}{lCr} ... \\end{tabularx}",
    ),

    # ── Font e dimensioni ─────────────────────────────────────────────────────
    "tiny": (
        r"{\tiny testo}",
        "Imposta la dimensione del font al valore minimo (~5pt per documenti 10pt). "
        "Le dimensioni in ordine crescente: tiny, scriptsize, footnotesize, small, normalsize, large, Large, LARGE, huge, Huge.",
        "LaTeX base",
        r"{\tiny testo molto piccolo}",
    ),
    "scriptsize": (
        r"{\scriptsize testo}",
        "Dimensione font per indici e apici (~7pt). "
        "Utile per annotazioni e note marginali.",
        "LaTeX base",
        r"{\scriptsize annotazione}",
    ),
    "footnotesize": (
        r"{\footnotesize testo}",
        "Dimensione font usata automaticamente nelle note a piè di pagina (~8pt). "
        "Utile per didascalie e testo secondario.",
        "LaTeX base",
        r"{\footnotesize Fonte: elaborazione propria.}",
    ),
    "small": (
        r"{\small testo}",
        "Dimensione font leggermente ridotta rispetto alla normale (~9pt per documenti 10pt). "
        "Usato spesso per blocchi di codice o citazioni.",
        "LaTeX base",
        r"{\small nota secondaria}",
    ),
    "normalsize": (
        r"{\normalsize testo}",
        "Ripristina la dimensione del font normale del documento. "
        "Usato per tornare alla dimensione standard dopo aver applicato un'altra.",
        "LaTeX base",
        r"{\normalsize testo normale}",
    ),
    "large": (
        r"{\large testo}",
        "Dimensione font leggermente maggiore della normale (~12pt per documenti 10pt). "
        "Spesso usato per titoli di secondo livello.",
        "LaTeX base",
        r"{\large Paragrafo importante}",
    ),
    "Large": (
        r"{\Large testo}",
        "Dimensione font grande (~14pt per documenti 10pt). "
        "Usato per titoli e intestazioni.",
        "LaTeX base",
        r"{\Large Titolo sezione}",
    ),
    "LARGE": (
        r"{\LARGE testo}",
        "Dimensione font molto grande (~17pt per documenti 10pt). "
        "Usato per titoli principali.",
        "LaTeX base",
        r"{\LARGE Titolo capitolo}",
    ),
    "huge": (
        r"{\huge testo}",
        "Dimensione font enorme (~20pt per documenti 10pt). "
        "Usato per titoli principali e copertine.",
        "LaTeX base",
        r"{\huge Titolo}",
    ),
    "Huge": (
        r"{\Huge testo}",
        "Dimensione font massima (~25pt per documenti 10pt). "
        "La più grande delle dimensioni standard LaTeX.",
        "LaTeX base",
        r"{\Huge TITOLO}",
    ),

    # ── Matematica ────────────────────────────────────────────────────────────
    "frac": (
        r"\frac{numeratore}{denominatore}",
        "Produce una frazione verticale. In modalità testo usa dimensioni ridotte; "
        "per forzare la dimensione display usare \\dfrac{}{}.",
        "LaTeX base (amsmath)",
        r"\frac{a^2 + b^2}{c^2}",
    ),
    "dfrac": (
        r"\dfrac{numeratore}{denominatore}",
        "Frazione in stile display (dimensioni piene) anche all'interno di testo inline. "
        "Richiede il pacchetto <b>amsmath</b>.",
        "amsmath",
        r"\dfrac{d}{dx}\sin(x) = \cos(x)",
    ),
    "tfrac": (
        r"\tfrac{numeratore}{denominatore}",
        "Frazione in stile testo (dimensioni ridotte) anche in ambienti display. "
        "Richiede il pacchetto <b>amsmath</b>.",
        "amsmath",
        r"\tfrac{1}{2}",
    ),
    "cfrac": (
        r"\cfrac{numeratore}{denominatore}",
        "Frazione per frazioni continue, con allineamento centrato. "
        "Richiede il pacchetto <b>amsmath</b>.",
        "amsmath",
        r"\cfrac{1}{1+\cfrac{1}{1+\cfrac{1}{2}}}",
    ),
    "binom": (
        r"\binom{n}{k}",
        "Produce il coefficiente binomiale «n su k» con parentesi tonde. "
        "Richiede il pacchetto <b>amsmath</b>.",
        "amsmath",
        r"\binom{n}{k} = \frac{n!}{k!(n-k)!}",
    ),
    "sqrt": (
        r"\sqrt[n]{argomento}",
        "Produce il simbolo di radice. Senza argomento opzionale è la radice quadrata; "
        "con \\sqrt[n]{} è la radice n-esima.",
        "LaTeX base",
        r"\sqrt[3]{x^3 + y^3}",
    ),
    "sum": (
        r"\sum_{basso}^{alto}",
        "Simbolo di sommatoria Σ. Gli indici si pongono in basso con _ e in alto con ^. "
        "In modalità display gli indici appaiono sopra e sotto.",
        "LaTeX base",
        r"\sum_{i=1}^{n} x_i^2",
    ),
    "prod": (
        r"\prod_{basso}^{alto}",
        "Simbolo di produttoria Π. Gli indici si pongono con _ (basso) e ^ (alto). "
        "In modalità display gli indici appaiono sopra e sotto.",
        "LaTeX base",
        r"\prod_{k=1}^{n} k = n!",
    ),
    "int": (
        r"\int_{basso}^{alto}",
        "Simbolo di integrale ∫. "
        "Varianti: \\iint (doppio), \\iiint (triplo), \\oint (circolare).",
        "LaTeX base",
        r"\int_0^\infty e^{-x}\,dx = 1",
    ),
    "iint": (
        r"\iint_{D}",
        "Integrale doppio ∬. Richiede il pacchetto <b>amsmath</b>.",
        "amsmath",
        r"\iint_D f(x,y)\,dx\,dy",
    ),
    "iiint": (
        r"\iiint_{V}",
        "Integrale triplo ∭. Richiede il pacchetto <b>amsmath</b>.",
        "amsmath",
        r"\iiint_V f\,dV",
    ),
    "oint": (
        r"\oint_C",
        "Integrale di linea chiuso ∮ (integrale circolare).",
        "LaTeX base",
        r"\oint_C \mathbf{F}\cdot d\mathbf{l}",
    ),
    "lim": (
        r"\lim_{x \to a}",
        "Operatore limite. Il pedice con _ specifica la variabile e il punto limite. "
        "In modalità display il pedice appare sotto.",
        "LaTeX base",
        r"\lim_{x \to 0} \frac{\sin x}{x} = 1",
    ),
    "partial": (
        r"\partial",
        "Simbolo ∂ della derivata parziale. "
        "Usato per costruire operatori come ∂f/∂x.",
        "LaTeX base",
        r"\frac{\partial f}{\partial x}",
    ),
    "nabla": (
        r"\nabla",
        "Simbolo ∇ dell'operatore nabla (gradiente, divergenza, rotore). "
        "Esempio: \\nabla f (gradiente), \\nabla \\cdot \\mathbf{F} (divergenza).",
        "LaTeX base",
        r"\nabla^2 \phi = 0",
    ),
    "infty": (
        r"\infty",
        "Simbolo dell'infinito ∞.",
        "LaTeX base",
        r"\lim_{n \to \infty}",
    ),
    "forall": (
        r"\forall",
        "Quantificatore universale ∀ (per ogni).",
        "LaTeX base",
        r"\forall x \in \mathbb{R}",
    ),
    "exists": (
        r"\exists",
        "Quantificatore esistenziale ∃ (esiste). "
        "\\nexists produce il simbolo negato ∄.",
        "LaTeX base",
        r"\exists x : f(x) = 0",
    ),
    "text": (
        r"\text{testo}",
        "Inserisce testo in font normale all'interno di una formula matematica. "
        "Richiede il pacchetto <b>amsmath</b>. Gestisce correttamente gli spazi.",
        "amsmath",
        r"x = 0 \text{ se e solo se } y = 0",
    ),
    "operatorname": (
        r"\operatorname{nome}",
        "Definisce un operatore matematico su misura con spaziatura corretta. "
        "Richiede il pacchetto <b>amsmath</b>. Variante \\operatorname*{} con pedice centrato.",
        "amsmath",
        r"\operatorname{div} \mathbf{F}",
    ),
    "left": (
        r"\left( ... \right)",
        "Produce delimitatori ad altezza automatica adattata al contenuto. "
        "I delimitatori devono essere accoppiati: \\left con \\right. "
        "Tipi: (, ), [, ], \\{, \\}, |, \\|, \\langle, \\rangle.",
        "LaTeX base",
        r"\left( \frac{a}{b} \right)^2",
    ),
    "overline": (
        r"\overline{simbolo}",
        "Disegna una barra orizzontale sopra il simbolo. "
        "Usato per coniugato complesso, media, complemento insiemistico.",
        "LaTeX base",
        r"\overline{z} = a - bi",
    ),
    "underline": (
        r"\underline{simbolo}",
        "Disegna una barra orizzontale sotto il simbolo o il testo.",
        "LaTeX base",
        r"\underline{x + y}",
    ),
    "overbrace": (
        r"\overbrace{formula}^{etichetta}",
        "Disegna una graffa sopra la formula con un'etichetta in apice. "
        "Usato per annotare parti di espressioni matematiche.",
        "LaTeX base",
        r"\overbrace{a + b + c}^{n \text{ termini}}",
    ),
    "underbrace": (
        r"\underbrace{formula}_{etichetta}",
        "Disegna una graffa sotto la formula con un'etichetta in pedice. "
        "Usato per annotare parti di espressioni matematiche.",
        "LaTeX base",
        r"\underbrace{x_1 + \cdots + x_n}_{n}",
    ),
    "hat": (
        r"\hat{simbolo}",
        "Accento circonflesso sopra il simbolo (stima statistica, operatore quantistico). "
        "Per simboli larghi usare \\widehat{}.",
        "LaTeX base",
        r"\hat{x}, \hat{\theta}",
    ),
    "bar": (
        r"\bar{simbolo}",
        "Barra corta sopra un singolo simbolo. "
        "Per simboli larghi usare \\overline{}.",
        "LaTeX base",
        r"\bar{x}  % media campionaria",
    ),
    "vec": (
        r"\vec{simbolo}",
        "Freccia sopra il simbolo per indicare un vettore. "
        "Per vettori in grassetto preferire \\mathbf{} o \\boldsymbol{}.",
        "LaTeX base",
        r"\vec{v} = v_x\hat{x} + v_y\hat{y}",
    ),
    "tilde": (
        r"\tilde{simbolo}",
        "Tilde sopra il simbolo (~). Usato per approssimazioni o variabili ridefinite.",
        "LaTeX base",
        r"\tilde{f}(k)",
    ),
    "dot": (
        r"\dot{simbolo}",
        "Punto sopra il simbolo (derivata temporale). "
        "\\ddot{} produce due punti.",
        "LaTeX base",
        r"\dot{x}, \ddot{x}  % velocità, accelerazione",
    ),
    "mathbf": (
        r"\mathbf{simbolo}",
        "Grassetto matematico (upright bold). "
        "Usato per vettori e matrici. Per lettere greche usare \\boldsymbol{} o \\bm{} (pacchetto bm).",
        "LaTeX base",
        r"\mathbf{A}\mathbf{x} = \mathbf{b}",
    ),
    "mathit": (
        r"\mathit{simbolo}",
        "Corsivo matematico (italic). È il default in modalità math per lettere latine. "
        "Usato esplicitamente per identificatori multi-lettera.",
        "LaTeX base",
        r"\mathit{Var}(X)",
    ),
    "mathrm": (
        r"\mathrm{simbolo}",
        "Font romano (upright) in modalità matematica. "
        "Usato per operatori, costanti fisiche, pedici descrittivi.",
        "LaTeX base",
        r"m_{\mathrm{e}}  % massa elettrone",
    ),
    "mathcal": (
        r"\mathcal{lettera}",
        "Font calligrafico per singole lettere maiuscole. "
        "Usato per insiemi, trasformate, categorie: ℒ, ℱ, 𝒜.",
        "LaTeX base",
        r"\mathcal{L}[f] = F(s)  % Laplace",
    ),
    "mathbb": (
        r"\mathbb{lettera}",
        "Font blackboard bold per lettere maiuscole: ℝ, ℕ, ℤ, ℚ, ℂ. "
        "Usato per insiemi numerici standard. Richiede il pacchetto <b>amssymb</b>.",
        "amssymb",
        r"x \in \mathbb{R}, \quad n \in \mathbb{N}",
    ),
    "mathfrak": (
        r"\mathfrak{lettera}",
        "Font fraktur per lettere minuscole/maiuscole. "
        "Usato in algebra per ideali, algebre di Lie. Richiede il pacchetto <b>amssymb</b>.",
        "amssymb",
        r"\mathfrak{g}  % algebra di Lie",
    ),
    "boldsymbol": (
        r"\boldsymbol{simbolo}",
        "Grassetto per simboli matematici, incluse lettere greche. "
        "Richiede il pacchetto <b>amsmath</b> o <b>bm</b>.",
        "amsmath",
        r"\boldsymbol{\alpha}, \boldsymbol{\nabla}",
    ),
    "overset": (
        r"\overset{sopra}{simbolo}",
        "Posiziona <i>sopra</i> in piccolo sopra il <i>simbolo</i>. "
        "Richiede il pacchetto <b>amsmath</b>.",
        "amsmath",
        r"\overset{!}{=}  % uguale con ! sopra",
    ),
    "underset": (
        r"\underset{sotto}{simbolo}",
        "Posiziona <i>sotto</i> in piccolo sotto il <i>simbolo</i>. "
        "Richiede il pacchetto <b>amsmath</b>.",
        "amsmath",
        r"\underset{n \to \infty}{\longrightarrow}",
    ),
    "stackrel": (
        r"\stackrel{sopra}{simbolo}",
        "Posiziona <i>sopra</i> sopra il <i>simbolo</i>. "
        "Alternativa storica a \\overset{}{}; \\overset è preferito con amsmath.",
        "LaTeX base",
        r"a \stackrel{\text{def}}{=} b",
    ),
    "xrightarrow": (
        r"\xrightarrow[sotto]{sopra}",
        "Freccia → estendibile con testo sopra (obbligatorio) e sotto (opzionale). "
        "Richiede il pacchetto <b>amsmath</b>.",
        "amsmath",
        r"A \xrightarrow{f} B",
    ),
    "xleftarrow": (
        r"\xleftarrow[sotto]{sopra}",
        "Freccia ← estendibile con testo sopra e sotto. "
        "Richiede il pacchetto <b>amsmath</b>.",
        "amsmath",
        r"B \xleftarrow{g} C",
    ),
    "intertext": (
        r"\intertext{testo}",
        "Inserisce testo normale tra righe di un ambiente align, "
        "mantenendo l'allineamento delle equazioni. "
        "Richiede il pacchetto <b>amsmath</b>.",
        "amsmath",
        r"\intertext{da cui segue che}",
    ),

    # ── Definizioni e nuovi comandi ────────────────────────────────────────────
    "newcommand": (
        r"\newcommand{\nome}[n]{definizione}",
        "Definisce un nuovo comando con n argomenti (0–9). "
        "Usare #1, #2… per riferirsi agli argomenti. "
        "\\renewcommand ridefinisce un comando esistente.",
        "LaTeX base",
        r"\newcommand{\R}{\mathbb{R}}  \newcommand{\norm}[1]{\|#1\|}",
    ),
    "renewcommand": (
        r"\renewcommand{\nome}[n]{definizione}",
        "Ridefinisce un comando LaTeX esistente. "
        "Uguale a \\newcommand ma non genera errore se il comando esiste già.",
        "LaTeX base",
        r"\renewcommand{\qedsymbol}{$\blacksquare$}",
    ),
    "newenvironment": (
        r"\newenvironment{nome}[n]{inizio}{fine}",
        "Definisce un nuovo ambiente LaTeX. "
        "<i>inizio</i> e <i>fine</i> sono il codice eseguito da \\begin e \\end.",
        "LaTeX base",
        r"\newenvironment{boxed}{\begin{center}\begin{tabular}{|c|}\hline}{\hline\end{tabular}\end{center}}",
    ),
    "newtheorem": (
        r"\newtheorem{nome}[condiviso]{Titolo}[sezione]",
        "Definisce un ambiente teorema numerato. "
        "L'argomento opzionale <i>condiviso</i> fa condividere il contatore con un altro teorema; "
        "<i>sezione</i> reimposta il contatore ad ogni sezione.",
        "LaTeX base (amsthm)",
        r"\newtheorem{thm}{Teorema}[section]",
    ),
    "theoremstyle": (
        r"\theoremstyle{stile}",
        "Imposta lo stile per i teoremi successivi. "
        "Stili: <b>plain</b> (testo corsivo, usato per teoremi e lemmi), "
        "<b>definition</b> (testo normale, per definizioni), "
        "<b>remark</b> (testo normale in tondo, per osservazioni). "
        "Richiede il pacchetto <b>amsthm</b>.",
        "amsthm",
        r"\theoremstyle{definition}  \newtheorem{defn}{Definizione}",
    ),
    "DeclareMathOperator": (
        r"\DeclareMathOperator{\nome}{testo}",
        "Definisce un operatore matematico con spaziatura corretta. "
        "La variante \\DeclareMathOperator*{} permette pedici centrati (stile \\sum). "
        "Richiede il pacchetto <b>amsmath</b>.",
        "amsmath",
        r"\DeclareMathOperator{\tr}{tr}  % traccia di matrice",
    ),
    "makeatletter": (
        r"\makeatletter ... \makeatother",
        "Permette di usare @ nei nomi dei comandi all'interno del preambolo. "
        "\\makeatletter rende @ una lettera; \\makeatother la ripristina.",
        "LaTeX base",
        r"\makeatletter \renewcommand{\@maketitle}{...} \makeatother",
    ),

    # ── Beamer ────────────────────────────────────────────────────────────────
    "frametitle": (
        r"\frametitle{titolo}",
        "Imposta il titolo dello slide corrente in una presentazione Beamer. "
        "Va usato all'interno dell'ambiente <b>frame</b>.",
        "beamer",
        r"\begin{frame}\frametitle{Risultati principali} ... \end{frame}",
    ),
    "framesubtitle": (
        r"\framesubtitle{sottotitolo}",
        "Imposta il sottotitolo dello slide corrente in Beamer. "
        "Appare sotto il titolo principale in carattere più piccolo.",
        "beamer",
        r"\framesubtitle{Analisi statistica}",
    ),
    "pause": (
        r"\pause",
        "Divide lo slide in due overlay: il contenuto dopo \\pause appare al click successivo. "
        "Più \\pause creano una sequenza di overlay progressivi.",
        "beamer",
        r"Primo punto. \pause Secondo punto.",
    ),
    "only": (
        r"\only<overlay>{contenuto}",
        "Mostra il contenuto solo negli overlay specificati, senza riservare spazio negli altri. "
        "Sintassi overlay: <2>, <1-3>, <2,4>, <3->.",
        "beamer",
        r"\only<2>{Questo appare solo al secondo click.}",
    ),
    "onslide": (
        r"\onslide<overlay>{contenuto}",
        "Come \\only ma riserva lo spazio anche quando il contenuto è invisibile. "
        "Evita che gli elementi successivi si spostino.",
        "beamer",
        r"\onslide<2->{Visibile dal secondo click.}",
    ),
    "alert": (
        r"\alert{testo}",
        "Evidenzia il testo nel colore di allerta del tema Beamer (solitamente rosso). "
        "Spesso usato per enfatizzare parole chiave negli slide.",
        "beamer",
        r"\alert{risultato fondamentale}",
    ),
    "usetheme": (
        r"\usetheme{nome}",
        "Imposta il tema grafico della presentazione Beamer. "
        "Temi popolari: <b>Berlin</b>, <b>Warsaw</b>, <b>Madrid</b>, <b>AnnArbor</b>, <b>default</b>.",
        "beamer",
        r"\usetheme{Berlin}",
    ),
    "usecolortheme": (
        r"\usecolortheme{nome}",
        "Imposta la combinazione di colori per la presentazione Beamer. "
        "Esempi: <b>beaver</b>, <b>crane</b>, <b>dolphin</b>, <b>orchid</b>, <b>seahorse</b>.",
        "beamer",
        r"\usecolortheme{seahorse}",
    ),
    "titlepage": (
        r"\titlepage",
        "Genera la diapositiva titolo in Beamer (oppure la pagina titolo in classi standard). "
        "Usa i dati impostati con \\title, \\author, \\date.",
        "beamer / LaTeX base",
        r"\begin{frame}\titlepage\end{frame}",
    ),

    # ── Algoritmi ─────────────────────────────────────────────────────────────
    "KwIn": (
        r"\KwIn{dati}",
        "Intestazione «Input:» per gli algoritmi nel pacchetto <b>algorithm2e</b>.",
        "algorithm2e",
        r"\KwIn{vettore $A$ di $n$ interi}",
    ),
    "KwOut": (
        r"\KwOut{risultato}",
        "Intestazione «Output:» per gli algoritmi nel pacchetto <b>algorithm2e</b>.",
        "algorithm2e",
        r"\KwOut{posizione dell'elemento cercato}",
    ),
    "Return": (
        r"\Return{valore}",
        "Istruzione di ritorno in un algoritmo (pacchetto algorithm2e). "
        "Produce «return valore» in stile algoritmo.",
        "algorithm2e",
        r"\Return{$\pi$}",
    ),
    "foreach": (
        r"\foreach \var in {lista}",
        "Ciclo su una lista di valori. Usato nei pacchetti TikZ e pgffor. "
        "La lista può essere esplicita ({1,2,3}) o un range ({1,...,5}).",
        "tikz / pgffor",
        r"\foreach \x in {0,1,...,4} {\draw (\x,0) circle(1pt);}",
    ),

    # ── TikZ ──────────────────────────────────────────────────────────────────
    "tikz": (
        r"\tikz[opzioni]{comandi}",
        "Crea un'immagine TikZ inline (senza ambiente tikzpicture). "
        "Utile per disegni piccoli all'interno del testo.",
        "tikz",
        r"\tikz \draw (0,0) circle (1cm);",
    ),
    "tikzset": (
        r"\tikzset{opzioni}",
        "Imposta opzioni e stili globali per TikZ. "
        "Equivale a \\pgfkeys{/tikz/.cd,...}.",
        "tikz",
        r"\tikzset{ogni nodo/.style={draw,circle}}",
    ),
    "usetikzlibrary": (
        r"\usetikzlibrary{libreria}",
        "Carica una libreria TikZ aggiuntiva. "
        "Librerie comuni: <b>arrows.meta</b>, <b>positioning</b>, <b>calc</b>, "
        "<b>shapes</b>, <b>decorations</b>, <b>matrix</b>.",
        "tikz",
        r"\usetikzlibrary{arrows.meta,positioning,calc}",
    ),
    "draw": (
        r"\draw[opzioni] percorso;",
        "Disegna un percorso in TikZ. "
        "Percorsi comuni: (x,y)--(x2,y2) (linea), (c) circle (r) (cerchio), "
        "(a) rectangle (b) (rettangolo).",
        "tikz",
        r"\draw[blue,thick] (0,0) -- (2,1) -- (1,2) -- cycle;",
    ),
    "fill": (
        r"\fill[opzioni] percorso;",
        "Riempie un'area in TikZ. "
        "Senza bordo visibile (per bordo + riempimento usare \\filldraw).",
        "tikz",
        r"\fill[red!30] (0,0) rectangle (2,1);",
    ),
    "filldraw": (
        r"\filldraw[opzioni] percorso;",
        "Riempie e disegna il bordo di un'area in TikZ. "
        "Opzioni separate: fill=colore, draw=colore.",
        "tikz",
        r"\filldraw[fill=yellow,draw=orange] (0,0) circle (0.5);",
    ),
    "node": (
        r"\node[opzioni](nome) at (pos) {etichetta};",
        "Crea un nodo TikZ con un'etichetta. "
        "Il nome è opzionale ma necessario per collegarlo con frecce. "
        "Opzioni comuni: draw, circle, rectangle, above, below, right of.",
        "tikz",
        r"\node[draw,circle] (A) at (0,0) {$v_1$};",
    ),

    # ── Listings e codice ─────────────────────────────────────────────────────
    "lstinputlisting": (
        r"\lstinputlisting[opzioni]{file}",
        "Include un file sorgente come listing di codice. "
        "Le opzioni principali: <b>language=</b>, <b>firstline=</b>, <b>lastline=</b>, "
        "<b>caption=</b>, <b>label=</b>. Richiede il pacchetto <b>listings</b>.",
        "listings",
        r"\lstinputlisting[language=Python,firstline=10,lastline=30]{codice.py}",
    ),
    "lstset": (
        r"\lstset{opzioni}",
        "Imposta le opzioni globali per tutti i listing di codice. "
        "Richiede il pacchetto <b>listings</b>.",
        "listings",
        r"\lstset{basicstyle=\small\ttfamily, breaklines=true, frame=single}",
    ),
    "mintinline": (
        r"\mintinline{linguaggio}{codice}",
        "Codice inline con colorazione sintattica tramite Pygments. "
        "Richiede il pacchetto <b>minted</b> e Python+Pygments installati.",
        "minted",
        r"La funzione \mintinline{python}{print()} scrive l'output.",
    ),

    # ── Varie ─────────────────────────────────────────────────────────────────
    "today": (
        r"\today",
        "Produce la data del giorno della compilazione nel formato della lingua del documento "
        "(es. «26 maggio 2025» con \\usepackage[italian]{babel}).",
        "LaTeX base",
        r"\date{\today}",
    ),
    "textcolor": (
        r"\textcolor{colore}{testo}",
        "Colora il testo con il colore specificato. "
        "Colori predefiniti: red, blue, green, black, white, cyan, magenta, yellow. "
        "Richiede il pacchetto <b>xcolor</b>.",
        "xcolor",
        r"\textcolor{red}{Attenzione!}",
    ),
    "colorbox": (
        r"\colorbox{colore}{testo}",
        "Evidenzia il testo con uno sfondo colorato. "
        "Per avere anche un bordo di colore diverso usare \\fcolorbox{}{}{}. "
        "Richiede il pacchetto <b>xcolor</b>.",
        "xcolor",
        r"\colorbox{yellow}{testo evidenziato}",
    ),
    "fcolorbox": (
        r"\fcolorbox{colore bordo}{colore sfondo}{testo}",
        "Box con bordo e sfondo colorati. "
        "Richiede il pacchetto <b>xcolor</b>.",
        "xcolor",
        r"\fcolorbox{red}{yellow}{Avviso}",
    ),
    "definecolor": (
        r"\definecolor{nome}{modello}{valore}",
        "Definisce un colore personalizzato. "
        "Modelli: <b>rgb</b> (0-1), <b>RGB</b> (0-255), <b>HTML</b> (esadecimale), <b>cmyk</b>. "
        "Richiede il pacchetto <b>xcolor</b>.",
        "xcolor",
        r"\definecolor{myblue}{HTML}{2563EB}",
    ),
    "todo": (
        r"\todo[opzioni]{testo}",
        "Inserisce una nota «todo» visibile nel margine durante la stesura. "
        "Opzioni: <b>inline</b>, <b>color=</b>, <b>size=</b>. "
        "Richiede il pacchetto <b>todonotes</b>.",
        "todonotes",
        r"\todo[color=green!40]{Aggiungere figure.}",
    ),
    "si": (
        r"\si{unità}",
        "Compone correttamente le unità di misura in tondo con spaziatura corretta. "
        "Richiede il pacchetto <b>siunitx</b>. Macros unità: \\meter, \\second, \\kilogram, ecc.",
        "siunitx",
        r"\si{\meter\per\second\squared}  →  m s⁻²",
    ),
    "SI": (
        r"\SI{valore}{unità}",
        "Compone un valore numerico con la sua unità di misura. "
        "Il numero è formattato secondo le impostazioni siunitx. "
        "Richiede il pacchetto <b>siunitx</b>.",
        "siunitx",
        r"\SI{9.81}{\meter\per\second\squared}  →  9.81 m s⁻²",
    ),
    "num": (
        r"\num{numero}",
        "Formatta un numero secondo le convenzioni di siunitx: "
        "separatore decimale, migliaia, notazione scientifica. "
        "Richiede il pacchetto <b>siunitx</b>.",
        "siunitx",
        r"\num{1.234e-5}  →  1.234 × 10⁻⁵",
    ),
    "enquote": (
        r"\enquote{testo}",
        "Racchiude il testo con le virgolette tipografiche corrette per la lingua del documento. "
        "Richiede il pacchetto <b>csquotes</b>.",
        "csquotes",
        r"\enquote{citazione diretta}",
    ),
    "setstretch": (
        r"\setstretch{fattore}",
        "Imposta l'interlinea come multiplo della normale. "
        "1.5 = interlinea 1,5; 2.0 = doppia. "
        "Richiede il pacchetto <b>setspace</b>.",
        "setspace",
        r"\setstretch{1.5}",
    ),
    "geometry": (
        r"\geometry{opzioni}",
        "Configura i margini e il layout della pagina. "
        "Opzioni: <b>margin=</b>, <b>top=</b>, <b>bottom=</b>, <b>left=</b>, <b>right=</b>, "
        "<b>a4paper</b>, <b>landscape</b>. "
        "Richiede il pacchetto <b>geometry</b>.",
        "geometry",
        r"\geometry{a4paper, margin=2.5cm}",
    ),
    "printbibliography": (
        r"\printbibliography[opzioni]",
        "Stampa la bibliografia gestita da biblatex. "
        "Opzioni: <b>title=</b>, <b>type=</b>, <b>keyword=</b>, <b>heading=</b>. "
        "Richiede il pacchetto <b>biblatex</b>.",
        "biblatex",
        r"\printbibliography[title={Riferimenti bibliografici}]",
    ),
    "bibliography": (
        r"\bibliography{file.bib}",
        "Specifica il file .bib da usare con BibTeX. "
        "Il nome del file è senza estensione. "
        "Usare \\bibliographystyle{} prima per impostare lo stile.",
        "LaTeX base (BibTeX)",
        r"\bibliographystyle{plain}  \bibliography{refs}",
    ),
    "bibliographystyle": (
        r"\bibliographystyle{stile}",
        "Imposta lo stile di formattazione della bibliografia BibTeX. "
        "Stili standard: <b>plain</b>, <b>alpha</b>, <b>abbrv</b>, <b>unsrt</b>. "
        "Stili estesi: <b>apalike</b>, <b>ieeetr</b>, <b>plainnat</b>.",
        "LaTeX base (BibTeX)",
        r"\bibliographystyle{apalike}",
    ),
    "addbibresource": (
        r"\addbibresource{file.bib}",
        "Aggiunge un file .bib alla bibliografia gestita da biblatex. "
        "Va nel preambolo. Richiede il pacchetto <b>biblatex</b>.",
        "biblatex",
        r"\addbibresource{riferimenti.bib}",
    ),
    "qedhere": (
        r"\qedhere",
        "Posiziona il simbolo di fine dimostrazione (□ o ■) alla fine "
        "dell'ultima riga di un'equazione display. Richiede il pacchetto <b>amsthm</b>.",
        "amsthm",
        r"\begin{proof} ... \qedhere \end{proof}",
    ),
    "item": (
        r"\item[etichetta opzionale]",
        "Introduce un elemento in una lista (itemize, enumerate, description). "
        "L'etichetta opzionale sovrascrive quella automatica.",
        "LaTeX base",
        r"\item Primo elemento  \item[*] Elemento con etichetta personalizzata",
    ),
    "verb": (
        r"\verb|testo|",
        "Compone il testo in font monospaziato esattamente come scritto, "
        "ignorando i comandi LaTeX. Il delimitatore può essere qualsiasi carattere non usato nel testo.",
        "LaTeX base",
        r"\verb|\textbf{non viene processato}|",
    ),
    "textbackslash": (
        r"\textbackslash",
        "Produce un carattere backslash \\ in modalità testo. "
        "Non funziona in modalità matematica (dove si usa \\backslash).",
        "LaTeX base",
        r"Il comando \textbackslash section{} crea una sezione.",
    ),
    "ldots": (
        r"\ldots",
        "Tre puntini di sospensione in basso (…). "
        "Per testo usare \\ldots; per matematica \\cdots (puntini centrati) "
        "o \\vdots (verticali), \\ddots (diagonali).",
        "LaTeX base",
        r"$a_1, a_2, \ldots, a_n$",
    ),
    "cdots": (
        r"\cdots",
        "Tre puntini centrati in matematica (⋯), usati tra operatori: a + ⋯ + n.",
        "LaTeX base",
        r"$a_1 + a_2 + \cdots + a_n$",
    ),
    "vdots": (
        r"\vdots",
        "Tre puntini verticali (⋮), usati nelle matrici per indicare righe omesse.",
        "LaTeX base",
        r"\begin{pmatrix} a_{11} \\ \vdots \\ a_{n1} \end{pmatrix}",
    ),
    "ddots": (
        r"\ddots",
        "Puntini diagonali (⋱), usati nelle matrici per indicare diagonale omessa.",
        "LaTeX base",
        r"A = \begin{pmatrix} 1 & \cdots & 0 \\ \vdots & \ddots & \vdots \\ 0 & \cdots & 1 \end{pmatrix}",
    ),
    "linebreak": (
        r"\linebreak[priorità]",
        "Suggerisce o forza un'interruzione di riga. "
        "Priorità da 0 (suggerimento) a 4 (forzato). "
        "Differisce da \\\\ che inserisce uno spazio verticale.",
        "LaTeX base",
        r"Prima parte\linebreak[2]seconda parte.",
    ),
    "fancyhf": (
        r"\fancyhf{}",
        "Azzera tutti i campi dell'intestazione e del piè di pagina di fancyhdr. "
        "Va chiamato prima di impostare i campi con \\fancyhead e \\fancyfoot. "
        "Richiede il pacchetto <b>fancyhdr</b>.",
        "fancyhdr",
        r"\fancyhf{}  \fancyhead[R]{\thepage}",
    ),
    "fancyhead": (
        r"\fancyhead[posizione]{testo}",
        "Imposta il contenuto di un campo dell'intestazione in fancyhdr. "
        "Posizioni: L (sinistra), C (centro), R (destra), "
        "E/O per pagine pari/dispari: LE, RE, LO, RO. "
        "Richiede il pacchetto <b>fancyhdr</b>.",
        "fancyhdr",
        r"\fancyhead[LE,RO]{\thepage}  \fancyhead[RE,LO]{\leftmark}",
    ),
    "fancyfoot": (
        r"\fancyfoot[posizione]{testo}",
        "Imposta il contenuto di un campo del piè di pagina in fancyhdr. "
        "Stesse posizioni di \\fancyhead. "
        "Richiede il pacchetto <b>fancyhdr</b>.",
        "fancyhdr",
        r"\fancyfoot[C]{\thepage}",
    ),
    "thepage": (
        r"\thepage",
        "Produce il numero della pagina corrente nel formato impostato da \\pagenumbering.",
        "LaTeX base",
        r"Pagina \thepage\ di \pageref{LastPage}",
    ),
    "theequation": (
        r"\theequation",
        "Produce il numero dell'equazione corrente. "
        "Usato per personalizzare la numerazione.",
        "LaTeX base",
        r"\renewcommand{\theequation}{\thesection.\arabic{equation}}",
    ),
    "pdfbookmark": (
        r"\pdfbookmark[livello]{testo}{chiave}",
        "Aggiunge un segnalibro PDF visibile nel pannello laterale del lettore PDF. "
        "Il livello 0 è il più alto. "
        "Richiede il pacchetto <b>hyperref</b>.",
        "hyperref",
        r"\pdfbookmark[0]{Introduzione}{intro}",
    ),
    "texorpdfstring": (
        r"\texorpdfstring{testo LaTeX}{testo PDF}",
        "Permette due versioni di un testo: una per LaTeX (può contenere formule) "
        "e una per le stringhe PDF (segnalibri, metadati) che non le supportano. "
        "Richiede il pacchetto <b>hyperref</b>.",
        "hyperref",
        r"\section{\texorpdfstring{$E=mc^2$}{E=mc²}}",
    ),
    "itemize": (
        r"\begin{itemize} \item ... \end{itemize}",
        "Ambiente per creare un elenco puntato (non ordinato). "
        "Ogni elemento della lista deve iniziare con il comando \\item.",
        "LaTeX base",
        r"\begin{itemize} \item Primo punto \item Secondo punto \end{itemize}",
    ),
    "enumerate": (
        r"\begin{enumerate} \item ... \end{enumerate}",
        "Ambiente per creare un elenco numerato (ordinato). "
        "Per personalizzare lo stile dei numeri (es. a), i), I.) è raccomandato il pacchetto <b>enumitem</b>.",
        "LaTeX base",
        r"\begin{enumerate} \item Primo passaggio \item Secondo passaggio \end{enumerate}",
    ),
    "description": (
        r"\begin{description} \item[Termine] ... \end{description}",
        "Ambiente per glossari o elenchi descrittivi. "
        "L'argomento opzionale tra parentesi quadre di \\item viene tipicamente stampato in grassetto all'inizio del rigo.",
        "LaTeX base",
        r"\begin{description} \item[API] Application Programming Interface \end{description}",
    ),
    "figure": (
        r"\begin{figure}[pos] ... \end{figure}",
        "Ambiente <b>flottante</b> per immagini e grafici.<br>"
        "Il parametro <b>pos</b> indica a LaTeX dove collocare il float:<br>"
        "<b>h</b> — here: qui dove appare nel sorgente (se c'è spazio)<br>"
        "<b>t</b> — top: in cima alla pagina corrente o successiva<br>"
        "<b>b</b> — bottom: in fondo alla pagina<br>"
        "<b>p</b> — page: su una pagina riservata solo ai float<br>"
        "<b>!</b> — ignora le restrizioni interne di LaTeX sul numero di float<br>"
        "<b>H</b> — here esatto (richiede pacchetto <b>float</b>); equivale a forza bruta<br>"
        "L'ordine delle lettere esprime la preferenza. <b>[htbp]</b> è la combinazione più comune.",
        "LaTeX base",
        "\\begin{figure}[htbp]\n  \\centering\n  \\includegraphics[width=0.8\\textwidth]{img.pdf}\n  \\caption{Descrizione immagine}\n  \\label{fig:etichetta}\n\\end{figure}",
    ),
    "figure*": (
        r"\begin{figure*}[pos] ... \end{figure*}",
        "Come <b>figure</b> ma occupa <b>entrambe le colonne</b> nei documenti a doppia colonna "
        "(<code>twocolumn</code> o con il pacchetto <b>multicol</b>). "
        "Accetta solo <b>t</b> (top) e <b>b</b> (bottom) come parametri di posizionamento.",
        "LaTeX base",
        "\\begin{figure*}[t]\n  \\centering\n  \\includegraphics[width=\\textwidth]{img.pdf}\n  \\caption{Figura a tutta larghezza}\n\\end{figure*}",
    ),
    "sidewaysfigure": (
        r"\begin{sidewaysfigure} ... \end{sidewaysfigure}",
        "Ambiente flottante come <b>figure</b> ma ruota l'immagine e la didascalia di 90 gradi. "
        "Occupa un'intera pagina in orizzontale. Richiede il pacchetto <b>rotating</b>.",
        "rotating",
        "\\begin{sidewaysfigure}\n  \\centering\n  \\includegraphics[width=0.9\\textheight]{img.pdf}\n  \\caption{Figura ruotata}\n  \\label{fig:ruotata}\n\\end{sidewaysfigure}",
    ),
    "table": (
        r"\begin{table}[pos] ... \end{table}",
        "Ambiente <b>flottante</b> per tabelle. Non disegna righe/colonne: "
        "al suo interno va un ambiente <b>tabular</b> (o simile). "
        "<i>table</i> gestisce posizionamento e didascalia.<br>"
        "Il parametro <b>pos</b> indica a LaTeX dove collocare il float:<br>"
        "<b>h</b> — here: qui dove appare nel sorgente<br>"
        "<b>t</b> — top: in cima alla pagina<br>"
        "<b>b</b> — bottom: in fondo alla pagina<br>"
        "<b>p</b> — page: su una pagina riservata solo ai float<br>"
        "<b>!</b> — ignora le restrizioni interne di LaTeX<br>"
        "<b>H</b> — posizione esatta forzata (richiede pacchetto <b>float</b>)<br>"
        "<b>[htbp]</b> è la combinazione più usata.",
        "LaTeX base",
        "\\begin{table}[htbp]\n  \\centering\n  \\begin{tabular}{|l|c|r|}\n    \\hline\n    Nome & Età & Città \\\\\n    \\hline\n    Mario & 30 & Roma \\\\\n    \\hline\n  \\end{tabular}\n  \\caption{Titolo tabella}\n  \\label{tab:miatabella}\n\\end{table}",
    ),
    "table*": (
        r"\begin{table*}[pos] ... \end{table*}",
        "Come <b>table</b> ma occupa <b>entrambe le colonne</b> nei documenti a doppia colonna. "
        "Accetta solo <b>t</b> (top) e <b>b</b> (bottom) come posizionamento.",
        "LaTeX base",
        "\\begin{table*}[t]\n  \\centering\n  \\begin{tabularx}{\\textwidth}{lXr}\n    Chiave & Valore & Note \\\\\n  \\end{tabularx}\n  \\caption{Tabella larga su due colonne}\n\\end{table*}",
    ),
    "minipage": (
        r"\begin{minipage}[pos]{larghezza} ... \end{minipage}",
        "Crea una 'pagina in miniatura' indipendente con una larghezza specificata. "
        "Indispensabile per affiancare figure, tabelle o blocchi di testo.",
        "LaTeX base",
        r"\begin{minipage}{0.45\textwidth} Testo colonna sinistra \end{minipage}",
    ),
    "center": (
        r"\begin{center} ... \end{center}",
        "Centra orizzontalmente il testo o gli elementi al suo interno. "
        "Aggiunge automaticamente spazio verticale prima e dopo l'ambiente.",
        "LaTeX base",
        r"\begin{center} \textbf{Titolo Centrato} \end{center}",
    ),
    "abstract": (
        r"\begin{abstract} ... \end{abstract}",
        "Ambiente per la composizione del riassunto (abstract) del documento. "
        "Tipicamente disponibile nelle classi <b>article</b> e <b>report</b>.",
        "LaTeX base",
        r"\begin{abstract} Questo articolo presenta una nuova metodologia... \end{abstract}",
    ),
    "rule": (
        r"\rule[sollevamento]{larghezza}{altezza}",
        "Disegna un blocco rettangolare solido (una linea). "
        "Spesso usato per linee divisorie personalizzate o per forzare un'altezza minima (strut) in tabelle invisibili.",
        "LaTeX base",
        r"\rule{\textwidth}{0.5pt}",
    ),
    "equation": (
        r"\begin{equation} ... \end{equation}",
        "Ambiente per una formula matematica in blocco, centrata e numerata automaticamente. "
        "La versione stellata <b>equation*</b> (richiede amsmath) omette il numero.",
        "LaTeX base",
        r"\begin{equation} E = mc^2 \end{equation}",
    ),
    "align": (
        r"\begin{align} ... \end{align}",
        "Ambiente per allineare equazioni multiple su più righe. "
        "Si usa la e commerciale (&amp;) per indicare il punto di allineamento (di solito il segno =) e \\\\ per andare a capo.",
        "amsmath",
        r"\begin{align} 2x + 1 &= 5 \\ 2x &= 4 \end{align}",
    ),
    "cases": (
        r"\begin{cases} ... \end{cases}",
        "Ambiente matematico essenziale per definire funzioni a tratti o sistemi di equazioni con graffa a sinistra. "
        "Si allineano le condizioni con &amp;.",
        "amsmath",
        r"|x| = \begin{cases} x & \text{se } x \ge 0 \\ -x & \text{se } x < 0 \end{cases}",
    ),
    "pmatrix": (
        r"\begin{pmatrix} ... \end{pmatrix}",
        "Compone una matrice racchiusa tra parentesi tonde. "
        "Varianti popolari: <b>bmatrix</b> (parentesi quadre), <b>vmatrix</b> (barre verticali).",
        "amsmath",
        r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}",
    ),
    "quad": (
        r"\quad",
        "Inserisce uno spazio orizzontale equivalente alla larghezza del carattere 'M' (1 em). "
        "Estremamente comune in modalità matematica per separare equazioni e condizioni.",
        "LaTeX base",
        r"x = 2 \quad \text{e} \quad y = 3",
    ),
    "qquad": (
        r"\qquad",
        "Inserisce uno spazio orizzontale doppio rispetto a \\quad (2 em).",
        "LaTeX base",
        r"f(x) = x^2 \qquad \forall x \in \mathbb{R}",
    ),
    "document": (
        r"\begin{document} ... \end{document}",
        "L'ambiente principale che racchiude tutto il contenuto stampabile del file LaTeX. "
        "Tutto ciò che lo precede è considerato il preambolo.",
        "LaTeX base",
        r"\begin{document} Il mio primo documento. \end{document}",
    ),
    "verbatim": (
        r"\begin{verbatim} ... \end{verbatim}",
        "Ambiente per testo preformattato o codice su più righe. "
        "Ignora tutti i comandi LaTeX al suo interno e usa un font monospaziato.",
        "LaTeX base",
        r"\begin{verbatim} \textbf{non diventerà grassetto} \end{verbatim}",
    ),
    "centering": (
        r"\centering",
        "Centra il contenuto all'interno dell'ambiente corrente (tipicamente figure o table) "
        "senza aggiungere lo spazio verticale extra generato invece dall'ambiente center.",
        "LaTeX base",
        r"\begin{figure}[h] \centering \includegraphics{...}",
    ),
    "raggedright": (
        r"\raggedright",
        "Allinea il testo a sinistra (bandiera a destra), disabilitando la giustificazione automatica "
        "e riducendo al minimo la sillabazione a fine riga.",
        "LaTeX base",
        r"\raggedright Questo testo non sarà giustificato.",
    ),
    "flushleft": (
        r"\begin{flushleft} ... \end{flushleft}",
        "Ambiente per allineare il testo a sinistra. A differenza del comando \raggedright, "
        "aggiunge automaticamente dello spazio verticale prima e dopo l'ambiente.",
        "LaTeX base",
        r"\begin{flushleft} Testo allineato a sinistra \end{flushleft}",
    ),
    "flushright": (
        r"\begin{flushright} ... \end{flushright}",
        "Ambiente per allineare il testo a destra (bandiera a sinistra). "
        "Spesso usato per firme, date o dediche a fine pagina.",
        "LaTeX base",
        r"\begin{flushright} Firma dell'autore \end{flushright}",
    ),
    "quote": (
        r"\begin{quote} ... \end{quote}",
        "Ambiente per citazioni brevi (un solo paragrafo). "
        "Applica un margine rientrato sia a sinistra che a destra rispetto al testo normale.",
        "LaTeX base",
        r"\begin{quote} Essere o non essere, questo è il problema. \end{quote}",
    ),
    "quotation": (
        r"\begin{quotation} ... \end{quotation}",
        "Ambiente per citazioni lunghe (più paragrafi). "
        "Simile a quote, ma aggiunge un rientro alla prima riga di ogni nuovo paragrafo interno.",
        "LaTeX base",
        r"\begin{quotation} Primo paragrafo citato... \par Secondo paragrafo... \end{quotation}",
    ),
    "verse": (
        r"\begin{verse} ... \end{verse}",
        "Ambiente per poesie o testi in versi. "
        "Mantiene gli a capo (\\\\) e indenta le righe troppo lunghe che si spezzano.",
        "LaTeX base",
        r"\begin{verse} Nel mezzo del cammin... \\ mi ritrovai per... \end{verse}",
    ),
    "multicols": (
        r"\begin{multicols}{n} ... \end{multicols}",
        "Divide il testo in <i>n</i> colonne bilanciate. "
        "Attenzione: non supporta l'inserimento di ambienti figure/table classici. Richiede il pacchetto <b>multicol</b>.",
        "multicol",
        r"\begin{multicols}{2} Testo su due colonne affiancate... \end{multicols}",
    ),
    "wrapfigure": (
        r"\begin{wrapfigure}[linee]{pos}{largh} ... \end{wrapfigure}",
        "Inserisce una figura affiancata dal testo (testo avvolto). "
        "<i>pos</i> indica la posizione (l, r, c) e <i>largh</i> la larghezza. Richiede <b>wrapfig</b>.",
        "wrapfig",
        r"\begin{wrapfigure}{r}{0.5\textwidth} \centering \includegraphics{...} \end{wrapfigure}",
    ),
    "landscape": (
        r"\begin{landscape} ... \end{landscape}",
        "Ruota il contenuto e l'orientamento del foglio PDF di 90 gradi (orizzontale). "
        "Ideale per tabelle molto larghe. Richiede il pacchetto <b>pdflscape</b> (o lscape).",
        "pdflscape",
        r"\begin{landscape} \begin{table} ... \end{table} \end{landscape}",
    ),
    "arraystretch": (
        r"\renewcommand{\arraystretch}{fattore}",
        "Comando per modificare l'altezza (spaziatura verticale) di tutte le righe nelle tabelle. "
        "Il valore standard è 1.0; valori come 1.3 o 1.5 danno più respiro al testo.",
        "LaTeX base",
        r"\renewcommand{\arraystretch}{1.5}",
    ),
    "textwidth": (
        r"\textwidth",
        "Variabile di lunghezza che rappresenta la larghezza totale del blocco di testo nella pagina. "
        "Ideale per definire tabelle o immagini che coprono tutta la pagina.",
        "LaTeX base",
        r"\includegraphics[width=0.8\textwidth]{immagine.jpg}",
    ),
    "linewidth": (
        r"\linewidth",
        "Larghezza della riga corrente. Si adatta automaticamente se ci si trova in un ambiente ristretto "
        "(es. dentro una lista o una minipage), rendendola più sicura e preferibile a \\textwidth.",
        "LaTeX base",
        r"\includegraphics[width=\linewidth]{grafico.png}",
    ),
    "textheight": (
        r"\textheight",
        "Variabile di lunghezza che rappresenta l'altezza totale del blocco di testo nella pagina.",
        "LaTeX base",
        r"\includegraphics[height=0.5\textheight]{immagine.jpg}",
    ),
    "newline": (
        r"\newline",
        "Forza un'interruzione di riga immediata senza giustificare il testo orizzontalmente. "
        "Spesso intercambiabile con il doppio backslash (\\\\) nel testo normale.",
        "LaTeX base",
        r"Prima riga \newline Seconda riga",
    ),
    "par": (
        r"\par",
        "Termina il paragrafo corrente. Equivale a lasciare una riga vuota nel codice sorgente. "
        "Utile all'interno di definizioni di comandi o ambienti dove la riga vuota non è permessa.",
        "LaTeX base",
        r"Fine del discorso.\par Nuovo argomento.",
    ),
    "smallskip": (
        r"\smallskip",
        "Inserisce un piccolo spazio verticale elastico (circa 1/4 di riga). "
        "Ideale per separare visivamente due paragrafi vicini.",
        "LaTeX base",
        r"Testo sopra \smallskip Testo sotto",
    ),
    "medskip": (
        r"\medskip",
        "Inserisce uno spazio verticale elastico medio (circa mezza riga).",
        "LaTeX base",
        r"Fine introduzione. \medskip Inizio sviluppo.",
    ),
    "bigskip": (
        r"\bigskip",
        "Inserisce un grande spazio verticale elastico (circa una riga intera).",
        "LaTeX base",
        r"Fine capitolo. \bigskip Nuovo argomento.",
    ),
    "frontmatter": (
        r"\frontmatter",
        "Segna l'inizio del materiale preliminare (prefazione, indici). "
        "Nelle classi book, imposta la numerazione delle pagine in numeri romani (i, ii, iii) e disattiva la numerazione dei capitoli.",
        "LaTeX base (classi book)",
        r"\begin{document} \frontmatter \maketitle",
    ),
    "mainmatter": (
        r"\mainmatter",
        "Segna l'inizio del corpo principale del documento. "
        "Ripristina la numerazione araba (1, 2, 3) partendo da 1 e riattiva la numerazione dei capitoli.",
        "LaTeX base (classi book)",
        r"\mainmatter \chapter{Introduzione}",
    ),
    "backmatter": (
        r"\backmatter",
        "Segna l'inizio del materiale finale (bibliografia, indici analitici). "
        "Mantiene la numerazione araba ma disattiva la numerazione dei capitoli.",
        "LaTeX base (classi book)",
        r"\backmatter \printbibliography",
    ),
    "resizebox": (
        r"\resizebox{larghezza}{altezza}{contenuto}",
        "Scala proporzionalmente il contenuto per adattarlo alle dimensioni specificate. "
        "Usando ! per l'altezza (o larghezza), la proporzione viene mantenuta. Utilissimo per stringere tabelle troppo larghe.",
        "graphicx",
        r"\resizebox{\textwidth}{!}{ \begin{tabular}... \end{tabular} }",
    ),
    "adjustbox": (
        r"\begin{adjustbox}{opzioni} ... \end{adjustbox}",
        "Ambiente “coltellino svizzero” per scalare, ruotare o allineare il contenuto. "
        "Usatissimo con l'opzione <b>max width=\textwidth</b> per rimpicciolire tabelle enormi senza farle uscire dai margini.",
        "adjustbox",
        r"\begin{adjustbox}{max width=\textwidth} \begin{tabular} ... \end{tabular} \end{adjustbox}",
    ),
    "sidewaystable": (
        r"\begin{sidewaystable} ... \end{sidewaystable}",
        "Ambiente flottante simile a <i>table</i>, ma ruota l'intera tabella e la didascalia di 90 gradi, "
        "occupando un'intera pagina in formato orizzontale. Ideale per dataset molto larghi.",
        "rotating",
        r"\begin{sidewaystable} \centering \begin{tabular} ... \end{tabular} \caption{Dati} \end{sidewaystable}",
    ),
    "addcontentsline": (
        r"\addcontentsline{file}{livello}{testo}",
        "Aggiunge manualmente una voce all'indice (TOC), elenco figure (LOF) o tabelle (LOT). "
        "Fondamentale per far apparire capitoli non numerati (es. Introduzione, Bibliografia) nell'indice.",
        "LaTeX base",
        r"\addcontentsline{toc}{chapter}{Introduzione}",
    ),
    "phantomsection": (
        r"\phantomsection",
        "Crea un'ancora invisibile per i collegamenti ipertestuali. "
        "Va usato <b>immediatamente prima</b> di \addcontentsline per far sì che il click nell'indice del PDF porti alla pagina corretta e non a quella precedente.",
        "hyperref",
        r"\phantomsection \addcontentsline{toc}{chapter}{Bibliografia}",
    ),
    "newacronym": (
        r"\newacronym{etichetta}{sigla}{nome per esteso}",
        "Definisce un nuovo acronimo nel preambolo. Usato tipicamente con il pacchetto <b>glossaries</b> "
        "per generare automaticamente la lista delle sigle a inizio/fine tesi.",
        "glossaries",
        r"\newacronym{api}{API}{Application Programming Interface}",
    ),
    "ac": (
        r"\ac{etichetta}",
        "Stampa un acronimo nel testo. La prima volta stampa il nome per esteso con la sigla tra parentesi; "
        "le volte successive stampa solo la sigla. Esiste anche \acf{} per forzare l'esteso.",
        "acronym / glossaries",
        r"Il sistema usa una \ac{api} RESTful.",
    ),
    "epigraph": (
        r"\epigraph{testo}{fonte}",
        "Inserisce una citazione stilizzata (epigrafe) tipicamente sotto il titolo del capitolo. "
        "La larghezza del blocco si controlla impostando la lunghezza \\epigraphwidth.",
        "epigraph",
        r"\epigraph{Fatti non foste a viver come bruti...}{Dante Alighieri}",
    ),
    "lipsum": (
        r"\lipsum[paragrafi]",
        "Genera testo riempitivo fittizio (Lorem ipsum) per testare l'impaginazione o i margini "
        "senza dover incollare testo a caso. L'argomento opzionale indica quali paragrafi stampare.",
        "lipsum",
        r"\lipsum[1-2]  % Stampa i primi due paragrafi",
    ),
    "headrulewidth": (
        r"\renewcommand{\headrulewidth}{spessore}",
        "Modifica lo spessore della linea divisoria sotto l'intestazione. "
        "Impostalo a 0pt per farla sparire del tutto.",
        "fancyhdr",
        r"\renewcommand{\headrulewidth}{0.4pt}",
    ),
    "footrulewidth": (
        r"\renewcommand{\footrulewidth}{spessore}",
        "Modifica lo spessore della linea divisoria sopra il piè di pagina. "
        "Di default è 0pt (invisibile).",
        "fancyhdr",
        r"\renewcommand{\footrulewidth}{0.4pt}",
    ),
    "leftmark": (
        r"\leftmark",
        "Variabile che contiene automaticamente il nome del capitolo corrente (nelle classi book/report) "
        "o della sezione (in article). Usatissimo all'interno di \\fancyhead.",
        "LaTeX base",
        r"\fancyhead[L]{\leftmark}",
    ),
    "rightmark": (
        r"\rightmark",
        "Variabile che contiene automaticamente il nome della sezione corrente (nelle classi book/report) "
        "o della sottosezione (in article).",
        "LaTeX base",
        r"\fancyhead[R]{\rightmark}",
    ),
    "headheight": (
        r"\setlength{\headheight}{lunghezza}",
        "Imposta l'altezza dello spazio riservato all'intestazione. "
        "Se fancyhdr ti dà un avviso (warning) che l'intestazione è troppo piccola, aumenta questo valore (es. a 15pt).",
        "LaTeX base",
        r"\setlength{\headheight}{14.5pt}",
    ),
    "onehalfspacing": (
        r"\onehalfspacing",
        "Imposta l'interlinea a 1.5 per tutto il documento (o fino a un nuovo comando). "
        "È lo standard richiesto per la formattazione della maggior parte delle tesi.",
        "setspace",
        r"\onehalfspacing",
    ),
    "doublespacing": (
        r"\doublespacing",
        "Imposta l'interlinea doppia.",
        "setspace",
        r"\doublespacing",
    ),
    "singlespacing": (
        r"\singlespacing",
        "Ripristina l'interlinea singola standard. "
        "Utile per annullare temporaneamente \\onehalfspacing in porzioni specifiche di testo.",
        "setspace",
        r"\singlespacing",
    ),
    "spacing": (
        r"\begin{spacing}{fattore} ... \end{spacing}",
        "Ambiente per cambiare l'interlinea solo in un blocco di testo specifico, "
        "senza influenzare il resto del documento.",
        "setspace",
        r"\begin{spacing}{1.2} Testo leggermente più arioso \end{spacing}",
    ),
    "microtype": (
        r"\usepackage[opzioni]{microtype}",
        "Il vero 'segreto' per un documento tipograficamente perfetto. "
        "Regola impercettibilmente la larghezza dei caratteri per ridurre la sillabazione e le righe che sbordano (overfull hbox).",
        "microtype",
        r"\usepackage{microtype}  % Basta caricarlo nel preambolo",
    ),
    "includepdf": (
        r"\includepdf[opzioni]{file.pdf}",
        "Inserisce intere pagine da un altro file PDF direttamente nel documento. "
        "Indispensabile per allegare il frontespizio ufficiale fornito dalla segreteria dell'università.",
        "pdfpages",
        r"\includepdf[pages={1}]{frontespizio_ufficiale.pdf}",
    ),
    "blankpage": (
        r"\clearpage \thispagestyle{empty} \mbox{} \clearpage",
        "Non è un comando nativo, ma il trick standard (da inserire in un tuo \\newcommand) "
        "per forzare l'inserimento di una pagina completamente bianca, senza testatina o numeri di pagina.",
        "LaTeX base",
        r"\newcommand{\blankpage}{\clearpage\thispagestyle{empty}\mbox{}\clearpage}",
    ),
    "tcolorbox": (
        r"\begin{tcolorbox}[opzioni] ... \end{tcolorbox}",
        "Crea un box colorato altamente personalizzabile. Perfetto per evidenziare definizioni, teoremi o avvisi. "
        "Opzioni comuni: <b>colback</b> (colore sfondo), <b>colframe</b> (colore bordo), <b>title</b>.",
        "tcolorbox",
        r"\begin{tcolorbox}[colback=red!5!white,colframe=red!75!black,title=Nota Bene] ... \end{tcolorbox}",
    ),
    "tcbox": (
        r"\tcbox[opzioni]{testo}",
        "Versione inline di tcolorbox. Crea un box colorato che si adatta alla larghezza del testo al suo interno, "
        "senza andare a capo. Ideale per evidenziare singole parole, acronimi o formule inline.",
        "tcolorbox",
        r"\tcbox[colback=yellow!30, colframe=yellow!80!black]{Testo evidenziato}",
    ),
    "newtcolorbox": (
        r"\newtcolorbox{nome}[argomenti]{opzioni base}",
        "Definisce un nuovo ambiente basato su tcolorbox per uniformare lo stile nel documento. "
        "Permette di creare box ricorrenti (es. 'Definizione' o 'Esercizio') con un layout coerente e modificabile centralmente.",
        "tcolorbox",
        r"\newtcolorbox{avviso}{colback=red!10, colframe=red, title=Attenzione}",
    ),
    "setlist": (
        r"\setlist[tipo, livello]{opzioni}",
        "Imposta globalmente le spaziature e gli stili per le liste (itemize, enumerate, description). "
        "L'opzione <b>nosep</b> è usatissima per eliminare gli spazi verticali extra tra gli elementi.",
        "enumitem",
        r"\setlist[itemize]{nosep, label=$\triangleright$}",
    ),
    "nocite": (
        r"\nocite{chiave}",
        "Aggiunge una voce alla bibliografia senza inserire alcun riferimento visibile nel testo. "
        "Usa <b>\nocite{*}</b> per forzare l'inclusione nel PDF di <i>tutte</i> le voci presenti nel file .bib, anche se non citate.",
        "LaTeX base / biblatex",
        r"\nocite{*}",
    ),
    "printbibheading": (
        r"\printbibheading[opzioni]",
        "Stampa solo il titolo generale della bibliografia. "
        "Utile per dividere le fonti in più sezioni (es. primarie e secondarie) usando successivi \\printbibliography[heading=none].",
        "biblatex",
        r"\printbibheading[title={Fonti e Bibliografia}]",
    ),
    "counterwithin": (
        r"\counterwithin{contatore}{genitore}",
        "Vincola la numerazione di un contatore a un altro (es. numera le figure per sezione: Figura 1.1, 1.2). "
        "Azzera automaticamente il contatore 'figlio' ogni volta che il 'genitore' avanza.",
        "LaTeX base",
        r"\counterwithin{figure}{section}",
    ),
    "counterwithout": (
        r"\counterwithout{contatore}{genitore}",
        "Svincola un contatore dal suo genitore (es. numera le figure in modo continuo: 1, 2, 3... per tutto il documento, "
        "ignorando del tutto i capitoli o le sezioni).",
        "LaTeX base",
        r"\counterwithout{figure}{chapter}",
    ),
    "patchcmd": (
        r"\patchcmd{comando}{cerca}{sostituisci}{successo}{fallimento}",
        "Cerca una porzione di codice all'interno della definizione di un comando esistente e la sostituisce. "
        "Strumento avanzatissimo per modificare il comportamento delle classi senza ridefinire interi macro.",
        "etoolbox",
        r"\patchcmd{\chapter}{\thispagestyle{plain}}{\thispagestyle{empty}}{}{}",
    ),
    "coordinate": (
        r"\coordinate (nome) at (x,y);",
        "Definisce un punto nello spazio senza stamparlo (a differenza di node). "
        "Utilissimo per memorizzare intersezioni o posizioni chiave da riutilizzare nei comandi di disegno successivi.",
        "tikz",
        r"\coordinate (Origine) at (0,0); \draw (Origine) -- (1,1);",
    ),
    "scope": (
        r"\begin{scope}[opzioni] ... \end{scope}",
        "Crea un gruppo locale all'interno di un'immagine TikZ. "
        "Tutte le opzioni (colore, traslazione, rotazione, clipping) applicate all'ambiente hanno effetto solo sugli elementi al suo interno.",
        "tikz",
        r"\begin{scope}[shift={(2,2)}, red] \draw (0,0) circle (1); \end{scope}",
    ),
    "clip": (
        r"\clip[opzioni] percorso;",
        "Taglia (maschera) tutti i disegni successivi all'interno del gruppo (o scope) corrente, "
        "limitandoli visivamente all'area interna definita dal percorso.",
        "tikz",
        r"\clip (0,0) circle (2); \draw (-3,-3) grid (3,3);",
    ),
    "path": (
        r"\path[opzioni] percorso;",
        "Il comando base di TikZ. A differenza di \\draw o \\fill, non disegna nulla di default. "
        "Si usa per posizionare nodi lungo un percorso invisibile o per definire i limiti della bounding box.",
        "tikz",
        r"\path (0,0) -- node[above]{etichetta} (2,2);",
    ),
    "lstlisting": (
        r"\begin{lstlisting}[opzioni] ... \end{lstlisting}",
        "Ambiente per inserire blocchi di codice sorgente multiriga direttamente nel documento. "
        "Ignora i comandi LaTeX interni e accetta stili personalizzati. Richiede <b>listings</b>.",
        "listings",
        r"\begin{lstlisting}[language=Python] print('Ciao Mondo') \end{lstlisting}",
    ),
    "minted": (
        r"\begin{minted}[opzioni]{linguaggio} ... \end{minted}",
        "Ambiente avanzato per codice sorgente con colorazione sintattica superiore tramite Pygments. "
        "Attenzione: richiede di compilare LaTeX con il flag -shell-escape e avere Python installato.",
        "minted",
        r"\begin{minted}[linenos]{c} int main() { return 0; } \end{minted}",
    ),
    "algorithm": (
        r"\begin{algorithm}[pos] ... \end{algorithm}",
        "Ambiente flottante (come table o figure) che contiene lo pseudocodice. "
        "Garantisce che l'algoritmo non venga spezzato su più pagine e fornisce didascalia e numerazione.",
        "algorithm",
        r"\begin{algorithm}[H] \caption{Ricerca Binaria} ... \end{algorithm}",
    ),
    "algorithmic": (
        r"\begin{algorithmic}[linee] ... \end{algorithmic}",
        "Ambiente per scrivere lo pseudocodice strutturato al riparo nell'ambiente algorithm. "
        "L'argomento opzionale attiva la numerazione delle righe (es. [1] le numera tutte). Richiede <b>algpseudocode</b>.",
        "algpseudocode",
        r"\begin{algorithmic}[1] \State $x \gets 0$ \end{algorithmic}",
    ),
    "State": (
        r"\State",
        "Inizia una nuova istruzione o riga di comando all'interno dell'ambiente algorithmic. "
        "Fondamentale per mantenere automaticamente la corretta indentazione dello pseudocodice.",
        "algpseudocode",
        r"\State $risultato \gets a + b$",
    ),
    "If": (
        r"\If{condizione} ... \EndIf",
        "Costrutto condizionale per pseudocodice. Supporta nativamente anche \\ElsIf e \\Else per le diramazioni. "
        "Richiede <b>algpseudocode</b>.",
        "algpseudocode",
        r"\If{$x > 0$} \State $x \gets x - 1$ \EndIf",
    ),
    "For": (
        r"\For{condizione} ... \EndFor",
        "Costrutto di ciclo for per pseudocodice. Per i cicli indefiniti è disponibile la variante \\While{condizione} ... \\EndWhile.",
        "algpseudocode",
        r"\For{$i = 1$ to $n$} \State \Call{Print}{$i$} \EndFor",
    ),
    "Call": (
        r"\Call{Funzione}{argomenti}",
        "Formatta la chiamata a una funzione o a una subroutine in stile small-caps tipico degli algoritmi.",
        "algpseudocode",
        r"\State $val \gets \Call{CalcolaDistanza}{A, B}$",
    ),
    "makeindex": (
        r"\makeindex[opzioni]",
        "Abilita la generazione dell'indice analitico. Va inserito nel preambolo del documento. "
        "Si raccomanda l'uso del pacchetto <b>imakeidx</b> per la compilazione automatica dell'indice senza passaggi esterni.",
        "imakeidx",
        r"\makeindex[columns=2, title=Indice Analitico]",
    ),
    "printindex": (
        r"\printindex",
        "Stampa l'indice analitico nel punto in cui viene inserito (solitamente a fine documento). "
        "Richiede aver usato \\makeindex nel preambolo e aver marcato le parole con \\index{}.",
        "imakeidx / makeidx",
        r"\printindex",
    ),
    "makeglossaries": (
        r"\makeglossaries",
        "Abilita la raccolta e la generazione dei glossari e degli acronimi. "
        "Va inserito nel preambolo dopo aver caricato il pacchetto <b>glossaries</b>.",
        "glossaries",
        r"\makeglossaries",
    ),
    "printglossary": (
        r"\printglossary[opzioni]",
        "Stampa il glossario standard. Tramite l'argomento opzionale è possibile specificare quale lista stampare "
        "(es. solo gli acronimi o solo i termini tecnici).",
        "glossaries",
        r"\printglossary[type=\acronymtype, title=Elenco degli Acronimi]",
    ),
    "printglossaries": (
        r"\printglossaries",
        "Stampa automaticamente in sequenza tutti i glossari e le liste di acronimi definiti nel documento.",
        "glossaries",
        r"\printglossaries",
    ),
    "newglossaryentry": (
        r"\newglossaryentry{etichetta}{nome=..., description=...}",
        "Definisce una nuova voce per il glossario, specificando il termine e la sua spiegazione. "
        "Nel testo si richiamerà poi con \\gls{etichetta}.",
        "glossaries",
        r"\newglossaryentry{latex}{name=LaTeX, description={Un sistema di preparazione testi}}",
    ),
    "gls": (
        r"\gls{etichetta}",
        "Richiama e stampa un termine del glossario nel testo. "
        "Varianti comuni: \\Gls{} (iniziale maiuscola), \\glspl{} (plurale).",
        "glossaries",
        r"La formattazione è gestita tramite \gls{latex}.",
    ),    
}


_BG     = "#fdf6d8"   # crema gialla, come i tooltip classici
_FG     = "#1a1a1a"
_SIG    = "#0d3d99"   # blu scuro per la firma
_PKG    = "#1a5c28"   # verde scuro per il pacchetto
_EX     = "#7c3500"   # ambra scura per l'esempio
_DIM    = "#6a6a5a"   # grigio per le label secondarie
_BORDER = "#c8ad00"   # bordo dorato


def get_latex_tooltip_html(cmd: str) -> str:
    """
    Restituisce HTML per il tooltip del comando LaTeX.
    Stringa vuota se il comando non è documentato.

    Usa solo elementi inline e <br> — nessun <div> annidato — per evitare
    che Qt applichi il background del tema dell'app ai blocchi interni.
    """
    entry = LATEX_CMD_DOCS.get(cmd)
    if not entry:
        return ""

    signature, description, package, example = entry

    def _esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    sig_esc = _esc(signature)
    desc    = description   # già HTML-safe (contiene solo <b> intenzionali)

    ex_block = ""
    if example:
        ex_lines = _esc(example).replace("\n", "<br>")
        ex_block = (
            f'<br><span style="color:{_DIM};font-size:11px;">&#9472;&#9472;&#9472;</span>'
            f'<br><span style="color:{_DIM};font-size:11px;"><b>Esempio</b></span>'
            f'<br><code style="color:{_EX};font-size:13px;line-height:1.7;">{ex_lines}</code>'
        )

    # Un solo <table> con una cella: il colore di sfondo viene rispettato
    # da Qt anche nelle celle interne quando si usa cellpadding/bgcolor
    html = (
        f'<table cellpadding="0" cellspacing="0" style="background:{_BG};">'
        f'<tr><td style="padding:12px 16px;background:{_BG};">'

        # firma
        f'<code style="color:{_SIG};font-size:14px;font-weight:bold;">{sig_esc}</code>'

        # separatore inline
        f'<br><span style="color:{_DIM};font-size:4px;">&#160;</span><br>'

        # descrizione
        f'<span style="color:{_FG};font-size:13px;line-height:1.65;">{desc}</span>'

        # pacchetto
        f'<br><span style="color:{_DIM};font-size:12px;">Pacchetto:</span>'
        f'&nbsp;<b style="color:{_PKG};font-size:12px;">{_esc(package)}</b>'

        # esempio
        f'{ex_block}'

        f'</td></tr></table>'
    )
    return html

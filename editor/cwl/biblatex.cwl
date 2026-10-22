# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Bibliography and citation commands
# package: biblatex
\autocite[options]{key}#D{Context-sensitive citation}
\autocites[options]{key}{key}#D{Multiple context-sensitive citations}
\parencite[options]{key}#D{Parenthesised citation}
\Parencite[options]{key}#D{Parenthesised citation at the start of a sentence}
\textcite[options]{key}#D{Textual citation}
\Textcite[options]{key}#D{Textual citation at the start of a sentence}
\footcite[options]{key}#D{Footnote citation}
\footcites[options]{key}{key}#D{Multiple footnote citations}
\smartcite[options]{key}#D{Footnote or parenthetical citation}
\cite[options]{key}#D{Generic citation}
\Cite[options]{key}#D{Generic citation at the start of a sentence}
\citeauthor{key}#D{Citation author}
\Citeauthor{key}#D{Citation author at the start of a sentence}
\citeyear{key}#D{Citation year}
\citedate{key}#D{Citation date}
\citetitle{key}#D{Citation title}
\citeurl{key}#D{Citation URL}
\fullcite{key}#D{Full citation in running text}
\footfullcite{key}#D{Full citation in a footnote}
\nocite{key}#D{Include an entry without citing it}
\addbibresource[options]{file}#D{Add a bibliography resource}
\printbibliography[options]#D{Print the bibliography}
\DeclareBibliographyCategory{name}#D{Declare a bibliography category}
\addtocategory{name}{key}#D{Add an entry to a category}
\AtEveryBibitem{code}#D{Insert code before every bibliography item}
\AtEveryCitekey{code}#D{Insert code before every citation}
\renewbibmacro{name}{code}#D{Redefine a bibliography macro}
\newbibmacro{name}{code}#D{Define a bibliography macro}
\bibstring{name}#D{Localised bibliography string}
\mkbibquote{text}#D{Localised quotation marks}
\mkbibemph{text}#D{Localised emphasis}
\mkbibbold{text}#D{Localised bold text}
\ExecuteBibliographyOptions{options}#D{Set biblatex options}

#keyvals:\printbibliography
heading#bibliography,subbibliography
title=
style=
sorting=
filter=
keyword=
category=
segment=
prefixnumbers=
#endkeyvals

#keyvals:\addbibresource
location=
label=
datatype#bib,ris,endnote
#endkeyvals

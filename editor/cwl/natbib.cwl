# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Author-year citation commands
# package: natbib
\citep[pre][post]{key}#D{Parenthetical citation}
\citet[pre][post]{key}#D{Textual citation}
\citep*{key}#D{Parenthetical citation with full author list}
\citet*{key}#D{Textual citation with full author list}
\Citep{key}#D{Parenthetical citation at the start of a sentence}
\Citet{key}#D{Textual citation at the start of a sentence}
\citealp{key}#D{Citation without parentheses}
\citealt{key}#D{Citation without parentheses, textual}
\citeauthor{key}#D{Author only}
\citeyear{key}#D{Year only}
\citeyearpar{key}#D{Year in parentheses}
\bibpunct{open}{close}{separator}{mode}{author-year separator}{year separator}#D{Configure citation punctuation}
\setcitestyle{options}#D{Configure natbib citation style}
\bibstyle{style}#D{Select the bibliography style}
\bibdata{file}#D{Select the bibliography database}
\citestyle{style}#D{Select the citation style}

#keyvals:\setcitestyle
authoryear
numbers
super
round
square
curly
angle
semicolon
comma
aysep=
yysep=
notesep=
#endkeyvals

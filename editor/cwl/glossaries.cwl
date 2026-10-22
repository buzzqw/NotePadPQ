# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Glossaries and acronyms
# package: glossaries
\newglossaryentry{label}{options}#D{Define a glossary entry}
\newacronym{label}{short}{long}#D{Define an acronym}
\gls{label}#D{Reference a glossary entry}
\Gls{label}#D{Reference a glossary entry at the start of a sentence}
\glspl{label}#D{Reference the plural form}
\Glspl{label}#D{Reference the plural form at the start of a sentence}
\glsname{label}#D{Print the entry name}
\glsdesc{label}#D{Print the entry description}
\glssymbol{label}#D{Print the entry symbol}
\glslink{label}{text}#D{Link text to a glossary entry}
\glsadd{label}#D{Add an entry to the glossary}
\glsaddall#D{Add every entry to the glossary}
\makeglossaries#D{Create the glossary files}
\printglossaries#D{Print all glossaries}
\printglossary[options]#D{Print one glossary}
\setglossarystyle{style}#D{Select a glossary style}
\glsentryname{label}#D{Print an entry name without a link}

#keyvals:\newglossaryentry
name=
description=
plural=
symbol=
sort=
type=
parent=
#endkeyvals

#keyvals:\printglossary
type=
style=
title=
toctitle=
nonumberlist
nogroupskip
nopostdot
#endkeyvals

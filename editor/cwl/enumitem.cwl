# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Customisable lists
# package: enumitem
\begin{enumerate}[options]#D{Numbered list with enumitem options}
\begin{itemize}[options]#D{Bulleted list with enumitem options}
\begin{description}[options]#D{Description list with enumitem options}
\setlist[options]{settings}#D{Configure list defaults}
\setlist*[options]{settings}#D{Configure list defaults for the current group}
\newlist{name}{environment}{depth}#D{Define a new list}
\renewlist{name}{environment}{depth}#D{Redefine a list}
\restartlist{name}#D{Restart list numbering}
\setlistdepth{depth}#D{Set the maximum list depth}

#keyvals:\setlist,\begin{enumerate},\begin{itemize},\begin{description}
label=
align#left,right,center
leftmargin=
rightmargin=
labelindent=
labelsep=
labelwidth=
itemindent=
itemsep=
parsep=
topsep=
partopsep=
start=
resume
resume*
nosep
noitemsep
#endkeyvals

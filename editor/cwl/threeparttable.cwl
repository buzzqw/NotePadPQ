# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Tables with notes and captions
# package: threeparttable
\begin{threeparttable}[width]#D{Table with notes below it}
\begin{threeparttable*}[width]#D{Table with notes and a full-width caption}
\begin{tablenotes}[options]#D{Notes belonging to a threeparttable}
\tnote{label}#D{Reference a table note}
\tnote*{label}#D{Reference a table note with a different marker}
\TPTtagStyle{style}#D{Set the style of note tags}

#keyvals:\begin{tablenotes}
flushleft
flushright
para
item
online
label=
labelwidth=
leftmargin=
rightmargin=
topsep=
partopsep=
itemsep=
parsep=
#endkeyvals

# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Modern flexible tables
# package: tabularray
\begin{tblr}[options]{keys}#D{Flexible table}
\begin{longtblr}[options]{keys}#D{Table that can break across pages}
\begin{talltblr}[options]{keys}#D{Table that can break across pages and floats}
\SetCell[options]{content}#D{Configure the current cell}
\SetRow{options}#D{Configure the current row}
\SetColumn{options}#D{Configure the current column}
\SetHline{spec}{options}#D{Configure horizontal rules}
\SetVline{spec}{options}#D{Configure vertical rules}
\hborder{spec}{options}#D{Horizontal border}
\vborder{spec}{options}#D{Vertical border}
\hline[options]#D{Horizontal rule}
\cline{columns}#D{Partial horizontal rule}
\rowcolor{color}#D{Colour the current row}
\cellcolor{color}#D{Colour the current cell}
\diagbox{lower}{upper}#D{Diagonal split in a cell}

#keyvals:\SetCell
r=
c=
span=
bg=
fg=
font=
halign#l,c,r
valign#t,m,b
#endkeyvals

#keyvals:\SetRow
bg=
fg=
font=
halign#l,c,r
valign#t,m,b
height=
#endkeyvals

#keyvals:\SetColumn
bg=
fg=
font=
halign#l,c,r
valign#t,m,b
width=
#endkeyvals

#keyvals:\begin{tblr},\begin{longtblr},\begin{talltblr}
colspec=
width=
hlines#true,false
vlines#true,false
rowhead=
rowfoot=
#endkeyvals

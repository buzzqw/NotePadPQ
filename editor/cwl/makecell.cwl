# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Multi-line and headed table cells
# package: makecell
\makecell[options]{content}#D{Multi-line table cell}
\makecell*[options]{content}#D{Multi-line table cell with a wider alignment}
\thead[options]{content}#D{Table heading cell}
\thead*[options]{content}#D{Table heading cell with a wider alignment}
\bhead{content}#D{Bottom-aligned heading}
\bhead*{content}#D{Bottom-aligned heading with a wider alignment}
\rothead{content}#D{Rotated table heading}
\rothead*{content}#D{Rotated table heading with a wider alignment}
\Xhline{width}#D{Full-width rule}
\Xcline{columns}{width}#D{Partial-width rule}
\setcellgapes{spacing}#D{Set cell gaps}
\makegapedcells#D{Enable cell gaps}

#keyvals:\makecell,\thead,\bhead,\rothead
align#l,c,r
#endkeyvals

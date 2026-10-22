# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Commutative diagrams with TikZ
# package: tikz-cd
\begin{tikzcd}[options]#D{Commutative diagram}
\begin{tikzcd*}[options]#D{Commutative diagram in a display style}
\arrow[options]{direction}#D{Draw an arrow}
\ar[options]{direction}#D{Draw an arrow}
\rar[options]{label}#D{Arrow to the right}
\lar[options]{label}#D{Arrow to the left}
\uar[options]{label}#D{Arrow upwards}
\dar[options]{label}#D{Arrow downwards}
\urar[options]{label}#D{Diagonal arrow up-right}
\ular[options]{label}#D{Diagonal arrow up-left}
\drar[options]{label}#D{Diagonal arrow down-right}
\dlar[options]{label}#D{Diagonal arrow down-left}

#keyvals:\arrow,\ar,\rar,\lar,\uar,\dar
from=
to=
dashed
dotted
Rightarrow
Leftarrow
hook
hook'
two heads
two tails
tail
bend left=
bend right=
shift left=
shift right=
swap
shorten=
color=
description
#endkeyvals

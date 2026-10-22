# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Non-floating tables that flow through multicols
# package: multicoltab
\begin{multicoltab}[options]{columns}#D{Table whose rows can continue in the next multicols column or page}
\mchead[before][after]{cells}#D{Declare and print a repeatable heading row}
\mcheadrepeat#D{Print the last declared heading again}
\multicoltabbreak#D{Force the next multicols column and repeat the heading}
\multicoltabpagebreak#D{Force the next page and repeat the heading}

#keyvals:\begin{multicoltab}
width=##length
row-sep=##length
break-penalty=
natural-widths#global,local
#endkeyvals

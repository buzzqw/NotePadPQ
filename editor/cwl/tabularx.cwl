# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Tables with flexible-width X columns
# package: tabularx
\begin{tabularx}{width}{columns}#D{Table with flexible X columns}
\begin{tabularx*}{width}{columns}#D{Unnumbered table with flexible X columns}
\newcolumntype{name}[arguments]{definition}#D{Define a column type}
\renewcolumntype{name}[arguments]{definition}#D{Redefine a column type}
\providecolumntype{name}[arguments]{definition}#D{Define a column type if it does not exist}
\arraybackslash#D{Restore the row terminator after a column modifier}
\tracingtabularx#D{Show the width calculation in the log}

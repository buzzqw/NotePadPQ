# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Source code listings
# package: listings
\lstset{options}#D{Configure listings}
\lstinline[options]{code}#D{Inline source code}
\lstinputlisting[options]{file}#D{Include a source file}
\begin{lstlisting}[options]#D{Source code listing}
\lstdefinestyle{name}{options}#D{Define a listing style}
\lstdefinelanguage{name}{options}#D{Define a language}
\lstnewenvironment{name}[arguments]{options}{end code}#D{Define a listing environment}
\lstMakeShortInline{character}#D{Define a short inline delimiter}
\lstDeleteShortInline{character}#D{Remove a short inline delimiter}

#keyvals:\lstset,\lstinline,\lstinputlisting,\begin{lstlisting}
language=
basicstyle=
numbers#none,left,right
numberstyle=
stepnumber=
frame#none,leftline,topline,bottomline,lines,shadowbox,box
backgroundcolor=
keywordstyle=
commentstyle=
stringstyle=
showstringspaces#true,false
breaklines#true,false
caption=
label=
firstnumber=
numbersep=
#endkeyvals

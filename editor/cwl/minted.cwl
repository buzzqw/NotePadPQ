# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Syntax-highlighted code with Pygments
# package: minted
\mint[options]{language}{code}#D{Inline source code}
\mintinline[options]{language}{code}#D{Inline source code with a background}
\inputminted[options]{language}{file}#D{Include a source file}
\begin{minted}[options]{language}#D{Source code listing}
\newminted{language}{options}#D{Define a minted environment}
\newmintinline{language}{options}#D{Define an inline minted command}
\newmintedfile{language}{options}#D{Define a command for an external file}
\usemintedstyle{style}#D{Select a Pygments style}
\setminted[language]{options}#D{Set default minted options}

#keyvals:\mint,\mintinline,\inputminted,\begin{minted},\setminted
linenos
linenos*#true,false
frame#none,leftline,topline,bottomline,lines,single
framesep=
bgcolor=
fontsize=
breaklines#true,false
mathescape#true,false
escapeinside=
autogobble#true,false
tabsize=
samepage#true,false
firstnumber=
numbersep=
#endkeyvals

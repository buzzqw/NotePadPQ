# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Coloured and decorated boxes
# package: tcolorbox
\begin{tcolorbox}[options]#D{Coloured box}
\begin{tcblisting}[options]{options}#D{Coloured box containing a listing}
\tcbox[options]{content}#D{Inline coloured box}
\newtcolorbox{name}[arguments]{options}#D{Define a new coloured box}
\renewtcolorbox{name}[arguments]{options}#D{Redefine a coloured box}
\tcbset{options}#D{Configure tcolorbox}
\tcbline#D{Divide the current box}
\tcbbreak#D{Break the current box}
\tcblower#D{Start the lower part of the current box}
\tcbstartrecording#D{Start recording box content}
\tcbstoprecording#D{Stop recording box content}
\tcbinputrecords#D{Insert recorded box content}

#keyvals:\begin{tcolorbox},\tcbox,\newtcolorbox,\renewtcolorbox,\tcbset
title=
colback=
colframe=
coltitle=
fonttitle=
boxrule=
arc=
left=
right=
top=
bottom=
width=
breakable
enhanced
sharp corners
rounded corners
drop shadow
#endkeyvals

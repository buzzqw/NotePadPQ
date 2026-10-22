# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Colours, boxes and table colouring
# package: xcolor
\textcolor{color}{text}#D{Coloured text}
\color{color}#D{Set the current text colour}
\colorbox{color}{text}#D{Coloured background}
\fcolorbox{frame}{background}{text}#D{Coloured box with a frame}
\definecolor{name}{model}{specification}#D{Define a colour}
\colorlet{name}{color}#D{Define a colour as a copy of another}
\rowcolor[model]{color}#D{Colour the current table row}
\cellcolor[model]{color}#D{Colour the current table cell}
\pagecolor{color}#D{Colour the page background}
\nopagecolor#D{Remove the page background colour}

#keyvals:\definecolor
model#rgb,RGB,HTML,gray,cmyk,named
#endkeyvals

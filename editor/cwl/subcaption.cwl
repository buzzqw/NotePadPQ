# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Sub-figures and sub-tables
# package: subcaption
\begin{subfigure}[options]{width}#D{Sub-figure}
\begin{subtable}[options]{width}#D{Sub-table}
\subcaption[options]{text}#D{Sub-caption}
\subcaptionbox[options]{text}{content}#D{Sub-caption with a box}
\phantomcaption#D{Create a caption without text}
\DeclareCaptionSubType{type}#D{Declare a new sub-caption type}

#keyvals:\begin{subfigure},\begin{subtable},\subcaption
labelformat=
justification#raggedright,raggedleft,centering
singlelinecheck#true,false
position#top,bottom
#endkeyvals

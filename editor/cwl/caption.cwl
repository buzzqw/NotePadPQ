# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Caption formatting
# package: caption
\caption[short]{text}#D{Figure or table caption}
\caption*{text}#D{Caption without a number}
\captionof{type}[short]{text}#D{Caption for a non-float}
\captionsetup[type]{options}#D{Configure captions}
\DeclareCaptionFormat{name}{code}#D{Define a caption format}
\DeclareCaptionLabelFormat{name}{code}#D{Define a caption label format}
\DeclareCaptionFont{name}{code}#D{Define a caption font}
\DeclareCaptionStyle{name}{options}#D{Define a caption style}
\clearcaptionsetup{type}#D{Clear caption settings}

#keyvals:\captionsetup
font=
labelfont=
textfont=
labelformat=
labelsep=
justification#raggedright,raggedleft,centering
singlelinecheck#true,false
position#top,bottom
skip=
margin=
width=
format=
#endkeyvals

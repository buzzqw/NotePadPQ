# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Presentation slides and overlays
# package: beamer
\begin{frame}[options]{title}#D{Presentation slide}
\begin{block}{title}#D{Highlighted block}
\begin{alertblock}{title}#D{Alert block}
\begin{exampleblock}{title}#D{Example block}
\begin{columns}[options]#D{Column layout}
\begin{column}{width}#D{One column}
\frametitle{title}#D{Set the frame title}
\framesubtitle{subtitle}#D{Set the frame subtitle}
\titlepage#D{Print the title page}
\pause#D{Pause the slide}
\onslide<overlay>{content}#D{Show content from an overlay onwards}
\only<overlay>{content}#D{Show content only on selected overlays}
\uncover<overlay>{content}#D{Reveal content on selected overlays}
\visible<overlay>{content}#D{Make content visible on selected overlays}
\invisible<overlay>{content}#D{Make content invisible on selected overlays}
\alert{text}#D{Highlighted text}
\tableofcontents#D{Print the table of contents}
\againframe<overlay>{name}#D{Repeat a frame}
\sectionpage#D{Print a section page}
\subsectionpage#D{Print a subsection page}
\note{text}#D{Speaker note}
\usetheme{theme}#D{Select a Beamer theme}
\usecolortheme{theme}#D{Select a Beamer colour theme}
\usefonttheme{theme}#D{Select a Beamer font theme}
\setbeamertemplate{element}{definition}#D{Configure a Beamer template}
\setbeamerfont{element}{options}#D{Configure a Beamer font}
\setbeamercolor{element}{options}#D{Configure a Beamer colour}
\beamertemplatenavigationsymbolsempty#D{Hide navigation symbols}
\beamertemplatenavigationsymbolsvertical#D{Use vertical navigation symbols}

#keyvals:\begin{frame}
t
c
b
label=
fragile
plain
shrink=
allowframebreaks
standout
noframenumbering
containsverbatim
#endkeyvals

# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Section title formatting
# package: titlesec
\titleformat{command}[shape]{format}{label}{separation}{before-code}[after-code]#D{Format a sectioning command}
\titleformat*{command}{format}#D{Format a sectioning command with a simple style}
\titlespacing{command}{left}{before}{after}[right]#D{Set spacing around a sectioning command}
\titlelabel{label}#D{Set the default section label}
\sectionbreak#D{Insert a section break}
\subsectionbreak#D{Insert a subsection break}
\subsubsectionbreak#D{Insert a subsubsection break}
\titleclass{name}{class}[super-level]#D{Set the class of a sectioning command}

#keyvals:\titleformat
hang
block
display
runin
leftmargin
rightmargin
wrap
frame
#endkeyvals

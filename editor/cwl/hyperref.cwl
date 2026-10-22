# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Hyperlinks, PDF metadata and bookmarks
# package: hyperref
\href[options]{url}{text}#D{Hyperlink with custom text}
\url{url}#D{Typeset a URL}
\nolinkurl{url}#D{Typeset a URL without creating a link}
\hyperref[label]{text}#D{Link to a document target}
\hyperlink{target}{text}#D{Link to a named target}
\hypertarget{target}{text}#D{Create a named link target}
\autoref{label}#D{Reference with an automatic type name}
\Autoref{label}#D{Reference with a capitalised automatic type name}
\nameref{label}#D{Reference by the target's name}
\Nameref{label}#D{Reference by the target's name, capitalised}
\hyperbaseurl{url}#D{Set the base URL for relative links}
\hypersetup{options}#D{Configure hyperref}
\phantomsection#D{Create an anchor for the next section-like command}
\pdfbookmark[level]{text}{name}#D{Add a PDF bookmark}
\currentpdfbookmark{text}{name}#D{Add a bookmark at the current level}
\subpdfbookmark{text}{name}#D{Add a bookmark one level below}
\texorpdfstring{tex}{pdf}#D{Use different text in TeX and in PDF metadata}

#keyvals:\hypersetup
colorlinks#true,false
hidelinks
linkcolor=
urlcolor=
citecolor=
filecolor=
anchorcolor=
pdfauthor=
pdftitle=
pdfsubject=
pdfkeywords=
bookmarks#true,false
bookmarksopen#true,false
bookmarksnumbered#true,false
pdfborder=
pdfstartview=
#endkeyvals

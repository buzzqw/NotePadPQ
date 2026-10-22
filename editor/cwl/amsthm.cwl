# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Theorem environments and proof tools
# package: amsthm
\newtheorem{environment}{Title}#D{Define a theorem-like environment}
\newtheorem*{environment}{Title}#D{Define an unnumbered theorem-like environment}
\newtheorem{environment}{Title}[section]#D{Define an environment numbered within a section}
\theoremstyle{style}#D{Select the theorem style}
\qed#D{End-of-proof symbol}
\qedhere#D{Place the end-of-proof symbol here}
\begin{theorem}#D{Theorem}
\begin{theorem*}#D{Unnumbered theorem}
\begin{lemma}#D{Lemma}
\begin{lemma*}#D{Unnumbered lemma}
\begin{proposition}#D{Proposition}
\begin{proposition*}#D{Unnumbered proposition}
\begin{corollary}#D{Corollary}
\begin{corollary*}#D{Unnumbered corollary}
\begin{definition}#D{Definition}
\begin{definition*}#D{Unnumbered definition}
\begin{remark}#D{Remark}
\begin{remark*}#D{Unnumbered remark}
\begin{example}#D{Example}
\begin{example*}#D{Unnumbered example}
\begin{proof}#D{Proof}
\begin{proof}[Title]#D{Proof with a custom title}

#keyvals:\theoremstyle
plain
definition
remark
#endkeyvals

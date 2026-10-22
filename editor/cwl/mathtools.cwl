# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Extended math typesetting tools
# package: mathtools
\DeclarePairedDelimiter{\name}{left}{right}#D{Define a paired-delimiter command}
\DeclarePairedDelimiterX{\name}[arguments]{left}{right}{body}#D{Define a flexible paired-delimiter command}
\abs{x}#D{Absolute value}
\abs*{x}#D{Absolute value with automatic delimiters}
\norm{x}#D{Norm}
\norm*{x}#D{Norm with automatic delimiters}
\floor{x}#D{Floor}
\floor*{x}#D{Floor with automatic delimiters}
\ceil{x}#D{Ceiling}
\ceil*{x}#D{Ceiling with automatic delimiters}
\round{x}#D{Rounding}
\coloneqq#D{Defined as (colon before equals)}
\eqqcolon#D{Equals by definition}
\xrightarrow[below]{above}#D{Arrow with labels}
\xleftarrow[below]{above}#D{Left arrow with labels}
\xleftrightarrow[below]{above}#D{Two-way arrow with labels}
\prescript{superscript}{subscript}{argument}#D{Prescript}
\mathclap{argument}#D{Clap in math mode}
\mathllap{argument}#D{Left overlap in math mode}
\mathrlap{argument}#D{Right overlap in math mode}
\smashoperator{argument}#D{Smash an operator}
\shortintertext{text}#D{Short intertext}
\begin{dcases}#D{Display-style cases}
\begin{dcases*}#D{Display-style cases with text in the second column}
\begin{rcases}#D{Cases with a right brace}
\begin{cases*}#D{Cases with text in the second column}

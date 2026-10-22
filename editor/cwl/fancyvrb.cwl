# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Flexible verbatim environments
# package: fancyvrb
\begin{Verbatim}[options]#D{Verbatim block}
\begin{Verbatim*}[options]#D{Verbatim block that ignores spaces}
\begin{BVerbatim}[options]#D{Block verbatim}
\begin{LVerbatim}[options]#D{Line verbatim}
\begin{SaveVerbatim}{name}#D{Save verbatim content}
\UseVerbatim{name}#D{Use saved verbatim content}
\VerbatimInput[options]{file}#D{Include a verbatim file}
\BVerbatimInput[options]{file}#D{Include a block verbatim file}
\DefineVerbatimEnvironment{name}{base}{options}#D{Define a verbatim environment}
\CustomVerbatimCommand{\name}{base}{options}#D{Define a verbatim command}
\fvset{options}#D{Configure fancyvrb}

#keyvals:\begin{Verbatim},\begin{Verbatim*},\begin{BVerbatim},\begin{LVerbatim},\VerbatimInput,\fvset
fontsize=
frame=
framesep=
rulecolor=
label=
labelposition=
numbers#none,left,right
numbersep=
firstnumber=
commandchars=
samepage
showspaces
showtabs
tabsize=
baselinestretch=
#endkeyvals

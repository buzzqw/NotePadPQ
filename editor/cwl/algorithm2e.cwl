# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Algorithm floats and pseudocode
# package: algorithm2e
\begin{algorithm}[options]#D{Algorithm float}
\begin{algorithm*}[options]#D{Unnumbered algorithm float}
\KwIn{input}#D{Input section}
\KwOut{output}#D{Output section}
\KwData{data}#D{Data section}
\KwResult{result}#D{Result section}
\If{condition}{body}#D{Conditional block}
\Else{body}#D{Else block}
\ElseIf{condition}{body}#D{Else-if block}
\For{condition}{body}#D{For loop}
\While{condition}{body}#D{While loop}
\Repeat{condition}{body}#D{Repeat loop}
\Until{condition}#D{Until clause}
\Return{value}#D{Return statement}
\SetKw{keyword}{text}#D{Define a keyword}
\SetKwFunction{name}{text}#D{Define a function keyword}
\SetKwProg{name}{text}{begin}{end}#D{Define a block keyword}
\tcc{comment}#D{Comment on its own line}
\tcp{comment}#D{Inline comment}
\nl#D{New line}
\BlankLine#D{Blank line}

#keyvals:\begin{algorithm},\begin{algorithm*}
ruled
linesnumbered
vlined
boxed
commentsnumbered
titlenotes
plain
standard
right
left
#endkeyvals

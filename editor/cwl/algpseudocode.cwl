# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Pseudocode blocks
# package: algpseudocode
\begin{algorithmic}[options]#D{Pseudocode block}
\State{statement}#D{A statement}
\Statex#D{A statement without a line number}
\If{condition}#D{Start a conditional block}
\ElsIf{condition}#D{Else-if branch}
\Else#D{Else branch}
\EndIf#D{End the conditional block}
\For{condition}#D{Start a for loop}
\EndFor#D{End the for loop}
\While{condition}#D{Start a while loop}
\EndWhile#D{End the while loop}
\Repeat#D{Start a repeat loop}
\Until{condition}#D{End the repeat loop}
\Function{name}{arguments}#D{Start a function}
\EndFunction#D{End the function}
\Procedure{name}{arguments}#D{Start a procedure}
\EndProcedure#D{End the procedure}
\Return{value}#D{Return a value}
\Require{input}#D{Declare the input}
\Ensure{output}#D{Declare the output}
\Comment{text}#D{Add a comment}
\Call{name}{arguments}#D{Call a procedure}

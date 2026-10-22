# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Core math environments and commands
# package: amsmath
\frac{numerator}{denominator}#D{Fraction}
\dfrac{numerator}{denominator}#D{Display-style fraction}
\tfrac{numerator}{denominator}#D{Text-style fraction}
\binom{n}{k}#D{Binomial coefficient}
\dbinom{n}{k}#D{Display-style binomial coefficient}
\tbinom{n}{k}#D{Text-style binomial coefficient}
\sqrt{x}#D{Square root}
\sqrt[index]{x}#D{Root with an optional index}
\operatorname{name}#D{Named mathematical operator}
\DeclareMathOperator{\name}{text}#D{Define a new operator}
\text{text}#D{Text inside a formula}
\textrm{text}#D{Roman text inside a formula}
\textbf{text}#D{Bold text inside a formula}
\textit{text}#D{Italic text inside a formula}
\intertext{text}#D{Text between aligned lines}
\shortintertext{text}#D{Short intertext (mathtools)}
\eqref{label}#D{Reference to an equation}
\tag{label}#D{Custom equation tag}
\tag*{label}#D{Custom equation tag without parentheses}
\notag#D{Suppress the equation number}
\nonumber#D{Suppress the equation number}
\begin{align}#D{Aligned equations}
\begin{align*}#D{Aligned equations without numbering}
\begin{alignat}{pairs}#D{Aligned equations with explicit spacing}
\begin{alignat*}{pairs}#D{Unnumbered aligned equations with explicit spacing}
\begin{gather}#D{Centered equations}
\begin{gather*}#D{Unnumbered centered equations}
\begin{multline}#D{Multi-line equation}
\begin{multline*}#D{Unnumbered multi-line equation}
\begin{split}#D{Split equation inside another environment}
\begin{aligned}#D{Aligned block inside math mode}
\begin{gathered}#D{Gathered block inside math mode}
\begin{equation}#D{Numbered equation}
\begin{equation*}#D{Unnumbered equation}
\begin{cases}#D{Piecewise cases}
\begin{matrix}#D{Matrix without delimiters}
\begin{pmatrix}#D{Matrix with parentheses}
\begin{bmatrix}#D{Matrix with square brackets}
\begin{Bmatrix}#D{Matrix with braces}
\begin{vmatrix}#D{Matrix with vertical bars}
\begin{Vmatrix}#D{Matrix with double vertical bars}
\begin{smallmatrix}#D{Small matrix}

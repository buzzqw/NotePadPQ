# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Numbers, units and quantities
# package: siunitx
\SI[options]{number}{unit}#D{Number with a unit}
\si[options]{unit}#D{Unit only}
\num[options]{number}#D{Format a number}
\qty[options]{number}{unit}#D{Quantity in the current siunitx style}
\unit[options]{unit}#D{Unit in the current siunitx style}
\ang[options]{angle}#D{Angle}
\complexnum{number}#D{Complex number}
\numlist{numbers}#D{List of numbers}
\numrange{start}{end}#D{Number range}
\SIlist{numbers}{unit}#D{List of quantities}
\SIrange{start}{end}{unit}#D{Quantity range}
\qtylist{numbers}{unit}#D{List of quantities}
\qtyrange{start}{end}{unit}#D{Quantity range}
\qtyproduct{numbers}{unit}#D{Product of quantities}
\sisetup{options}#D{Configure siunitx}
\DeclareSIUnit{\name}{symbol}#D{Declare a unit}
\DeclareSIPrefix{\name}{symbol}{power}#D{Declare a prefix}
\DeclareSIQualifier{\name}{symbol}#D{Declare a qualifier}

#keyvals:\SI,\si,\num,\qty,\unit,\ang
per-mode#symbol,reciprocal,fraction,bracket,power
scientific-notation#true,false,engineering
round-mode#none,figures,places,uncertainty
round-precision=
uncertainty-mode#full,compact,separate
separate-uncertainty#true,false
range-phrase=
range-units#single,repeat
list-separator=
list-final-separator=
list-pair-separator=
locale#DE,UK,US,FR
#endkeyvals

#keyvals:\sisetup
per-mode#symbol,reciprocal,fraction,bracket,power
scientific-notation#true,false,engineering
round-mode#none,figures,places,uncertainty
round-precision=
uncertainty-mode#full,compact,separate
separate-uncertainty#true,false
range-phrase=
range-units#single,repeat
#endkeyvals

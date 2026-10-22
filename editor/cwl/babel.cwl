# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Language selection and hyphenation
# package: babel
\selectlanguage{language}#D{Select the document language}
\foreignlanguage{language}{text}#D{Text in a foreign language}
\begin{otherlanguage}{language}#D{Block in another language}
\begin{otherlanguage*}{language}#D{Block in another language without changing captions}
\shorthandoff{characters}#D{Disable selected shorthands}
\shorthandon{characters}#D{Enable selected shorthands}
\useshorthands{character}#D{Enable a shorthand character}
\defineshorthand{character}{code}#D{Define a shorthand}
\babelprovide[options]{language}#D{Configure a language}
\babelfont{font}#D{Select a font for the current language}

#keyvals:\babelprovide
import
main
alphabetic
mapdigits
onchar=
#endkeyvals

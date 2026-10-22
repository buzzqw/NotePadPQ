# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Language handling for XeLaTeX and LuaLaTeX
# package: polyglossia
\setdefaultlanguage[options]{language}#D{Set the default language}
\setmainlanguage[options]{language}#D{Set the main language}
\setotherlanguage[options]{language}#D{Set another language}
\setotherlanguages{languages}#D{Set several other languages}
\begin{otherlanguage}{language}#D{Block in another language}
\textenglish{text}#D{English text}
\textitalian{text}#D{Italian text}
\textfrench{text}#D{French text}
\textgerman{text}#D{German text}
\textspanish{text}#D{Spanish text}
\textlatin{text}#D{Latin text}
\polyglossiaSetup{language}{options}#D{Configure a language}

#keyvals:\setdefaultlanguage,\setmainlanguage,\setotherlanguage
babelshorthands#true,false
spelling#new,old
#endkeyvals

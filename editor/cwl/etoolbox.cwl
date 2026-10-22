# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Programming tools and hooks
# package: etoolbox
\newtoggle{name}#D{Define a toggle}
\providetoggle{name}#D{Define a toggle if it does not exist}
\settoggle{name}{value}#D{Set a toggle}
\toggletrue{name}#D{Set a toggle to true}
\togglefalse{name}#D{Set a toggle to false}
\iftoggle{name}{true}{false}#D{Branch on a toggle}
\newbool{name}#D{Define a boolean}
\setbool{name}{value}#D{Set a boolean}
\ifbool{name}{true}{false}#D{Branch on a boolean}
\AtBeginEnvironment{environment}{code}#D{Insert code at the beginning of an environment}
\AtEndEnvironment{environment}{code}#D{Insert code at the end of an environment}
\AfterEndEnvironment{environment}{code}#D{Insert code after an environment}
\pretocmd{command}{code}{success}{failure}#D{Prepend code to a command}
\apptocmd{command}{code}{success}{failure}#D{Append code to a command}
\patchcmd{command}{search}{replace}{success}{failure}#D{Patch a command}
\ifpatchable{command}{search}{true}{false}#D{Test whether a command can be patched}
\newrobustcmd{command}{code}#D{Define a robust command}
\renewrobustcmd{command}{code}#D{Redefine a robust command}
\providerobustcmd{command}{code}#D{Define a robust command if it does not exist}
\csdef{name}{code}#D{Define a control sequence}
\csgdef{name}{code}#D{Define a global control sequence}
\csxdef{name}{code}#D{Define an expanded global control sequence}
\csuse{name}#D{Use a control sequence by name}

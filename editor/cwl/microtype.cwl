# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Typography and character protrusion
# package: microtype
\microtypesetup{options}#D{Configure microtype}
\textls[options]{text}#D{Letter-spaced text}
\lsstyle#D{Enable letter spacing for the current scope}
\DeclareMicrotypeSet{name}{options}#D{Define a microtype set}
\UseMicrotypeSet[options]{name}#D{Select a microtype set}
\SetProtrusion[options]{font}{settings}#D{Configure protrusion}
\SetExpansion[options]{font}{settings}#D{Configure expansion}
\SetTracking[options]{font}{settings}#D{Configure tracking}
\DisableLigatures[options]{characters}#D{Disable selected ligatures}

#keyvals:\microtypesetup
protrusion=
expansion=
tracking=
activate=
final
draft
verbose
babel
#endkeyvals

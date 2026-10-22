# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Document command and environment definitions
# package: xparse
\NewDocumentCommand{\name}{arguments}{body}#D{Define a document command}
\RenewDocumentCommand{\name}{arguments}{body}#D{Redefine a document command}
\ProvideDocumentCommand{\name}{arguments}{body}#D{Define a document command if it does not exist}
\DeclareDocumentCommand{\name}{arguments}{body}#D{Declare a document command}
\NewExpandableDocumentCommand{\name}{arguments}{body}#D{Define an expandable command}
\NewDocumentEnvironment{name}{arguments}{begin}{end}#D{Define an environment}
\RenewDocumentEnvironment{name}{arguments}{begin}{end}#D{Redefine an environment}
\ProvideDocumentEnvironment{name}{arguments}{begin}{end}#D{Define an environment if it does not exist}
\DeclareDocumentEnvironment{name}{arguments}{begin}{end}#D{Declare an environment}
\IfNoValueTF{argument}{true}{false}#D{Branch when an optional argument is absent}
\IfValueTF{argument}{true}{false}#D{Branch when an optional argument is present}
\IfBooleanTF{argument}{true}{false}#D{Branch on a star argument}
\SplitArgument{count}{token}#D{Split an argument into parts}
\ProcessList{list}{function}#D{Apply a function to a list}
\TrimSpaces{text}#D{Remove leading and trailing spaces}

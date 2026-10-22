# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Page layout and margins
# package: geometry
\geometry{options}#D{Set page geometry}
\newgeometry{options}#D{Change page geometry from this point}
\restoregeometry#D{Restore the geometry saved at the start}
\savegeometry{name}#D{Save the current geometry}
\loadgeometry{name}#D{Restore a saved geometry}

#keyvals:\geometry,\newgeometry
paper#a4paper,letterpaper,legalpaper,a5paper,b5paper
margin=
top=
bottom=
left=
right=
inner=
outer=
headheight=
headsep=
footskip=
includehead
includefoot
landscape
portrait
twoside
bindingoffset=
showframe
verbose
#endkeyvals

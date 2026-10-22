# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Data plots and axes
# package: pgfplots
\begin{axis}[options]#D{Cartesian plot}
\begin{semilogxaxis}[options]#D{Logarithmic x axis}
\begin{semilogyaxis}[options]#D{Logarithmic y axis}
\begin{loglogaxis}[options]#D{Logarithmic x and y axes}
\begin{polaraxis}[options]#D{Polar plot}
\begin{ternaryaxis}[options]#D{Ternary plot}
\begin{groupplot}[options]#D{Group of plots}
\addplot[options]{data}#D{Add a plot}
\addplot3[options]{data}#D{Add a three-dimensional plot}
\addlegendentry{text}#D{Add a legend entry}
\addlegendimage{options}#D{Add a custom legend image}
\pgfplotsset{options}#D{Configure pgfplots}
\usepgfplotslibrary{library}#D{Load a pgfplots library}
\pgfplotstableread{file}\table#D{Read a data table}
\nextgroupplot[options]#D{Start the next plot in a group}
\pgfplotstabletypeset[options]{table}#D{Typeset a data table}
\pgfplotstablegetelem{row}{column}\of{table}#D{Read one table cell}

#keyvals:\begin{axis},\begin{semilogxaxis},\begin{semilogyaxis},\begin{loglogaxis},\begin{polaraxis}
title=
xlabel=
ylabel=
zlabel=
xmin=
xmax=
ymin=
ymax=
zmin=
zmax=
domain=
samples=
width=
height=
grid#major,minor,both,none
legend pos#north east,north west,south east,south west,outer north east
legend style=
xmode#normal,log
ymode#normal,log
scaled ticks#true,false
enlargelimits#true,false
restrict y to domain=
colormap=
colorbar
#endkeyvals

#keyvals:\addplot,\addplot3
domain=
samples=
color=
mark=
mark size=
line width=
dashed
dotted
only marks
smooth
thick
name path=
#endkeyvals

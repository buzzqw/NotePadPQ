# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Vector graphics and diagrams
# package: tikz
\tikz[options]{code}#D{Draw a picture inline}
\tikzset{options}#D{Configure TikZ styles}
\usetikzlibrary{libraries}#D{Load TikZ libraries}
\draw[options]{path}#D{Draw a path}
\path[options]{path}#D{Create a path without drawing it}
\fill[options]{path}#D{Fill a path}
\filldraw[options]{path}#D{Fill and draw a path}
\shade[options]{path}#D{Shade a path}
\shadedraw[options]{path}#D{Shade and draw a path}
\clip[options]{path}#D{Clip following paths}
\node[options]{text}#D{Place a node}
\matrix[options]{content}#D{Place a TikZ matrix}
\graph[options]{content}#D{Draw a graph}
\pic[options]{name}#D{Place a picture}
\useasboundingbox{path}#D{Set the bounding box}
\begin{tikzpicture}[options]#D{TikZ picture}
\begin{scope}[options]#D{TikZ scope}
\begin{pgfonlayer}{layer}#D{Content on a PGF layer}

#keyvals:\draw,\path,\fill,\filldraw,\shade,\shadedraw,\clip
draw=
fill=
color=
line width=
opacity=
dashed
dotted
thick
thin
ultra thick
rounded corners=
->
<-
<->
#endkeyvals

#keyvals:\node
anchor=
above
below
left
right
inner sep=
outer sep=
minimum width=
minimum height=
text width=
align#left,center,right
draw=
fill=
rounded corners
#endkeyvals

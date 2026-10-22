# NotePadPQ original completion data — see README.md
# SPDX-License-Identifier: EUPL-1.2
# description: Images, scaling and rotation
# package: graphicx
\includegraphics[options]{file}#D{Include an image}
\includegraphics*[options]{file}#D{Include an image, clipped to its bounding box}
\rotatebox[options]{angle}{content}#D{Rotate content}
\scalebox{horizontal}{content}#D{Scale content}
\scalebox{horizontal}[vertical]{content}#D{Scale content with a separate vertical factor}
\resizebox{width}{height}{content}#D{Resize content}
\resizebox*{width}{height}{content}#D{Resize content, including its depth}
\reflectbox{content}#D{Mirror content horizontally}
\graphicspath{{directory/}}#D{Add an image search directory}
\DeclareGraphicsExtensions{.pdf,.png,.jpg}#D{Set the image extension precedence}
\DeclareGraphicsRule{extension}{type}{read}{command}#D{Declare a custom graphics rule}

#keyvals:\includegraphics
width=##length
height=##length
totalheight=##length
keepaspectratio#true,false
scale=
angle=
origin#l,r,c,t,b,L,R,C,T,B
trim=##length
clip#true,false
viewport=##length
page=
pagebox#mediabox,cropbox,bleedbox,trimbox,artbox
draft#true,false
interpolate#true,false
hiresbb#true,false
#endkeyvals

#keyvals:\rotatebox
origin=
units=%<number%>
#endkeyvals

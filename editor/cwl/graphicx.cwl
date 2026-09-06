# package: graphicx
\includegraphics[options]{file}#D{Include an image}
\rotatebox[options]{angle}{content}#D{Rotate content}
\scalebox{factor}{content}#D{Scale content}
\resizebox{width}{height}{content}#D{Resize content}

#keyvals:\includegraphics
width=##L
height=##L
totalheight=##L
keepaspectratio#true,false
scale=%<factor%>
angle=%<degrees%>
clip#true,false
draft#true,false
page=%<page number%>
#endkeyvals

#keyvals:\rotatebox
origin=
units=%<number%>
#endkeyvals

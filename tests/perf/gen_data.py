import random, sys, pathlib
out = pathlib.Path(sys.argv[1]); random.seed(1)
W = "alpha beta gamma delta value compute result index buffer stream parser token window editor cursor".split()
def py(n):
    p=[];s=0;i=0
    while s<n:
        a,b=random.sample(W,2)
        t=f'class {a.title()}{i}:\n    """Docstring for {a} {b}."""\n\n    def {a}_{i}(self, {b}, count=10):\n        # comment about {b}\n        for k in range(count):\n            self.{a} = "{b}" + str(k * {i})\n        return {{"{a}": {b}, "n": {i}}}\n\n'
        p.append(t);s+=len(t);i+=1
    return "".join(p)
def tex(n):
    p=["\\documentclass{article}\n\\usepackage{amsmath}\n\\usepackage{graphicx}\n\\begin{document}\n"];s=0;i=0
    while s<n:
        a,b,c=random.sample(W,3)
        t=f"\\section{{{a.title()} {i}}}\\label{{sec:{i}}}\nThe {a} of the {b} is related to {c} as in Eq.~\\ref{{eq:{i}}} and \\cite{{key{i}}}.\n\\begin{{equation}}\\label{{eq:{i}}}\n  x_{{{i}}} = \\frac{{{a[0]}}}{{{b[0]}}} + \\sum_{{k=0}}^{{n}} k^2\n\\end{{equation}}\n% note {c}\n\\begin{{itemize}}\n  \\item {a} \\textbf{{{b}}} and $y={i}$\n\\end{{itemize}}\n\n"
        p.append(t);s+=len(t);i+=1
    p.append("\\end{document}\n"); return "".join(p)
def txt(n):
    p=[];s=0
    while s<n:
        t=" ".join(random.choices(W,k=12))+"\n"; p.append(t); s+=len(t)
    return "".join(p)
def js(n): # minified-like: long lines
    p=[];s=0
    while s<n:
        t="function "+random.choice(W)+"(a,b){return a+b*"+str(random.randint(1,999))+"};"
        p.append(t);s+=len(t)
    return "".join(p)
M=1024*1024
for name,fn,n in [("s.py",py,100*1024),("m.py",py,M),("l.py",py,10*M),("xl.py",py,50*M),
                  ("s.tex",tex,100*1024),("m.tex",tex,M),("l.tex",tex,10*M),
                  ("l.txt",txt,10*M),("xl.txt",txt,100*M),("min.js",js,2*M)]:
    (out/name).write_text(fn(n))
for i in range(30):
    (out/f"tab{i:02}.py").write_text(py(20*1024))

# NotePadPQ LaTeX Manual

Version 1.9.9

This is the complete LaTeX reference for NotePadPQ. It covers editing,
project discovery, compilation, PDF preview, multi-file projects, SyncTeX,
completion, diagnostics and the optional external tools used by a LaTeX
workflow.

For the general application guide, see [MANUAL_EN.md](MANUAL_EN.md).

## 1. Scope and Requirements

NotePadPQ provides the editor and project integration. It does not install a
TeX distribution. Install the engines and tools required by your documents
separately, then make sure they are available on `PATH`.

### Minimal setup

At minimum, install one LaTeX engine and the packages required by the
document. `latexmk` is recommended because it runs the required passes for
references and auxiliary files.

On Debian or Ubuntu, a typical setup is:

```bash
sudo apt install latexmk texlive-latex-extra biber
python -m pip install -e ".[latex]"
```

The exact package names vary by distribution. For a complete workflow, check
that the relevant commands resolve:

```bash
command -v pdflatex
command -v xelatex
command -v lualatex
command -v latexmk
command -v bibtex
command -v biber
command -v synctex
```

Install optional NotePadPQ libraries with the setup script, selecting
**[1] Advanced LaTeX** when prompted:

```bash
bash setup.sh
```

Or install them directly:

```bash
pip install pymupdf matplotlib sympy
```

On Arch Linux, the corresponding packages include:

```bash
sudo pacman -S python-pymupdf python-matplotlib python-sympy texlive-bin
sudo pacman -S biber perl-yaml-tiny perl-file-homedir texlab
```

`texlab` is optional. NotePadPQ keeps local completion and semantic-navigation
fallbacks when no LSP server is installed. `perl-yaml-tiny` and
`perl-file-homedir` are needed by `latexindent`.

### Feature dependencies

| Feature | Requirement |
|---|---|
| Syntax highlighting, folding, completion and checkers | No extra Python library |
| PDF preview and image hover preview | `pymupdf` |
| Equation hover rendering | `matplotlib` |
| Symbolic computation | `sympy` |
| Editor/PDF SyncTeX navigation | `synctex` and a compiler built with SyncTeX support |
| LSP diagnostics and navigation | `texlab` |
| Package documentation | `texdoc` or an Internet connection for CTAN lookup |
| External diagnostics | `chktex` or `lacheck` |
| Formatting | `latexindent` |

Optional features activate automatically when their dependency is available.
The editor remains usable without them.

## 2. First LaTeX Project

1. Create or open a directory containing your `.tex` files.
2. Open the document that owns `\documentclass` and `\begin{document}`.
3. Save the file before configuring a build profile.
4. Open the **Build Panel** and select a LaTeX profile.
5. Compile with **Build -> Compile** or `F6`.
6. Open the Preview panel with `F12`, then use its `▶` button to compile the
   current LaTeX project directly into the preview.

A minimal document is:

```tex
\documentclass{article}
\usepackage{amsmath}

\begin{document}
Hello from NotePadPQ.

\section{First section}
An equation: $a^2+b^2=c^2$.
\end{document}
```

The compile command, output directory and generated PDF depend on the active
profile. A missing engine is reported in the Build panel rather than silently
being replaced by another engine.

## 3. Editing Features

LaTeX files receive syntax highlighting, code folding for matching
`\begin{...}` and `\end{...}` environments, indentation and contextual
completion.

### Contextual completion

The completion system understands the current LaTeX context:

- `\cite{` suggests BibTeX keys found in the project.
- `\ref{`, `\pageref{` and `\eqref{` suggest labels.
- `\begin{` suggests known environments.
- `\usepackage{` suggests packages.
- `[` suggests command, environment or package options.
- In key-value options, `,` starts the next key and `=` offers known values
  when the loaded CWL data provides them.

Package-specific suggestions are enabled by packages detected in the source.
Examples include `multicol`, `tabularx`, `longtable` and `tabulary`.

The environment popup can start from short prefixes such as `\be` or `\en`.
Renaming an environment keeps its matching `\begin` and `\end` names in sync.
`Alt+E` wraps a selection in an environment or tag.

### LaTeX menu assistants

- **LaTeX Wizard** creates equations, environments and tables. Generated code
  can be reviewed and edited before insertion.
- **Quick Table** configures environment, alignment, borders, merged cells,
  caption and label for visual table layout.
- **BibTeX Wizard** creates guided bibliography entries, generates a key and
  can retrieve metadata from a DOI through Crossref.
- **Symbol Palette** searches commands grouped by Greek letters, operators,
  relations, arrows, delimiters and font commands.
- **Citation chooser** searches project-wide BibTeX keys and inserts the
  selected key.

Dragging a local PNG, JPEG, SVG, PDF or other supported image onto a LaTeX
editor opens the figure assistant. After confirmation it can insert
`\includegraphics`, dimensions, a `figure` environment, caption and label.
Paths are made project-relative when possible, and `graphicx` is ensured in the
preamble.

## 4. Root Files and Multi-File Projects

Build and semantic tools need one root document. The root is resolved in this
order:

1. An explicit root directive such as `% !TEX root = main.tex`.
2. The project or build configuration.
3. A document containing `\documentclass`.
4. The current file as a last fallback.

Use a directive in included files when there could be more than one candidate:

```tex
% !TEX root = ../main.tex
```

Paths are resolved relative to the file containing the directive. The
extension may be omitted where LaTeX normally permits it.

The project parser follows common inclusion commands, including:

```tex
\input{chapters/introduction}
\include{chapters/results}
\subfile{chapters/conclusion}
```

It collects sections, labels, citations, custom commands and package context
across the resolved source graph. The same graph is used by completion,
semantic navigation, the Project Dashboard and Global References.

### Unsaved files

The editor keeps modified text in memory, so the active editor can be compiled
from its current contents when the profile supports it. A build started from
the external toolchain normally reads files from disk. Before a full build,
enable **Save automatically before building** or save all relevant files with
`Ctrl+S`/`Shift+Ctrl+S`.

The source tree in the LaTeX preview is also rebuilt from the current resolved
project. If an inactive included tab has unsaved changes, save it before
compiling to guarantee that the external compiler sees the same contents as
the editor.

## 5. Build Profiles and Recipes

The Build panel supports built-in, user and project profiles. Profiles can
define:

- LaTeX engine or `latexmk` command;
- arguments and working directory;
- output directory;
- environment variables;
- sequential pre-build and post-build commands;
- auxiliary processors such as BibTeX, Biber, MakeIndex and MakeGlossaries;
- cleanup behavior for auxiliary files;
- build timeout and output limits.

Use `F8` or **Build -> Build profiles** to inspect and edit profiles. The
**LaTeX Recipes** dialog shows the selected profile and its command pipeline.
Existing global settings and `.notepadpq-build.json` project profiles remain
valid.

Typical engine commands are:

```text
pdflatex -interaction=nonstopmode -synctex=1 <root>.tex
xelatex -interaction=nonstopmode -synctex=1 <root>.tex
lualatex -interaction=nonstopmode -synctex=1 <root>.tex
latexmk -pdf -synctex=1 <root>.tex
latexmk -xelatex -synctex=1 <root>.tex
```

Prefer `latexmk` for projects with bibliography, indexes or several rounds of
cross-references. Keep the output directory consistent with the profile so
the preview and SyncTeX can find the generated PDF and `.synctex` file.

### Automatic auxiliary tools

The Build menu can run auxiliary processors when source commands are detected.
The resulting pipeline is conceptually:

```text
LaTeX -> makeindex/makeglossaries/nomencl -> final LaTeX pass
```

Use explicit recipes when a project needs several named indexes or a custom
processor order. The LaTeX menu can insert `\makeindex`, `\makeglossaries`
and `\makenomenclature`.

### Build output and errors

Build output is parsed into navigable diagnostics. Click an error or warning to
jump to its source location. `Alt+Up` and `Alt+Down` move between build errors.
The Build preferences control auto-save, auto-build on save, a unified
LSP/build error view, maximum output lines and timeout.

## 6. PDF Preview

The Preview panel has two LaTeX modes:

- **Compiled PDF** when a supported compiler has produced a PDF.
- **Structural source view** as a fallback when compilation or PDF rendering
  is unavailable. It presents the resolved source tree rather than pretending
  that uncompiled LaTeX is a final PDF.

Open the panel with `F12`. When a LaTeX document is active, click `▶` in the
preview toolbar to compile the root project. The refresh button updates the
current preview. PDF rendering in the panel requires `pymupdf`.

The preview recognizes included files and the resolved root, not only the
currently selected tab. If the compiler is missing, inspect the Build panel
and the Project Dashboard for toolchain paths and versions.

### External PDF viewer

In Preview preferences, an external viewer command can be configured. Examples:

```text
zathura {PDF}
SumatraPDF.exe {PDF}
```

Leave the field empty to use the system default viewer. `{PDF}` is replaced as
one safe argument.

## 7. SyncTeX

SyncTeX connects source locations and PDF positions. The build must generate a
`.synctex` or `.synctex.gz` file, normally by passing `-synctex=1` to the engine
or `latexmk`.

- Place the editor cursor in a source line and use forward synchronization to
  locate the corresponding PDF position.
- Click a position in the PDF to perform backward synchronization and open the
  matching source file and line.
- Multi-file projects use the resolved source graph and can open an included
  file directly.

If synchronization does not work, verify that the PDF and SyncTeX files belong
to the same build, that the output directory is correct, and that the compiler
was invoked with SyncTeX enabled. Rebuild after changing the root or output
directory.

## 8. Diagnostics and Semantic Tools

The internal checkers run independently of external tools:

- **Environment balance** detects unmatched `\begin`/`\end` pairs and marks
  the gutter.
- **Table columns** checks `tabular`, `tabular*`, `tabularx`, `tabulary`,
  `array`, `longtable`, `supertabular` and `xltabular`. It understands
  `\multicolumn{N}` and highlights only the excess part of a row or column
  specification.
- **TikZ** finds drawing commands such as `\draw`, `\path` and `\node`
  without a terminating semicolon inside `tikzpicture`. A `\foreach` control
  construct does not need its own semicolon.
- **Structure** recognizes sections with short table-of-contents titles such
  as `\section[Short entry]{Full title}`.

The **Project Dashboard** reports the resolved root, source count, output and
PDF paths, selected profile, project health, auxiliary tools and toolchain
availability.

**Global References** scans definitions, references, citations, duplicate or
unused labels, missing includes and missing assets. Double-click a result to
jump to its source location.

### External tools

From **LaTeX -> Project tools**, run optional tools explicitly:

- `ChkTeX` or `lacheck` for external diagnostics;
- `latexindent` for formatting after a successful subprocess; a failed format
  leaves the original text unchanged and a successful replacement is one undo
  operation;
- `texdoc` and CTAN lookup for package or command documentation.

## 9. CWL Completion

NotePadPQ understands TeXstudio-style `.cwl` completion files. Files are loaded
lazily from built-in, user, configured and project directories. Static
completion remains available as a fallback, and malformed CWL files are
ignored.

Configure additional directories in LaTeX completion preferences or with:

```bash
export NOTEPADPQ_CWL_DIRS="$HOME/tex/cwl:/workspace/project/cwl"
```

Use the platform path separator when specifying more than one directory.
CWL data can provide commands, environments, packages, option keys and option
values. It supplements, rather than replaces, the built-in completion.

## 10. Troubleshooting

### The Build panel says that an engine is missing

Check the executable outside NotePadPQ, then restart the application if the
installation changed `PATH`:

```bash
which latexmk
latexmk -v
```

Check the active profile and its working directory. On systems with multiple
TeX installations, use an absolute executable path in the profile if needed.

### The PDF is stale or the wrong file is shown

Confirm the resolved root in the Project Dashboard, save all included files,
compile again and verify the profile's output directory. Remove stale output
only after checking that no other process is using the directory.

### References or citations are not completed

Confirm that the bibliography file is reachable from the resolved project and
that the citation command is complete enough to trigger (`\cite{`). For
multi-file projects, verify `\input`, `\include` or `\subfile` paths and save
files before a disk-based build.

### SyncTeX cannot find a source line

Rebuild with `-synctex=1`, keep the PDF and SyncTeX files in the configured
output directory, and avoid opening a PDF from an older build or a different
profile.

### Preview falls back to the source tree

This means that no usable compiled PDF is available. Install an engine and
`latexmk`, fix the build error, or install `pymupdf` if compilation succeeds but
the panel cannot render the PDF.

### `latexindent` does not start

Install `perl-yaml-tiny` and `perl-file-homedir` on Arch Linux, or install the
equivalent Perl modules for the current distribution. The internal checker does
not depend on `latexindent`.

## 11. Useful Shortcuts

| Shortcut | Action |
|---|---|
| `F6` | Compile |
| `F7` | Build |
| `F8` | Build profiles |
| `F12` | Preview |
| `Ctrl+S` | Save current file |
| `Shift+Ctrl+S` | Save all / Save as |
| `Alt+Up` / `Alt+Down` | Previous / next build error |
| `Ctrl+Shift+F` | Function List |
| `Ctrl+Shift+E` | File Browser |
| `Ctrl+F12` | LSP or semantic go to definition |
| `Shift+F12` | Show references |
| `Alt+Shift+F` | Format document through LSP |
| `Ctrl+Alt+P` | Preferences |

## 12. Limitations and Safe Workflow

- NotePadPQ supplies editor integration, not TeX packages or a complete TeX
  distribution.
- The source-tree preview is a fallback and is not a substitute for a
  successful PDF build.
- Disk-based external builds cannot see unsaved changes in inactive tabs; save
  before compiling.
- A project with multiple possible roots should use an explicit root directive.
- Build tools execute commands configured by the user. Review profiles and
  project build files before running them, especially in untrusted projects.

<div align="center">

<img src="icons/NotePadPQ_128.png" alt="NotePadPQ logo" width="96"/>

# NotePadPQ

**One editor. Every language. Every workflow.**

An open-source, cross-platform desktop environment for code, technical writing,
LaTeX, Markdown, data files and AI-assisted work. Built with Python, PyQt6 and
QScintilla, with native Qt panels and optional plugins instead of an Electron
runtime.

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.x-green?logo=qt)](https://riverbankcomputing.com/software/pyqt/)
[![License](https://img.shields.io/badge/License-EUPL%201.2-blue.svg)](EUPL-1.2%20EN.txt)
[![Latest release](https://img.shields.io/github/v/release/buzzqw/NotePadPQ?label=release)](https://github.com/buzzqw/NotePadPQ/releases/latest)

[English](#english) | [Italiano](#italiano) | [Manuale EN](MANUAL_EN.md) | [Manuale IT](MANUAL_IT.md)

</div>

NotePadPQ is designed for people who do not want to switch between a text
editor, a LaTeX IDE, a Markdown viewer, a terminal, a spreadsheet and a set of
small utilities. The core editor remains usable on its own; advanced workflows
are added through integrated panels and optional plugins.

## English

### What makes it different

| Area | Included capabilities |
|---|---|
| **Editor** | 40+ language modes, QScintilla and Pygments lexers, folding, minimap, smart highlighting, autocomplete, snippets, macros, multi-cursor, optional Vim mode and configurable typography |
| **Projects and files** | Tabs, split views, session restore, project manager, recent files, external-change handling, tail mode and paged editing for files over 200 MB |
| **LaTeX** | Root-file resolution, latexmk profiles, BibTeX/Biber awareness, Function List, completion, diagnostics, templates, PDF preview and bidirectional SyncTeX |
| **Build system** | 12 built-in profiles, custom profiles, variables, environment overrides, pre/post hooks, pipelines, task discovery, concurrent jobs and clickable diagnostics |
| **Preview** | Markdown, HTML, reStructuredText, LaTeX structure, PDF, images, equations, Mermaid and integrated PDF search/selection tools |
| **Development tools** | LSP client, terminal/PTY panel, Git integration, REST client, formatter plugin and project task runner |
| **Data and documents** | Spreadsheet editor, rich-text/WYSIWYG editor, database browser, hex viewer and file conversion workflows |
| **AI and plugins** | Multi-provider AI assistant, local models, contextual editor actions and a broad plugin ecosystem |

### Core editor

- Syntax highlighting for native QScintilla languages including Python,
  JavaScript, TypeScript, C/C++, Java, C#, Bash, SQL, LaTeX, Markdown, HTML,
  CSS, XML, JSON and YAML, plus Pygments-backed modes such as Go, Rust, PHP,
  Swift, Kotlin, Scala, Dart, R, TOML, Haskell, Elixir and Julia.
- Automatic language detection using file extension, filename and content.
- Code folding, dynamic line numbers, minimap, word wrap, whitespace display,
  EOL display, bracket/tag matching and auto-closing pairs.
- Context-aware autocomplete from document words, language snippets, API
  dictionaries and LSP servers.
- Multi-cursor editing, macros, column editor, case conversion, smart
  indentation, comment/uncomment, line operations, regex tester and numeric
  converter.
- Optional Vim mode with Normal, Insert and Visual input modes, core motions
  and operators, text objects, registers, jump navigation, `:` commands, and
  confirmed shell execution or selection filtering through `:!command`.
- Markup shortcuts for both Markdown and LaTeX, table alignment, environment
  and tag wrapping, LaTeX environment pairing and synchronized environment
  renaming.
- Encoding and line-ending detection, external modification handling, backup,
  autosave and recovery of unsaved buffers.

### Navigation, search and large files

- Command Palette (`Ctrl+Shift+P`) with fuzzy command search.
- Goto Anything (`Ctrl+Shift+G`) for open files, `:line`, `@symbol` and
  `>command` navigation.
- Find/Replace with Python regular expressions and capture-group substitution.
- Search across open tabs and recursive search/replace on files on disk.
- Bookmarks, five-color marks, go-to-line and matching-bracket navigation.
- Horizontal and vertical split view, cloned tabs and MRU tab switching
  (`Ctrl+Tab`).
- Files over 200 MB are loaded progressively in paged mode. Page navigation,
  approximate global line navigation and streaming save remain available;
  operations requiring the entire document are explicitly limited.

### LaTeX workflow

LaTeX is a first-class workflow, not only a syntax-highlighting mode.

- Root resolution follows project conventions such as `% !TEX root`,
  `.latexmkrc`, `main.tex` and included files.
- The Build Panel provides 12 built-in profiles:
  `Python`, `Python (uv)`, `C (gcc)`, `C++ (g++)`, `LaTeX (pdflatex)`,
  `LaTeX (xelatex)`, `LaTeX (lualatex)`, `Make`, `Bash`,
  `JavaScript (node)`, `Rust (cargo)` and `Go`.
- Custom profiles support `${FILE}`, `${DIR}`, `${OUTDIR}`, `${ROOT}`,
  `${BASENAME}`, `${BASEFILE}`, `${FILENAME}`, `${EXT}`, `${LINE}` and
  `${COL}`. The `$(VARIABLE)` spelling is accepted too.
- Build output can be separated from source files through `${OUTDIR}`. PDF
  preview and SyncTeX use the same project context.
- BibTeX is detected and can be forced through the supported `latexmk`
  options; Biber is discovered by `latexmk` from the project bibliography
  metadata.
- Build-on-save and debounced build-while-editing are configurable. Output,
  parsed errors, LSP diagnostics and build navigation are available in the
  integrated panels.
- The Function List understands sections, subsections, commands, labels,
  references and included files, with hierarchical navigation.
- LaTeX completion covers commands, environments, packages, labels,
  references, citations and bibliography keys across project files.
- The LaTeX Wizard handles equations, environments and content-filled tables;
  Quick Table handles visual table layout, borders and cell merges.
- Dropping an image into a LaTeX document opens the figure assistant and
  generates project-relative `\includegraphics` code with optional figure,
  caption and label syntax.
- Templates include article, report and Beamer variants. User and project
  templates can be placed under `.notepadpq/templates`.
- SyncTeX connects editor positions and PDF positions in both directions.

#### LaTeX quick start

Install a TeX distribution separately from NotePadPQ. On Debian/Ubuntu, a
typical setup is:

```bash
sudo apt install latexmk texlive-latex-extra biber
python -m pip install -e ".[latex]"
```

The exact package names vary by distribution. Ensure that the selected engine
(`pdflatex`, `xelatex` or `lualatex`), `latexmk`, `bibtex` or `biber`, and
`synctex` are available on `PATH`. Then open the root `.tex` file and use the
LaTeX profile from the Build Panel. The project manual contains the complete
LaTeX reference and troubleshooting notes.

On Arch Linux, the optional project tools can be installed with:

```bash
sudo pacman -S biber perl-yaml-tiny perl-file-homedir texlab
```

`perl-yaml-tiny` and `perl-file-homedir` are required by `latexindent`;
`texlab` enables LSP features, while NotePadPQ retains local LaTeX fallbacks
without it.

### Build Panel and task runner

- Built-in and user-defined profiles with per-profile environment variables.
- Pre-build and post-build hooks, sequential pipelines and independent
  concurrent build workers.
- Automatic task discovery from Makefile, `package.json`, `pyproject.toml`,
  `Cargo.toml`, `CMakeLists.txt`, Gradle, Docker Compose, Dockerfile and
  `justfile`.
- Interactive PTY mode for programs such as `npm init`, `ssh`, Python REPLs
  and other terminal applications.
- Configurable output limits to protect memory on very large logs.
- Clickable error lists that jump to the relevant file and line.
- Optional build-on-save and build-while-editing with debounce.

### Preview and PDF tools

- Live Markdown, HTML and reStructuredText preview.
- LaTeX structure preview without requiring a compiler.
- Integrated PDF viewer with thumbnails, zoom, continuous scrolling, search,
  text selection/copy, keyboard result navigation and printing.
- Image hover preview for LaTeX, Markdown and HTML image references, including
  vector PDF images when the optional PDF stack is available.
- Equation rendering for LaTeX and Markdown hover previews. MathJax can render
  formulas in the live Markdown preview when network access is available.
- Mermaid blocks in Markdown can be rendered through Mermaid.js when enabled
  and network access is available.
- Smart PDF crop, page navigation and PDF export workflows.
- Optional external PDF viewer command with a safe `{PDF}` placeholder, while
  the system default remains the fallback.

### LSP and integrated development tools

The native LSP client supports diagnostics, hover documentation, completion,
go-to-definition, references, rename and formatting where the selected server
provides the capability.

Supported server mappings include:

| Language | Server |
|---|---|
| Python | `pylsp` |
| C/C++ | `clangd` |
| Rust | `rust-analyzer` |
| Go | `gopls` |
| JavaScript/TypeScript | `typescript-language-server` |
| LaTeX | `texlab` |

Servers are external programs and must be installed separately. The integrated
terminal uses a native PTY where supported and follows the current editor
directory. Git, formatter, REST and task-runner functionality is available from
dedicated panels or plugins.

### Plugins

The plugin system includes the following integrated extensions:

| Plugin | Scope |
|---|---|
| **AI Assistant** | Multi-provider chat, streaming, contextual actions, attachments, token estimates, regeneration and inline diffs |
| **LanguageTool locale** | Optional LanguageTool Standalone server, live grammar/style diagnostics and contextual replacements; LaTeX prose is checked with markup masked |
| **Clipboard History** | Persistent multi-entry clipboard with quick selection |
| **Compare & Merge** | Editable three-way comparison, character-level diff and synchronized scrolling |
| **Code Formatter** | Python, JS/TS/HTML/CSS, C/C++, Rust, Go, JSON and XML formatting; optional format-on-save |
| **Database** | SQLite, PostgreSQL, MySQL/MariaDB and Oracle browser/query workflows with spreadsheet results |
| **Encrypt/Decrypt** | AES-256-GCM and ChaCha20-Poly1305 when `cryptography` is installed, with lighter fallback tools |
| **FTP Browser** | FTP/SFTP browsing, SSH terminal and SMB mount helpers where supported by the operating system |
| **Git Integration** | Status, log, diff, branches and PR/MR workflows |
| **Hex Viewer** | Binary file inspection in hexadecimal form |
| **REST Client** | HTTP/REST requests, OAuth 2.0, multipart uploads, scripts, assertions, collections and code snippets |
| **Rich Text Editor** | WYSIWYG editing for DOC/DOCX/ODT/RTF/HTML through optional conversion tools |
| **Search PQ** | Advanced multi-file search and replacement with text, AND/NOT, regexp and LIKE modes |
| **Spreadsheet** | CSV, TSV, XLSX, XLS, XLSM and ODS editing with filters, formulas, charts and export |
| **Terminal** | Native PTY/xterm.js terminal panel synchronized with the current file directory |
| **Web Search** | Web and Wikipedia search from selected editor text |

### Interface and customization

- Six interface languages: Italian, English, German, French, Spanish and
  Polish.
- Built-in themes, live theme editor and JSON import/export.
- Lucide, Material and system icon sets.
- Spell checking with independently selectable dictionary language.
- Smart typography, paragraph focus, Markdown task toggling and YAML front
  matter highlighting.
- Plain-text mode, distraction-free writing mode (`F11`), session restore and
  single-instance file opening.
- New interface languages can be added by placing a translated JSON file in
  `i18n/`; preserve the existing JSON keys and metadata format.

## Installation

### AppImage on Linux

Download the latest AppImage from the [GitHub releases page](https://github.com/buzzqw/NotePadPQ/releases/latest),
make it executable and run it:

```bash
chmod +x NotePadPQ-*.AppImage
./NotePadPQ-*.AppImage
```

The AppImage bundles the Python and Qt runtime. External tools such as a TeX
distribution, LSP servers and system formatters remain separate by design.

### Recommended source installation

```bash
git clone https://github.com/buzzqw/NotePadPQ.git
cd NotePadPQ
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
notepadpq
```

On Windows, use `py -m venv .venv` and `.venv\\Scripts\\activate`. On Linux,
FreeBSD and macOS, use the corresponding Python 3 executable. The repository
also contains `setup.sh`, which creates a virtual environment and interactively
offers optional components; run it from a Bash-compatible shell.

### Optional Python components

The optional groups are declared in `pyproject.toml` and can be combined:

```bash
python -m pip install -e ".[latex,spreadsheet,richtext,database,ftp,encrypt,formatter,restclient]"
```

| Extra | Enables | Main packages |
|---|---|---|
| `latex` | PDF hover, equation rendering and advanced LaTeX preview | `pymupdf`, `matplotlib`, `sympy` |
| `spreadsheet` | XLSX/XLS/ODS workflows | `openpyxl`, `xlrd`, `odfpy` |
| `richtext` | WYSIWYG and document conversion | `mammoth`, `htmldocx`, `pypandoc` |
| `database` | PostgreSQL, MySQL/MariaDB and Oracle connectors | `psycopg2-binary`, `mysql-connector-python`, `oracledb` |
| `ftp` | SFTP support | `paramiko` |
| `encrypt` | Strong encryption algorithms | `cryptography` |
| `formatter` | Python formatters | `black`, `ruff` |
| `restclient` | Advanced HTTP features | `requests` |
| `git` | GitHub/GitLab workflows and token storage | `PyGithub`, `python-gitlab`, `keyring` |
| `dev` | Test tooling | `pytest`, `pytest-qt` |

`requirements.txt` is a compatibility entry point for builds that need every
application feature (`.[all]`); dependency versions and extras are defined only
in `pyproject.toml`.

Some plugins also use system tools. Pandoc and LibreOffice are needed for
selected document conversions; Prettier, `clang-format`, `rustfmt` and `gofmt`
are installed through their respective ecosystems.

### LSP servers

Install only the servers for the languages you use. Examples:

```bash
python -m pip install python-lsp-server
npm install -g typescript-language-server typescript
```

Install `clangd`, `rust-analyzer`, `gopls` and `texlab` through the official
package or release mechanism for your operating system.

## Screenshots

### LaTeX editor, Function List, PDF preview and Build Panel

<img width="1920" alt="LaTeX editor with Function List, PDF preview and Build Panel" src="immagini/notepadpq11.png" />

### Markdown preview, Function List and Search PQ

<img width="1920" alt="Markdown live preview with Function List and Search PQ" src="immagini/notepadpq10.png" />

### Plugin ecosystem

<img width="1920" alt="NotePadPQ plugin menu" src="immagini/notepadpq09.png" />

Additional screenshots for PDF, spreadsheet, rich text and database workflows
are available in the [manual](MANUAL_EN.md).

## Documentation

- [English user manual](MANUAL_EN.md): complete interface reference, shortcuts,
  preferences, plugins, LSP and LaTeX documentation.
- [Manuale italiano](MANUAL_IT.md): riferimento completo in italiano.
- [Windows build system](windowsbuild/README.md): PyInstaller and installer
  workflows.

## Development

### Performance diagnostics

To identify slow operations or UI freezes, start NotePadPQ with the optional
profiler:

```bash
python main.py --profile
```

The log path is printed to the terminal and is normally
`~/.config/NotePadPQ/notepadpq-performance.log`. The log contains I/O,
loads, saves, slow Qt events, main-loop delays and a per-operation summary when
the application exits. To lower the default 100 ms threshold:

```bash
NOTEPADPQ_PROFILE_THRESHOLD_MS=25 python main.py --profile
```

It can also be enabled with `NOTEPADPQ_PROFILE=1`. Document contents, queries
and document values are not recorded.

Install development dependencies and run the test suite:

```bash
python -m pip install -e ".[dev]"
pytest -q
python -m compileall -q core editor ui plugins config i18n
```

The project uses `pyproject.toml` for package metadata, optional dependency
groups, pytest configuration and Ruff settings. Contributions should preserve
the existing test coverage and avoid committing credentials, generated build
artifacts or user configuration.

## License and support

NotePadPQ is released under the [EUPL-1.2](EUPL-1.2%20EN.txt). Issues,
feature requests and contributions are welcome on [GitHub](https://github.com/buzzqw/NotePadPQ).

If NotePadPQ is useful to you, you can support development through
[PayPal](https://www.paypal.com/cgi-bin/webscr?cmd=_donations&business=azanzani@gmail.com&item_name=Support+NotePadPQ+Project).

## Italiano

NotePadPQ è un ambiente desktop open source e multipiattaforma per sviluppo,
scrittura tecnica, LaTeX, Markdown, dati e lavoro assistito dall'AI. Non è
soltanto un editor: integra pannelli per compilazione, anteprima PDF/Markdown,
SyncTeX, LSP, terminale, Git, REST, database, fogli di calcolo, rich text e un
sistema di plugin estendibile.

Le aree principali sono:

- editor QScintilla/Pygments per oltre 40 linguaggi, autocomplete, macro,
  multi-cursore, modalità Vim opzionale, minimap, split view e recupero
  sessione;
- workflow LaTeX completo con root project, `latexmk`, BibTeX/Biber, Function
  List gerarchica, template, diagnostica, PDF preview e SyncTeX bidirezionale;
- Build Panel con 12 profili built-in, profili personalizzati, variabili,
  pipeline, task discovery, PTY, build concorrenti e lista errori cliccabile;
- anteprima live Markdown/HTML/reStructuredText, visualizzatore PDF, hover di
  immagini/equazioni e diagrammi Mermaid opzionali;
- plugin AI, Git, terminale, database, spreadsheet, rich text, REST, FTP,
  Search PQ, formatter, encrypt/decrypt, hex viewer e web search.

Per installazione, scorciatoie, preferenze, configurazione LaTeX, plugin e
risoluzione dei problemi, consulta il [Manuale italiano completo](MANUAL_IT.md).
Il [Manuale inglese](MANUAL_EN.md) contiene la stessa copertura tecnica e gli
esempi aggiornati.

### Avvio rapido in italiano

```bash
git clone https://github.com/buzzqw/NotePadPQ.git
cd NotePadPQ
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python main.py
```

Per il supporto LaTeX installa anche una distribuzione TeX con `latexmk`, un
engine (`pdflatex`, `xelatex` o `lualatex`), BibTeX/Biber e SyncTeX; per le
funzionalità PDF avanzate aggiungi `python -m pip install -e ".[latex]"`.

**[Torna all'inizio](#notepadpq)**

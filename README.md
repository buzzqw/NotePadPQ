<img width="1920" alt="NotePadPQ" src="immagini/NotePadPQ.png" />

<div align="center">

<img src="icons/NotePadPQ_128.png" alt="NotePadPQ Logo" width="96"/>

# NotePadPQ

**A modern, cross-platform text editor built with Python and PyQt6, featuring advanced editing tools, AI support, live document previews and many tools.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.x-green?logo=qt)](https://riverbankcomputing.com/software/pyqt/)
[![License](https://img.shields.io/badge/License-EUPL%201.2-blue.svg)](EUPL-1.2%20EN.txt)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20FreeBSD-lightgrey)]()
[![Version](https://img.shields.io/badge/Version-1.1.9-orange)]()

[🇬🇧 English](#-english) · [🇮🇹 Italiano](#-italiano) · [💖 Dona / Donate](https://www.paypal.com/donate/?business=azanzani%40gmail.com&currency_code=EUR)

</div>

---


# 🇬🇧 English

## What is NotePadPQ?

NotePadPQ is an advanced, free and open source text editor built with **Python 3**, **PyQt6**, and **QScintilla**. Inspired by Notepad++ but cross-platform and modern, it offers a professional feature set without sacrificing performance.

Runs natively on Linux, Windows, and FreeBSD.

---

## ✨ Key Features

### 📝 Advanced Editor
- **Syntax highlighting** for 40+ languages: native QScintilla lexers (Python, JavaScript, TypeScript, C/C++, Java, C#, Bash, SQL, LaTeX, Markdown, HTML, CSS, XML, JSON, YAML, Ruby, Perl, Lua, Pascal, Fortran, Verilog…) plus Pygments-backed lexers (Go, Rust, PHP, Swift, Kotlin, Scala, Dart, R, TOML, Haskell, Elixir, Julia). **Auto-detect** from extension, filename, or content.
- **Code folding**: collapse code blocks, classes, and functions from the gutter.
- **Smart Highlight**: all occurrences of the word under the cursor are highlighted automatically, with no typing lag.
- **Dynamic line numbers**: column width adapts to file size automatically.
- **Minimap** sidebar for quick navigation in long files.
- **Word wrap** configurable (`Alt+Z`).
- **Smart autocomplete**: words in document, per-language snippets, API dictionaries, LSP support.
- **Auto-close** brackets, quotes, and tags.
- **Show whitespace/tabs** and end-of-line characters.
- **Markup shortcuts**: `Ctrl+B` (Bold), `Ctrl+I` (Italic), `Ctrl+Shift+X` (Strikethrough): work natively in Markdown (`**`, `*`, `~~`) and LaTeX (`\textbf`, `\textit`, `\sout`).

### 🗂️ Tab Management & Split View
- **Multiple tabs** with drag & drop, modification indicator, session restore at startup.
- **Horizontal and vertical split view** (`Ctrl+Alt+2` / `Ctrl+Alt+3`).
- **Clone tab** to work on the same file at two positions simultaneously.
- **Project Manager** (PSPad-style): group files into named projects saved as `.npqproj` (JSON); toolbar to create groups, add/remove files; double-click to open.

### 🔍 Search, Navigation & Command Palette
- **Command Palette** (`Ctrl+Shift+P`): fuzzy-search over all editor commands.
- **Goto Anything** (`Ctrl+Shift+G`): Sublime-style quick navigation: open files, `:line`, `@symbol`, `>command`.
- Find/Replace with full **regular expressions** (Python syntax) and capture group substitution.
- **Search across all open tabs** simultaneously.
- **Search in files** on disk with extension filter and recursive search.
- **Inline incremental search** (`Ctrl+Shift+F2`).
- **Go to line** (`Ctrl+G`) and jump to matching bracket.
- **Bookmarks**: add (`Ctrl+F2`), navigate (`F2` / `Shift+F2`), remove.
- **5-color Mark** system for highlighting blocks of text (`Ctrl+1..5`).

### 🛠️ Editing Tools
- **Multi-cursor**: select next occurrence (`Ctrl+D`), all occurrences (`Ctrl+Shift+D`), add cursor above/below (`Ctrl+Alt+↑↓`), insert incremental numbers.
- **Macros**: record, save, load, and run N times.
- **Case conversion**: UPPERCASE, lowercase, Title Case, Invert Case.
- **Comment/uncomment** lines (`Ctrl+E`) with automatic language detection.
- **Smart indentation**, tabs↔spaces. **Auto-indent on paste**: pasted lines align automatically to the cursor context.
- **Sort lines** by 5 criteria: alphabetical, reverse, by length, random.
- **Word frequency**: occurrence analysis on the document or selection.
- **Table alignment** for Markdown/LaTeX, **wrap in environment/tag**.
- **Color Translator**: pick a color and get HTML/CSS name, `#HEX`, `rgb()`, `rgb(%)`, `hsl()`: insert or copy each format individually.
- **Lorem Ipsum generator**: insert placeholder text with configurable paragraphs, sentences, and separator.
- Interactive regex tester, numeric converter (dec/hex/bin/oct).

### 🏗️ Build Panel
- Configurable **build profiles** per language (LaTeX, Python, C/C++, Markdown, etc.).
- **Command variables**: `${FILE}` (full path), `${DIR}` (directory), `${BASENAME}` (name without extension), `${BASEFILE}` (full path without extension), `${FILENAME}`, `${EXT}`, `${LINE}`, `${COL}`. Also accepted as `$(VAR)`.
- Real-time output with **clickable error list**; click an error to jump directly to the line.
- **Automatic PDF detection**: the preview button activates instantly if a compiled PDF is already present.
- **Auto-save** before compilation.

### 👁️ Preview Panel
- **Live preview** for Markdown, HTML, reStructuredText, LaTeX (structure), PDF.
- **Hover preview**: mouse over `\includegraphics{...}`, `![img](...)`, or `<img src="...">` to see a floating image thumbnail (including vector PDF).
- **Math equation rendering** on hover in LaTeX/Markdown files (`$...$`, `$$...$$`, `\[...\]`).
- **SyncTeX**: bidirectional sync between editor cursor and PDF position.
- **Smart Crop**: auto-trim PDF white margins (`✂`).
- Zoom with `Ctrl+Wheel`, page navigation with the scroll wheel.

### 💻 Integrated Terminal (plugin)
- Full terminal based on **native PTY** as an independent dock panel (`Ctrl+Alt+T` from the Plugin menu).
- Supports any interactive program: vim, Python REPL, ssh, git, compilers.
- Automatically syncs with the directory of the file open in the editor.
- No external dependencies; works on all supported platforms.

### ⚡ LSP: Language Server Protocol

Native Language Server integration: real-time errors/warnings, hover documentation, go to definition, find references, rename symbol, format document.

Supported servers: `pylsp` (Python), `clangd` (C/C++), `rust-analyzer` (Rust), `gopls` (Go), `typescript-language-server` (TS/JS), `texlab` (LaTeX).

### ⚡ Task Runner

Dedicated tab in the bottom panel with auto-discovery of project tasks (Makefile, `npm scripts`, `pyproject.toml`) and a field for arbitrary manual commands.

### 🤖 AI Assistant (plugin)

Dock panel with multi-provider AI chat:

| Provider | Special features |
|---|---|
| **Anthropic Claude** | SSE streaming, Extended Thinking (Opus), **dynamic model list** from the API key |
| **OpenAI** | GPT-4o, GPT-4o-mini, o3-mini |
| **Google Gemini** | gemini-2.0-flash, gemini-1.5-pro |
| **Ollama** | Local models auto-detected (no key, no cost) |

Contextual actions (Explain, Refactor, Docstring, Fix bug, Unit tests, Review) directly from right-click in the editor. Bring-your-own-key; each provider has its own configurable API key.

### 🔌 Plugin System

<img width="1920" alt="Plugin menu" src="immagini/notepadpq09.png" />

*The Plugins menu displays the full extension ecosystem available*

| Plugin | Function |
|--------|----------|
| **AI Assistant** | Multi-provider AI chat with streaming, Extended Thinking, and dynamic model list |
| **Clipboard History** | Multi-entry clipboard with quick selection |
| **Compare & Merge** | Visual side-by-side file comparison |
| **Database** | Browser and query editor for SQLite, PostgreSQL, MySQL/MariaDB with AI SQL generation |
| **Encrypt/Decrypt** | AES-256-GCM and ChaCha20-Poly1305 encryption |
| **Rich Text Editor** | WYSIWYG editor for .doc, .docx, .odt, .rtf, .html powered by Jodit 4 |
| **Spreadsheet** | Full CSV, TSV, XLSX, XLS, XLSM, ODS editor with sort, filter, formulas, and charts |
| **FTP Browser** | Browse and edit files on FTP servers |
| **Git Integration** | Full Git panel: status, log, diff, branch, PR/MR |
| **Hex Viewer** | Hexadecimal view of binary files |
| **Search PQ** | Dock panel for advanced search and replace: TEXT mode (AND/NOT), regexp, LIKE; result queue, inline filter, context menu (`Ctrl+Alt+F`) |
| **Terminal** | xterm.js+PTY terminal as an independent dock panel, synced with the open file's directory (`Ctrl+Alt+T`) |
| **Web Search** | Web and Wikipedia search on selected text directly from the context menu |

### 🌍 Interface
- **6 languages**: Italian, English, German, French, Spanish, Polish; switch at runtime.
- **17 built-in themes** + theme editor with live preview; import/export JSON.
- **Icon sets**: Lucide, Material, System; auto-downloaded on first use.
- **Live clock** in the menu bar with localized date and time.
- **Spell checker** (`F4`): real-time spell checking with red squiggles for IT, EN, DE, FR, ES. Dictionary language is selectable independently from the UI language (Document → Dictionary Language). Right-click a highlighted word for suggestions, "Add to dictionary", or "Ignore all".
- **Plain text mode** (`Ctrl+Alt+N`): disable highlighting, brace matching and autocomplete per tab, restorable in one click.
- **Distraction-free writing mode** (`F11`): fullscreen with toolbar, statusbar, menubar, and panels hidden. Fully restored on exit.
- **Session restore**: all files, cursor positions, and panel layout restored at startup. Optional auto-save on focus loss.
- **Single instance**: opening files from the file manager sends them to the running window.

---

## 🚀 Installation

### Automated Setup (recommended)

```bash
git clone https://github.com/buzzqw/NotePadPQ.git
cd NotePadPQ
bash setup.sh
python main.py
```

### Manual Installation

**Core dependencies** (always required):
```bash
pip install PyQt6 PyQt6-QScintilla PyQt6-WebEngine chardet markdown docutils pygments pyspellchecker PyGithub python-gitlab keyring
```

**Rich Text Editor plugin** (optional):
```bash
pip install mammoth htmldocx   # DOCX read/write
# pandoc: system-level install for ODT/RTF
# libreoffice: system-level install for .doc (Word 97-2003)
```

**Database plugin** (optional):
```bash
pip install psycopg2-binary    # PostgreSQL
pip install pymysql            # MySQL/MariaDB
pip install cx_Oracle          # Oracle
# SQLite: included in Python standard library
```

**LaTeX optional** (only if you write/compile LaTeX):
```bash
pip install pymupdf matplotlib sympy
# synctex: included in TeX Live
```

> If you already have TeX Live for LaTeX compilation, all advanced LaTeX features (PDF hover preview, equation rendering, SyncTeX) activate automatically.

---

---

## 🌐 Adding a New Language

NotePadPQ automatically detects available languages by scanning `*.json` files in the `i18n/` folder.
To add a new language (e.g. Polish), just:

1. Copy `i18n/en.json` to `i18n/pl.json`
2. Edit the `meta` field in the new file:
   ```json
   "meta": {
     "language": "pl",
     "name": "Polski",
     "version": "1.0",
     "authors": ["Your name"]
   }
   ```
3. Translate all string values in the file (do not change the JSON keys)
4. Start NotePadPQ: the new language will appear automatically in **Preferences → Interface Language**

No source code changes are needed: the i18n engine discovers languages from the files present in the folder.

## 💖 Support the project

NotePadPQ is developed in spare time with passion. If you find it useful, consider a small donation; it helps keep the project alive.

<div align="center">

[![Donate with PayPal](https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif)](https://www.paypal.com/donate/?business=azanzani%40gmail.com&currency_code=EUR)

</div>

---

<div align="center">

Fatto con ❤️ in Italia · Made with ❤️ in Italy

**[⬆ Torna su / Back to top](#notepadpq)**

</div>

---

# 🇮🇹 Italiano

## Cos'è NotePadPQ?

NotePadPQ è un editor di testo avanzato, libero e open source, pensato per sviluppatori, scrittori tecnici e appassionati. Ispirato alla potenza di Notepad++ ma costruito con tecnologie moderne e multipiattaforma, offre un'interfaccia pulita e un set di funzionalità professionale, senza rinunciare alla leggerezza.

Scritto interamente in **Python 3** con **PyQt6** e **QScintilla**, gira nativamente su Linux, Windows e FreeBSD.

---

## ✨ Funzionalità principali

### 📝 Editor avanzato
- **Syntax highlighting** per oltre 40 linguaggi: lexer nativi QScintilla (Python, JavaScript, TypeScript, C/C++, Java, C#, Bash, SQL, LaTeX, Markdown, HTML, CSS, XML, JSON, YAML, Ruby, Perl, Lua, Pascal, Fortran, Verilog…) più lexer Pygments per Go, Rust, PHP, Swift, Kotlin, Scala, Dart, R, TOML, Haskell, Elixir, Julia. La voce **Automatico** nel menu rileva il linguaggio da estensione, nome file e contenuto.
- **Code folding**: collassa blocchi di codice, classi e funzioni direttamente nel margine.
- **Smart Highlight**: al posizionamento del cursore su una parola, tutte le sue occorrenze vengono evidenziate automaticamente in tutto il documento, in modo fluido e senza rallentare la digitazione.
- **Numeri di riga dinamici**: la larghezza si adatta automaticamente alla dimensione del file.
- **Minimap** laterale per navigazione rapida nei file lunghi.
- **Word wrap** configurabile (`Alt+Z`).
- **Autocompletamento** intelligente: parole nel documento, snippet per linguaggio, dizionari API, supporto LSP.
- **Auto-chiusura** di parentesi, virgolette e tag.
- **Mostra spazi/tab** e caratteri di fine riga.
- **Scorciatoie Markup**: `Ctrl+B` (Grassetto), `Ctrl+I` (Corsivo), `Ctrl+Shift+X` (Barrato): funzionano in Markdown (`**`, `*`, `~~`) e LaTeX (`\textbf`, `\textit`, `\sout`).

### 🗂️ Gestione tab e split view
- **Tab multipli** con drag & drop, indicatore di modifica, ripristino sessione all'avvio.
- **Split view** orizzontale e verticale (`Ctrl+Alt+2` / `Ctrl+Alt+3`).
- **Clona tab** per lavorare sulla stessa vista in due posizioni.
- **Gestione Progetti** stile PSPad: raggruppa file in progetti salvati come `.npqproj` (JSON); toolbar per creare gruppi, aggiungere/rimuovere file; doppio clic per aprire.

### 🔍 Ricerca, navigazione e palette comandi
- **Command Palette** (`Ctrl+Shift+P`): accesso fuzzy-search a tutti i comandi dell'editor.
- **Goto Anything** (`Ctrl+Shift+G`): navigazione rapida stile Sublime: file aperti, `:riga`, `@simbolo`, `>comando`.
- Trova/Sostituisci con **espressioni regolari** (sintassi Python completa) e sostituzione con gruppi di cattura.
- **Cerca in tutti i file** aperti nei tab contemporaneamente.
- **Cerca nei file** su disco con filtro estensione e ricerca ricorsiva.
- **Ricerca incrementale** inline (`Ctrl+Shift+F2`).
- **Vai alla riga** (`Ctrl+G`) e vai alla parentesi corrispondente.
- **Bookmark** su righe: aggiungi (`Ctrl+F2`), naviga (`F2` / `Shift+F2`), rimuovi.
- **Mark con 5 colori** distinti per evidenziare blocchi (`Ctrl+1..5`).

### 🛠️ Strumenti di editing
- **Multi-cursore**: seleziona occorrenza successiva (`Ctrl+D`), tutte le occorrenze (`Ctrl+Shift+D`), aggiungi cursore sopra/sotto (`Ctrl+Alt+↑↓`), inserisci numeri incrementali.
- **Macro**: registra, salva, carica ed esegui N volte.
- **Conversione caso**: MAIUSCOLO, minuscolo, Title Case, Invert Case.
- **Commenta/decommenta** righe (`Ctrl+E`) con rilevamento automatico del linguaggio.
- **Indentazione** smart, tabs↔spazi. **Auto-indenta su incolla**: le righe incollate si riallineano automaticamente al contesto del cursore.
- **Ordina righe** con 5 criteri: alfabetico, inverso, per lunghezza, casuale.
- **Frequenza parole**: analisi delle occorrenze sul documento o sulla selezione.
- **Allineamento tabelle** Markdown/LaTeX, **avvolgimento** in ambienti/tag.
- **Traduttore colori**: seleziona un colore e ottieni immediatamente nome HTML/CSS, `#HEX`, `rgb()`, `rgb(%)`, `hsl()`: pulsante inserisci/copia per ogni formato.
- **Generatore Lorem Ipsum**: inserisce testo segnaposto con opzioni (paragrafi, frasi, separatore, primo paragrafo classico).
- Tester regex interattivo, convertitore numerico (dec/hex/bin/oct).

### 🏗️ Pannello Build
- **Profili di build** configurabili per linguaggio (LaTeX, Python, C/C++, Markdown, ecc.).
- **Variabili nei comandi**: `${FILE}` (percorso completo), `${DIR}` (cartella), `${BASENAME}` (nome senza estensione), `${BASEFILE}` (percorso senza estensione), `${FILENAME}`, `${EXT}`, `${LINE}`, `${COL}`. Accettate anche nella forma `$(VAR)`.
- **Output in tempo reale** con lista errori cliccabile; click su un errore salta direttamente alla riga.
- **Rilevamento PDF automatico**: il pulsante anteprima si abilita istantaneamente se è presente un PDF già compilato.
- **Salvataggio automatico** prima della compilazione.

### 👁️ Pannello Anteprima
- **Anteprima live** di Markdown, HTML, reStructuredText, LaTeX (struttura), PDF.
- **Hover preview**: passa il mouse su `\includegraphics{...}`, `![img](...)` o `<img src="...">` per vedere l'anteprima dell'immagine in un popup; supporta anche i PDF vettoriali.
- **Rendering equazioni** matematiche inline con hover (file LaTeX/Markdown con `$...$`, `$$...$$`, `\[...\]`).
- **SyncTeX**: sincronizzazione bidirezionale cursore editor ↔ posizione nel PDF.
- **Smart Crop**: elimina automaticamente i margini bianchi dei PDF (`✂`).
- Zoom con `Ctrl+Rotella`, navigazione pagine con la rotella.

### 💻 Terminale integrato (plugin)
- Terminale completo basato su **PTY nativo** come pannello dock indipendente (`Ctrl+Alt+T` dal menu Plugin).
- Supporta qualsiasi programma interattivo: vim, python REPL, ssh, git, compilatori.
- Si sincronizza automaticamente con la directory del file aperto nell'editor.
- Nessuna dipendenza esterna; funziona su tutti i sistemi supportati.

### ⚡ LSP: Language Server Protocol

Integrazione nativa con i Language Server: errori/warning in tempo reale, hover con documentazione, vai alla definizione, mostra riferimenti, rinomina simbolo, formatta documento.

Server supportati: `pylsp` (Python), `clangd` (C/C++), `rust-analyzer` (Rust), `gopls` (Go), `typescript-language-server` (TS/JS), `texlab` (LaTeX).

### ⚡ Task Runner

Tab dedicato nel pannello inferiore con auto-scoperta dei task dal progetto (Makefile, `npm scripts`, `pyproject.toml`) e campo per comandi manuali arbitrari.

### 🤖 AI Assistant (plugin)

Panel dock con chat AI multi-provider:

| Provider | Funzionalità speciali |
|---|---|
| **Anthropic Claude** | Streaming SSE, Extended Thinking (Opus), **lista modelli dinamica** dalla chiave API |
| **OpenAI** | GPT-4o, GPT-4o-mini, o3-mini |
| **Google Gemini** | gemini-2.0-flash, gemini-1.5-pro |
| **Ollama** | Modelli locali rilevati automaticamente (nessuna chiave, nessun costo) |

Azioni contestuali (Spiega, Refactoring, Docstring, Correggi bug, Test unitari, Review) direttamente da tasto destro nell'editor. Bring-your-own-key; ogni provider ha la propria chiave configurabile.

### 🔌 Sistema Plugin

<img width="1920" alt="Plugin menu" src="immagini/notepadpq09.png" />

*Il menu Plugins mostra l'intero ecosistema di estensioni disponibili*

| Plugin | Funzione |
|--------|----------|
| **AI Assistant** | Chat AI multi-provider con streaming, Extended Thinking e lista modelli dinamica |
| **Clipboard History** | Cronologia degli appunti con selezione rapida |
| **Compare & Merge** | Confronto visuale side-by-side tra due file o versioni |
| **Database** | Browser e query editor per SQLite, PostgreSQL, MySQL/MariaDB con AI SQL generation |
| **Editor Rich Text** | Editor WYSIWYG per .doc, .docx, .odt, .rtf, .html basato su Jodit 4 |
| **Encrypt/Decrypt** | Cifratura/decifratura con AES-256-GCM e ChaCha20-Poly1305 |
| **Foglio di Calcolo** | Editing completo di CSV, TSV, XLSX, XLS, XLSM, ODS con ordinamento, filtro, formule e grafici |
| **FTP Browser** | Navigazione e modifica file su server FTP |
| **Git Integration** | Stato repo, commit, diff, branch, PR/MR direttamente dall'editor |
| **Hex Viewer** | Visualizzazione esadecimale dei file binari |
| **Search PQ** | Pannello dock per ricerca e sostituzione avanzata: modalità TEXT (AND/NOT), regexp, LIKE; coda di risultati, filtro inline, contesto menu (`Ctrl+Alt+F`) |
| **Terminal** | Terminale xterm.js+PTY come pannello dock indipendente, sincronizzato con la directory del file aperto (`Ctrl+Alt+T`) |
| **Web Search** | Ricerca web e Wikipedia sul testo selezionato direttamente dal menu contestuale |

### 🌍 Interfaccia e UI
- **Multilingua**: 6 lingue (Italiano, English, Deutsch, Français, Español, Polski) cambiabili a caldo.
- **Temi**: 17 temi integrati + editor di temi con anteprima live; importa/esporta in JSON.
- **Set icone**: Lucide, Material, Sistema; download automatico al primo utilizzo.
- **Orologio live** nella barra dei menu con data e ora localizzate.
- **Controllo ortografico** (`F4`): spell checker in tempo reale con sottolineatura rossa per IT, EN, DE, FR, ES. Lingua del dizionario selezionabile indipendentemente dalla lingua dell'interfaccia (Documento → Lingua dizionario). Click destro su una parola evidenziata per suggerimenti, "Aggiungi al dizionario" o "Ignora tutto".
- **Modalità testo semplice** (`Ctrl+Alt+N`): disabilita highlighting, brace matching e autocomplete per tab, ripristinabile in un click.
- **Modalità scrittura distraction-free** (`F11`): schermo intero senza toolbar, statusbar, menubar né pannelli. Ripristino completo all'uscita.
- **Sessioni**: ripristino automatico all'avvio di tutti i file, posizioni cursore e layout pannelli. Auto-save opzionale su perdita del fuoco.
- **Istanza singola**: aprire un file da file manager lo invia alla finestra già aperta.

---

## 🚀 Installazione

### Setup automatico (consigliato)

```bash
git clone https://github.com/buzzqw/NotePadPQ.git
cd NotePadPQ
bash setup.sh
python main.py
```

Lo script rileva il sistema operativo (Arch Linux, apt, dnf, Windows) e installa le dipendenze base in modo nativo.

### Installazione manuale

**Dipendenze base** (sempre richieste):
```bash
pip install PyQt6 PyQt6-QScintilla PyQt6-WebEngine chardet markdown docutils pygments pyspellchecker PyGithub python-gitlab keyring
```

**Plugin Editor Rich Text** (opzionali):
```bash
pip install mammoth htmldocx   # lettura/scrittura DOCX
# pandoc: installazione di sistema per ODT/RTF
# libreoffice: installazione di sistema per file .doc (Word 97-2003)
```

**Plugin Database** (opzionali):
```bash
pip install psycopg2-binary    # PostgreSQL
pip install pymysql            # MySQL/MariaDB
pip install cx_Oracle          # Oracle
# SQLite: incluso in Python standard library
```

**Dipendenze LaTeX** (opzionali, solo se usi NotePadPQ per scrivere/compilare LaTeX):
```bash
pip install pymupdf matplotlib sympy
# synctex: incluso in TeX Live (pacchetto di sistema)
```

> Se hai già TeX Live installato per compilare LaTeX, hai già tutto il necessario. Le funzionalità LaTeX avanzate (anteprima PDF hover, rendering equazioni, SyncTeX) si attivano automaticamente se le librerie sono presenti.

### Avvio

```bash
python main.py                    # apre con sessione precedente
python main.py file1.py file2.md  # apre i file specificati
```

---

## 🖥️ Screenshot

### Editor principale

<img width="1920" alt="NotePadPQ editor" src="immagini/notepadpq2.png" />

*Editor con syntax highlighting, pannello Search PQ con risultati e coda di ricerca*

---

### 👁️ Anteprima Markdown live

<img width="1920" alt="Markdown live preview" src="immagini/notepadpq02.png" />

*Editor Markdown con anteprima live nel pannello di destra e Function List con navigazione struttura*

---

### 📄 Visualizzatore PDF

<img width="1920" alt="PDF viewer" src="immagini/pdf.png" />

*Anteprima PDF integrata con SyncTeX, zoom e navigazione pagine*

---

### 🏗️ Build Panel — LaTeX

<img width="1920" alt="Build Panel LaTeX" src="immagini/notepadpq01.png" />

*Editor LaTeX con Function List, anteprima PDF integrata, pannello Build e output di compilazione in tempo reale*

> 💡 Il Build Panel supporta profili per LaTeX, Python, C/C++, Markdown e molti altri linguaggi. Variabili come `${FILE}`, `${DIR}`, `${BASENAME}` sono espanse automaticamente nei comandi di build.

---

### 📊 Foglio di Calcolo

<img width="1920" alt="Spreadsheet" src="immagini/spreadsheet.png" />

*Plugin Foglio di Calcolo: apertura di CSV/XLSX/ODS con ordinamento, filtro e grafici*

<img width="1920" alt="Spreadsheet con filtro" src="immagini/spreadsheet2.png" />

*Filtro attivo e paginazione risultati (100 righe per pagina)*

---

### 📝 Editor Rich Text

<img width="1920" alt="Rich text DOCX" src="immagini/docx.png" />

*Editor WYSIWYG Jodit per file .doc, .docx, .odt, .rtf, .html*

<img width="1920" alt="Rich text ODT" src="immagini/odt.png" />

*Apertura file ODT con formattazione completa*

---

### 🗄️ Plugin Database

*Browser database: schema tabelle, connessioni salvate, AI SQL generation*

<img width="1920" alt="Database query" src="immagini/query.png" />

*Query editor con risultati paginati, esportazione e navigazione ◀ ▶*

---

### 🔍 Plugin Search PQ

<img width="1920" alt="Search PQ panel" src="immagini/notepadpq10.png" />

*Pannello Search PQ: ricerca multi-modalità (TEXT/REGEXP/LIKE), coda risultati, filtro inline e sostituzione*
---

## 🌐 Aggiungere una nuova lingua

NotePadPQ rileva automaticamente le lingue disponibili scansionando i file `*.json` nella cartella `i18n/`.
Per aggiungere una nuova lingua (es. polacco) è sufficiente:

1. Copiare `i18n/en.json` in `i18n/pl.json`
2. Modificare il campo `meta` del nuovo file:
   ```json
   "meta": {
     "language": "pl",
     "name": "Polski",
     "version": "1.0",
     "authors": ["Il tuo nome"]
   }
   ```
3. Tradurre tutti i valori stringa nel file (le chiavi JSON non vanno modificate)
4. Avviare NotePadPQ: la nuova lingua comparirà automaticamente nel menu **Impostazioni → Lingua**

Non è necessario modificare il codice sorgente: il sistema i18n scopre le lingue dai file presenti nella cartella.

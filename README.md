<img width="1920" height="1046" alt="NotePadPQ" src="https://github.com/user-attachments/assets/3fdb606b-aebf-4a1e-b852-2c1ed6ab364f" />

<div align="center">

<img src="icons/NotePadPQ_128.png" alt="NotePadPQ Logo" width="96"/>

# NotePadPQ

**Un editor di testo avanzato, moderno e multipiattaforma — costruito con Python e PyQt6**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.x-green?logo=qt)](https://riverbankcomputing.com/software/pyqt/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey)]()
[![Version](https://img.shields.io/badge/Version-0.1.0-orange)]()

[🇮🇹 Italiano](#-italiano) · [🇬🇧 English](#-english) · [💖 Dona / Donate](#-supporta-il-progetto--support-the-project)

</div>

---

# 🇮🇹 Italiano

## Cos'è NotePadPQ?

NotePadPQ è un editor di testo avanzato, libero e open source, pensato per sviluppatori, sistemisti, scrittori tecnici e appassionati. Ispirato alla potenza di Notepad++ ma costruito con tecnologie moderne e multipiattaforma, offre un'interfaccia pulita e un set di funzionalità professionale — senza rinunciare alla leggerezza.

Scritto interamente in **Python 3** con **PyQt6** e **QScintilla**, gira su Linux, Windows e macOS.

---

## ✨ Funzionalità principali

### 📝 Editor avanzato
- **Syntax highlighting** per decine di linguaggi: Python, JavaScript, TypeScript, C/C++, Java, C#, Bash, SQL, LaTeX, Markdown, HTML, PHP, Ruby, Rust, Go e molti altri
- **Code folding** — collassa blocchi di codice, classi e funzioni
- **Numeri di riga**, indicatore di colonna, minimap laterale
- **Word wrap** configurabile
- **Autocompletamento** intelligente: parole nel documento, snippet per linguaggio, dizionari API, supporto LSP (Language Server Protocol)
- **Auto-chiusura** di parentesi, virgolette e tag
- **Mostra spazi/tab** e caratteri di fine riga
- **Margine dinamico**: La larghezza della colonna dei numeri di riga si adatta automaticamente alla dimensione del file per garantire una visibilità perfetta anche con file di grandi dimensioni.

### 🗂️ Gestione tab e split view
- **Tab multipli** con drag & drop, indicatore di modifica, ripristino sessione all'avvio
- **Split view** orizzontale e verticale (Ctrl+Alt+2 / Ctrl+Alt+3)
- Rotazione e sincronizzazione del cursore tra i pannelli
- **Clona tab** per lavorare sulla stessa vista in due posizioni

### 🔍 Ricerca e sostituzione
- Trova / Sostituisci con **espressioni regolari**
- **Cerca in tutti i file** aperti contemporaneamente
- **Cerca nei file** su disco (con filtro estensione)
- **Ricerca incrementale** inline (Ctrl+F2)
- **Vai alla riga** (Ctrl+G) e vai alla parentesi corrispondente
- **Bookmark** su righe: aggiungi, naviga, rimuovi (F2 / Shift+F2)
- **Mark con colori** (5 colori distinti) per evidenziare blocchi

### 🛠️ Strumenti di editing
- **Multi-cursore**: seleziona occorrenza successiva/tutte (Ctrl+D / Ctrl+Shift+D), cursori sopra/sotto (Ctrl+Alt+↑↓), numeri incrementali
- **Macro**: registra, salva, carica ed esegui N volte
- **Conversione caso**: MAIUSCOLO, minuscolo, Title Case, Invert Case
- **Commenta/decommenta** righe (con rilevamento automatico del linguaggio)
- **Indentazione**: indent/unindent, smart indent, tabs→spazi e viceversa
- **Rimuovi spazi in coda**, aggiungi newline a fine file
- **Unisci righe**, vai a riga specifica, conta parole
- **Color picker** integrato
- **Tester regex** interattivo
- **Convertitore numerico** (decimale, esadecimale, binario, ottale)
- **Statistiche colonna**

### 🏗️ Pannello Build (compilazione)
- **Profili di build** configurabili per linguaggio (LaTeX, Python, C/C++, Markdown, ecc.)
- Comandi Compile / Run / Build separati
- **Output in tempo reale** con lista errori cliccabile (click → vai alla riga dell'errore)
- **Anteprima PDF integrata** dopo la compilazione LaTeX (con PyMuPDF): zoom, navigazione pagine, SyncTeX
- **Salvataggio automatico** prima della compilazione
- **Rilevamento PDF intelligente**: Il pulsante di anteprima PDF si abilita istantaneamente all'apertura del file se viene trovato un documento già compilato sul disco.

### 👁️ Pannello Anteprima
- **Anteprima live** di **Markdown**, **HTML**, **reStructuredText**, **LaTeX**, **PDF**
- **Sincronizzazione cursore editor** ↔ anteprima
- **Ritardo configurabile per l'aggiornamento**
- **Ritaglio intelligente (Smart Crop)**: Funzione per eliminare automaticamente i margini bianchi dei PDF e massimizzare l'area di lettura.
- **Ritaglio manuale**: 4 contatori indipendenti per un controllo millimetrico del taglio sui quattro lati.
- **Navigazione fluida**: Supporto completo per lo scorrimento tra le pagine con la rotella del mouse e zoom rapido con Ctrl + Rotella.
- **Auto-posizionamento**: Passaggio automatico tra le pagine (dall'ultima riga della pagina precedente alla prima della successiva e viceversa).

### 📁 File Browser e Terminale
- **Browser file** laterale per navigare le directory del progetto
- **Terminale integrato** nel pannello inferiore
- **FTP Browser** (via plugin) per navigare e modificare file remoti

### 🌍 Interfaccia e UI
- **Orologio Live**: Un orologio integrato nella barra dei menu che mostra data e ora localizzate automaticamente in base alla lingua dell'interfaccia.
- **Sincronizzazione Menu**: Le voci del menu (Word Wrap, Line Numbers, ecc.) riflettono fedelmente le preferenze salvate fin dall'avvio del programma.

### 🔌 Sistema Plugin
Plugin inclusi pronti all'uso:
| Plugin | Funzione |
|--------|----------|
| **Clipboard History** | Cronologia degli appunti con selezione rapida |
| **Compare & Merge** | Confronto visuale tra due file o versioni |
| **Encrypt/Decrypt** | Cifratura/decifratura testo con AES |
| **FTP Browser** | Navigazione e modifica file su server FTP |
| **Git Integration** | Stato repo, commit, diff direttamente dall'editor |
| **Hex Viewer** | Visualizzazione esadecimale dei file binari |

Il Plugin Manager consente di attivare, disattivare e gestire i plugin.

### 🌍 Interfaccia multilingua
L'interfaccia è completamente tradotta in **5 lingue**, cambiabile a caldo senza riavviare:
🇮🇹 Italiano · 🇬🇧 English · 🇩🇪 Deutsch · 🇫🇷 Français · 🇪🇸 Español

### 🎨 Temi e icone
- **Temi editor** multipli, con editor visuale integrato
- Import/export temi in formato JSON
- **Set di icone** toolbar selezionabile: Lucide, Material, Sistema
- Download automatico dei set di icone mancanti

### 💾 File e sessioni
- Gestione **encoding** (UTF-8, UTF-8 BOM, Latin-1, CP1252, UTF-16, GB2312)
- **Line ending** configurabile (LF, CRLF, CR)
- **Backup automatico** periodico su cartella configurabile
- **Ripristino sessione** all'avvio (ultimi file aperti)
- **File recenti** con cronologia configurabile
- Rilevamento modifica esterna del file con opzioni (ricarica / confronta / sovrascrivi)
- **Proprietà file**: encoding, line ending, dimensione, BOM
- Stampa e **esportazione PDF**
- Modelli di file (Python, HTML, LaTeX, Markdown, Bash, C/C++, JavaScript)

### ⚙️ Preferenze
- Font e dimensione editor
- Indentazione (tab/spazi, larghezza)
- Comportamento visualizzazione (numeri riga, minimap, folding, ecc.)
- Autocompletamento configurabile
- Lingua, tema, set di icone
- Pannelli visibili all'avvio
- Tutto modificabile a caldo con Applica immediato

### 🔢 Function List
Pannello laterale con la lista di funzioni, metodi e classi del file aperto — con:
- Filtro rapido
- Ordinamento A-Z o per riga
- Click per navigare direttamente alla definizione
- Supporto per: Python, JavaScript, TypeScript, C/C++, Java, Bash, SQL, LaTeX, Markdown

---

## 🚀 Installazione

### Requisiti
- Python 3.10+
- PyQt6
- QScintilla

```bash
pip install PyQt6 PyQt6-QScintilla
```

### Dipendenze opzionali
```bash
pip install pymupdf        # Anteprima PDF e rendering LaTeX
pip install markdown       # Anteprima Markdown
pip install pygments       # Syntax highlighting esteso
pip install python-docutils # Anteprima reStructuredText
```

### Avvio
```bash
git clone https://github.com/buzzqw/NotePadPQ.git
cd NotePadPQ
python main.py
```

Puoi passare file come argomenti:
```bash
python main.py documento.py altro.md
```

---

## 🖥️ Piattaforme supportate

| Piattaforma | Stato |
|-------------|-------|
| Linux (Arch, Ubuntu, Debian, …) | ✅ Supportato |
| Windows 10/11 | ✅ Supportato |
| macOS | ✅ Supportato |
| FreeBSD | ✅ Supportato |

---

## 📄 Licenza

NotePadPQ è distribuito sotto licenza **MIT**. Libero per uso personale e commerciale.

---

---

# 🇬🇧 English

## What is NotePadPQ?

NotePadPQ is an advanced, free and open source text editor designed for developers, system administrators, technical writers and enthusiasts. Inspired by the power of Notepad++ but built with modern, cross-platform technologies, it offers a clean interface and a professional feature set — without sacrificing speed.

Written entirely in **Python 3** with **PyQt6** and **QScintilla**, it runs on Linux, Windows and macOS.

---

## ✨ Key Features

### 📝 Advanced Editor
- **Syntax highlighting** for dozens of languages: Python, JavaScript, TypeScript, C/C++, Java, C#, Bash, SQL, LaTeX, Markdown, HTML, PHP, Ruby, Rust, Go and many more
- **Code folding** — collapse blocks, classes and functions
- **Line numbers**, column indicator, side minimap
- Configurable **word wrap**
- Smart **autocompletion**: document words, per-language snippets, API dictionaries, LSP (Language Server Protocol) support
- **Auto-close** brackets, quotes and tags
- Show whitespace/tabs and end-of-line characters
- Dynamic Margin: Line number column width adjusts automatically based on file size to ensure perfect readability even with large documents

### 🗂️ Tabs & Split View
- **Multiple tabs** with drag & drop, modification indicator, session restore on startup
- **Horizontal and vertical split view** (Ctrl+Alt+2 / Ctrl+Alt+3)
- Split panel rotation and cursor synchronisation
- **Clone tab** to work on the same file from two scroll positions simultaneously

### 🔍 Search & Replace
- Find / Replace with **regular expressions**
- **Search across all open documents** simultaneously
- **Find in files** on disk (with extension filter)
- **Incremental search** bar (Ctrl+F2)
- **Go to line** (Ctrl+G) and jump to matching bracket
- **Bookmarks**: add, navigate, remove (F2 / Shift+F2)
- **Colour marks** (5 distinct colours) to highlight regions of interest

### 🛠️ Editing Tools
- **Multi-cursor**: select next/all occurrences (Ctrl+D / Ctrl+Shift+D), add cursors above/below (Ctrl+Alt+↑↓), incremental number insertion
- **Macro recorder**: record, save, load and replay N times
- **Case conversion**: UPPERCASE, lowercase, Title Case, Invert Case
- **Comment/uncomment** lines (with automatic language detection)
- **Indentation**: indent/unindent, smart indent, tabs↔spaces conversion
- Remove trailing whitespace, add newline at end of file
- **Join lines**, go to specific line, word count
- Built-in **colour picker**
- Interactive **regex tester**
- **Number converter** (decimal, hex, binary, octal)
- **Column statistics**

### 🏗️ Build Panel
- Configurable **build profiles** per language (LaTeX, Python, C/C++, Markdown, etc.)
- Separate Compile / Run / Build commands
- **Real-time output** with clickable error list (click → jump to error line)
- **Integrated PDF preview** after LaTeX compilation (requires PyMuPDF): zoom, page navigation, SyncTeX
- Auto-save before compilation
- Smart PDF Detection: The PDF preview button enables instantly upon opening a file if a pre-existing compiled document is found on disk.

### 👁️ Preview Panel
- Live preview for **Markdown**, **HTML**, **reStructuredText**, **LaTeX**, **PDF**
- Editor cursor ↔ preview synchronisation
- Configurable update delay
- Smart Crop: Feature to automatically trim PDF white margins and maximize the reading area.
- Manual Cropping: 4 independent counters for millimetric control of the cut on all four sides.
- Smooth Navigation: Full scroll-wheel support for page switching and fast Ctrl + Wheel zooming.
- Auto-positioning: Seamless page transitions (from the last line of the previous page to the first of the next and vice versa).

### 🌍 Interface & UI
- Live Clock: An integrated clock in the menu bar showing date and time automatically localized based on the interface language.
- Advanced Session Management: Opening files via double-click or CLI no longer overwrites the previous session; instead, new files are added to the existing tabs.
- Menu Synchronization: Menu items (Word Wrap, Line Numbers, etc.) accurately reflect saved preferences from the moment the program starts.

### 📁 File Browser & Terminal
- **Side file browser** for navigating project directories
- **Integrated terminal** in the bottom panel
- **FTP Browser** (via plugin) for browsing and editing remote files

### 🔌 Plugin System
Built-in ready-to-use plugins:
| Plugin | Function |
|--------|----------|
| **Clipboard History** | Clipboard history with quick selection |
| **Compare & Merge** | Visual diff between two files or versions |
| **Encrypt/Decrypt** | AES text encryption and decryption |
| **FTP Browser** | Browse and edit files on FTP servers |
| **Git Integration** | Repo status, commit, diff directly from the editor |
| **Hex Viewer** | Hexadecimal viewer for binary files |

The Plugin Manager lets you enable, disable and manage plugins.

### 🌍 Multilingual Interface
The interface is fully translated into **5 languages**, switchable on the fly without restarting:
🇮🇹 Italian · 🇬🇧 English · 🇩🇪 German · 🇫🇷 French · 🇪🇸 Spanish

### 🎨 Themes & Icons
- Multiple **editor themes** with a built-in visual theme editor
- Import/export themes as JSON
- Selectable **toolbar icon sets**: Lucide, Material, System
- Automatic download of missing icon sets

### 💾 Files & Sessions
- **Encoding** management (UTF-8, UTF-8 BOM, Latin-1, CP1252, UTF-16, GB2312)
- Configurable **line endings** (LF, CRLF, CR)
- Periodic **automatic backup** to a configurable folder
- **Session restore** on startup (last opened files)
- **Recent files** with configurable history length
- External file change detection with options (reload / compare / overwrite)
- **File properties**: encoding, line ending, size, BOM
- Print and **PDF export**
- File templates (Python, HTML, LaTeX, Markdown, Bash, C/C++, JavaScript)

### ⚙️ Preferences
- Editor font and size
- Indentation (tabs/spaces, width)
- Display behaviour (line numbers, minimap, folding, etc.)
- Configurable autocompletion
- Language, theme, icon set
- Panels visible at startup
- Everything changeable live with immediate Apply

### 🔢 Function List Panel
Side panel showing functions, methods and classes in the current file — with:
- Quick filter
- Sort A-Z or by line number
- Click to jump directly to the definition
- Language support: Python, JavaScript, TypeScript, C/C++, Java, Bash, SQL, LaTeX, Markdown

---

## 🚀 Installation

### Requirements
- Python 3.10+
- PyQt6
- QScintilla

```bash
pip install PyQt6 PyQt6-QScintilla
```

### Optional dependencies
```bash
pip install pymupdf        # PDF preview and LaTeX rendering
pip install markdown       # Markdown preview
pip install pygments       # Extended syntax highlighting
pip install python-docutils # reStructuredText preview
```

### Run
```bash
git clone https://github.com/buzzqw/NotePadPQ.git
cd NotePadPQ
python main.py
```

You can pass files as arguments:
```bash
python main.py document.py other.md
```

---

## 🖥️ Supported Platforms

| Platform | Status |
|----------|--------|
| Linux (Arch, Ubuntu, Debian, …) | ✅ Supported |
| Windows 10/11 | ✅ Supported |
| macOS | ✅ Supported |
| FreeBSD | ✅ Supported |

---

## 📄 License

NotePadPQ is released under the **MIT License**. Free for personal and commercial use.

---

---

# 💖 Supporta il progetto / Support the project

NotePadPQ è sviluppato nel tempo libero con passione. Se lo trovi utile, considera una donazione — aiuta a mantenere il progetto vivo e a finanziare nuove funzionalità.

NotePadPQ is developed in spare time with passion. If you find it useful, consider a donation — it helps keep the project alive and fund new features.

<div align="center">

[![Donate with PayPal](https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif)](https://www.paypal.com/donate/?business=azanzani%40gmail.com&currency_code=EUR)

**PayPal:** azanzani@gmail.com

*Grazie / Thank you!* 🙏

</div>

---

<div align="center">

Fatto con ❤️ in Italia · Made with ❤️ in Italy

**[⬆ Torna su / Back to top](#notePadPQ)**

</div>


<img width="1920" height="794" alt="notepadpq2" src="https://github.com/user-attachments/assets/6c717fa9-64aa-4f2b-81ed-0fcab9c190bd" />

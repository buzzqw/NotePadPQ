<img width="1920" alt="NotePadPQ" src="NotePadPQ.png" />

<div align="center">

<img src="icons/NotePadPQ_128.png" alt="NotePadPQ Logo" width="96"/>

# NotePadPQ

**Un editor di testo avanzato, moderno e multipiattaforma — costruito con Python e PyQt6**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.x-green?logo=qt)](https://riverbankcomputing.com/software/pyqt/)
[![License](https://img.shields.io/badge/License-EUPL%201.2-blue.svg)](EUPL-1.2%20EN.txt)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey)]()
[![Version](https://img.shields.io/badge/Version-0.2.0-orange)]()


[🇮🇹 Italiano](#-italiano) · [🇬🇧 English](#-english) · [💖 Dona / Donate](https://www.paypal.com/cgi-bin/webscr?cmd=_donations&business=azanzani@gmail.com&item_name=Support+NotePadPQ+Project)

</div>

---

# 🇮🇹 Italiano

## Cos'è NotePadPQ?

NotePadPQ è un editor di testo avanzato, libero e open source, pensato per sviluppatori, scrittori tecnici e appassionati. Ispirato alla potenza di Notepad++ ma costruito con tecnologie moderne e multipiattaforma, offre un'interfaccia pulita e un set di funzionalità professionale — senza rinunciare alla leggerezza.

Scritto interamente in **Python 3** con **PyQt6** e **QScintilla**, gira su Linux, Windows e macOS.

---

## ✨ Funzionalità principali

### 📝 Editor avanzato
- **Syntax highlighting** per decine di linguaggi: Python, JavaScript, TypeScript, C/C++, Java, C#, Bash, SQL, LaTeX, Markdown, HTML, PHP, Ruby, Rust, Go e molti altri.
- **Code folding** — collassa blocchi di codice, classi e funzioni.
- **Numeri di riga**, indicatore di colonna, minimap laterale.
- **Word wrap** configurabile (Alt+Z).
- **Autocompletamento** intelligente: parole nel documento, snippet per linguaggio, dizionari API, supporto LSP (Language Server Protocol).
- **Auto-chiusura** di parentesi, virgolette e tag.
- **Mostra spazi/tab** e caratteri di fine riga.
- **Margine dinamico**: La larghezza della colonna dei numeri di riga si adatta automaticamente alla dimensione del file per garantire una visibilità perfetta anche con file di grandi dimensioni.
- **Scorciatoie Markup**: `Ctrl+B` (Grassetto), `Ctrl+I` (Corsivo) e `Ctrl+Shift+X` (Barrato) funzionano nativamente in Markdown (`**`, `*`, `~~`) e LaTeX (`\textbf`, `\textit`, `\sout`).

### 🗂️ Gestione tab e split view
- **Tab multipli** con drag & drop, indicatore di modifica, ripristino sessione all'avvio.
- **Split view** orizzontale e verticale (Ctrl+Alt+2 / Ctrl+Alt+3).
- Rotazione e sincronizzazione del cursore tra i pannelli.
- **Clona tab** per lavorare sulla stessa vista in due posizioni.

### 🔍 Ricerca e sostituzione
- Trova / Sostituisci con **espressioni regolari**.
- **Cerca in tutti i file** aperti contemporaneamente.
- **Cerca nei file** su disco (con filtro estensione).
- **Ricerca incrementale** inline (Ctrl+F2).
- **Vai alla riga** (Ctrl+G) e vai alla parentesi corrispondente.
- **Bookmark** su righe: aggiungi, naviga, rimuovi (F2 / Shift+F2).
- **Mark con colori** (5 colori distinti) per evidenziare blocchi (Ctrl+1..5).

### 🛠️ Strumenti di editing
- **Multi-cursore**: seleziona occorrenza successiva/tutte (Ctrl+D / Ctrl+Shift+D), cursori sopra/sotto (Ctrl+Alt+↑↓), numeri incrementali.
- **Macro**: registra, salva, carica ed esegui N volte.
- **Conversione caso**: MAIUSCOLO, minuscolo, Title Case, Invert Case.
- **Commenta/decommenta** righe (Ctrl+E) con rilevamento automatico del linguaggio.
- **Indentazione**: indent/unindent, smart indent, tabs→spazi e viceversa.
- **Rimuovi spazi in coda**, aggiungi newline a fine file.
- **Unisci righe**, conta parole, color picker integrato e tester regex interattivo.

### 🏗️ Pannello Build (compilazione)
- **Profili di build** configurabili per linguaggio (LaTeX, Python, C/C++, Markdown, ecc.).
- **Output in tempo reale** con lista errori cliccabile (click → vai alla riga dell'errore).
- **Rilevamento PDF intelligente**: Il pulsante di anteprima PDF si abilita istantaneamente all'apertura del file se viene trovato un documento già compilato sul disco.
- **Salvataggio automatico** prima della compilazione.

### 👁️ Pannello Anteprima
- **Anteprima live** di **Markdown**, **HTML**, **reStructuredText**, **LaTeX**, **PDF**.
- **Sincronizzazione cursore editor** ↔ anteprima (SyncTeX supportato).
- **Ritaglio intelligente (Smart Crop)**: Funzione per eliminare automaticamente i margini bianchi dei PDF tramite l'icona `✂`.
- **Ritaglio manuale**: 4 contatori indipendenti per un controllo millimetrico del taglio sui quattro lati.
- **Navigazione fluida**: Supporto per lo scorrimento tra le pagine con la rotella del mouse e zoom rapido con `Ctrl + Rotella`.
- **Auto-posizionamento**: Passaggio automatico tra le pagine (dall'ultima riga della pagina precedente alla prima della successiva).

### 🔌 Sistema Plugin
| Plugin | Funzione |
|--------|----------|
| **Clipboard History** | Cronologia degli appunti con selezione rapida |
| **Compare & Merge** | Confronto visuale tra due file o versioni |
| **Encrypt/Decrypt** | Cifratura/decifratura testo con AES |
| **FTP Browser** | Navigazione e modifica file su server FTP |
| **Git Integration** | Stato repo, commit, diff direttamente dall'editor |
| **Hex Viewer** | Visualizzazione esadecimale dei file binari |

### 🌍 Interfaccia e UI
- **Orologio Live**: Un orologio integrato nella barra dei menu che mostra data e ora localizzate in base alla lingua.
- **Interfaccia multilingua**: 5 lingue supportate (IT, EN, DE, FR, ES) cambiabili a caldo.
- **Temi e icone**: Editor di temi integrato e set di icone selezionabili (Lucide, Material, Sistema) con download automatico.

---

## 🚀 Installazione

### Installazione rapida (Linux)
Il modo più semplice per installare NotePadPQ e tutte le sue dipendenze è utilizzare lo script di setup automatico:

```bash
git clone https://github.com/buzzqw/NotePadPQ.git
cd NotePadPQ
bash setup.sh
```

### Avvio
```bash
python main.py
```

### Dipendenze manuali
Se preferisci non usare lo script:
```bash
pip install PyQt6 PyQt6-QScintilla pymupdf markdown pygments python-docutils PyQt6-WebEngine
```

---

# 🇬🇧 English

## What is NotePadPQ?

NotePadPQ is an advanced, free and open source text editor built with **Python 3**, **PyQt6**, and **QScintilla**. It offers a professional feature set inspired by classic editors but with modern cross-platform capabilities.

---

## ✨ Key Features

### 📝 Advanced Editor
- **Syntax highlighting** for dozens of languages.
- **Dynamic Margin**: Line number column width adjusts automatically based on file size.
- **Markup Shortcuts**: Native support for `Ctrl+B`, `Ctrl+I`, and `Ctrl+Shift+X` in Markdown and LaTeX.

### 🏗️ Build Panel
- **Smart PDF Detection**: The PDF preview button enables instantly if a compiled document is found on disk.
- **Clickable Errors**: Jump directly to the source code from the build output.

### 👁️ Preview Panel
- **Smart Crop**: Automatically trim PDF white margins using the `✂` icon.
- **Manual Cropping**: 4 independent counters for precise control on all sides.
- **Smooth Navigation**: Full scroll-wheel support for page switching and `Ctrl + Wheel` zooming.

### 🌍 Interface & UI
- **Live Clock**: Integrated localized clock in the menu bar.
- **Session Management**: Restores last opened files and UI state on startup.

---

## 🚀 Installation

### Automated Setup (Recommended)
```bash
git clone [https://github.com/buzzqw/NotePadPQ.git](https://github.com/buzzqw/NotePadPQ.git)
cd NotePadPQ
bash setup.sh
python main.py
```

---

## 💖 Support the project

NotePadPQ is developed in spare time with passion. If you find it useful, consider a donation.

<div align="center">

[![Donate with PayPal](https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif)](https://www.paypal.com/donate/?business=azanzani%40gmail.com&currency_code=EUR)

**PayPal:** azanzani@gmail.com

</div>

---

<div align="center">

Fatto con ❤️ in Italia · Made with ❤️ in Italy

**[⬆ Torna su / Back to top](#notepadpq)**

</div>

<img width="1920" alt="notepadpq2" src="notepadpq2.png" />

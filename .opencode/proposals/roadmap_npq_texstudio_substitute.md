# Roadmap: NotePadPQ come sostituto completo di TeXstudio
# Data: 2026-07-21
# Target: v2.0 "LaTeX First-Class"

## Riepilogo dello stato attuale

NotePadPQ ha già ~80% delle feature LaTeX di TeXstudio, inclusi syntax highlighting,
SyncTeX, wizard, checker, tooltip, LSP texlab, preview PDF e molto altro.
I gap si concentrano su: completamento per-package (CWL), preview inline formule,
link overlay, grammar checker, annotazioni PDF, e alcuni miglioramenti UX.

---

# PARTE 1: GAP vs TEXSTUDIO - PROPOSTE DI IMPLEMENTAZIONE

---

## 1. [CRITICO] Sistema CWL / Completamento per-package

### Analisi del problema
Attualmente NotePadPQ ha `PACKAGE_COMMANDS`, `PACKAGE_ENVIRONMENTS`, e `PACKAGE_OPTIONS`
in `latex_support.py` (~500 righe hardcoded per ~60 pacchetti). TeXstudio ha centinaia
di file `.cwl` completi, mantenuti dalla community, uno per ogni pacchetto LaTeX.

### Proposta: CWL Loader + ibrido Python/JSON

**Fase 1 - CWL Parser (file: `editor/cwl_loader.py`)**
```python
class CWLLoader:
    """Carica e parsa file .cwl nel formato TeXstudio-compatibile."""
    
    def parse_cwl(self, content: str) -> dict:
        """
        Formato CWL:
        # commento
        \comando#t  (t=tex/LaTeX, g=graphics, m=math, ecc.)
        \comando{arg1}{arg2}#t
        \comando[opt]{req}#t
        \comando{arg}%labeldef  (argomento che definisce label)
        \comando/envname#S  (ambiente)
        keyname#*  (solo keyval)
        keyname#*c  (keyval per colore)
        """
```
- Supporta la sintassi completa CWL di TeXstudio
- Mappa le classificazioni `#t`, `#g`, `#m`, `#S`, `#*`, `%labeldef`, ecc.
- Cache lazy-loading: carica solo i CWL dei pacchetti effettivamente usati

**Fase 2 - Repository CWL sincronizzato**
- Sincronizzare il repository `texstudio-org/texstudio` → `data/cwl/` come submodule git
- oppure: copiare i file `.cwl` come assets statici (sono testo puro)
- ~500 file CWL disponibili, copertura quasi totale dei package CTAN

**Fase 3 - Integrazione autocomplete**
- `_ApiRebuildWorker` già chiama `build_dynamic_api()` dopo aver estratto i package
- Aggiungere: dopo `get_package_commands()` (che usa `PACKAGE_COMMANDS`), chiamare anche il CWL loader
- Unione: comandi CWL + comandi PACKAGE_COMMANDS + custom user commands
- Aggiornamento in tempo reale: quando l'utente digita `\usepackage{siunitx}`, i comandi di siunitx appaiono subito nell'autocomplete

**Fase 4 - Validazione keyval**
- I CWL definiscono `keyname#*` per il completamento keyval
- Quando l'utente digita `\sisetup{` → popup con le chiavi definite nel CWL
- Già esiste `handle_latex_option()` in `autocomplete.py` per `\usepackage[...]` — estendere il meccanismo

**Stima effort: 4-5 giorni**
- 1 giorno: CWL parser
- 1 giorno: integrazione autocomplete
- 1 giorno: sync repository CWL
- 1 giorno: keyval completion
- 1 giorno: test e polish

---

## 2. [CRITICO] Anteprima inline delle formule matematiche

### Analisi del problema
NotePadPQ ha solo hover preview (popup tooltip dopo 400ms di dwell).
TeXstudio mostra le formule renderizzate direttamente nell'editor come
"inline annotations" sopra il sorgente LaTeX, aggiornate in tempo reale.

### Proposta: QScintilla Annotation Layer

**Implementazione: `editor/latex_inline_preview.py`**

```python
class LaTeXInlinePreviewer:
    """
    Usa le QScintilla ANNOTATION per mostrare formule renderizzate
    come overlay inline sopra il sorgente LaTeX.
    
    Flusso:
    1. Scan del testo per pattern matematica ($...$, $$...$$, \[...\], \begin{equation}...)
    2. Per ogni match, genera rendering via matplotlib (formato piccola PNG → base64)
    3. Aggiungi annotation HTML sopra la riga: <img src="data:image/png;base64,...">
    4. QScintilla supporta annotation con stili per-riga tramite ANNOTATION_STYLED
    """

    def _render_inline_formula(self, latex: str, font_size: int = 14) -> str:
        """Renderizza formula LaTeX e restituisce tag <img> in base64."""
        import matplotlib.pyplot as plt
        import base64, io
        
        fig, ax = plt.subplots(figsize=(0.01, 0.01))
        ax.axis('off')
        text = ax.text(0, 0, f"${latex}$", fontsize=font_size)
        fig.savefig(buf := io.BytesIO(), format='png', dpi=150,
                     bbox_inches='tight', pad_inches=0.1, transparent=True)
        plt.close(fig)
        return f'<img src="data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}">'
```

**Requisiti tecnici:**
- Usare `SCI_ANNOTATIONSETSTYLEOFFSET` per stili di annotation
- Debounce: aggiornare dopo 800ms di inattività (più pesante del checker perché richiede matplotlib)
- Thread separato per il rendering delle formule (matplotlib è CPU-intensive)
- Cache delle formule renderizzate per evitare ri-rendering
- Toggle: "Mostra anteprima formule" nel menu Visualizza
- Opzione: dimensione font rendering configurabile

**Limitazioni:**
- QScintilla non supporta annotation multilinea vere → limitarsi a formule inline `$...$`
- Per display math (`$$...$$`), mostrare thumbnail centrata sotto il blocco
- Non funziona per formule troppo lunghe (troncare e mostrare "..." oppure scalare)

**Stima effort: 3-4 giorni**

---

## 3. [ALTO] Link Overlay (Ctrl+click navigabile)

### Analisi del problema
In TeXstudio, tenendo premuto Ctrl e passando il mouse su `\ref{label}` o `\cite{key}`,
il testo diventa un link cliccabile che naviga alla definizione. NotePadPQ non ha nulla.

### Proposta: Ctrl+Hover su riferimenti

**Implementazione: in `editor_widget.py`, modulo `SCN_DWELLSTART`**

```python
def _on_dwell_start(self, position, x, y):
    # Verifica se Ctrl è premuto
    if QApplication.keyboardModifiers() != Qt.KeyboardModifier.ControlModifier:
        return  
    
    # Rileva token sotto il cursore
    line, index = self.lineIndexFromPosition(position)
    text = self.text(line)
    
    # Cerca \ref{label}, \cite{key}, \input{file}, \include{file}
    # all'interno della posizione del cursore
    import re
    for pattern, action_type in [
        (r'\\ref\{([^}]+)\}', 'label'),
        (r'\\eqref\{([^}]+)\}', 'label'),
        (r'\\pageref\{([^}]+)\}', 'label'),
        (r'\\autoref\{([^}]+)\}', 'label'),
        (r'\\cref\{([^}]+)\}', 'label'),
        (r'\\cite\{([^}]+)\}', 'cite'),
        (r'\\citep\{([^}]+)\}', 'cite'),
        (r'\\citet\{([^}]+)\}', 'cite'),
        (r'\\parencite\{([^}]+)\}', 'cite'),
        (r'\\input\{([^}]+)\}', 'file'),
        (r'\\include\{([^}]+)\}', 'file'),
    ]:
        for m in pattern.finditer(text):
            if m.start() <= index < m.end():
                key = m.group(1)
                self._show_link_overlay(key, action_type, position)
                return

def _on_ctrl_click(self, position):
    """Se Ctrl+click su un link overlay, naviga."""
    if self._link_target:
        key, action_type = self._link_target
        if action_type == 'label':
            self._goto_label(key)
        elif action_type == 'cite':
            self._goto_bibtex_key(key)
        elif action_type == 'file':
            self._open_file(key)
```

**Feature aggiuntive:**
- Tooltip preview: al Ctrl+hover, mostra un popup con l'anteprima della destinazione
  - Per label: mostra la linea con `\label{key}` e il testo circostante
  - Per cite: mostra il record BibTeX completo
  - Per input/include: mostra le prime 10 righe del file
- Cambio cursore: da `IBeam` a `PointingHand` durante Ctrl+hover su link
- Sottolineatura: stile `INDICATOR_HYPERLINK` (sottolineatura blu) sul token attivo

**Stima effort: 2-3 giorni**

---

## 4. [ALTO] Grammar Checker (LanguageTool)

### Analisi del problema
NotePadPQ ha solo spell checking (pyspellchecker). TeXstudio integra LanguageTool
(tramite server HTTP locale o API cloud) per controllo grammaticale in tempo reale.

### Proposta: Integrazione LanguageTool via HTTP

**Implementazione: `editor/grammar_checker.py`**

```python
class GrammarChecker:
    """
    Integra LanguageTool per controllo grammaticale.
    
    Supporto:
    - LanguageTool locale (java -jar languagetool.jar --http)
    - LanguageTool cloud (api.languagetool.org)
    - Lingua: segue la lingua del documento o del sistema
    """

    ENDPOINT = "http://localhost:8081/v2/check"  # server locale
    
    def check_text(self, text: str, language: str = "en-US") -> list[dict]:
        """Invia testo a LanguageTool e restituisce errori."""
        response = requests.post(
            self.ENDPOINT,
            data={"text": text, "language": language},
            timeout=10
        )
        return response.json().get("matches", [])
```

**Visualizzazione:**
- Usare `INDICATOR_GRAMMAR` (indicatore 9) con `SquiggleIndicator`, colore verde/azzurro
  per distinguerlo dal rosso dello spell-check e dall'ambra del checker LaTeX
- Configurazione: server URL, lingua, categorie di regole (grammar, style, typography)
- Debounce: 1 secondo dopo l'ultima modifica, invio per paragrafi (non tutto il documento)
- Toggle nel menu Visualizza
- Supporto per `% !TEX spellcheck = it-IT` come magic comment

**Stima effort: 2 giorni**

---

## 5. [MEDIO-ALTO] Interattività Reference Checker

### Analisi del problema
Il `LaTeXChecker` attuale esegue il controllo in background ogni 1.5s e mostra
marker statici nel gutter. TeXstudio ha feedback interattivo: quando scrivi `\ref{`,
le label non definite vengono evidenziate mentre quelle definite appaiono normali.
Inoltre il popup di completamento mostra quali label esistono e quali no.

### Proposta: Checker incrementale con feedback inline

**Miglioramenti a `latex_checker.py`:**

1. **Indicatore per label/cite non definite** (in aggiunta al gutter marker):
   - Usare `INDICATOR_UNDEFINED` (indicatore 10) con `SquiggleIndicator`, colore viola
   - Sottolineare `\ref{undefined_key}` direttamente nel testo
   - Già esistono `_apply_markers()` e `_apply_tabular_indicators()` — aggiungere `_apply_undefined_indicators()`

2. **Popup completamento con stato label**:
   - In `_complete_labels()`, dopo aver recuperato le label dal progetto,
     contrassegnare quelle definite con ✓ e quelle non definite con ✗
   - Possibile perché QScintilla `showUserList` supporta testo ricco
     (o almeno prefissi Unicode come `✓ label (figura)`)

3. **Feedback durante la scrittura** (non solo dopo 1.5s):
   - Quando l'utente digita `\ref{` e poi `}`, controllare immediatamente
     la label appena inserita contro la cache delle label note
   - Se non trovata: sottolineatura viola immediata (senza attendere il ciclo completo)
   - Cache delle label deve essere sempre aggiornata (già fatto dal `_ApiRebuildWorker`)

4. **Auto-fix "Did you mean?"**:
   - Se una label non è definita, suggerire label simili (distanza Levenshtein)
   - Mostrare il suggerimento nel tooltip hover o nel gutter marker

**Stima effort: 2 giorni**

---

## 6. [MEDIO] Pannello Simboli Matematici (1000+ simboli)

### Analisi del problema
NotePadPQ ha `character_panel.py` (pannello caratteri speciali generico) ma non
un pannello dedicato ai simboli matematici LaTeX. TeXstudio ha un pannello con
1000+ simboli organizzati per categoria (frecce, operatori, lettere greche, ecc.).

### Proposta: LaTeX Symbol Panel

**Implementazione: `ui/latex_symbol_panel.py` (nuovo file)**

- Dati: file JSON `config/latex_symbols.json` con simboli organizzati per categoria:
  ```json
  {
    "categories": {
      "Lettere greche": {"alpha": "\\alpha", "beta": "\\beta", ...},
      "Frecce": {"rightarrow": "\\rightarrow", "leftarrow": "\\leftarrow", ...},
      "Operatori": {"sum": "\\sum", "prod": "\\prod", ...},
      "Relazioni": {"leq": "\\leq", "geq": "\\geq", ...},
      "Delimitatori": {"langle": "\\langle", "rangle": "\\rangle", ...},
      ...
    }
  }
  ```
- UI: `QDockWidget` con `QTabWidget` per categorie, griglia di bottoni
- Ogni bottone mostra il rendering del simbolo (via matplotlib, come l'hover preview)
  e il comando LaTeX
- Click → inserisce il comando nel documento
- Barra di ricerca: filtra per nome o comando
- Organizzato come TeXstudio: Relationship, Operator, Arrow, Delimiter, Greek, Misc, Symbols List
- Favoriti/Most used: i simboli più usati appaiono in una tab "Preferiti"
- Tema adattivo: i simboli si adattano al tema chiaro/scuro

**Fonti dati:**
- Usare il database simboli Unicode di TeXstudio o generarlo dalle CWL
- Alternativa: `unimath-symbols` dataset (https://milde.users.sourceforge.net/LUCR/Math/)

**Stima effort: 2-3 giorni**

---

## 7. [MEDIO] Manipolazione Tabelle Avanzata

### Analisi del problema
NotePadPQ ha `table_editor.py` per allineamento ma mancano tool interattivi.
TeXstudio permette: aggiungere/rimuovere colonne, aggiungere/rimuovere righe,
auto-formattare, incollare da LibreOffice Calc, "Remodel Table".

### Proposta: Estendere table_editor.py

**Aggiunte a `editor/table_editor.py`:**

1. **Aggiungi/Rimuovi colonna**: Contest menu su ambiente tabular → "Aggiungi colonna" / "Rimuovi colonna"
2. **Aggiungi/Rimuovi riga**: Inserisci/rimuovi `\\` e contenuti
3. **Allineamento automatico**: Già presente `align_table()`, migliorare con supporto per `tblr` (tabularray)
4. **Incolla da spreadsheet**: Rilevare testo con tabulazioni → convertire in `&` e `\\`
5. **Wizard tabella rapido**: Ctrl+Shift+T → dialog per scegliere righe/colonne → genera tabella
   (già parzialmente presente in `table_grid_picker.py`)
6. **Converti tabella**: Markdown ↔ LaTeX tabular

**Stima effort: 2 giorni**

---

## 8. [MEDIO] Drag & Drop Immagini nell'Editor

### Analisi del problema
NotePadPQ richiede l'uso del dialogo `latex_insert_image_dialog.py` manualmente.
TeXstudio: trascini l'immagine sull'editor e si apre il wizard.

### Proposta: Gestore drop nell'editor

**Modifiche a `editor_widget.py`:**
```python
def dragEnterEvent(self, event):
    if event.mimeData().hasUrls():
        for url in event.mimeData().urls():
            if url.isLocalFile() and self._is_image_file(url.toLocalFile()):
                event.acceptProposedAction()
                return
    super().dragEnterEvent(event)

def dropEvent(self, event):
    for url in event.mimeData().urls():
        filepath = url.toLocalFile()
        if self.language == "latex" and self._is_image_file(filepath):
            self._show_image_insert_dialog(filepath)
        elif self.language == "markdown":
            self._insert_markdown_image(filepath)
```

**Il dialogo `latex_insert_image_dialog.py` già esiste** — va solo chiamato al drop.
Aggiungere: copia automatica del file nella cartella `images/` del progetto (configurabile).

**Stima effort: 0.5 giorni**

---

## 9. [MEDIO] Editing Collaborativo (teamtype)

### Analisi
TeXstudio 4.9.0+ integra teamtype per editing peer-to-peer. Protocollo complesso.
NotePadPQ non ha infrastruttura collaborativa.

### Proposta: Operational Transform / CRDT via WebSocket

**Opzione A (leggera):** Usare `pycrdt` (CRDT, Y.js-compatibile) con WebSocket server locale
- Vantaggio: nessuna infrastruttura esterna
- Svantaggio: complessità implementativa

**Opzione B (pragmatica):** Integrare un server Collabora/LibreOffice Online? No, overkill.

**Opzione C (realistica per v2.1):** Integrazione con Etherpad o simili
- Usare `python-socketio` per comunicazione real-time
- Necessita: server di relay, Operational Transform, risoluzione conflitti

**Raccomandazione: Rimandare a v2.1+**
L'editing collaborativo è complesso e richiede protocollo di rete solido.
Non è un blocker per l'uso quotidiano di LaTeX.

**Stima effort: 10+ giorni (da pianificare separatamente)**

---

## 10. [MEDIO-BASSO] Wizard Avvio Rapido / Template

### Proposta: Quick Start Dialog per LaTeX

**Implementazione: `ui/latex_quickstart.py` (nuovo file)**

- Dialog con campi: tipo documento (article, report, book, beamer, letter), titolo, autore, data
- Checkbox per pacchetti comuni (graphicx, amsmath, hyperref, geometry, babel, fontspec)
- Opzioni: dimensione font (10pt, 11pt, 12pt), formato carta, lingua babel
- Generazione automatica di uno scheletro documento con preamble completo
- Salva template personalizzati: l'utente può creare e salvare i propri template

**Template repository online:** GitHub repo con template `.tex` → download on-demand
- Simile a TeXstudio template repository ma più semplice

**Stima effort: 2 giorni**

---

## 11. [MEDIO-BASSO] Auto-Detect Multi-Run LaTeX

### Analisi
Già coperto dal build profile `latexmk` che gestisce automaticamente le esecuzioni multiple.
Tuttavia gli utenti che usano `pdflatex` direttamente non hanno auto-detection.

### Proposta: Post-compilation log parser

```python
def _needs_rerun(log_text: str) -> bool:
    """Analizza .log per determinare se serve una seconda esecuzione."""
    needs_rerun_patterns = [
        r'LaTeX Warning: Label\(s\) may have changed',
        r'LaTeX Warning: There were undefined references',
        r'LaTeX Warning: Citation.*undefined',
        r'Package rerunfilecheck Warning: File.*has changed',
        r'\(.*\.aux\)',  # Nuovo aux file caricato
        r'No file.*\.toc',
    ]
    # Se rilevato, chiedere all'utente "Eseguire nuovamente?"
    # oppure (opzione) eseguire automaticamente fino a N=3 tentativi
```

**Stima effort: 1 giorno**

---

## 12. [MEDIO-BASSO] BibTeX Avanzato

### Miglioramenti a `latex_support.py`:

1. **Completamento tipi entry BibTeX**:
   - Dopo `@`, mostrare popup con: `article`, `book`, `inproceedings`, `techreport`, `phdthesis`, `misc`, `manual`, `incollection`, `inbook`, `mastersthesis`, `proceedings`, `unpublished`
   
2. **Completamento campi BibTeX**:
   - Dopo `@article{key,` → mostrare campi richiesti/opzionali: `author`, `title`, `journal`, `year`, `volume`, `number`, `pages`, `doi`
   
3. **Template snippet BibTeX**:
   - Trigger `@article` → genera entry template con tab-stops

4. **Auto-esecuzione bibtex/biber**:
   - Dopo compilazione LaTeX, se il log contiene "Citation ... undefined",
     eseguire automaticamente bibtex/biber e poi ri-compilare

**Stima effort: 1.5 giorni**

---

## 13. [BASSO] Global TOC + File Caching

### Proposta
- **Global TOC**: Estendere `extract_structure()` con supporto multi-file
  - `collect_project_files()` già esiste in `latex_support.py`
  - Nuovo widget: `ui/latex_global_toc.py` con `QTreeWidget` che mostra tutte le sezioni
    di tutti i file del progetto, con file di origine tra parentesi
- **File caching**: Già esiste `_cached_read_text()` con LRU 128 in `latex_support.py`
  - Espanderlo con cache persistente su disco (pickle/marshalling) per accelerare
    il caricamento di progetti grandi tra una sessione e l'altra

**Stima effort: 2 giorni**

---

## 14-17. [BASSI] Altri miglioramenti minori

**14. Expl3 highlighting** (`editor/lexer_latex_custom.py`):
- Aggiungere regole per `\cs_new:Npn`, `\tl_set:Nn`, `\prop_get:NnNTF`, `\str_if_eq:nnTF`
- Colore dedicato (viola chiaro) per distinguere da comandi LaTeX normali

**15. Indent guides + rainbow braces** (`editor/editor_widget.py`):
- Indent guides: `self.setIndentationGuides(True)` già disponibile in QScintilla
- Rainbow braces: Analizzare le parentesi `{}` nell'editor e assegnare colori ciclici
  usando `INDICATOR_BRACE_MATCH` con stili per nesting level 1-5

**16. Text selection in PDF viewer** (`ui/pdf_viewer_widget.py`):
- PyMuPDF supporta `page.get_text("words")` che restituisce bounding box
- Implementare: selezione rettangolo → estrarre testo dai bounding box → copiare negli appunti
- Oppure: passare completamente al rendering via `QWebEngineView` con PDF.js per selezione nativa

**17. Macro repository online**:
- Aggiungere pulsante "Scarica macro dalla community" in `core/macro.py`
- Endpoint GitHub per scaricare `.json` di macro condivise
- Simile a TeXstudio `texstudio-org/texstudio-macro`

**Stima effort (14-17): 3-4 giorni totali**

---

# PARTE 2: MIGLIORAMENTI A FUNZIONALITÀ ESISTENTI

---

## A. Git Plugin - Riscrittura sostanziale

### Problemi identificati
1. **Tutte le operazioni git bloccano l'UI** (nessun threading nel plugin)
2. **Commit stagia tutto con `git add .`** sempre, nessun partial staging
3. **Push senza branch specificato** è pericoloso
4. **Stash pop nel pulsante "No"** è UX confusionaria
5. **30 secondi timeout hardcoded** uccide push/pull su repo grandi
6. **Tre implementazioni git separate** (plugin, gutter, blame) senza shared code
7. **Nessun fetch, merge, rebase, tag, cherry-pick, revert**
8. **Diff viewer basilare** (nessun side-by-side, nessun hunk staging)
9. **Nessun merge conflict resolver**

### Proposta: GitFramework unificato + UI ridisegnata

**Fase 1 - Unificazione backend git (nuovo file: `core/git_framework.py`)**

```python
class GitFramework:
    """
    Backend git unificato condiviso da plugin, gutter, e blame.
    
    Caratteristiche:
    - Tutte le operazioni su QThread (mai UI thread)
    - Timeout configurabile per operazione
    - Credential helper integrato (SSH agent + token HTTPS)
    - Cache dello stato per evitare chiamate ridondanti
    - Segnali Qt per progresso, completamento, errore
    
    Sostituisce:
    - GitRunner in git_plugin.py
    - _run_git_diff in git_gutter.py
    - GitBlameManager._run_blame in git_blame_inline.py
    """

    # Operazioni
    def status(self, repo_path: Path) -> GitStatusResult
    def diff(self, repo_path: Path, file: Path = None, staged: bool = False) -> GitDiffResult
    def log(self, repo_path: Path, count: int = 60) -> GitLogResult
    def commit(self, repo_path: Path, message: str, files: list[str] = None)
    def push(self, repo_path: Path, remote: str, branch: str)
    def pull(self, repo_path: Path, remote: str, branch: str = None)
    def fetch(self, repo_path: Path, remote: str = "origin")
    def merge(self, repo_path: Path, branch: str)
    def rebase(self, repo_path: Path, branch: str)
    def stash_push(self, repo_path: Path, message: str = None)
    def stash_pop(self, repo_path: Path, index: int = 0)
    def stash_list(self, repo_path: Path) -> list
    def branch_create(self, repo_path: Path, name: str)
    def branch_delete(self, repo_path: Path, name: str)
    def branch_list(self, repo_path: Path) -> list
    def checkout(self, repo_path: Path, branch: str)
    def tag_create(self, repo_path: Path, name: str, message: str = None)
    def blame(self, repo_path: Path, file: Path, line: int) -> GitBlameResult
```

**Fase 2 - Nuova UI git panel (`plugins/git_plugin.py` riscritto)**

Riprogettare completamente l'interfaccia:

```
┌─────────────────────────────────────────────────────────┐
│ Repository: my-project  ⎇ main  [Fetch] [Pull] [Push]   │
├─────────────────────────────────────────────────────────┤
│ [Changes (3)] [Staged (2)] [History] [Branches] [Stash] │
│                                                         │
│ ○ file1.tex        ✎ modificato    [Stage] [Diff]       │
│ ○ file2.bib        ✎ modificato    [Stage] [Diff]       │   ← Checkbox per partial staging
│ ○ newfile.tex      ＋ nuovo         [Stage] [Diff]       │
│                                                         │
│ ── Staged ────────────────────────────────────────────── │
│ ● chapter1.tex     ＋ staged       [Unstage] [Diff]      │
│ ● image.png        ＋ staged       [Unstage] [Diff]      │
│                                                         │
│ [Commit message...                          ] [Commit ✓] │
│ [Push after commit ▢] [Amend ▢]                         │
└─────────────────────────────────────────────────────────┘
```

**Miglioramenti specifici:**
- **Partial staging**: Checkbox per ogni file invece di `git add .`
- **Commit + Push**: Opzione "Push after commit"
- **Amend commit**: Possibilità di modificare l'ultimo commit
- **Stash list**: Mostra stash stack con messaggi, possibilità di pop/apply/drop selettivi
- **Branch operations**: Merge, rebase, delete, rename (non solo checkout)
- **Fetch separato da Pull**: Bottone Fetch dedicato
- **Diff side-by-side**: Usare `ui/compare.py` (già esistente per confronto file) integrato
- **Conflict resolver**: UI a tre pannelli (ours, theirs, result) per merge conflicts
- **Progress indicator**: `QProgressBar` per push/pull/fetch con output in tempo reale
- **Threading**: TUTTE le operazioni in background, UI sempre responsive
- **Token GitHub/GitLab usati**: I token salvati nel config dialog vengono usati per autenticazione HTTPS e chiamate API (PR, issue, wiki)

**Fase 3 - Integrazione gutter/blame**
- `git_gutter.py` e `git_blame_inline.py` usano `GitFramework` invece di subprocess diretto
- Condivisione cache: una sola chiamata `git status` per tutte le feature
- Gutter markers già implementati correttamente (marker 1,2,3 vs 22,23 del checker) — mantenere

**Stima effort: 5-7 giorni**

---

## B. AI Plugin - Miglioramenti UX e funzionalità

### Problemi identificati
1. **Nessuna persistenza conversazioni** (perso al restart)
2. **Truncation silenzioso** del contenuto a 6000/8000/10000 char
3. **SSL bypass hardcoded** (rischio sicurezza, `CERT_NONE`)
4. **Chat ricostruita ogni risultato** (flickering, inefficiente)
5. **Nessun limite context window** (conversazioni lunghe falliscono)
6. **Inline edit pericoloso** (testo non-code può finire nell'editor)
7. **System prompt non persistente**
8. **Nessuna tool/function calling** per manipolare documenti

### Proposta: AI Plugin v2

**1. Persistenza conversazioni**
```python
class ConversationManager:
    """Salva/carica conversazioni in ~/.local/share/NotePadPQ/ai_conversations/"""
    
    def save(self, name: str, history: list[dict], provider: str, model: str) -> str
    def load(self, conversation_id: str) -> dict
    def list_conversations(self) -> list[dict]
    def delete(self, conversation_id: str)
```

**2. Context window management**
```python
def _prepare_messages(self) -> list[dict]:
    """Gestisce automaticamente la context window."""
    MAX_TOKENS = self._get_model_max_tokens()
    estimated_current = estimate_tokens(self._system_prompt, self._history)
    
    if estimated_current > MAX_TOKENS * 0.8:
        # Strategie:
        # 1. Rimuovi messaggi più vecchi (sliding window)
        # 2. Riassumi conversazione precedente (con chiamata AI di summarization)
        # 3. Avvisa utente che la conversazione è lunga
        self._trim_history(MAX_TOKENS)
    
    return [{"role": "system", "content": self._system_prompt}] + self._history[-self._max_messages:]
```

**3. Tool/Function Calling**
```python
TOOLS = [
    {
        "name": "read_file",
        "description": "Legge il contenuto di un file nel progetto",
        "parameters": {"file_path": str, "start_line": int, "end_line": int}
    },
    {
        "name": "write_file",
        "description": "Scrive o modifica il contenuto di un file",
        "parameters": {"file_path": str, "content": str, "mode": "replace"|"append"|"new"}
    },
    {
        "name": "search_code",
        "description": "Cerca pattern nel codice del progetto",
        "parameters": {"pattern": str, "file_pattern": str, "directory": str}
    },
    {
        "name": "run_command",
        "description": "Esegue un comando shell nel progetto",
        "parameters": {"command": str, "working_dir": str}
    },
    {
        "name": "edit_selection",
        "description": "Sostituisce il testo selezionato nell'editor",
        "parameters": {"new_text": str}
    }
]
```
- Supporto Anthropic tool_use e OpenAI function calling
- Preview delle modifiche prima dell'applicazione (conferma utente)
- Anche TeXstudio 4.9.4+ ha aggiunto tool functions → allinearsi

**4. Altre migliorie**
- **SSL fix**: Invece di `CERT_NONE`, distribuire un bundle CA aggiornato o usare `certifi`
- **Streaming reale**: Non ricostruire tutta la chat a ogni risultato; accumulare nel buffer
- **Warning truncation**: Mostrare avviso "File troncato a X caratteri" invece del silenzio
- **Retry button**: Dopo errore, pulsante "Riprova" invece di dover riselezionare tutto
- **System prompt salvo**: Persistente tra sessioni, salvato nelle impostazioni
- **Token count display**: Mostrare token usati e limite modello in tempo reale
- **Cost estimate**: Migliorare il calcolo costi con prezzi aggiornati per ogni modello
- **Vision support**: Implementare il supporto immagini (già menzionato nel docstring ma non implementato) — utile per Claude/GPT-4V
- **Selezione multipla**: "Chiedi su File 1 + File 2" per confrontare file

**5. UI riorganizzata**
```
┌───────────────────────────────────────────┐
│ Provider: [Anthropic ▼] Model: [Claude 5 ▼] [↻] [⚙] │
│ [Conversazioni salvate ▼] [Salva] [Elimina] │
├───────────────────────────────────────────┤
│ [E1: Explain] [Refactor] [Docstring] [FixBug] [▼ More] │
│ System prompt: [toggle ▸]                  │
├───────────────────────────────────────────┤
│ Chat history (con messaggi Markdown)       │
│                                             │
│ You: Spiega come funziona \DeclareMathOperator │
│                                             │
│ Claude: \DeclareMathOperator{cmd}{def}...   │
│                                             │
├───────────────────────────────────────────┤
│ [              Input message...            ] │
│ [+Contesto] [↻Riprova] [⬇Applica] [📄NuovoTab] [▶Invia] │
│ Token: 1,234/200,000 | Cost: ~$0.02         │
└───────────────────────────────────────────┘
```

**Stima effort: 5-6 giorni**

---

## C. Terminal Plugin - Miglioramenti

### Problemi identificati
1. **`cd` non iniettato nella shell** — label cambia ma directory no
2. **Font size e tema hardcoded**, non configurabili
3. **Nessun supporto multi-terminale**
4. **Dipendenze pesanti** (WebEngine + xterm.js + OpenGL)

### Proposta

**1. Fix cd injection**
```python
def set_cwd_from_file(self, file_path):
    """Cambia directory della shell attiva."""
    self._cwd = str(file_path.parent)
    # Inietta cd nella shell
    self._write_to_process(f"cd {self._cwd}\n".encode())
    self._cwd_label.setText(self._cwd)
```

**2. Preferenze utente**
- Aggiungere a `preferences.py`:
  - Dimensione font terminale (default: 13pt)
  - Tema (scuro/chiaro/personalizzato)
  - Shell predefinita (bash, zsh, fish, cmd, powershell) — attualmente hardcoded a `$SHELL`
  - Scrollback buffer (righe)

**3. Terminal multipli**
- Aggiungere `QTabWidget` al dock per supportare 2-3 terminali simultanei
- Ogni terminale ha il suo processo shell indipendente
- Tasto `Ctrl+Shift+T` per nuovo terminale

**4. Fallback senza WebEngine**
- Opzione alternativa: `QPlainTextEdit` + `QProcess` (terminale semplificato senza xterm.js)
- Per ambienti headless o senza OpenGL
- Meno bello ma sempre funzionante

**Stima effort: 1-2 giorni**

---

## D. PDF Viewer - Miglioramenti

### Problemi identificati (da analisi)
1. **Nessuna annotazione PDF** — funzionalità più richiesta
2. **Nessuna ricerca testo in modalità PyMuPDF**
3. **Nessuna selezione testo** — solo raster
4. **Nessuna lente di ingrandimento** (magnifier)
5. **Nessun multi-page view** (2-up, facing pages)

### Proposta

**Priorità 1: Ricerca e selezione testo con PyMuPDF**
```python
class PdfTextLayer:
    """Estrae layer di testo da PyMuPDF per ricerca e selezione."""
    
    def search_text(self, page: fitz.Page, query: str) -> list[fitz.Rect]:
        """Cerca testo nella pagina e restituisce bounding box."""
        return page.search_for(query)
    
    def get_text_at_position(self, page: fitz.Page, x: float, y: float) -> str:
        """Estrae testo alla posizione del clic."""
        # Usare page.get_text("words") con hit testing
        words = page.get_text("words")
        for x0, y0, x1, y1, word, *_ in words:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return word
        return ""
    
    def get_text_in_rect(self, page: fitz.Page, rect: fitz.Rect) -> str:
        """Estrae testo da una regione rettangolare (per selezione mouse)."""
        return page.get_textbox(rect)
```
- Aggiungere barra di ricerca (Ctrl+F) in modalità PyMuPDF, non solo WebEngine
- Selezione testo via mouse drag → estrae testo dai bounding box
- Highlight della ricerca con overlay rettangolo giallo semitrasparente

**Priorità 2: Annotazioni PDF** (versione base)
- PyMuPDF supporta `page.add_rect_annot()`, `page.add_text_annot()`, `page.add_highlight_annot()`
- Toolbar: pulsanti per Highlight, Strikethrough, Underline, Nota adesiva
- Barra laterale: lista annotazioni con navigazione
- Salvataggio: `pdf.save()` con `incremental=True` per non distruggere il file
- Versione completa (firma, timbri, forme) rimandata a v2.1+

**Priorità 3: Magnifier**
- Lente di ingrandimento circolare/rettangolare attivabile con tasto `M`
- Renderizza area sotto il cursore a 2-4x zoom in un overlay widget
- Utile per ispezionare posizionamento fine degli elementi LaTeX

**Stima effort: 5-6 giorni (ricerca, annotazioni base, magnifier)**

---

## E. Snippet System - Miglioramenti

### Problemi
Nessuna GUI per creare/modificare/importare snippet. Gli utenti devono editare JSON a mano.

### Proposta: Snippet Editor

**Nuovo file: `ui/snippet_editor.py`**

- Dialog accessibile da `Strumenti → Gestisci Snippet...`
- Lista snippet esistenti con filtro per linguaggio
- Editor con campi: Trigger, Descrizione, Corpo (con syntax highlighting)
- Anteprima live del corpo espanso (con tab-stops visualizzati)
- Pulsanti: Nuovo, Duplica, Elimina, Importa (da file .json), Esporta
- Validazione in tempo reale: controlla sintassi `${N}`, parentesi bilanciate
- Integrazione con `SnippetManager.save_user_snippet()` già esistente

**Fix: ripristinare Tab-expansion**
- Il commento in `snippets.py` dice "digitare il trigger + Tab espande il template"
- Ma `SnippetManager.expand()` non è mai chiamato nel codice
- Aggiungere in `editor_widget.py` `keyPressEvent`: quando l'utente preme Tab,
  controllare se la parola corrente è un trigger snippet e, se sì, espanderlo

**Stima effort: 2 giorni**

---

# RIEPILOGO PRIORITÀ E EFFORT TOTALE

## Fase 1: Gap Critici (v1.7) — ~9 giorni
| # | Feature | Effort |
|---|---------|--------|
| 1 | CWL System (parser + sync + autocomplete) | 4-5 gg |
| 2 | Inline formula preview | 3-4 gg |

## Fase 2: Gap Alti (v1.8) — ~7 giorni
| # | Feature | Effort |
|---|---------|--------|
| 3 | Link overlay Ctrl+click | 2-3 gg |
| 4 | Grammar checker (LanguageTool) | 2 gg |
| 5 | Reference checker interattivo | 2 gg |

## Fase 3: Gap Medi (v1.9) — ~9 giorni
| # | Feature | Effort |
|---|---------|--------|
| 6 | Pannello simboli matematici | 2-3 gg |
| 7 | Manipolazione tabelle avanzata | 2 gg |
| 8 | Drag & drop immagini | 0.5 gg |
| 10 | Wizard avvio rapido / template | 2 gg |
| 11 | Auto-detect multi-run LaTeX | 1 gg |
| 12 | BibTeX avanzato | 1.5 gg |

## Fase 4: Gap Bassi (v2.0 beta) — ~7 giorni
| # | Feature | Effort |
|---|---------|--------|
| 13 | Global TOC + file caching | 2 gg |
| 14-17 | Expl3, indent guides, rainbow braces, text selection PDF | 3-4 gg |
| - | Fix vari e polish | 2 gg |

## Fase 5: Miglioramenti Feature Esistenti (v2.0) — ~20 giorni
| # | Feature | Effort |
|---|---------|--------|
| A | Git plugin riscrittura | 5-7 gg |
| B | AI plugin v2 | 5-6 gg |
| C | Terminal plugin fix | 1-2 gg |
| D | PDF viewer (ricerca, annotazioni, magnifier) | 5-6 gg |
| E | Snippet editor GUI | 2 gg |

---

## Totale complessivo stimato: ~50-55 giorni di sviluppo

## Timeline suggerita:
- **v1.7** (gap critici): ~2 settimane
- **v1.8** (gap alti): ~2 settimane
- **v1.9** (gap medi): ~2 settimane
- **v2.0 beta** (gap bassi + fix): ~2 settimane
- **v2.0** (miglioramenti esistenti): ~4-5 settimane

**Totale: ~12-13 settimane (~3 mesi) per il sostituto completo di TeXstudio**

---

# NOTA SULLA STRATEGIA DI SVILUPPO

Per ogni fase, l'ordine di implementazione suggerito è:
1. Backend/logica (classi Python, parser, worker thread)
2. Integrazione editor (segnali, indicatori, marker)
3. UI/UX (dialog, panel, menu, azioni)
4. Configurazione (settings, preferenze, toggle)
5. Test (aprire documenti LaTeX reali, verificare tutte le interazioni)

Ogni file modificato deve:
- Seguire le convenzioni di codice esistenti (type hints, docstring, singleton pattern)
- Usare `tr()` per tutte le stringhe visibili (i18n)
- Rispettare il modello di threading esistente (QThread, signal/slot)
- Non introdurre dipendenze esterne se non strettamente necessario

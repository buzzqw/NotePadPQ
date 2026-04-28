# NotePadPQ — Manuale d'uso

> Versione 0.3.1 — Editor di testo avanzato basato su **QScintilla/PyQt6**  
> Piattaforme: Linux, Windows, macOS

---

## Indice

1. [Avvio e interfaccia](#1-avvio-e-interfaccia)
2. [Gestione file](#2-gestione-file)
3. [Modifica testo](#3-modifica-testo)
4. [Cerca e Sostituisci](#4-cerca-e-sostituisci)
5. [Evidenziazione colori (Mark)](#5-evidenziazione-colori-mark)
6. [Bookmark](#6-bookmark)
7. [Visualizzazione](#7-visualizzazione)
8. [Documento](#8-documento)
9. [Strumenti](#9-strumenti)
10. [Plugin](#10-plugin)
11. [Pannelli laterali e inferiori](#11-pannelli-laterali-e-inferiori)
12. [Multi-cursore](#12-multi-cursore)
13. [Split View](#13-split-view)
14. [Sessioni e ripristino](#14-sessioni-e-ripristino)
15. [Preferenze](#15-preferenze)
16. [Istanza singola](#16-istanza-singola)
17. [Supporto LaTeX](#17-supporto-latex)
18. [Espressioni regolari — riferimento completo](#18-espressioni-regolari--riferimento-completo)
19. [Scorciatoie da tastiera — riepilogo](#19-scorciatoie-da-tastiera--riepilogo)

---

## 1. Avvio e interfaccia

```bash
python main.py                    # apre con sessione precedente o tab vuoto
python main.py file1.py file2.md  # apre i file indicati
```

Se NotePadPQ è già aperto, i file vengono inviati alla sessione esistente senza aprirne una seconda — vedi [sezione 16](#16-istanza-singola).

L'interfaccia è composta da:

- **Menubar** — File / Modifica / Cerca / Visualizza / Documento / Strumenti / Plugin / Aiuto
- **Toolbar** — azioni comuni con icone (set selezionabile: Lucide, Material, Sistema)
- **Tab bar** — un tab per ogni file aperto; i file modificati mostrano `*` nel titolo
- **Editor** — area di testo principale con syntax highlighting, numeri di riga, fold margin, margine simboli (bookmark)
- **Statusbar** — riga/colonna, encoding, line ending, selezione, zoom, modalità inserimento
- **Pannelli dock** — File Browser, Function List, Anteprima, Pannello compilazione e terminale

---

## 2. Gestione file

| Azione | Scorciatoia |
|---|---|
| Nuovo file | `Ctrl+N` |
| Apri file | `Ctrl+O` |
| Apri file selezionato nell'editor | `Shift+Ctrl+O` |
| Salva | `Ctrl+S` |
| Salva con nome | `Shift+Ctrl+S` |
| Salva tutto | `Shift+Ctrl+S` |
| Ricarica da disco | `Shift+Ctrl+R` |
| Proprietà file | `Shift+Ctrl+V` |
| Stampa | `Ctrl+P` |
| Chiudi tab | `Ctrl+W` |
| Chiudi tutti | `Shift+Ctrl+W` |
| Esci | `Ctrl+Q` |

### File recenti
**File → File recenti** mostra gli ultimi file aperti. Clicca per riaprirli. Il numero massimo è configurabile nelle Preferenze.

### Nuovo da modello
**File → Nuovo da modello** crea un file con intestazione pronta per: Python, HTML, LaTeX, Markdown, Bash, C/C++, JavaScript.

### Drag & Drop
Trascina uno o più file direttamente sulla finestra o sull'editor per aprirli.

### Rilevamento modifica esterna
Se un file aperto viene modificato da un altro programma, NotePadPQ lo segnala con un dialog che offre tre opzioni:
- **Ricarica** — scarta le modifiche locali e ricarica da disco
- **Confronta** — apre il dialog Compare tra la versione in memoria e quella su disco
- **Sovrascrivi** — scrive la versione in memoria sovrascrivendo il file su disco

---

## 3. Modifica testo

### Operazioni base

| Azione | Scorciatoia |
|---|---|
| Annulla | `Ctrl+Z` |
| Ripeti | `Ctrl+Y` |
| Taglia | `Ctrl+X` |
| Copia | `Ctrl+C` |
| Incolla | `Ctrl+V` |
| Seleziona tutto | `Ctrl+A` |
| Elimina selezione | `Del` |
| Copia percorso file | — |
| Copia nome file | — |
| Inserisci data/ora | — |
| Conta parole | — |
| **Frequenza parole** | — |
| **Ordina righe (dialog)** | — |

### Frequenza parole

**Modifica → Frequenza parole** analizza il documento (o la selezione) e mostra una tabella ordinata per occorrenze con le prime 50 parole più frequenti, il totale di parole e il numero di parole uniche.

### Ordina righe

**Modifica → Ordina righe** apre un dialog con cinque criteri di ordinamento:

| Criterio | Effetto |
|---|---|
| Alfabetico crescente (A→Z) | Ordine lessicografico standard |
| Alfabetico decrescente (Z→A) | Ordine inverso |
| Per lunghezza crescente | Le righe più corte prima |
| Per lunghezza decrescente | Le righe più lunghe prima |
| Casuale | Mischia le righe in ordine casuale |

L'ordinamento si applica alla selezione (se attiva) o all'intero documento.  
Ulteriori operazioni sulle righe (rimuovi duplicati, rimuovi righe vuote, ecc.) sono in **Strumenti → Line Operations**.

### Formattazione testo

Accessibile da **Modifica → Formatta**:

| Azione | Scorciatoia |
|---|---|
| Unisci righe | — |
| Vai a capo forzato | — |
| Spezza righe lunghe a N colonne | — |
| MAIUSCOLO | — |
| minuscolo | — |
| Prima Lettera Maiuscola | — |
| Inverti maiuscolo/minuscolo | `Ctrl+Alt+U` |
| Attiva/disattiva commento | `Ctrl+E` |
| Commenta righe | — |
| Decommenta righe | — |
| Indenta | `Ctrl+Shift+I` |
| Deindenta | `Ctrl+U` |
| Indentazione intelligente | — |
| Rimuovi spazi finali | — |
| Tab → spazi | — |
| Spazi → tab | — |
| Grassetto (Markdown/LaTeX) | `Ctrl+B` |
| Corsivo (Markdown/LaTeX) | `Ctrl+I` |
| Barrato (Markdown/LaTeX) | `Ctrl+Shift+X` |
| Avvolgi in Ambiente / Tag HTML | `Alt+E` |
| Allinea Tabella (Markdown/LaTeX) | `Alt+T` |

> **Nota — A capo automatico vs. Spezza righe:**  
> **Visualizza / Documento → A capo automatico** (`Alt+Z`) è una visualizzazione: il testo appare mandato a capo a schermo senza modificare il file.  
> **Modifica → Formatta → Spezza righe lunghe** inserisce fisicamente `\n` nel testo — il file viene modificato. Usare con attenzione.

### Auto-chiusura parentesi
**Modifica → Auto-chiusura parentesi** (toggle) — chiude automaticamente `(`, `[`, `{`, `"`, `'` quando li digiti.

---

## 4. Cerca e Sostituisci

### Elenco comandi — Command Palette (`Ctrl+Shift+P`)

Apre una palette fuzzy-search su tutti i comandi dell'editor. Digita una parola qualsiasi del nome del comando, naviga con `↑`/`↓`, premi `Invio` per eseguire. Utile per accedere a funzioni senza memorizzare la scorciatoia.

### Vai a… — Goto Anything (`Ctrl+Shift+G`)

Navigazione rapida stile Sublime Text. Apre una palette che si comporta diversamente in base al prefisso digitato:

| Prefisso | Comportamento |
|---|---|
| *(niente)* | Ricerca fuzzy tra i **file aperti** per nome o percorso |
| `:42` | Salta alla **riga 42** del file corrente |
| `@nomeFunc` | Salta al **simbolo** (def/class/function) nel file corrente |
| `>testo` | Cerca tra i **comandi** (come la Command Palette) |

Naviga con `↑`/`↓`, conferma con `Invio`, chiudi con `Esc`.

### Dialog Cerca (`Ctrl+F`)

Il dialog ha 4 tab.

#### Tab "Cerca"

**Opzioni disponibili:**

| Opzione | Effetto |
|---|---|
| Maiuscole/minuscole | Distingue `Foo` da `foo` |
| Parola intera | Trova solo `ciao` e non `ciaocom` |
| Espressione regolare | Abilita la sintassi regex Python |
| Cerca circolare | Riparte dall'inizio/fine al termine del documento |
| Nella selezione | Cerca solo nel testo selezionato |

**Pulsanti:**

- **Trova successivo** — trova la prossima occorrenza (`F3`)
- **Trova precedente** — trova l'occorrenza precedente (`Shift+F3`)
- **Segna tutto** — evidenzia tutte le occorrenze con un bordo arancione
- **Conta** — popola la lista con tutte le occorrenze e mostra il totale

**Lista occorrenze:**  
Si popola automaticamente durante la digitazione (dopo 2 caratteri) e tramite il pulsante Conta. Doppio clic su una riga salta alla posizione corrispondente nel documento.

**Manuale regex:**  
Appare automaticamente quando si attiva "Espressione regolare" — vedi anche [sezione 18](#18-espressioni-regolari--riferimento-completo).

#### Tab "Sostituisci"

Stesse opzioni del tab Cerca più:

- **Sostituisci** — sostituisce l'occorrenza selezionata e passa alla successiva
- **Sostituisci tutto** — sostituisce tutte le occorrenze nel documento

Nel campo "Sostituisci con" puoi usare `\1`, `\2`, ... per riferirsi ai gruppi catturati dalla regex.

#### Tab "Cerca nei file"

Cerca in tutti i file di una directory, con filtro estensioni e opzione ricorsiva. I risultati mostrano file e righe — doppio clic apre il file alla riga corrispondente.

#### Tab "Cerca in tutti i documenti"

Cerca (e opzionalmente sostituisce) in tutti i file aperti nei tab.

### Navigazione

| Azione | Scorciatoia |
|---|---|
| Vai alla riga | `Ctrl+G` |
| Vai alla parentesi corrispondente | `Ctrl+]` |
| Ricerca incrementale inline | `Ctrl+Shift+F2` |

---

## 5. Evidenziazione colori (Mark)

Accessibile da **Cerca → Evidenzia in [colore]** o con le scorciatoie:

| Scorciatoia | Colore |
|---|---|
| `Ctrl+1` | Rosso |
| `Ctrl+2` | Verde |
| `Ctrl+3` | Blu |
| `Ctrl+4` | Arancione |
| `Ctrl+5` | Viola |
| `Ctrl+0` | Rimuovi tutti i mark |

**Come funziona:**

- **Con testo selezionato** → evidenzia/rimuove il mark sul testo selezionato (toggle)
- **Senza selezione** → marca tutte le occorrenze della parola sotto il cursore

I mark sono indipendenti tra loro: puoi avere contemporaneamente testo rosso, verde e blu. Gli indicatori disegnano un bordo colorato **sotto** il testo — il testo rimane sempre completamente leggibile indipendentemente dal tema.

### Smart Highlight (automatico)

Quando il cursore si ferma su una parola per più di 300ms, tutte le sue occorrenze vengono evidenziate automaticamente con un box grigio-blu tenue. Il sistema è ottimizzato per non interferire con la digitazione: non scatta mai mentre si scrive, si aggiorna solo quando la parola sotto il cursore cambia, e usa un singolo passaggio sul testo senza rallentare l'editor anche su documenti di grandi dimensioni.

È separato dai 5 colori manuali e non interferisce con essi.

---

## 6. Bookmark

I bookmark segnano righe di interesse con un cerchio colorato nel margine sinistro dell'editor.

| Azione | Scorciatoia |
|---|---|
| Attiva/disattiva bookmark sulla riga corrente | `Ctrl+F2` |
| Toggle bookmark via click | Click sul margine simboli |
| Prossimo bookmark | `F2` |
| Bookmark precedente | `Shift+F2` |
| Rimuovi tutti i bookmark | Menu Cerca |

La navigazione è circolare: dall'ultimo bookmark torna al primo e viceversa.  
I bookmark vengono salvati nella sessione e ripristinati alla riapertura del file.

---

## 7. Visualizzazione

### Toolbar e Statusbar
**Visualizza → Barra strumenti** e **Visualizza → Barra di stato** — mostrano/nascondono.

### Opzioni editor

| Azione | Scorciatoia |
|---|---|
| Numeri di riga | — |
| Margine fold (piegatura) | — |
| Mostra spazi bianchi | — |
| Mostra fine riga (¶) | — |
| A capo automatico | `Alt+Z` |
| Minimap | — |

> **A capo automatico** è presente sia in **Visualizza** che in **Documento**: sono la stessa azione — spuntarla in un menu aggiorna l'altra automaticamente.

### Modalità testo semplice (`Ctrl+Alt+T`)

**Visualizza → Modalità testo semplice** — toggle per tab. Quando attivo, disabilita sul tab corrente:

- Syntax highlighting (lexer rimosso)
- Brace matching
- Smart highlight (evidenziazione parola sotto cursore)
- Autocompletamento

Alla disattivazione, tutto viene ripristinato al linguaggio originale del file. Ogni tab mantiene il proprio stato indipendentemente.

### Modalità scrittura — Distraction-Free (`F11`)

**Visualizza → Modalità scrittura** — nasconde tutto tranne l'editor e va in schermo intero:

- Toolbar nascosta
- Statusbar nascosta
- Menubar nascosta
- Tutti i pannelli dock nascosti
- Finestra in modalità schermo intero

Premi di nuovo `F11` (oppure `Ctrl+Shift+F11` o `Ctrl+F11`) per uscire e ripristinare la visibilità precedente di tutti gli elementi. Ideale per sessioni di scrittura concentrata.

### Zoom

| Azione | Scorciatoia |
|---|---|
| Zoom in | `Ctrl+=` |
| Zoom out | `Ctrl+-` |
| Zoom reset | `Ctrl+0` |

Anche `Ctrl+Rotella mouse` direttamente nell'editor.

### Minimap
Colonna stretta sul lato dell'editor che mostra una versione rimpicciolita dell'intero documento. Clicca per navigare velocemente a qualsiasi punto del file.

### Anteprima (`F12`)
Apre il pannello Anteprima affiancato all'editor. Supporta:

- **Markdown** — rendering HTML in background, non blocca l'editor durante la digitazione
- **HTML** — preview diretta nel widget web integrato
- **LaTeX** — albero della struttura navigabile (sezioni, label, figure, tabelle)
- **reStructuredText** — rendering via docutils
- **PDF** — visualizzazione con PyMuPDF, navigazione pagine, zoom, SyncTeX

L'anteprima si aggiorna automaticamente con un delay configurabile (default 500ms). Non si aggiorna se il pannello è nascosto (risparmio CPU).

### Anteprima hover (passaggio del mouse)

Tenendo il cursore fermo per mezzo secondo su determinati elementi, NotePadPQ mostra un popup fluttuante:

- **Immagini** — posiziona il mouse su `\includegraphics{...}`, `![...](...)` o `<img src="...">` per vedere l'anteprima dell'immagine. Supporta PNG, JPG e anche la prima pagina dei file PDF vettoriali.
- **Formule matematiche** — nei file LaTeX e Markdown, passa il mouse sopra una formula (`$E=mc^2$`, `$$...$$`, `\[...\]`, `\begin{equation}...\end{equation}`) per vederla renderizzata ad alta risoluzione con sfondo scuro.

> Queste funzionalità richiedono le librerie opzionali `pymupdf` (per i PDF) e `matplotlib` (per le equazioni) — vedi [sezione 17](#17-supporto-latex).

---

## 8. Documento

### Impostazioni documento corrente

- **Tipo indentazione** — Tab o Spazi
- **Larghezza indentazione** — numero di spazi
- **Indentazione automatica** — re-indenta automaticamente la nuova riga in base alla precedente
- **Auto-indenta su incolla** — quando si incolla testo con più righe (`Ctrl+V`), le righe vengono riallineate all'indentazione del contesto corrente. Disattivabile dal menu Documento se non desiderato.
- **Sola lettura** — blocca le modifiche
- **Scrivi BOM** — aggiunge Byte Order Mark per UTF-8/UTF-16
- **A capo automatico** (`Alt+Z`) — manda a capo il testo a schermo senza modificare il file
- **Controllo Ortografico (`F4`)** — attiva la sottolineatura a zig-zag rossa per le parole errate. La lingua del dizionario è indipendente dalla lingua dell'interfaccia e si seleziona da **Documento → Lingua dizionario** (Italiano, English, Deutsch, Français, Español). Il click destro su una parola sottolineata mostra fino a 8 suggerimenti di correzione, "Aggiungi al dizionario" e "Ignora tutto". Ignora le sigle interamente maiuscole e le parole di meno di 3 lettere.
- **Lingua dizionario** — sottomenu di Documento che seleziona la lingua dello spell checker indipendentemente dalla lingua dell'interfaccia. La scelta viene salvata tra le sessioni.

### Tipo di file (syntax highlighting)

**Documento → Imposta tipo di file** — seleziona manualmente il linguaggio di colorazione. NotePadPQ rileva automaticamente il tipo dal suffisso del file e dallo shebang (`#!/usr/bin/env python3`).

Linguaggi supportati: Bash/Shell, Batch, C/C++, C#, CMake, CSS, Diff, Fortran, HTML, INI/Config, Java, JavaScript, JSON, LaTeX, Lua, Makefile, Markdown, Pascal, Perl, PostScript, Properties, Python, reStructuredText, Ruby, SPICE, SQL, TypeScript, Verilog, VHDL, XML, YAML, Testo normale.

### Codifica (encoding)

**Documento → Imposta codifica** — cambia l'encoding per il prossimo salvataggio. Encoding supportati: UTF-8, UTF-8 BOM, Latin-1, CP1252, UTF-16 LE/BE, GB2312.

### Terminatori di riga

**Documento → Imposta terminatori** — LF (Unix), CRLF (Windows), CR (Mac). Puoi anche convertire i terminatori del documento corrente alla nuova modalità.

### Operazioni documento

| Azione | Effetto |
|---|---|
| Clona documento | Apre una copia del file in un nuovo tab |
| Rimuovi spazi finali | Elimina gli spazi in fondo a ogni riga |
| Tab → Spazi | Converte le tabulazioni in spazi |
| Spazi → Tab | Converte i gruppi di spazi in tabulazioni |
| Piega tutto | Chiude tutti i blocchi piegabili |
| Espandi tutto | Apre tutti i blocchi piegabili |

---

## 9. Strumenti

### Preferenze (`Ctrl+Alt+P`)
Apre il dialog di configurazione — vedi [sezione 15](#15-preferenze).

### Build / Compilazione
Esegue il comando associato al tipo di file corrente e mostra l'output nel pannello "Output compilazione".

| Azione | Scorciatoia |
|---|---|
| Compila | `F6` |
| Build | `F7` |
| Stop compilazione | pulsante Stop nel pannello |

#### Profili di compilazione e variabili

I profili di compilazione si configurano da **Strumenti → Profili di compilazione**. Ogni profilo associa un tipo di file (es. `LaTeX`, `Python`, `Markdown`) a uno o più comandi (Compila, Build, Pulisci).

Nei comandi sono disponibili le seguenti variabili, accettate sia nella forma `${VAR}` che `$(VAR)`:

| Variabile | Descrizione | Esempio |
|---|---|---|
| `${FILE}` | Percorso completo del file | `/home/utente/doc/tesi.tex` |
| `${DIR}` | Cartella contenente il file | `/home/utente/doc` |
| `${FILENAME}` | Nome del file con estensione | `tesi.tex` |
| `${BASENAME}` | Nome del file senza estensione | `tesi` |
| `${BASEFILE}` | Percorso completo senza estensione | `/home/utente/doc/tesi` |
| `${EXT}` | Estensione del file (senza punto) | `tex` |
| `${LINE}` | Riga corrente del cursore | `42` |
| `${COL}` | Colonna corrente del cursore | `7` |

Esempio — compilazione LaTeX con pdflatex:
```
pdflatex -interaction=nonstopmode -synctex=1 ${FILE}
```

Esempio — conversione con pandoc:
```
pandoc ${FILE} -o ${BASEFILE}.pdf
```

Esempio — script che usa cartella e nome base:
```
cd ${DIR} && python ${FILENAME}
```

L'output appare nel pannello inferiore in tempo reale. Gli errori sono cliccabili: un click porta il cursore alla riga corrispondente nel file.

### Macro

Registra e riproduce sequenze di tasti:

| Azione | Funzione |
|---|---|
| Avvia/Ferma registrazione | Registra ogni tasto premuto nell'editor |
| Riproduci | Esegue la macro una volta |
| Riproduci N volte | Esegue la macro N volte consecutive |
| Salva su file | Salva la macro come file `.json` |
| Carica da file | Carica una macro salvata |

### Altri strumenti

| Strumento | Funzione |
|---|---|
| **Color Picker** | Selettore colore con codici HEX/RGB/HSL inseribili nell'editor |
| **Tester Regex** | Dialog interattivo per testare espressioni regolari su testo di prova |
| **Convertitore numerico** | Conversione tra decimale, esadecimale, binario, ottale |
| **Statistiche colonna** | Analisi statistica dei valori numerici nella colonna corrente |
| **Editor scorciatoie** | Personalizzazione dei tasti di scelta rapida |
| **Sessioni con nome** | Salva e ripristina gruppi di file come sessioni nominate |

---

## 10. Plugin

I plugin vengono caricati automaticamente dalla cartella `plugins/`. Per installarli, copiali in `plugins/` oppure inseriscili in `plugins_to_copy/` e riesegui `setup.sh`.

| Plugin | Funzione |
|---|---|
| **Clipboard History** | Cronologia degli appunti con possibilità di incollare elementi precedenti |
| **Compare & Merge** | Confronto visuale side-by-side di due file o tab |
| **Encrypt/Decrypt** | Cifratura AES-256-GCM e ChaCha20-Poly1305 del testo selezionato o dell'intero file |
| **FTP Browser** | Sfoglia e modifica file su server FTP |
| **Git Integration** | Pannello Git completo (vedi sotto) |
| **Hex Viewer** | Visualizza il file corrente in formato esadecimale |

### Plugin Git — dettaglio

Il pannello Git (`Plugin → Git Panel`) si aggiorna automaticamente al cambio di tab e rileva il repository dal percorso del file aperto. Ha 5 tab:

**Status** — elenco dei file modificati con indicatore colore (M=giallo, A=verde, D=rosso, ?=grigio). Click destro per: `git add`, `git reset HEAD`, `git checkout --`, apri nell'editor, blame, apri su GitHub/GitLab.

**Log** — ultimi 60 commit con hash, data, autore, messaggio. Filtrabile per branch. Click destro per: mostra diff completo, copia SHA, checkout, cherry-pick.

**Diff** — diff colorato (verde=aggiunto, rosso=rimosso, blu=header hunk) del file corrente o dell'intero repo, con opzione staged.

**Branch** — lista branch locali e remote. Doppio clic per checkout. Pulsanti: Nuova, Merge, Rebase, Elimina. Click destro per push al remote.

**Config** — nome e email correnti, `git config --local` completa, pulsante per il dialog credenziali.

**Azioni rapide** (barra superiore): Pull (con opzione `--rebase`), Push (con opzione `--force-with-lease`), Commit (dialog con selezione file e opzione amend), Stash, Fetch.

**Configurazione credenziali** (`Plugin → Git: Configura utente & token` oppure tab Config):

- Nome e email Git locale (per il repo corrente) e globale
- Token GitHub — salvato in keyring o `~/.config/notepadpq/git_tokens.json`
- Token GitLab — con supporto URL self-hosted

Con i token configurati è possibile creare Pull Request (GitHub) e Merge Request (GitLab) direttamente dal pannello. Richiede `PyGithub` e/o `python-gitlab` (installati dallo script di setup).

---

## 11. Pannelli laterali e inferiori

Tutti i pannelli sono dock widget: possono essere spostati, ridimensionati, staccati come finestre flottanti o riagganciati trascinando il titolo.

### File Browser (`Ctrl+Shift+E`)
Pannello sinistro con la struttura di directory. Doppio clic su un file per aprirlo nell'editor.

### Function List (`Ctrl+Shift+F`)
Pannello con la lista di funzioni, classi e metodi del file corrente. Si aggiorna automaticamente durante la digitazione.

- **Aggiornamento lazy** — se il pannello è nascosto, il refresh viene posticipato al momento dell'apertura (nessun consumo CPU inutile)
- **Filtro** — ricerca incrementale per nome funzione
- **Ordinamento** — ordine di apparizione nel file (default) o alfabetico (pulsante A↓)
- **Doppio clic** — salta direttamente alla riga nel file
- **Context menu** — vai alla riga, copia nome funzione

Linguaggi con parser dedicato: Python, JavaScript/TypeScript, C/C++, Java, Bash, SQL, LaTeX, Markdown.

### Pannello compilazione e terminale (`` Ctrl+` ``)

Un unico dock inferiore con due tab:

**Tab "Output compilazione"** — output testuale del comando build. La lista errori è cliccabile: click su un errore salta alla riga nel file sorgente. Dopo una compilazione LaTeX riuscita, il pulsante **📄 PDF** apre il documento nel pannello Anteprima.

**Tab "Terminale"** — terminale completo basato su xterm.js con PTY nativo. Non richiede configurazione aggiuntiva.

- Supporta qualsiasi programma interattivo: vim, python REPL, ssh, compilatori, git
- Gestione completa del colore ANSI e dei caratteri speciali
- Le librerie xterm.js sono incluse nel pacchetto — non richiede connessione internet

---

## 12. Multi-cursore

Il multi-cursore permette di modificare simultaneamente più punti del testo.

| Azione | Scorciatoia |
|---|---|
| Seleziona prossima occorrenza | `Ctrl+D` |
| Seleziona tutte le occorrenze | `Ctrl+Shift+D` |
| Aggiungi cursore sopra | `Ctrl+Alt+↑` |
| Aggiungi cursore sotto | `Ctrl+Alt+↓` |
| Inserisci numeri incrementali | `Ctrl+Shift+Alt+C` |
| Rimuovi cursori extra | `Esc` |

**Uso tipico:** seleziona una parola → premi `Ctrl+D` più volte per aggiungere le occorrenze successive → digita per sostituirle tutte simultaneamente.

---

## 13. Split View

Divide l'area editor in due pannelli per lavorare su due file (o due punti dello stesso file) contemporaneamente.

| Azione | Scorciatoia |
|---|---|
| Split verticale (affiancati) | `Ctrl+Alt+2` |
| Split orizzontale (sopra/sotto) | `Ctrl+Alt+3` |
| Ruota orientazione split | `Ctrl+Alt+R` |
| Sposta tab nell'altro pannello | `Ctrl+Alt+M` |
| Sincronizza cursore tra pannelli | Menu Visualizza → Split View |
| Rimuovi split | `Ctrl+Alt+1` |

---

## 14. Sessioni e ripristino

NotePadPQ salva automaticamente la sessione alla chiusura:

- File aperti (percorso, posizione cursore, encoding)
- Layout dock widget (posizione e dimensione dei pannelli)
- Stato dei bookmark

Al prossimo avvio i file vengono riaperti automaticamente (se abilitato in Preferenze → File → Ripristina sessione).

**Autobackup:** se abilitato nelle Preferenze, salva una copia `.bak` di ogni file modificato a intervalli regolari nella cartella configurata.

**Auto-save su perdita fuoco:** se abilitato nelle Preferenze → File → Auto-salvataggio, salva silenziosamente tutti i file modificati con un percorso su disco ogni volta che la finestra perde il fuoco (es. passando a un'altra applicazione).

**Sessioni con nome:** tramite **Strumenti → Sessioni con nome** puoi salvare e ripristinare gruppi di file come sessioni nominate indipendenti dalla sessione automatica.

---

## 15. Preferenze

Apri con `Ctrl+Alt+P` oppure **Strumenti → Preferenze**. Le modifiche possono essere applicate immediatamente con **Applica** senza chiudere il dialog.

### Scheda Editor
- Font e dimensione
- Larghezza tab e tipo indentazione (tab/spazi)
- Indentazione automatica
- Numeri di riga, fold margin, spazi/tab visibili, fine riga visibile
- A capo automatico, minimap
- Pannelli visibili all'avvio (compilazione, struttura documento)

### Scheda Aspetto
- **Tema attivo** — selezionabile dal combo; il cambio si applica immediatamente a tutti gli editor aperti
- **Editor tema** — modifica i colori del tema corrente con anteprima in tempo reale
- **Importa / Esporta tema** — formato JSON, per condividere temi tra installazioni
- **Set di icone toolbar** — Lucide (lineari, moderne), Material (Google, piene), Sistema (icone native OS). Se il set non è presente localmente, viene scaricato automaticamente da internet al momento della selezione.

### Scheda File
- Encoding predefinito (UTF-8, UTF-8 BOM, Latin-1, CP1252, UTF-16, GB2312)
- Line ending predefinito (LF, CRLF, CR)
- Backup al salvataggio (`.bak`)
- Rimuovi spazi in coda al salvataggio
- Aggiungi newline a fine file
- Ripristina sessione all'avvio
- Numero massimo file recenti
- **Autobackup periodico** — intervallo in minuti e cartella di destinazione
- **Auto-salvataggio** — salva automaticamente i file modificati quando la finestra perde il fuoco

### Scheda Autocompletamento
- Abilita/disabilita autocompletamento
- Sorgenti: parole nel documento, tutti i tab aperti, snippet per linguaggio, dizionari API, LSP
- Soglia di attivazione (numero minimo di caratteri)

### Scheda Anteprima
- Abilita pannello anteprima laterale
- Sincronizzazione cursore editor ↔ anteprima
- Ritardo aggiornamento in millisecondi

### Scheda Compilazione
- Salva automaticamente prima di compilare
- Mantieni sempre visibile il pannello di output

### Scheda Lingua
- Seleziona la lingua dell'interfaccia tra: Italiano, English, Deutsch, Français, Español
- Il cambio viene applicato immediatamente senza riavvio

---

## 16. Istanza singola

NotePadPQ gestisce l'istanza singola tramite socket locale. Se è già aperto e si tenta di avviarne una seconda (ad esempio con "Apri con..." dal file manager), il file viene inviato alla finestra già aperta e la seconda istanza termina immediatamente.

La finestra esistente viene portata automaticamente in primo piano anche se era minimizzata.

```bash
# Se NotePadPQ è già aperto, questo apre il file nella sessione esistente
python main.py nuovo_file.py
```

Funziona automaticamente su Linux, Windows e macOS senza alcuna configurazione.

---

## 17. Supporto LaTeX

NotePadPQ ha un supporto LaTeX completo, ma le funzionalità **avanzate** richiedono librerie opzionali che non vengono installate automaticamente dallo script di setup. L'idea è che chi usa NotePadPQ per scrivere LaTeX abbia già TeX Live installato e le librerie accessorie.

### Funzionalità sempre disponibili (nessuna dipendenza extra)
- **Syntax highlighting** LaTeX completo
- **Code folding** di ambienti (`\begin{...}` / `\end{...}`)
- **Autocompletamento contestuale**: digitando `\cite{` → chiavi BibTeX; `\ref{` → label; `\begin{` → ambienti; `\usepackage{` → pacchetti; `[` → opzioni comando/ambiente/pacchetto
- **Autocompletamento per pacchetto**: quando il documento usa `\usepackage{multicol}`, `\usepackage{tabularx}`, `\usepackage{longtable}`, `\usepackage{tabulary}` ecc., vengono suggeriti automaticamente i comandi specifici del pacchetto (es. `\columnbreak`, `\endhead`, `\endfirsthead`, template colonne `X`, `lX`, `LCR`…)
- **Build panel**: profili di compilazione configurabili (pdflatex, xelatex, lualatex, latexmk, ecc.)
- **Errori cliccabili**: click su un errore nell'output di compilazione salta alla riga nel sorgente
- **Scorciatoie markup**: `Ctrl+B` → `\textbf{...}`, `Ctrl+I` → `\textit{...}`, `Ctrl+Shift+X` → `\sout{...}`
- **Struttura documento** (Function List): sezioni, label, figure, tabelle del file `.tex`
- **Supporto multi-file**: label, chiavi BibTeX e comandi custom estratti dall'intero progetto seguendo `\input{}`, `\include{}`, `\subfile{}`
- **Checker bilanciamento**: rileva `\begin{}`/`\end{}` sbilanciati in tempo reale con marcatori nel gutter

### Funzionalità che richiedono librerie opzionali

| Funzionalità | Libreria necessaria | Installazione |
|---|---|---|
| Anteprima PDF (hover su `\includegraphics`) | `pymupdf` | `pip install pymupdf` |
| Anteprima PDF nel pannello Anteprima | `pymupdf` | `pip install pymupdf` |
| Rendering equazioni hover (`$...$`, `$$...$$`) | `matplotlib` | `pip install matplotlib` |
| Calcolo simbolico | `sympy` | `pip install sympy` |
| SyncTeX (cursore editor ↔ posizione PDF) | `synctex` | incluso in TeX Live |

**Installazione rapida:**
```bash
pip install pymupdf matplotlib sympy
```

Su **Arch Linux**:
```bash
sudo pacman -S python-pymupdf python-matplotlib python-sympy texlive-bin
```

> Se stai già usando TeX Live per compilare LaTeX, `synctex` è già disponibile. Le librerie Python puoi installarle separatamente senza toccare il resto del setup.

Le funzionalità opzionali si attivano automaticamente se le librerie sono presenti — non è necessaria nessuna configurazione aggiuntiva.

---

## 18. Espressioni regolari — riferimento completo

Le regex usano la sintassi Python (`re` module). Disponibili ovunque sia presente l'opzione "Espressione regolare". Il manuale inline appare automaticamente nel dialog Cerca quando si attiva la spunta.

### Metacaratteri base

| Pattern | Significato |
|---|---|
| `.` | Qualsiasi carattere eccetto newline |
| `\d` | Cifra decimale `[0-9]` |
| `\D` | Non-cifra |
| `\w` | Carattere "parola" `[a-zA-Z0-9_]` |
| `\W` | Non-carattere parola |
| `\s` | Spazio bianco (spazio, tab, `\n`, `\r`) |
| `\S` | Non-spazio bianco |
| `\b` | Confine di parola (tra `\w` e `\W`) |
| `\B` | Non-confine di parola |
| `\n` | Newline |
| `\t` | Tab |

### Quantificatori

| Pattern | Significato |
|---|---|
| `*` | 0 o più volte (greedy) |
| `+` | 1 o più volte (greedy) |
| `?` | 0 o 1 volta |
| `*?` | 0 o più volte (non-greedy) |
| `+?` | 1 o più volte (non-greedy) |
| `{n}` | Esattamente n volte |
| `{n,}` | Almeno n volte |
| `{n,m}` | Da n a m volte |

### Ancore

| Pattern | Significato |
|---|---|
| `^` | Inizio riga |
| `$` | Fine riga |

### Classi di caratteri

| Pattern | Significato |
|---|---|
| `[abc]` | Uno tra a, b, c |
| `[^abc]` | Nessuno tra a, b, c |
| `[a-z]` | Qualsiasi lettera minuscola |
| `[A-Z]` | Qualsiasi lettera maiuscola |
| `[0-9]` | Qualsiasi cifra |
| `[a-zA-Z0-9]` | Alfanumerico |

### Gruppi e alternativa

| Pattern | Significato |
|---|---|
| `(...)` | Gruppo catturante |
| `(?:...)` | Gruppo non catturante |
| `(?P<n>...)` | Gruppo con nome |
| `a\|b` | Alternativa: a oppure b |

### Riferimenti (nel campo Sostituisci)

| Pattern | Significato |
|---|---|
| `\1`, `\2` | Valore del gruppo 1, 2, ... |
| `\g<n>` | Valore del gruppo con nome |

### Esempi pratici

| Cerca | Sostituisci | Effetto |
|---|---|---|
| `\d+` | `NUM` | Sostituisce tutti i numeri con `NUM` |
| `\bdef\s+(\w+)` | `def \1` | Normalizza spazi dopo `def` |
| `(\w+)@(\w+)\.(\w+)` | `[\1 at \2 dot \3]` | Offusca email |
| `^\s+` | `` | Rimuove spazi iniziali da ogni riga |
| `\s+$` | `` | Rimuove spazi finali da ogni riga |
| `^(.+)$` | `> \1` | Aggiunge `>` a ogni riga (citazione) |
| `  +` | ` ` | Riduce spazi multipli a uno |
| `#.*$` | `` | Rimuove commenti Python (semplificato) |

---

## 19. Scorciatoie da tastiera — riepilogo

### File

| Scorciatoia | Azione |
|---|---|
| `Ctrl+N` | Nuovo file |
| `Ctrl+O` | Apri |
| `Ctrl+S` | Salva |
| `Shift+Ctrl+S` | Salva con nome / Salva tutto |
| `Ctrl+W` | Chiudi tab |
| `Shift+Ctrl+W` | Chiudi tutti |
| `Ctrl+Q` | Esci |
| `Shift+Ctrl+R` | Ricarica da disco |
| `Ctrl+P` | Stampa |

### Modifica

| Scorciatoia | Azione |
|---|---|
| `Ctrl+Z` | Annulla |
| `Ctrl+Y` | Ripeti |
| `Ctrl+X` / `C` / `V` | Taglia / Copia / Incolla |
| `Ctrl+A` | Seleziona tutto |
| `Ctrl+E` | Attiva/disattiva commento |
| `Ctrl+Shift+I` | Indenta |
| `Ctrl+U` | Deindenta |
| `Ctrl+Alt+U` | Inverti maiuscolo/minuscolo |
| `Ctrl+B` | Grassetto (Markup) |
| `Ctrl+I` | Corsivo (Markup) |
| `Ctrl+Shift+X` | Barrato (Markup) |
| `Alt+E` | Avvolgi in Ambiente / Tag |
| `Alt+T` | Allinea Tabella |

### Cerca e navigazione

| Scorciatoia | Azione |
|---|---|
| `Ctrl+Shift+P` | **Elenco comandi (Command Palette)** |
| `Ctrl+Shift+G` | **Vai a… (file aperto / riga / simbolo / comando)** |
| `Ctrl+F` | Apri dialog Cerca |
| `Ctrl+H` | Apri dialog Sostituisci |
| `F3` | Trova successivo |
| `Shift+F3` | Trova precedente |
| `Ctrl+Shift+F2` | Ricerca incrementale inline |
| `Ctrl+G` | Vai alla riga |
| `Ctrl+]` | Vai alla parentesi corrispondente |

### Evidenziazione colori

| Scorciatoia | Azione |
|---|---|
| `Ctrl+1` | Evidenzia in Rosso |
| `Ctrl+2` | Evidenzia in Verde |
| `Ctrl+3` | Evidenzia in Blu |
| `Ctrl+4` | Evidenzia in Arancione |
| `Ctrl+5` | Evidenzia in Viola |
| `Ctrl+0` | Rimuovi tutti i mark |

### Bookmark

| Scorciatoia | Azione |
|---|---|
| `Ctrl+F2` | Toggle bookmark riga corrente |
| `F2` | Prossimo bookmark |
| `Shift+F2` | Bookmark precedente |

### Visualizzazione

| Scorciatoia | Azione |
|---|---|
| `Alt+Z` | A capo automatico |
| `Ctrl+=` | Zoom in |
| `Ctrl+-` | Zoom out |
| `Ctrl+0` | Zoom reset |
| `F11` | **Modalità scrittura (distraction-free)** |
| `F12` | Anteprima |
| `Ctrl+Shift+E` | File Browser |
| `Ctrl+Shift+F` | Function List |
| `` Ctrl+` `` | Pannello compilazione e terminale |
| `Ctrl+Alt+T` | Modalità testo semplice (per tab) |
| `F4` | Controllo ortografico |

### Multi-cursore

| Scorciatoia | Azione |
|---|---|
| `Ctrl+D` | Seleziona prossima occorrenza |
| `Ctrl+Shift+D` | Seleziona tutte le occorrenze |
| `Ctrl+Alt+↑` | Aggiungi cursore sopra |
| `Ctrl+Alt+↓` | Aggiungi cursore sotto |
| `Ctrl+Shift+Alt+C` | Inserisci numeri incrementali |
| `Esc` | Rimuovi cursori extra |

### Split View

| Scorciatoia | Azione |
|---|---|
| `Ctrl+Alt+1` | Rimuovi split |
| `Ctrl+Alt+2` | Split verticale |
| `Ctrl+Alt+3` | Split orizzontale |
| `Ctrl+Alt+R` | Ruota orientazione |
| `Ctrl+Alt+M` | Sposta tab nell'altro pannello |

### Altro

| Scorciatoia | Azione |
|---|---|
| `Ctrl+Alt+P` | Preferenze |
| `Insert` | Modalità sovrascrittura |
| `F6` | Compila |
| `F7` | Build |
| `F8` | Profili di build |

---

*Manuale aggiornato — NotePadPQ 0.3.1*

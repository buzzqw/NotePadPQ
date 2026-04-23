# NotePadPQ — Manuale d'uso

> Versione 0.2.0 — Editor di testo avanzato basato su **QScintilla/PyQt6**  
> Piattaforme: Linux (Arch), FreeBSD, Windows, macOS

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
17. [Espressioni regolari — riferimento completo](#17-espressioni-regolari--riferimento-completo)
18. [Scorciatoie da tastiera — riepilogo](#18-scorciatoie-da-tastiera--riepilogo)

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
- **Pannelli dock** — File Browser, Function List, Anteprima, Output compilazione, Terminale

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
| Anteprima di stampa | — |
| Esporta PDF | — |
| Chiudi tab | `Ctrl+W` |
| Chiudi altri tab | — |
| Chiudi tutti | `Shift+Ctrl+W` |
| Esci | `Ctrl+Q` |

### File recenti
**File → File recenti** mostra gli ultimi file aperti. Clicca per riaprirli. Il numero massimo di file nella cronologia è configurabile nelle Preferenze.

### Nuovo da modello
**File → Nuovo da modello** crea un file con intestazione per: Python, HTML, LaTeX, Markdown, Bash, C/C++, JavaScript.

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
| Indenta | `Ctrl+I` |
| Deindenta | `Ctrl+U` |
| Indentazione intelligente | — |
| Rimuovi spazi finali | — |
| Tab → spazi | — |
| Spazi → tab | — |

> **Nota — A capo automatico vs. Spezza righe:**  
> **Visualizza / Documento → A capo automatico** (`Alt+Z`) è una visualizzazione: il testo appare mandato a capo a schermo senza modificare il file.  
> **Modifica → Formatta → Spezza righe lunghe** inserisce fisicamente `\n` nel testo — il file viene modificato. Usare con attenzione.

### Auto-chiusura parentesi
**Modifica → Auto-chiusura parentesi** (toggleable) — chiude automaticamente `(`, `[`, `{`, `"`, `'` quando li digiti.

---

## 4. Cerca e Sostituisci

Apri con `Ctrl+F`. Il dialog ha 4 tab.

### Tab "Cerca"

**Opzioni disponibili:**

| Opzione | Effetto |
|---|---|
| Maiuscole/minuscole | Distingue `Foo` da `foo` |
| Parola intera | Trova solo `ciao` e non `ciaoc` |
| Espressione regolare | Abilita la sintassi regex Python |
| Cerca circolare | Riparte dall'inizio/fine al termine del documento |
| Nella selezione | Cerca solo nel testo selezionato |

**Pulsanti:**

- **Trova successivo** — trova la prossima occorrenza (`F3`)
- **Trova precedente** — trova l'occorrenza precedente (`Shift+F3`)
- **Segna tutto** — evidenzia tutte le occorrenze con un bordo arancione sotto il testo
- **Conta** — popola la lista in basso con tutte le occorrenze e mostra il totale

**Lista occorrenze** (in basso nel tab):  
Viene popolata automaticamente mentre digiti (dopo 2 caratteri) e dal pulsante Conta.  
I numeri di riga sono allineati a destra. Doppio clic su una riga → salta a quella posizione nel documento.

**Manuale regex** (appare quando "Espressione regolare" è attivo):  
Pannello a font monospace con tutta la sintassi organizzata per sezioni — vedi anche [sezione 17](#17-espressioni-regolari--riferimento-completo).

### Tab "Sostituisci"

Stesse opzioni del tab Cerca più:

- **Sostituisci** — sostituisce l'occorrenza selezionata e passa alla successiva
- **Sostituisci tutto** — sostituisce tutte le occorrenze nel documento

Nel campo "Sostituisci con" puoi usare `\1`, `\2`, ... per riferirsi ai gruppi catturati dall'espressione regolare.

### Tab "Cerca nei file"

Cerca in tutti i file di una directory (con filtro estensioni e opzione ricorsiva).  
I risultati mostrano file e righe — doppio clic apre il file alla riga corrispondente.

### Tab "Cerca in tutti i documenti"

Cerca (e opzionalmente sostituisce) in tutti i file aperti nei tab.

### Ricerca incrementale inline

`Ctrl+F2` — apre una barra inline piccola in fondo all'editor per cercare senza aprire il dialog. Premi `Esc` per chiuderla.

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

**Smart Highlight** (automatico):  
Quando sposti il cursore su una parola, tutte le sue occorrenze vengono evidenziate automaticamente con un box grigio-blu tenue. È separato dai 5 colori manuali e non interferisce con essi.

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

### Zoom

| Azione | Scorciatoia |
|---|---|
| Zoom in | `Ctrl+=` |
| Zoom out | `Ctrl+-` |
| Zoom reset | `Ctrl+0` |

Anche `Ctrl+Rotella mouse` direttamente nell'editor.

### Schermo intero
`F11` — alterna la modalità a schermo intero.

### Minimap
Colonna stretta sul lato dell'editor che mostra una versione rimpicciolita dell'intero documento. Clicca per navigare velocemente.

### Anteprima (`F12`)
Apre il pannello Anteprima affiancato all'editor. Supporta:

- **Markdown** — rendering HTML in background, non blocca l'editor durante la digitazione
- **HTML** — preview diretta
- **LaTeX** — albero della struttura navigabile (sezioni, label, figure, tabelle)
- **reStructuredText** — rendering via docutils
- **PDF** — visualizzazione con PyMuPDF, navigazione pagine, zoom, SyncTeX

L'anteprima si aggiorna automaticamente con un delay configurabile (default 500ms). Non si aggiorna se il pannello è nascosto (risparmio CPU).

---

## 8. Documento

### Impostazioni documento corrente

- **Tipo indentazione** — Tab o Spazi
- **Larghezza indentazione** — numero di spazi
- **Sola lettura** — blocca le modifiche
- **Scrivi BOM** — aggiunge Byte Order Mark per UTF-8/UTF-16
- **A capo automatico** — identica alla voce in Visualizza (stessa azione)

### Tipo di file (syntax highlighting)

**Documento → Imposta tipo di file** — seleziona manualmente il linguaggio. NotePadPQ rileva automaticamente il tipo dal suffisso del file.

Linguaggi supportati: Bash/Shell, C/C++, C#, CMake, CSS, Diff, Go, HTML, INI/Config, Java, JavaScript, JSON, LaTeX, Lua, Makefile, Markdown, PHP, Python, Ruby, Rust, SQL, Testo normale, TypeScript, XML, YAML.

### Codifica (encoding)

**Documento → Imposta codifica** — cambia l'encoding per il prossimo salvataggio.

### Terminatori di riga

**Documento → Imposta terminatori** — LF (Unix), CRLF (Windows), CR (Mac).

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
Esegue il comando associato al tipo di file corrente e mostra l'output nel pannello "Output compilazione" — tasti `F6` (Compila), `F7` (Build), pulsante Stop.

### Macro
Registra e riproduce sequenze di tasti: Avvia/Ferma registrazione, Riproduci, Riproduci N volte, Salva/Carica su file.

### Altri strumenti

| Strumento | Funzione |
|---|---|
| **Color Picker** | Selettore colore con codici HEX/RGB/HSL inseribili nell'editor |
| **Tester Regex** | Dialog interattivo per testare espressioni regolari sul testo |
| **Convertitore numerico** | Conversione tra decimale, esadecimale, binario, ottale |
| **Statistiche colonna** | Analisi statistica dei valori numerici nella colonna corrente |
| **Editor scorciatoie** | Personalizzazione dei tasti di scelta rapida |
| **Sessioni con nome** | Salva e ripristina gruppi di file come sessioni nominate |

---

## 10. Plugin

I plugin vengono caricati automaticamente dalla cartella `plugins/`. Per installarli, copiali nella cartella `plugins/` oppure mettili in `plugins_to_copy/` e riesegui `setup.sh`.

| Plugin | Funzione |
|---|---|
| **Clipboard History** | Cronologia degli appunti con possibilità di incollare elementi precedenti |
| **Compare & Merge** | Confronto visuale side-by-side di due file o tab |
| **Encrypt/Decrypt** | Cifratura e decifratura AES del testo selezionato o dell'intero file |
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

**Azioni rapide** (barra superiore): Pull (con opzione --rebase), Push (con opzione --force-with-lease), Commit (dialog con selezione file e opzione amend), Stash, Fetch.

**Configurazione credenziali** (`Plugin → Git: Configura utente & token` oppure tab Config):

- Nome e email Git locale (per il repo corrente) e globale
- Token GitHub — salvato in keyring o `~/.config/notepadpq/git_tokens.json`
- Token GitLab — con supporto URL self-hosted

Con i token configurati è possibile creare Pull Request (GitHub) e Merge Request (GitLab) direttamente dal pannello (richiede `pip install PyGithub` o `pip install python-gitlab`).

---

## 11. Pannelli laterali e inferiori

Tutti i pannelli sono dock widget: possono essere spostati, ridimensionati, staccati come finestre flottanti o riagganciati trascinando il titolo.

### File Browser (`Ctrl+Shift+E`)
Pannello sinistro con la struttura di directory. Doppio clic su un file per aprirlo nell'editor.

### Function List (`Ctrl+Shift+F`)
Pannello con la lista di funzioni, classi e metodi del file corrente. Si aggiorna automaticamente durante la digitazione.

- **Aggiornamento lazy** — se il pannello è nascosto, il refresh viene posticipato al momento in cui lo apri (nessun consumo CPU inutile)
- **Filtro** — ricerca incrementale per nome funzione
- **Ordinamento** — ordine di apparizione nel file (default) o alfabetico (pulsante A↓)
- **Doppio clic** — salta direttamente alla riga nel file
- **Context menu** — vai alla riga, copia nome funzione

Linguaggi con parser dedicato: Python, JavaScript/TypeScript, C/C++, Java, Bash, SQL, LaTeX, Markdown.

### Output compilazione
Pannello inferiore con l'output testuale del comando build. La lista errori è cliccabile: click su un errore → salta alla riga nel file sorgente. Dopo una compilazione LaTeX riuscita, il pulsante **📄 PDF** apre il documento generato nel pannello Anteprima.

### Terminale integrato
Tab nel pannello inferiore. Terminale completo basato su PTY nativo — supporta qualsiasi programma interattivo (vim, python REPL, ssh, ecc.).

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

**Uso tipico:** seleziona una parola → `Ctrl+D` ripetuto per aggiungere le occorrenze successive → digita per sostituire tutte simultaneamente.

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

**Sessioni con nome:** tramite **Strumenti → Sessioni con nome** puoi salvare e ripristinare gruppi di file come sessioni nominate indipendenti dalla sessione automatica.

---

## 15. Preferenze

Apri con `Ctrl+Alt+P` oppure **Strumenti → Preferenze**. Le modifiche possono essere applicate immediatamente con il pulsante **Applica** senza chiudere il dialog.

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
- **Set di icone toolbar** — Lucide (lineari, moderne), Material (Google, piene), Sistema (icone native OS). Se il set non è presente localmente, viene scaricato automaticamente da internet al momento della selezione. Il download mostra una barra di avanzamento con il nome di ogni icona scaricata e un riepilogo finale.

### Scheda File
- Encoding predefinito (UTF-8, UTF-8 BOM, Latin-1, CP1252, UTF-16, GB2312)
- Line ending predefinito (LF, CRLF, CR)
- Backup al salvataggio (`.bak`)
- Rimuovi spazi in coda al salvataggio
- Aggiungi newline a fine file
- Ripristina sessione all'avvio
- Numero massimo file recenti
- **Autobackup periodico** — intervallo in minuti e cartella di destinazione

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

Questo comportamento si attiva anche da riga di comando:

```bash
# Se NotePadPQ è già aperto, questo comando apre il file nella sessione esistente
python main.py nuovo_file.py
```

Non è necessaria nessuna configurazione: funziona automaticamente su Linux, Windows e macOS.

---

## 17. Espressioni regolari — riferimento completo

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

## 18. Scorciatoie da tastiera — riepilogo

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

### Modifica

| Scorciatoia | Azione |
|---|---|
| `Ctrl+Z` | Annulla |
| `Ctrl+Y` | Ripeti |
| `Ctrl+X` / `C` / `V` | Taglia / Copia / Incolla |
| `Ctrl+A` | Seleziona tutto |
| `Ctrl+E` | Attiva/disattiva commento |
| `Ctrl+I` | Indenta |
| `Ctrl+U` | Deindenta |
| `Ctrl+Alt+U` | Inverti maiuscolo/minuscolo |

### Cerca

| Scorciatoia | Azione |
|---|---|
| `Ctrl+F` | Apri dialog Cerca |
| `Ctrl+H` | Apri dialog Sostituisci |
| `F3` | Trova successivo |
| `Shift+F3` | Trova precedente |
| `Ctrl+F2` | Ricerca incrementale inline / Toggle bookmark |
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
| `F11` | Schermo intero |
| `F12` | Anteprima |
| `Ctrl+Shift+E` | File Browser |
| `Ctrl+Shift+F` | Function List |
| `` Ctrl+` `` | Terminale |

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
| `Ctrl+Ins` | Modalità sovrascrittura |
| `F6` | Compila |
| `F7` | Build |

---

*Manuale aggiornato — NotePadPQ 0.1.0*

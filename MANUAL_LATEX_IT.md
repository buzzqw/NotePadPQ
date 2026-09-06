# Manuale LaTeX di NotePadPQ

Versione 1.9.9

Questo è il riferimento completo per l'uso di LaTeX in NotePadPQ. Comprende
modifica, risoluzione del progetto, compilazione, anteprima PDF, progetti
multi-file, SyncTeX, autocompletamento, diagnostica e strumenti esterni
opzionali.

Per la guida generale dell'applicazione, vedere [MANUAL_IT.md](MANUAL_IT.md).

## 1. Ambito e requisiti

NotePadPQ fornisce editor e integrazione con il progetto. Non installa una
distribuzione TeX. Installare separatamente gli engine e gli strumenti richiesti
dal documento e verificare che siano disponibili nel `PATH`.

### Installazione minima

Installare almeno un engine LaTeX e i pacchetti richiesti dal documento.
`latexmk` è consigliato perché esegue i passaggi necessari per riferimenti e
file ausiliari.

Su Debian o Ubuntu, una configurazione tipica è:

```bash
sudo apt install latexmk texlive-latex-extra biber
python -m pip install -e ".[latex]"
```

I nomi dei pacchetti cambiano in base alla distribuzione. Per una toolchain
completa, verificare i comandi necessari:

```bash
command -v pdflatex
command -v xelatex
command -v lualatex
command -v latexmk
command -v bibtex
command -v biber
command -v synctex
```

Per installare le librerie opzionali di NotePadPQ usare lo script di setup e
selezionare **[1] LaTeX avanzato**:

```bash
bash setup.sh
```

Oppure installarle direttamente:

```bash
pip install pymupdf matplotlib sympy
```

Su Arch Linux i pacchetti corrispondenti includono:

```bash
sudo pacman -S python-pymupdf python-matplotlib python-sympy texlive-bin
sudo pacman -S biber perl-yaml-tiny perl-file-homedir texlab
```

`texlab` è opzionale. Senza server LSP NotePadPQ mantiene fallback locali per
completamento e navigazione semantica. `perl-yaml-tiny` e
`perl-file-homedir` sono necessari a `latexindent`.

### Dipendenze delle funzionalità

| Funzionalità | Requisito |
|---|---|
| Evidenziazione, folding, completamento e checker | Nessuna libreria Python extra |
| Anteprima PDF e anteprima immagini al passaggio del mouse | `pymupdf` |
| Rendering hover delle equazioni | `matplotlib` |
| Calcolo simbolico | `sympy` |
| Navigazione SyncTeX editor/PDF | `synctex` e un engine compilato con SyncTeX |
| Diagnostica e navigazione LSP | `texlab` |
| Documentazione dei pacchetti | `texdoc` o connessione Internet per CTAN |
| Diagnostica esterna | `chktex` o `lacheck` |
| Formattazione | `latexindent` |

Le funzioni opzionali si attivano automaticamente quando la dipendenza è
presente. L'editor resta utilizzabile anche senza di esse.

## 2. Primo progetto LaTeX

1. Creare o aprire una directory contenente i file `.tex`.
2. Aprire il documento che contiene `\documentclass` e `\begin{document}`.
3. Salvare il file prima di configurare un profilo di build.
4. Aprire il **Pannello Build** e selezionare un profilo LaTeX.
5. Compilare con **Build -> Compila** o `F6`.
6. Aprire il pannello Anteprima con `F12`, quindi usare il pulsante `▶` per
   compilare il progetto LaTeX direttamente nell'anteprima.

Un documento minimo è:

```tex
\documentclass{article}
\usepackage{amsmath}

\begin{document}
Ciao da NotePadPQ.

\section{Prima sezione}
Un'equazione: $a^2+b^2=c^2$.
\end{document}
```

Comando di compilazione, directory di output e PDF generato dipendono dal
profilo attivo. Se manca un engine, l'errore viene mostrato nel pannello Build
senza sostituirlo silenziosamente con un altro engine.

## 3. Funzioni di modifica

I file LaTeX ricevono syntax highlighting, code folding per le coppie
`\begin{...}`/`\end{...}`, indentazione e completamento contestuale.

### Autocompletamento contestuale

Il completamento riconosce il contesto LaTeX corrente:

- `\cite{` propone le chiavi BibTeX trovate nel progetto.
- `\ref{`, `\pageref{` ed `\eqref{` propongono le label.
- `\begin{` propone gli ambienti noti.
- `\usepackage{` propone i pacchetti.
- `[` propone opzioni di comando, ambiente o pacchetto.
- Nei valori key-value, `,` avvia la chiave successiva e `=` propone i valori
  noti quando presenti nei dati CWL caricati.

I suggerimenti specifici dei pacchetti vengono attivati dai pacchetti rilevati
nel sorgente. Esempi: `multicol`, `tabularx`, `longtable` e `tabulary`.

Il popup degli ambienti può partire da prefissi brevi come `\be` o `\en`.
Rinominando un ambiente vengono mantenuti sincronizzati i nomi di `\begin` e
`\end`. `Alt+E` avvolge la selezione in un ambiente o tag.

### Assistenti del menu LaTeX

- **Assistente LaTeX** genera equazioni, ambienti e tabelle; il codice può
  essere controllato e modificato prima dell'inserimento.
- **Tabella rapida** configura ambiente, allineamento, bordi, celle unite,
  caption e label per definire visivamente la struttura della tabella.
- **BibTeX Wizard** crea voci guidate, genera una chiave e può recuperare dati
  da un DOI tramite Crossref.
- **Palette simboli** cerca comandi divisi per lettere greche, operatori,
  relazioni, frecce, delimitatori e font.
- **Chooser citazioni** cerca le chiavi BibTeX in tutto il progetto e inserisce
  quella selezionata.

Trascinando un'immagine PNG, JPEG, SVG, PDF o altro formato supportato
sull'editor LaTeX si apre l'assistente figura. Dopo la conferma può inserire
`\includegraphics`, dimensioni, ambiente `figure`, caption e label. I percorsi
diventano relativi al progetto quando possibile e `graphicx` viene assicurato
nel preambolo.

## 4. File root e progetti multi-file

Build e strumenti semantici hanno bisogno di un documento root. La root viene
risolta in quest'ordine:

1. Direttiva esplicita come `% !TEX root = main.tex`.
2. Configurazione del progetto o della build.
3. Documento contenente `\documentclass`.
4. File corrente come ultimo fallback.

Usare una direttiva nei file inclusi quando può esserci più di una candidata:

```tex
% !TEX root = ../main.tex
```

Il percorso è relativo al file che contiene la direttiva. L'estensione può
essere omessa nei casi consentiti normalmente da LaTeX.

Il parser segue i principali comandi di inclusione, tra cui:

```tex
\input{capitoli/introduzione}
\include{capitoli/risultati}
\subfile{capitoli/conclusione}
```

Raccoglie sezioni, label, citazioni, comandi custom e contesto dei pacchetti
attraverso il grafo dei sorgenti risolto. Lo stesso grafo alimenta
completamento, navigazione semantica, Dashboard progetto e Riferimenti globali.

### File non salvati

L'editor mantiene in memoria il testo modificato, quindi il tab attivo può
essere compilato dal contenuto corrente quando il profilo lo consente. Una
build avviata dalla toolchain esterna legge normalmente i file dal disco.
Prima di una build completa, abilitare **Salva automaticamente prima di
compilare** oppure salvare i file interessati con `Ctrl+S`/`Shift+Ctrl+S`.

Anche l'albero dell'anteprima LaTeX viene ricostruito dalla root e dal progetto
risolti. Se un tab incluso non attivo contiene modifiche non salvate, salvarlo
prima di compilare per assicurarsi che il compilatore esterno legga gli stessi
contenuti dell'editor.

## 5. Profili di build e ricette

Il pannello Build supporta profili built-in, utente e progetto. Un profilo può
definire:

- engine LaTeX o comando `latexmk`;
- argomenti e directory di lavoro;
- directory di output;
- variabili d'ambiente;
- comandi sequenziali pre-build e post-build;
- processori ausiliari come BibTeX, Biber, MakeIndex e MakeGlossaries;
- pulizia dei file ausiliari;
- timeout e limite dell'output.

Usare `F8` o **Build -> Profili di build** per ispezionare e modificare i
profili. La finestra **Ricette LaTeX** mostra profilo attivo e pipeline dei
comandi. Le impostazioni globali esistenti e i profili di progetto
`.notepadpq-build.json` restano validi.

Comandi tipici sono:

```text
pdflatex -interaction=nonstopmode -synctex=1 <root>.tex
xelatex -interaction=nonstopmode -synctex=1 <root>.tex
lualatex -interaction=nonstopmode -synctex=1 <root>.tex
latexmk -pdf -synctex=1 <root>.tex
latexmk -xelatex -synctex=1 <root>.tex
```

Preferire `latexmk` per progetti con bibliografia, indici o più passaggi di
riferimenti incrociati. Mantenere coerente la directory di output del profilo,
così anteprima e SyncTeX trovano PDF e file `.synctex` generati.

### Strumenti ausiliari automatici

Il menu Build può eseguire i processori ausiliari quando rileva i relativi
comandi nel sorgente. La pipeline concettuale è:

```text
LaTeX -> makeindex/makeglossaries/nomencl -> passaggio LaTeX finale
```

Usare ricette esplicite quando il progetto richiede più indici nominati o un
ordine personalizzato. Il menu LaTeX può inserire `\makeindex`,
`\makeglossaries` e `\makenomenclature`.

### Output ed errori

L'output della build viene trasformato in diagnostica navigabile. Fare click su
errore o warning per saltare alla posizione nel sorgente. `Alt+Su` e `Alt+Giù`
spostano tra gli errori di build. Le preferenze Build controllano salvataggio
automatico, build al salvataggio, vista unificata errori LSP/build, numero
massimo di righe e timeout.

## 6. Anteprima PDF

Il pannello Anteprima ha due modalità LaTeX:

- **PDF compilato** quando un compilatore supportato ha prodotto un PDF.
- **Vista strutturale del sorgente** come fallback quando compilazione o
  rendering PDF non sono disponibili. Mostra l'albero dei sorgenti risolti e
  non presenta il LaTeX non compilato come se fosse un PDF finale.

Aprire il pannello con `F12`. Quando è attivo un documento LaTeX, premere `▶`
nella toolbar dell'anteprima per compilare il progetto root. Il pulsante di
refresh aggiorna l'anteprima corrente. Il rendering PDF nel pannello richiede
`pymupdf`.

L'anteprima riconosce file inclusi e root risolta, non soltanto il tab corrente.
Se manca il compilatore, consultare pannello Build e Dashboard progetto per
percorsi e versioni della toolchain.

### Visualizzatore PDF esterno

Nelle preferenze Anteprima si può configurare un viewer esterno. Esempi:

```text
zathura {PDF}
SumatraPDF.exe {PDF}
```

Lasciando vuoto il campo viene usato il viewer predefinito del sistema. `{PDF}`
viene sostituito come un singolo argomento sicuro.

## 7. SyncTeX

SyncTeX collega le posizioni nel sorgente e nel PDF. La build deve generare un
file `.synctex` o `.synctex.gz`, normalmente passando `-synctex=1` all'engine o
a `latexmk`.

- Posizionare il cursore su una riga sorgente e usare la sincronizzazione in
  avanti per raggiungere la posizione corrispondente nel PDF.
- Fare click nel PDF per la sincronizzazione all'indietro e aprire file e riga
  sorgente corrispondenti.
- Nei progetti multi-file viene usato il grafo risolto e può essere aperto
  direttamente un file incluso.

Se la sincronizzazione non funziona, verificare che PDF e file SyncTeX
provengano dalla stessa build, che la directory di output sia corretta e che
l'engine sia stato avviato con SyncTeX attivo. Ricompilare dopo aver cambiato
root o directory di output.

## 8. Diagnostica e strumenti semantici

I checker interni funzionano indipendentemente dagli strumenti esterni:

- **Bilanciamento ambienti** rileva coppie `\begin`/`\end` non bilanciate e
  marca il gutter.
- **Colonne tabella** controlla `tabular`, `tabular*`, `tabularx`, `tabulary`,
  `array`, `longtable`, `supertabular` e `xltabular`. Comprende
  `\multicolumn{N}` e sottolinea solo la parte in eccesso della riga o della
  column specification.
- **TikZ** cerca comandi come `\draw`, `\path` e `\node` senza punto e
  virgola finale dentro `tikzpicture`. Un costrutto di controllo `\foreach` non
  richiede un punto e virgola proprio.
- **Struttura** riconosce sezioni con titolo breve per l'indice, come
  `\section[Voce breve]{Titolo completo}`.

La **Dashboard progetto** mostra root risolta, numero di sorgenti, percorsi di
output e PDF, profilo selezionato, salute del progetto, strumenti ausiliari e
disponibilità della toolchain.

**Riferimenti globali** analizza definizioni, riferimenti, citazioni, label
duplicate o inutilizzate, inclusioni e asset mancanti. Il doppio click porta
alla posizione nel sorgente.

### Strumenti esterni

Da **LaTeX -> Strumenti progetto** è possibile eseguire esplicitamente:

- `ChkTeX` o `lacheck` per diagnostica esterna;
- `latexindent` per formattare dopo un subprocess riuscito; in caso di errore
  il testo originale resta invariato e una sostituzione riuscita è una singola
  operazione di undo;
- `texdoc` e ricerca CTAN per la documentazione di pacchetti o comandi.

## 9. Autocompletamento CWL

NotePadPQ comprende i file di completamento `.cwl` in stile TeXstudio. I file
vengono caricati lazy dalle directory built-in, utente, configurate e di
progetto. Il completamento statico resta disponibile come fallback e i file
CWL corrotti vengono ignorati.

Configurare directory aggiuntive nelle preferenze di completamento LaTeX o con:

```bash
export NOTEPADPQ_CWL_DIRS="$HOME/tex/cwl:/workspace/progetto/cwl"
```

Usare il separatore previsto dalla piattaforma per più directory. I dati CWL
possono fornire comandi, ambienti, pacchetti, chiavi di opzioni e valori. Sono
un'integrazione del completamento built-in, non una sua sostituzione.

## 10. Risoluzione dei problemi

### Il pannello Build segnala che manca un engine

Controllare l'eseguibile fuori da NotePadPQ e riavviare l'applicazione se
l'installazione ha modificato il `PATH`:

```bash
which latexmk
latexmk -v
```

Controllare profilo attivo e directory di lavoro. Con più installazioni TeX,
usare eventualmente il percorso assoluto dell'eseguibile nel profilo.

### Il PDF è vecchio o viene mostrato il file sbagliato

Confermare la root nella Dashboard progetto, salvare tutti i file inclusi,
ricompilare e verificare la directory di output del profilo. Eliminare output
vecchi solo dopo aver verificato che nessun altro processo stia usando quella
directory.

### Non compaiono riferimenti o citazioni

Verificare che il file bibliografico sia raggiungibile dalla root risolta e che
il comando sia abbastanza completo da attivare il suggerimento (`\cite{`). Nei
progetti multi-file, controllare i percorsi di `\input`, `\include` o
`\subfile` e salvare i file prima di una build basata sul disco.

### SyncTeX non trova la riga sorgente

Ricompilare con `-synctex=1`, mantenere PDF e file SyncTeX nella directory di
output configurata ed evitare di aprire un PDF appartenente a una build o a un
profilo diverso.

### L'anteprima mostra l'albero del sorgente

Non è disponibile un PDF compilato utilizzabile. Installare engine e `latexmk`,
correggere l'errore di build oppure installare `pymupdf` se la compilazione
riesce ma il pannello non visualizza il PDF.

### `latexindent` non si avvia

Su Arch Linux installare `perl-yaml-tiny` e `perl-file-homedir`, oppure i moduli
Perl equivalenti per la distribuzione in uso. Il checker interno non dipende da
`latexindent`.

## 11. Scorciatoie utili

| Scorciatoia | Azione |
|---|---|
| `F6` | Compila |
| `F7` | Build |
| `F8` | Profili di build |
| `F12` | Anteprima |
| `Ctrl+S` | Salva il file corrente |
| `Shift+Ctrl+S` | Salva tutto / Salva con nome |
| `Alt+Su` / `Alt+Giù` | Errore build precedente / successivo |
| `Ctrl+Shift+F` | Function List |
| `Ctrl+Shift+E` | File Browser |
| `Ctrl+F12` | Vai alla definizione LSP o semantica |
| `Shift+F12` | Mostra riferimenti |
| `Alt+Shift+F` | Formatta documento tramite LSP |
| `Ctrl+Alt+P` | Preferenze |

## 12. Limiti e workflow sicuro

- NotePadPQ fornisce integrazione con l'editor, non i pacchetti TeX né una
  distribuzione TeX completa.
- L'albero del sorgente è un fallback e non sostituisce una build PDF riuscita.
- Le build esterne basate sul disco non vedono modifiche non salvate nei tab
  inattivi; salvare prima di compilare.
- Un progetto con più root possibili dovrebbe usare una direttiva root esplicita.
- Gli strumenti Build eseguono i comandi configurati dall'utente. Controllare
  profili e file di build prima di eseguirli, soprattutto nei progetti non
  attendibili.

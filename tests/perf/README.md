# Benchmark prestazioni

Non fa parte della suite pytest: misura tempi e memoria dell'applicazione vera.
Si esegue con una HOME temporanea per non toccare configurazione e sessione.

```bash
python tests/perf/gen_data.py /tmp/npq-data      # crea file di prova (circa 190 MB)
export HOME=$(mktemp -d) QT_QPA_PLATFORM=offscreen
python tests/perf/bench.py startup               # avvio e moduli caricati
python tests/perf/bench.py real /percorso/doc.tex  # apertura, scroll, digitazione
python tests/perf/bench.py pdf /percorso/doc.tex   # anteprima del PDF omonimo
```

Il risultato è una riga `BENCH={json}`. Altri scenari: `open`, `type`, `pause`,
`tabs`, `idle`, `mem`, `ops`, `brk`, `roots`, `overlap`, `spikes`, `verify`.

Attenzione a tre trappole:

- tieni ogni `.tex` di prova in una cartella sua, perché la ricerca del documento
  radice legge i file vicini;
- `offscreen` non include il costo del display: per i tempi reali usa
  `python main.py --profile` e leggi `notepadpq-performance.log`;
- il campionatore dello scenario `real` è falsato dal GIL: per attribuire i costi
  usa `type FILE prof` o i tempi di `brk`.

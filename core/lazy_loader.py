"""
core/lazy_loader.py — Caricamento lazy per file di grandi dimensioni
NotePadPQ

Per file oltre la soglia (default 50MB, configurabile), il file viene
caricato in chunks nel thread di background. L'editor mostra subito
il primo chunk e aggiunge il resto progressivamente senza bloccare l'UI.

Per file oltre 200MB viene usata la modalità "paginata": il file viene
letto a pagine (~4MB, allineate a fine riga) con navigazione tramite un
cursore virtuale sul disco, senza mai caricare l'intero file in RAM.
La pagina visibile resta modificabile; passare a un'altra pagina con
modifiche non salvate richiede prima di salvarle (in streaming, senza
mai materializzare l'intero file in memoria) o scartarle esplicitamente.

API:
    loader = LazyLoader(path, editor, main_window)
    loader.start()           # avvia il caricamento in background
    loader.cancel()          # annulla (es. tab chiuso)

    # Oppure, per file non enormi, usa il wrapper diretto:
    LazyLoader.open_file(path, editor, main_window)
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional, Callable, TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal, QTimer, Qt
from PyQt6.QtWidgets import QProgressDialog, QApplication, QLabel, QPushButton, QMessageBox
from PyQt6.Qsci import QsciScintilla

from core.file_manager import FileManager
from editor.editor_widget import LineEnding
from i18n.i18n import tr

if TYPE_CHECKING:
    from editor.editor_widget import EditorWidget
    from ui.main_window import MainWindow

# ─── Soglie ───────────────────────────────────────────────────────────────────

MB  = 1024 * 1024
GB  = 1024 * MB

# Sotto questa soglia → caricamento normale sincrono
THRESHOLD_LAZY     = 50 * MB      # 50 MB

# Sopra questa soglia → modalità paginata: editing una pagina alla volta
# (~4MB), veloce indipendentemente dalla dimensione del file perché non lo
# tocca mai tutto. Sotto, il file viene caricato interamente in RAM (a
# chunk, in background) restando liberamente modificabile ovunque.
#
# Il limite reale qui non è la RAM ma QScintilla stesso: ogni append() su
# un documento che cresce costa via via di più (misurato ~0,05s a 8MB fino
# a ~0,46s a 126MB, con lo stesso pattern indipendentemente da undo/
# folding/scroll-tracking/segnali disattivati — è intrinseco al buffer
# interno dell'editor). Il totale cresce quindi più che linearmente con la
# dimensione del file: 200MB tiene il caricamento sotto la decina di
# secondi, oltre diventa rapidamente questione di minuti.
THRESHOLD_PAGED    = 200 * MB

# Dimensione chunk per loading progressivo (in bytes)
CHUNK_SIZE_BYTES   = 4 * MB       # 4 MB per chunk
CHUNK_SIZE_PAGED   = 4 * MB       # idem per paged mode

# Lettura extra oltre CHUNK_SIZE_PAGED per allineare la fine pagina a un \n,
# senza spezzare una riga o un carattere multibyte. Tetto per righe patologiche
# senza alcun \n (garantisce comunque un limite fisso di memoria per pagina).
PAGE_LOOKAHEAD_CAP = 1 * MB

# Dimensione blocco per la copia byte-a-byte durante il salvataggio in streaming
SAVE_COPY_CHUNK    = 4 * MB

# Delay tra chunk successivi in ms (lascia respiro all'event loop)
CHUNK_DELAY_MS     = 30


# ─── _LoadWorker ──────────────────────────────────────────────────────────────

class _LoadWorker(QObject):
    """
    Worker che gira in un QThread separato e legge il file a chunks.
    Emette chunk_ready(str) per ogni porzione di testo letta,
    finished() quando ha finito o cancelled() se interrotto.
    """

    chunk_ready = pyqtSignal(str, int, int)  # text, chunk_index, total_chunks
    finished    = pyqtSignal(str, str)       # encoding, line_ending_label
    error       = pyqtSignal(str)

    def __init__(self, path: Path):
        super().__init__()
        self._path     = path
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        """Eseguito nel thread di background."""
        try:
            file_size = self._path.stat().st_size

            # Rilevamento encoding dal header del file (primi 8KB)
            with open(self._path, "rb") as f:
                header = f.read(8192)

            encoding, bom_len = FileManager._detect_bom(header)
            if not encoding:
                encoding = FileManager._chardet_detect(header) or "UTF-8"

            # Calcola numero di chunk approssimativo
            total_chunks = max(1, file_size // CHUNK_SIZE_BYTES + 1)
            chunk_idx = 0
            detected_le = None

            with open(self._path, "rb") as f:
                # Salta BOM se presente
                if bom_len:
                    f.seek(bom_len)

                buffer = b""
                while True:
                    if self._cancelled.is_set():
                        return

                    raw = f.read(CHUNK_SIZE_BYTES)
                    if not raw:
                        break

                    buffer += raw
                    more_data = bool(f.peek(1))

                    # Decodifica sicura: ritaglia alla fine dell'ultimo \n
                    # per non spezzare sequenze multibyte a metà. \n è un byte
                    # ASCII che non può comparire come byte di continuazione
                    # UTF-8, quindi tagliare subito dopo è sempre un confine
                    # di carattere valido.
                    split_pos = buffer.rfind(b"\n")
                    if split_pos == -1 and more_data:
                        # Nessun \n in questo blocco e il file non è ancora
                        # esaurito: continua ad accumulare invece di
                        # decodificare a metà di una sequenza multibyte.
                        continue
                    elif not more_data:
                        # Fine file (nessun altro byte in arrivo): decodifica
                        # tutto il buffer residuo, \n o non \n.
                        try:
                            text = buffer.decode(encoding, errors="replace")
                        except Exception:
                            text = buffer.decode("latin-1", errors="replace")
                        buffer = b""
                    else:
                        decode_part = buffer[:split_pos + 1]
                        buffer = buffer[split_pos + 1:]
                        try:
                            text = decode_part.decode(encoding, errors="replace")
                        except Exception:
                            text = decode_part.decode("latin-1", errors="replace")

                    if detected_le is None and text:
                        detected_le = LineEnding.detect(text)

                    self.chunk_ready.emit(text, chunk_idx, total_chunks)
                    chunk_idx += 1

                # Eventuale coda
                if buffer and not self._cancelled.is_set():
                    try:
                        text = buffer.decode(encoding, errors="replace")
                    except Exception:
                        text = buffer.decode("latin-1", errors="replace")
                    self.chunk_ready.emit(text, chunk_idx, total_chunks)

            le_label = (detected_le.label() if detected_le else "LF")
            enc_display = encoding.upper().replace("-SIG", " BOM")
            self.finished.emit(enc_display, le_label)

        except Exception as e:
            self.error.emit(str(e))


# ─── PagedDocument ────────────────────────────────────────────────────────────

class PagedDocument:
    """
    Vista paginata e MODIFICABILE su un file enorme (>200MB). Legge pagine dal
    disco on-demand (~4MB, allineate a fine riga) senza mai caricare l'intero
    file in memoria, e permette di salvare in streaming le modifiche alla
    pagina corrente senza materializzare l'intero file in RAM.

    Nessuna scansione/indicizzazione preventiva dell'intero file: si tiene
    traccia solo degli offset delle pagine già visitate durante la
    navigazione (piccola lista di interi), così "pagina precedente" è
    immediato senza dover indicizzare tutto il file all'apertura. Il numero
    totale di pagine mostrato è quindi solo una stima (dimensione file /
    dimensione pagina), non un conteggio esatto.

    Si edita una pagina alla volta: chi usa questa classe (LazyLoader) deve
    salvare o scartare le modifiche della pagina corrente prima di
    navigare altrove — vedi `_attach_pager_ui` in LazyLoader.

    Usato da LazyLoader in modalità PAGED per attacharsi a un EditorWidget.
    """

    def __init__(self, path: Path):
        self.path = path
        self.file_size = path.stat().st_size
        self.page_size = CHUNK_SIZE_PAGED

        # Encoding rilevato dall'header
        with open(path, "rb") as f:
            header = f.read(8192)
        enc, self._bom_len = FileManager._detect_bom(header)
        self._encoding = enc or FileManager._chardet_detect(header) or "UTF-8"

        # Intervallo di byte [current_start, current_end) della pagina
        # attualmente caricata nell'editor.
        self.current_start = self._bom_len
        self.current_end = self._bom_len

        # Offset delle pagine visitate in ordine di navigazione (per Prev O(1)
        # senza indice) + puntatore alla posizione corrente in questa lista.
        self._history: list[int] = [self._bom_len]
        self._hist_pos: int = 0

    # ── Info ─────────────────────────────────────────────────────────────────

    @property
    def file_size_mb(self) -> float:
        return self.file_size / MB

    @property
    def total_pages_estimate(self) -> int:
        return max(1, self.file_size // self.page_size + 1)

    @property
    def current_page_number(self) -> int:
        return self._hist_pos + 1

    @property
    def progress_fraction(self) -> float:
        return (self.current_start / self.file_size) if self.file_size else 0.0

    def encoding(self) -> str:
        return self._encoding.upper().replace("-SIG", " BOM")

    def encoding_raw(self) -> str:
        return self._encoding

    # ── Lettura pagine ───────────────────────────────────────────────────────

    def read_page_at(self, start: int) -> str:
        """Legge la pagina che inizia all'offset di byte `start`, allineando
        la fine al prossimo \\n (o al tetto PAGE_LOOKAHEAD_CAP in assenza di
        \\n). Aggiorna current_start/current_end."""
        start = max(self._bom_len, min(start, self.file_size))
        self.current_start = start

        if start >= self.file_size:
            self.current_end = start
            return ""

        with open(self.path, "rb") as f:
            f.seek(start)
            data = bytearray(f.read(self.page_size))
            extra = 0
            while (start + len(data)) < self.file_size and not data.endswith(b"\n") \
                    and extra < PAGE_LOOKAHEAD_CAP:
                chunk = f.read(65536)
                if not chunk:
                    break
                nl = chunk.find(b"\n")
                if nl != -1:
                    data += chunk[:nl + 1]
                    extra += nl + 1
                    break
                data += chunk
                extra += len(chunk)

        self.current_end = start + len(data)
        return self._decode(bytes(data))

    def next_page(self) -> Optional[str]:
        if self._hist_pos + 1 < len(self._history):
            self._hist_pos += 1
            return self.read_page_at(self._history[self._hist_pos])
        if self.current_end >= self.file_size:
            return None
        self._history.append(self.current_end)
        self._hist_pos += 1
        return self.read_page_at(self.current_end)

    def prev_page(self) -> Optional[str]:
        if self._hist_pos <= 0:
            return None
        self._hist_pos -= 1
        return self.read_page_at(self._history[self._hist_pos])

    def jump_to_fraction(self, pct: float) -> str:
        """Salta a un punto approssimato del file (0.0–1.0), allineando in
        avanti al prossimo \\n. Ricomincia una nuova sequenza di navigazione
        da lì (niente Prev verso i punti visitati prima del salto)."""
        pct = max(0.0, min(1.0, pct))
        target = self._bom_len + int((self.file_size - self._bom_len) * pct)
        aligned = self._align_forward(target)
        self._history = [aligned]
        self._hist_pos = 0
        return self.read_page_at(aligned)

    def _align_forward(self, offset: int) -> int:
        offset = max(self._bom_len, min(offset, self.file_size))
        if offset <= self._bom_len or offset >= self.file_size:
            return offset
        with open(self.path, "rb") as f:
            f.seek(offset)
            data = f.read(PAGE_LOOKAHEAD_CAP)
        nl = data.find(b"\n")
        if nl == -1:
            return offset
        return offset + nl + 1

    def _decode(self, data: bytes) -> str:
        try:
            return data.decode(self._encoding, errors="replace")
        except Exception:
            return data.decode("latin-1", errors="replace")

    # ── Post-salvataggio ─────────────────────────────────────────────────────

    def apply_save_result(self, new_start: int, new_end: int) -> None:
        """Aggiorna lo stato dopo un salvataggio riuscito: la pagina salvata
        potrebbe avere una lunghezza diversa dall'originale, quindi gli
        offset delle pagine visitate DOPO quella corrente non sono più
        validi (il file è cambiato di dimensione da quel punto in poi)."""
        self.current_start = new_start
        self.current_end = new_end
        self.file_size = self.path.stat().st_size
        self._history = self._history[: self._hist_pos + 1]


# ─── _SaveWorker ──────────────────────────────────────────────────────────────

class _SaveWorker(QObject):
    """
    Worker che gira in un thread separato e salva in streaming la pagina
    corrente di un PagedDocument: copia byte-a-byte le porzioni non toccate
    del file originale e sostituisce solo l'intervallo della pagina
    modificata, senza mai caricare l'intero file in RAM. Scrive su un file
    temporaneo nella stessa cartella e lo sostituisce atomicamente a fine
    scrittura.
    """

    progress = pyqtSignal(int)             # 0–100
    finished = pyqtSignal(int, int)        # nuovo (start, end) della pagina salvata
    error    = pyqtSignal(str)

    def __init__(self, doc: PagedDocument, new_text: str, dest_path: Optional[Path] = None):
        super().__init__()
        self._doc = doc
        self._new_text = new_text
        # dest_path diverso da doc.path → "Salva con nome": si legge sempre
        # dal file originale ma si scrive altrove, lasciando l'originale
        # intatto.
        self.dest_path = dest_path or doc.path

    def _encode_page(self) -> bytes:
        enc = self._doc.encoding_raw()
        # La porzione [0, start) copiata byte-a-byte include già un eventuale
        # BOM originale: non va aggiunto di nuovo codificando il testo della
        # sola pagina modificata.
        if enc.lower().endswith("-sig"):
            enc = enc[:-4]
        try:
            return self._new_text.encode(enc)
        except (LookupError, UnicodeEncodeError):
            return self._new_text.encode("utf-8")

    def run(self) -> None:
        doc = self._doc
        tmp_path = self.dest_path.with_name(self.dest_path.name + ".notepadpq_tmp")
        try:
            # Il file non deve essere stato modificato dall'esterno da quando
            # è stato aperto: altrimenti gli offset di pagina non sono più
            # affidabili e continuare scriverebbe dati nel punto sbagliato.
            current_size = doc.path.stat().st_size
            if current_size != doc.file_size:
                self.error.emit(tr(
                    "lazy_loader.save_external_change",
                    default="Il file è stato modificato da un altro programma dopo "
                            "l'apertura: salvataggio annullato per evitare di "
                            "corromperlo."
                ))
                return

            start, end = doc.current_start, doc.current_end
            new_bytes = self._encode_page()
            total = max(1, doc.file_size)
            copied = 0

            with open(doc.path, "rb") as src, open(tmp_path, "wb") as dst:
                # 1) [0, start) invariato
                remaining = start
                while remaining > 0:
                    block = src.read(min(SAVE_COPY_CHUNK, remaining))
                    if not block:
                        break
                    dst.write(block)
                    remaining -= len(block)
                    copied += len(block)
                    self.progress.emit(min(99, int(copied / total * 100)))

                # 2) nuovo contenuto della pagina modificata
                dst.write(new_bytes)
                copied += len(new_bytes)
                self.progress.emit(min(99, int(copied / total * 100)))

                # 3) [end, file_size) invariato
                src.seek(end)
                while True:
                    block = src.read(SAVE_COPY_CHUNK)
                    if not block:
                        break
                    dst.write(block)
                    copied += len(block)
                    self.progress.emit(min(99, int(copied / total * 100)))

            os.replace(tmp_path, self.dest_path)
            self.progress.emit(100)
            self.finished.emit(start, start + len(new_bytes))

        except Exception as e:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            self.error.emit(str(e))


# ─── LazyLoader ───────────────────────────────────────────────────────────────

class LazyLoader(QObject):
    """
    Gestisce il caricamento di file grandi in un EditorWidget.

    Modalità:
    - NORMAL  (<50MB):     caricamento sincrono standard (delega a FileManager)
    - LAZY    (50MB–200MB): caricamento progressivo in background con progress bar
    - PAGED   (>200MB):    vista paginata su disco, modificabile una pagina alla
                           volta, naviga con i pulsanti Pag. prec./succ.

    Uso standard:
        LazyLoader.open_file(path, editor, main_window)
    """

    # Segnali
    load_started   = pyqtSignal(str)          # modalità: "normal"/"lazy"/"paged"
    progress       = pyqtSignal(int)          # 0–100
    load_finished  = pyqtSignal()
    load_error     = pyqtSignal(str)

    # Soglie (ridefinibili via config)
    THRESHOLD_LAZY  = THRESHOLD_LAZY
    THRESHOLD_PAGED = THRESHOLD_PAGED

    def __init__(self, path: Path, editor: "EditorWidget",
                 main_window: Optional["MainWindow"] = None):
        super().__init__()
        self._path        = path
        self._editor      = editor
        self._mw          = main_window
        self._thread      = None
        self._worker      = None
        self._progress_dlg: Optional[QProgressDialog] = None
        self._cancelled   = False
        self._paged_view: Optional[PagedDocument] = None
        self._pager_widget: Optional[QWidget] = None
        self._accumulated = []   # chunks accumulati prima dell'append

    # ── Entry point statico ───────────────────────────────────────────────────

    @staticmethod
    def open_file(path: Path, editor: "EditorWidget",
                  main_window=None) -> "LazyLoader":
        """
        Apre path nell'editor con la strategia appropriata.
        Restituisce il LazyLoader per permettere cancel() se necessario.
        """
        loader = LazyLoader(path, editor, main_window)
        loader.start()
        return loader

    # ── Start ─────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Avvia il caricamento con la strategia più adatta alla dimensione."""
        try:
            file_size = self._path.stat().st_size
        except OSError as e:
            self.load_error.emit(str(e))
            return

        if file_size >= self.THRESHOLD_PAGED:
            self._start_paged(file_size)
        elif file_size >= self.THRESHOLD_LAZY:
            self._start_lazy(file_size)
        else:
            self._start_normal()

    # ── Modalità NORMAL ───────────────────────────────────────────────────────

    def _start_normal(self) -> None:
        self.load_started.emit("normal")
        try:
            content, encoding, le = FileManager.read(self._path)
            self._editor.load_content(content, encoding, le)
            self.load_finished.emit()
        except Exception as e:
            self.load_error.emit(str(e))

    # ── Modalità LAZY ─────────────────────────────────────────────────────────

    def _start_lazy(self, file_size: int) -> None:
        self.load_started.emit("lazy")

        size_mb = file_size / MB
        self._show_progress(
            tr("lazy_loader.opening_file", size_mb=size_mb, default=f"Apertura file ({size_mb:.1f} MB)…"),
            tr("lazy_loader.large_file_loading", default="Il file è di grandi dimensioni. Caricamento in corso…")
        )

        # Thread di lettura
        self._worker = _LoadWorker(self._path)
        self._worker.chunk_ready.connect(self._on_chunk_ready)
        self._worker.finished.connect(self._on_lazy_finished)
        self._worker.error.connect(self._on_error)

        self._thread = threading.Thread(target=self._worker.run, daemon=True)
        self._thread.start()

    def _on_chunk_ready(self, text: str, chunk_idx: int, total_chunks: int) -> None:
        if self._cancelled:
            return

        # Primo chunk: load_content (inizializza encoding/lexer, normalizza a LF)
        if chunk_idx == 0:
            self._editor.beginUndoAction()
            le = LineEnding.detect(text)
            self._editor.load_content(text, "UTF-8", le)
            # load_content blocca i segnali solo per la durata del suo
            # setText() interno e li riattiva subito dopo. Per un caricamento
            # a chunk questo è il vero collo di bottiglia: ogni append() dei
            # chunk successivi altrimenti emette textChanged/modificationChanged
            # /linesChanged a piena potenza, e tutto ciò che vi è agganciato
            # (margine numeri riga, git gutter, minimap, spell-check, LSP...)
            # rilavora sull'intero documento che nel frattempo è cresciuto a
            # centinaia di MB — con centinaia di chunk diventa quadratico e un
            # file da 1-2GB può metterci minuti invece di secondi. Si
            # ri-blocca qui e si riattiva una volta sola a fine caricamento.
            self._editor.blockSignals(True)
        else:
            # Append al fondo del documento. load_content normalizza a LF solo
            # il primo chunk: i successivi vanno normalizzati qui, altrimenti
            # i file CRLF/CR finirebbero con line ending misti nel buffer.
            # Usa append() (SCI_APPENDTEXT) invece di insertAt(): calcolare
            # end_line/end_col con lines()/text(riga) ad ogni chunk e poi
            # inserire in quel punto forza Scintilla a rileggere/riposizionarsi
            # sul documento che cresce a centinaia di MB — costo aggiuntivo
            # che si somma a quello dei segnali descritto sopra.
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            self._editor.append(normalized)

        # Aggiorna progress bar
        pct = min(99, int((chunk_idx + 1) / max(1, total_chunks) * 100))
        self.progress.emit(pct)
        if self._progress_dlg:
            self._progress_dlg.setValue(pct)
            QApplication.processEvents()

    def _on_lazy_finished(self, encoding: str, le_label: str) -> None:
        self._editor.endUndoAction()
        # Riattiva i segnali bloccati durante i chunk (vedi _on_chunk_ready) e
        # rifà a mano gli aggiornamenti che sarebbero dovuti scattare da soli:
        # margine numeri riga (normalmente su linesChanged) e stato "non
        # modificato" (ogni append() durante il caricamento, pur silenzioso
        # sui segnali, segna comunque il documento come modificato a livello
        # Scintilla — sarebbe scorretto per un file appena aperto).
        self._editor.blockSignals(False)
        self._editor.setModified(False)
        self._editor._update_line_number_margin()

        # Aggiorna encoding/le definitivi
        self._editor.set_encoding(encoding)
        try:
            le = LineEnding[le_label]
            self._editor.set_line_ending(le)
        except (KeyError, AttributeError):
            pass
        # Torna all'inizio del file
        self._editor.setCursorPosition(0, 0)
        self._editor.ensureLineVisible(0)
        self._close_progress()
        self.progress.emit(100)
        self.load_finished.emit()

    # ── Modalità PAGED ────────────────────────────────────────────────────────

    def _start_paged(self, file_size: int) -> None:
        self.load_started.emit("paged")

        try:
            self._paged_view = PagedDocument(self._path)
        except Exception as e:
            self.load_error.emit(str(e))
            return

        size_gb = file_size / GB
        page_text = self._paged_view.read_page_at(self._paged_view.current_start)
        le = LineEnding.detect(page_text)
        self._editor.load_content(page_text, self._paged_view.encoding(), le)
        self._editor.SendScintilla(QsciScintilla.SCI_EMPTYUNDOBUFFER)

        # File enorme: resta modificabile, una pagina alla volta — vedi
        # PagedDocument e _attach_pager_ui. Altre funzionalità che assumono
        # editor.text()/get_content() sia l'intero documento (ordina righe,
        # sostituisci tutto, ecc.) vengono disabilitate altrove riconoscendo
        # questo attributo.
        self._editor._paged_doc = self._paged_view

        # Barra di stato con info paginazione
        self._attach_pager_ui()

        self._show_paged_notice(size_gb)
        self.load_finished.emit()

    def _attach_pager_ui(self) -> None:
        """
        Aggiunge una barra di navigazione pagine alla statusbar di MainWindow.
        La barra persiste finché il tab rimane aperto.

        Navigare mentre la pagina corrente ha modifiche non salvate chiede
        prima di salvarle (in streaming) o scartarle — si edita sempre una
        sola pagina alla volta, niente editing multi-pagina in coda.
        """
        if self._mw is None:
            return

        pv = self._paged_view
        editor = self._editor
        mw = self._mw

        from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QInputDialog
        pager = QWidget()
        layout = QHBoxLayout(pager)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(4)

        lbl = QLabel()

        def _update_label():
            pct = pv.progress_fraction * 100
            lbl.setText(
                tr("lazy_loader.page_indicator",
                   page=pv.current_page_number, total=pv.total_pages_estimate,
                   pct=pct, size=pv.file_size_mb,
                   default=f"📄 ~Pagina {pv.current_page_number}/{pv.total_pages_estimate}  "
                           f"(~{pct:.0f}% di {pv.file_size_mb:.0f} MB) "
                           f"— numerazione riga locale alla pagina")
            )

        btn_prev = QPushButton(tr("lazy_loader.btn_prev_page", default="◀ Pag. prec."))
        btn_next = QPushButton(tr("lazy_loader.btn_next_page", default="Pag. succ. ▶"))
        btn_jump = QPushButton(tr("lazy_loader.btn_jump_page", default="Vai a…"))
        btn_prev.setFixedHeight(20)
        btn_next.setFixedHeight(20)
        btn_jump.setFixedHeight(20)

        def _load_page_text(text: Optional[str]) -> None:
            if text is None:
                return
            le = LineEnding.detect(text)
            editor.load_content(text, pv.encoding(), le)
            # Scope dell'undo alla sola pagina appena caricata: setText() di
            # QScintilla non svuota da solo lo storico undo, senza questa
            # chiamata l'undo di una pagina si mescolerebbe con la precedente.
            editor.SendScintilla(QsciScintilla.SCI_EMPTYUNDOBUFFER)
            _update_label()

        def _navigate(get_target_text: Callable[[], Optional[str]]) -> None:
            if not editor.isModified():
                _load_page_text(get_target_text())
                return

            choice = QMessageBox.question(
                mw,
                tr("lazy_loader.unsaved_page_title", default="Modifiche non salvate"),
                tr("lazy_loader.unsaved_page_body",
                   default="La pagina corrente contiene modifiche non salvate. "
                           "Vuoi salvarle prima di continuare?"),
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel
            )
            if choice == QMessageBox.StandardButton.Cancel:
                return
            if choice == QMessageBox.StandardButton.Discard:
                _load_page_text(get_target_text())
                return
            # Salva, poi naviga solo se il salvataggio è andato a buon fine
            mw.save_paged_page(editor, on_success=lambda: _load_page_text(get_target_text()))

        def _go_prev():
            _navigate(pv.prev_page)

        def _go_next():
            _navigate(pv.next_page)

        def _go_jump():
            pct, ok = QInputDialog.getInt(
                mw,
                tr("lazy_loader.jump_title", default="Vai a…"),
                tr("lazy_loader.jump_body", default="Percentuale del file (0-100):"),
                int(pv.progress_fraction * 100), 0, 100
            )
            if ok:
                _navigate(lambda: pv.jump_to_fraction(pct / 100))

        btn_prev.clicked.connect(_go_prev)
        btn_next.clicked.connect(_go_next)
        btn_jump.clicked.connect(_go_jump)

        layout.addWidget(btn_prev)
        layout.addWidget(lbl)
        layout.addWidget(btn_next)
        layout.addWidget(btn_jump)

        _update_label()

        # Aggiunge alla statusbar come widget permanente
        try:
            mw.statusBar().addPermanentWidget(pager)
            self._pager_widget = pager   # tienilo vivo
            # Riferimento anche sull'editor: LazyLoader viene scartato subito
            # dopo il caricamento iniziale (main_window.py:open_files rimuove
            # self._lazy_loaders[tab] non appena load_finished viene emesso),
            # quindi alla chiusura del tab non è più raggiungibile per fare
            # pulizia — senza questo riferimento diretto la barra di
            # navigazione pagine resterebbe orfana nella statusbar.
            editor._pager_widget = pager
        except Exception:
            pass

    def _show_paged_notice(self, size_gb: float) -> None:
        if self._mw is None:
            return
        self._mw.statusBar().showMessage(
            tr("lazy_loader.paged_mode_notice", size_gb=size_gb,
               total_pages=self._paged_view.total_pages_estimate,
               default=f"⚠ File enorme ({size_gb:.2f} GB): editing una pagina "
                       f"alla volta (~4MB). Salva o scarta le modifiche prima "
                       f"di cambiare pagina."),
            8000
        )

    # ── Annullamento ──────────────────────────────────────────────────────────

    def cancel(self) -> None:
        """Annulla il caricamento (da chiamare quando il tab viene chiuso)."""
        self._cancelled = True
        if self._worker:
            self._worker.cancel()
        self._close_progress()
        self._remove_pager_ui()

    # ── Progress dialog ───────────────────────────────────────────────────────

    def _show_progress(self, title: str, text: str) -> None:
        if self._mw is None:
            return
        dlg = QProgressDialog(text, tr("button.cancel", default="Annulla"), 0, 100, self._mw)
        dlg.setWindowTitle(title)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(500)
        dlg.setValue(0)
        dlg.canceled.connect(self.cancel)
        dlg.show()
        self._progress_dlg = dlg

    def _close_progress(self) -> None:
        if self._progress_dlg:
            try:
                self._progress_dlg.close()
            except Exception:
                pass
            self._progress_dlg = None

    def _on_error(self, msg: str) -> None:
        self._close_progress()
        self.load_error.emit(msg)

    def _remove_pager_ui(self) -> None:
        if self._pager_widget is not None and self._mw is not None:
            try:
                self._mw.statusBar().removeWidget(self._pager_widget)
                self._pager_widget.deleteLater()
            except Exception:
                pass
            self._pager_widget = None

    # ── Informazioni stato ────────────────────────────────────────────────────

    def is_paged(self) -> bool:
        return self._paged_view is not None

    def paged_view(self) -> Optional[PagedDocument]:
        return self._paged_view

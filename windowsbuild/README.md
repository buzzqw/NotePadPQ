# NotePadPQ — Windows Build System

Questa cartella contiene tutti gli strumenti per compilare NotePadPQ come eseguibile Windows (`.exe`) usando **PyInstaller**.

---

## File presenti

| File | Descrizione |
|------|-------------|
| `build.bat` | Script principale Windows — compila Full, Lite o entrambe |
| `build.sh` | Equivalente bash per Linux/macOS/CI |
| `install_deps.bat` | Installa le dipendenze Python necessarie per la build |
| `notepadpq_full.spec` | Spec PyInstaller — versione **Full** (tutte le dipendenze opzionali) |
| `notepadpq_lite.spec` | Spec PyInstaller — versione **Lite** (solo core obbligatori) |
| `version_info.txt` | Metadati PE Windows (versione, copyright, nome) per il .exe |
| `create_installer.iss` | Script Inno Setup 6 per creare un installer `.exe` professionale |

---

## Uso rapido (Windows)

```bat
REM 1. Prima volta: installa le dipendenze
install_deps.bat

REM 2. Compila entrambe le versioni (Full + Lite)
build.bat

REM 3. Compila solo una versione
build.bat full
build.bat lite

REM 4. Compila + crea installer (richiede Inno Setup installato)
build.bat installer
```

Gli archivi ZIP vengono creati automaticamente in `dist\`.

---

## Uso rapido (Linux/macOS/CI)

```bash
# Rendi eseguibile (solo la prima volta)
chmod +x windowsbuild/build.sh

# Compila entrambe le versioni
bash windowsbuild/build.sh

# Solo Full o solo Lite
bash windowsbuild/build.sh full
bash windowsbuild/build.sh lite
```

> ⚠️ **Nota:** PyInstaller produce `.exe` **solo su Windows**.  
> Su Linux/macOS questo script è pensato per ambienti CI (GitHub Actions) o Wine.  
> Per una build locale usa `build.bat` su una macchina Windows.

---

## Due versioni: Full vs Lite

| | **Full** | **Lite** |
|---|---|---|
| Editor core (PyQt6, QScintilla, WebEngine) | ✅ | ✅ |
| Anteprima PDF (`pymupdf`) | ✅ | ❌ |
| Anteprima Markdown / RST | ✅ | ❌ |
| Formule matematiche (`matplotlib`, `sympy`) | ✅ | ❌ |
| Rich Text / DOCX (`mammoth`, `htmldocx`) | ✅ | ❌ |
| Spreadsheet (`openpyxl`, `xlrd`, `odfpy`) | ✅ | ❌ |
| Plugin Git (`PyGithub`, `python-gitlab`) | ✅ | ❌ |
| Spell checker | ✅ | ❌ |
| Dimensione approssimativa | ~300–400 MB | ~120–180 MB |

---

## Creare un installer con Inno Setup

1. Scarica e installa [Inno Setup 6](https://jrsoftware.org/isdl.php)
2. Compila prima con `build.bat full` (o `lite`)
3. Lancia:
   ```bat
   build.bat installer
   ```
   oppure manualmente:
   ```bat
   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion="0.9.10" /DEdition="Full" create_installer.iss
   ```

L'installer risultante sarà in `dist\NotePadPQ_v0.9.10_Full_Setup.exe`.

---

## GitHub Actions (build automatica)

Il workflow `.github/workflows/build-windows.yml` si attiva:

- **Automaticamente** su ogni push di un tag `v*.*.*` (es. `v0.9.11`)
- **Manualmente** dalla tab *Actions* → *Build Windows* → *Run workflow*

Al termine crea automaticamente una **GitHub Release** con i due ZIP allegati.

---

## Integrazione con `versiona.sh`

Quando esegui `bash versiona.sh` dal progetto, lo script:

1. Aggiorna automaticamente `windowsbuild/version_info.txt` con la nuova versione
2. Include il file nel commit di release
3. Al termine chiede se avviare la build Windows locale

---

## Aggiornare la versione manualmente in `version_info.txt`

Il file viene aggiornato automaticamente da `versiona.sh` e dai batch/script di build.  
Se vuoi aggiornarlo a mano, modifica le righe:

```python
filevers=(0, 9, 10, 0),
prodvers=(0, 9, 10, 0),
StringStruct(u'FileVersion',      u'0.9.10.0'),
StringStruct(u'ProductVersion',   u'0.9.10'),
```

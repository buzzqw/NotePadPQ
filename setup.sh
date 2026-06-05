#!/bin/bash
# setup.sh — NotePadPQ setup

set -euo pipefail

PYTHON=${PYTHON:-python3}
OS=$(uname)
PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# Pacchetti base (sempre richiesti)
PIP_CORE="PyQt6 PyQt6-QScintilla PyQt6-WebEngine chardet markdown docutils pyspellchecker PyGithub python-gitlab keyring"

# Pacchetti opzionali per il supporto LaTeX avanzato
PIP_LATEX="pymupdf matplotlib sympy"

# Pacchetti per il plugin Foglio di Calcolo
PIP_SPREADSHEET="openpyxl xlrd odfpy"

# Pacchetti per il plugin Rich Text (WYSIWYG docx/odt/rtf)
PIP_RICHTEXT="mammoth htmldocx"

# ─── Helper ───────────────────────────────────────────────────────────────────

_print_latex_hint() {
    echo
    echo "┌─────────────────────────────────────────────────────────────────┐"
    echo "│  Supporto LaTeX avanzato (opzionale)                            │"
    echo "│                                                                 │"
    echo "│  Se usi NotePadPQ per compilare e scrivere LaTeX, installa:     │"
    echo "│                                                                 │"
    echo "│  • pymupdf     — anteprima PDF al passaggio del mouse           │"
    echo "│  • matplotlib  — rendering equazioni matematiche inline         │"
    echo "│  • sympy       — supporto calcolo simbolico                     │"
    echo "│  • synctex     — navigazione bidirezionale sorgente ↔ PDF       │"
    echo "│                  (pacchetto di sistema, incluso in TeX Live)    │"
    echo "│                                                                 │"
    echo "│  Installazione rapida (pip):                                    │"
    echo "│    pip install pymupdf matplotlib sympy                         │"
    echo "│                                                                 │"
    echo "│  Su Arch Linux:                                                 │"
    echo "│    sudo pacman -S python-pymupdf python-matplotlib python-sympy │"
    echo "│    sudo pacman -S texlive-bin   (include synctex)               │"
    echo "└─────────────────────────────────────────────────────────────────┘"
}

_check_synctex() {
    if command -v synctex &>/dev/null; then
        echo "  synctex        : OK  (navigazione bidirezionale LaTeX↔PDF)"
    else
        echo "  synctex        : non installato  (opzionale, incluso in TeX Live)"
    fi
}

_create_linux_launcher() {
    echo
    echo "=== Creazione lanciatore Linux ==="

    PYTHON_BIN=$(command -v "$PYTHON")

    ICON_PATH=""
    for _try_icon in \
        "${PROJECT_DIR}/icons/NotePadPQ_256.png" \
        "${PROJECT_DIR}/icons/NotePadPQ.png" \
        "${PROJECT_DIR}/icons/notepadpq.png"; do
        if [[ -f "$_try_icon" ]]; then
            ICON_PATH="$_try_icon"
            break
        fi
    done
    if [[ -z "$ICON_PATH" ]]; then
        echo "  Icona non trovata in icons/, uso icona generica."
        ICON_PATH="text-editor"
    else
        echo "  Icona trovata:    OK"
    fi

    mkdir -p "${HOME}/.local/share/applications"
    LAUNCHER_FILE="${HOME}/.local/share/applications/notepadpq.desktop"

    cat <<EOF > "$LAUNCHER_FILE"
[Desktop Entry]
Type=Application
Name=NotePadPQ
Comment=Advanced text editor based on PyQt6 and QScintilla
Exec=$PYTHON_BIN $PROJECT_DIR/main.py %F
Icon=$ICON_PATH
Terminal=false
Categories=Development;TextEditor;Utility;
MimeType=text/plain;text/x-python;text/x-c++src;text/x-latex;application/x-shellscript;application/json;application/xml;text/markdown;text/x-rst;
EOF

    chmod +x "$LAUNCHER_FILE"
    echo "  Lanciatore creato in: $LAUNCHER_FILE"
}

# ─── Installazione ────────────────────────────────────────────────────────────

echo "=== NotePadPQ Setup ==="
echo "Installazione dipendenze base: editor, spellcheck, plugin Git."
echo

if [[ "$OS" == MINGW* ]] || [[ "$OS" == CYGWIN* ]] || [[ "$OS" == MSYS* ]]; then
    $PYTHON -m pip install $PIP_CORE $PIP_SPREADSHEET $PIP_RICHTEXT

elif command -v pacman &>/dev/null; then
    echo "Arch Linux: installo dipendenze native via pacman..."
    sudo pacman -S --needed --noconfirm \
        python-pyqt6 python-pyqt6-webengine python-qscintilla-qt6 \
        python-chardet python-markdown python-docutils \
        python-pygithub python-gitlab \
        python-pyspellchecker python-keyring \
        python-openpyxl python-xlrd python-odfpy 2>/dev/null || true
    $PYTHON -m pip install $PIP_RICHTEXT 2>/dev/null || true

elif command -v apt-get &>/dev/null; then
    BREAK="--break-system-packages"
    sudo apt-get update
    sudo apt-get install -y \
        python3-pyqt6 python3-pyqt6.qsci python3-chardet \
        python3-markdown python3-pyqt6.qtwebengine \
        python3-openpyxl python3-xlrd python3-odf 2>/dev/null || true
    $PYTHON -m pip install $BREAK $PIP_CORE $PIP_SPREADSHEET $PIP_RICHTEXT 2>/dev/null || true

elif command -v dnf &>/dev/null; then
    sudo dnf install -y \
        python3-qt6 python3-qscintilla-qt6 python3-qt6-webengine \
        python3-chardet python3-markdown \
        python3-openpyxl 2>/dev/null || true
    $PYTHON -m pip install --user $PIP_CORE $PIP_SPREADSHEET $PIP_RICHTEXT || true

elif [[ "$OS" == "FreeBSD" ]]; then
    echo "FreeBSD: rilevazione versione Python..."
    PY_VER=$($PYTHON -c "import sys; print(f'{sys.version_info.major}{sys.version_info.minor}')")
    echo "  Versione Python: $PY_VER"
    # Pacchetti disponibili nei ports FreeBSD
    sudo pkg install -y \
        "py${PY_VER}-pip" \
        "py${PY_VER}-qt6-qscintilla2" \
        "py${PY_VER}-chardet" \
        "py${PY_VER}-markdown" \
        "py${PY_VER}-docutils" \
        "py${PY_VER}-keyring" \
        "py${PY_VER}-python-gitlab" \
        "py${PY_VER}-openpyxl" \
        "py${PY_VER}-xlrd" \
        "py${PY_VER}-odfpy"
    # PyQt6, PyQt6-WebEngine, pyspellchecker, PyGithub non sono nei ports -> pip
    PIPBIN=$(command -v pip3 || command -v pip || true)
    if [[ -n "$PIPBIN" ]]; then
        $PIPBIN install --user PyQt6 PyQt6-WebEngine PyQt6-QScintilla pyspellchecker PyGithub $PIP_RICHTEXT || true
    else
        echo "  ERRORE: pip non trovato dopo installazione py${PY_VER}-pip"
        echo "  Riprova: sudo pkg install py${PY_VER}-pip"
    fi

else
    $PYTHON -m pip install $PIP_CORE $PIP_SPREADSHEET $PIP_RICHTEXT || true
fi

# ─── Verifica finale ──────────────────────────────────────────────────────────

echo
echo "=== Verifica dipendenze ==="
echo "--- Base (richieste) ---"
$PYTHON -c "
def check(name, cmd):
    try:
        exec(cmd)
        print(f'  {name:15}: OK')
    except:
        print(f'  {name:15}: NON TROVATO')

check('PyQt6',       'from PyQt6.QtWidgets import QApplication')
check('QScintilla',  'from PyQt6.Qsci import QsciScintilla')
check('WebEngine',   'from PyQt6.QtWebEngineWidgets import QWebEngineView')
check('Chardet',     'import chardet')
check('Markdown',    'import markdown')
check('Docutils',    'from docutils.core import publish_parts')
check('Spellchecker','import spellchecker')
check('PyGithub',    'import github')
check('GitLab',      'import gitlab')
check('Keyring',     'import keyring')
"
echo
echo "--- Foglio di calcolo (opzionali) ---"
$PYTHON -c "
def check_opt(name, cmd, desc):
    try:
        exec(cmd)
        print(f'  {name:15}: OK')
    except:
        print(f'  {name:15}: non installato  ({desc})')

check_opt('openpyxl',   'import openpyxl',  'XLSX / ODS lettura e scrittura')
check_opt('xlrd',       'import xlrd',      'XLS legacy (sola lettura)')
check_opt('odfpy',      'import odf',       'ODS (fallback se openpyxl < 3.1)')
"

echo
echo "--- Plugin Rich Text (opzionali) ---"
$PYTHON -c "
def check_opt(name, cmd, desc):
    try:
        exec(cmd)
        print(f'  {name:15}: OK')
    except:
        print(f'  {name:15}: non installato  ({desc})')

check_opt('mammoth',    'import mammoth',   'lettura DOCX → HTML')
check_opt('htmldocx',   'import htmldocx',  'scrittura HTML → DOCX')
check_opt('pypandoc',   'import pypandoc',  'conversione ODT/RTF/DOCX/TEX')
"
if command -v pandoc &>/dev/null; then
    echo "  pandoc         : OK  (export DOCX/ODT/LaTeX e apertura ODT/RTF)"
else
    echo "  pandoc         : non installato  (opzionale — necessario per export DOCX/ODT/LaTeX e rich text ODT/RTF)"
fi

echo
echo "--- LaTeX avanzato (opzionali) ---"
$PYTHON -c "
def check_opt(name, cmd, desc):
    try:
        exec(cmd)
        print(f'  {name:15}: OK')
    except:
        print(f'  {name:15}: non installato  ({desc})')

check_opt('PyMuPDF',    'import fitz',       'anteprima PDF in hover')
check_opt('Matplotlib', 'import matplotlib', 'rendering equazioni')
check_opt('Sympy',      'import sympy',      'calcolo simbolico')
"
_check_synctex

echo
echo "--- Plugin FTP/SFTP/SMB ---"
if python3 -c "import paramiko" &>/dev/null 2>&1; then
    echo "  paramiko: OK  (SFTP)"
else
    echo "  paramiko: non installato  →  pip install paramiko  (per SFTP)"
fi
case "$(uname -s)" in
  Linux*)
    if command -v mount.cifs &>/dev/null; then
        echo "  cifs-utils: OK  (mount SMB)"
    else
        echo "  cifs-utils: non installato  →  sudo apt install cifs-utils  (per SMB)"
    fi ;;
  Darwin*)  echo "  macOS: mount_smbfs incluso nel sistema (SMB OK)" ;;
  MINGW*|CYGWIN*|MSYS*) echo "  Windows: net use incluso nel sistema (SMB OK)" ;;
esac
echo

echo "--- Code Formatter (opzionali) ---"
for tool in black ruff prettier clang-format rustfmt gofmt; do
    if command -v "$tool" &>/dev/null; then
        echo "  $tool: OK"
    else
        echo "  $tool: non installato  (opzionale)"
    fi
done
echo "  Installa i formatter mancanti:"
echo "    pip install black ruff              # Python"
echo "    npm i -g prettier                  # JS/TS/HTML/CSS"
echo "    apt install clang-format           # C/C++ (oppure brew/choco)"
echo "    rustup component add rustfmt       # Rust"
echo "    (gofmt è incluso nel toolchain Go)"

echo
echo "--- LSP (server di linguaggio, opzionali) ---"
for tool in pylsp clangd rust-analyzer gopls texlab typescript-language-server; do
    if command -v "$tool" &>/dev/null; then
        echo "  $tool: OK"
    else
        echo "  $tool: non installato"
    fi
done
echo "  Installa i server mancanti:"
echo "    pip install python-lsp-server        # Python"
echo "    apt install clangd                   # C/C++"
echo "    go install golang.org/x/tools/gopls@latest  # Go"
echo "    npm i -g typescript-language-server  # TypeScript/JavaScript"

echo
echo "--- Plugin AI Assistant ---"
$PYTHON -c "import urllib.request; print('  urllib (stdlib): OK')"
echo "  Configura le API key dal pannello AI (Ctrl+Alt+A → ⚙)"
echo "  Anthropic: https://console.anthropic.com/settings/keys"
echo "  OpenAI:    https://platform.openai.com/api-keys"
echo "  Gemini:    https://aistudio.google.com/app/apikey"
echo "  Ollama:    http://localhost:11434 (nessuna chiave necessaria)"

_print_latex_hint

echo
echo "┌─────────────────────────────────────────────────────────────────┐"
echo "│  Plugin Rich Text / Editor WYSIWYG (opzionale)                  │"
echo "│                                                                 │"
echo "│  Per aprire DOCX, ODT, RTF come rich text editabile:            │"
echo "│                                                                 │"
echo "│  • mammoth   — lettura DOCX (conversione a HTML)                │"
echo "│  • htmldocx  — scrittura DOCX (esportazione da HTML)            │"
echo "│  • pypandoc  — ODT/RTF/DOCX/LaTeX (richiede pandoc di sistema)  │"
echo "│                                                                 │"
echo "│  Installazione rapida (pip):                                    │"
echo "│    pip install mammoth htmldocx                                 │"
echo "└─────────────────────────────────────────────────────────────────┘"
echo

echo "┌─────────────────────────────────────────────────────────────────┐"
echo "│  Plugin Code Formatter (opzionale)                              │"
echo "│                                                                 │"
echo "│  Per formattare il codice con Ctrl+Alt+F:                       │"
echo "│                                                                 │"
echo "│  • black / ruff  — Python  (pip install black ruff)             │"
echo "│  • prettier      — JS/TS/HTML/CSS  (npm i -g prettier)          │"
echo "│  • clang-format  — C/C++  (apt install clang-format)            │"
echo "│  • rustfmt       — Rust  (rustup component add rustfmt)         │"
echo "│  • gofmt         — Go  (incluso nel toolchain Go)               │"
echo "│  • json.tool / minidom — JSON/XML  (stdlib Python, già incluso) │"
echo "│                                                                 │"
echo "│  Installazione rapida:                                          │"
echo "│    pip install black ruff                                       │"
echo "│    npm i -g prettier                                            │"
echo "└─────────────────────────────────────────────────────────────────┘"
echo
echo "┌─────────────────────────────────────────────────────────────────┐"
echo "│  Plugin Foglio di Calcolo (opzionale)                           │"
echo "│                                                                 │"
echo "│  Per aprire CSV, XLSX, XLS, ODS come foglio di calcolo:        │"
echo "│                                                                 │"
echo "│  • openpyxl  — XLSX, XLSM, ODS (lettura e scrittura)           │"
echo "│  • xlrd      — XLS legacy (sola lettura)                        │"
echo "│  • odfpy     — ODS (fallback per scrittura)                     │"
echo "│                                                                 │"
echo "│  Installazione rapida (pip):                                    │"
echo "│    pip install openpyxl xlrd odfpy                              │"
echo "└─────────────────────────────────────────────────────────────────┘"

if [[ "$OS" == "Linux" ]]; then
    _create_linux_launcher
fi



echo
echo "=== Setup completato ==="
echo "Avvia l'applicazione con: $PYTHON main.py"
echo "Oppure cercala nel menu applicazioni (Linux)."

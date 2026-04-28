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
    $PYTHON -m pip install $PIP_CORE

elif command -v pacman &>/dev/null; then
    echo "Arch Linux: installo dipendenze native via pacman..."
    sudo pacman -S --needed --noconfirm \
        python-pyqt6 python-pyqt6-webengine python-qscintilla-qt6 \
        python-chardet python-markdown python-docutils \
        python-pygithub python-gitlab \
        python-pyspellchecker python-keyring 2>/dev/null || true

elif command -v apt-get &>/dev/null; then
    BREAK="--break-system-packages"
    sudo apt-get update
    sudo apt-get install -y \
        python3-pyqt6 python3-pyqt6.qsci python3-chardet \
        python3-markdown python3-pyqt6.qtwebengine 2>/dev/null || true
    $PYTHON -m pip install $BREAK $PIP_CORE 2>/dev/null || true

elif command -v dnf &>/dev/null; then
    sudo dnf install -y \
        python3-qt6 python3-qscintilla-qt6 python3-qt6-webengine \
        python3-chardet python3-markdown 2>/dev/null || true
    $PYTHON -m pip install --user $PIP_CORE || true

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
        "py${PY_VER}-python-gitlab"
    # PyQt6, PyQt6-WebEngine, pyspellchecker, PyGithub non sono nei ports -> pip
    PIPBIN=$(command -v pip3 || command -v pip || true)
    if [[ -n "$PIPBIN" ]]; then
        $PIPBIN install --user PyQt6 PyQt6-WebEngine PyQt6-QScintilla pyspellchecker PyGithub || true
    else
        echo "  ERRORE: pip non trovato dopo installazione py${PY_VER}-pip"
        echo "  Riprova: sudo pkg install py${PY_VER}-pip"
    fi

else
    $PYTHON -m pip install $PIP_CORE || true
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

_print_latex_hint

if [[ "$OS" == "Linux" ]]; then
    _create_linux_launcher
fi



echo
echo "=== Setup completato ==="
echo "Avvia l'applicazione con: $PYTHON main.py"
echo "Oppure cercala nel menu applicazioni (Linux)."

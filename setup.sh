#!/bin/bash
# setup.sh — Versione 0.2.1 completa (Arch Linux 100% nativo)

set -euo pipefail

PYTHON=${PYTHON:-python3}
OS=$(uname)
PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# Lista completa pacchetti PIP (per gli altri OS)
PIP_PACKAGES="PyQt6 PyQt6-QScintilla PyQt6-WebEngine chardet markdown pymupdf docutils pyspellchecker matplotlib sympy PyGithub python-gitlab keyring"

# Funzione: controlla se synctex è disponibile
_check_synctex() {
    if command -v synctex &>/dev/null; then
        echo "  synctex        : OK  (navigazione bidirezionale LaTeX<->PDF)"
    else
        echo "  synctex        : NON TROVATO"
        echo "    -> (Usa il gestore pacchetti della tua distro per installare TeX Live / SyncTeX)"
    fi
}

# Funzione: crea file di avvio (.desktop) per Linux
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

echo "=== NotePadPQ Mega Setup ==="
echo "Installazione di tutte le funzioni: Editor, PDF, Math Preview, Spellcheck e Git Plugins."
echo

if [[ "$OS" == MINGW* ]] || [[ "$OS" == CYGWIN* ]] || [[ "$OS" == MSYS* ]]; then
    $PYTHON -m pip install $PIP_PACKAGES

elif command -v pacman &>/dev/null; then
    echo "Arch Linux: installo TUTTE le dipendenze native via pacman..."
    sudo pacman -S --needed --noconfirm \
        python-pyqt6 python-pyqt6-webengine python-qscintilla-qt6 \
        python-chardet python-markdown python-pymupdf python-docutils \
        python-pygithub python-gitlab python-matplotlib python-sympy \
        python-pyspellchecker python-keyring 2>/dev/null || true

elif command -v apt-get &>/dev/null; then
    BREAK="--break-system-packages"
    sudo apt-get update
    sudo apt-get install -y \
        python3-pyqt6 python3-pyqt6.qsci python3-chardet python3-markdown python3-pyqt6.qtwebengine 2>/dev/null || true
    $PYTHON -m pip install $BREAK $PIP_PACKAGES 2>/dev/null || true

elif command -v dnf &>/dev/null; then
    sudo dnf install -y \
        python3-qt6 python3-qscintilla-qt6 python3-qt6-webengine \
        python3-chardet python3-markdown python3-pymupdf 2>/dev/null || true
    $PYTHON -m pip install --user docutils pyspellchecker matplotlib sympy PyGithub python-gitlab keyring || true

else
    $PYTHON -m pip install $PIP_PACKAGES || true
fi

echo
echo "=== Verifica Finale ==="
$PYTHON -c "
def check(name, cmd):
    try:
        exec(cmd)
        print(f'  {name:15}: OK')
    except:
        print(f'  {name:15}: NON TROVATO')

check('PyQt6', 'from PyQt6.QtWidgets import QApplication')
check('QScintilla', 'from PyQt6.Qsci import QsciScintilla')
check('WebEngine', 'from PyQt6.QtWebEngineWidgets import QWebEngineView')
check('Chardet', 'import chardet')
check('Markdown', 'import markdown')
check('Docutils', 'from docutils.core import publish_parts')
check('PyMuPDF', 'import fitz')
check('Spellchecker', 'import spellchecker')
check('Matplotlib', 'import matplotlib')
check('Sympy', 'import sympy')
check('PyGithub', 'import github')
check('GitLab', 'import gitlab')
check('Keyring', 'import keyring')
"

_check_synctex

# Crea il lanciatore solo se siamo nativamente su Linux
if [[ "$OS" == "Linux" ]]; then
    _create_linux_launcher
fi

echo
echo "=== Setup completato ==="
echo "Ora puoi avviare l'applicazione. Se sei su Linux la trovi nel menu, altrimenti lancia: $PYTHON main.py"
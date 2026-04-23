#!/bin/bash
# setup.sh — Installazione dipendenze NotePadPQ e creazione lanciatore
# Supporto: Arch, Debian/Ubuntu, Fedora, openSUSE, FreeBSD, Windows (MSYS/MinGW)

set -euo pipefail

PYTHON=${PYTHON:-python3}
OS=$(uname)
PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
LAUNCHER_DIR="${HOME}/.local/share/applications"
LAUNCHER_FILE="${LAUNCHER_DIR}/notepadpq.desktop"

# Funzione: controlla se synctex è disponibile
_check_synctex() {
    if command -v synctex &>/dev/null; then
        echo "  synctex:          OK  (navigazione bidirezionale LaTeX<->PDF)"
    else
        echo "  synctex:          NON TROVATO"
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

    mkdir -p "$LAUNCHER_DIR"

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

echo "=== NotePadPQ Setup ==="
echo "Python: $($PYTHON --version)"
echo "Sistema: $OS"
echo "Directory progetto: $PROJECT_DIR"
echo

# Verifica Python >= 3.10
$PYTHON -c "
import sys
if sys.version_info < (3, 10):
    print('ERRORE: richiesto Python >= 3.10')
    sys.exit(1)
print(f'Python {sys.version_info.major}.{sys.version_info.minor} OK')
"

echo
echo "=== Installazione dipendenze di sistema ==="

# ─── Selezione Gestore Pacchetti in base all'OS ───────────────────────────────

if [[ "$OS" == MINGW* ]] || [[ "$OS" == CYGWIN* ]] || [[ "$OS" == MSYS* ]]; then
    echo "Windows rilevato: procedo esclusivamente via pip..."
    $PYTHON -m pip install PyQt6 PyQt6-QScintilla PyQt6-WebEngine chardet markdown pymupdf docutils

elif command -v pacman &>/dev/null; then
    echo "Arch Linux: installo da pacman..."
    sudo pacman -S --needed --noconfirm \
        python-pyqt6 python-pyqt6-webengine python-qscintilla-qt6 \
        python-chardet python-markdown python-pymupdf texlive-binextra 2>/dev/null || true

elif command -v apt-get &>/dev/null; then
    echo "Debian/Ubuntu: installazione da apt..."
    BREAK="--break-system-packages"
    sudo apt-get install -y \
        python3-pyqt6 python3-pyqt6.qsci python3-chardet python3-markdown texlive-extra-utils 2>/dev/null || true
    # Pip per i pacchetti spesso mancanti in apt
    $PYTHON -m pip install $BREAK PyQt6-WebEngine pymupdf docutils 2>/dev/null || true
    # Fallback se QScintilla manca
    $PYTHON -c "from PyQt6.Qsci import QsciScintilla" 2>/dev/null || $PYTHON -m pip install $BREAK PyQt6-QScintilla || true

elif command -v dnf &>/dev/null; then
    echo "Fedora/RHEL: installazione da dnf..."
    sudo dnf install -y \
        python3-qt6 python3-qscintilla-qt6 python3-qt6-webengine \
        python3-chardet python3-markdown python3-pymupdf texlive-synctex 2>/dev/null || true
    $PYTHON -m pip install --user docutils || true

elif command -v zypper &>/dev/null; then
    echo "openSUSE: installazione da zypper..."
    sudo zypper install -y -n \
        python3-qt6 python3-qscintilla-qt6 python3-qt6-webengine \
        python3-chardet python3-Markdown python3-PyMuPDF texlive-synctex 2>/dev/null || true
    $PYTHON -m pip install --user docutils || true

elif [[ "$OS" == "FreeBSD" ]]; then
    echo "FreeBSD: assicurati di aver eseguito 'pkg install python311 py311-pip' come root."
    $PYTHON -m pip install PyQt6 PyQt6-QScintilla PyQt6-WebEngine chardet markdown pymupdf docutils || true

else
    echo "Sistema generico o non riconosciuto: tento l'installazione completa via pip..."
    $PYTHON -m pip install PyQt6 PyQt6-QScintilla PyQt6-WebEngine chardet markdown pymupdf docutils || true
fi

echo
echo "=== Verifica dipendenze ==="
$PYTHON -c "
from PyQt6.QtWidgets import QApplication;          print('  PyQt6:            OK')
try:    from PyQt6.Qsci import QsciScintilla;      print('  QScintilla:       OK')
except: print('  QScintilla:       NON TROVATO (Critico)')
import chardet;                                    print('  chardet:          OK')
try:    import markdown;                           print('  markdown:         OK')
except: print('  markdown:         NON TROVATO (opzionale)')
try:    from PyQt6.QtWebEngineWidgets import QWebEngineView; print('  WebEngine:        OK')
except: print('  WebEngine:        NON TROVATO (opzionale, anteprima HTML/MD)')
try:    import fitz;                               print('  PyMuPDF:          OK')
except: print('  PyMuPDF:          NON TROVATO (opzionale, anteprima PDF)')
try:    from github import Github;                     print('  PyGithub:         OK')
except: print('  PyGithub:         NON TROVATO (opzionale, plugin Git PR)')
try:    import gitlab;                                 print('  python-gitlab:    OK')
except: print('  python-gitlab:    NON TROVATO (opzionale, plugin Git MR)')
try:    import keyring;                                print('  keyring:          OK')
except: print('  keyring:          NON TROVATO (opzionale, storage token sicuro)')
try:    from docutils.core import publish_parts;   print('  docutils:         OK')
except: print('  docutils:         NON TROVATO (opzionale, anteprima RST)')
"

_check_synctex

# Crea il lanciatore solo se siamo nativamente su Linux
if [[ "$OS" == "Linux" ]]; then
    _create_linux_launcher
fi

echo
echo "== = Setup completato ==="
echo "Ora puoi avviare l'applicazione. Se sei su Linux la trovi nel menu, altrimenti lancia: $PYTHON main.py"
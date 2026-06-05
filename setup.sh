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

# Pacchetti per i Code Formatter Python (black e ruff; prettier/clang-format si installano a parte)
PIP_FORMATTERS="black ruff"

# ─── Helper ───────────────────────────────────────────────────────────────────

# Controlla se tutti i moduli Python di una lista sono importabili.
# Usa prima il Python di sistema, poi quello del .venv se presente.
# Ritorna: "all" se tutti presenti, "partial" se alcuni, "none" se nessuno.
_check_pkg_status() {
    local pkgs="$1"
    local python_bins="$PYTHON"
    local VENV_DIR="${PROJECT_DIR}/.venv"
    [[ -x "${VENV_DIR}/bin/python" ]] && python_bins="$PYTHON ${VENV_DIR}/bin/python"

    local total=0
    local found=0
    for pkg in $pkgs; do
        total=$((total + 1))
        local import_name
        case "$pkg" in
            pymupdf)   import_name="fitz" ;;
            odfpy)     import_name="odf" ;;
            PyGithub)  import_name="github" ;;
            Pillow)    import_name="PIL" ;;
            *)         import_name="${pkg//-/_}" ;;
        esac
        import_name="${import_name,,}"   # lowercase
        # prova su tutti i Python disponibili
        local ok=false
        for pybin in $python_bins; do
            if $pybin -c "import ${import_name}" &>/dev/null 2>&1; then
                ok=true
                break
            fi
        done
        $ok && found=$((found + 1))
    done

    if   [[ $found -eq $total ]];   then echo "all"
    elif [[ $found -gt 0 ]];        then echo "partial"
    else                                 echo "none"
    fi
}

# Rileva lo stato di installazione di tutti i componenti opzionali;
# setta le variabili STATUS_LATEX, STATUS_SPREADSHEET, STATUS_RICHTEXT, STATUS_FORMATTERS.
_detect_installed_components() {
    STATUS_LATEX=$(_check_pkg_status "$PIP_LATEX")
    STATUS_SPREADSHEET=$(_check_pkg_status "$PIP_SPREADSHEET")
    STATUS_RICHTEXT=$(_check_pkg_status "$PIP_RICHTEXT")
    # Per i formatter controlliamo solo black e ruff (gli altri sono di sistema)
    STATUS_FORMATTERS=$(_check_pkg_status "$PIP_FORMATTERS")
}

# Restituisce l'etichetta visiva per uno stato componente.
_status_label() {
    case "$1" in
        all)     echo "✓ già installato" ;;
        partial) echo "~ parzialmente installato" ;;
        *)       echo "✗ non installato" ;;
    esac
}

# Chiede all'utente quali componenti opzionali installare;
# setta INSTALL_LATEX, INSTALL_SPREADSHEET, INSTALL_RICHTEXT, INSTALL_FORMATTERS (true/false)
_ask_optional_components() {
    _detect_installed_components
    local lbl1; lbl1=$(_status_label "$STATUS_LATEX")
    local lbl2; lbl2=$(_status_label "$STATUS_SPREADSHEET")
    local lbl3; lbl3=$(_status_label "$STATUS_RICHTEXT")
    local lbl4; lbl4=$(_status_label "$STATUS_FORMATTERS")

    echo
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║  Componenti opzionali di NotePadPQ                              ║"
    echo "║  (✓ già installato  ~ parziale  ✗ mancante)                     ║"
    echo "╠══════════════════════════════════════════════════════════════════╣"
    printf "║  [1] LaTeX avanzato  — pymupdf, matplotlib, sympy               ║\n"
    printf "║      Anteprima PDF, rendering equazioni, calcolo simbolico      ║\n"
    printf "║      Stato: %-52s║\n" "$lbl1"
    echo   "║                                                                 ║"
    printf "║  [2] Foglio di calcolo — openpyxl, xlrd, odfpy                  ║\n"
    printf "║      Apertura/salvataggio XLSX, XLS, ODS                        ║\n"
    printf "║      Stato: %-52s║\n" "$lbl2"
    echo   "║                                                                 ║"
    printf "║  [3] Rich Text (WYSIWYG) — mammoth, htmldocx                    ║\n"
    printf "║      Apertura/esportazione DOCX come rich text                  ║\n"
    printf "║      Stato: %-52s║\n" "$lbl3"
    echo   "║                                                                 ║"
    printf "║  [4] Code Formatter — black (Python), ruff                       ║\n"
    printf "║      Formattazione codice con Ctrl+Alt+F                        ║\n"
    printf "║      Stato: %-52s║\n" "$lbl4"
    echo   "║                                                                 ║"
    echo   "║  [a] Tutti i componenti opzionali                               ║"
    echo   "║  [n] Nessun componente opzionale (solo dipendenze base)         ║"
    echo   "╚══════════════════════════════════════════════════════════════════╝"
    echo
    echo    "  Componenti già completamente installati verranno saltati."
    echo -n "Seleziona i componenti da installare (es. 1 2 3 4 oppure a/n): "
    read -r OPT_CHOICE

    INSTALL_LATEX=false
    INSTALL_SPREADSHEET=false
    INSTALL_RICHTEXT=false
    INSTALL_FORMATTERS=false

    case "$OPT_CHOICE" in
        a|A|all|ALL)
            INSTALL_LATEX=true
            INSTALL_SPREADSHEET=true
            INSTALL_RICHTEXT=true
            INSTALL_FORMATTERS=true
            ;;
        n|N|no|NO|'')
            # nessun opzionale
            ;;
        *)
            # selezione multipla: es. "1 2" o "13"
            [[ "$OPT_CHOICE" == *1* ]] && INSTALL_LATEX=true
            [[ "$OPT_CHOICE" == *2* ]] && INSTALL_SPREADSHEET=true
            [[ "$OPT_CHOICE" == *3* ]] && INSTALL_RICHTEXT=true
            [[ "$OPT_CHOICE" == *4* ]] && INSTALL_FORMATTERS=true
            ;;
    esac

    # Salta automaticamente i componenti già completamente installati
    [[ "$STATUS_LATEX"        == "all" ]] && INSTALL_LATEX=false
    [[ "$STATUS_SPREADSHEET" == "all" ]] && INSTALL_SPREADSHEET=false
    [[ "$STATUS_RICHTEXT"     == "all" ]] && INSTALL_RICHTEXT=false
    [[ "$STATUS_FORMATTERS"  == "all" ]] && INSTALL_FORMATTERS=false

    echo
    echo "Componenti selezionati:"
    $INSTALL_LATEX        && echo "  LaTeX avanzato     : sì" || { [[ "$STATUS_LATEX"        == "all" ]] && echo "  LaTeX avanzato     : già installato (saltato)" || echo "  LaTeX avanzato     : no"; }
    $INSTALL_SPREADSHEET  && echo "  Foglio di calcolo  : sì" || { [[ "$STATUS_SPREADSHEET" == "all" ]] && echo "  Foglio di calcolo  : già installato (saltato)" || echo "  Foglio di calcolo  : no"; }
    $INSTALL_RICHTEXT     && echo "  Rich Text (WYSIWYG): sì" || { [[ "$STATUS_RICHTEXT"     == "all" ]] && echo "  Rich Text (WYSIWYG): già installato (saltato)" || echo "  Rich Text (WYSIWYG): no"; }
    $INSTALL_FORMATTERS   && echo "  Code Formatter     : sì" || { [[ "$STATUS_FORMATTERS"  == "all" ]] && echo "  Code Formatter     : già installato (saltato)" || echo "  Code Formatter     : no"; }
    echo
}

# Tenta pip con gli argomenti opzionali; se fallisce a causa di "externally managed",
# offre l'installazione in un venv dedicato e aggiorna il lanciatore.
# Se il .venv del progetto esiste già, installa direttamente lì senza passare per pip di sistema.
_pip_or_venv() {
    local pkgs="$1"
    local extra_args="${2:-}"
    local VENV_DIR="${PROJECT_DIR}/.venv"

    # Se il venv esiste già, installa direttamente nel venv (coerenza: tutto in un posto)
    if [[ -x "${VENV_DIR}/bin/python" ]]; then
        echo "  .venv rilevato — installo nel venv esistente: ${VENV_DIR}"
        "${VENV_DIR}/bin/pip" install --quiet $pkgs
        return $?
    fi

    $PYTHON -m pip install $extra_args $pkgs >/tmp/_pip_out.txt 2>&1
    local pip_exit=$?

    if [[ $pip_exit -eq 0 ]]; then
        return 0
    fi

    if grep -q "externally-managed\|externally managed\|--break-system-packages" /tmp/_pip_out.txt 2>/dev/null; then
        echo
        echo "  pip ha bloccato l'installazione (ambiente Python gestito dal sistema)."
        echo -n "  Installare i pacchetti in un virtualenv dedicato (${PROJECT_DIR}/.venv)? [S/n] "
        read -r VENV_CHOICE
        VENV_CHOICE=${VENV_CHOICE:-s}
        if [[ "$VENV_CHOICE" =~ ^[Ss]$ ]]; then
            _install_in_venv "$pkgs"
        else
            echo "  Installazione saltata. Puoi installare manualmente: pip install $pkgs"
        fi
    else
        echo "  ATTENZIONE: pip ha restituito un errore durante l'installazione."
        cat /tmp/_pip_out.txt
    fi
}

# Crea (o riusa) un venv in PROJECT_DIR/.venv e installa i pacchetti.
# Aggiorna anche il lanciatore .desktop per usare il Python del venv.
_install_in_venv() {
    local pkgs="$1"
    local VENV_DIR="${PROJECT_DIR}/.venv"

    echo "  Creazione virtualenv in ${VENV_DIR}..."
    $PYTHON -m venv "$VENV_DIR"
    "${VENV_DIR}/bin/pip" install --upgrade pip --quiet
    echo "  Installazione pacchetti nel venv..."
    "${VENV_DIR}/bin/pip" install $pkgs

    # Aggiorna il lanciatore .desktop (se già creato) per usare il Python del venv
    local LAUNCHER="${HOME}/.local/share/applications/notepadpq.desktop"
    if [[ -f "$LAUNCHER" ]]; then
        sed -i "s|^Exec=.*|Exec=${VENV_DIR}/bin/python ${PROJECT_DIR}/main.py %F|" "$LAUNCHER"
        echo "  Lanciatore aggiornato per usare il venv: ${VENV_DIR}/bin/python"
    fi

    echo
    echo "  NOTA: per avviare NotePadPQ dal terminale con le dipendenze del venv:"
    echo "    ${VENV_DIR}/bin/python ${PROJECT_DIR}/main.py"
    echo "  oppure attiva il venv prima:"
    echo "    source ${VENV_DIR}/bin/activate"
    echo
}

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

# Chiedi all'utente quali componenti opzionali installare
_ask_optional_components
echo

if [[ "$OS" == MINGW* ]] || [[ "$OS" == CYGWIN* ]] || [[ "$OS" == MSYS* ]]; then
    # Windows: pip funziona liberamente
    PIP_OPTIONAL=""
    $INSTALL_SPREADSHEET  && PIP_OPTIONAL+="$PIP_SPREADSHEET "
    $INSTALL_RICHTEXT     && PIP_OPTIONAL+="$PIP_RICHTEXT "
    $INSTALL_LATEX        && PIP_OPTIONAL+="$PIP_LATEX "
    $INSTALL_FORMATTERS   && PIP_OPTIONAL+="$PIP_FORMATTERS "
    $PYTHON -m pip install $PIP_CORE $PIP_OPTIONAL

elif command -v pacman &>/dev/null; then
    echo "Arch Linux: installo dipendenze native via pacman..."
    sudo pacman -S --needed --noconfirm \
        python-pyqt6 python-pyqt6-webengine python-qscintilla-qt6 \
        python-chardet python-markdown python-docutils \
        python-pygithub python-gitlab \
        python-pyspellchecker python-keyring 2>/dev/null || true

    if $INSTALL_SPREADSHEET; then
        echo "  Spreadsheet: installo dipendenze native..."
        sudo pacman -S --needed --noconfirm \
            python-openpyxl python-xlrd python-odfpy 2>/dev/null || true
    fi
    if $INSTALL_RICHTEXT; then
        echo "  Rich Text: installo via pip..."
        $PYTHON -m pip install $PIP_RICHTEXT 2>/dev/null || true
    fi
    if $INSTALL_LATEX; then
        echo "  LaTeX avanzato: installo dipendenze native..."
        sudo pacman -S --needed --noconfirm \
            python-pymupdf python-matplotlib python-sympy 2>/dev/null || \
            $PYTHON -m pip install $PIP_LATEX 2>/dev/null || true
    fi
    if $INSTALL_FORMATTERS; then
        echo "  Code Formatter: installo black e ruff via pip..."
        $PYTHON -m pip install $PIP_FORMATTERS 2>/dev/null || true
    fi

elif command -v apt-get &>/dev/null; then
    BREAK="--break-system-packages"
    sudo apt-get update
    # Pacchetti base via apt (preferiti al pip su Debian/Ubuntu)
    APT_BASE="python3-pyqt6 python3-pyqt6.qsci python3-chardet python3-markdown python3-pyqt6.qtwebengine"
    APT_OPTIONAL=""
    $INSTALL_SPREADSHEET && APT_OPTIONAL+=" python3-openpyxl python3-xlrd python3-odf"
    $INSTALL_LATEX       && APT_OPTIONAL+=" python3-matplotlib python3-sympy"
    sudo apt-get install -y $APT_BASE $APT_OPTIONAL 2>/dev/null || true

    # Pacchetti non disponibili in apt → pip (con fallback venv)
    echo "  Installazione pacchetti base non disponibili in apt (PyGithub, keyring, ecc.)..."
    _pip_or_venv "$PIP_CORE" "$BREAK"

    if $INSTALL_RICHTEXT; then
        echo "  Rich Text: installo via pip..."
        _pip_or_venv "$PIP_RICHTEXT" "$BREAK"
    fi
    if $INSTALL_LATEX; then
        echo "  LaTeX avanzato: installo pymupdf via pip..."
        _pip_or_venv "pymupdf" "$BREAK"
    fi
    if $INSTALL_FORMATTERS; then
        echo "  Code Formatter: installo black via apt e ruff via pip..."
        sudo apt-get install -y python3-black 2>/dev/null || true
        _pip_or_venv "ruff" "$BREAK"
    fi

elif command -v dnf &>/dev/null; then
    sudo dnf install -y \
        python3-qt6 python3-qscintilla-qt6 python3-qt6-webengine \
        python3-chardet python3-markdown 2>/dev/null || true

    PIP_OPTIONAL=""
    $INSTALL_SPREADSHEET  && PIP_OPTIONAL+="$PIP_SPREADSHEET "
    $INSTALL_RICHTEXT     && PIP_OPTIONAL+="$PIP_RICHTEXT "
    $INSTALL_LATEX        && PIP_OPTIONAL+="$PIP_LATEX "
    $INSTALL_FORMATTERS   && PIP_OPTIONAL+="$PIP_FORMATTERS "
    $PYTHON -m pip install --user $PIP_CORE $PIP_OPTIONAL || true

elif [[ "$OS" == "FreeBSD" ]]; then
    echo "FreeBSD: rilevazione versione Python..."
    PY_VER=$($PYTHON -c "import sys; print(f'{sys.version_info.major}{sys.version_info.minor}')")
    echo "  Versione Python: $PY_VER"
    # Pacchetti base disponibili nei ports FreeBSD
    PKG_OPTIONAL=""
    $INSTALL_SPREADSHEET && PKG_OPTIONAL+=" py${PY_VER}-openpyxl py${PY_VER}-xlrd py${PY_VER}-odfpy"
    sudo pkg install -y \
        "py${PY_VER}-pip" \
        "py${PY_VER}-qt6-qscintilla2" \
        "py${PY_VER}-chardet" \
        "py${PY_VER}-markdown" \
        "py${PY_VER}-docutils" \
        "py${PY_VER}-keyring" \
        "py${PY_VER}-python-gitlab" \
        $PKG_OPTIONAL
    # PyQt6, PyQt6-WebEngine, pyspellchecker, PyGithub non sono nei ports -> pip
    PIPBIN=$(command -v pip3 || command -v pip || true)
    if [[ -n "$PIPBIN" ]]; then
        PIP_OPTIONAL=""
        $INSTALL_RICHTEXT     && PIP_OPTIONAL+="$PIP_RICHTEXT "
        $INSTALL_LATEX        && PIP_OPTIONAL+="$PIP_LATEX "
        $INSTALL_FORMATTERS   && PIP_OPTIONAL+="$PIP_FORMATTERS "
        $PIPBIN install --user PyQt6 PyQt6-WebEngine PyQt6-QScintilla pyspellchecker PyGithub $PIP_OPTIONAL || true
    else
        echo "  ERRORE: pip non trovato dopo installazione py${PY_VER}-pip"
        echo "  Riprova: sudo pkg install py${PY_VER}-pip"
    fi

else
    PIP_OPTIONAL=""
    $INSTALL_SPREADSHEET  && PIP_OPTIONAL+="$PIP_SPREADSHEET "
    $INSTALL_RICHTEXT     && PIP_OPTIONAL+="$PIP_RICHTEXT "
    $INSTALL_LATEX        && PIP_OPTIONAL+="$PIP_LATEX "
    $INSTALL_FORMATTERS   && PIP_OPTIONAL+="$PIP_FORMATTERS "
    $PYTHON -m pip install $PIP_CORE $PIP_OPTIONAL || true
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

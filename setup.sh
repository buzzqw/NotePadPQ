#!/bin/bash
# setup.sh — NotePadPQ setup
# Valido su: Debian/Ubuntu, Fedora, Arch Linux, macOS, Windows, FreeBSD
set -euo pipefail

PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PYTHON=${PYTHON:-python3}
OS=$(uname)
VENV_DIR="${PROJECT_DIR}/.venv"

# ─── Configurazione pacchetti ─────────────────────────────────────────────────

# pyproject.toml is the authoritative source for dependencies and extras.
CORE_PY="${PROJECT_DIR}"

# Componenti opzionali
OPT_LATEX="pymupdf matplotlib sympy"
OPT_SPREAD="openpyxl xlrd odfpy"
OPT_RICHTEXT="mammoth htmldocx pypandoc"
OPT_FORMATTERS="black ruff"
OPT_DATABASE="psycopg2-binary mysql-connector-python oracledb"
OPT_FTP="paramiko"
OPT_ENCRYPT="cryptography"
OPT_GIT="PyGithub python-gitlab keyring"
OPT_RESTCLIENT="requests"

# ─── Helper: presenza uv ──────────────────────────────────────────────────────

_ensure_uv() {
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if command -v uv &>/dev/null; then
        echo "   uv $(uv --version 2>/dev/null || echo 'non specificata') — già presente"
        return 0
    fi
    echo "   uv non trovato: uso venv e pip senza scaricare script remoti."
}

# ─── Helper: crea .venv e installa pacchetti Python via uv ────────────────────

_uv_venv_install() {
    local pkgs="$1"
    local label="${2:-pacchetti}"
    local venv_opts="${3:-}"   # es. "--system-site-packages"

    if [[ ! -d "$VENV_DIR" ]]; then
        echo "   Creazione virtualenv con uv in ${VENV_DIR}..."
        if command -v uv &>/dev/null; then
            uv venv $venv_opts "$VENV_DIR" 2>/dev/null || true
        fi
        if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
            if [[ -n "$venv_opts" ]]; then
                $PYTHON -m venv $venv_opts "$VENV_DIR"
            else
                $PYTHON -m venv "$VENV_DIR"
            fi
        fi
    else
        echo "   Virtualenv esistente: ${VENV_DIR}"
    fi

    echo "   Installazione ${label} nel venv..."
    if command -v uv &>/dev/null; then
        uv pip install --python "${VENV_DIR}/bin/python" "$pkgs" || {
            echo "   uv fallito, provo con pip nel venv..."
            "${VENV_DIR}/bin/pip" install --quiet "$pkgs"
        }
    else
        "${VENV_DIR}/bin/pip" install --quiet "$pkgs"
    fi
    return 0
}

# ─── Helper: crea lanciatore .desktop ─────────────────────────────────────────

_create_launcher() {
    local PYTHON_BIN
    if [[ -x "${VENV_DIR}/bin/python" ]]; then
        PYTHON_BIN="${VENV_DIR}/bin/python"
    else
        PYTHON_BIN=$(command -v "$PYTHON")
    fi

    local ICON
    ICON="text-editor"
    for try in icons/NotePadPQ_256.png icons/NotePadPQ.png icons/notepadpq.png; do
        if [[ -f "${PROJECT_DIR}/${try}" ]]; then
            ICON="${PROJECT_DIR}/${try}"
            break
        fi
    done

    mkdir -p "${HOME}/.local/share/applications"
    cat > "${HOME}/.local/share/applications/notepadpq.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=NotePadPQ
Comment=Advanced text editor — PyQt6 + QScintilla
Exec=${PYTHON_BIN} ${PROJECT_DIR}/main.py %F
Icon=${ICON}
Terminal=false
Categories=Development;TextEditor;Utility;
MimeType=text/plain;text/x-python;text/x-c++src;text/x-latex;application/x-shellscript;application/json;application/xml;text/markdown;text/x-rst;
EOF
    chmod +x "${HOME}/.local/share/applications/notepadpq.desktop"
    echo "   Lanciatore creato: ~/.local/share/applications/notepadpq.desktop"
}

# ─── Verifica rapida moduli Python ────────────────────────────────────────────

_verify_module() {
    local pybin="${1:-$PYTHON}"
    local mod="$2"
    local label="$3"
    local good="$4"
    [[ -x "${VENV_DIR}/bin/python" ]] && pybin="${VENV_DIR}/bin/python"

    if $pybin -c "import ${mod}" &>/dev/null 2>&1; then
        printf "   %-20s OK\n" "$label"
    else
        printf "   %-20s NON TROVATO   (%s)\n" "$label" "$good"
    fi
}

# ─── Menù componenti opzionali ────────────────────────────────────────────────

_choose_optional() {
    local pybin="$PYTHON"
    [[ -x "${VENV_DIR}/bin/python" ]] && pybin="${VENV_DIR}/bin/python"

    _check_group() {
        local pkg grp found=0 total=0
        for pkg in $1; do
            total=$((total+1))
            local imp=""
            case "$pkg" in
                pymupdf)     imp="fitz" ;;  odfpy)       imp="odf" ;;
                PyGithub)    imp="github" ;; python-gitlab) imp="gitlab" ;;
                mysql-connector-python) imp="mysql.connector" ;;
                PyQt6-QScintilla) imp="PyQt6.Qsci" ;;
                *)           imp=$(echo "$pkg" | tr '-' '_') ;;
            esac
            $pybin -c "import ${imp}" &>/dev/null 2>&1 && found=$((found+1))
        done
        if   [[ $found -eq $total ]]; then echo "all"
        elif [[ $found -gt 0 ]];      then echo "partial"
        else                               echo "none"
        fi
    }

    local st_latex;       st_latex=$(_check_group "$OPT_LATEX")
    local st_spread;      st_spread=$(_check_group "$OPT_SPREAD")
    local st_richtext;    st_richtext=$(_check_group "$OPT_RICHTEXT")
    local st_formatters;  st_formatters=$(_check_group "$OPT_FORMATTERS")
    local st_database;    st_database=$(_check_group "$OPT_DATABASE")
    local st_ftp;         st_ftp=$(_check_group "$OPT_FTP")
    local st_encrypt;     st_encrypt=$(_check_group "$OPT_ENCRYPT")
    local st_git;         st_git=$(_check_group "$OPT_GIT")
    local st_restclient;  st_restclient=$(_check_group "$OPT_RESTCLIENT")

    _label() {
        case "$1" in all) echo "✓ già installato";; partial) echo "~ parziale";; *) echo "✗ mancante";; esac
    }

    echo
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║  Componenti opzionali — NotePadPQ                               ║"
    echo "╠══════════════════════════════════════════════════════════════════╣"
    printf "║  [1] LaTeX avanzato (pymupdf, matplotlib, sympy)       %s║\n" "$(_label "$st_latex")"
    printf "║  [2] Foglio di calcolo (openpyxl, xlrd, odfpy)        %s║\n" "$(_label "$st_spread")"
    printf "║  [3] Rich Text WYSIWYG (mammoth, htmldocx, pypandoc)  %s║\n" "$(_label "$st_richtext")"
    printf "║  [4] Code Formatter (black, ruff)                      %s║\n" "$(_label "$st_formatters")"
    printf "║  [5] Database (PostgreSQL, MySQL, Oracle)               %s║\n" "$(_label "$st_database")"
    printf "║  [6] FTP/SFTP (paramiko)                                %s║\n" "$(_label "$st_ftp")"
    printf "║  [7] Crittografia (cryptography)                        %s║\n" "$(_label "$st_encrypt")"
    printf "║  [8] GitHub/GitLab e keyring                            %s║\n" "$(_label "$st_git")"
    printf "║  [9] REST client (requests)                             %s║\n" "$(_label "$st_restclient")"
    echo "║  [a] Tutti                                                ║"
    echo "║  [n] Nessuno (solo dipendenze base)                       ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo -n "Scelta (es. 1 2 3 4, a, n): "
    read -r CHOICE

    IL=false; IS=false; IR=false; IF=false; IDB=false; IFTP=false; IENC=false; IGIT=false; IREST=false
    case "$CHOICE" in
        a|A) IL=true; IS=true; IR=true; IF=true; IDB=true; IFTP=true; IENC=true; IGIT=true; IREST=true ;;
        n|N|'') ;;
        *)
            [[ "$CHOICE" == *1* ]] && IL=true
            [[ "$CHOICE" == *2* ]] && IS=true
            [[ "$CHOICE" == *3* ]] && IR=true
            [[ "$CHOICE" == *4* ]] && IF=true
            [[ "$CHOICE" == *5* ]] && IDB=true
            [[ "$CHOICE" == *6* ]] && IFTP=true
            [[ "$CHOICE" == *7* ]] && IENC=true
            [[ "$CHOICE" == *8* ]] && IGIT=true
            [[ "$CHOICE" == *9* ]] && IREST=true
            ;;
    esac
    # Nota: anche se i pacchetti risultano già installati nel sistema,
    # li installiamo comunque nel venv (uv gestisce i duplicati).
    # Lo stato mostrato è solo informativo.
}

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

echo "=== NotePadPQ Setup ==="
echo

_choose_optional

echo
echo "=== Installazione dipendenze ==="

# ─── Raccogliamo la lista completa dei pacchetti Python da installare ─────────
SELECTED_EXTRAS=""
$IL && SELECTED_EXTRAS="${SELECTED_EXTRAS},latex"
$IS && SELECTED_EXTRAS="${SELECTED_EXTRAS},spreadsheet"
$IR && SELECTED_EXTRAS="${SELECTED_EXTRAS},richtext"
$IF && SELECTED_EXTRAS="${SELECTED_EXTRAS},formatter"
$IDB && SELECTED_EXTRAS="${SELECTED_EXTRAS},database"
$IFTP && SELECTED_EXTRAS="${SELECTED_EXTRAS},ftp"
$IENC && SELECTED_EXTRAS="${SELECTED_EXTRAS},encrypt"
$IGIT && SELECTED_EXTRAS="${SELECTED_EXTRAS},git"
$IREST && SELECTED_EXTRAS="${SELECTED_EXTRAS},restclient"
INSTALL_TARGET="$CORE_PY"
[[ -n "$SELECTED_EXTRAS" ]] && INSTALL_TARGET="${PROJECT_DIR}[${SELECTED_EXTRAS#,}]"

# ─── Funzione di installazione per-distro ─────────────────────────────────────

case "$OS" in
# ── macOS ─────────────────────────────────────────────────────────────────────
Darwin)
    echo "==> macOS: installazione tutto via uv"
    if ! command -v brew &>/dev/null; then
        echo "   Homebrew non trovato. Installalo da https://brew.sh"
        echo "   Poi riavvia setup.sh"
        exit 1
    fi
    brew install pandoc clang-format 2>/dev/null || true
    _ensure_uv && _uv_venv_install "$INSTALL_TARGET" "dipendenze Python"
    ;;

# ── Windows (MINGW/CYGWIN/MSYS) ───────────────────────────────────────────────
MINGW*|CYGWIN*|MSYS*)
    echo "==> Windows: installazione via pip"
    $PYTHON -m pip install --quiet "$INSTALL_TARGET" || {
        echo "   ERRORE: pip fallito. Installa uv (pip install uv) e riprova."
        exit 1
    }
    ;;

# ── FreeBSD ───────────────────────────────────────────────────────────────────
FreeBSD)
    echo "==> FreeBSD: installazione nativa + pip"
    PY_VER=$($PYTHON -c "import sys; print(f'{sys.version_info.major}{sys.version_info.minor}')")
    sudo pkg install -y \
        "py${PY_VER}-pip" \
        "py${PY_VER}-qt6-qscintilla2" \
        "py${PY_VER}-chardet" \
        "py${PY_VER}-markdown" \
        "py${PY_VER}-docutils" \
        "py${PY_VER}-pygments" \
        "py${PY_VER}-psutil" 2>/dev/null || true
    # Pacchetti non disponibili nei port → uv
    _ensure_uv && _uv_venv_install "$INSTALL_TARGET" "dipendenze rimanenti"
    ;;

# ── Linux ─────────────────────────────────────────────────────────────────────
Linux)
    if command -v pacman &>/dev/null; then
        # ─── Arch Linux ───────────────────────────────────────────────────────
        echo "==> Arch Linux: installazione via pacman + uv"

        APKGS="python-pyqt6 python-pyqt6-webengine python-qscintilla-qt6"
        APKGS="$APKGS python-chardet python-markdown python-docutils"
        APKGS="$APKGS python-pygments python-psutil python-pyspellchecker"

        $IL && APKGS="$APKGS python-pymupdf python-matplotlib python-sympy"
        $IS && APKGS="$APKGS python-openpyxl python-xlrd python-odfpy"
        $IR && APKGS="$APKGS python-mammoth python-htmldocx python-pypandoc"  # potrebbero non esistere
        $IF && APKGS="$APKGS python-black python-ruff"

        sudo pacman -S --needed --noconfirm $APKGS 2>/dev/null || true

        # Il venv eredita i pacchetti pacman e riceve i mancanti via uv
        echo "   Installazione pacchetti rimanenti via uv..."
        _ensure_uv && _uv_venv_install "$INSTALL_TARGET" "dipendenze Python" "--system-site-packages"

    elif command -v apt-get &>/dev/null; then
        # ─── Debian / Ubuntu ──────────────────────────────────────────────────
        echo "==> Debian/Ubuntu: installazione via apt + uv"

        sudo apt-get update -qq 2>/dev/null || true

        # Pacchetti disponibili via apt
        APT="python3-pyqt6 python3-pyqt6.qscintilla python3-pyqt6.qtwebengine"
        APT="$APT python3-chardet python3-markdown python3-docutils"
        APT="$APT python3-pygments python3-psutil python3-pip python3-venv"

        $IL && APT="$APT python3-matplotlib python3-sympy"
        $IS && APT="$APT python3-openpyxl python3-xlrd python3-odf"
        $IF && APT="$APT python3-black"

        sudo apt-get install -y $APT 2>/dev/null || true

        # Pacchetti NON disponibili via apt → uv (venv eredita i pacchetti apt)
        echo "   Installazione pacchetti rimanenti via uv..."
        _ensure_uv && _uv_venv_install "$INSTALL_TARGET" "dipendenze Python" "--system-site-packages"

    elif command -v dnf &>/dev/null; then
        # ─── Fedora ───────────────────────────────────────────────────────────
        echo "==> Fedora: installazione via dnf + uv"

        DNF="python3-qt6 python3-qscintilla-qt6 python3-qt6-webengine"
        DNF="$DNF python3-chardet python3-markdown python3-docutils"
        DNF="$DNF python3-pygments python3-psutil python3-pip"

        $IL && DNF="$DNF python3-matplotlib python3-sympy"
        $IS && DNF="$DNF python3-openpyxl python3-xlrd python3-odfpy"
        $IF && DNF="$DNF python3-black"

        sudo dnf install -y $DNF 2>/dev/null || true

        # Pacchetti NON disponibili via dnf → uv (venv eredita i pacchetti dnf)
        echo "   Installazione pacchetti rimanenti via uv..."
        _ensure_uv && _uv_venv_install "$INSTALL_TARGET" "dipendenze Python" "--system-site-packages"

    else
        # ─── Altra distro Linux (fallback totale su uv) ───────────────────────
        echo "==> Distro Linux sconosciuta: installazione tutto via uv"
        _ensure_uv && _uv_venv_install "$INSTALL_TARGET" "dipendenze Python"
    fi
    ;;

# ── Fallback ──────────────────────────────────────────────────────────────────
*)
    echo "==> OS sconosciuto: installazione via uv"
    _ensure_uv && _uv_venv_install "$INSTALL_TARGET" "dipendenze Python"
    ;;
esac

# ═══════════════════════════════════════════════════════════════════════════════
# VERIFICA FINALE
# ═══════════════════════════════════════════════════════════════════════════════

VERIFY_PY="$PYTHON"
[[ -x "${VENV_DIR}/bin/python" ]] && VERIFY_PY="${VENV_DIR}/bin/python"

echo
echo "=== Verifica dipendenze ==="
echo "--- Base (richieste) ---"
_verify_module "$VERIFY_PY" "PyQt6.QtWidgets"     "PyQt6"              "pip install PyQt6"
_verify_module "$VERIFY_PY" "PyQt6.Qsci"          "QScintilla"         "pip install PyQt6-QScintilla"
_verify_module "$VERIFY_PY" "PyQt6.QtWebEngineWidgets" "WebEngine"     "pip install PyQt6-WebEngine"
_verify_module "$VERIFY_PY" "chardet"             "chardet"            "pip install chardet"
_verify_module "$VERIFY_PY" "pygments"            "pygments"           "pip install pygments"
_verify_module "$VERIFY_PY" "psutil"              "psutil"             "pip install psutil"
_verify_module "$VERIFY_PY" "markdown"            "markdown"           "pip install markdown"
_verify_module "$VERIFY_PY" "docutils"            "docutils"           "pip install docutils"
_verify_module "$VERIFY_PY" "spellchecker"        "spellchecker"       "pip install pyspellchecker"
echo
echo "--- Database, FTP e servizi (opzionale) ---"
_verify_module "$VERIFY_PY" "psycopg2"            "PostgreSQL"         "pip install '.[database]'"
_verify_module "$VERIFY_PY" "mysql.connector"     "MySQL"              "pip install '.[database]'"
_verify_module "$VERIFY_PY" "oracledb"            "Oracle"             "pip install '.[database]'"
_verify_module "$VERIFY_PY" "paramiko"            "SFTP"               "pip install '.[ftp]'"
_verify_module "$VERIFY_PY" "requests"            "REST client"        "pip install '.[restclient]'"

echo
echo "--- Git e sicurezza (opzionale) ---"
_verify_module "$VERIFY_PY" "github"              "PyGithub"           "pip install '.[git]'"
_verify_module "$VERIFY_PY" "gitlab"              "python-gitlab"      "pip install '.[git]'"
_verify_module "$VERIFY_PY" "keyring"             "keyring"            "pip install '.[git]'"
_verify_module "$VERIFY_PY" "cryptography"        "cryptography"       "pip install '.[encrypt]'"

echo
echo "--- Foglio di calcolo (opzionale) ---"
_verify_module "$VERIFY_PY" "openpyxl"  "openpyxl"  "pip install openpyxl"
_verify_module "$VERIFY_PY" "xlrd"      "xlrd"      "pip install xlrd"
_verify_module "$VERIFY_PY" "odf"       "odfpy"     "pip install odfpy"

echo
echo "--- Rich Text (opzionale) ---"
_verify_module "$VERIFY_PY" "mammoth"   "mammoth"   "pip install mammoth"
_verify_module "$VERIFY_PY" "htmldocx"  "htmldocx"  "pip install htmldocx"
_verify_module "$VERIFY_PY" "pypandoc"  "pypandoc"  "pip install pypandoc"
command -v pandoc &>/dev/null && echo "   pandoc              OK" || echo "   pandoc              NON TROVATO (apt install pandoc)"

echo
echo "--- LaTeX avanzato (opzionale) ---"
_verify_module "$VERIFY_PY" "fitz"       "PyMuPDF"    "pip install pymupdf"
_verify_module "$VERIFY_PY" "matplotlib" "matplotlib" "pip install matplotlib"
_verify_module "$VERIFY_PY" "sympy"      "sympy"      "pip install sympy"
command -v synctex &>/dev/null && echo "   synctex             OK" || echo "   synctex             non installato (incluso in TeX Live)"

echo
echo "--- Code Formatter (opzionale) ---"
_verify_module "$VERIFY_PY" "black"  "black (Python)"  "pip install black"
_verify_module "$VERIFY_PY" "ruff"   "ruff (Python)"   "pip install ruff"
for t in prettier clang-format; do
    command -v "$t" &>/dev/null && echo "   $t                  OK" || echo "   $t                  non installato"
done

echo
echo "--- LSP (opzionale) ---"
for t in pylsp clangd texlab; do
    command -v "$t" &>/dev/null && echo "   $t                  OK" || echo "   $t                  non installato"
done

# ─── Lanciatore .desktop (solo Linux) ─────────────────────────────────────────
if [[ "$OS" == "Linux" ]]; then
    echo
    echo "=== Lanciatore desktop ==="
    _create_launcher
fi

# ─── Istruzioni finali ────────────────────────────────────────────────────────
echo
echo "=== Setup completato ==="
if [[ -x "${VENV_DIR}/bin/python" ]]; then
    echo "Avvia NotePadPQ con:"
    echo "  ${VENV_DIR}/bin/python ${PROJECT_DIR}/main.py"
    echo "  oppure: source ${VENV_DIR}/bin/activate && python main.py"
else
    echo "Avvia NotePadPQ con: $PYTHON main.py"
fi
echo "Oppure cercala nel menu applicazioni (Linux)."

#!/bin/bash
# build-appimage.sh — Costruisce l'AppImage di NotePadPQ in locale.
#
# Uso:
#   cd <root-del-progetto>
#   bash packaging/appimage/build-appimage.sh [--skip-deps] [--skip-pyinstaller]
#
# Opzioni:
#   --skip-deps          Non reinstalla le dipendenze Python (più veloce nelle build ripetute)
#   --skip-pyinstaller   Salta PyInstaller (usa dist/notepadpq/ già esistente)
#
# Requisiti di sistema:
#   - python3 (con python3-venv)
#   - fuse (o fuse2) per eseguire/testare l'AppImage
#   appimagetool viene scaricato automaticamente se non trovato nel PATH.
#
# Note:
#   Le dipendenze Python vengono installate in un virtualenv isolato (.venv-build/)
#   per evitare il blocco PEP 668 degli ambienti Python "externally-managed".

set -euo pipefail

# ── Colori ─────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
info()  { echo -e "${CYAN}ℹ  ${RESET}$*"; }
ok()    { echo -e "${GREEN}✔  ${RESET}$*"; }
warn()  { echo -e "${YELLOW}⚠  ${RESET}$*" >&2; }
err()   { echo -e "${RED}✘  ${RESET}$*" >&2; exit 1; }
step()  { echo -e "\n${BOLD}══ $* ══${RESET}"; }

# ── Argomenti ──────────────────────────────────────────────────────────────────
SKIP_DEPS=false
SKIP_PYINSTALLER=false
for arg in "$@"; do
    case "$arg" in
        --skip-deps)         SKIP_DEPS=true ;;
        --skip-pyinstaller)  SKIP_PYINSTALLER=true ;;
        -h|--help)
            grep '^#' "$0" | head -20 | sed 's/^# \?//'
            exit 0
            ;;
        *) warn "Argomento sconosciuto: $arg" ;;
    esac
done

# ── Posizionamento nella root del progetto ─────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${ROOT}"
info "Root progetto: ${ROOT}"

# ── Rileva versione ────────────────────────────────────────────────────────────
APP_VERSION=$(python3 -c "
import re, sys
content = open('ui/main_window.py').read()
m = re.search(r'APP_VERSION\s*=\s*[\"\\']([^\"\\']+)[\"\\']', content)
print(m.group(1) if m else 'unknown')
" 2>/dev/null || echo "unknown")
ARCH="$(uname -m)"
APPIMAGE_NAME="NotePadPQ-${APP_VERSION}-${ARCH}.AppImage"
info "Versione: ${APP_VERSION}  |  Arch: ${ARCH}"
info "Output:   ${ROOT}/dist/${APPIMAGE_NAME}"

# ── 1. Verifica python3 ────────────────────────────────────────────────────────
step "Verifica ambiente Python"
command -v python3 >/dev/null 2>&1 || err "python3 non trovato nel PATH."
ok "python3: $(python3 --version)"

# ── 2. Virtualenv isolato ─────────────────────────────────────────────────────
# Usiamo sempre un venv dedicato (.venv-build/) per evitare il blocco PEP 668
# degli ambienti Python "externally-managed" (Debian/Ubuntu moderni).
VENV_DIR="${ROOT}/.venv-build"
if [[ "${SKIP_DEPS}" = false ]]; then
    step "Preparazione virtualenv (.venv-build/)"
    python3 -m venv "${VENV_DIR}" || \
        err "python3 -m venv fallito. Installa python3-venv: sudo apt install python3-venv"
    # Attiva il venv solo per questo script (PATH + VIRTUAL_ENV)
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
    pip install --quiet pyinstaller
    ok "Dipendenze installate nel venv."
else
    info "Installazione dipendenze saltata (--skip-deps)."
    # Attiva comunque il venv se esiste, altrimenti usa il Python di sistema
    if [[ -f "${VENV_DIR}/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source "${VENV_DIR}/bin/activate"
        info "Venv esistente attivato: ${VENV_DIR}"
    else
        warn "Nessun .venv-build/ trovato: si usa il Python di sistema."
    fi
fi

# Verifica pyinstaller dopo l'eventuale installazione
python3 -m PyInstaller --version >/dev/null 2>&1 || \
    err "pyinstaller non trovato nel venv. Rimuovi --skip-deps per reinstallare."

# ── 3. PyInstaller ────────────────────────────────────────────────────────────
if [[ "${SKIP_PYINSTALLER}" = false ]]; then
    step "Build PyInstaller (--onedir)"
    # Elimina build precedenti per evitare artefatti stantii
    rm -rf build/ dist/notepadpq/ dist/notepadpq.AppDir/

    # Usa python3 -m PyInstaller dal venv attivo
    python3 -m PyInstaller packaging/appimage/notepadpq.spec --noconfirm
    ok "PyInstaller completato: dist/notepadpq/"
else
    info "PyInstaller saltato (--skip-pyinstaller)."
    [[ -d "dist/notepadpq" ]] || err "dist/notepadpq/ non trovato. Rimuovi --skip-pyinstaller."
fi

# ── 4. Assembla AppDir ────────────────────────────────────────────────────────
step "Assemblaggio AppDir"
bash packaging/appimage/make-appdir.sh
ok "AppDir pronto: dist/notepadpq.AppDir/"

# ── 5. Cerca / scarica appimagetool ───────────────────────────────────────────
step "Ricerca appimagetool"
APPIMAGETOOL=""
if command -v appimagetool >/dev/null 2>&1; then
    APPIMAGETOOL="appimagetool"
    ok "appimagetool trovato nel PATH: $(command -v appimagetool)"
else
    # Cerca nella directory locale e in packaging/
    for candidate in \
        "${ROOT}/packaging/appimage/appimagetool-${ARCH}.AppImage" \
        "${ROOT}/packaging/appimagetool-${ARCH}.AppImage" \
        "${ROOT}/appimagetool-${ARCH}.AppImage" \
        "${ROOT}/packaging/appimage/appimagetool.AppImage" \
        "${ROOT}/appimagetool.AppImage"
    do
        if [[ -x "$candidate" ]]; then
            APPIMAGETOOL="$candidate"
            ok "appimagetool trovato: $candidate"
            break
        fi
    done
fi

if [[ -z "${APPIMAGETOOL}" ]]; then
    warn "appimagetool non trovato. Scaricamento in corso..."
    APPIMAGETOOL_URL="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-${ARCH}.AppImage"
    APPIMAGETOOL_DEST="${ROOT}/packaging/appimage/appimagetool-${ARCH}.AppImage"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL -o "${APPIMAGETOOL_DEST}" "${APPIMAGETOOL_URL}"
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "${APPIMAGETOOL_DEST}" "${APPIMAGETOOL_URL}"
    else
        err "curl e wget non disponibili. Scarica manualmente appimagetool da:\n  ${APPIMAGETOOL_URL}\ne salvalo in packaging/appimage/."
    fi
    chmod +x "${APPIMAGETOOL_DEST}"
    APPIMAGETOOL="${APPIMAGETOOL_DEST}"
    ok "appimagetool scaricato in: ${APPIMAGETOOL_DEST}"
fi

# ── 6. Crea AppImage ──────────────────────────────────────────────────────────
step "Creazione AppImage"
OUTPUT_PATH="${ROOT}/dist/${APPIMAGE_NAME}"

# ARCH deve essere esportata: appimagetool la usa per il nome del file interno
export ARCH

# Prova prima con FUSE (montaggio nativo); se non disponibile usa --appimage-extract-and-run
FUSE_FLAG=""
if ! ( fusermount --version >/dev/null 2>&1 || fusermount3 --version >/dev/null 2>&1 ); then
    warn "FUSE non disponibile: uso --appimage-extract-and-run per appimagetool."
    FUSE_FLAG="--appimage-extract-and-run"
fi

APPIMAGETOOL_SYSTEM_PATH="${APPIMAGE_EXTRACT_AND_RUN:-}"
if [[ -n "${FUSE_FLAG}" ]]; then
    APPIMAGE_EXTRACT_AND_RUN=1 "${APPIMAGETOOL}" \
        "${ROOT}/dist/notepadpq.AppDir" "${OUTPUT_PATH}" 2>&1
else
    "${APPIMAGETOOL}" \
        "${ROOT}/dist/notepadpq.AppDir" "${OUTPUT_PATH}" 2>&1
fi

# ── 7. Riepilogo ──────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}  AppImage creata con successo!${RESET}"
echo -e "${BOLD}  File: ${OUTPUT_PATH}${RESET}"
echo -e "  Dimensione: $(du -sh "${OUTPUT_PATH}" | cut -f1)"
echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════${RESET}"
echo ""
info "Per testare l'AppImage:"
echo "    chmod +x ${OUTPUT_PATH}"
echo "    ${OUTPUT_PATH}"

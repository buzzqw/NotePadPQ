#!/usr/bin/env bash
# ============================================================
#  build.sh — Build NotePadPQ per Windows (da Linux/macOS)
#  Equivalente bash di build.bat
# ============================================================
#  Uso:
#    ./build.sh           -> compila entrambe le versioni
#    ./build.sh full      -> compila solo versione Full
#    ./build.sh lite      -> compila solo versione Lite
#    ./build.sh installer -> compila entrambe + crea installer
#                           (richiede Inno Setup via Wine su Linux)
# ============================================================
#  NOTA: PyInstaller produce eseguibili .exe solo su Windows.
#  Questo script è pensato per:
#   - Ambienti CI/CD (GitHub Actions su windows-latest)
#   - Sviluppatori che usano Wine + PyInstaller su Linux/macOS
#   - Build in container Docker Windows (via QEMU/crosscompile)
#  Per una build locale nativa usare build.bat su Windows.
# ============================================================

set -euo pipefail

# ── Colori ────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'  # No Color

ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
info() { echo -e "${CYAN}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[AVVISO]${NC} $*"; }
err()  { echo -e "${RED}[ERRORE]${NC} $*" >&2; }

# ── Posizionati nella cartella windowsbuild ───────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# ── Leggi versione da main.py ─────────────────────────────────
VERSION=$(python3 -c "
import re
content = open('${PROJECT_ROOT}/main.py').read()
m = re.search(r\"setApplicationVersion\('(.+?)'\)\", content)
print(m.group(1) if m else '0.0.0')
" 2>/dev/null || echo "0.9.10")

BUILD_MODE="${1:-both}"

echo ""
echo "============================================================"
echo -e " ${CYAN}NotePadPQ v${VERSION} — Build Windows${NC}"
echo " Modalita': ${BUILD_MODE}"
echo " Data: $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
echo ""

# ── Controlla dipendenze ──────────────────────────────────────
check_deps() {
    local missing=()

    if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
        missing+=("python3")
    fi

    # Determina il comando python disponibile
    PYTHON_CMD="python3"
    command -v python3 &>/dev/null || PYTHON_CMD="python"

    if ! $PYTHON_CMD -m PyInstaller --version &>/dev/null 2>&1; then
        missing+=("pyinstaller (pip install pyinstaller)")
    fi

    if [[ ${#missing[@]} -gt 0 ]]; then
        err "Dipendenze mancanti:"
        for dep in "${missing[@]}"; do
            echo "   - $dep"
        done
        echo ""
        echo "   Esegui prima: bash install_deps.sh"
        exit 1
    fi

    ok "Python: $($PYTHON_CMD --version)"
    ok "PyInstaller: $($PYTHON_CMD -m PyInstaller --version)"
}

check_deps

# ── Pulizia build precedenti ──────────────────────────────────
info "Pulizia build precedenti..."
rm -rf "${PROJECT_ROOT}/dist/NotePadPQ_Full"
rm -rf "${PROJECT_ROOT}/dist/NotePadPQ_Lite"
rm -rf "${PROJECT_ROOT}/build"

# ── Aggiorna version_info.txt ─────────────────────────────────
info "Aggiorno version_info.txt per v${VERSION}..."
$PYTHON_CMD - <<PYEOF
import re

version = "${VERSION}".split(".")
while len(version) < 4:
    version.append("0")
ver_tuple = "({})".format(", ".join(version))

with open("version_info.txt", "r", encoding="utf-8") as f:
    content = f.read()

content = re.sub(r"filevers=\([\d, ]+\)", f"filevers={ver_tuple}", content)
content = re.sub(r"prodvers=\([\d, ]+\)", f"prodvers={ver_tuple}", content)
content = re.sub(r"'FileVersion',\s+'[\d.]+'", f"'FileVersion', '${VERSION}.0'", content)
content = re.sub(r"'ProductVersion',\s+'[\d.]+'", f"'ProductVersion', '${VERSION}'", content)

with open("version_info.txt", "w", encoding="utf-8") as f:
    f.write(content)

print("  version_info.txt aggiornato.")
PYEOF

# ── Funzione build ────────────────────────────────────────────
build_variant() {
    local variant="$1"   # full | lite
    local label="$2"     # etichetta leggibile
    local spec_file="notepadpq_${variant}.spec"
    local dist_name="NotePadPQ_$(echo "${variant^}" | sed 's/./\u&/')"

    # Normalizza nome cartella dist (Full/Lite con maiuscola)
    if [[ "$variant" == "full" ]]; then dist_name="NotePadPQ_Full"; fi
    if [[ "$variant" == "lite" ]]; then dist_name="NotePadPQ_Lite"; fi

    echo ""
    echo "============================================================"
    echo -e " ${CYAN}Build ${label}${NC}"
    echo "============================================================"
    echo ""

    $PYTHON_CMD -m PyInstaller --clean --noconfirm "$spec_file"
    local exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        err "Build ${label} fallita! (exit code: ${exit_code})"
        return 1
    fi

    ok "Build ${label} completata: dist/${dist_name}/"

    # Crea archivio ZIP
    local zip_name="NotePadPQ_v${VERSION}_${label}_Windows.zip"
    local zip_path="${PROJECT_ROOT}/dist/${zip_name}"
    local dist_path="${PROJECT_ROOT}/dist/${dist_name}"

    if [[ -d "$dist_path" ]]; then
        info "Creo archivio ${zip_name}..."
        # Usa zip se disponibile, altrimenti python
        if command -v zip &>/dev/null; then
            (cd "$dist_path" && zip -r "$zip_path" . -q)
        else
            $PYTHON_CMD -c "
import zipfile, pathlib
src = pathlib.Path('${dist_path}')
with zipfile.ZipFile('${zip_path}', 'w', zipfile.ZIP_DEFLATED) as zf:
    for f in src.rglob('*'):
        if f.is_file():
            zf.write(f, f.relative_to(src))
print('  ZIP creato.')
"
        fi
        ok "Archivio: dist/${zip_name}"
    fi

    return 0
}

# ── Esegui build richieste ────────────────────────────────────
BUILD_ERRORS=0

case "$BUILD_MODE" in
    full)
        build_variant "full" "Full" || BUILD_ERRORS=$((BUILD_ERRORS + 1))
        ;;
    lite)
        build_variant "lite" "Lite" || BUILD_ERRORS=$((BUILD_ERRORS + 1))
        ;;
    both|installer)
        build_variant "full" "Full" || BUILD_ERRORS=$((BUILD_ERRORS + 1))
        build_variant "lite" "Lite" || BUILD_ERRORS=$((BUILD_ERRORS + 1))
        ;;
    *)
        err "Modalita' non riconosciuta: ${BUILD_MODE}"
        echo "  Usa: both | full | lite | installer"
        exit 1
        ;;
esac

# ── Installer con Inno Setup via Wine (opzionale) ─────────────
if [[ "$BUILD_MODE" == "installer" ]]; then
    echo ""
    echo "============================================================"
    echo -e " ${CYAN}Creazione installer (Inno Setup via Wine)${NC}"
    echo "============================================================"
    echo ""

    ISCC=""
    for candidate in \
        "/root/.wine/drive_c/Program Files (x86)/Inno Setup 6/ISCC.exe" \
        "/home/$USER/.wine/drive_c/Program Files (x86)/Inno Setup 6/ISCC.exe" \
        "/opt/wine/drive_c/Program Files (x86)/Inno Setup 6/ISCC.exe"; do
        if [[ -f "$candidate" ]]; then
            ISCC="$candidate"
            break
        fi
    done

    if [[ -z "$ISCC" ]] && command -v wine &>/dev/null; then
        warn "Inno Setup non trovato nel prefisso Wine."
        warn "Per installarlo: wine InnoSetup-6.x.x.exe"
    elif [[ -n "$ISCC" ]]; then
        wine "$ISCC" /DMyAppVersion="${VERSION}" create_installer.iss
        if [[ $? -eq 0 ]]; then
            ok "Installer creato in dist/"
        else
            err "Creazione installer fallita."
            BUILD_ERRORS=$((BUILD_ERRORS + 1))
        fi
    else
        warn "Wine non disponibile. Salta creazione installer."
        warn "Su Ubuntu: sudo apt install wine"
    fi
fi

# ── Riepilogo ─────────────────────────────────────────────────
echo ""
echo "============================================================"
if [[ $BUILD_ERRORS -eq 0 ]]; then
    echo -e " ${GREEN}BUILD COMPLETATA CON SUCCESSO${NC}"
else
    echo -e " ${RED}BUILD COMPLETATA CON ${BUILD_ERRORS} ERRORE/I${NC}"
fi
echo "============================================================"
echo ""
echo "  Versione : ${VERSION}"
echo "  Cartella : ${PROJECT_ROOT}/dist/"
echo ""

[[ -d "${PROJECT_ROOT}/dist/NotePadPQ_Full" ]] && \
    echo "  [Full]  dist/NotePadPQ_Full/NotePadPQ.exe"
[[ -d "${PROJECT_ROOT}/dist/NotePadPQ_Lite" ]] && \
    echo "  [Lite]  dist/NotePadPQ_Lite/NotePadPQ.exe"
[[ -f "${PROJECT_ROOT}/dist/NotePadPQ_v${VERSION}_Full_Windows.zip" ]] && \
    echo "  [ZIP]   dist/NotePadPQ_v${VERSION}_Full_Windows.zip"
[[ -f "${PROJECT_ROOT}/dist/NotePadPQ_v${VERSION}_Lite_Windows.zip" ]] && \
    echo "  [ZIP]   dist/NotePadPQ_v${VERSION}_Lite_Windows.zip"

echo ""
echo "============================================================"

exit $BUILD_ERRORS

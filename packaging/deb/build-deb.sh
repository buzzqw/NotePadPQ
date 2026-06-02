#!/bin/bash
# build-deb.sh — Costruisce il pacchetto .deb di NotePadPQ in locale.
#
# Richiede un ambiente Ubuntu/Debian con:
#   sudo apt install python3 python3-pip rsync fakeroot dpkg-dev
#
# Uso:
#   cd <root-del-progetto>
#   bash packaging/deb/build-deb.sh [--skip-vendor]
#
# Opzioni:
#   --skip-vendor   Non reinstalla i pacchetti pip vendor (build ripetute)
#
# Output:
#   dist/notepadpq_<versione>_amd64.deb

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
info()  { echo -e "${CYAN}ℹ  ${RESET}$*"; }
ok()    { echo -e "${GREEN}✔  ${RESET}$*"; }
warn()  { echo -e "${YELLOW}⚠  ${RESET}$*" >&2; }
err()   { echo -e "${RED}✘  ${RESET}$*" >&2; exit 1; }
step()  { echo -e "\n${BOLD}══ $* ══${RESET}"; }

# ── Argomenti ──────────────────────────────────────────────────────────────────
SKIP_VENDOR=false
for arg in "$@"; do
    case "$arg" in
        --skip-vendor) SKIP_VENDOR=true ;;
        -h|--help)
            grep '^#' "$0" | head -15 | sed 's/^# \?//'; exit 0 ;;
        *) warn "Argomento sconosciuto: $arg" ;;
    esac
done

# ── Posizionamento nella root del progetto ─────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${ROOT}"
info "Root progetto: ${ROOT}"

# ── Verifica prerequisiti ─────────────────────────────────────────────────────
step "Verifica prerequisiti"
for cmd in python3 pip3 rsync fakeroot dpkg-deb; do
    command -v "$cmd" >/dev/null 2>&1 \
        || err "${cmd} non trovato. Installa: sudo apt install python3 python3-pip rsync fakeroot dpkg-dev"
done
ok "Tutti i prerequisiti trovati."

# ── Versione ──────────────────────────────────────────────────────────────────
APP_VERSION=$(python3 -c "
import re
m = re.search(r'APP_VERSION\s*=\s*[\"\\']([^\"\\']+)', open('ui/main_window.py').read())
print(m.group(1) if m else 'unknown')
" 2>/dev/null || echo "unknown")
DEB_NAME="notepadpq_${APP_VERSION}_amd64.deb"
info "Versione: ${APP_VERSION}  →  dist/${DEB_NAME}"

# ── 1. Pacchetti vendor (pip-only) ────────────────────────────────────────────
step "Pacchetti vendor"
VENDOR_DIR="${ROOT}/_vendor"

if [[ "${SKIP_VENDOR}" = false ]]; then
    rm -rf "${VENDOR_DIR}"
    mkdir -p "${VENDOR_DIR}"
    pip3 install --quiet --no-compile --target "${VENDOR_DIR}" \
        "PyQt6-QScintilla>=2.13" \
        "pyspellchecker>=0.7"    \
        "mammoth>=0.11"          \
        "htmldocx>=0.0.6"        \
        "PyGithub>=1.55"         \
        "python-gitlab>=3.0"     \
        "pypandoc>=1.8"
    find "${VENDOR_DIR}" -type d -name "__pycache__"  -exec rm -rf {} + 2>/dev/null || true
    find "${VENDOR_DIR}" -type d -name "*.dist-info"  -exec rm -rf {} + 2>/dev/null || true
    find "${VENDOR_DIR}" -type d -name "*.data"       -exec rm -rf {} + 2>/dev/null || true
    find "${VENDOR_DIR}" -name "*.pyc"                -delete 2>/dev/null || true
    ok "Vendor installato: $(du -sh "${VENDOR_DIR}" | cut -f1)"
else
    [[ -d "${VENDOR_DIR}" ]] \
        || err "_vendor/ non trovato. Rimuovi --skip-vendor per crearlo."
    info "Vendor saltato (--skip-vendor)."
fi

# ── 2. Staging directory ──────────────────────────────────────────────────────
step "Assembla staging directory"
STAGING="${ROOT}/dist/staging"
APP="${STAGING}/opt/notepadpq"

rm -rf "${STAGING}"
mkdir -p "${APP}"

rsync -a \
    --exclude='.git'            \
    --exclude='.github'         \
    --exclude='packaging'       \
    --exclude='windowsbuild'    \
    --exclude='immagini'        \
    --exclude='tests'           \
    --exclude='dist'            \
    --exclude='build'           \
    --exclude='.venv*'          \
    --exclude='_vendor'         \
    --exclude='__pycache__'     \
    --exclude='*.pyc'           \
    --exclude='*.spec'          \
    --exclude='versiona.sh'     \
    --exclude='setup.sh'        \
    --exclude='test.sh'         \
    --exclude='port-to-gtk4.md' \
    --exclude='CLAUDE.md'       \
    --exclude='README.md'       \
    . "${APP}/"

cp -r "${VENDOR_DIR}" "${APP}/_vendor"
find "${APP}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# ── Launcher ──────────────────────────────────────────────────────────────────
install -d "${STAGING}/usr/bin"
cat > "${STAGING}/usr/bin/notepadpq" << 'LAUNCHER'
#!/bin/bash
export PYTHONPATH="/opt/notepadpq/_vendor${PYTHONPATH:+:${PYTHONPATH}}"
exec python3 /opt/notepadpq/main.py "$@"
LAUNCHER
chmod 755 "${STAGING}/usr/bin/notepadpq"

# ── Desktop, metainfo, icone, licenza ─────────────────────────────────────────
install -Dm644 data/notepadpq.desktop \
    "${STAGING}/usr/share/applications/io.github.buzzqw.NotePadPQ.desktop"

install -Dm644 data/io.github.buzzqw.NotePadPQ.metainfo.xml \
    "${STAGING}/usr/share/metainfo/io.github.buzzqw.NotePadPQ.metainfo.xml"

for SIZE in 16 32 48 64 128 256; do
    SRC="icons/NotePadPQ_${SIZE}.png"
    DST="${STAGING}/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps/notepadpq.png"
    [ -f "${SRC}" ] && install -Dm644 "${SRC}" "${DST}"
done
install -Dm644 icons/NotePadPQ_256.png "${STAGING}/usr/share/pixmaps/notepadpq.png"

install -Dm644 "EUPL-1.2 EN.txt" "${STAGING}/usr/share/doc/notepadpq/copyright"

ok "Staging pronto: $(du -sh "${STAGING}" | cut -f1)"

# ── 3. DEBIAN/control e script ────────────────────────────────────────────────
step "Genera DEBIAN/control"

INSTALLED_KB=$(
    { du -sk "${STAGING}/opt" 2>/dev/null
      du -sk "${STAGING}/usr" 2>/dev/null; } \
    | awk '{s+=$1} END{print s}'
)

install -d "${STAGING}/DEBIAN"
cat > "${STAGING}/DEBIAN/control" << EOF
Package: notepadpq
Version: ${APP_VERSION}
Architecture: amd64
Maintainer: buzzqw <azanzani@gmail.com>
Installed-Size: ${INSTALLED_KB}
Depends: python3 (>= 3.10),
 python3-pyqt6 (>= 6.0),
 python3-pyqt6.qtwebengine,
 python3-chardet,
 python3-markdown,
 python3-docutils,
 python3-keyring,
 python3-cryptography,
 python3-pygments,
 python3-psutil
Recommends: python3-matplotlib,
 python3-sympy,
 python3-openpyxl,
 python3-xlrd,
 python3-odf,
 python3-paramiko,
 pandoc
Suggests: python3-pymupdf
Homepage: https://github.com/buzzqw/NotePadPQ
Description: Advanced text editor with syntax highlighting, LaTeX support and plugins
 NotePadPQ is a modern, cross-platform text editor built with Python 3,
 PyQt6 and QScintilla. Inspired by Notepad++ but runs natively on Linux,
 Windows and macOS without Wine or emulation layers.
 .
 Features: syntax highlighting for 40+ languages, full LaTeX suite with
 autocomplete and SyncTeX, LSP client, split view, command palette,
 Markdown and RST live preview, spell checker, integrated build system,
 plugin architecture with AI assistant, PDF viewer, hex viewer,
 spreadsheet, rich text editor, Git integration, and more.
EOF

cat > "${STAGING}/DEBIAN/postinst" << 'POSTINST'
#!/bin/bash
set -e
case "$1" in
    configure)
        gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
        update-desktop-database -q /usr/share/applications 2>/dev/null || true
        ;;
esac
POSTINST
chmod 755 "${STAGING}/DEBIAN/postinst"

cat > "${STAGING}/DEBIAN/postrm" << 'POSTRM'
#!/bin/bash
set -e
case "$1" in
    remove|purge)
        gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
        update-desktop-database -q /usr/share/applications 2>/dev/null || true
        ;;
esac
POSTRM
chmod 755 "${STAGING}/DEBIAN/postrm"

ok "DEBIAN/control generato (${INSTALLED_KB} KiB installati)"

# ── 4. Build .deb ─────────────────────────────────────────────────────────────
step "Build .deb"
OUTPUT="${ROOT}/dist/${DEB_NAME}"
fakeroot dpkg-deb --build --root-owner-group "${STAGING}" "${OUTPUT}"

echo ""
echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}  .deb creato con successo!${RESET}"
echo -e "${BOLD}  File: ${OUTPUT}${RESET}"
echo -e "  Dimensione: $(du -sh "${OUTPUT}" | cut -f1)"
echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════${RESET}"
echo ""

dpkg-deb --info "${OUTPUT}"

info "Per installare: sudo dpkg -i ${OUTPUT} && sudo apt-get install -f"

#!/bin/bash
# make-appdir.sh — Assembla l'AppDir da usare con appimagetool.
# Deve essere eseguito dalla root del progetto dopo "pyinstaller notepadpq.spec".
#
# Input:  dist/notepadpq/   (output --onedir di PyInstaller)
# Output: dist/notepadpq.AppDir/

set -euo pipefail

SRC="dist/notepadpq"
APPDIR="dist/notepadpq.AppDir"

if [[ ! -d "$SRC" ]]; then
    echo "ERRORE: $SRC non trovato. Esegui prima PyInstaller." >&2
    exit 1
fi

echo "=== Creazione AppDir in ${APPDIR} ==="

rm -rf "${APPDIR}"
mkdir -p "${APPDIR}/usr/share/icons/hicolor/"{16x16,32x32,48x48,64x64,128x128,256x256}"/apps"

# ── Bundle PyInstaller ────────────────────────────────────────────────────────
cp -r "${SRC}/." "${APPDIR}/"

# ── Desktop entry ─────────────────────────────────────────────────────────────
# appimagetool cerca il .desktop nella root dell'AppDir
cp data/notepadpq.desktop "${APPDIR}/notepadpq.desktop"

# ── Icone ────────────────────────────────────────────────────────────────────
# Icona root (usata da appimagetool per il metadata dell'AppImage)
cp icons/NotePadPQ_256.png "${APPDIR}/notepadpq.png"

for size in 16 32 48 64 128 256; do
    src="icons/NotePadPQ_${size}.png"
    [[ -f "$src" ]] && cp "$src" \
        "${APPDIR}/usr/share/icons/hicolor/${size}x${size}/apps/notepadpq.png"
done

# ── AppRun ────────────────────────────────────────────────────────────────────
# Punto d'ingresso invocato direttamente dall'AppImage.
# Imposta LD_LIBRARY_PATH e variabili Qt, poi lancia il binario PyInstaller.
cat > "${APPDIR}/AppRun" << 'APPRUN'
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"

# PyInstaller 6+ puts internal files in _internal/; older builds use root.
if [[ -d "${HERE}/_internal" ]]; then
    INT="${HERE}/_internal"
else
    INT="${HERE}"
fi

# Salviamo il LD_LIBRARY_PATH originale PRIMA di modificarlo.
# Python lo usa (via core.external_open) per ripristinare l'ambiente pulito
# nei sottoprocessi di sistema (xelatex, evince, browser, file manager…).
export APPIMAGE_ORIG_LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"

# Solo le librerie Qt vanno aggiunte esplicitamente; non preporre INT stesso
# per non mascherare libGL/libEGL di sistema con eventuali versioni bundled.
export LD_LIBRARY_PATH="${INT}/PyQt6/Qt6/lib:${LD_LIBRARY_PATH:-}"

# Qt platform plugins
export QT_QPA_PLATFORM_PLUGIN_PATH="${INT}/PyQt6/Qt6/plugins/platforms"
export QT_PLUGIN_PATH="${INT}/PyQt6/Qt6/plugins"

# WebEngine: percorso esatto dell'eseguibile QtWebEngineProcess
export QTWEBENGINEPROCESS_PATH="${INT}/PyQt6/Qt6/libexec/QtWebEngineProcess"

# Runtime dir scrivibile per WebEngine (usa /tmp se XDG non è impostato)
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/notepadpq-rt-${UID}}"
mkdir -p "${XDG_RUNTIME_DIR}"

# --no-sandbox: necessario in AppImage dove il namespace sandbox di Chromium
# non è disponibile. GPU acceleration rimane attiva.
# Per sistemi senza driver GL (VM, driver legacy): LIBGL_ALWAYS_SOFTWARE=1 ./NotePadPQ.AppImage
export QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS:-} --no-sandbox"

exec "${HERE}/notepadpq" "$@"
APPRUN
chmod +x "${APPDIR}/AppRun"

echo "=== AppDir pronto: ${APPDIR} ==="
echo "    Dimensione: $(du -sh "${APPDIR}" | cut -f1)"

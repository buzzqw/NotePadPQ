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

# Librerie bundled
export LD_LIBRARY_PATH="${HERE}:${HERE}/PyQt6/Qt6/lib:${LD_LIBRARY_PATH:-}"

# Qt platform plugins
export QT_QPA_PLATFORM_PLUGIN_PATH="${HERE}/PyQt6/Qt6/plugins/platforms"
export QT_PLUGIN_PATH="${HERE}/PyQt6/Qt6/plugins"

# WebEngine: directory dove risiede QtWebEngineProcess (stesso bundle)
export QTWEBENGINEPROCESS_PATH="${HERE}/PyQt6/Qt6/libexec/QtWebEngineProcess"

# Runtime dir scrivibile per WebEngine (usa /tmp se XDG non è impostato)
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/notepadpq-rt-${UID}}"
mkdir -p "${XDG_RUNTIME_DIR}"

exec "${HERE}/notepadpq" "$@"
APPRUN
chmod +x "${APPDIR}/AppRun"

echo "=== AppDir pronto: ${APPDIR} ==="
echo "    Dimensione: $(du -sh "${APPDIR}" | cut -f1)"

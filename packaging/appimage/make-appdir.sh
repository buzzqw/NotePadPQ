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

# Impedisce a GIO di caricare moduli di sistema (es. libgvfsdbus.so) che
# potrebbero dipendere da simboli GLib non presenti nella versione di sistema
# (es. g_task_set_static_name richiede GLib >= 2.76).
# Usiamo una directory vuota dentro l'AppDir così GIO non trova nessun modulo.
export GIO_MODULE_DIR="${HERE}/gio-modules"
mkdir -p "${GIO_MODULE_DIR}"

# Qt platform plugins
export QT_QPA_PLATFORM_PLUGIN_PATH="${INT}/PyQt6/Qt6/plugins/platforms"
export QT_PLUGIN_PATH="${INT}/PyQt6/Qt6/plugins"

# WebEngine: percorso esatto dell'eseguibile QtWebEngineProcess
export QTWEBENGINEPROCESS_PATH="${INT}/PyQt6/Qt6/libexec/QtWebEngineProcess"

# Runtime dir scrivibile per WebEngine (usa /tmp se XDG non è impostato)
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/notepadpq-rt-${UID}}"
mkdir -p "${XDG_RUNTIME_DIR}"

# --no-sandbox: necessario in AppImage dove il namespace sandbox di Chromium
# non è disponibile. GPU acceleration rimane attiva se la GPU funziona.
export QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS:-} --no-sandbox"

# Auto-detect: se GLX non ha FBConfig hardware disponibili, attiva il renderer
# software Mesa (llvmpipe). Permette a WebEngine (terminale, richeditor, ecc.)
# di funzionare anche su VM e macchine senza driver GL proprietari.
# L'utente può forzare il comportamento con LIBGL_ALWAYS_SOFTWARE=0 o =1.
if [[ -z "${LIBGL_ALWAYS_SOFTWARE+x}" && -n "${DISPLAY:-}" ]]; then
    _glx_ok=0
    if command -v glxinfo >/dev/null 2>&1; then
        glxinfo >/dev/null 2>&1 && _glx_ok=1
    else
        # Fallback: testa direttamente con python3 di sistema se disponibile
        python3 - <<'PYGLX' 2>/dev/null && _glx_ok=1
import ctypes, ctypes.util, sys
try:
    x11 = ctypes.CDLL(ctypes.util.find_library('X11') or 'libX11.so.6')
    gl  = ctypes.CDLL(ctypes.util.find_library('GL')  or 'libGL.so.1')
    x11.XOpenDisplay.restype = ctypes.c_void_p
    dpy = x11.XOpenDisplay(None)
    if not dpy: sys.exit(1)
    gl.glXQueryExtension.restype = ctypes.c_int
    err = ctypes.c_int(); ev = ctypes.c_int()
    if not gl.glXQueryExtension(ctypes.c_void_p(dpy), ctypes.byref(err), ctypes.byref(ev)): sys.exit(1)
    gl.glXChooseFBConfig.restype = ctypes.c_void_p
    n = ctypes.c_int(0)
    attrs = (ctypes.c_int * 7)(0x8010,1, 0x8011,1, 8,1, 0)
    gl.glXChooseFBConfig(ctypes.c_void_p(dpy), 0, attrs, ctypes.byref(n))
    sys.exit(0 if n.value > 0 else 1)
except: sys.exit(1)
PYGLX
    fi
    if [[ "${_glx_ok}" = "0" ]]; then
        export LIBGL_ALWAYS_SOFTWARE=1
    fi
fi

# Quando non c'è GPU hardware, Chromium (WebEngine) deve usare il suo renderer
# software interno (SwiftShader) altrimenti la pagina rimane nera.
# --disable-gpu: disabilita il renderer OpenGL hardware di Chromium
# --use-gl=swiftshader: forza SwiftShader (software GL) per il compositing
if [[ "${LIBGL_ALWAYS_SOFTWARE:-0}" = "1" ]]; then
    export QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS} --disable-gpu --use-gl=swiftshader"
fi

exec "${HERE}/notepadpq" "$@"
APPRUN
chmod +x "${APPDIR}/AppRun"

echo "=== AppDir pronto: ${APPDIR} ==="
echo "    Dimensione: $(du -sh "${APPDIR}" | cut -f1)"

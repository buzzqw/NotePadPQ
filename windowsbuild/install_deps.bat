@echo off
REM ============================================================
REM  install_deps.bat — Installa le dipendenze per il build
REM  NotePadPQ Windows Build System
REM ============================================================
REM  Uso:
REM    install_deps.bat          -> installa dipendenze FULL (tutto)
REM    install_deps.bat lite     -> installa solo dipendenze CORE
REM ============================================================

setlocal EnableDelayedExpansion

set MODE=full
if /i "%~1"=="lite" set MODE=lite

echo.
echo ============================================================
echo  NotePadPQ - Installazione dipendenze Windows  [%MODE%]
echo ============================================================
echo.

REM ── Controlla Python ─────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] Python non trovato nel PATH.
    echo          Installa Python 3.10+ da https://www.python.org/downloads/
    echo          e assicurati di spuntare "Add Python to PATH".
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version') do set PYVER=%%i
echo [OK] %PYVER%

REM ── Aggiorna pip ─────────────────────────────────────────────
echo.
echo [1/4] Aggiorno pip...
python -m pip install --upgrade pip
if errorlevel 1 goto :error

REM ── Installa PyInstaller ──────────────────────────────────────
echo.
echo [2/4] Installo PyInstaller...
python -m pip install --upgrade pyinstaller
if errorlevel 1 goto :error

REM ── Dipendenze CORE (sempre installate) ──────────────────────
echo.
echo [3/4] Installo dipendenze CORE...
python -m pip install ^
    "PyQt6>=6.0.0" ^
    "PyQt6-QScintilla>=2.13.0" ^
    "PyQt6-WebEngine>=6.0.0" ^
    "chardet>=4.0.0" ^
    "pygments>=2.10.0" ^
    "psutil>=5.9.0"
if errorlevel 1 goto :error

REM ── Dipendenze OPZIONALI (solo versione full) ─────────────────
if /i "%MODE%"=="full" (
    echo.
    echo [4/4] Installo dipendenze OPZIONALI ^(versione Full^)...
    python -m pip install ^
        "pymupdf>=1.20.0" ^
        "markdown>=3.3.0" ^
        "docutils>=0.18" ^
        "matplotlib>=3.5.0" ^
        "sympy>=1.10" ^
        "mammoth>=0.11.0" ^
        "htmldocx>=0.0.6" ^
        "pypandoc>=1.8.0" ^
        "pyspellchecker>=0.7.0" ^
        "openpyxl>=3.1.0" ^
        "xlrd>=2.0.1" ^
        "odfpy>=1.4.1" ^
        "PyGithub>=1.55" ^
        "python-gitlab>=3.0.0" ^
        "keyring>=23.5.0" ^
        "cryptography>=41.0.0"
    if errorlevel 1 goto :error
) else (
    echo.
    echo [4/4] Modalita' Lite: dipendenze opzionali saltate.
)

echo.
echo ============================================================
echo  Installazione completata con successo!
echo ============================================================
echo.
goto :eof

:error
echo.
echo [ERRORE] Installazione fallita. Controlla la connessione
echo          o i permessi e riprova.
pause
exit /b 1

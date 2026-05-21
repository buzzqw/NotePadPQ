@echo off
REM ============================================================
REM  build.bat — Build principale NotePadPQ per Windows
REM  Compila sia la versione Full che la versione Lite
REM ============================================================
REM  Uso:
REM    build.bat           -> compila entrambe le versioni
REM    build.bat full      -> compila solo versione Full
REM    build.bat lite      -> compila solo versione Lite
REM    build.bat installer -> compila entrambe + crea installer
REM ============================================================

setlocal EnableDelayedExpansion

REM ── Leggi versione da main.py ─────────────────────────────────
set VERSION=0.9.10
for /f "tokens=2 delims==''" %%i in ('python -c "import re,sys; m=re.search(r\"setApplicationVersion\('(.+?)'\)\", open('../main.py').read()); print(m.group(1) if m else '0.0.0')" 2^>nul') do set VERSION=%%i

set BUILD_MODE=both
if /i "%~1"=="full"      set BUILD_MODE=full
if /i "%~1"=="lite"      set BUILD_MODE=lite
if /i "%~1"=="installer" set BUILD_MODE=installer

REM ── Posizionati nella cartella windowsbuild ───────────────────
cd /d "%~dp0"

echo.
echo ============================================================
echo  NotePadPQ v%VERSION% — Build Windows
echo  Modalita': %BUILD_MODE%
echo  Data: %DATE% %TIME%
echo ============================================================
echo.

REM ── Controlla Python e PyInstaller ───────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] Python non trovato nel PATH.
    echo          Esegui prima: install_deps.bat
    pause & exit /b 1
)

pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] PyInstaller non trovato.
    echo          Esegui prima: install_deps.bat
    pause & exit /b 1
)

REM ── Pulizia cartelle precedenti ──────────────────────────────
echo [INFO] Pulizia build precedenti...
if exist "..\dist\NotePadPQ_Full" rmdir /s /q "..\dist\NotePadPQ_Full"
if exist "..\dist\NotePadPQ_Lite" rmdir /s /q "..\dist\NotePadPQ_Lite"
if exist "..\build"               rmdir /s /q "..\build"

REM ── Genera version_info.txt aggiornato ───────────────────────
echo [INFO] Aggiorno version_info.txt per v%VERSION%...
python -c ^
    "import re; ^
     content = open('version_info.txt','r',encoding='utf-8').read(); ^
     ver = '%VERSION%'.split('.'); ^
     ver = [int(x) for x in ver]; ^
     while len(ver) < 4: ver.append(0); ^
     ver_str = str(tuple(ver)); ^
     content = re.sub(r'filevers=\([\d, ]+\)', 'filevers='+ver_str, content); ^
     content = re.sub(r'prodvers=\([\d, ]+\)', 'prodvers='+ver_str, content); ^
     content = re.sub(r\"'FileVersion',\s+'[\d.]+'\", \"'FileVersion', '%VERSION%.0'\", content); ^
     content = re.sub(r\"'ProductVersion',\s+'[\d.]+'\", \"'ProductVersion', '%VERSION%'\", content); ^
     open('version_info.txt','w',encoding='utf-8').write(content)" 2>nul

REM ============================================================
REM  BUILD FULL
REM ============================================================
if /i "%BUILD_MODE%"=="full" goto :build_full
if /i "%BUILD_MODE%"=="both" goto :build_full
if /i "%BUILD_MODE%"=="installer" goto :build_full
goto :skip_full

:build_full
echo.
echo ============================================================
echo  [1/2] Build FULL (con tutte le dipendenze opzionali)
echo ============================================================
echo.

pyinstaller --clean --noconfirm notepadpq_full.spec
if errorlevel 1 (
    echo.
    echo [ERRORE] Build FULL fallita!
    goto :build_failed
)

echo.
echo [OK] Build Full completata: dist\NotePadPQ_Full\

REM Crea ZIP della versione Full
if exist "..\dist\NotePadPQ_Full" (
    echo [INFO] Creo archivio ZIP...
    powershell -Command ^
        "Compress-Archive -Path '..\dist\NotePadPQ_Full\*' ^
         -DestinationPath '..\dist\NotePadPQ_v%VERSION%_Full_Windows.zip' ^
         -Force" 2>nul
    if not errorlevel 1 (
        echo [OK] Archivio: dist\NotePadPQ_v%VERSION%_Full_Windows.zip
    )
)

:skip_full

REM ============================================================
REM  BUILD LITE
REM ============================================================
if /i "%BUILD_MODE%"=="lite" goto :build_lite
if /i "%BUILD_MODE%"=="both" goto :build_lite
if /i "%BUILD_MODE%"=="installer" goto :build_lite
goto :skip_lite

:build_lite
echo.
echo ============================================================
echo  [2/2] Build LITE (solo dipendenze core)
echo ============================================================
echo.

pyinstaller --clean --noconfirm notepadpq_lite.spec
if errorlevel 1 (
    echo.
    echo [ERRORE] Build LITE fallita!
    goto :build_failed
)

echo.
echo [OK] Build Lite completata: dist\NotePadPQ_Lite\

REM Crea ZIP della versione Lite
if exist "..\dist\NotePadPQ_Lite" (
    echo [INFO] Creo archivio ZIP...
    powershell -Command ^
        "Compress-Archive -Path '..\dist\NotePadPQ_Lite\*' ^
         -DestinationPath '..\dist\NotePadPQ_v%VERSION%_Lite_Windows.zip' ^
         -Force" 2>nul
    if not errorlevel 1 (
        echo [OK] Archivio: dist\NotePadPQ_v%VERSION%_Lite_Windows.zip
    )
)

:skip_lite

REM ============================================================
REM  INSTALLER (opzionale, richiede Inno Setup installato)
REM ============================================================
if /i NOT "%BUILD_MODE%"=="installer" goto :summary

echo.
echo ============================================================
echo  [3/3] Creazione installer con Inno Setup
echo ============================================================
echo.

set ISCC=
for %%p in (
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    "C:\Program Files\Inno Setup 6\ISCC.exe"
    "C:\Program Files (x86)\Inno Setup 5\ISCC.exe"
) do (
    if exist %%p set ISCC=%%p
)

if "%ISCC%"=="" (
    echo [AVVISO] Inno Setup non trovato. Salta creazione installer.
    echo          Installa da: https://jrsoftware.org/isdl.php
    goto :summary
)

%ISCC% /DMyAppVersion="%VERSION%" create_installer.iss
if errorlevel 1 (
    echo [ERRORE] Creazione installer fallita.
) else (
    echo [OK] Installer creato in dist\
)

:summary
echo.
echo ============================================================
echo  BUILD COMPLETATA
echo ============================================================
echo.
echo  Versione  : %VERSION%
echo  Cartella  : dist\
echo.
if exist "..\dist\NotePadPQ_Full" (
    echo  [Full]  dist\NotePadPQ_Full\NotePadPQ.exe
)
if exist "..\dist\NotePadPQ_Lite" (
    echo  [Lite]  dist\NotePadPQ_Lite\NotePadPQ.exe
)
if exist "..\dist\NotePadPQ_v%VERSION%_Full_Windows.zip" (
    echo  [ZIP]   dist\NotePadPQ_v%VERSION%_Full_Windows.zip
)
if exist "..\dist\NotePadPQ_v%VERSION%_Lite_Windows.zip" (
    echo  [ZIP]   dist\NotePadPQ_v%VERSION%_Lite_Windows.zip
)
echo.
echo ============================================================
pause
exit /b 0

:build_failed
echo.
echo  Controlla i messaggi di errore sopra.
echo  Suggerimento: esegui 'install_deps.bat' per assicurarti
echo  che tutte le dipendenze siano installate.
echo.
pause
exit /b 1

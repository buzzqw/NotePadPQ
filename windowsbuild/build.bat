@echo off
REM ============================================================
REM  build.bat — Build principale NotePadPQ per Windows
REM ============================================================
REM  Uso:
REM    build.bat                 -> compila entrambe (cartella)
REM    build.bat full            -> solo Full (cartella)
REM    build.bat lite            -> solo Lite (cartella)
REM    build.bat both            -> entrambe (cartella)
REM    build.bat full --onefile  -> Full come .exe singolo
REM    build.bat lite --onefile  -> Lite come .exe singolo
REM    build.bat both --onefile  -> entrambe come .exe singolo
REM    build.bat installer       -> entrambe + Inno Setup
REM
REM  NOTA sulla modalita' onefile: produce un singolo NotePadPQ.exe
REM  che estrae i file in %TEMP% ad ogni avvio (avvio piu' lento).
REM  Per un editor e' consigliata la modalita' cartella (default).
REM ============================================================

setlocal EnableDelayedExpansion

REM ── Posizionati nella cartella windowsbuild ───────────────────
cd /d "%~dp0"

REM ── Leggi versione da main.py ─────────────────────────────────
set VERSION=0.9.10
for /f "usebackq delims=" %%i in (`python -c "import re; m=re.search(r'setApplicationVersion\(\"(.+?)\"\)', open('../main.py').read()); print(m.group(1) if m else '0.0.0')" 2^>nul`) do set VERSION=%%i

REM ── Parsing argomenti CLI ─────────────────────────────────────
set BUILD_MODE=
set NOTEPADPQ_ONEFILE=0
set ONEFILE_LABEL=cartella

if /i "%~1"=="full"      set BUILD_MODE=full
if /i "%~1"=="lite"      set BUILD_MODE=lite
if /i "%~1"=="installer" set BUILD_MODE=installer
if /i "%~1"=="both"      set BUILD_MODE=both

REM Controlla il flag --onefile in qualsiasi posizione
for %%a in (%*) do (
    if /i "%%a"=="--onefile" (
        set NOTEPADPQ_ONEFILE=1
        set ONEFILE_LABEL=onefile
    )
)

echo.
echo ============================================================
echo  NotePadPQ v%VERSION% — Build Windows
echo  Data: %DATE% %TIME%
echo ============================================================
echo.

REM ── Prompt interattivo variante (solo se non passata da CLI) ──
if not "%BUILD_MODE%"=="" goto :skip_prompt_variant
echo  Quale variante vuoi compilare?
echo    1) full      - Solo versione Full (default)
echo    2) both      - Full + Lite
echo    3) lite      - Solo versione Lite
echo    4) installer - Full + Lite + Inno Setup
echo.
set /p _choice="  Scelta [1]: "
if "%_choice%"==""  set BUILD_MODE=full
if "%_choice%"=="1" set BUILD_MODE=full
if "%_choice%"=="2" set BUILD_MODE=both
if "%_choice%"=="3" set BUILD_MODE=lite
if "%_choice%"=="4" set BUILD_MODE=installer
if /i "%_choice%"=="both"      set BUILD_MODE=both
if /i "%_choice%"=="full"      set BUILD_MODE=full
if /i "%_choice%"=="lite"      set BUILD_MODE=lite
if /i "%_choice%"=="installer" set BUILD_MODE=installer
if "%BUILD_MODE%"=="" set BUILD_MODE=full
echo.
:skip_prompt_variant

REM ── Prompt interattivo onefile (solo se non passato da CLI) ───
if "%NOTEPADPQ_ONEFILE%"=="1" goto :skip_prompt_onefile
set /p _onefile="  Modalita' onefile (singolo .exe, avvio piu' lento)? [s/N]: "
if /i "%_onefile%"=="s" (
    set NOTEPADPQ_ONEFILE=1
    set ONEFILE_LABEL=onefile
)
echo.
:skip_prompt_onefile

echo  Variante  : %BUILD_MODE%
echo  Modalita' : %ONEFILE_LABEL%
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
if exist "dist\NotePadPQ_Full"    rmdir /s /q "dist\NotePadPQ_Full"
if exist "dist\NotePadPQ_Lite"    rmdir /s /q "dist\NotePadPQ_Lite"
if exist "..\build"               rmdir /s /q "..\build"
if exist "build"                  rmdir /s /q "build"

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
if /i "%BUILD_MODE%"=="full"      goto :build_full
if /i "%BUILD_MODE%"=="both"      goto :build_full
if /i "%BUILD_MODE%"=="installer" goto :build_full
goto :skip_full

:build_full
echo.
echo ============================================================
if "%NOTEPADPQ_ONEFILE%"=="1" (
    echo  [1/2] Build FULL - onefile ^(singolo .exe^)
) else (
    echo  [1/2] Build FULL ^(con tutte le dipendenze opzionali^)
)
echo ============================================================
echo.

set NOTEPADPQ_ONEFILE=%NOTEPADPQ_ONEFILE%
pyinstaller --clean --noconfirm notepadpq_full.spec
if errorlevel 1 (
    echo.
    echo [ERRORE] Build FULL fallita!
    goto :build_failed
)

echo.
if "%NOTEPADPQ_ONEFILE%"=="1" (
    REM Modalita' onefile: rinomina il .exe per evitare sovrascrittura con Lite
    if exist "dist\NotePadPQ.exe" (
        move /y "dist\NotePadPQ.exe" "dist\NotePadPQ_Full_Onefile.exe" >nul
        echo [OK] Build Full onefile completata: dist\NotePadPQ_Full_Onefile.exe
        powershell -Command "Compress-Archive -Path 'dist\NotePadPQ_Full_Onefile.exe' -DestinationPath 'dist\NotePadPQ_v%VERSION%_Full_Windows_Onefile.zip' -Force" 2>nul
        if not errorlevel 1 echo [OK] Archivio: dist\NotePadPQ_v%VERSION%_Full_Windows_Onefile.zip
    ) else (
        echo [OK] Build Full onefile completata.
    )
) else (
    echo [OK] Build Full completata: dist\NotePadPQ_Full\
    REM Crea ZIP della versione Full
    if exist "dist\NotePadPQ_Full" (
        echo [INFO] Creo archivio ZIP...
        powershell -Command "Compress-Archive -Path 'dist\NotePadPQ_Full\*' -DestinationPath 'dist\NotePadPQ_v%VERSION%_Full_Windows.zip' -Force" 2>nul
        if not errorlevel 1 echo [OK] Archivio: dist\NotePadPQ_v%VERSION%_Full_Windows.zip
    )
)

:skip_full

REM ============================================================
REM  BUILD LITE
REM ============================================================
if /i "%BUILD_MODE%"=="lite"      goto :build_lite
if /i "%BUILD_MODE%"=="both"      goto :build_lite
if /i "%BUILD_MODE%"=="installer" goto :build_lite
goto :skip_lite

:build_lite
echo.
echo ============================================================
if "%NOTEPADPQ_ONEFILE%"=="1" (
    echo  [2/2] Build LITE - onefile ^(singolo .exe^)
) else (
    echo  [2/2] Build LITE ^(solo dipendenze core^)
)
echo ============================================================
echo.

pyinstaller --clean --noconfirm notepadpq_lite.spec
if errorlevel 1 (
    echo.
    echo [ERRORE] Build LITE fallita!
    goto :build_failed
)

echo.
if "%NOTEPADPQ_ONEFILE%"=="1" (
    if exist "dist\NotePadPQ.exe" (
        move /y "dist\NotePadPQ.exe" "dist\NotePadPQ_Lite_Onefile.exe" >nul
        echo [OK] Build Lite onefile completata: dist\NotePadPQ_Lite_Onefile.exe
        powershell -Command "Compress-Archive -Path 'dist\NotePadPQ_Lite_Onefile.exe' -DestinationPath 'dist\NotePadPQ_v%VERSION%_Lite_Windows_Onefile.zip' -Force" 2>nul
        if not errorlevel 1 echo [OK] Archivio: dist\NotePadPQ_v%VERSION%_Lite_Windows_Onefile.zip
    ) else (
        echo [OK] Build Lite onefile completata.
    )
) else (
    echo [OK] Build Lite completata: dist\NotePadPQ_Lite\
    if exist "dist\NotePadPQ_Lite" (
        echo [INFO] Creo archivio ZIP...
        powershell -Command "Compress-Archive -Path 'dist\NotePadPQ_Lite\*' -DestinationPath 'dist\NotePadPQ_v%VERSION%_Lite_Windows.zip' -Force" 2>nul
        if not errorlevel 1 echo [OK] Archivio: dist\NotePadPQ_v%VERSION%_Lite_Windows.zip
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
echo  Modalita' : %ONEFILE_LABEL%
echo  Cartella  : dist\
echo.
if "%NOTEPADPQ_ONEFILE%"=="1" (
    if exist "dist\NotePadPQ_Full_Onefile.exe"  echo  [Full]  dist\NotePadPQ_Full_Onefile.exe
    if exist "dist\NotePadPQ_Lite_Onefile.exe"  echo  [Lite]  dist\NotePadPQ_Lite_Onefile.exe
    if exist "dist\NotePadPQ_v%VERSION%_Full_Windows_Onefile.zip" echo  [ZIP]   dist\NotePadPQ_v%VERSION%_Full_Windows_Onefile.zip
    if exist "dist\NotePadPQ_v%VERSION%_Lite_Windows_Onefile.zip" echo  [ZIP]   dist\NotePadPQ_v%VERSION%_Lite_Windows_Onefile.zip
) else (
    if exist "dist\NotePadPQ_Full" echo  [Full]  dist\NotePadPQ_Full\NotePadPQ.exe
    if exist "dist\NotePadPQ_Lite" echo  [Lite]  dist\NotePadPQ_Lite\NotePadPQ.exe
    if exist "dist\NotePadPQ_v%VERSION%_Full_Windows.zip" echo  [ZIP]   dist\NotePadPQ_v%VERSION%_Full_Windows.zip
    if exist "dist\NotePadPQ_v%VERSION%_Lite_Windows.zip" echo  [ZIP]   dist\NotePadPQ_v%VERSION%_Lite_Windows.zip
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

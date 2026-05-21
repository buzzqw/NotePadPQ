# notepadpq_lite.spec
# PyInstaller spec — versione LITE (solo dipendenze obbligatorie)
# Generato per NotePadPQ 0.9.10

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ── Dati non-Python da includere ─────────────────────────────────────────────
datas = [
    ('../i18n',    'i18n'),
    ('../icons',   'icons'),
    ('../config',  'config'),
    ('../plugins', 'plugins'),
    ('../core',    'core'),
    ('../editor',  'editor'),
    ('../ui',      'ui'),
]
datas += collect_data_files('pygments')

# ── Import nascosti (solo core obbligatori) ───────────────────────────────────
hiddenimports = (
    collect_submodules('pygments.lexers') +
    collect_submodules('pygments.formatters') +
    collect_submodules('pygments.styles') +
    collect_submodules('PyQt6') +
    [
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebEngineCore',
        'PyQt6.Qsci',
        'chardet',
        'psutil',
        'json',
        'pathlib',
        'threading',
        'subprocess',
    ]
)

# ── Escludi tutte le dipendenze opzionali pesanti ─────────────────────────────
excludes = [
    # Opzionali escluse dalla versione lite
    'fitz',
    'pymupdf',
    'markdown',
    'docutils',
    'matplotlib',
    'sympy',
    'mammoth',
    'htmldocx',
    'pypandoc',
    'openpyxl',
    'xlrd',
    'odf',
    'odfpy',
    'github',
    'gitlab',
    'keyring',
    'cryptography',
    'spellchecker',
    # Librerie standard inutili nell'eseguibile
    'tkinter',
    'unittest',
    'xmlrpc',
    'pydoc',
    'doctest',
    'ftplib',
    'imaplib',
    'nntplib',
    'optparse',
    'poplib',
    'smtplib',
    'telnetlib',
    'turtle',
    'turtledemo',
    'numpy',
    'scipy',
    'pandas',
    'PIL',
    'cv2',
]

a = Analysis(
    ['../main.py'],
    pathex=['..'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['hooks'],
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NotePadPQ',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=['vcruntime140.dll', 'msvcp140.dll', 'python3*.dll'],
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='../icons/NotePadPQ.ico',
    version='version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=['vcruntime140.dll', 'msvcp140.dll'],
    name='NotePadPQ_Lite',
)

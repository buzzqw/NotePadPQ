# notepadpq_full.spec
# PyInstaller spec — versione FULL (tutte le dipendenze opzionali incluse)
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

# ── Import nascosti non rilevati automaticamente ──────────────────────────────
hiddenimports = (
    collect_submodules('pygments.lexers') +
    collect_submodules('pygments.formatters') +
    collect_submodules('pygments.styles') +
    collect_submodules('PyQt6') +
    [
        # Core Qt
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebEngineCore',
        'PyQt6.Qsci',
        # Core obbligatori
        'chardet',
        'psutil',
        # Anteprima e PDF
        'fitz',          # pymupdf
        'markdown',
        'docutils',
        'docutils.parsers.rst',
        'matplotlib',
        'matplotlib.backends.backend_qt5agg',
        'sympy',
        # Rich Text / WYSIWYG
        'mammoth',
        'htmldocx',
        'pypandoc',
        # Spell Checker
        'spellchecker',
        # Spreadsheet
        'openpyxl',
        'xlrd',
        'odf',           # odfpy
        # Git Plugin
        'github',        # PyGithub
        'gitlab',        # python-gitlab
        'keyring',
        'cryptography',
        'cryptography.fernet',
        # html / xml (richiesti da markdown e altri)
        'html',
        'html.parser',
        'html.entities',
        'xml',
        'xml.etree',
        'xml.etree.ElementTree',
        'xml.etree.cElementTree',
        # Miscellanea
        'json',
        'pathlib',
        'threading',
        'subprocess',
    ]
)

# ── Escludi moduli pesanti/inutili per ridurre dimensioni ─────────────────────
excludes = [
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
    name='NotePadPQ_Full',
)

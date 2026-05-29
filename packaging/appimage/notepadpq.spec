# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for NotePadPQ AppImage build.

Build:
    pyinstaller packaging/appimage/notepadpq.spec --noconfirm
Output:
    dist/notepadpq/   (--onedir bundle, then wrapped by make-appdir.sh)
"""

block_cipher = None

# ── Data files bundled into the application ───────────────────────────────────
# Plugins are included as source so plugin_manager can load them dynamically.
# Web assets (Jodit WYSIWYG, xterm.js terminal) are served from a temp dir.
added_datas = [
    ('i18n/*.json',             'i18n'),
    ('icons/*.png',             'icons'),
    ('icons/*.ico',             'icons'),
    ('ui/assets/jodit',         'ui/assets/jodit'),
    ('ui/assets/xterm',         'ui/assets/xterm'),
    ('plugins/*.py',            'plugins'),
    ('plugins/__init__.py',     'plugins'),
    ('MANUAL_EN.md',            '.'),
    ('MANUAL_IT.md',            '.'),
    ('data/notepadpq.desktop',  'data'),
    ('data/io.github.buzzqw.NotePadPQ.metainfo.xml', 'data'),
]

# ── Hidden imports (loaded via importlib or lazy import) ──────────────────────
hidden_imports = [
    # Plugins — discovered at runtime by plugin_manager via importlib
    'plugins.ai_plugin',
    'plugins.base_plugin',
    'plugins.clipboard_history_plugin',
    'plugins.compare_plugin',
    'plugins.db_plugin',
    'plugins.encrypt_plugin',
    'plugins.ftp_browser_plugin',
    'plugins.git_plugin',
    'plugins.hex_viewer_plugin',
    'plugins.pdf_viewer_plugin',
    'plugins.plugin_manager',
    'plugins.richtext_plugin',
    'plugins.search_results_plugin',
    'plugins.spreadsheet_plugin',
    'plugins.terminal_plugin',
    'plugins.websearch_plugin',
    # Core — lazy-imported inside functions
    'chardet',
    'markdown',
    'markdown.extensions',
    'markdown.extensions.fenced_code',
    'markdown.extensions.tables',
    'docutils',
    'docutils.core',
    'docutils.parsers.rst',
    'docutils.writers.html4css1',
    'spellchecker',
    'keyring',
    'keyring.backends',
    'keyring.backends.SecretService',
    'cryptography',
    'cryptography.hazmat.primitives.ciphers.aead',
    'pygments',
    'pygments.lexers',
    'pygments.formatters',
    'pygments.styles',
    'psutil',
    # Optional plugins — imported inside on_load, not at module level
    'openpyxl',
    'xlrd',
    'odf',
    'odf.opendocument',
    'mammoth',
    'htmldocx',
    'github',
    'gitlab',
    # Optional LaTeX/PDF — guarded by try/except at call site
    'fitz',
    'matplotlib',
    'matplotlib.pyplot',
    'matplotlib.backends.backend_agg',
    'sympy',
]

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=added_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={
        'PyQt6': {
            'binaries': True,
            'translations': False,
        },
    },
    runtime_hooks=[],
    excludes=[
        'tkinter', '_tkinter',
        'test', 'unittest',
        'distutils', 'setuptools', 'pkg_resources',
        'PyQt5', 'PyQt4',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='notepadpq',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,   # no terminal window; errors go to stderr only
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='notepadpq',
)

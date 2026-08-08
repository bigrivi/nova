# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Nova Desktop (Linux).

Produces: dist/Nova/ directory with Nova executable

Usage:
    python -m PyInstaller build_desktop_linux.spec
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(os.environ.get("NOVA_PROJECT_ROOT", Path.cwd()))

block_cipher = None

# pywebview loads its platform backend (webview.platforms.gtk on Linux) and
# JS assets dynamically, which static analysis misses. Collect everything so
# mouse interaction / text selection keep working when packaged.
webview_datas, webview_binaries, webview_hidden = collect_all('webview')

a = Analysis(
    ['nova/desktop/entry.py'],
    pathex=[str(ROOT)],
    binaries=webview_binaries,
    datas=[
        (str(ROOT / 'frontend' / 'dist'), 'frontend/dist'),
        *webview_datas,
    ],
    hiddenimports=[
        'nova.server.app',
        'nova.server.chat_service',
        'nova.settings',
        'nova.app.runtime',
        'nova.config.service',
        'nova.db.database',
        'nova.license',
        *webview_hidden,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'PIL',
        'cv2',
        'scipy',
        'PyQt5',
        'PyQt6',
        'PySide2',
        'PySide6',
        'playwright',
        'pyee',
        'pyobjc_core',
        'pyobjc_framework_Cocoa',
        'pyobjc_framework_WebKit',
        'pyobjc_framework_Quartz',
        'pyobjc_framework_Security',
        # TUI-only (not needed by desktop)
        'textual',
        'opentui',
        'nova.cli',
        'nova.opentui_app',
        'tree_sitter_python', 'tree_sitter_javascript',
        'tree_sitter_typescript', 'tree_sitter_json',
        'tree_sitter_bash', 'tree_sitter_markdown',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Nova',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Nova',
)

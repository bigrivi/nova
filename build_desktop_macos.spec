# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Nova Desktop (macOS).

Produces: dist/Nova.app (macOS application bundle)

Usage:
    python -m PyInstaller build_desktop_macos.spec
"""

import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path so nova package is found
ROOT = Path(os.environ.get("NOVA_PROJECT_ROOT", Path.cwd()))
sys.path.insert(0, str(ROOT))

block_cipher = None

a = Analysis(
    ['nova/desktop/entry.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Frontend static build output
        (str(ROOT / 'frontend' / 'dist'), 'frontend/dist'),
    ],
    hiddenimports=[
        # uvicorn + pywebview ship their own hooks, but ensure key nova
        # submodules are found by static analysis.
        'nova.server.app',
        'nova.server.chat_service',
        'nova.settings',
        'nova.app.runtime',
        'nova.config.service',
        'nova.db.database',
        'nova.license',
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

app = BUNDLE(
    coll,
    name='Nova.app',
    icon=None,
    bundle_identifier='ai.nova.desktop',
    info_plist={
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
        'CFBundleName': 'Nova',
        'CFBundleDisplayName': 'Nova',
        'CFBundlePackageType': 'APPL',
        'NSHighResolutionCapable': True,
    },
)

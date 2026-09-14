# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the MedFlow desktop app.

Build:  pyinstaller MedFlow.spec
Result: dist/MedFlow  (Windows: dist/MedFlow.exe)

The web assets and CustomTkinter theme JSONs are bundled as data so the
executable can print charts and render correctly on a clean machine. The
data directory is created beside the executable at runtime, so the
database stays with the installation, never inside the bundle.
"""

import sys
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)
WEB_DIR = ROOT / "app" / "server" / "web"

datas = [
    (str(WEB_DIR), "app/server/web"),
]

# CustomTkinter ships theme JSONs that must be collected explicitly.
import customtkinter
ctk_dir = Path(customtkinter.__file__).parent
for asset in ("assets/themes", "assets/fonts"):
    if (ctk_dir / asset).exists():
        datas.append((str(ctk_dir / asset), f"customtkinter/{asset}"))

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.protocols",
    "customtkinter",
]

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="MedFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # windowed app; no terminal on launch
    icon=None,
)

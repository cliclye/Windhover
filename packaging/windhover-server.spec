# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: builds windhover-server[.exe] for the Tauri sidecar.
# Run from repo root:
#   pyinstaller packaging/windhover-server.spec --noconfirm

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # packaging/
REPO = ROOT.parent

block_cipher = None

datas = [
    (str(REPO / "windhover"), "."),
    (str(REPO / "app" / "dist"), "app/dist"),
    (str(REPO / "app" / "public" / "catalog.json"), "app/public"),
    (str(REPO / "app" / "public" / "windhover-icon.png"), "app/public"),
    (str(REPO / "tools" / "agent_workspace.py"), "tools"),
]

# Optional icon for Windows
icon = None
ico = REPO / "desktop" / "src-tauri" / "icons" / "icon.ico"
if ico.is_file() and sys.platform == "win32":
    icon = str(ico)

a = Analysis(
    [str(ROOT / "server_entry.py")],
    pathex=[str(REPO)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "agent_workspace",
        "http.server",
        "json",
        "urllib",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "transformers", "numpy", "tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
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
    name="windhover-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Windowed on Windows installs; set WINDHOVER_SERVER_CONSOLE=1 in CI for logs.
    console=(
        True
        if sys.platform != "win32"
        or os.environ.get("WINDHOVER_SERVER_CONSOLE", "").lower() in ("1", "true", "yes")
        else False
    ),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Windows one-folder Bridge build.

Build (on Windows):

    uv sync
    uv run pyinstaller KinkajouBridge.spec

Output:

    dist/KinkajouBridge/KinkajouBridge.exe
"""

from __future__ import annotations

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_all, copy_metadata

datas: list = []
binaries: list = []
hiddenimports: list[str] = [
    # Built-in plugins (also registered via entry points / load_builtins)
    "kinkajou_bridge.plugins.bambu",
    "kinkajou_bridge.plugins.bambu.plugin",
    "kinkajou_bridge.plugins.bambu.cloud",
    "kinkajou_bridge.plugins.bambu.mqtt_session",
    "kinkajou_bridge.plugins.bambu.report",
    "kinkajou_bridge.plugins.octoprint",
    "kinkajou_bridge.plugins.octoprint.plugin",
    "kinkajou_bridge.plugins.octoprint.status",
    "kinkajou_bridge.plugins.moonraker",
    "kinkajou_bridge.plugins.moonraker.plugin",
    "kinkajou_bridge.plugins.moonraker.status",
    "kinkajou_bridge.plugins.streamerbot",
    "kinkajou_bridge.plugins.streamerbot.plugin",
    # Uvicorn lazy imports
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
]

for package in ("kinkajou_bridge", "uvicorn", "aiomqtt", "certifi"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

datas += copy_metadata("kinkajou-bridge")

# Attribution for redistributed third-party components (required for several licenses).
datas += [
    ("LICENSE", "."),
    ("THIRD_PARTY_NOTICES.md", "."),
    ("third_party_licenses", "third_party_licenses"),
]

a = Analysis(
    ["src/kinkajou_bridge/cli.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KinkajouBridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # tray app — no console window
    disable_windowed_traceback=False,
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
    name="KinkajouBridge",
)

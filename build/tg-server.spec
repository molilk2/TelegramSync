# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

ROOT = Path.cwd()

readme = ROOT / "README.md"
docs = ROOT / "docs.md"

datas = []
if readme.exists():
    datas.append((str(readme), "."))
if docs.exists():
    datas.append((str(docs), "."))

a = Analysis(
    [str(ROOT / "server_main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
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
    a.binaries,
    a.datas,
    [],
    name="tg-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
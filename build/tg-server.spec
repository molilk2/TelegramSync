# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent.parent
DOC_FILES = []
for name in ("README.md", "docs.md"):
    path = ROOT / name
    if path.exists():
        DOC_FILES.append((str(path), "."))

hiddenimports = sorted(set(
    collect_submodules('telethon')
    + collect_submodules('platformdirs')
    + ['sqlite3']
))

a = Analysis(
    [str(ROOT / 'server_main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=DOC_FILES,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='tg-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

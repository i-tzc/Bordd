# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 规格文件 —— 命令行版（保留控制台，便于查看进度与脚本调用）。

产物：
    Windows : dist/Bordd_cli/Bordd.exe
    macOS   : dist/Bordd_cli/Bordd

同样使用 onedir 模式（原因见 Bordd_gui.spec）：不依赖系统临时目录，
启动更快、兼容性更好。命令行版保留控制台，所以即使出错也能看到报错。

共用的核心逻辑是 ../bordd.py，命令行行为与旧版本完全一致。

构建（在 bordd_dist 目录下执行）：
    python -m PyInstaller Bordd_cli.spec --noconfirm
"""

import os
import sys

TARGET_ARCH = os.environ.get("BORDD_ARCH") or None

a = Analysis(
    ['../bordd.py'],
    pathex=['..'],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'numpy', 'scipy', 'matplotlib', 'pandas', 'pytest',
        'IPython', 'notebook', 'jupyter', 'setuptools', 'pip',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'wx',
        'sqlite3', 'curses', 'distutils',
        # CLI 版不需要 GUI 相关模块
        'tkinter', 'PIL.ImageTk', 'PIL._tkinter_finder',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,      # onedir：依赖放进 _internal/
    name='Bordd',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,               # 命令行版保留控制台输出
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=TARGET_ARCH,
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
    name='Bordd_cli',
)

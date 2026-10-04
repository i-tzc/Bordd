# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 规格文件 —— GUI 版（无控制台窗口，onedir 目录模式）。

产物：
    Windows : dist/Bordd_gui/Bordd_gui.exe   双击即可运行
    macOS   : dist/Bordd.app                 双击即可运行

为什么用 onedir 而不是 onefile：

    onefile 每次启动都要先把自身解压到系统临时目录（%TEMP%\\_MEIxxxx），
    这带来三个真实问题：
      1. 临时目录不可写就直接启动失败，而且窗口版没有控制台，
         报错完全看不见 —— 表现就是"双击没反应"；
      2. 部分杀毒 / 终端防护软件会拦这个解压行为；
      3. 每次启动都要解压 20+ MB，慢 1~2 秒。

    onedir 直接从同目录的 _internal/ 加载，不写临时目录，启动更快、
    兼容性更好。代价是产物是一个文件夹而不是单个文件 ——
    **发布时必须整个文件夹一起拷，不能只拷 exe。**

为什么 console=False：
    GUI 版不需要控制台；console=True 时双击会先弹出黑色命令行窗口。

构建（在 bordd_dist 目录下执行）：
    python -m PyInstaller Bordd_gui.spec --noconfirm

macOS 通用二进制：设置环境变量 BORDD_ARCH=universal2 后重新构建；
要求所用的 Python 本身是 universal2 构建，否则 PyInstaller 会报错。
"""

import os
import sys

TARGET_ARCH = os.environ.get("BORDD_ARCH") or None

a = Analysis(
    ['../bordd_gui.py'],
    pathex=['..'],
    binaries=[],
    datas=[
        # 窗口 / 任务栏图标（运行时通过 sys._MEIPASS 定位）
        ('../assets/Bordd.ico', 'assets'),
        ('../assets/icon_png', 'assets/icon_png'),
    ],
    hiddenimports=[
        # ImageTk 是动态导入的，显式声明以免被裁掉导致预览失效
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 明确用不到的重型库，排除后体积明显更小
        'numpy', 'scipy', 'matplotlib', 'pandas', 'pytest',
        'IPython', 'notebook', 'jupyter', 'setuptools', 'pip',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'wx',
        'sqlite3', 'curses', 'distutils',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,      # 关键：依赖放进 _internal/，不打进 exe
    name='Bordd_gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,              # 无控制台，双击直接出界面
    disable_windowed_traceback=False,
    argv_emulation=False,       # macOS 上必须为 False（Carbon 已废弃）
    target_arch=TARGET_ARCH,
    codesign_identity=None,
    entitlements_file=None,
    icon='../assets/Bordd.ico' if sys.platform == 'win32' else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Bordd_gui',
)

# macOS 需要 .app 包才能正常获得 Dock 图标、菜单栏与“应用程序”行为
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Bordd.app',
        icon='../assets/Bordd.icns'
             if os.path.exists(os.path.join(SPECPATH, '..', 'assets',
                                            'Bordd.icns')) else None,
        bundle_identifier='com.bordd.app',
        info_plist={
            'CFBundleName': 'Bordd',
            'CFBundleDisplayName': 'Bordd',
            'CFBundleShortVersionString': '1.2.0',
            'CFBundleVersion': '1.2.0',
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '10.15',
            'LSApplicationCategoryType': 'public.app-category.photography',
        },
    )

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包「发给 Mac 朋友」的传输包 —— 一个真正的 Bordd.app。

生成：
    mac_share/Bordd_mac/           可直接传输的文件夹
    mac_share/Bordd_mac.zip        推荐传输这个（已保留可执行权限）

产物结构（解压后）：
    Bordd_mac/
    ├── Bordd.app/                 ← 双击这个就能启动，体验与 Windows 的
    │   └── Contents/                 Bordd_gui.exe 完全一致
    │       ├── Info.plist
    │       ├── PkgInfo
    │       ├── MacOS/Bordd            可执行入口（双击 .app 时由系统运行）
    │       └── Resources/
    │           ├── lib.sh             共用函数
    │           ├── setup.sh           首次运行安装依赖
    │           ├── Bordd.icns         应用图标
    │           └── app/               程序本体
    │               ├── bordd.py
    │               ├── bordd_gui.py
    │               └── assets/
    ├── 使用说明.txt
    └── 界面预览.png

为什么必须用本脚本打 zip，而不是系统自带的「压缩」：
    macOS 双击 .app、运行 .command，都依赖文件带「可执行」权限位。
    Windows 的压缩工具不会写入 Unix 权限信息，解压后权限全丢，
    双击就没反应。ZIP 格式本身可以在文件属性里记录 Unix 权限，
    Python 的 zipfile 能写进去，macOS 自带的解压工具也认。
    所以这里对每个文件手工设置 0755 / 0644，并且统一成 LF 换行。

用法（在 bordd_dist 目录下）：
    python make_mac_share.py
"""

import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent          # bordd_dist/
ROOT = HERE.parent                              # 仓库根
TEMPLATE = HERE / "mac_template"
OUT_ROOT = ROOT / "mac_share"
PKG_NAME = "Bordd_mac"
PKG = OUT_ROOT / PKG_NAME

APP_IN_PKG = "Bordd.app"
MANUAL_NAME = "使用说明.txt"
SCREENSHOT_NAME = "界面预览.png"

VERSION = "1.2.0"

# 包内需要「可执行」权限的文件
EXECUTABLE = {
    f"{APP_IN_PKG}/Contents/MacOS/Bordd",
    f"{APP_IN_PKG}/Contents/Resources/setup.sh",
    f"{APP_IN_PKG}/Contents/Resources/lib.sh",
}

# 需要统一成 LF 的文本后缀（带 CRLF 的 shell 脚本在 macOS 上会报错）
LF_ONLY_SUFFIX = {".sh", ".command", ".py", ".txt", ".plist", ""}


def log(msg=""):
    print(msg, flush=True)


def copy_text(src: Path, dst: Path) -> None:
    """复制文本文件，强制 LF 换行、去掉 UTF-8 BOM。"""
    data = src.read_bytes().replace(b"\r\n", b"\n")
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)


def _is_script(path: Path) -> bool:
    try:
        return path.read_bytes()[:2] == b"#!"
    except OSError:
        return False


def assemble() -> None:
    if PKG.exists():
        shutil.rmtree(PKG)
    PKG.mkdir(parents=True)

    if not TEMPLATE.is_dir():
        raise SystemExit(f"找不到模板目录：{TEMPLATE}")

    log("组装 Bordd.app：")

    # 1) 复制 .app 模板骨架（只取 Bordd.app 内的文件；
    #    使用说明.txt 等放在模板根，由第 4 步单独复制，避免重复）
    bundle_root = TEMPLATE / APP_IN_PKG
    for path in sorted(bundle_root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(TEMPLATE).as_posix()
        dst = PKG / rel
        if path.suffix.lower() in LF_ONLY_SUFFIX or _is_script(path):
            copy_text(path, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dst)
        log(f"  + {rel}")

    # 2) 程序本体放进 Resources/app/
    app_src = PKG / APP_IN_PKG / "Contents" / "Resources" / "app"
    for name in ("bordd.py", "bordd_gui.py"):
        copy_text(ROOT / name, app_src / name)
        log(f"  + {APP_IN_PKG}/Contents/Resources/app/{name}")

    assets_dst = app_src / "assets"
    for name in ("Bordd.ico", "make_icon.py"):
        src = ROOT / "assets" / name
        if src.exists():
            copy_text(src, assets_dst / name)
            log(f"  + {APP_IN_PKG}/Contents/Resources/app/assets/{name}")

    png_dir = ROOT / "assets" / "icon_png"
    if png_dir.is_dir():
        (assets_dst / "icon_png").mkdir(parents=True, exist_ok=True)
        n = 0
        for p in sorted(png_dir.glob("*.png")):
            shutil.copy2(p, assets_dst / "icon_png" / p.name)
            n += 1
        log(f"  + {APP_IN_PKG}/Contents/Resources/app/assets/icon_png/（{n} 个图标）")

    # 3) 应用图标
    icns = ROOT / "assets" / "Bordd.icns"
    if not icns.exists():
        log("  ! 缺少 Bordd.icns，正在生成…")
        subprocess.run([sys.executable, str(ROOT / "assets" / "make_icon.py")],
                       cwd=str(ROOT / "assets"))
    if icns.exists():
        shutil.copy2(icns, PKG / APP_IN_PKG / "Contents" / "Resources" / "Bordd.icns")
        log(f"  + {APP_IN_PKG}/Contents/Resources/Bordd.icns")
    else:
        log("  ! 未能生成 .icns，应用将使用系统默认图标")

    # 4) 说明文件
    manual = TEMPLATE / MANUAL_NAME
    if manual.exists():
        copy_text(manual, PKG / MANUAL_NAME)
        log(f"  + {MANUAL_NAME}")
    shot = ROOT / "docs" / "gui_frozen_done.png"
    if shot.exists():
        shutil.copy2(shot, PKG / SCREENSHOT_NAME)
        log(f"  + {SCREENSHOT_NAME}")


def make_zip() -> Path:
    zip_path = OUT_ROOT / f"{PKG_NAME}.zip"
    if zip_path.exists():
        zip_path.unlink()

    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(PKG.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(OUT_ROOT).as_posix()      # 含顶层目录名
            info = zipfile.ZipInfo(rel, date_time=(2025, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            # 关键：写入 Unix 权限位，macOS 解压后才保得住「可执行」
            inner = rel.split("/", 1)[1]
            mode = 0o755 if inner in EXECUTABLE else 0o644
            info.external_attr = (mode | stat.S_IFREG) << 16
            info.flag_bits |= 0x800          # 文件名用 UTF-8（含中文文件名）
            zf.writestr(info, path.read_bytes())
            count += 1
    log(f"  已写入 {count} 个条目")
    return zip_path


def main() -> int:
    log(f"Bordd v{VERSION} — 生成给 Mac 的传输包")
    log(f"源目录  : {ROOT}")
    log(f"输出目录: {OUT_ROOT}")
    log()
    assemble()

    zip_path = make_zip()
    size_kb = zip_path.stat().st_size / 1024

    log()
    log("=" * 62)
    log("打包完成")
    log("=" * 62)
    log(f"  文件夹: {PKG}")
    log(f"  压缩包: {zip_path}  ({size_kb:.0f} KB)  <-- 发这个给朋友")
    log()
    log("朋友解压后：双击 Bordd（应用程序图标）即可启动；")
    log("首次会引导安装运行环境，之后就是纯双击、没有终端窗口。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

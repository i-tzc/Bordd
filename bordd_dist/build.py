#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bordd 跨平台构建驱动（Windows / macOS 共用同一套逻辑）。

为什么用 Python 而不是把逻辑写在 .bat / .sh 里：
    Windows 的 cmd.exe 按「控制台代码页」（简体中文系统通常是 936/GBK）
    读取批处理文件。若 .bat 存为 UTF-8，中文会被错误解码，甚至把某个汉字
    的尾字节当成 | 或 > 之类的特殊符号，导致语法错误、脚本无法执行。
    因此 build_windows.bat / build_mac.sh 只做一件事：调用本脚本；
    所有中文提示与构建逻辑都放在这个 UTF-8 的 Python 文件里。

产物：
    Windows : dist/Bordd_gui/Bordd_gui.exe   图形界面版（双击使用）
              dist/Bordd_cli/Bordd.exe       命令行版
    macOS   : dist/Bordd.app                 图形界面版（双击使用）
              dist/Bordd_cli/Bordd           命令行版

采用 onedir（目录）模式：不依赖系统临时目录，启动快、兼容性好。
发布时整个文件夹一起拷，不能只拷 exe。

用法：
    python build.py                 # 构建全部
    python build.py --gui-only      # 只构建 GUI 版
    python build.py --cli-only      # 只构建命令行版
    python build.py --arch native   # macOS：只构建当前架构（默认先试 universal2）
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # bordd_dist/
ROOT = HERE.parent                              # 仓库根
DIST = HERE / "dist"
ASSETS = ROOT / "assets"

VERSION = "1.2.0"
GUI_SPEC = "Bordd_gui.spec"
CLI_SPEC = "Bordd_cli.spec"

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# onedir：产物是文件夹；macOS 的 GUI 被 BUNDLE 包成 .app，落在 dist 根下
GUI_ARTIFACT = (DIST / "Bordd.app") if IS_MAC else (
    DIST / "Bordd_gui" / ("Bordd_gui.exe" if IS_WIN else "Bordd_gui"))
CLI_ARTIFACT = DIST / "Bordd_cli" / ("Bordd.exe" if IS_WIN else "Bordd")
# 上面两个是「可执行文件」；下面两个是用来算体积的整包目录
GUI_BUNDLE = (DIST / "Bordd.app") if IS_MAC else (DIST / "Bordd_gui")
CLI_BUNDLE = DIST / "Bordd_cli"


# --------------------------------------------------------------------------
# 输出辅助：保留控制台原编码（中文系统下 GBK 可正常显示中文），
# 仅把无法编码的字符替换掉，避免 UnicodeEncodeError 中断构建。
# --------------------------------------------------------------------------
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass


def log(msg: str = "") -> None:
    print(msg, flush=True)


def section(title: str) -> None:
    log()
    log("=" * 62)
    log(title)
    log("=" * 62)


def die(msg: str, code: int = 1):
    log(f"[错误] {msg}")
    sys.exit(code)


# --------------------------------------------------------------------------
# 环境检查
# --------------------------------------------------------------------------
def check_env() -> None:
    section("[0/4] 检查构建环境")
    log(f"解释器  : {sys.executable}")
    log(f"Python  : {sys.version.split()[0]}")
    log(f"平台    : {platform.platform()}")

    missing = []
    try:
        import PIL

        log(f"Pillow  : {PIL.__version__}")
    except ImportError:
        missing.append("Pillow")
    try:
        import PyInstaller

        log(f"PyInstaller: {PyInstaller.__version__}")
    except ImportError:
        missing.append("pyinstaller")

    if missing:
        die(
            "缺少依赖：" + "、".join(missing) + "\n"
            f"        请执行：{Path(sys.executable).name} -m pip install "
            f"{' '.join(m.lower() for m in missing)}"
        )

    if IS_WIN:
        # GUI 版需要 tkinter；缺失时构建仍能成功，但界面无法启动
        try:
            import tkinter  # noqa: F401

            log("tkinter : 可用")
        except ImportError:
            die("当前解释器没有 tkinter，GUI 版无法运行。\n"
                "        请安装带 tcl/tk 的 Python（官方安装包默认包含）。")
    if sys.version_info < (3, 9):
        die(f"Python 版本过低（{sys.version.split()[0]}），需要 3.9 以上。")


def ensure_icons(force: bool = False) -> None:
    """确保存在程序图标；缺失时调用 assets/make_icon.py 现场生成。"""
    section("[1/4] 准备图标资源")
    ico = ASSETS / "Bordd.ico"
    maker = ASSETS / "make_icon.py"
    if maker.exists() and (force or not ico.exists()):
        log("生成图标中…")
        rc = subprocess.run([sys.executable, str(maker)], cwd=str(ASSETS)).returncode
        if rc != 0:
            log("[警告] 图标生成失败，将使用默认图标继续构建。")
    if ico.exists():
        log(f"Windows 图标: {ico.name} ({ico.stat().st_size} 字节)")
    else:
        log("[警告] 未找到 Bordd.ico，将使用默认图标。")

    if IS_MAC:
        icns = ASSETS / "Bordd.icns"
        if icns.exists():
            log(f"macOS 图标  : {icns.name}")
        elif _make_icns():
            log(f"macOS 图标  : {icns.name}（已生成）")
        else:
            log("[警告] 未生成 .icns（缺少 iconutil 或 PNG），将使用默认图标。")


def _make_icns() -> bool:
    """用 macOS 自带的 iconutil 把 PNG 合成 .icns。"""
    import shutil
    import tempfile

    if not shutil.which("iconutil"):
        return False
    png_dir = ASSETS / "icon_png"
    if not png_dir.is_dir():
        return False

    mapping = {
        "icon_16.png": "icon_16x16.png",
        "icon_32.png": "icon_16x16@2x.png",
        "icon_64.png": "icon_32x32@2x.png",
        "icon_128.png": "icon_128x128.png",
        "icon_256.png": "icon_128x128@2x.png",
        "icon_512.png": "icon_256x256@2x.png",
        "icon_1024.png": "icon_512x512@2x.png",
    }
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "Bordd.iconset"
        iconset.mkdir()
        for src_name, dst_name in mapping.items():
            src = png_dir / src_name
            if src.exists():
                (iconset / dst_name).write_bytes(src.read_bytes())
        # 32x32 与 512x512 的 1x 槽位
        for src_name, dst_name in (("icon_32.png", "icon_32x32.png"),
                                   ("icon_512.png", "icon_512x512.png")):
            src = png_dir / src_name
            if src.exists():
                (iconset / dst_name).write_bytes(src.read_bytes())
        rc = subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o",
             str(ASSETS / "Bordd.icns")],
            capture_output=True,
        ).returncode
    return rc == 0


# --------------------------------------------------------------------------
# 构建
# --------------------------------------------------------------------------
def run_pyinstaller(spec: str, arch: str | None) -> int:
    cmd = [sys.executable, "-m", "PyInstaller", spec,
           "--noconfirm", "--clean"]
    env = dict(os.environ)
    if arch:
        env["BORDD_ARCH"] = arch
    else:
        env.pop("BORDD_ARCH", None)
    return subprocess.run(cmd, cwd=str(HERE), env=env).returncode


def build_one(spec: str, label: str, arch_mode: str) -> None:
    section(f"构建 {label}")
    if IS_MAC and arch_mode != "native":
        log("尝试 universal2（Apple Silicon + Intel 二合一）…")
        if run_pyinstaller(spec, "universal2") == 0:
            return
        log("universal2 构建失败 —— 常见原因是当前 Python 不是 universal2 版本。")
        log("回退为仅构建当前架构…")
    rc = run_pyinstaller(spec, None)
    if rc != 0:
        die(f"{label} 构建失败（PyInstaller 退出码 {rc}）。")


# --------------------------------------------------------------------------
# 验证
# --------------------------------------------------------------------------
def _dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def verify(expect_gui: bool, expect_cli: bool) -> None:
    section("验证产物")
    ok = True

    if expect_gui:
        if GUI_ARTIFACT.exists():
            log(f"[OK] {GUI_ARTIFACT.relative_to(ROOT)}"
                f"   整包 {_dir_size(GUI_BUNDLE) / 1048576:.1f} MB")
        else:
            log(f"[失败] 缺少 GUI 产物：{GUI_ARTIFACT.relative_to(ROOT)}")
            ok = False

    if expect_cli:
        if CLI_ARTIFACT.exists():
            log(f"[OK] {CLI_ARTIFACT.relative_to(ROOT)}"
                f"   整包 {_dir_size(CLI_BUNDLE) / 1048576:.1f} MB")
            # 必须能响应 --version，否则说明打包有问题。
            # 这里显式指定一个构建目录内的临时目录：极少数受限环境
            # （沙箱、部分 CI）下系统 TEMP 对子进程不可写。
            check_tmp = HERE / "_selfcheck_tmp"
            check_tmp.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ)
            env["TEMP"] = env["TMP"] = str(check_tmp)
            try:
                proc = subprocess.run([str(CLI_ARTIFACT), "--version"],
                                      capture_output=True, text=True,
                                      encoding="utf-8", errors="replace",
                                      env=env)
            finally:
                shutil.rmtree(check_tmp, ignore_errors=True)
            if proc.returncode == 0:
                log(f"[OK] 命令行自检：{(proc.stdout or '').strip()}")
            else:
                log(f"[失败] `--version` 退出码 {proc.returncode}："
                    f"{(proc.stderr or proc.stdout or '').strip()}")
                ok = False
        else:
            log(f"[失败] 缺少命令行产物：{CLI_ARTIFACT.relative_to(ROOT)}")
            ok = False

    if not ok:
        die("构建产物验证未通过。")


def print_summary(expect_gui: bool, expect_cli: bool) -> None:
    section(f"构建完成  Bordd v{VERSION}")
    log("产物位置：")
    if expect_gui:
        log(f"  {GUI_BUNDLE}")
        log(f"     图形界面版 —— 双击里面的 "
            f"{GUI_ARTIFACT.name if IS_MAC else 'Bordd_gui.exe'} 即可使用。")
    if expect_cli:
        log(f"  {CLI_BUNDLE}")
        log("     命令行版 —— 用法：" +
            (f"{CLI_ARTIFACT.name} --help" if IS_WIN
             else f"./{CLI_ARTIFACT.name} --help"))
    log()
    log("重要提示：")
    log("  · 这是 onedir 目录模式：整个文件夹要一起拷，不能只拷 exe，")
    log("    否则会因为缺少同目录的 _internal/ 而无法启动。")
    log("  · onedir 不需要系统临时目录，启动也更快（无解压过程）。")
    if IS_MAC:
        log("  · 若提示“来自身份不明的开发者”，执行：")
        log(f"      xattr -dr com.apple.quarantine {GUI_BUNDLE}")
    if IS_WIN:
        log("  · 若被杀毒软件误报，添加信任即可。")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bordd 跨平台构建驱动（Windows / macOS）。")
    parser.add_argument("--gui-only", action="store_true", help="只构建 GUI 版")
    parser.add_argument("--cli-only", action="store_true", help="只构建命令行版")
    parser.add_argument("--skip-icons", action="store_true", help="跳过图标生成")
    parser.add_argument("--arch", choices=["auto", "native", "universal2"],
                        default="auto",
                        help="macOS 构建架构，默认 auto（先试 universal2）")
    args = parser.parse_args()

    if args.gui_only and args.cli_only:
        die("--gui-only 与 --cli-only 不能同时使用。")

    do_gui = not args.cli_only
    do_cli = not args.gui_only

    log(f"Bordd v{VERSION} 构建驱动")
    log(f"工作目录: {HERE}")

    check_env()
    if args.skip_icons:
        section("[1/4] 跳过图标资源")
    else:
        ensure_icons()

    arch_mode = args.arch
    if not IS_MAC:
        arch_mode = "native"

    if do_gui:
        build_one(GUI_SPEC, "图形界面版（Bordd_gui）", arch_mode)
    if do_cli:
        build_one(CLI_SPEC, "命令行版（Bordd）", arch_mode)

    verify(do_gui, do_cli)
    print_summary(do_gui, do_cli)
    return 0


if __name__ == "__main__":
    sys.exit(main())

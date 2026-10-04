#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验发给 Mac 的 Bordd.app 传输包是否结构正确、权限正确。

检查项：
  1. .app 目录结构齐全（Info.plist / MacOS/Bordd / Resources/...）
  2. Info.plist 能被 plistlib 解析，关键字段正确
  3. 所有 shell 脚本：LF 换行、无 BOM、bash -n 语法通过
  4. 脚本里的路径引用都能在包内解析到
  5. zip 内权限：可执行文件为 0755，其余 0644
  6. zip 解压后内容与文件夹一致

用法：python tests/verify_mac_package.py [bash 路径]
"""
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "mac_share" / "Bordd_mac"
ZIP = ROOT / "mac_share" / "Bordd_mac.zip"
APP = PKG / "Bordd.app"

BASH = sys.argv[1] if len(sys.argv) > 1 else None

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAILS = []


def check(label, cond, extra=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAILS.append(label)


def find_bash():
    if BASH and Path(BASH).exists():
        return BASH
    for c in (r"D:\Git\bin\bash.exe", "/bin/bash"):
        if Path(c).exists():
            return c
    return shutil.which("bash")


def main() -> int:
    bash = find_bash()
    print(f"包目录: {PKG}")
    print(f"压缩包: {ZIP}")
    print(f"bash  : {bash or '（未找到，跳过语法检查）'}")
    print("-" * 68)

    # ---------- 1. 结构 ----------
    required = [
        "Contents/Info.plist",
        "Contents/PkgInfo",
        "Contents/MacOS/Bordd",
        "Contents/Resources/lib.sh",
        "Contents/Resources/setup.sh",
        "Contents/Resources/Bordd.icns",
        "Contents/Resources/app/bordd.py",
        "Contents/Resources/app/bordd_gui.py",
        "Contents/Resources/app/assets/Bordd.ico",
    ]
    for rel in required:
        check(f"存在 {rel}", (APP / rel).exists())
    check("存在 使用说明.txt", (PKG / "使用说明.txt").exists())
    check("存在 界面预览.png", (PKG / "界面预览.png").exists())

    # ---------- 2. Info.plist ----------
    try:
        with open(APP / "Contents" / "Info.plist", "rb") as fh:
            pl = plistlib.load(fh)
        check("Info.plist 可解析", True)
        check("CFBundleExecutable = Bordd", pl.get("CFBundleExecutable") == "Bordd")
        check("CFBundleName = Bordd", pl.get("CFBundleName") == "Bordd")
        check("CFBundleDisplayName = Bordd", pl.get("CFBundleDisplayName") == "Bordd")
        check("CFBundlePackageType = APPL", pl.get("CFBundlePackageType") == "APPL")
        check("CFBundleIconFile = Bordd",
              pl.get("CFBundleIconFile") == "Bordd",
              "对应 Resources/Bordd.icns")
        check("NSHighResolutionCapable = true",
              pl.get("NSHighResolutionCapable") is True)
    except Exception as e:
        check("Info.plist 可解析", False, str(e))

    # ---------- 3. shell 脚本 ----------
    scripts = sorted(APP.rglob("*.sh")) + [APP / "Contents" / "MacOS" / "Bordd"]
    for s in scripts:
        raw = s.read_bytes()
        name = s.relative_to(APP).as_posix()
        check(f"{name}: LF 换行", b"\r\n" not in raw)
        check(f"{name}: 无 BOM", not raw.startswith(b"\xef\xbb\xbf"))
        check(f"{name}: 有 shebang", raw.startswith(b"#!"))
        if bash:
            r = subprocess.run([bash, "-n", str(s)], capture_output=True, text=True)
            check(f"{name}: bash -n 通过", r.returncode == 0,
                  (r.stderr or "").strip()[:120])

    # ---------- 4. 脚本内路径引用可解析（真实解析，不是字符串匹配）----------
    res = APP / "Contents" / "Resources"
    check("Resources/app 目录存在", (res / "app").is_dir())
    check("bordd_gui.py 就位", (res / "app" / "bordd_gui.py").exists())

    for s in (APP / "Contents" / "MacOS" / "Bordd", res / "setup.sh"):
        text = s.read_text(encoding="utf-8")
        here = s.parent
        # 变量取值规则与脚本里一致
        vars_ = {
            "$_HERE": str(here),
            "$RES": str(res),
            "$BUNDLE": str(APP),
            "$APP_SRC": str(res / "app"),
        }
        targets = re.findall(r'^\s*\.\s+"?([^"\s]+)"?', text, re.M)
        if not targets:
            check(f"{s.name}: 有 source 语句", False)
            continue
        for t in targets:
            resolved = t
            for k, v in vars_.items():
                resolved = resolved.replace(k, v)
            ok = Path(resolved).exists()
            check(f"{s.name} source 的 {t} 可解析", ok, resolved)

    # ---------- 5/6. zip 权限与内容 ----------
    if not ZIP.exists():
        check("zip 存在", False)
    else:
        exec_expected = {
            "Bordd_mac/Bordd.app/Contents/MacOS/Bordd": 0o755,
            "Bordd_mac/Bordd.app/Contents/Resources/setup.sh": 0o755,
            "Bordd_mac/Bordd.app/Contents/Resources/lib.sh": 0o755,
        }
        with zipfile.ZipFile(ZIP) as zf:
            infos = {i.filename: i for i in zf.infolist()}
            check("zip 条目数与文件夹一致",
                  len(infos) == len([p for p in PKG.rglob("*") if p.is_file()]),
                  f"{len(infos)} 条")
            for name, want in exec_expected.items():
                info = infos.get(name)
                if info is None:
                    check(f"zip 含 {name}", False)
                    continue
                got = (info.external_attr >> 16) & 0o777
                check(f"zip 权限 {name.split('/')[-1]}", got == want,
                      f"{oct(got)}（期望 {oct(want)}）")
            # 非脚本文件必须是 0644，避免出现意外的可执行
            odd = [n for n, i in infos.items()
                   if ((i.external_attr >> 16) & 0o111) and n not in exec_expected]
            check("zip 中无多余的可执行文件", not odd, str(odd[:3]))

            # 解压到临时目录，逐个比对内容
            with tempfile.TemporaryDirectory() as tmp:
                zf.extractall(tmp)
                bad = []
                for p in PKG.rglob("*"):
                    if not p.is_file():
                        continue
                    rel = p.relative_to(PKG.parent).as_posix()
                    q = Path(tmp) / rel
                    if not q.exists() or q.read_bytes() != p.read_bytes():
                        bad.append(rel)
                check("zip 内容与文件夹逐字节一致", not bad, f"{len(bad)} 处不同 {bad[:3]}")

    # ---------- 附加：确认没有遗留旧命名 ----------
    leftover = []
    for p in PKG.rglob("*"):
        if p.is_file():
            n = p.name
            if "add_border" in n or "Bordd_gui.app" in n:
                leftover.append(p.relative_to(PKG).as_posix())
    check("包内无 add_border 旧命名", not leftover, str(leftover[:3]))

    print("-" * 68)
    if FAILS:
        print(f"失败 {len(FAILS)} 项：")
        for f in FAILS:
            print(f"  · {f}")
        return 1
    print("全部通过 [OK]")
    return 0


if __name__ == "__main__":
    sys.exit(main())

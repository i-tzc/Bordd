#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一个 macOS .app 打包成「权限正确」的 zip。

为什么需要它：

    GitHub Actions 官方文档明确写着 "File permissions are not maintained
    during artifact upload" —— 直接把 Bordd.app 交给 upload-artifact，
    下载回来时 Contents/MacOS/ 里的可执行位会丢失，朋友双击就是「没有任何反应」。
    同理，符号链接也可能被压成普通文件，.app 直接损坏。

解决办法：

    不让 GitHub 去压 .app。改成在 CI 里先用本脚本把它压成一个**普通文件**
    （zip 内部记录好 0755 权限和符号链接），再把「这个 zip 文件」交给
    upload-artifact。传输过程只需要保证文件内容不变 —— 这一点是可靠的。
    朋友下载后用 macOS 自带的解压（双击）即可还原出可执行的 .app。

写入的权限规则：
    目录 / 可执行文件 -> 0755
    普通文件          -> 0644
    符号链接          -> 原样保留（S_IFLNK + 链接目标）

用法：
    python make_app_zip.py <Bordd.app 路径> <输出 zip 路径>
    例：python make_app_zip.py dist/Bordd.app ../mac_share/Bordd-macos-arm64.zip
"""

import os
import stat
import sys
import zipfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 非 macOS 上无法判断可执行位，此时一律按 0755 写
_FORCE_EXEC = False


def _info(arcname: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(arcname, date_time=(2025, 1, 1, 0, 0, 0))
    info.create_system = 3              # 3 = Unix，解压端才会读权限位
    info.external_attr = mode << 16
    info.flag_bits |= 0x800             # 文件名按 UTF-8 编码
    return info


def add_tree(zf: zipfile.ZipFile, root: Path, counters: dict) -> None:
    """递归写入 root（含 root 自身这个名字）。"""
    base = root.parent
    root_arc = root.name + "/"

    # 根目录本身
    zf.writestr(_info(root_arc, stat.S_IFDIR | 0o755), b"")
    counters["dir"] += 1

    # followlinks=False：不跟进符号链接目录，避免内容被复制一份
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        d = Path(dirpath)

        keep = []
        for name in dirnames:
            p = d / name
            arc = p.relative_to(base).as_posix() + "/"
            if p.is_symlink():
                zf.writestr(_info(arc.rstrip("/"),
                                  stat.S_IFLNK | 0o755),
                            os.readlink(p).encode("utf-8"))
                counters["link"] += 1
            else:
                zf.writestr(_info(arc, stat.S_IFDIR | 0o755), b"")
                counters["dir"] += 1
                keep.append(name)
        dirnames[:] = keep        # 不进入符号链接目录

        for name in filenames:
            p = d / name
            arc = p.relative_to(base).as_posix()
            if p.is_symlink():
                zf.writestr(_info(arc, stat.S_IFLNK | 0o755),
                            os.readlink(p).encode("utf-8"))
                counters["link"] += 1
                continue
            # 只用 st_mode 判断可执行：Windows 上 os.access(X_OK) 会把普通文件
            # 也报成可执行（Windows 没有真正的可执行位），会把 Info.plist 之类
            # 误标成 0755。本脚本实际运行在 macOS 上，st_mode 是准确的。
            st = p.stat()
            executable = _FORCE_EXEC or bool(st.st_mode & 0o111)
            mode = stat.S_IFREG | (0o755 if executable else 0o644)
            info = _info(arc, mode)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, p.read_bytes())
            counters["exec" if executable else "file"] += 1


def make_zip(app: Path, out_zip: Path) -> dict:
    if not app.is_dir():
        raise SystemExit(f"找不到 .app 目录：{app}")

    # Windows 的 stat 不反映 Unix 可执行位：如果在这里跑，所有文件都会被判成
    # 0644，产出的 .app 双击没反应。此时一律按 0755 写，宁可权限放宽，
    # 也要保证程序能启动。（正常用法是在 macOS / CI 上运行。）
    if sys.platform != "darwin":
        global _FORCE_EXEC
        _FORCE_EXEC = True
        print("[提示] 当前不是 macOS，无法准确判断可执行位；"
              "将把所有文件按 0755 写入以保证可启动。")

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    if out_zip.exists():
        out_zip.unlink()

    counters = {"dir": 0, "file": 0, "exec": 0, "link": 0}
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        add_tree(zf, app, counters)
    return counters


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    app = Path(sys.argv[1]).resolve()
    out_zip = Path(sys.argv[2]).resolve()

    counters = make_zip(app, out_zip)
    size = out_zip.stat().st_size / 1048576

    print(f"已打包: {out_zip}")
    print(f"  源     : {app}")
    print(f"  大小   : {size:.1f} MB")
    print(f"  目录   : {counters['dir']}")
    print(f"  文件   : {counters['file'] + counters['exec']}"
          f"  （其中可执行 {counters['exec']}）")
    print(f"  符号链接: {counters['link']}")

    # 自检：Contents/MacOS/ 下的入口必须带可执行位，否则朋友双击没反应。
    # 这一步顺便让 CI 在出问题时自动失败，不用再单独写校验步骤。
    problems = []
    with zipfile.ZipFile(out_zip) as zf:
        for i in zf.infolist():
            if i.filename.endswith("/"):
                continue
            if "/MacOS/" not in i.filename:
                continue
            mode = (i.external_attr >> 16) & 0o777
            ok = bool(mode & 0o111)
            print(f"  入口检查: {i.filename}  权限={oct(mode)}  "
                  f"{'OK' if ok else '!! 缺可执行位'}")
            if not ok:
                problems.append(i.filename)

    if problems:
        print()
        print("[失败] 下列入口缺少可执行位，解压后 .app 将无法启动：")
        for p in problems:
            print(f"  - {p}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对冻结后的 Windows 产物做端到端验收。

产物是 onedir 目录模式：
    dist/Bordd_gui/Bordd_gui.exe     图形界面版
    dist/Bordd_cli/Bordd.exe         命令行版

用法：python tests/verify_frozen.py [dist目录]
"""
import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from PIL import Image, ImageDraw  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIST = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "bordd_dist" / "dist"
CLI = DIST / "Bordd_cli" / "Bordd.exe"
GUI = DIST / "Bordd_gui" / "Bordd_gui.exe"

# 刻意不改 TEMP：onedir 不依赖系统临时目录，用默认环境跑才能验出
# 「一旦退回 onefile 就会在受限环境下启动失败」这类回归。
RUN_ENV = dict(os.environ)

FAILS = []


def check(label, cond, extra=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAILS.append(label)


def make_samples(d: Path):
    d.mkdir(parents=True, exist_ok=True)
    specs = [("landscape.jpg", (1920, 1080)), ("portrait.jpg", (1080, 1440)),
             ("square.png", (1200, 1200)), ("gray.jpg", (800, 600))]
    for name, (w, h) in specs:
        im = Image.new("RGB", (w, h))
        dr = ImageDraw.Draw(im)
        for y in range(h):
            t = y / max(h - 1, 1)
            dr.line([(0, y), (w, y)],
                    fill=(round(20 + 100 * t), round(60 + 130 * t), round(100 + 130 * t)))
        dr.rectangle([w * 0.1, h * 0.1, w * 0.4, h * 0.4], outline=(255, 255, 255), width=5)
        if name.endswith(".jpg"):
            im.save(d / name, quality=95)
        else:
            im.save(d / name)
    return sorted(p.name for p in d.iterdir())


def run_cli(*args):
    # 冻结程序通过管道输出时使用系统区域编码（简体中文 Windows 为 cp936/GBK），
    # 按 UTF-8 解码会得到乱码，导致中文断言失效。
    enc = "mbcs" if sys.platform == "win32" else "utf-8"
    p = subprocess.run([str(CLI), *args], capture_output=True, text=True,
                       encoding=enc, errors="replace", env=RUN_ENV)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    # 工作目录放在仓库内，而不是系统临时目录：
    # 一是在受限沙箱里子进程只能写工作区，放系统 TEMP 会被拒绝；
    # 二是失败时便于直接查看中间产物。
    work_root = ROOT / "_verify_work"
    shutil.rmtree(work_root, ignore_errors=True)
    tmp = work_root
    src = tmp / "src"
    names = make_samples(src)
    print(f"工作目录: {tmp}")
    print(f"样张: {', '.join(names)}")
    print("-" * 66)

    # 1. 产物存在且带图标资源
    check("CLI 产物存在", CLI.exists(), f"{CLI.stat().st_size/1048576:.1f} MB" if CLI.exists() else "缺失")
    check("GUI 产物存在", GUI.exists(), f"{GUI.stat().st_size/1048576:.1f} MB" if GUI.exists() else "缺失")

    # 2. --version
    rc, out = run_cli("--version")
    check("--version 退出码 0 且版本为 1.2.0", rc == 0 and "1.2.0" in out, out.strip())

    # 3. --help
    rc, out = run_cli("--help")
    check("--help 可用", rc == 0 and "--no-border" in out)

    # 4. 三种格式真实处理（统一按 4:3 处理，便于后面校验画布比例）
    jpeg_count = sum(1 for n in names if n.lower().endswith((".jpg", ".jpeg")))
    for fmt in ("keep", "png", "pdf"):
        outdir = tmp / f"out_{fmt}"
        rc, text = run_cli("-i", str(src), "-o", str(outdir),
                           "-r", "4:3", "-c", "black", "-f", fmt)
        produced = sorted(p.name for p in outdir.iterdir()) if outdir.is_dir() else []
        if fmt == "pdf":
            # PDF 只支持 JPEG：3 张 jpg 成功，square.png 明确失败 => 退出码 1
            check("PDF 模式：JPEG 成功、非 JPEG 明确失败",
                  rc == 1 and len(produced) == jpeg_count
                  and "square.png" in text,
                  f"rc={rc} 产物={len(produced)}/{jpeg_count}（期望 {jpeg_count} 个 PDF）")
        else:
            check(f"{fmt} 模式全部成功且退出码 0",
                  rc == 0 and len(produced) == len(names),
                  f"rc={rc} 产物={len(produced)}/{len(names)}")

    # 5. 画布比例 + 边框像素正确
    with Image.open(src / "landscape.jpg") as a, Image.open(tmp / "out_keep" / "landscape.jpg") as b:
        check("keep：画布比例被改成 4:3",
              abs(b.size[0] / b.size[1] - 4 / 3) < 0.002, f"{b.size}")
        check("keep：画布大于原图（确实加了边框）",
              b.size[0] >= a.size[0] and b.size[1] >= a.size[1], f"{a.size} -> {b.size}")
        check("keep：左上角是黑色边框像素", b.getpixel((2, 2)) == (0, 0, 0),
              str(b.getpixel((2, 2))))

    # 单独的 1:1 用例：方形输出
    sq_dir = tmp / "out_square"
    rc, _ = run_cli("-i", str(src), "-o", str(sq_dir), "-r", "1:1", "-f", "png")
    with Image.open(sq_dir / "landscape.jpg".replace(".jpg", ".png")) as b:
        check("png + 1:1：输出为正方形（宽高相等）",
              b.size[0] == b.size[1], f"{b.size}")

    # 6. 纯压缩：画布必须等于原图
    outdir = tmp / "out_noborder"
    rc, _ = run_cli("-i", str(src), "-o", str(outdir), "--no-border", "--jpeg-quality", "90")
    with Image.open(src / "landscape.jpg") as a, Image.open(outdir / "landscape.jpg") as b:
        check("纯压缩：画布 = 原图尺寸", a.size == b.size, f"{a.size} vs {b.size}")
        check("纯压缩：确实重压缩了（体积下降）",
              (outdir / "landscape.jpg").stat().st_size < (src / "landscape.jpg").stat().st_size)

    # 7. PDF 字节级无损
    try:
        import pikepdf
        raw_src = (src / "landscape.jpg").read_bytes()
        with pikepdf.open(tmp / "out_pdf" / "landscape.pdf") as pdf:
            page = pdf.pages[0]
            xo = page.Resources["/XObject"]["/Im0"]
            raw_pdf = bytes(xo.read_raw_bytes())
            check("PDF：图像流与源 JPEG 逐字节一致",
                  raw_src == raw_pdf,
                  f"sha={hashlib.sha256(raw_src).hexdigest()[:12]}")
            check("PDF：Filter 为 /DCTDecode（未重编码）",
                  str(xo.Filter) == "/DCTDecode", str(xo.Filter))
            box = [float(v) for v in page.MediaBox]
            check("PDF：页面尺寸符合 4:3",
                  abs((box[2] - box[0]) / (box[3] - box[1]) - 4 / 3) < 0.002, str(box))
    except ImportError:
        check("pikepdf 可用（用于校验 PDF）", False, "未安装，跳过 PDF 校验")

    # 8. 防覆盖保护
    rc, text = run_cli("-i", str(src), "-o", str(src), "-r", "4:3")
    check("拒绝 输出目录 = 输入目录", rc != 0 and "相同" in text, f"rc={rc}")

    # 9. 参数缺失退出码 2；且从 shell 调用时不应该被误判成「双击」而暂停
    rc, text = run_cli()
    check("无参数时退出码 2", rc == 2, f"rc={rc}")
    check("从 shell 调用时未被误判为双击（不含暂停提示）",
          "按回车键关闭" not in text and "图形界面版" not in text,
          "出现暂停提示说明引导进程数判断有误")

    # 10. 非法比例被拒绝
    rc, text = run_cli("-i", str(src), "-o", str(tmp / "x"), "-r", "abc")
    check("非法比例被拒绝", rc != 0 and "无效" in text, f"rc={rc}")

    # 11. 双击检测：新建控制台应暂停，shell 调用不应暂停
    if sys.platform == "win32":
        CREATE_NEW_CONSOLE = 0x00000010
        p = subprocess.Popen([str(CLI)], creationflags=CREATE_NEW_CONSOLE,
                             env=RUN_ENV)
        time.sleep(7)
        alive = p.poll() is None
        check("双击（新建控制台）时暂停等待回车，不再闪退", alive)
        if alive:
            p.kill()
            p.wait()
        elif p.returncode is not None:
            print(f"        （进程提前退出，退出码 {p.returncode}）")

    # 12. GUI 能否在「默认系统 TEMP」下正常启动并出现窗口
    #     目的是让「退回 onefile 导致启动失败」这类问题一定会被测出来：
    #     onefile 需要往 %TEMP% 解压，受限环境下窗口版会静默死亡、什么都看不到。
    if sys.platform == "win32":
        p = subprocess.Popen([str(GUI), str(src)], env=RUN_ENV,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def window_title(timeout=25.0) -> str:
            """轮询同名进程的可见窗口标题（onefile 引导进程无窗口，故按进程名找）。"""
            end = time.time() + timeout
            while time.time() < end:
                time.sleep(1.5)
                if p.poll() is not None:
                    return ""
                try:
                    out = subprocess.run(
                        ["powershell", "-NoProfile", "-Command",
                         "(Get-Process -Name Bordd_gui -ErrorAction SilentlyContinue"
                         " | Where-Object { $_.MainWindowHandle -ne 0 }"
                         " | Select-Object -First 1).MainWindowTitle"],
                        capture_output=True, text=True, errors="replace",
                        timeout=20)
                    title = (out.stdout or "").strip()
                except Exception:
                    title = ""
                if title:
                    return title
            return ""

        title = window_title()
        alive = p.poll() is None
        check("GUI 在默认 TEMP 下能启动并出现窗口", bool(title) and alive,
              f"标题={title!r} 存活={alive}")
        check("窗口标题就是 Bordd", title == "Bordd", repr(title))
        if alive:
            p.kill()
            p.wait()

    print("-" * 66)
    if FAILS:
        print(f"失败 {len(FAILS)} 项：")
        for f in FAILS:
            print(f"  · {f}")
        return 1
    print("全部通过 [OK]")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

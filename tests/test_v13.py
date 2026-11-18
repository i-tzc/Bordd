#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.3 新功能验收：单图输入 + 文件名后缀、单张体积上限。

用法（在工程根目录）：python tests/test_v13.py
"""
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from PIL import Image  # noqa: E402

from bordd import (  # noqa: E402
    _encode_bytes, add_border_to_image, build_save_kwargs, format_size,
    parse_size, process_directory, save_with_size_limit,
)

WORK = ROOT / "_v13_work"
FAILS = []


def check(label, cond, extra=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAILS.append(label)


def make_images(d: Path):
    d.mkdir(parents=True, exist_ok=True)
    specs = [("photo.jpg", (1920, 1080)), ("square.png", (900, 900)),
             ("tall.jpg", (1200, 2000))]
    for name, size in specs:
        im = Image.new("RGB", size)
        px = im.load()
        # 造一点纹理，避免纯色把体积压得过于极端
        for y in range(0, size[1], 7):
            for x in range(0, size[0], 7):
                px[x, y] = ((x * 3) % 256, (y * 5) % 256, (x + y) % 256)
        if name.endswith(".jpg"):
            im.save(d / name, quality=95)
        else:
            im.save(d / name)
    return [d / n for n, _ in specs]


# ---------------------------------------------------------------- 1. parse_size
def test_parse_size():
    print("\n=== 1. 体积字符串解析 ===")
    cases = [
        ("10MB", 10 * 1024 ** 2), ("500KB", 500 * 1024),
        ("1.5M", int(1.5 * 1024 ** 2)), ("2G", 2 * 1024 ** 3),
        ("10485760", 10485760), ("", 0), (None, 0), ("0", 0), ("1024B", 1024),
    ]
    for text, want in cases:
        got = parse_size(text)
        check(f"parse_size({text!r}) == {want}", got == want, f"得到 {got}")
    for bad in ("abc", "10TB", "MB"):
        try:
            parse_size(bad)
            check(f"parse_size({bad!r}) 应报错", False)
        except ValueError:
            check(f"parse_size({bad!r}) 正确报错", True)
    check("format_size(10MB) 显示合理", "MB" in format_size(10 * 1024 ** 2),
          format_size(10 * 1024 ** 2))


# ------------------------------------------------- 2. save_with_size_limit
def test_size_limit(images):
    print("\n=== 2. 按体积上限保存 ===")
    src = images[0]
    with Image.open(src) as im:
        im.load()
        result = add_border_to_image(im, (4, 3), (0, 0, 0), 0.02)
        kw = build_save_kwargs(im, "JPEG", 95)

    def enc(q):
        return len(_encode_bytes(result, "JPEG", dict(kw, quality=q)))

    out = WORK / "cap.jpg"

    # 2a 不设上限：应保持原质量
    q, n, ok = save_with_size_limit(result, out, "JPEG", kw, max_bytes=0,
                                    emit=lambda *_: None)
    check("无上限时质量不变", q == 95 and ok, f"q={q}")
    check("无上限时写盘大小与返回一致", out.stat().st_size == n)

    # 2b 上限很大：不应降质量
    q, n, ok = save_with_size_limit(result, out, "JPEG", kw,
                                    max_bytes=50 * 1024 ** 2,
                                    emit=lambda *_: None)
    check("上限宽松时质量仍为 95", q == 95 and ok, f"q={q}")

    # 2c 上限很小：必须降质量且不超过上限
    limit = 120 * 1024
    q, n, ok = save_with_size_limit(result, out, "JPEG", kw, max_bytes=limit,
                                    emit=lambda *_: None)
    check("上限收紧后体积达标", n <= limit and ok, f"{format_size(n)} <= {format_size(limit)}")
    check("上限收紧后质量下降", q < 95, f"q={q}")

    # 2d 最大性：q 已是能满足上限的最高质量
    q_ok = enc(q) <= limit
    q_next_over = enc(q + 1) > limit if q < 100 else True
    check("选出的质量是「能通过上限的最高档」", q_ok and q_next_over,
          f"q={q} 满足={q_ok} q+1超限={q_next_over}")

    # 2e 上限小于最低质量能达到的体积：不该报错，只是给出提示
    tiny = 1024
    q, n, ok = save_with_size_limit(result, out, "JPEG", kw, max_bytes=tiny,
                                    emit=lambda *_: None)
    check("上限过小时不抛异常且标记未满足", (not ok) and out.exists(),
          f"q={q} 大小={format_size(n)}")


# ------------------------------------- 3. process_directory：后缀与单图模式
def test_single_and_suffix(images):
    print("\n=== 3. 单图输入与文件名后缀 ===")
    src = images[0]

    # 3a 传文件列表 + 后缀
    out1 = WORK / "out_single"
    res = process_directory(
        input_dir=str(src), output_dir=str(out1), target_ratio=(4, 3),
        border_color=(0, 0, 0), border_percent=0.02,
        input_files=[src], name_suffix="_bdd",
        log=lambda *_: None, progress=None,
    )
    produced = sorted(p.name for p in out1.iterdir()) if out1.is_dir() else []
    check("单图模式成功", res["ok"] and res["success"] == 1)
    check("输出名带 _bdd 后缀", produced == [src.stem + "_bdd" + src.suffix],
          str(produced))

    # 3b 自定义后缀
    out2 = WORK / "out_suffix"
    process_directory(
        input_dir=str(src), output_dir=str(out2), target_ratio=(4, 3),
        border_color=(0, 0, 0), border_percent=0.02,
        input_files=[src], name_suffix="_custom", log=lambda *_: None,
    )
    produced = sorted(p.name for p in out2.iterdir())
    check("自定义后缀生效", produced == [src.stem + "_custom" + src.suffix],
          str(produced))

    # 3c 只传单个文件路径（不传 input_files）
    out3 = WORK / "out_filepath"
    process_directory(
        input_dir=str(src), output_dir=str(out3), target_ratio=(4, 3),
        border_color=(0, 0, 0), border_percent=0.02, name_suffix="_p",
        log=lambda *_: None,
    )
    produced = sorted(p.name for p in out3.iterdir())
    check("input_dir 直接给文件也能处理",
          produced == [src.stem + "_p" + src.suffix], str(produced))

    # 3d 目录模式不加后缀（保持原文件名，向后兼容）
    srcdir = WORK / "in_dir"
    out4 = WORK / "out_dir"
    res = process_directory(
        input_dir=str(srcdir), output_dir=str(out4), target_ratio=(4, 3),
        border_color=(0, 0, 0), border_percent=0.02, log=lambda *_: None,
    )
    names = sorted(p.name for p in out4.iterdir()) if out4.is_dir() else []
    expect = sorted(p.name for p in srcdir.iterdir())
    check("目录模式保持原文件名（不加后缀）", names == expect,
          f"{names} vs {expect}")
    check("目录模式处理全部图片", res["success"] == len(expect))

    # 3e 空后缀 + 输出到原目录 -> 必须报错，不能覆盖原图
    same = WORK / "in_same"
    same.mkdir(exist_ok=True)
    target = same / "x.jpg"
    shutil.copy2(images[0], target)
    before = target.stat().st_size
    res = process_directory(
        input_dir=str(target), output_dir=str(same), target_ratio=(4, 3),
        border_color=(0, 0, 0), border_percent=0.02,
        input_files=[target], name_suffix="", log=lambda *_: None,
    )
    after = target.stat().st_size
    check("空后缀 + 同目录：拒绝覆盖原图", (not res["ok"]) and before == after)


# ------------------------------------------ 4. 目录批处理时的体积上限
def test_batch_with_limit(images):
    print("\n=== 4. 批量 + 体积上限 ===")
    srcdir = WORK / "in_dir"

    # 先测出「即使降到 q=1 也仍然要这么大」的下限，
    # 再把上限设在它之上 —— 保证这个上限是可达的，测的才是"能否达标"。
    with Image.open(images[2]) as im:
        im.load()
        r = add_border_to_image(im, (4, 3), (0, 0, 0), 0.02)
        kw = build_save_kwargs(im, "JPEG", 95)
    floor = len(_encode_bytes(r, "JPEG", dict(kw, quality=1)))
    limit = int(floor * 1.6)

    out = WORK / "out_capped"
    logs = []
    res = process_directory(
        input_dir=str(srcdir), output_dir=str(out), target_ratio=(4, 3),
        border_color=(0, 0, 0), border_percent=0.02, max_bytes=limit,
        log=lambda m, l="info": logs.append((l, m)),
    )
    files = {p.name: p.stat().st_size for p in out.iterdir()} if out.is_dir() else {}
    jpegs = {k: v for k, v in files.items() if k.lower().endswith((".jpg", ".jpeg"))}
    over = {k: format_size(v) for k, v in jpegs.items() if v > limit}
    check("批量处理成功", res["ok"], str(res["errors"]))
    check(f"JPEG 产物都不超过上限（{format_size(limit)}）", not over, str(over))
    check("JPEG 产物确实降了质量",
          any("q=" in m and "q=95" not in m for l, m in logs if l == "ok"),
          "日志中没有降质量的记录")

    # PNG 是无损格式：给一个肯定达不到的上限，应提示而不是失败
    out_png = WORK / "out_png_capped"
    logs_png = []
    res_png = process_directory(
        input_dir=str(srcdir), output_dir=str(out_png), target_ratio=(4, 3),
        border_color=(0, 0, 0), border_percent=0.02, output_format="png",
        max_bytes=1024,
        log=lambda m, l="info": logs_png.append((l, m)),
    )
    check("PNG + 上限：不失败", res_png["ok"], str(res_png["errors"]))
    check("PNG + 上限：给出无损格式无法压缩的提示",
          any(l == "warn" and "无损" in m for l, m in logs_png),
          f"警告数={sum(1 for l, _ in logs_png if l == 'warn')}")


# ------------------------------------------------------------ 5. GUI 层
def test_gui(images):
    print("\n=== 5. GUI 层 ===")
    try:
        import tkinter as tk

        import bordd_gui as gui
    except Exception as e:
        check("GUI 可导入", False, str(e))
        return

    try:
        root = tk.Tk()
    except Exception as e:
        check("GUI 可创建窗口", False, str(e))
        return

    app = gui.AddBorderApp(root)
    root.update()
    check("GUI 构建成功", True)
    check("新增控件齐全",
          all(hasattr(app, n) for n in
              ("btn_pick_files", "ent_suffix", "ent_max_size")))

    srcdir = WORK / "in_dir"
    app._set_input_dir(srcdir)
    root.update()
    check("目录模式下后缀框禁用",
          str(app.ent_suffix.cget("state")) == "disabled")
    check("目录模式输出目录为 <目录名>_bordered",
          app.var_output.get().endswith("in_dir_bordered"), app.var_output.get())

    app._set_input_files(images)
    root.update()
    check("单图模式下后缀框启用",
          str(app.ent_suffix.cget("state")) == "normal")
    check("单图模式输出目录 = 图片所在目录",
          Path(app.var_output.get()) == images[0].parent, app.var_output.get())
    check("多选时保留全部文件", len(app._selected_files) == len(images),
          f"{len(app._selected_files)}/{len(images)}")

    # 参数收集
    out = WORK / "gui_out"
    out.mkdir(exist_ok=True)
    app.var_output.set(str(out))
    app.var_suffix.set("_g")
    app.var_max_size.set("0.8")
    app._sync_enabled_states()
    opts = app._collect_options()
    check("_collect_options 返回参数", isinstance(opts, dict))
    if isinstance(opts, dict):
        check("input_files 已传入", len(opts.get("input_files") or []) == len(images))
        check("name_suffix 已传入", opts.get("name_suffix") == "_g")
        check("max_bytes 已换算",
              opts.get("max_bytes") == int(0.8 * 1024 ** 2),
              str(opts.get("max_bytes")))

    # 真正跑一遍 worker
    app._start()
    deadline = time.time() + 180
    while time.time() < deadline:
        root.update()
        time.sleep(0.05)
        if app._worker is None:
            break
    root.update()
    produced = sorted(p.name for p in out.iterdir()) if out.is_dir() else []
    check("GUI 处理完成", len(produced) == len(images), str(produced))
    over = [p.name for p in out.iterdir()
            if p.stat().st_size > int(0.8 * 1024 ** 2)]
    check("GUI 产物都满足体积上限", not over, str(over))
    root.destroy()


def main() -> int:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    images = make_images(WORK / "in_dir")

    test_parse_size()
    test_size_limit(images)
    test_single_and_suffix(images)
    test_batch_with_limit(images)
    test_gui(images)

    print("-" * 66)
    if FAILS:
        print(f"失败 {len(FAILS)} 项：")
        for f in FAILS:
            print(f"  · {f}")
        return 1
    print("全部通过 [OK]")
    return 0


if __name__ == "__main__":
    sys.exit(main())

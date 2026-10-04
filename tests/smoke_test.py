#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bordd GUI 冒烟测试：构建窗口、跑一遍真实处理、校验产物。

不依赖人工点击：构造界面 → 注入参数 → 后台处理 → 断言输出文件存在。
用法（在仓库根目录）：python tests/smoke_test.py
"""
import os
import shutil
import sys
import time
from pathlib import Path

# tests/ 的上一级才是源码所在目录
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

import bordd_gui as gui
from bordd import list_images, parse_ratio, process_directory

FAILURES = []

# Windows 控制台默认 GBK，强制 UTF-8 以免中文/符号打印报错
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def check(label, cond, extra=""):
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {label}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(label)


def make_images(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    specs = [
        ("wide.jpg", (1600, 900), "RGB"),
        ("tall.jpg", (900, 1600), "RGB"),
        ("square.png", (1000, 1000), "RGB"),
        ("rgb.png", (640, 480), "RGBA"),
        ("gray.jpg", (800, 600), "L"),
    ]
    for name, size, mode in specs:
        img = Image.new(mode, size, (200, 90, 60) if mode == "RGB" else None)
        if mode == "RGB":
            # 加点结构，便于肉眼确认没有拉伸
            for x in range(0, size[0], 40):
                for y in range(0, size[1], 40):
                    img.putpixel((x, y), (20, 160, 220))
        path = root / name
        if path.suffix.lower() in (".jpg", ".jpeg"):
            img.convert("RGB").save(path, quality=95)
        else:
            img.save(path)
    return specs


def main() -> int:
    # 工作目录放在仓库内：受限沙箱里子进程只能写工作区，
    # 而且失败时便于直接查看中间产物。
    work_root = Path(__file__).resolve().parent.parent / "_smoke_work"
    if work_root.exists():
        shutil.rmtree(work_root, ignore_errors=True)
    tmp = work_root
    src = tmp / "in"
    out = tmp / "out"
    print(f"工作目录: {tmp}")
    specs = make_images(src)
    check("生成测试图片", len(list_images(src)) == len(specs),
          f"{len(list_images(src))}/{len(specs)} 张")

    # ---------- 1. 界面能否构建 ----------
    try:
        import tkinter as tk
        root = tk.Tk()
    except Exception as e:
        print(f"无法创建 Tk 窗口（无图形环境？）：{e}")
        return 2

    gui._apply_theme(root)
    app = gui.AddBorderApp(root)
    root.update_idletasks()
    root.update()
    check("GUI 窗口构建成功", True)

    # ---------- 2. 控件状态联动 ----------
    app.var_no_border.set(True)
    root.update()
    app._sync_enabled_states()
    check("纯压缩模式下禁用比例下拉",
          str(app.cmb_ratio.cget("state")) == "disabled",
          f"state={app.cmb_ratio.cget('state')}")
    app.var_no_border.set(False)
    app._sync_enabled_states()
    check("加边框模式下启用比例下拉",
          str(app.cmb_ratio.cget("state")) == "normal")

    # JPEG 质量只在 keep 模式可用
    app.var_format.set(gui.FORMAT_LABELS["png"])
    app._sync_enabled_states()
    check("PNG 模式下禁用 JPEG 质量",
          str(app.spn_quality.cget("state")) == "disabled")
    app.var_format.set(gui.FORMAT_LABELS["keep"])
    app._sync_enabled_states()
    check("keep 模式下启用 JPEG 质量",
          str(app.spn_quality.cget("state")) == "normal")

    # 边框滑杆对齐到 0.5%
    app.var_border_pct.set(2.0374)
    app._on_border_slide()
    check("边框宽度对齐 0.5% 步进",
          abs(app.var_border_pct.get() - 2.0) < 1e-9,
          f"值={app.var_border_pct.get()}")

    # ---------- 3. 参数校验 ----------
    app.var_input.set(str(src))
    app.var_output.set(str(out))
    app.var_ratio.set("4:3")
    app.var_color.set("black")
    app.var_border_pct.set(2.0)
    app.var_format.set(gui.FORMAT_LABELS["keep"])
    app.var_no_border.set(False)
    root.update()
    opts = app._collect_options()
    check("_collect_options 返回参数", isinstance(opts, dict), str(opts and opts.keys()))
    check("比例解析为 (4,3)", opts and opts["target_ratio"] == (4, 3))
    check("边框比例 0.02", opts and abs(opts["border_percent"] - 0.02) < 1e-9)

    # 非法比例必须被 parse_ratio 拒绝
    try:
        parse_ratio("abc")
        check("非法比例被拒绝", False)
    except ValueError as e:
        check("非法比例被拒绝", True, str(e))
    check("自定义比例 21:9 可用", parse_ratio("21:9") == (21, 9))

    # ---------- 4. 预览能否生成 ----------
    app._render_preview()
    deadline = time.time() + 20
    got_preview = False
    while time.time() < deadline:
        root.update()
        app._drain_queue()
        if app._preview_image is not None:
            got_preview = True
            break
        time.sleep(0.05)
    check("预览图生成成功", got_preview,
          f"信息={app.var_preview_info.get().splitlines()[:2]}")
    root.update()

    # ---------- 5. 真实处理（GUI 用的那条路径） ----------
    for fmt_key, ext, label in (("keep", None, "保持原格式"),
                                ("png", ".png", "统一 PNG"),
                                ("pdf", ".pdf", "PDF 容器")):
        target = tmp / f"out_{fmt_key}"
        src_dir = src if fmt_key != "pdf" else src
        logs = []
        prog = []
        if fmt_key == "pdf":
            # PDF 只支持 JPEG，单独准备一个纯 JPEG 目录
            src_dir = tmp / "in_jpeg"
            src_dir.mkdir(exist_ok=True)
            for p in src.glob("*.jpg"):
                (src_dir / p.name).write_bytes(p.read_bytes())
        res = process_directory(
            input_dir=str(src_dir),
            output_dir=str(target),
            target_ratio=(4, 3),
            border_color=(0, 0, 0),
            border_percent=0.02,
            output_format=fmt_key,
            jpeg_quality=95,
            no_border=False,
            log=lambda m, l="info": logs.append((l, m)),
            progress=lambda d, t, n: prog.append((d, t)),
        )
        produced = sorted(p.name for p in target.iterdir()) if target.is_dir() else []
        check(f"处理完成[{label}]", res["success"] > 0 and res["fail"] == 0,
              f"成功={res['success']} 失败={res['fail']} 产物={len(produced)}")
        check(f"进度回调[{label}]", len(prog) == res["total"] and res["total"] > 0,
              f"{len(prog)}/{res['total']}")
        check(f"日志回调[{label}]", len(logs) > 0, f"{len(logs)} 条")

        # 校验画布比例确实被改成了 4:3
        if fmt_key in ("keep", "png"):
            sample = target / ("wide.jpg" if fmt_key == "keep" else "wide.png")
            if sample.exists():
                with Image.open(sample) as im:
                    w, h = im.size
                check(f"画布比例 4:3[{label}]", abs(w / h - 4 / 3) < 0.005,
                      f"{w}x{h} = {w/h:.4f}")

    # 纯压缩模式：画布必须等于原图
    out_c = tmp / "out_compress"
    res = process_directory(
        input_dir=str(src), output_dir=str(out_c),
        target_ratio=(1, 1), border_color=(0, 0, 0),
        border_percent=0.02, output_format="keep",
        jpeg_quality=90, no_border=True,
    )
    with Image.open(src / "wide.jpg") as a, Image.open(out_c / "wide.jpg") as b:
        check("纯压缩模式画布 = 原图", a.size == b.size, f"{a.size} vs {b.size}")
    check("纯压缩模式成功", res["ok"], str(res["errors"]))

    # ---------- 6. 输出=输入 的防覆盖保护 ----------
    res_same = process_directory(
        input_dir=str(src), output_dir=str(src),
        target_ratio=(4, 3), border_color=(0, 0, 0),
        border_percent=0.02, output_format="png", jpeg_quality=95,
    )
    check("拒绝输出目录 = 输入目录", not res_same["ok"])

    # ---------- 7. 取消功能 ----------
    out_x = tmp / "out_cancel"
    calls = {"n": 0}

    def cancel_after_two():
        calls["n"] += 1
        return calls["n"] > 2

    res_cancel = process_directory(
        input_dir=str(src), output_dir=str(out_x),
        target_ratio=(4, 3), border_color=(0, 0, 0),
        border_percent=0.02, output_format="keep", jpeg_quality=95,
        should_cancel=cancel_after_two,
    )
    check("取消后标记 cancelled", res_cancel["cancelled"] is True,
          f"成功={res_cancel['success']} 总数={res_cancel['total']}")

    # ---------- 8. 异常钩子（防止 windowed 构建静默退出） ----------
    check("已安装全局异常钩子", sys.excepthook is not None)
    check("已安装 Tk 回调异常钩子",
          getattr(root, "report_callback_exception", None) is not None)

    # 保存一张界面截图供人工查看
    try:
        root.update()
        root.after(200, root.quit)
        root.mainloop()
    except Exception:
        pass

    try:
        root.destroy()
    except Exception:
        pass

    print("-" * 60)
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for f in FAILURES:
            print(f"  · {f}")
        return 1
    print("全部通过 [OK]")
    print(f"测试产物保留在：{tmp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

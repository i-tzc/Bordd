#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""驱动真实 GUI 到指定状态并截图，用于人工/自动核对界面布局。

用法：
    python tests/capture_gui.py <输入图片目录> <输出png路径> [场景]
场景：border（默认）| noborder | pdf | error
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import tkinter as tk

import bordd_gui as gui


def settle(root, app, seconds=3.0):
    """跑满事件循环，让预览线程的结果回到界面。"""
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.03)


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src = Path(sys.argv[1])
    out_png = Path(sys.argv[2])
    scene = sys.argv[3] if len(sys.argv) > 3 else "border"

    gui._enable_hidpi()
    root = tk.Tk()
    root.title(f"{gui.APP_TITLE}  v{gui.VERSION}")
    gui._install_crash_handlers(root)
    gui._apply_theme(root)
    try:
        root.tk.call("tk", "scaling", root.winfo_fpixels("1i") / 72.0)
    except Exception:
        pass

    app = gui.AddBorderApp(root)
    gui._fit_and_center(root)
    root.update()

    app.var_input.set(str(src))
    app.var_output.set(str(src.parent / f"{src.name}_bordered"))
    app.var_ratio.set("4:3")
    app.var_color.set("black")
    app.var_border_pct.set(4.0)
    app._on_border_slide()

    if scene == "noborder":
        app.var_no_border.set(True)
        app.var_format.set(gui.FORMAT_LABELS["keep"])
    elif scene == "pdf":
        app.var_format.set(gui.FORMAT_LABELS["pdf"])
        app.var_color.set("white")
    elif scene == "error":
        app.var_ratio.set("这不是比例")
    else:
        app.var_format.set(gui.FORMAT_LABELS["keep"])

    app._sync_enabled_states()
    app._on_input_changed()
    settle(root, app, 4.0)

    root.update_idletasks()
    root.lift()
    root.attributes("-topmost", True)
    root.update()
    time.sleep(0.5)
    root.update()

    x = root.winfo_rootx()
    y = root.winfo_rooty()
    ww = root.winfo_width()
    hh = root.winfo_height()
    print(f"窗口区域: {x},{y} {ww}x{hh}")

    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=(x, y, x + ww, y + hh), all_screens=True)
        out_png.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_png)
        print(f"截图已保存: {out_png}  尺寸={img.size}")
    except Exception as e:
        print(f"截图失败: {e}")
        root.destroy()
        return 1

    root.attributes("-topmost", False)
    root.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())

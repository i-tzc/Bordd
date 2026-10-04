#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在正在运行的 Bordd GUI 里点「开始处理」，验证冻结版端到端可用。

按钮靠颜色定位（主按钮是 #2d7ff9），比硬编码坐标更稳。

用法：python click_start.py [超时秒数] [输出目录]
"""
import ctypes
import ctypes.wintypes as wt
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

user32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

EnumWindows = user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def find_window(fragment="Bordd"):
    found = []

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if fragment in buf.value:
            r = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            if r.right - r.left > 400 and r.bottom - r.top > 400:
                found.append((hwnd, buf.value, r))
        return True

    EnumWindows(EnumWindowsProc(cb), 0)
    return found


def find_button(img):
    """在截图里定位主按钮（#2d7ff9）。

    用「紧色差 + 行直方图」而不是简单求重心：
    窗口截图会带上 Windows 的不可见投影边，边角可能混入后面其它程序的
    像素；只要有一颗偏蓝的像素，求重心就会被带偏。这里要求颜色紧贴主按钮
    的蓝，并找出匹配像素最多的那一条横向色带。
    """
    px = img.convert("RGB").load()
    w, h = img.size

    target = (45, 127, 249)
    tol = 22

    row_counts = [0] * h
    row_xs = [[] for _ in range(h)]
    for y in range(h):
        cnt = 0
        xs = row_xs[y]
        for x in range(w):
            r, g, b = px[x, y]
            if abs(r - target[0]) <= tol and abs(g - target[1]) <= tol \
                    and abs(b - target[2]) <= tol:
                cnt += 1
                xs.append(x)
        row_counts[y] = cnt

    # 按钮是一整条宽色带：至少 40 像素宽
    band = [y for y, c in enumerate(row_counts) if c >= 40]
    if not band:
        return None

    # 取最宽的那段连续行
    best = []
    cur = [band[0]]
    for y in band[1:]:
        if y == cur[-1] + 1:
            cur.append(y)
        else:
            if len(cur) > len(best):
                best = cur
            cur = [y]
    if len(cur) > len(best):
        best = cur

    if len(best) < 8:          # 按钮至少有 8 行高
        return None

    y_lo, y_hi = best[0], best[-1]
    y_mid = (y_lo + y_hi) // 2
    xs = row_xs[y_mid] or [x for yy in best for x in row_xs[yy]]
    if not xs:
        return None
    x_lo, x_hi = min(xs), max(xs)
    width, height = x_hi - x_lo, y_hi - y_lo
    if width < 3 * max(height, 1):     # 按钮是扁的，不是方块
        return None

    return (x_lo + x_hi) // 2, y_mid, width * height


def click(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.25)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.08)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def main() -> int:
    timeout = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    wins = find_window()
    if not wins:
        print("未找到 GUI 窗口")
        return 1
    hwnd, title, rect = wins[0]
    print(f"窗口: {title!r} rect=({rect.left},{rect.top})-({rect.right},{rect.bottom})")

    # 置前，保证点击落在 GUI 上
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.8)
    user32.GetWindowRect(hwnd, ctypes.byref(rect))

    from PIL import ImageGrab
    img = ImageGrab.grab(
        bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True)

    hit = find_button(img)
    if not hit:
        print("未在界面上找到「开始处理」按钮（蓝色区域）")
        return 1
    bx, by, area = hit
    sx, sy = rect.left + bx, rect.top + by
    print(f"按钮图像坐标=({bx},{by}) 面积≈{area} → 屏幕坐标=({sx},{sy})")

    click(sx, sy)
    print("已点击「开始处理」")

    # 等待输出目录出现产物
    baseline = 0
    if out_dir and out_dir.is_dir():
        baseline = len(list(out_dir.iterdir()))

    deadline = time.time() + timeout
    produced = []
    while time.time() < deadline:
        time.sleep(0.5)
        if out_dir and out_dir.is_dir():
            produced = [p for p in out_dir.iterdir() if p.is_file()]
            if len(produced) > baseline:
                break

    if out_dir:
        print(f"输出目录: {out_dir}")
        print(f"产物数量: {len(produced)}")
        for p in sorted(produced)[:12]:
            print(f"  · {p.name}  ({p.stat().st_size} 字节)")
    return 0 if produced else 1


if __name__ == "__main__":
    sys.exit(main())

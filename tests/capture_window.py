#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""截取一个正在运行的窗口（按窗口标题匹配），用于验证 GUI。

优先用 Win32 的 PrintWindow + PW_RENDERFULLCONTENT 直接取窗口自身内容，
这样即使窗口被别的程序挡住、或系统拒绝把窗口置前，也能截到正确画面。
失败时退回 ImageGrab 屏幕区域截图。

用法：python tests/capture_window.py "<窗口标题片段>" <输出png>
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
gdi32 = ctypes.windll.gdi32

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

EnumWindows = user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

PW_RENDERFULLCONTENT = 0x00000002
BI_RGB = 0
DIB_RGB_COLORS = 0
SRCCOPY = 0x00CC0020


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


def find_window(fragment: str):
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
            if r.right - r.left > 300 and r.bottom - r.top > 300:
                found.append((hwnd, buf.value, r))
        return True

    EnumWindows(EnumWindowsProc(cb), 0)
    return found


def grab_printwindow(hwnd, rect):
    """用 PrintWindow 抓窗口自身内容（不受遮挡影响）。"""
    from PIL import Image

    w = rect.right - rect.left
    h = rect.bottom - rect.top

    hdc_win = user32.GetWindowDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    gdi32.SelectObject(hdc_mem, hbmp)

    ok = user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)
    if not ok:
        ok = user32.PrintWindow(hwnd, hdc_mem, 0)

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h          # 负数 = 自上而下
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB

    buf = ctypes.create_string_buffer(w * h * 4)
    got = gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), DIB_RGB_COLORS)

    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(hwnd, hdc_win)

    if not ok or got == 0:
        return None
    return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    fragment, out = sys.argv[1], Path(sys.argv[2])

    wins = find_window(fragment)
    if not wins:
        print(f"未找到标题包含「{fragment}」的可见窗口")
        return 1

    hwnd, title, rect = wins[0]
    print(f"找到窗口: {title!r}  hwnd={hwnd}  "
          f"rect=({rect.left},{rect.top})-({rect.right},{rect.bottom})")

    out.parent.mkdir(parents=True, exist_ok=True)

    img = None
    try:
        img = grab_printwindow(hwnd, rect)
        if img is not None:
            print("抓取方式: PrintWindow（窗口自身内容）")
    except Exception as e:
        print(f"PrintWindow 失败（{e}），改用屏幕截图")

    if img is None:
        user32.SetForegroundWindow(hwnd)
        time.sleep(1.2)
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        from PIL import ImageGrab
        img = ImageGrab.grab(
            bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True)
        print("抓取方式: ImageGrab（屏幕区域）")

    img.save(out)
    print(f"已保存: {out}  尺寸={img.size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

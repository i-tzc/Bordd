#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bordd 图形界面（Tkinter / ttk，跨平台：Windows + macOS）。

为什么需要它：
    bordd.py 是纯命令行程序（必需参数 -i / -o）。双击打包好的
    Bordd.exe 时，argparse 发现缺少必需参数，打印用法后以退出码 2
    结束；控制台窗口随进程结束而关闭 —— 表现就是“闪一下就没了”。
    本模块提供窗口界面，双击即可使用，无需任何命令行参数。

设计要点：
    - 只依赖标准库 tkinter + 已安装的 Pillow，不引入新依赖；
    - 界面语言中文，字体按平台自动选择（Windows: 微软雅黑，macOS: 苹方）；
    - 支持高 DPI 屏幕（Windows 下开启 DPI 感知并同步 tk 缩放）；
    - 处理在后台线程执行，界面不卡死，可随时“停止”；
    - 窗口版（--windowed）没有控制台，因此安装了全局异常钩子：
      任何未捕获异常都会弹窗提示并写入日志文件，避免再次“静默闪退”。

用法：
    python bordd_gui.py
"""

import os
import queue
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

# 保证以「脚本」或「PyInstaller 冻结」两种方式都能导入核心模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bordd import (  # noqa: E402
    PRESET_RATIOS,
    ProcessingCancelled,
    add_border_to_image,
    compute_canvas_size,
    get_border_color,
    list_images,
    parse_ratio,
    process_directory,
)

APP_NAME = "Bordd"          # 对话框标题、日志目录名
APP_TITLE = "Bordd"         # 窗口标题栏只显示 Bordd
VERSION = "1.2.0"

# 边框宽度滑杆范围（百分比）
BORDER_PCT_MIN = 0.0
BORDER_PCT_MAX = 40.0
BORDER_PCT_DEFAULT = 2.0

# 预览区基准尺寸（逻辑像素，会按 DPI 缩放）
PREVIEW_W = 300
PREVIEW_H = 212

FORMAT_LABELS = {
    "keep": "保持原格式（JPEG 重编码 / 其余无损）",
    "png": "统一无损 PNG",
    "pdf": "PDF 容器保真（仅 JPEG，字节级无损）",
}
FORMAT_KEYS = list(FORMAT_LABELS.keys())


# --------------------------------------------------------------------------
# 平台辅助
# --------------------------------------------------------------------------
def _log_dir() -> Path:
    """崩溃日志目录（用户可写，且卸载程序后仍便于排查）。"""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / APP_NAME
    return Path.home() / ".local" / "state" / APP_NAME


def _enable_hidpi() -> None:
    """Windows 上开启 DPI 感知，避免高分屏字体模糊。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            # PROCESS_PER_MONITOR_DPI_AWARE
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _resource_path(relative: str) -> Path:
    """定位随程序打包的资源文件。

    PyInstaller onefile 运行时会把 datas 解压到 sys._MEIPASS；
    未打包时则相对本文件所在目录查找。
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / relative
    return Path(__file__).resolve().parent / relative


def _set_window_icon(root: tk.Tk) -> None:
    """设置窗口 / 任务栏图标；资源缺失时静默跳过（不影响功能）。"""
    if sys.platform == "win32":
        ico = _resource_path("assets/Bordd.ico")
        if ico.exists():
            try:
                root.iconbitmap(default=str(ico))
                return
            except Exception:
                pass

    for candidate in ("assets/icon_png/icon_256.png", "assets/icon_png/icon_64.png"):
        png = _resource_path(candidate)
        if not png.exists():
            continue
        try:
            from PIL import Image, ImageTk

            with Image.open(png) as im:
                photo = ImageTk.PhotoImage(im.convert("RGBA"))
            root.iconphoto(True, photo)
            root._dsh_icon_ref = photo  # 必须持有引用，否则被 GC 后图标消失
            return
        except Exception:
            continue


def _open_in_file_manager(path: Path) -> None:
    """用系统文件管理器打开目录。"""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _default_output_dir(input_dir: Path) -> Path:
    """默认输出目录：输入目录同级的 <名字>_bordered。"""
    return input_dir.parent / f"{input_dir.name}_bordered"


def _format_ratio(w: int, h: int) -> str:
    """把 (w, h) 写成最简比；比数太复杂时退回小数形式。

    例：4000:3000 -> 4:3；2074:1556 -> 1.333（而不是难读的 1037:778）。
    """
    from math import gcd

    if w <= 0 or h <= 0:
        return "?"
    g = gcd(int(w), int(h))
    a, b = int(w) // g, int(h) // g
    if a <= 40 and b <= 40:
        return f"{a}:{b}"
    return f"{w / h:.3f}"


# --------------------------------------------------------------------------
# 主窗口
# --------------------------------------------------------------------------
class AddBorderApp(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=(12, 10))
        self.master: tk.Tk = master

        self.grid(row=0, column=0, sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)

        # ---- 状态 ----
        self._log_queue: "queue.Queue[tuple]" = queue.Queue()
        self._cancel_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._preview_job: str | None = None
        self._preview_image = None  # 必须持有引用，否则被 GC 后不显示
        self._preview_token = 0

        # 按 DPI 计算缩放系数（96 DPI == 1.0）
        try:
            self._ui_scale = max(1.0, master.winfo_fpixels("1i") / 96.0)
        except Exception:
            self._ui_scale = 1.0

        # ---- 变量 ----
        self.var_input = tk.StringVar()
        self.var_output = tk.StringVar()
        self.var_ratio = tk.StringVar(value="4:3")
        self.var_color = tk.StringVar(value="black")
        self.var_border_pct = tk.DoubleVar(value=BORDER_PCT_DEFAULT)
        self.var_border_pct_label = tk.StringVar(value=f"{BORDER_PCT_DEFAULT:.1f}%")
        self.var_format = tk.StringVar(value=FORMAT_LABELS["keep"])
        self.var_jpeg_quality = tk.IntVar(value=95)
        self.var_no_border = tk.BooleanVar(value=False)
        self.var_open_after = tk.BooleanVar(value=False)
        self.var_status = tk.StringVar(value="就绪")
        self.var_preview_info = tk.StringVar(value="选择输入目录后显示预览")

        self._build_ui()
        self._bind_events()
        self._sync_enabled_states()
        self._draw_placeholder_preview()

        # 轮询后台线程消息
        self.after(80, self._drain_queue)

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        row = 0

        # ============ 1. 目录 ============
        dirs = ttk.LabelFrame(self, text=" 目录 ", padding=(10, 8))
        dirs.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        dirs.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(dirs, text="输入目录：").grid(row=0, column=0, sticky="w", pady=3)
        self.ent_input = ttk.Entry(dirs, textvariable=self.var_input)
        self.ent_input.grid(row=0, column=1, sticky="ew", padx=(4, 6), pady=3)
        ttk.Button(dirs, text="浏览…", width=9,
                   command=self._pick_input).grid(row=0, column=2, pady=3)

        ttk.Label(dirs, text="输出目录：").grid(row=1, column=0, sticky="w", pady=3)
        self.ent_output = ttk.Entry(dirs, textvariable=self.var_output)
        self.ent_output.grid(row=1, column=1, sticky="ew", padx=(4, 6), pady=3)
        self.btn_output = ttk.Button(dirs, text="浏览…", width=9,
                                     command=self._pick_output)
        self.btn_output.grid(row=1, column=2, pady=3)

        self.lbl_found = ttk.Label(dirs, text="尚未选择输入目录", foreground="#666666")
        self.lbl_found.grid(row=2, column=0, columnspan=3, sticky="w", pady=(5, 0))

        # ============ 2. 设置（双列排布，压缩高度以适配 1366×768 等小屏）============
        settings = ttk.LabelFrame(self, text=" 处理设置 ", padding=(10, 8))
        settings.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)
        row += 1

        # -- 第 0 行：目标比例 / 输出格式 --
        ttk.Label(settings, text="目标比例：").grid(row=0, column=0, sticky="w", pady=3)
        self.cmb_ratio = ttk.Combobox(
            settings, textvariable=self.var_ratio, width=9,
            values=list(PRESET_RATIOS.keys()),
        )
        self.cmb_ratio.grid(row=0, column=1, sticky="w", padx=(4, 18), pady=3)

        ttk.Label(settings, text="输出格式：").grid(row=0, column=2, sticky="w", pady=3)
        self.cmb_format = ttk.Combobox(
            settings, textvariable=self.var_format, state="readonly",
            values=[FORMAT_LABELS[k] for k in FORMAT_KEYS],
        )
        self.cmb_format.grid(row=0, column=3, sticky="ew", padx=(4, 0), pady=3)

        self.lbl_ratio_hint = ttk.Label(
            settings, text="可选预设，或直接输入自定义比例，如 21:9",
            foreground="#666666",
        )
        self.lbl_ratio_hint.grid(row=1, column=1, columnspan=3, sticky="w",
                                 padx=(4, 0), pady=(0, 3))

        # -- 第 2 行：边框颜色 / JPEG 质量 --
        ttk.Label(settings, text="边框颜色：").grid(row=2, column=0, sticky="w", pady=3)
        color_box = ttk.Frame(settings)
        color_box.grid(row=2, column=1, sticky="w", padx=(4, 18), pady=3)
        self.rdo_black = ttk.Radiobutton(color_box, text="黑色", value="black",
                                         variable=self.var_color)
        self.rdo_black.pack(side="left")
        self.rdo_white = ttk.Radiobutton(color_box, text="白色", value="white",
                                         variable=self.var_color)
        self.rdo_white.pack(side="left", padx=(10, 0))
        self.swatch = tk.Canvas(color_box, width=18, height=18, highlightthickness=1,
                                highlightbackground="#9a9a9a")
        self.swatch.pack(side="left", padx=(10, 0))
        self._swatch_item = self.swatch.create_rectangle(0, 0, 18, 18, fill="black")

        ttk.Label(settings, text="JPEG 质量：").grid(row=2, column=2, sticky="w", pady=3)
        self.spn_quality = ttk.Spinbox(settings, from_=1, to=100, width=6,
                                       textvariable=self.var_jpeg_quality)
        self.spn_quality.grid(row=2, column=3, sticky="w", padx=(4, 0), pady=3)

        # -- 第 3 行：边框宽度 --
        ttk.Label(settings, text="边框宽度：").grid(row=3, column=0, sticky="w", pady=3)
        self.scl_border = ttk.Scale(
            settings, from_=BORDER_PCT_MIN, to=BORDER_PCT_MAX,
            variable=self.var_border_pct, command=self._on_border_slide,
        )
        self.scl_border.grid(row=3, column=1, columnspan=2, sticky="ew",
                             padx=(4, 8), pady=3)
        ttk.Label(settings, textvariable=self.var_border_pct_label, width=6,
                  anchor="e").grid(row=3, column=3, sticky="e", pady=3)

        ttk.Label(settings, text="（长边每侧占原图长边的比例）",
                  foreground="#666666").grid(row=4, column=1, columnspan=3,
                                             sticky="w", padx=(4, 0), pady=(0, 4))

        # -- 第 5 行：开关 --
        self.chk_no_border = ttk.Checkbutton(
            settings, text="不加边框（纯压缩，画布 = 原图）",
            variable=self.var_no_border, command=self._sync_enabled_states,
        )
        self.chk_no_border.grid(row=5, column=0, columnspan=2, sticky="w", pady=(2, 0))

        self.chk_open_after = ttk.Checkbutton(
            settings, text="完成后打开输出目录", variable=self.var_open_after)
        self.chk_open_after.grid(row=5, column=2, columnspan=2, sticky="w",
                                 padx=(4, 0), pady=(2, 0))

        # ============ 3. 预览 ============
        preview = ttk.LabelFrame(self, text=" 效果预览 ", padding=(10, 8))
        preview.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        preview.columnconfigure(0, weight=1)
        row += 1

        pw = int(PREVIEW_W * self._ui_scale)
        ph = int(PREVIEW_H * self._ui_scale)
        self.canvas = tk.Canvas(preview, width=pw, height=ph,
                                background="#f4f4f4", highlightthickness=1,
                                highlightbackground="#c8c8c8")
        self.canvas.grid(row=0, column=0, sticky="w")
        self.lbl_preview_info = ttk.Label(preview, textvariable=self.var_preview_info,
                                          foreground="#444444", justify="left")
        self.lbl_preview_info.grid(row=0, column=1, sticky="nw", padx=(12, 0))

        # ============ 4. 执行 ============
        actions = ttk.Frame(self)
        actions.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        actions.columnconfigure(2, weight=1)
        row += 1

        self.btn_start = tk.Button(
            actions, text="开始处理", width=13, command=self._start,
            background="#2d7ff9", foreground="white",
            activebackground="#1c66d6", activeforeground="white",
            relief="flat", borderwidth=0, highlightthickness=0,
            font=("", 10, "bold"), cursor="hand2", padx=6, pady=4,
        )
        self.btn_start.grid(row=0, column=0)
        self.btn_stop = ttk.Button(actions, text="停止", width=10,
                                   command=self._stop, state="disabled")
        self.btn_stop.grid(row=0, column=1, padx=(8, 0))

        self.pbar = ttk.Progressbar(actions, mode="determinate", maximum=100)
        self.pbar.grid(row=0, column=2, sticky="ew", padx=(14, 10))

        self.lbl_status = ttk.Label(actions, textvariable=self.var_status, width=22,
                                    anchor="e")
        self.lbl_status.grid(row=0, column=3, sticky="e")

        # ============ 5. 日志 ============
        logframe = ttk.LabelFrame(self, text=" 运行日志 ", padding=(8, 6))
        logframe.grid(row=row, column=0, sticky="nsew")
        logframe.columnconfigure(0, weight=1)
        logframe.rowconfigure(0, weight=1)
        self.rowconfigure(row, weight=1)
        row += 1

        self.txt_log = tk.Text(logframe, height=7, wrap="none", state="disabled",
                               background="#1f1f1f", foreground="#e6e6e6",
                               insertbackground="#e6e6e6", borderwidth=0,
                               font=("Consolas", 9) if sys.platform == "win32"
                               else ("Menlo", 10))
        self.txt_log.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(logframe, orient="vertical", command=self.txt_log.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb = ttk.Scrollbar(logframe, orient="horizontal", command=self.txt_log.xview)
        hsb.grid(row=1, column=0, sticky="ew")
        self.txt_log.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.txt_log.tag_configure("ok", foreground="#7ddc7d")
        self.txt_log.tag_configure("error", foreground="#ff8080")
        self.txt_log.tag_configure("warn", foreground="#ffd479")
        self.txt_log.tag_configure("info", foreground="#e6e6e6")
        self.txt_log.tag_configure("head", foreground="#79c0ff")

        self._append_log(f"{APP_NAME} v{VERSION} 图形界面已启动。", "head")
        self._append_log("请选择输入目录，确认设置后点击「开始处理」。", "info")

    # ------------------------------------------------------------------
    # 事件绑定
    # ------------------------------------------------------------------
    def _bind_events(self) -> None:
        self.var_input.trace_add("write", lambda *_: self._on_input_changed())
        self.var_ratio.trace_add("write", lambda *_: self._schedule_preview())
        self.var_color.trace_add("write", lambda *_: (self._update_swatch(),
                                                     self._schedule_preview()))
        self.var_border_pct.trace_add("write", lambda *_: self._schedule_preview())
        self.var_format.trace_add("write", lambda *_: (self._sync_enabled_states(),
                                                       self._schedule_preview()))
        self.var_no_border.trace_add("write", lambda *_: self._schedule_preview())
        self.var_jpeg_quality.trace_add("write", lambda *_: self._sync_enabled_states())

        self.master.bind("<Return>", lambda _e: self._start())
        self.canvas.bind("<Configure>", lambda _e: self._schedule_preview())

    # ------------------------------------------------------------------
    # 目录选择
    # ------------------------------------------------------------------
    def _pick_input(self) -> None:
        initial = self.var_input.get().strip() or str(Path.home())
        chosen = filedialog.askdirectory(title="选择输入图片目录", initialdir=initial)
        if chosen:
            self.var_input.set(os.path.normpath(chosen))
            if not self.var_output.get().strip():
                self.var_output.set(str(_default_output_dir(Path(chosen))))

    def _pick_output(self) -> None:
        initial = self.var_output.get().strip()
        if not initial:
            raw_in = self.var_input.get().strip()
            initial = (str(_default_output_dir(Path(raw_in))) if raw_in
                       else str(Path.home()))
        chosen = filedialog.askdirectory(title="选择输出目录", initialdir=initial)
        if chosen:
            self.var_output.set(os.path.normpath(chosen))

    def _on_input_changed(self) -> None:
        raw = self.var_input.get().strip()
        if not raw:
            self.lbl_found.configure(text="尚未选择输入目录", foreground="#666666")
        else:
            p = Path(raw)
            if not p.is_dir():
                self.lbl_found.configure(text=f"目录不存在：{raw}", foreground="#c0392b")
            else:
                images = list_images(p)
                if images:
                    self.lbl_found.configure(
                        text=f"找到 {len(images)} 张受支持的图片", foreground="#1e7e34")
                else:
                    self.lbl_found.configure(
                        text="该目录下没有受支持的图片（png / jpg / jpeg / webp / bmp / tif / tiff）",
                        foreground="#b9770e")
        self._schedule_preview()

    def _sync_enabled_states(self) -> None:
        """按当前选项启用/禁用相关控件。"""
        no_border = self.var_no_border.get()
        idle = self._worker is None or not self._worker.is_alive()

        # 纯压缩模式下比例 / 颜色 / 边框宽度无意义
        state_ratio = "disabled" if no_border else "normal"
        self.cmb_ratio.configure(state=state_ratio)
        for w in (self.rdo_black, self.rdo_white, self.scl_border):
            w.configure(state="disabled" if no_border else "normal")

        # JPEG 质量只在 keep 模式下有意义
        fmt = self._selected_format()
        self.spn_quality.configure(
            state="normal" if (fmt == "keep" and idle) else "disabled")

        # PDF 模式提示
        if fmt == "pdf" and not no_border:
            self.lbl_ratio_hint.configure(
                text="  PDF 保真模式仅支持 JPEG 输入；边框为矢量矩形",
                foreground="#b9770e")
        else:
            self.lbl_ratio_hint.configure(
                text="  可选预设，或直接输入自定义比例，如 21:9",
                foreground="#666666")

        self.ent_input.configure(state="normal" if idle else "disabled")
        self.ent_output.configure(state="normal" if idle else "disabled")
        self.btn_output.configure(state="normal" if idle else "disabled")
        self.cmb_format.configure(state="readonly" if idle else "disabled")
        self.chk_no_border.configure(state="normal" if idle else "disabled")
        self.btn_start.configure(state="normal" if idle else "disabled")
        if idle and no_border:
            self.cmb_ratio.configure(state="disabled")

    def _selected_format(self) -> str:
        label = self.var_format.get()
        for key, text in FORMAT_LABELS.items():
            if text == label:
                return key
        return "keep"

    def _update_swatch(self) -> None:
        self.swatch.itemconfigure(
            self._swatch_item,
            fill="black" if self.var_color.get() == "black" else "white",
        )

    def _on_border_slide(self, _value=None) -> None:
        # 对齐到 0.5% 步进，避免滑杆出现 2.0374% 之类的数值
        snapped = round(self.var_border_pct.get() * 2) / 2
        if abs(snapped - self.var_border_pct.get()) > 1e-9:
            self.var_border_pct.set(snapped)
        self.var_border_pct_label.set(f"{snapped:.1f}%")

    # ------------------------------------------------------------------
    # 预览
    # ------------------------------------------------------------------
    def _schedule_preview(self) -> None:
        """去抖：连续改动只在最后一次之后 220ms 真正重绘。"""
        if self._preview_job is not None:
            try:
                self.after_cancel(self._preview_job)
            except Exception:
                pass
        self._preview_job = self.after(220, self._render_preview)

    def _preview_box(self) -> tuple:
        w = max(int(self.canvas.winfo_width()), 1)
        h = max(int(self.canvas.winfo_height()), 1)
        if w <= 1 or h <= 1:
            w = int(PREVIEW_W * self._ui_scale)
            h = int(PREVIEW_H * self._ui_scale)
        return w, h

    def _draw_placeholder_preview(self) -> None:
        self.canvas.delete("all")
        w, h = self._preview_box()
        self.canvas.create_text(
            w // 2, h // 2, text="预览区\n\n选择输入目录后\n显示第一张图片的加边框效果",
            fill="#8a8a8a", justify="center",
            font=("", int(10 * self._ui_scale)),
        )

    def _render_preview(self) -> None:
        self._preview_job = None
        fmt = self._selected_format()

        raw_in = self.var_input.get().strip()
        images = list_images(raw_in) if raw_in else []
        if not images:
            self._draw_placeholder_preview()
            if fmt == "pdf":
                self.var_preview_info.set("PDF 保真模式：\n仅支持 JPEG 输入")
            else:
                self.var_preview_info.set("选择输入目录后显示预览")
            return

        first = images[0]

        # 解析比例（失败则退回占位图）
        ratio = None
        if not self.var_no_border.get():
            try:
                ratio = parse_ratio(self.var_ratio.get().strip())
            except ValueError as e:
                self._draw_placeholder_preview()
                self.canvas.create_text(
                    self._preview_box()[0] // 2, self._preview_box()[1] - 22,
                    text=str(e), fill="#c0392b", font=("", int(9 * self._ui_scale)),
                )
                self.var_preview_info.set(f"比例无效：{e}")
                return

        # 后台线程做解码 + 缩放，主线程只负责显示
        self._preview_token += 1
        token = self._preview_token
        border_color = get_border_color(self.var_color.get())
        pct = max(0.0, self.var_border_pct.get() / 100.0)
        no_border = self.var_no_border.get()
        box = self._preview_box()

        def work():
            try:
                from PIL import Image
                with Image.open(first) as im:
                    im.load()
                    src_size = im.size
                    src_mode = im.mode
                    # 预览用缩略图：比例与成品完全一致，但快得多
                    thumb = im.copy()
                thumb.thumbnail((1400, 1400), Image.LANCZOS)
                if no_border:
                    result = thumb
                    out_size = src_size
                else:
                    # 缩略图只用于显示；显示的尺寸数字必须按原图真实计算，
                    # 否则会误报成缩略图算出来的小尺寸
                    cw, ch = compute_canvas_size(
                        src_size[0], src_size[1],
                        ratio[0], ratio[1], pct,
                    )
                    out_size = (max(cw, src_size[0]), max(ch, src_size[1]))
                    result = add_border_to_image(thumb, ratio, border_color, pct)
                if result.mode not in ("RGB", "RGBA", "L"):
                    result = result.convert("RGB")
                # 按比例铺满预览框（留 10px 边距）
                avail_w = max(box[0] - 20, 20)
                avail_h = max(box[1] - 20, 20)
                scale = min(avail_w / result.width, avail_h / result.height)
                disp_w = max(int(result.width * scale), 1)
                disp_h = max(int(result.height * scale), 1)
                shown = result.resize((disp_w, disp_h), Image.LANCZOS)
                payload = (first.name, src_size, src_mode, out_size,
                           shown, disp_w, disp_h)
            except Exception as e:  # 预览失败不能影响主流程
                payload = ("error", str(e))
            self._log_queue.put(("preview", token, payload))

        threading.Thread(target=work, daemon=True).start()

    def _apply_preview(self, token: int, payload) -> None:
        if token != self._preview_token:
            return  # 已有更新的预览请求，丢弃这次结果
        if isinstance(payload, tuple) and payload and payload[0] == "error":
            self._draw_placeholder_preview()
            self.var_preview_info.set(f"预览失败：{payload[1]}")
            return

        try:
            from PIL import ImageTk
        except Exception as e:
            self.var_preview_info.set(f"缺少 Pillow 的 ImageTk，无法预览：{e}")
            return

        src_name, src_size, src_mode, out_size, shown, disp_w, disp_h = payload
        self._preview_image = ImageTk.PhotoImage(shown)

        self.canvas.delete("all")
        w, h = self._preview_box()
        x = (w - disp_w) // 2
        y = (h - disp_h) // 2

        # 输出画布外框（即加边框后的成品）
        self.canvas.create_rectangle(x, y, x + disp_w, y + disp_h,
                                     outline="#2d7ff9", width=2)
        self.canvas.create_image(x, y, image=self._preview_image, anchor="nw")

        info_lines = [
            f"文件：{src_name}",
            f"源图：{src_size[0]}×{src_size[1]}  ({_format_ratio(*src_size)})  模式 {src_mode}",
        ]
        if self.var_no_border.get():
            info_lines.append("纯压缩模式：画布 = 原图尺寸，不加边框")
        else:
            try:
                rw, rh = parse_ratio(self.var_ratio.get().strip())
                target_text = f"{rw}:{rh}"
            except ValueError:
                target_text = "?"
            info_lines.append(
                f"输出：{out_size[0]}×{out_size[1]}  (目标 {target_text}，"
                f"实际 {_format_ratio(*out_size)})")
            info_lines.append(
                f"边框：{'黑色' if self.var_color.get() == 'black' else '白色'}"
                f"  每侧 {self.var_border_pct.get():.1f}%")
        if self._selected_format() == "pdf":
            if Path(src_name).suffix.lower() in (".jpg", ".jpeg"):
                info_lines.append("PDF 保真：JPEG 字节原样嵌入（逐字节一致）")
            else:
                info_lines.append("⚠ PDF 模式只支持 JPEG 输入")
        info_lines.append("蓝框 = 输出画布范围，预览为缩略图。")
        self.var_preview_info.set("\n".join(info_lines))

    # ------------------------------------------------------------------
    # 日志 / 进度
    # ------------------------------------------------------------------
    def _append_log(self, message: str, level: str = "info") -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", f"[{stamp}] {message}\n", level)
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _drain_queue(self) -> None:
        try:
            while True:
                msg = self._log_queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    _, text, level = msg
                    self._append_log(text, level)
                elif kind == "progress":
                    _, done, total, _name = msg
                    self.pbar.configure(maximum=max(total, 1), value=done)
                    self.var_status.set(f"处理中 {done}/{total}")
                elif kind == "preview":
                    _, token, payload = msg
                    self._apply_preview(token, payload)
                elif kind == "done":
                    _, payload = msg
                    self._on_finished(payload)
        except queue.Empty:
            pass
        self.after(80, self._drain_queue)

    # ------------------------------------------------------------------
    # 开始 / 停止
    # ------------------------------------------------------------------
    def _collect_options(self):
        """校验并收集参数；出错时弹窗并返回 None。"""
        raw_in = self.var_input.get().strip()
        raw_out = self.var_output.get().strip()

        if not raw_in:
            messagebox.showwarning(APP_NAME, "请先选择输入图片目录。", parent=self.master)
            return None
        in_path = Path(raw_in)
        if not in_path.is_dir():
            messagebox.showerror(APP_NAME, f"输入目录不存在：\n{raw_in}",
                                 parent=self.master)
            return None

        images = list_images(in_path)
        if not images:
            messagebox.showwarning(
                APP_NAME,
                "输入目录中没有受支持的图片。\n\n"
                "支持的格式：png / jpg / jpeg / webp / bmp / tif / tiff",
                parent=self.master)
            return None

        if not raw_out:
            raw_out = str(_default_output_dir(in_path))
            self.var_output.set(raw_out)
        out_path = Path(raw_out)
        try:
            if out_path.resolve() == in_path.resolve():
                messagebox.showerror(
                    APP_NAME,
                    "输出目录不能与输入目录相同。\n\n"
                    "输出文件会与源文件重名并覆盖源文件。",
                    parent=self.master)
                return None
        except OSError:
            pass

        no_border = self.var_no_border.get()
        fmt = self._selected_format()

        target_ratio = None
        if not no_border:
            try:
                target_ratio = parse_ratio(self.var_ratio.get().strip())
            except ValueError as e:
                messagebox.showerror(APP_NAME, f"{e}\n\n示例：4:3、1:1、21:9",
                                     parent=self.master)
                return None
            if target_ratio[0] / target_ratio[1] <= 0:
                messagebox.showerror(APP_NAME, "比例数值必须为正数。", parent=self.master)
                return None

        if no_border:
            target_ratio = (1, 1)  # 占位，处理逻辑会忽略

        border_pct = max(BORDER_PCT_MIN, min(BORDER_PCT_MAX,
                                             self.var_border_pct.get())) / 100.0
        if not (0 <= border_pct < 0.5):
            messagebox.showerror(APP_NAME, "边框宽度必须在 0% ~ 40% 之间。",
                                 parent=self.master)
            return None

        try:
            quality = int(self.var_jpeg_quality.get())
        except (tk.TclError, ValueError):
            quality = 95
        quality = max(1, min(100, quality))

        if fmt == "pdf" and not no_border:
            non_jpeg = [p.name for p in images if p.suffix.lower() not in (".jpg", ".jpeg")]
            if non_jpeg:
                preview = "、".join(non_jpeg[:5])
                more = f" 等 {len(non_jpeg)} 个" if len(non_jpeg) > 5 else ""
                if not messagebox.askyesno(
                    APP_NAME,
                    "PDF 保真模式仅支持 JPEG 输入。\n\n"
                    f"以下文件会被跳过并记为失败：\n{preview}{more}\n\n"
                    "确定继续吗？（建议改用「统一无损 PNG」）",
                    parent=self.master,
                ):
                    return None

        return {
            "input_dir": str(in_path),
            "output_dir": str(out_path),
            "target_ratio": target_ratio,
            "border_color": get_border_color(self.var_color.get()),
            "border_percent": border_pct,
            "output_format": fmt,
            "jpeg_quality": quality,
            "no_border": no_border,
            "image_count": len(images),
        }

    def _start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return  # 已在处理中
        opts = self._collect_options()
        if opts is None:
            return

        self._cancel_event.clear()
        self.pbar.configure(value=0, maximum=max(opts["image_count"], 1))
        self.var_status.set(f"处理中 0/{opts['image_count']}")
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

        self._append_log("=" * 62, "head")
        self._append_log(f"输入目录：{opts['input_dir']}", "head")
        self._append_log(f"输出目录：{opts['output_dir']}", "head")
        self._append_log(f"待处理：{opts['image_count']} 张图片", "head")
        self._append_log("=" * 62, "head")

        emit = lambda text, level="info": self._log_queue.put(("log", text, level))  # noqa: E731
        report = lambda done, total, name: self._log_queue.put(  # noqa: E731
            ("progress", done, total, name))
        cancel = self._cancel_event.is_set

        self._worker = threading.Thread(
            target=self._run_worker,
            args=(opts, emit, report, cancel),
            daemon=True,
        )
        self._worker.start()
        self._sync_enabled_states()
        self.btn_stop.configure(state="normal")

    def _run_worker(self, opts, emit, report, cancel) -> None:
        try:
            result = process_directory(
                input_dir=opts["input_dir"],
                output_dir=opts["output_dir"],
                target_ratio=opts["target_ratio"],
                border_color=opts["border_color"],
                border_percent=opts["border_percent"],
                output_format=opts["output_format"],
                jpeg_quality=opts["jpeg_quality"],
                no_border=opts["no_border"],
                log=emit,
                progress=report,
                should_cancel=cancel,
            )
        except ProcessingCancelled:
            result = {"ok": False, "total": 0, "success": 0, "fail": 0,
                      "cancelled": True, "errors": [], "output_dir": opts["output_dir"]}
        except Exception as e:
            emit(f"发生未预期的错误：{e}", "error")
            emit(traceback.format_exc(), "error")
            result = {"ok": False, "total": 0, "success": 0, "fail": 0,
                      "cancelled": False, "errors": [(None, str(e))],
                      "output_dir": opts["output_dir"]}
        self._log_queue.put(("done", result))

    def _stop(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            self._cancel_event.set()
            self.btn_stop.configure(state="disabled")
            self.var_status.set("正在停止…")
            self._append_log("已请求停止，将在当前图片处理完成后中止…", "warn")

    def _on_finished(self, result: dict) -> None:
        self._worker = None
        self.btn_stop.configure(state="disabled")
        self._sync_enabled_states()

        total = result.get("total", 0)
        success = result.get("success", 0)
        fail = result.get("fail", 0)
        cancelled = result.get("cancelled", False)

        if cancelled:
            self.pbar.configure(value=0)
            self.var_status.set(f"已中止：成功 {success}")
            self._append_log(
                f"已中止：成功 {success} 张，失败 {fail} 张（共 {total} 张）", "warn")
        elif fail:
            self.pbar.configure(value=self.pbar.cget("maximum"))
            self.var_status.set(f"完成：成功 {success}，失败 {fail}")
            self._append_log(f"处理结束：成功 {success} 张，失败 {fail} 张。", "error")
        else:
            self.pbar.configure(value=self.pbar.cget("maximum"))
            self.var_status.set(f"完成：成功 {success}")
            self._append_log(f"处理结束：成功 {success} 张，全部完成。", "ok")

        out_dir = Path(result.get("output_dir", ""))
        if success and out_dir:
            if self.var_open_after.get():
                try:
                    _open_in_file_manager(out_dir)
                except Exception as e:
                    self._append_log(f"无法打开输出目录：{e}", "warn")
            else:
                self._append_log(f"输出目录：{out_dir}", "info")

        errors = result.get("errors") or []
        if errors:
            detail = "\n".join(
                f"· {name or '(未知文件)'}: {msg}" for name, msg in errors[:10])
            if len(errors) > 10:
                detail += f"\n… 另有 {len(errors) - 10} 个失败"
            self._append_log("失败明细：\n" + detail, "error")


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------
def _install_crash_handlers(root: tk.Tk) -> None:
    """窗口版没有控制台，把未捕获异常变成弹窗 + 日志文件。"""
    log_path = _log_dir() / "error.log"

    def report(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"\n===== {stamp} =====\n{text}")
        except Exception:
            pass
        try:
            messagebox.showerror(
                APP_NAME,
                f"程序遇到一个错误：\n\n{exc_type.__name__}: {exc}\n\n"
                f"详细信息已写入：\n{log_path}",
            )
        except Exception:
            pass

    sys.excepthook = report
    root.report_callback_exception = report


def _apply_theme(root: tk.Tk) -> None:
    """平台相关的字体与主题微调。"""
    family = None
    if sys.platform == "win32":
        family = "Microsoft YaHei UI"
    elif sys.platform == "darwin":
        family = "PingFang SC"

    if family:
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont",
                     "TkHeadingFont", "TkTooltipFont"):
            try:
                tkfont.nametofont(name).configure(family=family)
            except Exception:
                pass

    try:
        tkfont.nametofont("TkDefaultFont").configure(size=10)
    except Exception:
        pass

    style = ttk.Style(root)
    for theme in ("vista", "aqua", "clam"):
        if theme in style.theme_names():
            try:
                style.theme_use(theme)
            except Exception:
                pass
            break

    # 主按钮着色（不支持时静默忽略）
    try:
        style.configure("Accent.TButton", font=("", 10, "bold"))
    except Exception:
        pass


def _fit_and_center(root: tk.Tk) -> tuple:
    """按 DPI 设定窗口尺寸并居中；夹紧到屏幕内，避免小屏上超出边界。"""
    root.update_idletasks()
    k = root.winfo_fpixels("1i") / 96.0
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()

    min_w = min(int(700 * k), max(sw - 60, 480))
    min_h = min(int(560 * k), max(sh - 120, 400))
    root.minsize(min_w, min_h)

    w = min(max(root.winfo_reqwidth(), int(720 * k)), max(sw - 40, 480))
    h = min(max(root.winfo_reqheight(), int(620 * k)), max(sh - 70, 400))
    x = max((sw - w) // 2, 0)
    y = max((sh - h) // 3, 0)
    root.geometry(f"{w}x{h}+{x}+{y}")
    return w, h


def _bring_to_front(root: tk.Tk) -> None:
    """把窗口提到最前面。

    macOS 下从 .app 双击启动时，窗口偶尔开在其它程序后面，用户会以为没反应。
    这里用 Tk 自带方式抢一次焦点（短暂置顶后取消，不改变正常层叠行为）。
    """
    try:
        root.lift()
        root.focus_force()
        root.attributes("-topmost", True)
        root.after(350, lambda: root.attributes("-topmost", False))
    except Exception:
        pass


def main() -> int:
    _enable_hidpi()
    root = tk.Tk()
    root.title(APP_TITLE)

    _install_crash_handlers(root)
    _apply_theme(root)
    _set_window_icon(root)

    # 同步 tk 缩放与真实 DPI（让字体在高分屏上不模糊、不偏小）
    try:
        root.tk.call("tk", "scaling", root.winfo_fpixels("1i") / 72.0)
    except Exception:
        pass

    app = AddBorderApp(root)

    # 支持 `bordd_gui.py <输入目录>` 直接带参打开（例如右键“发送到”）
    if len(sys.argv) > 1:
        candidate = Path(sys.argv[1])
        if candidate.is_dir():
            app.var_input.set(str(candidate))
            app.var_output.set(str(_default_output_dir(candidate)))

    _fit_and_center(root)

    try:
        app._on_input_changed()  # 初始化目录状态与预览
    except Exception:
        pass

    # macOS：从 .app 双击启动时，主动把窗口提到最前面
    if sys.platform == "darwin":
        root.after(120, lambda: _bring_to_front(root))

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

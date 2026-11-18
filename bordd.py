#!/usr/bin/env python3
"""
为图像添加边框以统一不同尺寸图片的比例（零画质损失版）。

本文件是「核心逻辑 + 命令行入口」。
如果不想敲命令，请使用图形界面版 bordd_gui.py（打包后为
Bordd_gui.exe / Bordd.app），双击即可使用。

关于“双击闪退”：
  本程序是命令行工具，-i / --input 与 -o / --output 是必需参数。
  直接双击时没有参数，argparse 打印用法后以退出码 2 结束，控制台窗口
  随进程结束立即关闭，看起来就是“闪一下就没了”。这不是崩溃。
  现在双击启动会被识别出来，并暂停等待回车，以便看清提示。

功能：
  - 批量处理指定目录下的所有图片。
  - 支持目标比例：4:3, 3:4, 9:16, 16:9, 1:1，或自定义如 21:9。
  - 边框颜色可选：黑色或白色。
  - 核心策略：不缩放原图（零画质损失），仅在长边方向两侧各留固定比例
    （默认 10%）的边框，画布严格符合目标比例。
      · 原图更宽 -> 宽度方向两侧留边框
      · 原图更高 -> 高度方向两侧留边框
      · 比例相等 -> 仍按宽度方向留边框，保持风格统一
  - 原图在画布中居中。
  - 输出格式由 --format 控制：
      · keep（默认）：保持原格式，并按格式采用零/近零损失保存
          - JPEG: 默认 quality=95 + 4:4:4 采样（JPEG 本质有损；95 档对近无损
            源图体积约减半、视觉几乎无差，可用 --jpeg-quality 调整）
          - WebP: 无损模式；PNG / TIFF / BMP: 本身无损
          - 同时保留 EXIF、ICC 色彩配置、DPI 等元数据
      · png：统一输出为无损 PNG（像素级无损，保留 EXIF / ICC / 位深）
      · pdf：PDF 容器保真版——仅支持 JPEG 输入，把原始 JPEG 字节原样嵌入
          PDF（/DCTDecode 透传，不重编码，可逐字节校验），边框以矢量矩形
          绘制在图像四周
  - --no-border：不加任何边框，画布 = 原图尺寸，等价于纯图像压缩模式
      · keep 下按 --jpeg-quality 对 JPEG 重压缩（默认 q95），其余格式无损；
      · png 下为无损压缩优化；
      · 此模式下 --ratio / --color 被忽略。

用法示例：
  python bordd.py --input ./images --output ./output --ratio 4:3 --color black
  python bordd.py --input ./images --output ./output --ratio 1:1 --color white --border-percent 0.1
  python bordd.py -i ./photos -o ./result -r 21:9 -c black --border-percent 0.15
  python bordd.py -i ./photos -o ./result -r 4:3 --format png
  python bordd.py -i ./photos -o ./result -r 4:3 --format pdf
  python bordd.py -i ./photos -o ./compressed --no-border --jpeg-quality 90

v1.3 新增：
  · 输入可以是单个图片文件，输出名默认加 _bdd 后缀（可用 --suffix 自定义）；
  · --max-size 10MB 可限制单张输出体积，超出时自动逐个降低 JPEG 质量。
"""

import argparse
import io
import os
import re
import sys
from pathlib import Path

from PIL import Image


# 支持的图片扩展名
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}

# 支持的预设比例（宽:高）
PRESET_RATIOS = {
    "4:3": (4, 3),
    "3:4": (3, 4),
    "9:16": (9, 16),
    "16:9": (16, 9),
    "1:1": (1, 1),
}


def parse_ratio(ratio_str: str):
    """解析比例字符串，支持预设（如 4:3）和自定义（如 21:9）。"""
    if ratio_str in PRESET_RATIOS:
        return PRESET_RATIOS[ratio_str]
    if ":" not in ratio_str:
        raise ValueError(f"无效的比例格式: {ratio_str}，应为 W:H 格式，例如 4:3")
    parts = ratio_str.split(":")
    if len(parts) != 2:
        raise ValueError(f"无效的比例格式: {ratio_str}，应为 W:H 格式")
    try:
        w, h = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(f"无效的比例数值: {ratio_str}")
    if w <= 0 or h <= 0:
        raise ValueError(f"比例数值必须为正数: {ratio_str}")
    return (w, h)


def get_border_color(color_str: str):
    """根据颜色名称返回 PIL 颜色值。"""
    color_map = {
        "black": (0, 0, 0),
        "white": (255, 255, 255),
    }
    key = color_str.strip().lower()
    if key not in color_map:
        raise ValueError(f"不支持的颜色: {color_str}，可选: black 或 white")
    return color_map[key]


# 体积单位换算（1 KB = 1024 B）
_SIZE_UNITS = {
    "": 1, "B": 1,
    "K": 1024, "KB": 1024, "KIB": 1024,
    "M": 1024 ** 2, "MB": 1024 ** 2, "MIB": 1024 ** 2,
    "G": 1024 ** 3, "GB": 1024 ** 3, "GIB": 1024 ** 3,
}


def parse_size(text) -> int:
    """把体积字符串解析成字节数；空值或 0 表示“不限制”。

    支持：'10MB'、'500KB'、'1.5M'、'2G'、'10485760'（纯数字按字节）。
    """
    if text is None:
        return 0
    if isinstance(text, (int, float)):
        return max(int(text), 0)
    s = str(text).strip().upper().replace(" ", "")
    if not s:
        return 0
    m = re.fullmatch(r"([0-9]*\.?[0-9]+)([A-Z]*)", s)
    if not m:
        raise ValueError(
            f"无法识别的体积格式: {text}（示例：10MB、500KB、10485760）"
        )
    number, unit = m.group(1), m.group(2)
    if unit not in _SIZE_UNITS:
        raise ValueError(f"不支持的体积单位: {unit}（可用 KB / MB / GB）")
    return int(float(number) * _SIZE_UNITS[unit])


def format_size(nbytes: int) -> str:
    """把字节数显示成 '9.83 MB' 这样的短字符串。"""
    if nbytes >= 1024 ** 3:
        return f"{nbytes / 1024 ** 3:.2f} GB"
    if nbytes >= 1024 ** 2:
        return f"{nbytes / 1024 ** 2:.2f} MB"
    if nbytes >= 1024:
        return f"{nbytes / 1024:.1f} KB"
    return f"{nbytes} B"


def compute_canvas_size(img_w: int, img_h: int,
                        target_ratio_w: int, target_ratio_h: int,
                        border_percent: float = 0.1):
    """
    计算画布尺寸：在长边方向两侧各留 border_percent 比例的边框，
    画布严格符合目标比例，不缩放原图。

    参数：
        img_w, img_h: 原图尺寸
        target_ratio_w, target_ratio_h: 目标比例（宽, 高）
        border_percent: 长边方向每侧边框占原图长边的比例（默认 0.1，即每边 10%）

    返回：
        (canvas_w, canvas_h)
    """
    target = target_ratio_w / target_ratio_h
    current = img_w / img_h
    scale = 1 + 2 * border_percent  # 长边放大系数，如 10% -> 1.2

    if current > target:
        # 原图更宽 -> 宽度方向两侧留边框
        canvas_w = round(img_w * scale)
        canvas_h = round(canvas_w / target)
    elif current < target:
        # 原图更高 -> 高度方向两侧留边框
        canvas_h = round(img_h * scale)
        canvas_w = round(canvas_h * target)
    else:
        # 比例已相等，仍按宽度方向留边框，保持风格统一
        canvas_w = round(img_w * scale)
        canvas_h = round(canvas_w / target)

    return canvas_w, canvas_h


def _canvas_fill(mode: str, color):
    """把 (r,g,b) 边框颜色转成目标图像模式可接受的填充值。"""
    if mode in ("I", "I;16"):
        return int(color[0])
    if mode == "1":
        return 1 if color[0] > 127 else 0
    if mode == "L":
        return int(color[0])
    if mode == "P":
        return 0  # 调色板索引，画布随后复制源图调色板
    if mode in ("LA", "PA"):
        return (int(color[0]), 255)
    return color


def add_border_to_image(img: Image.Image,
                        target_ratio: tuple,
                        border_color,
                        border_percent: float = 0.1) -> Image.Image:
    """
    为单张图片添加固定比例边框，不缩放原图。

    参数：
        img: PIL Image 对象
        target_ratio: (w, h) 目标比例
        border_color: 边框颜色元组，如 (0,0,0)
        border_percent: 长边方向每侧边框占原图长边的比例（默认 0.1）

    返回：
        添加边框后的 PIL Image 对象（与原图模式一致）
    """
    ratio_w, ratio_h = target_ratio
    img_w, img_h = img.size

    canvas_w, canvas_h = compute_canvas_size(
        img_w, img_h, ratio_w, ratio_h, border_percent
    )

    # 安全兜底：防止浮点误差导致画布小于原图
    canvas_w = max(canvas_w, img_w)
    canvas_h = max(canvas_h, img_h)

    # 创建画布并居中粘贴（填充值按模式适配，避免 I;16/P 等模式报错）
    canvas = Image.new(
        img.mode, (canvas_w, canvas_h), _canvas_fill(img.mode, border_color)
    )
    if img.mode == "P":
        # 复制源图调色板，保证调色板索引对应的颜色不变
        canvas.putpalette(img.getpalette())
    paste_x = (canvas_w - img_w) // 2
    paste_y = (canvas_h - img_h) // 2
    canvas.paste(img, (paste_x, paste_y))
    return canvas


def build_save_kwargs(src_img: Image.Image,
                      save_format: str,
                      jpeg_quality: int = 95) -> dict:
    """
    构造"零信息损失"的保存参数。

    像素层面：
      - JPEG 只能有损重编码，默认 quality=95 + subsampling=0（4:4:4 不缩减
        色彩分辨率）：对近无损源图（Lightroom 100 导出等）体积约减半，
        视觉几乎无差；需要更高保真可用 --jpeg-quality 调高。
      - WebP 切到真正的无损模式（lossless=True）；
      - PNG / TIFF / BMP 本身无损，只做无损压缩优化。

    元数据层面：把源图的 EXIF、ICC 色彩配置、DPI 一并传给保存函数；
    不支持这些参数的格式会由 Pillow 自动忽略，不影响保存。
    """
    kwargs = {}
    if save_format == "JPEG":
        kwargs.update(quality=jpeg_quality, subsampling=0)
    elif save_format == "WEBP":
        kwargs["lossless"] = True
    elif save_format == "PNG":
        kwargs.update(compress_level=9, optimize=True)
    elif save_format == "TIFF":
        kwargs["compression"] = "tiff_lzw"

    for key in ("exif", "icc_profile", "dpi"):
        if key in src_img.info:
            kwargs[key] = src_img.info[key]
    return kwargs


def jpeg_to_pdf_lossless(src_path: Path,
                         out_path: Path,
                         target_ratio: tuple,
                         border_color,
                         border_percent: float = 0.02,
                         no_border: bool = False) -> None:
    """
    PDF 容器保真版：把 JPEG 的原始字节原样嵌入 PDF，不经过任何重编码。

    实现方式：
      - 读取源 JPEG 的完整文件字节，作为 PDF 图像流直接写入，声明
        /Filter /DCTDecode，因此 PDF 里的图像数据与源文件逐字节一致；
      - 边框是 PDF 矢量矩形（先铺底色、再画图像），不产生任何像素级修改；
      - 页面尺寸 = 带边框的画布尺寸，图像按原始分辨率居中放置。
      - no_border=True 时页面尺寸 = 原图尺寸，不画边框（纯 PDF 封装）。

    注意：
      - 仅支持 JPEG（含 RGB / 灰度 / CMYK）；其它格式请用 --format png。
      - PDF 本身不承载 EXIF，拍摄信息不会带进 PDF；要保留请用 --format png。
    """
    try:
        import pikepdf  # 延迟导入：仅在 --format pdf 时需要
    except ImportError:
        raise RuntimeError(
            "PDF 保真模式需要 pikepdf，请先安装：pip install pikepdf"
        ) from None

    with Image.open(src_path) as im:
        w, h = im.size  # 只读头部，不解码像素
        mode = im.mode

    colorspace = {
        "RGB": "/DeviceRGB",
        "L": "/DeviceGray",
        "CMYK": "/DeviceCMYK",
    }.get(mode)
    if colorspace is None:
        raise ValueError(f"不支持的 JPEG 色彩模式: {mode}；该文件请改用 --format png")

    if no_border:
        canvas_w, canvas_h = w, h
        paste_x, paste_y = 0, 0
    else:
        canvas_w, canvas_h = compute_canvas_size(
            w, h, target_ratio[0], target_ratio[1], border_percent
        )
        canvas_w = max(canvas_w, w)
        canvas_h = max(canvas_h, h)
        paste_x = (canvas_w - w) // 2
        paste_y = (canvas_h - h) // 2

    pdf = pikepdf.Pdf.new()

    # 原始 JPEG 字节直接入流（compress=False，确保字节不被改动）
    img = pdf.make_stream(src_path.read_bytes(), compress=False)
    img.Type = pikepdf.Name("/XObject")
    img.Subtype = pikepdf.Name("/Image")
    img.Filter = pikepdf.Name("/DCTDecode")
    img.Width = w
    img.Height = h
    img.BitsPerComponent = 8
    img.ColorSpace = pikepdf.Name(colorspace)

    page = pdf.add_blank_page(page_size=(canvas_w, canvas_h))
    # 注意：pikepdf 的 Dictionary 不支持关键字参数构造（会报 bad cast），
    # 这里用普通 dict 构造资源字典
    page.Resources = pikepdf.Dictionary({"/XObject": {"/Im0": img}})

    # 内容流：先铺满边框底色（no_border 时省略），再按原始尺寸把图像画在中央
    r, g, b = border_color
    if no_border:
        content = (
            "q\n"
            f"{w} 0 0 {h} 0 0 cm\n"
            "/Im0 Do\n"
            "Q\n"
        ).encode("ascii")
    else:
        content = (
            "q\n"
            f"{r / 255:.6f} {g / 255:.6f} {b / 255:.6f} rg\n"
            f"0 0 {canvas_w} {canvas_h} re\n"
            "f\n"
            "Q\n"
            "q\n"
            f"{w} 0 0 {h} {paste_x} {paste_y} cm\n"
            "/Im0 Do\n"
            "Q\n"
        ).encode("ascii")
    page.Contents = pdf.make_indirect(pikepdf.Stream(pdf, content))

    pdf.save(str(out_path), compress_streams=False)


def _encode_bytes(img, save_format: str, kwargs: dict) -> bytes:
    """把图片编码到内存，返回字节数据（便于反复试不同质量而不落盘）。"""
    buf = io.BytesIO()
    img.save(buf, format=save_format, **kwargs)
    return buf.getvalue()


def save_with_size_limit(img, out_path, save_format: str, kwargs: dict,
                         max_bytes: int = 0, minimum_quality: int = 1,
                         emit=None):
    """保存图片；给了体积上限时，在“不超过上限”的前提下选**最高**质量。

    实现思路（等价于“95 → 94 → 93 … 逐个试”，但快得多）：
        1. 先用设定质量编一次，没超限就直接保存 —— 绝大多数情况只编码 1 次；
        2. 超限则二分查找“还能满足上限的最高质量”（约 7 次编码），
           而不是从 95 一路线性试到 60（那要几十次）；
        3. 最后向上再确认一次，避免体积非严格单调导致漏掉更高档。

    只有 JPEG / WebP 这类“有质量旋钮”的格式能压体积；
    PNG 等无损格式无法通过质量调体积，仅在超限时给出提示。

    返回 (实际使用的质量, 最终字节数, 是否满足上限)。
    """
    log = emit or _default_log
    out_path = Path(out_path)

    # ---- 未设上限：按原样保存 ----
    if max_bytes <= 0:
        img.save(out_path, format=save_format, **kwargs)
        return kwargs.get("quality"), out_path.stat().st_size, True

    # ---- 上限对无损格式无效：照常保存并提示 ----
    if save_format not in ("JPEG", "WEBP"):
        img.save(out_path, format=save_format, **kwargs)
        size = out_path.stat().st_size
        if size > max_bytes:
            log(f"  提示：{out_path.name} 为 {format_size(size)}，"
                f"超过上限 {format_size(max_bytes)}；"
                f"但 {save_format} 是无损格式，无法通过降低质量来压缩", "warn")
        return kwargs.get("quality"), size, True

    start_quality = int(kwargs.get("quality", 95))
    start_quality = max(min(start_quality, 100), minimum_quality)

    # ---- 1) 设定质量直接达标 ----
    best_q = start_quality
    best_data = _encode_bytes(img, save_format, dict(kwargs, quality=best_q))
    if len(best_data) <= max_bytes:
        out_path.write_bytes(best_data)
        return best_q, len(best_data), True

    # ---- 2) 最低质量都超限：只能保存最低质量并告警 ----
    floor_data = _encode_bytes(img, save_format,
                               dict(kwargs, quality=minimum_quality))
    if len(floor_data) > max_bytes:
        out_path.write_bytes(floor_data)
        log(f"  提示：即使质量降到 {minimum_quality}，体积仍有 "
            f"{format_size(len(floor_data))}，超过上限 "
            f"{format_size(max_bytes)}（图片本身太大或上限过小）", "warn")
        return minimum_quality, len(floor_data), False

    best_q, best_data = minimum_quality, floor_data

    # ---- 3) 二分找“仍满足上限的最高质量” ----
    lo, hi = minimum_quality, start_quality - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        data = _encode_bytes(img, save_format, dict(kwargs, quality=mid))
        if len(data) <= max_bytes:
            if mid > best_q:
                best_q, best_data = mid, data
            lo = mid + 1
        else:
            hi = mid - 1

    # ---- 4) 兜底向上校正（最多几步，防止体积非严格单调）----
    for _ in range(4):
        if best_q >= start_quality:
            break
        nxt = best_q + 1
        data = _encode_bytes(img, save_format, dict(kwargs, quality=nxt))
        if len(data) <= max_bytes:
            best_q, best_data = nxt, data
        else:
            break

    out_path.write_bytes(best_data)
    return best_q, len(best_data), True


class ProcessingCancelled(Exception):
    """用户主动中止批处理时抛出（GUI 的“停止”按钮）。"""


def _default_log(message: str, level: str = "info") -> None:
    """CLI 默认日志：error/warn 走 stderr，其余走 stdout。"""
    if level in ("error", "warn"):
        print(message, file=sys.stderr)
    else:
        print(message)


def list_images(input_dir) -> list:
    """列出目录下所有受支持的图片文件（不递归）。"""
    input_path = Path(input_dir)
    if not input_path.is_dir():
        return []
    return sorted(
        (f for f in input_path.iterdir()
         if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS),
        key=lambda p: p.name.lower(),
    )


def process_directory(input_dir: str,
                      output_dir: str,
                      target_ratio: tuple,
                      border_color,
                      border_percent: float = 0.1,
                      output_format: str = "keep",
                      jpeg_quality: int = 95,
                      no_border: bool = False,
                      log=None,
                      progress=None,
                      should_cancel=None,
                      input_files=None,
                      name_suffix: str = "",
                      max_bytes: int = 0):
    """批量处理图片。

    输入有三种给法（优先级从高到低）：
        input_files  明确的文件列表（GUI 里「选择图片」走这条）
        input_dir    指向单个图片文件
        input_dir    指向目录 —— 扫描目录内的图片

    可选回调（GUI 使用；CLI 全部省略，行为与从前一致）：
        log(message, level="info")  输出一条日志，level ∈ info/ok/warn/error
        progress(done, total, name) 每处理完一张图片回调一次
        should_cancel() -> bool     返回 True 时在下一张图片之前中止

    name_suffix  输出文件名后缀（如 "_bdd"）；空字符串表示保持原文件名
    max_bytes    单张输出体积上限（字节）；0 表示不限制

    返回摘要 dict：
        {"ok": bool, "total": int, "success": int, "fail": int,
         "cancelled": bool, "errors": [(文件名, 错误信息), ...],
         "output_dir": str}
    """
    emit = _default_log if log is None else log

    def summary(ok, total=0, success=0, fail=0, cancelled=False, errors=None):
        return {
            "ok": ok,
            "total": total,
            "success": success,
            "fail": fail,
            "cancelled": cancelled,
            "errors": errors or [],
            "output_dir": str(output_dir),
        }

    input_path = Path(input_dir)
    output_path = Path(output_dir)

    # ---- 解析输入：文件列表 > 单个文件 > 目录 ----
    if input_files is None and input_path.is_file():
        input_files = [input_path]

    if input_files is not None:
        image_files = [Path(f) for f in input_files]
        if not image_files:
            emit("警告：没有指定任何图片文件。", "warn")
            return summary(False)
        missing = [f for f in image_files if not f.is_file()]
        if missing:
            names = "、".join(p.name for p in missing[:5])
            emit(f"错误：以下文件不存在: {names}", "error")
            return summary(False)
    else:
        if not input_path.exists():
            emit(f"错误：输入目录不存在: {input_dir}", "error")
            return summary(False)
        if not input_path.is_dir():
            emit(f"错误：输入路径既不是目录也不是文件: {input_dir}", "error")
            return summary(False)
        image_files = list_images(input_path)
        if not image_files:
            emit(f"警告：在 {input_dir} 中未找到支持的图片文件。", "warn")
            return summary(False)

    try:
        output_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        emit(f"错误：无法创建输出目录 {output_dir}: {e}", "error")
        return summary(False)

    # 规划输出文件名，并做防覆盖/防冲突检查
    plan = []
    for f in image_files:
        stem = f.stem + (name_suffix or "")
        if output_format == "png":
            out_name = stem + ".png"
        elif output_format == "pdf":
            out_name = stem + ".pdf"
        else:
            out_name = stem + f.suffix
        out_path = output_path / out_name
        if out_path.resolve() == f.resolve():
            emit(
                f"错误：输出文件与输入文件相同（请换一个输出目录，"
                f"或设置文件名后缀）: {f.name}",
                "error",
            )
            return summary(False, total=len(image_files))
        plan.append((f, out_path))
    names = [p.name for _, p in plan]
    if len(names) != len(set(names)):
        dups = sorted({n for n in names if names.count(n) > 1})
        emit(
            f"错误：{output_format} 模式下输出文件名冲突（a.jpg 与 a.png 会都变成 a.png）: "
            f"{', '.join(dups)}；请重命名源文件",
            "error",
        )
        return summary(False, total=len(image_files))

    emit(f"找到 {len(image_files)} 张图片，开始处理...")
    if no_border:
        emit("模式: 纯压缩（不加边框）")
        emit("目标比例: 忽略")
        emit("边框颜色: 忽略")
    else:
        emit(f"目标比例: {target_ratio[0]}:{target_ratio[1]}")
        emit(f"边框颜色: {border_color}")
        emit(f"长边每侧边框占比: {border_percent:.1%}")
    emit(f"输出格式: {output_format}")
    if output_format == "keep":
        emit(f"JPEG 质量: {jpeg_quality}")
    if name_suffix:
        emit(f"文件名后缀: {name_suffix}")
    if max_bytes > 0:
        emit(f"单张体积上限: {format_size(max_bytes)}（超限时自动降低质量）")
    emit("-" * 50)

    total = len(plan)
    success_count = 0
    fail_count = 0
    errors = []
    cancelled = False

    for index, (img_file, output_file) in enumerate(plan, start=1):
        if should_cancel is not None and should_cancel():
            cancelled = True
            emit("已中止：用户取消。", "warn")
            break
        try:
            if output_format == "pdf":
                if img_file.suffix.lower() not in (".jpg", ".jpeg"):
                    raise ValueError(
                        "PDF 保真模式仅支持 JPEG 输入，该文件请改用 --format png"
                    )
                jpeg_to_pdf_lossless(
                    img_file, output_file,
                    target_ratio, border_color, border_percent,
                    no_border,
                )
                with Image.open(img_file) as im:
                    src_size = im.size  # 只读头部，不加载像素
                emit(f"[OK] {img_file.name}  {src_size} -> PDF {output_file.name}", "ok")
                success_count += 1
                if progress is not None:
                    progress(index, total, img_file.name)
                continue

            with Image.open(img_file) as img:
                img.load()  # 强制加载，避免延迟加载问题
                if no_border:
                    result = img  # 纯压缩模式：画布 = 原图尺寸
                else:
                    result = add_border_to_image(
                        img, target_ratio, border_color, border_percent
                    )
                if output_format == "png":
                    save_format = "PNG"
                else:
                    save_format = Image.registered_extensions().get(
                        img_file.suffix.lower(), "PNG"
                    )
                # JPEG 不支持 RGBA/LA/P，PNG 不支持 CMYK，需转为兼容模式
                if save_format == "JPEG" and result.mode in ("RGBA", "LA", "P"):
                    result = result.convert("RGB")
                if save_format == "PNG" and result.mode == "CMYK":
                    result = result.convert("RGB")
                save_kwargs = build_save_kwargs(img, save_format, jpeg_quality)
                used_q, nbytes, _size_ok = save_with_size_limit(
                    result, output_file, save_format, save_kwargs,
                    max_bytes=max_bytes, emit=emit,
                )
                detail = save_format
                if save_format in ("JPEG", "WEBP"):
                    detail += f" q={used_q}"
                detail += f" {format_size(nbytes)}"
                emit(
                    f"[OK] {img_file.name}  {img.size} -> {result.size} ({detail})",
                    "ok",
                )
                success_count += 1
        except Exception as e:
            emit(f"[失败] {img_file.name}: {e}", "error")
            errors.append((img_file.name, str(e)))
            fail_count += 1
        if progress is not None:
            progress(index, total, img_file.name)

    emit("-" * 50)
    if cancelled:
        emit(f"已中止：成功 {success_count} 张，失败 {fail_count} 张")
    else:
        emit(f"处理完成：成功 {success_count} 张，失败 {fail_count} 张")
    emit(f"输出目录: {output_dir}")

    return summary(
        ok=(fail_count == 0 and not cancelled),
        total=total,
        success=success_count,
        fail=fail_count,
        cancelled=cancelled,
        errors=errors,
    )


def _bootloader_process_count() -> int:
    """返回「除自己以外，打包引导还额外占用几个进程」。

    PyInstaller 两个模式不一样：
      · onefile：引导进程先把程序解压到临时目录，再拉起真正跑 Python 的子
        进程，父进程一直等着 —— 所以多占 1 个；
      · onedir：引导进程就在本进程内，不额外起进程 —— 多占 0 个。

    区分办法：onedir 的 sys._MEIPASS 就是可执行文件旁边的 _internal/，
    onefile 的则在系统临时目录里。
    """
    if not getattr(sys, "frozen", False):
        return 0
    try:
        meipass = Path(getattr(sys, "_MEIPASS", "")).resolve()
        exe_dir = Path(sys.executable).resolve().parent
        if meipass.parent == exe_dir:
            return 0            # onedir
    except Exception:
        pass
    return 1                    # onefile（或判断不出来时按保守值）


def _launched_by_double_click() -> bool:
    """判断本进程是否由资源管理器“双击”启动（独占一个新建的控制台）。

    原理：统计当前控制台里挂着的进程数。
      · 双击运行时，Windows 为该程序新建一个控制台，里面只有它自己和
        打包引导进程；
      · 从 cmd / PowerShell / 批处理里调用时，控制台里还有父 shell，
        进程数会再多一个。

    这个判断只用于一件事：双击启动时不要把用法信息一闪而过地关掉。
    判断不出来时返回 False，行为与从前完全一致（安全降级）。
    """
    if os.name != "nt":
        return False
    try:
        import ctypes

        buf = (ctypes.c_uint32 * 16)()
        count = int(ctypes.windll.kernel32.GetConsoleProcessList(buf, 16))
    except Exception:
        return False
    if count <= 0:
        return False
    return count <= 1 + _bootloader_process_count()


def _pause_if_double_clicked() -> None:
    """双击启动时暂停，让用户能看清提示（否则窗口会立即消失）。"""
    if not _launched_by_double_click():
        return
    try:
        input("按回车键关闭此窗口…")
    except (EOFError, KeyboardInterrupt, OSError):
        pass


def main():
    parser = argparse.ArgumentParser(
        description="为图像添加边框以统一不同尺寸图片的比例（零画质损失版）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python Bordd.py --input ./images --output ./output --ratio 4:3 --color black\n"
            "  python Bordd.py -i ./photos -o ./result -r 1:1 -c white --border-percent 0.1\n"
            "  python Bordd.py -i ./photos -o ./result -r 21:9 -c black --border-percent 0.15\n"
            "  python Bordd.py -i ./photos -o ./result -r 4:3 -f png\n"
            "  python Bordd.py -i ./photos -o ./result -r 4:3 -f pdf\n"
            "  python Bordd.py -i ./photos -o ./compressed --no-border --jpeg-quality 90\n"
            "\n"
            "v1.3 新增:\n"
            "  python Bordd.py -i ./a.jpg -r 4:3                 # 单张图片，输出 a_bdd.jpg\n"
            "  python Bordd.py -i ./a.jpg -r 4:3 --suffix _out   # 自定义后缀\n"
            "  python Bordd.py -i ./photos -o ./out -r 4:3 --max-size 10MB  # 限制单张体积\n"
        ),
    )
    parser.add_argument(
        "-i", "--input", required=True,
        help="输入图片目录，或单个图片文件（v1.3 起支持文件）"
    )
    parser.add_argument(
        "--version", action="version", version="%(prog)s 1.3.0",
        help="显示版本号并退出"
    )
    parser.add_argument(
        "-o", "--output", default=None,
        help="输出目录（可省略：输入是文件时默认输出到同目录，"
             "是目录时默认输出到同级的 <目录名>_bordered）"
    )
    parser.add_argument(
        "-r", "--ratio", default=None,
        help=f"目标宽高比，支持预设: {', '.join(PRESET_RATIOS.keys())}，或自定义如 21:9；"
             "--no-border 模式下可省略"
    )
    parser.add_argument(
        "-c", "--color", default="black", choices=["black", "white"],
        help="边框颜色，可选 black（默认）或 white"
    )
    parser.add_argument(
        "--border-percent", type=float, default=0.02,
        help="长边方向每侧边框占原图长边的比例（默认 0.02，即每边 2%%）"
    )
    parser.add_argument(
        "-f", "--format", dest="output_format", default="keep",
        choices=["keep", "png", "pdf"],
        help=(
            "输出格式：keep=保持原格式（默认）；png=统一输出无损 PNG；"
            "pdf=PDF 容器保真版（仅 JPEG，原始字节原样嵌入，边框为矢量）"
        ),
    )
    parser.add_argument(
        "--jpeg-quality", type=int, default=95,
        help="keep 模式下 JPEG 重编码质量（默认 95；1-100，越高体积越大，"
             "近无损源图 q95 体积约为 q100 的一半）"
    )
    parser.add_argument(
        "--no-border", action="store_true",
        help="不加任何边框，画布 = 原图尺寸，等价于纯图像压缩（--ratio/--color 被忽略）"
    )
    parser.add_argument(
        "--suffix", default=None,
        help="输出文件名后缀（v1.3）。默认：输入为单个文件时用 _bdd，"
             "输入为目录时保持原文件名。传空字符串表示不加后缀"
    )
    parser.add_argument(
        "--max-size", dest="max_size", default=None, metavar="体积",
        help="单张输出体积上限（v1.3，可选）。如 10MB、500KB。"
             "超出时自动从 --jpeg-quality 往下降低质量，直到不超过上限。"
             "留空表示不限制。仅对 JPEG / WebP 有效"
    )

    # 双击启动（零参数）时给出明确指引并暂停：
    # 否则窗口会在打印用法后立即关闭，观感上就是“闪退”。
    if len(sys.argv) == 1 and _launched_by_double_click():
        parser.print_help()
        print()
        print("提示：本程序是命令行工具，必须指定参数才能运行。")
        print("      若想双击直接使用，请运行图形界面版：")
        print("        Windows : Bordd_gui.exe")
        print("        macOS   : Bordd.app")
        _pause_if_double_clicked()
        sys.exit(2)

    args = parser.parse_args()

    # ---- 输入到底是「单个文件」还是「目录」----
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"错误：输入路径不存在: {args.input}", file=sys.stderr)
        sys.exit(1)

    input_files = None
    if input_path.is_file():
        if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            print(f"错误：不支持的图片格式: {input_path.suffix}"
                  f"（支持 {', '.join(sorted(SUPPORTED_EXTENSIONS))}）",
                  file=sys.stderr)
            sys.exit(1)
        input_files = [input_path]
        default_out = input_path.parent           # 单图模式：默认输出到同目录
        default_suffix = "_bdd"                   # 并加后缀，避免覆盖原图
    else:
        default_out = input_path.parent / f"{input_path.name}_bordered"
        default_suffix = ""                       # 目录模式：保持原文件名

    output_dir = args.output or str(default_out)
    name_suffix = default_suffix if args.suffix is None else args.suffix

    # ---- 体积上限（可选）----
    try:
        max_bytes = parse_size(args.max_size)
    except ValueError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)

    target_ratio = None
    if args.no_border:
        print("提示：--no-border 模式下忽略 --ratio / --color")
    else:
        if not args.ratio:
            print("错误：加边框模式必须提供 --ratio（--no-border 模式可省略）",
                  file=sys.stderr)
            sys.exit(1)
        try:
            target_ratio = parse_ratio(args.ratio)
        except ValueError as e:
            print(f"错误：{e}", file=sys.stderr)
            sys.exit(1)

    border_color = get_border_color(args.color)

    if not (0 <= args.border_percent < 0.5):
        print("错误：--border-percent 必须在 [0, 0.5) 之间", file=sys.stderr)
        sys.exit(1)

    if not (1 <= args.jpeg_quality <= 100):
        print("错误：--jpeg-quality 必须在 1-100 之间", file=sys.stderr)
        sys.exit(1)

    summary = process_directory(
        input_dir=str(input_path),
        output_dir=output_dir,
        target_ratio=target_ratio,
        border_color=border_color,
        border_percent=args.border_percent,
        output_format=args.output_format,
        jpeg_quality=args.jpeg_quality,
        no_border=args.no_border,
        input_files=input_files,
        name_suffix=name_suffix,
        max_bytes=max_bytes,
    )

    # 有失败或提前出错时以非 0 退出，便于脚本 / 批处理判断
    sys.exit(0 if summary["ok"] else 1)


if __name__ == "__main__":
    main()
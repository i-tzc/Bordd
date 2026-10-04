#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 Bordd 程序图标（Windows .ico + macOS .icns + 一组 PNG）。

图标语义：深色画布 + 居中的图像块 + 可见的边框，直观表达“加边框”。

.icns 是直接按 ICNS 容器格式拼出来的（内部放 PNG 数据），因此**不需要
macOS 的 iconutil**，在 Windows 上也能为 Mac 版准备好图标。

用法：
    python make_icon.py            # 生成 Bordd.ico / Bordd.icns / icon_png/*.png
"""
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ICO_PATH = HERE / "Bordd.ico"
ICNS_PATH = HERE / "Bordd.icns"
PNG_DIR = HERE / "icon_png"
ICONSET_PNG_SIZES = [16, 32, 64, 128, 256, 512, 1024]

# ICNS 里各槽位对应的 (类型码, 边长)
#   icp4/icp5 = 16/32 像素；ic07..ic14 为 Retina 时代的 PNG 槽位
ICNS_SLOTS = [
    (b"icp4", 16),      # 16x16
    (b"icp5", 32),      # 32x32
    (b"ic11", 32),      # 16x16@2x
    (b"ic12", 64),      # 32x32@2x
    (b"ic07", 128),     # 128x128
    (b"ic13", 256),     # 128x128@2x
    (b"ic08", 256),     # 256x256
    (b"ic14", 512),     # 256x256@2x
    (b"ic09", 512),     # 512x512
    (b"ic10", 1024),    # 512x512@2x
]

# 配色
CANVAS = (24, 28, 38, 255)      # 画布底色（深蓝灰）
BORDER = (45, 127, 249, 255)    # 边框蓝（与 GUI 主按钮同色）
PHOTO_A = (255, 214, 64, 255)   # 图像块渐变起点（暖黄）
PHOTO_B = (240, 128, 60, 255)   # 图像块渐变终点（橙）


def draw_icon(size: int) -> Image.Image:
    """按指定边长绘制图标（矢量式按比例计算，任意尺寸都清晰）。"""
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)

    # 画布（圆角方块），留出少量外边距
    pad = max(round(s * 0.045), 0)
    radius = max(round(s * 0.18), 1)
    dr.rounded_rectangle([pad, pad, s - 1 - pad, s - 1 - pad],
                         radius=radius, fill=CANVAS)

    # 边框区域（蓝色外框）+ 内部图像块
    margin = s * 0.30           # 边框宽度（占边长比例）
    left, top = round(margin), round(margin)
    right, bottom = s - 1 - round(margin), s - 1 - round(margin)

    # 蓝色边框：先画外框实心，再在里面放图像
    dr.rectangle([left, top, right, bottom], fill=BORDER)

    inner_pad = max(round(s * 0.055), 1)
    il, it = left + inner_pad, top + inner_pad
    ir, ib = right - inner_pad, bottom - inner_pad
    if ir <= il or ib <= it:
        return img

    # 图像块：上→下线性渐变，做出“照片”的感觉
    block = Image.new("RGBA", (ir - il + 1, ib - it + 1))
    bd = ImageDraw.Draw(block)
    bw, bh = block.size
    for y in range(bh):
        t = y / max(bh - 1, 1)
        bd.line(
            [(0, y), (bw, y)],
            fill=tuple(round(PHOTO_A[i] + (PHOTO_B[i] - PHOTO_A[i]) * t)
                       for i in range(4)),
        )
    img.paste(block, (il, it))
    return img


def build_icns(png_dir: Path) -> bool:
    """把各尺寸 PNG 拼成 ICNS 文件（纯 Python，无需 macOS 的 iconutil）。

    ICNS 结构：
        'icns' + 总长度(4字节, 大端)
        之后是一串数据块：类型码(4字节) + 块长度(4字节, 含头部) + 数据
    macOS 支持在块里直接放 PNG 数据，所以这里直接把 PNG 塞进去即可。
    """
    chunks = []
    seen = set()
    for type_code, size in ICNS_SLOTS:
        if (type_code, size) in seen:
            continue
        seen.add((type_code, size))
        png = png_dir / f"icon_{size}.png"
        if not png.exists():
            continue
        data = png.read_bytes()
        chunks.append(type_code + struct.pack(">I", len(data) + 8) + data)

    if not chunks:
        return False

    body = b"".join(chunks)
    icns = b"icns" + struct.pack(">I", len(body) + 8) + body
    ICNS_PATH.write_bytes(icns)
    return True


def main() -> int:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = {sz: draw_icon(sz) for sz in sizes}

    base = frames[256]
    base.save(ICO_PATH, format="ICO",
              sizes=[(sz, sz) for sz in sizes])
    print(f"已生成 {ICO_PATH}  ({ICO_PATH.stat().st_size} 字节)")

    PNG_DIR.mkdir(exist_ok=True)
    for sz in ICONSET_PNG_SIZES:
        out = PNG_DIR / f"icon_{sz}.png"
        draw_icon(sz).save(out)
    print(f"已生成 {len(ICONSET_PNG_SIZES)} 个 PNG 到 {PNG_DIR}")

    if build_icns(PNG_DIR):
        print(f"已生成 {ICNS_PATH}  ({ICNS_PATH.stat().st_size} 字节)")
    else:
        print("[警告] 未能生成 .icns（缺少 PNG 源）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

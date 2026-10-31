#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
夜秣漫画生成器 · 文字组版引擎（图字分离核心）
================================================

把「没有字的漫画页 + 一份气泡坐标表」合成成「带中文对话、气泡、尾巴的成品页」。

为什么要图字分离：
  图像模型画中文必错。把「画」和「字」拆开，字由代码写，笔画 100% 正确，
  而且改台词只需要重跑本脚本（秒级），不用重新生图（烧钱+脸会变）。

两种用法
--------
1) 直接合成（推荐）
   python lettering.py --page page.png --spec bubbles.json --out page-final.png

2) 自动排气泡（给脸/保护框，让脚本算位置）
   python lettering.py --page page.png --spec bubbles.json --out page-final.png --auto-layout

气泡 JSON 结构
--------------
{
  "page": {"w": 1024, "h": 1536},
  "font": "C:/Windows/Fonts/msyh.ttc",
  "defaults": {"size": 30, "min_size": 20, "line_gap": 1.38, "padding": 0.72},
  "bubbles": [
    {
      "speaker": "苏念一",
      "text": "你怎么会在这里？",
      "style": "round",              // round | oval | thought | caption | shout | bare
      "x": 120, "y": 240,            // 左上角；auto-layout 时可省略
      "w": 300, "h": 130,            // 省略时按文本自动算
      "tail": {"to": [420, 380]},    // 尾巴指向（嘴部坐标）；caption/bare 不用
      "face": [380, 300, 160, 180],  // 可选：说话人脸部矩形，用于避让校验
      "size": 30,                    // 可选：覆盖默认字号
      "align": "center"              // center | left
    }
  ],
  "keepout": [[40, 600, 200, 120]]   // 保护区（重要手部/道具），气泡不得压、尾巴不得穿
}

输出
----
- 成品 PNG
- 同目录 <out>.report.json：校验报告（越界 / 压脸 / 压保护物 / 尾巴穿人 / 字数超限）
"""

import argparse
import json
import math
import os
import sys
import unicodedata

from PIL import Image, ImageDraw, ImageFilter

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("需要 Pillow：pip install pillow")

# ---------------------------------------------------------------- 标点规则

# 不能出现在行首的字符（避头点）
NO_LINE_START = set("，。、；：？！）〕］｝〉》」』】…‥·ー～!?,.;:)]}%")
# 不能出现在行尾的字符（避尾点）
NO_LINE_END = set("（〔［｛〈《「『【([{")

FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]


def load_font(path, size):
    for candidate in ([path] if path else []) + FONT_CANDIDATES:
        if candidate and os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
    print("⚠ 找不到中文字体，退回默认字体（中文可能显示为方块）", file=sys.stderr)
    return ImageFont.load_default()


def char_width(font, ch):
    """按真实字形宽度量一个字符。"""
    try:
        return font.getlength(ch)
    except AttributeError:
        bbox = font.getbbox(ch)
        return bbox[2] - bbox[0]


def wrap_text(text, font, max_width):
    """
    中文换行：逐字累加宽度，照顾避头尾。
    英文/数字按词断行。
    """
    lines = []
    for raw_line in text.split("\n"):
        if not raw_line:
            lines.append("")
            continue
        # 先按「中文逐字 / 英文按词」切成最小单元
        units = []
        buf = ""
        for ch in raw_line:
            if ch.isascii() and (ch.isalnum() or ch in "'-"):
                buf += ch
            else:
                if buf:
                    units.append(buf)
                    buf = ""
                units.append(ch)
        if buf:
            units.append(buf)

        cur = ""
        for unit in units:
            trial = cur + unit
            if char_width(font, trial) <= max_width or not cur:
                cur = trial
                continue
            # 需要换行：处理避头尾
            if unit and unit[0] in NO_LINE_START:
                # 标点跟着上一行走（悬挂），实在超宽才换
                if char_width(font, trial) <= max_width * 1.18:
                    cur = trial
                    continue
            if cur and cur[-1] in NO_LINE_END:
                # 行尾不能是开引号，把它推到下一行
                moved = cur[-1]
                cur = cur[:-1]
                lines.append(cur)
                cur = moved + unit
            else:
                lines.append(cur)
                cur = unit
        if cur:
            lines.append(cur)
    return lines or [""]


def fit_text(text, font_path, max_width, start_size, min_size, line_gap):
    """从 start_size 往下缩，直到文字装进 max_width。返回 (font, lines, line_height, size)。"""
    size = start_size
    while size >= min_size:
        font = load_font(font_path, size)
        lines = wrap_text(text, font, max_width)
        widest = max((char_width(font, ln) for ln in lines), default=0)
        if widest <= max_width:
            return font, lines, int(size * line_gap), size
        size -= 1
    font = load_font(font_path, min_size)
    return font, wrap_text(text, font, max_width), int(min_size * line_gap), min_size


# ---------------------------------------------------------------- 几何

def rect_of(x, y, w, h):
    return [x, y, w, h]


def overlap(a, b, pad=0):
    return (a[0] - pad < b[0] + b[2] and b[0] - pad < a[0] + a[2]
            and a[1] - pad < b[1] + b[3] and b[1] - pad < a[1] + a[3])


def segment_hits_rect(p0, p1, rect):
    """线段是否穿过矩形（Liang-Barsky 裁剪），返回首个交点参数或 None。"""
    low, high = 0.0, 1.0
    for axis in (0, 1):
        delta = p1[axis] - p0[axis]
        lo = rect[axis]
        hi = lo + rect[axis + 2]
        if abs(delta) < 1e-9:
            if p0[axis] < lo or p0[axis] > hi:
                return None
            continue
        t1 = (lo - p0[axis]) / delta
        t2 = (hi - p0[axis]) / delta
        low = max(low, min(t1, t2))
        high = min(high, max(t1, t2))
        if low > high:
            return None
    return low


def rect_edge_point(cx, cy, w, h, tx, ty, radius=0):
    """从矩形中心朝目标方向，求落在矩形边框上的点。"""
    dx, dy = tx - cx, ty - cy
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return cx, cy
    hw, hh = w / 2.0, h / 2.0
    scale = float("inf")
    if abs(dx) > 1e-9:
        scale = min(scale, hw / abs(dx))
    if abs(dy) > 1e-9:
        scale = min(scale, hh / abs(dy))
    return cx + dx * scale, cy + dy * scale


def ellipse_edge_point(cx, cy, w, h, tx, ty):
    """从椭圆中心朝目标方向，求落在椭圆上的点。"""
    a, b = w / 2.0, h / 2.0
    theta = math.atan2((ty - cy) / b if b else 0, (tx - cx) / a if a else 0)
    return cx + a * math.cos(theta), cy + b * math.sin(theta)


def star_polygon(cx, cy, w, h, spikes=12, inner=0.78):
    """爆炸形气泡多边形。"""
    pts = []
    a, b = w / 2.0, h / 2.0
    for i in range(spikes * 2):
        theta = math.pi * i / spikes
        f = 1.0 if i % 2 == 0 else inner
        pts.append((cx + a * f * math.cos(theta), cy + b * f * math.sin(theta)))
    return pts


# ---------------------------------------------------------------- 绘制

def cover_shape_polygon(box, style, pad):
    """按气泡形状生成覆盖块的外形（比气泡外扩 pad）。"""
    x, y, w, h = box
    x, y, w, h = x - pad, y - pad, w + pad * 2, h + pad * 2
    if style in ("oval", "thought"):
        return ("ellipse", (x, y, x + w, y + h))
    if style == "shout":
        return ("polygon", star_polygon(x + w / 2.0, y + h / 2.0, w, h))
    if style == "caption":
        return ("rect", (x, y, x + w, y + h))
    radius = min(int(h / 2.2), 34) + pad // 2
    return ("rrect", (x, y, x + w, y + h, radius))


def ring_median_color(canvas, geo, kind, pad=10, thick=26):
    """取覆盖块外一圈环带的中位色，让补丁颜色贴近周围背景。"""
    x0, y0, x1, y1 = geo[:4]
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    px = canvas.load()
    w, h = canvas.size
    samples = []
    import random
    rnd = random.Random(7)
    for _ in range(2200):
        ang = rnd.uniform(0, math.tau)
        r = rnd.uniform(0.5, 0.62) + rnd.uniform(0, 1) * 0.0
        # 在椭圆/矩形外环采样
        if kind == "ellipse":
            ax = (x1 - x0) / 2.0 + pad + thick * rnd.random()
            ay = (y1 - y0) / 2.0 + pad + thick * rnd.random()
            sx, sy = cx + math.cos(ang) * ax, cy + math.sin(ang) * ay
        else:
            bx, by = (x1 - x0) / 2.0 + pad, (y1 - y0) / 2.0 + pad
            sx = cx + math.cos(ang) * (bx + thick * rnd.random())
            sy = cy + math.sin(ang) * (by + thick * rnd.random())
        ix, iy = int(sx), int(sy)
        if 0 <= ix < w and 0 <= iy < h:
            samples.append(px[ix, iy])
    if not samples:
        return None
    rs = sorted(c[0] for c in samples)
    gs = sorted(c[1] for c in samples)
    bs = sorted(c[2] for c in samples)
    mid = len(samples) // 2
    return (rs[mid], gs[mid], bs[mid])


def apply_cover(canvas, bubble, box, style, paper="white"):
    """
    模式 B 专用：先在原气泡位置盖一块羽化底，把模型画错的字吃掉。
    cover 支持：
      true                                  → 按新气泡外扩 pad
      {"pad":18, "blur":7}                  → 按新气泡外扩 pad
      {"box":[x,y,w,h], "shape":"oval"}     → 显式指定要盖掉的矩形（原气泡含尾巴的范围）
      {"color":"auto"}                      → 取外圈中位色，让补丁贴近背景
    返回实际覆盖框 [x,y,w,h]，供报告用。
    """
    spec = bubble.get("cover")
    if not spec:
        return None
    if spec is True:
        spec = {}
    if not isinstance(spec, dict):
        spec = {}
    pad = int(spec.get("pad", 14))
    blur = float(spec.get("blur", 6))
    shape = spec.get("shape", style)
    color = spec.get("color", paper)

    rect = spec.get("box")
    if rect:
        bx, by, bw, bh = [int(v) for v in rect]
        shape_for_mask = shape
        kind, geo = cover_shape_polygon([bx, by, bw, bh], shape_for_mask, 0)
        area = [bx, by, bw, bh]
    else:
        kind, geo = cover_shape_polygon(box, style, pad)
        area = [int(box[0]) - pad, int(box[1]) - pad, int(box[2]) + pad * 2, int(box[3]) + pad * 2]

    if color == "auto":
        picked = ring_median_color(canvas, geo, kind)
        color = picked if picked else paper

    mask = Image.new("L", canvas.size, 0)
    md = ImageDraw.Draw(mask)
    if kind == "ellipse":
        md.ellipse(geo, fill=255)
    elif kind == "polygon":
        md.polygon(geo, fill=255)
    elif kind == "rect":
        md.rectangle(geo, fill=255)
    else:
        md.rounded_rectangle(geo[:4], radius=geo[4], fill=255)
    if blur and blur > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(blur))
    patch = Image.new("RGB", canvas.size, color)
    canvas.paste(patch, (0, 0), mask)
    return {"box": area, "color": tuple(color) if isinstance(color, tuple) else color, "blur": blur}


def draw_bubble(draw, bubble, font, lines, line_h, box, style, ink="black", paper="white", width=3):
    x, y, w, h = box
    cx, cy = x + w / 2.0, y + h / 2.0
    tail = bubble.get("tail")

    # 1) 尾巴（先画，让气泡盖住尾巴根部）
    if tail and style not in ("caption", "bare"):
        tx, ty = tail["to"]
        face = bubble.get("face")
        # 尾巴尖端不要顶到脸里，留 4px 空隙
        if face:
            entry = segment_hits_rect((cx, cy), (tx, ty), face)
            if entry is not None:
                span = math.hypot(tx - cx, ty - cy)
                gap = max(0.0, entry * span - 4)
                tx, ty = cx + (tx - cx) / span * gap, cy + (ty - cy) / span * gap
        if style in ("oval", "thought"):
            bx, by = ellipse_edge_point(cx, cy, w, h, tx, ty)
        else:
            bx, by = rect_edge_point(cx, cy, w, h, tx, ty)
        span = math.hypot(tx - bx, ty - by) or 1.0
        ux, uy = (tx - bx) / span, (ty - by) / span
        # 尾巴长度上限：真实的漫画尾巴是短短的三角形，拉到半页远会变成两根筷子
        max_len = float(tail.get("max_length", 160))
        if span > max_len:
            if span > max_len * 1.6:
                bubble.setdefault("_notes", []).append(
                    f"气泡离说话人约 {round(span)}px，尾巴已被截到 {round(max_len)}px。"
                    f"建议把气泡挪到人物附近（160px 内），否则读者要靠猜")
            tx, ty = bx + ux * max_len, by + uy * max_len
            span = max_len
        half = tail.get("width", max(10, min(22, w * 0.09))) / 2.0
        # 尾巴底边垂直于指向
        ax, ay = bx - uy * half, by + ux * half
        bx2, by2 = bx + uy * half, by - ux * half
        if style == "thought":
            # 思考泡用三个递减圆点代替三角形
            for i, r in enumerate((half * 0.9, half * 0.62, half * 0.36)):
                t = (i + 1) / 4.0
                px, py = bx + (tx - bx) * t, by + (ty - by) * t
                draw.ellipse([px - r, py - r, px + r, py + r], fill=paper, outline=ink, width=width)
        else:
            draw.polygon([(ax, ay), (tx, ty), (bx2, by2)], fill=paper)
            draw.line([(ax, ay), (tx, ty)], fill=ink, width=width)
            draw.line([(tx, ty), (bx2, by2)], fill=ink, width=width)

    # 2) 气泡主体
    if style == "caption":
        draw.rectangle([x, y, x + w, y + h], fill=paper, outline=ink, width=width)
    elif style == "bare":
        pass
    elif style in ("oval", "thought"):
        draw.ellipse([x, y, x + w, y + h], fill=paper, outline=ink, width=width)
    elif style == "shout":
        draw.polygon(star_polygon(cx, cy, w, h), fill=paper, outline=ink, width=width)
    else:  # round
        radius = min(int(h / 2.2), 34)
        draw.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=paper, outline=ink, width=width)

    # 3) 文字
    align = bubble.get("align", "center")
    total = len(lines) * line_h
    ty = cy - total / 2.0
    for line in lines:
        lw = char_width(font, line)
        tx = cx - lw / 2.0 if align == "center" else x + font.size * 0.72
        draw.text((tx, ty), line, font=font, fill=ink)
        ty += line_h


def measure_box(text, font_path, pad_ratio, start_size, min_size, line_gap, max_width, style="round"):
    """按文字算气泡尺寸。椭圆和爆炸形的内接空间比外框小，需要额外放大。"""
    font, lines, line_h, size = fit_text(text, font_path, max_width, start_size, min_size, line_gap)
    widest = max((char_width(font, ln) for ln in lines), default=size)
    pad = int(size * pad_ratio)
    w = int(widest + pad * 2)
    h = int(len(lines) * line_h + pad * 1.5)
    # 椭圆内接矩形只有 0.707 倍，爆炸形锯齿要吃掉一圈
    factor = {"oval": 1.28, "thought": 1.28, "shout": 1.32}.get(style, 1.0)
    return int(w * factor), int(h * factor), font, lines, line_h, size


# ---------------------------------------------------------------- 自动布局

def auto_place(bubble, page_w, page_h, taken, keepout_list):
    """
    没给坐标时，在页面内网格搜索一个位置：
    - 越靠近嘴部越好
    - 不压脸 / 不压保护区 / 不压已有气泡
    - 尾巴不穿保护区
    """
    tail = bubble.get("tail") or {}
    target = tail.get("to") or [page_w / 2, page_h / 2]
    w, h = bubble["_w"], bubble["_h"]
    faces = [bubble["face"]] if bubble.get("face") else []
    best, best_score = None, None
    step = 16
    for gy in range(step, max(step, page_h - h - step), step):
        for gx in range(step, max(step, page_w - w - step), step):
            box = rect_of(gx, gy, w, h)
            if any(overlap(box, t) for t in taken):
                continue
            if any(overlap(box, f, pad=6) for f in faces):
                continue
            if any(overlap(box, k, pad=4) for k in keepout_list):
                continue
            cx, cy = gx + w / 2.0, gy + h / 2.0
            if any(segment_hits_rect((cx, cy), tuple(target), k) is not None for k in keepout_list):
                continue
            dist = math.hypot(cx - target[0], cy - target[1])
            score = dist + 0.6 * abs(cy - target[1])
            if best_score is None or score < best_score:
                best, best_score = (gx, gy), score
    return best


# ---------------------------------------------------------------- 主流程

def process(page_path, spec_path, out_path, auto_layout=False, ink="black", paper="white"):
    with open(spec_path, "r", encoding="utf-8") as fh:
        spec = json.load(fh)

    page = Image.open(page_path).convert("RGBA")
    page_w, page_h = page.size
    declared = spec.get("page") or {}
    if declared.get("w") and int(declared["w"]) != page_w:
        print(f"⚠ 画布宽度不一致：spec={declared['w']} 实际={page_w}，以实际为准", file=sys.stderr)

    defaults = spec.get("defaults") or {}
    start_size = int(defaults.get("size", max(22, round(page_w / 32))))
    min_size = int(defaults.get("min_size", max(15, round(start_size * 0.62))))
    line_gap = float(defaults.get("line_gap", 1.38))
    pad_ratio = float(defaults.get("padding", 0.72))
    font_path = spec.get("font")
    width = int(defaults.get("width", max(2, round(page_w / 340))))
    default_max_w = int(defaults.get("max_text_width", page_w * 0.42))

    keepout = [list(map(int, k)) for k in (spec.get("keepout") or [])]
    bubbles = spec.get("bubbles") or []
    warnings = []
    taken = []

    # 第一遍：量尺寸
    for i, b in enumerate(bubbles):
        style = b.get("style", "round")
        text = str(b.get("text", ""))
        size = int(b.get("size", start_size))
        max_w = int(b.get("max_w", default_max_w))
        if style == "caption":
            max_w = int(b.get("max_w", page_w * 0.9))
        w, h, font, lines, line_h, used = measure_box(
            text, font_path, pad_ratio, size, min_size, line_gap, max_w, style)
        b["_w"], b["_h"], b["_font"], b["_lines"], b["_lh"], b["_size"] = w, h, font, lines, line_h, used
        if used < int(min_size * 1.001) and char_width(font, text) > max_w * 3:
            warnings.append(f"[{i}] 「{text[:12]}…」字数偏多，已压到最小字号 {used}px，建议拆成两格或精简台词")

    # 第二遍：定位（自动布局需要按顺序占位）
    for i, b in enumerate(bubbles):
        style = b.get("style", "round")
        if b.get("w") and b.get("h"):
            b["_box"] = rect_of(int(b["x"]), int(b["y"]), int(b["w"]), int(b["h"]))
        elif b.get("x") is not None and b.get("y") is not None:
            b["_box"] = rect_of(int(b["x"]), int(b["y"]), b["_w"], b["_h"])
        elif auto_layout and style not in ("caption", "bare"):
            placed = auto_place(b, page_w, page_h, taken, keepout)
            if placed is None:
                warnings.append(f"[{i}] 自动布局找不到空位，已放到格子左上；请手动给坐标")
                placed = (16, 16)
            b["_box"] = rect_of(placed[0], placed[1], b["_w"], b["_h"])
        elif style == "caption":
            b["_box"] = rect_of(int(page_w * 0.05), int(page_h * 0.04), b["_w"], b["_h"])
        else:
            warnings.append(f"[{i}] 未给坐标且未开启 --auto-layout，已放到页面左上")
            b["_box"] = rect_of(16, 16, b["_w"], b["_h"])
        taken.append(b["_box"])

    # 第三遍：校验
    def tail_obstacles(b):
        """
        尾巴的障碍物：保护区 + 后面的气泡。
        豁免两类误报：
          - 与说话人自己的脸重合的保护区（那本来就是嘴所在的位置）
          - 尾巴目标点本身落在里面的框（那就是说话人自己）
        """
        to = tuple(b["tail"]["to"])
        own_face = b.get("face")
        out = []
        for k in keepout:
            if own_face and overlap(k, own_face):
                continue
            if k[0] <= to[0] <= k[0] + k[2] and k[1] <= to[1] <= k[1] + k[3]:
                continue
            out.append(k)
        return out

    for i, b in enumerate(bubbles):
        box = b["_box"]
        if box[0] < 0 or box[1] < 0 or box[0] + box[2] > page_w or box[1] + box[3] > page_h:
            warnings.append(f"[{i}] 气泡超出页面边界 {box}")
        if b.get("face") and overlap(box, b["face"]):
            warnings.append(f"[{i}] 气泡压住了 {b.get('speaker', '角色')} 的脸，读者会看不清表情")
        for k in keepout:
            if overlap(box, k):
                warnings.append(f"[{i}] 气泡压住了保护区 {k}（可能是关键手部或道具）")
        tail = b.get("tail")
        if tail and tail.get("to"):
            cx, cy = box[0] + box[2] / 2.0, box[1] + box[3] / 2.0
            for j, other in enumerate(bubbles):
                if j <= i:
                    continue
                if segment_hits_rect((cx, cy), tuple(tail["to"]), other["_box"]) is not None:
                    warnings.append(f"[{i}] 尾巴穿过了第 {j} 个气泡")
            for k in tail_obstacles(b):
                if segment_hits_rect((cx, cy), tuple(tail["to"]), k) is not None:
                    warnings.append(f"[{i}] 尾巴穿过了保护区 {k}，读者会误认说话人")

    # 相邻气泡「左→右回跳 + 纵向重叠」检测（旁白不参与，它本来就横跨）
    def is_caption(b):
        return b.get("style") in ("caption", "bare")

    for i in range(1, len(bubbles)):
        if is_caption(bubbles[i - 1]) or is_caption(bubbles[i]):
            continue
        a, bb = bubbles[i - 1]["_box"], bubbles[i]["_box"]
        if bb[0] > a[0] and bb[1] < a[1] + a[3]:
            warnings.append(
                f"[{i - 1}→{i}] 后一句在更靠右的位置且纵向范围重叠，读者容易当成一组连着读；"
                f"建议拉开行高差或换位置")

    # 非连续气泡同列近邻（跳读高发）
    def gap(a, b):
        dx = max(0, a[0] - b[0] - b[2], b[0] - a[0] - a[2])
        dy = max(0, a[1] - b[1] - b[3], b[1] - a[1] - a[3])
        return math.hypot(dx, dy)

    for i in range(len(bubbles) - 2):
        if is_caption(bubbles[i]) or is_caption(bubbles[i + 1]):
            continue
        for j in range(i + 2, len(bubbles)):
            if is_caption(bubbles[j]):
                continue
            a, expect, comp = bubbles[i]["_box"], bubbles[i + 1]["_box"], bubbles[j]["_box"]
            same_col = a[0] < comp[0] + comp[2] and comp[0] < a[0] + a[2]
            eg, cg = gap(a, expect), gap(a, comp)
            if same_col and cg < eg * 0.65 and cg <= max(32, page_w * 0.14):
                warnings.append(
                    f"[{i}→{j}] 第 {i + 1} 句与第 {j + 1} 句同列且靠得比第 {i + 2} 句更近"
                    f"（{round(cg)} < {round(eg)}），读者会跳读中间那句；请调整行/分组或拆格")

    # 落笔
    canvas = page.copy()
    # 第一轮：模式 B 的覆盖块（先把模型画错的字吃掉，再画新气泡）
    covered = 0
    for b in bubbles:
        if apply_cover(canvas, b, b["_box"], b.get("style", "round"), paper=paper):
            covered += 1
    draw = ImageDraw.Draw(canvas)
    for b in bubbles:
        draw_bubble(draw, b, b["_font"], b["_lines"], b["_lh"], b["_box"],
                    b.get("style", "round"), ink=ink, paper=paper, width=width)
        for note in b.get("_notes", []):
            warnings.append(f"[气泡 {bubbles.index(b)}] {note}")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    canvas.convert("RGB").save(out_path)

    report = {
        "page": page_path,
        "output": out_path,
        "size": [page_w, page_h],
        "bubbles": [
            {
                "index": i,
                "speaker": b.get("speaker"),
                "style": b.get("style", "round"),
                "text": b.get("text"),
                "box": b["_box"],
                "font_size": b["_size"],
                "lines": b["_lines"],
            }
            for i, b in enumerate(bubbles)
        ],
        "covered": covered,
        "warnings": warnings,
        "ok": not warnings,
    }
    report_path = os.path.splitext(out_path)[0] + ".report.json"
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print(f"✓ 已合成 {out_path}")
    print(f"  气泡 {len(bubbles)} 个，画布 {page_w}×{page_h}")
    if warnings:
        print(f"  ⚠ {len(warnings)} 条校验警告：")
        for w in warnings:
            print("    -", w)
    else:
        print("  校验通过：无越界 / 无压脸 / 无尾巴穿物")
    print(f"  报告：{report_path}")
    return report


def main():
    ap = argparse.ArgumentParser(description="夜秣漫画 · 文字组版引擎")
    ap.add_argument("--page", required=True, help="无字页面图（生图产物）")
    ap.add_argument("--spec", required=True, help="气泡坐标表 JSON")
    ap.add_argument("--out", required=True, help="输出成品图")
    ap.add_argument("--auto-layout", action="store_true", help="没给坐标时自动找位置")
    ap.add_argument("--ink", default="black", help="文字/描边颜色")
    ap.add_argument("--paper", default="white", help="气泡底色")
    args = ap.parse_args()
    process(args.page, args.spec, args.out, args.auto_layout, args.ink, args.paper)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""章节扉页：把「第 N 章 + 章名」排成一张大标题页（每章的第 1 页）。

底：
  --page 图  → 拿一张无字气氛图做底（split 版式会把图放在上半部）
  不给       → 本地生成纸纹底，纯排版，不花生图额度

版式：
  split     上图下文，最像实体书扉页（给 --page 时默认）
  vertical  日漫刊头：标题竖排在右，章号竖线在左（无图时默认）
  center    文艺居中：标题横排居中，上下双横线 + 细边框
  band      杂志横带：中段一条实色横带压标题

用法：
  python make_title.py --out 扉页.png --no 1 --title "九月的第一个bug" --en "CH.01 / 九月的第一个bug"
  python make_title.py --page art/P01.png --out 扉页.png --no 2 --title "公共课的同桌" --style split
"""
import argparse
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

# 中文字体：思源宋体 Heavy / 雅黑粗 / 等线粗
CJK = {
    "serif": [
        "C:/Windows/Fonts/Source Han Serif SC Heavy (TrueType).ttf",
        "C:/Windows/Fonts/Source Han Serif SC Bold (TrueType).ttf",
        "/System/Library/Fonts/Songti.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
        "C:/Windows/Fonts/simsun.ttc",
    ],
    "sans": [
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    ],
    "round": [
        "C:/Windows/Fonts/Dengb.ttf",
        "C:/Windows/Fonts/msyhbd.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ],
}
# 拉丁补充字体（数字、空格、标点必须有：思源宋体这个子集缺 ASCII 数字）
LATIN = {
    "serif": ["C:/Windows/Fonts/NotoSerif-Bold.ttf", "C:/Windows/Fonts/georgiab.ttf",
              "/System/Library/Fonts/Times.ttc"],
    "sans": ["C:/Windows/Fonts/NotoSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf",
             "/System/Library/Fonts/Helvetica.ttc"],
    "round": ["C:/Windows/Fonts/NotoSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf",
              "/System/Library/Fonts/Helvetica.ttc"],
}


def pick(paths):
    for p in paths:
        if Path(p).exists():
            return p
    return ""


CN = "零一二三四五六七八九十"


def num_cn(n):
    if n <= 10:
        return CN[n]
    if n < 20:
        return "十" + CN[n - 10]
    if n < 100:
        t, o = divmod(n, 10)
        return CN[t] + "十" + (CN[o] if o else "")
    return str(n)


def load_base(path, focus="center", crop=""):
    img = Image.open(path).convert("RGB")
    if crop:
        x, y, w, h = [int(v) for v in crop.split(",")]
        img = img.crop((x, y, x + w, y + h))
    return img


def hex2rgb(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def stroke_of(ink):
    return (255, 255, 255) if lum(ink) < 150 else (22, 20, 18)


def cover_crop(img, W, H, focus="center"):
    r = max(W / img.width, H / img.height)
    nw, nh = int(img.width * r + 0.5), int(img.height * r + 0.5)
    img = img.resize((nw, nh), Image.LANCZOS)
    x = (nw - W) // 2
    if focus == "top":
        y = 0
    elif focus == "bottom":
        y = nh - H
    else:
        y = (nh - H) // 2
    return img.crop((x, y, x + W, y + H))


def dim_image(img, pct):
    if pct <= 0:
        return img
    k = 1.0 - pct / 100.0
    return Image.eval(img.convert("RGB"), lambda v: int(v * k))


def vignette(img, top=0, bottom=0):
    """上/下加暗，中间不动；top/bottom 是 0-255 的压暗强度。"""
    if not top and not bottom:
        return img
    W, H = img.size
    veil = Image.new("L", (1, H))
    pv = veil.load()
    for y in range(H):
        t = y / (H - 1)
        v = top * (1 - t / 0.5) if t < 0.5 else 0
        v = max(v, bottom * ((t - 0.5) / 0.5) if t > 0.5 else 0)
        pv[0, y] = int(max(0, v))
    veil = veil.resize((W, H))
    return ImageChops.subtract(img.convert("RGB"), Image.merge("RGB", (veil, veil, veil)))


def make_paper(W, H, base):
    img = Image.new("RGB", (W, H), base)
    noise = Image.effect_noise((W, H), 26).convert("L")
    img = ImageChops.blend(img, Image.merge("RGB", (noise, noise, noise)), 0.05)
    veil = Image.new("L", (1, H))
    pv = veil.load()
    for y in range(H):
        pv[0, y] = int(20 * y / (H - 1))
    veil = veil.resize((W, H))
    return ImageChops.subtract(img, Image.merge("RGB", (veil, veil, veil)))


class Type:
    """中文走主字体，ASCII 走拉丁字体（思源宋体子集缺数字，必须分派）。"""

    def __init__(self, cjk_path, latin_path, style):
        self.cjk_path = cjk_path
        self.latin_path = latin_path or cjk_path
        self.cache = {}

    def cjk(self, size):
        k = ("c", size)
        if k not in self.cache:
            self.cache[k] = ImageFont.truetype(self.cjk_path, size)
        return self.cache[k]

    def latin(self, size):
        k = ("l", size)
        if k not in self.cache:
            self.cache[k] = ImageFont.truetype(self.latin_path, size)
        return self.cache[k]

    def font(self, ch, size):
        return self.latin(size) if ord(ch) < 128 else self.cjk(size)

    def width(self, d, text, size):
        return sum(d.textlength(c, font=self.font(c, size)) for c in text)

    def draw(self, d, xy, text, size, ink, stroke=0, anchor_x="l", spacing=0.0):
        """逐字绘制，anchor_x: l/c/r。返回总宽。"""
        total = self.width(d, text, size) + spacing * max(0, len(text) - 1)
        x = xy[0] - (total if anchor_x == "r" else total / 2 if anchor_x == "c" else 0)
        for c in text:
            f = self.font(c, size)
            d.text((x, xy[1]), c, font=f, fill=ink, anchor="lm",
                   stroke_width=stroke, stroke_fill=stroke_of(ink))
            x += d.textlength(c, font=f) + spacing
        return total

    def vertical(self, img, x, y, text, size, ink, stroke=0, gap=1.10, latin_gap=0.18):
        """竖排：中文逐字下排，连续 ASCII 片段旋转 90° 整体嵌入。返回底部 y。"""
        d = ImageDraw.Draw(img)
        for tok in split_tokens(text):
            if len(tok) > 1 and all(ord(c) < 128 for c in tok):
                f = self.latin(size)
                tw = d.textlength(tok, font=f)
                pad = max(6, stroke * 2)
                layer = Image.new("RGBA", (int(tw) + pad * 2, size * 2), (0, 0, 0, 0))
                ld = ImageDraw.Draw(layer)
                ld.text((pad, layer.height / 2), tok, font=f, fill=ink + (255,), anchor="lm",
                        stroke_width=stroke, stroke_fill=stroke_of(ink) + (255,))
                layer = layer.rotate(90, expand=True)
                img.alpha_composite(layer, (int(x - layer.width / 2), int(y)))
                y += layer.height + size * latin_gap
            else:
                for ch in tok:
                    self.draw(d, (x, y + size * 0.56), ch, size, ink, stroke, "c")
                    y += size * gap
        return y


def split_tokens(text):
    out, buf = [], ""
    for ch in text:
        if ord(ch) < 128 and not ch.isspace():
            buf += ch
        else:
            if buf:
                out.append(buf)
                buf = ""
            out.append(ch)
    if buf:
        out.append(buf)
    return out


def vheight(d, text, typ, size, gap=1.10, latin_gap=0.18):
    h = 0
    for tok in split_tokens(text):
        if len(tok) > 1 and all(ord(c) < 128 for c in tok):
            h += size * 2 + size * latin_gap
        else:
            h += size * gap * len(tok)
    return h


def fit_v(text, typ, size_start, max_h, min_size=26):
    size = size_start
    while size > min_size:
        if vheight(None, text, typ, size) <= max_h:
            return size
        size -= 2
    return size


def fit_h(d, text, typ, size_start, max_w, min_size=26):
    size = size_start
    while size > min_size:
        if typ.width(d, text, size) <= max_w:
            return size
        size -= 2
    return size


def main():
    ap = argparse.ArgumentParser(description="章节扉页大标题排版")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", required=True, help="章名，如「九月的第一个bug」")
    ap.add_argument("--no", type=int, default=1, help="章号")
    ap.add_argument("--page", default="", help="底图，不给则用纸纹底")
    ap.add_argument("--en", default="", help="底部一行小字（英文刊头 / 引子），纯横排")
    ap.add_argument("--kicker", default="", help="章号行文案，默认「第 N 章」")
    ap.add_argument("--style", choices=["auto", "split", "vertical", "center", "band"],
                    default="auto")
    ap.add_argument("--face", choices=["serif", "sans", "round"], default="serif")
    ap.add_argument("--face-font", default="", help="自定义中文字体路径")
    ap.add_argument("--ink", default="#16171B")
    ap.add_argument("--accent", default="#B33A2B")
    ap.add_argument("--paper", default="#F4EFE4")
    ap.add_argument("--dim", type=int, default=40, help="底图压暗 0-100")
    ap.add_argument("--focus", choices=["top", "center", "bottom"], default="center",
                    help="底图裁切焦点，默认居中")
    ap.add_argument("--crop", default="", help="先从底图裁出一整格：x,y,w,h（像素）")
    ap.add_argument("--split-h", type=float, default=0.56, help="split 版式图区高度占比")
    ap.add_argument("--size", type=int, default=0, help="标题字号，0 自动")
    ap.add_argument("--ghost", action="store_true", help="背景压一个大号章号水印")
    ap.add_argument("--w", type=int, default=1080)
    ap.add_argument("--h", type=int, default=1536)
    a = ap.parse_args()

    W, H = a.w, a.h
    ink = hex2rgb(a.ink)
    accent = hex2rgb(a.accent)
    paper = hex2rgb(a.paper)
    M = int(W * 0.089)  # 96

    cjk_path = a.face_font or pick(CJK[a.face])
    if not cjk_path:
        raise SystemExit("找不到中文字体，请用 --face-font 指定")
    latin_path = pick(LATIN[a.face]) or cjk_path
    typ = Type(cjk_path, latin_path, a.face)

    style = a.style
    if style == "auto":
        style = "split" if a.page else "vertical"

    kicker = a.kicker or f"第{num_cn(a.no)}章"

    # ---------------- split：上图下文 ----------------
    if style == "split":
        h1 = int(H * (a.split_h if a.page else 0.0))
        if a.page:
            img = cover_crop(load_base(a.page, a.focus, a.crop), W, h1, a.focus)
            img = dim_image(img, a.dim)
            img = vignette(img, bottom=70)
        else:
            img = make_paper(W, h1, paper)
        canvas = Image.new("RGB", (W, H), paper)
        canvas.paste(img, (0, 0))
        d0 = ImageDraw.Draw(canvas)
        if a.page:
            d0.rectangle([0, h1, W, h1 + 9], fill=accent)
        canvas = canvas.convert("RGBA")
        d = ImageDraw.Draw(canvas)

        # 章号
        ks = int(min(W, H) * 0.032)
        typ.draw(d, (W / 2, h1 + 96), kicker, ks, accent, 0, "c", spacing=1.5)

        # 标题
        avail_w = W - M * 2
        size = a.size or fit_h(d, a.title, typ, int(W * 0.155), avail_w)
        ty = h1 + 96 + ks * 2.4 + size * 0.5
        tw = typ.draw(d, (W / 2, ty), a.title, size, ink, max(2, size // 26), "c")

        # 标题下细线
        ly = ty + size * 0.92
        d.line([(W / 2 - tw * 0.34, ly), (W / 2 + tw * 0.34, ly)], fill=ink, width=3)

        # 英文行
        if a.en:
            es = int(min(W, H) * 0.026)
            fe = typ.latin(es)
            ew = d.textlength(a.en, font=fe)
            if ew > W - M * 2:
                es = int(es * (W - M * 2) / ew)
                fe = typ.latin(es)
                ew = d.textlength(a.en, font=fe)
            d.text((W / 2, H - 92), a.en, font=fe, fill=ink, anchor="mm")
            d.line([(W / 2 - ew / 2 - 42, H - 92), (W / 2 - ew / 2 - 18, H - 92)],
                   fill=accent, width=3)
            d.line([(W / 2 + ew / 2 + 18, H - 92), (W / 2 + ew / 2 + 42, H - 92)],
                   fill=accent, width=3)

        if a.ghost:
            gf = typ.latin(int(H * 0.26))
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(layer).text((W - M, H - 150), f"{a.no:02d}", font=gf,
                                       fill=accent + (26,), anchor="rs")
            canvas = Image.alpha_composite(canvas, layer)

    # ---------------- vertical：竖排刊头 ----------------
    elif style == "vertical":
        base = make_paper(W, H, paper).convert("RGBA")
        if a.page:
            base = dim_image(cover_crop(load_base(a.page, a.focus, a.crop), W, H, a.focus), a.dim)
            base = base.convert("RGBA")
        canvas = base
        d = ImageDraw.Draw(canvas)

        size = a.size or fit_v(a.title, typ, int(W * 0.24), H - 380)
        col_x = W - M - size * 0.62
        y0 = int(H * 0.10)
        stroke = max(2, size // 26)

        # 章号竖排 + 竖线（长度按实际渲染高度，与标题齐脚）
        rule_x = col_x - size * 1.45
        ks = max(20, int(size * 0.30))
        ky = y0 + size * 0.10
        for ch in kicker:
            if ch.isspace():
                ky += ks * 0.30
                continue
            typ.draw(d, (rule_x - size * 0.50, ky + ks * 0.55), ch, ks, ink, 0, "c")
            ky += ks * 1.32

        y_end = typ.vertical(canvas, col_x, y0, a.title, size, ink, stroke)
        d.rectangle([rule_x, y0 + size * 0.10, rule_x + 5, y_end - size * 0.42], fill=accent)

        if a.ghost:
            gf = typ.latin(int(H * 0.30))
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(layer).text((M - 10, H - 240), f"{a.no:02d}", font=gf,
                                       fill=accent + (30,), anchor="ls")
            canvas = Image.alpha_composite(canvas, layer)
            d = ImageDraw.Draw(canvas)

        if a.en:
            es = int(min(W, H) * 0.026)
            fe = typ.latin(es)
            ew = d.textlength(a.en, font=fe)
            if ew > W - M * 2:
                es = int(es * (W - M * 2) / ew)
                fe = typ.latin(es)
                ew = d.textlength(a.en, font=fe)
            d.text((M, H - 96), a.en, font=fe, fill=ink, anchor="lm")
            d.line([(M, H - 96 - es * 1.7), (M + min(ew, W - M * 2), H - 96 - es * 1.7)],
                   fill=accent, width=3)

    # ---------------- center：文艺居中 ----------------
    elif style == "center":
        base = make_paper(W, H, paper).convert("RGBA")
        if a.page:
            base = dim_image(cover_crop(load_base(a.page, a.focus, a.crop), W, H, a.focus), a.dim)
            base = base.convert("RGBA")
        canvas = base
        d = ImageDraw.Draw(canvas)

        # 细边框
        fr = 46
        d.rectangle([fr, fr, W - fr, H - fr], outline=ink + (60,), width=2)

        size = a.size or fit_h(d, a.title, typ, int(W * 0.145), W - M * 2 - 130)
        cy = H * 0.47
        ks = int(size * 0.30)
        tw = typ.draw(d, (W / 2, cy), a.title, size, ink, max(2, size // 26), "c")
        half = min(tw / 2 + 64, W / 2 - fr - 26)
        # 章号在上横线之上，横线不穿字
        typ.draw(d, (W / 2, cy - size * 1.42), kicker, ks, accent, 0, "c", spacing=2)
        for dy in (-size * 0.80, size * 0.80):
            d.line([(W / 2 - half, cy + dy), (W / 2 + half, cy + dy)], fill=ink, width=4)
        if a.en:
            es = int(size * 0.28)
            fe = typ.latin(es)
            ew = d.textlength(a.en, font=fe)
            if ew > W - M * 2 - 40:
                es = int(es * (W - M * 2 - 40) / ew)
                fe = typ.latin(es)
            d.text((W / 2, cy + size * 1.40), a.en, font=fe, fill=ink, anchor="mm")
        if a.ghost:
            gf = typ.latin(int(H * 0.22))
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(layer).text((W / 2, H - fr - 96), f"{a.no:02d}", font=gf,
                                       fill=accent + (20,), anchor="ms")
            canvas = Image.alpha_composite(canvas, layer)

    # ---------------- band：杂志横带 ----------------
    else:
        base = make_paper(W, H, paper).convert("RGB")
        if a.page:
            base = dim_image(cover_crop(load_base(a.page, a.focus, a.crop), W, H, a.focus), max(a.dim, 30))
            base = vignette(base, top=60, bottom=90).convert("RGB")
        canvas = base.convert("RGBA")
        d = ImageDraw.Draw(canvas)

        size = a.size or fit_h(d, a.title, typ, int(W * 0.15), W - M * 2 - 60)
        band_h = int(size * 1.85)
        tabs = int(size * 0.62)
        by = int(H * 0.47 - band_h / 2)
        # 章号窄条 + 主横带 + 下方 accent 细线：章号永远落在实色上，不会被画面吃掉
        d.rectangle([0, by - tabs, W, by], fill=accent + (255,))
        d.rectangle([0, by, W, by + band_h], fill=ink + (236,))
        d.rectangle([0, by + band_h, W, by + band_h + 12], fill=accent + (255,))
        typ.draw(d, (W / 2, by + band_h / 2), a.title, size, stroke_of(ink), 0, "c")
        ks = int(tabs * 0.56)
        typ.draw(d, (M, by - tabs / 2), kicker, ks, (255, 255, 255), 0, "l", spacing=1.5)
        if a.en:
            es = int(size * 0.28)
            fe = typ.latin(es)
            ew = d.textlength(a.en, font=fe)
            if ew > W - M * 2:
                es = int(es * (W - M * 2) / ew)
                fe = typ.latin(es)
                ew = d.textlength(a.en, font=fe)
            fy = H - 108
            d.rectangle([0, fy - es * 1.5, W, fy + es * 1.5], fill=(10, 10, 12, 150))
            d.text((W / 2, fy), a.en, font=fe, fill=(255, 255, 255), anchor="mm")

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out)
    print(f"✓ {out}  ({W}×{H})  style={style} face={Path(cjk_path).name} size={size}")


if __name__ == "__main__":
    main()

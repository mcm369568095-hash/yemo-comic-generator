# -*- coding: utf-8 -*-
"""章末「下期预告」页排版：标题 + 副标题 + 底部文案卡。

用法：
  python make_preview.py --page art/P17.png --out final/P17.png \
      --title 下期预告 --sub "第 3 章 · 食堂里的卡路里战争" \
      --lines "十二点零五分，他端着五百卡的午餐。|她夹过来一块鸡腿。|「你的人生不需要每一口都按公式来。」"

可选：
  --pos top|bottom     文案卡位置（默认 bottom）
  --size 28            正文字号
  --card-alpha 232     文案卡不透明度 0-255
  --title-size 82      标题字号
  --no-rule            不画标题下的分隔线
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BOLD_CANDIDATES = [
    "C:/Windows/Fonts/msyhbd.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
]
REG_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]


def pick(paths):
    for p in paths:
        if Path(p).exists():
            return p
    raise SystemExit("找不到中文字体，请用 --font 指定")


def main():
    ap = argparse.ArgumentParser(description="章末下期预告页排版")
    ap.add_argument("--page", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="下期预告")
    ap.add_argument("--sub", default="")
    ap.add_argument("--lines", default="", help="用 | 分隔的多行文案")
    ap.add_argument("--pos", choices=["top", "bottom"], default="bottom")
    ap.add_argument("--size", type=int, default=28)
    ap.add_argument("--title-size", type=int, default=82)
    ap.add_argument("--card-alpha", type=int, default=232)
    ap.add_argument("--font", default="", help="自定义正文字体路径")
    ap.add_argument("--no-rule", action="store_true")
    a = ap.parse_args()

    bold = pick(BOLD_CANDIDATES)
    reg = a.font or pick(REG_CANDIDATES)

    img = Image.open(a.page).convert("RGB")
    W, H = img.size
    d = ImageDraw.Draw(img)

    # ---- 标题（带白描边，压在任何背景上都读得清）
    ft = ImageFont.truetype(bold, a.title_size)
    d.text((56, 62), a.title, font=ft, fill=(18, 18, 22),
           stroke_width=max(3, a.title_size // 16), stroke_fill=(255, 255, 255), anchor="la")
    bbox = d.textbbox((56, 62), a.title, font=ft, anchor="la")
    y = bbox[3] + 16

    if a.sub:
        fs = ImageFont.truetype(reg, max(20, int(a.title_size * 0.4)))
        d.text((60, y), a.sub, font=fs, fill=(32, 32, 36),
               stroke_width=max(2, a.title_size // 20), stroke_fill=(255, 255, 255), anchor="la")
        sb = d.textbbox((60, y), a.sub, font=fs, anchor="la")
        y = sb[3]

    if not a.no_rule:
        d.line([(58, y + 16), (58 + max(180, int(a.title_size * 3.6)), y + 16)],
               fill=(24, 24, 28), width=3)

    # ---- 文案卡
    lines = [s.strip() for s in a.lines.split("|") if s.strip()]
    if lines:
        fb = ImageFont.truetype(reg, a.size)
        line_h = int(a.size * 2.1)
        pad_x, pad_y = 30, 30
        widest = max(d.textlength(t, font=fb) for t in lines)
        card_w = int(widest) + pad_x * 2
        card_h = line_h * (len(lines) - 1) + a.size + pad_y * 2
        card_x = 46
        card_y = (H - card_h - 42) if a.pos == "bottom" else (int(H * 0.62) - card_h // 2)

        card = Image.new("RGBA", (card_w, card_h), (255, 255, 255, a.card_alpha))
        img.paste(card, (card_x, card_y), card)
        d.rectangle([card_x, card_y, card_x + card_w, card_y + card_h],
                    outline=(24, 24, 28), width=3)
        ty = card_y + pad_y
        for t in lines:
            d.text((card_x + pad_x, ty), t, font=fb, fill=(22, 22, 26), anchor="la")
            ty += line_h

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"✓ {out}  ({W}×{H})")
    if lines:
        print(f"  文案卡 {card_w}×{card_h} @ ({card_x},{card_y}) · {len(lines)} 行")


if __name__ == "__main__":
    main()

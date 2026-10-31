#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
夜秣漫画生成器 · 对照看板生成器
================================

把分镜数据（JSON）灌进模板，产出一个**单文件、零依赖、双击即开**的 HTML：
左边是每一页的提示词，右边是这一页的成图，翻页对照着看。

用法
----
# 1) 用分镜 JSON 生成看板
python build_board.py --data chapter.json --out 第01章-对照台.html

# 2) 没有 JSON，只想先要个空壳手动填
python build_board.py --out 对照台.html

数据格式（chapter.json）
-----------------------
{
  "title": "我的漫画",
  "chapter": "第 1 章",
  "style": "日系厚涂 + 清晰勾线",
  "pages": [
    {
      "no": 1,
      "scene": "大学教室 / 上午",
      "costume": "男主白T牛仔裤 / 女主淡黄连衣裙",
      "skeleton": "竖排多格（3格）",
      "layout": "SB-023 · 由远到近",
      "family": "C情绪",
      "modes": "陈序之：正式版 / 苏念一：独白Q版（角落插图）",
      "anchor": ["全局色调：暖黄阳光调", "光源：左侧窗光", "背景：黑板课桌", "画风：日系厚涂"],
      "panels": [
        {"no": 1, "pos": "上", "shot": "全景", "desc": "教室全景，阳光洒入", "extra": "无"},
        {"no": 2, "pos": "中", "shot": "中景", "desc": "男主低头画画", "extra": "画板、铅笔"}
      ],
      "prompt": "完整英文生图提示词……",
      "panelPrompts": ["格1独立提示词", "格2独立提示词"],
      "image": "images/p01.png"
    }
  ]
}

图片怎么进来：三种方式任选
  1. 把图存成 images/p01.png、p02.png… 放在 HTML 同级目录（推荐，打开就有）
  2. 打开看板后，把图片拖到右栏（支持一次拖多张，按顺序填）
  3. 点「批量载入图片」选择文件
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(os.path.dirname(HERE), "templates", "对比看板.html")

PLACEHOLDER = "__BOARD_DATA__"


def empty_board():
    return {
        "title": "分镜对照台",
        "chapter": "",
        "style": "",
        "pages": [
            {
                "no": 1,
                "scene": "",
                "costume": "",
                "skeleton": "",
                "layout": "",
                "family": "",
                "modes": "",
                "anchor": [],
                "panels": [],
                "prompt": "",
                "panelPrompts": [],
                "image": "images/p01.png",
            }
        ],
    }


def normalize(data):
    """补默认值、按页号排序、把 image 路径规范化成相对路径。"""
    board = empty_board()
    board["title"] = data.get("title") or board["title"]
    board["chapter"] = data.get("chapter", "")
    board["style"] = data.get("style", "")

    pages = data.get("pages") or []
    if not pages:
        return board

    out = []
    for i, p in enumerate(pages, start=1):
        page = {
            "no": int(p.get("no", i)),
            "scene": p.get("scene", ""),
            "costume": p.get("costume", ""),
            "skeleton": p.get("skeleton", ""),
            "layout": p.get("layout", ""),
            "family": p.get("family", ""),
            "modes": p.get("modes", ""),
            "anchor": p.get("anchor") or [],
            "panels": p.get("panels") or [],
            "prompt": p.get("prompt", ""),
            "panelPrompts": p.get("panelPrompts") or [],
            "image": p.get("image") or "images/p%02d.png" % int(p.get("no", i)),
        }
        # 图片路径统一成「相对 HTML 的路径」，兼容 Windows 反斜杠
        page["image"] = str(page["image"]).replace("\\", "/")
        out.append(page)

    out.sort(key=lambda x: x["no"])
    board["pages"] = out
    return board


def build(data_path, out_path, title_override=None):
    if not os.path.exists(TEMPLATE):
        sys.exit("找不到模板：" + TEMPLATE)
    with open(TEMPLATE, "r", encoding="utf-8") as fh:
        tpl = fh.read()

    if data_path:
        with open(data_path, "r", encoding="utf-8") as fh:
            board = normalize(json.load(fh))
    else:
        board = empty_board()

    if title_override:
        board["title"] = title_override

    payload = json.dumps(board, ensure_ascii=False)
    # 防止数据里出现 </script> 截断脚本
    payload = payload.replace("</", "<\\/")

    html = tpl.replace(PLACEHOLDER, payload)
    html = html.replace("__TITLE__", board["title"])

    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)

    # 顺手建一个 images 目录，用户把图丢进去就有
    img_dir = os.path.join(out_dir, "images")
    os.makedirs(img_dir, exist_ok=True)

    print("✓ 对照台已生成：" + out_path)
    print("  页数：%d" % len(board["pages"]))
    print("  图片目录：%s" % img_dir)
    print("  把成图存成 p01.png / p02.png … 放进去，刷新即有；也可以打开后直接拖进去。")
    return out_path


def main():
    ap = argparse.ArgumentParser(description="夜秣漫画 · 对照看板生成器")
    ap.add_argument("--data", help="分镜数据 JSON（省略则生成空壳）")
    ap.add_argument("--out", required=True, help="输出的 HTML 路径")
    ap.add_argument("--title", help="覆盖作品标题")
    args = ap.parse_args()
    build(args.data, args.out, args.title)


if __name__ == "__main__":
    main()

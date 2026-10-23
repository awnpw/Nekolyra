# -*- coding: utf-8 -*-
r"""把「所有插件的指令 + 用法」画成图片（给群里的帮助指令用）。

为什么画图而不是发文字：
  · 指令有几十条，文字消息会刷屏、还会被 QQ 折叠；
  · 图里能做分组和层级，一眼能扫。

渲染走 Pillow（打包里已经带上了）。字体用系统的微软雅黑，
拿不到就退回默认字体 —— 绝不因为字体缺失把帮助整个搞挂。

**量高和画高必须是同一套数字**，否则分页会算错、底部提示会压住最后一段。
对外只有一个入口：render_help_pages(sections, out_dir, ...) -> [png 路径, ...]
"""

import os
import datetime

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except Exception:          # 没装/打包漏了 —— 调用方会退回纯文本
    _HAS_PIL = False


W = 900                    # 画布宽（QQ 群里常见的显示宽度）
PAD = 36
MAX_H = 1800               # 单页最高，超了就分页（太高在手机上看要放大半天）

# 行高（量与画共用）
H_TITLE = 34
H_DESC = 21
H_CMD = 24
H_HELP = 21
GAP_PLUG = 16              # 段与段之间
HEAD_H = 92
FOOT_H = 42
FOOT_GAP = 22              # 正文与页脚之间必须留出来，否则横线会压住最后一段

C_BG = (255, 255, 255)
C_HEAD = (10, 14, 26)
C_TEXT = (36, 42, 58)
C_SUB = (108, 116, 138)
C_LINE = (228, 232, 242)
C_ACCENT = (37, 99, 235)
C_CHIP_BG = (237, 243, 255)
C_FOOT = (150, 158, 178)

_FONT_MAIN = (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc")
_FONT_ALT = (r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simhei.ttf")


def _load(size, bold=False, pair=None):
    reg, bd = pair or _FONT_MAIN
    order = (bd, reg) if bold else (reg, bd)
    for p in order:
        try:
            if p and os.path.exists(p):
                return ImageFont.truetype(p, size)
        except Exception:
            continue
    for p in _FONT_ALT:
        try:
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _fonts():
    return {
        "title": _load(32, bold=True),
        "plug": _load(22, bold=True),
        "ver": _load(14),
        "desc": _load(15),
        # 命令名用**中文字体**：命令基本是中文，等宽字体没有汉字会全是方框
        "cmd": _load(16, bold=True),
        "help": _load(15),
        "foot": _load(13),
    }


def _text_w(draw, s, font):
    try:
        return draw.textlength(str(s), font=font)
    except Exception:
        return len(str(s)) * 8


def _wrap(draw, text, font, max_w):
    text = str(text or "").strip()
    if not text:
        return []
    out, line = [], ""
    for ch in text:
        if ch == "\n":
            out.append(line)
            line = ""
            continue
        if _text_w(draw, line + ch, font) > max_w and line:
            out.append(line)
            line = ch
        else:
            line += ch
    if line:
        out.append(line)
    return out


def _build(sections, f, draw):
    r"""摊平成可绘制块，每块给出**唯一**的高度；绘制阶段严格按这个高度推进。"""
    inner = W - PAD * 2
    items = []
    for s in sections:
        cmds = s.get("commands") or []
        if not cmds:
            continue
        desc = _wrap(draw, s.get("desc") or "", f["desc"], inner) if s.get("desc") else []
        items.append({
            "type": "plug", "name": s.get("name") or "?",
            "version": str(s.get("version") or ""), "desc": desc,
            # 段间距**不算进 h**，由绘制/分页各自按 first 加一次 ——
            # 之前算进 h、绘制时又加一遍，累计多画出 16px×段数，把末段顶到页脚上
            "h": 30 + len(desc) * H_DESC,
            "plug": True,
        })
        for cmd, help_text, prefix in cmds:
            # 没写说明就留白（插件作者不一定都写了 help）。
            # 以前这里画「（没写说明）」占位，几十条命令满屏占位符，比留白难看多了。
            lines = _wrap(draw, help_text or "", f["help"], inner - 200) if help_text else []
            items.append({
                "type": "cmd",
                "cmd": str(cmd) + (" …" if prefix else ""),
                "help": lines,
                "h": max(H_CMD, len(lines) * H_HELP) + 4,
            })
    return items


def _page_body(page):
    """一页正文占多高（含块间距）。"""
    return sum(it["h"] + it.get("gap_before", 0) for it in page)


def _finalize(pages):
    r"""给每页的块补上 gap_before：只有"页内不是第一块、且是插件块"才隔空。"""
    out = []
    for page in pages:
        fixed = []
        for i, it in enumerate(page):
            it = dict(it)
            it["gap_before"] = GAP_PLUG if (i > 0 and it.get("plug")) else 0
            fixed.append(it)
        out.append(fixed)
    return out


def _rebalance(pages):
    r"""末页只剩一小截时，从上一页尾部搬几块过来 —— 不然群里会收到一张
    几乎空白的第二张图。"""
    if len(pages) < 2:
        return pages
    min_page = 420
    for _ in range(400):
        last = pages[-1]
        last_h = HEAD_H + _page_body(last) + FOOT_GAP + FOOT_H
        if last_h >= min_page:
            break
        prev = pages[-2]
        if len(prev) <= 1:
            break
        moved = prev.pop()
        prev_h = HEAD_H + _page_body(prev) + FOOT_GAP + FOOT_H
        if prev_h < min_page:
            prev.append(moved)
            break
        pages[-1] = [moved] + last
    return pages


def _paginate(items):
    pages, cur, used = [], [], HEAD_H
    for it in items:
        gap = GAP_PLUG if (cur and it.get("plug")) else 0
        if cur and used + gap + it["h"] + FOOT_GAP + FOOT_H > MAX_H:
            pages.append(cur)
            cur, used = [], HEAD_H
            gap = 0
        cur.append(it)
        used += gap + it["h"]
    if cur:
        pages.append(cur)
    pages = _finalize(pages or [[]])
    return _rebalance(pages)


def render_help_pages(sections, out_dir, title="指令一览", subtitle="", footer_hint=""):
    r"""渲染成 1~N 张 PNG，返回路径列表；出错抛异常（调用方负责兜底文字版）。"""
    if not _HAS_PIL:
        raise RuntimeError("没有可用的 Pillow")
    os.makedirs(out_dir, exist_ok=True)
    f = _fonts()
    probe = ImageDraw.Draw(Image.new("RGB", (W, 10), C_BG))
    items = _build(sections, f, probe)
    pages = _paginate(items)
    total = len(pages)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    paths = []

    for idx, page in enumerate(pages):
        body = _page_body(page)
        H = HEAD_H + body + FOOT_GAP + FOOT_H
        img = Image.new("RGB", (W, H), C_BG)
        d = ImageDraw.Draw(img)

        d.text((PAD, 24), title, font=f["title"], fill=C_HEAD)
        sub = subtitle or ""
        if total > 1:
            sub = (sub + "  ·  " if sub else "") + "第 %d/%d 页" % (idx + 1, total)
        if sub:
            d.text((PAD, 64), sub, font=f["ver"], fill=C_SUB)
        d.line([(PAD, HEAD_H - 16), (W - PAD, HEAD_H - 16)], fill=C_LINE, width=1)

        y = HEAD_H
        for it in page:
            if it["type"] == "plug":
                y += it.get("gap_before", 0)
                d.text((PAD, y), it["name"], font=f["plug"], fill=C_HEAD)
                if it["version"]:
                    nw = _text_w(d, it["name"], f["plug"])
                    chip = "v" + it["version"]
                    cw = _text_w(d, chip, f["ver"])
                    d.rounded_rectangle([PAD + nw + 10, y + 4, PAD + nw + 10 + cw + 14, y + 26],
                                        radius=6, fill=C_CHIP_BG)
                    d.text((PAD + nw + 17, y + 7), chip, font=f["ver"], fill=C_ACCENT)
                yy = y + 30
                for ln in it["desc"]:
                    d.text((PAD, yy), ln, font=f["desc"], fill=C_SUB)
                    yy += H_DESC
                y += it["h"]
            else:
                d.text((PAD + 2, y + 2), it["cmd"], font=f["cmd"], fill=C_ACCENT)
                yy = y + 2
                for ln in it["help"]:
                    d.text((PAD + 200, yy), ln, font=f["help"], fill=C_TEXT)
                    yy += H_HELP
                y += it["h"]

        fy = HEAD_H + body + FOOT_GAP
        d.line([(PAD, fy - 10), (W - PAD, fy - 10)], fill=C_LINE, width=1)
        tail = (footer_hint + "  ·  " if footer_hint else "") + "生成于 " + stamp
        d.text((PAD, fy), tail, font=f["foot"], fill=C_FOOT)

        p = os.path.join(out_dir, "help_%02d.png" % (idx + 1))
        img.save(p, format="PNG", optimize=True)
        paths.append(p)
    return paths

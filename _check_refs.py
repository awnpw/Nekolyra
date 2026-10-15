# -*- coding: utf-8 -*-
r"""悬空引用检查：HTML 里 onclick/onchange 等内联事件引用的函数，JS 里是否真的存在。

删功能时最容易留下的坑：按钮还在，函数已经没了 —— 点了报错，或者整段脚本
因为一处 ReferenceError 直接不执行（"什么都点不动"就是这个）。

同时检查 JS 里调用的、以 setPage/load 开头的本地函数是否存在。
"""
import io
import os
import re
import sys

P = r"D:\ai\qq_bot\bot.py"
s = io.open(P, encoding="utf-8").read()

# 管理页前端已经拆成独立文件了（见 nekolyra/web/static/）。
# （以前是从 bot.py 的 ADMIN_HTML + 12 个 *_CSS 常量里正则抠出来的。
#   常量没了，再按老办法读会静默退化成"分析整个 bot.py"，全是假结果。）
HTML_P = r"D:\ai\qq_bot\nekolyra\web\static\admin.html"
JS_P = r"D:\ai\qq_bot\nekolyra\web\static\admin.js"
CSS_P = r"D:\ai\qq_bot\nekolyra\web\static\admin.css"
html = io.open(HTML_P, encoding="utf-8").read()
js = io.open(JS_P, encoding="utf-8").read()
# 第 3 段的"残留引用"要在页面上也查一遍。以前页面就在 s 里，
# 现在拆出去了，必须补进来 —— 否则 page-points / data-api="wife"
# 这类东西删干净了也看不出来。
s = "\n".join([s, html, js, io.open(CSS_P, encoding="utf-8").read()])
print(f"  取自 admin.html / admin.js：HTML {len(html)} 字符，"
      f"其中 JS {len(js)} 字符")

# JS 里定义的函数名（function foo / var foo=function / const foo=async (…) => / foo=()=>）
defined = set()
for m in re.finditer(r"function\s+([A-Za-z_$][\w$]*)", js):
    defined.add(m.group(1))
for m in re.finditer(r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function|\()", js):
    defined.add(m.group(1))
for m in re.finditer(r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?[A-Za-z_$][\w$]*\s*=>", js):
    defined.add(m.group(1))
for m in re.finditer(r"^\s*([A-Za-z_$][\w$]*)\s*[:=]\s*(?:async\s*)?\([^)]*\)\s*=>", js, re.M):
    defined.add(m.group(1))
# window.xxx = ...
for m in re.finditer(r"window\.([A-Za-z_$][\w$]*)\s*=", js):
    defined.add(m.group(1))

# 浏览器内置 / 全局，不算悬空
BUILTIN = {
    "alert", "confirm", "prompt", "print", "open", "close", "focus", "blur",
    "location", "history", "navigator", "document", "window", "console",
    "setTimeout", "setInterval", "clearTimeout", "clearInterval",
    "encodeURIComponent", "decodeURIComponent", "parseInt", "parseFloat",
    "String", "Number", "Boolean", "Array", "Object", "JSON", "Math", "Date",
    "Promise", "Error", "RegExp", "Map", "Set", "URLSearchParams", "fetch",
    "requestAnimationFrame", "isNaN", "escape", "unescape", "eval", "this",
    "event", "arguments", "return", "if", "for", "while", "switch", "catch",
    "typeof", "new", "function", "async", "await", "true", "false", "null",
    "undefined", "void", "delete", "in", "of", "instanceof", "class", "const",
    "let", "var", "try", "else", "do", "break", "continue", "throw", "case",
    "default", "yield", "static", "get", "set", "super", "extends",
    "copyText", "toast", "api", "post", "esc",
}

# 1) HTML 内联事件
print("=" * 66)
print("HTML 内联事件引用的函数")
print("=" * 66)
inline = set()
for m in re.finditer(r'\son(?:click|change|input|submit|keydown|keyup|focus|blur)\s*=\s*"([^"]*)"', html):
    body = m.group(1)
    for f in re.finditer(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", body):
        inline.add(f.group(1))
missing = sorted(x for x in inline if x not in defined and x not in BUILTIN)
print(f"  内联事件共引用 {len(inline)} 个函数")
if missing:
    print(f"  ❌ {len(missing)} 个找不到定义:")
    for x in missing:
        # 找出引用位置
        for mm in re.finditer(r'on\w+\s*=\s*"[^"]*\b' + re.escape(x) + r'\s*\(', html):
            ln = html[:mm.start()].count("\n") + 1
            print(f"      {x}  (首次出现 L{ln})")
            break
else:
    print("  ✅ 全都能找到定义")

# 2) JS 内部调用 setPage/load*/render*/run*/toggle* 这类本地函数
print()
print("=" * 66)
print("JS 内部调用的本地函数（setPage / load* / render* / run* / toggle*）")
print("=" * 66)
called = set()
for m in re.finditer(r"(?<![.\w$])((?:setPage|load|render|run|toggle|setPlugTab|install|uninstall|update|save|clear|show|submit|add)[A-Za-z0-9_$]*)\s*\(", js):
    called.add(m.group(1))
missing2 = sorted(x for x in called if x not in defined and x not in BUILTIN)
print(f"  共调用 {len(called)} 个")
if missing2:
    print(f"  ❌ {len(missing2)} 个找不到定义:")
    for x in missing2:
        for mm in re.finditer(r"\b" + re.escape(x) + r"\s*\(", js):
            ln = js[:mm.start()].count("\n") + 1
            line = js.splitlines()[ln - 1].strip()[:110] if ln <= len(js.splitlines()) else ""
            print(f"      {x}  (L{ln}) {line}")
            break
else:
    print("  ✅ 全都能找到定义")

# 3) 已被删掉的功能，不该再有任何引用
print()
print("=" * 66)
print("已迁出主程序的功能，不该再有残留引用")
print("=" * 66)
GONE = ["do_lottery", "LOTTERY_KW", "runLottery", "lottery_last",
        "do_report", "REPORT_YESTERDAY_KW", "REPORT_TODAY_KW",
        "REPORT_DEFAULT_KW", "runReport", "_report_impl",
        "do_sign", "SIGN_KW", "RANK_KW", "ME_KW", "runSign", "runRank",
        "runMe", "loadPoints", "clearPoints", "_sign_impl",
        "api/sign", "api/points", "page-points",
        'data-page="points"', 'data-api="sign"', 'data-api="rank"',
        'data-api="me"', 'id="api-sign"', 'id="api-rank"', 'id="api-me"',
        # 今日老婆（第 4 个迁走的）
        'do_wife', '_wife_impl', '_gen_wife_intro', '_wife_change_cost',
        'WIFE_KW', 'WIFE_CHANGE_KW', 'runWife', 'def wife_get', 'def wife_save',
        'def wife_try_change', 'def wife_clear', 'api/wife',
        'CREATE TABLE IF NOT EXISTS wife_records',
        'data-api="wife"', 'data-api="wifechange"',
        'id="api-wife"', 'id="api-wifechange"']
bad = [g for g in GONE if g in s]
if bad:
    print(f"  ❌ 还有 {len(bad)} 个残留: {bad}")
else:
    print(f"  ✅ {len(GONE)} 个全部已清干净")

sys.exit(1 if (missing or missing2 or bad) else 0)

# -*- coding: utf-8 -*-
r"""全量体检 —— 从静态检查一直到真实行为。

分七层，每层都实际跑、不靠"看代码觉得没问题"：

  ① 静态      ast.parse / pyflakes / 三个自检脚本
  ② 守门      35 项行为探测（自己起沙箱）
  ③ 接口      把源码里所有 GET 路由都打一遍
  ④ 页面      管理页的 JS 函数 / 容器 / 引用
  ⑤ 行为      /api/chat 真跑几条，看回复和日志
  ⑥ 插件      8 个插件的加载状态和声明
  ⑦ 日志      有没有 Traceback / NameError

**不断言"应该没问题"，只报实测结果。**
"""
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = r"D:\ai\qq_bot"
INST = r"D:\ai\Nekoe-v1.0.0.0"
PY = r"C:\Users\ry135\AppData\Local\Python\pythoncore-3.14-64\python.exe"
T = "1234569w"
B = "http://127.0.0.1:8080"

FAIL = []
WARN = []


def head(t):
    print()
    print("=" * 78)
    print(t)
    print("=" * 78)


def run(cmd, cwd=None, timeout=1800):
    return subprocess.run(cmd, cwd=cwd or BASE, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


# ============================================================
head("① 静态检查")
# ============================================================
r = run([PY, "-c", "import ast,io;ast.parse(io.open('bot.py',encoding='utf-8').read())"])
print("    bot.py 语法        %s" % ("✅" if r.returncode == 0 else "❌ " + r.stderr[:120]))
if r.returncode:
    FAIL.append("bot.py 语法")

r = run([PY, "-m", "pyflakes", "bot.py", "nekolyra"])
lines = [l for l in (r.stdout or "").splitlines() if l.strip()]
# 两类"本来就不是错"的：
#   1) 搬家留下的 unused import / f-string 没占位符
#   2) routes_*.py 里 register 注入的名字 —— pyflakes 看不到 globals().update(deps)
KNOWN = ("imported but unused", "f-string is missing placeholders")
real = []
for l in lines:
    if any(k in l for k in KNOWN):
        continue
    if "undefined name" in l and re.search(r"routes_\w+\.py", l):
        continue          # register 注入的，本来就该"未定义"
    real.append(l)
print("    pyflakes           %d 条（%d 条是已知无害的）"
      % (len(lines), len(lines) - len(real)))
for l in real[:8]:
    print("      ❌ %s" % l[:130])
if real:
    FAIL.append("pyflakes: %s" % real[0][:60])

for script, tag in (("_check_ui.py", "UI 容器/函数"),
                    ("_check_html.py", "标签配对"),
                    ("_check_refs.py", "前端引用")):
    r = run([PY, script])
    last = [l for l in (r.stdout or "").splitlines() if l.strip()]
    ok = "✅" in (last[-1] if last else "") or "通过" in (last[-1] if last else "")
    print("    %-14s %s   %s" % (tag, "✅" if ok else "❌", (last[-1] if last else "")[:60]))
    if not ok:
        FAIL.append(script)

# 「不伪造用户说的话」—— 用户在意的点，单独查
b = io.open(os.path.join(BASE, "bot.py"), encoding="utf-8").read()
qq = io.open(os.path.join(BASE, "nekolyra", "adapters", "qq.py"),
             encoding="utf-8").read()
n_fake = b.count('raw_text = "在吗"') + qq.count('text = "在吗"')
print("    伪造「在吗」        %d 处 %s" % (n_fake, "✅" if n_fake == 0 else "❌"))
if n_fake:
    FAIL.append("还有伪造文本")

# ============================================================
# ② 守门脚本（**必须放最后**）
# ============================================================
# ⚠ 踩过的坑：_build_guard.py 里会 taskkill /F /IM Nekolyra.exe，
# 因为它要替换 exe 做沙箱测试。放在前面的话，等于**先把被测对象杀了再测它** ——
# 后面 ③~⑦ 全部 URLError，看起来像"程序崩溃了"，其实是自己干的。
#
# 今天为此误判了三轮（05:17 / 12:49 / 13:12 三次"它自己挂了"全是这个）。
# 所以挪到最后，而且跑完提醒要重启实例。


def guard_layer():
    head("② 守门脚本 35 项行为探测（⚠ 这一步会杀掉正在跑的实例）")
    r = run([PY, "_build_guard.py"], timeout=3000)
    out = r.stdout or ""
    tail = [l for l in out.splitlines() if "探测通过" in l or "探测失败" in l]
    print("    %s" % (tail[-1].strip() if tail else "❌ 没拿到结论"))
    if not tail or "探测通过" not in tail[-1]:
        FAIL.append("守门探测")
        for l in out.splitlines():
            if "FAIL" in l or "❌" in l:
                print("      %s" % l.strip()[:140])
    print()
    print("    ⚠ 实例已经被这一步杀掉 —— 要接着测别的，先重新启动它")

# ============================================================
head("③ 接口（源码里所有 GET 路由）")
# ============================================================
paths = set()
for f, src in (("bot.py", b),):
    for m in re.finditer(r'@app\.get\("([^"]+)"\)', src):
        paths.add(m.group(1))
d = os.path.join(BASE, "nekolyra", "web")
for f in sorted(os.listdir(d)):
    if f.startswith("routes_") and f.endswith(".py"):
        s = io.open(os.path.join(d, f), encoding="utf-8").read()
        for m in re.finditer(r'@app\.get\("([^"]+)"\)', s):
            paths.add(m.group(1))
gets = sorted(p for p in paths if "{" not in p)


def get(path, timeout=120, tok=True):
    sep = "&" if "?" in path else "?"
    u = B + path + (sep + "token=" + T if tok else "")
    with urllib.request.urlopen(u, timeout=timeout) as r:
        return json.loads(r.read())


ok = warn = bad = 0
for p in gets:
    try:
        with urllib.request.urlopen(
                B + p + ("&" if "?" in p else "?") + "token=" + T,
                timeout=120) as r:
            raw = r.read()
        ok += 1
    except urllib.error.HTTPError as e:
        if e.code < 500:
            warn += 1
        else:
            bad += 1
            print("    ❌ %-46s HTTP %s" % (p[:46], e.code))
            FAIL.append("接口 %s" % p)
    except Exception as e:
        bad += 1
        print("    ❌ %-46s %s" % (p[:46], type(e).__name__))
        FAIL.append("接口 %s" % p)
print("    %d 个 GET：%d 正常 / %d 参数类 4xx / %d 真错" % (len(gets), ok, warn, bad))

# ============================================================
head("④ 管理页")
# ============================================================
try:
    with urllib.request.urlopen(B + "/admin?token=" + T, timeout=120) as r:
        h = r.read().decode("utf-8", "replace")
    print("    页面        %d 字符" % len(h))
    called = set(re.findall(r'on(?:click|change)="(\w+)\(', h))
    defined = set(re.findall(r'function\s+(\w+)\s*\(', h))
    defined |= set(re.findall(r'(\w+)\s*=\s*async\s*\(', h))
    missing = sorted(c for c in called if c not in defined and c not in ("fn", "if"))
    print("    调了 %d 个函数，缺定义 %s" % (len(called), missing or "无 ✅"))
    if missing:
        FAIL.append("页面缺函数 %s" % missing[0])
    boot = re.findall(r'if\(n==="(\w+)"\)(\w+)\(\)', h)
    badboot = [(n, fn) for n, fn in boot if fn not in defined]
    print("    切页钩子 %d 个，缺 %s" % (len(boot), badboot or "无 ✅"))
    if badboot:
        FAIL.append("切页钩子缺 %s" % badboot[0][1])
    # 时间观念在不在
    print("    提示词里的时间   %s"
          % ("✅（要看 ⑤ 的实际回复）" if "【当前时间】" not in h else "在页面里？"))
except Exception as e:
    print("    ❌ 取页面失败: %s" % e)
    FAIL.append("管理页")

# ============================================================
head("⑤ 行为：/api/chat 真跑")
# ============================================================


def chat(text, uid=2338914955, gid=312546565, timeout=240):
    body = json.dumps({"text": text, "user_id": uid, "group_id": gid}).encode()
    rq = urllib.request.Request(B + "/api/chat?token=" + T, data=body,
                                headers={"Content-Type": "application/json"},
                                method="POST")
    with urllib.request.urlopen(rq, timeout=timeout) as r:
        return json.loads(r.read())


now = time.strftime("%H:%M")
print("    现在真实时间 %s" % now)
cases = [
    ("时间观念", "现在几点？只答时间，不要别的话"),
    ("记忆",     "你还记得我上次说的事吗"),
    ("短句",     "嗯"),
]
for tag, q in cases:
    t0 = time.time()
    try:
        d = chat(q)
        rep = str(d.get("reply") or d)[:110]
        print("    %-8s %.1fs  %r" % (tag, time.time() - t0, rep))
        if tag == "时间观念":
            hh = now.split(":")[0].lstrip("0") or "0"
            if hh in rep:
                print("             ✅ 答出的小时跟真实时间对得上")
            else:
                print("             ⚠ 没在回复里看到当前小时（模型可能只说分钟/整点）")
    except Exception as e:
        print("    %-8s ❌ %s: %s" % (tag, type(e).__name__, e))
        FAIL.append("chat %s" % tag)

# ============================================================
head("⑥ 插件")
# ============================================================
try:
    d = get("/admin/api/plugins")
    items = d.get("items") or []
    print("    %d 个" % len(items))
    for it in items:
        nm = it.get("name")
        err = (it.get("error") or "")[:56]
        print("      %-12s loaded=%-6s api=%-5s perms=%-22s %s"
              % (nm, it.get("loaded"), it.get("api_version") or "-",
                 ",".join(it.get("permissions") or []) or "-", err))
except Exception as e:
    print("    ❌ %s" % e)
    FAIL.append("插件接口")

# ============================================================
head("⑦ 日志")
# ============================================================
LOG = os.path.join(INST, "startup.log")
lines = io.open(LOG, encoding="utf-8", errors="replace").read().splitlines()
print("    %d 行，最后改动 %s" % (len(lines),
      time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(LOG)))))
bad = [l for l in lines[-200:] if any(k in l for k in
       ("Traceback", "NameError", "ImportError", "AttributeError", "TypeError"))]
print("    近 200 行里的异常: %d 条 %s" % (len(bad), "" if not bad else bad[0][:110]))
for l in bad[:4]:
    print("      %s" % l.strip()[:130])
if bad:
    FAIL.append("日志异常")
# 时间戳跟真实时间对不对得上
m = re.match(r"\[(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)\]", lines[-1]) if lines else None
if m:
    real = time.strftime("%m-%d %H:%M")
    got = "%s-%s %s:%s" % m.groups()[:4]
    print("    最后一行时间戳 %s / 真实 %s  %s"
          % (got, real, "✅" if got == real else "⚠ 可能隔了几分钟"))

# ============================================================
head("结论")
# ============================================================
print("    失败 %d 项" % len(FAIL))
for f in FAIL:
    print("      ❌ %s" % f[:130])
if not FAIL:
    print("      ✅ 全过")

# 守门放最后（它会杀实例）
guard_layer()

# 跑完看一眼实例还在不在
alive = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Nekolyra.exe"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60).stdout or ""
print()
if "Nekolyra.exe" in alive:
    print("    实例还在跑 ✅")
else:
    print("    实例已经不在了（被守门那步杀的）—— 要用的话记得重新启动")

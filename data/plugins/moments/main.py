# -*- coding: utf-8 -*-
"""朋友圈：她自己发 QQ 空间说说。

**谁在决定？她。**
这个插件里没有随机间隔、没有概率跳过——那些都是代码在替她做决定，发出来一看就假。
做法是：每隔一段时间把她**唤醒一次**，问一句"现在想不想发？发什么？下次多久后再想？"，
三件事全由模型输出。代码只保留两条**护栏**（不是决策）：
  下限 mt_min_gap —— 防止一秒一条刷屏
  上限 mt_max_gap —— 防止她说"我一年后再想"

为什么必须有"唤醒"这一步：模型没有时钟，不会自己在后台醒来。
能给的是"每次醒来时的自主权"，不是真正自由的计时器。

依赖 NapCat 扩展动作 send_qzone_msg。
注意：get_qzone_msg_list 在这版 NapCat 没实现（retcode 1404），
所以"发过什么"记在本地 kv，不从空间读。
"""
import asyncio
import os
import re
import time

_STATE = {"task": None, "next_at": 0.0, "last": None, "think": None}

_URL_RE = re.compile(r"https?://\S+")
_NUM_RE = re.compile(r"(?<!\d)\d{6,}(?!\d)")
_WS_RE = re.compile(r"[ \t\u3000]+")
_BAD = ("台独", "港独", "法轮", "六四", "翻墙", "政治", "代练", "广告位")


def setup(ctx):
    def cb(key, default):
        v = ctx.cfg(key, default)
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "on", "开启")
        return bool(v)

    def ci(key, default):
        try:
            v = ctx.cfg(key, default)
            return default if v in (None, "") else int(float(v))
        except Exception:
            return default

    data_dir = os.path.dirname(os.path.dirname(os.path.abspath(ctx.dir)))

    def _persona():
        return (
            str(ctx.cfg("persona_name", "") or "她").strip(),
            str(ctx.cfg("persona_identity", "") or "").strip(),
            str(ctx.cfg("persona_behavior", "") or "").strip(),
            str(ctx.cfg("persona_speech", "") or "").strip(),
        )

    def _recent_chat(limit=24):
        try:
            rows = ctx.db_query(
                "SELECT nickname, text FROM chat_log WHERE is_bot=0 "
                "ORDER BY id DESC LIMIT ?", (limit,))
        except Exception as e:
            ctx.warn("读聊天记录失败：%s: %s" % (type(e).__name__, e))
            return []
        out = []
        for r in rows or []:
            try:
                nick, text = r[0], r[1]
            except Exception:
                continue
            text = str(text or "").strip().replace("\n", " ")
            if not text or len(text) > 80:
                continue
            out.append("%s：%s" % (nick or "某人", text))
        out.reverse()
        return out

    def _sticker_file():
        try:
            rows = ctx.db_query(
                "SELECT hash, ext FROM stickers WHERE kind='sticker' "
                "ORDER BY RANDOM() LIMIT 1")
        except Exception:
            return None
        if not rows:
            return None
        try:
            name = "%s.%s" % (rows[0][0], rows[0][1])
        except Exception:
            return None
        p = os.path.join(data_dir, "stickers", name)
        return p if os.path.isfile(p) else None

    def _remember(text):
        old = ctx.kv_get("moments_recent", [])
        if not isinstance(old, list):
            old = []
        old = [text] + [x for x in old if x != text]
        ctx.kv_set("moments_recent", old[:8])

    def _clean(txt):
        t = str(txt or "").strip().strip("\u201c\u201d\"'\u0060 \n\t")
        for pref in ("说说：", "说说:", "正文：", "正文:", "内容：", "内容:", "文案："):
            if t.startswith(pref):
                t = t[len(pref):].strip()
        t = _URL_RE.sub("", t)
        t = _NUM_RE.sub("", t)
        t = _WS_RE.sub(" ", t)
        t = " ".join(x.strip() for x in t.split("\n") if x.strip())
        if len(t) >= 2 and t[0] in "\u201c\"'" and t[-1] in "\u201d\"'":
            t = t[1:-1].strip()
        limit = max(40, min(400, ci("mt_max_len", 140)))
        if len(t) > limit:
            t = t[:limit].rstrip("，,、 ") + "…"
        if not t or any(b in t for b in _BAD):
            return ""
        return t

    def _how_long_ago(ts):
        if not ts:
            return "你还没发过说说。"
        mins = int((time.time() - float(ts)) / 60)
        if mins < 60:
            return "你上一次发说说是在 %d 分钟前。" % mins
        if mins < 60 * 24:
            return "你上一次发说说是在 %d 小时前。" % (mins // 60)
        return "你上一次发说说是在 %d 天前。" % (mins // 1440)

    async def _think():
        name, ident, beh, sp = _persona()
        lines = _recent_chat(24)
        context = "\n".join(lines) if lines else "（群里最近很安静）"
        old = ctx.kv_get("moments_recent", []) or []
        avoid = "\n".join("- " + str(x) for x in old[:6]) or "（还没发过）"
        last_ts = float(ctx.kv_get("moments_last_ts", 0) or 0)
        now = time.strftime("%Y-%m-%d %H:%M", time.localtime())
        week = "一二三四五六日"[time.localtime().tm_wday]
        prompt = (
            "你就是%s。%s%s%s\n" % (name, ident, beh, sp)
            + "你在过自己的日子，没人管你，也没人要求你现在必须发什么。\n"
            + "现在是 %s（星期%s）。%s\n\n" % (now, week, _how_long_ago(last_ts))
            + "群里最近在聊：\n%s\n\n" % context
            + "你以前发过的说说（别重复）：\n%s\n\n" % avoid
            + "现在轮到你决定：这一刻，你想不想在空间发条说说？\n"
            + "想发就自己写；不想发就不发，没人在催你。\n\n"
            + "然后自己决定：你打算什么时候再想起这件事？可以写「几点」（22:40、明天08:30），也可以写「几分钟后」。\n"
            + "刚发完可能很快想再看一眼，也可能要到明天才想起来，随你。\n\n"
            + "写的时候遵守：\n"
            + "1. 一到三句，口语，像随手发的，别写成作文。\n"
            + "2. 不许点名任何人、不许出现 QQ 号/群号/链接、不许说自己是 AI 或机器人。\n"
            + "3. 不要「#话题」，emoji 最多一个。\n\n"
            + "严格按这四行输出，不要多写别的：\n"
            + "NOW: 发  或  不发\n"
            + "TEXT: 正文；不发就写 -\n"
            + "IMAGE: 带  或  不带\n"
            + "NEXT: 直接写你打算几点再想这件事（例：22:40 / 明天08:30），写分钟数也行\n"
            + "REASON: 一句话说明你为什么这么决定"
        )
        try:
            raw = await ctx.ai(prompt, timeout=60.0)
        except Exception as e:
            ctx.warn("思考失败：%s: %s" % (type(e).__name__, e))
            return None
        return _parse(raw)

    def _parse(raw):
        t = str(raw or "")
        out = {"now": "", "text": "", "image": False, "next": 0, "reason": ""}
        m = re.search(r"NOW\s*[:：]\s*(发|不发)", t)
        out["now"] = m.group(1) if m else ""
        m = re.search(r"TEXT\s*[:：]\s*(.+)", t)
        if m:
            out["text"] = _clean(m.group(1))
        m = re.search(r"IMAGE\s*[:：]\s*(带|不带)", t)
        out["image"] = bool(m and m.group(1) == "带")
        m = re.search(r"NEXT\s*[:：]\s*(.+)", t)
        if m:
            out["next_spec"] = m.group(1).strip()[:24]
            _d = re.search(r"(\d+)", out["next_spec"])
            if _d:
                out["next"] = int(_d.group(1))
        m = re.search(r"REASON\s*[:：]\s*(.+)", t)
        if m:
            out["reason"] = m.group(1).strip()[:120]
        if not out["now"] and not out["text"]:
            guess = _clean(t)
            if guess:
                out["now"] = "发"
                out["text"] = guess
        return out
    async def _publish(text, with_image=False):
        params = {"content": text, "ugc_right": ci("mt_ugc_right", 4)}
        imgs = []
        if with_image and cb("mt_allow_image", True):
            p = _sticker_file()
            if p:
                imgs.append("file:///" + p.replace("\\", "/"))
        if imgs:
            params["images"] = imgs
        try:
            res = await ctx.onebot("send_qzone_msg", **params)
        except Exception as e:
            msg = "%s: %s" % (type(e).__name__, e)
            ctx.warn("发说说失败：%s" % msg)
            _STATE["last"] = {"text": text, "ts": time.time(), "ok": False, "error": msg}
            return False, msg
        if res is None:
            # ctx.onebot 会吞异常返回 None，这里不能假装成功
            _STATE["last"] = {"text": text, "ts": time.time(), "ok": False,
                              "error": "NapCat 返回空（看日志）"}
            return False, "NapCat 返回空（看日志）"
        _remember(text)
        ctx.kv_set("moments_last_ts", time.time())
        _STATE["last"] = {"text": text, "image": bool(imgs), "ts": time.time(), "ok": True}
        ctx.log("发了一条说说%s：%s" % ("（带图）" if imgs else "", text[:40]))
        return True, res

    def _next_seconds(spec):
        """把她的 NEXT 解析成秒数：22:40 / 明天08:30 / 45 / +45。

        她用不着自己算间隔 —— 适配器每次都在提示词里放了【当前时间】
        （nekolyra/adapters/ai.py 里那段，每次现算，不能缓存），
        所以让她直接说"几点再想"最自然，换算交给这里。
        """
        s = str(spec or "").strip()
        if not s:
            return None
        m = re.search(r"(\d{1,2})\s*[:：]\s*(\d{2})", s)
        if m:
            hh, mm = int(m.group(1)), int(m.group(2))
            if 0 <= hh < 24 and 0 <= mm < 60:
                now = time.localtime()
                tgt = time.mktime((now.tm_year, now.tm_mon, now.tm_mday,
                                   hh, mm, 0, 0, 0, -1))
                if "明天" in s or tgt <= time.time() + 30:
                    tgt += 86400
                return max(60.0, tgt - time.time())
        m = re.search(r"(\d+)", s)
        if m:
            return max(60.0, int(m.group(1)) * 60.0)
        return None

    def _schedule_secs(secs):
        lo = max(5, ci("mt_min_gap", 15)) * 60.0
        hi = max(lo, ci("mt_max_gap", 1440) * 60.0)
        try:
            secs = float(secs)
        except Exception:
            secs = lo
        if secs <= 0:
            secs = lo
        nxt = time.time() + max(lo, min(hi, secs))
        _STATE["next_at"] = nxt
        ctx.kv_set("moments_next_at", nxt)
        return nxt

    def _schedule_think(d):
        secs = _next_seconds((d or {}).get("next_spec", ""))
        if secs is None:
            secs = float(ci("mt_min_gap", 15)) * 60.0
        return _schedule_secs(secs)

    async def _wake_once():
        d = await _think()
        if not d:
            _schedule_secs(ci("mt_min_gap", 15) * 60.0)
            return
        _STATE["think"] = {
            "now": d.get("now"), "text": d.get("text"), "image": d.get("image"),
            "next_spec": d.get("next_spec"), "reason": d.get("reason"),
            "ts": time.time(),
        }
        will = (d.get("now") == "发") and bool(d.get("text"))
        ctx.log("她想了一下：%s（%s） 下次她说：%s"
                % ("发" if will else "不发", d.get("reason") or "-",
                   d.get("next_spec") or "?"))
        if will:
            if cb("mt_dry_run", False):
                ctx.log("（演练模式）本来要发：%s" % d.get("text"))
                _STATE["last"] = {"text": d.get("text"), "ts": time.time(),
                                  "ok": True, "dry": True}
            else:
                await _publish(d.get("text"), with_image=bool(d.get("image")))
        _schedule_think(d)

    async def _loop():
        await asyncio.sleep(20)
        while True:
            try:
                if not cb("mt_enabled", True):
                    await asyncio.sleep(300)
                    continue
                nxt = _STATE["next_at"] or float(ctx.kv_get("moments_next_at", 0) or 0)
                if nxt <= 0:
                    _schedule_secs(ci("mt_min_gap", 15) * 60.0)
                    continue
                wait = nxt - time.time()
                if wait > 0:
                    await asyncio.sleep(min(wait, 90.0))
                    continue
                await _wake_once()
            except Exception as e:
                ctx.warn("循环异常：%s: %s" % (type(e).__name__, e))
                await asyncio.sleep(120)

    def _ensure_task():
        if _STATE["task"] is not None and not _STATE["task"].done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        _STATE["task"] = loop.create_task(_loop())
        ctx.log("朋友圈已启用：什么时候发由她自己想")

    try:
        _ensure_task()
    except Exception:
        pass

    def _super_ok(event):
        try:
            return ctx.is_super(int(getattr(event, "user_id", 0) or 0))
        except Exception:
            return False

    async def _reply(event, text):
        gid = getattr(event, "group_id", None)
        try:
            if gid:
                await ctx.send_group(int(gid), text)
            else:
                await ctx.send_private(int(getattr(event, "user_id", 0) or 0), text)
        except Exception:
            pass

    @ctx.command("发说说", help="让她立刻想一次（该发就发），仅超管", timeout=150)
    async def _cmd_post(event, cmd):
        if not _super_ok(event):
            return True
        d = await _think()
        if not d:
            await _reply(event, "她走神了，没想出东西。")
            return True
        will = (d.get("now") == "发") and bool(d.get("text"))
        if not will:
            await _reply(event, "她说这次不想发：%s" % (d.get("reason") or "没理由"))
            _schedule_think(d)
            return True
        ok, err = await _publish(d.get("text"), with_image=bool(d.get("image")))
        await _reply(event, ("发了：" if ok else "发失败了：") + (d.get("text") if ok else str(err)))
        _schedule_think(d)
        return True

    @ctx.command("说说预览", help="只让她想一次，不发布，仅超管", timeout=150)
    async def _cmd_preview(event, cmd):
        if not _super_ok(event):
            return True
        d = await _think()
        if not d:
            await _reply(event, "这次真没想出来。")
            return True
        will = (d.get("now") == "发") and bool(d.get("text"))
        head = ("她想发：\n" + str(d.get("text"))) if will else "她说现在不想发。"
        await _reply(event, head + "\n（理由：%s ／ 下次 %s 分钟后）"
                     % (d.get("reason") or "-", d.get("next") or "?"))
        return True

    @ctx.command("最近的说说", help="她最近发过什么（本地记录）", timeout=30)
    async def _cmd_recent(event, cmd):
        old = ctx.kv_get("moments_recent", []) or []
        if not old:
            await _reply(event, "她还没发过说说。")
            return True
        lines = ["她最近发的（本地记录）："]
        for x in old[:5]:
            lines.append("- " + str(x)[:50])
        await _reply(event, "\n".join(lines))
        return True

    def _state_dict():
        nxt = _STATE["next_at"] or float(ctx.kv_get("moments_next_at", 0) or 0)
        return {
            "ok": True,
            "enabled": cb("mt_enabled", True),
            "dry_run": cb("mt_dry_run", False),
            "clamp": [ci("mt_min_gap", 15), ci("mt_max_gap", 1440)],
            "ugc_right": ci("mt_ugc_right", 4),
            "allow_image": cb("mt_allow_image", True),
            "next_at": nxt,
            "next_in": max(0, int(nxt - time.time())) if nxt else 0,
            "last": _STATE["last"],
            "think": _STATE["think"],
            "recent": ctx.kv_get("moments_recent", []) or [],
        }

    def api_state(request, body):
        return _state_dict()

    def api_save(request, body):
        b = body or {}
        if b.get("clear_recent"):
            # 说说已经在空间删掉了，本地记录也要跟着清，不然「最近的说说」会骗人
            ctx.kv_set("moments_recent", [])
            ctx.kv_set("moments_last_ts", 0)
        ctx.set_cfg("mt_enabled", bool(b.get("enabled", True)))
        ctx.set_cfg("mt_dry_run", bool(b.get("dry_run", False)))
        ctx.set_cfg("mt_allow_image", bool(b.get("allow_image", True)))
        for key, field, lo in (("mt_min_gap", "min_gap", 5),
                               ("mt_max_gap", "max_gap", 30),
                               ("mt_ugc_right", "ugc_right", 1),
                               ("mt_max_len", "max_len", 40)):
            try:
                ctx.set_cfg(key, max(lo, int(float(b.get(field, ci(key, lo))))))
            except Exception:
                pass
        ctx.log("配置已更新")
        return _state_dict()

    async def api_think(request, body):
        d = await _think()
        if d:
            # 手动让她想一次也要算数：按她说的重排，否则状态里还挂着旧时间
            _schedule_think(d)
        return {"ok": bool(d), "think": d}

    async def api_post(request, body):
        b = body or {}
        text = str(b.get("text") or "").strip()
        want_img = bool(b.get("image", False))
        if not text:
            d = await _think()
            if not d or d.get("now") != "发" or not d.get("text"):
                return {"ok": False, "error": "她这次不想发", "think": d}
            text = d.get("text")
            want_img = want_img or bool(d.get("image"))
            _schedule_think(d)
        ok, res = await _publish(text, with_image=want_img)
        return {"ok": ok, "text": text, "image": want_img, "result": str(res)[:300]}

    async def api_recent(request, body):
        return {"ok": True, "local": ctx.kv_get("moments_recent", []) or [],
                "remote_supported": False}

    async def api_probe(request, body):
        # 不能走 ctx.onebot：它吞异常返回 None，会把"不支持"和"成功"混成一样。
        # 这里直接 call_api 看真异常；两项都不产生副作用（读只读，写故意传非法 ugc_right）。
        import nonebot
        bots = list(nonebot.get_bots().values())
        if not bots:
            return {"ok": False, "error": "没有已连接的机器人"}
        bot = bots[0]
        out = {}
        for act, kw in (("get_qzone_msg_list", {"pos": 0, "num": 1}),
                        ("send_qzone_msg", {"content": "x", "ugc_right": 2})):
            try:
                await bot.call_api(act, **kw)
                out[act] = "ok"
            except Exception as e:
                msg = str(e)
                if "不支持的Api" in msg:
                    out[act] = "不支持"
                elif "参数不合法" in msg or "allowEmpty" in msg:
                    out[act] = "支持（参数校验已触发，未发布）"
                else:
                    out[act] = msg[:140]
        return {"ok": True, "probe": out}

    async def api_delete(request, body):
        # 删一条说说。不能靠 ctx.onebot 的返回值判断成败：
        # 这个动作成功时 NapCat 回的是 null，失败时 ctx.onebot 也回 None —— 分不清。
        import nonebot
        tid = str((body or {}).get("tid") or "").strip()
        if not tid:
            return {"ok": False, "error": "缺 tid"}
        bots = list(nonebot.get_bots().values())
        if not bots:
            return {"ok": False, "error": "没有已连接的机器人"}
        try:
            await bots[0].call_api("delete_qzone_msg", tid=tid)
            return {"ok": True, "tid": tid}
        except Exception as e:
            return {"ok": False, "tid": tid, "error": str(e)[:200]}

    ctx.register_api("/admin/api/plugins/moments/state", api_state, ("GET",))
    ctx.register_api("/admin/api/plugins/moments/delete", api_delete, ("POST",))
    ctx.register_api("/admin/api/plugins/moments/save", api_save, ("POST",))
    ctx.register_api("/admin/api/plugins/moments/think", api_think, ("POST",))
    ctx.register_api("/admin/api/plugins/moments/post", api_post, ("POST",))
    ctx.register_api("/admin/api/plugins/moments/recent", api_recent, ("GET",))
    ctx.register_api("/admin/api/plugins/moments/probe", api_probe, ("GET",))

    PAGE = """
<div class="card">
  <div class="card-h"><h3>朋友圈</h3><span class="en">Moments</span></div>
  <p class="hint">什么时候发、发什么、下次多久后再想，<b>全都由她自己决定</b>。
  这里没有随机数也没有概率，只有两条护栏（最短/最长间隔）。</p>
  <div class="row" style="gap:8px;flex-wrap:wrap;margin:12px 0">
    <button class="btn" onclick="mtThink(this)">让她想一次</button>
    <button class="btn" onclick="mtPost(this)">立刻想并发布</button>
  </div>
  <div id="mtOut" class="hint" style="white-space:pre-wrap"></div>
</div>
<div class="card">
  <div class="card-h"><h3>护栏</h3><span class="en">Rails</span></div>
  <div id="mtState" class="hint">读取中…</div>
  <div class="form-grid" style="margin-top:12px">
    <div class="form-row"><label>最短间隔（分钟，防刷屏）</label><input id="mtMin" type="number" min="5"></div>
    <div class="form-row"><label>最长间隔（分钟，防睡死）</label><input id="mtMax" type="number" min="30"></div>
    <div class="form-row"><label>可见范围（1/4/16/64/128）</label><input id="mtRight" type="number" min="1"></div>
    <div class="form-row"><label><input id="mtEnabled" type="checkbox"> 允许她发</label></div>
    <div class="form-row"><label><input id="mtDry" type="checkbox"> 演练模式（只生成不发布）</label></div>
    <div class="form-row"><label><input id="mtImg" type="checkbox"> 允许配图</label></div>
  </div>
  <button class="btn" style="margin-top:12px" onclick="mtSave(this)">保存</button>
</div>
"""
    ctx.register_page("moments", "朋友圈", PAGE)
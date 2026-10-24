# -*- coding: utf-8 -*-
r"""晨昏播报：每天早晚各一次，带天气 + 可选语音。

为什么要它（2026-10-20 用户选定）：现有的语音只有"被点名的时���才说一句"，
平时用不上。早晚各播报一次能天天用上，也让群里有个稳定的话题起点。

设计取舍：
- 不依赖任何付费 API：天气走 open-meteo（免费、无需 key）。
- 群列表为空时发给机器人所在的**所有群**；填了就只发那些群。
- 语音走本机轻量 TTS（127.0.0.1:7871）；失败就只发文字，绝不因为语音挂掉整条播报。
- 定时靠自带的 30 秒轮询 + 按 (日期, 早/晚) 去重，不依赖外部调度器。
"""
import asyncio
import json
import os
import re
import time
import urllib.parse
import urllib.request

WCODE = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴", 45: "有雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨", 56: "冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "强阵雨", 82: "暴雨", 85: "阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷暴伴冰雹",
}
WIND = {0: "北", 45: "东北", 90: "东", 135: "东南", 180: "南", 225: "西南", 270: "西", 315: "西北"}


def setup(ctx):
    # ---------------- 配置 ----------------
    _DEFAULTS = {
        "dg_enabled": True,
        "dg_morning": "08:00",
        "dg_evening": "23:30",
        "dg_city": "",
        "dg_cities": "",
        "dg_weather": False,
        "dg_voice": False,
        "dg_ai_line": True,
        "dg_groups": "",
        "dg_tts_url": "http://127.0.0.1:7871/v1/audio/speech",
        "dg_tts_voice": "卡提希娅-中文",
    }
    try:
        if hasattr(ctx, "_DEFAULTS"):
            ctx._DEFAULTS.update({k: v for k, v in _DEFAULTS.items()
                                  if k not in ctx._DEFAULTS})
    except Exception:
        pass

    def c_get(k, d=None):
        v = ctx.cfg(k, _DEFAULTS.get(k, d))
        return _DEFAULTS.get(k, d) if v in (None, "") and _DEFAULTS.get(k, d) not in (None, "") else v

    TMP = os.path.join(ctx.dir, "voice_cache")
    os.makedirs(TMP, exist_ok=True)

    # ---------------- 小工具 ----------------
    def _hhmm(s):
        m = re.match(r"^(\d{1,2})[:：](\d{1,2})$", str(s or "").strip())
        if not m:
            return None
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return h, mi
        return None

    def _target_groups():
        raw = str(c_get("dg_groups") or "").strip()
        if not raw:
            return None                      # None = 所有群
        out = []
        for part in re.split(r"[,，\s]+", raw):
            if part.isdigit():
                out.append(int(part))
        return out

    def _geocode(city):
        key = "daily:geo:" + city
        try:
            cached = ctx.kv_get(key, "")
            if cached:
                j = json.loads(cached)
                return float(j["lat"]), float(j["lon"]), j.get("name") or city
        except Exception:
            pass
        url = ("https://geocoding-api.open-meteo.com/v1/search?name=%s&count=1&language=zh&format=json"
               % urllib.parse.quote(city))
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
        rows = data.get("results") or []
        if not rows:
            return None
        row = rows[0]
        info = {"lat": row["latitude"], "lon": row["longitude"], "name": row.get("name") or city}
        try:
            ctx.kv_set(key, json.dumps(info, ensure_ascii=False))
        except Exception:
            pass
        return float(info["lat"]), float(info["lon"]), info["name"]

    def _weather_multi(cities):
        """多个城市各返回一句，取不到的跳过。"""
        out = []
        for c in cities[:4]:
            t = _weather(c)
            if t:
                out.append(t)
        return out

    def _weather(city):
        """返回一句话天气，取不到返回 ''。"""
        if not city:
            return ""
        try:
            geo = _geocode(city)
            if not geo:
                return ""
            lat, lon, name = geo
            url = ("https://api.open-meteo.com/v1/forecast?latitude=%.3f&longitude=%.3f"
                   "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
                   "precipitation_probability_max&timezone=Asia%%2FShanghai&forecast_days=1"
                   % (lat, lon))
            with urllib.request.urlopen(url, timeout=15) as r:
                d = json.loads(r.read())
            day = (d.get("daily") or {})
            code = int((day.get("weather_code") or [0])[0])
            tmax = (day.get("temperature_2m_max") or [None])[0]
            tmin = (day.get("temperature_2m_min") or [None])[0]
            pop = (day.get("precipitation_probability_max") or [None])[0]
            text = "%s %s" % (name, WCODE.get(code, "天气"))
            if tmin is not None and tmax is not None:
                text += " %.0f~%.0f℃" % (tmin, tmax)
            if pop is not None and pop >= 30:
                text += "，降水概率 %d%%" % int(pop)
            return text
        except Exception as e:
            ctx.warn(f"天气获取失败：{type(e).__name__}: {e}")
            return ""

    async def _ai_line(kind):
        if not bool(c_get("dg_ai_line")):
            return ""
        what = "早安" if kind == "morning" else "晚安"
        prompt = ("你在一个 QQ 群里当助理。写一句%s的问候，中文，不超过 18 个字，"
                  "语气自然像熟人说话，不要提问，不要用 emoji，不要引号。" % what)
        try:
            raw = await ctx.ai(prompt, timeout=25.0)
            line = str(raw or "").strip().split("\n")[0]
            line = re.sub(r"^[\"'「『]|[\"'」』]$", "", line).strip()
            return line[:24]
        except Exception as e:
            ctx.warn(f"AI 问候失败：{type(e).__name__}: {e}")
            return ""

    CN_NUM = "零一二三四五六七八九十"

    def _cn_int(n):
        """数字读成中文，免得 TTS 把 12 念成"一二"。"""
        n = int(round(float(n)))
        n = max(0, n)
        if n < 10:
            return CN_NUM[n]
        if n == 10:
            return "十"
        if n < 20:
            return "十" + CN_NUM[n - 10]
        if n < 100:
            return CN_NUM[n // 10] + "十" + (CN_NUM[n % 10] if n % 10 else "")
        return str(n)

    def _speak_weather(text):
        """天气念成中文：-2~4℃ → 零下二到四度；降水概率不念数字。"""
        def one(x):
            x = int(x)
            return ("零下" + _cn_int(-x)) if x < 0 else _cn_int(x)

        t = str(text or "")
        t = re.sub(r"(-?\d+)\s*~\s*(-?\d+)\s*℃",
                   lambda m: one(m.group(1)) + "到" + one(m.group(2)) + "度", t)
        t = re.sub(r"(-?\d+)\s*℃", lambda m: one(m.group(1)) + "度", t)
        t = re.sub(r"[，,]?\s*降水概率\s*\d+%", "，可能下雨", t)
        return t

    def _compose_display(kind, weather_lines, ai_line):
        """群里看到的文字（可以带 emoji 和标题）。"""
        lines = ["早安 ☀️" if kind == "morning" else "晚安 🌙"]
        if ai_line:
            lines.append(ai_line)
        for w in weather_lines:
            lines.append("· " + w)
        if kind == "evening":
            lines.append("早点休息，别熬太晚。")
        return "\n".join(lines)

    def _compose_spoken(kind, weather_lines, ai_line):
        """语音念的话：没有标题、没有 emoji、数字读中文。"""
        parts = [ai_line or ("早，今天也要开心" if kind == "morning" else "晚安，早点睡")]
        for w in weather_lines[:2]:
            parts.append(_speak_weather(w))
        if kind == "evening":
            parts.append("别熬太晚")
        clean = [re.sub(r"^[，。、\s]+|[，。、\s]+$", "", str(p)) for p in parts]
        return "，".join([p for p in clean if p]) + "。"

    def _speakable(text):
        """去掉念不出来的东西（emoji、装饰符号）—— emoji 会让 TTS 直接报错。"""
        ranges = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0xFE00, 0xFE0F),
                  (0x2B00, 0x2BFF), (0x1F1E6, 0x1F1FF))
        drop = "*#<>[]|" + chr(96) + "_~"
        out = []
        for ch in str(text or ""):
            o = ord(ch)
            if any(a <= o <= b for a, b in ranges):
                continue
            if ch in drop:
                continue
            out.append(ch)
        return re.sub(r"\s+", " ", "".join(out)).strip()

    def _tts(text):
        """调本机轻量 TTS，返回 mp3 路径（失败返回 ''）。"""
        text = _speakable(text)
        if not text:
            return ""
        url = str(c_get("dg_tts_url") or "").strip()
        if not url:
            return ""
        payload = {"model": "tts-1", "input": text,
                   "voice": str(c_get("dg_tts_voice") or "卡提希娅-中文"),
                   "response_format": "mp3", "speed": 1.0}
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            data = r.read()
        if not data:
            return ""
        p = os.path.join(TMP, "d-%d.mp3" % int(time.time() * 1000))
        with open(p, "wb") as f:
            f.write(data)
        return p

    async def _send_one(gid, kind="morning", with_voice=None):
        weather_lines = []
        if bool(c_get("dg_weather")):
            cities = [c.strip() for c in
                      re.split(r"[,，\s]+", str(c_get("dg_cities") or c_get("dg_city") or ""))
                      if c.strip()]
            if cities:
                weather_lines = await asyncio.to_thread(_weather_multi, cities)
        ai_line = await _ai_line(kind)
        text = _compose_display(kind, weather_lines, ai_line)
        spoken = _compose_spoken(kind, weather_lines, ai_line)
        try:
            await ctx.send_group(int(gid), text)
        except Exception as e:
            ctx.warn(f"播报发送失败（群 {gid}）：{type(e).__name__}: {e}")
            return False
        use_voice = bool(c_get("dg_voice")) if with_voice is None else bool(with_voice)
        if use_voice:
            p = ""
            try:
                ctx.log(f"要念的句子：{spoken[:60]}")
                p = await asyncio.to_thread(_tts, spoken)
            except Exception as e:
                ctx.warn(f"播报语音失败：{type(e).__name__}: {e}")
            if p:
                uri = "file:///" + p.replace("\\", "/")
                ok = False
                for payload in (
                        {"group_id": int(gid),
                         "message": [{"type": "record", "data": {"file": uri}}]},
                        {"group_id": int(gid), "file": uri}):
                    try:
                        r = await ctx.onebot("send_group_msg", **payload)
                        if isinstance(r, dict) and (r.get("message_id") or r.get("data")):
                            ok = True
                            break
                    except Exception:
                        continue
                if not ok:
                    try:
                        await ctx.onebot("upload_group_file",
                                         group_id=int(gid), file=uri,
                                         name="播报.mp3")
                        ok = True
                    except Exception as e:
                        ctx.warn(f"语音兜底失败：{type(e).__name__}")
                try:
                    if os.path.exists(p):
                        os.unlink(p)
                except Exception:
                    pass
                if ok:
                    ctx.log(f"群 {gid} 语音已发送（{os.path.basename(p)}）")
                else:
                    ctx.warn(f"群 {gid} 语音发送未成功")
        ctx.log(f"播报({kind}) → 群 {gid}：{text[:40].replace(chr(10), ' ')}")
        return True

    async def _broadcast(kind):
        targets = _target_groups()
        if targets is None:
            try:
                gl = await ctx.onebot("get_group_list") or []
                targets = [int(g.get("group_id")) for g in gl if g.get("group_id")]
            except Exception as e:
                ctx.warn(f"取群列表失败：{type(e).__name__}: {e}")
                return 0
        n = 0
        for gid in targets:
            if await _send_one(gid, kind):
                n += 1
            await asyncio.sleep(1.5)
        return n

    # ---------------- 定时循环 ----------------
    _STATE = {"fired": set(), "task": None}

    def _next_wait():
        """返回 (等待秒数, 下一个 kind)。"""
        now = time.localtime()
        today = time.strftime("%Y-%m-%d", now)
        plan = []
        for kind, key in (("morning", "dg_morning"), ("evening", "dg_evening")):
            hm = _hhmm(c_get(key))
            if not hm:
                continue
            t = time.mktime(time.strptime("%s %02d:%02d" % (today, hm[0], hm[1]), "%Y-%m-%d %H:%M"))
            plan.append((t, kind, "%s:%s" % (today, kind)))
        plan.sort()
        stamp = time.strftime("%Y%m%d", now)
        # 今天剩下的
        for t, kind, tag in plan:
            if t > time.time() + 1 and tag not in _STATE["fired"]:
                return max(5.0, min(1800.0, t - time.time())), kind
        # 都过了 → 明天最早那一班
        if not plan:
            return 1800.0, "morning"
        t, kind, _ = plan[0]
        return max(30.0, min(1800.0, t + 86400 - time.time())), kind

    async def _loop():
        await asyncio.sleep(20)
        while True:
            try:
                if not bool(c_get("dg_enabled")):
                    await asyncio.sleep(300)
                    continue
                wait, kind = _next_wait()
                await asyncio.sleep(wait)
                now = time.localtime()
                tag = "%s:%s" % (time.strftime("%Y-%m-%d", now), kind)
                hm = _hhmm(c_get("dg_morning" if kind == "morning" else "dg_evening"))
                if not hm:
                    continue
                target = time.mktime(time.strptime("%s %02d:%02d" % (time.strftime("%Y-%m-%d", now), hm[0], hm[1]),
                                                   "%Y-%m-%d %H:%M"))
                if abs(time.time() - target) > 120:
                    continue
                if tag in _STATE["fired"]:
                    continue
                _STATE["fired"].add(tag)
                n = await _broadcast(kind)
                ctx.log(f"定时播报({kind})完成：{n} 个群")
            except Exception as e:
                ctx.warn(f"播报循环异常：{type(e).__name__}: {e}")
                await asyncio.sleep(120)

    def _ensure_task():
        # 2026-10-24 修：这段原来在 setup() 里直接 get_running_loop().create_task()，
        # 但 setup() 是模块导入期同步执行的，那时没有事件循环 -> RuntimeError ->
        # 被外层 try/except 吞掉，后台循环从未启动（startup.log 里一条"已启用"都没有）。
        # 改用 ctx.spawn()：有循环立刻起，没有就排队，主循环就绪后由核心统一拉起。
        if _STATE.get("started"):
            return
        _STATE["started"] = True
        task = ctx.spawn(_loop)
        _STATE["task"] = task
        if task is None:
            ctx.log("晨昏播报：已排队，等主循环就绪后启动")
            return
        return
        ctx.log("晨昏播报定时器已启动")

    _ensure_task()

    # ---------------- 命令 ----------------
    @ctx.command("早安", help="立刻发一条早安播报（本群）", timeout=200)
    async def _cmd_morning(event, cmd):
        _ensure_task()
        gid = getattr(event, "group_id", None)
        if not gid:
            return
        await _send_one(gid, "morning")

    @ctx.command("晚安", help="立刻发一条晚安播报（本群）", timeout=200)
    async def _cmd_evening(event, cmd):
        _ensure_task()
        gid = getattr(event, "group_id", None)
        if not gid:
            return
        await _send_one(gid, "evening")

    @ctx.command("播报测试", help="发一条完整播报测试（管理员）", timeout=300)
    async def _cmd_test(event, cmd):
        gid = getattr(event, "group_id", None)
        if not gid:
            return
        if not ctx.is_super(event.user_id):
            await ctx.send_group(gid, [ctx.mention(event.user_id), "只有管理员能用这个。"])
            return
        await _send_one(gid, "morning")

    @ctx.command("播报状态", help="看播报设置与下次时间", timeout=60)
    async def _cmd_status(event, cmd):
        gid = getattr(event, "group_id", None)
        if not gid:
            return
        wait, kind = _next_wait()
        nxt = time.strftime("%m-%d %H:%M", time.localtime(time.time() + wait))
        lines = [
            "晨昏播报",
            "· 开关：%s" % ("开" if bool(c_get("dg_enabled")) else "关"),
            "· 时间：早 %s / 晚 %s" % (c_get("dg_morning"), c_get("dg_evening")),
            "· 天气：%s" % (("开：" + (str(c_get("dg_cities") or c_get("dg_city") or "（没配城市）").strip())) if bool(c_get("dg_weather")) else "关"),
            "· 语音：%s" % ("开" if bool(c_get("dg_voice")) else "关"),
            "· 群：%s" % (str(c_get("dg_groups") or "").strip() or "所有群"),
            "· 下次：%s（%s）" % (nxt, "早安" if kind == "morning" else "晚安"),
        ]
        await ctx.send_group(gid, "\n".join(lines))

    @ctx.command("设置城市", help="设置天气城市，如：设置城市 江门", timeout=60)
    async def _cmd_city(event, cmd):
        gid = getattr(event, "group_id", None)
        if not gid:
            return
        if not ctx.is_super(event.user_id):
            await ctx.send_group(gid, [ctx.mention(event.user_id), "只有管理员能改。"])
            return
        city = str(cmd or "").strip()
        city = re.sub(r"^(设置城市|设置|城市)\s*", "", city).strip()
        if not city:
            await ctx.send_group(gid, [ctx.mention(event.user_id), "用法：设置城市 江门"])
            return
        ctx.set_cfg("dg_city", city)
        w = await asyncio.to_thread(_weather, city)
        await ctx.send_group(gid, [ctx.mention(event.user_id),
                                   "城市已设为「%s」。%s" % (city, ("当前：" + w) if w else "（天气接口暂时取不到）")])

    # ---------------- 管理接口 ----------------
    async def _api_send(request, body):
        b = body or {}
        kind = str(b.get("kind") or "morning")
        gid = b.get("gid")
        voice = b.get("voice")
        voice = None if voice is None else bool(voice)
        if gid:
            ok = await _send_one(int(gid), kind, with_voice=voice)
            return {"ok": bool(ok), "gid": int(gid), "kind": kind, "voice": voice}
        n = await _broadcast(kind)
        return {"ok": True, "sent": n, "kind": kind}

    async def _api_status(request, body):
        wait, kind = _next_wait()
        return {"ok": True,
                "enabled": bool(c_get("dg_enabled")),
                "morning": c_get("dg_morning"), "evening": c_get("dg_evening"),
                "city": c_get("dg_city"), "voice": bool(c_get("dg_voice")),
                "groups": _target_groups(),
                "next_in": int(wait), "next_kind": kind,
                "fired": sorted(_STATE["fired"])}

    ctx.register_api("/admin/api/plugins/daily/send", _api_send, methods=("POST",), timeout=600)
    ctx.register_api("/admin/api/plugins/daily/status", _api_status, methods=("GET",))

    ctx.register_config("晨昏播报", [
        ["dg_enabled", "启用早晚播报", "bool"],
        ["dg_morning", "早安时间（如 08:00）", "string"],
        ["dg_evening", "晚安时间（如 23:30）", "string"],
        ["dg_cities", "天气城市（可多填，逗号分隔）", "string"],
        ["dg_city", "（旧）单个城市", "string"],
        ["dg_weather", "播报里带天气", "bool"],
        ["dg_voice", "播报时配一条语音", "bool"],
        ["dg_ai_line", "让 AI 加一句问候", "bool"],
        ["dg_groups", "播报到哪些群（群号逗号分隔，留空=所有群）", "string"],
        ["dg_tts_url", "语音服务地址", "string"],
        ["dg_tts_voice", "语音音色名", "string"],
    ])

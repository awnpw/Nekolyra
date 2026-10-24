# -*- coding: utf-8 -*-
"""网易云音乐解析：把分享链接或歌曲 ID 解析成歌名 / 歌手 / 专辑 / 封面 / 直链 / 歌词。

接口：https://api.pearapi.ai/api/cloudmusic/
  GET  ?url=<分享链接>   或   ?id=<歌曲ID>    -> {"code":200,"data":{...}}

命令：
  网易云 <链接或ID>      解析并发卡片
  点歌 <链接或ID>        同上（别名）
  歌词 <链接或ID>        显示歌词前 N 行

另外会自动识别群里出现的 music.163.com 链接（可在插件配置里关掉）。

注意：核心的全局插件超时默认 15 秒，联网命令必须显式声明 timeout，
      否则超时会被当成"没处理"，消息继续往下走被 AI 抢答。
"""
import os
import re
import time

#: 分享链接里常见的 ID 位置：song?id=123 / /song/123 / id=123
_ID_RE = re.compile(r"(?:song\?id=|/song/|songId=|id=)(\d{3,})")
_URL_RE = re.compile(r"https?://[^\s<>\"']*music\.163\.com[^\s<>\"']*")
_PURE_ID_RE = re.compile(r"^\d{3,}$")
#: LRC 时间戳：[00:12.345] / [00:12]
_STAMP_RE = re.compile(r"\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]")

#: 官方搜索接口（用 UA + Referer 就能通，实测 200）
#: pearapi 的解析接口只接受链接或 ID，所以"按歌名点歌"必须先在这里查 ID
_SEARCH_URL = "https://music.163.com/api/search/get"
#: 兜底：pearapi 对部分歌返回 code=400「获取音频失败」（版权限制），
#: 这时直接问网易云要播放地址。实测这两首都能拿到 128kbps 直链。
_FALLBACK_URL = "https://music.163.com/api/song/enhance/player/url"
_FALLBACK_DETAIL = "https://music.163.com/api/song/detail"
_FALLBACK_LYRIC = "https://music.163.com/api/song/lyric"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

#: MPEG 音频比特率表（kbps）：[版本组][层索引][比特率索引]
#: 版本组 0 = MPEG1，1 = MPEG2/2.5；层索引 1 = Layer3
_BR_V1_L3 = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0)
_BR_V2_L3 = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0)
_SR_V1 = (44100, 48000, 32000)
_SR_V2 = (22050, 24000, 16000)
_SR_V25 = (11025, 12000, 8000)


def cut_mp3(data, max_sec):
    """把 MP3 截到前 max_sec 秒，返回 (bytes, 实际秒数, 原总秒数)。

    为什么不用 ffmpeg：这台机器上没装（做过音乐功能的人大概都有体会）。
    MP3 的帧是独立的，按帧边界切就能得到可播放的前半段 —— 纯 Python 够用。
    切不了（找不到帧头/ID3 奇怪）就原样返回，让调用方自己兜底。
    """
    n = len(data)
    i = 0
    # 跳过 ID3v2 头
    if n > 10 and data[:3] == b"ID3":
        sz = ((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) |              ((data[8] & 0x7F) << 7) | (data[9] & 0x7F)
        i = 10 + sz
    start = None
    total_frames = 0
    cut_at = None
    elapsed = 0.0
    total = 0.0
    while i + 4 <= n:
        if data[i] != 0xFF or (data[i + 1] & 0xE0) != 0xE0:
            if start is None:
                i += 1
                continue
            break
        b1, b2 = data[i + 1], data[i + 2]
        ver = (b1 >> 3) & 0x03        # 3=MPEG1, 2=MPEG2, 0=MPEG2.5
        layer = (b1 >> 1) & 0x03      # 1 = Layer III
        br_idx = (b2 >> 4) & 0x0F
        sr_idx = (b2 >> 2) & 0x03
        pad = (b2 >> 1) & 0x01
        if br_idx == 0 or br_idx == 15 or sr_idx == 3 or layer != 1:
            if start is None:
                i += 1
                continue
            break
        if ver == 3:
            br = _BR_V1_L3[br_idx] * 1000
            sr = _SR_V1[sr_idx]
        else:
            br = _BR_V2_L3[br_idx] * 1000
            sr = (_SR_V2 if ver == 2 else _SR_V25)[sr_idx]
        if not br or not sr:
            break
        flen = int(144 * br / sr) + pad
        if flen <= 4:
            break
        if start is None:
            start = i
        dur = 1152.0 / sr
        total += dur
        total_frames += 1
        if cut_at is None:
            elapsed += dur
            if elapsed >= max_sec:
                cut_at = i + flen
        i += flen
    if start is None:
        return data, 0.0, 0.0
    end = cut_at if cut_at else n
    return data[start:end], min(elapsed, total), total


CMDS = ("网易云", "点歌", "歌词")


def setup(ctx):
    def _url():
        return str(ctx.cfg("music_api_url") or "https://api.pearapi.ai/api/cloudmusic/").strip()

    def _flag(key, default=True):
        v = ctx.cfg(key, default)
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("1", "true", "yes", "on", "开启")

    def _num(key, default):
        try:
            v = ctx.cfg(key, default)
            return default if v in (None, "") else int(float(v))
        except Exception:
            return default

    _CACHE = {}          # id/url -> (时间戳, data)
    #: 待选版本：(群, 人) -> {"list": [...], "ts": 时间, "lyric": bool}
    #: 用户回数字时按这个选 —— 只对**发起点歌的人**、在有效期内生效
    _PENDING = {}

    def _extract(text):
        """从一段文字里认出「链接或 ID」，返回 (kind, value)；认不出返回 (None, None)。"""
        t = str(text or "").strip()
        m = _URL_RE.search(t)
        if m:
            u = m.group(0)
            mid = _ID_RE.search(u)
            if mid:
                return "id", mid.group(1)      # 有 ID 就按 ID 查，链接可能会过期
            return "url", u
        m = _ID_RE.search(t)
        if m:
            return "id", m.group(1)
        m = _PURE_ID_RE.match(t)
        if m:
            return "id", t
        return None, None

    def _cached(kind, value):
        ttl = _num("music_cache_ttl", 300)
        if ttl <= 0:
            return None
        hit = _CACHE.get(value)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        return None

    async def _parse(kind, value):
        """调接口。返回 (data, 错误说明)。"""
        if not kind:
            return None, "没认出链接或歌曲 ID"
        hit = _cached(kind, value)
        if hit:
            return hit, ""
        params = {"url": value} if kind == "url" else {"id": value}
        try:
            r = await ctx.http_get(_url(), params=params, timeout=20)
            r.raise_for_status()
            j = r.json()
        except Exception as e:
            return None, "解析接口连不上：%s: %s" % (type(e).__name__, e)
        if not isinstance(j, dict):
            return None, "解析接口返回了非 JSON"
        if int(j.get("code") or 0) != 200:
            msg = j.get("msg") or j.get("message") or "未知错误"
            return None, "解析失败（code=%s）：%s" % (j.get("code"), msg)
        d = j.get("data") or {}
        if not isinstance(d, dict) or not d.get("song_name"):
            return None, "解析成功但没有歌曲信息（可能链接失效）"
        if _num("music_cache_ttl", 300) > 0:
            _CACHE[value] = (time.time(), d)
        return d, ""

    async def _search(keyword, limit=5):
        """按歌名搜候选，返回 [(id, 歌名, 歌手), ...]；搜不到返回空列表。

        为什么返回多个：同名的版本很多，而且**版权受限**的那些解析接口会返回
        code=400「获取音频失败」。逐个试才有机会命中能解析的那个。
        """
        kw = str(keyword or "").strip().strip('"')
        if not kw:
            return []
        hit = _cached("kw", kw)
        if hit:
            return hit.get("list") or []
        try:
            r = await ctx.http_get(_SEARCH_URL, params={"s": kw, "type": 1, "limit": int(limit)},
                                   timeout=15,
                                   headers={"User-Agent": _UA, "Referer": "https://music.163.com/"})
            r.raise_for_status()
            j = r.json()
        except Exception as e:
            ctx.warn("搜索失败：%s: %s" % (type(e).__name__, e))
            return []
        songs = ((j or {}).get("result") or {}).get("songs") or []
        out = []
        for s in songs[:int(limit)]:
            sid = str(s.get("id") or "")
            if not sid:
                continue
            artists = s.get("artists") or s.get("ar") or []
            singer = "、".join(str(a.get("name") or "") for a in artists if isinstance(a, dict))
            out.append({"id": sid, "song_name": str(s.get("name") or ""), "singers": singer})
        if out and _num("music_cache_ttl", 300) > 0:
            _CACHE[kw] = (time.time(), {"list": out})
        if out:
            ctx.log("搜索「%s」→ %d 个候选，首个：%s — %s（id=%s）"
                    % (kw, len(out), out[0]["song_name"], out[0]["singers"], out[0]["id"]))
        return out

    def _hdr():
        return {"User-Agent": _UA, "Referer": "https://music.163.com/"}

    async def _fallback_direct(sid):
        """pearapi 解析不到音频时的兜底：直接取网易云的播放地址 + 详情 + 歌词。

        返回与 pearapi 的 data 同构的 dict；拿不到直链返回 None。
        """
        sid = str(sid or "").strip()
        if not sid.isdigit():
            return None
        try:
            r = await ctx.http_get(_FALLBACK_URL, params={"ids": "[%s]" % sid, "br": 128000},
                                   timeout=15, headers=_hdr())
            j = r.json()
            arr = (j or {}).get("data") or []
            if not arr or not str(arr[0].get("url") or ""):
                return None
            url = str(arr[0]["url"])
            size = int(arr[0].get("size") or 0)
        except Exception as e:
            ctx.warn("兜底取直链失败：%s: %s" % (type(e).__name__, e))
            return None

        d = {"url": url,
             "level": "128kbps（网易云直连）",
             "size": ("%.2fMB" % (size / 1048576.0)) if size else ""}
        try:
            r2 = await ctx.http_get(_FALLBACK_DETAIL, params={"ids": "[%s]" % sid},
                                    timeout=15, headers=_hdr())
            songs = (r2.json() or {}).get("songs") or []
            if songs:
                s = songs[0]
                album = s.get("album") or {}
                d["song_name"] = str(s.get("name") or "")
                d["singers"] = "、".join(str(a.get("name") or "")
                                        for a in (s.get("artists") or []) if isinstance(a, dict))
                d["album"] = str(album.get("name") or "")
                d["cover"] = str(album.get("picUrl") or "")
        except Exception as e:
            ctx.warn("兜底取详情失败：%s: %s" % (type(e).__name__, e))
        try:
            r3 = await ctx.http_get(_FALLBACK_LYRIC, params={"id": sid, "lv": 1, "kv": 1, "tv": -1},
                                    timeout=15, headers=_hdr())
            d["lyric"] = str(((r3.json() or {}).get("lrc") or {}).get("lyric") or "")
        except Exception:
            pass
        if not d.get("song_name"):
            return None
        return d

    def _summary(d):
        name = str(d.get("song_name") or "未知歌曲")
        singer = str(d.get("singers") or "未知歌手")
        bits = []
        if d.get("album"):
            bits.append("专辑：%s" % d["album"])
        if d.get("level"):
            bits.append(str(d["level"]))
        if d.get("size"):
            bits.append(str(d["size"]))
        line1 = "🎵 %s — %s" % (name, singer)
        return line1 + ("\n" + " ｜ ".join(bits) if bits else "")

    def _pending_get(gid, uid):
        key = (int(gid), int(uid))
        p = _PENDING.get(key)
        if not p:
            return None
        if time.time() - p["ts"] > _num("music_pick_ttl", 120):
            _PENDING.pop(key, None)
            return None
        return p

    async def _ask_which(gid, uid, cands, want_lyric=False):
        """搜到多个版本时回编号列表，等用户回数字。"""
        key = (int(gid), int(uid))
        _PENDING[key] = {"list": cands, "ts": time.time(), "lyric": bool(want_lyric)}
        ttl = _num("music_pick_ttl", 120)
        lines = ["搜到 %d 个版本，回数字选（%d 秒内有效）：" % (len(cands), ttl)]
        for i, c in enumerate(cands, 1):
            lines.append("%d. %s — %s" % (i, c["song_name"], c["singers"]))
        await ctx.send_group(gid, "\n".join(lines))
        ctx.log("列出 %d 个候选，等 %s 选" % (len(cands), uid))

    async def _send_voice(gid, d):
        """把歌下载下来，当录音（语音条）发出去。失败返回 False。

        QQ 语音条有长度限制（一般 60 秒），长歌会被协议端拒绝 —— 那时返回 False，
        调用方自动退回链接/卡片。下载落盘是因为 record 段认本地 file:/// 路径最稳。
        """
        url = str(d.get("url") or "")
        if not url:
            return False
        cache_dir = os.path.join(str(ctx.dir), "cache")
        try:
            os.makedirs(cache_dir, exist_ok=True)
            path = os.path.join(cache_dir, "song_%d.mp3" % int(time.time() * 1000))
            r = await ctx.http_get(url, timeout=90)
            r.raise_for_status()
            data = getattr(r, "content", None)
            if not data:
                try:
                    data = await r.aread()
                except Exception:
                    data = b""
            if not data:
                ctx.warn("下载音频为空")
                return False
            max_sec = _num("music_voice_max_sec", 55)
            orig_mb = len(data) / 1048576.0
            if max_sec > 0:
                data, got, total = cut_mp3(data, max_sec)
                if total:
                    ctx.log("音频 %.1fMB / %.0f 秒，截到前 %.0f 秒（%.1fMB）"
                            % (orig_mb, total, got, len(data) / 1048576.0))
            with open(path, "wb") as f:
                f.write(data)
            size_mb = len(data) / 1048576.0
            ctx.log("准备发语音条 %.1fMB" % size_mb)
            seg = [{"type": "record", "data": {"file": "file:///" + path.replace(os.sep, "/")}}]
            res = await ctx.onebot("send_group_msg", group_id=gid, message=seg)
            if res:
                ctx.log("已发语音条：%s" % d.get("song_name"))
                return True
            ctx.warn("语音条发送被拒绝（多半超过 60 秒上限），改用链接")
        except Exception as e:
            ctx.warn("发语音条失败：%s: %s" % (type(e).__name__, e))
        finally:
            try:
                if 'path' in dir() and os.path.isfile(path):
                    os.remove(path)
            except Exception:
                pass
        return False

    async def _send_card(gid, d):
        """发音乐卡片。NapCat 支持 custom 类型；失败返回 False 让调用方改发文字。"""
        if not d.get("url"):
            return False
        seg = [{
            "type": "music",
            "data": {
                "type": "custom",
                "url": str(d.get("url")),
                "audio": str(d.get("url")),
                "title": str(d.get("song_name") or "网易云音乐"),
                "content": str(d.get("singers") or ""),
                "image": str(d.get("cover") or ""),
            },
        }]
        try:
            res = await ctx.onebot("send_group_msg", group_id=gid, message=seg)
        except Exception as e:
            ctx.warn("发音乐卡片异常：%s: %s" % (type(e).__name__, e))
            return False
        return bool(res)

    async def _reply_song(event, d):
        gid = event.group_id
        # 顺序：语音条 -> 音乐卡片 -> 文字 + 封面
        if _flag("music_send_voice", True) and await _send_voice(gid, d):
            return
        if _flag("music_voice_only", False):
            await ctx.send_group(gid, "这首歌发不成语音条（多半超过 60 秒），换成短一点的歌试试。")
            return
        if _flag("music_send_card", True) and await _send_card(gid, d):
            ctx.log("已发音乐卡片：%s" % d.get("song_name"))
            return
        parts = [_summary(d)]
        if d.get("url"):
            parts.append(str(d["url"]))
        await ctx.send_group(gid, parts)
        if _flag("music_cover", True) and d.get("cover"):
            try:
                await ctx.send_group(gid, [ctx.image(str(d["cover"]))])
            except Exception as e:
                ctx.warn("发封面失败：%s: %s" % (type(e).__name__, e))

    def _lyric_text(d, limit):
        raw = str(d.get("lyric") or "").strip()
        if not raw:
            return ""
        lines = []
        for ln in raw.splitlines():
            ln = _STAMP_RE.sub("", ln).strip()
            if ln:
                lines.append(ln)
        if limit > 0:
            lines = lines[:limit]
        return "\n".join(lines)

    # ---------------- 命令 ----------------

    async def _cmd_common(event, cmd, want_lyric=False):
        text = str(cmd or "").strip()
        for kw in CMDS:
            if text.startswith(kw):
                text = text[len(kw):].strip()
                break
        kind, value = _extract(text)
        d, err, searched = None, "", ""
        if not kind and text:
            # 不是链接也不是纯数字 -> 当歌名搜（pearapi 只接受 url/id，得先拿 ID）
            cands = await _search(text, limit=_num("music_search_limit", 5))
            if not cands:
                await ctx.send_group(event.group_id,
                                     "没搜到「%s」。换个写法，或者直接把网易云链接贴给我。" % text[:30])
                return True
            if len(cands) > 1:
                # 多个版本交给用户挑，别自作主张选错
                await _ask_which(event.group_id, event.user_id, cands, want_lyric)
                return True
            # 同名版本很多、版权受限的会解析失败 —— 逐个试到能出音频为止
            for c in cands:
                d2, e2 = await _parse("id", c["id"])
                if d2:
                    d, value, searched = d2, c["id"], "找到：%s — %s\n" % (c["song_name"], c["singers"])
                    break
                err = e2
            if not d:
                # pearapi 全军覆没 -> 用网易云直连再试一遍
                for c in cands:
                    d2 = await _fallback_direct(c["id"])
                    if d2:
                        d, value = d2, c["id"]
                        searched = "找到：%s — %s\n" % (c["song_name"], c["singers"])
                        ctx.log("pearapi 全失败，网易云直连兜底成功：%s" % c["song_name"])
                        break
            if not d:
                await ctx.send_group(
                    event.group_id,
                    "搜到 %d 个版本，但都拿不到音频（版权限制或需要登录）：\n%s\n"
                    "换一首试试，或者把网易云里的分享链接直接贴给我。" % (len(cands), err or ""))
                return True
        else:
            d, err = await _parse(kind, value)
            if not d:
                d = await _fallback_direct(value)
                if d:
                    ctx.log("pearapi 解析失败，已用网易云直连兜底：%s" % d.get("song_name"))
                else:
                    await ctx.send_group(event.group_id, err)
                    return True
        if searched:
            await ctx.send_group(event.group_id, searched.strip())
        if want_lyric:
            body = _lyric_text(d, _num("music_lyric_lines", 12))
            head = _summary(d)
            await ctx.send_group(event.group_id, head + ("\n\n" + body if body else "\n\n（这首歌没有歌词）"))
            return True
        await _reply_song(event, d)
        return True

    @ctx.command("网易云", "解析网易云链接或歌曲 ID（示例：网易云 2618165651）", prefix=True, timeout=40)
    async def on_parse(event, cmd):
        return await _cmd_common(event, cmd)

    @ctx.command("点歌", "同「网易云」", prefix=True, timeout=40)
    async def on_play(event, cmd):
        return await _cmd_common(event, cmd)

    @ctx.command("歌词", "显示歌词前 N 行（示例：歌词 2618165651）", prefix=True, timeout=40)
    async def on_lyric(event, cmd):
        return await _cmd_common(event, cmd, want_lyric=True)

    # ---------------- 自动识别链接 ----------------

    @ctx.on_message(timeout=40)
    async def on_any_message(event, text):
        # ① 先看是不是在"回数字选"（只认发起人的数字，且没过期）
        raw = str(text or "").strip()
        if raw.isdigit():
            pend = _pending_get(event.group_id, event.user_id)
            if pend:
                idx = int(raw) - 1
                lst = pend["list"]
                _PENDING.pop((int(event.group_id), int(event.user_id)), None)
                if not (0 <= idx < len(lst)):
                    await ctx.send_group(event.group_id, "只有 1~%d，重新点一次吧。" % len(lst))
                    return True
                c = lst[idx]
                d, err = await _parse("id", c["id"])
                if not d:
                    d = await _fallback_direct(c["id"])
                if not d:
                    await ctx.send_group(event.group_id, err or "这个版本拿不到音频，换一个试试。")
                    return True
                await ctx.send_group(event.group_id, "选中：%s — %s" % (c["song_name"], c["singers"]))
                if pend.get("lyric"):
                    body = _lyric_text(d, _num("music_lyric_lines", 12))
                    await ctx.send_group(event.group_id, body or "（这首歌没有歌词）")
                else:
                    await _reply_song(event, d)
                return True
        # ② 再走自动识别链接
        if not _flag("music_auto_parse", True):
            return False
        t = str(text or "")
        if not _URL_RE.search(t):
            return False
        # 已经用命令的，交给命令处理（钩子先于命令执行，这里要主动让开）
        for kw in CMDS:
            if t.strip().startswith(kw):
                return False
        kind, value = _extract(t)
        if not kind:
            return False
        d, err = await _parse(kind, value)
        if not d:
            ctx.warn("自动识别失败：%s" % err)
            return False
        await _reply_song(event, d)
        return True

    ctx.log("网易云解析已就绪（命令：网易云 / 点歌 / 歌词，自动识别 %s）"
            % ("开" if _flag("music_auto_parse", True) else "关"))

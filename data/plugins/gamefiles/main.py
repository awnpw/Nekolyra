# -*- coding: utf-8 -*-
r"""游戏库 —— 群文件自动收纳 + 按需发送。

解决什么：
    群里文件一多，群员问「有没有 XX」就得一个个翻。这个插件把群文件
    扫下来建索引，用 AI 把「塞尔达传说 王国之泪 v1.2 汉化硬盘版.rar」
    这种名字整理成「塞尔达传说：王国之泪」+ 别名，然后群员一问就回链接。

命令（都要 @ 机器人）：
    扫游戏库        扫一遍群文件，重建索引（只有超管能扫）
    游戏库          看收录了多少个、上次什么时候扫的
    重扫游戏库      同上，但连 AI 整理也重做一遍

群员不用命令 —— 直接说「有没有塞尔达」就会触发。

依赖的两件事：
    · ctx.onebot("get_group_root_files" ...)  读群文件
    · ctx.onebot("get_group_file_url" ...)    取下载链接
    这两个是 OneBot v11 的标准动作，NapCat 都支持。

数据存在插件的 kv 里（key = gamefiles:<群号>），不碰主程序的库。
"""

import json
import re
import time

# 文件名里的噪声：版本号、分辨率、渠道、包装词
_NOISE = re.compile(
    r"(?:"
    r"\d+(?:\.\d+)?\s*(?:GB|MB|KB|TB)|"           # ★ 体积必须排在版本前面。
                                                  #   Python 正则交替是首个匹配优先，
                                                  #   顺序反了就会把 52.3GB 吃成 52.3 + 残留 GB
    r"v\d+(?:\.\d+)+|"                            # v1.2 / v4.04
    r"\d+(?:\.\d+)+|"                             # ★ 裸数字**必须带点**才算版本。
                                                  #   否则「赛博朋克2077」的 2077 会被当成版本号吃掉
    r"\d{4}\s*年(?:\s*\d{1,2}\s*月)?(?:\s*\d{1,2}\s*日)?|"   # ★ 必须带「年」。
                                                  #   写成 \d{4}年?\d{0,2}月?\d{0,2}日? 的话
                                                  #   年月日全可选 -> 退化成「任意 4 位数字」，
                                                  #   会把「赛博朋克2077」的 2077 当日期吃掉
    r"汉化|中文|官中|官方|简体|繁體|繁体|绿色|免安装|硬盘版|便携版|"
    r"整合包|豪华版|终极版|决定版|重制版|复刻版|完整版|正式版|"
    r"修改器|存档|全DLC|DLC|预购|特典|原声|OST|"
    r"3DM|ali213|GBT|游侠|游民|"                  # 下载站标记（方括号已被 _SEP 去掉）
    r"PC|安卓|手机版|模拟器|Switch|NS|PS[45]|XBOX|"
    r"x64|x86|win(?:dows)?|linux|mac|"
    r"repack|fitgirl|dodi|codex|plaza|skidrow|goldberg|rune|empress|"
    r"\.\d{1,3}(?=\s|$)|"    # 分卷后缀：xxx.001 / xxx(破解版).1
    #   放在**最后** —— 交替是首个匹配优先，放前面会把 v2.13 的 .13 也吃掉
    r"\.?(?:zip|rar|7z|tar|gz|iso|exe|apk)\b)",
    re.I)
_SEP = re.compile(r"[\[\]【】()（）_\-\+~·,，。、!！?？]+")
# 单独的「版」——「中文版」去掉「中文」之后剩下的那个。
# 必须两边都是边界才去，否则「次世代版」「决定版」这类真名字会被削掉。
_ALONE_BAN = re.compile(r"(?:^|\s)版(?=\s|$)")


def _clean(name):
    """把文件名里明显是噪声的部分去掉，留下大概是游戏名的部分。

    这只是**兜底** —— 正常情况下 AI 会给出更准的名字（见 _ai_titles）。
    所以宁可保守：留一点噪声，也别把游戏名削没了。
    """
    n = _SEP.sub(" ", _NOISE.sub(" ", str(name or "")))
    n = _ALONE_BAN.sub(" ", n)
    n = re.sub(r"\s{2,}", " ", n).strip(" .-_")
    return n


def _key(s):
    """比较用的规范形式：小写、去掉一切非字母数字汉字。"""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(s or "").lower())


class _Index:
    def __init__(self, raw):
        raw = raw or {}
        self.gid = raw.get("gid")
        self.scanned_at = raw.get("scanned_at") or 0
        self.ai_done = raw.get("ai_done") or 0
        self.items = raw.get("items") or []

    def dump(self):
        return {"gid": self.gid, "scanned_at": self.scanned_at,
                "ai_done": self.ai_done, "items": self.items}


def setup(ctx):
    # ── 配置默认值自愈 ──────────────────────────────────────
    #
    # 为什么要这一步（2026-10-15 实测到的真问题）：
    #   配置存储会给插件**声明过的每个键**按类型塞一个零值
    #   （text -> ''，number -> 0，bool -> False），于是 CFG 里键是**存在**的，
    #   只是值为空。而 ctx.cfg 的回退链是
    #       CFG.get(key) -> self.config.get(key) -> metadata.defaults
    #   只在拿到 None 时才往下走 —— 拿到 '' 或 0 就停住了。
    #   表现：metadata.json 里写的 defaults 全部失效，插件拿到一堆空配置。
    #   对 THIS 插件最致命的是 gf_ask_words='' —— 问句触发词为空，
    #   群员怎么问「有没有XX」都不会命中，看起来就像插件没工作。
    #
    #   所以这里在**首次加载时**把默认值写进去，之后就不再碰 ——
    #   否则你在配置弹窗里把 gf_ai_max_calls 设成 0（真的不想调 AI），
    #   下次重载又被改回 6。
    _DEFAULTS = {
        # ★ 留空 = **扫所有文件夹**（递归往下走）。这是默认。
        #   以前默认填了「游戏,游戏库,games,单机游戏」，只进名字对得上的文件夹，
        #   你在别的目录名里放的东西就永远扫不到 —— 用户报的"无法扫描文件夹"
        #   就是这个。想让插件只认某几个目录，再把名字填回来。
        "gf_scan_folders": "",
        "gf_ai_enabled": True,
        "gf_ai_batch": 30,
        "gf_ai_max_calls": 6,
        "gf_ask_words": "有没有,有木有,求,谁有,在哪,找一下,来个,想要",
        "gf_reply_limit": 5,
        "gf_auto_link": True,
        "gf_collect_shares": True,
        "gf_auto_scan_hours": 1,
        # link = 只发下载链接（默认，省流量）
        # file = 把文件本身当消息发出来
        # auto = 小于 gf_file_max_mb 的用 file，大的用 link
        "gf_send_mode": "auto",
        "gf_file_max_mb": 100,
    }
    try:
        # ★ 用**版本号**当标记，不是布尔。
        #   布尔只播种一次，之后再加新配置项就永远轮不到它
        #   （2026-10-15 加 gf_auto_scan_hours 时踩到：键是 None，
        #     读出来当成 0，定时扫描起来了却什么都不做）。
        #   版本号变了就重新播一遍 —— 已有的值会被下面的判断跳过，不会覆盖你改过的。
        _SEED_VER = 10
        if int(ctx.cfg("gf_seed_ver", 0) or 0) < _SEED_VER:
            _added = []
            for _k, _v in _DEFAULTS.items():
                _cur = ctx.cfg(_k, None)
                if _cur is None or _cur == "" or _cur is False or _cur == 0:
                    ctx.set_cfg(_k, _v)
                    _added.append(_k)
            ctx.set_cfg("gf_seed_ver", _SEED_VER)
            ctx.log(f"首次运行：已写入默认配置（{len(_added)} 项）")
    except Exception as e:
        ctx.warn(f"写默认配置失败：{type(e).__name__}: {e}")

    # ── 配置 ────────────────────────────────────────────────
    def _folder_names():
        raw = str(ctx.cfg("gf_scan_folders", "游戏,游戏库") or "")
        return [x.strip().lower() for x in re.split(r"[,，\s]+", raw) if x.strip()]

    def _ask_words():
        raw = str(ctx.cfg("gf_ask_words", "有没有,求,谁有") or "")
        return [x.strip() for x in re.split(r"[,，\s]+", raw) if x.strip()]

    def _load(gid):
        try:
            return _Index(json.loads(ctx.kv_get(f"gamefiles:{gid}", "") or "{}"))
        except Exception as e:
            ctx.warn(f"索引读取失败（群 {gid}）：{type(e).__name__}: {e}")
            return _Index({})

    def _save(idx):
        try:
            ctx.kv_set(f"gamefiles:{idx.gid}", json.dumps(idx.dump(), ensure_ascii=False))
            return True
        except Exception as e:
            ctx.warn(f"索引保存失败：{type(e).__name__}: {e}")
            return False

    # ── 读群文件 ────────────────────────────────────────────
    async def _list_dir(gid, folder_id=""):
        """取一层目录。返回 (files, folders)；出错返回 (None, None)。

        None 和「这层是空的」要分开 —— 前者说明 OneBot 调用失败，
        继续往下走会把已有索引覆盖成空的。
        """
        if folder_id:
            r = await ctx.onebot("get_group_files_by_folder",
                                 group_id=int(gid), folder_id=folder_id)
        else:
            r = await ctx.onebot("get_group_root_files", group_id=int(gid))
        if not isinstance(r, dict):
            return None, None
        return (r.get("files") or []), (r.get("folders") or [])

    async def _walk(gid, folder_id="", want=None, depth=0, out=None):
        """递归扫目录。want 非空时只进名字匹配的文件夹。"""
        if out is None:
            out = []
        if depth > 4:                      # 防目录套娃
            return out
        files, folders = await _list_dir(gid, folder_id)
        if files is None:
            return None                    # 传上去：整次扫描算失败
        for f in files:
            if f.get("file_name"):
                out.append({
                    "name": str(f.get("file_name")),
                    "file_id": str(f.get("file_id") or ""),
                    "busid": f.get("busid"),
                    "size": int(f.get("file_size") or 0),
                    "folder_id": folder_id,
                })
        for d in folders:
            dn = str(d.get("folder_name") or "")
            fid = str(d.get("folder_id") or "")
            if not fid:
                continue
            if want and _key(dn) and not any(w in _key(dn) or _key(dn) in w for w in want):
                continue
            r = await _walk(gid, fid, want, depth + 1, out)
            if r is None:
                return None
        return out

    # ── AI 整理 ─────────────────────────────────────────────
    async def _ai_titles(names):
        """让 AI 把一批文件名整成 {原名: {title, aliases}}。失败返回 {}。"""
        listing = "\n".join(f"{i+1}. {n}" for i, n in enumerate(names))
        prompt = (
            "下面是一批游戏文件的文件名。请把每个文件名整理成游戏名。\n"
            "要求：\n"
            "1. 去掉版本号、汉化/免安装/硬盘版之类的字样和下载站标记\n"
            "2. 保留游戏正式名称，中英文都保留（如「塞尔达传说：王国之泪 / Tears of the Kingdom」）\n"
            "3. 另给 2-4 个群员可能用来搜的别名（简称、英文名、俗称）\n"
            "4. **只输出一个 JSON 数组**，不要解释、不要代码块标记。格式：\n"
            '[{"i":1,"title":"游戏名","aliases":["别名1","别名2"]}]\n\n'
            f"文件名：\n{listing}"
        )
        try:
            raw = await ctx.ai(prompt, timeout=60.0)
        except Exception as e:
            ctx.warn(f"AI 整理失败：{type(e).__name__}: {e}")
            return {}
        if not raw:
            return {}
        m = re.search(r"\[.*\]", str(raw), re.S)
        if not m:
            ctx.warn("AI 整理返回的不是 JSON 数组，这一批跳过")
            return {}
        try:
            arr = json.loads(m.group(0))
        except Exception as e:
            ctx.warn(f"AI 整理 JSON 解析失败：{type(e).__name__}: {e}")
            return {}
        out = {}
        for row in arr if isinstance(arr, list) else []:
            try:
                i = int(row.get("i")) - 1
            except Exception:
                continue
            if 0 <= i < len(names):
                t = str(row.get("title") or "").strip()
                al = row.get("aliases")
                al = [str(x).strip() for x in al if str(x).strip()] if isinstance(al, list) else []
                if t:
                    out[names[i]] = {"title": t, "aliases": al[:6]}
        return out

    async def _ai_enrich(idx, force=False):
        """给索引里还没有 title 的条目补上。返回补了几条。"""
        if not ctx.cfg("gf_ai_enabled", True):
            return 0
        todo = [it for it in idx.items if force or not it.get("title")]
        if not todo:
            return 0
        try:
            batch = max(5, min(80, int(ctx.cfg("gf_ai_batch", 30))))
        except Exception:
            batch = 30
        try:
            max_calls = max(0, min(30, int(ctx.cfg("gf_ai_max_calls", 6))))
        except Exception:
            max_calls = 6
        got, calls = 0, 0
        for s in range(0, len(todo), batch):
            if calls >= max_calls:
                ctx.warn(f"AI 整理已达本次上限 {max_calls} 批，剩下的下次再补")
                break
            chunk = todo[s:s + batch]
            names = [it["name"] for it in chunk]
            res = await _ai_titles(names)
            calls += 1
            for it in chunk:
                r = res.get(it["name"])
                if r:
                    it["title"] = r["title"]
                    it["aliases"] = r["aliases"]
                    got += 1
                else:
                    it.setdefault("title", _clean(it["name"]))
                    it.setdefault("aliases", [])
            ctx.log(f"AI 整理第 {calls} 批：{len(chunk)} 个里成功 {len(res)} 个")
        idx.ai_done = int(idx.ai_done or 0) + got
        return got

    def _fallback_titles(idx):
        """AI 关掉或失败时，用去噪后的文件名当标题，保证还能搜。"""
        n = 0
        for it in idx.items:
            if not it.get("title"):
                it["title"] = _clean(it["name"]) or it["name"]
                it.setdefault("aliases", [])
                n += 1
        return n

    # ── 扫描 ────────────────────────────────────────────────
    async def _scan(gid, force_ai=False):
        gid = int(gid)
        want = [_key(x) for x in _folder_names()]
        want = [w for w in want if w]
        files = await _walk(gid, "", want)
        if files is None:
            return None, "读群文件失败 —— 检查 NapCat 是否在线、有没有 get_group_root_files 权限"
        if not files:
            return None, "这个群里没扫到文件。如果文件都在某个文件夹里，把文件夹名填进插件配置的「扫描目录」"
        old = _load(gid)
        oldmap = {}
        for it in old.items:
            if it.get("file_id"):
                oldmap[it["file_id"]] = it
        items = []
        for f in files:
            prev = oldmap.get(f["file_id"])
            if prev:
                prev.update({"name": f["name"], "busid": f["busid"],
                             "size": f["size"], "folder_id": f["folder_id"]})
                items.append(prev)
            else:
                f["title"] = ""
                f["aliases"] = []
                items.append(f)
        # ★ 去重：同一个文件名在根目录和子目录里各有一份时会重复出现
        #   （2026-10-15 群里实测：回复里同一条列了两遍）。
        #   按 (文件名, 大小) 去重 —— 名字和大小都一样就当同一个。
        _seen, _uniq = set(), []
        for it in items:
            k = (_key(it.get("name")), it.get("size"))
            if k in _seen:
                continue
            _seen.add(k)
            _uniq.append(it)
        if len(_uniq) != len(items):
            ctx.log(f"去重：{len(items)} -> {len(_uniq)}")
        items = _uniq
        idx = _Index({"gid": gid, "scanned_at": int(time.time()),
                      "ai_done": old.ai_done, "items": items})
        _n_share = _merge_shares(idx)     # 把消息里收到的闪传链接并进来
        got = await _ai_enrich(idx, force=force_ai)
        if not got:
            _fallback_titles(idx)
        _save(idx)
        await _reg_touch(gid, idx)    # 登记到管理页的群列表里
        tail = f"，AI 整理了 {got} 个" if got else ""
        if _n_share:
            tail += f"，闪传 {_n_share} 个"
        return idx, f"扫到 {len(items)} 个文件{tail}"

    # ── 搜索 ────────────────────────────────────────────────
    def _search(idx, q):
        """返回按相关度排好的条目。"""
        kq = _key(q)
        if not kq:
            return []
        hits = []
        for it in idx.items:
            cands = [it.get("title") or "", it.get("name") or ""] + list(it.get("aliases") or [])
            best, why = 0, ""
            for c in cands:
                kc = _key(c)
                if not kc:
                    continue
                if kc == kq:
                    s = 100
                elif kq in kc:
                    s = 80 - min(30, len(kc) - len(kq))       # 越短越像
                elif kc in kq:
                    s = 60 - min(20, len(kq) - len(kc))
                else:
                    continue
                if s > best:
                    best, why = s, c
            if best:
                hits.append((best, it, why))
        hits.sort(key=lambda x: -x[0])
        return hits

    def _ask_query(text):
        """从一句话里抽出他在找什么。不是「在问有没有东西」就返回 ''。"""
        t = str(text or "").strip()
        if not t or len(t) > 60:
            return ""
        t = re.sub(r"@\S+\s*", "", t).strip()
        for w in _ask_words():
            if w and w in t:
                q = t.split(w, 1)[1]
                q = re.sub(r"^(一下|一个|个|款|这|那|个游戏|游戏)?\s*", "", q.strip())
                q = re.sub(r"[?？!！。.~～\s]+$", "", q).strip()
                q = re.sub(r"^(叫|是)?\s*", "", q).strip()
                if 1 < len(q) <= 30:
                    return q
                return ""
        return ""

    # ── 发链接 ──────────────────────────────────────────────
    async def _fresh_id(gid, name):
        """按文件名现查一遍群文件，拿**当前**的 file_id/busid。

        为什么需要（2026-10-15 实测到的真 bug）：
          索引里存的 file_id 会失效 —— 群文件被重传、改名、或群文件系统
          重建之后，同一个文件的 file_id 会变。而 get_group_file_url 拿到
          失效 id 时**不报错、不抛异常，直接返回 null**，于是插件一直走
          "链接取不到"分支 —— 用户看到的就是"无法分享文件"。
          实测对比：索引里是 58dd183b…，get_group_root_files 现在给的是
          eb86e99e…，同一个「汉堡店的4夜.zip」。
        """
        # ★ 第三个参数是「只进名字匹配的文件夹」——**这里必须传 None**。
        #   传文件名的话，就变成"只在名字等于这个文件名的文件夹里找"，
        #   子目录里的文件永远查不到（2026-10-15 群里实测：
        #   「【AZ】野猫0.4全画廊『官中』.zip」在子目录里 -> 重查返回空 -> 回复没链接）。
        files = await _walk(int(gid), "", None)
        if not files:
            return None
        want = _key(name)
        for f in files:
            if _key(f.get("name")) == want:
                return f
        for f in files:
            k = _key(f.get("name"))
            if want and (want in k or k in want):
                return f
        return None

    async def _send_as_file(gid, it, url):
        r"""把文件**本身**当消息发到群里（而不是贴一条链接）。

        原理：NapCat 的 upload_group_file 收 URL —— 它会把文件拉到临时目录、
        作为文件消息发出去、发完删掉临时文件。
        （源码：actionDescription = "上传资源路径或URL指定的文件到指定群聊的
          文件系统中"，_handle 里 Wr(NapCatTempPath, n) 再 sendMsgWithOb11UniqueId）

        upload_file=False 是 NapCat 的临时扩展，让它**只发消息、不落进群文件列表**
        —— 否则群里会多出一份重复文件。

        ★ 代价：QQ 仍然要把这个文件重新传一遍。3GB 的文件就是真传 3GB，
          群里所有人也会收到一个大文件。所以默认不走这条路。
        """
        import asyncio
        try:
            r = await asyncio.wait_for(
                ctx.onebot("upload_group_file", group_id=int(gid),
                           file=str(url),
                           name=str(it.get("name") or "file"),
                           upload_file=False),
                timeout=45)
            return isinstance(r, dict)
        except asyncio.TimeoutError:
            ctx.warn(f"发文件超时（{it.get('name')}）—— 文件太大，改发链接")
            return False
        except Exception as e:
            ctx.warn(f"发文件失败（{it.get('name')}）：{type(e).__name__}: {e}")
            return False

    def _with_fname(url, name):
        r"""把文件名填进腾讯下载链接末尾那个空的 fname= 参数。

        为什么（2026-10-15 用户反馈"不好看"）：
            NapCat 的 get_group_file_url 返回的链接长这样：
                https://njc-download.ftn.qq.com/ftn_handler/<hash>/?fname=
            **fname 是空的**。填上文件名有两个好处：
              ① 群员点下载时，存下来的文件名是对的，不是一串哈希
              ② QQ 看到 URL 里带文件名，更可能把它渲染成下载卡片
        已经带了 fname 的就原样返回，不覆盖。
        """
        try:
            from urllib.parse import quote
            u = str(url or "")
            n = str(name or "").strip()
            if not u or not n:
                return u
            if "fname=" not in u:
                return u + ("&" if "?" in u else "?") + "fname=" + quote(n)
            head, _, tail = u.partition("fname=")
            if tail.strip():
                return u                      # 已经有了，不动
            return head + "fname=" + quote(n)
        except Exception:
            return str(url or "")

    async def _link(it, gid):
        """取文件的分享链接。先试索引里的 id，失效了再按名字现查。"""
        # ★ 不要先拿索引里的 file_id 去试。
        #   为什么（2026-10-15 实测）：get_group_root_files 返回的 file_id 是
        #   **会话级**的 —— 扫的时候拿到，回复的时候早就过期了。拿它去调
        #   get_group_file_url，NapCat 会在**它自己的日志**里打一条
        #     [error] real fileUUID not found!
        #   每次问文件都蹦一条，看着像出了大问题，其实只是白试一次。
        #   所以直接按名字现查当前 id，一次到位，日志也干净。
        f = await _fresh_id(gid, it.get("name"))
        if not f:
            return ""
        r = await ctx.onebot("get_group_file_url", group_id=int(gid),
                             file_id=f.get("file_id"), busid=f.get("busid"))
        u = (r or {}).get("url") if isinstance(r, dict) else ""
        if u:
            # 顺手把索引里的旧 id 就地更新，下次就不用再查一遍
            it["file_id"] = f.get("file_id")
            it["busid"] = f.get("busid")
            return _with_fname(u, it.get("name"))
        return ""

    def _size(n):
        try:
            n = float(n or 0)
        except Exception:
            return "?"
        for u in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024 or u == "TB":
                return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
            n /= 1024.0
        return "?"

    # ── 命令 ────────────────────────────────────────────────
    @ctx.command("扫游戏库", "扫描本群文件，重建游戏索引（仅超管）", timeout=600)
    async def _cmd_scan(event, cmd):
        if not ctx.is_super(event.user_id):
            await ctx.send_group(event.group_id, [ctx.mention(event.user_id), "这个只有管理员能扫。"])
            return True
        await ctx.send_group(event.group_id, "开始扫群文件，文件多的话要等一会儿……")
        idx, msg = await _scan(event.group_id, force_ai=False)
        if idx is None:
            await ctx.send_group(event.group_id, f"扫描失败：{msg}")
            return True
        await ctx.send_group(event.group_id,
                             f"{msg}。\n群员直接说「有没有 游戏名」就能查了。")
        return True

    @ctx.command("重扫游戏库", "重扫并把 AI 整理也重做一遍（仅超管）", timeout=900)
    async def _cmd_rescan(event, cmd):
        if not ctx.is_super(event.user_id):
            await ctx.send_group(event.group_id, [ctx.mention(event.user_id), "这个只有管理员能做。"])
            return True
        await ctx.send_group(event.group_id, "重扫中，AI 要重新过一遍，会慢一些……")
        idx, msg = await _scan(event.group_id, force_ai=True)
        if idx is None:
            await ctx.send_group(event.group_id, f"扫描失败：{msg}")
            return True
        await ctx.send_group(event.group_id, msg)
        return True

    @ctx.command("游戏库", "看看收录了多少个游戏")
    async def _cmd_info(event, cmd):
        idx = _load(event.group_id)
        if not idx.items:
            await ctx.send_group(event.group_id,
                                 "还没有索引。让管理员发一次「扫游戏库」。")
            return True
        named = sum(1 for it in idx.items if it.get("title"))
        when = time.strftime("%m-%d %H:%M", time.localtime(idx.scanned_at)) if idx.scanned_at else "未知"
        await ctx.send_group(event.group_id,
                             f"收录 {len(idx.items)} 个文件，其中 {named} 个整理出了名字。\n"
                             f"上次扫描：{when}\n"
                             f"直接说「有没有 游戏名」就能查。")
        return True

    # ── 群员问询（不用命令）────────────────────────────────
    @ctx.on_message(timeout=600)   # 发文件可能传很久
    async def _on_ask(event, text):
        _ensure_auto()
        gid = getattr(event, "group_id", None)
        if not gid:                       # 只管群，私聊不掺和
            return False
        q = _ask_query(text)
        if not q:
            return False
        idx = _load(gid)
        if not idx.items:
            return False                  # 没索引就别乱答，让 AI 正常回
        hits = _search(idx, q)
        if not hits:
            await ctx.send_group(gid, [ctx.mention(event.user_id),
                                       f"群里好像没有「{q}」。"])
            return True
        try:
            limit = max(1, min(10, int(ctx.cfg("gf_reply_limit", 5))))
        except Exception:
            limit = 5
        lines = [f"找到 {len(hits)} 个和「{q}」有关的："]
        _links = []          # 收集链接，正文里不再内联
        for _, it, why in hits[:limit]:
            title = it.get("title") or _clean(it["name"]) or it["name"]
            lines.append(f"· {title}  ({_size(it.get('size'))})")
            if not ctx.cfg("gf_auto_link", True):
                continue
            # 先拿到这个文件的下载链接（顺带自愈失效的 file_id）
            _u = str(it.get("url") or "")
            if not _u and it.get("file_id"):
                _u = await _link(it, gid)

            # 按 gf_send_mode 决定：发**文件本身**，还是发链接
            _mode = str(ctx.cfg("gf_send_mode", "link") or "link").strip().lower()
            _mb = float(it.get("size") or 0) / 1024.0 / 1024.0
            try:
                _maxmb = float(ctx.cfg("gf_file_max_mb", 100) or 100)
            except Exception:
                _maxmb = 100.0
            # ★ 硬上限 200MB —— 不管配置填多大都不越过。
            #   为什么（2026-10-15 群里实测）：NapCat 的 upload_group_file 里
            #   第一步就是 Wr(NapCatTempPath, url) —— **把文件整个下载到本地临时目录**，
            #   不管 upload_file 传 true 还是 false。2.5GB 的文件下载必然超过
            #   NapCat 的 WS 调用超时（约 30 秒），报
            #   "WebSocket call api upload_group_file timeout"，
            #   而且白占一份磁盘。所以大文件只能发链接。
            _HARD_MAX_MB = 200.0
            _cap = min(_maxmb, _HARD_MAX_MB)
            _want_file = (_mode == "file" or _mode == "auto") and _mb <= _cap
            if _mode in ("file", "auto") and _mb > _HARD_MAX_MB:
                ctx.log(f"{it.get('name')} 有 {_mb:.0f}MB，超过 200MB 硬上限，改发链接")

            if _u and _want_file:
                if await _send_as_file(gid, it, _u):
                    continue          # 文件发出去了，就不用再贴链接
                # 发失败就落回链接，不要什么都不给
            if _u:
                _links.append(_u)
            else:
                lines.append(f"  （链接取不到，去群文件里搜「{it['name']}」）")
        await ctx.send_group(gid, [ctx.mention(event.user_id), "\n".join(lines)])

        # ★ 链接**每条单独发**，不要拼进上面那段。
        #   为什么：QQ 只有在"整条消息就是链接"的时候才渲染成下载卡片；
        #   夹在文字中间只是一串蓝字，又长又难看出是能点的。
        #   条与条之间停一下，免得刷屏或者被当成刷屏。
        import asyncio
        for _l in _links[:limit]:
            try:
                await ctx.send_group(gid, _l)
            except Exception as e:
                ctx.warn(f"发链接失败：{type(e).__name__}: {e}")
            await asyncio.sleep(0.8)

        ctx.log(f"群 {gid}：{event.user_id} 问「{q}」，命中 {len(hits)} 个，发了 {len(_links)} 条链接")
        return True

    # ── ★ 闪传链接收集 ──────────────────────────────────────
    #
    # 为什么需要（2026-10-15 实测到的真问题）：
    #   群里的游戏大多是**「QQ文件闪传」**分享的，消息长这样：
    #       洛通过QQ文件闪传分享了【【AZ】[安卓]凤凰17.0.1.zip】
    #       链接：https://qfile.qq.com/q/TJHIl0WF6q
    #   闪传**不在群文件列表里** —— get_group_root_files 看不到它，
    #   get_group_file_url 也生成不了它的链接（那个动作只认群文件）。
    #   所以光扫群文件，"分享文件"这一步永远做不到。
    #   好在链接就明明白白写在消息里 —— 收下来直接发就行。
    _SHARE_URL = re.compile(r"https?://qfile\.qq\.com/q/[\w\-]+", re.I)
    # 注意用贪婪的 (.+) —— 标题里常带嵌套的【】：【【AZ】[安卓]xxx.zip】
    # 非贪婪会把「【AZ」当成标题、丢掉后面的真名字。
    _SHARE_TITLE = re.compile(r"分享了?【(.+)】")

    def _load_shares(gid):
        try:
            d = json.loads(ctx.kv_get(f"gamefiles:shared:{gid}", "") or "[]")
            return d if isinstance(d, list) else []
        except Exception:
            return []

    def _save_share(gid, url, title, who):
        rows = _load_shares(gid)
        for r in rows:
            if r.get("url") == url:
                r["title"] = title or r.get("title") or ""
                r["hits"] = int(r.get("hits") or 0) + 1
                break
        else:
            rows.append({"url": url, "title": title or "",
                         "name": title or url, "from": str(who or ""),
                         "at": int(time.time()), "hits": 1,
                         "size": 0, "aliases": []})
            ctx.log(f"群 {gid}：收到一个新闪传链接 —— {title or url}")
        try:
            ctx.kv_set(f"gamefiles:shared:{gid}", json.dumps(rows[-3000:], ensure_ascii=False))
        except Exception as e:
            ctx.warn(f"闪传链接保存失败：{type(e).__name__}: {e}")

    def _merge_shares(idx):
        """把闪传链接并进索引（作为 url 条目）。返回并进来几条新的。"""
        rows = _load_shares(idx.gid)
        if not rows:
            return 0
        have = {it.get("url") for it in idx.items if it.get("url")}
        add = 0
        for r in rows:
            u = r.get("url")
            if not u or u in have:
                continue
            t = r.get("title") or ""
            idx.items.append({
                "name": (t or u), "url": u, "file_id": "", "busid": None,
                "size": int(r.get("size") or 0), "folder_id": "",
                "title": _clean(t) if t else "", "aliases": [],
                "from": r.get("from") or "",
            })
            add += 1
        return add

    @ctx.on_message(timeout=20)
    async def _on_share(event, text):
        """消息里出现闪传链接就收下来。永远返回 False —— 不拦消息。"""
        _ensure_auto()
        gid = getattr(event, "group_id", None)
        if not gid or not ctx.cfg("gf_collect_shares", True):
            return False
        t = str(text or "")
        urls = _SHARE_URL.findall(t)
        if not urls:
            return False
        m = _SHARE_TITLE.search(t)
        title = m.group(1).strip() if m else ""
        for u in urls[:3]:
            _save_share(gid, u, title, getattr(event, "user_id", ""))
        return False

    # ── ★ 每小时自动扫 ──────────────────────────────────────
    async def _auto_scan_loop():
        import asyncio
        # 启动后先等一会儿，别和开机那堆事抢
        await asyncio.sleep(120)
        while True:
            try:
                hrs = float(ctx.cfg("gf_auto_scan_hours", 1) or 0)
            except Exception:
                hrs = 1.0
            if hrs <= 0:
                await asyncio.sleep(1800)
                continue
            try:
                reg = _reg_load()
                for gid in list(reg.keys()):
                    try:
                        idx, msg = await _scan(int(gid), force_ai=False)
                        if idx is None:
                            ctx.warn(f"定时扫描：群 {gid} 失败 —— {msg}")
                        else:
                            ctx.log(f"定时扫描：群 {gid} {msg}")
                    except Exception as e:
                        ctx.warn(f"定时扫描异常（群 {gid}）：{type(e).__name__}: {e}")
                    await asyncio.sleep(5)      # 群之间喘口气
            except Exception as e:
                ctx.warn(f"定时扫描循环异常：{type(e).__name__}: {e}")
            await asyncio.sleep(max(600.0, hrs * 3600.0))

    # ★ setup() 是**同步**跑的，那时还没有事件循环 ——
    #   asyncio.create_task 会抛 RuntimeError: no running event loop，
    #   定时扫描就永远起不来（2026-10-15 实测，日志里那行"启动失败"就是它）。
    #   所以第一次失败不要紧，等第一条消息进来时在**事件循环里**再起。
    _AUTO = {"started": False}

    def _ensure_auto():
        if _AUTO["started"]:
            return
        try:
            import asyncio
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return                      # 还没进事件循环，下次再说
        try:
            loop.create_task(_auto_scan_loop())
            _AUTO["started"] = True
            ctx.log("定时扫描已启动")
        except Exception as e:
            ctx.warn(f"定时扫描启动失败：{type(e).__name__}: {e}")

    try:
        _ensure_auto()                  # 热重载时这里就能起
    except Exception:
        pass

    # ── 群登记表 ────────────────────────────────────────────
    # kv 里每个群的索引是 gamefiles:<群号>，天然是分群的。
    # 但光有那些 key 没法枚举 —— 管理页要列出"哪些群扫过"，
    # 所以另外维护一份小登记表。键名带 __ 前缀，不会跟群号撞。
    _REG_KEY = "gamefiles:__groups__"

    def _reg_load():
        try:
            d = json.loads(ctx.kv_get(_REG_KEY, "") or "{}")
            return d if isinstance(d, dict) else {}
        except Exception as e:
            ctx.warn(f"群登记表读取失败：{type(e).__name__}: {e}")
            return {}

    async def _reg_touch(gid, idx):
        """把这个群登记进管理页的群列表。

        ★ group_name 是 **async** 的 —— 不 await 会拿到一个协程对象，
          然后 json.dumps 报 "Object of type coroutine is not JSON serializable"。
          （2026-10-15 第一次跑真群扫描时踩到的，日志里那句话就是它。）
        """
        d = _reg_load()
        try:
            nm = await ctx.group_name(int(gid))
            nm = str(nm or "")
        except Exception as e:
            ctx.warn(f"取群名失败（群 {gid}）：{type(e).__name__}: {e}")
            nm = ""
        d[str(gid)] = {"name": nm, "count": len(idx.items),
                       "named": sum(1 for it in idx.items if it.get("title")),
                       "scanned_at": idx.scanned_at}
        try:
            ctx.kv_set(_REG_KEY, json.dumps(d, ensure_ascii=False))
        except Exception as e:
            ctx.warn(f"群登记表保存失败：{type(e).__name__}: {e}")

    # ── 管理页接口 ──────────────────────────────────────────
    async def _api_groups(request, body):
        """所有扫过的群。带群名、文件数、上次扫描时间。"""
        d = _reg_load()
        rows = []
        for gid, info in d.items():
            if not isinstance(info, dict):
                continue
            rows.append({"gid": gid, "name": info.get("name") or "",
                         "count": info.get("count") or 0,
                         "named": info.get("named") or 0,
                         "scanned_at": info.get("scanned_at") or 0})
        rows.sort(key=lambda r: -int(r.get("scanned_at") or 0))
        return {"ok": True, "groups": rows}

    async def _api_items(request, body):
        """某个群的索引明细。q 非空时按关键词过滤。"""
        gid = str(request.query_params.get("gid") or "").strip()
        q = str(request.query_params.get("q") or "").strip()
        if not gid:
            return {"ok": False, "error": "缺少 gid"}
        try:
            idx = _load(int(gid))
        except Exception:
            return {"ok": False, "error": "群号不是数字"}
        items = idx.items
        if q:
            got = _search(idx, q)
            items = [it for _, it, _ in got] or items
        out = []
        for it in items[:2000]:
            out.append({
                "name": it.get("name") or "",
                "title": it.get("title") or "",
                "aliases": it.get("aliases") or [],
                "size": it.get("size") or 0,
                "size_h": _size(it.get("size")),
            })
        return {"ok": True, "gid": gid, "scanned_at": idx.scanned_at,
                "count": len(idx.items), "shown": len(out), "items": out}

    # 扫描在后台跑。
    # 为什么：AI 开着的时候一次扫描可能要好几分钟（每批最多 60 秒 ×
    # gf_ai_max_calls 批），让管理页的 HTTP 请求一直等着会直接超时 500，
    # 而且超时会把 _reg_touch 那一步也打断 —— 表现就是"扫完了但群列表还是空的"。
    # 所以这里立刻返回，页面自己刷新看结果。
    _SCANNING = {}

    async def _api_scan(request, body):
        """触发一次扫描。立刻返回，实际扫描在后台跑。"""
        import asyncio
        gid = str((body or {}).get("gid") or "").strip()
        force = bool((body or {}).get("force"))
        if not gid:
            return {"ok": False, "error": "缺少 gid"}
        if _SCANNING.get(gid):
            return {"ok": False, "error": "这个群正在扫，等它跑完再点"}

        async def _job():
            _SCANNING[gid] = True
            try:
                idx, msg = await _scan(int(gid), force_ai=force)
                ctx.log(f"群 {gid} 扫描完成：{msg}" if idx is not None
                        else f"群 {gid} 扫描失败：{msg}")
            except Exception as e:
                ctx.warn(f"后台扫描异常（群 {gid}）：{type(e).__name__}: {e}")
            finally:
                _SCANNING.pop(gid, None)

        asyncio.create_task(_job())
        return {"ok": True, "msg": "已开始扫描，跑完页面刷新就能看到（AI 开着的话要几分钟）"}

    async def _api_forget(request, body):
        """删掉一个群的索引（重扫之前想清干净时用）。"""
        gid = str((body or {}).get("gid") or "").strip()
        if not gid:
            return {"ok": False, "error": "缺少 gid"}
        try:
            ctx.kv_set(f"gamefiles:{gid}", "")
            d = _reg_load()
            d.pop(gid, None)
            ctx.kv_set(_REG_KEY, json.dumps(d, ensure_ascii=False))
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        return {"ok": True}

    # 调试用：拿索引里第 N 个群文件，真的去问一次 OneBot 要链接，
    # 把**原始返回**原样吐出来。排查"分享不了文件"时必须看这个 ——
    # 到底是 NapCat 不支持这个动作、还是 file_id/busid 不对、
    # 还是返回了 URL 但 QQ 那边不认。
    async def _api_probe(request, body):
        import asyncio
        gid = str(request.query_params.get("gid") or "").strip()
        n = int(request.query_params.get("n") or 0)
        if not gid:
            return {"ok": False, "error": "缺少 gid"}
        idx = _load(int(gid))
        files = [it for it in idx.items if it.get("file_id")]
        if not files:
            return {"ok": False, "error": "索引里没有带 file_id 的群文件"}
        it = files[min(n, len(files) - 1)]
        out = {"ok": True, "picked": {"name": it.get("name"),
                                      "file_id": it.get("file_id"),
                                      "busid": it.get("busid")}}
        # ① 先问一次版本，确认 OneBot 是活的
        try:
            out["version_info"] = await ctx.onebot("get_version_info")
        except Exception as e:
            out["version_info_error"] = f"{type(e).__name__}: {e}"
        # ② 一次试多个变体 —— 不猜 NapCat 支持哪个，实测。
        #    背景：get_group_file_url 在 NapCat 4.18.30 上返回的是 **null**
        #    （不报错、不抛异常），所以插件一直走"链接取不到"那条分支 ——
        #    用户看到的就是"无法分享文件"。
        # ★ 不要拿索引里的旧 file_id 去试 get_group_file_url ——
        #   那个 id 解不出 fileUUID，NapCat 会在**它自己的日志**里刷
        #   "real fileUUID not found!"，看着像出了大问题，其实只是这个探针。
        #   （2026-10-15 排查了半天，就是这三条自己造的。）
        #   直接走真实路径 _link()，它内部会先用索引 id、失败再按名字现查。
        variants = [
            ("get_group_file_system_info", {"group_id": int(gid)}),
            ("get_group_root_files", {"group_id": int(gid)}),
        ]
        tried = []
        for name, kw in variants:
            try:
                r = await asyncio.wait_for(ctx.onebot(name, **kw), timeout=25)
            except Exception as e:
                tried.append({"action": name, "args": list(kw.keys()),
                              "error": f"{type(e).__name__}: {e}"})
                continue
            got = None
            if isinstance(r, dict):
                for key in ("url", "file_url", "download_url"):
                    if r.get(key):
                        got = r[key]
                        break
            tried.append({"action": name, "args": list(kw.keys()),
                          "type": type(r).__name__, "url": got,
                          "raw": (json.dumps(r, ensure_ascii=False)[:400]
                                  if r is not None else None)})
            if got:
                out["url"] = got
                out["works"] = {"action": name, "args": list(kw.keys())}
                break
        out["tried"] = tried
        # ③ 走真实代码路径：_link() 会先用索引 id、失效就按名字现查
        try:
            out["_link_result"] = await asyncio.wait_for(_link(it, gid), timeout=60)
        except Exception as e:
            out["_link_error"] = f"{type(e).__name__}: {e}"
        # ④ 顺便看看现查能不能拿到正确的 id
        try:
            f = await asyncio.wait_for(_fresh_id(gid, it.get("name")), timeout=60)
            out["fresh"] = ({"name": f.get("name"), "file_id": f.get("file_id"),
                             "busid": f.get("busid")} if f else None)
            if f:
                r = await asyncio.wait_for(
                    ctx.onebot("get_group_file_url", group_id=int(gid),
                               file_id=f.get("file_id"), busid=f.get("busid")),
                    timeout=25)
                out["fresh_url"] = (r or {}).get("url") if isinstance(r, dict) else None
                out["fresh_raw"] = (json.dumps(r, ensure_ascii=False)[:300]
                                    if r is not None else None)
        except Exception as e:
            out["fresh_error"] = f"{type(e).__name__}: {e}"
        return out

    ctx.register_api("/admin/api/plugins/gamefiles/probe", _api_probe, ("GET",), timeout=180)

    ctx.register_api("/admin/api/plugins/gamefiles/groups", _api_groups, ("GET",))
    ctx.register_api("/admin/api/plugins/gamefiles/items", _api_items, ("GET",))
    ctx.register_api("/admin/api/plugins/gamefiles/scan", _api_scan, ("POST",), timeout=120)
    ctx.register_api("/admin/api/plugins/gamefiles/forget", _api_forget, ("POST",))

    # ── 管理页 ──────────────────────────────────────────────
    # 插件页面的脚本跑在**全局作用域**，所以函数名统一加 gf_ 前缀。
    ctx.register_page("gamefiles", "游戏库", r"""
<div class="card">
  <h3 style="margin:0 0 4px">游戏库索引</h3>
  <div class="muted" style="margin-bottom:12px">
    每个群的索引是分开存的。群里发一次「扫游戏库」就会登记到这里。
  </div>

  <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px">
    <select id="gf-gid" onchange="gf_load()" style="min-width:220px"></select>
    <input id="gf-q" placeholder="筛选游戏名…" oninput="gf_filter()"
           style="min-width:200px;flex:1">
    <button class="btn" onclick="gf_load()">刷新</button>
    <button class="btn" onclick="gf_scan(false)">重新扫描</button>
    <button class="btn" onclick="gf_scan(true)">重扫+AI整理</button>
  </div>

  <div id="gf-stat" class="muted" style="margin-bottom:8px"></div>
  <div id="gf-list"></div>
</div>

<script>
(function(){
  var GF_ROWS = [];
  function tok(){ return (typeof TOKEN !== "undefined") ? TOKEN : ""; }
  function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g, function(c){
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  function api(p, opt){
    var s = p.indexOf("?") >= 0 ? "&" : "?";
    return fetch(p + s + "token=" + encodeURIComponent(tok()), opt || {})
      .then(function(r){ return r.json(); });
  }

  window.gf_load = function(){
    var sel = document.getElementById("gf-gid");
    var gid = sel ? sel.value : "";
    if (!gid) { gf_groups(); return; }
    document.getElementById("gf-stat").textContent = "读取中…";
    api("/admin/api/plugins/gamefiles/items?gid=" + encodeURIComponent(gid))
      .then(function(d){
        if (!d || !d.ok) {
          document.getElementById("gf-stat").textContent = "读取失败：" + ((d&&d.error)||"?");
          return;
        }
        GF_ROWS = d.items || [];
        var t = d.scanned_at ? new Date(d.scanned_at*1000).toLocaleString() : "未知";
        document.getElementById("gf-stat").textContent =
          "共 " + d.count + " 个文件，上次扫描 " + t;
        gf_filter();
      })
      .catch(function(e){
        document.getElementById("gf-stat").textContent = "请求出错：" + e;
      });
  };

  window.gf_filter = function(){
    var q = (document.getElementById("gf-q").value || "").trim().toLowerCase();
    var rows = GF_ROWS;
    if (q) {
      rows = rows.filter(function(it){
        var hay = [it.title, it.name].concat(it.aliases || []).join(" ").toLowerCase();
        return hay.indexOf(q) >= 0;
      });
    }
    var el = document.getElementById("gf-list");
    if (!rows.length) { el.innerHTML = '<div class="muted">没有匹配的条目。</div>'; return; }
    var h = ['<table style="width:100%;border-collapse:collapse;font-size:13px">',
             '<tr><th style="text-align:left;padding:6px 8px;border-bottom:1px solid #0002">游戏名</th>',
             '<th style="text-align:left;padding:6px 8px;border-bottom:1px solid #0002">文件名</th>',
             '<th style="text-align:right;padding:6px 8px;border-bottom:1px solid #0002">大小</th>',
             '<th style="text-align:left;padding:6px 8px;border-bottom:1px solid #0002">别名</th></tr>'];
    rows.slice(0, 500).forEach(function(it){
      h.push("<tr>",
        '<td style="padding:5px 8px;border-bottom:1px solid #0001">', esc(it.title || "—"), "</td>",
        '<td style="padding:5px 8px;border-bottom:1px solid #0001;color:#888">', esc(it.name), "</td>",
        '<td style="padding:5px 8px;border-bottom:1px solid #0001;text-align:right">', esc(it.size_h), "</td>",
        '<td style="padding:5px 8px;border-bottom:1px solid #0001;color:#888">',
          esc((it.aliases || []).join("、")), "</td>",
      "</tr>");
    });
    h.push("</table>");
    if (rows.length > 500) h.push('<div class="muted">只显示前 500 条。</div>');
    el.innerHTML = h.join("");
  };

  window.gf_groups = function(){
    api("/admin/api/plugins/gamefiles/groups").then(function(d){
      var sel = document.getElementById("gf-gid");
      if (!d || !d.ok) { sel.innerHTML = "<option>读取失败</option>"; return; }
      var gs = d.groups || [];
      if (!gs.length) {
        sel.innerHTML = "<option value=''>还没有群扫过</option>";
        document.getElementById("gf-list").innerHTML =
          '<div class="muted">还没有索引。去群里发一次「扫游戏库」，或者填群号扫描。</div>';
        return;
      }
      var keep = sel.value;
      sel.innerHTML = gs.map(function(g){
        var nm = g.name ? (g.name + " (" + g.gid + ")") : ("群 " + g.gid);
        return '<option value="' + esc(g.gid) + '">' + esc(nm) +
               " — " + g.count + " 个</option>";
      }).join("");
      if (keep && gs.some(function(g){ return String(g.gid) === String(keep); })) sel.value = keep;
      gf_load();
    }).catch(function(e){
      document.getElementById("gf-gid").innerHTML = "<option>请求出错</option>";
    });
  };

  window.gf_scan = function(force){
    var gid = (document.getElementById("gf-gid") || {}).value;
    if (!gid) { alert("先选一个群"); return; }
    if (!confirm((force ? "重扫并让 AI 重新整理" : "重新扫描") + "群 " + gid + " 的文件？")) return;
    document.getElementById("gf-stat").textContent = "扫描中，文件多的话要等一会儿…";
    api("/admin/api/plugins/gamefiles/scan", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({gid: gid, force: !!force})
    }).then(function(d){
      if (!d || !d.ok) { document.getElementById("gf-stat").textContent = "失败：" + ((d&&d.error)||"?"); return; }
      gf_groups();
    }).catch(function(e){
      document.getElementById("gf-stat").textContent = "请求出错：" + e;
    });
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", gf_groups);
  } else {
    setTimeout(gf_groups, 30);
  }
})();
</script>
""")

    ctx.register_config("游戏库", [
        ["gf_scan_folders", "只扫这些名字的文件夹（逗号分隔，留空=只扫根目录）", "text"],
        ["gf_ai_enabled", "用 AI 整理文件名", "bool"],
        ["gf_ai_batch", "AI 每批处理几个文件（5-80）", "number"],
        ["gf_ai_max_calls", "一次扫描最多调几次 AI（0=不调）", "number"],
        ["gf_ask_words", "问句触发词（逗号分隔）", "text"],
        ["gf_reply_limit", "一次最多回几个结果", "number"],
        ["gf_auto_link", "回复里带上文件下载链接", "bool"],
        ["gf_collect_shares", "自动收集群里的「QQ文件闪传」链接", "bool"],
        ["gf_auto_scan_hours", "每隔几小时自动扫一次（0=不自动扫）", "number"],
        ["gf_send_mode", "回复方式：link=发链接 / file=发文件 / auto=小的发文件", "text"],
        ["gf_file_max_mb", "超过多少 MB 就改发链接（**硬上限 200MB**，填再大也不越过）", "number"],
    ])

    ctx.log("游戏库插件已就绪")

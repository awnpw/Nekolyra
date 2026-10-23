# -*- coding: utf-8 -*-
"""互动式学习：她遇到不懂的词会主动问，有人回答就记住，之后能用上。

为什么这么做（2026-10-21）：统计式新词发现对语料量要求太高 —— 实测 906 条真实消息
（1.3 万字）只挖出「游戏」「领取」这类普通词，零黑话。改用互动：
以「她主动发问」换取有人在下面解释，几乎不耗算力，行为本身也是差异化的。

学到的词最终落进主程序的 kb 表 —— 那是她回复时检索的知识库，
所以写进去之后她自己就会用了，不需要改主程序。
"""
import json
import re
import time

QUOTE_RE = re.compile(r"[「『“\"'《]([\u4e00-\u9fa5A-Za-z0-9_\-·]{1,12})[」』”\"'》]")
ACRONYM_RE = re.compile(r"(?<![A-Za-z])([A-Z]{2,6})(?![A-Za-z])")
CJK_RE = re.compile(r"[\u4e00-\u9fa5]+")

# 明显不该学的词（语气词、代词、常见动词）
STOP = set("""
的 是 了 我 你 他 她 它 们 这 那 有 不 在 就 也 都 和 与 吗 呢 吧 啊 呀 哦 嗯
一个 我们 你们 他们 什么 怎么 这个 那个 可以 因为 所以 但是 然后 现在 时候
今天 明天 昨天 知道 觉得 感觉 应该 可能 真的 不是 没有 就是 还是 这么 那么
""".split())

# 提问冷却：每群每天最多问几次、同一个词最多问几次
MAX_ASK_PER_DAY = 2
CAND_MIN_HITS = 3          # 同一候选见到 3 次才问
PENDING_TTL = 15 * 60      # 问出去之后 15 分钟内等解释


def _today():
    return time.strftime("%Y-%m-%d")


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def setup(ctx):
    db = ctx.db

    def _init():
        ctx.db_exec(
            "CREATE TABLE IF NOT EXISTS lexicon ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " group_id INTEGER NOT NULL,"
            " term TEXT NOT NULL,"
            " meaning TEXT DEFAULT '',"
            " status TEXT DEFAULT 'candidate',"
            " hits INTEGER DEFAULT 0,"
            " asked_at TEXT DEFAULT '',"
            " learned_at TEXT DEFAULT '',"
            " teacher_id INTEGER DEFAULT 0,"
            " teacher_name TEXT DEFAULT '',"
            " created_at TEXT DEFAULT '')")
        ctx.db_exec("CREATE UNIQUE INDEX IF NOT EXISTS idx_lexicon_gid_term ON lexicon(group_id, term)")
        ctx.db_exec("CREATE INDEX IF NOT EXISTS idx_lexicon_status ON lexicon(group_id, status)")

    try:
        _init()
    except Exception as e:
        ctx.warn("建表失败：%s: %s" % (type(e).__name__, e))

    # ---------- 候选收集 ----------
    def _known(term, gid):
        """已经学会的词（learned）或者知识库里已有同名词。"""
        try:
            row = ctx.db_query("SELECT 1 FROM lexicon WHERE group_id=? AND term=? AND status='learned' LIMIT 1",
                               (gid, term))
            if row:
                return True
            row = ctx.db_query("SELECT 1 FROM kb WHERE (group_id=? OR group_id=0) AND question LIKE ? LIMIT 1",
                               (gid, "%" + term + "%"))
            return bool(row)
        except Exception:
            return False

    def _add_hit(gid, term):
        try:
            ctx.db_exec("INSERT INTO lexicon(group_id, term, status, hits, created_at) VALUES(?,?,?,1,?) "
                        "ON CONFLICT(group_id, term) DO UPDATE SET hits=hits+1",
                        (gid, term, "candidate", _now()))
        except Exception as e:
            ctx.warn("记候选失败 %s：%s" % (term, type(e).__name__))

    def _candidates(text, gid):
        """从一条消息里找值得学的词。"""
        out = []
        for m in QUOTE_RE.finditer(text):
            w = m.group(1).strip()
            if 1 < len(w) <= 12 and w not in STOP:
                out.append(w)
        for m in ACRONYM_RE.finditer(text):
            out.append(m.group(1))
        return [w for w in dict.fromkeys(out) if not _known(w, gid)]

    # ---------- 提问 ----------
    def _max_ask():
        try:
            return max(0, int(ctx.cfg("lx_max_ask_per_day", MAX_ASK_PER_DAY) or 0))
        except Exception:
            return MAX_ASK_PER_DAY

    def _min_hits():
        try:
            return max(1, int(ctx.cfg("lx_cand_min_hits", CAND_MIN_HITS) or CAND_MIN_HITS))
        except Exception:
            return CAND_MIN_HITS

    def _enabled():
        try:
            return bool(ctx.cfg("lx_enabled", True))
        except Exception:
            return True

    def _ask_quota(gid):
        """今天还剩几次提问机会。"""
        key = "ask:%s:%s" % (gid, _today())
        used = int(ctx.kv_get(key, 0) or 0)
        return max(0, _max_ask() - used)

    def _spend_quota(gid):
        key = "ask:%s:%s" % (gid, _today())
        used = int(ctx.kv_get(key, 0) or 0)
        ctx.kv_set(key, used + 1)

    async def _maybe_ask(gid):
        """挑一个候选，主动问一句。"""
        if _ask_quota(gid) <= 0:
            return
        try:
            rows = ctx.db_query(
                "SELECT term, hits FROM lexicon WHERE group_id=? AND status='candidate' AND hits>=? "
                "ORDER BY hits DESC LIMIT 5", (gid, _min_hits()))
        except Exception:
            return
        if not rows:
            return
        term = rows[0]["term"]
        try:
            ctx.db_exec("UPDATE lexicon SET status='asking', asked_at=? WHERE group_id=? AND term=?",
                        (_now(), gid, term))
        except Exception:
            return
        _spend_quota(gid)
        ctx.kv_set("pending:%s" % gid, json.dumps(
            {"term": term, "ts": int(time.time())}, ensure_ascii=False))
        await ctx.send_group(gid, "「%s」这个词我听不懂，是什么意思呀？" % term)
        ctx.log("主动提问：%s（群 %s）" % (term, gid))

    # ---------- 学习 ----------
    async def _learn(gid, term, text, uid, nick):
        meaning = ""
        try:
            meaning = await ctx.ai(
                "有人解释「%s」这个词。请把它的含义压缩成一句不超过 20 字的中文释义，只输出释义本身。\n"
                "原话：%s" % (term, text[:200]), timeout=8.0)
        except Exception:
            meaning = ""
        meaning = (meaning or "").strip().replace("\n", " ")[:60] or text.strip()[:60]
        try:
            ctx.db_exec(
                "UPDATE lexicon SET meaning=?, status='learned', learned_at=?, teacher_id=?, teacher_name=? "
                "WHERE group_id=? AND term=?", (meaning, _now(), int(uid or 0), nick or "", gid, term))
            # 写进主程序知识库：她之后回复时会检索到
            ctx.db_exec(
                "INSERT INTO kb(group_id, question, answer, tags, author_id, author_name, hits, created_at) "
                "VALUES(?,?,?,?,?,?,0,?)",
                (gid, term, meaning, "学来的,词条", int(uid or 0), nick or "", _now()))
        except Exception as e:
            ctx.warn("写入失败 %s：%s: %s" % (term, type(e).__name__, e))
            return
        ctx.kv_set("pending:%s" % gid, "")
        await ctx.send_group(gid, "原来是这个意思，我记下了。")
        ctx.log("学到词条：%s = %s（群 %s，来自 %s）" % (term, meaning, gid, nick))

    # ---------- 消息钩子 ----------
    @ctx.on_message(timeout=12.0)
    async def _on_msg(event, text):
        try:
            gid = int(getattr(event, "group_id", 0) or 0)
        except Exception:
            gid = 0
        if gid <= 0 or not text:
            return
        raw = str(text).strip()
        if not raw or len(raw) > 200 or not _enabled():
            return
        # 节流：同一个群 30 秒内只做一次检测，避免每条消息都查库
        key = "tick:%s" % gid
        now = int(time.time())
        if now - int(ctx.kv_get(key, 0) or 0) < 30:
            return
        ctx.kv_set(key, now)
        # 1) 有等待解释的词 → 判断这条是不是解释
        pend = ctx.kv_get("pending:%s" % gid, "") or ""
        if pend:
            try:
                info = json.loads(pend)
            except Exception:
                info = {}
            term = info.get("term") or ""
            age = int(time.time()) - int(info.get("ts") or 0)
            if term and age < PENDING_TTL:
                if term in raw and len(raw) >= 4:
                    nick = ""
                    try:
                        nick = await ctx.nick(gid, getattr(event, "user_id", 0))
                    except Exception:
                        pass
                    await _learn(gid, term, raw, getattr(event, "user_id", 0), nick)
                    return
            elif age >= PENDING_TTL:
                # 超时没解释：退回候选，以后还能再问
                try:
                    ctx.db_exec("UPDATE lexicon SET status='candidate' WHERE group_id=? AND term=?", (gid, term))
                except Exception:
                    pass
                ctx.kv_set("pending:%s" % gid, "")
        # 2) 收集候选
        for w in _candidates(raw, gid):
            _add_hit(gid, w)
        # 3) 有机会就问一句
        await _maybe_ask(gid)

    # ---------- 命令 ----------
    @ctx.command("词典", help="看本群她学到的词")
    async def _cmd_list(event, cmd):
        gid = int(getattr(event, "group_id", 0) or 0)
        try:
            rows = ctx.db_query(
                "SELECT term, meaning FROM lexicon WHERE group_id=? AND status='learned' "
                "ORDER BY learned_at DESC LIMIT 20", (gid,))
        except Exception:
            rows = []
        if not rows:
            await ctx.send_group(gid, "这边我还没学到什么词。")
            return
        lines = ["我在这边学到的："]
        for r in rows:
            lines.append("· %s：%s" % (r["term"], (r["meaning"] or "")[:24]))
        await ctx.send_group(gid, "\n".join(lines))

    @ctx.command("教", help="教她一个词：教 某某 是 什么什么意思")
    async def _cmd_teach(event, cmd):
        gid = int(getattr(event, "group_id", 0) or 0)
        body = (cmd or "").strip()
        m = re.match(r"^(.{1,12}?)\s*(?:是|＝|=|：|:)\s*(.{1,80})$", body)
        if not m:
            await ctx.send_group(gid, "这样教：教 某某 是 什么意思")
            return
        term, meaning = m.group(1).strip(), m.group(2).strip()
        uid = getattr(event, "user_id", 0)
        nick = ""
        try:
            nick = await ctx.nick(gid, uid)
        except Exception:
            pass
        try:
            ctx.db_exec(
                "INSERT INTO lexicon(group_id, term, meaning, status, hits, learned_at, teacher_id, "
                "teacher_name, created_at) VALUES(?,?,?,'learned',1,?,?,?,?) "
                "ON CONFLICT(group_id, term) DO UPDATE SET meaning=excluded.meaning, status='learned', "
                "learned_at=excluded.learned_at, teacher_name=excluded.teacher_name",
                (gid, term, meaning, _now(), int(uid or 0), nick, _now()))
            ctx.db_exec(
                "INSERT INTO kb(group_id, question, answer, tags, author_id, author_name, hits, created_at) "
                "VALUES(?,?,?,?,?,?,0,?)",
                (gid, term, meaning, "学来的,词条", int(uid or 0), nick, _now()))
        except Exception as e:
            await ctx.send_group(gid, "没记住（%s）" % type(e).__name__)
            return
        await ctx.send_group(gid, "好，「%s」我记下了。" % term)

    @ctx.command("忘掉", help="让她忘掉某个词（超管）")
    async def _cmd_forget(event, cmd):
        gid = int(getattr(event, "group_id", 0) or 0)
        if not ctx.is_super(getattr(event, "user_id", 0)):
            await ctx.send_group(gid, "这个要让管理员来。")
            return
        term = (cmd or "").strip()
        if not term:
            await ctx.send_group(gid, "忘掉 词")
            return
        try:
            ctx.db_exec("DELETE FROM lexicon WHERE group_id=? AND term=?", (gid, term))
            ctx.db_exec("DELETE FROM kb WHERE group_id=? AND question=?", (gid, term))
        except Exception:
            pass
        await ctx.send_group(gid, "好，忘了「%s」。" % term)

    # ---------- 管理接口 ----------
    def _api_list(request, body):
        q = getattr(request, "query_params", {}) or {}
        gid = q.get("gid") or q.get("group_id") or ""
        status = q.get("status") or ""
        sql = "SELECT group_id, term, meaning, status, hits, learned_at, teacher_name FROM lexicon WHERE 1=1"
        args = []
        if str(gid).strip():
            sql += " AND group_id=?"
            args.append(int(gid))
        if str(status).strip():
            sql += " AND status=?"
            args.append(str(status))
        sql += " ORDER BY hits DESC LIMIT 200"
        try:
            rows = ctx.db_query(sql, tuple(args))
        except Exception:
            rows = []
        data = [{"group_id": r["group_id"], "term": r["term"], "meaning": r["meaning"],
                 "status": r["status"], "hits": r["hits"], "learned_at": r["learned_at"],
                 "teacher": r["teacher_name"]} for r in rows]
        return {"ok": True, "count": len(data), "items": data}

    ctx.register_api("/admin/api/plugins/lexicon/list", _api_list, methods=("GET",))

    def _api_forget(request, body):
        b = body or {}
        q = getattr(request, "query_params", {}) or {}
        gid = b.get("gid") or b.get("group_id") or q.get("gid") or 0
        term = b.get("term") or q.get("term") or ""
        try:
            ctx.db_exec("DELETE FROM lexicon WHERE group_id=? AND term=?", (int(gid), str(term)))
            ctx.db_exec("DELETE FROM kb WHERE group_id=? AND question=?", (int(gid), str(term)))
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    ctx.register_api("/admin/api/plugins/lexicon/forget", _api_forget, methods=("POST",))

    async def _api_ask(request, body):
        """调试/手动触发：往指定群问一个候选词。不传 term 就挑命中数最高的。"""
        b = body or {}
        q = getattr(request, "query_params", {}) or {}
        gid = int(b.get("gid") or b.get("group_id") or q.get("gid") or q.get("group_id") or 0)
        term = str(b.get("term") or q.get("term") or "")
        if not gid:
            return {"ok": False, "error": "需要 gid"}
        if term:
            try:
                ctx.db_exec("INSERT INTO lexicon(group_id, term, status, hits, created_at) VALUES(?,?,'candidate',?,?) "
                            "ON CONFLICT(group_id, term) DO UPDATE SET status='candidate', hits=MAX(hits, ?)",
                            (gid, term, CAND_MIN_HITS, _now(), CAND_MIN_HITS))
            except Exception as e:
                return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        before = int(ctx.kv_get("ask:%s:%s" % (gid, _today()), 0) or 0)
        ctx.kv_set("ask:%s:%s" % (gid, _today()), 0)     # 手动触发不受限额影响
        await _maybe_ask(gid)
        ctx.kv_set("ask:%s:%s" % (gid, _today()), before)
        pend = ctx.kv_get("pending:%s" % gid, "") or ""
        return {"ok": True, "gid": gid, "pending": pend}

    ctx.register_api("/admin/api/plugins/lexicon/ask", _api_ask, methods=("POST",), timeout=60)

    async def _api_learn(request, body):
        """调试：模拟"有人解释了 pending 里的词"，走完整学习链路。"""
        b = body or {}
        gid = int(b.get("gid") or 0)
        term = str(b.get("term") or "")
        text = str(b.get("text") or "")
        if not (gid and term and text):
            return {"ok": False, "error": "需要 gid / term / text"}
        await _learn(gid, term, text, int(b.get("uid") or 0), str(b.get("nick") or "测试"))
        return {"ok": True, "gid": gid, "term": term}

    ctx.register_api("/admin/api/plugins/lexicon/learn", _api_learn, methods=("POST",), timeout=120)

    def _api_stats(request, body):
        q = getattr(request, "query_params", {}) or {}
        gid = q.get("gid") or q.get("group_id") or 0
        out = {"ok": True}
        try:
            if gid:
                out["rows"] = ctx.db_query(
                    "SELECT status, COUNT(*) AS n FROM lexicon WHERE group_id=? GROUP BY status", (int(gid),))
                out["pending"] = ctx.kv_get("pending:%s" % int(gid), "")
                out["quota_used"] = int(ctx.kv_get("ask:%s:%s" % (int(gid), _today()), 0) or 0)
            else:
                out["rows"] = ctx.db_query("SELECT status, COUNT(*) AS n FROM lexicon GROUP BY status")
        except Exception as e:
            out["error"] = "%s: %s" % (type(e).__name__, e)
        return out

    ctx.register_api("/admin/api/plugins/lexicon/stats", _api_stats, methods=("GET",))

    ctx.register_config("互动学习", [
        ["lx_enabled", "启用", "bool"],
        ["lx_max_ask_per_day", "每群每天最多问几次", "int"],
        ["lx_cand_min_hits", "同一候选见几次才问", "int"],
    ])

    ctx.log("互动学习已就绪（提问上限 %d 次/群/天，候选阈值 %d 次）" % (MAX_ASK_PER_DAY, CAND_MIN_HITS))

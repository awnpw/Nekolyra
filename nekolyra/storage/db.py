# -*- coding: utf-8 -*-
r"""SQLite 存储层。

从 bot.py 里整块搬出来的 —— 只是搬家，逻辑一行没改。

跟主程序的耦合只有 5 个名字（cfg_bool / log / log_startup / threading /
timedelta），其中 3 个是主程序的函数，通过 configure() 注入：

    from nekolyra.storage.db import Database, configure
    configure(log=log, cfg_bool=cfg_bool, log_startup=log_startup)
    DB = Database(path, ...)

**不 import bot** —— 那样会循环导入（bot 要 import 本模块）。
没注入之前，log 是空操作、cfg_bool 返回默认值，不会崩。
"""

import sqlite3
import threading
from datetime import date, datetime, timedelta

__all__ = ["Database", "configure"]

# 注入进来的主程序函数（默认是安全的空实现）
_log = None
_cfg_bool = None
_log_startup = None


def configure(log=None, cfg_bool=None, log_startup=None):
    """由主程序在创建 Database 之前调用一次。"""
    global _log, _cfg_bool, _log_startup
    if log is not None:
        _log = log
    if cfg_bool is not None:
        _cfg_bool = cfg_bool
    if log_startup is not None:
        _log_startup = log_startup


def _L(level, tag, msg):
    """内部日志。没注入就什么都不做。"""
    if _log is not None:
        try:
            _log(level, tag, msg)
        except Exception:
            pass


def _CB(key, default=False):
    """内部读布尔配置。没注入就返回默认值。"""
    if _cfg_bool is not None:
        try:
            return _cfg_bool(key, default)
        except Exception:
            return default
    return default


def _LS(msg):
    if _log_startup is not None:
        try:
            _log_startup(msg)
        except Exception:
            pass


class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init()

    def _conn(self):
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA busy_timeout=5000")
        except Exception:
            pass
        return c

    def checkpoint(self):
        try:
            with self._lock:
                with self._conn() as c:
                    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as e:
            _LS(f"数据库 checkpoint 失败: {type(e).__name__}: {e}")

    # ---- 音色偏好（私聊按用户、群按群）----
    def voice_pref_get(self, scope, key):
        try:
            with self._conn() as c:
                row = c.execute("SELECT voice FROM voice_pref WHERE scope=? AND key=?",
                                (str(scope), str(key))).fetchone()
            return (row["voice"] if row else "") or ""
        except Exception:
            return ""

    def voice_pref_set(self, scope, key, voice):
        import time as _t
        with self._conn() as c:
            c.execute("INSERT INTO voice_pref(scope, key, voice, updated_at) VALUES(?,?,?,?) "
                      "ON CONFLICT(scope, key) DO UPDATE SET voice=excluded.voice, "
                      "updated_at=excluded.updated_at",
                      (str(scope), str(key), str(voice), _t.strftime("%Y-%m-%dT%H:%M:%S")))

    def voice_pref_del(self, scope, key):
        with self._conn() as c:
            c.execute("DELETE FROM voice_pref WHERE scope=? AND key=?", (str(scope), str(key)))

    def voice_pref_all(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT scope, key, voice, updated_at FROM voice_pref ORDER BY updated_at DESC")]

    def close(self):
        self.checkpoint()

    def _init(self):
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS blacklist(
                user_id INTEGER NOT NULL, group_id INTEGER NOT NULL,
                nickname TEXT, reason TEXT, added_at TEXT,
                PRIMARY KEY(user_id, group_id))""")
            c.execute("""CREATE TABLE IF NOT EXISTS memory(
                id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER NOT NULL,
                content TEXT NOT NULL, category TEXT DEFAULT '其他',
                importance INTEGER DEFAULT 3, created_at TEXT NOT NULL)""")
            # 新增：用户级记忆。scope='user' 时 user_id 是归属人；
            # scope='group'（或 user_id=0）时是原来的群级记忆。
            # 老库没有这两列，用 ALTER 补上，不重建表（不丢数据）。
            _mem_cols = [r[1] for r in c.execute("PRAGMA table_info(memory)").fetchall()]
            if "user_id" not in _mem_cols:
                c.execute("ALTER TABLE memory ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")
                _L("info", "数据库", "memory 表新增 user_id 列")
            if "scope" not in _mem_cols:
                c.execute("ALTER TABLE memory ADD COLUMN scope TEXT NOT NULL DEFAULT 'group'")
                _L("info", "数据库", "memory 表新增 scope 列")
            c.execute("CREATE INDEX IF NOT EXISTS idx_mem ON memory(group_id, id DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_mem_user ON memory(group_id, user_id, id DESC)")
            # 聊天记录：群聊和私聊都存，供管理界面按群/按人查看
            # 每个私聊/每个群单独指定的音色；没有记录就回退全局 voice_name
            c.execute("""CREATE TABLE IF NOT EXISTS voice_pref(
                scope TEXT NOT NULL, key TEXT NOT NULL, voice TEXT NOT NULL,
                updated_at TEXT, PRIMARY KEY(scope, key))""")
            c.execute("""CREATE TABLE IF NOT EXISTS chat_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL DEFAULT 0,
                user_id INTEGER NOT NULL DEFAULT 0,
                nickname TEXT,
                text TEXT NOT NULL,
                is_bot INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL)""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_log_g ON chat_log(group_id, id DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_log_u ON chat_log(user_id, id DESC)")
            # 表情库：收到的图片/表情。文件按 hash 存 STICKER_DIR，这里只记元数据。
            c.execute("""CREATE TABLE IF NOT EXISTS stickers(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hash TEXT NOT NULL UNIQUE,
                ext TEXT NOT NULL DEFAULT 'jpg',
                size INTEGER NOT NULL DEFAULT 0,
                group_id INTEGER NOT NULL DEFAULT 0,
                user_id INTEGER NOT NULL DEFAULT 0,
                nickname TEXT DEFAULT '',
                kind TEXT NOT NULL DEFAULT 'image',
                note TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                use_count INTEGER NOT NULL DEFAULT 0,
                last_used TEXT,
                created_at TEXT NOT NULL)""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_st_kind ON stickers(kind, id DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_st_used ON stickers(last_used)")
            c.execute("""CREATE TABLE IF NOT EXISTS points(
                user_id INTEGER NOT NULL, group_id INTEGER NOT NULL,
                points INTEGER DEFAULT 0, sign_count INTEGER DEFAULT 0,
                streak INTEGER DEFAULT 0, best_streak INTEGER DEFAULT 0,
                last_sign_date TEXT, nickname TEXT,
                PRIMARY KEY (user_id, group_id))""")
            c.execute("""CREATE TABLE IF NOT EXISTS activity(
                user_id INTEGER NOT NULL, group_id INTEGER NOT NULL,
                last_active TEXT, msg_count INTEGER DEFAULT 0, nickname TEXT,
                PRIMARY KEY (user_id, group_id))""")
            c.execute("""CREATE TABLE IF NOT EXISTS daily_activity(
                user_id INTEGER NOT NULL, group_id INTEGER NOT NULL,
                date TEXT NOT NULL, msg_count INTEGER DEFAULT 0, nickname TEXT,
                PRIMARY KEY (user_id, group_id, date))""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_daily ON daily_activity(group_id, date)")
            # 知识库：group_id = 0 表示"全局知识"（所有群都能命中）
            c.execute("""CREATE TABLE IF NOT EXISTS kb(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL DEFAULT 0,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                tags TEXT DEFAULT '',
                author_id INTEGER DEFAULT 0,
                author_name TEXT DEFAULT '',
                hits INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                folder TEXT DEFAULT '')""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_kb ON kb(group_id, id DESC)")
            # 空文件夹也要能被记住，所以单独一张表存文件夹路径
            c.execute("""CREATE TABLE IF NOT EXISTS kb_folders(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL DEFAULT 0,
                path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(group_id, path))""")
            # 老库补 folder 列（可重复执行）
            try:
                kb_cols = [r[1] for r in c.execute("PRAGMA table_info(kb)").fetchall()]
                if kb_cols and "folder" not in kb_cols:
                    _L("warn", "数据库", "检测到旧 kb 表，正在补 folder 列...")
                    c.execute("ALTER TABLE kb ADD COLUMN folder TEXT DEFAULT ''")
                c.execute("CREATE INDEX IF NOT EXISTS idx_kb_folder ON kb(group_id, folder)")
            except Exception as e:
                _L("warn", "数据库", f"检查 kb 表出错：{e}")
            c.commit()

    def bl_add(self, u, g, n="", r="主动退群"):
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO blacklist VALUES(?,?,?,?,?)",
                      (u, g, n, r, datetime.now().isoformat()))
            c.commit()

    def bl_check(self, u, g):
        with self._conn() as c:
            return c.execute("SELECT 1 FROM blacklist WHERE user_id=? AND group_id=?",
                            (u, g)).fetchone() is not None

    def bl_remove(self, u, g):
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM blacklist WHERE user_id=? AND group_id=?", (u, g))
            c.commit()

    def bl_list_group(self, g):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM blacklist WHERE group_id=? ORDER BY added_at DESC", (g,))]

    def bl_list_all(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM blacklist ORDER BY added_at DESC")]

    def bl_count(self):
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM blacklist").fetchone()[0]

    def mem_add(self, g, content, cat="其他", imp=3, uid=0, uname="", scope="group"):
        """写一条记忆。

        scope="group" -> 群级记忆（谁能看到都行）
        scope="user"  -> 用户级记忆，按 (群, 用户) 隔离；私聊时群固定为 0
        """
        scope = "user" if str(scope) == "user" and int(uid or 0) else "group"
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO memory(group_id,user_id,scope,content,category,"
                      "importance,created_at) VALUES(?,?,?,?,?,?,?)",
                      (int(g), int(uid or 0), scope, content, cat, imp,
                       datetime.now().isoformat()))
            c.commit()

    def mem_recent(self, g, limit=3):
        """群级记忆（不含用户级）。"""
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT content,category,importance,created_at FROM memory "
                "WHERE group_id=? AND scope='group' ORDER BY id DESC LIMIT ?",
                (g, limit))]

    def mem_recent_user(self, g, uid, limit=3):
        """某个用户在某个群里的专属记忆（按群隔离）。"""
        if not uid:
            return []
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT content,category,importance,created_at FROM memory "
                "WHERE group_id=? AND user_id=? AND scope='user' "
                "ORDER BY importance DESC, id DESC LIMIT ?",
                (g, int(uid), limit))]

    # ---------------- 聊天记录 ----------------
    def log_add(self, g, uid, nick, text, is_bot=False):
        if not _CB("chatlog_enabled", True):
            return
        txt = str(text or "").strip()
        if not txt:
            return
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO chat_log(group_id,user_id,nickname,text,is_bot,"
                      "created_at) VALUES(?,?,?,?,?,?)",
                      (int(g or 0), int(uid or 0), str(nick or ""), txt[:2000],
                       1 if is_bot else 0, datetime.now().isoformat()))
            c.commit()

    def log_list(self, g=None, uid=None, limit=200, keyword="", before_id=0):
        """按群或按人查聊天记录。g/uid 传 None 表示不限制。"""
        sql = ["SELECT id,group_id,user_id,nickname,text,is_bot,created_at FROM chat_log WHERE 1=1"]
        args = []
        if g is not None:
            sql.append("AND group_id=?")
            args.append(int(g))
        if uid is not None:
            sql.append("AND user_id=?")
            args.append(int(uid))
        if keyword:
            sql.append("AND text LIKE ?")
            args.append(f"%{keyword}%")
        if before_id:
            sql.append("AND id<?")
            args.append(int(before_id))
        sql.append("ORDER BY id DESC LIMIT ?")
        args.append(int(limit))
        with self._conn() as c:
            return [dict(r) for r in c.execute(" ".join(sql), args)]

    def log_count(self, g=None, uid=None):
        sql = ["SELECT COUNT(*) FROM chat_log WHERE 1=1"]
        args = []
        if g is not None:
            sql.append("AND group_id=?")
            args.append(int(g))
        if uid is not None:
            sql.append("AND user_id=?")
            args.append(int(uid))
        with self._conn() as c:
            return c.execute(" ".join(sql), args).fetchone()[0]

    def log_groups(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT group_id, COUNT(*) as cnt, MAX(created_at) as last "
                "FROM chat_log GROUP BY group_id ORDER BY MAX(id) DESC")]

    def log_users(self, g=None, limit=300):
        sql = ("SELECT user_id, nickname, COUNT(*) as cnt, MAX(created_at) as last "
               "FROM chat_log WHERE is_bot=0")
        args = []
        if g is not None:
            sql += " AND group_id=?"
            args.append(int(g))
        sql += " GROUP BY user_id ORDER BY MAX(id) DESC LIMIT ?"
        args.append(int(limit))
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, args)]

    def log_clear(self, g=None, uid=None):
        sql = ["DELETE FROM chat_log WHERE 1=1"]
        args = []
        if g is not None:
            sql.append("AND group_id=?")
            args.append(int(g))
        if uid is not None:
            sql.append("AND user_id=?")
            args.append(int(uid))
        with self._lock, self._conn() as c:
            cur = c.execute(" ".join(sql), args)
            c.commit()
            return cur.rowcount or 0

    def log_prune(self, keep_days=30):
        """删掉太老的记录，防止库无限膨胀。"""
        try:
            # 文件头是 from datetime import datetime, date, timedelta ——
            # datetime 是**类**不是模块，datetime.timedelta 根本不存在。
            # 原来这里每次进 try 就抛 AttributeError，被
            # `except Exception: return 0` 吞掉，函数永远返回 0：
            # 启动日志一直打"共 N 条，无需清理"，实际一行没删，
            # chat_log 表无限膨胀。文件里另外三处（daily_backup_task /
            # act_recent / backup_db）用的都是正确的 timedelta(days=...)。
            cutoff = (datetime.now() - timedelta(days=int(keep_days))).isoformat()
        except Exception as e:
            # 别再静默 return 0 了 —— 就是它让上面那个 bug 藏了这么久。
            _L("warn", "聊天记录",
                f"计算保留日期失败: {type(e).__name__}: {e}")
            return 0
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM chat_log WHERE created_at<?", (cutoff,))
            c.commit()
            return cur.rowcount or 0

    # ---------------- 用户画像 ----------------
    def user_facts(self, g, uid):
        """汇总 bot 已经掌握的关于这个人的事实（用于注入提示词）。"""
        out = {}
        with self._conn() as c:
            if g:
                r = c.execute("SELECT nickname,msg_count,last_active FROM activity "
                              "WHERE user_id=? AND group_id=?", (int(uid), int(g))).fetchone()
                if r:
                    out["nickname"], out["msg_count"], out["last_active"] = r[0], r[1], r[2]
                p = c.execute("SELECT points,sign_count,streak FROM points "
                              "WHERE user_id=? AND group_id=?", (int(uid), int(g))).fetchone()
                if p:
                    out["points"], out["sign_count"], out["streak"] = p[0], p[1], p[2]
                d = c.execute("SELECT COUNT(*), MIN(date) FROM daily_activity "
                              "WHERE user_id=? AND group_id=?", (int(uid), int(g))).fetchone()
                if d and d[0]:
                    out["active_days"], out["first_date"] = d[0], d[1]
            # 跨群总发言（说明是老熟人）
            t = c.execute("SELECT SUM(msg_count) FROM activity WHERE user_id=?",
                          (int(uid),)).fetchone()
            if t and t[0]:
                out["total_msgs"] = t[0]
            gn = c.execute("SELECT COUNT(DISTINCT group_id) FROM activity WHERE user_id=?",
                           (int(uid),)).fetchone()
            if gn and gn[0]:
                out["group_count"] = gn[0]
            # 和这个人聊过多少次
            lc = c.execute("SELECT COUNT(*) FROM chat_log WHERE user_id=? AND is_bot=1",
                           (int(uid),)).fetchone()
            if lc and lc[0]:
                out["replied"] = lc[0]
        return out

    def mem_count(self, g=None):
        with self._conn() as c:
            if g is None:
                return c.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
            return c.execute("SELECT COUNT(*) FROM memory WHERE group_id=?", (g,)).fetchone()[0]

    def mem_list_group(self, g, limit=100):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT id,content,category,importance,created_at,user_id,scope "
                "FROM memory WHERE group_id=? ORDER BY id DESC LIMIT ?", (g, limit))]

    def mem_find_similar(self, gid, uid, scope, category, prefix, min_prefix=6):
        """找同一归属、同一类别、内容前缀相近的已有记忆（用来替换而不是堆叠）。

        前缀取开头的字，比整句比更稳：AI 每次措辞都会变，但"偏好语音"这类
        开头是稳定的。
        """
        pfx = str(prefix or "")[:min_prefix]
        if not pfx:
            return None
        try:
            with self._conn() as c:
                row = c.execute(
                    "SELECT id FROM memory WHERE group_id=? AND user_id=? AND scope=? "
                    "AND category=? AND content LIKE ? ORDER BY id DESC LIMIT 1",
                    (int(gid), int(uid), str(scope), str(category), pfx + "%")).fetchone()
            return row["id"] if row else None
        except Exception:
            return None

    def mem_update_one(self, mid, content, importance=None):
        with self._lock, self._conn() as c:
            if importance is None:
                c.execute("UPDATE memory SET content=? WHERE id=?", (str(content), int(mid)))
            else:
                c.execute("UPDATE memory SET content=?, importance=? WHERE id=?",
                          (str(content), int(importance), int(mid)))
            c.commit()

    def mem_clear_group(self, g):
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM memory WHERE group_id=?", (g,))
            c.commit()

    def mem_clear_user(self, g, uid):
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM memory WHERE group_id=? AND user_id=? AND scope='user'",
                      (int(g), int(uid)))
            c.commit()

    def mem_delete_one(self, mid):
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM memory WHERE id=?", (mid,))
            c.commit()

    def mem_users(self):
        """所有有专属记忆的用户，跨群聚合（用于"按人"视图）。"""
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT user_id, COUNT(*) as cnt, COUNT(DISTINCT group_id) as gcnt, "
                "MAX(id) as last_id FROM memory WHERE scope='user' AND user_id>0 "
                "GROUP BY user_id ORDER BY MAX(id) DESC")]

    def mem_list_by_user(self, uid, limit=300):
        """某个人在所有群的记忆（用于"按人"视图）。"""
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT id,group_id,user_id,content,category,importance,created_at,scope "
                "FROM memory WHERE scope='user' AND user_id=? "
                "ORDER BY group_id, importance DESC, id DESC LIMIT ?",
                (int(uid), int(limit)))]

    def mem_clear_user_all(self, uid):
        """删掉某人在所有群的专属记忆（群级记忆不动）。返回删除条数。"""
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM memory WHERE scope='user' AND user_id=?",
                            (int(uid),))
            c.commit()
            return cur.rowcount or 0

    def mem_groups_of_user(self, uid):
        """某人分布在哪些群（删之前给用户看清楚）。"""
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT group_id, COUNT(*) as cnt FROM memory "
                "WHERE scope='user' AND user_id=? GROUP BY group_id ORDER BY group_id",
                (int(uid),))]

    def mem_all_groups(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT group_id, COUNT(*) as cnt, "
                "SUM(CASE WHEN scope='user' THEN 1 ELSE 0 END) as user_cnt "
                "FROM memory GROUP BY group_id ORDER BY MAX(id) DESC")]

    # ---------------- 知识库 ----------------
    def kb_add(self, g, question, answer, tags="", uid=0, uname="", folder=""):
        now = datetime.now().isoformat()
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO kb(group_id,question,answer,tags,author_id,author_name,"
                "hits,created_at,updated_at,folder) VALUES(?,?,?,?,?,?,0,?,?,?)",
                (int(g), question.strip(), answer.strip(), tags.strip(), int(uid),
                 uname, now, now, (folder or "").strip()))
            c.commit()
            return cur.lastrowid

    def kb_update_folder(self, kid, folder):
        with self._lock, self._conn() as c:
            cur = c.execute("UPDATE kb SET folder=?, updated_at=? WHERE id=?",
                            ((folder or "").strip(), datetime.now().isoformat(), int(kid)))
            c.commit()
            return cur.rowcount > 0

    def kb_set_folders_bulk(self, ids, folder):
        now = datetime.now().isoformat()
        n = 0
        with self._lock, self._conn() as c:
            for kid in ids:
                try:
                    n += c.execute("UPDATE kb SET folder=?, updated_at=? WHERE id=?",
                                   ((folder or "").strip(), now, int(kid))).rowcount
                except (TypeError, ValueError):
                    continue
            c.commit()
        return n

    def kb_folder_list(self, g=None):
        """实际被条目使用的文件夹路径 + 显式创建的空文件夹。"""
        with self._conn() as c:
            if g is None:
                used = [r[0] for r in c.execute(
                    "SELECT DISTINCT folder FROM kb WHERE folder IS NOT NULL AND folder<>''")]
                created = [r[0] for r in c.execute("SELECT path FROM kb_folders")]
            else:
                used = [r[0] for r in c.execute(
                    "SELECT DISTINCT folder FROM kb WHERE folder IS NOT NULL AND folder<>'' "
                    "AND group_id IN (0,?)", (int(g),))]
                created = [r[0] for r in c.execute(
                    "SELECT path FROM kb_folders WHERE group_id IN (0,?)", (int(g),))]
        return sorted(set(used) | set(created))

    def kb_folder_create(self, g, path):
        with self._lock, self._conn() as c:
            c.execute("INSERT OR IGNORE INTO kb_folders(group_id,path,created_at) "
                      "VALUES(?,?,?)", (int(g), path.strip(), datetime.now().isoformat()))
            c.commit()

    def kb_folder_delete(self, path, g=None):
        """删除文件夹定义，并把里面的条目移回根目录（不删条目）。"""
        with self._lock, self._conn() as c:
            if g is None:
                c.execute("DELETE FROM kb_folders WHERE path=?", (path,))
                c.execute("UPDATE kb SET folder='' WHERE folder=?", (path,))
            else:
                c.execute("DELETE FROM kb_folders WHERE path=? AND group_id IN (0,?)",
                          (path, int(g)))
                c.execute("UPDATE kb SET folder='' WHERE folder=? AND group_id IN (0,?)",
                          (path, int(g)))
            c.commit()

    def kb_get(self, kid):
        with self._conn() as c:
            row = c.execute("SELECT * FROM kb WHERE id=?", (int(kid),)).fetchone()
            return dict(row) if row else None

    def kb_update(self, kid, question=None, answer=None, tags=None, group_id=None):
        sets, args = [], []
        if question is not None:
            sets.append("question=?"); args.append(question.strip())
        if answer is not None:
            sets.append("answer=?"); args.append(answer.strip())
        if tags is not None:
            sets.append("tags=?"); args.append(tags.strip())
        if group_id is not None:
            sets.append("group_id=?"); args.append(int(group_id))
        if not sets:
            return False
        sets.append("updated_at=?"); args.append(datetime.now().isoformat())
        args.append(int(kid))
        with self._lock, self._conn() as c:
            cur = c.execute(f"UPDATE kb SET {','.join(sets)} WHERE id=?", tuple(args))
            c.commit()
            return cur.rowcount > 0

    def kb_delete(self, kid):
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM kb WHERE id=?", (int(kid),))
            c.commit()
            return cur.rowcount > 0

    # ---------------- 表情库 ----------------
    # ---------------- 聊天管理 ----------------
    def chats_list(self, kind="", kw="", limit=300):
        r"""列出所有有聊天记录的会话。

        群聊：group_id != 0，按群号聚合
        私聊：group_id == 0，按 user_id 聚合
        返回每项带最后一条消息的时间、消息数、最后昵称。
        """
        out = []
        with self._conn() as c:
            if kind != "private":
                for r in c.execute(
                        "SELECT group_id gid, COUNT(*) n, MAX(created_at) last "
                        "FROM chat_log WHERE group_id<>0 GROUP BY group_id "
                        "ORDER BY last DESC LIMIT ?", (limit,)).fetchall():
                    # 昵称要取"最后一条真人消息"的，不能直接取最后一条 ——
                    # 机器人自己的回复也在同一张表里，那样会显示成机器人的名字。
                    nick = ""
                    row = c.execute(
                        "SELECT nickname FROM chat_log WHERE group_id=? "
                        "AND is_bot=0 ORDER BY id DESC LIMIT 1",
                        (r["gid"],)).fetchone()
                    if row and row["nickname"]:
                        nick = row["nickname"]
                    else:
                        row = c.execute(
                            "SELECT nickname FROM chat_log WHERE group_id=? "
                            "ORDER BY id DESC LIMIT 1", (r["gid"],)).fetchone()
                        nick = (row["nickname"] or "") if row else ""
                    out.append({"key": "g:%d" % r["gid"], "kind": "group",
                                "gid": r["gid"], "uid": 0, "name": nick,
                                "count": r["n"], "last": r["last"]})
            if kind != "group":
                # user_id=0 是机器人自己发出去的私聊记录，不是一个"会话"，
                # 列出来会多出一行叫 u:0 的怪东西（实测确实冒出来了）。
                for r in c.execute(
                        "SELECT user_id uid, COUNT(*) n, MAX(created_at) last "
                        "FROM chat_log WHERE group_id=0 AND user_id<>0 "
                        "GROUP BY user_id ORDER BY last DESC LIMIT ?",
                        (limit,)).fetchall():
                    nick = ""
                    row = c.execute(
                        "SELECT nickname FROM chat_log WHERE group_id=0 "
                        "AND user_id=? AND is_bot=0 ORDER BY id DESC LIMIT 1",
                        (r["uid"],)).fetchone()
                    if row and row["nickname"]:
                        nick = row["nickname"]
                    else:
                        row = c.execute(
                            "SELECT nickname FROM chat_log WHERE group_id=0 "
                            "AND user_id=? ORDER BY id DESC LIMIT 1",
                            (r["uid"],)).fetchone()
                        nick = (row["nickname"] or "") if row else ""
                    out.append({"key": "u:%d" % r["uid"], "kind": "private",
                                "gid": 0, "uid": r["uid"], "name": nick,
                                "count": r["n"], "last": r["last"]})
        if kw:
            kw = str(kw)
            out = [x for x in out
                   if kw in str(x["key"]) or kw in (x["name"] or "")]
        out.sort(key=lambda x: x.get("last") or "", reverse=True)
        return out[:limit]

    def chat_log_page(self, key, kw="", limit=80, offset=0):
        """按会话读聊天记录。key 形如 g:123 / u:456。"""
        key = str(key or "").strip()
        if ":" not in key:
            return []
        kind, _, num = key.partition(":")
        try:
            num = int(num)
        except (TypeError, ValueError):
            return []
        sql = "SELECT * FROM chat_log WHERE "
        args = []
        if kind == "g":
            sql += "group_id=?"
            args.append(num)
        else:
            sql += "group_id=0 AND user_id=?"
            args.append(num)
        if kw:
            sql += " AND (text LIKE ? OR nickname LIKE ?)"
            args += ["%" + str(kw) + "%", "%" + str(kw) + "%"]
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        args += [int(limit), int(offset)]
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, tuple(args)).fetchall()]

    def chat_log_pairs(self, key, only_bot=True, kw="", limit=60, offset=0):
        r"""读会话记录。only_bot=True 时只给"跟机器人的对话"。

        群里每个人说的每句话都会进 chat_log（那份数据是给记忆和统计用的），
        直接列出来就是整个群的流水。要的是"我跟机器人说过什么、它怎么回的"，
        所以按**成对**筛：
          从前往后扫，攒着真人消息；一遇到机器人说的话，
          就把"攒着的那几条 + 这一句"一起交出来，然后清空。
        没触发机器人的闲聊自然被丢掉。

        返回 (当页记录, 总条数)。
        """
        key = str(key or "").strip()
        if ":" not in key:
            return [], 0
        kind, _, num = key.partition(":")
        try:
            num = int(num)
        except (TypeError, ValueError):
            return [], 0
        sql = "SELECT * FROM chat_log WHERE "
        args = []
        if kind == "g":
            sql += "group_id=?"
            args.append(num)
        else:
            sql += "group_id=0 AND user_id=?"
            args.append(num)
        if kw:
            sql += " AND (text LIKE ? OR nickname LIKE ?)"
            args += ["%" + str(kw) + "%", "%" + str(kw) + "%"]
        sql += " ORDER BY id ASC LIMIT 20000"
        with self._conn() as c:
            rows = [dict(r) for r in c.execute(sql, tuple(args)).fetchall()]
        if not only_bot:
            rows.reverse()
            total = len(rows)
            return rows[int(offset):int(offset) + int(limit)], total
        out, buf = [], []
        for r in rows:
            if r.get("is_bot"):
                # 机器人这句话，连同触发它的上文一起算一轮对话
                out.extend(buf[-6:])
                out.append(r)
                buf = []
            else:
                buf.append(r)
                if len(buf) > 12:
                    buf.pop(0)
        out.reverse()          # 新的在前
        total = len(out)
        return out[int(offset):int(offset) + int(limit)], total

    def chat_log_count(self, key, kw=""):
        """按会话数总数 —— 前端靠它决定「下一页」该不该能点。"""
        key = str(key or "").strip()
        if ":" not in key:
            return 0
        kind, _, num = key.partition(":")
        try:
            num = int(num)
        except (TypeError, ValueError):
            return 0
        sql = "SELECT COUNT(*) n FROM chat_log WHERE "
        args = []
        if kind == "g":
            sql += "group_id=?"
            args.append(num)
        else:
            sql += "group_id=0 AND user_id=?"
            args.append(num)
        if kw:
            sql += " AND (text LIKE ? OR nickname LIKE ?)"
            args += ["%" + str(kw) + "%", "%" + str(kw) + "%"]
        with self._conn() as c:
            r = c.execute(sql, tuple(args)).fetchone()
            return int(r["n"] if r else 0)

    # 一条 SQL 最多 32766 个绑定变量（老版本 SQLite 只有 999）。
    # 「清空会话」是把整段聊天记录的 id 一次性传进来的（管理页取 100000 条），
    # 超过上限就抛 OperationalError: too many SQL variables —— 表现是清空失败、
    # 一条都没删。按批删，语义不变。
    _DEL_CHUNK = 500

    def chat_log_del(self, ids):
        if not ids:
            return 0
        ids = list(ids)
        n = 0
        with self._lock, self._conn() as c:
            for i in range(0, len(ids), self._DEL_CHUNK):
                part = ids[i:i + self._DEL_CHUNK]
                qs = ",".join("?" * len(part))
                n += c.execute("DELETE FROM chat_log WHERE id IN (%s)" % qs,
                               tuple(part)).rowcount
            c.commit()
        return n

    def sticker_add(self, h, ext, size, gid=0, uid=0, nick="", kind="image",
                    note="", now=None):
        """入库。同一张图（hash 相同）只记一条，重复发只更新来源。"""
        now = now or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as c:
            row = c.execute("SELECT id FROM stickers WHERE hash=?", (h,)).fetchone()
            if row:
                c.execute("UPDATE stickers SET use_count=use_count+1, "
                          "last_used=? WHERE id=?", (now, row["id"]))
                return row["id"], False
            cur = c.execute(
                "INSERT INTO stickers(hash,ext,size,group_id,user_id,nickname,"
                "kind,note,tags,created_at) VALUES(?,?,?,?,?,?,?,?,'',?)",
                (h, ext, size, gid, uid, nick, kind, note, now))
            return cur.lastrowid, True

    def sticker_set_note(self, sid, note=None, tags=None):
        with self._conn() as c:
            if note is not None:
                c.execute("UPDATE stickers SET note=? WHERE id=?", (note, sid))
            if tags is not None:
                c.execute("UPDATE stickers SET tags=? WHERE id=?", (tags, sid))

    def sticker_del(self, ids):
        """删记录，返回被删掉的 hash 列表（文件由调用方删）。

        分批删 —— 原因同 chat_log_del：id 一多就会撞上 SQL 绑定变量上限。
        """
        if not ids:
            return []
        ids = list(ids)
        out = []
        with self._lock, self._conn() as c:
            for i in range(0, len(ids), self._DEL_CHUNK):
                part = ids[i:i + self._DEL_CHUNK]
                qs = ",".join("?" * len(part))
                rows = c.execute("SELECT hash FROM stickers WHERE id IN (%s)" % qs,
                                 tuple(part)).fetchall()
                c.execute("DELETE FROM stickers WHERE id IN (%s)" % qs, tuple(part))
                out.extend(r["hash"] for r in rows)
            c.commit()
        return out

    def sticker_list(self, kind="", gid=0, kw="", limit=200, offset=0):
        sql = "SELECT * FROM stickers WHERE 1=1"
        args = []
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        if gid:
            sql += " AND group_id=?"
            args.append(gid)
        if kw:
            sql += " AND (note LIKE ? OR tags LIKE ?)"
            args += ["%" + kw + "%", "%" + kw + "%"]
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        args += [limit, offset]
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, tuple(args)).fetchall()]

    def sticker_count(self):
        with self._conn() as c:
            r = c.execute("SELECT COUNT(*) n, COALESCE(SUM(size),0) s "
                          "FROM stickers").fetchone()
            return r["n"], r["s"]

    def sticker_by_hash(self, h):
        with self._conn() as c:
            r = c.execute("SELECT * FROM stickers WHERE hash=?", (h,)).fetchone()
            return dict(r) if r else None

    def sticker_touch(self, sid):
        with self._conn() as c:
            c.execute("UPDATE stickers SET use_count=use_count+1, last_used=? "
                      "WHERE id=?",
                      (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), sid))

    def sticker_search(self, kw, kind="", limit=6):
        r"""按关键词找表情：先匹配标签，再匹配备注。

        标签是人工/机器人整理的（"开心""无语""猫"这种），命中优先；
        备注是视觉模型写的一整段描述，用来兜底。
        """
        kw = str(kw or "").strip()
        if not kw:
            return []
        like = "%" + kw + "%"
        sql = ("SELECT * FROM stickers WHERE (tags LIKE ? OR note LIKE ?)")
        args = [like, like]
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        # 标签命中排在备注命中前面
        sql += (" ORDER BY CASE WHEN tags LIKE ? THEN 0 ELSE 1 END,"
                " use_count ASC, RANDOM() LIMIT ?")
        args += [like, int(limit)]
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, tuple(args)).fetchall()]

    def sticker_candidates(self, tags, limit=40):
        """命中**任意一个**标签的全部候选（不再"第一个有货的标签就返回"）。

        为什么要换：sticker_by_tags 按标签优先级短路，热标签（搞笑 83 张）几乎
        总是赢，冷门但更贴切的表情永远轮不到，表现就是"老是那几张"。
        """
        tags = [str(t or "").strip() for t in (tags or [])]
        tags = [t for t in tags if t]
        if not tags:
            return []
        where = " OR ".join(["tags LIKE ?"] * len(tags))
        args = ["%" + t + "%" for t in tags]
        sql = "SELECT * FROM stickers WHERE (%s) ORDER BY RANDOM() LIMIT ?" % where
        args.append(int(limit))
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, tuple(args)).fetchall()]

    def sticker_by_tags(self, tags, kind="", limit=4):
        r"""按标签挑表情：按优先级逐个标签试，第一个有货的标签返回它的候选。

        只查 tags，**不查 note** —— note 是视觉模型写的画面描述，
        拿情绪词去里面搜会命中一堆"看着像那么回事、发出去很莫名"的图
        （比如画面里有"文字/游戏/人物"就撞上内容词）。

        返回 [(行字典, 命中的标签), ...]，随机序。
        """
        for tag in (tags or []):
            tag = str(tag or "").strip()
            if not tag:
                continue
            sql = "SELECT * FROM stickers WHERE tags LIKE ?"
            args = ["%" + tag + "%"]
            if kind:
                sql += " AND kind=?"
                args.append(kind)
            sql += " ORDER BY use_count ASC, RANDOM() LIMIT ?"
            args.append(int(limit))
            with self._conn() as c:
                rows = c.execute(sql, tuple(args)).fetchall()
            if rows:
                return [(dict(r), tag) for r in rows]
        return []

    def sticker_pick(self, kind=""):
        """随机挑一张 —— AI 挑不出来时的兜底。"""
        with self._conn() as c:
            sql = "SELECT * FROM stickers"
            args = ()
            if kind:
                sql += " WHERE kind=?"
                args = (kind,)
            sql += " ORDER BY RANDOM() LIMIT 1"
            r = c.execute(sql, args).fetchone()
            return dict(r) if r else None

    def sticker_old(self, days=90, limit=500):
        """太久没用的，按最久没用排前面。"""
        cutoff = (datetime.now() - timedelta(days=days)
                  ).strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM stickers WHERE COALESCE(last_used, created_at) < ? "
                "ORDER BY COALESCE(last_used, created_at) ASC LIMIT ?",
                (cutoff, limit)).fetchall()]

    def kb_touch(self, kid):
        """命中计数 +1"""
        try:
            with self._lock, self._conn() as c:
                c.execute("UPDATE kb SET hits=hits+1 WHERE id=?", (int(kid),))
                c.commit()
        except Exception:
            pass

    def kb_count(self, g=None):
        with self._conn() as c:
            if g is None:
                return c.execute("SELECT COUNT(*) FROM kb").fetchone()[0]
            return c.execute("SELECT COUNT(*) FROM kb WHERE group_id IN (0,?)",
                             (int(g),)).fetchone()[0]

    def kb_list(self, g=None, limit=200):
        """g 为 None 列出全部；否则列出该群 + 全局条目"""
        with self._conn() as c:
            if g is None:
                rows = c.execute("SELECT * FROM kb ORDER BY group_id, id DESC LIMIT ?",
                                 (int(limit),)).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM kb WHERE group_id IN (0,?) ORDER BY group_id, id DESC LIMIT ?",
                    (int(g), int(limit))).fetchall()
            return [dict(r) for r in rows]

    def kb_groups(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT group_id, COUNT(*) as cnt FROM kb GROUP BY group_id "
                "ORDER BY group_id")]

    def kb_clear_group(self, g):
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM kb WHERE group_id=?", (int(g),))
            c.commit()
            return cur.rowcount

    def sign_get(self, u, g):
        with self._conn() as c:
            row = c.execute("SELECT * FROM points WHERE user_id=? AND group_id=?",
                            (u, g)).fetchone()
            return dict(row) if row else None

    def sign_do(self, u, g, nick, points_added, new_streak, today_str):
        with self._conn() as c:
            existing = c.execute("SELECT * FROM points WHERE user_id=? AND group_id=?",
                                 (u, g)).fetchone()
            if existing:
                new_points = existing["points"] + points_added
                new_count = existing["sign_count"] + 1
                best = max(existing["best_streak"] or 0, new_streak)
                c.execute("""UPDATE points SET points=?, sign_count=?, streak=?,
                             best_streak=?, last_sign_date=?, nickname=?
                             WHERE user_id=? AND group_id=?""",
                          (new_points, new_count, new_streak, best, today_str, nick, u, g))
            else:
                new_points = points_added
                c.execute("""INSERT INTO points(user_id,group_id,points,sign_count,
                             streak,best_streak,last_sign_date,nickname)
                             VALUES(?,?,?,?,?,?,?,?)""",
                          (u, g, points_added, 1, new_streak, new_streak, today_str, nick))
            c.commit()
            return new_points

    def points_spend(self, u, g, amount):
        amount = int(amount or 0)
        if amount <= 0:
            info = self.sign_get(u, g)
            return True, (info["points"] if info else 0)
        with self._lock, self._conn() as c:
            cur = c.execute(
                "UPDATE points SET points=points-? "
                "WHERE user_id=? AND group_id=? AND points>=?",
                (amount, u, g, amount))
            c.commit()
            if cur.rowcount:
                row = c.execute("SELECT points FROM points WHERE user_id=? AND group_id=?",
                                (u, g)).fetchone()
                return True, (row["points"] if row else 0)
            row = c.execute("SELECT points FROM points WHERE user_id=? AND group_id=?",
                            (u, g)).fetchone()
            return False, (row["points"] if row else 0)

    def points_refund(self, u, g, amount):
        amount = int(amount or 0)
        if amount <= 0:
            return
        with self._lock, self._conn() as c:
            c.execute("UPDATE points SET points=points+? WHERE user_id=? AND group_id=?",
                      (amount, u, g))
            c.commit()

    def sign_do_atomic(self, u, g, nick, base, bonus_per, bonus_cap, today_str):
        with self._lock:
            c = sqlite3.connect(self.db_path, timeout=10)
            c.row_factory = sqlite3.Row
            try:
                c.execute("PRAGMA busy_timeout=5000")
                c.execute("BEGIN IMMEDIATE")
                row = c.execute("SELECT * FROM points WHERE user_id=? AND group_id=?",
                                (u, g)).fetchone()
                if row and row["last_sign_date"] == today_str:
                    return {"ok": False, "already": True,
                            "total": row["points"] or 0,
                            "streak": row["streak"] or 0,
                            "sign_count": row["sign_count"] or 0}

                cur_streak = (row["streak"] or 0) if row else 0
                last_date = row["last_sign_date"] if row else None
                new_streak = 1
                if last_date:
                    try:
                        if (date.fromisoformat(today_str) - date.fromisoformat(last_date)).days == 1:
                            new_streak = cur_streak + 1
                    except Exception:
                        new_streak = 1

                bonus = min(max(0, (new_streak - 1)) * bonus_per, bonus_cap)
                added = base + bonus
                if row:
                    total = (row["points"] or 0) + added
                    c.execute("""UPDATE points SET points=?, sign_count=sign_count+1,
                                 streak=?, best_streak=?, last_sign_date=?, nickname=?
                                 WHERE user_id=? AND group_id=?""",
                              (total, new_streak, max(row["best_streak"] or 0, new_streak),
                               today_str, nick, u, g))
                else:
                    total = added
                    c.execute("""INSERT INTO points(user_id,group_id,points,sign_count,
                                 streak,best_streak,last_sign_date,nickname)
                                 VALUES(?,?,?,?,?,?,?,?)""",
                              (u, g, added, 1, new_streak, new_streak, today_str, nick))
                c.commit()
                return {"ok": True, "already": False, "points_added": added,
                        "bonus": bonus, "total": total, "streak": new_streak}
            except Exception:
                try:
                    c.rollback()
                except Exception:
                    pass
                raise
            finally:
                c.close()

    def sign_rank(self, g, limit=10):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT user_id, nickname, points, sign_count, streak "
                "FROM points WHERE group_id=? ORDER BY points DESC LIMIT ?",
                (g, limit))]

    def sign_rank_all(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT group_id, COUNT(*) as cnt, SUM(points) as total "
                "FROM points GROUP BY group_id ORDER BY total DESC")]

    def sign_clear_group(self, g):
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM points WHERE group_id=?", (g,))
            c.commit()

    def act_touch(self, u, g, nick):
        now = datetime.now().isoformat()
        today_str = date.today().isoformat()
        with self._lock, self._conn() as c:
            c.execute("""INSERT INTO activity(user_id,group_id,last_active,msg_count,nickname)
                         VALUES(?,?,?,1,?)
                         ON CONFLICT(user_id,group_id) DO UPDATE SET
                           last_active=excluded.last_active,
                           msg_count=activity.msg_count+1,
                           nickname=excluded.nickname""",
                      (u, g, now, nick))
            c.execute("""INSERT INTO daily_activity(user_id,group_id,date,msg_count,nickname)
                         VALUES(?,?,?,1,?)
                         ON CONFLICT(user_id,group_id,date) DO UPDATE SET
                           msg_count=daily_activity.msg_count+1,
                           nickname=excluded.nickname""",
                      (u, g, today_str, nick))
            c.commit()

    def act_recent(self, g, days=7):
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM activity WHERE group_id=? AND last_active>=? "
                "ORDER BY last_active DESC", (g, cutoff))]

    def daily_rank(self, g, date_str, limit=10):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT user_id, nickname, msg_count FROM daily_activity "
                "WHERE group_id=? AND date=? ORDER BY msg_count DESC LIMIT ?",
                (g, date_str, limit))]

    def daily_summary(self, g, date_str):
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) as users, COALESCE(SUM(msg_count),0) as total "
                "FROM daily_activity WHERE group_id=? AND date=?",
                (g, date_str)).fetchone()
            return {"users": row["users"] or 0, "total": row["total"] or 0}


    def nick_lookup(self, u, g):
        try:
            with self._conn() as c:
                row = c.execute(
                    "SELECT nickname FROM activity WHERE user_id=? AND group_id=? "
                    "AND nickname IS NOT NULL AND nickname != '' LIMIT 1",
                    (u, g)).fetchone()
                if row and row["nickname"]:
                    return row["nickname"]
                row = c.execute(
                    "SELECT nickname FROM points WHERE user_id=? AND group_id=? "
                    "AND nickname IS NOT NULL AND nickname != '' LIMIT 1",
                    (u, g)).fetchone()
                if row and row["nickname"]:
                    return row["nickname"]
        except Exception:
            pass
        return None

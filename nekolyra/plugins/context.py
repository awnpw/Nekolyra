# -*- coding: utf-8 -*-
r"""插件上下文 —— 插件唯一能拿到的东西。

从 bot.py 里整块搬出来的，类里代码一字未改。

主程序通过 configure() **同名重绑**下面这些全局：

    AI
    CFG
    DB
    DB_PATH
    SUPERUSERS
    _PLUGIN_KEYS
    _PLUGIN_STATE
    _check_handler_sig
    _save_plugin_state
    get_http
    safe_nick
    save_config

**这就是插件的全部世界。** 插件不许 import bot / nekolyra.core /
nekolyra.storage / nekolyra.web —— 由加载器扫描源码拒绝（见
nekolyra/plugins/loader.py 和第 6 步）。用意是给插件一个稳定的边界：
主程序内部随便重构，只要这套 ctx 方法不变，插件就不会坏。
"""

import os
import sqlite3

import nonebot
from nonebot.adapters.onebot.v11 import Message, MessageSegment

__all__ = ["PluginContext", "configure", "is_configured"]


def _noop(*a, **k):
    return None


# 重绑前的安全占位
AI = {}
CFG = {}
DB = {}
DB_PATH = {}
SUPERUSERS = {}
_PLUGIN_KEYS = {}
_PLUGIN_STATE = {}
_check_handler_sig = _noop
_save_plugin_state = _noop
get_http = _noop
safe_nick = _noop
save_config = _noop

log = _noop

_configured = False


def is_configured():
    return _configured


def configure(
    log_=None,
    AI_=None,
    CFG_=None,
    DB_=None,
    DB_PATH_=None,
    SUPERUSERS_=None,
    _PLUGIN_KEYS_=None,
    _PLUGIN_STATE_=None,
    _check_handler_sig_=None,
    _save_plugin_state_=None,
    get_http_=None,
    safe_nick_=None,
    save_config_=None
):
    """由主程序在扫描插件之前调用一次。"""
    global AI, CFG, DB, DB_PATH, SUPERUSERS, _PLUGIN_KEYS, _PLUGIN_STATE, _check_handler_sig, _save_plugin_state, get_http, safe_nick, save_config
    global log
    global _configured
    if AI_ is not None:
        AI = AI_
    if CFG_ is not None:
        CFG = CFG_
    if DB_ is not None:
        DB = DB_
    if DB_PATH_ is not None:
        DB_PATH = DB_PATH_
    if SUPERUSERS_ is not None:
        SUPERUSERS = SUPERUSERS_
    if _PLUGIN_KEYS_ is not None:
        _PLUGIN_KEYS = _PLUGIN_KEYS_
    if _PLUGIN_STATE_ is not None:
        _PLUGIN_STATE = _PLUGIN_STATE_
    if _check_handler_sig_ is not None:
        _check_handler_sig = _check_handler_sig_
    if _save_plugin_state_ is not None:
        _save_plugin_state = _save_plugin_state_
    if get_http_ is not None:
        get_http = get_http_
    if safe_nick_ is not None:
        safe_nick = safe_nick_
    if save_config_ is not None:
        save_config = save_config_
    if log_ is not None:
        log = log_
    _configured = True


class PluginContext:
    """传给插件的上下文。插件入口只需要 `def setup(ctx)`。"""

    def __init__(self, meta, pdir, epath):
        self.meta = meta
        self.dir = pdir
        self.entry_path = epath
        self.name = str(meta.get("name") or os.path.basename(pdir))
        self.display_name = str(meta.get("display_name") or self.name)
        self.version = str(meta.get("version") or "1.0.0")
        self.author = str(meta.get("author") or "")
        self.description = str(meta.get("description") or "")
        self.tags = [str(t) for t in (meta.get("tags") or [])]
        # ---- 接口契约相关（插件 API 版本化）----
        # api_version：这个插件是按哪个版本的公开契约写的。
        #   兼容性判定在加载器那边做（bot.py 的 load_plugin 调 check_manifest），
        #   不兼容时会把原因写进 self.error，管理页显示它。
        #   这里只负责**存下来给界面看** —— 判定和展示分开，免得两处规则不一致。
        # permissions：声明的权限。**只声明、不强制** —— 本机插件本来就能干这些事，
        #   列出来是为了让"这插件要干什么"一目了然，也为将来的沙箱留个抓手。
        self.api_version = str(meta.get("api_version") or "")
        self.permissions = [str(p) for p in (meta.get("permissions") or [])]
        _deps = meta.get("dependencies")
        if isinstance(_deps, dict):
            self.dependencies = {str(k): str(v) for k, v in _deps.items()}
        elif isinstance(_deps, list):
            self.dependencies = {str(k): "" for k in _deps}
        else:
            self.dependencies = {}
        # 插件注册进来的东西
        self.commands = {}         # cmd -> (handler, help, prefix)
        self.message_hooks = []    # [handler]
        self.config_schema = []    # [{"title", "fields"}]
        self.pages = []            # [{"id", "title", "html"}]
        self.apis = []             # [{"path", "handler", "methods"}]
        self.loaded = False
        self.enabled = True
        self.error = ""
        self.activated = False      # setup() 是否已经执行过
        self._pending_setup = None  # 扫描阶段先存着，核心就绪后再调
        self.order = 100

    # ---------------- 日志 ----------------
    def log(self, msg):
        log("info", "插件", f"{self.display_name}：{msg}")

    def warn(self, msg):
        log("warn", "插件", f"{self.display_name}：{msg}")

    # ---------------- 配置 ----------------
    # 插件配置跟内置配置一样，**平铺在 config.json 顶层**。
    # 这样管理界面（它就是把值平铺提交的）跟插件的读写能对上，
    # 老用户配置里已有的 lottery_* 这类键也天然兼容。
    @property
    def config(self):
        pc = CFG.get("plugin_config")
        if isinstance(pc, dict):
            d = pc.get(self.name)
            if isinstance(d, dict):
                return d
        return {}

    def cfg(self, key, default=None):
        """读插件配置。顺序：顶层平铺键 -> plugin_config.<插件名> -> metadata 里的 defaults。"""
        v = CFG.get(key)
        if v is None:
            v = self.config.get(key)
        if v is None:
            v = (self.meta.get("defaults") or {}).get(key)
        return default if v is None else v

    def set_cfg(self, key, value):
        """写插件配置（写到顶层平铺键，跟管理界面一致）。"""
        CFG[key] = value
        _PLUGIN_KEYS.add(key)
        save_config()

    # ---------------- 注册能力 ----------------
    def command(self, cmd, help="", prefix=False, timeout=None):
        """注册一个群命令（被 @ 时触发）。handler(event, cmd) 返回 True 表示已处理。

        命令是**精确匹配**整条消息的。想让「查询游戏 鸣潮」这种带参数的也能触发，
        传 prefix=True —— 那样匹配「查询游戏」本身，或者「查询游戏 + 空格 + 任意参数」。
        handler 收到的 cmd 仍然是**整条消息**，自己 split 取参数：

            @ctx.command("查询游戏", "查资源", prefix=True)
            async def h(event, cmd):
                arg = cmd[len("查询游戏"):].strip()   # 「查询游戏 鸣潮」→「鸣潮」
                ...

        参数个数不对会**当场报错**（而不是等群里发命令时才在日志里报）。

        timeout：这个命令**单独**的超时秒数。不传就用全局的 plugin_timeout。
            做实事（扫群文件、调 AI、拉外部 HTTP）的命令一定要传 ——
            全局值默认很短，做不完就被砍掉，表现是"命令没反应"，
            而且消息会继续往下走到 AI，被 AI 抢答。
        """
        def deco(fn):
            err = _check_handler_sig(fn, f"命令「{cmd}」的处理函数", 2, "event, cmd")
            if err:
                raise TypeError(err)
            if timeout is not None:
                try:
                    fn.__plugin_timeout__ = float(timeout)
                except Exception:
                    pass
            self.commands[str(cmd)] = (fn, help, bool(prefix))
            return fn
        return deco

    def on_message(self, timeout=None):
        """注册全量消息钩子。handler(event, text) 返回 True 表示吞掉这条消息。

        参数个数不对会**当场报错**。timeout 含义同 command()。
        """
        def deco(fn):
            err = _check_handler_sig(fn, "消息钩子", 2, "event, text")
            if err:
                raise TypeError(err)
            if timeout is not None:
                try:
                    fn.__plugin_timeout__ = float(timeout)
                except Exception:
                    pass
            self.message_hooks.append(fn)
            return fn
        return deco

    def register_config(self, title, fields):
        """声明这个插件的配置项。

        fields 格式跟内置的一样：[[键, 标签, 类型], ...]
        类型：bool / number / text / backend(下拉) 等，跟内置渲染器一致。

        这些配置**不会**混进「系统配置」页 —— 它们出现在**这个插件自己的配置小窗**里：
        管理界面「插件 → 已安装」的卡片上点「配置」就弹出来。
        """
        self.config_schema.append({"title": str(title), "fields": list(fields)})
        for f in fields:
            try:
                _PLUGIN_KEYS.add(f[0])
            except Exception:
                pass

    def register_page(self, pid, title, html=""):
        """往管理界面「扩展」分组下加一个侧边栏页面。

        pid 建议带插件名前缀避免撞车（它同时是页面元素 id：page-<pid>）。
        html 里可以直接写 <script>，会被执行 —— 但脚本跑在全局作用域，
        函数名请自己加前缀，别用 load() / run() 这种通用名。

        插件被停用或卸载时，页面和导航项会自动消失。
        """
        self.pages.append({"id": str(pid), "title": str(title), "html": html})

    def register_api(self, path, handler, methods=("GET",), timeout=None):
        """注册管理接口（跟插件一起装卸）。

        path 以 / 开头，**建议放 /admin/api/plugins/<插件名>/ 下面**避免撞车。
        会自动带上 token 校验（跟内置管理接口一致）。

        handler 可以是 async 或普通函数，签名 handler(request, body)：
            request = FastAPI 的 Request，查询参数用 request.query_params.get("x")
            body    = POST 的 JSON body（dict；GET 时是 {}）
        返回值会被 JSON 序列化成响应。

        handler 不是函数、或参数个数不对，会**当场报错**。
        """
        _e = _check_handler_sig(handler, f"接口 {path} 的处理函数", 2, "request, body")
        if _e:
            raise TypeError(_e)
        self.apis.append({
            "path": str(path),
            "handler": handler,
            "methods": [str(m).upper() for m in methods],
            "timeout": (float(timeout) if timeout is not None else None),
        })

    # ---------------- 服务 ----------------
    def mention(self, uid):
        """@某人的片段。跟字符串混在一个列表里传给 send_group / send_private。

        用法：
            await ctx.send_group(gid, [ctx.mention(uid), " 恭喜中奖！"])
        """
        return ("__at__", int(uid))

    def image(self, url):
        """图片片段。同样放进列表里。

        用法：
            await ctx.send_group(gid, [ctx.mention(uid), " 你的图：", ctx.image(url)])
        """
        return ("__img__", str(url))

    @staticmethod
    def _build_message(content):
        """把字符串或列表拼成 OneBot 的 Message。"""
        m = Message()
        if isinstance(content, str):
            if content:
                m.append(MessageSegment.text(content))
            return m
        if isinstance(content, (list, tuple)):
            for part in content:
                if (isinstance(part, tuple) and len(part) == 2
                        and part[0] == "__at__"):
                    m.append(MessageSegment.at(int(part[1])))
                elif (isinstance(part, tuple) and len(part) == 2
                        and part[0] == "__img__"):
                    m.append(MessageSegment.image(str(part[1])))
                elif part is not None and str(part) != "":
                    m.append(MessageSegment.text(str(part)))
            return m
        m.append(MessageSegment.text(str(content)))
        return m

    async def onebot(self, action, **params):
        r"""直接调一个 OneBot 动作，取协议层的数据。

        用法：
            r = await ctx.onebot("get_group_root_files", group_id=123456)
            files = (r or {}).get("files", [])

            r = await ctx.onebot("get_group_file_url", group_id=gid,
                                 file_id=fid, busid=busid)
            url = (r or {}).get("url", "")

        返回动作的原始结果（通常 dict）；**所有连接都失败时返回 None**。
        注意 None 和「动作成功但结果为空」是两回事，调用方要分开处理。

        为什么需要它：插件原来只能发消息，读不到群文件、群成员、群公告
        这类协议层数据，也就做不出「按群文件回答」的插件。Nekolyra 内部
        本来就在用 bot.call_api，这里只是把它暴露出来 —— 遍历现有连接，
        跟 send_group 走同一个路子。
        """
        last = None
        for bot in list(nonebot.get_bots().values()):
            try:
                return await bot.call_api(action, **params)
            except Exception as e:
                last = e
                continue
        if last is not None:
            self.warn(f"onebot({action}) 全部连接都失败："
                      f"{type(last).__name__}: {last}")
        return None

    async def send_group(self, gid, content):
        """发群消息。content 可以是字符串，或 [ctx.mention(uid), "文字"] 这样的列表。"""
        msg = self._build_message(content)
        if not len(msg):
            return False
        for bot in list(nonebot.get_bots().values()):
            try:
                await bot.send_group_msg(group_id=int(gid), message=msg)
                return True
            except Exception:
                continue
        return False

    async def send_private(self, uid, content):
        """发私聊。content 同上，支持字符串或列表。"""
        msg = self._build_message(content)
        if not len(msg):
            return False
        for bot in list(nonebot.get_bots().values()):
            try:
                await bot.send_private_msg(user_id=int(uid), message=msg)
                return True
            except Exception:
                continue
        return False

    # ---------------- 群管动作 ----------------
    # 管群类插件（反广告、刷屏、违规词…）都要这几样。
    # 没做成"插件自己 import nonebot"—— 那是内部实现，不该让插件依赖。
    async def delete_msg(self, event):
        r"""撤回一条消息。失败返回 False（比如不是管理员、消息太旧）。"""
        try:
            for bot in list(nonebot.get_bots().values()):
                try:
                    await bot.delete_msg(message_id=int(event.message_id))
                    return True
                except Exception:
                    continue
        except Exception as e:
            self.warn(f"撤回失败 {type(e).__name__}: {e}")
        return False

    async def kick(self, gid, uid, reject_add=True):
        r"""把某人踢出群。reject_add=True 时同时拒绝他再申请。"""
        try:
            for bot in list(nonebot.get_bots().values()):
                try:
                    await bot.set_group_kick(group_id=int(gid), user_id=int(uid),
                                             reject_add_request=bool(reject_add))
                    return True
                except Exception:
                    continue
        except Exception as e:
            self.warn(f"踢出失败 {type(e).__name__}: {e}")
        return False

    def bl_add(self, uid, gid, nick="", reason=""):
        r"""加进黑名单（主程序那张表，管理界面「黑名单」能看见）。"""
        try:
            DB.bl_add(int(uid), int(gid), str(nick or ""), str(reason or ""))
            return True
        except Exception as e:
            self.warn(f"拉黑失败 {type(e).__name__}: {e}")
            return False

    def is_super(self, uid):
        r"""是不是超管（配置里的 superusers）。插件通常该放行超管。"""
        try:
            return str(uid) in SUPERUSERS
        except Exception:
            return False

    async def nick(self, gid, uid):
        r"""取群昵称。取不到时返回 QQ 号字符串。"""
        try:
            for bot in list(nonebot.get_bots().values()):
                n = await safe_nick(bot, int(gid), int(uid))
                if n:
                    return n
        except Exception:
            pass
        return str(uid)

    def db(self):
        """开一个主库连接（插件自己的表自己建，建议加插件名前缀）。"""
        return sqlite3.connect(DB_PATH, timeout=15)

    def self_id(self):
        """当前登录的机器人 QQ（字符串）。没有在线 bot 时返回空串。"""
        try:
            bots = list(nonebot.get_bots().values())
            return str(bots[0].self_id) if bots else ""
        except Exception:
            return ""

    def act_recent(self, gid, days=7):
        """最近 N 天在群里说过话的成员。

        返回 [{user_id, group_id, last_active, msg_count, nickname}, ...]，
        按最近活跃时间倒序。注意字段是 msg_count，不是 count。

        依赖主库的 activity 表。表不存在或查询失败时返回空列表，
        插件自己判断"没人活跃"即可，不用额外 try。
        """
        try:
            return DB.act_recent(int(gid), days=int(days)) or []
        except Exception as e:
            log("warn", "插件", f"{self.display_name}：act_recent 失败 {type(e).__name__}: {e}")
            return []

    def db_exec(self, sql, params=()):
        """执行写语句（插件可以建自己的表、写自己的数据）。

        表名建议加插件前缀，避免跟别的插件撞车。
        """
        with DB._lock, DB._conn() as c:
            cur = c.execute(sql, params if params is not None else ())
            c.commit()
            return cur.rowcount

    def db_query(self, sql, params=()):
        """执行查询，返回 [dict, ...]。"""
        with DB._conn() as c:
            return [dict(r) for r in c.execute(sql, params if params is not None else ())]

    async def http_get(self, url, params=None, timeout=15.0, headers=None):
        """GET 请求。

        用主程序的共享客户端，本机地址会自动直连 —— 系统代理开着也不会
        把 localhost 请求发给代理（那会导致 502，是个踩过的真坑）。
        """
        return await get_http().get(url, params=params, timeout=float(timeout),
                                    headers=headers or {})

    async def ai(self, prompt, timeout=15.0, use_gap=False):
        """让模型生成一段文字。模型没启用或调用失败时返回空字符串（不抛异常）。"""
        try:
            if not AI.enabled:
                return ""
            r = await AI.raw([{"role": "user", "content": str(prompt)}],
                             timeout=float(timeout), use_gap=use_gap)
            return (r or "").strip()
        except Exception as e:
            self.warn(f"AI 调用失败 {type(e).__name__}: {e}")
            return ""

    def sign_do(self, uid, gid, nick, base, bonus_per, bonus_cap, today):
        """原子签到（同一天重复调用会返回 already=True）。返回 dict。"""
        return DB.sign_do_atomic(int(uid), int(gid), str(nick or ""), int(base),
                                 int(bonus_per), int(bonus_cap), str(today))

    def sign_get(self, uid, gid):
        """某人的积分记录（没签过返回 None）。"""
        return DB.sign_get(int(uid), int(gid))

    def sign_rank(self, gid, limit=10):
        """本群积分榜：[{user_id, nickname, points, sign_count, streak}, ...]。"""
        try:
            return DB.sign_rank(int(gid), limit=int(limit)) or []
        except Exception as e:
            log("warn", "插件", f"{self.display_name}：sign_rank 失败 {type(e).__name__}: {e}")
            return []

    def sign_rank_all(self):
        """所有群的积分汇总：[{group_id, cnt, total}, ...]。"""
        try:
            return DB.sign_rank_all() or []
        except Exception:
            return []

    def sign_clear_group(self, gid):
        """清空某群所有人的积分。"""
        return DB.sign_clear_group(int(gid))

    def points_spend(self, uid, gid, amount):
        """扣积分。返回 (是否成功, 剩余积分)。积分不够就返回 (False, 当前值)。"""
        return DB.points_spend(int(uid), int(gid), int(amount))

    def points_refund(self, uid, gid, amount):
        """退还积分。"""
        return DB.points_refund(int(uid), int(gid), int(amount))

    def daily_rank(self, gid, date_str, limit=10):
        """某天的发言榜：[{user_id, nickname, msg_count}, ...] 按条数降序。"""
        try:
            return DB.daily_rank(int(gid), str(date_str), limit=int(limit)) or []
        except Exception as e:
            log("warn", "插件", f"{self.display_name}：daily_rank 失败 {type(e).__name__}: {e}")
            return []

    def daily_summary(self, gid, date_str):
        """某天的汇总：{"users": 发言人数, "total": 总条数}。"""
        try:
            r = DB.daily_summary(int(gid), str(date_str)) or {}
            return {"users": int(r.get("users") or 0),
                    "total": int(r.get("total") or 0)}
        except Exception as e:
            log("warn", "插件", f"{self.display_name}：daily_summary 失败 {type(e).__name__}: {e}")
            return {"users": 0, "total": 0}

    async def group_name(self, gid):
        """群名（走一次接口，有失败兜底）。

        群名不存库 —— 数据库里只有 activity/points 这些业务表，
        群名一直是实时调 bot.get_group_info() 拿的。
        """
        try:
            for bot in list(nonebot.get_bots().values()):
                info = await bot.get_group_info(group_id=int(gid), no_cache=False)
                n = (info or {}).get("group_name")
                if n:
                    return str(n)
        except Exception:
            pass
        return f"群{gid}"

    def kv_get(self, key, default=None):
        """插件私有键值存储（存在 data/plugins.json 的 installed 下）。"""
        try:
            st = _PLUGIN_STATE.get("installed") or {}
            me = st.get(self.name) or {}
            kv = me.get("kv") or {}
            v = kv.get(key)
            return default if v is None else v
        except Exception:
            return default

    def kv_set(self, key, value):
        """写插件私有键值。适合存少量状态（大量数据请用自己的表）。"""
        try:
            st = _PLUGIN_STATE.setdefault("installed", {})
            me = st.setdefault(self.name, {})
            kv = me.setdefault("kv", {})
            kv[key] = value
            _save_plugin_state()
            return True
        except Exception:
            return False

    def info(self):
        return {
            "name": self.name,
            "display_name": self.display_name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "tags": self.tags,
            "dir": self.dir,
            "loaded": self.loaded,
            "activated": bool(self.activated),
            "enabled": self.enabled,
            "error": self.error,
            "commands": sorted(self.commands.keys()),
            "hooks": len(self.message_hooks),
            "pages": [p["id"] for p in self.pages],
            "page_titles": {p["id"]: p["title"] for p in self.pages},
            "apis": [a["path"] for a in self.apis],
            "config": list(self.config_schema),
            # 插件 API 版本化：声明了什么就显示什么
            "api_version": self.api_version,
            "permissions": self.permissions,
            "dependencies": dict(self.dependencies),
        }

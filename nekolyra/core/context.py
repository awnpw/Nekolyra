# -*- coding: utf-8 -*-
r"""第 6 段：上下文组装 —— `build_context(inc, deps)`。

**不 import nonebot，也不 import bot。** 需要的东西全部注入
（跟 Database / AIHandler / PluginContext 一个套路，前面验证过三次）。

群聊和私聊的差异，逐条对到参数上 —— **并排量过，不是猜的**：

    群聊                                  私聊
    历史      get_context(gid)             get_private_context(uid)
    群记忆    mem_recent(gid, …)           （没有 -> 空 list）
    个人记忆  mem_recent_user(gid, uid)    mem_recent_user(0, uid)
    画像      user_profile_block(gid, …)   user_profile_block(0, …)
    知识库    kb_search(gid, …)            （没有 -> 空串）
    mode      "group"                      "private"
    记忆 key  gid（正）                     -uid（负，不跟群号撞）
    text 为空 return                        text 补成「在吗」

**最后那条是写这个文件时才发现的第 9 处差异** —— 群聊碰到空 text 直接
return，私聊却补一句「在吗」。所以本函数在群聊下**会返回 None**，
调用方必须判；私聊永远返回 Context。

写这段的时候我差点读错函数：第一次读到的其实是**私聊**那版
（get_private_context / mem_recent_user(0, uid, …)），差点当成群聊的抽 ——
那样会少注入群记忆和知识库，**机器人突然记不住群里的事，而且不报错**。
所以这里先并排量清楚才动手。
"""

from typing import Optional

from nekolyra.core.types import Context, Incoming

__all__ = ["build_context", "DEPS_NEEDED"]

#: 注入字典里需要的键 -> 说明。主程序照着这个准备就行。
DEPS_NEEDED = {
    "enrich": "async (event, text, images) -> (text, has_img)  识图补文本",
    "get_ctx": "(gid) -> list                群历史",
    "get_private": "(uid) -> list            私聊历史",
    "mem_recent": "(gid, limit=n) -> list    群记忆",
    "mem_user": "(gid, uid, limit=n) -> list 个人记忆",
    "profile_of": "(gid, uid, name) -> str   用户画像",
    "kb_search": "(gid, text, limit=n) -> [(score, row)]",
    "kb_block": "(hits) -> str               知识库引用块",
    "kb_touch": "(id) -> None                命中计数",
    "cfg_bool": "(key, default) -> bool",
    "cfg_int": "(key, default) -> int",
    "log": "(level, tag, msg) -> None",
}


def _call(deps, name, *a, default=None, **kw):
    """注入的函数可能没给、也可能抛 —— 都不能让整条消息挂掉。

    这是每条消息的必经之路，抛异常 = 机器人静默不理人，最难查的那种。
    """
    fn = (deps or {}).get(name)
    if fn is None:
        return default
    try:
        return fn(*a, **kw)
    except Exception as e:
        _log(deps, "warn", "上下文", "%s(%s): %s" % (name, type(e).__name__, e))
        return default


def _log(deps, level, tag, msg):
    fn = (deps or {}).get("log")
    if fn is None:
        return
    try:
        fn(level, tag, msg)
    except Exception:
        pass


def _trigger_text(inc: Incoming, mentioned_by_name: bool) -> str:
    if inc.to_me:
        return "被@"
    if mentioned_by_name:
        return "提及名字"
    return "主动"


async def build_context(inc: Incoming, *, deps,
                        mentioned_by_name: bool = False,
                        persona_name: str = "",
                        inject_count: int = 0) -> Optional[Context]:
    r"""组装交给 AI 的上下文。返回 None = 这条消息不该往下走（只有群聊会）。"""
    is_g = inc.is_group

    # ---- 1. 识图补文本 ----
    enrich = (deps or {}).get("enrich")
    has_img = False
    text = inc.text
    if enrich is not None:
        try:
            got = await enrich(inc.raw, inc.text, inc.images)
        except Exception as e:
            # enrich 是每条消息的第一步 (识图要过网络, 最容易失败)。
            # 跟 _call 一个道理: 让它穿出去 = 机器人静默不理人。
            _log(deps, "warn", "上下文", "enrich: %s: %s" % (type(e).__name__, e))
            got = None
        if isinstance(got, tuple) and len(got) == 2:
            text, has_img = got
        else:
            text = got
    text = str(text or "")

    if has_img and is_g:
        _log(deps, "msg", "识图",
             "[群%d] %s 发来 %d 张图，已转描述"
             % (inc.gid, inc.nick, len(inc.images)))

    # ---- 2. 空文本：两边处理不一样（第 9 处差异）----
    if not text.strip():
        if is_g:
            return None
        text = "在吗"

    # ---- 3. 说话人 ----
    speaker_name = inc.nick
    speaker = {"name": speaker_name, "qq": inc.uid}

    if is_g:
        _log(deps, "msg", "消息",
             "[群%d] %s %s(%d): %s"
             % (inc.gid, _trigger_text(inc, mentioned_by_name),
                speaker_name, inc.uid, text[:60]))

    # ---- 4. 剥掉名字 ----
    clean_text = text
    if is_g and mentioned_by_name and persona_name:
        clean_text = clean_text.replace(persona_name, "").strip()
    if not clean_text:
        clean_text = "在吗"

    # ---- 5. 历史 / 记忆 / 画像 ----
    key = inc.gid if is_g else -inc.uid
    if is_g:
        history = _call(deps, "get_ctx", inc.gid, default=[]) or []
        mems = _call(deps, "mem_recent", inc.gid, limit=inject_count,
                     default=[]) or []
    else:
        history = _call(deps, "get_private", inc.uid, default=[]) or []
        mems = []                       # 私聊没有群记忆

    if _call(deps, "cfg_bool", "memory_user_enabled", True, default=True):
        umems = _call(deps, "mem_user", inc.gid if is_g else 0, inc.uid,
                      limit=_call(deps, "cfg_int",
                                  "memory_user_inject_count", 3, default=3),
                      default=[]) or []
    else:
        umems = []

    # 画像要传**说话人**的名字，不是机器人的人格名 ——
    # 传错了画像里会写成"昵称：默认角色"，把用户的专属记忆归到机器人名下
    profile = _call(deps, "profile_of", inc.gid if is_g else 0, inc.uid,
                    speaker_name, default="") or ""

    # ---- 6. 知识库（只有群聊有）----
    knowledge = ""
    if is_g \
            and _call(deps, "cfg_bool", "kb_enabled", True, default=True) \
            and _call(deps, "cfg_bool", "kb_auto_inject", True, default=True):
        hits = _call(deps, "kb_search", inc.gid, clean_text,
                     limit=_call(deps, "cfg_int", "kb_inject_count", 3,
                                 default=3), default=[]) or []
        if hits:
            knowledge = _call(deps, "kb_block", hits, default="") or ""
            for item in hits:
                try:
                    _row = item[1]
                    _call(deps, "kb_touch", _row["id"])
                except Exception:
                    pass
            _log(deps, "info", "知识库",
                 "[群%d] 注入 %d 条给 AI：%s"
                 % (inc.gid, len(hits), clean_text[:30]))

    return Context(text=clean_text, speaker=speaker, history=history,
                   group_memories=mems, user_memories=umems,
                   profile=profile, knowledge=knowledge,
                   mode=("group" if is_g else "private"),
                   mem_key=key, has_img=has_img)

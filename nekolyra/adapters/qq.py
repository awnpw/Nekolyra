# -*- coding: utf-8 -*-
r"""QQ / OneBot v11 适配器 —— 平台相关的东西集中在这里。

职责只有两件：
  1. `to_incoming(event)`  —— 把 QQ 事件转成 core 的 Incoming
  2. `send_parts(...)`     —— 把 core 的 Outgoing 发出去

**core 不认识 event / MessageSegment / bot** —— 那些只在本模块里出现。

转换函数要用的四个工具（`plaintext_with_at` / `extract_images` /
`tag_image_kind` / `describe_segments`）目前还在 bot.py 里，
所以用 `configure()` 注入 —— 跟 Database / AIHandler / PluginContext 一个套路。
等那四个也搬进本模块之后，configure() 就可以去掉。
"""

from typing import Any, Callable, List, Optional

from nekolyra.core.types import Incoming, Outgoing

__all__ = ["to_incoming", "to_outgoing", "send_parts", "configure",
           "is_configured", "to_message", "safe_reply",
           "seg_at", "seg_reply", "seg_image", "seg_record"]

# ---- 注入点（重绑前是安全的占位）----
_plaintext_with_at: Optional[Callable] = None
_extract_images: Optional[Callable] = None
_tag_image_kind: Optional[Callable] = None
_describe_segments: Optional[Callable] = None
_log: Optional[Callable] = None

_configured = False


def is_configured() -> bool:
    return _configured


def configure(plaintext_with_at=None, extract_images=None,
              tag_image_kind=None, describe_segments=None, log=None):
    r"""由主程序在启动时调一次（在第一个消息进来之前）。"""
    global _plaintext_with_at, _extract_images, _tag_image_kind
    global _describe_segments, _log, _configured
    if plaintext_with_at is not None:
        _plaintext_with_at = plaintext_with_at
    if extract_images is not None:
        _extract_images = extract_images
    if tag_image_kind is not None:
        _tag_image_kind = tag_image_kind
    if describe_segments is not None:
        _describe_segments = describe_segments
    if log is not None:
        _log = log
    _configured = True


def _safe(fn, *a, default=None, **kw):
    """注入的函数可能没给、也可能抛 —— 都不能让整条消息挂掉。"""
    if fn is None:
        return default
    try:
        return fn(*a, **kw)
    except Exception as e:
        if _log is not None:
            try:
                _log("warn", "适配器", "%s: %s" % (type(e).__name__, e))
            except Exception:
                pass
        return default


def to_incoming(event: Any, is_group: Optional[bool] = None) -> Incoming:
    r"""QQ 事件 -> Incoming。

    这些取值的写法跟原来 `_on_ai` 里那几行**完全一致** —— 只是挪了地方，
    没有"顺手改成更好的写法"。搬家和改逻辑混在一起最难排查
    （搬 Database 那次就混了）。
    """
    self_id = int(getattr(event, "self_id", 0) or 0)
    text = _safe(_plaintext_with_at, event, skip_self_id=self_id, default="")
    text = str(text or "").strip()
    images = _safe(_extract_images, event, default=[]) or []
    images = [str(u) for u in images]
    kinds = _safe(_tag_image_kind, event, default={}) or {}

    if is_group is None:
        is_group = getattr(event, "group_id", None) is not None

    gid = int(getattr(event, "group_id", 0) or 0)
    uid = int(getattr(event, "user_id", 0) or 0)

    # 显示名：群名片优先，其次昵称
    nick = ""
    try:
        nick = str(event.sender.card or event.sender.nickname or "") or ""
    except Exception:
        nick = ""
    if not nick:
        nick = str(uid)

    # 段类型描述（没有文字也没有图时才有意义，但算了也无妨）
    segments = ""
    if (not text) and (not images):
        segments = str(_safe(_describe_segments, event, self_id, default="")
                       or "")

    # 纯 @ 这里**不造文本**。
    #
    # 我一度在这里补过一句「在吗」—— 那是错的：用户根本没说过这三个字，
    # 而它会一路存进聊天记录（DB.log_add）和记忆流水（push_mem_turn），
    # 等于**往库里写假数据**，AI 也会以为他真的说了「在吗」。
    # 比"不回"更糟：不回只是没反应，这是污染。
    #
    # 纯 @ 的正确形态就是：to_me 为真、text 为空。要不要回、怎么回是 core
    # 的事，适配器不该替用户编话。

    return Incoming(
        gid=gid, uid=uid, nick=nick, self_id=self_id,
        text=text, images=images, kinds=dict(kinds), segments=segments,
        to_me=_decide_to_me(event, text, images),
        is_group=bool(is_group),
        raw=event,
    )


def _decide_to_me(event, text: str, images) -> bool:
    r"""算「这条是不是在叫它」。

    两条来源，取并集但要排除 @全体：

        is_at_me(event)         自己扫 at 段 —— 最可靠，@全体天然排除
        协议端的 event.to_me     兜底 —— 有些协议端会为「回复机器人」之类
                                也置 True，那种情况我们也该认

    @全体单独排除：如果这条消息里 @了全体、又没有 @机器人自己，
    那不管协议端怎么说，都不该当成在叫它。
    """
    if is_at_me(event):
        return True
    if has_at_all(event):
        return False
    return bool(getattr(event, "to_me", False))



def to_outgoing(reply: str = "", sticker_id: Optional[int] = None,
                voice_text: Optional[str] = None,
                parts: Optional[List[str]] = None) -> Outgoing:
    r"""把 core 算出来的几样东西打包成 Outgoing。

    顺序在 Outgoing 的 docstring 里写了：表情 → 语音 → 文字。
    """
    o = Outgoing(sticker_id=sticker_id, voice_text=voice_text,
                 text=str(reply or ""), parts=list(parts or []))
    if not o.parts and o.text:
        o.parts = [o.text]
    return o


async def send_parts(bot, event, parts: List[str], delay: float = 0.8) -> int:
    r"""把几条文字依次发出去。返回发了几条。

    切分 + 间隔是原来 `_on_ai` 里那段的做法（split_reply_text + 随机延时），
    这里只是把"发"这一步收进适配器。
    """
    import asyncio
    import random

    sent = 0
    for i, part in enumerate(parts):
        t = str(part or "").strip()
        if not t:
            continue
        try:
            await bot.send(event, t)
            sent += 1
        except Exception as e:
            if _log is not None:
                try:
                    _log("error", "发送", "%s: %s" % (type(e).__name__, e))
                except Exception:
                    pass
            return sent
        # 最后一条之后不用等
        if i < len(parts) - 1 and delay > 0:
            await asyncio.sleep(delay * (0.6 + random.random() * 0.8))
    return sent


# ============================================================
# 消息构建 / 回复（从 bot.py 搬过来的）
#
# 这两个是 MessageSegment 那 14 处里的 7 处 —— 搬进来之后
# bot.py 就不再直接依赖 nonebot 的消息类型了（对这两个功能而言）。
#
# 日志文案**一字未改**（"构建消息" / "发送" 两个 tag）——
# 用户排查时是按 tag 找的，改了等于把线索弄丢。
# ============================================================


def _msg_types():
    r"""延迟 import nonebot 的消息类型。

    放函数里而不是模块顶层：这个模块会被 web 那边 import，
    而 nonebot 的消息类型要在 nonebot.init() 之后才拿得到。
    """
    from nonebot.adapters.onebot.v11 import Message, MessageSegment
    return Message, MessageSegment


def to_message(*parts):
    r"""把任意几段东西拼成一条 Message。

    字符串当文本、MessageSegment 原样、Message 展开、列表递归。
    认不出来的转成 str 当文本 —— **不抛异常**，只记一条 warn，
    因为它是发送路径上的必经之处，抛了整条消息就发不出去了。
    """
    Message, MessageSegment = _msg_types()
    result = Message()
    for p in parts:
        if p is None:
            continue
        try:
            if isinstance(p, str):
                if p:
                    result.append(MessageSegment.text(p))
            elif isinstance(p, MessageSegment):
                result.append(p)
            elif isinstance(p, Message):
                result.extend(p)
            elif isinstance(p, (list, tuple)):
                for item in p:
                    if item is None:
                        continue
                    if isinstance(item, str):
                        if item:
                            result.append(MessageSegment.text(item))
                    elif isinstance(item, MessageSegment):
                        result.append(item)
                    elif isinstance(item, Message):
                        result.extend(item)
                    else:
                        result.append(MessageSegment.text(str(item)))
            else:
                result.append(MessageSegment.text(str(p)))
        except Exception as e:
            _safe_log("warn", "构建消息",
                      "跳过一段：%s: %s" % (type(e).__name__, e))
    return result


async def safe_reply(bot, event, *parts):
    r"""带引用的回复；reply 段不被支持时**降级成普通发送**。

    为什么要降级：不是所有协议端都支持 reply 段，失败的可能是
    「这条消息不能引用」而不是「发不出去」—— 直接返回失败的话，
    用户看到的是机器人完全不回话。
    """
    content = to_message(*parts)
    if len(content) == 0:
        content = to_message("（空）")
    try:
        Message, MessageSegment = _msg_types()
        full = Message([MessageSegment.reply(event.message_id)])
        full.extend(content)
        await bot.send(event, full)
        return True
    except Exception as e1:
        _safe_log("warn", "发送",
                  "reply 失败(%s: %s)，改用普通发送" % (type(e1).__name__, e1))
        try:
            await bot.send(event, content)
            return True
        except Exception as e2:
            _safe_log("error", "发送",
                      "普通发送也失败: %s: %s" % (type(e2).__name__, e2))
            return False


def _safe_log(level, tag, msg):
    r"""用注入进来的 log；没注入就静默（不能因为日志而把发送搞挂）。"""
    if _log is None:
        return
    try:
        _log(level, tag, msg)
    except Exception:
        pass


# ============================================================
# 消息段助手（拆包 ④ 第二块）
#
# 把「造一个消息段」这件事收在这里 —— bot.py 里剩下的 7 处
# MessageSegment.xxx(...) 全部改调这些。
#
# **不是搬函数，是搬"造段"这个动作**：_send_impl / try_send_voice 那些
# 是路由和业务流程，搬它们要动控制流，风险跟收益不成比例。
# 这样收一下，bot.py 就不再认识 MessageSegment 了 —— 换协议端时
# 只改本文件。
# ============================================================


def seg_at(uid) -> "object":
    r"""@某人。"""
    _Message, MessageSegment = _msg_types()
    return MessageSegment.at(int(uid))


def seg_reply(message_id) -> "object":
    r"""回复某条消息（引用）。"""
    _Message, MessageSegment = _msg_types()
    return MessageSegment.reply(message_id)


def seg_image(url) -> "object":
    r"""发图。"""
    _Message, MessageSegment = _msg_types()
    return MessageSegment.image(url)


def seg_record(path) -> "object":
    r"""发语音。

    路径要转成 file:/// 形式并把反斜杠换成正斜杠 —— Windows 上直接给
    `C:\x\y.mp3` 有些协议端认不出来。这行原来散在两处，写法一样。
    """
    import os
    _Message, MessageSegment = _msg_types()
    vpath = str(path)
    return MessageSegment.record("file:///" + vpath.replace(os.sep, "/"))


# ============================================================
# 「在叫它吗」—— 判断收在适配器里
#
# 为什么不直接用 event.to_me：那是**协议端填的**字段，OneBot v11 规范
# 只说它是「消息是否与机器人有关」，没写死 @全体算不算。各家实现不一样。
# 自己扫 at 段跟 self_id 精确比对，行为就确定了：
#     @机器人        qq == self_id   -> True
#     @全体          qq == "all"     -> False（天然排除）
#     @别人          qq == 别人的号   -> False
# ============================================================


def is_at_me(event) -> bool:
    r"""这条消息里有没有 @机器人自己。"""
    me = str(getattr(event, "self_id", "") or "")
    if not me:
        return False
    try:
        for seg in event.message:
            if getattr(seg, "type", "") != "at":
                continue
            qq = str((getattr(seg, "data", None) or {}).get("qq", ""))
            if qq and qq == me:
                return True
    except Exception:
        pass
    return False


def has_at_all(event) -> bool:
    r"""这条消息里有没有 @全体成员。"""
    try:
        for seg in event.message:
            if getattr(seg, "type", "") != "at":
                continue
            qq = str((getattr(seg, "data", None) or {}).get("qq", ""))
            if qq == "all":
                return True
    except Exception:
        pass
    return False

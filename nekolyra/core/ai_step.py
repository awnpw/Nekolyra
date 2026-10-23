# -*- coding: utf-8 -*-
r"""第 7 段：AI 调用编排 —— `run_ai(inc, ctx, deps)`。

**不 import nonebot，也不 import bot。** AI 实例和超时值都注入。

群聊和私聊的差异（第 10 处）：群聊多传四个参数。

    群聊    memories=mems / knowledge=kb_block / group_id=gid / is_super=…
    私聊    都不传

**`is_super` 用 `str(uid) in SUPERUSERS` 比** —— 不是 `uid in SUPERUSERS`。
SUPERUSERS 里是字符串（从配置读来的），拿 int 比永远 False。
注释里写清楚，免得以后有人"顺手改成 int 比较"。

异常分三种，处理方式各不相同 —— 这是原样搬的，没动：

    asyncio.TimeoutError    记 warn，返回 None（AI 太慢，放弃）
    asyncio.CancelledError  **原样抛**（不能被吞！吞了关不掉进程）
    Exception               记 error，返回 None

**CancelledError 必须重新抛** —— 它是 BaseException 的子类，
但 `except Exception` 抓不到它，所以原来就单独写了一支。
搬的时候保留这个结构。
"""

import asyncio
from typing import Any, Dict, Optional

from nekolyra.core.types import Context, Incoming

__all__ = ["run_ai", "DEPS_NEEDED"]

DEPS_NEEDED = {
    "chat": "async (text, **kw) -> str|None   AI.chat",
    "timeout": "float                          AI_HARD_TIMEOUT",
    "superusers": "set[str]                    SUPERUSERS（字符串集合）",
    "log": "(level, tag, msg) -> None",
}


def _log(deps, level, tag, msg):
    fn = (deps or {}).get("log")
    if fn is None:
        return
    try:
        fn(level, tag, msg)
    except Exception:
        pass


async def run_ai(inc: Incoming, ctx: Context, *, deps) -> Optional[str]:
    r"""调 AI，返回它的回复；失败/超时返回 None。

    `ctx` 是 build_context() 的产物 —— 这个函数只管"怎么调"，
    不管"拿什么调"（那是上一段的事）。
    """
    chat = (deps or {}).get("chat")
    if chat is None:
        return None
    timeout = (deps or {}).get("timeout") or 60.0
    supers = (deps or {}).get("superusers") or ()

    where = ("群%d" % inc.gid) if inc.is_group else ("私聊 %d" % inc.uid)

    kw: Dict[str, Any] = {
        "speaker": ctx.speaker,
        "history": ctx.history,
        "mode": ctx.mode,
        "user_memories": ctx.user_memories,
        "user_name": ctx.speaker.get("name") or str(inc.uid),
        "profile": ctx.profile,
    }
    if inc.is_group:
        # 这四个只有群聊传
        kw["memories"] = ctx.group_memories
        kw["knowledge"] = ctx.knowledge
        kw["group_id"] = inc.gid
        # 注意：SUPERUSERS 里是**字符串**，转成 str 再比 ——
        # 拿 int 比永远 False（这个坑注释在这里，免得被"顺手改回去"）
        kw["is_super"] = str(inc.uid) in supers

    try:
        return await asyncio.wait_for(chat(ctx.text, **kw), timeout=timeout)
    except asyncio.TimeoutError:
        _log(deps, "warn", "AI", "%s 对话硬超时（%.0fs）" % (where, timeout))
        return None
    except asyncio.CancelledError:
        # 必须原样抛 —— 吞掉它进程关不掉
        raise
    except Exception as e:
        _log(deps, "error", "AI", "%s 对话异常: %s: %s"
             % (where, type(e).__name__, e))
        return None

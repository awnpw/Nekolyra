# -*- coding: utf-8 -*-
r"""消息处理流水线 —— **不 import nonebot**。

从 `_on_ai`（220 行）里把三段抽出来：

    第 5 段  触发判断   should_reply()      ← 本文件
    第 6 段  上下文组装 build_context()      ⏳ c4
    第 7 段  AI 编排    run_ai()            ⏳ c5

抽的规则跟前面六步一样：**先原样搬，不顺手改写法**。
`should_reply` 里的判断顺序、默认值、短路方式，跟 bot.py 里那 10 行**逐字一致**
（`talk_value` 的默认 0.0、`reply_to_name` 默认 True、三个条件的与或关系）。
搬家和改逻辑混在一起最难排查 —— 搬 Database 那次就混了。

**唯一多出来的是 `rng`** —— 原来直接调 `random.random()`，没法测。
换成可注入的随机源之后，单测能覆盖"抽中/没抽中"两条路。
"""

import random
from dataclasses import dataclass
from typing import Callable, Optional

from nekolyra.core.types import Incoming

#: build_context 一度打算放这个模块，后来放进了 core/context.py ——
#: 名字别加回来，这个模块里没有它（加了 from ... import * 会炸）。
__all__ = ["TriggerDecision", "should_reply", "TRIGGER_REASONS"]


#: 触发原因 -> 日志里显示的中文。原来散在 `_on_ai` 里写死的三元表达式里。
TRIGGER_REASONS = {
    "at": "被@",
    "name": "提及名字",
    "chance": "主动",
    "cmd": "命令",
    "none": "",
}


@dataclass
class TriggerDecision:
    r"""要不要回这条消息，以及为什么。"""

    reply: bool = False
    reason: str = "none"        # at / name / chance / none
    mentioned_by_name: bool = False
    is_command: bool = False    # 被 @ 且带文字 —— 调用方该先试命令分发

    @property
    def reason_text(self) -> str:
        return TRIGGER_REASONS.get(self.reason, "")


def should_reply(inc: Incoming, *, persona_name: str = "",
                 reply_to_name: bool = True, talk_value: float = 0.0,
                 ai_enabled: bool = True,
                 rng: Optional[Callable[[], float]] = None) -> TriggerDecision:
    r"""第 5 段：判断这条消息要不要交给 AI。

    跟 bot.py 里那段的对应关系（逐条）：

        to_me = event.to_me                                  -> inc.to_me
        if to_me and raw_text: 试命令分发                       -> decision.is_command
        name = cfg_str("persona_name").strip()                -> persona_name
        reply_to_name = cfg_bool("reply_to_name", True)       -> reply_to_name
        mentioned_by_name = bool(name) and reply_to_name
                            and bool(raw_text) and (name in raw_text)
        talk_value = cfg_float("talk_value", 0.0)             -> talk_value
        triggered_by_chance = (not to_me) and (not mentioned_by_name)
                              and (random.random() < talk_value)
        if not (to_me or mentioned_by_name or triggered_by_chance): 不回
        if not AI.enabled: 不回

    **注意 `talk_value` 默认 0.0** —— 也就是说没配的话"主动插话"永不触发。
    这个默认值是刻意的（机器人不该自己找话说），搬的时候没动它。

    纯 @ 机器人（没文字）**算触发** —— 这条消息的 text 可能是空的，
    但 inc.to_me 是 True，所以会回。以前这里跟"是不是空消息"的判断混在一起，
    结果纯 @ 被当成空消息丢掉了，机器人装死（用户实测发现的真实 bug）。
    """
    rnd = rng or random.random

    # 被 @ 且有文字 —— 调用方应该先试命令分发（命令是精确匹配整条消息的）
    is_command = bool(inc.to_me) and bool(inc.text.strip())

    mentioned = (bool(persona_name) and bool(reply_to_name)
                 and bool(inc.text.strip()) and (persona_name in inc.text))
    by_chance = ((not inc.to_me) and (not mentioned)
                 and (rnd() < talk_value))

    if inc.to_me:
        decision = TriggerDecision(reply=True, reason="at",
                                   mentioned_by_name=mentioned,
                                   is_command=is_command)
    elif mentioned:
        decision = TriggerDecision(reply=True, reason="name",
                                   mentioned_by_name=True)
    elif by_chance:
        decision = TriggerDecision(reply=True, reason="chance",
                                   mentioned_by_name=False)
    else:
        return TriggerDecision(reply=False, reason="none",
                               mentioned_by_name=mentioned,
                               is_command=is_command)

    if not ai_enabled:
        # AI 关着就一律不回 —— 但命令分发仍然该走（那不走 AI）。
        return TriggerDecision(reply=False, reason="none",
                               mentioned_by_name=decision.mentioned_by_name,
                               is_command=decision.is_command)
    return decision

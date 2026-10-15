# -*- coding: utf-8 -*-
r"""core 的中立对象 —— **不 import nonebot，也不 import 任何 adapters。**

这一层存在的理由：消息处理流程（_on_ai，220 行）里其实只有 4 个平台名字
（GroupMessageEvent / MessageSegment / bot / event），其余全是"拿值算事"。
把值抽成这两个对象之后，触发判断、上下文组装、AI 编排这三段就能脱离
QQ 协议端 —— 以后换 NapCat、或者加第二个协议端，这三段一行都不用动。

    QQ 事件  ──adapters/qq.py──▶  Incoming  ──core──▶  Outgoing  ──adapters/qq.py──▶ 发送

**只有 Incoming.raw 是平台相关的** —— 它是原始 event，留给"命令分发"
和"插件钩子"那两段用（那两段本来就要透传 event，不算污染）。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = ["Incoming", "Outgoing", "Context"]


@dataclass
class Incoming:
    r"""一条进来的消息，跟平台无关。

    这些字段都是 `_on_ai` 里实实在在用到的 —— 没有一个是"以后可能用得上"
    才放进来的。加字段的时候请保持这个习惯：core 不囤没人用的东西。
    """

    # ---- 谁、在哪 ----
    gid: int = 0                 # 群号；私聊是 0
    uid: int = 0                 # 发消息的人
    nick: str = ""               # 显示名（群名片优先）
    self_id: int = 0             # 机器人自己的号

    # ---- 说了什么 ----
    text: str = ""               # 纯文本（已去掉 @ 段）
    images: List[str] = field(default_factory=list)     # 图片 URL
    kinds: Dict[str, str] = field(default_factory=dict)  # URL -> "sticker"/"image"
    segments: str = ""           # 段类型描述，如 "[@全体] [表情]"

    # ---- 语气 ----
    to_me: bool = False          # 是不是在叫机器人（@ 或提及名字）
    is_group: bool = True

    # ---- 平台相关的那一点 ----
    raw: Any = None              # 原始 event，只给命令分发 / 插件钩子用

    # ---- 便利属性 ----
    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())

    @property
    def has_image(self) -> bool:
        return bool(self.images)

    @property
    def empty(self) -> bool:
        r"""没有文字也没有图。

        注意：**纯 @ 机器人也是"空"** —— 这个判断只描述"有没有内容"，
        要不要回它由 core.should_reply() 决定（那边会把纯 @ 当成"在吗"）。
        这两件事以前混在一处，结果纯 @ 被当成空消息直接丢掉，
        机器人装死（真实 bug，用户实测发现的）。
        """
        return (not self.has_text) and (not self.has_image)

    @property
    def preview(self) -> str:
        r"""日志里显示的那一行。"""
        if self.has_text:
            return self.text[:80]
        if self.has_image:
            n_st = sum(1 for u in self.images
                       if self.kinds.get(u) == "sticker")
            n_im = len(self.images) - n_st
            parts = []
            if n_st:
                parts.append("[表情]" if n_st == 1 else "[表情 x%d]" % n_st)
            if n_im:
                parts.append("[图片]" if n_im == 1 else "[图片 x%d]" % n_im)
            return " ".join(parts)
        if self.to_me:
            return "[@机器人]"
        return self.segments or "(空)"


@dataclass
class Context:
    r"""交给 AI 的一整套上下文。

    字段是按**群聊和私聊的实际差异**定的 —— 并排量过，8 处不同：

        群聊                                私聊
        历史      get_context(gid)           get_private_context(uid)
        群记忆    DB.mem_recent(gid, …)      （没有 —— 所以这里是空 list）
        个人记忆  mem_recent_user(gid, uid)  mem_recent_user(0, uid)
        画像      user_profile_block(gid,…)  user_profile_block(0, …)
        知识库    kb_search(gid, …)          （没有 —— 所以这里是空串）
        mode      "group"                    "private"
        写回历史  push_context(gid, …)       push_private_context(uid, …)
        记忆 key  gid（正数）                 -uid（负数，不跟群号撞）

    **私聊走的是同一套字段，只是群记忆和知识库是空的** —— 不是"私聊另有一套"。
    这样 core 里只有一条流水线，而不是两条长得像的。
    """

    text: str = ""                     # 可能被 enrich_text_with_images 补过
    speaker: Dict[str, Any] = field(default_factory=dict)   # {"name","qq"}
    history: List[Any] = field(default_factory=list)
    group_memories: List[Any] = field(default_factory=list)  # 私聊为空
    user_memories: List[Any] = field(default_factory=list)
    profile: str = ""
    knowledge: str = ""                # 私聊为空
    mode: str = "group"                # "group" / "private"
    mem_key: int = 0                   # gid 或 -uid
    has_img: bool = False

    @property
    def is_group(self) -> bool:
        return self.mode == "group"


@dataclass
class Outgoing:
    r"""机器人要发出去的东西，跟平台无关。

    分成三块是因为它们**发送顺序有讲究**（实测踩过）：
      1. 表情先发（sticker_id）
      2. 语音其次（voice_text）—— 必须已经剥掉 [情绪:xx] / [表情:xx] 标记，
         否则标记会被念出来
      3. 文字最后（parts，可能切成几条）
    """

    sticker_id: Optional[int] = None    # 表情库里那张的 id
    voice_text: Optional[str] = None    # 要发语音的话念这句
    text: str = ""                      # 实际发出去的纯文本
    parts: List[str] = field(default_factory=list)   # 切分后的几条

    # 给写回上下文 / 记忆流水用（那边要记"实际念出去的那句"）
    spoken: str = ""
    sticker_sent: bool = False
    voice_sent: bool = False

    @property
    def anything(self) -> bool:
        return bool(self.parts or self.text or self.voice_text
                    or self.sticker_id is not None)

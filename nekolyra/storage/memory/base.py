# -*- coding: utf-8 -*-
r"""记忆后端的接口 —— SQLite 是默认实现，PostgreSQL / 向量库按同一套接口接。

## 为什么要这层

现在 `nekolyra/storage/db.py` 里有 19 个记忆相关方法，全都直接写 SQLite。
想换 PostgreSQL 或者加向量检索，得改这 19 个方法 + 所有调用点。

有接口之后，换后端 = 新写一个类。

## 分层（这是这次要补的核心）

现在**只有一张 memory 表**，短期 / 长期 / 摘要混在一起，而且没有 TTL。
实际有三种寿命完全不同的东西：

    短期 SHORT    最近几条对话的上下文。        **几小时到几天**，用完就扔。
                  现在是内存里的 get_context() + chat_log 表。

    长期 LONG     从对话里提炼出来的事实。       **长期保留**，但该按重要性衰减。
                  「他 14 号要考科目一」「他喜欢鸣潮」——
                  现在是 memory 表，importance 1~5。

    摘要 SUMMARY  按天/按群的统计与总结。        **永久保留**（体积小、价值高）。
                  现在是 daily_stats / daily_summary。

**三者的清理策略完全不同**，混在一张表里就只能一刀切（要么全留、要么全清）。

## TTL 与清理策略

    SHORT    按天清：超过 short_ttl_days 的删掉。
             对应现有配置 chat_log_keep_days / chatlog_keep_days。

    LONG     按重要性衰减：importance 低的先过期。
             建议：importance 5 -> 永不过期；4 -> 180 天；3 -> 90 天；
                   2 -> 30 天；1 -> 7 天。
             这样"随口一提"的会自动消失，"重要的"会留下。

    SUMMARY  不清理（只按群删）。

    sweep()  由调用方定期调（现在有清理线程，挂在它上面就行）。
             **必须是幂等的** —— 重复调不能删两次东西。

## 关于"向量库接口"

不在这里定义 —— 向量检索是**另一个能力**（不是"存/取记忆"），
接口应该是：

    class MemoryIndex(ABC):
        def index(self, mid: int, text: str) -> None
        def search(self, text: str, k: int = 5) -> List[int]   # 返回 mid

    search() 返回 id，再由 MemoryBackend 取回内容。
    这样"存储"和"检索"分开：可以 SQLite 存 + 向量库检索，
    也可以两个都用同一个后端。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = ["Layer", "MemoryRecord", "MemoryBackend", "MemoryIndex",
           "BACKENDS", "register", "get_backend", "list_backends",
           "TTL_BY_IMPORTANCE"]


class Layer:
    r"""记忆的三种寿命。别用裸字符串 —— 拼错了不会报错，只是查不到。"""
    SHORT = "short"
    LONG = "long"
    SUMMARY = "summary"
    ALL = (SHORT, LONG, SUMMARY)


#: importance -> 保留天数。None = 永不过期。
#: 依据：这是"随口一提"和"值得记住"的分界，改之前先想清楚
#: —— 调小会把用户说过的事忘掉，调大会让注入的提示词越来越长。
TTL_BY_IMPORTANCE: Dict[int, Optional[int]] = {
    5: None,
    4: 180,
    3: 90,
    2: 30,
    1: 7,
}


@dataclass
class MemoryRecord:
    r"""一条记忆。字段跟现有 memory 表对齐 —— **多一个少一个都要想清楚**。

    id 为 None 表示还没入库（add 时由后端分配）。
    """
    content: str = ""
    group_id: int = 0
    user_id: int = 0                 # 0 = 群级记忆（不针对某个人）
    category: str = "其他"
    importance: int = 3
    created_at: str = ""             # ISO 字符串；空 = 由后端填现在
    scope: str = "group"             # group / user
    layer: str = Layer.LONG          # ★ 新增字段：分层
    id: Optional[int] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def ttl_days(self) -> Optional[int]:
        r"""这条记忆该留多久。None = 永久。"""
        if self.layer == Layer.SUMMARY:
            return None
        if self.layer == Layer.SHORT:
            return 3
        return TTL_BY_IMPORTANCE.get(int(self.importance or 3), 90)


class MemoryBackend(ABC):
    r"""记忆后端要提供的东西。

    实现时注意：
    · **方法名跟 db.py 现有的对齐**（mem_add / mem_recent / ...）——
      迁移时调用点不用改，换个实例就行。
    · group_id 用 0 表示"全局/跨群"，负数表示私聊（现有约定：私聊用 -uid）。
    · 所有方法都该**自己吞掉底层异常并记日志**，返回空结果 ——
      记忆取不到不该让整条消息失败。
    """

    name: str = ""

    # ---- 生命周期 ----
    @abstractmethod
    def init(self) -> None:
        r"""建表 / 建索引。**必须幂等** —— 每次启动都会调。"""
        raise NotImplementedError

    # ---- 写 ----
    @abstractmethod
    def add(self, rec: MemoryRecord) -> Optional[int]:
        r"""加一条。返回新 id（拿不到返回 None）。"""
        raise NotImplementedError

    @abstractmethod
    def delete_one(self, mid: int) -> bool:
        raise NotImplementedError

    @abstractmethod
    def clear_group(self, g: int) -> int:
        r"""清某个群的全部记忆，返回删了几条。"""
        raise NotImplementedError

    @abstractmethod
    def clear_user(self, g: int, uid: int) -> int:
        raise NotImplementedError

    # ---- 读 ----
    @abstractmethod
    def recent(self, g: int, limit: int = 10) -> List[MemoryRecord]:
        r"""某个群最近的记忆（按重要性 + 时间排序，不是纯时间倒序）。"""
        raise NotImplementedError

    @abstractmethod
    def recent_user(self, g: int, uid: int, limit: int = 5) -> List[MemoryRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_group(self, g: int, limit: int = 200) -> List[MemoryRecord]:
        raise NotImplementedError

    @abstractmethod
    def count(self, g: int) -> int:
        raise NotImplementedError

    # ---- 清理 ----
    @abstractmethod
    def sweep(self, now: Optional[str] = None, dry_run: bool = False) -> Dict[str, int]:
        r"""按 TTL 清过期记忆。返回 `{层: 删了几条}`。

        **必须幂等** —— 重复调用不能再删东西（按 created_at 判断，不是按计数器）。
        dry_run=True 时只算不删，给管理页预览用。
        """
        raise NotImplementedError

    # ---- 可选 ----
    def stats(self) -> Dict[str, Any]:
        r"""给管理页看的统计：各层条数、最老的、最大的。"""
        return {}

    def health(self) -> tuple:
        r"""`(ok, 说明)`。启动时调一次，连不上就该早点知道。"""
        return True, ""


class MemoryIndex(ABC):
    r"""向量/全文检索。**跟存储分开** —— 可以 SQLite 存 + 向量库检索。"""

    name: str = ""

    @abstractmethod
    def index(self, mid: int, text: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(self, text: str, k: int = 5,
               group_id: Optional[int] = None) -> List[int]:
        r"""返回**记忆 id** 列表（不是内容）—— 内容由 MemoryBackend 取。"""
        raise NotImplementedError

    @abstractmethod
    def remove(self, mid: int) -> None:
        raise NotImplementedError


#: 后端注册表。跟 adapters/providers 一个套路。
BACKENDS: Dict[str, type] = {}


def register(cls):
    r"""登记一个后端。可以当装饰器用。"""
    BACKENDS[cls.name] = cls
    return cls


def get_backend(name: str) -> Optional[type]:
    return BACKENDS.get(str(name or "").strip().lower())


def list_backends() -> List[str]:
    return sorted(BACKENDS)

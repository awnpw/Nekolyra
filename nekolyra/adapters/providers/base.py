# -*- coding: utf-8 -*-
r"""AI provider 的接口定义。

**为什么要有这层**：现在 `AIHandler.reload()` 里用 `if backend == "deepseek" ... else`
硬分派两个后端，而 `raw()` 里写死的是 OpenAI 的协议细节（`{"model","messages","stream":true}`
+ `Authorization: Bearer` + SSE 的 `delta.content` / `delta.reasoning_content`）。

结果就是：**想加一个 OpenAI 兼容的后端（OpenAI 官方、通义、Kimi、硅基流动…），
得去改 `raw()` 里的协议代码** —— 而它们其实一模一样，只是 host 和 model 不同。

抽成 provider 之后，加后端只写一个类：

    class MyProvider(AIProvider):
        name = "myvendor"
        def endpoint(self): return "https://api.myvendor.com/v1/chat/completions"
        ...

**大部分情况连类都不用写** —— 直接用 `openai_compat`，填 host/model/api_key 就行：
OpenAI、智谱、DeepSeek、通义、Kimi、硅基流动、vLLM、LM Studio、one-api… 全是这套协议。

这一层**只管协议**，不管：
    · 限速（_wait_gap）、有没有 user 消息 —— 那是 AIHandler 的事
    · 人格 / 记忆 / 知识库拼提示词 —— 那是 chat() / _build_persona() 的事
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["AIProvider", "AIChunk", "PROVIDER_NAMES", "register", "get_provider",
           "list_providers"]

#: 流式解析出来的一小块。content 是正文，reasoning 是思维链（没有就空）。
AIChunk = Tuple[str, str]

#: name -> 类。providers/__init__.py 会 import 各个模块来填充它。
PROVIDER_NAMES: Dict[str, type] = {}


def register(cls):
    r"""把 provider 类登记进注册表。可以当装饰器用。"""
    PROVIDER_NAMES[cls.name] = cls
    return cls


def get_provider(name: str) -> Optional[type]:
    r"""按名字拿 provider 类；不认识的返回 None（调用方该回退到默认）。"""
    return PROVIDER_NAMES.get(str(name or "").strip().lower())


def list_providers() -> List[str]:
    return sorted(PROVIDER_NAMES)


class AIProvider(ABC):
    r"""一个 AI 后端要提供的东西。**只有这四件事**。

    实现时注意：`endpoint` / `headers` / `payload` 都是**每次请求现算** ——
    因为用户在设置页改了 host / key 之后要立刻生效，不能缓存。
    """

    #: 配置里 `ai_backend` 写什么就用哪个。全小写。
    name: str = ""

    #: 给设置页显示的中文名。
    display_name: str = ""

    #: 这个 provider 需不需要 API Key。Ollama 本地不需要，界面上就不该逼人填。
    needs_key: bool = True

    def __init__(self, host: str = "", model: str = "", api_key: str = "",
                 **opts: Any):
        self.host = str(host or "").rstrip("/")
        self.model = str(model or "").strip()
        self.api_key = str(api_key or "").strip()
        self.opts = dict(opts or {})

    # ---------------- 必须实现 ----------------

    @abstractmethod
    def endpoint(self) -> str:
        r"""对话接口的完整 URL。"""
        raise NotImplementedError

    @abstractmethod
    def headers(self) -> Dict[str, str]:
        r"""请求头。"""
        raise NotImplementedError

    @abstractmethod
    def payload(self, messages: List[Dict[str, Any]], model: str = "",
                stream: bool = True, **kw: Any) -> Dict[str, Any]:
        r"""请求体。"""
        raise NotImplementedError

    @abstractmethod
    def parse_chunk(self, obj: Dict[str, Any]) -> AIChunk:
        r"""把一个 SSE 里解析出来的 JSON 对象变成 (正文, 思维链)。

        没有内容就返回 ("", "")。**不要在这里做累积** —— 累积是调用方的事。
        """
        raise NotImplementedError

    # ---------------- 可选 ----------------

    def models_endpoint(self) -> Optional[str]:
        r"""列出模型的 URL。返回 None 表示这个后端不支持列模型。"""
        return None

    def parse_models(self, data: Any) -> List[str]:
        r"""把 models 接口的响应变成模型名列表。

        OpenAI 格式是 {"data": [{"id": "..."}]}，所以默认实现就能覆盖大多数。
        """
        out: List[str] = []
        if isinstance(data, dict):
            for it in (data.get("data") or data.get("models") or []):
                if isinstance(it, dict):
                    mid = it.get("id") or it.get("name") or it.get("model")
                    if mid:
                        out.append(str(mid))
                elif isinstance(it, str):
                    out.append(it)
        elif isinstance(data, list):
            for it in data:
                if isinstance(it, str):
                    out.append(it)
                elif isinstance(it, dict) and it.get("id"):
                    out.append(str(it["id"]))
        return out

    def done_marker(self) -> str:
        r"""流结束的标记。OpenAI 系是 "[DONE]"。"""
        return "[DONE]"

    def __repr__(self) -> str:
        return "<%s host=%s model=%s>" % (type(self).__name__, self.host,
                                          self.model)

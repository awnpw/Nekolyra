# -*- coding: utf-8 -*-
r"""AI provider 注册表。

加一个后端 = 在这里 import 一下 + 写一个类（或者干脆复用 openai_compat）。
**AIHandler 那边不用改** —— 它只认 `AIProvider` 这个接口。
"""

from typing import List

from nekolyra.adapters.providers.base import (  # noqa: F401
    PROVIDER_NAMES,
    AIChunk,
    AIProvider,
    get_provider,
    list_providers,
    register,
)

# ---- 具体实现：import 就会自动登记 ----
from nekolyra.adapters.providers.openai_compat import (  # noqa: F401
    OpenAICompatProvider,
)

__all__ = [
    "AIProvider",
    "AIChunk",
    "PROVIDER_NAMES",
    "register",
    "get_provider",
    "list_providers",
    "make_provider",
    "DEFAULT_PROVIDER",
]

#: 配置里 ai_backend 没写或写错时用哪个
DEFAULT_PROVIDER = "openai"


def make_provider(name: str, host: str = "", model: str = "",
                  api_key: str = "", **opts):
    r"""按名字造一个 provider 实例。

    不认识的 name 返回 None（调用方自己决定回退还是报错 —— 不要在这里
    偷偷换一个，否则用户配错了却看不出，只会觉得"改了没反应"）。
    """
    cls = get_provider(name)
    if cls is None:
        return None
    return cls(host=host, model=model, api_key=api_key, **opts)


def provider_choices() -> List[dict]:
    r"""给设置页的下拉框用：[{value, label, needs_key}]。"""
    out = []
    for n in list_providers():
        cls = PROVIDER_NAMES[n]
        out.append({
            "value": n,
            "label": getattr(cls, "display_name", "") or n,
            "needs_key": bool(getattr(cls, "needs_key", True)),
        })
    return out

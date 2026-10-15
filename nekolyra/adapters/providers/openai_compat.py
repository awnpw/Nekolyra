# -*- coding: utf-8 -*-
r"""OpenAI 兼容协议的 provider —— **一个类覆盖一大片后端**。

这些全都用同一套协议（`POST {base}/v1/chat/completions`、`Bearer` 鉴权、
SSE 的 `choices[0].delta.content`）：

    OpenAI / Azure OpenAI
    智谱 GLM（open.bigmodel.cn/api/paas/v4）
    DeepSeek / 通义千问 / Kimi / 豆包 / 百川
    硅基流动 / OpenRouter / together.ai
    本地：vLLM / LM Studio / text-generation-webui / one-api 网关
    Ollama 的兼容层（/v1）

所以"加一个后端"绝大多数时候**不是写代码，是填三个配置**：
`ai_backend=openai`、`openai_host=...`、`openai_model=...`。

真正需要另写 provider 的，是协议不一样的那些 —— 比如 Claude 的
`/v1/messages` + `content_block_delta`，或者 Ollama 原生 `/api/chat`。
"""

from typing import Any, Dict, List, Optional

from nekolyra.adapters.providers.base import AIChunk, AIProvider, register

__all__ = ["OpenAICompatProvider"]


def _join(base: str, path: str) -> str:
    r"""拼 URL，兼容 base 已经带 /v1、/v4 的情况。

    原来的 AIHandler.endpoint() 就是这么干的（判断结尾是不是 /v1 或 /v4），
    这里保留同样的行为 —— 因为智谱的 base 是 `.../api/paas/v4`，
    再拼一个 `/v1` 就错了。
    """
    b = str(base or "").rstrip("/")
    if not b:
        return path
    for suff in ("/v1", "/v4", "/v3", "/v2", "/api"):
        if b.endswith(suff):
            return b + path
    return b + "/v1" + path


@register
class OpenAICompatProvider(AIProvider):
    r"""任何 OpenAI 兼容端点。"""

    name = "openai"
    display_name = "OpenAI 兼容（DeepSeek / 智谱 / 通义 / Kimi / vLLM …）"
    needs_key = True

    #: 默认 host —— 没配的时候用它。**故意留空**：
    #: 这类端点没有一个"通用默认"，必须让用户填。
    DEFAULT_HOST = ""

    def endpoint(self) -> str:
        return _join(self.host, "/chat/completions")

    def models_endpoint(self) -> Optional[str]:
        return _join(self.host, "/models")

    def headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = "Bearer " + self.api_key
        return h

    def payload(self, messages: List[Dict[str, Any]], model: str = "",
                stream: bool = True, **kw: Any) -> Dict[str, Any]:
        p: Dict[str, Any] = {
            "model": str(model or self.model),
            "messages": messages,
            "stream": bool(stream),
        }
        # 透传额外参数（temperature / max_tokens / top_p …）。
        # 不写死默认值 —— 各家的合法范围不一样，硬塞会让请求被拒。
        for k, v in (kw or {}).items():
            if v is not None:
                p[k] = v
        return p

    def parse_chunk(self, obj: Dict[str, Any]) -> AIChunk:
        r"""OpenAI 的流：choices[0].delta.content / .reasoning_content。

        reasoning_content 是 DeepSeek-R1 / GLM 这类"会想一下"的模型加的字段，
        不在标准里，但很常见 —— 原来的代码就在读它（管理页的「AI思维链」）。
        """
        choices = obj.get("choices") or []
        if not choices:
            return "", ""
        first = choices[0]
        # 外部数据不可信: 网关报错时 choices[0] 可能是 None / str,
        # 直接 .get 会抛 AttributeError, 害得整次流式请求作废重发 (白花额度)。
        if not isinstance(first, dict):
            return "", ""
        delta = first.get("delta") or {}
        c = delta.get("content") or ""
        rc = delta.get("reasoning_content") or ""
        # 有些实现（少数网关）走非流式字段
        if not c and not rc:
            msg = first.get("message")
            if isinstance(msg, dict):
                c = msg.get("content") or ""
                rc = msg.get("reasoning_content") or ""
        return str(c), str(rc)

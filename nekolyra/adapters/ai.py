# -*- coding: utf-8 -*-
r"""AI 后端适配器（OpenAI 兼容：智谱 / DeepSeek / Ollama）。

从 bot.py 里整块搬出来的 —— 只是搬家，逻辑一行没改。

跟主程序的耦合有 9 个名字，全部通过 configure() **重绑**到本模块的同名全局：

    CFG  log  cfg_str  cfg_bool  cfg_float  get_http
    _admin_prompt_hint  _sticker_prompt_hint  _voice_prompt_hint

重绑而不是改调用点的原因：类里的代码可以保持**一字不动**，
搬家和改逻辑就不会混在一起（那次搬 Database 时改了 log( / cfg_bool( 的写法，
虽然成功了，但"搬家"和"改代码"混在一起不好排查）。

**没 configure 之前用不了**（重绑前是占位的空实现，不会崩，但也查不到东西）。
"""

import asyncio
import json
import random
import re
import time
from datetime import datetime

from nekolyra.adapters.providers import DEFAULT_PROVIDER, make_provider

__all__ = ["AIHandler", "configure", "is_configured"]

#: 老配置值 -> (provider 名字, host 键, model 键, key 键, 默认 host, 默认 model)
#:
#: 为什么要有这张表：以前 ai_backend 只认 "deepseek" / "ollama" 两个值，
#: 对应的 host/model/key 分散在 deepseek_* / ollama_* / ai_model 三套键前缀下。
#: 换成 provider 名字之后，**老配置必须继续能用** —— 否则用户升级完
#: AI 直接不通，而且报的是"连不上"，看不出是配置键换了。
#:
#: 两个老值都映射到 openai provider，因为它们本来就是同一套协议，
#: 区别只在 host / model / key（Ollama 自己有 /v1 兼容层）。
_LEGACY_BACKENDS = {
    "deepseek": ("openai", "deepseek_api_host", "deepseek_model",
                 "deepseek_api_key",
                 "https://open.bigmodel.cn/api/paas/v4", "glm-4.7-flash"),
    "ollama": ("openai", "ollama_host", "ai_model", "ollama_api_key",
               "http://localhost:11434", "qwen3:4b"),
}

# ---- 注入点（重绑前是安全的占位）----
CFG = {}


def log(level, tag, msg):
    return None


def cfg_str(key, default=""):
    return default


def cfg_bool(key, default=False):
    return default


def cfg_float(key, default=0.0):
    return default


def get_http():
    raise RuntimeError("AIHandler 还没 configure()，拿不到 http 客户端")


def _admin_prompt_hint(group_id=None):
    return ""


def _sticker_prompt_hint(group_id=None):
    return ""


def _voice_prompt_hint(group_id=None):
    return ""


_configured = False


def is_configured():
    return _configured


def configure(CFG_=None, log_=None, cfg_str_=None, cfg_bool_=None,
              cfg_float_=None, get_http_=None, admin_hint=None,
              sticker_hint=None, voice_hint=None):
    """由主程序在创建 AIHandler 之前调用一次。

    参数带下划线是为了跟要重绑的全局名区分开（重绑用的还是原名）。
    """
    global CFG, log, cfg_str, cfg_bool, cfg_float, get_http
    global _admin_prompt_hint, _sticker_prompt_hint, _voice_prompt_hint
    global _configured
    if CFG_ is not None:
        CFG = CFG_
    if log_ is not None:
        log = log_
    if cfg_str_ is not None:
        cfg_str = cfg_str_
    if cfg_bool_ is not None:
        cfg_bool = cfg_bool_
    if cfg_float_ is not None:
        cfg_float = cfg_float_
    if get_http_ is not None:
        get_http = get_http_
    if admin_hint is not None:
        _admin_prompt_hint = admin_hint
    if sticker_hint is not None:
        _sticker_prompt_hint = sticker_hint
    if voice_hint is not None:
        _voice_prompt_hint = voice_hint
    _configured = True


def _parse_plan(text):
    r"""从规划模型的输出里抠出 JSON 策略。抠不到返回 None。

    规划模型可能不听话（加解释、包代码块、输出半截 JSON）——
    这些都不算错误，只是"这轮没有策略"，调用方照常生成。
    """
    s = str(text or "").strip()
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        d = json.loads(s[i:j + 1])
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    out = {}
    if "reply" in d:
        out["reply"] = bool(d.get("reply"))
    for k in ("tone", "length"):
        v = str(d.get(k) or "").strip()
        if v:
            out[k] = v[:12]
    for k in ("emoji", "sticker", "kb"):
        if k in d:
            out[k] = bool(d.get(k))
    return out or None


# ---- AI 请求限流用的共享状态（按进程，不区分会话）----
_RATE_LOCK = asyncio.Lock()
_RATE_TIMES = __import__("collections").deque()
# 全局 429 冷却：撞到限流后所有请求一起安静，直到这个时间点。
# 渠道限流是分钟级的，「3 秒后重试」根本不够，反而把配额继续烧光。
_COOLDOWN_UNTIL = [0.0]
# 被限流过的模型 -> 恢复时间戳。撞过 429 的模型在一段时间内直接跳过，
# 免得每条消息都先白撞一次 429、白等一秒（实测 flash 模型持续被限流）。
_MODEL_DOWN_UNTIL = {}
# 429 时依次换用的模型（限额按 model 算，不同模型是不同配额池）。
# 空 = 只用配置里那个模型。可以在设置里用 ai_fallback_models 覆盖。
_DEFAULT_FALLBACK = ["deepseek-v4-pro-0813", "glm-5.3", "kimi-k2.6",
                     "qwen3.8-27b", "intern-s2", "minimax-m3"]


def _fallback_models():
    """429 时依次换用的模型列表。"""
    try:
        raw = cfg_str("ai_fallback_models").strip()
        if raw:
            out = [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]
            if out:
                return out
    except Exception:
        pass
    return list(_DEFAULT_FALLBACK)


class AIHandler:
    """AI 后端：支持流式接收，主通道/辅助通道分离限速"""

    def __init__(self):
        self.backend = "deepseek"
        self.provider = None
        self.provider_name = ""
        self.host = ""
        self.model = ""
        self.api_key = ""
        self.enabled = False
        self._last_call = 0.0
        self._last_aux_call = 0.0
        # 该端点是否已证明「不接受关思考参数」—— 记住它，之后别再白挨一次 400
        self._think_unsupported = False
        self.reload()

    def reload(self):
        r"""按配置建 provider。**老配置值照旧能用**（见 _LEGACY_BACKENDS）。"""
        raw_backend = cfg_str("ai_backend", DEFAULT_PROVIDER).lower().strip()

        if raw_backend in _LEGACY_BACKENDS:
            # 老值：走映射表，键前缀也跟着老的那套
            _pname, _hk, _mk, _kk, _dh, _dm = _LEGACY_BACKENDS[raw_backend]
            self.backend = raw_backend          # 日志里照旧显示 deepseek / ollama
            self.provider_name = _pname
            host = cfg_str(_hk, _dh).rstrip("/")
            model = cfg_str(_mk, _dm).strip() or _dm
            key = cfg_str(_kk, "ollama").strip() if raw_backend == "ollama" \
                else cfg_str(_kk).strip()
        else:
            # 新值：provider 名字 + <provider>_host / _model / _api_key
            self.backend = raw_backend
            self.provider_name = raw_backend
            host = cfg_str(raw_backend + "_host").rstrip("/")
            model = cfg_str(raw_backend + "_model").strip()
            key = cfg_str(raw_backend + "_api_key").strip()
            if not host:
                # 没配 host 就别硬来 —— 让 enabled 变 False，界面会显示未启用
                host = ""

        self.host = host
        self.model = model
        self.api_key = key
        self._think_unsupported = False
        # 多 Key 池：配置里用逗号 / 分号 / 换行分隔多个 key，撞 429 时自动换下一个。
        # 上游渠道是共享的，单个 key 被限流很常见，有备用 key 就能顶过去。
        _pool = []
        for _src in (key, cfg_str("deepseek_api_key"), cfg_str("vision_api_key")):
            for _one in _src.replace(chr(10), ",").replace(";", ",").split(","):
                _one = _one.strip()
                # 滤掉占位值和重复项（ollama 的 key 常写成 "ollama"，不是真 key）
                if len(_one) < 12 or _one in _pool or _one.lower() == "ollama":
                    continue
                _pool.append(_one)
        self._key_pool = _pool
        self._key_idx = 0

        self.provider = make_provider(self.provider_name, host=host,
                                      model=model, api_key=key)
        if self.provider is None:
            # 不认识的 provider 名：**不偷偷回退**，只记下来。
            # 静默换一个的话，用户会以为"改了没反应"，其实是名字打错了。
            log("warn", "AI",
                "不认识的 ai_backend=%r，AI 将不可用。可选：openai / deepseek / ollama"
                % raw_backend)
        self.enabled = (cfg_bool("ai_enabled", True) and bool(self.host)
                        and self.provider is not None)

    def endpoint(self):
        r"""委托给 provider。没有 provider 时退回老写法（保证不返回空串）。"""
        if self.provider is not None:
            return self.provider.endpoint()
        base = self.host
        if base.endswith("/v1") or base.endswith("/v4"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def models_endpoint(self):
        if self.provider is not None:
            return self.provider.models_endpoint()
        base = self.host
        if base.endswith("/v1") or base.endswith("/v4"):
            return f"{base}/models"
        return f"{base}/v1/models"

    async def _wait_gap(self, use_gap):
        if use_gap:
            lo = cfg_float("ai_min_gap", 0.0)
            hi = cfg_float("ai_max_gap", 0.0)
            gap = random.uniform(min(lo, hi), max(lo, hi))
            if gap > 0:
                elapsed = time.time() - self._last_call
                if elapsed < gap:
                    await asyncio.sleep(gap - elapsed)
            self._last_call = time.time()
        else:
            aux_gap = 1.0
            elapsed = time.time() - self._last_aux_call
            if elapsed < aux_gap:
                await asyncio.sleep(aux_gap - elapsed)
            self._last_aux_call = time.time()

    @staticmethod
    def _has_user_message(messages):
        for m in messages:
            if m.get("role") != "user":
                continue
            content = m.get("content")
            if isinstance(content, str):
                if content.strip():
                    return True
            elif isinstance(content, (list, tuple)) and content:
                return True
        return False

    async def _rate_gate(self):
        """全局限流：每分钟最多 N 次请求。

        上游给的额度是 50 次/分钟（RPM），不是"总共能用多少"——
        额度还剩 90% 但每分钟超过 50 次就会 429。
        一条群消息可能触发好几次调用（主对话 + 规划 + 记忆分析 + 打标），
        不挡一下很容易撞线。这里挡在唯一出口 raw() 前面，主动排队等，
        比事后 429 重试友好得多。
        """
        try:
            # 这个模块里没有 cfg_int（导入清单和 configure 注入都没有），
            # 以前写 cfg_int 会抛 NameError 被吞掉，配置项形同虚设。
            limit = int(cfg_float("ai_rpm_limit", 45) or 45)
        except Exception:
            limit = 45
        if limit <= 0:
            return
        # 先看全局冷却：撞过 429 就一起等，别再往上打
        _cd = _COOLDOWN_UNTIL[0]
        if _cd > time.time():
            _w = _cd - time.time()
            log("warn", "AI", "上游限流冷却中，等 %.0f 秒再发" % _w)
            await asyncio.sleep(_w)
        while True:
            async with _RATE_LOCK:
                now = time.time()
                while _RATE_TIMES and now - _RATE_TIMES[0] > 60.0:
                    _RATE_TIMES.popleft()
                if len(_RATE_TIMES) < limit:
                    _RATE_TIMES.append(now)
                    return
                wait = 60.0 - (now - _RATE_TIMES[0]) + 0.3
            if wait > 0.5:
                log("warn", "AI", "每分钟请求数已达上限（%d），排队等 %.1f 秒" % (limit, wait))
            await asyncio.sleep(max(wait, 0.5))

    async def raw(self, messages, timeout=120.0, use_gap=True, model=None,
                  _retry=0, _no_think=False):
        r"""裸调用。model 传了就临时换一个模型跑这一条 ——
        内部那些「想一下」的活（记忆分析、情绪打标）可以用规划模型，
        不用跟聊天抢同一个。不传就还是 self.model。
        """
        # 无效请求先挡掉：以前这两个检查排在限流/间隔之后，
        # 空消息也会先占掉一个配额、先等两秒，纯浪费。
        if not self.enabled:
            return None
        if not self._has_user_message(messages):
            log("warn", "AI", "消息列表中没有有效的用户消息，跳过调用")
            return None

        # 限流排队和请求间隔只在「本次用户请求的第一次尝试」生效。
        # 重试是同一个请求的延续，再占一次配额、再等一次间隔只会让用户多等
        # 好几秒（以前撞一次 429 光排队和间隔就要多花 4~6 秒）。
        if _retry == 0:
            try:
                await self._rate_gate()
            except Exception:
                pass
            await self._wait_gap(use_gap)

        _mdl = str(model or "").strip() or self.model
        # 主模型刚被限流过就直接用能用的那个，不再每次都白撞一次
        if model is None and _retry == 0:
            _until = _MODEL_DOWN_UNTIL.get(_mdl, 0)
            if _until > time.time():
                _pool = _fallback_models()
                if _pool:
                    log("warn", "AI", "模型 %s 还在限流冷却期，直接用 %s"
                        % (_mdl, _pool[0]))
                    _mdl = _pool[0]

        # 「想多久」——这个模型默认会先吐一大段思维链再回答，
        # 首字因此慢到十几秒（实测 11s / 18s / 63s）。
        # 实测同一句话：不加参数 2.6s、reasoning_effort=none 1.2s 且直接给正文。
        #
        # 配置里本来就有 reasoning_effort，但从来没人读它 —— 所以一直用默认。
        # 空值 = 用 none（快）；想让它多想就填 low / medium / high。
        _effort = str(cfg_str("reasoning_effort", "") or "").strip().lower()
        if _effort in ("", "off", "no", "false"):
            _effort = "none"
        _extra = {}
        # _no_think：上一次带「关思考」参数被端点拒了，这次就一个都别带。
        # _think_unsupported：这个端点已经被证明不接受这类参数，以后直接不带，
        # 免得每条消息都先白挨一个 HTTP 400 再重试。
        _skip_think = _no_think or self._think_unsupported
        if not _skip_think and _effort and _effort != "default":
            _extra["reasoning_effort"] = _effort
        # 关掉思考的另一个常见写法（有些端点认这个）
        if not _skip_think and _effort == "none":
            _extra["enable_thinking"] = False

        if self.provider is not None:
            # 协议细节交给 provider：OpenAI 兼容是
            # {"model","messages","stream"} + Bearer，
            # 换成 Claude 之类的就是另一套 —— AIHandler 不该关心。
            payload = self.provider.payload(messages, model=_mdl, stream=True,
                                            **_extra)
            headers = self.provider.headers()
        else:
            # provider 不可用（名字不认识）：走老路径，至少别让 AI 整个挂掉
            payload = {"model": _mdl, "messages": messages, "stream": True,
                       **_extra}
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        # 注意：这里不再按 key 轮换。上游的 429 是「rate limit reached for
        # MODEL」，按模型算配额，换 key 一点用没有，只会多烧一次请求。
        # 撞限流的正确做法是换模型（见下面 429 分支）。

        full_text = []
        reasoning_text = []
        _t_call = time.time()
        _t_first = None
        try:
            client = get_http()
            async with client.stream("POST", self.endpoint(), json=payload,
                                     headers=headers, timeout=timeout) as r:
                if r.status_code >= 400:
                    body = (await r.aread()).decode("utf-8", errors="ignore")
                    _low = body.lower()
                    # 有些模型「始终思考」，端点会直接拒掉 reasoning_effort /
                    # enable_thinking（实测 deepseek 网关 code 1210：
                    # 「该模型始终思考，不支持关闭思考」）。
                    # 以前这里直接 return None —— 表现就是「机器人不回话」。
                    # 现在去掉这两个参数重试一次：慢一点，但能说话。
                    if (r.status_code == 400 and not _no_think and _extra and
                            ("思考" in body or "thinking" in _low
                             or "reasoning" in _low or '"1210"' in body)):
                        self._think_unsupported = True
                        log("warn", "AI",
                            f"[{self.backend}] 该端点不接受「关思考」参数，"
                            "记下来：以后不再发这两个参数，去掉后重试一次")
                        return await self.raw(messages, timeout=timeout,
                                              use_gap=False, model=model,
                                              _retry=_retry, _no_think=True)
                    # 429（每分钟次数/渠道限流）和 5xx：等一会儿重试，别直接判死。
                    # 这条路径是「状态码直连返回」，以前只在 except 里重试，
                    # 所以 429 永远不走重试 —— 群友看到的就是她突然不回话。
                    if r.status_code in (429, 500, 502, 503, 504) and _retry < 2:
                        # 429 的错误原文是「rate limit reached for MODEL」——
                        # 限额按模型算，同一渠道换 key 完全没用（所以别再换 key）。
                        # 不同模型是不同配额池：立刻换一个模型重试，成功率最高。
                        _w = 1.0
                        if r.status_code == 429:
                            _pool = _fallback_models()
                            _MODEL_DOWN_UNTIL[_mdl] = time.time() + 180.0
                            if _pool:
                                _next = _pool[_retry % len(_pool)]
                                log("warn", "AI", "[%s] 模型 %s 被限流，换 %s 重试"
                                    "（%s 冷却 3 分钟）"
                                    % (self.backend, _mdl, _next, _mdl))
                                return await self.raw(messages, timeout=timeout,
                                                      use_gap=False, model=_next,
                                                      _retry=_retry + 1,
                                                      _no_think=_no_think)
                            _COOLDOWN_UNTIL[0] = time.time() + 12.0
                            _w = 12.0
                        else:
                            _w = (3.0, 8.0)[min(_retry, 1)]
                            log("warn", "AI", "[%s] HTTP %s（上游繁忙），%.0f 秒后重试"
                                % (self.backend, r.status_code, _w))
                        await asyncio.sleep(_w)
                        return await self.raw(messages, timeout=timeout,
                                              use_gap=False, model=model,
                                              _retry=_retry + 1,
                                              _no_think=_no_think)
                    log("error", "AI", f"[{self.backend}] HTTP {r.status_code}: {body[:200]}")
                    if r.status_code in (400, 404, 422) and "model" in _low:
                        log("error", "AI",
                            f"[{self.backend}] 上面这条像是「模型名不被该后端接受」——"
                            f"去「设置 → AI」把它改成该后端列表里的；当前配的是 {_mdl}")
                    return None

                async for line in r.aiter_lines():
                    # 空行直接跳过。以前这里是「not line 之后再判 line.strip()」
                    # —— not line 之后 strip() 必然为空，_t_first 永远不赋值，
                    # 「首字」那项指标一直在打总耗时，看不出到底是慢还是卡在别处。
                    if not line:
                        continue
                    if line.startswith("data:"):
                        chunk = line[5:].strip()
                    elif line.startswith("{"):
                        chunk = line.strip()
                    else:
                        continue
                    if not chunk:
                        continue
                    if chunk == (self.provider.done_marker()
                                 if self.provider is not None else "[DONE]"):
                        break
                    try:
                        obj = json.loads(chunk)
                    except Exception:
                        continue
                    if self.provider is not None:
                        c, rc = self.provider.parse_chunk(obj)
                    else:
                        choices = obj.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        c = delta.get("content")
                        rc = delta.get("reasoning_content")
                    if (c or rc) and _t_first is None:
                        # 第一个真正有内容的块才算「首字」（思维链也算 ——
                        # 用户感知到的等待就是这一段）
                        _t_first = time.time() - _t_call
                    if c:
                        full_text.append(c)
                    if rc:
                        reasoning_text.append(rc)

            # 流读完了但一个字都没拿到 —— 也算失败，重试一次
            if _retry < 1 and not full_text and not reasoning_text:
                log("warn", "AI", "第 1 次没拿到内容，重试一次")
                return await self.raw(messages, timeout=timeout,
                                      use_gap=False, model=model,
                                      _retry=_retry + 1)

            reasoning = "".join(reasoning_text).strip()
            if reasoning:
                log("mem", "AI思维链", reasoning[:200] + ("..." if len(reasoning) > 200 else ""))
            _dt = time.time() - _t_call
            _n = len("".join(full_text))
            log("info", "AI", "%s 首字 %.1fs | 总 %.1fs | %d 字"
                % (self.backend, _t_first or _dt, _dt, _n))
            return "".join(full_text).strip()
        except asyncio.CancelledError:
            # 机器人自己在关闭/重启 —— 不能吞，也不能重试
            raise
        except Exception as e:
            # 免费端点偶发超时很常见（实测 ReadTimeout 会让机器人静默）。
            # **只重试"什么都没收到"的** —— 已经拿到内容的不重试，
            # 否则会把同一段话再说一遍，或者发出两截。
            _msg = str(e)
            _limited = ("429" in _msg or "rate_limit" in _msg
                        or "rate limit" in _msg.lower())
            _server = any(x in _msg for x in ("500", "502", "503", "504"))
            # 限流/上游抽风：等一会儿再试，别立刻把错误甩给用户。
            # 实测 429 的 "Channel rate limit reached" 通常几秒后就恢复。
            if not full_text and not reasoning_text:
                # 限流：和状态码分支保持一致 —— 换模型，不等
                if _limited and _retry < 2:
                    _MODEL_DOWN_UNTIL[_mdl] = time.time() + 180.0
                    _pool = _fallback_models()
                    if _pool:
                        _next = _pool[_retry % len(_pool)]
                        log("warn", "AI", "[%s] 模型 %s 被限流（异常路径），换 %s 重试"
                            % (self.backend, _mdl, _next))
                        return await self.raw(messages, timeout=timeout,
                                              use_gap=False, model=_next,
                                              _retry=_retry + 1,
                                              _no_think=_no_think)
                # 上游 5xx / 超时：短等重试
                _max_retry = 2 if _server else 1
                if _retry < _max_retry:
                    _wait = (3.0, 8.0)[min(_retry, 1)] if _server else 1.5
                    log("warn", "AI", "第 %d 次失败（%s%s），%.0f 秒后重试"
                        % (_retry + 1, type(e).__name__,
                           "，上游错误" if _server else "", _wait))
                    await asyncio.sleep(_wait)
                    return await self.raw(messages, timeout=timeout,
                                          use_gap=False, model=model,
                                          _retry=_retry + 1)
            log("error", "AI", f"[{self.backend}] {type(e).__name__}: {e}")
            return None

    def _build_persona(self, mode="group", chat_key=""):
        name = cfg_str("persona_name").strip()
        identity = cfg_str("persona_identity").strip()
        behavior = cfg_str("persona_behavior").strip()
        speech = cfg_str("persona_speech").strip()
        # 按会话覆盖：只覆盖填了的项，没填的继续用全局。
        # 这样「只想让某个群说话简短点」就只填 speech，不用重写整份人格。
        _ov = {}
        try:
            _all = CFG.get("persona_overrides")
            if isinstance(_all, dict) and chat_key:
                _one = _all.get(str(chat_key))
                if isinstance(_one, dict):
                    _ov = _one
        except Exception:
            _ov = {}
        if _ov:
            _nm = str(_ov.get("name") or "").strip()
            _id = str(_ov.get("identity") or "").strip()
            _bh = str(_ov.get("behavior") or "").strip()
            _sp = str(_ov.get("speech") or "").strip()
            if _nm:
                name = _nm
            if _id:
                identity = _id
            if _bh:
                behavior = _bh
            if _sp:
                speech = _sp
        parts = []
        # ---- 当前时间 ----
        #
        # 模型自己不知道今天几号，而记忆和历史里全是日期。不给它"现在"，
        # 它就会把记忆里背下来的日期当成今天 —— 实测：昨天是 14 号，
        # 它回答「14号。科目一，还没考。」的时候并不知道那天就是 14 号，
        # 只是在照搬记忆里那条「14号要考科目一」。
        #
        # 每次调用现算（提示词本来就是每条消息重新拼的，不缓存）。
        #
        # **千万不要挪到别处去** —— 时间这东西只要被缓存一次就等于没有：
        #   ✗ 写进 config.json        -> 永远是配置那天的日期
        #   ✗ 写进 persona_identity   -> 用户手填的人格，改了才变
        #   ✗ 启动时算一次存到变量     -> 机器人跑一个月就错一个月
        #   ✓ 每次拼提示词时现算       <- 就是这里
        # 所以这段的**位置**比它的内容更容易出错。要动它之前先跑一遍：
        #   连续调两次 _build_persona，中间隔一分钟，看「【当前时间】」那行变不变。
        #
        # 光给日期不够，还得说清楚**怎么用** —— 否则它当背景信息忽略掉，
        # 继续照搬记忆里的说法。
        try:
            _now = datetime.now()
            _wd = "一二三四五六日"[_now.weekday()]
            parts.append(
                "【当前时间】%s 星期%s %02d:%02d\n"
                "以上是此刻的真实时间。记忆和历史里出现的日期，都要跟它"
                "对照着说 —— 过去的就说过去了，未来的才说还没到。"
                "不要把记忆里记下的某个日期当成今天。"
                % (_now.strftime("%Y年%m月%d日"), _wd, _now.hour, _now.minute))
        except Exception:
            pass
        if name:
            parts.append(f"你的名字是「{name}」。")
        if identity:
            parts.append(f"【人格设定】{identity}")
        if behavior:
            parts.append(f"【行为准则】{behavior}")
        if speech:
            parts.append(f"【表达风格】{speech}")
        parts.append(
            "【硬性铁律】\n"
            "1. 死死盯住每条消息的发送者标识，严禁张冠李戴。\n"
            "2. 只针对当前跟你说话的那个人回答。\n"
            "3. 不要在回复里 @ 任何人。\n"
            "4. 不要提及其他群成员的昵称或 QQ。\n"
            "5. 不要输出括号说明、旁白、内心戏。\n"
            "6. 严禁提及自己是 AI、机器人或系统。\n"
            "7. 如果消息里有[图片内容]前缀，说明是别人发的图，描述已经是你看过的，可以自然回应。")
        if mode != "group":
            parts[-1] = (
                "【硬性铁律】\n"
                "1. 不要在回复里 @ 对方。\n"
                "2. 不要输出括号说明、旁白、内心戏。\n"
                "3. 严禁提及自己是 AI、机器人或系统。\n"
                "4. 如果消息里有[图片内容]前缀，说明是别人发的图，描述已经是你看过的，可以自然回应。")
        return "\n\n".join(parts)

    async def chat(self, user_msg, speaker=None, history=None, memories=None,
                   mode="group", knowledge=None, group_id=None, is_super=False,
                   user_memories=None, user_name="", profile=None,
                   plan_hint=""):
        if not self.enabled:
            return None
        # 会话键：群聊 g:<群号>，私聊 u:<QQ号>。
        # _build_persona 拿它去 persona_overrides 里找这个会话的覆盖项。
        _ck = ""
        try:
            if mode == "group" and group_id:
                _ck = "g:%d" % int(group_id)
            elif mode != "group" and speaker and speaker.get("qq"):
                _ck = "u:%s" % str(speaker.get("qq")).strip()
        except Exception:
            _ck = ""
        sys_p = self._build_persona(mode, _ck)
        # 规划模型的产出：一行「本轮策略」。没有就什么都不加。
        if plan_hint:
            sys_p += "\n\n" + plan_hint
        if mode == "group" and group_id is not None:
            _sh = _sticker_prompt_hint(group_id)
            if _sh:
                sys_p += _sh
            _vh = _voice_prompt_hint(group_id)
            if _vh:
                sys_p += "\n\n" + _vh
            sys_p += "\n\n" + _admin_prompt_hint(is_super)
        if speaker and speaker.get("name"):
            sys_p += (f"\n\n【当前正在跟你说话的人】\n"
                      f"昵称：{speaker['name']}\nQQ：{speaker.get('qq', '未知')}")
            sys_p += (
                "\n\n【群聊记录的格式，务必看清说话人】\n"
                "历史里每条消息开头的 [昵称(QQ)] 是**那条消息的说话人**，括号里是 QQ 号。\n"
                "只有最后一条是现在这个人说的，前面那些是群里其他人的发言。\n"
                "- 回复只针对最后这条的说话人；不要把他没说过的话算到他头上。\n"
                "- 提到别人说过的话时，说清是谁说的（例如「刚才洛说……」），不要张冠李戴。\n"
                "- 两个人昵称一样时看括号里的 QQ 号区分。"
            )
        # 用户画像：bot 自己数据库里的客观统计。有了它，"我是谁""我常来吗"
        # 这类问题才答得上 —— 否则模型只看得到当场这一句昵称。
        if profile:
            sys_p += "\n\n" + profile
        # 知识库优先于长期记忆：它是群友明确整理过的准确信息
        if knowledge:
            sys_p += "\n\n" + knowledge
        if memories:
            lines = [f"- {m.get('content','').strip()}" for m in memories if m.get("content", "").strip()]
            if lines:
                sys_p += "\n\n【你记住的关于本群的历史】\n" + "\n".join(lines)
                sys_p += "\n（相关才自然体现，不相关不要提。）"
        if user_memories:
            lines = [f"- {m.get('content','').strip()}"
                     for m in user_memories if m.get("content", "").strip()]
            if lines:
                who = user_name or (speaker or {}).get("name") or "这个人"
                sys_p += (f"\n\n【你记住的关于「{who}」的事】\n" + "\n".join(lines))
                sys_p += ("\n（这是你对他的了解，用来让对话更自然；"
                          "不要生硬罗列，也不要让他觉得被监视。）")
        # 当前这条也带上同样的说话人标记：历史带、当前不带的话，
        # 模型会把历史里的标记当成"转述"，反而更容易把别人的话算到当前说话人头上。
        _um = user_msg
        if speaker and speaker.get("name"):
            _um = "[%s(%s)] %s" % (speaker["name"], speaker.get("qq", ""), user_msg)
        msgs = [{"role": "system", "content": sys_p}]
        if history: msgs.extend(history)
        msgs.append({"role": "user", "content": _um})
        return await self.raw(msgs, use_gap=True)

    async def plan_reply(self, user_msg, *, persona_name="", mode="group",
                         recent="", timeout=8.0, model=None):
        r"""让「规划模型」先决定这一轮该怎么回，返回策略 dict（失败返回 None）。

        这是 pipeline.py 第 7 段（`run_ai()`）一直标着 ⏳ 的那一步：
        先判断「要不要接、什么语气、多长、要不要表情 / 知识库」，
        再把这一行提示塞进正文生成的 system prompt。

        **任何失败（超时 / JSON 坏了 / 没配模型）都返回 None** ——
        调用方照常生成，绝不因为"规划"出问题就不回话。
        """
        if not self.enabled:
            return None
        _p = str(user_msg or "").strip()
        if not _p:
            return None
        who = str(persona_name or cfg_str("persona_name", "") or "").strip()
        head = (f"你是「{who}」的回复规划器。" if who else "你是回复规划器。")
        prompt = (
            head + "根据下面这条消息，决定这一轮该怎么回。\n"
            "只输出一行纯 JSON，不要解释、不要代码块：\n"
            '{"reply":true,"tone":"语气","length":"短",'
            '"emoji":true,"sticker":false,"kb":false}\n'
            "tone 从「吐槽/卖萌/正经/敷衍/损人/安慰/好奇/冷淡」里选一个；"
            "length 只填「短」（1 句）/「中」（2-3 句）/「长」（4 句以上）；"
            "emoji / sticker / kb 填 true 或 false；"
            "reply 只在这条明显跟你无关、或纯刷屏时填 false。\n"
            + (f"最近几条：\n{recent}\n" if recent else "")
            + f"\n这条消息：\n{_p[:800]}"
        )
        try:
            raw = await self.raw([{"role": "user", "content": prompt}],
                                 timeout=timeout, use_gap=False, model=model)
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None
        if not raw:
            return None
        return _parse_plan(raw)

    async def analyze_memory(self, dialogue):
        prompt = (
            "分析下面这段QQ群对话，分别提取【群级记忆】和【用户级记忆】。\n"
            "\n"
            "【群级】整个群共享的事：群规约定、重要话题及结论、群内共识、未解决问题。\n"
            "【用户级】属于某个具体人的事：稳定偏好、身份信息、口头习惯、"
            "他个人的约定或承诺、他的近况。判断依据是发言里标注的 QQ 号。\n"
            "\n"
            "【不要记】寒暄、刷屏、一次性提问、玩笑、表情包、转述别人的话。\n"
            "【不要揣测】只写对话里明确说出来的，不要推断性格或编造。\n"
            "\n"
            "只输出纯JSON，不要markdown代码块，不要任何解释：\n"
            '{"group_memories":[{"content":"一句话","importance":3,"category":"话题"}],'
            '"user_memories":[{"qq":"123456","content":"一句话","importance":4,"category":"偏好"}]}\n'
            "\n"
            "importance 1-5（5 最重要）；category 从「偏好/话题/规则/成员/近况/其他」中选。\n"
            "qq 必须填发言前缀里那个数字 QQ 号，不要填昵称。\n"
            "某一类为空就给空数组 []。\n\n"
            f"对话：\n{dialogue}")
        r = await self.raw([{"role": "user", "content": prompt}], timeout=120.0, use_gap=False)
        if not r:
            return None
        r = r.strip()
        if r.startswith("```"):
            r = re.sub(r'^```\w*\n?', '', r)
            r = re.sub(r'\n?```$', '', r)
        try:
            data = json.loads(r)
            return data if isinstance(data, dict) else None
        except Exception as e:
            log("warn", "记忆", f"JSON解析失败: {e}")
            return None

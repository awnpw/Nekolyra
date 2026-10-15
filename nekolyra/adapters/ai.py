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

    async def raw(self, messages, timeout=120.0, use_gap=True, model=None,
                  _retry=0):
        r"""裸调用。model 传了就临时换一个模型跑这一条 ——
        内部那些「想一下」的活（记忆分析、情绪打标）可以用规划模型，
        不用跟聊天抢同一个。不传就还是 self.model。"""
        if not self.enabled:
            return None

        await self._wait_gap(use_gap)

        if not self._has_user_message(messages):
            log("warn", "AI", "消息列表中没有有效的用户消息，跳过调用")
            return None

        _mdl = str(model or "").strip() or self.model

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
        if _effort and _effort != "default":
            _extra["reasoning_effort"] = _effort
        # 关掉思考的另一个常见写法（有些端点认这个）
        if _effort == "none":
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
                    log("error", "AI", f"[{self.backend}] HTTP {r.status_code}: {body[:200]}")
                    return None

                async for line in r.aiter_lines():
                    if not line:
                        if _t_first is None and line.strip():
                            _t_first = time.time() - _t_call
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
            # 重试时 use_gap=False：限速已经等过一次了，别等两次。
            if _retry < 1 and not full_text and not reasoning_text:
                log("warn", "AI", "第 1 次失败（%s: %s），重试一次"
                    % (type(e).__name__, e))
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
        except Exception as e:
            log("warn", "AI", "_build_persona 吞掉异常：%s: %s" % (type(e).__name__, e))
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
                   user_memories=None, user_name="", profile=None):
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
        msgs = [{"role": "system", "content": sys_p}]
        if history: msgs.extend(history)
        msgs.append({"role": "user", "content": user_msg})
        return await self.raw(msgs, use_gap=True)

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

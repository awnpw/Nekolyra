# -*- coding: utf-8 -*-
r"""配置的 schema 与校验 —— 启动时跑一次，别等到运行到一半才炸。

## 为什么要有这个

原来配置是一坨 dict（bot.py 的 DEFAULT_CONFIG，104 个键），读取靠
cfg_str / cfg_bool / cfg_float / cfg_int 各自带默认值。这有三个问题：

1. **类型错不报错，行为却变了**
   `"ai_enabled": "true"`（字符串）—— `cfg_bool` 拿它当 True，看着"能用"，
   但如果哪天有人写 `"false"`，字符串非空照样是 True —— 关不掉。

2. **值域没人管**
   `port = 99999`、概率 = 5、负数超时 —— 都要等真的用到那一行才炸，
   而且报的是 ValueError，看不出是配置写错了。

3. **★ 键名拼错会被静默忽略**（最坑的一类）
   写 `deepseek_modle` —— 程序当它不存在，你改半天没反应。
   这跟 EDITABLE_KEYS 那个白名单坑是同一类：接口返回 ok:true，其实没存。

## 关于「缺 key 就 fail fast」

用户要的是"缺 key 直接挂"，但**照字面做会把所有配置都拦住**：
104 个键全都有默认值，加载时本来就自动补齐，实例配置里
"在 DEFAULT 但配置里没有的" = 0 个。

**所以"缺 key"根本不是真实故障** —— 真正的故障是上面那三类。
这里的做法：
    ERROR   类型错 / 值域错 / 必填为空     -> 调用方该拒绝启动
    WARN    不认识的键 / 可疑值            -> 记日志，管理页显示
    INFO    自动补上的键

## 类型是从 DEFAULT_CONFIG 自动推的

手写 104 条容易跟 DEFAULT_CONFIG 对不上（改了默认值忘了改 schema）。
这里只在需要额外约束时才手写（见 RULES）。
"""

import io
import json
import os
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["build_schema", "validate", "format_report", "SCHEMA_OVERRIDES",
           "fill_defaults"]

#: 从这些值推不出来的约束，手写在这里。键名 -> 约束。
#:
#:   min / max      数值范围（含端点）
#:   choices        只能是这几个值之一
#:   required       空值也算错（默认 False —— 有默认值就不算必填）
#:   doc            一句说明，报错时带上，让人知道这键是干什么的
SCHEMA_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "port": {"min": 1, "max": 65535, "doc": "管理页监听端口"},
    "admin_token": {"doc": "管理页口令。**留空等于谁都能进**，别留空"},
    "ai_backend": {"choices": ["openai", "deepseek", "ollama"],
                   "doc": "AI 后端；deepseek/ollama 是旧值，会映射到 openai"},
    "talk_value": {"min": 0.0, "max": 1.0,
                   "doc": "主动插话概率；0 = 从不主动"},
    "sticker_auto_chance": {"min": 0.0, "max": 1.0,
                            "doc": "回复时附带表情的概率"},
    "split_delay_seconds": {"min": 0.0, "max": 30.0,
                            "doc": "分段发送之间的间隔"},
    "ai_min_gap": {"min": 0.0, "doc": "两次主通道调用的最小间隔（秒）"},
    "ai_max_gap": {"min": 0.0, "doc": "两次主通道调用的最大间隔（秒）"},
    "kb_inject_count": {"min": 0, "max": 50, "doc": "每次注入几条知识库"},
    "memory_user_inject_count": {"min": 0, "max": 50,
                                 "doc": "每次注入几条个人记忆"},
    "chat_log_keep_days": {"min": 1, "max": 3650,
                           "doc": "聊天记录保留天数"},
    "log_all_group_msgs": {"doc": "是否把每条群消息都记进聊天记录"},
}

#: 这些键的值允许是空字符串（不然会报"空值"警告）
_ALLOW_EMPTY = {
    "deepseek_api_key", "ollama_api_key", "openai_api_key", "openai_host",
    "openai_model", "github_token", "persona_name", "persona_identity",
    "persona_behavior", "persona_speech", "plan_model", "wallpaper_path",
    "wallpaper_custom", "proxy", "voice_model", "tts_host",
}

#: 内置插件会往 config.json 里写自己的键 —— 这些不该报"不认识"。
#: 前缀按插件名来：adfilter / autoreply / lottery / report / sign / wife。
#: （以前只列了三个，结果 report_* / sign_* / wife_* 全被当成"拼错的键"报出来。）
_PLUGIN_KEY_PREFIXES = ("ad_", "auto_sign_", "lottery_", "plugin_", "kb_auto",
                        "report_", "sign_", "wife_")


def build_schema(default_config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    r"""从 DEFAULT_CONFIG 推出 schema：类型取默认值的类型，再叠加手写约束。"""
    out: Dict[str, Dict[str, Any]] = {}
    for k, v in (default_config or {}).items():
        if isinstance(v, bool):
            t = "bool"
        elif isinstance(v, int):
            t = "int"
        elif isinstance(v, float):
            t = "float"
        elif isinstance(v, str):
            t = "str"
        elif isinstance(v, list):
            t = "list"
        elif isinstance(v, dict):
            t = "dict"
        else:
            t = "any"
        entry = {"type": t, "default": v}
        entry.update(SCHEMA_OVERRIDES.get(k) or {})
        out[k] = entry
    # 手写约束里有、但 DEFAULT_CONFIG 里没有的 —— 说明两边对不上了，也收进来
    for k, ov in SCHEMA_OVERRIDES.items():
        if k not in out:
            out[k] = dict(ov, type="any", default=None)
    return out


def _type_ok(value: Any, want: str) -> bool:
    if want == "any":
        return True
    if want == "bool":
        return isinstance(value, bool)
    if want == "int":
        # bool 是 int 的子类，这里要排掉 —— 不然 True 会被当成合法的 int
        return isinstance(value, int) and not isinstance(value, bool)
    if want == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if want == "str":
        return isinstance(value, str)
    if want == "list":
        return isinstance(value, list)
    if want == "dict":
        return isinstance(value, dict)
    return True


def _is_plugin_key(k: str) -> bool:
    return any(str(k).startswith(p) for p in _PLUGIN_KEY_PREFIXES)


def validate(cfg: Dict[str, Any], default_config: Dict[str, Any],
             schema: Optional[Dict[str, Dict[str, Any]]] = None
             ) -> Tuple[List[str], List[str], List[str]]:
    r"""校验配置。返回 `(errors, warnings, filled)`。

    errors   —— 不该启动的理由（类型错 / 值域错 / 必填为空）
    warnings —— 能跑，但该看看（不认识的键 / 可疑的空值）
    filled   —— 自动补上的键（配置文件里没有、用了默认值）
    """
    sch = schema or build_schema(default_config)
    errors: List[str] = []
    warnings: List[str] = []
    filled: List[str] = []
    cfg = cfg if isinstance(cfg, dict) else {}

    # ---- 1. 逐个键校验 ----
    for k, spec in sch.items():
        has = k in cfg
        v = cfg.get(k)
        doc = spec.get("doc") or ""
        tail = ("（%s）" % doc) if doc else ""

        if not has:
            filled.append(k)
            continue

        want = spec.get("type", "any")
        if v is None:
            # None 当"用默认值"处理 —— 管理页清空输入框会写 null
            warnings.append("[空值] %s 是 null，按默认值 %r 用%s"
                            % (k, spec.get("default"), tail))
            continue

        if not _type_ok(v, want):
            errors.append(
                "[类型] %s 应该是 %s，实际是 %s（%r）。"
                "改 config.json 里这一项，或者删掉它用默认值 %r%s"
                % (k, want, type(v).__name__, v, spec.get("default"), tail))
            continue

        # 数值范围
        lo, hi = spec.get("min"), spec.get("max")
        if (lo is not None or hi is not None) and isinstance(v, (int, float)) \
                and not isinstance(v, bool):
            if lo is not None and v < lo:
                errors.append("[值域] %s 不能小于 %s，实际是 %s%s" % (k, lo, v, tail))
            if hi is not None and v > hi:
                errors.append("[值域] %s 不能大于 %s，实际是 %s%s" % (k, hi, v, tail))

        # 枚举
        ch = spec.get("choices")
        if ch and v not in ch:
            warnings.append("[取值] %s = %r 不在推荐值 %s 里%s"
                            % (k, v, ch, tail))

        # 可疑的空值（有些键空着是正常的，见 _ALLOW_EMPTY）
        if isinstance(v, str) and not v.strip() and k not in _ALLOW_EMPTY:
            required = bool(spec.get("required"))
            msg = "[空值] %s 是空字符串%s" % (k, tail)
            if required:
                errors.append(msg + " —— 这一项不能空")
            else:
                warnings.append(msg)

    # ---- 2. 配置文件里有、schema 不认识的键 ----
    unknown = [k for k in cfg if k not in sch and not _is_plugin_key(k)]
    if unknown:
        warnings.append(
            "[不认识] 配置里有 %d 个核心不认识的键：%s"
            % (len(unknown), ", ".join(sorted(unknown)[:12])))
        warnings.append(
            "          —— 大多是**拼错了**（比如 deepseek_modle）。"
            "写错的键会被静默忽略，改了没反应。")

    # ---- 3. 几项跨键的常识检查 ----
    try:
        lo = cfg.get("ai_min_gap", default_config.get("ai_min_gap", 0)) or 0
        hi = cfg.get("ai_max_gap", default_config.get("ai_max_gap", 0)) or 0
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > hi:
            errors.append("[关系] ai_min_gap(%s) 比 ai_max_gap(%s) 还大 —— "
                          "请求间隔会算成负数" % (lo, hi))
    except Exception:
        pass

    if not str(cfg.get("admin_token") or "").strip():
        errors.append("[必填] admin_token 空着等于**谁都能打开管理页** —— "
                      "填一个口令再启动")

    return errors, warnings, filled


def format_report(errors: List[str], warnings: List[str],
                  filled: List[str], max_filled: int = 6) -> str:
    r"""把校验结果拼成给人看的一段话。"""
    out = []
    if errors:
        out.append("配置有 %d 处错误：" % len(errors))
        for e in errors:
            out.append("  ✗ %s" % e)
    if warnings:
        out.append("")
        out.append("配置有 %d 处提醒（不拦启动）：" % len(warnings))
        for w in warnings:
            out.append("  ! %s" % w)
    if filled:
        out.append("")
        out.append("以下 %d 个键配置文件里没有，已用默认值：%s%s"
                   % (len(filled), ", ".join(filled[:max_filled]),
                      " …" if len(filled) > max_filled else ""))
    return "\n".join(out) if out else "配置检查通过。"


def fill_defaults(cfg: Dict[str, Any], default_config: Dict[str, Any]
                  ) -> Dict[str, Any]:
    r"""把缺的键用默认值补齐（不改原 dict）。"""
    out = dict(default_config or {})
    out.update(cfg or {})
    return out


def load_and_validate(path: str, default_config: Dict[str, Any]
                      ) -> Tuple[Dict[str, Any], List[str], List[str], List[str], str]:
    r"""读 config.json + 校验。返回 `(cfg, errors, warnings, filled, 原始文本错误)`。

    文件不存在/读不动时，cfg 用默认值、raw_err 带上原因 ——
    **不在这里 raise**，让调用方决定是"首次运行"还是"真出错"。
    """
    cfg, raw_err = {}, ""
    try:
        if os.path.exists(path):
            with io.open(path, encoding="utf-8") as f:
                cfg = json.load(f)
            if not isinstance(cfg, dict):
                raw_err = "config.json 根节点必须是对象"
                cfg = {}
    except json.JSONDecodeError as e:
        raw_err = "config.json 不是合法 JSON：第 %d 行 %s" % (
            getattr(e, "lineno", 0), getattr(e, "msg", ""))
        cfg = {}
    except Exception as e:
        raw_err = "config.json 读不了：%s: %s" % (type(e).__name__, e)
        cfg = {}

    merged = fill_defaults(cfg, default_config)
    errs, warns, filled = validate(cfg, default_config)
    if raw_err:
        errs.insert(0, "[文件] %s" % raw_err)
    return merged, errs, warns, filled, raw_err

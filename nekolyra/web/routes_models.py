# -*- coding: utf-8 -*-
r"""管理页 · api_models 路由（1 个）。

**注册模式**：路由函数一字未改，只是整体缩进进了 register()。

必须缩进进去：`@app.get(...)` 是装饰器，**import 时就执行**，
放模块顶层会直接 NameError: app，整个模块导不进来。

由 _routes_extract.py 生成。
"""

import time

from fastapi.responses import JSONResponse

__all__ = ["register"]


def _llm_conf(kind="chat"):
    r"""按 ai_backend 取接口地址和 key。

    以前这里写死 cfg_str("deepseek_api_host")：用户 ai_backend=openai 时，
    实际对话用的是 openai_host/openai_api_key，而模型列表和"测试"按钮却去问
    deepseek 那组（可能是空地址或另一个端点）—— 结果好模型被判成不可用。
    """
    be = (cfg_str("ai_backend") or "openai").strip().lower()
    if kind == "vision":
        h = (cfg_str("vision_api_host") or cfg_str(be + "_host")
             or cfg_str("deepseek_api_host"))
        k = (cfg_str("vision_api_key") or cfg_str(be + "_api_key")
             or cfg_str("deepseek_api_key"))
    else:
        h = cfg_str(be + "_host") or cfg_str("deepseek_api_host")
        k = cfg_str(be + "_api_key") or cfg_str("deepseek_api_key")
    return (h or "").strip().rstrip("/"), (k or "").strip()

# 平台 /v1/models 会继续返回已经下线的模型（实测官网只列 11 个、接口返回 13 个），
# 用户在下拉里选到它们只会在发消息时才报错。这里直接剔掉，
# 新发现下线的往这里加一行即可；手填仍然不受限制。
RETIRED_MODELS = {
    "deepseek-v4-flash-0731",
    "deepseek-v4-flash-vision",
    "Atria-Dawn-Preview",
}


def register(app, **deps):
    r"""把这些路由挂到 app 上。deps：全局名 = 值。"""
    globals().update(deps)

    @app.get("/admin/api/models/test")
    async def api_models_test(token: str = "", model: str = "", kind: str = "chat"):
        r"""验证一个模型名当前能不能真的用。

        平台的 /v1/models 会把已下线的模型也列出来（实测：官网 11 个、
        接口 13 个），用户在下拉里选到死模型时只有发消息才发现。
        这里发一个 max_tokens=1 的极小请求，一次就能判断死活。
        """
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        m = (model or "").strip()
        if not m:
            return JSONResponse({"ok": False, "error": "没有模型名"})
        h, k = _llm_conf(kind)
        if not h:
            return JSONResponse({"ok": False, "error": "没有配置接口地址"})
        hd = {"User-Agent": _ua()}
        if k:
            hd["Authorization"] = "Bearer " + k
        # 冷却中就别再打了 —— 连点「测试」会把渠道配额烧光，拖累正常对话
        try:
            from nekolyra.adapters.ai import _COOLDOWN_UNTIL as _CD
            _left = _CD[0] - time.time()
            if _left > 0:
                return JSONResponse({"ok": False, "model": m, "status": 429,
                                     "error": "上游限流冷却中，请 %.0f 秒后再试" % _left})
        except Exception:
            pass
        payload = {"model": m, "messages": [{"role": "user", "content": "hi"}],
                   "max_tokens": 1, "stream": False}
        t0 = time.time()
        try:
            cli = get_http()
            r = await cli.post(h + "/chat/completions", json=payload, headers=hd,
                               timeout=30.0)
            ms = int((time.time() - t0) * 1000)
            if r.status_code < 400:
                log("info", "模型", f"测试 {m}：可用（{ms}ms）")
                return JSONResponse({"ok": True, "ms": ms, "model": m})
            body = (r.text or "")[:220]
            log("warn", "模型", f"测试 {m}：HTTP {r.status_code} {body[:80]}")
            return JSONResponse({"ok": False, "ms": ms, "model": m,
                                 "status": r.status_code, "error": body})
        except Exception as e:
            return JSONResponse({"ok": False, "model": m,
                                 "error": "%s: %s" % (type(e).__name__, e)})

    @app.get("/admin/api/models")
    async def api_models(token: str = "", host: str = "", key: str = "",
                         kind: str = "chat"):
        r"""列出后端支持的模型，给管理页的下拉框用。

        走 OpenAI 兼容的 GET {host}/models —— 智谱、DeepSeek、Ollama 都支持这个。
        拿不到就返回空列表，前端会退回「手填」，不会因为列不出来就用不了。
        """
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        h = (host or "").strip().rstrip("/")
        k = (key or "").strip()
        if not h or not k:
            _h2, _k2 = _llm_conf(kind)
            h = h or _h2
            k = k or _k2
        if not h:
            return JSONResponse({"items": [], "error": "没有配置接口地址"})
        try:
            cli = get_http()
            hd = {"User-Agent": _ua()}
            if k:
                hd["Authorization"] = "Bearer " + k
            r = await cli.get(h + "/models", headers=hd, timeout=15.0)
            if r.status_code >= 400:
                _body = ""
                try:
                    _body = (r.text or "")[:160]
                except Exception:
                    pass
                return JSONResponse({"items": [], "host": h,
                                     "error": "HTTP %s %s" % (r.status_code, _body)})
            d = r.json()
            arr = d.get("data") if isinstance(d, dict) else d
            items = []
            for x in (arr or []):
                if isinstance(x, dict):
                    mid = str(x.get("id") or x.get("name") or "").strip()
                else:
                    mid = str(x or "").strip()
                if mid and mid not in items and mid not in RETIRED_MODELS:
                    items.append(mid)
            # 有些网关（实测 intern-ai）把「只在网页展示、当前协议不可用」的模型
            # 放在顶层另一个键里（models），只读 data 就会少几个 ——
            # 用户在网页上看到 12 个、下拉里只有 11 个，会以为"读漏了"。
            # 这里一并返回并标出原因，前端一起放进候选列表。
            extra = []
            if isinstance(d, dict):
                for _k in ("models", "extra_models"):
                    for x in (d.get(_k) or []):
                        if isinstance(x, dict):
                            mid = str(x.get("id") or x.get("name") or "").strip()
                            why = str(x.get("description") or x.get("protocol") or "").strip()
                        else:
                            mid = str(x or "").strip()
                            why = ""
                        if not mid or mid in items:
                            continue
                        if any(e["id"] == mid for e in extra):
                            continue
                        extra.append({"id": mid, "reason": why})
            items.sort()
            log("info", "模型", f"{h} 返回 {len(items)} 个可用模型"
                             + (f"；另有 {len(extra)} 个仅网页展示（该协议不可用）" if extra else ""))
            return JSONResponse({"items": items, "count": len(items),
                                 "extra": extra, "host": h})
        except Exception as e:
            log("warn", "模型", f"列模型失败: {type(e).__name__}: {e}")
            return JSONResponse({"items": [], "error": f"{type(e).__name__}"})


# -*- coding: utf-8 -*-
r"""管理页 · api_models 路由（1 个）。

**注册模式**：路由函数一字未改，只是整体缩进进了 register()。

必须缩进进去：`@app.get(...)` 是装饰器，**import 时就执行**，
放模块顶层会直接 NameError: app，整个模块导不进来。

由 _routes_extract.py 生成。
"""

from fastapi.responses import JSONResponse

__all__ = ["register"]


def register(app, **deps):
    r"""把这些路由挂到 app 上。deps：全局名 = 值。"""
    globals().update(deps)

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
        if not h:
            h = (cfg_str("deepseek_api_host") if kind == "chat"
                 else cfg_str("vision_api_host") or cfg_str("deepseek_api_host"))
            h = (h or "").strip().rstrip("/")
        k = (key or "").strip()
        if not k:
            k = (cfg_str("deepseek_api_key") if kind == "chat"
                 else cfg_str("vision_api_key") or cfg_str("deepseek_api_key"))
            k = (k or "").strip()
        if not h:
            return JSONResponse({"items": [], "error": "没有配置接口地址"})
        try:
            cli = get_http()
            hd = {"User-Agent": _ua()}
            if k:
                hd["Authorization"] = "Bearer " + k
            r = await cli.get(h + "/models", headers=hd, timeout=15.0)
            if r.status_code >= 400:
                return JSONResponse({"items": [],
                                     "error": f"HTTP {r.status_code}"})
            d = r.json()
            arr = d.get("data") if isinstance(d, dict) else d
            items = []
            for x in (arr or []):
                if isinstance(x, dict):
                    mid = str(x.get("id") or x.get("name") or "").strip()
                else:
                    mid = str(x or "").strip()
                if mid and mid not in items:
                    items.append(mid)
            items.sort()
            log("info", "模型", f"{h} 返回 {len(items)} 个模型")
            return JSONResponse({"items": items, "count": len(items), "host": h})
        except Exception as e:
            log("warn", "模型", f"列模型失败: {type(e).__name__}: {e}")
            return JSONResponse({"items": [], "error": f"{type(e).__name__}"})


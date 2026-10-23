# -*- coding: utf-8 -*-
r"""管理页 · api_ai 路由（2 个）。

**注册模式**：路由函数一字未改，只是整体缩进进了 register()。

必须缩进进去：`@app.get(...)` 是装饰器，**import 时就执行**，
放模块顶层会直接 NameError: app，整个模块导不进来。

由 _routes_extract.py 生成。
"""

import asyncio

import httpx

from fastapi.responses import JSONResponse

__all__ = ["register"]


def register(app, **deps):
    r"""把这些路由挂到 app 上。deps：全局名 = 值。"""
    globals().update(deps)

    @app.get("/admin/api/ai/models")
    async def api_ai_models(token: str = ""):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        models = []
        headers = {"Authorization": f"Bearer {AI.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=8.0, mounts=_http_mounts()) as client:
                r = await client.get(AI.models_endpoint(), headers=headers)
                r.raise_for_status()
                data = r.json()
                for m in data.get("data", []):
                    name = (m.get("id") or "").strip()
                    if name:
                        models.append(name)
        except Exception as e:
            return JSONResponse({"models": [], "backend": AI.backend,
                                 "error": f"{type(e).__name__}: {e}"})
        return JSONResponse({"models": models, "backend": AI.backend})

    @app.post("/admin/api/ai/test")
    async def api_ai_test(token: str = "", text: str = ""):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        if not text: return JSONResponse({"error": "empty"})
        try:
            reply = await asyncio.wait_for(
                AI.chat(text, speaker={"name": "管理员", "qq": "console"}, mode="private"),
                timeout=AI_HARD_TIMEOUT
            )
        except asyncio.TimeoutError:
            return JSONResponse({"reply": "（超时）"})
        return JSONResponse({"reply": reply or "(无回复)"})


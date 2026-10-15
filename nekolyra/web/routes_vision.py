# -*- coding: utf-8 -*-
r"""管理页 · api_vision 路由（1 个）。

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

    @app.get("/api/vision/test")
    async def api_vision_test(token: str = "", url: str = ""):
        if not _auth(token): return JSONResponse({"error": "invalid token"}, status_code=401)
        if not url: return JSONResponse({"error": "缺少 url"}, status_code=400)
        d = await _vision_test_impl(url)
        if d:
            return JSONResponse({"ok": True, "description": d})
        return JSONResponse({"ok": False, "error": "识图失败，看日志"})


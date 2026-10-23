# -*- coding: utf-8 -*-
r"""管理页 · api_logs 路由（1 个）。

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

    @app.get("/admin/api/logs")
    async def api_logs(token: str = "", since: int = 0):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        return JSONResponse(LOG_BUF.since(since))


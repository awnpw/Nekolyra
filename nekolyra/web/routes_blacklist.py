# -*- coding: utf-8 -*-
r"""管理页 · api_bl 路由（3 个）。

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

    @app.get("/admin/api/blacklist")
    async def api_bl(token: str = ""):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        return JSONResponse(DB.bl_list_all())

    @app.post("/admin/api/blacklist/remove")
    async def api_bl_rm(token: str = "", user_id: int = 0, group_id: int = 0):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        DB.bl_remove(user_id, group_id); return JSONResponse({"ok": True})

    @app.post("/admin/api/blacklist/add")
    async def api_bl_add(token: str = "", user_id: int = 0, group_id: int = 0):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        if group_id < 0:
            group_id = 0     # 负数 = 幽灵群，那条黑名单不会生效
        DB.bl_add(user_id, group_id, "", "控制台手动拉黑"); return JSONResponse({"ok": True})


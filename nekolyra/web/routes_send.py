# -*- coding: utf-8 -*-
r"""管理页 · api_send 路由（1 个）。

**注册模式**：路由函数一字未改，只是整体缩进进了 register()。

必须缩进进去：`@app.get(...)` 是装饰器，**import 时就执行**，
放模块顶层会直接 NameError: app，整个模块导不进来。

由 _routes_extract.py 生成。
"""

from fastapi import Request
from fastapi.responses import JSONResponse

__all__ = ["register"]


def register(app, **deps):
    r"""把这些路由挂到 app 上。deps：全局名 = 值。"""
    globals().update(deps)

    @app.post("/api/send")
    async def api_send(token: str = "", request: Request = None):
        if not _auth(token): return JSONResponse({"error": "invalid token"}, status_code=401)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid body"}, status_code=400)
        except Exception:
            return JSONResponse({"error": "invalid body"}, status_code=400)
        try:
            gid = int(body.get("group_id", 0))
        except (TypeError, ValueError):
            return JSONResponse({"error": "group_id 必须是数字"}, status_code=400)
        msg = str(body.get("message", "")).strip()
        at = body.get("at_user_id")
        # 同上：`not gid` 挡不住负数（not -1 是 False）。
        if gid <= 0 or not msg:
            return JSONResponse(
                {"error": "group_id 必须是正整数，且 message 不能为空"},
                status_code=400)
        try:
            ok = await _send_impl(gid, msg, at)
        except Exception as e:
            return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)
        if not ok:
            return JSONResponse({"error": "机器人未连接"}, status_code=503)
        return JSONResponse({"ok": True})


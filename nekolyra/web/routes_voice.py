# -*- coding: utf-8 -*-
r"""管理页 · api_voice 路由（2 个）。

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

    @app.get("/api/voice/test")
    async def api_voice_test(token: str = "", text: str = ""):
        if not _auth(token): return JSONResponse({"error": "invalid token"}, status_code=401)
        text = (text or "").strip()
        if not text:
            return JSONResponse({"ok": False, "error": "缺少 text"})
        return JSONResponse(await _voice_test_impl(text))

    @app.post("/api/voice/send")
    async def api_voice_send(token: str = "", request: Request = None):
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
        text = str(body.get("text", "")).strip()
        # 群号必须为正。以前写的是 `not gid` —— 但 `not -1` 是 False，
        # 负数会一路传到 bot.send_group_msg(group_id=-1)，拿一个 NapCat 的
        # 接口报错回来。不折算成 0：那会把"发到负群号"静默变成"发到别处"。
        if gid <= 0 or not text:
            return JSONResponse(
                {"error": "group_id 必须是正整数，且 text 不能为空"},
                status_code=400)
        return JSONResponse(await _send_voice_impl(gid, text))


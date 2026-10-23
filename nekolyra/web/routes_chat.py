# -*- coding: utf-8 -*-
r"""管理页 · api_chat 路由（1 个）。

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

    @app.post("/api/chat")
    async def api_chat(token: str = "", request: Request = None):
        if not _auth(token): return JSONResponse({"error": "invalid token"}, status_code=401)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid body"}, status_code=400)
        except Exception:
            return JSONResponse({"error": "invalid body"}, status_code=400)
        try:
            gid = int(body.get("group_id", 0))
            uid = int(body.get("user_id", 0))
        except (TypeError, ValueError):
            return JSONResponse({"error": "group_id/user_id 必须是数字"}, status_code=400)
        text = str(body.get("text", "")).strip()
        nickname = str(body.get("nickname", "")).strip()
        mode = "private" if str(body.get("mode", "group")) == "private" else "group"
        # 私聊模式根本不用 group_id（do_chat 走的是 get_private_context(uid)），
        # 所以 gid=0 是合法的 —— 以前 `not gid` 会把它当成"没填"直接拒掉，
        # 用户只能随便填个假群号绕过去。
        # uid 允许为正数即可；群聊模式下 gid 也必须为正
        # （`not gid` 同样挡不住负数）。
        if uid <= 0 or (mode == "group" and gid <= 0):
            return JSONResponse({"error": "user_id / group_id 必须是正整数"},
                                status_code=400)
        if not text:
            return JSONResponse({"error": "text 不能为空"}, status_code=400)
        dry = bool(body.get("dry_run"))
        return JSONResponse(await _chat_impl(gid, uid, text, nickname, mode, dry))


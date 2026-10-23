# -*- coding: utf-8 -*-
r"""管理页 · api_nickname 路由（1 个）。

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

    @app.get("/api/nickname")
    async def api_nickname(token: str = "", group_id: int = 0, user_id: int = 0):
        if not _auth(token): return JSONResponse({"error": "invalid token"}, status_code=401)
        if not group_id or not user_id:
            return JSONResponse({"error": "缺少参数"}, status_code=400)
        bot = get_any_bot()
        if not bot:
            return JSONResponse({"nickname": str(user_id), "source": "no_bot"})
        try:
            info = await bot.get_group_member_info(
                group_id=int(group_id), user_id=int(user_id), no_cache=False
            )
            card = (info.get("card") or "").strip()
            nick = (info.get("nickname") or "").strip()
            name = card or nick or str(user_id)
            return JSONResponse({
                "nickname": name,
                "card": card,
                "qq_nick": nick,
                "source": "card" if card else ("nick" if nick else "fallback"),
            })
        except Exception as e:
            log("warn", "昵称", f"查 {user_id} 失败: {type(e).__name__}: {e}")
            return JSONResponse({"nickname": str(user_id), "source": "error"})


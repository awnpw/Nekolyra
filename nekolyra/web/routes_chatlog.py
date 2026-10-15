# -*- coding: utf-8 -*-
r"""管理页 · api_chatlog 路由（5 个）。

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

    @app.get("/admin/api/chatlog")
    async def api_chatlog(token: str = "", group_id: int = -1, user_id: int = -1,
                          limit: int = 200, keyword: str = "", before_id: int = 0):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        g, u = _log_scope(group_id, user_id)
        limit = max(1, min(500, int(limit or 200)))
        rows = DB.log_list(g=g, uid=u, limit=limit, keyword=keyword.strip(),
                           before_id=int(before_id or 0))
        total = DB.log_count(g=g, uid=u)
        # 倒序返回，前端自己按时间正序渲染
        return JSONResponse({"total": total, "count": len(rows), "items": rows})

    @app.get("/admin/api/chatlog/groups")
    async def api_chatlog_groups(token: str = ""):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        return JSONResponse(DB.log_groups())

    @app.get("/admin/api/chatlog/users_all")
    async def api_chatlog_users_all(token: str = ""):
        """所有说过话的人（跨群聚合），用于"按人"清记录。"""
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        return JSONResponse(DB.log_users(g=None))

    @app.get("/admin/api/chatlog/users")
    async def api_chatlog_users(token: str = "", group_id: int = -1):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        g, _ = _log_scope(group_id, -1)
        return JSONResponse(DB.log_users(g=g))

    @app.post("/admin/api/chatlog/clear")
    async def api_chatlog_clear(token: str = "", group_id: int = -1, user_id: int = -1):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        g, u = _log_scope(group_id, user_id)
        if g is None and u is None:
            return JSONResponse({"error": "拒绝清空全部：至少指定群或用户"}, status_code=400)
        n = DB.log_clear(g=g, uid=u)
        log("block", "聊天记录", f"控制台清空 群={g} 用户={u} 共 {n} 条")
        return JSONResponse({"ok": True, "deleted": n})


# -*- coding: utf-8 -*-
r"""管理页 · api_mem 路由（6 个）。

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

    @app.get("/admin/api/memories")
    async def api_mem(token: str = "", view: str = "group", user_id: int = 0):
        """view=group（默认）按群列；view=user 按人列（跨群）。"""
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        view = (view or "group").strip().lower()
        if view == "user":
            if not user_id:
                return JSONResponse({"view": "user", "users": DB.mem_users()})
            rows = DB.mem_list_by_user(user_id)
            return JSONResponse({"view": "user", "user_id": user_id, "count": len(rows),
                                 "groups": DB.mem_groups_of_user(user_id),
                                 "memories": rows})
        res = []
        for g in DB.mem_all_groups():
            gid = g["group_id"]
            ms = DB.mem_list_group(gid, limit=100)
            res.append({"group_id": gid, "count": g["cnt"],
                        "user_count": g.get("user_cnt") or 0,
                        "memories": [{"id": m["id"], "content": m["content"],
                                      "category": m.get("category", "其他"),
                                      "importance": m.get("importance", 3),
                                      "created_at": m["created_at"],
                                      "scope": m.get("scope") or "group",
                                      "user_id": m.get("user_id") or 0} for m in ms]})
        return JSONResponse(res)

    @app.post("/admin/api/memories/clear")
    async def api_mem_clear(token: str = "", group_id: int = 0):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        DB.mem_clear_group(group_id); return JSONResponse({"ok": True})

    @app.post("/admin/api/memories/delete")
    async def api_mem_del(token: str = "", id: int = 0):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        DB.mem_delete_one(id); return JSONResponse({"ok": True})

    @app.post("/admin/api/memories/clear_user_all")
    async def api_mem_clear_user_all(token: str = "", user_id: int = 0):
        """删掉某人在【所有群】的专属记忆（群级记忆不动）。"""
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        if not user_id:
            return JSONResponse({"error": "缺少 user_id"}, status_code=400)
        groups = DB.mem_groups_of_user(user_id)
        n = DB.mem_clear_user_all(user_id)
        log("block", "记忆", f"控制台清空 用户{user_id} 在 {len(groups)} 个群的全部专属记忆（{n} 条）")
        return JSONResponse({"ok": True, "deleted": n, "groups": len(groups)})

    @app.post("/admin/api/memories/add")
    async def api_mem_add(token: str = "", request: Request = None):
        """手动加一条记忆（AI 自动记忆之外的人工补充/纠正）。"""
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid body"}, status_code=400)
        except Exception:
            return JSONResponse({"error": "invalid body"}, status_code=400)

        content = str(body.get("content", "")).strip()
        if not content:
            return JSONResponse({"error": "内容不能为空"}, status_code=400)
        if len(content) > 200:
            return JSONResponse({"error": "内容太长（最多 200 字）"}, status_code=400)

        try:
            gid = int(body.get("group_id", 0) or 0)
            uid = int(body.get("user_id", 0) or 0)
            imp = int(body.get("importance", 3) or 3)
        except (TypeError, ValueError):
            return JSONResponse({"error": "群号/QQ/重要度必须是数字"}, status_code=400)
        # 负数群号会写进"幽灵群"，任何群视图里都看不到。
        # （注意：私聊记忆的 key 确实是负 uid，但那是 bot 自己写的，
        #   不走这个接口 —— 这里只归一化网页传进来的群号。）
        if gid < 0:
            gid = 0

        scope = str(body.get("scope", "group")).strip().lower()
        if scope not in ("group", "user"):
            return JSONResponse({"error": "scope 只能是 group 或 user"}, status_code=400)
        # 用户级必须有 QQ；私聊时群号固定 0
        if scope == "user" and not uid:
            return JSONResponse({"error": "用户级记忆必须提供 user_id"}, status_code=400)
        if scope == "group":
            uid = 0
        imp = max(1, min(5, imp))
        cat = str(body.get("category", "其他")).strip() or "其他"

        uname = ""
        if scope == "user":
            try:
                uname = DB.nick_lookup(uid, gid) or ""
            except Exception:
                uname = ""
        DB.mem_add(gid, content, cat, imp, uid=uid, uname=uname, scope=scope)
        who = f"群{gid}" if scope == "group" else f"群{gid} 用户{uid}"
        log("block", "记忆", f"控制台手动添加 [{who}] [{cat}·{imp}星] {content[:40]}")
        return JSONResponse({"ok": True})

    @app.post("/admin/api/memories/clear_user")
    async def api_mem_clear_user(token: str = "", group_id: int = 0, user_id: int = 0):
        """只清掉某人在某群（或私聊 user_id + group_id=0）的专属记忆。"""
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        if not user_id:
            return JSONResponse({"error": "缺少 user_id"}, status_code=400)
        DB.mem_clear_user(group_id, user_id)
        log("block", "记忆", f"控制台清空 群{group_id} 用户{user_id} 的专属记忆")
        return JSONResponse({"ok": True})


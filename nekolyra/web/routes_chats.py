# -*- coding: utf-8 -*-
r"""管理页 · api_chats 路由（3 个）。

**注册模式**：路由函数一字未改，只是整体缩进进了 register()。

必须缩进进去：`@app.get(...)` 是装饰器，**import 时就执行**，
放模块顶层会直接 NameError: app，整个模块导不进来。

由 _routes_extract.py 生成。
"""

import asyncio

from fastapi import Request
from fastapi.responses import JSONResponse

__all__ = ["register"]


def register(app, **deps):
    r"""把这些路由挂到 app 上。deps：全局名 = 值。"""
    globals().update(deps)

    @app.get("/admin/api/chats")
    async def api_chats(token: str = "", kind: str = "", kw: str = ""):
        """聊天管理的会话列表。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        items = await asyncio.to_thread(DB.chats_list, (kind or "").strip(),
                                        (kw or "").strip(), 300)
        ov = CFG.get("persona_overrides")
        ov = ov if isinstance(ov, dict) else {}
        for x in items:
            one = ov.get(x["key"])
            x["has_persona"] = bool(isinstance(one, dict) and any(
                str(one.get(k) or "").strip()
                for k in ("name", "identity", "behavior", "speech",
                          "voice", "voice_chance")))
        return JSONResponse({"items": items, "count": len(items)})

    @app.get("/admin/api/chats/log")
    async def api_chats_log(token: str = "", key: str = "", kw: str = "",
                          limit: int = 80, offset: int = 0,
                          only_bot: bool = False):
        """读某个会话的聊天记录。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        try:
            limit = max(1, min(int(limit), 500))
            offset = max(0, int(offset))
        except (TypeError, ValueError):
            limit, offset = 80, 0
        # 默认 False = 这个会话的全部消息（群里所有人说的每句话）。
        # only_bot=True 是可选的一个筛选：只看跟机器人有来有回的那几轮。
        rows, total = await asyncio.to_thread(
            DB.chat_log_pairs, key, bool(only_bot), (kw or "").strip(),
            limit, offset)
        return JSONResponse({"items": rows, "count": len(rows), "key": key,
                             "total": total, "offset": offset, "limit": limit,
                             "only_bot": bool(only_bot)})

    @app.post("/admin/api/chats/log/delete")
    async def api_chats_log_delete(token: str = "", request: Request = None):
        """删聊天记录。ids 传 ["all:<key>"] 就清空整个会话。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid json"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid body"}, status_code=400)
        raw = body.get("ids")
        if isinstance(raw, list) and raw and str(raw[0]).startswith("all:"):
            key = str(raw[0])[4:].strip()
            rows = await asyncio.to_thread(DB.chat_log_page, key, "", 100000, 0)
            n = await asyncio.to_thread(DB.chat_log_del,
                                        [r["id"] for r in rows])
            log("info", "聊天管理", f"清空会话 {key}：{n} 条")
            return JSONResponse({"ok": True, "deleted": n})
        if not isinstance(raw, list):
            return JSONResponse({"error": "ids 必须是数组"}, status_code=400)
        ids = []
        for x in raw[:500]:
            try:
                ids.append(int(x))
            except (TypeError, ValueError) as e:
                log("warn", "聊天", "api_chats_log_delete 吞掉异常：%s: %s" % (type(e).__name__, e))
        if not ids:
            return JSONResponse({"error": "没有有效的 id"}, status_code=400)
        n = await asyncio.to_thread(DB.chat_log_del, ids)
        return JSONResponse({"ok": True, "deleted": n})


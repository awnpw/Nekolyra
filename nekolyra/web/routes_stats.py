# -*- coding: utf-8 -*-
r"""管理页 · api_stats 路由（1 个）。

**注册模式**：路由函数一字未改，只是整体缩进进了 register()。

必须缩进进去：`@app.get(...)` 是装饰器，**import 时就执行**，
放模块顶层会直接 NameError: app，整个模块导不进来。

由 _routes_extract.py 生成。
"""

import time

import nonebot

from fastapi.responses import JSONResponse

__all__ = ["register"]


def register(app, **deps):
    r"""把这些路由挂到 app 上。deps：全局名 = 值。"""
    globals().update(deps)

    @app.get("/admin/api/stats")
    async def api_stats(token: str = ""):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        _prune_pending_verify()
        bots = nonebot.get_bots()
        bot_info = []
        for sid, b in bots.items():
            bot_info.append({"self_id": str(sid)})
        return JSONResponse({
            "uptime": time.time() - START_TIME,
            "memory_total": DB.mem_count(),
            "blacklist_total": DB.bl_count(),
            "active_groups": len(ai_context),
            "pending_count": len(pending_verify),
            "request_count": len(pending_requests),
            "mem_saved": mem_stats["saved"],
            "mem_skipped": mem_stats["skipped"],
            "model": AI.model,
            "backend": AI.backend,
            "bots": bot_info,
            "vision_enabled": cfg_bool("vision_enabled", False),
            "vision_model": cfg_str("vision_model"),
            "voice_enabled": cfg_bool("voice_enabled", False),
            "voice_name": cfg_str("voice_name"),
        })


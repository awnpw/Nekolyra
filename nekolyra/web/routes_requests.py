# -*- coding: utf-8 -*-
r"""管理页 · api_requests 路由（3 个）。

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

    @app.get("/admin/api/requests")
    async def api_requests(token: str = ""):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        _cleanup_pending_requests()
        items = list(pending_requests.values())
        items.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return JSONResponse([{
            "flag": it["flag"],
            "user_id": it["user_id"],
            "group_id": it["group_id"],
            "nickname": it.get("nickname", ""),
            "comment": it.get("comment", ""),
            "created_at": int(it.get("created_at", 0)),
        } for it in items])

    @app.post("/admin/api/requests/approve")
    async def api_requests_approve(token: str = "", flag: str = ""):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        info = pending_requests.get(flag)
        if not info:
            return JSONResponse({"error": "该申请已不存在或已处理"}, status_code=404)
        ok, err = await _approve_request(flag, True, "")
        if ok is None:
            return JSONResponse({"error": err}, status_code=503)
        if not ok:
            log("error", "审批", f"通过失败: {err}")
            return JSONResponse({"error": err}, status_code=500)
        log("success", "审批", f"手动通过 {info['nickname']}({info['user_id']}) @群{info['group_id']}")
        pending_requests.pop(flag, None)
        return JSONResponse({"ok": True})

    @app.post("/admin/api/requests/reject")
    async def api_requests_reject(token: str = "", flag: str = "", reason: str = ""):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        info = pending_requests.get(flag)
        if not info:
            return JSONResponse({"error": "该申请已不存在或已处理"}, status_code=404)
        ok, err = await _approve_request(flag, False, reason or "管理员拒绝了你的申请")
        if ok is None:
            return JSONResponse({"error": err}, status_code=503)
        if not ok:
            log("error", "审批", f"拒绝失败: {err}")
            return JSONResponse({"error": err}, status_code=500)
        log("block", "审批", f"手动拒绝 {info['nickname']}({info['user_id']}) @群{info['group_id']}")
        pending_requests.pop(flag, None)
        return JSONResponse({"ok": True})


# -*- coding: utf-8 -*-
r"""管理页 · api_persona 路由（2 个）。

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

    @app.get("/admin/api/persona/override")
    async def api_persona_override_get(token: str = "", key: str = ""):
        """读某个会话的人格覆盖（没填的项返回空串，前端显示成占位符）。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        ov = CFG.get("persona_overrides")
        ov = ov if isinstance(ov, dict) else {}
        one = ov.get(str(key or "").strip())
        one = one if isinstance(one, dict) else {}
        return JSONResponse({
            "key": key, "override": {
                "name": str(one.get("name") or ""),
                "identity": str(one.get("identity") or ""),
                "behavior": str(one.get("behavior") or ""),
                "speech": str(one.get("speech") or ""),
            },
            "global": {
                "name": cfg_str("persona_name"),
                "identity": cfg_str("persona_identity"),
                "behavior": cfg_str("persona_behavior"),
                "speech": cfg_str("persona_speech"),
            },
        })

    @app.post("/admin/api/persona/override")
    async def api_persona_override_set(token: str = "", request: Request = None):
        """写某个会话的人格覆盖。四项全空 = 删掉这个会话的覆盖，回到全局。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid json"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid body"}, status_code=400)
        key = str(body.get("key") or "").strip()
        if not key or ":" not in key:
            return JSONResponse({"error": "key 不合法"}, status_code=400)
        vals = {}
        for k in ("name", "identity", "behavior", "speech"):
            v = str(body.get(k) or "").strip()
            if v:
                vals[k] = v[:4000]
        ov = CFG.get("persona_overrides")
        if not isinstance(ov, dict):
            ov = {}
        if vals:
            ov[key] = vals
        else:
            ov.pop(key, None)
        CFG["persona_overrides"] = ov
        save_config()
        log("info", "聊天管理",
            f"{'设置' if vals else '清除'}会话 {key} 的人格覆盖"
            f"（{len(vals)} 项）")
        return JSONResponse({"ok": True, "key": key, "saved": len(vals)})


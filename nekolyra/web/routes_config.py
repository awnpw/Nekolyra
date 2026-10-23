# -*- coding: utf-8 -*-
r"""管理页 · api_cfg 路由（2 个）。

**注册模式**：路由函数一字未改，只是整体缩进进了 register()。

必须缩进进去：`@app.get(...)` 是装饰器，**import 时就执行**，
放模块顶层会直接 NameError: app，整个模块导不进来。

由 _routes_extract.py 生成。
"""

from fastapi import Request
from fastapi.responses import JSONResponse

__all__ = ["register"]

#: 名字以此结尾的键**一律当密钥**：不回传明文，且空值不覆盖已存的值。
#: 以前是硬编码 5 个键，漏了 openai_api_key / github_token ——
#: 那两个会被明文返回到设置页（真实泄露）。
_SECRET_SUFFIXES = ("_api_key", "_token", "_secret", "_password")


def _is_secret(key) -> bool:
    return str(key).endswith(_SECRET_SUFFIXES)


def register(app, **deps):
    r"""把这些路由挂到 app 上。deps：全局名 = 值。"""
    globals().update(deps)

    @app.get("/admin/api/config")
    async def api_cfg(token: str = ""):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        safe = dict(CFG)
        for k in list(safe.keys()):
            if _is_secret(k) and safe.get(k):
                safe[k] = ""            # 明文一律不回传
                safe[k + "_set"] = True  # 前端据此显示「留空 = 不修改」
        return JSONResponse(safe)

    @app.post("/admin/api/config")
    async def api_cfg_set(token: str = "", request: Request = None):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid body"}, status_code=400)
        except Exception:
            return JSONResponse({"error": "invalid body"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid body"}, status_code=400)

        changed = []
        for k, v in body.items():
            if k not in EDITABLE_KEYS and k not in _PLUGIN_KEYS:
                continue
            # 密钥留空 = 保持原值（打码后前端本来就会回传空串）
            if _is_secret(k) and isinstance(v, str) and not v.strip():
                continue
            if CFG.get(k) != v:
                CFG[k] = v
                changed.append(k)
        normalize_config()
        ok, err = save_config()
        if not ok:
            return JSONResponse({"error": f"写入配置失败: {err}"}, status_code=500)
        reload_config()
        if not changed:
            return JSONResponse({"ok": True, "changed": 0})
        log("success", "配置", f"更新了 {len(changed)} 项：{', '.join(changed[:8])}"
                              + (" 等" if len(changed) > 8 else ""))
        return JSONResponse({"ok": True, "changed": len(changed)})


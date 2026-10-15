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


#: 哪些键算「密钥」—— 读取时抹掉、提交空值时不覆盖。
#:
#: **按后缀判断，不写死名单。** 写死名单的坑踩过：新加了 openai_api_key，
#: 名单没跟上 —— 管理页就把完整 key 明文显示出来（而这个程序默认开
#: 局域网访问，同一个 WiFi 拿到 token 就能看到）。
#:
#: 这个项目里符合 _api_key/_token 的：deepseek/openai/vision/voice/ollama_api_key、
#: admin_token、github_token —— 全都是真密钥。
_SECRET_SUFFIXES = ("_api_key", "_token")


def is_secret_key(k):
    return str(k).endswith(_SECRET_SUFFIXES)


def register(app, **deps):
    r"""把这些路由挂到 app 上。deps：全局名 = 值。"""
    globals().update(deps)

    @app.get("/admin/api/config")
    async def api_cfg(token: str = ""):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        safe = dict(CFG)
        for k in list(safe.keys()):
            if not is_secret_key(k):
                continue
            if safe.get(k):
                safe[k] = ""
                safe[k + "_set"] = True
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
            # 密钥留空 = 不修改（页面拿到的是抹掉的空串，
            # 不当成「用户要清空」）
            if is_secret_key(k) and isinstance(v, str) and not v.strip():
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


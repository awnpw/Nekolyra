# -*- coding: utf-8 -*-
r"""管理页 · api_version 路由（1 个）。

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

    @app.get("/admin/api/version")
    async def api_version(token: str = "", force: int = 0):
        """当前版本 + 远程最新版本。force=1 时绕过缓存重新查。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        info = await fetch_latest_release(force=bool(force))
        latest = (info or {}).get("latest") or ""
        # 只有本地版本读得到、远程版本也拿到了，才谈得上"要不要更新"
        has = bool(latest and APP_VERSION and
                   _ver_tuple(latest) > _ver_tuple(APP_VERSION))
        return JSONResponse({
            "current": APP_VERSION,
            "latest": latest,
            "has_update": has,
            "name": (info or {}).get("name") or "",
            "url": (info or {}).get("url")
                   or f"https://github.com/{UPDATE_REPO}/releases/latest",
            "notes": (info or {}).get("notes") or "",
            "published": (info or {}).get("published") or "",
            "assets": (info or {}).get("assets") or [],
            "ok": info is not None,
            "error": _VER_CACHE.get("error") or "",
            # 下载源列表交给前端渲染下拉（顺序就是推荐顺序）
            "sources": [{"k": k, "label": lb} for k, lb, _p in UPDATE_SOURCES],
            # 验签能力（cryptography 有没有被打进 exe）和公钥指纹。
            # 暴露出来是为了让 _build_guard.py 能在发布前就发现"打不进去"。
            "sig_ready": _sig_ready(),
            "sig_key": RELEASE_KEY_FP,
        })


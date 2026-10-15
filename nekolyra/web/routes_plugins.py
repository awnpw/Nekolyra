# -*- coding: utf-8 -*-
r"""管理页 · 插件管理路由（9 个）。

**注册模式**：路由函数一字未改，只是整体缩进进了 register()。

为什么必须缩进进去：`@app.get(...)` 是**装饰器，import 时就执行**。
放在模块顶层的话，import 这个模块的瞬间就会 NameError: app ——
（第一版就是这样，pyflakes 直接报 undefined name app。）

为什么不用 FastAPI 的 APIRouter：那要把 80 多个 @app.get(...)
全改成 @router.get(...)，改动面大得多。

主程序在 app 建好之后调一次：

    from nekolyra.web.routes_plugins import register as _reg_plugins
    _reg_plugins(app, PLUGINS=PLUGINS, ...)
"""

import os

from fastapi import Request
from fastapi.responses import JSONResponse

__all__ = ["register"]


def register(app, **deps):
    r"""把这些路由挂到 app 上。deps 是主程序传进来的依赖（全局名 = 值）。"""
    globals().update(deps)

    @app.get("/admin/api/plugins")
    async def api_plugins(token: str = ""):
        """插件列表（含加载失败的，带 error 字段）。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        _load_plugin_state()
        dis = set(_PLUGIN_STATE.get("disabled") or [])
        items = []
        for ctx in sorted(PLUGINS.values(), key=lambda c: (c.order, c.name)):
            folder = os.path.basename(ctx.dir)
            d = ctx.info()
            d["folder"] = folder
            d["enabled"] = folder not in dis and ctx.name not in dis
            items.append(d)
        return JSONResponse({
            "dir": PLUGIN_DIR,
            "items": items,
            "count": len(items),
            "loaded": len([c for c in PLUGINS.values() if c.loaded]),
            "disabled": sorted(dis),
        })

    @app.get("/admin/api/plugins/schema")
    async def api_plugins_schema(token: str = ""):
        """插件声明的配置分组，管理界面追加到配置页。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        return JSONResponse(plugin_config_schema())

    @app.get("/admin/api/plugins/pages")
    async def api_plugins_pages(token: str = ""):
        """插件声明的管理页面。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        return JSONResponse(plugin_pages())

    @app.post("/admin/api/plugins/toggle")
    async def api_plugins_toggle(token: str = "", request: Request = None):
        """启用/停用一个插件。停用后命令和钩子立刻不响应。

        token 走 query 参数（跟前端 post() 一致），也兼容放 body 里。
        """
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid body"}, status_code=400)
        except Exception:
            body = {}
        if not _auth(token):
            token = str(body.get("token") or "")
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        key = str(body.get("key") or "").strip()
        # 严格判 True：bool("false") 是 True，字符串传进来会误开
        want = body.get("enabled") is True
        if not key:
            return JSONResponse({"error": "缺少 key"}, status_code=400)
        if key not in PLUGINS and key not in [os.path.basename(c.dir) for c in PLUGINS.values()]:
            return JSONResponse({"error": "插件不存在"}, status_code=404)
        set_plugin_enabled(key, want)
        return JSONResponse({"ok": True, "key": key, "enabled": want})

    @app.get("/admin/api/plugins/market")
    async def api_plugin_market(token: str = "", refresh: int = 0):
        """插件市场列表（带每项的本地安装状态）。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        try:
            await fetch_market(force=bool(refresh))
        except Exception as e:
            log("warn", "插件", f"拉市场索引失败：{type(e).__name__}: {e}")
        return JSONResponse(market_with_status())

    @app.post("/admin/api/plugins/install")
    async def api_plugin_install(token: str = "", request: Request = None):
        """装插件。body: {url} 或 {name}（name 从市场索引里找 repo）。"""
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid body"}, status_code=400)
        except Exception:
            body = {}
        if not _auth(token):
            token = str(body.get("token") or "")
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        url = str(body.get("url") or "").strip()
        want = str(body.get("name") or "").strip()
        if not url and want:
            try:
                await fetch_market()
            except Exception as e:
                log("warn", "插件", "api_plugin_install 吞掉异常：%s: %s" % (type(e).__name__, e))
            with _MARKET_LOCK:
                items = list(_PLUGIN_MARKET.get("items") or [])
            hit = None
            for it in items:
                if isinstance(it, dict) and str(it.get("name")) == want:
                    hit = it
                    break
            if not hit:
                return JSONResponse({"error": f"市场里没有 {want}"}, status_code=404)
            url = str(hit.get("repo") or hit.get("url") or "").strip()
            if not url:
                return JSONResponse({"error": f"{want} 没填 repo 地址"}, status_code=400)
            _subpath = str(hit.get("path") or "").strip()
        else:
            _subpath = str(body.get("path") or "").strip()
        if not url:
            return JSONResponse({"error": "要装哪个？给个 url 或 name"}, status_code=400)
        log("info", "插件", f"开始安装：{url}" + (f"（子目录 {_subpath}）" if _subpath else ""))
        try:
            r = await install_plugin_from_url(url, expect_name=want, subpath=_subpath)
        except Exception as e:
            log("error", "插件", f"安装异常：{type(e).__name__}: {e}")
            return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)
        if r.get("ok"):
            log("success", "插件",
                f"已安装 {r.get('display_name')} v{r.get('version')}"
                + ("" if r.get("loaded") else f"（但没加载成功：{r.get('error')}）"))
        else:
            log("warn", "插件", f"安装失败：{r.get('error')}")
        return JSONResponse(r, status_code=(200 if r.get("ok") else 400))

    @app.post("/admin/api/plugins/uninstall")
    async def api_plugin_uninstall(token: str = "", request: Request = None):
        """卸载插件（删目录）。"""
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid body"}, status_code=400)
        except Exception:
            body = {}
        if not _auth(token):
            token = str(body.get("token") or "")
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        key = str(body.get("name") or body.get("key") or "").strip()
        if not key:
            return JSONResponse({"error": "缺少 name"}, status_code=400)
        try:
            r = uninstall_plugin(key)
        except Exception as e:
            return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)
        if r.get("ok"):
            log("info", "插件", r.get("message") or f"已卸载 {key}")
        return JSONResponse(r, status_code=(200 if r.get("ok") else 400))

    @app.post("/admin/api/plugins/update")
    async def api_plugin_update(token: str = "", request: Request = None):
        """更新已装插件（重新拉一遍源地址）。"""
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid body"}, status_code=400)
        except Exception:
            body = {}
        if not _auth(token):
            token = str(body.get("token") or "")
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        key = str(body.get("name") or "").strip()
        if not key:
            return JSONResponse({"error": "缺少 name"}, status_code=400)
        st = (_PLUGIN_STATE.get("installed") or {}).get(key) or {}
        url = str(st.get("source") or "").strip()
        # 装的时候存下来的仓库子目录（老版本装的没有这个键，会走下面的市场兜底）
        subpath = str(st.get("path") or "").strip()
        if not url or not subpath:
            try:
                await fetch_market()
            except Exception as e:
                log("warn", "插件", "api_plugin_update 吞掉异常：%s: %s" % (type(e).__name__, e))
            with _MARKET_LOCK:
                items = list(_PLUGIN_MARKET.get("items") or [])
            for it in items:
                if isinstance(it, dict) and str(it.get("name")) == key:
                    if not url:
                        url = str(it.get("repo") or it.get("url") or "").strip()
                    if not subpath:
                        subpath = str(it.get("path") or "").strip()
                    break
        if not url:
            return JSONResponse({"error": f"不知道 {key} 从哪来的，没法更新"}, status_code=400)
        try:
            r = await install_plugin_from_url(url, expect_name=key, subpath=subpath)
        except Exception as e:
            return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)
        if r.get("ok"):
            _old = str(r.get("replaced") or "")
            log("success", "插件",
                f"已更新 {key} " + (f"{_old} -> " if _old else "-> ") + f"v{r.get('version')}")
        return JSONResponse(r, status_code=(200 if r.get("ok") else 400))

    @app.post("/admin/api/plugins/reload")
    async def api_plugins_reload(token: str = "", request: Request = None):
        """重新扫描并加载所有插件（改完插件代码点这个，不用重启）。"""
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid body"}, status_code=400)
        except Exception:
            body = {}
        if not _auth(token):
            token = str(body.get("token") or "")
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        try:
            n = reload_all_plugins()
        except Exception as e:
            return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)
        bad = [c.display_name for c in PLUGINS.values() if not c.loaded]
        return JSONResponse({"ok": True, "loaded": n, "total": len(PLUGINS), "failed": bad})


# -*- coding: utf-8 -*-
r"""管理页 · api_wall 路由（7 个）。

**注册模式**：路由函数一字未改，只是整体缩进进了 register()。

必须缩进进去：`@app.get(...)` 是装饰器，**import 时就执行**，
放模块顶层会直接 NameError: app，整个模块导不进来。

由 _routes_extract.py 生成。
"""

import base64
import os
import re

from fastapi import Request
from fastapi.responses import JSONResponse, Response

__all__ = ["register"]


def register(app, **deps):
    r"""把这些路由挂到 app 上。deps：全局名 = 值。"""
    globals().update(deps)

    @app.get("/admin/api/wallpaper/presets")
    async def api_wall_presets(token: str = ""):
        """预设列表。前端拿它画缩略图（缩略图直接渲染同一个渐变）。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        return JSONResponse({
            "presets": [{"id": p, "name": n, "css": c}
                        for p, n, c in WALL_PRESETS],
            "current": cfg_str("wallpaper_preset", "kv"),
            "rotate": cfg_bool("wallpaper_rotate", False),
            "rotate_sec": cfg_int("wallpaper_rotate_sec", 15),
            "custom": bool(wall_custom_path()),
        })

    @app.get("/admin/api/wallpaper/preset/{pid}")
    async def api_wall_preset_pic(pid: str):
        """预设里那几张角色图。

        跟 builtin 一样：图内嵌在程序里，预设只存 URL —— 不然 /admin 页面
        和 presets 接口会各背几百 KB。
        """
        import base64 as _b64
        tbl = {"pic1": WALL_PIC_PIC1, "pic2": WALL_PIC_PIC2, "pic3": WALL_PIC_PIC3}
        d = tbl.get(pid)
        if not d:
            return JSONResponse({"error": "no such preset"}, status_code=404)
        try:
            raw = _b64.b64decode(d.split("base64,", 1)[1])
        except Exception as e:
            return JSONResponse({"error": f"图损坏: {type(e).__name__}"},
                                status_code=500)
        return Response(content=raw, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/admin/api/wallpaper/builtin")
    async def api_wall_builtin():
        """把内置的那张默认壁纸吐出来。

        以前它是 `WALL_BAKED` 这个几百 KB 的 data URI，被拼进
        `WALL_PRESETS` —— 于是 /admin 页面和 /admin/api/wallpaper/presets
        各传一遍，开一次外观页光壁纸就下 500KB。
        改成走接口：两个地方都只带一个几十字节的 URL。
        不需要 token —— 它是内置资源，不含用户数据。
        """
        import base64 as _b64
        try:
            raw = _b64.b64decode(WALL_BAKED.split("base64,", 1)[1])
        except Exception as e:
            return JSONResponse({"error": f"内置壁纸损坏: {type(e).__name__}"},
                                status_code=500)
        return Response(content=raw, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/admin/api/wallpaper/raw")
    async def api_wall_raw(token: str = ""):
        """把自定义壁纸原文件吐出来。

        为什么需要它：外观页的「我的图片」缩略图以前是个写死的黑块 ——
        api_wall_state 只回 custom/name/size，前端拿不到任何可用的图片地址。
        《token 走查询参数，跟这个页面其它接口一致》
        """
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        p = wall_custom_path()
        if not p or not os.path.exists(p):
            return JSONResponse({"error": "没有自定义壁纸"}, status_code=404)
        try:
            with open(p, "rb") as f:
                data = f.read()
        except Exception as e:
            return JSONResponse({"error": f"读取失败: {type(e).__name__}"},
                                status_code=500)
        ext = os.path.splitext(p)[1].lower()
        mime = {".png": "image/png", ".webp": "image/webp",
                ".gif": "image/gif"}.get(ext, "image/jpeg")
        return Response(content=data, media_type=mime,
                        headers={"Cache-Control": "no-cache"})

    @app.get("/admin/api/wallpaper/state")
    async def api_wall_state(token: str = ""):
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        p = wall_custom_path()
        return JSONResponse({
            "on": cfg_bool("wallpaper_enabled", True),
            "dim": cfg_int("wallpaper_dim", 40),
            "blur": cfg_int("wallpaper_blur", 0),
            "custom": bool(p),
            "name": os.path.basename(p) if p else "",
            "size": (os.path.getsize(p) if p else 0),
        })

    @app.post("/admin/api/wallpaper")
    async def api_wall_set(token: str = "", request: Request = None):
        """上传壁纸。body: {"data":"<base64>","ext":".jpg"}，也接受 data URI。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid body"}, status_code=400)
        except Exception:
            return JSONResponse({"error": "invalid body"}, status_code=400)
        raw = str(body.get("data") or "")
        if not raw:
            return JSONResponse({"error": "没有收到图片数据"}, status_code=400)
        ext = str(body.get("ext") or "").lower()
        if raw.startswith("data:"):
            m = re.match(r"data:image/([a-z+]+);base64,", raw)
            if m:
                ext = "." + ("jpg" if m.group(1) == "jpeg" else m.group(1))
            raw = raw.split(",", 1)[-1]
        if ext not in WALL_EXTS:
            ext = ".jpg"
        try:
            data = base64.b64decode(raw, validate=False)
        except Exception:
            return JSONResponse({"error": "base64 解不开"}, status_code=400)
        if len(data) < 1024:
            return JSONResponse({"error": "图太小了（<1KB），不像是张图"},
                                status_code=400)
        if len(data) > 16 * 1024 * 1024:
            return JSONResponse({"error": "图太大了（>16MB），压一下再传"},
                                status_code=400)
        # 先清掉旧的，避免留下两种扩展名同时存在
        for e in WALL_EXTS:
            try:
                os.remove(WALL_STEM + e)
            except Exception as e:
                log("warn", "外观", "api_wall_set 吞掉异常：%s: %s" % (type(e).__name__, e))
        dst = WALL_STEM + ext
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
        except Exception as ex:
            return JSONResponse({"error": "写文件失败：%s" % ex}, status_code=500)
        _WALL_CACHE.update({"key": None, "uri": None})
        log("success", "外观", "壁纸已更换：%s（%.0f KB）"
            % (os.path.basename(dst), len(data) / 1024))
        return JSONResponse({"ok": True, "name": os.path.basename(dst),
                             "size": len(data)})

    @app.post("/admin/api/wallpaper/reset")
    async def api_wall_reset(token: str = ""):
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        n = 0
        for e in WALL_EXTS:
            try:
                os.remove(WALL_STEM + e)
                n += 1
            except Exception as e:
                log("warn", "外观", "api_wall_reset 吞掉异常：%s: %s" % (type(e).__name__, e))
        _WALL_CACHE.update({"key": None, "uri": None})
        log("info", "外观", "壁纸已恢复默认（删掉 %d 个自定义文件）" % n)
        return JSONResponse({"ok": True, "removed": n})


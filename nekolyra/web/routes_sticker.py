# -*- coding: utf-8 -*-
r"""管理页 · api_sticker 路由（5 个）。

**注册模式**：路由函数一字未改，只是整体缩进进了 register()。

必须缩进进去：`@app.get(...)` 是装饰器，**import 时就执行**，
放模块顶层会直接 NameError: app，整个模块导不进来。

由 _routes_extract.py 生成。
"""

import asyncio
import os

from urllib.parse import quote as _urlquote

from fastapi import Request
from fastapi.responses import JSONResponse, Response

__all__ = ["register"]


def register(app, **deps):
    r"""把这些路由挂到 app 上。deps：全局名 = 值。"""
    globals().update(deps)

    @app.get("/admin/api/stickers")
    async def api_stickers(token: str = "", kind: str = "", gid: int = 0,
                           kw: str = "", limit: int = 120, offset: int = 0):
        """表情库列表。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        try:
            limit = max(1, min(int(limit), 500))
            offset = max(0, int(offset))
        except (TypeError, ValueError):
            limit, offset = 120, 0
        items = DB.sticker_list(kind=(kind or "").strip(), gid=int(gid or 0),
                                kw=(kw or "").strip(), limit=limit, offset=offset)
        n, total_bytes = DB.sticker_count()
        # <img> 带不了请求头，所以把 token 拼进 URL —— 跟壁纸接口一个办法
        q = _urlquote(token or "", safe="")
        for it in items:
            it["url"] = "/admin/api/sticker/%s?token=%s" % (it.get("hash"), q)
        return JSONResponse({
            "items": items, "count": len(items),
            "total": n, "bytes": total_bytes,
            "max_count": cfg_int("sticker_max_count", 2000),
            "max_mb": cfg_int("sticker_max_mb", 500),
            "enabled": cfg_bool("sticker_enabled", True),
            "send_enabled": cfg_bool("sticker_send_enabled", True),
        })

    @app.post("/admin/api/stickers/cleanup")
    async def api_sticker_cleanup(token: str = ""):
        """手动跑一次清理。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        try:
            a, b, c = await asyncio.to_thread(sticker_cleanup, True)
        except Exception as e:
            return JSONResponse({"error": f"{type(e).__name__}: {e}"},
                                status_code=500)
        n, total = DB.sticker_count()
        return JSONResponse({"ok": True, "deleted": a, "files": b,
                             "freed_kb": c // 1024, "left": n,
                             "bytes": total})

    @app.get("/admin/api/sticker/{h}")
    async def api_sticker_img(h: str, token: str = ""):
        """读一张表情的原图。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        row = DB.sticker_by_hash(str(h or "").strip())
        if not row:
            return JSONResponse({"error": "not found"}, status_code=404)
        p = sticker_path(row)
        if not p or not os.path.exists(p):
            return JSONResponse({"error": "文件不在了"}, status_code=404)
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "gif": "image/gif", "webp": "image/webp",
                "bmp": "image/bmp"}.get(str(row.get("ext") or "jpg").lower(),
                                        "image/jpeg")
        try:
            with open(p, "rb") as f:
                data = f.read()
        except Exception as e:
            return JSONResponse({"error": f"{type(e).__name__}"}, status_code=500)
        return Response(content=data, media_type=mime,
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.post("/admin/api/stickers/note")
    async def api_sticker_note(token: str = "", request: Request = None):
        """改备注 / 标签。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid json"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid body"}, status_code=400)
        try:
            sid = int(body.get("id") or 0)
        except (TypeError, ValueError):
            return JSONResponse({"error": "id 必须是数字"}, status_code=400)
        if not sid:
            return JSONResponse({"error": "缺少 id"}, status_code=400)
        note = body.get("note")
        tags = body.get("tags")
        DB.sticker_set_note(sid,
                            note=None if note is None else str(note)[:1000],
                            tags=None if tags is None else str(tags)[:300])
        return JSONResponse({"ok": True})

    @app.post("/admin/api/stickers/delete")
    async def api_sticker_delete(token: str = "", request: Request = None):
        """删除（连磁盘文件一起删）。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid json"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "invalid body"}, status_code=400)
        raw = body.get("ids") or []
        if not isinstance(raw, list):
            return JSONResponse({"error": "ids 必须是数组"}, status_code=400)
        ids = []
        for x in raw[:500]:
            try:
                ids.append(int(x))
            except (TypeError, ValueError):
                log("warn", "表情库", "api_sticker_delete 吞掉异常：%s: %s" % (type(e).__name__, e))
        if not ids:
            return JSONResponse({"error": "没有有效的 id"}, status_code=400)
        hashes = DB.sticker_del(ids)
        gone = 0
        for h in hashes:
            for ext in ("jpg", "jpeg", "png", "gif", "webp", "bmp"):
                p = os.path.join(STICKER_DIR, "%s.%s" % (h, ext))
                if os.path.exists(p):
                    try:
                        os.remove(p)
                        gone += 1
                    except Exception as e:
                        log("warn", "表情库", "api_sticker_delete 吞掉异常：%s: %s" % (type(e).__name__, e))
        log("info", "表情库", f"删了 {len(hashes)} 条记录、{gone} 个文件")
        return JSONResponse({"ok": True, "deleted": len(hashes), "files": gone})


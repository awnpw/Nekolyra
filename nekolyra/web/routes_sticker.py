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
            except (TypeError, ValueError) as e:
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

    @app.post("/admin/api/stickers/retag")
    async def api_stickers_retag(token: str = "", request: Request = None):
        r"""按当前词表给已有表情重新打标签（只读已存的备注，不重新识图）。

        为什么需要它：词表换过一次（把 网络梗/游戏梗 这类内容体裁词去掉了），
        库里老数据的标签还是旧词表写的，挑图会一直按旧词匹配 —— 不重打一遍
        等于新逻辑只看得到新收进来的那几张。

        每批默认 20 张：一次请求里跑太多会顶到网关超时，前端循环调到 left=0。
        """
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        body = {}
        if request is not None:
            try:
                body = await request.json()
            except Exception:
                body = {}
        if not isinstance(body, dict):
            body = {}
        try:
            batch = int(body.get("batch") or 20)
        except (TypeError, ValueError):
            batch = 20
        batch = max(1, min(batch, 50))
        only_empty = bool(body.get("only_empty"))
        try:
            rows = DB.sticker_list(limit=100000)
        except Exception as e:
            return JSONResponse({"error": "读取表情失败：%s" % e}, status_code=500)
        vocab = globals().get("STICKER_TAG_SET") or frozenset()

        def _needs_fix(tags):
            # "需要打标的" = 标签为空，或者里面还含词表外的旧词
            # （比如以前写进去的 网络梗 / 游戏梗 / 沙雕）。
            # 这样重打一遍之后这些行就不再是候选，循环才会收敛；
            # 否则每批都在重复打前 20 张，永远打不完。
            parts = [x.strip() for x in
                     str(tags or "").replace("，", ",").split(",") if x.strip()]
            if not parts:
                return True
            if not vocab:
                return False
            return any(p not in vocab for p in parts)

        todo = []
        for it in rows:
            note = str(it.get("note") or "").strip()
            tags = str(it.get("tags") or "").strip()
            if not note:
                continue          # 没描述就没法打标（等它被识图一次）
            if only_empty and tags:
                continue
            if not only_empty and not _needs_fix(tags):
                continue          # 标签已经全是新词表里的，跳过
            todo.append(it)
        done = same = fail = 0
        for it in todo[:batch]:
            sid = it.get("id")
            note = str(it.get("note") or "").strip()
            old_tags = str(it.get("tags") or "").strip()
            try:
                tg = await emotion_tags_for(note, keep=6)
            except Exception as e:
                fail += 1
                log("warn", "表情库", "重打标失败 id=%s: %s: %s" % (sid, type(e).__name__, e))
                continue
            if not tg:
                fail += 1
                continue
            if tg == old_tags:
                same += 1
                continue
            try:
                DB.sticker_set_note(sid, tags=tg)
                done += 1
            except Exception as e:
                fail += 1
                log("warn", "表情库", "重打标写库失败 id=%s: %s" % (sid, e))
        left = max(0, len(todo) - batch)
        if done or fail:
            log("info", "表情库", "重新打标：更新 %d 张（未变 %d、失败 %d），还剩 %d"
                % (done, same, fail, left))
        return JSONResponse({"ok": True, "done": done, "same": same, "fail": fail,
                             "left": left, "batch": batch, "total": len(todo)})


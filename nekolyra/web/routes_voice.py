# -*- coding: utf-8 -*-
r"""管理页 · api_voice 路由（2 个）。

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

    @app.get("/admin/api/voice/list")
    async def api_voice_list(token: str = ""):
        r"""可用音色列表（转发语音服务的 /v1/audio/voices）。

        管理页「这个会话的人格」用它填下拉框。语音服务没起来时返回空列表
        而不是报错 —— 用户至少还能手填音色名。

        路径必须跟 bot.py 的 _fetch_voice_names 一致（那里 /speech -> /voices，
        所以默认配置 http://127.0.0.1:7861/v1/audio/speech 要问
        /v1/audio/voices）。以前这里拼的是 /v1/voices，服务端 404，
        下拉框永远空的。
        """
        if not _auth(token):
            return JSONResponse({"error": "invalid token"}, status_code=401)
        base = (cfg_str("voice_api_url") or "").strip().rstrip("/")
        if not base:
            return JSONResponse({"ok": True, "items": [], "note": "未配置语音服务地址"})
        if base.endswith("/speech"):
            url = base[:-len("/speech")] + "/voices"
        else:
            url = base + "/voices"
        items = []
        note = ""
        try:
            r = await get_http().get(url, timeout=20.0)
            if r.status_code == 200:
                data = r.json()
                arr = data.get("data") if isinstance(data, dict) else data
                for x in (arr or []):
                    if isinstance(x, dict):
                        # 音色名在 name 里（bot.py 的 _fetch_voice_names 只读 name，
                        # voice_name 配置存的也是它）。以前优先取 id，
                        # 真拿到的 id 填进配置合成时服务端不认。
                        nm = str(x.get("name") or x.get("id") or "").strip()
                    else:
                        nm = str(x).strip()
                    if nm:
                        items.append({"id": nm, "name": nm})
            else:
                note = "语音服务返回 HTTP %s" % r.status_code
        except Exception as e:
            note = "%s: %s" % (type(e).__name__, e)
            log("warn", "语音", "取音色列表失败：%s" % note)
        return JSONResponse({"ok": True, "items": items, "count": len(items), "note": note})

    @app.get("/api/voice/test")
    async def api_voice_test(token: str = "", text: str = ""):
        if not _auth(token): return JSONResponse({"error": "invalid token"}, status_code=401)
        text = (text or "").strip()
        if not text:
            return JSONResponse({"ok": False, "error": "缺少 text"})
        return JSONResponse(await _voice_test_impl(text))

    @app.post("/api/voice/send")
    async def api_voice_send(token: str = "", request: Request = None):
        if not _auth(token): return JSONResponse({"error": "invalid token"}, status_code=401)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid body"}, status_code=400)
        except Exception:
            return JSONResponse({"error": "invalid body"}, status_code=400)
        try:
            gid = int(body.get("group_id", 0))
        except (TypeError, ValueError):
            return JSONResponse({"error": "group_id 必须是数字"}, status_code=400)
        text = str(body.get("text", "")).strip()
        # 群号必须为正。以前写的是 `not gid` —— 但 `not -1` 是 False，
        # 负数会一路传到 bot.send_group_msg(group_id=-1)，拿一个 NapCat 的
        # 接口报错回来。不折算成 0：那会把"发到负群号"静默变成"发到别处"。
        if gid <= 0 or not text:
            return JSONResponse(
                {"error": "group_id 必须是正整数，且 text 不能为空"},
                status_code=400)
        return JSONResponse(await _send_voice_impl(gid, text))


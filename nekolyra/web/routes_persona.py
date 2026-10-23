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
                "voice": str(one.get("voice") or ""),
                "voice_chance": str(one.get("voice_chance") or ""),
            },
            "global": {
                "name": cfg_str("persona_name"),
                "identity": cfg_str("persona_identity"),
                "behavior": cfg_str("persona_behavior"),
                "speech": cfg_str("persona_speech"),
                "voice": cfg_str("voice_name"),
                "voice_chance": str(cfg_float("voice_random_chance")),
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
        # 只处理**这次真的提交了**的字段：没提交的保持原样。
        # 以前是整体替换 —— 前端音色下拉是异步加载的，用户在前端还没拉到列表
        # 时点保存，提交的 voice 是空串，结果把已经设好的音色抹掉了
        # （线上真实发生：私聊设的音色凭空消失，听感又变回全局）。
        ov = CFG.get("persona_overrides")
        if not isinstance(ov, dict):
            ov = {}
        _fields = ("name", "identity", "behavior", "speech", "voice", "voice_chance")
        _sent = [k for k in _fields if k in body]
        if not _sent:
            # 一个人格字段都没提交 = 管理页的「清除独立人格」按钮（它只发 key）。
            # 不特判的话上面那条"没提交就保留原值"会把覆盖原样留着，
            # 前端却提示"已恢复全局" —— 实际什么都没清（音色/概率照旧生效）。
            one = {}
            ov.pop(key, None)
        else:
            one = ov.get(key)
            one = dict(one) if isinstance(one, dict) else {}
            for k in _sent:
                v = str(body.get(k) or "").strip()
                if v:
                    one[k] = v[:4000]
                else:
                    one.pop(k, None)           # 明确提交了空 -> 清除这一项
            if one:
                ov[key] = one
            else:
                ov.pop(key, None)
        vals = one
        CFG["persona_overrides"] = ov
        # 写盘失败必须报出来 —— 以前忽略返回值，磁盘满/只读时也回 {"ok": True}，
        # 前端显示"已保存"，实际重启就没了。
        _ok, _err = save_config()
        if not _ok:
            return JSONResponse({"error": f"写入配置失败: {_err}"}, status_code=500)
        log("info", "聊天管理",
            f"{'设置' if vals else '清除'}会话 {key} 的人格覆盖"
            f"（{len(vals)} 项）")
        return JSONResponse({"ok": True, "key": key, "saved": len(vals)})


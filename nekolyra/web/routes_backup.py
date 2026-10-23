# -*- coding: utf-8 -*-
r"""管理页 · api_backup 路由（2 个）。

**注册模式**：路由函数一字未改，只是整体缩进进了 register()。

必须缩进进去：`@app.get(...)` 是装饰器，**import 时就执行**，
放模块顶层会直接 NameError: app，整个模块导不进来。

由 _routes_extract.py 生成。
"""

import datetime
import os

from fastapi.responses import JSONResponse

__all__ = ["register"]


def register(app, **deps):
    r"""把这些路由挂到 app 上。deps：全局名 = 值。"""
    globals().update(deps)

    @app.get("/api/backup/list")
    async def api_backup_list(token: str = ""):
        if not _auth(token): return JSONResponse({"error": "invalid token"}, status_code=401)
        items = []
        if os.path.isdir(BACKUP_DIR):
            for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
                if f.startswith("bot-") and f.endswith(".db"):
                    p = os.path.join(BACKUP_DIR, f)
                    try:
                        items.append({
                            "file": f,
                            "date": f[4:-3],
                            "size_kb": os.path.getsize(p) // 1024,
                            "mtime": datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M"),
                        })
                    except Exception as e:
                        log("warn", "备份", "api_backup_list 吞掉异常：%s: %s" % (type(e).__name__, e))
        return JSONResponse({"items": items, "dir": BACKUP_DIR})

    @app.post("/api/backup/now")
    async def api_backup_now(token: str = ""):
        if not _auth(token): return JSONResponse({"error": "invalid token"}, status_code=401)
        ok, msg = backup_db(force=True)
        if not ok:
            return JSONResponse({"ok": False, "error": msg}, status_code=500)
        dst = os.path.join(BACKUP_DIR, f"bot-{datetime.date.today().isoformat()}.db")
        return JSONResponse({"ok": True, "file": os.path.basename(dst),
                             "size_kb": (os.path.getsize(dst) // 1024) if os.path.exists(dst) else 0})


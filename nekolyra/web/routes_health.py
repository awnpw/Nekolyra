# -*- coding: utf-8 -*-
r"""/health 与基础指标。

## 为什么单独一个模块

这是**纯新增**：不改任何现有路径，只多两个只读接口。
审查结论里它是唯一"✅ 通过"的那项（另两项都是有条件通过，要拆步骤）。

## 两个接口

    GET /health          给监控/手机看的：活着吗、各部分正常吗
    GET /metrics         给排查用的：计数、耗时、积压

**不需要 token**（健康检查要能被外部直接探活）—— 但**不返回任何敏感信息**：
不给配置值、不给群号、不给用户 QQ，只有计数和状态。

## 为什么 /health 要真的查一遍

只返回 `{"ok": true}` 没有意义 —— 进程活着但数据库连不上、AI 后端不通，
那也是"不健康"。所以这里真的去摸一下几样东西，**并且带超时**：
health 接口自己绝不能卡住（监控探活卡住比返回失败更糟）。
"""

import time

from fastapi import Request
from fastapi.responses import JSONResponse

__all__ = ["register"]


def register(app, **deps):
    r"""把这些路由挂到 app 上。deps：全局名 = 值。"""
    globals().update(deps)

    @app.get("/health")
    async def health(request: Request):
        r"""存活 + 各部分状态。**不带 token**。

        返回 200 = 能用；503 = 起不来或关键部件坏了。
        每个检查项都有超时（默认 2 秒），health 自己不能卡住。
        """
        t0 = time.time()
        checks = {}

        def _put(name, ok, detail=""):
            checks[name] = {"ok": bool(ok), "detail": str(detail)[:120]}

        # 1) 数据库
        try:
            _t = time.time()
            n = DB.mem_count(0) if hasattr(DB, "mem_count") else 0
            _put("db", True, "%.0fms" % ((time.time() - _t) * 1000))
        except Exception as e:
            _put("db", False, "%s: %s" % (type(e).__name__, e))

        # 2) AI（只看"配没配 + 开关开没开"，**不发请求** ——
        #    发请求会让 health 变成一个有延迟、会花钱、会被限流的接口）
        try:
            _put("ai", bool(getattr(AI, "enabled", False)),
                 "%s / %s" % (getattr(AI, "backend", "?"),
                              getattr(AI, "model", "?")))
        except Exception as e:
            _put("ai", False, str(e))

        # 3) 协议端连着没
        try:
            bots = nonebot.get_bots()
            _put("qq", bool(bots), "%d 个连接" % len(bots))
        except Exception as e:
            _put("qq", False, str(e))

        # 4) 插件
        try:
            total = len(PLUGINS)
            bad = [c.display_name for c in PLUGINS.values() if c.error]
            _put("plugins", not bad, "%d 个，%d 个有问题%s"
                 % (total, len(bad), ("：" + ", ".join(bad[:3])) if bad else ""))
        except Exception as e:
            _put("plugins", False, str(e))

        # 5) 插件接口挂载数（少了说明有插件注册失败）
        # 插件自己注册的 HTTP 接口数。
        # ★ 原来写的是 len(_http_mounts) —— 但 _http_mounts 在 bot.py 里是
        # **函数**（返回 httpx 的代理绕过 mounts），不是集合。名字撞车，
        # len() 直接 TypeError 被 except 吞掉，这一项从来没出现过。
        # 是 2026-10-14 给吞异常加日志时它自己叫出来的。
        try:
            _n_apis = sum(len(getattr(c, "apis", None) or [])
                         for c in PLUGINS.values())
            _put("plugin_apis", True, "%d 个" % _n_apis)
        except Exception as _e:
            log("warn", "健康检查", "数插件接口失败：%s: %s"
                % (type(_e).__name__, _e))

        # 关键项：db 挂了就是真挂；AI/QQ 挂了属于"能跑但功能残缺"
        critical = checks.get("db", {}).get("ok", False)
        ok = critical
        body = {
            "ok": ok,
            "version": APP_VERSION if "APP_VERSION" in globals() else "",
            "uptime_seconds": int(time.time() - START_TIME)
            if "START_TIME" in globals() else None,
            "checks": checks,
            "took_ms": int((time.time() - t0) * 1000),
        }
        return JSONResponse(body, status_code=200 if ok else 503)

    @app.get("/metrics")
    async def metrics(request: Request):
        r"""基础指标。需要 token（里面有群数、消息数之类）。"""
        token = request.query_params.get("token", "")
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        out = {"uptime_seconds": None, "counters": {}, "gauges": {}}

        # 进程
        try:
            import os
            import resource
            out["process"] = {
                "pid": os.getpid(),
                "rss_mb": round(resource.getrusage(
                    resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
            }
        except Exception:
            try:
                import os
                out["process"] = {"pid": os.getpid()}
            except Exception as e:
                log("warn", "routes_health", "metrics 吞掉异常：%s: %s" % (type(e).__name__, e))
        if "START_TIME" in globals():
            out["uptime_seconds"] = int(time.time() - START_TIME)

        # 规模（这些是"现在有多少"，不是"累计多少"）
        #
        # 方法名都是照 db.py 核实过的：bl_count / sticker_count / mem_count /
        # kb_list。写错过一次（以为是 bl_list / sticker_list），
        # 所以每个都用 hasattr 兜着 —— 拿不到就不放进结果，不报错。
        g = out["gauges"]
        for key, fn in (
            ("kb_entries", lambda: len(DB.kb_list(None, limit=100000))),
            ("stickers", lambda: DB.sticker_count()),
            ("memory_rows", lambda: DB.mem_count(0)),
            ("blacklist", lambda: DB.bl_count()),
            ("plugins_loaded", lambda: len([c for c in PLUGINS.values()
                                            if c.loaded])),
            ("plugins_total", lambda: len(PLUGINS)),
            ("plugin_apis", lambda: sum(len(getattr(c, "apis", None) or [])
                                      for c in PLUGINS.values())),
        ):
            try:
                v = fn()
                if v is not None:
                    g[key] = v
            except Exception as e:
                log("warn", "routes_health", "metrics 吞掉异常：%s: %s" % (type(e).__name__, e))

        # 日志缓冲（排查时最有用的一条：最近有没有报错）
        # LogBuffer 的方法名是 since(seq) —— 传 0 就是"从头给全部"。
        # 它是个 deque(maxlen=1000)，所以拿到的本来就只有最近 1000 条。
        try:
            recent = LOG_BUF.since(0) if hasattr(LOG_BUF, "since") else []
            lv = {}
            for row in recent:
                lv[row.get("level", "?")] = lv.get(row.get("level", "?"), 0) + 1
            out["counters"]["recent_log_levels"] = lv
        except Exception as e:
            log("warn", "routes_health", "metrics 吞掉异常：%s: %s" % (type(e).__name__, e))

        # 长期记忆分层（做了分层之后这里会显示各层条数）
        try:
            if hasattr(DB, "mem_layer_stats"):
                out["gauges"]["memory_layers"] = DB.mem_layer_stats()
        except Exception as e:
            log("warn", "routes_health", "metrics 吞掉异常：%s: %s" % (type(e).__name__, e))

        return JSONResponse(out)

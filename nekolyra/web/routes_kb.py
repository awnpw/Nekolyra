# -*- coding: utf-8 -*-
r"""管理页 · api_kb 路由（15 个）。

**注册模式**：路由函数一字未改，只是整体缩进进了 register()。

必须缩进进去：`@app.get(...)` 是装饰器，**import 时就执行**，
放模块顶层会直接 NameError: app，整个模块导不进来。

由 _routes_extract.py 生成。
"""

from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

__all__ = ["register"]


def register(app, **deps):
    r"""把这些路由挂到 app 上。deps：全局名 = 值。"""
    globals().update(deps)

    @app.get("/admin/api/kb/categories")
    async def api_kb_categories(token: str = "", group_id: int = -1, game: str = ""):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        g = None if group_id < 0 else group_id
        return JSONResponse({
            "categories": [{"name": c, "count": n} for c, n in
                           kb_category_counts(g, game or None)],
            "games": [{"name": x, "count": n} for x, n in kb_game_counts(g)],
            "total": len(DB.kb_list(g, limit=100000)),
            "order": KB_CATEGORY_ORDER,
            "game_order": KB_GAMES,
        })

    @app.post("/admin/api/kb/reclassify")
    async def api_kb_reclassify(token: str = "", group_id: int = -1):
        """按问题内容重新打标签（游戏 + 分类，保留具体名词标签）。"""
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        g = None if group_id < 0 else group_id
        stat = kb_reclassify(g)
        log("success", "知识库",
            f"重新分类：{stat['total']} 条，改动 {stat['changed']} 条，游戏分布 {stat['games']}")
        return JSONResponse({"ok": True, **stat})

    @app.post("/admin/api/kb/clear_category")
    async def api_kb_clear_category(token: str = "", request: Request = None):
        """按 文件夹/游戏/分类 批量删除。body: {folder?, category?, game?, group_id?}

        folder 传 "" 表示"根目录（未归档）"；不传该键表示不按文件夹过滤。
        """
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid body"}, status_code=400)
        except Exception:
            return JSONResponse({"error": "invalid body"}, status_code=400)
        # all=True 才表示"不设范围、整库清"。必须显式传 ——
        # 光靠"不传 folder" 不行：下面的守卫会拦，而且太容易误用。
        #
        # 踩过的坑：前端在「全部条目」下传的是 folder:""，
        # 而后端把 "" 解释成"根目录（未归档）"。UI 写着「清空全部条目」，
        # 实际只删了未归档那部分，其余安静地留在各文件夹里 —— 不可恢复。
        all_ = bool(body.get("all"))
        cat = str(body.get("category", "")).strip()
        gm = str(body.get("game", "")).strip()
        folder = body.get("folder", None)
        if folder is not None:
            folder = str(folder).strip().strip("/")
        if not all_ and not cat and not gm and folder is None:
            return JSONResponse({"error": "缺少 all / folder / category / game"},
                                status_code=400)
        try:
            gid = int(body.get("group_id", -1))
        except (TypeError, ValueError):
            gid = -1
        rows = _kb_filter(DB.kb_list(None if gid < 0 else gid, limit=100000),
                          cat, gm, None if all_ else folder)
        deleted = 0
        for r in rows:
            if DB.kb_delete(r["id"]):
                deleted += 1
        label = " / ".join(x for x in (gm, cat, folder if folder is not None else "") if x)
        if not label:
            label = "全部（含所有文件夹）" if all_ else (
                "根目录（未归档）" if folder == "" else "全部")
        log("block", "知识库", f"按范围删除「{label}」：{deleted} 条")
        return JSONResponse({"ok": True, "deleted": deleted, "label": label})

    @app.get("/admin/api/kb/folders")
    async def api_kb_folders(token: str = "", group_id: int = -1):
        """文件夹树（含空文件夹）。"""
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        g = None if group_id < 0 else group_id
        rows = DB.kb_list(g, limit=100000)
        counts = {}
        root = 0
        for r in rows:
            f = (r.get("folder") or "").strip()
            if f:
                counts[f] = counts.get(f, 0) + 1
            else:
                root += 1
        paths = DB.kb_folder_list(g)
        for p in paths:
            counts.setdefault(p, 0)
        return JSONResponse({
            "folders": [{"path": p, "count": counts.get(p, 0)} for p in paths],
            "root_count": root,
            "total": len(rows),
        })

    @app.post("/admin/api/kb/folder/create")
    async def api_kb_folder_create(token: str = "", request: Request = None):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid body"}, status_code=400)
        except Exception:
            return JSONResponse({"error": "invalid body"}, status_code=400)
        path = str(body.get("path", "")).strip().strip("/")
        if not path:
            return JSONResponse({"error": "文件夹名不能为空"}, status_code=400)
        if len(path) > 120:
            return JSONResponse({"error": "文件夹名太长"}, status_code=400)
        if ".." in path:
            return JSONResponse({"error": "文件夹名不能包含 .."}, status_code=400)
        try:
            gid = int(body.get("group_id", 0))
        except (TypeError, ValueError):
            gid = 0
        if gid < 0:
            gid = 0          # 负数 = 幽灵群，文件夹谁也看不到
        DB.kb_folder_create(gid, path)
        log("success", "知识库", f"新建文件夹「{path}」@群{gid}")
        return JSONResponse({"ok": True, "path": path})

    @app.post("/admin/api/kb/folder/delete")
    async def api_kb_folder_delete(token: str = "", request: Request = None):
        """删除文件夹（只删文件夹本身，里面的条目移回根目录，不删条目）。"""
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid body"}, status_code=400)
        except Exception:
            return JSONResponse({"error": "invalid body"}, status_code=400)
        path = str(body.get("path", "")).strip()
        if not path:
            return JSONResponse({"error": "缺少 path"}, status_code=400)
        # kb_folders 是按 group_id 隔离存的（见 kb_folder_create）。
        # 这里以前调 DB.kb_folder_delete(path)，g 是 None -> 走全库分支，
        # 把**所有群**的同名文件夹一起删了：A 群建了「剧情」、B 群也建了，
        # 在 A 群点删除，B 群的一起没。
        # 默认取 0（共享域）而不是 None —— "没传"绝不该等于"删全部"。
        try:
            g = int(body.get("group_id", 0))
        except (TypeError, ValueError):
            g = 0
        # 跟 kb_folder_create 一个约定：-1（全部群视图）按共享域处理
        if g < 0:
            g = 0
        DB.kb_folder_delete(path, g)
        log("block", "知识库", f"删除文件夹「{path}」@群{g}（条目已移回根目录）")
        return JSONResponse({"ok": True, "path": path})

    @app.post("/admin/api/kb/move")
    async def api_kb_move(token: str = "", request: Request = None):
        """把条目移动到指定文件夹（folder 为空 = 移回根目录）。"""
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid body"}, status_code=400)
        except Exception:
            return JSONResponse({"error": "invalid body"}, status_code=400)
        folder = str(body.get("folder", "")).strip().strip("/")
        ids = body.get("ids")
        if ids is None and body.get("id") is not None:
            ids = [body.get("id")]
        if not isinstance(ids, list) or not ids:
            return JSONResponse({"error": "缺少 id 或 ids"}, status_code=400)
        if ".." in folder:
            return JSONResponse({"error": "文件夹名不能包含 .."}, status_code=400)
        # 移到不存在的文件夹时自动创建，避免"移了个假文件夹"
        if folder:
            try:
                _mg = int(body.get("group_id", 0))
                DB.kb_folder_create(_mg if _mg > 0 else 0, folder)
            except Exception as e:
                log("warn", "知识库", "api_kb_move 吞掉异常：%s: %s" % (type(e).__name__, e))
        n = DB.kb_set_folders_bulk(ids, folder)
        log("success", "知识库", f"移动 {n} 条 -> 「{folder or '根目录'}」")
        return JSONResponse({"ok": True, "moved": n, "folder": folder})

    @app.get("/admin/api/kb")
    async def api_kb_list(token: str = "", group_id: int = -1, q: str = "",
                          category: str = "", game: str = "",
                          folder: Optional[str] = None, limit: int = 200,
                          offset: int = 0):
        # limit 是每页条数，默认 200；offset 是起始下标，两者配合翻页。
        # 这两个参数只影响 items / shown / has_more，meta 里的统计照旧全量算。
        #
        # 以前没这个参数、一次返回 5000 条（实测 2111 条 = 1.27 MB），
        # 浏览器渲染两千多个 DOM 节点就卡住 —— 表现是「知识库打不开」。
        # 实测后端只要 0.08 秒，慢的从来不是这里，但让前端少渲染十倍有效。
        #
        # meta 里的统计不受 limit 影响（分类数 / 群数 / 总数照旧全量算），
        # 所以筛选下拉和文件夹树的表现跟以前一样。
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        g = None if group_id < 0 else group_id
        try:
            _lim = max(1, min(int(limit), 2000))
        except (TypeError, ValueError):
            _lim = 200
        try:
            _off = max(0, int(offset))
        except (TypeError, ValueError):
            _off = 0
        meta = {
            "categories": [{"name": c, "count": n} for c, n in
                           kb_category_counts(g, game or None)],
            "games": [{"name": x, "count": n} for x, n in kb_game_counts(g)],
            "total": len(DB.kb_list(g, limit=100000)),
        }
        if q.strip():
            qn = _kb_norm(q)
            tq = _kb_terms(q)
            rows = DB.kb_list(g, limit=5000)
            scored = sorted(((_kb_score(tq, qn, r), r) for r in rows), key=lambda x: -x[0])
            hits = [_kb_row_out(r, s) for s, r in scored if s > 0.05]
            matched = len(hits)
            page = hits[_off:_off + _lim]
            return JSONResponse({"items": page, "query": q,
                                 "shown": len(page), "matched": matched,
                                 "offset": _off,
                                 "has_more": (_off + len(page)) < matched,
                                 "groups": DB.kb_groups(), **meta})
        rows = DB.kb_list(g, limit=5000)
        # 这一段以前会整体 500（异常被 FastAPI 吞掉、日志里连 traceback 都没有），
        # 表现是知识库**整页打不开**：loadKB 的第二次请求（文件夹树 allForTree）
        # 带 folder= 参数，它一 500，loadKB 就中断，列表根本没渲染。
        #
        # 这里把异常抓出来、**写进日志和响应体** —— 先让它可见，再谈修。
        # 顺带保证页面不再因为这一处而空白。
        try:
            rows = _kb_filter(rows, category, game, folder)
        except Exception as e:
            import traceback as _tb
            _err = "%s: %s" % (type(e).__name__, e)
            log("error", "知识库",
                "折叠筛选失败（folder=%r category=%r game=%r）：%s\n%s"
                % (folder, category, game, _err, _tb.format_exc()))
            return JSONResponse({"items": [], "groups": DB.kb_groups(),
                                 "filter_error": _err, "offset": _off,
                                 "has_more": False, "shown": 0, "matched": 0,
                                 **meta})
        matched = len(rows)
        rows = rows[_off:_off + _lim]
        items = [_kb_row_out(r) for r in rows]
        return JSONResponse({"items": items, "groups": DB.kb_groups(),
                             "shown": len(items), "matched": matched,
                             "offset": _off,
                             "has_more": (_off + len(items)) < matched,
                             **meta})

    @app.post("/admin/api/kb/add")
    async def api_kb_add(token: str = "", request: Request = None):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
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
        if gid < 0:
            gid = 0          # 负数 = 幽灵群，条目在任何群里都查不到
        ok, res = kb_add_entry(gid, body.get("question", ""), body.get("answer", ""),
                               tags=str(body.get("tags", "")), uid=0, uname="控制台",
                               folder=str(body.get("folder", "")))
        if not ok:
            return JSONResponse({"error": res}, status_code=400)
        return JSONResponse({"ok": True, **res})

    @app.post("/admin/api/kb/update")
    async def api_kb_update(token: str = "", request: Request = None):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid body"}, status_code=400)
        except Exception:
            return JSONResponse({"error": "invalid body"}, status_code=400)
        try:
            kid = int(body.get("id", 0))
        except (TypeError, ValueError):
            return JSONResponse({"error": "id 必须是数字"}, status_code=400)
        if not kid:
            return JSONResponse({"error": "缺少 id"}, status_code=400)
        if not DB.kb_get(kid):
            return JSONResponse({"error": "条目不存在"}, status_code=404)
        max_ans = cfg_int("kb_answer_max_chars", 500)
        ans = body.get("answer")
        if ans is not None and len(str(ans)) > max_ans:
            return JSONResponse({"error": f"答案太长（最多 {max_ans} 字）"}, status_code=400)
        # 这里的 group_id 是"把条目改挂到哪个群"。
        # 负数会挪进幽灵群（kb_list 过滤是 IN (0,?)，之后任何群都看不到）；
        # 而且 int() 以前不在 try 里，传个非数字会直接 500。
        gid = body.get("group_id")
        move_gid = None
        if gid is not None and gid != "":
            try:
                move_gid = int(gid)
            except (TypeError, ValueError):
                return JSONResponse({"error": "group_id 必须是数字"}, status_code=400)
            if move_gid < 0:
                move_gid = 0
        ok = DB.kb_update(kid, question=body.get("question"), answer=ans,
                          tags=body.get("tags"), group_id=move_gid)
        if not ok:
            return JSONResponse({"error": "没有需要更新的字段"}, status_code=400)
        log("success", "知识库", f"更新 #{kid}")
        return JSONResponse({"ok": True, "item": _kb_row_out(DB.kb_get(kid))})

    @app.post("/admin/api/kb/delete")
    async def api_kb_delete(token: str = "", request: Request = None):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid body"}, status_code=400)
        except Exception:
            return JSONResponse({"error": "invalid body"}, status_code=400)
        ids = body.get("ids")
        if ids is None and body.get("id") is not None:
            ids = [body.get("id")]
        if not isinstance(ids, list) or not ids:
            return JSONResponse({"error": "缺少 id 或 ids"}, status_code=400)
        deleted = 0
        for raw in ids:
            try:
                if DB.kb_delete(int(raw)):
                    deleted += 1
            except (TypeError, ValueError):
                continue
        log("block", "知识库", f"控制台删除 {deleted} 条")
        return JSONResponse({"ok": True, "deleted": deleted})

    @app.post("/admin/api/kb/clear")
    async def api_kb_clear(token: str = "", group_id: int = 0):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        n = DB.kb_clear_group(group_id)
        log("block", "知识库", f"清空群 {group_id} 的 {n} 条知识")
        return JSONResponse({"ok": True, "deleted": n})

    @app.get("/admin/api/kb/search")
    async def api_kb_search(token: str = "", group_id: int = 0, text: str = ""):
        """模拟群里的匹配效果，用来调阈值。"""
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        if not text.strip():
            return JSONResponse({"error": "缺少 text"}, status_code=400)
        qn = _kb_norm(text)
        tq = _kb_terms(text)
        rows = DB.kb_list(group_id, limit=5000)
        scored = sorted(((_kb_score(tq, qn, r), r) for r in rows), key=lambda x: -x[0])
        thr = cfg_float("kb_match_threshold", 0.5)
        return JSONResponse({
            "query": text,
            "threshold": thr,
            "would_hit": [_kb_row_out(r, s) for s, r in scored if s >= thr][:10],
            "near_miss": [_kb_row_out(r, s) for s, r in scored if 0.05 < s < thr][:10],
        })

    @app.post("/admin/api/kb/import")
    async def api_kb_import(token: str = "", request: Request = None):
        """批量导入：{"group_id":0,"items":[{"question":..,"answer":..,"tags":..}]}
        也接受纯文本 lines（每行「问题|答案」）。"""
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
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
        # 负数会写进"幽灵群"：kb_list 的过滤是 group_id IN (0,?)，-1 的条目
        # 在任何具体群里都查不到，聊天也检索不到 —— 等于白导入。
        # 接口层不该接受这种值，一律归到全局（0）。
        if gid < 0:
            gid = 0

        items = body.get("items")
        if items is None and isinstance(body.get("text"), str):
            parsed = []
            for line in body["text"].splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                q, a = parse_kb_add(line)
                if q and a:
                    parsed.append({"question": q, "answer": a})
            items = parsed
        if not isinstance(items, list) or not items:
            return JSONResponse({"error": "没有可导入的条目（格式：每行「问题|答案」）"},
                                status_code=400)

        added, failed = 0, []
        folder_default = str(body.get("folder", "")).strip()
        for it in items:
            if not isinstance(it, dict):
                failed.append("格式错误")
                continue
            ok, res = kb_add_entry(gid, it.get("question", ""), it.get("answer", ""),
                                   tags=str(it.get("tags", "")), uid=0, uname="导入",
                                   folder=str(it.get("folder", folder_default)))
            if ok:
                added += 1
            else:
                failed.append(f"{str(it.get('question'))[:20]}: {res}")
        log("success", "知识库", f"导入 {added} 条到群 {gid}，失败 {len(failed)}")
        return JSONResponse({"ok": True, "added": added, "failed": failed[:20],
                             "failed_count": len(failed)})

    @app.get("/admin/api/kb/export")
    async def api_kb_export(token: str = "", group_id: int = -1):
        if not _auth(token): return JSONResponse({"error": "invalid"}, status_code=401)
        rows = DB.kb_list(None if group_id < 0 else group_id, limit=20000)
        lines = [f"{r['question']}|{r['answer']}" for r in rows]
        return JSONResponse({"text": "\n".join(lines), "count": len(rows)})


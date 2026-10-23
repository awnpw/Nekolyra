# -*- coding: utf-8 -*-
r"""管理页 · api_update 路由（6 个）。

**注册模式**：路由函数一字未改，只是整体缩进进了 register()。

必须缩进进去：`@app.get(...)` 是装饰器，**import 时就执行**，
放模块顶层会直接 NameError: app，整个模块导不进来。

由 _routes_extract.py 生成。
"""

import asyncio
import httpx
import os
import re
import subprocess
import time

from fastapi.responses import JSONResponse, Response

__all__ = ["register"]


def register(app, **deps):
    r"""把这些路由挂到 app 上。deps：全局名 = 值。"""
    globals().update(deps)

    @app.post("/admin/api/update/fetch")
    async def api_update_fetch(token: str = "", name: str = "", src: str = "direct"):
        r"""开始把更新包下到 data/updates/。立刻返回，进度靠 progress 接口轮询。

        为什么不在浏览器里下：一是要停在"这个程序里"，二是页面里的
        blob 下载在 pywebview 窗口里不一定可用。后端落盘最稳。
        """
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        if _UPDATE_DL["busy"]:
            # 跟 api_update_progress 同一个坑：busy 为真时 task 必然是个
            # asyncio.Task，dict() 浅拷贝带进去 -> JSONResponse 序列化抛
            # TypeError -> 500。用户重复点「下载」本该看到「已有下载在进行」，
            # 实际看到的是 500。
            return JSONResponse({"error": "已经有一个下载在进行",
                                 "state": _update_snapshot()}, status_code=409)
        want = str(name or "").strip()
        info = await fetch_latest_release()
        if not info:
            return JSONResponse({"error": "拿不到 Release 信息"
                                 + (f"（{_VER_CACHE.get('error') or ''}）")},
                                status_code=502)
        hit = next((a for a in (info.get("assets") or [])
                    if a.get("name") == want), None)
        if hit is None:
            return JSONResponse({"error": f"这次 Release 里没有 {want}"}, status_code=404)
        if src not in UPDATE_SRC_MAP:
            src = "direct"
        info["_want"] = want
        src, label, url = _update_pick_source(info, src)

        # 取校验和 + 签名状态。**直连也要取** —— 签名有效时直连下完同样比对，
        # 否则"账号被拿走 -> 投毒直连路径"照样得手。
        expect, sums_state = await _update_expected_sha(want, info.get("tag") or "")
        if sums_state == "bad":
            # 有签名但验不过：这是发布被篡改的强信号，任何来源都不许装
            log("error", "更新", f"{want} 的发布签名验证失败，拒绝下载")
            return JSONResponse(
                {"error": "发布签名验证失败：这个版本的校验文件签名不对，"
                          "可能已被篡改。为安全起见拒绝了下载，请联系作者。"},
                status_code=400)
        if src != "direct" and not expect:
            # 走镜像必须拿到校验和，拿不到就不许用（fail closed）
            return JSONResponse(
                {"error": "这个版本没有可用的校验和"
                          "（缺 SHA256SUMS.txt，或里面没列这个文件）。"
                          "用加速节点无法验证文件是否被篡改，请改用直连"},
                status_code=400)
        if src == "direct":
            url = (hit or {}).get("api_url") or ""
            if not url.startswith(f"https://api.github.com/repos/{UPDATE_REPO}/"):
                return JSONResponse({"error": "没有可用的下载地址"}, status_code=400)

        # 回退地址：官方直连（镜像挂了也能下完）
        # 用 hit（上面已经查过的那条），别再引用只在某个分支里才存在的变量 ——
        # 之前这里写的是只在该 if 里定义的 hit2，走镜像时直接 NameError -> HTTP 500
        fb = (hit or {}).get("api_url") or ""
        if not fb.startswith(f"https://api.github.com/repos/{UPDATE_REPO}/"):
            fb = ""
        _UPDATE_DL.update({"busy": True, "name": want, "src": label, "got": 0,
                           "total": int(hit.get("size") or 0), "saved": "",
                           "error": "", "done": False, "verify": "", "speed": 0.0,
                           "cancelled": False, "task": None, "sha": "",
                           "sha_src": ""})
        _UPDATE_DL["task"] = asyncio.create_task(
            _update_fetch_task(want, src, url, expect, fb, _UPDATE_SUMS["state"]))
        return JSONResponse({"ok": True, "src": label, "name": want})

    @app.get("/admin/api/update/ping")
    async def api_update_ping(token: str = "", src: str = "direct"):
        r"""测一条线路的延迟 —— 就为了用户在卡片上看到"0.3s"还是">1s"。

        只取前 64KB（Range），不下整个包。直连要打一次 api.github.com，
        所以结果缓存 2 分钟，免得反复开弹窗把配额烧光。
        """
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        if src not in UPDATE_SRC_MAP:
            src = "direct"
        info = await fetch_latest_release()
        tag = (info or {}).get("tag") or ""
        # 三段 tag（v1.1）会让版本比较算错：_ver_tuple 补零后 "1.1" -> (1,1,0,0)，
        # 比 "1.0.2.1" -> (1,0,2,1) 大，看着像有新版，但语义上根本不是一回事。
        # 靠"发布时永远打四段"这个约定规避 —— 这里加一句警告，真出现时能看见。
        try:
            _segs = [x for x in re.sub(r"^[vV]", "", tag).split(".") if x != ""]
            # 只对同一个 tag 警告一次：弹窗会 ping 三路，每路都调这个函数，
            # 不记标记的话用户每开一次弹窗就刷三条日志。
            if tag and len(_segs) < 4 and _PING_CACHE.get("tag_warned") != tag:
                _PING_CACHE["tag_warned"] = tag
                log("warn", "更新",
                    f"Release tag {tag!r} 不是四段，版本比较可能不准（约定见 README）")
        except Exception as e:
            log("warn", "更新", "api_update_ping 吞掉异常：%s: %s" % (type(e).__name__, e))
        now = time.time()
        if (_PING_CACHE["tag"] == tag and _PING_CACHE["res"]
                and now - _PING_CACHE["ts"] < _PING_TTL
                and src in _PING_CACHE["res"]):
            return JSONResponse(_PING_CACHE["res"][src])
        if not info or not (info.get("assets") or []):
            return JSONResponse({"ok": False, "error": "拿不到 Release 信息"})
        # 用最小的那个附件来测（少下点）
        a = min(info["assets"], key=lambda x: int(x.get("size") or 0))
        info["_want"] = a["name"]

        if src == "auto":
            # 自动线路：把所有节点都测一遍，报最快的那条给前端显示。
            # 请求方式跟下面的直连分支保持一致（cli.get + 64KB Range），
            # 不自己另写一套，避免 API 细节踩坑。
            best = None
            last_err = ""
            for _sid, _lab, _pfx in UPDATE_SOURCES:
                if _sid == "auto":
                    continue
                try:
                    _s2, _l2, _u2 = _update_pick_source(info, _sid)
                except Exception:
                    continue
                if _sid == "direct" or not _u2:
                    _u2 = a.get("api_url") or ""
                if not _u2:
                    continue
                _hh = {"Accept": "application/octet-stream",
                       "Range": "bytes=0-65535",
                       "User-Agent": _ua()}
                _tk2 = _update_token()
                if _tk2:
                    _hh["Authorization"] = "Bearer " + _tk2
                _t0 = time.time()
                try:
                    _r = await get_http().get(_u2, headers=_hh, timeout=15.0,
                                              follow_redirects=True)
                    _ms = int((time.time() - _t0) * 1000)
                    if _r.status_code not in (200, 206):
                        last_err = "HTTP %s" % _r.status_code
                        continue
                    if best is None or _ms < best[0]:
                        best = (_ms, _l2, len(_r.content))
                except Exception as _e:
                    last_err = "%s: %s" % (type(_e).__name__, _e)
                    continue
            if best is None:
                return JSONResponse({"ok": False, "error": "所有线路都不通" + (
                    "（" + last_err + "）" if last_err else "")})
            return JSONResponse({"ok": True, "ms": best[0], "bytes": best[2],
                                 "label": "自动：" + best[1]})

        _s, _label, url = _update_pick_source(info, src)
        if src == "direct" or not url:
            url = a.get("api_url") or ""
        if not url:
            return JSONResponse({"ok": False, "error": "没有可用地址"})
        h = {"Accept": "application/octet-stream",
             "Range": "bytes=0-65535",
             "User-Agent": _ua()}
        _tk = _update_token()
        if _tk:
            h["Authorization"] = "Bearer " + _tk
        t0 = time.time()
        try:
            cli = get_http()
            r = await cli.get(url, headers=h, timeout=15.0, follow_redirects=True)
            ms = int((time.time() - t0) * 1000)
            if r.status_code not in (200, 206):
                out = {"ok": False, "ms": ms, "error": f"HTTP {r.status_code}"}
            else:
                out = {"ok": True, "ms": ms, "bytes": len(r.content)}
        except Exception as e:
            out = {"ok": False, "ms": int((time.time() - t0) * 1000),
                   "error": f"{type(e).__name__}: {e}"}
        if _PING_CACHE["tag"] != tag:
            _PING_CACHE.update({"tag": tag, "res": {}})
        # ts 每次存结果都要刷新。只在换 tag 时写的话，120 秒一过
        # now-ts 就永远 >= TTL，缓存再也命中不了 —— 弹窗每开一次
        # 就把三路测速重新打一遍 GitHub 配额（正是这个缓存要防的事）。
        _PING_CACHE["ts"] = now
        _PING_CACHE["res"][src] = out
        return JSONResponse(out)

    @app.post("/admin/api/update/cancel")
    async def api_update_cancel(token: str = ""):
        """取消正在进行的下载。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        t = _UPDATE_DL.get("task")
        if t is not None and not t.done():
            _UPDATE_DL["cancelled"] = True
            t.cancel()
            log("info", "更新", "用户取消了下载")
            return JSONResponse({"ok": True})
        return JSONResponse({"ok": False, "error": "没有正在进行的下载"})

    @app.get("/admin/api/update/progress")
    async def api_update_progress(token: str = ""):
        """下载进度。前端每 300ms 拉一次，画进度条。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        st = _update_snapshot()
        st["pct"] = (round(st["got"] * 100.0 / st["total"], 2)
                     if st["total"] else 0)
        st["dir"] = UPDATE_DIR
        return JSONResponse(st)

    @app.post("/admin/api/update/reveal")
    async def api_update_reveal(token: str = ""):
        """在资源管理器里定位到刚下好的文件。"""
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        path = _UPDATE_DL.get("saved") or UPDATE_DIR
        try:
            if os.path.exists(path):
                # /select 会打开文件夹并选中该文件。
                # Popen 是阻塞调用, 直接在 async 里执行会卡住事件循环,
                # 丢到线程里跑 (跟 routes_chats / routes_sticker 一个处理)。
                await asyncio.to_thread(
                    subprocess.Popen,
                    ["explorer", "/select,", os.path.normpath(path)])
            else:
                os.makedirs(UPDATE_DIR, exist_ok=True)
                os.startfile(UPDATE_DIR)
            return JSONResponse({"ok": True, "path": path})
        except Exception as e:
            return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)

    @app.post("/admin/api/update/apply")
    async def api_update_apply(token: str = "", name: str = ""):
        r"""应用更新：解压暂存 → 拉起无窗口更新器 → 本进程退出 → 更新器 robocopy 覆盖。

        这套流程照搬开源实现，不是自己发明的：
          tufup    src/tufup/utils/platform_specific.py
                   WIN_ROBOCOPY_OVERWRITE = ('/move', '/w:2')
          PyUpdater pyupdater/client/updates.py
                   self.bat_file = .../update.bat
        两者都是「等主程序退出 → robocopy 覆盖 → 重启」，用 .bat 承载。
        这里保留 robocopy 参数，把承载换成无窗口进程，所以不弹黑框，
        也不用用户手动关程序（主进程自己退出）。
        """
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        want = os.path.basename(str(name or "").strip())
        if not want.lower().endswith(".zip"):
            return JSONResponse({"error": "只接受 .zip 更新包"}, status_code=400)
        zpath = os.path.join(UPDATE_DIR, want)
        if not os.path.isfile(zpath):
            return JSONResponse({"error": "更新包不存在，请先下载"}, status_code=404)

        base = str(globals().get("BASE_DIR") or os.getcwd())
        applier = os.path.join(base, "NekolyraUpdater.exe")
        if not os.path.isfile(applier):
            return JSONResponse({
                "error": "缺少更新器 NekolyraUpdater.exe",
                "hint": "更新包不完整，请重新下载完整版本",
            }, status_code=400)

        try:
            import shutil
            import sys as _sys
            import threading
            import zipfile

            # 暂存目录必须放在安装目录**之外**：更新器拿它当"源"去覆盖安装目录，
            # 源在目标内部就等于搬自己的祖先 —— 出错时连原状都拼不回来。
            import tempfile
            payload = tempfile.mkdtemp(prefix="nekolyra_payload_")

            # 落盘后再核一次 SHA-256（下载时核过；这里防"文件被换掉/写坏"）
            try:
                want_sha = str((_UPDATE_SUMS.get("map") or {}).get(want) or "")
                if want_sha:
                    import hashlib
                    h = hashlib.sha256()
                    with open(zpath, "rb") as _f:
                        for _chunk in iter(lambda: _f.read(1 << 20), b""):
                            h.update(_chunk)
                    got_sha = h.hexdigest()
                    if got_sha.lower() != want_sha.lower():
                        shutil.rmtree(payload, ignore_errors=True)
                        return JSONResponse({
                            "error": "更新包校验失败（SHA-256 不符），已丢弃",
                            "expect": want_sha, "got": got_sha}, status_code=400)
                    log("info", "更新", "应用前 SHA-256 复核通过")
            except Exception as _e:
                log("warn", "更新", "应用前复核跳过：%s: %s" % (type(_e).__name__, _e))

            with zipfile.ZipFile(zpath) as z:
                names = z.namelist()
                tops = {n.split("/")[0] for n in names if n.strip("/")}
                strip = ""
                if len(tops) == 1:
                    only = tops.pop()
                    if all(n.startswith(only + "/") for n in names if n.strip("/")):
                        strip = only + "/"
                n_files = 0
                root_abs = os.path.normpath(payload)
                for item in z.infolist():
                    if item.is_dir():
                        continue
                    rel = item.filename[len(strip):] if strip else item.filename
                    if not rel:
                        continue
                    target = os.path.normpath(os.path.join(payload, rel.replace("/", os.sep)))
                    if not target.startswith(root_abs + os.sep):
                        return JSONResponse({"error": "更新包里有非法路径"}, status_code=400)
                    os.makedirs(os.path.dirname(target) or payload, exist_ok=True)
                    with z.open(item) as src_f, open(target, "wb") as dst_f:
                        shutil.copyfileobj(src_f, dst_f)
                    n_files += 1

            exe_name = os.path.basename(_sys.executable) if getattr(_sys, "frozen", False) else "Nekolyra.exe"
            flags = 0
            if os.name == "nt":
                flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                         | getattr(subprocess, "DETACHED_PROCESS", 0))
            # 更新器必须从临时目录运行：它要替换安装目录里的 NekolyraUpdater.exe，
            # 而自己正在运行的文件是改不动的（实测 robocopy 报 Error 32）。
            # PyUpdater 也是把更新脚本放在 data_dir 而不是安装目录。
            import tempfile
            tmp_applier = os.path.join(tempfile.gettempdir(),
                                       "NekolyraUpdater_%d.exe" % os.getpid())
            try:
                shutil.copyfile(applier, tmp_applier)
                runner = tmp_applier
            except Exception as _e:
                log("warn", "更新", "复制更新器到临时目录失败（就地运行）：%s" % _e)
                runner = applier
            # 交给更新器的关键参数：就绪端口（起来后要靠它验收）、备份保留份数
            subprocess.Popen([runner, "--install", base, "--payload", payload,
                              "--wait-pid", str(os.getpid()), "--exe", exe_name,
                              "--restart", "--ready-port", str(PORT or 8080),
                              "--keep-backups", "1"],
                             cwd=base, close_fds=True, creationflags=flags)
            log("info", "更新", "%s 解压 %d 个文件，更新器已拉起，本进程即将退出" % (want, n_files))

            def _bye():
                time.sleep(1.5)
                # 走真正的收尾：停后台任务 / checkpoint WAL / 落盘配置。
                # 以前直接 os._exit(0) 等于拔电源 —— 每次更新都可能丢最后几条数据。
                try:
                    fn = globals().get("shutdown")
                    if callable(fn):
                        fn()
                except Exception as _e:
                    log("warn", "更新", "关停收尾出错（继续退出）：%s" % _e)
                os._exit(0)

            threading.Thread(target=_bye, daemon=True, name="apply-exit").start()
            return JSONResponse({
                "ok": True, "restarting": True, "files": n_files,
                "hint": "程序即将退出并覆盖，几秒后自动重启（期间机器人短暂离线）",
            })
        except Exception as e:
            log("error", "更新", "应用失败：%s: %s" % (type(e).__name__, e))
            return JSONResponse({"error": "%s: %s" % (type(e).__name__, e)}, status_code=500)

    @app.get("/admin/api/update/download")
    async def api_update_download(token: str = "", name: str = "", src: str = "direct"):
        r"""把更新包从 GitHub 取回来转给浏览器 —— 就地下载，不用跳转。

        为什么不让浏览器直接点 browser_download_url（真实问题）：
            那个地址第一跳是 github.com，实测国内直连不通（TLS 握手过不去）。
            用户点「下载」只会一直转圈，什么也拿不到。
            而 api.github.com 和 release-assets.githubusercontent.com 是通的，
            所以这里由服务端经 assets 接口取回文件，再转给浏览器 ——
            用户实际是从 127.0.0.1 拿，全程不碰那个不通的域名。

        安全：只接受**这次 Release 里真实存在的文件名**，绝不接受任意 URL。
              否则这就是个"让服务器去请求任意地址"的洞（SSRF）。
        """
        if not _auth(token):
            return JSONResponse({"error": "invalid"}, status_code=401)
        want = str(name or "").strip()
        if not want:
            return JSONResponse({"error": "缺少 name"}, status_code=400)
        info = await fetch_latest_release()
        assets = (info or {}).get("assets") or []
        hit = next((a for a in assets if a.get("name") == want), None)
        if hit is None:
            return JSONResponse(
                {"error": f"这次 Release 里没有 {want}"}, status_code=404)
        api_url = str(hit.get("api_url") or "")
        # 地址必须是 api.github.com 下面这个仓库的。
        # 注意：token 在函数开头已经校验过了，这里不用再检一遍。
        if not api_url.startswith(f"https://api.github.com/repos/{UPDATE_REPO}/"):
            return JSONResponse({"error": "这个文件没有可用的下载地址"},
                                status_code=400)
        log("info", "更新", f"开始取 {want}（{hit.get('size', 0)/1024/1024:.1f} MB）")
        t0 = time.time()
        try:
            cli = get_http()
            _h2 = {"Accept": "application/octet-stream",
                   "User-Agent": _ua()}
            _tk2 = _update_token()
            if _tk2:
                _h2["Authorization"] = "Bearer " + _tk2
            r = await cli.get(api_url, headers=_h2,
                              timeout=900.0, follow_redirects=True)
        except Exception as e:
            log("error", "更新", f"取 {want} 失败：{type(e).__name__}: {e}")
            return JSONResponse(
                {"error": f"下载失败：{type(e).__name__}: {e}"}, status_code=502)
        if r.status_code != 200:
            log("error", "更新", f"取 {want} 失败：HTTP {r.status_code}")
            return JSONResponse(
                {"error": f"下载失败：GitHub 返回 HTTP {r.status_code}"},
                status_code=502)
        data = r.content
        if not data:
            return JSONResponse({"error": "下载到 0 字节"}, status_code=502)
        log("success", "更新",
            f"{want} 已转给浏览器（{len(data)/1024/1024:.1f} MB，"
            f"耗时 {time.time()-t0:.0f}s）")
        # 文件名都是 ASCII，不用管 RFC 5987 那套编码
        return Response(
            content=data, media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{want}"',
                     "Content-Length": str(len(data))})


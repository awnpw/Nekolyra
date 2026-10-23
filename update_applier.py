# -*- coding: utf-8 -*-
"""更新应用器 —— 按 tufup / PyUpdater 的做法用 robocopy 覆盖安装目录。

扒到的实现（不是我自己想的）：
    tufup 0.10.0  src/tufup/utils/platform_specific.py
        WIN_ROBOCOPY_OVERWRITE = ('/move', '/w:2')
        WIN_BATCH_TEMPLATE = '@echo off / robocopy "{src_dir}" "{dst_dir}" {opts} / (goto) 2>nul & del "%~f0"'
    PyUpdater 4.0  pyupdater/client/updates.py
        self.bat_file = os.path.join(self.data_dir, "update.bat")

两者的 Windows 覆盖更新都是「等主程序退出 → robocopy 覆盖 → 启动新程序」，用 .bat 承载。
这里照搬 robocopy 参数，只把承载方式从 .bat 换成无窗口进程（--noconsole 打包），
所以不会再弹黑框，也不需要用户手动关程序（主程序自己退出）。

用法（由 bot 退出前拉起）：
    NekolyraUpdater.exe --install <安装根> --payload <暂存目录> --wait-pid <pid> --exe Nekolyra.exe --restart
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

LOG_PATH = ""
NO_WINDOW = 0x08000000

# tufup 的选项（/move /w:2），外加：
#   /e       必须加 —— robocopy 不指定 /e 时**不下钻子目录**，实测只搬了根目录那一个
#            exe，_internal 里的 dll 全部漏掉（payload 也因此没被搬空）
#   /is /it  必须加 —— 默认按「大小 + 时间戳」判断相同就跳过，
#            实测会把同尺寸的新 dll 漏掉，这里强制包含全部文件
#   /r:2     重试次数；/njh /njs /nc /ns /np /ndl /nfl 只影响输出，让日志干净
ROBOCOPY_MOVE = ["/move", "/e", "/w:2", "/r:2", "/is", "/it",
                 "/njh", "/njs", "/nc", "/ns", "/np", "/ndl", "/nfl"]


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        print(line)
    except Exception:
        pass
    if LOG_PATH:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def wait_pid_exit(pid, timeout=180.0):
    """等主程序退出。用 tasklist 轮询，避免 ctypes 句柄类型踩坑。"""
    if not pid:
        return True
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            out = subprocess.run(["tasklist", "/FI", "PID eq %d" % int(pid), "/NH"],
                                 capture_output=True, encoding="utf-8",
                                 errors="replace", timeout=30,
                                 creationflags=NO_WINDOW).stdout or ""
        except Exception:
            return False
        if str(pid) not in out:
            log("主进程 %s 已退出（等 %.1f 秒）" % (pid, time.time() - t0))
            return True
        time.sleep(1.0)
    log("等主进程超时（%.0f 秒）" % timeout)
    return False


def run_robocopy(src, dst):
    """robocopy 源目录 → 目标目录。返回 (退出码, 是否成功)。"""
    args = ["robocopy", src, dst] + ROBOCOPY_MOVE
    log("robocopy %s -> %s %s" % (src, dst, " ".join(ROBOCOPY_MOVE)))
    try:
        r = subprocess.run(args, capture_output=True, encoding="utf-8",
                           errors="replace", timeout=900, creationflags=NO_WINDOW)
    except Exception as e:
        log("robocopy 没跑起来：%s: %s" % (type(e).__name__, e))
        return -1, False
    code = r.returncode
    # robocopy 的退出码：0-7 表示成功（含义不同），>=8 才是失败
    ok = 0 <= code < 8
    log("robocopy 退出码 %s（%s）" % (code, "成功" if ok else "失败"))
    if not ok:
        tail = ((r.stdout or "") + (r.stderr or "")).strip().split("\n")[-6:]
        for line in tail:
            log("  " + line.strip()[:120])
    return code, ok


def fallback_copy(src, dst, skip_names=()):
    """robocopy 不可用时的兜底：逐文件复制 + 删除源文件。"""
    ok = fail = 0
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target_root = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target_root, exist_ok=True)
        for name in files:
            if name in skip_names:
                log("  跳过更新器自身 %s（正在运行，下次用临时副本方式替换）" % name)
                continue
            s = os.path.join(root, name)
            d = os.path.join(target_root, name)
            try:
                shutil.copy2(s, d)
                os.remove(s)
                ok += 1
            except Exception:
                fail += 1
    log("兜底复制：成功 %d，失败 %d" % (ok, fail))
    return fail == 0


def main():
    global LOG_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", required=True)
    ap.add_argument("--payload", required=True)
    ap.add_argument("--wait-pid", type=int, default=0)
    ap.add_argument("--exe", default="Nekolyra.exe")
    ap.add_argument("--restart", action="store_true")
    a = ap.parse_args()

    install = os.path.abspath(a.install)
    payload = os.path.abspath(a.payload)
    LOG_PATH = os.path.join(install, "update.log")
    log("=" * 52)
    log("开始更新：%s -> %s" % (payload, install))

    if not os.path.isdir(payload):
        log("暂存目录不存在，退出")
        return 2

    if not wait_pid_exit(a.wait_pid):
        # 主进程没退出就覆盖 = 往正在运行的程序上盖文件：exe/dll 被占用，
        # robocopy 只会盖成功一部分（/move 还会把没搬成功的留在暂存区），
        # 安装目录变成一半新一半旧 —— 比这次不更新糟得多。
        # 上层（routes_update.api_update_apply）已经安排主进程自己退出，
        # 走到这里说明它卡住了，宁可不更新。
        log("主进程仍在运行，放弃本次更新（安装目录未改动）")
        return 4
    time.sleep(2)

    # 若更新器本身就在安装目录里运行，它替换不了自己 —— 这是 Windows 的限制，
    # 不是错误。真正「全新」的更新器下一轮会从 %TEMP% 运行，那时就能换掉。
    self_name = os.path.basename(os.path.abspath(sys.argv[0]))
    me_in_install = os.path.dirname(os.path.abspath(sys.argv[0])).lower() == install.lower()
    skip = {self_name} if me_in_install else set()

    code, ok = run_robocopy(payload, install)
    if not ok:
        log("robocopy 报错，改用兜底复制（跳过更新器自身）")
        ok = fallback_copy(payload, install, skip_names=skip)

    exe = os.path.join(install, a.exe)
    if not ok:
        log("更新未完成，程序保持原状")
        if a.restart and os.path.isfile(exe):
            log("启动原版本 %s" % exe)
            subprocess.Popen([exe], cwd=install, close_fds=True)
        return 3

    log("更新完成")
    try:
        if os.path.isdir(payload) and not os.listdir(payload):
            os.rmdir(payload)
    except Exception:
        pass

    # 清掉堆在 data/updates 里的旧更新包：每次更新都会留一个几十 MB 的 zip，
    # 不清理的话半年就是几个 G（实测用户机器上已经堆了 200+ MB）
    try:
        upd_dir = os.path.join(install, "data", "updates")
        keep_ms = 3 * 24 * 3600
        now = time.time()
        freed = 0
        if os.path.isdir(upd_dir):
            for name in os.listdir(upd_dir):
                if not name.lower().endswith(".zip"):
                    continue
                p = os.path.join(upd_dir, name)
                try:
                    if now - os.path.getmtime(p) > keep_ms:
                        freed += os.path.getsize(p)
                        os.remove(p)
                except OSError:
                    pass
        if freed:
            log("清理旧更新包，释放 %.1f MB" % (freed / 1048576.0))
    except Exception as e:
        log("清理旧更新包失败：%s" % e)

    if a.restart:
        log("启动 %s" % exe)
        time.sleep(1)
        subprocess.Popen([exe], cwd=install, close_fds=True)

    # 自己可能是从 %TEMP% 复制过来的副本，删掉它（删除会延迟到进程退出）
    try:
        me = os.path.abspath(sys.argv[0])
        if os.path.dirname(me).lower() != install.lower() and os.path.isfile(me):
            os.remove(me)
            log("已删除临时副本 %s" % me)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

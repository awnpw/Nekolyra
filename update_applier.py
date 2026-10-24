# -*- coding: utf-8 -*-
"""更新应用器（也兼作 NekolyraUpdater.exe 的入口）。

**为什么不直接在安装目录里逐文件覆盖**（上一版的写法，三个真实风险）：

  1. Windows 下正在运行的 exe/dll 被锁，先关主进程也可能被子进程、
     杀毒、资源管理器、搜索索引器临时占着；
  2. 逐文件 copy2 是几百次写操作，中途断电/崩溃就留下半新半旧的目录；
  3. 更新器自己若是崩在中间，回滚逻辑根本没机会执行。

所以改成「暂存 + 原子换名 + 日志自愈」：

    stage   把 payload 复制到 install/_stage_<ts>/（全新的目录，不碰活的文件）
            —— 这一步崩了，安装目录一个字节都没动，只留个垃圾目录
    verify  核对暂存区的文件数
    swap    对每个顶层条目：活的重命名成 .old_<ts>，暂存的换成正式名
            —— 每次 rename 都是原子的，实测被占用时会明确失败（WinError 5/32），
               不会出现"改一半"；总共只有几个条目，暴露窗口从"几百次写"缩到"几次改名"
    health  拉起新 exe，等「端口就绪 + 进程存活」
    成功     删 .old_*、删暂存、清旧 zip
    失败     反向 rename 还原

**journal**：每次换阶段前把状态写进 data/updates/update_journal.json。
更新器自己崩了也没关系 —— 下次启动（程序侧或更新器侧）读它就知道该还原什么。

用法：
    NekolyraUpdater.exe --install <根> --payload <暂存> --wait-pid <pid>
                        --exe Nekolyra.exe --restart --ready-port 8080
    NekolyraUpdater.exe --install <根> --recover        # 只做自愈，不更新
"""
import argparse
import json
import os
import shutil
import socket
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
DETACHED = 0x00000008
CREATE_NEW_GROUP = 0x00000200
STILL_ACTIVE = 259
OLD_PREFIX = ".old_"
STAGE_PREFIX = "_stage_"
JOURNAL_NAME = "update_journal.json"


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


def set_log(install):
    global LOG_PATH
    try:
        d = os.path.join(install, "data", "updates")
        os.makedirs(d, exist_ok=True)
        LOG_PATH = os.path.join(d, "update.log")
    except Exception:
        LOG_PATH = os.path.join(os.environ.get("TEMP", "."), "nekolyra_update.log")


# ---------------- 进程 ----------------
def pid_alive(pid):
    """不用 tasklist：它要解析文本，过滤失效返回全表时会把"还在跑"判成"已退出"。"""
    if not pid:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    except Exception:
        return False


def wait_pid_exit(pid, timeout=180.0):
    if not pid:
        return True
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not pid_alive(pid):
            log("主进程 %s 已退出（等了 %.1f 秒）" % (pid, time.time() - t0))
            return True
        time.sleep(0.5)
    log("等主进程超时（%.0f 秒），它还在运行" % timeout)
    return False


# ---------------- 版本 / 容量 ----------------
def read_version(root):
    try:
        with open(os.path.join(root, "VERSION"), "r", encoding="utf-8") as f:
            txt = f.read().strip()
        parts = [int(x) for x in txt.split(".")[:4]]
        while len(parts) < 4:
            parts.append(0)
        return tuple(parts), txt
    except Exception:
        return None, ""


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


# ---------------- journal ----------------
def journal_path(install):
    return os.path.join(install, "data", "updates", JOURNAL_NAME)


def journal_write(install, data):
    p = journal_path(install)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except Exception as e:
        log("写 journal 失败：%s: %s" % (type(e).__name__, e))


def journal_read(install):
    try:
        with open(journal_path(install), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def journal_clear(install):
    try:
        os.remove(journal_path(install))
    except Exception:
        pass


# ---------------- 自愈 ----------------
def recover(install, exe="Nekolyra.exe"):
    """按 journal 把没做完的更新收拾干净。返回一句人类可读的结论。"""
    j = journal_read(install)
    if not j:
        return "no journal"
    phase = str(j.get("phase") or "")
    stamp = str(j.get("stamp") or "")
    items = j.get("items") or []
    log("发现未完成的更新（阶段 %s，时间戳 %s）" % (phase, stamp))

    if phase in ("stage", "preflight"):
        stage = j.get("stage") or ""
        if stage and os.path.isdir(stage):
            force_remove(stage)
            log("已清理未完成的暂存目录")
        journal_clear(install)
        return "discarded stage (安装目录未改动)"

    if phase in ("swap", "verify", "rollback"):
        kill_processes_under(install)          # 残留进程会锁着 exe/dll，不杀掉还原必失败
        restored = 0
        for it in reversed(items):
            live = it.get("live") or ""
            old = it.get("old") or ""
            if not live or not old:
                continue
            if os.path.exists(old):
                force_remove(live)
                for _ in range(20):
                    try:
                        os.rename(old, live)
                        restored += 1
                        break
                    except Exception:
                        time.sleep(0.5)
                else:
                    log("还原失败：%s" % live)
        stage = j.get("stage") or ""
        if stage and os.path.isdir(stage):
            force_remove(stage)
        journal_clear(install)
        log("自愈完成，还原 %d 项" % restored)
        return "rolled back %d items" % restored

    journal_clear(install)
    return "journal phase %s ignored" % phase


# ---------------- 工具 ----------------
def kill_processes_under(install):
    """杀掉可执行文件路径位于安装目录下的进程。

    为什么必须做：新版本刚被拉起来就验收失败时，那个进程还活着并占着 exe/dll，
    改名还原会失败；用户说的"子进程、后台线程残留"就是这个。
    只按**可执行文件路径**匹配，绝不用镜像名 —— 同名的程序可能不止一个。
    """
    if os.name != "nt":
        return 0
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        TH32CS_SNAPPROCESS = 0x2
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        PROCESS_TERMINATE = 0x0001

        class PE32(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_char * 260)]

        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == -1:
            return 0
        entry = PE32()
        entry.dwSize = ctypes.sizeof(PE32)
        me = os.getpid()
        root = os.path.abspath(install).lower()
        killed = 0
        try:
            ok = k32.Process32First(snap, ctypes.byref(entry))
            while ok:
                pid = int(entry.th32ProcessID)
                if pid and pid != me:
                    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                    if h:
                        try:
                            buf = ctypes.create_unicode_buffer(1024)
                            size = wintypes.DWORD(1024)
                            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                                path = buf.value.lower()
                                if path.startswith(root):
                                    hp = k32.OpenProcess(PROCESS_TERMINATE, False, pid)
                                    if hp:
                                        try:
                                            k32.TerminateProcess(hp, 1)
                                            killed += 1
                                        finally:
                                            k32.CloseHandle(hp)
                        finally:
                            k32.CloseHandle(h)
                ok = k32.Process32Next(snap, ctypes.byref(entry))
        finally:
            k32.CloseHandle(snap)
        if killed:
            log("已终止 %d 个占用安装目录的进程" % killed)
            time.sleep(1.0)
        return killed
    except Exception as e:
        log("枚举进程失败：%s: %s" % (type(e).__name__, e))
        return 0


def force_remove(p, tries=12, delay=0.5):
    """删文件/目录，带重试。进程刚退出时句柄不一定立刻释放。"""
    for _ in range(tries):
        if not os.path.exists(p):
            return True
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
        except Exception:
            pass
        if not os.path.exists(p):
            return True
        time.sleep(delay)
    return not os.path.exists(p)


def rename_retry(src, dst, tries=12, delay=0.5):
    last = None
    for _ in range(tries):
        try:
            os.rename(src, dst)
            return True, ""
        except Exception as e:
            last = e
            time.sleep(delay)
    return False, "%s: %s" % (type(last).__name__, last)


def copy_tree(src, dst):
    ok = fail = 0
    first_err = ""
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target_root = dst if rel == "." else os.path.join(dst, rel)
        try:
            os.makedirs(target_root, exist_ok=True)
        except Exception as e:
            fail += len(files)
            first_err = first_err or ("建目录 %s: %s" % (target_root, e))
            continue
        for name in files:
            try:
                shutil.copy2(os.path.join(root, name), os.path.join(target_root, name))
                ok += 1
            except Exception as e:
                fail += 1
                if not first_err:
                    first_err = "%s: %s" % (name, e)
    log("暂存复制：成功 %d，失败 %d%s" % (ok, fail, ("；首个错误 " + first_err) if first_err else ""))
    return fail == 0, fail, first_err


# ---------------- 预检 ----------------
def preflight(install, payload, exe, allow_downgrade):
    if not os.path.isdir(payload):
        return False, "暂存目录不存在：%s" % payload
    if not os.path.isfile(os.path.join(payload, exe)):
        return False, "暂存目录里没有 %s，这不是完整安装包" % exe
    if not os.path.isdir(os.path.join(payload, "_internal")):
        return False, "暂存目录里没有 _internal/，更新包里缺运行库"
    n_files = sum(len(fs) for _r, _d, fs in os.walk(payload))
    if n_files < 100:
        return False, "暂存目录只有 %d 个文件，明显不完整（正常安装包 800+）" % n_files
    new_v, new_txt = read_version(payload)
    old_v, old_txt = read_version(install)
    if new_v and old_v and new_v < old_v and not allow_downgrade:
        return False, "更新包版本 %s 比当前 %s 旧（要降级加 --allow-downgrade）" % (new_txt, old_txt)
    need = dir_size(payload)
    try:
        free = shutil.disk_usage(install).free
    except Exception:
        free = 0
    if free and free < need * 2:
        return False, "磁盘余量不足：暂存 + 切换需要约 %.0f MB，只剩 %.0f MB" % (need * 2 / 1048576, free / 1048576)
    log("预检通过：%d 个文件 / %.1f MB，版本 %s -> %s"
        % (n_files, need / 1048576, old_txt or "?", new_txt or "?"))
    return True, ""


# ---------------- 拉起 / 验收 ----------------
def launch(install, exe):
    path = os.path.join(install, exe)
    if not os.path.isfile(path):
        return 0
    flags = DETACHED | CREATE_NEW_GROUP if os.name == "nt" else 0
    try:
        p = subprocess.Popen([path], cwd=install, close_fds=True, creationflags=flags)
        log("已拉起：%s（pid %d）" % (exe, p.pid))
        return p.pid
    except Exception as e:
        log("拉起失败：%s: %s" % (type(e).__name__, e))
        return 0


def port_ready(port, timeout=1.0):
    if not port:
        return False
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", int(port)))
        return True
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def health_check(pid, port, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pid and not pid_alive(pid):
            return False, "新进程已退出（启动即崩）"
        if port_ready(port):
            return True, "端口 %s 就绪（%.1f 秒）" % (port, time.time() - t0)
        time.sleep(1.0)
    return False, "等 %.0f 秒仍未就绪" % timeout


# ---------------- 清理 ----------------
def cleanup(install, stage, keep_backups):
    force_remove(stage)
    upd_dir = os.path.join(install, "data", "updates")
    if os.path.isdir(upd_dir):
        for name in os.listdir(upd_dir):
            if name.lower().endswith(".zip"):
                force_remove(os.path.join(upd_dir, name))
    try:
        groups = {}
        for name in os.listdir(install):
            if OLD_PREFIX in name:
                groups.setdefault(name.split(OLD_PREFIX)[-1], []).append(name)
        for st in sorted(groups.keys(), reverse=True)[keep_backups:]:
            for name in groups[st]:
                force_remove(os.path.join(install, name))
                log("清理旧备份 %s" % name)
    except Exception as e:
        log("清理备份出错：%s" % e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", required=True)
    ap.add_argument("--payload", default="")
    ap.add_argument("--wait-pid", type=int, default=0)
    ap.add_argument("--exe", default="Nekolyra.exe")
    ap.add_argument("--restart", action="store_true")
    ap.add_argument("--ready-port", type=int, default=8080)
    ap.add_argument("--ready-timeout", type=float, default=90.0)
    ap.add_argument("--keep-backups", type=int, default=1)
    ap.add_argument("--allow-downgrade", action="store_true")
    ap.add_argument("--recover", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    install = os.path.abspath(a.install)
    set_log(install)

    if a.recover:
        log("=" * 56)
        log("自愈模式：%s" % install)
        result = recover(install, a.exe)      # 只调一次：它会自己判断该不该动手
        log("自愈结果：%s" % result)
        return 0 if result else 1

    payload = os.path.abspath(a.payload) if a.payload else ""
    log("=" * 56)
    log("更新开始：%s -> %s" % (payload, install))

    # 先收拾上一次没做完的
    if journal_read(install):
        recover(install, a.exe)

    ok, why = preflight(install, payload, a.exe, a.allow_downgrade)
    if not ok:
        log("预检未通过，安装目录未改动：" + why)
        return 2

    if not wait_pid_exit(a.wait_pid):
        log("主进程仍在运行，放弃本次更新（安装目录未改动）")
        return 4
    time.sleep(1.5)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    stage = os.path.join(install, STAGE_PREFIX + stamp)
    items = [n for n in sorted(os.listdir(payload)) if os.path.exists(os.path.join(payload, n))]
    plan = [{"name": n,
             "live": os.path.join(install, n),
             "old": os.path.join(install, n + OLD_PREFIX + stamp),
             "stage": os.path.join(stage, n)} for n in items]

    # --- 1) 暂存 ---
    journal_write(install, {"phase": "stage", "stamp": stamp, "stage": stage, "items": plan})
    force_remove(stage)
    try:
        os.makedirs(stage, exist_ok=True)
    except Exception as e:
        log("建暂存目录失败：%s" % e)
        journal_clear(install)
        return 3
    ok, _n, err = copy_tree(payload, stage)
    if not ok:
        log("暂存失败，安装目录未改动：" + err)
        force_remove(stage)
        journal_clear(install)
        return 6

    staged_files = sum(len(fs) for _r, _d, fs in os.walk(stage))
    payload_files = sum(len(fs) for _r, _d, fs in os.walk(payload))
    if staged_files < 20 or not os.path.isfile(os.path.join(stage, a.exe)):
        log("暂存区不完整（%d 个文件），放弃" % staged_files)
        force_remove(stage)
        journal_clear(install)
        return 6
    if staged_files != payload_files:
        log("暂存复制后对账失败：payload %d 个文件，暂存区 %d 个，放弃本次更新"
            % (payload_files, staged_files))
        force_remove(stage)
        journal_clear(install)
        return 6

    if a.dry_run:
        log("--dry-run：暂存 %d 个文件成功；现在验证「换名」是否可行（不真正切换）" % staged_files)
        blocked = 0
        for it in plan:
            if os.path.exists(it["live"]):
                try:
                    os.rename(it["live"], it["live"] + ".probe")
                    os.rename(it["live"] + ".probe", it["live"])
                except Exception as e:
                    blocked += 1
                    log("  占用中，无法换名：%s（%s）" % (it["name"], type(e).__name__))
        force_remove(stage)
        journal_clear(install)
        log("干跑结论：%d 个条目被占用" % blocked)
        return 0 if blocked == 0 else 5

    # --- 2) 换名（原子）---
    kill_processes_under(install)      # 任何还占着安装目录的残留进程，先清掉
    # 换名前记下每个条目应有的文件数：rename 是原子的，但"暂存区本身是不是完整"
    # 只有事后对账才知道。少了就整体回滚，绝不让半截目录上线。
    expect = {}
    for it in plan:
        src = os.path.join(payload, it["name"])
        expect[it["name"]] = (sum(len(fs) for _r, _d, fs in os.walk(src))
                              if os.path.isdir(src) else 1)
    log("预期文件数：" + "，".join("%s=%d" % (k, v) for k, v in expect.items()))
    journal_write(install, {"phase": "swap", "stamp": stamp, "stage": stage, "items": plan})
    swapped = []
    for it in plan:
        if os.path.exists(it["live"]):
            ok_r, err = rename_retry(it["live"], it["old"])
            if not ok_r:
                log("换名失败（%s 被占用）：%s" % (it["name"], err))
                _undo(install, swapped)
                force_remove(stage)
                return 5
            swapped.append(it)
        ok_r, err = rename_retry(it["stage"], it["live"])
        if not ok_r:
            log("就位失败（%s）：%s" % (it["name"], err))
            _undo(install, swapped)
            force_remove(stage)
            return 5
    # 对账：每个条目实际到位的文件数必须与预期一致
    bad = []
    for it in plan:
        live = it["live"]
        got = (sum(len(fs) for _r, _d, fs in os.walk(live))
               if os.path.isdir(live) else (1 if os.path.isfile(live) else 0))
        want = expect.get(it["name"], 0)
        if got != want:
            bad.append("%s：预期 %d 个文件，实际 %d 个" % (it["name"], want, got))
    if bad:
        log("换名后对账失败：" + "；".join(bad))
        log("正在整体回滚……")
        _undo(install, list(plan))
        force_remove(stage)
        journal_clear(install)
        return 7
    log("换名完成：%d 个条目已切换到新版（文件数对账通过）" % len(plan))

    # --- 3) 验收 ---
    journal_write(install, {"phase": "verify", "stamp": stamp, "stage": stage,
                            "items": [{"name": it["name"], "live": it["live"], "old": it["old"]} for it in plan]})
    pid = launch(install, a.exe) if a.restart else 0
    if a.restart:
        good, note = health_check(pid, a.ready_port, a.ready_timeout)
        log("验收：%s（%s）" % ("通过" if good else "未通过", note))
        if not good:
            if pid and pid_alive(pid):
                for _ in range(10):
                    subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                                   capture_output=True, creationflags=NO_WINDOW)
                    if not pid_alive(pid):
                        break
                    time.sleep(0.5)
            rb = recover(install, a.exe)
            log("回滚结果：%s" % rb)
            if rb.startswith("rolled back"):
                if a.restart:
                    launch(install, a.exe)
                return 8
            log("回滚不完整，已停止；手工恢复办法：把 install 下的 *%s<时间戳> 改回原名" % OLD_PREFIX)
            return 10

    log("更新成功")
    journal_write(install, {"phase": "done", "stamp": stamp, "stage": stage, "items": []})
    cleanup(install, stage, max(0, a.keep_backups))
    journal_clear(install)
    return 0


def _undo(install, swapped):
    """把已经换过的条目改名还原（换名阶段失败时用）。"""
    for it in reversed(swapped):
        if os.path.exists(it["old"]):
            force_remove(it["live"])
            ok, err = rename_retry(it["old"], it["live"])
            log("还原 %s：%s" % (it["name"], "OK" if ok else err))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        log("更新器异常退出：%s: %s" % (type(e).__name__, e))
        sys.exit(9)

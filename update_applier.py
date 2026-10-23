# -*- coding: utf-8 -*-
"""更新应用器（也兼作 NekolyraUpdater.exe 的入口）。

设计原则：**任何一步失败都不能让安装目录卡在半新半旧的状态。**

    preflight  预检：payload 完整性 / 版本方向 / 磁盘余量 / 可选 SHA-256
    backup     备份：exe 与 _internal 改名（同盘 rename，快且可逆）
    apply      覆盖：逐文件 copy2，不用 /move —— payload 留着，失败了还能重试
    verify     验收：拉起新 exe，等端口就绪 + 进程存活
    成功       清理 payload / 旧 zip / 多余备份
    失败       回滚：杀掉新进程、删除半成品、改名还原、拉起旧版

被替换/被回滚的只有程序本体（exe + _internal），**绝不碰 data/**。

用法（由主程序退出前拉起）：
    NekolyraUpdater.exe --install <安装根> --payload <暂存目录> --wait-pid <pid>
                        --exe Nekolyra.exe --restart --ready-port 8080
"""
import argparse
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


# ---------------- 进程存活判断 ----------------
# 为什么不用 tasklist：它要解析文本（/FI 失效时返回全表），
# 子串匹配 "PID 在不在输出里" 会把"还在运行"误判成"已退出"，
# 然后往运行中的程序上盖文件 —— 最坏的那种失败。
def pid_alive(pid):
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
        h = k32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
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


# ---------------- 版本与容量 ----------------
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


# ---------------- 预检 ----------------
def preflight(install, payload, exe, allow_downgrade):
    """返回 (ok, 原因)。这一关不过就一个字节都不动。"""
    if not os.path.isdir(payload):
        return False, "暂存目录不存在：%s" % payload
    if not os.path.isfile(os.path.join(payload, exe)):
        return False, "暂存目录里没有 %s，这不是完整安装包" % exe
    inner = os.path.join(payload, "_internal")
    if not os.path.isdir(inner):
        return False, "暂存目录里没有 _internal/，更新包里缺运行库"

    n_files = sum(len(fs) for _r, _d, fs in os.walk(payload))
    if n_files < 20:
        return False, "暂存目录只有 %d 个文件，明显不完整" % n_files

    new_v, new_txt = read_version(payload)
    old_v, old_txt = read_version(install)
    if new_v and old_v and new_v < old_v and not allow_downgrade:
        return False, "更新包版本 %s 比当前 %s 旧（要降级加 --allow-downgrade）" % (new_txt, old_txt)

    need = dir_size(payload)
    try:
        free = shutil.disk_usage(install).free
    except Exception:
        free = 0
    if free and free < need * 1.5:
        return False, "磁盘余量不足：需要约 %.0f MB，只剩 %.0f MB" % (need / 1048576, free / 1048576)

    log("预检通过：%d 个文件 / %.1f MB，版本 %s -> %s"
        % (n_files, need / 1048576, old_txt or "?", new_txt or "?"))
    return True, ""


# ---------------- 备份 / 覆盖 / 回滚 ----------------
def make_backup(install, payload, exe, stamp, made):
    """把「payload 顶层会覆盖到的每个条目」改名备份。

    为什么不是只备份 exe + _internal：payload 里还有 VERSION / requirements.txt 这些
    根目录文件，它们也会被覆盖。只备份程序本体的话，回滚后就成了
    「新 VERSION + 旧程序」—— 还是半新半旧，只是不容易看出来。
    改名失败（文件被占用）说明主程序没退干净，此时必须停下，一个字节都别动。
    """
    names = set()
    try:
        names.update(os.listdir(payload))
    except Exception:
        pass
    names.add(exe)
    names.add("_internal")
    pairs = []
    for name in sorted(names):
        src = os.path.join(install, name)
        if not os.path.exists(src):
            continue
        dst = src + ".bak_" + stamp
        try:
            os.rename(src, dst)
            pairs.append((dst, src))
        except Exception as e:
            log("备份 %s 失败（可能被占用）：%s: %s" % (name, type(e).__name__, e))
            for d, s in reversed(pairs):
                try:
                    os.rename(d, s)
                except Exception:
                    pass
            return False
    made.extend(pairs)
    log("已备份 %d 项（后缀 %s）：%s" % (len(pairs), stamp, ", ".join(os.path.basename(s) for _d, s in pairs)))
    return True


def copy_tree(src, dst):
    """逐文件复制。返回 (ok, 失败数, 首条错误)。不删源目录。"""
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
            s = os.path.join(root, name)
            d = os.path.join(target_root, name)
            try:
                shutil.copy2(s, d)
                ok += 1
            except Exception as e:
                fail += 1
                if not first_err:
                    first_err = "%s: %s" % (name, e)
    log("复制完成：成功 %d，失败 %d%s" % (ok, fail, ("；首个错误 " + first_err) if first_err else ""))
    return fail == 0, fail, first_err


def remove_path(p):
    try:
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        elif os.path.isfile(p):
            os.remove(p)
    except Exception:
        pass


def force_remove(p, tries=12, delay=0.5):
    """删文件/目录，带重试。

    Windows 上进程刚被杀掉时句柄不一定立刻释放，直接 os.remove 会报
    PermissionError，紧接着 rename 就会撞 FileExistsError —— 回滚会失败。"""
    for i in range(tries):
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


def rollback(install, exe, made, started_pid):
    """回滚：杀掉新进程 → 等它真的退出 → 带重试删掉半成品 → 逐个还原。"""
    log("开始回滚")
    if started_pid:
        for _ in range(10):
            if not pid_alive(started_pid):
                break
            try:
                subprocess.run(["taskkill", "/PID", str(started_pid), "/F", "/T"],
                               capture_output=True, creationflags=NO_WINDOW, timeout=30)
            except Exception:
                pass
            time.sleep(0.5)
        if pid_alive(started_pid):
            log("新进程 %s 杀不掉，回滚可能失败" % started_pid)
        else:
            log("新进程已结束（pid %s）" % started_pid)

    restored = failed = 0
    for dst, src in reversed(made):
        if not force_remove(src):
            failed += 1
            log("删除半成品失败：%s（文件被占用）" % src)
            continue
        ok = False
        for _ in range(10):
            try:
                os.rename(dst, src)
                ok = True
                break
            except Exception as e:
                last = e
                time.sleep(0.5)
        if ok:
            restored += 1
        else:
            failed += 1
            log("还原 %s 失败：%s" % (src, last))
    log("回滚完成：还原 %d 项，失败 %d 项" % (restored, failed))
    return failed == 0


# ---------------- 拉起与验收 ----------------
def launch(install, exe):
    path = os.path.join(install, exe)
    if not os.path.isfile(path):
        return 0
    flags = 0
    if os.name == "nt":
        flags = DETACHED | CREATE_NEW_GROUP
    try:
        p = subprocess.Popen([path], cwd=install, close_fds=True, creationflags=flags)
        log("已拉起新版：%s（pid %d）" % (exe, p.pid))
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
    """等「端口就绪 + 进程还活着」。两者都要，只看一个都可能误判。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pid and not pid_alive(pid):
            return False, "新进程已退出（启动即崩）"
        if port_ready(port):
            return True, "端口 %s 就绪（%.1f 秒）" % (port, time.time() - t0)
        time.sleep(1.0)
    return False, "等 %.0f 秒仍未就绪" % timeout


# ---------------- 清理 ----------------
def cleanup(payload, install, keep_backups):
    remove_path(payload)
    # 旧 zip
    upd_dir = os.path.join(install, "data", "updates")
    if os.path.isdir(upd_dir):
        for name in os.listdir(upd_dir):
            if name.lower().endswith(".zip"):
                remove_path(os.path.join(upd_dir, name))
    # 过多备份：只留最近 keep_backups 组
    try:
        groups = {}
        for name in os.listdir(install):
            if ".bak_" in name:
                stamp = name.split(".bak_")[-1]
                groups.setdefault(stamp, []).append(name)
        stamps = sorted(groups.keys(), reverse=True)
        for st in stamps[keep_backups:]:
            for name in groups[st]:
                remove_path(os.path.join(install, name))
            log("清理旧备份 %s" % st)
    except Exception as e:
        log("清理备份出错：%s" % e)


def main():
    global LOG_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", required=True)
    ap.add_argument("--payload", required=True)
    ap.add_argument("--wait-pid", type=int, default=0)
    ap.add_argument("--exe", default="Nekolyra.exe")
    ap.add_argument("--restart", action="store_true")
    ap.add_argument("--ready-port", type=int, default=8080)
    ap.add_argument("--ready-timeout", type=float, default=90.0)
    ap.add_argument("--keep-backups", type=int, default=1)
    ap.add_argument("--allow-downgrade", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    install = os.path.abspath(a.install)
    payload = os.path.abspath(a.payload)
    upd_dir = os.path.join(install, "data", "updates")
    try:
        os.makedirs(upd_dir, exist_ok=True)
        LOG_PATH = os.path.join(upd_dir, "update.log")
    except Exception:
        LOG_PATH = os.path.join(os.environ.get("TEMP", "."), "nekolyra_update.log")

    log("=" * 56)
    log("更新开始：%s -> %s" % (payload, install))

    ok, why = preflight(install, payload, a.exe, a.allow_downgrade)
    if not ok:
        log("预检未通过，安装目录未改动：" + why)
        return 2

    if not wait_pid_exit(a.wait_pid):
        log("主进程仍在运行，放弃本次更新（安装目录未改动）")
        return 4
    time.sleep(1.5)      # 给句柄释放留一点余量

    stamp = time.strftime("%Y%m%d_%H%M%S")
    backups = []
    if not make_backup(install, payload, a.exe, stamp, backups):
        log("备份失败，放弃本次更新（安装目录未改动）")
        return 5

    copied, _fail, _err = copy_tree(payload, install)
    if not copied:
        log("复制阶段有失败，回滚")
        if rollback(install, a.exe, backups, 0) and a.restart:
            launch(install, a.exe)
        return 6

    if a.dry_run:
        log("--dry-run：复制与备份都成功，现在回滚以验证可逆性")
        ok_rb = rollback(install, a.exe, backups, 0)
        log("回滚%s" % ("成功（安装目录已复原）" if ok_rb else "失败！需要人工处理"))
        return 0 if ok_rb else 7

    pid = launch(install, a.exe) if a.restart else 0
    if a.restart:
        good, note = health_check(pid, a.ready_port, a.ready_timeout)
        log("验收：%s（%s）" % ("通过" if good else "未通过", note))
        if not good:
            rb_ok = rollback(install, a.exe, backups, pid)
            if not rb_ok:
                # 回滚不完整时**不要**启动任何东西：安装目录现在是半新半旧，
                # 拉起来只会让人以为更新成功了。留日志让用户按提示手工处理。
                log("回滚不完整，已停止；请把 *%s 改回原名后重启" % ".bak_" )
                return 10
            log("已回滚到上一版")
            if a.restart:
                launch(install, a.exe)
            return 8

    log("更新成功")
    cleanup(payload, install, max(0, a.keep_backups))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        log("更新器异常退出：%s: %s" % (type(e).__name__, e))
        sys.exit(9)

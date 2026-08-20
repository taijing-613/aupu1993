# 淘宝巡检网站 · 常驻启动器（纯 Python，无 PowerShell 依赖）
# 作用：确保 app.py 始终在 8000 端口运行；退出/崩溃自动重启；由 Windows 计划任务开机/登录时拉起。
# 日志：与本文件同目录的 server.log

import subprocess
import socket
import time
import os
import sys

PY = r"C:\Users\J\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
# 用 pythonw 拉起 app.py：无控制台窗口（避免反复弹窗）
PYW = r"C:\Users\J\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
APP = r"C:\Users\J\WorkBuddy\2026-08-17-08-58-49\app\app.py"
BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "server.log")
PORT = 8000
LOCK = os.path.join(BASE, ".guard.lock")


def port_open(p):
    try:
        s = socket.create_connection(("127.0.0.1", p), timeout=2)
        s.close()
        return True
    except Exception:
        return False


def log(m):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (ts, m))
    except Exception:
        pass


if __name__ == "__main__":
    # 单实例保护：若锁文件指向的进程仍存活，则退出，避免重复拉起
    if os.path.exists(LOCK):
        try:
            with open(LOCK) as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)  # Windows 上：进程存在则不抛异常
                log("[GUARD] 另一实例已在运行 (pid %s)，本实例退出" % pid)
                sys.exit(0)
            except Exception:
                pass  # 锁文件过期，覆盖之
        except Exception:
            pass
    with open(LOCK, "w") as f:
        f.write(str(os.getpid()))

    log("[GUARD] 启动器启动（python=%s）" % PY)
    try:
        while True:
            if not os.path.exists(PY):
                log("[GUARD] 找不到 python，5 秒后重试")
                time.sleep(5)
                continue
            if not os.path.exists(APP):
                log("[GUARD] 找不到 app.py，5 秒后重试")
                time.sleep(5)
                continue
            if port_open(PORT):
                time.sleep(10)  # 服务在跑，仅轮询等待
                continue
            log("[GUARD] 端口 %d 未监听，启动 app.py ..." % PORT)
            try:
                with open(LOG, "a", encoding="utf-8") as lf:
                    proc = subprocess.Popen([PYW, APP], stdout=lf, stderr=subprocess.STDOUT)
                proc.wait()
                log("[GUARD] app.py 已退出 (code=%s)，3 秒后重启" % proc.returncode)
            except Exception as e:
                log("[GUARD] 启动失败: %s" % e)
            time.sleep(3)
    finally:
        try:
            os.remove(LOCK)
        except Exception:
            pass

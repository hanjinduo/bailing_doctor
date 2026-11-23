# -*- coding: utf-8 -*-
"""自包含冒烟：必要时拉起后端 → 跑 tests/ → 关掉。用于本机无 pytest 环境。"""
import os
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # output\bailing_doctor
BASE = os.getenv("BASE_URL", "http://127.0.0.1:8010")
TMP = os.path.join(os.path.dirname(os.path.dirname(ROOT)), "temp")  # 会话 temp 目录


def alive():
    try:
        urllib.request.urlopen(BASE + "/api/doctors", timeout=2)
        return True
    except urllib.error.HTTPError:
        return True          # 401 也说明服务活着
    except Exception:
        return False


proc = None
if not alive():
    log = open(os.path.normpath(os.path.join(TMP, "uvicorn_run.log")), "a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8010"],
        cwd=ROOT, stdout=log, stderr=log,
        creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    for _ in range(60):
        if alive():
            break
        time.sleep(0.5)
print("服务就绪：", alive(), "| 自启动：", proc is not None)

os.chdir(ROOT)
sys.path.insert(0, ROOT)
suite = unittest.TestLoader().discover(os.path.join(ROOT, "tests"))
res = unittest.TextTestRunner(verbosity=2).run(suite)
print("SUMMARY run=%d fail=%d err=%d" % (res.testsRun, len(res.failures), len(res.errors)))

if proc:
    proc.terminate()

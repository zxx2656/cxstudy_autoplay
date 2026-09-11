# -*- coding: utf-8 -*-
"""验证主程序行为: 自动连播开关、以及"无浏览器"时能正常退出。
(测试中不会启动或关闭任何浏览器)"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
config.CLOSE_BROWSER_ON_EXIT = False   # 安全: 测试中绝不关闭任何浏览器
from main import App


def main():
    app = App()
    app.browser.start = lambda *a, **k: False     # 测试中绝不真的启动浏览器
    app.auto = True
    app._worker = threading.Thread(target=app._worker_loop, daemon=True)
    app._worker.start()
    time.sleep(3)
    print("status =", app.status, "|", app.status_text())

    app.act_toggle_auto()                 # 关闭自动连播
    time.sleep(2)
    print("关闭后 status =", app.status, "| auto =", app.auto)

    app.act_quit()
    time.sleep(2)
    print("worker alive =", app._worker.is_alive())
    ok = (not app._worker.is_alive()) and (app.auto is False)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())


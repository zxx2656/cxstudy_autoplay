# -*- coding: utf-8 -*-
"""验证抗崩溃: 模拟 Target crashed, 程序应复位重连而不是退出(且不启动浏览器)。"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
config.CLOSE_BROWSER_ON_EXIT = False   # 安全: 测试中绝不关闭任何浏览器
from main import App


class BoomPage:
    @staticmethod
    def is_closed():
        return False


class BoomController:
    page = BoomPage()

    def tick(self):
        raise RuntimeError("Target crashed")


def main():
    app = App()
    app.browser.start = lambda *a, **k: False   # 测试中绝不真的启动浏览器
    app.browser.port = 1                        # 伪装"已连接"
    app.controller = BoomController()
    app.auto = True
    app._user_paused = False

    app._worker = threading.Thread(target=app._worker_loop, daemon=True)
    app._worker.start()
    time.sleep(3)
    print("崩溃后 worker 存活:", app._worker.is_alive())
    print("控制器已复位:", app.controller is None)
    app.act_quit()
    time.sleep(2)
    print("退出后 worker 存活:", app._worker.is_alive())
    ok = (app.controller is None) and (not app._worker.is_alive())
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())


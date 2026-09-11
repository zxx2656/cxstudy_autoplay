# -*- coding: utf-8 -*-
"""学习通自动连播 —— 主程序(仅托盘)。

流程:
  1. 运行程序 -> 自动打开一个"专用调试版浏览器"(程序自己的配置, 与你日常浏览器隔离),
     停在超星学习通登录页;
  2. 你在专用浏览器里登录、进入课程、点开一个视频;
  3. 托盘点「开始自动连播」-> 程序检测视频并自动连播
     (播完自动下一节、跳过章节测验、已完成的跳过不重播、被暂停自动恢复);
  4. 可随时「暂停连播」; 点「退出」-> 程序完全关闭, 专用浏览器一并关闭。

界面: 只有托盘图标(功能键只有自动连播相关项)。若 Win11 把图标折叠进 ^ 区,
      可把它拖到任务栏固定; 程序也会尝试自动设为"常显"。
"""
import os
import sys
import threading
import time

_CRASH_LOG = True          # 由 config.CRASH_LOG 覆盖


def _write_crash(tag):
    """把启动/运行异常写入 crash.log(仅在异常时生成)。
    打包后的程序不写运行日志, 因此这是唯一的排障线索。"""
    if not _CRASH_LOG:
        return
    try:
        import traceback
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "cxauto")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "crash.log"), "a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] {tag}\n")
            f.write(traceback.format_exc())
    except Exception:
        pass


try:
    import config
    from browser_manager import BrowserManager
    from video_controller import VideoController
    _CRASH_LOG = bool(getattr(config, "CRASH_LOG", True))
except Exception:
    _write_crash("导入模块失败")
    raise


def _app_dir():
    """程序所在目录(打包后是 exe 目录, 源码运行是脚本目录)。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


APP_TITLE = "学习通自动连播"
MUTEX_NAME = "Local\\cxauto_single_instance"
LOG_FILE = os.path.join(_app_dir(), "cxstudy_auto.log")
# 打包后的程序不写运行日志; 源码运行时写(便于排障)
LOG_ENABLED = (not getattr(sys, "frozen", False)) or bool(getattr(config, "LOG_IN_PACKAGED", False))


def _single_instance_guard():
    """只允许运行一个实例。返回句柄; 若已有实例在运行则返回 None。"""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.CreateMutexW(None, False, MUTEX_NAME)
        if k32.GetLastError() == 183:      # ERROR_ALREADY_EXISTS
            return None
        return h
    except Exception:
        return True                        # 判断不了就不阻挡


def _message_box(text, title=APP_TITLE, warn=False):
    """原生消息框(不依赖 tkinter, 保持体积轻量)。"""
    try:
        import ctypes
        flags = 0x30 if warn else 0x40     # MB_ICONWARNING / MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(None, text, title, flags)
    except Exception:
        pass


class App:
    def __init__(self):
        self.browser = BrowserManager(log=self.log)
        self.controller = None
        self.status = "idle"
        self.auto = bool(config.AUTO_START)
        self._user_paused = False
        self._quit = threading.Event()
        self._cmd = None
        self._cmd_evt = threading.Event()
        self._lock = threading.Lock()
        self._worker = None
        self._rescan = 0
        self._nf_count = 0
        self._start_fails = 0
        self._last_scan = 0.0
        self._noted_end = False
        self.icon = None

    # ---------- 日志(打包后关闭) ----------
    def log(self, msg):
        if not LOG_ENABLED:
            return
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        try:
            print(line, flush=True)
        except Exception:
            pass
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    # ---------- 状态 ----------
    def _set_status(self, st):
        with self._lock:
            self.status = st
        if self.icon:
            try:
                tag = "连播中" if self.auto else "未连播"
                self.icon.title = f"{APP_TITLE}[{tag}]——{config.STATUS_TEXT.get(st, st)}"
            except Exception:
                pass

    def status_text(self):
        return config.STATUS_TEXT.get(self.status, self.status)

    def _notify(self, msg, title=APP_TITLE):
        self.log(f"[通知] {msg}")
        icon = self.icon
        if icon is None:
            return

        def _do():
            try:
                icon.notify(msg, title)
            except Exception:
                pass

        threading.Thread(target=_do, daemon=True).start()

    # ---------- 托盘动作 ----------
    def _send(self, cmd):
        self._cmd = cmd
        self._cmd_evt.set()

    def act_toggle_auto(self):
        self.auto = not self.auto
        self._send("auto")

    def act_pause(self):
        self._send("pause")

    def act_resume(self):
        self._send("resume")

    def act_open_login(self):
        self._send("login")

    def act_quit(self):
        self._send("quit")

    # ---------- worker ----------
    def _worker_loop(self):
        exe = config.browser_exe()
        self.log(f"程序已启动。专用浏览器: {config.BROWSER_NAME}({exe})")
        if not exe:
            self.log("[启动] 未找到浏览器。")
            _message_box(
                f"没有找到{config.BROWSER_NAME}。\n\n"
                f"请安装它, 或把主程序路径写入:\n{config.user_path_file()}\n\n"
                f"(文件名应为 {config.BROWSER_EXE_NAME})", warn=True)
        self._notify("正在打开专用浏览器, 请在其中登录学习通。")
        while not self._quit.is_set():
            try:
                self._tick_once()
            except Exception as e:
                self._reset(f"异常: {type(e).__name__}: {e}")
                self._wait(2.0)
        self._shutdown()

    def _tick_once(self):
        if self._cmd_evt.is_set():
            self._do_cmd()
            return

        # 1) 连接(首次会启动专用浏览器并打开登录页)
        if not self.browser.connected:
            if not self.browser.start(open_login=True):
                self._start_fails += 1
                if self._start_fails >= 3:
                    if self._start_fails == 3:
                        self._notify("打开专用浏览器失败(已重试3次), 已暂停重试。")
                        self.log("[worker] 连续 3 次无法启动专用浏览器, 暂停重试。")
                    self._set_status("browser-fail")
                    self._wait(30.0)
                    return
                self._set_status("no-browser")
                self._wait(3.0)
                return
            self._start_fails = 0
            self._set_status("stopped" if not self.auto else "watching")
            self._notify("专用浏览器已打开: 请登录学习通 → 进入课程 → 点开视频, "
                         "然后点托盘「自动连播」。")

        # 2) 未开启自动连播: 只保持连接
        if not self.auto:
            self._set_status("stopped")
            self._wait(0.5)
            return

        # 3) 页面关闭 -> 解绑
        if self.controller is not None:
            try:
                if self.controller.page.is_closed():
                    self.log("[worker] 页面已关闭, 重新检测。")
                    self.controller = None
                    self._set_status("watching")
            except Exception:
                self.controller = None

        # 4) 自动检测视频页
        if not self._user_paused and self.controller is None:
            now = time.time()
            if now - self._last_scan >= config.SCAN_INTERVAL:
                self._last_scan = now
                page = self.browser.find_video_page(quiet=True)
                if page is not None:
                    self._bind(page)
                else:
                    self._set_status("watching")

        # 5) 监控
        if self.controller is not None and not self._user_paused:
            ev = self.controller.tick()
            self._set_status(ev)
            self._note_end_once(ev)
            self._after_tick(ev)
            self._wait(config.POLL_INTERVAL)
        else:
            self._wait(0.4)

    def _note_end_once(self, ev):
        if ev == "course-end" and not self._noted_end:
            self._noted_end = True
            self.log("[连播] 已到本章/课程末尾, 自动前进已停止。")
            self._notify("已播到本章/课程末尾。请在浏览器里进入下一个章节的"
                         "任务页, 会自动继续连播。")

    def _do_cmd(self):
        cmd = self._cmd
        self._cmd = None
        self._cmd_evt.clear()
        if cmd == "quit":
            self._quit.set()
        elif cmd == "pause":
            self._user_paused = True
            if self.controller:
                self.controller.paused = True
            self._set_status("paused")
            self._notify("已暂停连播。")
        elif cmd == "resume":
            self._user_paused = False
            if self.controller:
                self.controller.paused = False
            self._set_status("playing" if self.controller else "watching")
        elif cmd == "login":
            if not self.browser.connected and not self.browser.start(open_login=True):
                self._notify("无法打开专用浏览器。")
                return
            self.browser.open_login()
        elif cmd == "auto":
            if self.auto:
                self._start_fails = 0
                self._user_paused = False
                self._set_status("watching")
                self._notify("自动连播已开启: 请进入课程并点开一个视频。")
            else:
                self.controller = None
                self._user_paused = False
                self._set_status("stopped")
                self._notify("自动连播已关闭。")

    def _bind(self, page):
        self.controller = VideoController(page, log=self.log)
        self.controller.paused = False
        self._rescan = 0
        self._nf_count = 0
        self._noted_end = False
        try:
            self.log(f"[连播] 检测到学习通视频页, 开始: {(page.url or '')[:80]}")
        except Exception:
            self.log("[连播] 检测到学习通视频页, 开始。")
        self._set_status("playing")
        self._notify("检测到学习通视频, 已开始自动连播。")

    def _after_tick(self, ev):
        if ev == "next-not-found":
            self._nf_count += 1
            if self._nf_count >= 3:
                self._nf_count = 0
                self._reset("连续找不到下一节")
                return
        else:
            self._nf_count = 0
        if ev in ("waiting-video", "next-not-found", "next-clicked", "done", "done-grace"):
            self._rescan += 1
            if self._rescan % 4 == 0:
                page = self.browser.find_video_page(quiet=True)
                if page is not None and self.controller and page != self.controller.page:
                    self._bind(page)

    def _reset(self, why):
        self.controller = None
        try:
            self.browser.reset(why)
        except Exception:
            pass

    def _wait(self, timeout):
        if self._cmd_evt.wait(timeout=timeout):
            self._do_cmd()

    def _shutdown(self):
        self.log("正在退出…")
        try:
            self.browser.shutdown_browser()   # 断开连接 + 关闭专用浏览器
        except Exception:
            pass
        try:
            if self.icon:
                self.icon.stop()
        except Exception:
            pass

    # ---------- 托盘(唯一界面) ----------
    def _tray_thread(self):
        try:
            import pystray
            import PIL.Image, PIL.ImageDraw
        except Exception as e:
            self.log(f"[托盘] 依赖不可用: {e}")
            _message_box(f"托盘组件不可用, 程序无法操作。\n{e}", warn=True)
            return
        try:
            img = PIL.Image.new("RGB", (64, 64), (30, 120, 220))
            d = PIL.ImageDraw.Draw(img)
            d.polygon([(22, 18), (22, 46), (50, 32)], fill="white")
            menu = pystray.Menu(
                pystray.MenuItem("自动连播", lambda *a: self.act_toggle_auto(),
                                 checked=lambda i: self.auto, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("暂停连播", lambda *a: self.act_pause()),
                pystray.MenuItem("继续连播", lambda *a: self.act_resume()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("打开学习通登录页", lambda *a: self.act_open_login()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出(同时关闭专用浏览器)", lambda *a: self.act_quit()),
            )
            self.icon = pystray.Icon(APP_TITLE, img, APP_TITLE, menu)
            self.log("[托盘] 图标已创建")
            threading.Thread(target=self._promote_tray_later, daemon=True).start()
            self.icon.run()
        except Exception as e:
            self.log(f"[托盘] 创建失败: {e}")
            _message_box(f"托盘图标创建失败, 程序无法操作。\n{e}", warn=True)

    def _promote_tray_later(self):
        time.sleep(4)
        self._promote_tray_icon()

    def _promote_tray_icon(self):
        """尽力把托盘图标设为"始终显示"(Win11 默认会把新图标折叠进 ^ 区)。"""
        try:
            import winreg
            exe = os.path.normcase(os.path.abspath(sys.executable))
            base = r"Control Panel\NotifyIconSettings"
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as k:
                    n = winreg.QueryInfoKey(k)[0]
                    subs = [winreg.EnumKey(k, i) for i in range(n)]
            except Exception:
                self.log("[托盘] 当前系统无托盘设置项(可手动把图标拖到任务栏)")
                return
            changed = 0
            for sub in subs:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base + "\\" + sub, 0,
                                        winreg.KEY_READ | winreg.KEY_SET_VALUE) as sk:
                        try:
                            path, _ = winreg.QueryValueEx(sk, "ExecutablePath")
                        except Exception:
                            continue
                        if os.path.normcase(os.path.abspath(str(path))) != exe:
                            continue
                        winreg.SetValueEx(sk, "IsPromoted", 0, winreg.REG_DWORD, 1)
                        changed += 1
                except Exception:
                    continue
            if changed:
                self.log(f"[托盘] 已把图标设为常显({changed} 项)")
        except Exception as e:
            self.log(f"[托盘] 设置常显失败(不影响使用): {e}")

    # ---------- 入口 ----------
    def run(self):
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        threading.Thread(target=self._tray_thread, daemon=True).start()
        self._quit.wait()
        try:
            if self._worker is not None:
                self._worker.join(timeout=8)   # 等收尾(关闭专用浏览器)
        except Exception:
            pass


def main():
    if _single_instance_guard() is None:
        _message_box("学习通自动连播已经在运行了(请看任务栏右下角托盘图标)。")
        return
    App().run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _write_crash("运行失败")
        raise

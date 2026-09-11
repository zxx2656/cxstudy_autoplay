# -*- coding: utf-8 -*-
"""专用浏览器管理(轻量 CDP 接管, 不用 Playwright)。

关键设计(避免干扰你自己点开的窗口):
  · 列举页面只用 HTTP 接口 /json/list —— 零侵扰, 不建立任何连接;
  · 只有"开启自动连播"后, 才会对**学习通域名**的页面建立 CDP 连接;
  · 完全不接管浏览器本身, 因此新开的弹窗/窗口不受任何影响;
  · 退出时只关闭"本程序启动的那个实例", 绝不动你自己的浏览器。
"""
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.request

import cdp
import config


# ---------- 基础工具 ----------
def port_open(port, timeout=0.8):
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def free_port():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def probe_app_browser():
    """查询"本程序启动的"专用浏览器: 返回 (是否存在, 调试端口或 None)。"""
    ps = ("Get-CimInstance Win32_Process -Filter "
          f"\"Name='{config.BROWSER_EXE_NAME}'\" | "
          "Select-Object -ExpandProperty CommandLine")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=20).stdout or ""
    except Exception:
        return False, None
    if config.MARKER not in out:
        return False, None
    for m in re.finditer(r"--remote-debugging-port=(\d+)", out):
        p = int(m.group(1))
        if port_open(p):
            return True, p
    return True, None


def kill_app_browser(log=print):
    """只结束"本程序启动的"专用浏览器(按标记匹配)。"""
    ps = ("Get-CimInstance Win32_Process -Filter "
          f"\"Name='{config.BROWSER_EXE_NAME}'\" | "
          f"Where-Object {{ $_.CommandLine -like '*{config.MARKER}*' }} | "
          "Select-Object -ExpandProperty ProcessId")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=20).stdout or ""
    except Exception:
        return 0
    n = 0
    for tok in out.split():
        if tok.strip().isdigit():
            subprocess.run(["taskkill", "/F", "/PID", tok.strip()],
                           capture_output=True, text=True)
            n += 1
    return n


def clear_profile(log=print):
    p = os.path.expandvars(config.BROWSER_PROFILE)
    if os.path.isdir(p):
        shutil.rmtree(p, ignore_errors=True)
        log("[browser] 已清空专用浏览器配置")


# ---------- 启动 ----------
def launch_browser(port, open_login=True, log=print):
    exe = config.browser_exe()
    if not exe:
        log(f"[browser] 未找到{config.BROWSER_NAME}可执行文件"
            "(请检查 config.py 里的路径)。")
        return False
    profile = config.browser_profile()
    args = [exe, f"--remote-debugging-port={port}", f"--user-data-dir={profile}"]
    args += config.EXTRA_ARGS
    if open_login and config.LOGIN_URL:
        args.append(config.LOGIN_URL)
    log(f"[browser] 启动专用{config.BROWSER_NAME} (端口 {port})")
    try:
        subprocess.Popen(args, cwd=os.path.dirname(exe))
    except Exception as e:
        log("[browser] 启动失败:", e)
        return False
    deadline = time.time() + config.PAGE_WAIT
    while time.time() < deadline:
        if port_open(port):
            time.sleep(1.5)
            log("[browser] 专用浏览器已就绪")
            return True
        time.sleep(0.5)
    log("[browser] 等待调试端口超时。")
    return False


def ensure_browser(open_login=True, log=print):
    exists, port = probe_app_browser()
    if port:
        log(f"[browser] 复用已在运行的专用浏览器 (端口 {port})")
        return port
    if exists:
        log("[browser] 专用浏览器状态异常, 重启它。")
        kill_app_browser(log=log)
        time.sleep(2)
    if port_open(config.CDP_PORT):
        return config.CDP_PORT
    port = free_port()
    return port if launch_browser(port, open_login=open_login, log=log) else None


# ---------- 轻量接管 ----------
class BrowserManager:
    def __init__(self, log=print):
        self.log = log
        self.port = None
        self._pages = {}        # target_id -> cdp.CDPPage

    @property
    def connected(self):
        return self.port is not None

    def start(self, open_login=True):
        """启动/连接专用浏览器。注意: 这里**不会**连接任何页面。"""
        if self.port is not None:
            return True
        port = ensure_browser(open_login=open_login, log=self.log)
        if not port:
            return False
        try:
            cdp.list_targets(port)
        except Exception as e:
            self.log(f"[browser] 调试端口不可用: {e}")
            return False
        self.port = port
        self.log(f"[browser] 已连接专用浏览器 (端口 {port}); "
                 "未开启连播时不会接管任何页面。")
        return True

    # ---------- 页面(HTTP 枚举, 零侵扰) ----------
    def list_pages(self):
        if self.port is None:
            return []
        try:
            targets = cdp.list_targets(self.port)
        except Exception:
            return []
        out = []
        for t in targets:
            if t.get("type") != "page" or not t.get("webSocketDebuggerUrl"):
                continue
            out.append({"id": t.get("id"),
                        "url": t.get("url") or "",
                        "ws": t["webSocketDebuggerUrl"]})
        alive = {p["id"] for p in out}
        for tid in list(self._pages):
            if tid not in alive:
                try:
                    self._pages[tid].close()
                except Exception:
                    pass
                self._pages.pop(tid, None)
        return out

    def _allowed(self, url):
        u = (url or "").lower()
        return any(k.lower() in u for k in config.ALLOWED_PAGE_KEYWORDS)

    def _order_key(self, url):
        u = (url or "").lower()
        for i, k in enumerate(config.PREFERRED_PAGE_KEYWORDS):
            if k.lower() in u:
                return i
        return len(config.PREFERRED_PAGE_KEYWORDS)

    def _page_obj(self, info):
        """按需建立到该页面的 CDP 连接(缓存)。只对学习通页面调用。"""
        pg = self._pages.get(info["id"])
        if pg is None:
            pg = cdp.CDPPage(self.port,
                             {"id": info["id"], "url": info["url"],
                              "webSocketDebuggerUrl": info["ws"]},
                             log=self.log)
            self._pages[info["id"]] = pg
            self.log(f"[browser] 连接页面: {(info['url'] or '')[:70]}")
        return pg

    def pages(self):
        """只返回"学习通页面"的对象(会按需建立连接)。"""
        return [self._page_obj(i) for i in self.list_pages() if self._allowed(i["url"])]

    def open_login(self):
        infos = self.list_pages()
        for info in infos:
            if self._allowed(info["url"]):
                try:
                    self._page_obj(info).bring_to_front()
                except Exception:
                    pass
                return True
        blank = next((p for p in infos
                      if (p["url"] or "").startswith("about:")
                      or "new-tab" in (p["url"] or "")), None)
        target = blank or (infos[0] if infos else None)
        if target is None:
            return False
        try:
            self._page_obj(target).navigate(config.LOGIN_URL)
            self.log("[browser] 已打开学习通登录页")
            return True
        except Exception as e:
            self.log(f"[browser] 打开登录页失败: {e}")
            return False

    def find_video_page(self, quiet=False):
        """只在学习通页面里找含 <video> 的页面, 优先"未播完"的。"""
        infos = [i for i in self.list_pages() if self._allowed(i["url"])]
        if not infos:
            if not quiet:
                self.log("[browser] 当前没有学习通页面。")
            return None
        infos.sort(key=lambda i: self._order_key(i["url"]))
        fallback = None
        for info in infos:
            try:
                page = self._page_obj(info)
            except Exception as e:
                if not quiet:
                    self.log(f"[browser] 连接页面失败: {e}")
                continue
            for fr in page.frames:
                try:
                    if not fr.evaluate("() => !!document.querySelector('video')"):
                        continue
                except Exception:
                    continue
                try:
                    st = fr.evaluate(config.VIDEO_STATE_JS)
                    dur = (st or {}).get("dur") or 0
                    ct = (st or {}).get("ct") or 0
                    if dur > 0 and ct >= dur - config.VIDEO_END_TOLERANCE:
                        if fallback is None:
                            fallback = page
                        continue
                except Exception:
                    pass
                if not quiet:
                    self.log(f"[browser] 找到视频页: {(info['url'] or '')[:80]!r}")
                return page
        return fallback

    # ---------- 关闭 ----------
    def close(self):
        """断开所有页面连接(不关闭浏览器)。"""
        for p in list(self._pages.values()):
            try:
                p.close()
            except Exception:
                pass
        self._pages = {}
        self.port = None

    def shutdown_browser(self):
        self.close()
        if config.CLOSE_BROWSER_ON_EXIT:
            n = kill_app_browser(log=self.log)
            if n:
                self.log(f"[browser] 已关闭专用浏览器 ({n} 个进程)")
        if config.CLEAR_PROFILE_ON_EXIT:
            clear_profile(log=self.log)

    def reset(self, why=""):
        if why:
            self.log(f"[browser] 复位连接: {why}")
        self.close()

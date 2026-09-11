# -*- coding: utf-8 -*-
"""极简 Chrome DevTools Protocol 客户端(不依赖 Playwright/Node)。

只实现本项目需要的能力:
  · 列出页面目标 (/json/list)
  · 连接某个页面, 执行 JS(支持 iframe 子框架)
  · 截图 / 置前 / 自动接受 confirm、alert 弹窗
"""
import base64
import json
import time
import urllib.request

from websocket import create_connection, WebSocketTimeoutException


class CDPError(Exception):
    pass


def http_json(port, path, method="GET"):
    req = urllib.request.Request(f"http://127.0.0.1:{int(port)}{path}", method=method)
    with urllib.request.urlopen(req, timeout=3) as r:
        body = r.read().decode("utf-8", "replace")
    return json.loads(body) if body.strip() else {}


def list_targets(port):
    """返回所有 CDP 目标。"""
    return http_json(port, "/json/list") or []


def _wrap(expr, arg=None):
    """把 JS 表达式规范化:
    - 传入 arg: 视为函数, 调用 (fn)(arg)
    - 以 "()" 开头的箭头函数: 调用之
    - 其它(如已是 IIFE): 原样求值
    """
    e = (expr or "").strip()
    if arg is not None:
        return f"({e})({json.dumps(arg, ensure_ascii=False)})"
    if e.startswith("()") or e.startswith("(function"):
        return f"({e})()"
    return e


class CDPConnection:
    """与单个页面目标的 CDP 连接。"""

    def __init__(self, ws_url, log=print, timeout=15):
        self.log = log
        self.timeout = timeout
        self._id = 0
        self._ctx_cache = {}
        self.ws = create_connection(ws_url, timeout=1.0, max_size=None,
                                    suppress_origin=True)
        self._call("Page.enable")
        self._call("Runtime.enable")

    # ---- 底层收发 ----
    def _call(self, method, params=None, timeout=None):
        timeout = timeout or self.timeout
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = self.ws.recv()
            except WebSocketTimeoutException:
                continue
            except Exception as e:
                raise CDPError(f"连接中断: {e}")
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if "id" in msg:
                if msg["id"] == mid:
                    if "error" in msg:
                        raise CDPError(f"{method}: {msg['error'].get('message')}")
                    return msg.get("result", {})
                continue  # 其它命令的响应(如弹窗处理), 忽略
            self._on_event(msg)
        raise CDPError(f"{method} 超时")

    def _on_event(self, msg):
        """处理事件: 自动接受 JS 弹窗(跳过测验常被 confirm 拦住)。"""
        if msg.get("method") == "Page.javascriptDialogOpening":
            p = msg.get("params", {})
            self.log(f"[cdp] 自动接受弹窗({p.get('type')}): "
                     f"{str(p.get('message'))[:50]}")
            try:
                self._id += 1
                self.ws.send(json.dumps({
                    "id": self._id, "method": "Page.handleJavaScriptDialog",
                    "params": {"accept": True}}))
            except Exception:
                pass

    # ---- 求值 ----
    def _context(self, frame_id):
        ctx = self._ctx_cache.get(frame_id)
        if ctx:
            return ctx
        res = self._call("Page.createIsolatedWorld",
                         {"frameId": frame_id, "worldName": "cxauto"})
        ctx = res.get("executionContextId")
        self._ctx_cache[frame_id] = ctx
        return ctx

    def evaluate(self, expr, frame_id=None, arg=None, timeout=None):
        js = _wrap(expr, arg)
        for attempt in (0, 1):
            try:
                ctx = self._context(frame_id) if frame_id else None
                params = {"expression": js, "returnByValue": True,
                          "awaitPromise": True, "userGesture": True}
                if ctx:
                    params["contextId"] = ctx
                res = self._call("Runtime.evaluate", params, timeout=timeout)
                if res.get("exceptionDetails"):
                    desc = (res["exceptionDetails"].get("exception") or {}).get("description")
                    raise CDPError(desc or "JS 异常")
                return (res.get("result") or {}).get("value")
            except CDPError as e:
                if attempt == 0 and "context" in str(e).lower() and frame_id:
                    self._ctx_cache.pop(frame_id, None)
                    continue
                raise
        return None

    # ---- 框架 ----
    def frame_list(self):
        """返回 [(frameId, url)] —— 含所有子 iframe。
        注意: CDP 的 Frame 对象里帧 ID 字段名是 "id"(不是 frameId)。"""
        res = self._call("Page.getFrameTree")
        out = []

        def walk(node):
            f = node.get("frame") or {}
            fid = f.get("id") or f.get("frameId")
            out.append((fid, f.get("url", "")))
            for ch in (node.get("childFrames") or []):
                walk(ch)

        walk(res.get("frameTree") or {})
        return out

    # ---- 其它 ----
    def bring_to_front(self):
        try:
            self._call("Page.bringToFront", timeout=5)
        except Exception:
            pass

    def screenshot(self, path):
        res = self._call("Page.captureScreenshot", {"format": "png"})
        data = res.get("data")
        if not data:
            raise CDPError("截图返回为空")
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))

    def navigate(self, url):
        self._call("Page.navigate", {"url": url})

    def alive(self):
        try:
            self._call("Runtime.evaluate",
                       {"expression": "1", "returnByValue": True}, timeout=3)
            return True
        except Exception:
            return False

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


class CDPFrame:
    def __init__(self, page, frame_id, url):
        self._page = page
        self.frame_id = frame_id
        self.url = url or ""
        self.is_closed = False

    def evaluate(self, expr, arg=None):
        return self._page._conn.evaluate(expr, frame_id=self.frame_id, arg=arg)


class CDPPage:
    """一个页面(标签)的封装, 提供与控制器兼容的接口。"""

    def __init__(self, port, target, log=print):
        self.port = int(port)
        self.target_id = target.get("id")
        self._log = log
        self._url = target.get("url", "") or ""
        self._url_at = 0.0
        self._frames = []
        self._conn = CDPConnection(target["webSocketDebuggerUrl"], log=log)

    # ---- 基础 ----
    @property
    def url(self):
        if self._url and (time.time() - self._url_at) < 1.0:
            return self._url
        try:
            u = self._conn.evaluate("() => location.href")
            if isinstance(u, str) and u:
                self._url = u
                self._url_at = time.time()
        except Exception:
            pass
        return self._url

    @property
    def frames(self):
        try:
            lst = self._conn.frame_list()
        except Exception:
            return self._frames or []
        # 关键: 重建帧列表时, 把上一轮的帧对象标记为"已关闭",
        # 否则状态机会一直拿着失效的旧 iframe 求值, 永远看不到新视频。
        for old in self._frames:
            old.is_closed = True
        new_frames = [CDPFrame(self, fid, u) for fid, u in lst]
        by_id = {f.frame_id: f for f in new_frames}
        # 帧 ID 不变的(内容在同一 iframe 内刷新)沿用状态, 不过期
        for old in self._frames:
            cur = by_id.get(old.frame_id)
            if cur is not None:
                cur.is_closed = False
        self._frames = new_frames
        if self._frames:
            self._url = self._frames[0].url or self._url
            self._url_at = time.time()
        return self._frames

    def is_closed(self):
        try:
            if not self._conn.ws.connected:
                return True
        except Exception:
            return True
        return False

    # ---- 动作 ----
    def bring_to_front(self):
        self._conn.bring_to_front()

    def navigate(self, url):
        self._conn.navigate(url)

    def screenshot(self, path):
        self._conn.screenshot(path)

    def close(self):
        self._conn.close()

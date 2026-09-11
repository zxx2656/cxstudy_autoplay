# -*- coding: utf-8 -*-
"""回归测试: 视频页查找只在学习通域名内进行(不接管 B 站等), 且只在需要时才连接页面。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from browser_manager import BrowserManager


class FakeFrame:
    def __init__(self, has_video, dur=60.0, ct=10.0):
        self.has = has_video
        self.dur = dur
        self.ct = ct
        self.is_closed = False
        self.url = "https://x/player"

    def evaluate(self, expr, arg=None):
        js = expr or ""
        if js.strip() == config.VIDEO_STATE_JS.strip():
            if not self.has:
                return None
            return {"paused": False, "ct": self.ct, "dur": self.dur,
                    "ended": False, "rate": 1, "ready": 4}
        if "querySelector('video')" in js:
            return self.has
        return None


class FakePage:
    def __init__(self, url, has_video=True, dur=60.0, ct=10.0):
        self.url = url
        self._frames = [FakeFrame(has_video, dur, ct)]

    @property
    def frames(self):
        return self._frames

    def is_closed(self):
        return False


def make(pages):
    bm = BrowserManager(log=lambda *a: None)
    bm.port = 1
    infos = [{"id": f"t{i}", "url": p.url, "ws": "ws://x"} for i, p in enumerate(pages)]
    mapping = {f"t{i}": p for i, p in enumerate(pages)}
    bm.list_pages = lambda: infos                      # HTTP 枚举(零侵扰)
    bm._page_obj = lambda info: mapping[info["id"]]    # 按需连接
    return bm, mapping


def main():
    ok = True

    bm, _ = make([FakePage("https://www.bilibili.com/video/BV1xx")])
    r = bm.find_video_page(quiet=True) is None
    ok &= r
    print(("OK " if r else "XX ") + "只有B站视频 -> 不接管")

    cxk = FakePage("https://mooc1.chaoxing.com/mycourse/studentstudy?chapterId=1")
    bm2, _ = make([FakePage("https://www.bilibili.com/video/BV1xx"), cxk])
    r2 = bm2.find_video_page(quiet=True) is cxk
    ok &= r2
    print(("OK " if r2 else "XX ") + "B站+学习通 -> 选学习通")

    done = FakePage("https://mooc1.chaoxing.com/mycourse/studentstudy?chapterId=1", ct=60.0, dur=60.0)
    fresh = FakePage("https://mooc1.chaoxing.com/mycourse/studentstudy?chapterId=2", ct=1.0, dur=60.0)
    bm3, _ = make([done, fresh])
    r3 = bm3.find_video_page(quiet=True) is fresh
    ok &= r3
    print(("OK " if r3 else "XX ") + "优先未播完页面")

    bm4, _ = make([FakePage("https://mooc1.chaoxing.com/work/index", has_video=False)])
    r4 = bm4.find_video_page(quiet=True) is None
    ok &= r4
    print(("OK " if r4 else "XX ") + "学习通无视频页 -> None")

    # 关键回归: 只有学习通页面才会被建立连接
    bm5, mapping5 = make([FakePage("https://www.bilibili.com/x"),
                          FakePage("https://mooc1.chaoxing.com/a", has_video=False)])
    connected = []

    def spy(info):
        connected.append(info["url"])
        return mapping5[info["id"]]

    bm5._page_obj = spy
    bm5.find_video_page(quiet=True)
    only_cx = bool(connected) and all("chaoxing" in u for u in connected)
    ok &= only_cx
    print(("OK " if only_cx else "XX ") + f"只连接学习通页面(实际: {connected})")

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())


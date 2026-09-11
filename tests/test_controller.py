# -*- coding: utf-8 -*-
"""单元测试: 纯 JS/CDP 版状态机(不依赖真实浏览器)。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from video_controller import VideoController


class FakeFrame:
    def __init__(self, video_state=None, has_next=True):
        self.video_state = video_state
        self.has_next = has_next
        self.is_closed = False
        self.url = "https://mooc1.chaoxing.com/player"

    def evaluate(self, expr, arg=None):
        js = expr or ""
        if js.strip() == config.VIDEO_STATE_JS.strip():
            return self.video_state
        if "out.push" in js:                 # 调试快照
            return []
        if "querySelector(sel)" in js:       # CSS 选择器点击
            return bool(self.has_next)
        if "links[i]" in js:                 # 目录 chapterId 回退
            return None
        if "下一" in js:                     # 文字策略
            return "下一节" if self.has_next else None
        if "播放" in js:                     # 播放按钮文字
            return None
        if "querySelector('video')" in js:
            return self.video_state is not None
        return None


class FakePage:
    def __init__(self, frame, url="https://mooc1.chaoxing.com/mycourse/studentstudy?chapterId=1"):
        self._f = frame
        self.url = url

    @property
    def frames(self):
        return [self._f]

    def is_closed(self):
        return False


def check(name, got, want):
    ok = got == want
    print(f"{'OK ' if ok else 'XX '} {name}: got={got} want={want}")
    return ok


def main():
    ok = True

    # 1) 播完 -> 点下一节
    done = {"paused": False, "ct": 60.0, "dur": 60.0, "ended": False, "rate": 1, "ready": 4}
    c = VideoController(FakePage(FakeFrame(done)), log=print)
    ev1 = c.tick()
    c._done_at = time.time() - 10
    ev2 = c.tick()
    ok &= check("播完第1拍", ev1, "done")
    ok &= check("播完宽限后", ev2, "next-clicked")

    # 2) 播放中
    playing = {"paused": False, "ct": 10.0, "dur": 60.0, "ended": False, "rate": 1, "ready": 4}
    ok &= check("播放中", VideoController(FakePage(FakeFrame(playing)), log=print).tick(), "playing")

    # 3) 暂停 -> 自愈
    paused = {"paused": True, "ct": 10.0, "dur": 60.0, "ended": False, "rate": 1, "ready": 4}
    ok &= check("暂停自愈", VideoController(FakePage(FakeFrame(paused)), log=print).tick(), "recovering")

    # 4) 无视频(测验) -> 宽限后点下一节前进
    c4 = VideoController(FakePage(FakeFrame(None)), log=print)
    e1 = c4.tick()
    c4._no_video_since = time.time() - 10
    e2 = c4.tick()
    ok &= check("无视频首拍", e1, "waiting-video")
    ok &= check("无视频宽限后前进", e2, "next-clicked")

    # 5) 非学习通页面 -> 绝不点击
    c5 = VideoController(FakePage(FakeFrame(None), url="https://www.bilibili.com/video/x"), log=print)
    c5.tick()
    c5._no_video_since = time.time() - 10
    ok &= check("非学习通页不动作", c5.tick(), "waiting-video")

    # 6) 连续前进上限
    c6 = VideoController(FakePage(FakeFrame(None)), log=print)
    c6.tick()                                    # 先跑一拍以同步页面地址
    c6._advance_streak = config.MAX_ADVANCE_STREAK
    c6._no_video_since = time.time() - 10
    ok &= check("达到上限停止", c6.tick(), "next-not-found")

    # 7) 找不到下一节 -> next-not-found
    c7 = VideoController(FakePage(FakeFrame(done, has_next=False)), log=print)
    c7.tick()
    c7._done_at = time.time() - 10
    ok &= check("找不到下一节", c7.tick(), "next-not-found")

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())


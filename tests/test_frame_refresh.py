# -*- coding: utf-8 -*-
"""回归测试(对应真实故障):
  切换任务时, 学习通会把内容 iframe 换掉(frameId 变化)。
  程序必须能发现旧 iframe 已失效并重新定位, 否则会"永远找不到视频"。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from video_controller import VideoController

URL = "https://mooc1.chaoxing.com/mycourse/studentstudy?chapterId=111"


class Frame:
    def __init__(self, fid, state, task_done=False):
        self.frame_id = fid
        self.state = state
        self.task_done = task_done
        self.is_closed = False
        self.url = "https://mooc1.chaoxing.com/player/" + fid

    def evaluate(self, expr, arg=None):
        js = expr or ""
        if js.strip() == config.VIDEO_STATE_JS.strip():
            return self.state
        if "out.push" in js:
            return []
        if "任务点已完成" in js:
            return self.task_done
        if "isTask" in js:
            return {"status": "clicked", "text": "next-task"}
        if "下一" in js:
            return None
        if "querySelector('video')" in js:
            return self.state is not None
        return None


class Page:
    """模拟 CDPPage: 重建帧列表时把旧帧标记为已关闭(与 cdp.py 行为一致)。"""

    def __init__(self, frame):
        self.url = URL
        self.cur = frame
        self._seen = [frame]

    @property
    def frames(self):
        for f in self._seen:
            f.is_closed = True
        self.cur.is_closed = False
        self._seen = [self.cur]
        return [self.cur]

    def is_closed(self):
        return False


PLAYING = {"paused": False, "ct": 5.0, "dur": 60.0, "ended": False, "rate": 1, "ready": 4}
DONE = {"paused": False, "ct": 60.0, "dur": 60.0, "ended": False, "rate": 1, "ready": 4}


def check(name, got, want, ok):
    good = got == want
    print(("OK " if good else "XX ") + f"{name}: got={got} want={want}")
    return ok and good


def main():
    ok = True

    # 1) 正常播放
    page = Page(Frame("f1", DONE))
    c = VideoController(page, log=print)
    e1 = c.tick()
    ok = check("第1个任务: 已播完", e1, "done", ok)
    c._done_at = time.time() - 10
    e2 = c.tick()
    ok = check("第1个任务: 前进", e2, "next-clicked", ok)

    # 2) 关键: 任务切换后 iframe 被替换(URL 不变), 必须重新定位到新帧
    page.cur = Frame("f2", PLAYING)          # 新任务的视频(刚开始播)
    e3 = c.tick()
    ok = check("iframe被替换后应看到新视频", e3, "playing", ok)

    # 3) 再换一次: 新任务已标记完成 -> 应跳过而不重播
    page.cur = Frame("f3", PLAYING, task_done=True)
    page.url = URL + "&x=2"                   # 换个地址, 模拟跳到下一个任务
    e4 = c.tick()
    ok = check("已完成任务 -> 跳过", e4, "next-clicked", ok)

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())


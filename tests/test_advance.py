# -*- coding: utf-8 -*-
"""回归测试: 前进逻辑
  · 优先用目录(chapterId)跳转;
  · 目录里后面没有任务了 -> 干净停下(course-end), 不再盲目连点;
  · 不在"任务页"(例如课程首页)时 -> 绝不点击;
  · 视频播完 -> 正常前进。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from video_controller import VideoController


class FakeFrame:
    def __init__(self, state=None, catalog=None):
        self.state = state
        self.catalog = catalog          # {"status": "clicked"/"end"/"nolocate"}
        self.is_closed = False
        self.url = "https://mooc1.chaoxing.com/player"

    def evaluate(self, expr, arg=None):
        js = expr or ""
        if js.strip() == config.VIDEO_STATE_JS.strip():
            return self.state
        if "out.push" in js:            # 调试快照
            return []
        if "isTask" in js:              # 目录跳转
            return self.catalog
        if "下一" in js:                # 文字兜底: 本测试中一律找不到
            return None
        if "querySelector('video')" in js:
            return self.state is not None
        return None


class FakePage:
    def __init__(self, url, frame):
        self.url = url
        self._f = frame

    @property
    def frames(self):
        return [self._f]

    def is_closed(self):
        return False


STUDY = "https://mooc1.chaoxing.com/mycourse/studentstudy?chapterId=111&courseId=2"
HOME = "https://i.chaoxing.com/base?t=1789107325867"
PLAYING = {"paused": False, "ct": 10.0, "dur": 60.0, "ended": False, "rate": 1, "ready": 4}
DONE = {"paused": False, "ct": 60.0, "dur": 60.0, "ended": False, "rate": 1, "ready": 4}


def check(name, got, want, ok):
    good = got == want
    print(("OK " if good else "XX ") + f"{name}: got={got} want={want}")
    return ok and good


def main():
    ok = True

    # 1) 学习页 + 目录有下一项 -> 点目录前进
    c = VideoController(FakePage(STUDY, FakeFrame(DONE, {"status": "clicked", "text": "3.4 xxx"})), log=print)
    c.tick()
    c._done_at = time.time() - 10
    ok = check("播完->目录跳转", c.tick(), "next-clicked", ok)

    # 2) 学习页 + 目录后面没有任务 -> 干净停下
    c2 = VideoController(FakePage(STUDY, FakeFrame(DONE, {"status": "end"})), log=print)
    c2.tick()
    c2._done_at = time.time() - 10
    e = c2.tick()
    ok = check("播完->到末尾", e, "course-end", ok)
    e2 = c2.tick()
    ok = check("末尾后不再动", e2, "course-end", ok)

    # 3) 无视频 + 学习页 + 目录到末尾 -> course-end, 不是 next-clicked
    c3 = VideoController(FakePage(STUDY, FakeFrame(None, {"status": "end"})), log=print)
    c3.tick()
    c3._no_video_since = time.time() - 10
    e3 = c3.tick()
    ok = check("无视频->到末尾", e3, "course-end", ok)

    # 4) 课程首页(非任务页) + 无视频 -> 绝不点击, 直接 course-end
    c4 = VideoController(FakePage(HOME, FakeFrame(None, {"status": "clicked"})), log=print)
    e4 = c4.tick()
    ok = check("非任务页不点击", e4, "course-end", ok)
    ok = check("非任务页未累计前进", c4._advance_streak, 0, ok)

    # 5) 学习页无视频且目录定位不到 -> 走兜底; 兜底也找不到 -> next-not-found
    c5 = VideoController(FakePage(STUDY, FakeFrame(None, {"status": "nolocate"})), log=print)
    c5.tick()
    c5._no_video_since = time.time() - 10
    e5 = c5.tick()
    ok = check("定位不到->兜底失败", e5, "next-not-found", ok)

    # 6) 正常播放不受影响
    c6 = VideoController(FakePage(STUDY, FakeFrame(PLAYING, {"status": "clicked"})), log=print)
    ok = check("播放中", c6.tick(), "playing", ok)

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())


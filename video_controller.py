# -*- coding: utf-8 -*-
"""核心状态机:
- 读 <video> 状态, 保证持续播放(被暂停/卡住自动恢复)
- 播完 -> 点"下一节"进入下一个任务
- 落到没有视频的任务(如章节测验) -> 也用"下一节"前进, 直接跳过
  (绝不点击目录列表的任意项, 那会跳回第一章)
"""
import re
import time

import config

# ---- 点击"下一节": 精确文字(跨 Playwright / CDP 通用) ----
JS_NEXT_EXACT = """() => {
  const wants = ['下一节','下一讲','下一个','下一章','下一任务','下一课'];
  const els = document.querySelectorAll('a,button,div,span,li');
  for (const e of els) {
    const t = (e.innerText || '').trim().replace(/\\s+/g, '');
    if (!t || t.length > 6) continue;
    if (wants.indexOf(t) >= 0) {
      const r = e.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) { e.click(); return t; }
    }
  }
  return null;
}"""

# ---- 点击"下一节": 包含"下一" ----
JS_NEXT_CONTAINS = """() => {
  const els = document.querySelectorAll('a,button,div,span,li');
  for (const e of els) {
    const t = (e.innerText || '').trim().replace(/\\s+/g, '');
    if (!t || t.length > 8) continue;
    if (t.indexOf('下一') >= 0) {
      const r = e.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) { e.click(); return t; }
    }
  }
  return null;
}"""

JS_PLAY = """() => {
  const wants = ['播放','继续播放','点击播放','开始播放'];
  const els = document.querySelectorAll('a,button,div,span');
  for (const e of els) {
    const t = (e.innerText || '').trim().replace(/\\s+/g, '');
    if (wants.indexOf(t) >= 0) {
      const r = e.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) { e.click(); return t; }
    }
  }
  return null;
}"""

# ---- 任务点是否已标记完成(已看过的不需要重播) ----
JS_TASK_DONE = """() => {
  const t = (document.body && document.body.innerText) || '';
  return t.indexOf('任务点已完成') >= 0;
}"""

# ---- 导出课程目录结构(用于精确实现"跳过已完成、直达未完成") ----
JS_CATALOG_DUMP = """() => {
  const out = [];
  document.querySelectorAll('a[href]').forEach(a => {
    const h = a.getAttribute('href') || '';
    if (h.indexOf('chapterId=') < 0) return;
    const t = (a.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 26);
    if (!t) return;
    let cls = '';
    let node = a;
    for (let i = 0; i < 3 && node; i++) {
      const c = (typeof node.className === 'string') ? node.className.trim() : '';
      if (c) cls += (cls ? ' | ' : '') + c.slice(0, 60);
      node = node.parentElement;
    }
    out.push(t + '  >>  ' + (cls || '(无class)'));
  });
  return out.slice(0, 40);
}"""


class VideoController:
    def __init__(self, page, log=print):
        self.page = page
        self.log = log
        self.paused = False
        self._done_at = None
        self._vf = None
        self._last_ct = None
        self._stall_since = None
        self._no_video_since = None
        self._advance_streak = 0
        self._dumped = False
        self._at_end = False          # 已到本章/课程末尾
        self._noted_non_task = False  # 已提示"不在任务页"
        self._noted_giveup = False    # 已提示"放弃前进"
        self._done_checked = False    # 本任务是否已判断过"是否已完成"
        self._catalog_dumped = False  # 是否已导出过目录结构
        self._last_url = ""
        self.last_event = "idle"
        # Playwright 默认"自动取消"弹窗, 会拦住跳转; 这里改成自动接受
        try:
            page.on("dialog", self._on_dialog)
        except Exception:
            pass

    def _on_dialog(self, dialog):
        try:
            self.log(f"[ctrl] 自动接受弹窗({dialog.type}): {str(dialog.message)[:50]}")
            dialog.accept()
        except Exception:
            try:
                dialog.dismiss()
            except Exception:
                pass

    # ---------- 帧 ----------
    def _all_frames(self):
        try:
            return self.page.frames
        except Exception:
            return []

    def _video_frame(self):
        """定位含 <video> 的 iframe。
        注意: 切换任务时学习通会替换内容 iframe, 所以每拍都刷新帧列表,
        并让缓存随之失效——否则会一直拿着失效的旧 iframe, 表现为"永远找不到视频"。"""
        frames = self._all_frames()          # 每拍刷新(Page.getFrameTree, 很轻)
        if self._vf is not None and getattr(self._vf, "is_closed", True) is False:
            vfid = getattr(self._vf, "frame_id", None)
            for f in frames:
                if f is self._vf:
                    return f
                if vfid and getattr(f, "frame_id", None) == vfid:
                    self._vf = f             # 同 ID 的新对象, 换成新的
                    return f
            self._vf = None                  # 旧帧已不在列表里
        for fr in frames:
            if getattr(fr, "is_closed", False):
                continue
            try:
                if fr.evaluate("() => !!document.querySelector('video')"):
                    self._vf = fr
                    return fr
            except Exception:
                continue
        self._vf = None
        return None

    def _page_allowed(self):
        try:
            url = (self.page.url or "").lower()
        except Exception:
            return False
        return any(k.lower() in url for k in config.ALLOWED_PAGE_KEYWORDS)

    def _task_marked_done(self):
        """当前任务点是否已标记"已完成"(已看过的不需要重播)。"""
        for fr in self._all_frames():
            try:
                if fr.evaluate(JS_TASK_DONE):
                    return True
            except Exception:
                continue
        return False

    # ---------- 状态 ----------
    def _state(self):
        fr = self._video_frame()
        if fr is None:
            return None
        try:
            return fr.evaluate(config.VIDEO_STATE_JS)
        except Exception:
            # 帧可能刚被替换掉: 丢弃缓存, 下一次重新定位
            self._vf = None
            return None

    def is_video_done(self, s):
        if not s:
            return False
        if s.get("ended"):
            return True
        dur = s.get("dur") or 0
        ct = s.get("ct") or 0
        return dur > 0 and ct >= dur - config.VIDEO_END_TOLERANCE

    # ---------- 播放控制 ----------
    def _js_play(self):
        fr = self._video_frame()
        if fr is None:
            return
        try:
            fr.evaluate("()=>{const v=document.querySelector('video');"
                        "if(v){v.play().catch(()=>{});}return true;}")
        except Exception:
            pass

    def _click_play_button(self):
        for fr in self._all_frames():
            try:
                if fr.evaluate(JS_PLAY):
                    self.log("[ctrl] 点击了播放按钮")
                    return True
            except Exception:
                pass
            for c in config.PLAY_BUTTON_CANDIDATES:
                try:
                    loc = fr.locator(c).first
                    if loc.count() > 0:
                        loc.click(timeout=1500)
                        self.log(f"[ctrl] 点击播放按钮: {c}")
                        return True
                except Exception:
                    continue
        return False

    def ensure_playing(self):
        s = self._state()
        if not s:
            return False
        if s.get("paused") and not s.get("ended"):
            self.log("[ctrl] 检测到暂停, 尝试恢复…")
            self._js_play()
            self._click_play_button()
            return True
        return False

    # ---------- 前进(三层策略) ----------
    def go_next(self):
        return self._click_next()

    def _click_next(self):
        """前进到下一个任务。顺序: 目录跳转(最稳, 可跨章节) -> 选择器 -> 文字。
        若目录里"当前任务"之后已无任务, 说明到了本章/课程末尾 -> 干净停下。"""
        if self._at_end:
            return "course-end"
        frames = self._all_frames()
        st = self._catalog_next(frames)
        if st == "clicked":
            return "next-clicked"
        if st == "end":
            self._at_end = True
            self.log("[ctrl] 目录里当前任务之后没有任务了: 已到本章/课程末尾, 停止前进。")
            return "course-end"
        # 目录里定位不到当前任务 -> 退回按钮/文字方式
        if frames and hasattr(frames[0], "locator"):
            for fr in frames:
                for c in config.NEXT_BUTTON_CANDIDATES:
                    try:
                        loc = fr.locator(c).first
                        if loc.count() > 0:
                            loc.click(timeout=2000)
                            self.log(f"[ctrl] 点下一节(选择器): {c}")
                            return "next-clicked"
                    except Exception:
                        continue
        for fr in frames:
            try:
                hit = fr.evaluate(JS_NEXT_EXACT)
            except Exception:
                hit = None
            if hit:
                self.log(f"[ctrl] 点下一节(文字): {hit}")
                return "next-clicked"
        for fr in frames:
            try:
                hit = fr.evaluate(JS_NEXT_CONTAINS)
            except Exception:
                hit = None
            if hit:
                self.log(f"[ctrl] 点下一节(含下一): {hit}")
                return "next-clicked"
        self.log("[ctrl] 没找到\"下一节\"。")
        if not self._dumped:
            self._dumped = True
            self._debug_dump("next-not-found")
        return "next-not-found"

    def _current_chapter_id(self):
        try:
            url = self.page.url or ""
        except Exception:
            return None
        m = re.search(r"[?&]chapterId=(\d+)", url)
        return m.group(1) if m else None

    def _catalog_next(self, frames):
        """按 chapterId 在目录(课程侧栏)里精确定位当前任务, 点它的下一项。
        返回: "clicked" / "end"(后面没有任务了) / None(定位不到当前任务)。
        绝不回退到第 0 项, 因此不会跳回第一章。"""
        cid = self._current_chapter_id()
        if not cid:
            return None
        js = """(cid) => {
          const links = Array.from(document.querySelectorAll('a[href]'));
          const isTask = h => !!h && h.indexOf('chapterId=') >= 0;
          let idx = -1;
          for (let i = 0; i < links.length; i++) {
            const h = links[i].getAttribute('href') || '';
            if (h.indexOf('chapterId=' + cid) >= 0) { idx = i; break; }
          }
          if (idx < 0) return {status: 'nolocate'};
          for (let i = idx + 1; i < links.length; i++) {
            const h = links[i].getAttribute('href') || '';
            if (isTask(h)) {
              links[i].click();
              return {status: 'clicked',
                      text: (links[i].innerText || '').trim().slice(0, 30)};
            }
          }
          return {status: 'end'};
        }"""
        for fr in frames:
            try:
                res = fr.evaluate(js, cid)
            except Exception:
                res = None
            if not isinstance(res, dict):
                continue
            if res.get("status") == "clicked":
                self.log(f"[ctrl] 目录跳转(当前 chapterId={cid}) -> {res.get('text')!r}")
                return "clicked"
            if res.get("status") == "end":
                return "end"
        return None

    # ---------- 无视频 ----------
    def _page_can_advance(self):
        """只有"任务页"才允许自动前进, 避免在课程首页盲目连点。"""
        try:
            url = (self.page.url or "").lower()
        except Exception:
            return False
        return any(k.lower() in url for k in config.ADVANCE_ALLOWED_KEYWORDS)

    def _handle_no_video(self):
        if not self._page_allowed():
            self.last_event = "waiting-video"
            return
        if self._at_end:
            self.last_event = "course-end"
            return
        if not self._page_can_advance():
            # 例如课程首页/课程列表: 绝不点击, 只等待(并提示一次)
            if not self._noted_non_task:
                self._noted_non_task = True
                self.log("[ctrl] 当前不在任务页(可能是课程首页/目录页), 已停止自动前进; "
                         "请手动进入下一章的任务页。")
            self._no_video_since = None
            self.last_event = "course-end"
            return
        if self._no_video_since is None:
            self._no_video_since = time.time()
            self.last_event = "waiting-video"
            return
        if time.time() - self._no_video_since < config.QUIZ_GRACE:
            self.last_event = "waiting-video"
            return
        if self._advance_streak >= config.MAX_ADVANCE_STREAK:
            if not self._noted_giveup:
                self._noted_giveup = True
                self.log(f"[ctrl] 已连续前进 {self._advance_streak} 次仍无视频, 停止前进。")
            self._no_video_since = None
            self.last_event = "next-not-found"
            return
        self._no_video_since = None
        self._advance_streak += 1
        self.log(f"[ctrl] 当前任务无视频(可能是章节测验), 前进第 {self._advance_streak} 次。")
        self.last_event = self._click_next()

    # ---------- 主节拍 ----------
    def tick(self):
        if self.paused:
            self.last_event = "paused"
            return self.last_event

        # 页面地址变了 -> 清掉"到末尾/已提示"等状态, 重新开始判断
        try:
            url = self.page.url or ""
        except Exception:
            url = ""
        if url != self._last_url:
            self._last_url = url
            self._at_end = False
            self._noted_non_task = False
            self._noted_giveup = False
            self._no_video_since = None
            self._vf = None          # 换了任务 -> 视频 iframe 缓存必须失效
            self._done_checked = False

        s = self._state()
        if s is None:
            self._handle_no_video()
            return self.last_event

        # 首次看到视频时, 把课程目录结构导出到日志(便于精确识别"已完成")
        if not self._catalog_dumped:
            self._catalog_dumped = True
            self._dump_catalog()

        self._no_video_since = None
        self._advance_streak = 0

        # 任务点已标记"已完成" -> 不重播, 直接前进(每个任务只判断一次)
        if not self._done_checked:
            self._done_checked = True
            if self._task_marked_done():
                self.log("[ctrl] 当前任务点已标记完成, 跳过不重播。")
                self.last_event = self.go_next()
                return self.last_event

        if self.is_video_done(s):
            if self._at_end:
                # 已经到末尾且这个视频就是最后一个: 保持"末尾"状态, 不再来回重试
                self.last_event = "course-end"
                return self.last_event
            if self._done_at is None:
                self._done_at = time.time()
                self.last_event = "done"
                return self.last_event
            if time.time() - self._done_at < config.AUTO_ADVANCE_GRACE:
                self.last_event = "done-grace"
                return self.last_event
            self._done_at = None
            self.last_event = self.go_next()
            return self.last_event

        self._done_at = None
        # 视频正在播放(不是"已播完") -> 说明已经进入新任务, 清掉"末尾/放弃"状态
        self._at_end = False
        self._noted_giveup = False

        if s.get("paused"):
            self.ensure_playing()
            self.last_event = "recovering"
            return self.last_event

        ct = s.get("ct") or 0
        if self._last_ct is not None and abs(ct - self._last_ct) < 0.05:
            if self._stall_since is None:
                self._stall_since = time.time()
            elif time.time() - self._stall_since > config.STALL_SECONDS:
                self.log(f"[ctrl] currentTime 停滞 {config.STALL_SECONDS}s, 恢复。")
                self._js_play()
                self._click_play_button()
                self._stall_since = None
        else:
            self._stall_since = None
        self._last_ct = ct

        self.last_event = "playing"
        return self.last_event

    def _dump_catalog(self):
        """把课程目录(侧栏任务列表)导出到日志, 便于精确识别已完成/未完成。"""
        try:
            self.log("[catalog] ===== 目录结构(供分析) =====")
            self.log(f"[catalog] 当前任务: {(self.page.url or '')[:100]}")
            got = False
            for fr in self._all_frames():
                try:
                    items = fr.evaluate(JS_CATALOG_DUMP)
                except Exception:
                    items = None
                if not items:
                    continue
                got = True
                self.log(f"[catalog] frame: {(fr.url or '')[:70]}")
                for it in items:
                    self.log(f"[catalog]   {it}")
            if not got:
                self.log("[catalog] 未在页面里找到目录项(chapterId 链接)")
            self.log("[catalog] ===== 目录结构结束 =====")
        except Exception as e:
            self.log(f"[catalog] 导出失败: {e}")

    # ---------- 调试快照 ----------
    def _debug_dump(self, reason):
        """只挑与导航相关的关键元素, 便于精调选择器。"""
        try:
            self.log(f"[debug] reason={reason}")
            try:
                self.log(f"[debug] page.url={self.page.url}")
            except Exception:
                pass
            js = """() => {
                const out = [];
                const keys = ['下一','上一','节','测验','提交','作业'];
                document.querySelectorAll('a,button,div,span,li').forEach(e=>{
                  const t = (e.innerText||'').trim();
                  if (!t || t.length > 10) return;
                  const h = (e.getAttribute && (e.getAttribute('href')||'')) || '';
                  if (!keys.some(k=>t.indexOf(k)>=0) && h.indexOf('chapterId=')<0) return;
                  const cls = (typeof e.className==='string'?e.className:'').slice(0,28);
                  out.push(e.tagName + (cls?'.'+cls:'') + ' | ' + t);
                });
                return [...new Set(out)].slice(0,25);
            }"""
            for i, fr in enumerate(self._all_frames()):
                try:
                    info = fr.evaluate(js)
                except Exception:
                    info = None
                if info:
                    self.log(f"[debug] frame[{i}] {(fr.url or '')[:70]}")
                    for line in info:
                        self.log(f"[debug]     {line}")
        except Exception as e:
            self.log(f"[debug] dump 出错: {e}")

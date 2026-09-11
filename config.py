# -*- coding: utf-8 -*-
"""配置。

设计理念:
  · 程序启动后自动打开一个"专用的调试版浏览器", 只用来刷课;
  · 该浏览器使用程序自己的配置目录(非默认目录), 因此
      - 调试端口能正常开启(浏览器 136+ 只对"默认目录"禁用调试端口);
      - 与你日常使用的同款浏览器是两个独立实例, 互不影响;
  · 不需要记录登录信息 —— 每次由你自己在调试版浏览器里登录;
  · 你在托盘里打开"自动连播"后, 程序才开始检测并自动连播;
  · 退出程序时, 调试版浏览器一并关闭。
"""
import os

# ---- 专用浏览器: 夸克 ----
# 提示: 这里只列"通用"位置; 程序还会查注册表, 并在各盘符搜索常见布局
#       (X:\Quark\ , X:\Program Files\Quark\ 等); 都找不到时会提示把路径
#       写入 browser_path.txt(只需一次)。
BROWSER_NAME = "夸克"
BROWSER_EXE_CANDIDATES = [
    r"%LOCALAPPDATA%\Quark\quark.exe",
    r"%ProgramFiles%\Quark\quark.exe",
    r"%ProgramFiles(x86)%Quark\quark.exe",
]
BROWSER_EXE_NAME = "quark.exe"
# 程序自己的浏览器配置(非默认目录, 且与你日常浏览器隔离)
BROWSER_PROFILE = r"%LOCALAPPDATA%\cxauto\quark-profile"

# ---- CDP ----
CDP_PORT = 9222
# 标记: 用于识别"是本程序启动的专用浏览器"。
# 特意用一个新值, 以免与历史版本/其它实例混淆, 从而绝不误关别人的窗口。
MARKER = "--cxauto-dedicated=1"
EXTRA_ARGS = [
    MARKER,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-popup-blocking",
    "--disable-blink-features=AutomationControlled",
    "--autoplay-policy=no-user-gesture-required",
    "--lang=zh-CN",
]

# ---- 启动后自动打开的登录页 ----
LOGIN_URL = ("https://passport2.chaoxing.com/login?fid=&newversion=true"
             "&refer=https%3A%2F%2Fi.chaoxing.com")

# ---- 行为开关 ----
AUTO_START = False              # 默认不自动连播, 由你在托盘里打开
CLOSE_BROWSER_ON_EXIT = True    # 退出程序时关闭调试版浏览器
CLEAR_PROFILE_ON_EXIT = False   # 退出时是否清空浏览器配置(置 True 则每次全新)

# ---- 日志 ----
# 打包成 exe 后默认不写运行日志(保持成品干净); 源码运行时仍写日志便于排障。
LOG_IN_PACKAGED = False
# 崩溃日志: 只在程序异常退出时生成, 正常使用不会产生任何文件。
CRASH_LOG = True

# ---- 只接管这些网站的页面(避免误接管 B 站等) ----
ALLOWED_PAGE_KEYWORDS = ["chaoxing"]
PREFERRED_PAGE_KEYWORDS = ["studentstudy", "mycourse", "nodedetail", "mooc1"]
# 只有这些"任务页"才允许自动前进; 其它页面(课程首页/课程列表等)一律不点,
# 否则会在没有视频的页面上盲目连点"下一节", 陷入死循环。
ADVANCE_ALLOWED_KEYWORDS = [
    "studentstudy", "nodedetail", "knowledge/cards",
    "/work/", "worklist", "exam", "quiz", "chapter_test",
]

# ---- 自动检测 ----
SCAN_INTERVAL = 2.5             # 未绑定视频时的扫描间隔(秒)

# ---- 心跳/时序 ----
POLL_INTERVAL = 1.0
VIDEO_END_TOLERANCE = 0.8       # currentTime 距 duration 小于该值视为播完(秒)
STALL_SECONDS = 10.0            # currentTime 长时间不推进视为卡住(秒)
AUTO_ADVANCE_GRACE = 3.0        # 播完后等待平台自动跳转的宽限(秒)
QUIZ_GRACE = 2.5                # 落在无视频任务上后, 等待稳定再前进的宽限(秒)
MAX_ADVANCE_STREAK = 10         # 连续前进上限(防死循环乱跳)
PAGE_WAIT = 30.0                # 等待调试端口超时(秒)

# ---- <video> 状态探测 JS ----
VIDEO_STATE_JS = """(() => {
  const v = document.querySelector('video');
  if (!v) return null;
  return {paused:v.paused, ct:v.currentTime||0, dur:v.duration||0,
          ended:v.ended, rate:v.playbackRate, ready:v.readyState};
})()"""

# ---- "下一节"按钮候选(Playwright 选择器, 含文字匹配) ----
NEXT_BUTTON_CANDIDATES = [
    "button:has-text('下一节')", "a:has-text('下一节')", "text:下一节",
    "button:has-text('下一讲')", "a:has-text('下一讲')",
    "button:has-text('下一')", "a:has-text('下一')",
    ".next", ".next-btn", ".btn-next", "[class*=next]", "[id*=next]",
]

# ---- 播放按钮蒙层候选 ----
PLAY_BUTTON_CANDIDATES = [
    "text:播放", "text:继续播放", ".vjs-big-play-button", ".xgplayer-play",
    ".prism-big-play-btn", "[class*=play-btn]", "[class*=big-play]",
]

# ---- 状态文案 ----
STATUS_TEXT = {
    "idle": "待命",
    "stopped": "自动连播已关闭(在托盘中打开)",
    "no-browser": "正在准备浏览器…",
    "watching": "已连接, 等待你打开学习通视频",
    "no-video": "未找到学习通视频页",
    "waiting-video": "等待视频…",
    "playing": "连播中",
    "paused": "已暂停",
    "done": "播完, 准备下一节",
    "done-grace": "播完, 等待跳转",
    "next-clicked": "已点下一节",
    "recovering": "恢复播放中…",
    "next-not-found": "找不到下一节",
    "course-end": "已到本章/课程末尾",
    "browser-fail": "浏览器连接失败(已停止重试, 请查看日志)",
}


def _user_path_file():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "cxauto")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return os.path.join(d, "browser_path.txt")


def user_path_file():
    """用户手动指定浏览器路径的文件(找不到浏览器时, 把路径写进这里即可)。"""
    return _user_path_file()


def load_user_browser_path():
    """读取用户手动指定的浏览器路径(可为空)。"""
    try:
        with open(_user_path_file(), "r", encoding="utf-8") as f:
            p = f.read().strip()
        return p or None
    except Exception:
        return None


def save_user_browser_path(path):
    try:
        with open(_user_path_file(), "w", encoding="utf-8") as f:
            f.write(path or "")
    except Exception:
        pass


def _from_registry():
    """从注册表里找: App Paths + 卸载信息里的安装目录。"""
    try:
        import winreg
    except Exception:
        return None
    # 1) App Paths
    sub = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{BROWSER_EXE_NAME}"
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for flag in (0, getattr(winreg, "KEY_WOW64_64KEY", 0),
                     getattr(winreg, "KEY_WOW64_32KEY", 0)):
            try:
                with winreg.OpenKey(root, sub, 0, winreg.KEY_READ | flag) as k:
                    v, _ = winreg.QueryValueEx(k, "")
                    if v and os.path.isfile(v):
                        return v
            except Exception:
                pass
    # 2) 卸载信息表: 按产品名匹配, 再拼上可执行文件名
    keys = [r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"]
    names = ("夸克", "quark", "Quark")
    for kp in keys:
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, kp) as base:
                    n = winreg.QueryInfoKey(base)[0]
                    for i in range(n):
                        try:
                            with winreg.OpenKey(base, winreg.EnumKey(base, i)) as sk:
                                dn = ""
                                try:
                                    dn, _ = winreg.QueryValueEx(sk, "DisplayName")
                                except Exception:
                                    continue
                                if not any(x.lower() in str(dn).lower() for x in names):
                                    continue
                                try:
                                    loc, _ = winreg.QueryValueEx(sk, "InstallLocation")
                                except Exception:
                                    loc = ""
                                if loc:
                                    cand = os.path.join(loc, BROWSER_EXE_NAME)
                                    if os.path.isfile(cand):
                                        return cand
                        except Exception:
                            continue
            except Exception:
                continue
    return None


def _search_disks():
    """在各盘符的常见目录里浅层搜索(有界限, 不会很慢)。"""
    subs = [
        r"Quark\{exe}", r"Program Files\Quark\{exe}",
        r"Program Files (x86)\Quark\{exe}",
        r"QuarkPC\{exe}", r"Program Files\QuarkPC\{exe}",
        r"Program Files (x86)\QuarkPC\{exe}",
        r"Apps\Quark\{exe}",
    ]
    try:
        import string
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if not os.path.isdir(drive):
                continue
            for s in subs:
                p = os.path.join(drive, s.format(exe=BROWSER_EXE_NAME))
                if os.path.isfile(p):
                    return p
    except Exception:
        pass
    return None


_EXE_CACHE = {"path": None, "done": False}


def browser_exe(do_search=True, use_cache=True):
    """定位浏览器可执行文件。顺序:
    1) 用户手动指定(会记住)  2) 常见安装路径  3) 注册表  4) 各盘浅层搜索
    结果会缓存, 避免每次调用都扫描磁盘。
    """
    if use_cache and _EXE_CACHE["done"]:
        p = _EXE_CACHE["path"]
        if p and os.path.isfile(p):
            return p
    p = load_user_browser_path()
    if not (p and os.path.isfile(p)):
        p = None
        for cand in BROWSER_EXE_CANDIDATES:
            cand = os.path.expandvars(cand)
            if os.path.isfile(cand):
                p = cand
                break
        if not p:
            p = _from_registry()
        if not p and do_search:
            p = _search_disks()
    _EXE_CACHE["path"] = p
    _EXE_CACHE["done"] = True
    return p


def forget_browser_exe_cache():
    _EXE_CACHE["path"] = None
    _EXE_CACHE["done"] = False


def browser_profile():
    p = os.path.expandvars(BROWSER_PROFILE)
    os.makedirs(p, exist_ok=True)
    return p

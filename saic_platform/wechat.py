"""通过文件传输助手发送并点击目标文章；wxauto4 按需加载。"""

from contextlib import contextmanager
import ctypes
import sys
import time
from urllib.parse import urlsplit

from .api import PlatformError


_DPI_PER_MONITOR_AWARE_V2 = -4
_MOUSE_LEFT_DOWN = 0x0002
_MOUSE_LEFT_UP = 0x0004


@contextmanager
def _automation_context():
    if sys.platform != "win32":
        raise PlatformError("微信打开文章功能仅支持 Windows。")
    result = ctypes.windll.ole32.CoInitializeEx(None, 2)
    if result < 0:
        raise PlatformError("无法初始化微信自动化线程。")
    previous = _enable_physical_coordinates()
    try:
        yield
    finally:
        if previous:
            ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))
        ctypes.windll.ole32.CoUninitialize()


def _enable_physical_coordinates():
    """UIA 与截图使用物理像素；鼠标坐标也要切到同一坐标系。"""
    setter = getattr(ctypes.windll.user32, "SetThreadDpiAwarenessContext", None)
    if setter is None:
        return None
    setter.argtypes = [ctypes.c_void_p]
    setter.restype = ctypes.c_void_p
    try:
        return setter(ctypes.c_void_p(_DPI_PER_MONITOR_AWARE_V2))
    except (AttributeError, OSError, ValueError):
        return None


def _load_wechat():
    try:
        from wxauto4 import WeChat
    except ImportError:
        raise PlatformError("缺少 wxauto4 或其依赖，请在运行桌面程序的 Python 环境中执行：python -m pip install -r requirements-wechat.txt") from None
    return WeChat()


def _check_result(result, action):
    # 兼容无返回值的旧 API，以及 WxResponse / 字典结果。
    if result is not None and (not result or isinstance(result, dict) and result.get("status") == "失败"):
        raise PlatformError(f"{action}失败，请检查微信窗口和登录状态。")


def _main_window_handle(wx):
    root = getattr(getattr(wx, "SessionBox", None), "root", None)
    hwnd = getattr(root, "HWND", None)
    return hwnd if isinstance(hwnd, int) and hwnd else None


def _activate(hwnd):
    if not hwnd:
        return
    user32 = ctypes.windll.user32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)


def _ensure_foreground(hwnd, timeout=2):
    if not hwnd:
        return
    user32 = ctypes.windll.user32
    deadline = time.monotonic() + timeout
    while user32.GetForegroundWindow() != hwnd:
        _activate(hwnd)
        if time.monotonic() >= deadline:
            raise PlatformError("无法将微信主窗口置于前台，已停止点击；请手动切换到微信窗口后重试。")
        time.sleep(0.2)


def _chat_with(wx):
    last_error = None
    for _ in range(3):
        try:
            return wx.ChatWith(who="文件传输助手", exact=True)
        except Exception as error:  # wxauto4 偶尔在会话控件重建时查找失败。
            last_error = error
            time.sleep(0.4)
    raise PlatformError("无法切换到微信“文件传输助手”，请确认微信窗口可见且已登录。") from last_error


def _wait_for_link(wx, url, timeout):
    deadline = time.monotonic() + timeout
    while True:
        messages = wx.GetAllMessage()
        if messages:
            msg = messages[-1]
            if (msg.attr == "self" and msg.type == "text"
                    and msg.content.strip() == url):
                return msg
        if time.monotonic() >= deadline:
            raise PlatformError("文件传输助手最后一条记录不是当前任务链接，请检查后重试；程序未点击历史记录，也不会自动重发。")
        time.sleep(0.25)


def _message_box(msg, timeout=2):
    msg.roll_into_view()
    deadline = time.monotonic() + timeout
    while True:
        rect = msg.control.BoundingRectangle
        box = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
        if box[2] > box[0] and box[3] > box[1]:
            return box
        if time.monotonic() >= deadline:
            raise PlatformError("链接消息不在可见区域，无法点击；请将微信窗口恢复为正常大小后重试。")
        time.sleep(0.2)


def _bubble_click_point(box):
    """自己发送的消息靠右显示；按气泡填充色定位，避免行中心落在气泡外。"""
    from PIL import ImageGrab
    width = box[2] - box[0]
    height = box[3] - box[1]
    fallback = (box[2] - max(80, width // 5), box[1] + height // 2)
    try:
        image = ImageGrab.grab(bbox=box, all_screens=True).convert("RGB")
    except Exception:
        return fallback
    image_width, image_height = image.size
    y = image_height // 2
    background = image.getpixel((2, y))
    runs, start = [], None
    for x in range(image_width):
        pixel = image.getpixel((x, y))
        if sum(abs(a - b) for a, b in zip(pixel, background)) > 24:
            start = x if start is None else start
        elif start is not None:
            runs.append((start, x - 1))
            start = None
    if start is not None:
        runs.append((start, image_width - 1))
    if not runs:
        return fallback
    start, end = max(runs, key=lambda run: run[1] - run[0])
    if end - start < 8:
        return fallback
    return box[0] + (start + end) // 2, box[1] + y


def _click_link(msg):
    user32 = ctypes.windll.user32
    x, y = _bubble_click_point(_message_box(msg))
    user32.SetCursorPos(x, y)
    # 微信需要先更新悬停状态，紧接着点击会被当成普通选中。
    time.sleep(0.35)
    user32.mouse_event(_MOUSE_LEFT_DOWN, 0, 0, 0, 0)
    time.sleep(0.06)
    user32.mouse_event(_MOUSE_LEFT_UP, 0, 0, 0, 0)


def _article_window_handles():
    try:
        from wxauto4 import uia
        import psutil
    except ImportError:
        return set()
    handles = set()
    for window in uia.GetRootControl().GetChildren():
        try:
            if psutil.Process(window.ProcessId).name().lower() != "wechatappex.exe":
                continue
        except psutil.Error:
            continue
        rect = window.BoundingRectangle
        if window.IsOffscreen or rect.right <= rect.left or rect.bottom <= rect.top:
            continue
        handles.add(window.NativeWindowHandle)
    return handles


def _wait_for_article_window(before, timeout=8):
    if before:
        # 已有文章窗口时微信可能复用窗口或新建标签页，交给后续文章识别判断。
        return
    deadline = time.monotonic() + timeout
    while True:
        if _article_window_handles():
            return
        if time.monotonic() >= deadline:
            raise PlatformError(
                "已发送并点击文章链接，但微信没有打开文章窗口；请确认链接有效且微信可正常联网，"
                "或手动打开文章后使用“当前文章执行并截图”。"
            )
        time.sleep(0.3)


def open_article(url, *, factory=None, timeout=8, after_click=None):
    """发送一次，只打开聊天末尾的当前任务链接，不扫描历史记录。"""
    if not isinstance(url, str):
        raise ValueError("目标文章链接为空。")
    url = url.strip()
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "mp.weixin.qq.com"
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or any(char.isspace() for char in url)):
        raise ValueError("微信打开文章仅支持 https://mp.weixin.qq.com/ 公众号文章链接。")
    with _automation_context():
        try:
            wx = (factory or _load_wechat)()
            hwnd = _main_window_handle(wx)
            _activate(hwnd)
            _check_result(_chat_with(wx), "打开文件传输助手")
            _activate(hwnd)
            _check_result(wx.SendMsg(msg=url, who="文件传输助手", exact=True), "发送文章链接")
            msg = _wait_for_link(wx, url, timeout)
            before = _article_window_handles()
            _ensure_foreground(hwnd)
            _click_link(msg)
            _wait_for_article_window(before)
            if after_click:
                return after_click()
            return "已向文件传输助手发送链接并点击，请在微信中确认文章页面。"
        except (PlatformError, ValueError):
            raise
        except Exception as error:
            raise PlatformError(
                f"微信自动化失败（{type(error).__name__}）：未能操作微信主窗口。"
                "请确认微信已登录且主窗口已打开（不是仅保留托盘图标），客户端版本受 "
                "wxauto4 支持（约 4.1.8 及以下）；微信 4.1.13+ 请改用“当前文章执行并截图”。"
            ) from error

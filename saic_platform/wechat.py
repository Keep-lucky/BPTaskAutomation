"""通过文件传输助手发送并点击目标文章；wxauto4 按需加载。"""

from contextlib import contextmanager
import ctypes
import sys
import time
from urllib.parse import urlsplit

from .api import PlatformError


@contextmanager
def _automation_context():
    if sys.platform != "win32":
        raise PlatformError("微信打开文章功能仅支持 Windows。")
    result = ctypes.windll.ole32.CoInitializeEx(None, 2)
    if result < 0:
        raise PlatformError("无法初始化微信自动化线程。")
    try:
        yield
    finally:
        ctypes.windll.ole32.CoUninitialize()


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
            _check_result(wx.ChatWith(who="文件传输助手", exact=True), "打开文件传输助手")
            _check_result(wx.SendMsg(msg=url, who="文件传输助手", exact=True), "发送文章链接")
            deadline = time.monotonic() + timeout
            while True:
                messages = wx.GetAllMessage()
                if messages:
                    msg = messages[-1]
                    if (msg.attr == "self" and msg.type == "text"
                            and msg.content.strip() == url):
                        msg.roll_into_view()
                        _check_result(msg.click(), "点击文章链接")
                        if after_click:
                            return after_click()
                        return "已向文件传输助手发送链接并点击，请在微信中确认文章页面。"
                if time.monotonic() >= deadline:
                    raise PlatformError("文件传输助手最后一条记录不是当前任务链接，请检查后重试；程序未点击历史记录，也不会自动重发。")
                time.sleep(0.25)
        except (PlatformError, ValueError):
            raise
        except Exception:
            raise PlatformError("微信自动化失败，请确认微信已登录且 wxauto4 与客户端版本匹配；若已发送链接，可在文件传输助手中手动打开。") from None

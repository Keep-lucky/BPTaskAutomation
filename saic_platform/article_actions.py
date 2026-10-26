"""wxauto4 UIA 文章互动适配；仅操作可唯一确认的具名控件。"""

import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .api import PlatformError
from .wechat import open_article
from .workflow import IMAGES_DIR, platform_folder


def screenshot_path(detail, directory=None):
    root = Path(directory) if directory else IMAGES_DIR
    folder = platform_folder(detail or {})
    if folder:
        root = root / folder
    task_id = str((detail or {}).get("taskId") or "article")
    task_id = "".join(c for c in task_id if c.isalnum() or c in "-_")[:80] or "article"
    return root / f"{task_id}_{datetime.now():%Y%m%d_%H%M%S_%f}_{uuid4().hex[:8]}.png"


def _nodes(root):
    pending = [(root, 0)]
    count = 0
    while pending and count < 3000:
        node, depth = pending.pop()
        count += 1
        yield node
        if depth < 40:
            pending.extend((child, depth + 1) for child in reversed(node.GetChildren()))


class ArticleUI:
    """按文章标题和微信进程绑定窗口，不使用屏幕坐标。"""

    def __init__(self, title, timeout=10):
        from wxauto4 import uia
        import psutil
        self.uia = uia
        self.title = title.strip()
        self.timeout = timeout
        if not self.title:
            raise PlatformError("任务缺少文章标题，无法确认目标微信窗口。")
        def find_window():
            matches = []
            for window in uia.GetRootControl().GetChildren():
                try:
                    process = psutil.Process(window.ProcessId).name().lower()
                    if process in {"weixin.exe", "wechat.exe", "wechatappex.exe"} :
                        documents = [n for n in _nodes(window)
                                     if n.ControlTypeName == "DocumentControl"
                                     and n.Name.strip() == self.title and not n.IsOffscreen]
                        if len(documents) == 1:
                            matches.append((window, documents[0]))
                except psutil.Error:
                    continue
            if len(matches) == 1:
                return matches[0]
        self.window, self.document = self.wait(find_window, "未能唯一确认目标文章窗口，请关闭重复文章窗口，并确认微信已加载文章。")

    def wait(self, find, message):
        deadline = time.monotonic() + self.timeout
        while True:
            result = find()
            if result is not None:
                return result
            if time.monotonic() >= deadline:
                raise PlatformError(message)
            time.sleep(0.3)

    def find(self, names, root=None, types=None):
        types = types or {"ButtonControl", "MenuItemControl", "HyperlinkControl", "CheckBoxControl"}
        matches = [n for n in _nodes(root or self.window)
                   if n.Name in names and n.ControlTypeName in types and not n.IsOffscreen]
        if len(matches) > 1:
            raise PlatformError("发现多个同名文章操作控件，已停止，请在微信中手动操作。")
        return matches[0] if matches else None

    def click(self, names, root=None):
        control = self.wait(lambda: self.find(names, root), f"未找到可确认的控件：{' / '.join(names)}。当前微信版本可能未向 UIA 暴露此操作。")
        control.Click()

    def _reaction_button(self, kind):
        bars = [n for n in _nodes(self.document) if n.AutomationId == "js_article_bottom_bar"]
        if len(bars) != 1:
            return None
        matches = [n for n in _nodes(bars[0]) if n.ControlTypeName == "ButtonControl"
                   and not n.IsOffscreen and
                   ((kind == "like" and "sns_praise_btn" in n.ClassName.split())
                    or (kind == "watch" and n.AutomationId == "js_zaikan"))]
        if len(matches) > 1:
            raise PlatformError("文章底部互动按钮不唯一，已停止。")
        return matches[0] if matches else None

    def _react(self, kind, label, state_class):
        control = self.wait(lambda: self._reaction_button(kind), f"未找到文章底部{label}按钮，请确认文章已加载。")
        if state_class in control.ClassName.split():
            return f"文章已{label}，跳过。"
        self.window.SetActive()
        control.Click()
        def confirmed():
            current = self._reaction_button(kind)
            return True if current is not None and state_class in current.ClassName.split() else None
        self.wait(confirmed, f"已点击{label}，但未能确认选中状态，请在微信中检查，勿重复点击。")
        return f"已确认文章{label}。"

    def like(self):
        return self._react("like", "点赞", "praised")

    def watch(self):
        return self._react("watch", "在看", "love_btn_loved")

    def screenshot(self, path):
        from PIL import ImageGrab
        path = Path(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.window.SetActive()
            image = ImageGrab.grab(window=self.window.NativeWindowHandle)
            if image.width <= 1 or image.height <= 1:
                raise ValueError("截图尺寸无效")
            image.save(path, format="PNG")
        except Exception as error:
            raise PlatformError(f"文章操作已完成，但截图保存失败（{type(error).__name__}），请检查截图目录和微信文章窗口。") from None
        return str(path.resolve())

    def menu(self):
        self.click({"更多", "更多操作"})
        # 微信弹出菜单可能是独立窗口，只接受前台微信同进程菜单。
        foreground = self.uia.GetForegroundControl()
        if foreground.ProcessId != self.window.ProcessId:
            raise PlatformError("微信菜单焦点已切换到其他进程，已停止。")
        return foreground

    def prepare_moments(self, caption):
        self.click({"分享到朋友圈", "分享至朋友圈"}, self.menu())
        def find_dialog():
            foreground = self.uia.GetForegroundControl()
            if foreground.ProcessId != self.window.ProcessId:
                return None
            # 分享草稿必须包含当前文章标题及发布按钮，防止在错误窗口输入。
            if (any(self.title in n.Name for n in _nodes(foreground))
                    and self.find({"发表", "发布"}, foreground)):
                return foreground
        dialog = self.wait(find_dialog, "未能确认当前文章的朋友圈分享界面；请在微信中检查客户端是否支持文章分享。")
        if caption:
            edits = [n for n in _nodes(dialog) if n.ControlTypeName == "EditControl" and not n.IsOffscreen]
            if len(edits) != 1:
                raise PlatformError("朋友圈配文输入框不唯一，已保留分享界面，请手动填写配文。")
            pattern = edits[0].GetValuePattern()
            pattern.SetValue(caption)
            if pattern.Value != caption:
                raise PlatformError("朋友圈配文未能确认写入，请在微信中检查。")
        return "已准备朋友圈分享，请在微信中核对配文、可见范围并自行点击发表。"


def interact_article(url, title, *, like=False, watch=False, moments=False, caption="", detail=None, screenshot_directory=None, emit=lambda text: None, ui_factory=ArticleUI):
    if not any((like, watch, moments)):
        raise ValueError("请至少选择一项文章操作。")
    def after_click():
        ui = ui_factory(title)
        for enabled, action in ((like, ui.like), (watch, ui.watch)):
            if enabled:
                emit(action())
        path = ui.screenshot(screenshot_path(detail or {"platformCode": "WeChat"}, screenshot_directory))
        emit(f"文章截图已保存：{path}")
        if moments:
            emit(ui.prepare_moments(caption))
        return "所选文章操作已执行；如准备了朋友圈分享，请在微信中确认发布。"
    return open_article(url, after_click=after_click)

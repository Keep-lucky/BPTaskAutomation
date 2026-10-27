"""wxauto4 UIA 文章互动适配；仅操作可唯一确认的具名控件。"""

import ctypes
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

try:
    from _ctypes import COMError as _COMError
except ImportError:  # 非 Windows 平台不会进入 UIA 分支。
    class _COMError(Exception):
        pass

from .api import PlatformError
from .wechat import _enable_physical_coordinates, open_article
from .workflow import IMAGES_DIR, material_fields, platform_folder


# 页面导航/重绘时 UIA 控件会短暂失效，这些异常都可以等待后重试。
_CONTROL_ERRORS = (_COMError, LookupError)


# 材料名称 → 自动截图动作。只做明确匹配，不猜测「喜欢」等其他叫法。
FIELD_ACTIONS = (("转发", "moments"), ("朋友圈", "moments"), ("在看", "watch"), ("点赞", "like"))
ACTION_LABELS = {"like": "点赞", "watch": "在看", "moments": "朋友圈分享"}
CONTENT_KEYWORDS = ("评论", "回帖", "收藏", "赞同")


def _work_area(hwnd):
    """窗口所在显示器的工作区（物理像素）；取不到时返回 None。"""
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    user32 = ctypes.windll.user32
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    monitor = user32.MonitorFromWindow(wintypes.HWND(hwnd), 2)  # MONITOR_DEFAULTTONEAREST
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    work = info.rcWork
    return int(work.left), int(work.top), int(work.right), int(work.bottom)


def _clamp_to_work_area(hwnd, box):
    """最大化窗口的 UIA 矩形包含屏幕外的边框，裁剪后截图才没有黑边/任务栏。"""
    work = _work_area(hwnd)
    if work is None:
        return box
    left, top = max(box[0], work[0]), max(box[1], work[1])
    right, bottom = min(box[2], work[2]), min(box[3], work[3])
    if right - left < 200 or bottom - top < 200:
        return box
    return left, top, right, bottom


def screenshot_path(detail, directory=None, label=""):
    root = Path(directory) if directory else IMAGES_DIR
    folder = platform_folder(detail or {})
    if folder:
        root = root / folder
    task_id = str((detail or {}).get("taskId") or "article")
    task_id = "".join(c for c in task_id if c.isalnum() or c in "-_")[:80] or "article"
    label = "".join(c for c in str(label) if c.isalnum() or c in "-_")[:40]
    parts = [task_id] + ([label] if label else []) + [f"{datetime.now():%Y%m%d_%H%M%S_%f}", uuid4().hex[:8]]
    return root / ("_".join(parts) + ".png")


def screenshots_for_fields(detail, shots):
    """把动作截图映射到任务材料字段，返回 (材料名→路径, 提示)。

    只填充名称能明确对应的字段；评论等需要真实发布内容的材料不会用其他截图顶替。
    """
    try:
        fields = [name for name, _ in material_fields(detail)]
    except ValueError:
        return {}, ["任务材料配置未知，自动截图未映射到提交材料。"]
    selected, warnings = {}, []
    for name in fields:
        action = next((action for keyword, action in FIELD_ACTIONS if keyword in name), None)
        if action is None:
            if any(keyword in name for keyword in CONTENT_KEYWORDS):
                warnings.append(f"材料「{name}」需要真实互动内容，微信自动化未执行该操作，请手动补充截图。")
            else:
                warnings.append(f"材料「{name}」没有对应的自动截图动作，请手动选择。")
            continue
        if any(keyword in name for keyword in CONTENT_KEYWORDS):
            warnings.append(f"材料「{name}」还要求互动内容，自动截图只包含{ACTION_LABELS[action]}，请确认是否满足要求。")
        if action in shots:
            selected[name] = shots[action]
        else:
            warnings.append(f"材料「{name}」对应{ACTION_LABELS[action]}，但本次没有可用的该操作截图，材料仍为空。")
    return selected, warnings


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
    """按当前打开的公众号文章窗口绑定，不使用屏幕坐标。"""

    def __init__(self, title="", timeout=10):
        from wxauto4 import uia
        import psutil
        self.uia = uia
        self.title = (title or "").strip()
        self.timeout = timeout

        def find_window():
            matches, seen = [], []
            try:
                for window in uia.GetRootControl().GetChildren():
                    try:
                        process = psutil.Process(window.ProcessId).name().lower()
                    except psutil.Error:
                        continue
                    if process not in {"weixin.exe", "wechat.exe", "wechatappex.exe"}:
                        continue
                    documents, article_bar = [], False
                    for node in _nodes(window):
                        # 文章加载过程中会先出现标题为“微信公众平台”的空白页，等待真正标题。
                        if (node.ControlTypeName == "DocumentControl" and node.Name.strip()
                                and not node.IsOffscreen and node.Name.strip() != "微信公众平台"):
                            documents.append(node)
                        elif node.AutomationId == "js_article_bottom_bar":
                            article_bar = True
                    if not article_bar:
                        continue
                    if len(documents) > 1:
                        # 文章页里的 iframe 也可能暴露 DocumentControl，只保留含底部互动栏的文档。
                        documents = [d for d in documents
                                     if any(n.AutomationId == "js_article_bottom_bar" for n in _nodes(d))]
                    for document in documents:
                        name = document.Name.strip()
                        seen.append(name)
                        if not self.title or name == self.title:
                            matches.append((window, document))
            except _CONTROL_ERRORS:
                # 页面导航时控件会短暂失效，等下一轮重试。
                return None
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise PlatformError("检测到多篇已打开的公众号文章，请关闭其他文章，只保留目标文章后重试。")
            if self.title and seen:
                raise PlatformError("已打开的公众号文章与任务标题不一致，请确认打开的是目标文章。")
            return None

        self.window, self.document = self.wait(
            find_window,
            "未找到已加载完成的公众号文章窗口；请确认文章已在微信中打开、内容可正常显示并保持窗口可见。",
        )
        if not self.title:
            self.title = self.document.Name.strip()

    def wait(self, find, message, timeout=None):
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            result = find()
            if result is not None:
                return result
            if time.monotonic() >= deadline:
                raise PlatformError(message)
            time.sleep(0.3)

    def find(self, names, root=None, types=None):
        types = types or {"ButtonControl", "MenuItemControl", "HyperlinkControl", "CheckBoxControl"}
        try:
            matches = [n for n in _nodes(root or self.window)
                       if n.Name in names and n.ControlTypeName in types and not n.IsOffscreen]
        except _CONTROL_ERRORS:
            return None
        if len(matches) > 1:
            raise PlatformError("发现多个同名文章操作控件，已停止，请在微信中手动操作。")
        return matches[0] if matches else None

    def click(self, names, root=None, timeout=None):
        control = self.wait(lambda: self.find(names, root), f"未找到可确认的控件：{' / '.join(names)}。当前微信版本可能未向 UIA 暴露此操作。", timeout)
        control.Click()

    def _reaction_button(self, kind):
        try:
            bars = [n for n in _nodes(self.document) if n.AutomationId == "js_article_bottom_bar"]
            if len(bars) != 1:
                return None
            matches = [n for n in _nodes(bars[0]) if n.ControlTypeName == "ButtonControl"
                       and not n.IsOffscreen and
                       ((kind == "like" and "sns_praise_btn" in n.ClassName.split())
                        or (kind == "watch" and n.AutomationId == "js_zaikan"))]
        except _CONTROL_ERRORS:
            # 页面仍在渲染时控件会短暂失效，由 wait() 重试。
            return None
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

    def _stable_window_box(self, timeout=3):
        """等待窗口展开/缩放动画结束，避免截到半途尺寸。"""
        deadline = time.monotonic() + timeout
        previous, stable = None, 0
        while True:
            try:
                rect = self.window.BoundingRectangle
            except _CONTROL_ERRORS:
                rect = None
            if rect is not None:
                current = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
                if current == previous and current[2] > current[0] and current[3] > current[1]:
                    stable += 1
                    if stable >= 3:
                        return current
                else:
                    stable = 0
                previous = current
            if time.monotonic() >= deadline:
                if previous is None:
                    raise PlatformError("无法读取文章窗口位置，已取消截图；请手动点击文章窗口后重试。")
                return previous
            time.sleep(0.2)

    def screenshot(self, path, control=None):
        """截取文章窗口；传入控件时按控件区域截图（用于独立的分享对话框）。"""
        from PIL import ImageGrab
        path = Path(path)
        previous = _enable_physical_coordinates()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if control is not None:
                rect = control.BoundingRectangle
                try:
                    box = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
                except AttributeError:
                    box = tuple(int(value) for value in rect)
                if box[2] <= box[0] or box[3] <= box[1]:
                    raise ValueError("截图区域无效")
                image = ImageGrab.grab(bbox=box, all_screens=True)
            else:
                # 微信 4.1.15 的窗口对 PrintWindow 返回空白，改为先置前再按屏幕区域截图。
                hwnd = self.window.NativeWindowHandle
                user32 = ctypes.windll.user32
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                # 文章窗口可能以较小尺寸打开，最大化后才能同时截到正文和底部互动栏。
                if not user32.IsZoomed(hwnd):
                    user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
                box = None
                for _ in range(2):
                    self.window.SetActive()
                    box = self._stable_window_box()
                    if user32.GetForegroundWindow() == hwnd:
                        break
                if user32.GetForegroundWindow() != hwnd:
                    raise PlatformError("微信文章窗口未能置于前台，已取消截图；请手动点击文章窗口后重试。")
                box = _clamp_to_work_area(hwnd, box)
                time.sleep(0.3)
                image = ImageGrab.grab(bbox=box, all_screens=True)
            if image.width <= 1 or image.height <= 1:
                raise ValueError("截图尺寸无效")
            image.save(path, format="PNG")
        except PlatformError:
            raise
        except Exception as error:
            raise PlatformError(f"文章操作已完成，但截图保存失败（{type(error).__name__}），请检查截图目录和目标窗口。") from None
        finally:
            if previous:
                ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))
        return str(path.resolve())

    def _share_button(self):
        # 4.x 文章底栏是“分享”（sns_share_btn）；旧版可能在“更多”菜单里。
        try:
            matches = [n for n in _nodes(self.document) if n.ControlTypeName == "ButtonControl"
                       and not n.IsOffscreen and "sns_share_btn" in n.ClassName.split()]
        except _CONTROL_ERRORS:
            return None
        if len(matches) > 1:
            raise PlatformError("文章分享按钮不唯一，已停止。")
        return matches[0] if matches else self.find({"更多", "更多操作"}, self.document)

    def menu(self):
        control = self._share_button()
        if control is None:
            raise PlatformError("当前微信版本未向 UIA 暴露文章分享入口，无法自动准备朋友圈分享；请在微信中手动分享后手动选择截图。")
        self.window.SetActive()
        control.Click()
        # 微信弹出菜单可能是独立窗口，只接受前台微信同进程菜单。
        foreground = self.uia.GetForegroundControl()
        if foreground.ProcessId != self.window.ProcessId:
            raise PlatformError("微信分享菜单未在当前进程中暴露（当前版本可能不支持自动分享），已停止。")
        return foreground

    def prepare_moments(self, caption):
        self.click({"分享到朋友圈", "分享至朋友圈"}, self.menu(), timeout=5)
        def find_dialog():
            foreground = self.uia.GetForegroundControl()
            if foreground.ProcessId != self.window.ProcessId:
                return None
            # 分享草稿必须包含当前文章标题及发布按钮，防止在错误窗口输入。
            if (any(self.title in n.Name for n in _nodes(foreground))
                    and self.find({"发表", "发布"}, foreground)):
                return foreground
        dialog = self.wait(find_dialog, "未能确认当前文章的朋友圈分享界面；当前版本可能不支持自动分享，请在微信中手动完成后重新选择截图。", timeout=5)
        if caption:
            edits = [n for n in _nodes(dialog) if n.ControlTypeName == "EditControl" and not n.IsOffscreen]
            if len(edits) != 1:
                raise PlatformError("朋友圈配文输入框不唯一，已保留分享界面，请手动填写配文。")
            pattern = edits[0].GetValuePattern()
            pattern.SetValue(caption)
            if pattern.Value != caption:
                raise PlatformError("朋友圈配文未能确认写入，请在微信中检查。")
        # 分享对话框通常独立于主窗口，截图时按该控件区域裁剪。
        self.moments_dialog = dialog
        return "已准备朋友圈分享，请在微信中核对配文、可见范围并自行点击发表。"


def interact_article(url, title="", *, like=False, watch=False, moments=False, caption="", detail=None, screenshot_directory=None, emit=lambda text: None, ui_factory=ArticleUI, reuse_open_article=False):
    if not any((like, watch, moments)):
        raise ValueError("请至少选择一项文章操作。")
    detail = detail or {"platformCode": "WeChat"}

    def after_click():
        ui = ui_factory(title)
        shots, warnings = {}, []
        if like:
            emit(ui.like())
            shots["like"] = ui.screenshot(screenshot_path(detail, screenshot_directory, "like"))
            emit(f"点赞后文章截图已保存：{shots['like']}")
        if watch:
            emit(ui.watch())
            shots["watch"] = ui.screenshot(screenshot_path(detail, screenshot_directory, "watch"))
            emit(f"在看后文章截图已保存：{shots['watch']}")
        if moments:
            # 4.1.15 等版本可能不暴露分享面板；失败时保留已完成的点赞/在看截图。
            try:
                emit(ui.prepare_moments(caption))
                dialog = getattr(ui, "moments_dialog", None)
                if dialog is None:
                    raise PlatformError("朋友圈分享界面未返回可截图控件，请在微信中手动截图。")
                shots["moments"] = ui.screenshot(screenshot_path(detail, screenshot_directory, "moments"), dialog)
                emit(f"朋友圈发布界面截图已保存：{shots['moments']}")
            except PlatformError as error:
                warning = f"朋友圈分享未完成：{error}"
                warnings.append(warning)
                emit(warning)
        materials, mapped_warnings = screenshots_for_fields(detail, shots)
        warnings.extend(mapped_warnings)
        for warning in mapped_warnings:
            emit(warning)
        return {
            "message": "所选文章操作已执行，截图已保存并尝试填入提交材料。",
            "screenshots": shots,
            "materials": materials,
            "warnings": warnings,
        }
    if reuse_open_article:
        # 微信 4.1.13+ 主窗口不暴露 UIA，无法自动打开链接；
        # 直接操作用户已打开并核对过的文章窗口。
        return after_click()
    return open_article(url, after_click=after_click)

import unittest
from unittest.mock import Mock, call, patch

from saic_platform.article_actions import (
    ArticleUI, _COMError, _clamp_to_work_area, interact_article, screenshot_path,
)
from saic_platform.workflow import IMAGES_DIR
from saic_platform.api import PlatformError


def detail(names=("点赞", "转发"), task_id="123"):
    return {"taskId": task_id, "platformCode": "WeChat", "taskType": 3,
            "taskRewardDTO": {"operationTarget": "1",
                              "taskRewardReferenceDTOList": [{"name": name} for name in names]}}


class ArticleActionTests(unittest.TestCase):
    def test_selected_actions_run_in_order_and_report_partial_progress(self):
        ui = Mock()
        ui.like.return_value = "点赞成功"
        ui.watch.side_effect = PlatformError("在看失败")
        emit = Mock()
        with patch("saic_platform.article_actions.open_article", side_effect=lambda url, after_click: after_click()):
            with self.assertRaisesRegex(PlatformError, "在看失败"):
                interact_article("url", "标题", like=True, watch=True, moments=True,
                                 emit=emit, ui_factory=lambda title: ui)
        self.assertEqual(emit.call_args_list[0], call("点赞成功"))
        ui.screenshot.assert_called_once()
        ui.prepare_moments.assert_not_called()

    def test_only_prepares_requested_moments_with_caption(self):
        ui = Mock()
        with patch("saic_platform.article_actions.open_article", side_effect=lambda url, after_click: after_click()):
            interact_article("url", "标题", moments=True, caption="配文",
                             detail=detail(), ui_factory=lambda title: ui)
        ui.like.assert_not_called()
        ui.watch.assert_not_called()
        ui.prepare_moments.assert_called_once_with("配文")
        ui.screenshot.assert_called_once()
        self.assertIs(ui.screenshot.call_args.args[1], ui.moments_dialog)

    def test_screenshot_paths_are_per_platform_unique_and_safe(self):
        detail = {"taskId": "../123", "platformCode": "WeChat"}
        path = screenshot_path(detail)
        self.assertEqual(path.parent, IMAGES_DIR / "wechat")
        self.assertTrue(path.name.startswith("123_"))
        self.assertEqual(path.suffix, ".png")
        self.assertNotEqual(path, screenshot_path(detail))
        self.assertIn("like", screenshot_path(detail, label="like").name)
        self.assertEqual(screenshot_path({"platformCode": "Tiktok"}).parent, IMAGES_DIR / "tiktok")

    def test_captures_article_after_reactions_before_share_dialog(self):
        ui = Mock()
        with patch("saic_platform.article_actions.open_article", side_effect=lambda url, after_click: after_click()):
            interact_article("url", "标题", like=True, watch=True, moments=True,
                             detail=detail(), ui_factory=lambda title: ui)
        self.assertEqual([call[0] for call in ui.method_calls],
                         ["like", "screenshot", "watch", "screenshot", "prepare_moments", "screenshot"])

    def test_screenshots_fill_matching_material_fields(self):
        ui = Mock()
        ui.screenshot.side_effect = ["C:/shots/like.png", "C:/shots/moments.png"]
        with patch("saic_platform.article_actions.open_article", side_effect=lambda url, after_click: after_click()):
            result = interact_article("url", "标题", like=True, moments=True,
                                      detail=detail(), ui_factory=lambda title: ui)
        self.assertEqual(result["materials"], {"点赞": "C:/shots/like.png", "转发": "C:/shots/moments.png"})
        self.assertEqual(result["screenshots"], {"like": "C:/shots/like.png", "moments": "C:/shots/moments.png"})
        self.assertEqual(result["warnings"], [])

    def test_unmapped_comment_field_is_not_filled_and_warns(self):
        ui = Mock()
        ui.screenshot.return_value = "C:/shots/like.png"
        with patch("saic_platform.article_actions.open_article", side_effect=lambda url, after_click: after_click()):
            result = interact_article("url", "标题", like=True,
                                      detail=detail(("点赞", "评论")), ui_factory=lambda title: ui)
        self.assertEqual(result["materials"], {"点赞": "C:/shots/like.png"})
        self.assertTrue(any("评论" in warning for warning in result["warnings"]))

    def test_moments_failure_keeps_completed_screenshots(self):
        ui = Mock()
        ui.screenshot.return_value = "C:/shots/like.png"
        ui.prepare_moments.side_effect = PlatformError("当前版本不支持分享")
        with patch("saic_platform.article_actions.open_article", side_effect=lambda url, after_click: after_click()):
            result = interact_article("url", "标题", like=True, moments=True,
                                      detail=detail(("点赞", "转发")), ui_factory=lambda title: ui)
        self.assertEqual(result["materials"], {"点赞": "C:/shots/like.png"})
        self.assertTrue(any("朋友圈分享未完成" in warning for warning in result["warnings"]))
        self.assertTrue(any("转发" in warning for warning in result["warnings"]))

    def test_missing_selected_action_leaves_field_empty_with_warning(self):
        ui = Mock()
        ui.screenshot.return_value = "C:/shots/like.png"
        with patch("saic_platform.article_actions.open_article", side_effect=lambda url, after_click: after_click()):
            result = interact_article("url", "标题", like=True,
                                      detail=detail(("点赞", "转发")), ui_factory=lambda title: ui)
        self.assertEqual(set(result["materials"]), {"点赞"})
        self.assertTrue(any("转发" in warning for warning in result["warnings"]))

    def test_requires_selection_before_opening_article(self):
        with patch("saic_platform.article_actions.open_article") as opening:
            with self.assertRaises(ValueError):
                interact_article("url", "标题")
            opening.assert_not_called()

    def test_reuse_open_article_skips_wechat_main_window(self):
        ui = Mock()
        ui.screenshot.return_value = "C:/shots/like.png"
        with patch("saic_platform.article_actions.open_article") as opening:
            result = interact_article("", like=True, detail=detail(("点赞",)),
                                      reuse_open_article=True, ui_factory=lambda title: ui)
        opening.assert_not_called()
        self.assertEqual(result["materials"], {"点赞": "C:/shots/like.png"})

    def test_reactions_skip_selected_and_verify_new_state(self):
        for kind, label, state in (("like", "点赞", "praised"), ("watch", "在看", "love_btn_loved")):
            with self.subTest(kind=kind):
                ui = ArticleUI.__new__(ArticleUI)
                ui.timeout = 0
                ui.window = Mock()
                control = Mock(ClassName="sns_opr_btn " + state)
                ui._reaction_button = Mock(return_value=control)
                self.assertIn("跳过", ui._react(kind, label, state))
                control.Click.assert_not_called()
                control.ClassName = "sns_opr_btn"
                control.Click.side_effect = lambda: setattr(control, "ClassName", "sns_opr_btn " + state)
                self.assertIn("已确认", ui._react(kind, label, state))
                control.Click.assert_called_once()

    def test_reaction_failure_does_not_click_twice(self):
        ui = ArticleUI.__new__(ArticleUI)
        ui.timeout = 0
        ui.window = Mock()
        control = Mock(ClassName="sns_opr_btn")
        ui._reaction_button = Mock(return_value=control)
        with self.assertRaisesRegex(PlatformError, "未能确认"):
            ui.like()
        control.Click.assert_called_once()


class ScreenshotClampTests(unittest.TestCase):
    def test_clamps_offscreen_maximized_borders_to_work_area(self):
        with patch("saic_platform.article_actions._work_area", return_value=(0, 0, 1920, 1020)):
            self.assertEqual(_clamp_to_work_area(1, (-11, -11, 1931, 1031)), (0, 0, 1920, 1020))

    def test_keeps_box_when_work_area_is_unknown(self):
        box = (30, 15, 1290, 685)
        with patch("saic_platform.article_actions._work_area", return_value=None):
            self.assertEqual(_clamp_to_work_area(1, box), box)

    def test_keeps_box_when_clamping_leaves_too_little(self):
        box = (30, 15, 1290, 685)
        with patch("saic_platform.article_actions._work_area", return_value=(0, 0, 50, 50)):
            self.assertEqual(_clamp_to_work_area(1, box), box)


class ScreenshotWindowTests(unittest.TestCase):
    def ui(self):
        ui = ArticleUI.__new__(ArticleUI)
        ui.window = Mock(NativeWindowHandle=123)
        ui.window.BoundingRectangle = Mock(left=-11, top=-11, right=1931, bottom=1031)
        return ui

    def capture(self, ui, zoomed=False, foreground=123):
        image = Mock(width=1890, height=1005)
        with patch("saic_platform.article_actions._enable_physical_coordinates", return_value=-1), \
                patch("saic_platform.article_actions._work_area", return_value=(0, 0, 1920, 1020)), \
                patch("saic_platform.article_actions.time.sleep"), \
                patch("saic_platform.article_actions.ctypes.windll.user32") as user32, \
                patch("PIL.ImageGrab.grab", return_value=image) as grab:
            user32.IsIconic.return_value = False
            user32.IsZoomed.return_value = zoomed
            user32.GetForegroundWindow.return_value = foreground
            try:
                ui.screenshot("shot.png")
            except Exception as error:
                return error, user32, grab
        return None, user32, grab

    def test_maximizes_and_crops_to_work_area(self):
        error, user32, grab = self.capture(self.ui())
        self.assertIsNone(error)
        user32.ShowWindow.assert_any_call(123, 3)
        grab.assert_called_once_with(bbox=(0, 0, 1920, 1020), all_screens=True)

    def test_does_not_remaximize_an_already_maximized_window(self):
        error, user32, grab = self.capture(self.ui(), zoomed=True)
        self.assertIsNone(error)
        self.assertNotIn(call(123, 3), user32.ShowWindow.call_args_list)
        grab.assert_called_once_with(bbox=(0, 0, 1920, 1020), all_screens=True)

    def test_refuses_to_capture_when_article_cannot_be_brought_forward(self):
        error, user32, grab = self.capture(self.ui(), foreground=999)
        self.assertIsInstance(error, PlatformError)
        self.assertIn("未能置于前台", str(error))
        grab.assert_not_called()


class TransientControlErrorTests(unittest.TestCase):
    def test_find_returns_none_when_controls_invalidate(self):
        ui = ArticleUI.__new__(ArticleUI)
        ui.window = Mock()
        error = _COMError(-2147220991, "gone", None)
        with patch("saic_platform.article_actions._nodes", side_effect=error):
            self.assertIsNone(ui.find({"点赞"}))


class FakeNode:
    def __init__(self, name="", control="PaneControl", automation_id="", children=(), offscreen=False):
        self.Name = name
        self.ControlTypeName = control
        self.AutomationId = automation_id
        self.IsOffscreen = offscreen
        self.ProcessId = 1
        self._children = list(children)

    def GetChildren(self):
        return list(self._children)


def article_window(*titles):
    documents = [FakeNode(title, "DocumentControl",
                          children=[FakeNode(automation_id="js_article_bottom_bar")])
                 for title in titles]
    page = FakeNode(children=documents)
    return FakeNode(name="微信", children=[page])


class ArticleDiscoveryTests(unittest.TestCase):
    def open(self, root):
        from unittest.mock import patch as patcher
        process = Mock()
        process.name.return_value = "wechatappex.exe"
        return patcher("wxauto4.uia.GetRootControl", return_value=root), patcher("psutil.Process", return_value=process)

    def test_discovers_single_open_article_without_title(self):
        root = FakeNode(children=[article_window("目标文章")])
        root_patch, process_patch = self.open(root)
        with root_patch, process_patch:
            ui = ArticleUI()
        self.assertEqual(ui.title, "目标文章")
        self.assertEqual(ui.document.Name, "目标文章")

    def test_rejects_mismatched_title(self):
        root = FakeNode(children=[article_window("另一篇文章")])
        root_patch, process_patch = self.open(root)
        with root_patch, process_patch:
            with self.assertRaisesRegex(PlatformError, "不一致"):
                ArticleUI("任务标题", timeout=0)

    def test_rejects_multiple_open_articles(self):
        root = FakeNode(children=[article_window("文章一", "文章二")])
        root_patch, process_patch = self.open(root)
        with root_patch, process_patch:
            with self.assertRaisesRegex(PlatformError, "多篇"):
                ArticleUI(timeout=0)

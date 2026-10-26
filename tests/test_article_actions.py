import unittest
from unittest.mock import Mock, patch

from saic_platform.article_actions import ArticleUI, interact_article, screenshot_path
from saic_platform.workflow import IMAGES_DIR
from saic_platform.api import PlatformError


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
        emit.assert_called_once_with("点赞成功")
        ui.prepare_moments.assert_not_called()
        ui.screenshot.assert_not_called()

    def test_only_prepares_requested_moments_with_caption(self):
        ui = Mock()
        with patch("saic_platform.article_actions.open_article", side_effect=lambda url, after_click: after_click()):
            interact_article("url", "标题", moments=True, caption="配文", ui_factory=lambda title: ui)
        ui.like.assert_not_called()
        ui.watch.assert_not_called()
        ui.prepare_moments.assert_called_once_with("配文")
        ui.screenshot.assert_called_once()

    def test_screenshot_paths_are_per_platform_unique_and_safe(self):
        detail = {"taskId": "../123", "platformCode": "WeChat"}
        path = screenshot_path(detail)
        self.assertEqual(path.parent, IMAGES_DIR / "wechat")
        self.assertTrue(path.name.startswith("123_"))
        self.assertEqual(path.suffix, ".png")
        self.assertNotEqual(path, screenshot_path(detail))
        self.assertEqual(screenshot_path({"platformCode": "Tiktok"}).parent, IMAGES_DIR / "tiktok")

    def test_captures_article_after_reactions_before_share_dialog(self):
        ui = Mock()
        with patch("saic_platform.article_actions.open_article", side_effect=lambda url, after_click: after_click()):
            interact_article("url", "标题", like=True, watch=True, moments=True, ui_factory=lambda title: ui)
        self.assertEqual([call[0] for call in ui.method_calls], ["like", "watch", "screenshot", "prepare_moments"])

    def test_requires_selection_before_opening_article(self):
        with patch("saic_platform.article_actions.open_article") as opening:
            with self.assertRaises(ValueError):
                interact_article("url", "标题")
            opening.assert_not_called()

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

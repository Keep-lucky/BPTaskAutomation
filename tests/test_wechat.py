from contextlib import nullcontext
import importlib.util
import unittest
from unittest.mock import Mock, patch
from types import ModuleType

from saic_platform.api import PlatformError
from saic_platform.wechat import _bubble_click_point, open_article, _load_wechat


class WechatTests(unittest.TestCase):
    url = "https://mp.weixin.qq.com/s/example"

    def test_loads_wxauto4(self):
        module = ModuleType("wxauto4")
        module.WeChat = Mock()
        with patch.dict("sys.modules", {"wxauto4": module, "wxauto": None}):
            self.assertIs(_load_wechat(), module.WeChat.return_value)
        module.WeChat.assert_called_once_with()

    def test_missing_wxauto4_has_install_instructions(self):
        with patch.dict("sys.modules", {"wxauto4": None}):
            with self.assertRaisesRegex(PlatformError, "requirements-wechat.txt"):
                _load_wechat()

    def message(self, identity, content=None, attr="self"):
        return Mock(id=identity, content=content or self.url, attr=attr, type="text")

    @patch("saic_platform.wechat._automation_context", side_effect=nullcontext)
    @patch("saic_platform.wechat._article_window_handles", return_value=set())
    @patch("saic_platform.wechat._wait_for_article_window")
    @patch("saic_platform.wechat._click_link")
    def test_send_once_and_click_only_new_matching_self_message(
            self, click_link, wait_window, article_handles, _):
        wx = Mock()
        old = self.message("old")
        new = self.message("new")
        other = self.message("other", attr="friend")
        wx.GetAllMessage.return_value = [old, other, new]
        open_article(self.url, factory=lambda: wx)
        wx.ChatWith.assert_called_once_with(who="文件传输助手", exact=True)
        wx.SendMsg.assert_called_once_with(msg=self.url, who="文件传输助手", exact=True)
        click_link.assert_called_once_with(new)
        wait_window.assert_called_once_with(set())

    @patch("saic_platform.wechat._automation_context", side_effect=nullcontext)
    @patch("saic_platform.wechat._article_window_handles", return_value=set())
    @patch("saic_platform.wechat._wait_for_article_window")
    @patch("saic_platform.wechat._click_link")
    def test_timeout_does_not_resend_or_click_old_message(
            self, click_link, wait_window, article_handles, _):
        wx = Mock()
        old = self.message("old", content="其他聊天记录")
        wx.GetAllMessage.return_value = [old]
        with self.assertRaisesRegex(PlatformError, "最后一条"):
            open_article(self.url, factory=lambda: wx, timeout=0)
        wx.SendMsg.assert_called_once()
        click_link.assert_not_called()
        wait_window.assert_not_called()

    @patch("saic_platform.wechat._automation_context", side_effect=nullcontext)
    @patch("saic_platform.wechat._article_window_handles", return_value=set())
    @patch("saic_platform.wechat._wait_for_article_window")
    @patch("saic_platform.wechat._click_link")
    def test_send_failure_stops_before_click(
            self, click_link, wait_window, article_handles, _):
        wx = Mock()
        wx.GetAllMessage.return_value = []
        wx.SendMsg.return_value = False
        with self.assertRaisesRegex(PlatformError, "发送文章链接失败"):
            open_article(self.url, factory=lambda: wx)
        wx.GetAllMessage.assert_not_called()
        click_link.assert_not_called()

    @patch("saic_platform.wechat._automation_context", side_effect=nullcontext)
    @patch("saic_platform.wechat._article_window_handles", return_value=set())
    @patch("saic_platform.wechat._wait_for_article_window")
    @patch("saic_platform.wechat._click_link")
    def test_never_scans_older_matching_url_when_last_record_is_other(
            self, click_link, wait_window, article_handles, _):
        wx = Mock()
        old = self.message("old")
        last = self.message("last", content="https://mp.weixin.qq.com/s/other")
        wx.GetAllMessage.return_value = [old, last]
        with self.assertRaisesRegex(PlatformError, "最后一条"):
            open_article(self.url, factory=lambda: wx, timeout=0)
        click_link.assert_not_called()

    def test_invalid_urls_never_initialize_wechat(self):
        factory = Mock()
        for url in ("", "https://example.com", "https://mp.weixin.qq.com.evil.com/s/a", "javascript:alert(1)"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                open_article(url, factory=factory)
        factory.assert_not_called()


class BubbleClickPointTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("PIL"), "需要 Pillow")
    def test_uses_bubble_area_instead_of_row_center(self):
        from PIL import Image
        image = Image.new("RGB", (400, 100), (250, 250, 250))
        for x in range(240, 360):
            for y in range(10, 90):
                image.putpixel((x, y), (157, 242, 159))
        with patch("PIL.ImageGrab.grab", return_value=image):
            point = _bubble_click_point((0, 0, 400, 100))
        self.assertEqual(point, (299, 50))

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "需要 Pillow")
    def test_falls_back_to_right_side_when_capture_fails(self):
        with patch("PIL.ImageGrab.grab", side_effect=OSError("no screen")):
            point = _bubble_click_point((0, 0, 400, 100))
        self.assertEqual(point, (320, 50))

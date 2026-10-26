from contextlib import nullcontext
import unittest
from unittest.mock import Mock, patch
from types import ModuleType

from saic_platform.api import PlatformError
from saic_platform.wechat import open_article, _load_wechat


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
    def test_send_once_and_click_only_new_matching_self_message(self, _):
        wx = Mock()
        old = self.message("old")
        new = self.message("new")
        other = self.message("other", attr="friend")
        wx.GetAllMessage.return_value = [old, other, new]
        open_article(self.url, factory=lambda: wx)
        wx.ChatWith.assert_called_once_with(who="文件传输助手", exact=True)
        wx.SendMsg.assert_called_once_with(msg=self.url, who="文件传输助手", exact=True)
        new.click.assert_called_once()
        old.click.assert_not_called()
        other.click.assert_not_called()

    @patch("saic_platform.wechat._automation_context", side_effect=nullcontext)
    def test_timeout_does_not_resend_or_click_old_message(self, _):
        wx = Mock()
        old = self.message("old", content="其他聊天记录")
        wx.GetAllMessage.return_value = [old]
        with self.assertRaisesRegex(PlatformError, "最后一条"):
            open_article(self.url, factory=lambda: wx, timeout=0)
        wx.SendMsg.assert_called_once()
        old.click.assert_not_called()

    @patch("saic_platform.wechat._automation_context", side_effect=nullcontext)
    def test_send_failure_stops_before_click(self, _):
        wx = Mock()
        wx.GetAllMessage.return_value = []
        wx.SendMsg.return_value = False
        with self.assertRaisesRegex(PlatformError, "发送文章链接失败"):
            open_article(self.url, factory=lambda: wx)
        wx.GetAllMessage.assert_not_called()

    @patch("saic_platform.wechat._automation_context", side_effect=nullcontext)
    def test_never_scans_older_matching_url_when_last_record_is_other(self, _):
        wx = Mock()
        old = self.message("old")
        last = self.message("last", content="https://mp.weixin.qq.com/s/other")
        wx.GetAllMessage.return_value = [old, last]
        with self.assertRaisesRegex(PlatformError, "最后一条"):
            open_article(self.url, factory=lambda: wx, timeout=0)
        old.click.assert_not_called()
        last.click.assert_not_called()

    def test_invalid_urls_never_initialize_wechat(self):
        factory = Mock()
        for url in ("", "https://example.com", "https://mp.weixin.qq.com.evil.com/s/a", "javascript:alert(1)"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                open_article(url, factory=factory)
        factory.assert_not_called()

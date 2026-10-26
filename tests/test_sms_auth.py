import unittest
from unittest.mock import Mock, patch

import requests

from saic_platform.auth import SmsAuth
from saic_platform.api import BASE_URL, PlatformError


class SmsAuthTests(unittest.TestCase):
    def setUp(self):
        self.auth = SmsAuth()
        self.addCleanup(self.auth.close)

    def response(self, data, code=0):
        response = Mock(status_code=200)
        response.json.return_value = {"errcode": code, "data": data}
        return response

    def test_send_contract_and_no_authorize(self):
        with patch.object(self.auth.session, "post", return_value=self.response("ok")) as post:
            self.auth.send_code("13800000000")
        post.assert_called_once_with(BASE_URL + "/api/front/system-auths/send-sms-code",
                                     json={"phone": "13800000000", "isUser": 1}, timeout=20, allow_redirects=False)
        self.assertNotIn("authorize", self.auth.session.headers)

    def test_login_validates_received_token(self):
        with patch.object(self.auth.session, "post", return_value=self.response({"token": "example"})) as post, \
                patch("saic_platform.auth.SaicClient") as client:
            result = self.auth.login("13800000000", "123456")
        self.assertIs(result, client.return_value)
        client.assert_called_once_with("example", timeout=20)
        client.return_value.validate_login.assert_called_once()
        self.assertEqual(post.call_args.kwargs["json"], {"phone": "13800000000", "code": "123456",
                         "wxCode": "", "openId": "", "nickname": "", "avatar": ""})

    def test_invalid_inputs_never_send(self):
        with patch.object(self.auth.session, "post") as post:
            for phone, code in [("123", "123456"), ("13800000000", ""), ("13800000000", "abcdef")]:
                with self.assertRaises(ValueError):
                    self.auth.login(phone, code)
            post.assert_not_called()

    def test_bad_response_and_timeout(self):
        for response in [self.response({}), self.response({"token": "x"}, False),
                         self.response("rejected", -1), Mock(status_code=302)]:
            with patch.object(self.auth.session, "post", return_value=response):
                with self.assertRaises(PlatformError):
                    self.auth.login("13800000000", "123456")
        with patch.object(self.auth.session, "post", side_effect=requests.Timeout):
            with self.assertRaises(PlatformError):
                self.auth.send_code("13800000000")

    def test_verification_failure_closes_client(self):
        with patch.object(self.auth.session, "post", return_value=self.response({"token": "example"})), \
                patch("saic_platform.auth.SaicClient") as client:
            client.return_value.validate_login.side_effect = PlatformError("invalid")
            with self.assertRaises(PlatformError):
                self.auth.login("13800000000", "123456")
            client.return_value.close.assert_called_once()

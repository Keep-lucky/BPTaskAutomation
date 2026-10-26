"""无需已有 Token 的手机号短信认证。"""

import re
import requests

from .api import BASE_URL, PlatformError, SaicClient


def validate_phone(phone):
    if not isinstance(phone, str) or not re.fullmatch(r"1[3-9][0-9]{9}", phone):
        raise ValueError("请输入正确的 11 位手机号。")
    return phone


class SmsAuth:
    def __init__(self, timeout=20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "Referer": BASE_URL + "/"})

    def _post(self, endpoint, body):
        try:
            response = self.session.post(BASE_URL + "/api/front/system-auths/" + endpoint,
                                         json=body, timeout=self.timeout, allow_redirects=False)
        except requests.Timeout:
            raise PlatformError("认证请求超时，请稍后手动重试。") from None
        except requests.RequestException:
            raise PlatformError("无法连接认证服务，请检查网络。") from None
        if response.status_code != 200:
            raise PlatformError(f"认证接口返回 HTTP {response.status_code}。")
        try:
            payload = response.json()
        except ValueError:
            raise PlatformError("认证接口未返回 JSON。") from None
        if not isinstance(payload, dict):
            raise PlatformError("认证接口响应格式错误。")
        code = payload.get("errcode")
        if type(code) is not int or code != 0:
            if code == -1:
                raise PlatformError("该账号需先在平台完成注册。")
            # 使用固定提示，避免服务端回显手机号、验证码或凭证到日志。
            raise PlatformError("认证失败，请检查手机号、验证码或稍后重试（验证码可能已失效，或发送过于频繁）。")
        return payload.get("data")

    def send_code(self, phone):
        self._post("send-sms-code", {"phone": validate_phone(phone), "isUser": 1})

    def login(self, phone, code):
        validate_phone(phone)
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
            raise ValueError("请输入 6 位短信验证码。")
        data = self._post("phone-login", {"phone": phone, "code": code,
                          "wxCode": "", "openId": "", "nickname": "", "avatar": ""})
        if not isinstance(data, dict) or not isinstance(data.get("token"), str) or not data["token"].strip():
            raise PlatformError("登录响应缺少有效 Token。")
        client = SaicClient(data["token"], timeout=self.timeout)
        try:
            client.validate_login()
        except Exception:
            client.close()
            raise
        return client

    def close(self):
        self.session.close()

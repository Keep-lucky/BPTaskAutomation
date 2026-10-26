import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from saic_platform import AuthenticationError, PlatformError, SaicClient
from saic_platform.api import USER_INFO_URL
from saic_platform.config import load_token


class LoginTests(unittest.TestCase):
    def test_success_and_request_contract(self):
        with SaicClient(" Bearer example-token ") as client:
            response = Mock(status_code=200)
            response.json.return_value = {"errcode": 0, "data": {"id": 123}}
            with patch.object(client.get_session(), "get", return_value=response) as get:
                self.assertEqual(client.validate_login(), {"id": 123})
            get.assert_called_once_with(USER_INFO_URL, timeout=20, allow_redirects=False)
            self.assertEqual(client.get_session().headers["authorize"], "Bearer example-token")

    def test_response_failures(self):
        cases = [
            (401, {}, AuthenticationError), (403, {}, AuthenticationError),
            (302, {}, PlatformError), (500, {}, PlatformError),
            (200, {"errcode": 401}, AuthenticationError),
            (200, {"errcode": 1, "data": {"id": 1}}, PlatformError),
            (200, {"errcode": False, "data": {"id": 1}}, PlatformError),
            (200, {"errcode": 0, "data": {}}, PlatformError),
            (200, {"errcode": 0, "data": None}, PlatformError),
            (200, [], PlatformError),
        ]
        with SaicClient("example-token") as client:
            for status, body, expected in cases:
                with self.subTest(status=status, body=body):
                    response = Mock(status_code=status)
                    response.json.return_value = body
                    with patch.object(client.get_session(), "get", return_value=response):
                        with self.assertRaises(expected):
                            client.validate_login()

    def test_non_json_and_network_failures(self):
        with SaicClient("example-token") as client:
            response = Mock(status_code=200)
            response.json.side_effect = ValueError("HTML")
            with patch.object(client.get_session(), "get", return_value=response):
                with self.assertRaises(PlatformError):
                    client.validate_login()
            for error in [requests.Timeout(), requests.ConnectionError()]:
                with patch.object(client.get_session(), "get", side_effect=error):
                    with self.assertRaises(PlatformError):
                        client.validate_login()

    def test_blank_or_malformed_token(self):
        for token in ["", "  ", "Bearer ", "abc\r\nx: y", None]:
            with self.subTest(token=token), self.assertRaises(ValueError):
                SaicClient(token)

    def test_config_precedence_and_invalid_config(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps({"token": "file-token"}), encoding="utf-8")
            with patch.dict(os.environ, {"SAIC_TOKEN": " env-token "}):
                self.assertEqual(load_token(path), "env-token")
            with patch.dict(os.environ, {"SAIC_TOKEN": ""}):
                self.assertEqual(load_token(path), "file-token")
                for content in ['{"token": null}', '[]', '{bad']:
                    path.write_text(content, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_token(path)
                with self.assertRaises(ValueError):
                    load_token(Path(folder) / "missing.json")


if __name__ == "__main__":
    unittest.main()

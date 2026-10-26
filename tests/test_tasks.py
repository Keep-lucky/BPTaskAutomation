import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import main
from saic_platform import AuthenticationError, PlatformError, SaicClient
from saic_platform.api import TASK_LIST_URL


class TaskTests(unittest.TestCase):
    def test_status_filters_and_json_request(self):
        with SaicClient("example") as client:
            for status, value in {"plaza": "0", "active": "1,2", "completed": "3", "expired": "5,4"}.items():
                with self.subTest(status=status):
                    response = Mock(status_code=200)
                    response.json.return_value = {"errcode": 0, "count": 1, "data": [{"taskId": "123"}]}
                    with patch.object(client.get_session(), "post", return_value=response) as post:
                        self.assertEqual(client.list_tasks(status=status, page=2, size=10)["count"], 1)
                    post.assert_called_once_with(TASK_LIST_URL, timeout=20, allow_redirects=False,
                                                 json={"page": 2, "size": 10, "status": value})

    def test_empty_and_malformed_results(self):
        with SaicClient("example") as client:
            for data, count, valid in [([], 0, True), (None, 1, False), ([{}], 1, False), ([], "0", False)]:
                response = Mock(status_code=200)
                response.json.return_value = {"errcode": 0, "data": data, "count": count}
                with self.subTest(data=data, count=count), patch.object(client.get_session(), "post", return_value=response):
                    if valid:
                        self.assertEqual(client.list_tasks(), {"data": [], "count": 0})
                    else:
                        with self.assertRaises(PlatformError):
                            client.list_tasks()

    def test_invalid_parameters_do_not_request(self):
        with SaicClient("example") as client, patch.object(client.get_session(), "post") as post:
            for kwargs in [{"page": 0}, {"size": -1}, {"status": "bad"}]:
                with self.assertRaises(ValueError):
                    client.list_tasks(**kwargs)
            post.assert_not_called()

    def test_cli_login_before_list_and_failure_label(self):
        for failure in [False, True]:
            with self.subTest(failure=failure), patch("sys.argv", ["main.py"]), \
                 patch("main.load_token", return_value="example"), patch("main.SaicClient") as factory:
                client = factory.return_value.__enter__.return_value
                client.list_tasks.return_value = {"data": [], "count": 0}
                if failure:
                    client.list_tasks.side_effect = PlatformError("网络错误")
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main.main(), 1 if failure else 0)
                self.assertEqual([call[0] for call in client.method_calls], ["validate_login", "list_tasks"])
                self.assertIn("获取任务列表失败" if failure else "本页暂无任务", output.getvalue())

    def test_cli_does_not_list_after_login_failure(self):
        with patch("sys.argv", ["main.py"]), patch("main.load_token", return_value="example"), \
             patch("main.SaicClient") as factory, redirect_stdout(io.StringIO()):
            client = factory.return_value.__enter__.return_value
            client.validate_login.side_effect = AuthenticationError("失效")
            self.assertEqual(main.main(), 1)
            client.list_tasks.assert_not_called()

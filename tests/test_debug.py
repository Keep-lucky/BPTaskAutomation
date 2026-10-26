import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import main
from saic_platform import SaicClient
from saic_platform.debug import build_request_preview


class DebugTests(unittest.TestCase):
    def test_inspection_uses_only_read_requests(self):
        with SaicClient("example") as client:
            response = Mock(status_code=200)
            response.json.side_effect = [
                {"errcode": 0, "data": {"taskId": "123"}},
                {"errcode": 0, "data": {"status": 0, "ticketId": None}},
            ]
            with patch.object(client.get_session(), "get", return_value=response) as get, \
                 patch.object(client.get_session(), "post") as post:
                self.assertEqual(client.get_task_detail("123"), {"taskId": "123"})
                self.assertEqual(client.get_task_status("123"), {"status": 0, "ticketId": None})
                post.assert_not_called()
                self.assertEqual(get.call_args.kwargs["params"], {"taskId": "123"})

    def test_preview_serialization_and_ticket_fields(self):
        detail = {"taskId": "123", "taskType": 3, "rewardTaskFlag": 1,
                  "taskRewardDTO": {"operationTarget": "1", "taskRewardReferenceDTOList": [
                      {"name": "点赞"}, {"name": "评论"}]}}
        preview = build_request_preview(detail, {"ticketId": "456"})
        self.assertTrue(all(item["preview_only"] for item in preview))
        self.assertEqual(preview[0]["json"], {"rewardTaskFlag": 1})
        submit, supplement = preview[-2]["json"], preview[-1]["json"]
        self.assertEqual(submit["ticketId"], "456")
        self.assertNotIn("taskCompletionId", submit)
        self.assertEqual(supplement["taskCompletionId"], "456")
        self.assertEqual([item["img"] for item in json.loads(submit["imageUrls"])], ["点赞", "评论"])
        self.assertIsInstance(supplement["contentUrl"], str)

    def test_cli_inspection_does_not_fetch_list_or_write(self):
        with patch("sys.argv", ["main.py", "--inspect-task", "123"]), \
             patch("main.load_token", return_value="example"), patch("main.SaicClient") as factory, \
             redirect_stdout(io.StringIO()) as output:
            client = factory.return_value.__enter__.return_value
            client.get_task_detail.return_value = {"taskId": "123", "taskType": 1}
            client.get_task_status.return_value = {"status": 0, "ticketId": None}
            self.assertEqual(main.main(), 0)
            self.assertEqual([call[0] for call in client.method_calls],
                             ["validate_login", "get_task_detail", "get_task_status"])
            self.assertIn('"preview_only": true', output.getvalue())


if __name__ == "__main__":
    unittest.main()

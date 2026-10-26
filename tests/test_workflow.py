import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from saic_platform import PlatformError, SaicClient
from saic_platform.workflow import STEPS, UploadService, Workflow, material_fields, default_material_path


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.file = Path(self.folder.name) / "proof.png"
        self.file.write_bytes(b"example images fixture")
        self.detail = {"taskId": "123", "taskType": 3, "taskRewardDTO": {
            "operationTarget": "1", "taskRewardReferenceDTOList": [{"name": "点赞", "isRequired": None}]}}
        self.client = Mock()
        self.client.get_task_status.return_value = {"status": 0, "ticketId": None}
        self.client.claim_task.return_value = "456"
        self.client.get_upload_policy.return_value = {"token": "upload-secret", "key": "proof.png"}
        self.uploader = Mock()
        self.uploader.upload.return_value = "/proof.png"
        self.workflow = Workflow(self.client, self.uploader)
        self.events = []

    def run_flow(self, files=None):
        return self.workflow.run(self.detail, {"点赞": str(self.file)} if files is None else files,
                                 "", lambda *e: self.events.append(e))

    def test_success_and_correct_submission(self):
        self.assertTrue(self.run_flow())
        self.assertEqual([c[0] for c in self.client.method_calls],
                         ["get_task_status", "claim_task", "get_upload_policy", "submit_task"])
        self.client.submit_task.assert_called_once_with("123", "456", [{"img": "点赞", "url": "/proof.png"}], link="")
        self.assertEqual([e[0] for e in self.events if e[1] == "成功"], list(STEPS))
        self.assertNotIn("upload-secret", str(self.events))

    def test_default_like_review_mapping_is_preserved_in_submission(self):
        self.detail["taskRewardDTO"]["taskRewardReferenceDTOList"].append({"name": "评论", "isRequired": None})
        selected = {name: default_material_path(name) for name in ("点赞", "评论")}
        # 使用临时图片，验证路径与提交类别绑定，不发送真实请求。
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            for filename in ("like.jpg", "review.jpg"):
                (directory / filename).write_bytes(b"fixture")
            with patch("saic_platform.workflow.IMAGE_DIR", directory):
                selected = {name: default_material_path(name) for name in ("点赞", "评论")}
            self.uploader.upload.side_effect = ["/uploaded-like.jpg", "/uploaded-review.jpg"]
            self.assertTrue(self.run_flow(selected))
        self.assertEqual([call.args[0].name for call in self.uploader.upload.call_args_list], ["like.jpg", "review.jpg"])
        self.assertEqual(self.client.submit_task.call_args.args[2], [
            {"img": "点赞", "url": "/uploaded-like.jpg"},
            {"img": "评论", "url": "/uploaded-review.jpg"},
        ])
        self.assertEqual(default_material_path("转发"), "")

    def test_missing_material_does_not_claim(self):
        self.assertFalse(self.run_flow({}))
        self.client.claim_task.assert_not_called()
        self.assertEqual(self.events[-1][:2], ("检查材料", "失败"))

    def test_already_claimed_reuses_ticket(self):
        self.client.get_task_status.return_value = {"status": 1, "ticketId": "existing"}
        self.assertTrue(self.run_flow())
        self.client.claim_task.assert_not_called()
        self.assertEqual(self.client.submit_task.call_args.args[1], "existing")

    def test_reviewing_task_is_not_resubmitted(self):
        self.client.get_task_status.return_value = {"status": 2, "ticketId": "existing"}
        self.assertFalse(self.run_flow())
        self.client.submit_task.assert_not_called()

    def test_upload_failure_stops_submission_and_can_retry(self):
        self.uploader.upload.side_effect = PlatformError("上传失败")
        self.assertFalse(self.run_flow())
        self.assertEqual(self.events[-1][:2], ("上传文件", "失败"))
        self.client.submit_task.assert_not_called()
        self.client.get_task_status.return_value = {"status": 1, "ticketId": "456"}
        self.uploader.upload.side_effect = None
        self.assertTrue(self.run_flow())
        self.assertEqual(self.client.claim_task.call_count, 1)

    def test_uncertain_submission_blocks_blind_retry(self):
        self.client.submit_task.side_effect = PlatformError("超时")
        self.assertFalse(self.run_flow())
        self.assertEqual(self.events[-1][:2], ("提交审核", "失败"))
        self.assertFalse(self.run_flow())
        self.assertEqual(self.client.submit_task.call_count, 1)

    def test_material_config(self):
        self.assertEqual(material_fields(self.detail), [("点赞", True)])
        original = {"taskType": 2, "taskRewardDTO": {"category": 2, "workDataSubmission": 1}}
        self.assertEqual(len(material_fields(original)), 6)

    def test_write_api_payloads(self):
        with SaicClient("example") as client, patch.object(client.get_session(), "post") as post:
            response = Mock(status_code=200)
            post.return_value = response
            response.json.return_value = {"errcode": 0, "data": "ticket"}
            self.assertEqual(client.claim_task("123", reward=True), "ticket")
            self.assertEqual(post.call_args.kwargs["json"], {"rewardTaskFlag": 1})
            for body in [{"errcode": 0, "data": {"token": "up", "key": "key"}}, {"token": "up", "key": "key"}]:
                response.json.return_value = body
                self.assertEqual(client.get_upload_policy("proof.png"), {"token": "up", "key": "key"})
            response.json.return_value = {"errcode": 0}
            client.submit_task("123", "ticket", [{"img": "点赞", "url": "/key"}])
            body = post.call_args.kwargs["json"]
            self.assertEqual(body["ticketId"], "ticket")
            self.assertEqual(json.loads(body["imageUrls"]), [{"img": "点赞", "url": "/key"}])

    def test_upload_uses_separate_session_and_multipart(self):
        encoded = base64.urlsafe_b64encode(json.dumps({"scope": "bucket:key"}).encode()).decode().rstrip("=")
        policy = {"token": "access:signature:" + encoded, "key": "proof.png"}
        with patch("saic_platform.workflow.requests.Session") as factory:
            session = factory.return_value.__enter__.return_value
            query = Mock(status_code=200)
            query.json.return_value = {"up": {"acc": {"main": ["up.qiniup.com"]}}}
            upload = Mock(status_code=200)
            upload.json.return_value = {"key": "proof.png"}
            session.get.return_value, session.post.return_value = query, upload
            self.assertEqual(UploadService().upload(self.file, policy, lambda _: None), "/proof.png")
            kwargs = session.post.call_args.kwargs
            self.assertNotIn("headers", kwargs)
            self.assertEqual(kwargs["data"], policy)
            self.assertEqual(kwargs["files"]["file"][0], "proof.png")
            query.json.return_value = {"up": {"acc": {"main": ["untrusted.example"]}}}
            session.post.reset_mock()
            with self.assertRaises(PlatformError):
                UploadService().upload(self.file, policy, lambda _: None)
            session.post.assert_not_called()

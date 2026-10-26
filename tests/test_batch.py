from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from saic_platform.batch import BatchRunner
from saic_platform.api import PlatformError, SaicClient
from saic_platform.workflow import batch_materials, default_material_path


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for platform in ('wechat', 'toutiao', 'tiktok'):
            directory = self.root / platform
            directory.mkdir()
            for name in ('like.jpg', 'review.jpg', 'forward.jpg'):
                (directory / name).write_bytes(b'fixture')
        self.patcher = patch('saic_platform.workflow.IMAGES_DIR', self.root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def detail(self, task_id, platform='Wechat'):
        return {'taskId': task_id, 'platformCode': platform, 'taskType': 3,
                'taskRewardDTO': {'operationTarget': '1', 'taskRewardReferenceDTOList': [
                    {'name': name} for name in ('点赞', '评论', '转发')]}}

    def client(self, task_id):
        client = Mock()
        client.get_task_detail.return_value = self.detail(task_id)
        client.get_task_status.return_value = {'status': 0, 'ticketId': None}
        client.claim_task.return_value = 'ticket-' + task_id
        return client

    def test_platform_mapping_and_fallback(self):
        for platform, folder in [('Wechat', 'wechat'), ('今日头条', 'toutiao'), ('Tiktok', 'tiktok')]:
            selected = batch_materials(self.detail('1', platform))
            self.assertEqual(Path(selected['点赞']), self.root / folder / 'like.jpg')
            self.assertEqual(Path(selected['评论']), self.root / folder / 'review.jpg')
            self.assertEqual(Path(selected['转发']), self.root / folder / 'forward.jpg')
        (self.root / 'wechat' / 'review.jpg').unlink()
        self.assertEqual(Path(default_material_path('评论', self.detail('1'))).name, 'forward.jpg')
        (self.root / 'toutiao' / 'forward.jpg').unlink()
        self.assertEqual(Path(default_material_path('转发', self.detail('1', 'Toutiao'))).name, 'review.jpg')
        self.assertEqual(default_material_path('未知材料', self.detail('1')), '')
        with self.assertRaises(ValueError):
            batch_materials(self.detail('1', 'unknown'))

    def test_real_parallelism_isolated_sessions_deduplicated_ids(self):
        barrier = threading.Barrier(2)
        created = []
        lock = threading.Lock()
        def factory():
            client = self.client('unused')
            def read(task_id):
                barrier.wait(timeout=5)
                return self.detail(task_id, 'Toutiao' if task_id == '2' else 'Wechat')
            client.get_task_detail.side_effect = read
            with lock:
                created.append(client)
            return client
        events = []
        runner = BatchRunner(factory)
        with patch('saic_platform.workflow.UploadService.upload', return_value='/uploaded.jpg'):
            results = runner.run([{'taskId': '1'}, {'taskId': '2'}, {'taskId': '1'}], 2, lambda *e: events.append(e))
        self.assertEqual(results, {'1': True, '2': True})
        self.assertEqual(len(created), 2)
        for client in created:
            client.close.assert_called_once()
            client.claim_task.assert_called_once()
            client.submit_task.assert_called_once()
        self.assertEqual(sum(e[0] == 'batch_result' for e in events), 2)

    def test_missing_files_fail_before_claim_and_other_task_continues(self):
        clients = [self.client('1'), self.client('2')]
        clients[0].get_task_detail.return_value = self.detail('1', 'Tiktok')
        (self.root / 'tiktok' / 'like.jpg').unlink()
        runner = BatchRunner(Mock(side_effect=clients))
        with patch('saic_platform.workflow.UploadService.upload', return_value='/uploaded.jpg'):
            results = runner.run([{'taskId': '1'}, {'taskId': '2'}], 1, lambda *e: None)
        self.assertEqual(results, {'1': False, '2': True})
        clients[0].claim_task.assert_not_called()
        clients[0].submit_task.assert_not_called()
        clients[1].submit_task.assert_called_once()

    def test_uncertain_submission_not_retried_across_batches(self):
        clients = [self.client('1'), self.client('1')]
        clients[0].submit_task.side_effect = PlatformError('timeout')
        uncertain = set()
        runner = BatchRunner(Mock(side_effect=clients), uncertain)
        with patch('saic_platform.workflow.UploadService.upload', return_value='/uploaded.jpg'):
            for _ in range(2):
                self.assertEqual(runner.run([{'taskId': '1'}], 1, lambda *e: None), {'1': False})
        self.assertIn('1', uncertain)
        clients[1].claim_task.assert_not_called()
        clients[1].submit_task.assert_not_called()

    def test_original_and_unknown_platform_do_not_claim(self):
        for detail in [dict(self.detail('1'), taskType=2), self.detail('1', 'unknown')]:
            client = self.client('1')
            client.get_task_detail.return_value = detail
            self.assertEqual(BatchRunner(lambda: client).run([{'taskId': '1'}], 1, lambda *e: None), {'1': False})
            client.claim_task.assert_not_called()
            client.close.assert_called_once()

    def test_cloned_client_has_independent_session(self):
        with SaicClient('example') as client, client.clone() as cloned:
            self.assertIsNot(client.get_session(), cloned.get_session())
            self.assertEqual(client.get_session().headers['authorize'], cloned.get_session().headers['authorize'])

import tkinter as tk
import unittest
from unittest.mock import Mock

from saic_platform.desktop import DesktopApp
from saic_platform.workflow import IMAGE_DIR


class DesktopTests(unittest.TestCase):
    def test_check_all_and_batch_events(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        app = DesktopApp(root)
        self.addCleanup(app.auth.close)
        app.show_tasks({'data': [{'taskId': '1', 'taskName': '任务一'},
                                 {'taskId': '2', 'taskName': '任务二'}], 'count': 2})
        app.select_all(True)
        self.assertEqual(app.checked, {'0', '1'})
        self.assertEqual(app.table.set('0', 'check'), '☑')
        app.busy = True
        app.select_all(False)
        self.assertEqual(len(app.checked), 2)
        app.busy = False
        app.client = Mock()
        app.batch_runner = Mock()
        app.start = lambda work, done: done(work())
        def run(tasks, workers, emit):
            self.assertEqual([t['taskId'] for t in tasks], ['1', '2'])
            self.assertEqual(workers, 3)
            emit('batch_step', '1', '提交审核', '成功', '已提交')
            emit('batch_result', '1', True)
            emit('batch_step', '2', '检查材料', '失败', '材料缺失')
            emit('batch_result', '2', False)
            return {'1': True, '2': False}
        app.batch_runner.run.side_effect = run
        app.real.set(True)
        app.execute()
        app.poll()
        self.assertEqual(app.table.set('0', 'result'), '已提交待审核')
        self.assertEqual(app.table.set('1', 'result'), '失败，查看日志')
        self.assertEqual(app.steps.item('batch:2:检查材料', 'values'), ('失败', '材料缺失'))
        self.assertEqual(app.progress['value'], 2)
        app.select_all(False)
        self.assertEqual(app.checked, set())
        app.select_all(True)
        app.show_tasks({'data': [], 'count': 0})
        self.assertEqual(app.checked, set())
        self.assertFalse(app.real.get())

    def test_sms_login_loads_tasks_and_clears_secrets(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        app = DesktopApp(root)
        self.addCleanup(app.auth.close)
        app.auth.close()
        app.auth = Mock()
        app.start = lambda work, done: done(work())
        app.phone.insert(0, "13800000000")
        app.send_code()
        app.auth.send_code.assert_called_once_with("13800000000")
        app.poll()
        self.assertEqual(str(app.sms_button['state']), 'disabled')
        app.send_code()
        app.auth.send_code.assert_called_once()
        app.code.insert(0, "123456")
        client = app.auth.login.return_value
        client.list_tasks.return_value = {"data": [], "count": 0}
        app.sms_login()
        app.auth.login.assert_called_once_with("13800000000", "123456")
        self.assertIs(app.client, client)
        self.assertEqual(app.code.get(), "")
        self.assertEqual(app.login_status['text'], "登录成功")

    def test_window_material_fields_and_step_events(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        app = DesktopApp(root)
        root.update()
        app.show_detail(({"taskId": "123", "name": "测试任务", "taskType": 3, "platformCode": "Wechat",
                          "taskDetailDTOS": {"taskLinkUrl": "https://mp.weixin.qq.com/s/test-article", "articleBody": [{"name": "要求", "body": "<p>真实截图</p>"}]},
                          "taskRewardDTO": {"operationTarget": "1", "taskRewardReferenceDTOList": [
                              {"name": "点赞", "isRequired": None}, {"name": "评论", "isRequired": None}]}},
                         {"status": 0, "ticketId": None}))
        self.assertEqual(set(app.files), {"点赞", "评论"})
        self.assertEqual(app.target_url.get(), "https://mp.weixin.qq.com/s/test-article")
        app.copy_target_url()
        self.assertEqual(root.clipboard_get(), "https://mp.weixin.qq.com/s/test-article")
        self.assertEqual(app.files["点赞"].get(), str(IMAGE_DIR / "wechat" / "like.jpg"))
        self.assertEqual(app.files["评论"].get(), str(IMAGE_DIR / "wechat" / "forward.jpg"))
        app.events.put(("step", "领取任务", "失败", "测试错误"))
        app.poll()
        root.update()
        self.assertEqual(app.steps.item("领取任务", "values"), ("失败", "测试错误"))
        self.assertIn("测试错误", app.log.get("1.0", "end"))
        app.show_detail(({"taskId": "456", "taskType": 2}, {"status": 1, "ticketId": "789"}))
        self.assertEqual(app.target_url.get(), "")
        root.update()
        self.assertEqual(len(app.files), 4)
        self.assertFalse(app.real.get())
        self.assertGreater(app.steps.winfo_height(), 80)

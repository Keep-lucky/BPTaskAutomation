import tkinter as tk
import unittest
from unittest.mock import Mock, patch

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
        self.assertTrue(app.article_like.get())
        self.assertFalse(app.article_watch.get())
        self.assertFalse(app.article_moments.get())
        self.assertEqual(app.target_url.get(), "https://mp.weixin.qq.com/s/test-article")
        app.copy_target_url()
        self.assertEqual(root.clipboard_get(), "https://mp.weixin.qq.com/s/test-article")
        self.assertEqual(app.files["点赞"].get(), str(IMAGE_DIR / "wechat" / "like.jpg"))
        self.assertEqual(app.files["评论"].get(), str(IMAGE_DIR / "wechat" / "review.jpg"))
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
        self.assertFalse(app.article_like.get())
        self.assertGreater(app.steps.winfo_reqheight(), 80)

    def test_current_article_runs_without_target_url(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        app = DesktopApp(root)
        self.addCleanup(app.auth.close)
        app.show_detail(({"taskId": "123", "name": "测试任务", "taskType": 3, "platformCode": "Wechat",
                          "taskRewardDTO": {"operationTarget": "1", "taskRewardReferenceDTOList": [
                              {"name": "点赞", "isRequired": None}]}},
                         {"status": 0, "ticketId": None}))
        app.start = lambda work, done: done(work())
        with patch("saic_platform.desktop.interact_article", return_value={
                "message": "已完成", "materials": {}, "warnings": []}) as interact:
            app.interact_current_article()
        self.assertEqual(interact.call_args.args[0], "")
        self.assertTrue(interact.call_args.kwargs["reuse_open_article"])
        self.assertNotIn("url", interact.call_args.kwargs)

    def test_article_screenshots_fill_material_fields(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        app = DesktopApp(root)
        self.addCleanup(app.auth.close)
        app.show_detail(({"taskId": "123", "name": "测试任务", "taskType": 3, "platformCode": "Wechat",
                          "taskRewardDTO": {"operationTarget": "1", "taskRewardReferenceDTOList": [
                              {"name": "点赞", "isRequired": None}, {"name": "转发", "isRequired": None}]}},
                         {"status": 0, "ticketId": None}))
        app.article_done({"message": "已完成", "materials": {"点赞": "C:/shot/like.png"},
                          "screenshots": {"like": "C:/shot/like.png"},
                          "warnings": ["材料「转发」对应朋友圈分享，但本次未勾选该操作，材料仍为空。"]})
        self.assertEqual(app.files["点赞"].get(), "C:/shot/like.png")
        self.assertEqual(app.files["转发"].get(), str(IMAGE_DIR / "wechat" / "forward.jpg"))
        log = app.log.get("1.0", "end")
        self.assertIn("已自动填入材料：点赞", log)
        self.assertIn("注意：材料「转发」", log)

    def detail(self, names=("点赞",)):
        return ({"taskId": "123", "name": "测试任务", "taskType": 3, "platformCode": "Wechat",
                 "taskRewardDTO": {"operationTarget": "1", "taskRewardReferenceDTOList": [
                     {"name": name, "isRequired": None} for name in names]}},
                {"status": 0, "ticketId": None})

    def test_auto_submit_runs_current_task_after_screenshots(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        app = DesktopApp(root)
        self.addCleanup(app.auth.close)
        app.show_detail(self.detail())
        app.auto_submit.set(True)
        app.client = Mock()
        app.workflow = Mock()
        app.workflow.run.return_value = True
        app.start = lambda work, done: done(work())
        app.article_done({"message": "已完成", "materials": {"点赞": "C:/shot/like.png"}, "warnings": []})
        self.assertTrue(app.pending_auto_submit)
        app.poll()
        app.workflow.run.assert_called_once()
        detail, selected, link, _ = app.workflow.run.call_args.args
        self.assertEqual(detail["taskId"], "123")
        self.assertEqual(selected["点赞"], "C:/shot/like.png")
        self.assertEqual(link, "")
        # 自动提交绕过人工确认框，但不改动勾选状态。
        self.assertFalse(app.real.get())
        log = app.log.get("1.0", "end")
        self.assertIn("自动提交已开启", log)
        self.assertIn("流程完成，材料已提交等待审核", log)

    def test_auto_submit_is_off_by_default(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        app = DesktopApp(root)
        self.addCleanup(app.auth.close)
        app.show_detail(self.detail())
        app.workflow = Mock()
        app.article_done({"message": "已完成", "materials": {"点赞": "C:/shot/like.png"}, "warnings": []})
        self.assertFalse(app.pending_auto_submit)
        app.poll()
        app.workflow.run.assert_not_called()
        self.assertIn("确认无误后勾选真实完成", app.log.get("1.0", "end"))

    def test_auto_submit_skips_when_no_material_was_filled(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        app = DesktopApp(root)
        self.addCleanup(app.auth.close)
        app.show_detail(self.detail())
        app.auto_submit.set(True)
        app.workflow = Mock()
        app.article_done({"message": "已完成", "materials": {}, "warnings": ["无可用截图"]})
        self.assertFalse(app.pending_auto_submit)
        app.poll()
        app.workflow.run.assert_not_called()
        self.assertIn("自动提交已跳过：本次没有自动填入任何材料", app.log.get("1.0", "end"))

    def test_auto_submit_skips_when_required_material_is_missing(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        app = DesktopApp(root)
        self.addCleanup(app.auth.close)
        app.show_detail(self.detail(("点赞", "转发")))
        app.files["转发"].set("")
        app.auto_submit.set(True)
        app.client = Mock()
        app.workflow = Mock()
        app.article_done({"message": "已完成", "materials": {"点赞": "C:/shot/like.png"}, "warnings": []})
        app.poll()
        app.workflow.run.assert_not_called()
        self.assertIn("必填材料仍为空（转发）", app.log.get("1.0", "end"))

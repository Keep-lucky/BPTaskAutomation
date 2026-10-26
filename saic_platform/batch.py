"""有界线程池执行任务；每任务独立会话，保留上传缓存和不确定提交状态。"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from .api import PlatformError
from .workflow import Workflow, batch_materials


class BatchRunner:
    def __init__(self, client_factory, uncertain=None):
        self.client_factory = client_factory
        self.workflows = {}
        self.uncertain = uncertain if uncertain is not None else set()

    def run(self, tasks, workers, emit):
        if type(workers) is not int or not 1 <= workers <= 8:
            raise ValueError("并发线程数必须为 1 到 8。")
        unique = {str(task["taskId"]): dict(task) for task in tasks}

        def process(task_id, task):
            client = None
            try:
                emit("batch_step", task_id, "检查材料", "进行中", "读取任务详情")
                client = self.client_factory()
                detail = client.get_task_detail(task_id)
                detail = {**task, **detail}
                selected = batch_materials(detail)
                workflow = self.workflows.get(task_id)
                if workflow is None:
                    workflow = self.workflows[task_id] = Workflow(client)
                    workflow.uncertain = self.uncertain
                else:
                    workflow.client = client
                return workflow.run(detail, selected, "",
                                    lambda *args: emit("batch_step", task_id, *args))
            except Exception as error:
                message = str(error) if isinstance(error, (PlatformError, ValueError)) else f"本地异常：{type(error).__name__}"
                emit("batch_step", task_id, "检查材料", "失败", message)
                return False
            finally:
                if client is not None:
                    client.close()

        results = {}
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="saic-task") as pool:
            futures = {pool.submit(process, task_id, task): task_id for task_id, task in unique.items()}
            for future in as_completed(futures):
                task_id = futures[future]
                results[task_id] = future.result()
                emit("batch_result", task_id, results[task_id])
        return results

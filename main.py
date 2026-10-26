"""验证上汽平台登录凭证并查看任务列表。"""

import argparse
import json
from getpass import getpass
from pathlib import Path

from saic_platform import SaicClient, PlatformError
from saic_platform.config import load_token
from saic_platform.debug import build_request_preview


STATUS_LABELS = {"plaza": "任务广场", "active": "进行中", "completed": "已完成", "expired": "已失效"}


def print_tasks(result: dict, *, status: str, page: int, size: int) -> None:
    print(f"\n{STATUS_LABELS[status]}：共 {result['count']} 条，第 {page} 页，本页 {len(result['data'])} 条")
    if not result["data"]:
        print("本页暂无任务。")
        return
    statuses = {"0": "未领取", "1": "进行中", "2": "审核中", "3": "已完成", "4": "已失效", "5": "未通过"}
    types = {"1": "转发", "2": "原创", "3": "互动", "4": "原创"}
    for index, task in enumerate(result["data"], start=(page - 1) * size + 1):
        kind = str(task.get("taskType", ""))
        unit = "荣誉值" if kind == "2" else "贡献值"
        print(f"{index}. {task.get('taskName', '未命名任务')} | {types.get(kind, '任务')}-{task.get('platformName', '-')}"
              f" | {statuses.get(str(task.get('status')), '未知状态')}")
        print(f"   ID：{task['taskId']} | 基础奖励：{task.get('pointNum', 0)}{unit}"
              f" | 截止：{task.get('endTime', '-')}")
    if page * size < result["count"]:
        print(f"还有更多任务，使用 --page {page + 1} 查看下一页。")


def main() -> int:
    parser = argparse.ArgumentParser(description="验证上汽平台登录并查看任务列表")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--prompt", action="store_true", help="隐藏输入 Token")
    parser.add_argument("--status", choices=STATUS_LABELS, default="plaza", help="任务状态（默认 plaza：任务广场）")
    parser.add_argument("--page", type=int, default=1, help="页码，默认 1")
    parser.add_argument("--size", type=int, default=20, help="每页条数，默认 20")
    parser.add_argument("--inspect-task", metavar="TASK_ID", help="只读查看任务详情、领取状态，并预览接口请求（不发送写入请求）")
    args = parser.parse_args()
    if args.page < 1 or args.size < 1:
        parser.error("--page 和 --size 必须是正整数。")
    stage = "登录验证"
    try:
        token = getpass("请输入 Token 或 authorize 请求头值：") if args.prompt else load_token(args.config)
        with SaicClient(token) as client:
            client.validate_login()
            print("登录验证成功。")
            if args.inspect_task:
                stage = "读取任务详情"
                detail = client.get_task_detail(args.inspect_task)
                status = client.get_task_status(args.inspect_task)
                print(json.dumps({"detail": detail, "user_task_status": status,
                                  "request_preview": build_request_preview(detail, status)}, ensure_ascii=False, indent=2))
                return 0
            stage = "获取任务列表"
            result = client.list_tasks(status=args.status, page=args.page, size=args.size)
            print_tasks(result, status=args.status, page=args.page, size=args.size)
        return 0
    except (ValueError, PlatformError) as error:
        print(f"{stage}失败：{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

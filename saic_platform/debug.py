"""纯本地请求预览。不获取上传凭证、不发送领取/上传/提交请求。"""

import json
from typing import Any

from .api import BASE_URL


def build_request_preview(detail: dict[str, Any], status: dict[str, Any]) -> list[dict[str, Any]]:
    """按网页代码生成请求说明；占位符不能作为真实请求使用。"""
    task_id = str(detail["taskId"])
    ticket_id = status.get("ticketId") or "<领取成功返回的 ticketId>"
    claim_body = {"rewardTaskFlag": 1} if str(detail.get("rewardTaskFlag")) == "1" else {}
    reward = detail.get("taskRewardDTO") or {}
    references = reward.get("taskRewardReferenceDTOList") or []
    is_special = str(detail.get("taskType")) == "3" or (
        str(detail.get("taskType")) == "1" and detail.get("platformCode") in {"Weibo", "Tiktok"}
    )
    if is_special:
        operation = str(reward.get("operationTarget"))
        operations = {"2": "提高视频质量", "3": "转发+评论", "4": "评论", "5": "回帖",
                      "6": "点赞", "7": "评论+点赞", "8": "赞同", "9": "喜欢",
                      "10": "喜欢+评论", "11": "收藏", "12": "自定义"}
        names = ([item["name"] for item in references if isinstance(item, dict) and item.get("name")]
                 if operation == "1" else [operations.get(operation, "未知操作")])
        images = [{"img": name, "url": "<上传结果 /key>"} for name in names]
        if not images:
            images = [{"img": "<按 operationTarget 确定的截图名称>", "url": "<上传结果 /key>"}]
    else:
        images = [{"img": "", "url": "<上传结果 /key>"}]
    submit = {"taskId": task_id, "ticketId": ticket_id, "imageUrls": json.dumps(images, ensure_ascii=False)}
    if str(detail.get("taskType")) in {"2", "4"}:
        submit["submitLink"] = "<真实作品链接>"

    def spec(name: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return {"name": name, "preview_only": True, "method": "POST", "url": BASE_URL + path, "json": body}

    return [
        spec("领取任务（未发送）", f"/api/front/task-completions/claim/{task_id}", claim_body),
        spec("获取上传临时凭证（未发送）", "/api/front/oss/policy", {"fileName": "<实际截图文件名.png>"}),
        {"name": "解析上传域名（未发送）", "preview_only": True, "method": "GET",
         "url": "https://api.qiniu.com/v2/query", "query": {"ak": "<上传 Token 中的 access key>", "bucket": "<上传 Token scope 中的 bucket>"}},
        {"name": "文件直传（未发送）", "preview_only": True, "method": "POST",
         "url": "https://<域名查询响应 up.acc.main[0]>", "encoding": "multipart/form-data",
         "fields": {"token": "<policy 返回的上传 Token>", "key": "<policy 返回的 key>", "file": "<真实截图文件>"}},
        spec("提交审核（未发送）", "/api/front/task-completions/submit", submit),
        spec("补充材料（未发送）", "/api/front/chat-messages", {
            "taskId": task_id, "taskCompletionId": ticket_id, "content": "<补充说明>",
            "contentUrl": json.dumps(images, ensure_ascii=False),
        }),
    ]

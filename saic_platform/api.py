"""复用已有 Token，通过受保护的用户信息接口验证登录。"""

from typing import Any
from urllib.parse import quote

import requests


BASE_URL = "https://saic-px.saicmotor.com"
USER_INFO_URL = f"{BASE_URL}/api/front/mobile-users/show"
TASK_LIST_URL = f"{BASE_URL}/api/front/tasks/list"
TASK_STATUSES = {"plaza": "0", "active": "1,2", "completed": "3", "expired": "5,4"}


class PlatformError(RuntimeError):
    """接口或网络异常。"""


class AuthenticationError(PlatformError):
    """登录凭证失效或无访问权限。"""


class SaicClient:
    """保留会话，供后续任务接口复用。"""

    def __init__(self, token: str, *, timeout: float = 20) -> None:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("Token 不能为空。")
        value = token.strip()
        if value.lower() == "bearer":
            raise ValueError("Bearer 后缺少 Token。")
        if value.lower().startswith("bearer "):
            value = value[7:].strip()
        if not value or any(char.isspace() for char in value):
            raise ValueError("Token 格式错误，请粘贴 Token 或完整 Bearer 请求头值。")
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0。")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "authorize": f"Bearer {value}",
            "Accept": "application/json",
            "Referer": f"{BASE_URL}/",
        })

    def validate_login(self) -> dict[str, Any]:
        """成功返回用户信息；不将首页可访问或 HTTP 200 单独视为登录成功。"""
        payload = self._request_payload("GET", USER_INFO_URL)
        user = payload.get("data")
        if not isinstance(user, dict) or not user.get("id"):
            raise PlatformError("接口未返回有效用户信息，无法确认登录状态。")
        return user

    def list_tasks(
        self, *, status: str = "plaza", page: int = 1, size: int = 20
    ) -> dict[str, Any]:
        """读取一页普通任务，返回 data 列表和 count 总数。"""
        if status not in TASK_STATUSES:
            raise ValueError("status 必须为 plaza、active、completed 或 expired。")
        if type(page) is not int or type(size) is not int or page < 1 or size < 1:
            raise ValueError("page 和 size 必须是正整数。")
        payload = self._request_payload("POST", TASK_LIST_URL, json={
            "page": page, "size": size, "status": TASK_STATUSES[status],
        })
        tasks, count = payload.get("data"), payload.get("count")
        if (
            not isinstance(tasks, list)
            or any(not isinstance(item, dict) or not item.get("taskId") for item in tasks)
            or type(count) is not int or count < 0
        ):
            raise PlatformError("任务列表响应格式不符合预期。")
        return {"data": tasks, "count": count}

    def get_task_detail(self, task_id: str) -> dict[str, Any]:
        """只读任务要求、奖励配置和素材信息。"""
        task_id = self._task_id(task_id)
        payload = self._request_payload("GET", f"{BASE_URL}/api/front/tasks/show/{quote(task_id, safe='')}")
        detail = payload.get("data")
        if not isinstance(detail, dict) or str(detail.get("taskId")) != task_id:
            raise PlatformError("任务详情响应格式不符合预期。")
        return detail

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        """只读当前用户的领取状态与 ticketId。"""
        payload = self._request_payload(
            "GET", f"{BASE_URL}/api/front/task-completions/task-status",
            params={"taskId": self._task_id(task_id)},
        )
        status = payload.get("data")
        if not isinstance(status, dict) or "status" not in status or "ticketId" not in status:
            raise PlatformError("任务状态响应格式不符合预期。")
        return status

    def claim_task(self, task_id: str, *, reward: bool = False) -> str:
        payload = self._request_payload("POST", f"{BASE_URL}/api/front/task-completions/claim/{quote(self._task_id(task_id), safe='')}",
                                        json={"rewardTaskFlag": 1} if reward else {})
        ticket = payload.get("data")
        if not isinstance(ticket, (str, int)) or isinstance(ticket, bool) or not ticket:
            raise PlatformError("领取响应缺少 ticketId，请刷新任务状态后再操作。")
        return str(ticket)

    def get_upload_policy(self, filename: str) -> dict[str, Any]:
        payload = self._request_payload("POST", f"{BASE_URL}/api/front/oss/policy", json={"fileName": filename})
        policy = payload.get("data", payload)
        if not isinstance(policy, dict) or not all(isinstance(policy.get(k), str) and policy[k] for k in ("token", "key")):
            raise PlatformError("上传凭证响应缺少 token 或 key。")
        return policy

    def submit_task(self, task_id: str, ticket_id: str, images: list[dict[str, str]], *, link: str = "") -> None:
        import json
        body = {"taskId": self._task_id(task_id), "ticketId": ticket_id,
                "imageUrls": json.dumps(images, ensure_ascii=False)}
        if link:
            body["submitLink"] = link
        self._request_payload("POST", f"{BASE_URL}/api/front/task-completions/submit", json=body)

    @staticmethod
    def _task_id(task_id: str) -> str:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id 必须为非空字符串。")
        return task_id.strip()

    def _request_payload(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        label = "用户信息" if url == USER_INFO_URL else "任务"
        try:
            request = self._session.get if method == "GET" else self._session.post
            response = request(url, timeout=self.timeout, allow_redirects=False, **kwargs)
        except requests.Timeout:
            raise PlatformError("请求超时，请稍后重试。") from None
        except requests.RequestException:
            raise PlatformError("无法连接平台，请检查网络。") from None
        if response.status_code in (401, 403):
            raise AuthenticationError("Token 已失效或没有权限，请在浏览器重新登录并获取 Token。")
        if response.status_code != 200:
            raise PlatformError(f"{label}接口返回 HTTP {response.status_code}。")
        try:
            payload = response.json()
        except ValueError:
            raise PlatformError(f"{label}接口未返回 JSON。") from None
        if not isinstance(payload, dict):
            raise PlatformError(f"{label}接口响应格式不符合预期。")
        # 上传工具的前端同时兼容带 data 的业务封装和裸 token/key 响应。
        if url == f"{BASE_URL}/api/front/oss/policy" and "errcode" not in payload:
            if all(isinstance(payload.get(k), str) and payload[k] for k in ("token", "key")):
                return payload
        code = payload.get("errcode")
        if code in (401, 403, "401", "403"):
            raise AuthenticationError("登录凭证失效或没有权限，请重新登录。")
        if type(code) is not int or code != 0:
            safe_code = code if isinstance(code, int) else "未知"
            raise PlatformError(f"{label}接口未返回成功业务状态（errcode={safe_code}）。")
        return payload

    def get_session(self) -> requests.Session:
        """获取带有 authorize 请求头的会话；调用方应避免记录请求头。"""
        return self._session

    def clone(self) -> "SaicClient":
        """为并发任务创建独立连接池；不在线程间共享 requests.Session。"""
        return SaicClient(self._session.headers["authorize"], timeout=self.timeout)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "SaicClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

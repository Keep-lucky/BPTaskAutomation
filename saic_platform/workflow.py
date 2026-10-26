"""任务执行流程：校验本地材料、领取、签发凭证、上传、提交。"""

import base64
import json
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import requests

from .api import PlatformError


OPERATIONS = {"2": "提高视频质量", "3": "转发+评论", "4": "评论", "5": "回帖", "6": "点赞",
              "7": "评论+点赞", "8": "赞同", "9": "喜欢", "10": "喜欢+评论", "11": "收藏", "12": "自定义"}
STEPS = ("检查材料", "领取任务", "获取上传凭证", "上传文件", "提交审核")
IMAGE_DIR = Path(__file__).resolve().parent.parent / "images"
IMAGES_DIR = Path(__file__).resolve().parent.parent / "images"
DEFAULT_MATERIALS = {"点赞": "like.jpg", "评论": "review.jpg"}
PLATFORM_FOLDERS = {
    "wechat": "wechat", "weixin": "wechat", "微信": "wechat", "微信公众号": "wechat",
    "微信视频号": "wechat", "视频号": "wechat",
    "toutiao": "toutiao", "今日头条": "toutiao", "头条": "toutiao",
    "tiktok": "tiktok", "douyin": "tiktok", "抖音": "tiktok",
}


def platform_folder(detail):
    for key in ("platformCode", "platformName"):
        value = str(detail.get(key) or "").strip().lower()
        if value in PLATFORM_FOLDERS:
            return PLATFORM_FOLDERS[value]
    return None


def default_material_path(name, detail=None):
    """相对于项目目录定位，避免从其他工作目录启动时找错文件。"""
    if detail is not None:
        folder = platform_folder(detail)
        if not folder:
            return ""
        # 同一平台选择一个根目录，不跨平台或根目录拼凑材料。
        directory = IMAGES_DIR / folder
        if not directory.is_dir() and (IMAGE_DIR / folder).is_dir():
            directory = IMAGE_DIR / folder
        if "评论" in name or "回帖" in name:
            filenames = ("review.jpg", "forward.jpg")
        elif "转发" in name:
            filenames = ("forward.jpg", "review.jpg")
        elif name in {"点赞", "赞同", "喜欢"}:
            filenames = ("like.jpg",)
        else:
            return ""
        return str(next((directory / f for f in filenames if (directory / f).is_file()), directory / filenames[0]))
    filename = DEFAULT_MATERIALS.get(name)
    return str(IMAGE_DIR / filename) if filename else ""


def batch_materials(detail):
    """只自动匹配已知平台和操作；原创链接及未知截图需单任务手工填写。"""
    if not platform_folder(detail):
        raise ValueError("平台不支持自动匹配图片，请使用单任务手工选择材料。")
    if str(detail.get("taskType")) in {"2", "4"}:
        raise ValueError("原创任务需要独立作品链接，请使用单任务提交。")
    selected = {name: default_material_path(name, detail) for name, _ in material_fields(detail)}
    if not any(selected.values()):
        raise ValueError("没有可自动匹配的材料，请使用单任务手工选择截图。")
    return selected


def material_fields(detail):
    """返回 (名称,必填)；与前端首次提交材料配置一致。"""
    kind = str(detail.get("taskType"))
    reward = detail.get("taskRewardDTO") or {}
    special = kind == "3" or (kind == "1" and detail.get("platformCode") in {"Weibo", "Tiktok"})
    fields = []
    if kind in {"2", "4"}:
        fields.extend((f"截图 {i}", False) for i in range(1, 5))
        if str(reward.get("category")) == "2" and str(reward.get("workDataSubmission")) == "1":
            fields.extend((name, False) for name in ("抖音创作中心-总览截图", "抖音创作中心-流量分析截图"))
    elif special:
        operation = str(reward.get("operationTarget"))
        if operation == "1":
            fields = [(item["name"], item.get("isRequired") != 2) for item in reward.get("taskRewardReferenceDTOList", [])]
        elif operation in OPERATIONS:
            fields = [(OPERATIONS[operation], True)]
        if not fields:
            raise ValueError("任务材料配置为空或未知，请先核对平台要求。")
    else:
        fields = [(f"截图 {i}", i == 1) for i in range(1, 5)]
    return fields


def image_label(name):
    return "" if name in {f"截图 {i}" for i in range(1, 5)} else name


class UploadService:
    """独立 Session，绝不携带平台登录头向对象存储上传。"""

    def upload(self, path, policy, report):
        try:
            parts = policy["token"].split(":")
            if len(parts) < 3:
                raise ValueError()
            access = parts[1] if len(parts) > 3 else parts[0]
            raw = parts[-1]
            decoded = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
            bucket = decoded["scope"].split(":")[0]
            if not access or not bucket:
                raise ValueError()
        except (ValueError, KeyError, TypeError, AttributeError):
            raise PlatformError("上传凭证格式无法解析。") from None
        try:
            with requests.Session() as session:
                response = session.get("https://api.qiniu.com/v2/query", params={"ak": access, "bucket": bucket}, timeout=20, allow_redirects=False)
                if response.status_code != 200:
                    raise PlatformError(f"上传域名查询 HTTP {response.status_code}。")
                host = response.json()["up"]["acc"]["main"][0]
                parsed = urlparse("https://" + host)
                if (parsed.username or parsed.password or parsed.port or parsed.path not in {"", "/"}
                        or parsed.query or parsed.fragment or not parsed.hostname
                        or not any(parsed.hostname.endswith("." + suffix) for suffix in ("qiniup.com", "qbox.me", "qiniu.com"))):
                    raise PlatformError("上传域名不符合预期，请核对七牛域名查询响应。")
                report(f"上传目标：{parsed.hostname}；文件：{path.name}（{path.stat().st_size:,} 字节）")
                with path.open("rb") as stream:
                    response = session.post(parsed.geturl(), data={"token": policy["token"], "key": policy["key"]},
                                            files={"file": (path.name, stream, mimetypes.guess_type(path.name)[0] or "application/octet-stream")},
                                            timeout=(20, 120), allow_redirects=False)
                if response.status_code != 200:
                    raise PlatformError(f"文件上传 HTTP {response.status_code}。")
                key = response.json().get("key")
                if not isinstance(key, str) or not key or key != policy["key"]:
                    raise PlatformError("上传响应 key 与签发凭证不一致。")
                return "/" + key.lstrip("/")
        except requests.RequestException:
            raise PlatformError("上传服务网络异常或超时，请查看当前步骤并重试。") from None
        except (KeyError, IndexError, ValueError, TypeError):
            raise PlatformError("上传服务响应格式不符合预期。") from None


class Workflow:
    def __init__(self, client, uploader=None):
        self.client = client
        self.uploader = uploader or UploadService()
        self.cache = {}
        self.uncertain = set()

    def run(self, detail, selected, link, emit):
        """emit(step,state,message)；失败停止，不自动重试任何写请求。"""
        step = STEPS[0]
        task_id = str(detail["taskId"])
        try:
            emit(step, "进行中", "校验文件及当前用户任务状态")
            if task_id in self.uncertain:
                raise PlatformError("上次提交结果不确定，请在平台核对审核状态，重新登录后再决定是否重试。")
            fields = material_fields(detail)
            if any(required and not selected.get(name) for name, required in fields):
                raise ValueError("缺少必填截图，请按任务要求选择材料。")
            paths = []
            for name, _ in fields:
                if selected.get(name):
                    path = Path(selected[name])
                    if not path.is_file() or path.stat().st_size == 0 or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
                        raise ValueError(f"材料“{name}”必须是存在且非空的图片文件。")
                    paths.append((name, path))
            parsed_link = urlparse(link.strip())
            if str(detail.get("taskType")) in {"2", "4"} and (parsed_link.scheme not in {"http", "https"} or not parsed_link.netloc):
                raise ValueError("原创任务需要填写有效的真实作品链接。")
            status = self.client.get_task_status(task_id)
            if str(status["status"]) not in {"0", "1"}:
                raise ValueError("任务不处于可领取/进行中状态，不能重复提交。")
            emit(step, "成功", f"材料 {len(paths)} 张，检查通过")
            step = STEPS[1]
            emit(step, "进行中", "检查是否已有领取单号")
            ticket = status.get("ticketId")
            if str(status["status"]) == "0" and not ticket:
                ticket = self.client.claim_task(task_id, reward=str(detail.get("rewardTaskFlag")) == "1")
                emit(step, "成功", f"领取成功，单号 {ticket}")
            elif ticket:
                emit(step, "成功", f"复用已领取单号 {ticket}")
            else:
                raise PlatformError("进行中任务缺少领取单号，请刷新状态。")
            policies = []
            step = STEPS[2]
            emit(step, "进行中", "逐文件获取临时上传凭证")
            for name, path in paths:
                fingerprint = (task_id, str(ticket), name, str(path.resolve()), path.stat().st_size, path.stat().st_mtime_ns)
                policy = None if fingerprint in self.cache else self.client.get_upload_policy(path.name)
                policies.append((name, path, fingerprint, policy))
                emit(step, "进行中", f"{name} ← {path.name}：{'复用已上传文件' if policy is None else '凭证已获取'}")
            emit(step, "成功", "上传凭证准备完成")
            step = STEPS[3]
            emit(step, "进行中", "开始上传文件")
            images = []
            for index, (name, path, fingerprint, policy) in enumerate(policies, 1):
                if fingerprint not in self.cache:
                    self.cache[fingerprint] = self.uploader.upload(path, policy, lambda msg: emit(step, "进行中", msg))
                images.append({"img": image_label(name), "url": self.cache[fingerprint]})
                emit(step, "进行中", f"{index}/{len(paths)} {name} 上传完成")
            emit(step, "成功", f"{len(images)} 张图片准备完成")
            step = STEPS[4]
            emit(step, "进行中", "发送提交审核请求")
            # 写入超时也可能已被服务器接收；禁止盲目重复提交。
            self.uncertain.add(task_id)
            self.client.submit_task(task_id, str(ticket), images, link=link.strip())
            self.uncertain.discard(task_id)
            emit(step, "成功", "平台已接收材料，等待审核（不代表审核通过）")
        except Exception as error:
            message = str(error) if isinstance(error, (PlatformError, ValueError)) else f"本地处理异常：{type(error).__name__}"
            emit(step, "失败", message)
            return False
        return True

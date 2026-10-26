"""读取本地登录凭证，环境变量优先。"""

import json
import os
from pathlib import Path


def load_token(config_path: Path | None = None) -> str:
    token = os.getenv("SAIC_TOKEN", "").strip()
    if token:
        return token
    path = config_path or Path.cwd() / "config.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise ValueError("请设置 SAIC_TOKEN、填写 config.json 的 token，或使用 --prompt。") from None
    except (OSError, ValueError):
        raise ValueError("无法读取配置，请检查文件权限及 JSON 格式。") from None
    token = config.get("token") if isinstance(config, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise ValueError("配置文件缺少非空字符串 token 字段。")
    return token.strip()

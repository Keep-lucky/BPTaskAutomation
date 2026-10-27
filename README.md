# XX平台任务工作台

通过 API 访问 XX平台，提供命令行查询和 `desktop.py` 桌面工作台，支持短信登录、任务查询、材料上传及提交审核。

本文使用 XX平台、示例域名和占位参数，不包含真实账号、凭证、任务编号或本机路径。示例域名不能直接用于请求；项目中的平台地址目前由 API 模块的 `BASE_URL` 常量定义，并非配置文件选项。

## 环境配置

基础功能需要 Python 3.10+、`requests` 和 Tkinter。推荐在 Windows 上创建独立虚拟环境；可选的微信自动化功能仅支持 Windows。

在项目根目录执行以下 PowerShell 命令，无需激活虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

检查 Tkinter 是否可用：

```powershell
.\.venv\Scripts\python.exe -m tkinter
```

出现测试窗口即表示可用。若提示缺少 `tkinter`，请通过 Python 安装程序安装 Tcl/Tk 组件；它不由 `requirements.txt` 安装。

### 登录配置

桌面端直接使用手机号和验证码登录，也支持在窗口中粘贴 Token，无需预先配置文件。Token 支持裸值或 `Bearer <TOKEN>` 格式，窗口不会将 Token 保存到配置文件。

命令行推荐使用 `--prompt` 隐藏输入 Token：

```powershell
.\.venv\Scripts\python.exe main.py --prompt
```

也可以复制配置模板，**仅在本机**填写有效凭证：

```powershell
Copy-Item config.example.json config.json
```

```json
{
  "token": "<TOKEN>"
}
```

随后执行 `main.py`，或用 `--config <配置文件路径>` 指定其他 JSON 文件。命令行还兼容代码中定义的 Token 环境变量，读取优先级为：显式 `--prompt` 输入 > 环境变量 > 配置文件。程序不会自动读取 `.env` 文件。

`config.json`、`.env`、虚拟环境、日志及本地图片材料已加入 `.gitignore`。示例配置保持空凭证。

## desktop.py 使用方法

启动桌面工作台：

```powershell
.\.venv\Scripts\python.exe desktop.py
```

### 登录与查询

1. 输入手机号，点击“获取验证码”，再输入收到的 6 位验证码，点击“短信登录”。发送成功后有 59 秒重发倒计时，失败后需手动重试。
2. 也可在“备用 Token”中粘贴凭证，点击“登录并加载任务”。
3. 选择任务状态及页码，点击“刷新列表”。状态包括任务广场、进行中、已完成、已失效。
4. 选中任务后点击“查看选中任务”，查看要求、领取状态、目标链接和材料字段。

### 单任务提交

1. 阅读任务要求，完成相应操作并准备真实材料。
2. 为材料字段选择本地截图，带 `*` 的字段为必填；原创任务还需填写有效作品链接。
3. 可先点击“调试预览（不领取、不上传、不提交）”，查看请求结构。
4. 勾选已真实完成任务的确认框，点击“一键领取、上传并提交审核”。
5. 在步骤树与日志中查看“检查材料 → 领取任务 → 获取上传凭证 → 上传文件 → 提交审核”的执行结果。

材料缺失时会在领取前停止；已有领取单号时复用。上传缓存仅在当前窗口内保留，文件大小及修改时间未变化时可复用成功上传的材料。提交成功表示进入审核，最终结果以 XX平台为准。

### 批量提交与材料目录

在任务列表左侧勾选多个任务，也可“全选本页”或“取消全选”。全选仅作用于当前页，刷新列表会清空勾选。

- 并发线程数默认为 3，可设置为 1–8，每个任务使用独立请求会话。
- 勾选任务后，提交按钮执行批量流程；未勾选时提交当前详情任务。
- 批量模式从对应平台目录匹配图片，不使用详情面板手动选择的材料或作品链接。
- 原创任务及无法自动匹配材料的任务需单独处理；单个任务失败不影响其他任务。

材料目录位于项目根目录，需要自行创建并放入真实图片：

```text
images/
├── wechat/
│   ├── like.jpg
│   ├── review.jpg
│   └── forward.jpg
├── toutiao/
│   └── ...
└── tiktok/
    └── ...
```

上述子目录对应任务的平台类型。点赞优先使用 `like.jpg`，评论优先使用 `review.jpg`，转发优先使用 `forward.jpg`；评论和转发的首选文件不存在时互相备选，含评论的组合材料使用评论图片。程序不会跨平台寻找材料，文件必须存在且非空。单任务可手动更换图片。

### 可选：微信文章操作

需要已登录的 Windows 微信客户端及与客户端版本匹配的 `wxauto4`。在同一个虚拟环境中安装可选依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-wechat.txt
.\.venv\Scripts\python.exe -c "from wxauto4 import WeChat; print('依赖导入成功')"
```

项目固定 `wxauto4==41.1.7`，使用前需自行核对客户端兼容性。`wxauto4` 官方适配到微信 4.1.8；微信 4.1.13 起主窗口改为自绘界面，不再向 UIA 暴露控件，因此无法自动发送链接，但仍可通过“当前文章执行并截图”操作已打开的文章窗口。缺少可选依赖时，其他任务功能仍可使用。

查看任务详情后，勾选“点赞”“在看”“准备朋友圈分享”，填写选填配文，再选择一种执行方式：

- **自动打开（需 wxauto4 能识别微信主窗口，客户端约为 4.1.8 及以下）**：确保微信主窗口已打开（仅保留托盘图标不够），点击“自动打开并截图”，程序向文件传输助手发送当前公众号文章链接并点击打开。
- **手动打开（微信 4.1.13+，含 4.1.15）**：先在微信中手动打开目标文章，确认只打开这一篇、并让文章窗口保持可见，再回到本工具点击“当前文章执行并截图”。程序通过文章底部互动栏识别唯一的文章窗口，不要求任务标题等于文章标题；若同时打开了多篇公众号文章会停止并提示关闭其他文章。

程序会在每项操作确认成功后立即截取对应窗口，保存到 `images/<平台>/`，并按任务材料名称自动填入提交材料：

- 点赞、在看：截取文章窗口，文件名带操作标识，例如 `470998190082_like_20261027_...png`（使用 ASCII 标识，避免上传文件名编码问题）。截图前会把文章窗口置前并最大化，再裁剪到显示器工作区（避免黑边和任务栏）；若无法置前则取消截图，避免截到其他窗口。
- 转发、朋友圈：截取朋友圈发布界面（按独立对话框的区域裁剪）。该界面是发表前的草稿，平台若要求“已发布公开页面”截图，请在微信发表后手动重新截图并替换；程序会在日志中提示。
- 评论、回帖、收藏、赞同：需要真实发布内容，微信自动化不执行这些操作，对应材料保持为空并提示手动补充。

只有名称能明确匹配的材料才会自动填入；未勾选或未成功生成截图的操作不会用其他截图顶替。朋友圈分享失败不会影响已完成的点赞/在看截图和材料填充，日志会提示手动补充。自动填入后仍需核对截图与任务要求，勾选确认框后再执行提交。批量模式仍从 `images/<平台>/` 目录匹配图片，不使用自动截图。

勾选“截图完成后自动提交审核”后，程序会在截图填入材料后自动执行当前详情任务的“检查材料 → 领取任务 → 获取上传凭证 → 上传文件 → 提交审核”，**不再弹出人工确认**。该选项默认关闭，只处理当前详情任务，不影响已勾选的批量任务；以下情况会跳过自动提交并在日志说明：未登录或详情失效、本次没有填入任何材料、必填材料仍为空。自动提交仍会在领取前校验材料，任务状态不允许提交时会在对应步骤停止。启用前请确认截图确实满足任务要求，因为提交会真实改变平台状态。

朋友圈功能仅准备分享界面和配文，需要在微信中确认可见范围并自行发表。操作期间请等待完成再切换聊天；状态无法确认时先查看客户端，避免重复操作。点赞、在看及自动截图已在微信 4.1.8.107 上完成实机验证；朋友圈分享尚未完成端到端验证。

## API 调用说明

### 请求约定

以下接口均相对于 XX平台服务地址，例如 `https://xx-platform.example`。JSON 请求使用 `Content-Type: application/json`；受保护的业务接口使用自定义认证头：

```http
Accept: application/json
authorize: Bearer <TOKEN>
```

认证字段名为 `authorize`。短信认证接口无需已有 Token。一般业务响应以 HTTP 200 且整数 `errcode` 为 0 表示成功，业务数据位于 `data`；登录验证还要求 `data.id` 非空。上传凭证接口另兼容直接返回 `token`、`key` 的响应。

### 接口与参数

| 功能 | 方法 | 路径 | 参数概要 |
| --- | --- | --- | --- |
| 发送短信验证码 | POST | `/api/front/system-auths/send-sms-code` | JSON：`phone`、`isUser: 1` |
| 短信登录 | POST | `/api/front/system-auths/phone-login` | JSON：`phone`、`code`，以及空字符串 `wxCode`、`openId`、`nickname`、`avatar` |
| 验证登录 | GET | `/api/front/mobile-users/show` | 认证头 |
| 查询任务列表 | POST | `/api/front/tasks/list` | JSON：`page`、`size`、`status` |
| 查询任务详情 | GET | `/api/front/tasks/show/{taskId}` | 路径参数 `taskId` |
| 查询领取状态 | GET | `/api/front/task-completions/task-status` | 查询参数 `taskId` |
| 领取任务 | POST | `/api/front/task-completions/claim/{taskId}` | 普通任务 JSON：`{}`；奖励任务：`{"rewardTaskFlag": 1}` |
| 获取上传凭证 | POST | `/api/front/oss/policy` | JSON：`fileName` |
| 提交审核 | POST | `/api/front/task-completions/submit` | JSON：`taskId`、`ticketId`、`imageUrls`，可选 `submitLink` |

任务列表的 `status` 使用字符串：`"0"` 为任务广场，`"1,2"` 为进行中/审核中，`"3"` 为已完成，`"5,4"` 为已失效/未通过。当前列表仅查询普通任务，不合并季度奖励任务列表。

### Python 查询示例

以下示例直接使用 `requests`，运行前将示例地址替换为实际服务地址。Token 在终端隐藏输入，示例仅输出任务总数：

```python
from getpass import getpass
import requests

base_url = "https://xx-platform.example"
token = getpass("Token（不含 Bearer 前缀）：").strip()

with requests.Session() as session:
    session.headers.update({
        "Accept": "application/json",
        "authorize": f"Bearer {token}",
        "Referer": f"{base_url}/",
    })
    response = session.post(
        f"{base_url}/api/front/tasks/list",
        json={"page": 1, "size": 20, "status": "0"},
        timeout=20,
        allow_redirects=False,
    )
    if response.status_code != 200:
        raise RuntimeError(f"请求失败：HTTP {response.status_code}")
    payload = response.json()
    if type(payload.get("errcode")) is not int or payload["errcode"] != 0:
        raise RuntimeError("业务请求失败，请检查登录状态和请求参数")
    print("任务总数：", payload.get("count", 0))
```

### 上传与提交顺序

先读取任务详情和领取状态，再校验材料；需要领取时取得 `ticketId`，随后按文件获取上传凭证，将图片上传到对象存储，最后提交材料。

文件上传使用独立会话，以 multipart 表单发送上传凭证 `token`、对象键 `key` 和 `file`，不向对象存储传递 XX平台登录头。上传目标由上传模块解析凭证并查询服务得到，不应把平台 API 地址作为文件上传地址。

提交参数中的 `imageUrls` 是 **JSON 序列化后的字符串**，其中每项包含 `img` 和 `url`。`img` 按任务要求匹配，`url` 使用上传结果对应的资源路径：

```json
{
  "taskId": "<TASK_ID>",
  "ticketId": "<TICKET_ID>",
  "imageUrls": "[{\"img\":\"点赞\",\"url\":\"/<UPLOADED_KEY>\"}]"
}
```

原创任务额外传入 `submitLink`。领取、上传和提交会改变远端状态；写请求没有自动重试。若提交超时或结果不确定，先在 XX平台核对状态，再决定后续操作。

## 命令行查询与验证

```powershell
# 查询任务列表，隐藏输入 Token
.\.venv\Scripts\python.exe main.py --prompt

# 查询进行中任务
.\.venv\Scripts\python.exe main.py --prompt --status active

# 分页查询已完成任务
.\.venv\Scripts\python.exe main.py --prompt --status completed --page 1 --size 20

# 查看任务详情、领取状态及请求预览；替换占位任务编号
.\.venv\Scripts\python.exe main.py --prompt --inspect-task "<TASK_ID>"

# 运行模拟接口测试
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`--status` 支持 `plaza`、`active`、`completed`、`expired`；`--page` 和 `--size` 必须为正整数。详情预览会读取远端数据，但不执行领取、上传或提交。命令行成功退出码为 0，失败为 1。

## 常见问题

- **登录失败或 HTTP 401/403**：重新登录并取得有效凭证；短信登录需先在 XX平台完成账号注册。
- **缺少必填截图**：检查任务要求、平台子目录和文件名，或在单任务详情中手动选择材料。
- **上传失败**：查看失败步骤及网络状态；领取成功后通常可复用领取单号。
- **提交结果不确定**：先到 XX平台核对审核状态，避免直接重复提交。
- **微信控件找不到或无法确认状态**：检查客户端与可选依赖兼容性，并在微信中核对文章窗口。微信 4.1.13+ 请手动打开文章后使用“当前文章执行并截图”，并确保只打开目标文章。

现有测试主要通过模拟请求验证逻辑，真实材料提交链路尚未完成端到端验证。


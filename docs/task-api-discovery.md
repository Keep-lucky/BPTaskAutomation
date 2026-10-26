# 任务领取、上传、提交接口调试记录

核查时间：2026-10-22。基址：`https://saic-px.saicmotor.com`。
平台请求使用 `authorize: Bearer <登录 Token>`，JSON 请求使用 `application/json`。

本次仅执行静态 JS 获取及任务详情/状态读取。领取、上传策略签发、文件上传、
提交审核、补充材料均未调用。表中“源码确认”表示从前端代码确认，尚未验证服务端响应。

## 接口清单

| 用途 | 方法与路径 | 参数 | 核查情况 |
| --- | --- | --- | --- |
| 普通任务列表 | POST `/api/front/tasks/list` | JSON：`page,size,status`，可选 `platforms:[{taskType,platformCodes}]` | 列表请求已观察；筛选来自源码 |
| 季度奖励列表 | GET `/api/front/tasks/season-reward/list` | 网页默认不传参数 | 请求已观察 |
| 季度奖励统计 | GET `/api/front/tasks/season-reward/stats` | 网页默认不传参数 | 请求已观察 |
| 任务详情及要求 | GET `/api/front/tasks/show/{taskId}` | 路径 taskId | 两条任务读取成功 |
| 当前用户任务状态 | GET `/api/front/task-completions/task-status` | Query：`taskId` | 两条任务读取成功，均为 status=0、ticketId=null |
| 获取已有领取单号 | GET `/api/front/task-completions/ticket-id` | Query：`taskId` | 源码确认 |
| 领取任务 | POST `/api/front/task-completions/claim/{taskId}` | 普通任务 JSON `{}`；奖励任务 `{"rewardTaskFlag":1}` | 源码确认，未执行 |
| 获取上传策略 | POST `/api/front/oss/policy` | JSON：`{"fileName":"截图.png"}` | 源码确认，未执行 |
| 解析七牛上传地址 | GET `https://api.qiniu.com/v2/query` | Query：`ak,bucket`，由上传 Token 解析 | 源码确认，未执行 |
| 图片文件直传 | POST `https://<查询响应 up.acc.main[0]>` | multipart：`token,key,file` | 源码确认，未执行 |
| 提交审核 | POST `/api/front/task-completions/submit` | JSON：`taskId,ticketId,imageUrls`，原创另传 `submitLink` | 源码确认，未执行 |
| 沟通/补充材料记录 | GET `/api/front/chat-messages` | Query：`taskCompletionId,taskId` | 页面请求已观察 |
| 追加补充材料 | POST `/api/front/chat-messages` | JSON：`content,taskId,taskCompletionId,contentUrl` | 源码确认，未执行 |
| 任务状态集合 | GET `/api/front/task-completions/statuses` | 通用参数透传，具体参数未确认 | 源码确认 |
| 剩余可领次数 | GET `/api/front/task-completions/remaining-counts` | Query：`taskId` | 源码确认 |
| 提交记录列表 | GET `/api/front/task-completions/submission-list` | 通用参数透传，具体分页/筛选字段未确认 | 源码确认 |
| 任务关联平台 | GET `/api/front/platforms/by-task-id` | Query：`taskId` | 源码确认 |
| 已绑定媒体账号 | GET `/api/front/mobile-user-platforms/list` | 通用参数透传，具体字段未确认 | 源码确认 |
| 平台/任务分类 | GET `/api/front/platforms/group-by-task-type` | 通用参数透传 | 源码确认 |

页面还包含 `GET /api/front/ai-comments/stats/{taskId}`、
`GET /api/front/ai-comments/claim/{taskId}`（领取评论，虽为 GET 也可能修改状态），
`POST /api/front/task-completions/increase-view-count`（`ticketId,openId`）。
这两个有副作用的接口没有调用，亦未通过打开分享页面触发计数。

## 调用顺序与字段

1. 从列表取 `taskId`，读取任务详情与当前用户状态。
2. 真实领取时调用 claim，前端将成功响应的 `data` 作为 `ticketId`，然后重新读取 task-status。
   该响应结构仅由源码确认。详情中的 `status` 不等同于当前用户领取状态；本次详情为 `"1"`，
   用户状态仍是 `0`，应以 task-status 为准。
3. 按详情里的 `taskDetailDTOS.articleBody`、`taskRewardDTO` 准备真实材料。
4. 对每个文件请求 policy。前端支持响应为 `{data:{token,key}}` 或 `{token,key}`。
   这里的 token 是临时上传凭证，与登录 Token 不同，不应混用或记录。
5. 上传 Token 按 `:` 分段：源码取 access key 为第一段（段数大于 3 时取第二段）；
   最后一段进行 URL-safe Base64 解码得到 JSON，其中 `scope` 冒号前的部分是 bucket。
   SDK 用 ak/bucket 查询域名，再选 `up.acc.main[0]`，协议默认为 HTTPS，实际域名尚未请求验证。
6. 使用新的上传连接，multipart 字段 `file` 是文件，`token/key` 来自 policy；
   不应把平台 `authorize` 登录头发送到七牛域名，也不应手写 multipart boundary。
7. 上传返回 JSON，前端读取 `key`，转换为 `"/" + key`。展示时前缀为
   `https://oss.sc.etkj.com.cn`；提交材料传相对路径。
8. submit 成功条件为 `errcode == 0`，之后可查询任务状态。

普通截图的提交示例（仅说明结构，不可直接提交）：

```json
{
  "taskId": "<任务 ID>",
  "ticketId": "<领取返回的单号>",
  "imageUrls": "[{\"img\":\"\",\"url\":\"/file/example.png\"}]"
}
```

`imageUrls` 是 **JSON 字符串**，不是 JSON 数组。分类截图的 `img` 为配置中的名称，
例如 `点赞`、`评论`。原创任务增加 `submitLink`；前端普通上传区最多 4 张，
分类上传区每个名称一张，后端文件类型/体积限制尚未验证。

补充材料使用另一个请求体：

```json
{
  "taskId": "<任务 ID>",
  "taskCompletionId": "<领取返回的单号>",
  "content": "<真实补充说明>",
  "contentUrl": "[{\"img\":\"评论\",\"url\":\"/file/example.png\"}]"
}
```

`contentUrl` 同样是字符串，图片为空时前端省略该字段。补充材料要求图片与文字至少一项。
首次提交使用 `ticketId`，补充材料使用 `taskCompletionId`，两者不要混淆。

## 根据要求选择材料

- 互动任务（taskType=3），或微博/抖音转发任务（taskType=1）：使用分类截图。
- `operationTarget=1`：使用 `taskRewardReferenceDTOList` 中的名称；
  前端校验逻辑为 `isRequired !== 2` 时必传，因此 null 也会按必填处理。
- operationTarget 其他映射：2 提高视频质量、3 转发+评论、4 评论、5 回帖、
  6 点赞、7 评论+点赞、8 赞同、9 喜欢、10 喜欢+评论、11 收藏、12 自定义。
- 原创任务 taskType=2/4：前端要求作品链接；页面文字另提示视频号二维码，但源码校验
  仍检查链接，二者存在差异，未实测前不推定二维码可替代链接。
- 原创的 `category=2,workDataSubmission=1` 还显示两种抖音创作中心截图；
  补充模式下 `countReward=1` 显示流量分析截图，或
  `category=2,workDataSubmission=2` 显示总览及流量分析截图。这些配置均标为 isRequired=2。

当前两条任务：

| taskId | 平台 | 页面文字要求 | 分类截图字段 img |
| --- | --- | --- | --- |
| 407447791006 | 今日头条 | 目标作品点赞并评论；评论大于 10 字、结合内容；完成后上传截图 | 点赞、评论 |
| 470998190082 | 微信 | 目标文章点赞并公开转发朋友圈，上传朋友圈公开页面截图 | 点赞、转发 |

两者 operationTarget 都为 `"1"`，参考配置的 isRequired 都为 null，按网页校验均必填。
本次两条任务用户状态均为未领取，没有获取到真实 ticketId。

## 本地只读调试

```powershell
.\.venv\Scripts\python.exe main.py --prompt --inspect-task 407447791006
```

该模式仅请求登录验证、任务详情和任务状态；输出要求以及带占位符的领取、上传、
提交请求预览，不会执行这些预览请求。预览是请求结构说明，不是完整的材料合规检查器。
该 CLI 调试入口不调用写入接口。后续桌面工作台已增加实际领取、上传、提交方法，
需要在窗口选择真实材料后点击执行；本记录中的“未执行”指接口发现阶段的核查情况。

## 前端证据

- `/static/js/index.9d56a878.js`：模块 21629，API 路径、HTTP 方法与导出映射。
- `/static/js/pages-task-detail.f4893187.js`：claimTask、getTaskStatus、submitTask。
- `/static/js/pages-task-submit.fb1457e7.js`：uploadConfigList、validateBeforeSubmit、
  chooseImage、operationChooseImage、submitTask、submitSupplement。
- `/static/js/6310.6cc521e1.js`：模块 36310，Zt（policy）、ee（上传）、st/et（域名解析）。
- `/static/js/pages-task-interaction-index.a477228d.js`：onLoad 先查 ticket-id，
  没有单号时自动调用 claim；调试时不直接打开此页面。

动态构建文件名可能变化。接口存在、参数来自源码，并不代表服务端已接受这些写入请求。

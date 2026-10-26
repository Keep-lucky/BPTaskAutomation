# 短信登录接口核查

核查日期：2026-10-22。使用 Playwright + 无头 Edge 打开真实登录页，读取加载脚本，并拦截页面点击产生的认证请求。所有认证请求在本地返回模拟失败响应，没有向服务器发送短信或尝试登录。

基址：`https://saic-px.saicmotor.com`。以下请求均为 POST，Content-Type 为 application/json。

## 获取验证码

路径：`/api/front/system-auths/send-sms-code`

```json
{"phone":"<用户手机号>","isUser":1}
```

页面手机号校验为 `^1[3-9]\d{9}$`。点击后倒计时从 59 开始，失败时清零。源码按 errcode=0 判断成功，显示 data；errcode=-1 引导注册，其他错误显示 errmsg。

## 验证码登录

路径：`/api/front/system-auths/phone-login`

```json
{"phone":"<用户手机号>","code":"<短信验证码>","wxCode":"","openId":"","nickname":"","avatar":""}
```

普通浏览器页面实际请求包含以上六个字段；验证码输入框最大长度为 6，源码仅检查非空。页面从入口参数获取 wxCode/openId，普通直达页面为空。

源码成功条件为 errcode=0，并读取 data.token 和 data.userRoleType。随后请求 `/api/front/mobile-users/show` 获取用户信息。现有项目可用 `SaicClient(token).validate_login()` 验证并衔接任务列表。

## 证据与限制

- `login-discovery/intercepted-requests.json`：本地拦截的实际页面请求，仅含测试占位值。
- `login-discovery/pages-login-login.b4deaba8.js.txt`：页面方法与字段源码片段。
- `login-discovery/index.9d56a878.js.txt`：接口定义等源码片段。
- 复现脚本：`browser/inspect_login.cjs`，使用本机 bundled Playwright 路径，运行需要可启动浏览器并访问网络。
- 当前普通登录页及其提交逻辑未观察到滑块或图形验证码；不排除服务端在特定条件触发额外校验。
- 未验证真实短信送达、成功登录响应、有效期、服务端频率限制或账号准入条件。响应字段与业务码解释来自源码，不能视为真实成功响应抓包。

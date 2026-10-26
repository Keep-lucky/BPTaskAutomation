// 在已登录的上汽平台页面，按 F12，在 Console 中粘贴本文件全部内容运行。
(async () => {
  "use strict";
  if (location.origin !== "https://saic-px.saicmotor.com") {
    alert("请在 https://saic-px.saicmotor.com/ 页面运行此脚本。");
    return;
  }

  // uni-app 的持久化值可能是裸字符串、JSON 字符串或 {data: ...}。
  function unwrap(value, depth = 0) {
    if (depth > 5 || value == null) return "";
    if (typeof value === "string") {
      const text = value.trim();
      if (!text) return "";
      try {
        return unwrap(JSON.parse(text), depth + 1);
      } catch {
        return text;
      }
    }
    if (typeof value === "object") {
      for (const key of ["token", "data", "value"]) {
        if (Object.prototype.hasOwnProperty.call(value, key)) {
          const result = unwrap(value[key], depth + 1);
          if (result) return result;
        }
      }
    }
    return "";
  }

  const candidates = [];
  try {
    if (typeof window.uni?.getStorageSync === "function") {
      candidates.push(window.uni.getStorageSync("token"));
    }
  } catch { /* 继续读取浏览器存储。 */ }
  for (const name of ["localStorage", "sessionStorage"]) {
    try {
      candidates.push(window[name].getItem("token"));
    } catch { /* 存储不可用时继续尝试其他来源。 */ }
  }

  const tokens = [...new Set(candidates.map(value => unwrap(value))
    .map(value => value.replace(/^Bearer\s+/i, "").trim())
    .filter(value => value && !/^bearer$/i.test(value) && !/\s/.test(value)))];
  if (!tokens.length) {
    alert("未找到登录 Token，请先登录平台，待页面加载完成后再次运行脚本。");
    return;
  }

  let token = "";
  for (const candidate of tokens) {
    try {
      const response = await fetch("/api/front/mobile-users/show", {
        headers: { authorize: `Bearer ${candidate}`, Accept: "application/json" },
        redirect: "error",
        signal: AbortSignal.timeout(15000),
      });
      if (response.status === 401 || response.status === 403) continue;
      if (!response.ok) throw new Error("接口异常");
      const body = await response.json();
      if (body.errcode === 0 && body.data?.id) {
        token = candidate;
        break;
      }
    } catch {
      alert("验证请求失败，请检查网络或稍后重新运行脚本。");
      return;
    }
  }
  if (!token) {
    alert("未找到通过验证的 Token，请重新登录平台后再次运行。");
    return;
  }

  const panelId = "saic-token-helper";
  document.getElementById(panelId)?.remove();
  const host = document.createElement("div");
  host.id = panelId;
  host.style.cssText = "position:fixed;inset:0;z-index:2147483647;display:grid;place-items:center;background:#0008";
  const root = host.attachShadow({ mode: "closed" });
  root.innerHTML = `
    <style>
      section{width:min(520px,85vw);padding:24px;background:white;color:#172033;border-radius:12px;font:15px/1.6 system-ui}
      h3{margin:0 0 12px}textarea{box-sizing:border-box;width:100%;height:110px;margin:12px 0;font:13px monospace}
      button{padding:8px 12px;margin:4px;cursor:pointer}p{margin:8px 0}
    </style>
    <section>
      <h3>登录 Token 验证成功</h3>
      <p>点击按钮复制，然后粘贴到 Python 程序的 Token 输入提示中。</p>
      <button data-kind="token">复制 Token</button>
      <button data-kind="authorize">复制 authorize 值</button>
      <button data-kind="close">关闭并清除</button>
      <textarea readonly aria-label="手动复制凭证" hidden></textarea>
      <p role="status">凭证仅在当前页面处理。</p>
    </section>`;
  const field = root.querySelector("textarea");
  const status = root.querySelector('[role="status"]');
  root.addEventListener("click", async event => {
    const kind = event.target.dataset?.kind;
    if (!kind) return;
    if (kind === "close") {
      token = "";
      field.value = "";
      host.remove();
      return;
    }
    const value = kind === "authorize" ? `Bearer ${token}` : token;
    try {
      await navigator.clipboard.writeText(value);
      field.hidden = true;
      field.value = "";
      status.textContent = "已复制，可粘贴到 Python 程序。";
    } catch {
      field.hidden = false;
      field.value = value;
      field.focus();
      field.select();
      status.textContent = "浏览器未允许自动复制，请按 Ctrl+C 手动复制选中内容。";
    }
  });
  document.body.appendChild(host);
})();

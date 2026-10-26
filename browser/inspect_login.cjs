const { chromium } = require('C:/Users/sky/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('fs');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage();
    const scripts = [];
    page.on('response', r => { if (/\.js(?:\?|$)/.test(r.url())) scripts.push(r); });
    await page.goto('https://saic-px.saicmotor.com/#/pages/login/login');
    await page.waitForTimeout(2500);
    console.log('PAGE', await page.locator('body').innerText());
    console.log('INPUTS', await page.locator('input').evaluateAll(es => es.map(e => ({placeholder:e.placeholder,type:e.type,maxLength:e.maxLength}))));
    const captured = [];
    await page.route('**/api/front/system-auths/**', async route => {
      const request = route.request();
      captured.push({url:request.url(), method:request.method(), contentType:request.headers()['content-type'], body:request.postDataJSON()});
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({errcode:1,errmsg:'本地拦截验证，未发送请求'})});
    });
    await page.locator('input').nth(0).fill('13800000000');
    await page.getByText('获取验证码', {exact:true}).click();
    await page.waitForTimeout(300);
    await page.locator('input').nth(1).fill('000000');
    await page.getByText('立即登录', {exact:true}).click();
    await page.waitForTimeout(300);
    fs.mkdirSync('docs/login-discovery', {recursive:true});
    fs.writeFileSync('docs/login-discovery/intercepted-requests.json',JSON.stringify(captured,null,2));
    console.log('INTERCEPTED_ONLY', JSON.stringify(captured));
    for (const response of scripts) {
      const source = await response.text();
      if (source.length > 3000000) continue;
      const pattern = /验证码|mobile-users|sms|sendCode|phoneLogin|\/login|captcha/gi;
      let match;
      const snippets = [];
      while ((match = pattern.exec(source))) snippets.push(source.slice(Math.max(0,match.index-400), match.index+650));
      if (snippets.length) {
        console.log('SCRIPT', response.url(), 'MATCHES', snippets.length);
        fs.mkdirSync('docs/login-discovery', {recursive:true});
        fs.writeFileSync('docs/login-discovery/'+new URL(response.url()).pathname.split('/').pop()+'.txt',snippets.join('\n\n'));
      }
    }
  } finally { await browser.close(); }
})().catch(e=>{console.error(e.message);process.exitCode=1;});

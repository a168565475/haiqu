/** 手机企微入口只读检查：真实匿名 API；授权导航在发出前阻断，不模拟 API。 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('../src/frontend/node_modules/playwright-core');

const root = path.resolve(__dirname, '..');
const evidence = path.join(root, 'qa/mobile_wecom_20261102');
const runtime = path.join(root, 'qa/_tmp/mobile-wecom-readonly-20261102');
const base = 'http://localhost:8082';
const report = {
  status: 'RUNNING', mode: 'anonymous-real-api-read-only', checks: [],
  resources: { runtime, created: false, browser_closed: false, verified_absent: false },
  not_covered: ['真实企业微信 OAuth 身份交换', '真实成员授权等待及授权后回跳', '生产发布及企业微信入口配置'],
};
let browser, ownsRuntime = false;
const errors = [], blockedWrites = [], oauthTargets = [];
function check(name, passed, detail) {
  report.checks.push({ name, passed: Boolean(passed), ...(detail === undefined ? {} : { detail }) });
  assert.ok(passed, name);
}
async function context(options = {}) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: 'zh-CN', serviceWorkers: 'block', acceptDownloads: false, ...options });
  await ctx.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      blockedWrites.push({ method: request.method(), path: url.pathname });
      return route.abort('blockedbyclient');
    }
    if (url.origin !== base) return route.abort('blockedbyclient');
    if (url.pathname === '/api/auth/wecom/start/') {
      oauthTargets.push(url.searchParams.get('next'));
      return route.abort('blockedbyclient');
    }
    return route.continue();
  });
  return ctx;
}
async function layout(page, label) {
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    const dimensions = await page.evaluate(() => ({ viewport: innerWidth, content: document.documentElement.scrollWidth, buttons: [...document.querySelectorAll('button')].map(el => el.getBoundingClientRect().height) }));
    check(`${label} ${width}px 无横向溢出且按钮可触达`, dimensions.content <= dimensions.viewport && dimensions.buttons.every(height => height >= 44), dimensions);
    if (width === 390) await page.screenshot({ path: path.join(evidence, `${label}-390.png`), fullPage: true });
  }
}
async function main() {
  fs.mkdirSync(evidence, { recursive: true });
  // 创建前保存完整路径、归属及清理办法，禁止接管既有目录。
  fs.writeFileSync(path.join(evidence, 'browser-resources.json'), JSON.stringify({ owner: 'mobile-wecom-20261102', runtime, purpose: 'headless browser temporary files', cleanup: 'close browser; verify exact resolved path; remove owned runtime; verify absent' }, null, 2));
  assert.ok(!fs.existsSync(runtime), '临时目录已存在，不能覆盖');
  const executablePath = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
  assert.ok(executablePath, '需要现有 Chrome 或 Edge');
  fs.mkdirSync(runtime, { recursive: true });
  ownsRuntime = true; report.resources.created = true;
  browser = await chromium.launch({ executablePath, headless: true, env: { ...process.env, TEMP: runtime, TMP: runtime, TMPDIR: runtime } });
  const ordinary = await context();
  const page = await ordinary.newPage();
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => errors.push(error.message));
  const me = await ordinary.request.get(`${base}/api/auth/me/`);
  check('真实 ERP 会话接口返回匿名', me.status() === 200 && (await me.json()).authenticated === false);
  const plans = await ordinary.request.get(`${base}/api/v1/workshop-mobile/plans/`);
  check('真实计划 API 拒绝匿名读取', [401, 403].includes(plans.status()));
  await page.goto(`${base}/m/plan?id=read-only-navigation`);
  await page.waitForURL(url => url.pathname === '/m/login');
  await page.getByRole('heading', { name: '登录工作账号' }).waitFor();
  check('普通浏览器保留手机目标并使用密码登录', new URL(page.url()).searchParams.get('redirect') === '/plan?id=read-only-navigation' && oauthTargets.length === 0);
  check('普通浏览器无 WebView OAuth 按钮', await page.getByRole('button', { name: '使用企业微信登录' }).count() === 0);
  await layout(page, 'login');

  await page.goto(`${base}/m/auth/wecom-error?reason=BINDING_REQUIRED&next=%2Fm%2Freport%3Fplan%3Dread-only-navigation`);
  await page.getByRole('heading', { name: '企业微信登录未完成' }).waitFor();
  check('错误页显示固定的绑定提示', (await page.textContent('main')).includes('成员身份需要管理员核对关联'));
  check('错误页无脚本参数泄露', !(await page.textContent('main')).includes('read-only-navigation'));
  await layout(page, 'wecom-error');
  await page.getByRole('button', { name: '使用 ERP 账号登录', exact: true }).click();
  await page.waitForURL(url => url.pathname === '/m/login');
  check('错误页密码恢复保留手机业务目标', new URL(page.url()).searchParams.get('redirect') === '/report?plan=read-only-navigation');
  await page.goto(`${base}/m/auth/waiting-role?next=%2Fm%2Freport%3Fplan%3Dread-only-navigation`);
  await page.waitForURL(url => url.pathname === '/m/login');
  check('匿名用户不能伪装等待授权身份', oauthTargets.length === 0);

  const wecom = await context({ userAgent: 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 MicroMessenger/8.0 wxwork/4.1' });
  const mobile = await wecom.newPage();
  mobile.setDefaultTimeout(15000);
  mobile.on('pageerror', error => errors.push(error.message));
  const authorization = mobile.waitForRequest(request => new URL(request.url()).pathname === '/api/auth/wecom/start/');
  const authorizationBlocked = mobile.waitForEvent('requestfailed', request => new URL(request.url()).pathname === '/api/auth/wecom/start/');
  await mobile.goto(`${base}/m/report?plan=read-only-navigation`);
  const attempted = new URL((await authorization).url());
  await authorizationBlocked;
  check('企微入口指向同源授权且带完整手机深链', attempted.origin === base && attempted.searchParams.get('next') === '/m/report?plan=read-only-navigation', { path: attempted.pathname, next: attempted.searchParams.get('next') });
  // 等浏览器完成被阻断的顶层导航，不能与错误页提交竞争下一次 goto。
  await mobile.waitForFunction(() => document.documentURI.startsWith('chrome-error://'));
  await mobile.goto(`${base}/m/report?plan=read-only-navigation`);
  await mobile.waitForURL(url => url.pathname === '/m/login');
  await mobile.getByRole('button', { name: '使用企业微信登录', exact: true }).waitFor();
  check('回跳仍匿名时不循环授权，可手动重试', oauthTargets.length === 1);
  await layout(mobile, 'wecom-fallback');
  check('无前端运行时错误', errors.length === 0, errors);
  check('没有写请求；真实 OAuth 已在客户端阻断', blockedWrites.length === 0 && oauthTargets.length === 1);
  report.status = 'PASS_WITH_GAPS';
}
(async () => {
  try { await main(); }
  catch (error) { report.status = 'FAIL'; report.failure = error.message; }
  finally {
    try {
      if (browser) { await browser.close(); report.resources.browser_closed = true; }
      if (ownsRuntime) {
        const resolved = fs.realpathSync(runtime);
        assert.equal(resolved.toLowerCase(), path.resolve(root, 'qa/_tmp/mobile-wecom-readonly-20261102').toLowerCase(), '临时目录越界');
        fs.rmSync(resolved, { recursive: true, force: false });
      }
      report.resources.verified_absent = !fs.existsSync(runtime);
      assert.ok(report.resources.verified_absent && (!browser || report.resources.browser_closed), '资源未清理');
    } catch (error) { report.status = 'FAIL'; report.cleanup_failure = error.message; }
    fs.writeFileSync(path.join(evidence, 'browser.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
    process.exitCode = report.status === 'PASS_WITH_GAPS' ? 0 : 1;
  }
})();

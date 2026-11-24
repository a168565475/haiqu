/** 手机端匿名真实 API 与登录门禁检查；不登录、不写业务、不拦截替换 API 数据。 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('../src/frontend/node_modules/playwright-core');

const root = path.resolve(__dirname, '..');
const evidence = path.join(root, 'qa/mobile_workshop_20261031');
const runtime = path.join(root, 'qa/_tmp/mobile-workshop-anonymous-20261031');
const base = 'http://localhost:8082';
const report = {
  qa_result_version: 1, status: 'RUNNING', mode: 'anonymous-real-api-read-only',
  started_at: new Date().toISOString(), checks: [], screenshots: [],
  not_covered: ['普通车间账号登录后的计划、材料及报工页面真实数据验收', '真实领料申请、仓库确认及多人报工写入闭环', '手机真机与局域网访问'],
  resources: { runtime, created: false, browser_closed: false, removed: false, verified_absent: false },
  cleanup: false,
};
let browser;
let ownsRuntime = false;
const pageErrors = [];
const writes = [];
function check(name, passed, detail) {
  report.checks.push({ name, passed: Boolean(passed), ...(detail === undefined ? {} : { detail }) });
  assert.ok(passed, name);
}

async function main() {
  const executablePath = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
  assert.ok(executablePath, '需要现有 Chrome 或 Edge');
  assert.ok(!fs.existsSync(runtime), '临时目录已存在，不能覆盖其他任务资源');
  fs.mkdirSync(runtime, { recursive: true });
  ownsRuntime = true;
  report.resources.created = true;
  browser = await chromium.launch({ executablePath, headless: true, env: { ...process.env, TEMP: runtime, TMP: runtime, TMPDIR: runtime } });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, locale: 'zh-CN', timezoneId: 'Asia/Shanghai', serviceWorkers: 'block', acceptDownloads: false });
  await context.route('**/*', async route => {
    const request = route.request();
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      writes.push({ method: request.method(), path: new URL(request.url()).pathname });
      await route.abort('blockedbyclient');
      return;
    }
    if (new URL(request.url()).origin !== base) { await route.abort('blockedbyclient'); return; }
    await route.continue();
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => pageErrors.push(error.message));
  const me = await context.request.get(`${base}/api/auth/me/`);
  check('匿名认证状态使用真实 API', me.status() === 200 && (await me.json()).authenticated === false, { status: me.status() });
  check('服务端发放 CSRF Cookie', (await context.cookies(base)).some(cookie => cookie.name === 'csrftoken'));
  const plans = await context.request.get(`${base}/api/v1/workshop-mobile/plans/`);
  check('未登录不能读取生产计划', [401, 403].includes(plans.status()), { status: plans.status() });

  for (const target of ['', 'plan', 'issue', 'issue-records', 'report', 'report-records']) {
    await page.goto(`${base}/m/${target}`);
    await page.waitForURL(url => url.pathname === '/m/login');
    await page.getByRole('heading', { name: '登录工作账号' }).waitFor();
    check(`路由 ${target || 'index'} 先要求登录`, await page.getByRole('heading', { name: '登录工作账号' }).isVisible());
  }
  for (const width of [320, 390, 768]) {
    await page.setViewportSize({ width, height: 844 });
    const dimensions = await page.evaluate(() => ({
      viewport: innerWidth, content: document.documentElement.scrollWidth,
      button: document.querySelector('button[type="submit"]').getBoundingClientRect().height,
      inputs: [...document.querySelectorAll('input')].map(input => ({ width: input.getBoundingClientRect().width, font: Number.parseFloat(getComputedStyle(input).fontSize) })),
    }));
    check(`${width}px 登录页无横向溢出`, dimensions.content <= dimensions.viewport, dimensions);
    check(`${width}px 登录控件可触达`, dimensions.button >= 44 && dimensions.inputs.every(input => input.width >= 100 && input.font >= 16));
    const screenshot = `login-${width}.png`;
    await page.screenshot({ path: path.join(evidence, screenshot), fullPage: true });
    report.screenshots.push(screenshot);
  }
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.getByText('请输入账号', { exact: true }).waitFor();
  check('空表单本地提示必填且未发登录请求', writes.length === 0);
  check('没有前端运行时错误', pageErrors.length === 0, pageErrors);
  check('全程没有写请求', writes.length === 0, writes);
  report.status = 'PASS_WITH_GAPS';
}

(async () => {
  try { await main(); }
  catch (error) { report.status = 'FAIL'; report.failure = { message: error.message }; }
  finally {
    try {
      if (browser) { await browser.close(); report.resources.browser_closed = true; }
      if (ownsRuntime) {
        const resolved = fs.realpathSync(runtime);
        assert.equal(resolved.toLowerCase(), path.resolve(root, 'qa/_tmp/mobile-workshop-anonymous-20261031').toLowerCase(), '临时目录解析后越界');
        fs.rmSync(resolved, { recursive: true, force: false });
        report.resources.removed = true;
      }
      report.resources.verified_absent = !fs.existsSync(runtime);
      report.cleanup = report.resources.verified_absent && (!browser || report.resources.browser_closed);
      assert.ok(report.cleanup, '临时资源未清理');
    } catch (error) { report.status = 'FAIL'; report.failure = { message: `清理失败：${error.message}` }; }
    report.finished_at = new Date().toISOString();
    fs.writeFileSync(path.join(evidence, 'anonymous-browser.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
    process.exitCode = report.status === 'PASS_WITH_GAPS' ? 0 : 1;
  }
})();

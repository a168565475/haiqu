// 真实本地应用的只读布局验收；不打开设计预览、不提交登录或扫码请求。
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('../src/frontend/node_modules/playwright-core');
const root = path.resolve(__dirname, 'wecom_qr_20261019');
const runtime = path.join(root, 'runtime');
const origin = 'http://127.0.0.1:8080';
const report = { scope: '真实本地页面与GET接口；未提交登录、未获取二维码，不代表真实扫码验收', checks: [], screenshots: [], cleanup: {} };
let browser, runtimeCreated = false;
function check(name, actual) { report.checks.push({ name, passed: !!actual }); assert(actual, name); }
async function screenshot(page, name) { await page.screenshot({ path: path.join(root, name), fullPage: true }); report.screenshots.push(name); }

(async () => {
  fs.mkdirSync(root, { recursive: true });
  assert(!fs.existsSync(runtime), '登记的runtime必须不存在，禁止覆盖其他任务资源');
  fs.mkdirSync(runtime);
  runtimeCreated = true;
  browser = await chromium.launchPersistentContext(path.join(runtime, 'profile'), {
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true,
    viewport: { width: 1440, height: 900 }, reducedMotion: 'no-preference',
  });
  const forbidden = [], errors = [], meResponses = [];
  await browser.route('**/*', route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== origin || !['GET', 'HEAD'].includes(request.method())) {
      forbidden.push(request.method() + ' ' + url.origin + url.pathname);
      return route.abort('blockedbyclient');
    }
    return route.continue();
  });
  const page = await browser.newPage();
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => {
    if (new URL(response.url()).pathname === '/api/auth/me/') meResponses.push(response.status());
  });
  await page.goto(origin + '/login', { waitUntil: 'networkidle' });
  await page.locator('#login-username').waitFor();
  check('真实会话查询接口成功', meResponses.includes(200));
  check('保留账号密码输入', await page.locator('#login-password').isEditable());
  check('普通浏览器提供扫码切换', await page.getByRole('button', { name: '切换企业微信扫码登录', exact: true }).isVisible());
  const brand = await page.locator('.login-brand').innerText();
  check('Logo仅保留HiTree字标', brand.trim() === 'HiTree');
  check('插画加载', await page.locator('.flow-image').evaluate(img => img.complete && img.naturalWidth === 1448));

  const motion = await page.evaluate(async () => {
    const samples = [], start = performance.now();
    while (performance.now() - start < 11000) {
      samples.push({ offset: getComputedStyle(document.querySelector('.flow-trail')).strokeDashoffset,
        nodes: [...document.querySelectorAll('.flow-node')].map(node => Number(getComputedStyle(node).opacity)) });
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    return samples;
  });
  check('光流持续移动', new Set(motion.map(sample => sample.offset)).size > 10);
  check('四个节点均依次点亮', [0, 1, 2, 3].every(index => motion.some(sample => sample.nodes[index] > 0.4)));
  check('不会全部同时点亮', motion.every(sample => sample.nodes.filter(opacity => opacity > 0.4).length <= 1));
  report.motion = motion;
  await page.emulateMedia({ reducedMotion: 'reduce' });
  check('减少动态效果设置生效', await page.locator('.flow-trail').evaluate(el => getComputedStyle(el).animationName === 'none'));
  for (const [width, height] of [[1440, 900], [1920, 1080], [390, 844]]) {
    await page.setViewportSize({ width, height });
    const layout = await page.evaluate(() => {
      const button = document.querySelector('.login-button'), rect = button.getBoundingClientRect();
      return { width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth,
        submit: { x: rect.x, right: rect.right, bottom: rect.bottom },
        inputHeight: document.querySelector('#login-username').getBoundingClientRect().height,
        buttonHeight: rect.height };
    });
    check(width + 'px无横向溢出', layout.scrollWidth <= width);
    check(width + 'px登录按钮完整可见', layout.submit.x >= 0 && layout.submit.right <= width && layout.submit.bottom <= height);
    check(width + 'px输入框60px/按钮56px', Math.abs(layout.inputHeight - 60) <= 1 && Math.abs(layout.buttonHeight - 56) <= 1);
    report.checks.push({ name: width + 'px布局实测', passed: true, actual: layout });
    await screenshot(page, 'login-password-' + width + '.png');
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(origin + '/auth/wecom-error?reason=STATE_INVALID', { waitUntil: 'networkidle' });
  check('浏览器错误页提示重新扫码', (await page.locator('main').innerText()).includes('重新扫码'));
  await screenshot(page, 'wecom-error-browser.png');
  check('无业务或认证写请求/外部请求', forbidden.length === 0);
  check('无页面JS异常', errors.length === 0);
  report.forbiddenRequests = forbidden; report.pageErrors = errors;
  report.status = 'PASS_WITH_GAPS';
})().catch(error => { report.status = 'FAIL'; report.error = error.message; process.exitCode = 1; })
  .finally(async () => {
    if (browser) await browser.close();
    assert(runtime === path.join(path.resolve(root), 'runtime'));
    if (runtimeCreated && fs.existsSync(runtime)) {
      assert(!fs.lstatSync(runtime).isSymbolicLink(), 'runtime归属发生变化，停止删除');
      fs.rmSync(runtime, { recursive: true });
    }
    report.cleanup = { browserClosed: true, runtimeRemoved: !fs.existsSync(runtime), businessWrites: 0 };
    fs.writeFileSync(path.join(root, 'readonly-page-checks.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ qa_result_version: 1, status: report.status,
      not_covered: ['真实企业微信扫码与身份回调', '扫码面板及登录后的实际页面：本脚本只允许匿名GET'],
      checks: report.checks.length, cleanup: report.cleanup.runtimeRemoved,
      failure: report.error ? { message: report.error } : undefined }));
  });

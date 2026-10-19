// 仅配合 test_browser_fixture 的独占测试库运行；不替代真实企业微信验收。
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('../src/frontend/node_modules/playwright-core');
const root = path.join(__dirname, 'wecom_phase1_20261019');
const runtime = path.join(root, 'page_runtime');
const control = path.join(runtime, 'ready.json');
const apiOrigin = 'http://127.0.0.1:18591';
const webOrigin = 'http://127.0.0.1:8080';
const checks = [], screenshots = [], runtimeErrors = [];
let context;
function check(name, condition, actual) { checks.push({ name, passed: !!condition, actual }); assert.ok(condition, name); }
async function screenshot(page, name) { await page.screenshot({ path: path.join(root, name + '.png'), fullPage: true }); screenshots.push(name + '.png'); }
async function main() {
  if (!fs.existsSync(control)) throw new Error('隔离API服务尚未就绪；禁止回退到业务API。');
  const fixture = JSON.parse(fs.readFileSync(control, 'utf8'));
  assert.equal(fixture.port, 8000);
  assert.equal(fixture.accounts.waiting.username, 'wecom_qa_waiting');
  context = await chromium.launchPersistentContext(path.join(runtime, 'browser'), {
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true, viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce',
  });
  let failConfig = false;
  await context.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url());
    if (failConfig && url.pathname === '/api/v1/wecom/config/') return route.abort('failed');
    if (route.request().method() === 'POST' && !['/api/auth/login/', '/api/auth/logout/'].includes(url.pathname)) {
      throw new Error('隔离页面检查禁止第三方连接、绑定或其他业务提交：' + url.pathname);
    }
    await route.continue({ url: apiOrigin + url.pathname + url.search });
  });
  const page = context.pages()[0];
  page.on('pageerror', error => runtimeErrors.push(error.message));
  page.setDefaultTimeout(60000);
  await page.goto(webOrigin + '/settings/wecom', { waitUntil: 'domcontentloaded' });
  await page.locator('#login-username').fill(fixture.accounts.admin.username);
  await page.locator('#login-password').fill(fixture.accounts.admin.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.locator('#wecom-corp').waitFor();
  check('管理页深链接经过真实Session登录后返回', new URL(page.url()).pathname === '/settings/wecom');
  check('企业ID来自实际API', await page.locator('#wecom-corp').inputValue() === 'ww08890a52e3ab432d');
  check('消息回调状态常驻且内容默认折叠', await page.locator('.callback-card').getAttribute('open') === null);
  await screenshot(page, 'actual_config_1440');
  for (const [width, height] of [[1920, 1080], [1440, 1000], [1024, 900], [390, 844]]) {
    await page.setViewportSize({ width, height });
    const style = await page.evaluate(() => {
      const input = document.querySelector('#wecom-secret');
      const card = document.querySelector('.config-grid .content-card');
      const inputStyle = getComputedStyle(input), cardStyle = getComputedStyle(card);
      return { scroll: document.documentElement.scrollWidth, viewport: innerWidth, inputHeight: input.getBoundingClientRect().height,
        radius: inputStyle.borderRadius, cardBorders: ['Top', 'Right', 'Bottom', 'Left'].map(side => cardStyle['border' + side + 'Width']),
        gridColumns: getComputedStyle(document.querySelector('.config-grid')).gridTemplateColumns,
        font: getComputedStyle(document.querySelector('.wecom-page h1')).fontSize,
        fontFamily: getComputedStyle(document.querySelector('.wecom-page h1')).fontFamily,
        lineHeight: getComputedStyle(document.querySelector('.wecom-page h1')).lineHeight,
        weight: getComputedStyle(document.querySelector('.wecom-page h1')).fontWeight };
    });
    check(width + '配置页无整页横溢出', style.scroll <= style.viewport, style);
    check(width + '控件32px圆角8px且卡片单层边框', style.inputHeight === 32 && style.radius === '8px' && style.cardBorders.every(value => value === '1px'), style);
    check(width + '标题符合已确认桌面与移动规则', style.font === (width <= 640 ? '28px' : '36px') && style.lineHeight === (width <= 640 ? '38px' : '44px') && style.weight === '700' && !/Noto Serif|SimSun|宋体/i.test(style.fontFamily), style);
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.locator('.callback-card summary').click();
  check('Token与AES均为密码输入', await page.locator('#wecom-token').getAttribute('type') === 'password' && await page.locator('#wecom-aes').getAttribute('type') === 'password');
  const testToken = 'IsolatedCallback123', testAes = 'A'.repeat(43);
  await page.locator('#wecom-token').fill(testToken);
  await page.locator('#wecom-aes').fill(testAes);
  const saved = page.waitForResponse(response => response.url().includes('/api/v1/wecom/config/') && response.request().method() === 'PATCH');
  await page.getByRole('button', { name: '保存配置', exact: true }).click();
  const saveResponse = await saved, saveData = await saveResponse.json();
  check('真实Session+CSRF保存回调凭据', saveResponse.status() === 200 && saveData.data.has_callback_token && saveData.data.has_callback_aes_key);
  check('配置响应不回传凭据', !JSON.stringify(saveData).includes(testToken) && !JSON.stringify(saveData).includes(testAes));
  check('保存后清空凭据输入', await page.locator('#wecom-token').inputValue() === '' && await page.locator('#wecom-aes').inputValue() === '');
  await screenshot(page, 'actual_callback_credentials_1440');
  const csrf = (await context.cookies(apiOrigin)).find(cookie => cookie.name === 'csrftoken')?.value;
  assert.ok(csrf);
  const rejectedCsrf = await context.request.patch(apiOrigin + '/api/v1/wecom/config/', { data: { enabled: false }, headers: { 'If-Match': saveResponse.headers().etag } });
  check('缺失CSRF真实API拒绝', rejectedCsrf.status() === 403);
  const rejectedVersion = await context.request.patch(apiOrigin + '/api/v1/wecom/config/', { data: { enabled: false }, headers: { 'X-CSRFToken': csrf, 'If-Match': '"stale"' } });
  check('过期ETag真实API拒绝', rejectedVersion.status() === 412);
  await page.getByRole('tab', { name: '员工绑定' }).click();
  await page.getByRole('cell', { name: /隔离测试待授权员工/ }).waitFor();
  const tableStyle = await page.evaluate(() => {
    const frame = document.querySelector('.table-frame'), header = frame.querySelector('th'), first = frame.querySelector('tbody td'), last = frame.querySelector('tbody td:last-child');
    const s = element => getComputedStyle(element);
    return { frameBorders: ['Top', 'Right', 'Bottom', 'Left'].map(side => s(frame)['border' + side + 'Width']),
      headerHeight: header.getBoundingClientRect().height, rowHeight: first.getBoundingClientRect().height,
      headerColor: s(header).backgroundColor, gridColor: s(header).borderBottomColor, padding: s(first).paddingLeft,
      cellBorders: [...frame.querySelectorAll('tbody td')].map(cell => ['Top','Right','Bottom','Left'].map(side => s(cell)['border' + side + 'Width'])),
      firstBottom: s(first).borderBottomWidth, lastRight: s(last).borderRightWidth, scrollWidth: frame.scrollWidth, width: frame.clientWidth };
  });
  check('表格四边仅外框负责', tableStyle.frameBorders.every(value => value === '1px') && tableStyle.firstBottom === '0px' && tableStyle.lastRight === '0px', tableStyle);
  check('表头行高和内边距沿用预览', Math.abs(tableStyle.headerHeight - 38) <= 1 && tableStyle.rowHeight >= 40 && tableStyle.padding === '16px', tableStyle);
  check('表头及内部网格颜色沿用主题', tableStyle.headerColor === 'rgb(216, 233, 247)' && tableStyle.gridColor === 'rgb(220, 235, 245)', tableStyle);
  check('单行首末单元格不叠加外边', tableStyle.cellBorders.every((b, i, all) => b[0] === '0px' && b[2] === '0px' && b[3] === '0px' && b[1] === (i === all.length - 1 ? '0px' : '1px')), tableStyle);
  check('1440表格无多余横向滚动', tableStyle.scrollWidth <= tableStyle.width, tableStyle);
  await screenshot(page, 'actual_bindings_1440');
  await page.getByRole('button', { name: '绑定已有员工', exact: true }).click();
  await page.locator('#wecom-employee option').filter({ hasText: '隔离测试管理员' }).waitFor({ state: 'attached' });
  check('绑定未确认时不可提交', await page.getByRole('button', { name: '确认绑定', exact: true }).isDisabled());
  await screenshot(page, 'actual_binding_dialog_1440');
  await page.setViewportSize({ width: 390, height: 844 });
  const dialogFits = await page.getByRole('dialog').evaluate(element => {
    const rect = element.getBoundingClientRect(); return { left: rect.left, right: rect.right, viewport: innerWidth };
  });
  check('390绑定弹窗不溢出视口', dialogFits.left >= 0 && dialogFits.right <= dialogFits.viewport, dialogFits);
  await screenshot(page, 'actual_binding_dialog_390');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('button', { name: '取消', exact: true }).click();
  await page.getByRole('button', { name: '绑定记录', exact: true }).click();
  await page.getByText('隔离浏览器集成测试数据，不是真实企业微信身份。', { exact: true }).waitFor();
  check('审计页面来自真实测试API且不含密钥', !(await page.locator('.wecom-dialog-content').last().textContent()).includes(testToken));
  await screenshot(page, 'actual_audit_1440');
  await page.getByRole('button', { name: '关闭', exact: true }).last().click();
  await page.getByRole('textbox', { name: '搜索成员' }).fill('NO_SUCH_ISOLATED_MEMBER');
  await page.getByRole('button', { name: '查询', exact: true }).click();
  await page.locator('.empty-cell').waitFor();
  check('空数据使用真实查询结果', (await page.locator('.empty-cell').textContent()).includes('暂无'));
  await screenshot(page, 'actual_empty_1440');
  failConfig = true;
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.getByText('暂时无法加载配置', { exact: true }).waitFor();
  check('网络失败显示明确状态且不假报成功', await page.getByRole('button', { name: '保存配置', exact: true }).isDisabled());
  await screenshot(page, 'actual_network_error_1440');
  failConfig = false;
  await page.getByRole('button', { name: '重新加载配置', exact: true }).click();
  await page.locator('#wecom-corp').waitFor();
  check('网络恢复可重新读取', true);
  await context.clearCookies();
  await page.goto(webOrigin + '/login', { waitUntil: 'domcontentloaded' });
  await page.locator('#login-username').fill(fixture.accounts.waiting.username);
  await page.locator('#login-password').fill(fixture.accounts.waiting.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.getByRole('heading', { name: '等待管理员分配角色' }).waitFor();
  check('待授权账号落到独立等待页', new URL(page.url()).pathname === '/auth/waiting-role');
  const denied = await context.request.get(apiOrigin + '/api/v1/wecom/config/');
  check('待授权会话业务API403门禁', denied.status() === 403 && (await denied.json()).error.code === 'WECOM_ROLE_REQUIRED');
  const me = await context.request.get(apiOrigin + '/api/auth/me/');
  check('拒绝业务后会话仍保留', me.status() === 200 && (await me.json()).authenticated);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '检查授权状态', exact: true }).click();
  await page.getByText('尚未分配有效角色，请联系管理员后再次检查。', { exact: true }).waitFor();
  check('等待页无循环跳转', new URL(page.url()).pathname === '/auth/waiting-role');
  check('390等待页无横溢出', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await screenshot(page, 'actual_waiting_390');
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await page.locator('#login-username').waitFor();
  check('待授权会话可退出', !(await (await context.request.get(apiOrigin + '/api/auth/me/')).json()).authenticated);
  await page.goto(webOrigin + '/auth/wecom-error?reason=STATE_INVALID', { waitUntil: 'domcontentloaded' });
  await page.getByRole('heading', { name: '企业微信登录未完成' }).waitFor();
  check('错误页深链接显示固定安全文案', (await page.getByRole('alert').textContent()).includes('过期或已使用'));
  await screenshot(page, 'actual_oauth_error_390');
  check('页面无未处理JS异常', runtimeErrors.length === 0, runtimeErrors);
}
(async () => {
  let failure;
  try { await main(); } catch (error) {
    failure = error.message;
    const page = context?.pages()[0];
    if (page) {
      await screenshot(page, 'actual_failure');
      runtimeErrors.push({ url: page.url(), body: (await page.locator('body').innerText()).slice(0,500) });
    }
  }
  finally {
    if (context) await context.close();
    // API服务由外层LiveServer测试持有；失败时保留其300秒诊断窗口，宿主可修复后立即重试。
    // 成功发送结束信号；无人继续时fixture超时也会销毁独占库，浏览器始终在此关闭。
    if (!failure && fs.existsSync(control)) fs.writeFileSync(path.join(runtime, 'finished'), 'finished');
    const browser = path.resolve(runtime, 'browser');
    if (browser.startsWith(path.resolve(runtime) + path.sep) && fs.existsSync(browser)) fs.rmSync(browser, { recursive: true });
  }
  const result = { status: failure ? 'FAIL' : 'PASS', message: failure || '隔离真实API页面检查通过；不代表真实企业微信身份链路验收。', checks, screenshots, runtimeErrors };
  fs.writeFileSync(path.join(root, 'page_checks.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ qa_result_version: 1, status: failure ? 'FAIL' : 'PASS_WITH_GAPS', failure: failure ? { message: failure } : undefined,
    not_covered: ['真实企业微信工作台身份链路', '业务库迁移与真实员工绑定', '公网部署及外层代理日志'], cleanup: true,
    message: result.message, checks: checks.length, screenshots: screenshots.length }));
  process.exitCode = failure ? 1 : 0;
})();

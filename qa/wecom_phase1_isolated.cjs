// 仅配合 test_browser_fixture 的独占测试库运行；不替代真实企业微信验收。
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('../src/frontend/node_modules/playwright-core');
const root = path.resolve(process.env.WECOM_QA_ARTIFACT_DIR || path.join(__dirname, 'wecom_phase1_20261019'));
const runtime = path.resolve(process.env.WECOM_QA_RUNTIME_DIR || path.join(__dirname, 'wecom_phase1_20261019', 'page_runtime'));
const control = path.join(runtime, 'ready.json');
const apiOrigin = 'http://127.0.0.1:18591';
const webOrigin = 'http://127.0.0.1:8080';
const checks = [], screenshots = [], runtimeErrors = [], blockedRequests = [];
let context;
function check(name, condition, actual) { checks.push({ name, passed: !!condition, actual }); assert.ok(condition, name); }
async function screenshot(page, name) { await page.screenshot({ path: path.join(root, name + '.png'), fullPage: true }); screenshots.push(name + '.png'); }

// 每种入口使用独立 cookie/storage；这里只模拟客户端标识，身份和配置仍由独占测试 API 判断。
async function checkHomeEntry(browser, fixture, userAgent) {
  const wecomAgent = userAgent + ' MicroMessenger/8.0.0 wxwork/4.1.0';
  async function scenario(name, agent, run, { failMe = false } = {}) {
    const entryContext = await browser.newContext({ userAgent: agent, viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
    const starts = [], rejected = [];
    let failedMeRequests = 0;
    await entryContext.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (![webOrigin, apiOrigin].includes(url.origin)) {
        rejected.push(url.origin + url.pathname);
        return route.abort('blockedbyclient');
      }
      if (!url.pathname.startsWith('/api/')) return route.continue();
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method()) &&
          !(request.method() === 'POST' && ['/api/auth/login/', '/api/auth/logout/'].includes(url.pathname))) {
        rejected.push(request.method() + ' ' + url.pathname);
        return route.abort('blockedbyclient');
      }
      if (failMe && url.pathname === '/api/auth/me/') {
        failedMeRequests += 1;
        return route.abort('failed');
      }
      // 禁止自动跟随 API 重定向，避免配置异常时跳到真实企业微信。
      const response = await route.fetch({ url: apiOrigin + url.pathname + url.search, maxRedirects: 0 });
      const headers = response.headers();
      if (url.pathname === '/api/auth/wecom/start/') {
        starts.push({ method: request.method(), search: url.search, status: response.status(), location: headers.location });
      }
      if (headers.location) {
        const destination = new URL(headers.location, apiOrigin);
        if (destination.origin !== apiOrigin) {
          rejected.push(destination.origin + destination.pathname);
          return route.abort('blockedbyclient');
        }
        // LiveServer 只提供 API；真实 302 的站内错误页仍须由前端服务渲染。
        headers.location = webOrigin + destination.pathname + destination.search + destination.hash;
      }
      return route.fulfill({ response, headers });
    });
    const entryPage = await entryContext.newPage();
    entryPage.setDefaultTimeout(30000);
    entryPage.on('pageerror', error => runtimeErrors.push(name + ': ' + error.message));
    try {
      await run(entryPage, entryContext, starts, () => failedMeRequests);
      check(name + '仅访问本机页面与隔离API', rejected.length === 0, rejected);
    } catch (error) {
      await screenshot(entryPage, 'home_entry_failure_' + name);
      throw error;
    } finally {
      await entryContext.close();
    }
  }
  for (const [name, agent, entry] of [
    ['普通浏览器主页', userAgent, '/'],
    ['个人微信主页', userAgent + ' MicroMessenger/8.0.0', '/'],
    ['企微显式密码入口', wecomAgent, '/login'],
  ]) {
    await scenario(name, agent, async (entryPage, entryContext, starts) => {
      await entryPage.goto(webOrigin + entry, { waitUntil: 'domcontentloaded' });
      await entryPage.locator('#login-username').waitFor();
      await entryPage.waitForLoadState('networkidle');
      check(name + '保留密码登录且不发起授权', new URL(entryPage.url()).pathname === '/login' && starts.length === 0);
      check(name + '密码控件可编辑', await entryPage.locator('#login-password').isEditable() && await entryPage.getByRole('button', { name: '登录', exact: true }).isEnabled());
      if (name === '普通浏览器主页') await screenshot(entryPage, 'home_entry_browser_password');
    });
  }
  for (const [name, entry] of [['企微主页', '/'], ['企微业务深链接', '/settings/wecom?from=workbench']]) {
    await scenario(name, wecomAgent, async (entryPage, entryContext, starts) => {
      await entryPage.goto(webOrigin + entry, { waitUntil: 'domcontentloaded' });
      await entryPage.getByRole('heading', { name: '企业微信登录未完成', exact: true }).waitFor();
      await entryPage.waitForLoadState('networkidle');
      const location = new URL(entryPage.url());
      check(name + '调用一次真实start并收到配置错误302', starts.length === 1 && starts[0].method === 'GET' && starts[0].search === '' && starts[0].status === 302 && starts[0].location === '/auth/wecom-error?reason=CONFIGURATION_ERROR', starts);
      check(name + '错误页不重复授权', location.origin === webOrigin && location.pathname === '/auth/wecom-error' && location.searchParams.get('reason') === 'CONFIGURATION_ERROR' && (await entryPage.getByRole('alert').innerText()).includes('接入配置尚未就绪'));
      await screenshot(entryPage, name === '企微主页' ? 'home_entry_wecom_configuration_error' : 'home_entry_wecom_deep_link');
      await entryPage.getByRole('button', { name: '返回账号登录', exact: true }).click();
      await entryPage.locator('#login-username').waitFor();
      await entryPage.waitForLoadState('networkidle');
      check(name + '返回密码页不再次授权', new URL(entryPage.url()).pathname === '/login' && starts.length === 1);
    });
  }
  await scenario('企微循环保护标记', wecomAgent, async (entryPage, entryContext, starts) => {
    // 仅覆盖授权尝试后仍匿名的导航保护，不冒充 OAuth 已成功回调。
    await entryPage.addInitScript(() => sessionStorage.setItem('wecom:auto-login-attempted', '1'));
    await entryPage.goto(webOrigin + '/', { waitUntil: 'domcontentloaded' });
    await entryPage.locator('#login-username').waitFor();
    await entryPage.waitForLoadState('networkidle');
    check('已有尝试标记且仍匿名时降级密码页不循环授权', new URL(entryPage.url()).pathname === '/login' && starts.length === 0);
  });
  async function passwordLogin(entryPage, account) {
    await entryPage.goto(webOrigin + '/login', { waitUntil: 'domcontentloaded' });
    await entryPage.locator('#login-username').fill(account.username);
    await entryPage.locator('#login-password').fill(account.password);
    await entryPage.getByRole('button', { name: '登录', exact: true }).click();
  }
  await scenario('企微已有管理员Session', wecomAgent, async (entryPage, entryContext, starts) => {
    await passwordLogin(entryPage, fixture.accounts.admin);
    await entryPage.locator('[data-workbench-page]').waitFor();
    const before = await (await entryContext.request.get(apiOrigin + '/api/auth/me/')).json();
    await entryPage.goto(webOrigin + '/', { waitUntil: 'domcontentloaded' });
    await entryPage.locator('[data-workbench-page]').waitFor();
    await entryPage.waitForLoadState('networkidle');
    const after = await (await entryContext.request.get(apiOrigin + '/api/auth/me/')).json();
    check('企微已有Session主页复用原账号不授权', before.authenticated && after.authenticated && after.user.id === before.user.id && after.user.username === fixture.accounts.admin.username && new URL(entryPage.url()).pathname === '/' && starts.length === 0);
    await screenshot(entryPage, 'home_entry_existing_session');
  });
  await scenario('企微待授权Session', wecomAgent, async (entryPage, entryContext, starts) => {
    await passwordLogin(entryPage, fixture.accounts.waiting);
    await entryPage.getByRole('heading', { name: '等待管理员分配角色', exact: true }).waitFor();
    await entryPage.goto(webOrigin + '/', { waitUntil: 'domcontentloaded' });
    await entryPage.getByRole('heading', { name: '等待管理员分配角色', exact: true }).waitFor();
    await entryPage.waitForLoadState('networkidle');
    const waiting = await (await entryContext.request.get(apiOrigin + '/api/auth/me/')).json();
    check('企微待授权Session主页回等待页不重复授权', waiting.authenticated && waiting.user.waiting_for_role && new URL(entryPage.url()).pathname === '/auth/waiting-role' && starts.length === 0);
    await entryPage.getByRole('button', { name: '退出登录', exact: true }).click();
    await entryPage.locator('#login-username').waitFor();
    await entryPage.waitForLoadState('networkidle');
    const loggedOut = await (await entryContext.request.get(apiOrigin + '/api/auth/me/')).json();
    check('企微待授权Session退出后停留密码页', !loggedOut.authenticated && new URL(entryPage.url()).pathname === '/login' && starts.length === 0);
  });
  await scenario('企微会话查询网络失败', wecomAgent, async (entryPage, entryContext, starts, failedMeCount) => {
    await entryPage.goto(webOrigin + '/', { waitUntil: 'domcontentloaded' });
    await entryPage.locator('#login-username').waitFor();
    await entryPage.waitForLoadState('networkidle');
    check('会话查询网络失败不误判为可自动授权', failedMeCount() > 0 && new URL(entryPage.url()).pathname === '/login' && starts.length === 0);
  }, { failMe: true });
}
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
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (![webOrigin, apiOrigin].includes(url.origin)) {
      blockedRequests.push(url.origin + url.pathname);
      return route.abort('blockedbyclient');
    }
    if (!url.pathname.startsWith('/api/')) return route.continue();
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
  check('消息回调凭据直接显示', await page.locator('#wecom-token').isVisible() && await page.locator('#wecom-aes').isVisible());
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
  check('三项凭据均直接明文显示', (await Promise.all(['#wecom-secret', '#wecom-token', '#wecom-aes'].map(selector => page.locator(selector).getAttribute('type')))).every(type => type === 'text'));
  const testSecret = 'IsolatedSecretForDisplayOnly', testToken = 'IsolatedCallback123', testAes = 'A'.repeat(43);
  await page.locator('#wecom-secret').fill(testSecret);
  await page.locator('#wecom-token').fill(testToken);
  await page.locator('#wecom-aes').fill(testAes);
  const saved = page.waitForResponse(response => response.url().includes('/api/v1/wecom/config/') && response.request().method() === 'PATCH');
  await page.getByRole('button', { name: '保存配置', exact: true }).click();
  const saveResponse = await saved, saveData = await saveResponse.json();
  check('真实Session+CSRF保存回调凭据', saveResponse.status() === 200 && saveData.data.has_callback_token && saveData.data.has_callback_aes_key);
  check('管理员配置响应返回已保存真值', saveData.data.secret === testSecret && saveData.data.callback_token === testToken && saveData.data.callback_aes_key === testAes);
  check('配置响应禁止缓存', /no-store/.test(saveResponse.headers()['cache-control'] || ''));
  check('保存后保留三项凭据', await page.locator('#wecom-secret').inputValue() === testSecret && await page.locator('#wecom-token').inputValue() === testToken && await page.locator('#wecom-aes').inputValue() === testAes);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('#wecom-secret').waitFor();
  check('刷新后仍显示已保存三项真值', await page.locator('#wecom-secret').inputValue() === testSecret && await page.locator('#wecom-token').inputValue() === testToken && await page.locator('#wecom-aes').inputValue() === testAes);
  check('回显不被误判为未保存编辑', await page.getByRole('button', { name: '检查连接', exact: true }).isEnabled());
  const storage = await page.evaluate(() => ({ local: Object.values(localStorage), session: Object.values(sessionStorage) }));
  check('凭据未写入浏览器持久化存储', ![testSecret, testToken, testAes].some(value => JSON.stringify(storage).includes(value)));
  await screenshot(page, 'actual_callback_credentials_1440');
  await page.setViewportSize({ width: 390, height: 844 });
  check('390凭据回显后无整页横溢出', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await screenshot(page, 'actual_callback_credentials_390');
  await page.setViewportSize({ width: 1440, height: 1000 });
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
  const auditText = await page.locator('.wecom-dialog-content').last().textContent();
  check('审计页面来自真实测试API且不含密钥', ![testSecret, testToken, testAes].some(value => auditText.includes(value)));
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
  await checkHomeEntry(context.browser(), fixture, await page.evaluate(() => navigator.userAgent));
  check('全部页面未尝试访问真实外部服务', blockedRequests.length === 0, blockedRequests);
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

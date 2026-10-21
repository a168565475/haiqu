// 单元四独占库真实 Session/CSRF 页面验收；不调用真实企微，不模拟任何响应。
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('../src/frontend/node_modules/playwright-core');

const project = path.resolve(__dirname, '..');
const runtime = path.join(project, '.tmp', 'wecom-login-unit4-a15c89');
const control = path.join(runtime, 'control');
const browserDirectory = path.join(runtime, 'browser');
const output = path.join(project, 'output', 'playwright', 'wecom-login-unit4-20261021');
const readyPath = path.join(control, 'ready.json');
const finishedPath = path.join(control, 'finished');
const database = 'test_haiqu_employee_login_u4_20261021_a15c89';
const webOrigin = 'http://127.0.0.1:18595';
const waitingTitle = '等待管理员分配访问权限';
const waitingMessage = '尚未分配有效访问权限，请联系管理员后再次检查。';
const checks = [], screenshots = [], blockedRequests = [], runtimeErrors = [], writes = [], cleanupErrors = [];
const contexts = [];
let fixture, browser, workerPage, browserCreated = false, browserClosed = null, failure;

function redact(value) {
  let text = String(value);
  for (const account of Object.values(fixture?.accounts || {})) text = text.split(account.password).join('[已隐藏]');
  return text.slice(0, 1200);
}
function check(name, passed, actual) {
  checks.push({ name, passed: Boolean(passed), ...(actual === undefined ? {} : { actual }) });
  assert.ok(passed, name);
}
function samePath(left, right) { return path.resolve(left).toLowerCase() === path.resolve(right).toLowerCase(); }
async function readFixture() {
  const deadline = Date.now() + 600000;
  while (Date.now() < deadline) {
    if (fs.existsSync(readyPath)) {
      assert.ok(!fs.lstatSync(readyPath).isSymbolicLink(), 'ready.json 不能为符号链接');
      try { fixture = JSON.parse(fs.readFileSync(readyPath, 'utf8')); }
      catch (error) { if (!(error instanceof SyntaxError)) throw error; }
      if (fixture) break;
    }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  assert.ok(fixture, '等待独占测试库 ready.json 超过 600 秒');
  assert.equal(fixture.database, database, 'fixture 不是已登记的单元四测试库');
  assert.equal(fixture.web_origin, webOrigin);
  assert.equal(fixture.backend_origin, 'http://127.0.0.1:18594');
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  assert.ok(uuid.test(fixture.run_id) && uuid.test(fixture.target.employee_id) && uuid.test(fixture.target.role_id));
  assert.ok(Number.isInteger(fixture.target.account_id) && fixture.target.account_id > 0);
  for (const account of Object.values(fixture.accounts)) {
    assert.ok(typeof account.username === 'string' && typeof account.password === 'string'
      && account.password.length > 0 && account.password.length <= 128, '测试账号契约无效');
  }
  assert.ok(fixture.expires_at * 1000 > Date.now(), 'fixture 已过期，禁止登录');
  assert.ok(!fs.existsSync(finishedPath), 'finished 已存在，禁止覆盖');
  assert.equal(fixture.target.permission, 'reference_data.view_referencedictionary');
  assert.equal(fixture.target.employee_roles_path, `/api/v1/access/employees/${fixture.target.employee_id}/roles/`);
  assert.equal(fixture.target.role_grants_path, `/api/v1/access/roles/${fixture.target.role_id}/grants/`);
  assert.equal(fixture.target.business_path, '/api/v1/reference-data/dictionary-items/');
}
async function screenshot(page, name) {
  await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true });
  screenshots.push(`${name}.png`);
}
async function checkOverflow(page, name) {
  const size = await page.evaluate(() => ({
    viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth,
  }));
  check(name + '无横向溢出', size.document <= size.viewport && size.body <= size.viewport, size);
}
async function protectContext(context, allowAuthorizationWrites = false) {
  contexts.push(context);
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== webOrigin) {
      blockedRequests.push({ kind: '外部请求', method: request.method(), origin: url.origin, path: url.pathname });
      return route.abort('blockedbyclient');
    }
    if (url.pathname.startsWith('/api/') && !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      const login = request.method() === 'POST' && ['/api/auth/login/', '/api/auth/logout/'].includes(url.pathname);
      const authorization = allowAuthorizationWrites && request.method() === 'PUT'
        && [fixture.target.employee_roles_path, fixture.target.role_grants_path].includes(url.pathname);
      if (!login && !authorization) {
        blockedRequests.push({ kind: '范围外写入', method: request.method(), path: url.pathname });
        return route.abort('blockedbyclient');
      }
      if (authorization) {
        const body = request.postDataJSON();
        const allowed = url.pathname === fixture.target.employee_roles_path
          ? JSON.stringify(body) === JSON.stringify({ role_ids: [fixture.target.role_id] })
          : JSON.stringify(body) === JSON.stringify({ grants: [] }) || JSON.stringify(body) === JSON.stringify({
            grants: [{ permission: fixture.target.permission, scope: 'MODULE' }],
          });
        if (!allowed) {
          blockedRequests.push({ kind: '范围外授权内容', method: request.method(), path: url.pathname });
          return route.abort('blockedbyclient');
        }
        writes.push({ method: request.method(), csrf: Boolean(request.headers()['x-csrftoken']),
          etag: Boolean(request.headers()['if-match']) });
      }
    }
    return route.continue();
  });
  context.on('page', page => page.on('pageerror', error => runtimeErrors.push(redact(error.message))));
  return context;
}
async function api(page, pathname, { method = 'GET', body, etag } = {}) {
  assert.ok(pathname.startsWith('/api/') && !pathname.includes('://'));
  return page.evaluate(async ({ pathname, method, body, etag }) => {
    const headers = { Accept: 'application/json' };
    if (body !== undefined) {
      const cookie = document.cookie.split('; ').find(value => value.startsWith('csrftoken='));
      if (!cookie) throw new Error('未获取真实 CSRF Cookie');
      headers['Content-Type'] = 'application/json';
      headers['X-CSRFToken'] = decodeURIComponent(cookie.slice('csrftoken='.length));
    }
    if (etag) headers['If-Match'] = etag;
    const response = await fetch(pathname, { method, headers, credentials: 'same-origin',
      ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    if (new URL(response.url).origin !== location.origin) throw new Error('API 离开同源代理');
    return { status: response.status, etag: response.headers.get('etag'), body: await response.json() };
  }, { pathname, method, body, etag });
}
async function login(page, account) {
  page.setDefaultTimeout(20000);
  await page.goto(webOrigin + '/login', { waitUntil: 'domcontentloaded' });
  await page.locator('#login-username').fill(account.username);
  await page.locator('#login-password').fill(account.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
}
async function assertWaiting(page, label) {
  await page.getByRole('heading', { name: waitingTitle, exact: true }).waitFor();
  const current = await api(page, '/api/auth/me/');
  check(label, current.status === 200 && current.body.authenticated && current.body.user.waiting_for_role
    && current.body.user.id === fixture.target.account_id && !current.body.user.is_superuser
    && current.body.user.permissions.length === 0);
}
async function checkErrorPages(userAgent) {
  for (const [mode, agent] of [['browser', userAgent], ['wecom', userAgent + ' wxwork/4.1.0']]) {
    const context = await protectContext(await browser.newContext({
      userAgent: agent, viewport: { width: 1440, height: 960 }, reducedMotion: 'reduce', serviceWorkers: 'block',
    }));
    const page = await context.newPage();
    for (const [code, text] of [
      ['BINDING_REQUIRED', '成员身份需要管理员核对关联，请联系管理员确认对应的 ERP 员工后重新登录。'],
      ['ACCOUNT_INACTIVE', '对应的 ERP 员工或账号当前不可用，请联系管理员核对员工状态及账号是否启用。'],
    ]) {
      await page.goto(webOrigin + '/auth/wecom-error?reason=' + code, { waitUntil: 'domcontentloaded' });
      await page.getByRole('heading', { name: '企业微信登录未完成', exact: true }).waitFor();
      check(`${mode} ${code}固定安全提示`, await page.getByRole('alert').innerText() === text);
      check(`${mode} ${code}保留返回账号入口`, await page.getByRole('button', { name: '返回登录页', exact: true }).isVisible());
      for (const width of [1440, 390]) {
        await page.setViewportSize({ width, height: width === 390 ? 844 : 960 });
        await checkOverflow(page, `${mode} ${code} ${width}`);
        await screenshot(page, `${mode}_${code.toLowerCase()}_${width}`);
      }
    }
    await context.close();
  }
}
async function main() {
  await readFixture();
  fs.mkdirSync(output, { recursive: true });
  assert.ok(!fs.existsSync(browserDirectory), 'browser 目录已存在，须先核对归属');
  assert.ok(samePath(fs.realpathSync(runtime), runtime), '浏览器临时目录的父路径不能重定向');
  fs.mkdirSync(browserDirectory);
  browserCreated = true;
  const executablePath = process.env.WECOM_LOGIN_U4_BROWSER_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
  assert.ok(fs.existsSync(executablePath), '未找到现有 Chrome；请配置 WECOM_LOGIN_U4_BROWSER_PATH');
  const employeeContext = await chromium.launchPersistentContext(browserDirectory, {
    executablePath, headless: true, viewport: { width: 1440, height: 960 }, reducedMotion: 'reduce',
    serviceWorkers: 'block', args: ['--disable-background-networking', '--disable-component-update'],
  });
  browser = employeeContext.browser();
  browserClosed = false;
  await protectContext(employeeContext);
  workerPage = await employeeContext.newPage();
  await login(workerPage, fixture.accounts.employee);
  await assertWaiting(workerPage, '已有密码账号的绑定员工无权限时进入等待页');
  await workerPage.getByRole('button', { name: '检查授权状态', exact: true }).click();
  await workerPage.getByText(waitingMessage, { exact: true }).waitFor();
  for (const width of [1440, 390]) {
    await workerPage.setViewportSize({ width, height: width === 390 ? 844 : 960 });
    await checkOverflow(workerPage, `等待页 ${width}`);
    await screenshot(workerPage, `waiting_${width}`);
  }
  const denied = await api(workerPage, fixture.target.business_path);
  check('无权限员工业务 API 返回真实门禁 403', denied.status === 403 && denied.body.error?.code === 'WECOM_ROLE_REQUIRED');

  const adminContext = await protectContext(await browser.newContext({ viewport: { width: 1440, height: 960 }, serviceWorkers: 'block' }), true);
  const adminPage = await adminContext.newPage();
  await login(adminPage, fixture.accounts.admin);
  await adminPage.locator('[data-workbench-page]').waitFor();
  const employee = await api(adminPage, fixture.target.employee_roles_path);
  check('管理员读取同一员工当前角色及版本', employee.status === 200 && employee.body.id === fixture.target.employee_id
    && employee.body.role_ids.length === 0 && employee.etag === fixture.target.employee_etag);
  const assigned = await api(adminPage, fixture.target.employee_roles_path, {
    method: 'PUT', etag: employee.etag, body: { role_ids: [fixture.target.role_id] },
  });
  check('通过真实权限 API 分配空角色', assigned.status === 200 && assigned.body.role_ids.length === 1
    && assigned.body.role_ids[0] === fixture.target.role_id);
  await workerPage.getByRole('button', { name: '检查授权状态', exact: true }).click();
  await workerPage.getByText(waitingMessage, { exact: true }).waitFor();
  await assertWaiting(workerPage, '分配空权限角色后仍等待有效权限');
  const role = await api(adminPage, fixture.target.role_grants_path);
  check('目标角色初始确实无操作授权', role.status === 200 && role.body.grants.length === 0 && role.etag === fixture.target.role_etag);
  const granted = await api(adminPage, fixture.target.role_grants_path, {
    method: 'PUT', etag: role.etag, body: { grants: [{ permission: fixture.target.permission, scope: 'MODULE' }] },
  });
  check('通过真实权限 API 授予字典读取权限', granted.status === 200 && granted.body.grants.length === 1
    && granted.body.grants[0].permission === fixture.target.permission && granted.body.grants[0].scope === 'MODULE');
  await workerPage.setViewportSize({ width: 1440, height: 960 });
  await workerPage.getByRole('button', { name: '检查授权状态', exact: true }).click();
  await workerPage.locator('[data-workbench-page]').waitFor();
  const active = await api(workerPage, '/api/auth/me/');
  check('原员工刷新授权后进入首页且未换账号', active.status === 200 && active.body.authenticated
    && !active.body.user.waiting_for_role && active.body.user.id === fixture.target.account_id
    && !active.body.user.is_superuser && new URL(workerPage.url()).pathname === '/');
  check('获得权限后真实字典列表可读取', (await api(workerPage, fixture.target.business_path)).status === 200);
  await screenshot(workerPage, 'authorized_home_1440');
  const revoked = await api(adminPage, fixture.target.role_grants_path, {
    method: 'PUT', etag: granted.etag, body: { grants: [] },
  });
  check('通过真实权限 API 撤回最后一项权限', revoked.status === 200 && revoked.body.grants.length === 0);
  // 调用页面实际使用的 Axios 实例，验证真实 403 触发已安装的前端响应拦截器。
  const rejected = await workerPage.evaluate(async businessPath => {
    const { apiClient } = await import('/src/api/request.ts');
    try { const response = await apiClient.get(businessPath); return { status: response.status }; }
    catch (error) { return { status: error.response?.status, code: error.response?.data?.error?.code }; }
  }, fixture.target.business_path);
  check('撤权后的真实业务请求被后端拒绝', rejected.status === 403 && rejected.code === 'WECOM_ROLE_REQUIRED');
  await assertWaiting(workerPage, '前端业务 403 拦截器使原员工返回等待页');
  check('响应拦截后当前路由为等待页', new URL(workerPage.url()).pathname === '/auth/waiting-role');
  await screenshot(workerPage, 'revoked_waiting_1440');
  await checkErrorPages(await workerPage.evaluate(() => navigator.userAgent));
  check('只发生三次已登记的授权写入且均有 CSRF/ETag', writes.length === 3 && writes.every(row => row.csrf && row.etag));
  check('未尝试外部请求或范围外写入', blockedRequests.length === 0);
  check('页面没有未处理 JavaScript 异常', runtimeErrors.length === 0);
}

(async () => {
  try { await main(); }
  catch (error) {
    failure = redact(error.message);
    if (workerPage && !workerPage.isClosed() && new URL(workerPage.url()).pathname !== '/login') {
      try { await screenshot(workerPage, 'failure'); }
      catch (error) { runtimeErrors.push('失败截图未保存：' + redact(error.message)); }
    }
  } finally {
    for (const context of contexts.reverse()) {
      try { await context.close(); }
      catch (error) { cleanupErrors.push('关闭浏览器上下文失败：' + redact(error.message)); failure ||= cleanupErrors.at(-1); }
    }
    if (browser) {
      try { await browser.close(); browserClosed = true; }
      catch (error) { cleanupErrors.push('关闭浏览器失败：' + redact(error.message)); failure ||= cleanupErrors.at(-1); }
    }
    if (browserCreated) {
      try {
        assert.ok(samePath(path.dirname(fs.realpathSync(browserDirectory)), runtime), '浏览器目录不在登记范围内');
        assert.ok(!fs.lstatSync(browserDirectory).isSymbolicLink(), '浏览器目录不能为符号链接');
        fs.rmSync(browserDirectory, { recursive: true });
        assert.ok(!fs.existsSync(browserDirectory), '浏览器临时目录未清理');
      } catch (error) { cleanupErrors.push('浏览器临时目录清理失败：' + redact(error.message)); failure ||= cleanupErrors.at(-1); }
    }
    const report = {
      status: failure ? 'FAIL' : 'PASS_WITH_GAPS', message: failure || '独占测试库真实页面与 API 检查通过。',
      checks, screenshots, blockedRequests, runtimeErrors, authorization_writes: writes,
      cleanup: { browser_closed: browserClosed, browser_directory_removed: browserCreated ? !fs.existsSync(browserDirectory) : null,
        errors: cleanupErrors,
        control_and_database: '由 LiveServer fixture 及外层测试进程完成并复查' },
      not_covered: ['真实企业微信 OAuth/扫码身份链路', '真实业务库和公网部署', '历史 wecom_phase1_isolated.cjs 空角色解锁断言需更新，本轮未运行'],
    };
    try {
      fs.mkdirSync(output, { recursive: true });
      fs.writeFileSync(path.join(output, 'page_checks.json'), JSON.stringify(report, null, 2));
    } catch (error) { failure ||= '验收报告保存失败：' + redact(error.message); }
    try {
      assert.ok(fs.existsSync(control), '控制目录尚未准备好');
      assert.ok(samePath(fs.realpathSync(control), control), '控制目录不能重定向');
      fs.writeFileSync(finishedPath, JSON.stringify({ run_id: fixture?.run_id || null, database,
        passed: !failure, checks: checks.length }), { flag: 'wx' });
    } catch (error) {
      failure ||= '结束信号写入失败：' + redact(error.message);
      report.status = 'FAIL'; report.message = failure;
      try { fs.writeFileSync(path.join(output, 'page_checks.json'), JSON.stringify(report, null, 2)); }
      catch (reportError) { console.error('失败报告保存失败：' + redact(reportError.message)); }
    }
    console.log(JSON.stringify({ qa_result_version: 1, status: failure ? 'FAIL' : 'PASS_WITH_GAPS',
      message: failure || report.message, checks: checks.length, screenshots: screenshots.length,
      cleanup: browserClosed === true && !fs.existsSync(browserDirectory) && cleanupErrors.length === 0,
      report: path.relative(project, path.join(output, 'page_checks.json')), not_covered: report.not_covered }));
    process.exitCode = failure ? 1 : 0;
  }
})();

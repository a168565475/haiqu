// 单元六独占库真实页面/API 验收；不模拟响应，不访问主业务库。
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const project = path.resolve(__dirname, '..');
const runtime = path.join(project, '.tmp', 'employee-menu-u6-a15c89');
const control = path.join(runtime, 'control');
const browserDirectory = path.join(runtime, 'browser');
const output = path.join(project, 'output', 'playwright', 'employee-menu-unit6-20261021');
const readyPath = path.join(control, 'ready.json'), finishedPath = path.join(control, 'finished');
const database = 'test_haiqu_employee_menu_u6_20261021_a15c89';
const webOrigin = 'http://127.0.0.1:18599';
const listPath = '/api/v1/access/employees/';
const checks = [], screenshots = [], domChecks = [], blockedRequests = [], runtimeErrors = [], writes = [], cleanupErrors = [];
const contexts = [];
const permittedUpdatePaths = new Set();
let fixture, browser, activePage, fixtureReady = false, browserCreated = false, browserClosed = null, failure;

function redact(value) {
  let text = String(value);
  for (const account of Object.values(fixture?.accounts || {})) text = text.split(account.password).join('[已隐藏]');
  return text.slice(0, 1200);
}
function check(name, passed) {
  checks.push({ name, passed: Boolean(passed) });
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
  assert.equal(fixture.database, database);
  assert.equal(fixture.web_origin, webOrigin);
  assert.equal(fixture.backend_origin, 'http://127.0.0.1:18598');
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  for (const id of [fixture.run_id, fixture.target.employee_id, fixture.target.department_id]) assert.ok(uuid.test(id), '测试夹具 ID 无效');
  for (const account of Object.values(fixture.accounts)) {
    assert.ok(Number.isInteger(account.id) && typeof account.username === 'string'
      && typeof account.password === 'string' && account.password.length > 0 && account.password.length <= 128);
  }
  assert.ok(fixture.expires_at * 1000 > Date.now(), 'fixture 已过期');
  assert.ok(!fs.existsSync(finishedPath), 'finished 已存在，禁止覆盖');
  permittedUpdatePaths.add(listPath + fixture.target.employee_id + '/departments/');
  fixtureReady = true;
}
async function screenshot(page, name) {
  await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true });
  screenshots.push(`${name}.png`);
}
async function checkLayout(page, name, dialog) {
  const dimensions = await page.evaluate(() => ({
    width: innerWidth, height: innerHeight, documentWidth: document.documentElement.scrollWidth,
    bodyWidth: document.body.scrollWidth,
  }));
  domChecks.push({ name, ...dimensions });
  check(`${name}1440视口无页面横向溢出`, dimensions.width === 1440
    && dimensions.documentWidth <= dimensions.width && dimensions.bodyWidth <= dimensions.width);
  if (dialog) {
    const bounds = await dialog.boundingBox();
    domChecks.push({ name: `${name}弹窗边界`, bounds });
    check(`${name}弹窗完整位于视口内`, bounds && bounds.x >= -1 && bounds.y >= -1
      && bounds.x + bounds.width <= dimensions.width + 1 && bounds.y + bounds.height <= dimensions.height + 1);

  }
}
async function protectContext(context) {
  contexts.push(context);
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== webOrigin) {
      blockedRequests.push({ kind: '外部请求', method: request.method(), origin: url.origin, path: url.pathname });
      return route.abort('blockedbyclient');
    }
    if (url.pathname.startsWith('/api/') && !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      const login = request.method() === 'POST' && ['/api/auth/login/', '/api/auth/logout/'].includes(url.pathname);
      const update = request.method() === 'PUT' && permittedUpdatePaths.has(url.pathname);
      if (!login && !update) {
        blockedRequests.push({ kind: '范围外写入', method: request.method(), path: url.pathname });
        return route.abort('blockedbyclient');
      }
      if (update) {
        const body = request.postDataJSON();
        if (!Array.isArray(body.departments) || body.departments.some(row => row.department_id !== fixture.target.department_id)) {
          blockedRequests.push({ kind: '范围外部门', path: url.pathname });
          return route.abort('blockedbyclient');
        }
      }
      if (!login) writes.push({ method: request.method(), csrf: Boolean(request.headers()['x-csrftoken']),
        etag: Boolean(request.headers()['if-match']) });
    }
    return route.continue();
  });
  context.on('page', page => page.on('pageerror', error => runtimeErrors.push(redact(error.message))));
  return context;
}
async function api(page, pathname, { method = 'GET', body, etag, csrf = true } = {}) {
  assert.ok(pathname.startsWith('/api/') && !pathname.includes('://'));
  return page.evaluate(async ({ pathname, method, body, etag, csrf }) => {
    const headers = { Accept: 'application/json' };
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      if (csrf) {
        const cookie = document.cookie.split('; ').find(value => value.startsWith('csrftoken='));
        if (!cookie) throw new Error('未获取真实 CSRF Cookie');
        headers['X-CSRFToken'] = decodeURIComponent(cookie.slice('csrftoken='.length));
      }
    }
    if (etag) headers['If-Match'] = etag;
    const response = await fetch(pathname, { method, headers, credentials: 'same-origin',
      ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    if (new URL(response.url).origin !== location.origin) throw new Error('API 离开同源代理');
    const text = await response.text();
    return { status: response.status, etag: response.headers.get('etag'),
      body: response.headers.get('content-type')?.includes('application/json') ? JSON.parse(text) : null };
  }, { pathname, method, body, etag, csrf });
}
async function login(page, account, target = '/employees') {
  page.setDefaultTimeout(30000);
  page.setDefaultNavigationTimeout(120000);
  await page.goto(webOrigin + '/login', { waitUntil: 'domcontentloaded' });
  await page.locator('#login-username').fill(account.username);
  await page.locator('#login-password').fill(account.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL(url => url.pathname !== '/login');
  const current = await api(page, '/api/auth/me/');
  check(`${account.username}使用真实普通账号登录`, current.status === 200 && current.body.authenticated
    && current.body.user.id === account.id && !current.body.user.is_superuser);
  await page.goto(webOrigin + target, { waitUntil: 'domcontentloaded' });
}

async function main() {
  await readFixture();
  const { chromium } = require(process.env.EMPLOYEE_MENU_U6_PLAYWRIGHT_MODULE || '../src/frontend/node_modules/playwright-core');
  fs.mkdirSync(output, { recursive: true });
  assert.ok(!fs.existsSync(browserDirectory), 'browser 目录已存在，禁止覆盖');
  assert.ok(samePath(fs.realpathSync(runtime), runtime), '浏览器父目录不能重定向');
  fs.mkdirSync(browserDirectory); browserCreated = true;
  const managerContext = await chromium.launchPersistentContext(browserDirectory, {
    executablePath: process.env.EMPLOYEE_MENU_U6_BROWSER_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true, viewport: { width: 1440, height: 960 }, reducedMotion: 'reduce', serviceWorkers: 'block',
    args: ['--disable-background-networking', '--disable-component-update'],
  });
  browser = managerContext.browser(); browserClosed = false;
  await protectContext(managerContext);
  activePage = await managerContext.newPage();
  const page = activePage, target = fixture.target;
  await login(page, fixture.accounts.manager);
  const list = page.getByTestId('employee-list');
  await list.getByText(target.employee_code, { exact: true }).waitFor();
  const initial = await api(page, listPath);
  check('真实员工列表可读取，归档员工被排除', initial.status === 200
    && initial.body.data.some(row => row.id === target.employee_id)
    && !initial.body.data.some(row => row.employee_code === 'QA_U6_ARCHIVED'));
  check('同名员工按各自编码显示', await list.getByText(target.second_code, { exact: true }).count() === 1);
  await checkLayout(page, '员工管理页');
  await screenshot(page, 'employee_list');
  const search = list.getByRole('textbox', { name: '搜索员工', exact: true });
  await search.fill('QA_U6_NO_MATCH');
  await list.getByRole('button', { name: '查询', exact: true }).click();
  await list.getByText('没有符合条件的员工。', { exact: true }).waitFor();
  check('员工搜索支持真实空结果状态', await list.locator('tbody tr').count() === 0);
  await search.fill(target.employee_code);
  await list.getByRole('button', { name: '查询', exact: true }).click();
  const row = list.locator(`tr[data-employee-id="${target.employee_id}"]`);
  await row.waitFor();
  await row.getByRole('button', { name: '部门管理', exact: true }).click();
  const editor = page.getByRole('dialog', { name: '员工部门管理', exact: true });
  await editor.getByRole('checkbox', { name: target.department_name, exact: true }).waitFor();
  await checkLayout(page, '员工部门弹窗', editor);
  const path = listPath + target.employee_id + '/departments/';
  const original = await api(page, path);
  check('部门维护读取真实版本与空历史', original.status === 200 && !!original.body.etag && original.body.departments.length === 0);
  const body = { departments: [{ department_id: target.department_id, is_primary: true, position_title: '单元六验收岗位' }] };
  check('缺少CSRF的部门写入被拒绝', (await api(page, path, { method: 'PUT', body, etag: original.body.etag, csrf: false })).status === 403);
  await editor.getByRole('checkbox', { name: target.department_name, exact: true }).check();
  await editor.getByRole('textbox', { name: target.department_name + '岗位', exact: true }).fill('单元六验收岗位');
  await screenshot(page, 'employee_department_dialog');
  const savedResponse = page.waitForResponse(response => response.request().method() === 'PUT' && new URL(response.url()).pathname === path);
  await editor.getByRole('button', { name: '保存员工部门', exact: true }).click();
  check('普通组织管理员通过真实页面保存部门', (await savedResponse).status() === 200);
  await editor.waitFor({ state: 'hidden' });
  await row.getByText(target.department_name, { exact: true }).waitFor();
  check('旧ETag不能覆盖部门保存', (await api(page, path, { method: 'PUT', body, etag: original.body.etag })).status === 412);
  check('成功后仍是同一员工且没有新建账号', (await api(page, listPath)).body.data.find(item => item.id === target.employee_id).username === null);
  await list.getByRole('button', { name: '从企业微信读取', exact: true }).click();
  const directory = page.getByRole('dialog', { name: '从企业微信读取员工', exact: true });
  await directory.waitFor();
  const readButton = directory.getByRole('button', { name: '读取通讯录', exact: true });
  if (await readButton.count()) await readButton.click();
  await directory.getByRole('alert').waitFor();
  check('缺少真实配置显示错误且没有同步名单', await directory.locator('tbody tr').count() === 0);
  await checkLayout(page, '通讯录错误弹窗', directory);
  await screenshot(page, 'directory_unconfigured');
  await directory.getByRole('button', { name: '关闭', exact: true }).last().click();
  await list.getByRole('button', { name: '部门映射', exact: true }).click();
  const mapping = page.getByRole('dialog', { name: '企业微信部门映射', exact: true });
  await mapping.waitFor();
  const readMappings = mapping.getByRole('button', { name: '读取部门', exact: true });
  if (await readMappings.count()) await readMappings.click();
  await mapping.getByRole('alert').waitFor();
  check('部门映射配置缺失不伪造映射数据', await mapping.locator('tbody tr').count() === 0);
  await mapping.getByRole('button', { name: '关闭', exact: true }).last().click();
  for (const key of ['accounts', 'organization', 'attendance', 'wecom', 'ordinary']) {
    const context = await protectContext(await browser.newContext({ viewport: { width: 1440, height: 960 }, serviceWorkers: 'block' }));
    activePage = await context.newPage();
    await login(activePage, fixture.accounts[key], key === 'wecom' ? '/settings/wecom' : '/employees');
    const other = activePage, directoryPermitted = ['accounts', 'organization', 'wecom'].includes(key);
    const employeeResponse = await api(other, listPath);
    check(`${key}服务端员工目录权限正确`, employeeResponse.status === (directoryPermitted ? 200 : 403));
    if (key === 'wecom') {
      const tabs = other.getByRole('tablist', { name: '企业微信管理功能', exact: true });
      await tabs.getByRole('tab', { name: '接入配置', exact: true }).waitFor();
      check('企业微信保留配置消息并移除旧员工绑定标签', await tabs.getByRole('tab').count() === 2
        && await tabs.getByRole('tab', { name: '消息模板', exact: true }).count() === 1
        && await tabs.getByRole('tab', { name: /员工绑定/ }).count() === 0);
      check('原绑定查询接口仍保留供消息功能使用', (await api(other, '/api/v1/wecom/bindings/')).status === 200);
      await screenshot(other, 'wecom_settings_without_binding_tab');
      continue;
    }
    const otherList = other.getByTestId('employee-list');
    if (directoryPermitted) {
      await otherList.getByText(target.employee_code, { exact: true }).waitFor();
      check(`${key}同步按钮按账号管理权限显示`, await otherList.getByRole('button', { name: '从企业微信读取', exact: true }).count() === (key === 'accounts' ? 1 : 0));
      check(`${key}映射按钮按组织管理权限显示`, await otherList.getByRole('button', { name: '部门映射', exact: true }).count() === (key === 'organization' ? 1 : 0));
      check(`${key}不能读取企业微信密钥配置`, (await api(other, '/api/v1/wecom/config/')).status === 403);
    } else {
      await otherList.getByText('没有员工目录查看权限。', { exact: true }).waitFor();
      check(`${key}无权限页面不泄露员工行`, await otherList.locator('tbody tr').count() === 0);
      check(`${key}无权限不能读取通讯录`, (await api(other, '/api/v1/wecom/employee-directory/')).status === 403);
    }
    if (key === 'attendance') {
      await other.goto(webOrigin + '/attendance/wecom', { waitUntil: 'domcontentloaded' });
      await other.getByRole('heading', { name: /考勤/ }).first().waitFor();
      check('原考勤URL保留且使用员工考勤菜单组', new URL(other.url()).pathname === '/attendance/wecom'
        && await other.getByRole('button', { name: '员工与考勤', exact: true }).count() === 1);
      await screenshot(other, 'attendance_old_url');
    }
  }
  check('未访问外部地址或范围外写接口', blockedRequests.length === 0);
  check('页面没有未处理JavaScript异常', runtimeErrors.length === 0);
}

(async () => {
  try { await main(); }
  catch (error) {
    failure = redact(error.message);
    if (activePage && !activePage.isClosed() && new URL(activePage.url()).pathname !== '/login') {
      try { await screenshot(activePage, 'failure'); }
      catch (captureError) { runtimeErrors.push('失败截图未保存：' + redact(captureError.message)); }
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
        assert.ok(!fs.lstatSync(browserDirectory).isSymbolicLink(), '浏览器目录不能为符号链接');
        assert.ok(samePath(path.dirname(fs.realpathSync(browserDirectory)), runtime), '浏览器目录不在登记范围内');
        fs.rmSync(browserDirectory, { recursive: true });
        assert.ok(!fs.existsSync(browserDirectory), '浏览器临时目录未清理');
      } catch (error) { cleanupErrors.push('浏览器临时目录清理失败：' + redact(error.message)); failure ||= cleanupErrors.at(-1); }
    }
    const report = {
      status: failure ? 'FAIL' : 'PASS_WITH_GAPS', message: failure || '独占库真实Session/CSRF页面检查通过；数据库最终断言由夹具完成。',
      checks, screenshots, domChecks, blockedRequests, runtimeErrors, writes,
      cleanup: { browser_closed: browserClosed, browser_directory_removed: browserCreated ? !fs.existsSync(browserDirectory) : null,
        errors: cleanupErrors, control_and_database: '由 LiveServer fixture 和外层测试进程清理及复查' },
      not_covered: ['真实企业微信通讯录及同步成功、扫码登录', '主业务库迁移、真实员工导入与正式发布', '预览重名及映射成功流程由明确标注模拟依赖的组件与后端单元测试覆盖'],
    };
    try {
      fs.mkdirSync(output, { recursive: true });
      fs.writeFileSync(path.join(output, 'page_checks.json'), JSON.stringify(report, null, 2));
    } catch (error) { failure ||= '验收报告保存失败：' + redact(error.message); }
    if (fixtureReady) {
      try {
        assert.ok(samePath(fs.realpathSync(control), control), '控制目录不能重定向');
        fs.writeFileSync(finishedPath, JSON.stringify({ run_id: fixture.run_id, database,
          passed: !failure, checks: checks.length }), { flag: 'wx' });
      } catch (error) { failure ||= '结束信号写入失败：' + redact(error.message); }
    }
    if (failure) {
      report.status = 'FAIL'; report.message = failure;
      try { fs.writeFileSync(path.join(output, 'page_checks.json'), JSON.stringify(report, null, 2)); }
      catch (error) { console.error('失败报告保存失败：' + redact(error.message)); }
    }
    console.log(JSON.stringify({ qa_result_version: 1, status: failure ? 'FAIL' : 'PASS_WITH_GAPS',
      message: failure || report.message, checks: checks.length, screenshots: screenshots.length,
      cleanup: browserClosed === true && !fs.existsSync(browserDirectory) && cleanupErrors.length === 0,
      report: path.relative(project, path.join(output, 'page_checks.json')), not_covered: report.not_covered }));
    process.exitCode = failure ? 1 : 0;
  }
})();

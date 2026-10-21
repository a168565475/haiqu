// 单元五独占库真实页面/API 验收；不模拟响应，不访问主业务库。
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const project = path.resolve(__dirname, '..');
const runtime = path.join(project, '.tmp', 'employee-workshop-u5-a15c89');
const control = path.join(runtime, 'control');
const browserDirectory = path.join(runtime, 'browser');
const output = path.join(project, 'output', 'playwright', 'employee-workshop-unit5-20261021');
const readyPath = path.join(control, 'ready.json'), finishedPath = path.join(control, 'finished');
const database = 'test_haiqu_employee_workshop_u5_20261021_a15c89';
const webOrigin = 'http://127.0.0.1:18597';
const listPath = '/api/v1/workshop-config/employees/';
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
  assert.equal(fixture.backend_origin, 'http://127.0.0.1:18596');
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  for (const id of [fixture.run_id, fixture.target.workshop_id, fixture.target.first.id,
    fixture.target.second.id, fixture.target.legacy_id]) assert.ok(uuid.test(id), '测试夹具 ID 无效');
  for (const account of Object.values(fixture.accounts)) {
    assert.ok(Number.isInteger(account.id) && typeof account.username === 'string'
      && typeof account.password === 'string' && account.password.length > 0 && account.password.length <= 128);
  }
  assert.ok(fixture.expires_at * 1000 > Date.now(), 'fixture 已过期');
  assert.ok(!fs.existsSync(finishedPath), 'finished 已存在，禁止覆盖');
  permittedUpdatePaths.add(listPath + fixture.target.legacy_id + '/');
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
    for (const label of ['关闭', '保存']) {
      const button = dialog.getByRole('button', { name: label, exact: true });
      const rect = await button.boundingBox();
      check(`${name}${label}按钮可见且位于视口内`, await button.isVisible() && rect && rect.x >= 0 && rect.y >= 0
        && rect.x + rect.width <= dimensions.width && rect.y + rect.height <= dimensions.height);
    }
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
      const create = request.method() === 'POST' && url.pathname === listPath;
      const update = request.method() === 'PATCH' && permittedUpdatePaths.has(url.pathname);
      if (!login && !create && !update) {
        blockedRequests.push({ kind: '范围外写入', method: request.method(), path: url.pathname });
        return route.abort('blockedbyclient');
      }
      if (create) {
        const body = request.postDataJSON();
        if (body.workshop !== fixture.target.workshop_id
          || ![fixture.target.first.id, fixture.target.second.id].includes(body.employee)) {
          blockedRequests.push({ kind: '范围外新增员工或车间', method: request.method(), path: url.pathname });
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
async function login(page, account) {
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
  await page.goto(webOrigin + '/workshop/configuration?panel=employees', { waitUntil: 'domcontentloaded' });
  await page.getByTestId('workshop-manager-employees').waitFor();
}
async function chooseOption(page, selectLocator, label) {
  // 非搜索式 ElSelect 的 input 不可见，点击实际可见的控件包装层。
  await selectLocator.locator('.el-select__wrapper').click();
  await page.getByRole('option', { name: label, exact: true }).click();
}
async function editRow(page, text) {
  const row = page.getByTestId('workshop-manager-employees').locator('.el-table__body tr').filter({ hasText: text });
  await row.getByRole('button', { name: '更多操作', exact: true }).click();
  await page.getByRole('menuitem', { name: '编辑', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '编辑车间员工', exact: true });
  await dialog.waitFor();
  return dialog;
}
async function saveEditor(page, dialog, method, pathname) {
  const responsePromise = page.waitForResponse(response => response.request().method() === method
    && new URL(response.url()).pathname === pathname);
  await dialog.getByRole('button', { name: '保存', exact: true }).click();
  const response = await responsePromise;
  const body = await response.json();
  check(`${method}车间配置通过真实接口保存`, response.status() === (method === 'POST' ? 201 : 200));
  await dialog.waitFor({ state: 'hidden' });
  return { body, etag: response.headers().etag };
}
async function main() {
  await readFixture();
  const { chromium } = require(process.env.WORKSHOP_EMPLOYEE_U5_PLAYWRIGHT_MODULE
    || '../src/frontend/node_modules/playwright-core');
  fs.mkdirSync(output, { recursive: true });
  assert.ok(!fs.existsSync(browserDirectory), 'browser 目录已存在，须先核对归属');
  assert.ok(samePath(fs.realpathSync(runtime), runtime), '浏览器父目录不能重定向');
  fs.mkdirSync(browserDirectory);
  browserCreated = true;
  const executablePath = process.env.WORKSHOP_EMPLOYEE_U5_BROWSER_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
  assert.ok(fs.existsSync(executablePath), '未找到现有 Chrome，请配置 WORKSHOP_EMPLOYEE_U5_BROWSER_PATH');
  const managerContext = await chromium.launchPersistentContext(browserDirectory, {
    executablePath, headless: true, viewport: { width: 1440, height: 960 }, reducedMotion: 'reduce',
    serviceWorkers: 'block', args: ['--disable-background-networking', '--disable-component-update'],
  });
  browser = managerContext.browser();
  browserClosed = false;
  await protectContext(managerContext);
  activePage = await managerContext.newPage();
  const page = activePage, target = fixture.target;
  await login(page, fixture.accounts.manager);
  const manager = page.getByTestId('workshop-manager-employees');
  await manager.getByText(`${target.legacy_name}（待关联）`, { exact: true }).waitFor();
  await checkLayout(page, '员工管理页');
  check('旧员工显示待关联且没有同名自动合并', (await api(page, listPath + target.legacy_id + '/')).body.data.employee === null);
  await manager.getByRole('button', { name: '新增员工', exact: true }).click();
  let editor = page.getByRole('dialog', { name: '新增车间员工', exact: true });
  await editor.waitFor();
  await checkLayout(page, '新增员工', editor);
  const workshopField = editor.locator('.el-form-item').filter({
    has: page.locator('.el-form-item__label').filter({ hasText: /^车间$/ }),
  });
  await chooseOption(page, workshopField.locator('.el-select'), target.workshop_name);
  await editor.getByPlaceholder('请输入岗位').fill(target.new_position);
  const employeeInput = editor.getByRole('combobox', { name: '选择统一员工', exact: true });
  const emptyQuery = `QA_U5_NO_MATCH_${fixture.run_id}`;
  const emptyResponsePromise = page.waitForResponse(response => {
    const url = new URL(response.url());
    return response.request().method() === 'GET' && url.pathname === listPath + 'employee-options/'
      && url.searchParams.get('q') === emptyQuery;
  });
  await employeeInput.fill(emptyQuery);
  const emptyResponse = await emptyResponsePromise;
  const emptyData = await emptyResponse.json();
  check('无匹配搜索返回真实空候选列表', emptyResponse.status() === 200 && emptyData.data.length === 0 && emptyData.meta.total === 0);
  await page.getByText('暂无可选的在职员工', { exact: true }).waitFor();
  check('无匹配搜索显示空状态提示', await page.getByText('暂无可选的在职员工', { exact: true }).isVisible());
  await employeeInput.fill(target.first.name);
  for (const item of [target.first, target.second]) {
    await page.getByRole('option', { name: `${item.name}（${item.code}）`, exact: true }).waitFor();
  }
  check('同名员工候选以不同工号区分', target.first.code !== target.second.code);
  await page.getByRole('option', { name: `${target.first.name}（${target.first.code}）`, exact: true }).click();
  await chooseOption(page, editor.locator('.el-form-item').filter({ hasText: '是否为主管' }).locator('.el-select'), '是');
  await screenshot(page, 'create_selected_without_account');
  const created = await saveEditor(page, editor, 'POST', listPath);
  check('无账号主档可以新建车间配置并设置主管', created.body.data.employee === target.first.id
    && created.body.data.name === target.first.name && created.body.data.is_supervisor === true);
  const createdId = created.body.data.id, detailPath = listPath + createdId + '/';
  assert.match(createdId, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
  permittedUpdatePaths.add(detailPath);
  await manager.getByText(`${target.first.name}（${target.first.code}）`, { exact: true }).waitFor();
  editor = await editRow(page, target.legacy_name);
  await editor.getByRole('combobox', { name: '选择统一员工', exact: true }).fill(target.second.code);
  await page.getByRole('option', { name: `${target.second.name}（${target.second.code}）`, exact: true }).click();
  const linked = await saveEditor(page, editor, 'PATCH', listPath + target.legacy_id + '/');
  check('旧记录按人工选择关联且保留原ID与历史姓名', linked.body.data.id === target.legacy_id
    && linked.body.data.name === target.legacy_name && linked.body.data.employee === target.second.id);
  await manager.getByText(`${target.second.name}（${target.second.code}）`, { exact: true }).waitFor();
  editor = await editRow(page, target.second.code);
  await checkLayout(page, '编辑已关联员工', editor);
  check('已关联员工在编辑界面锁定', await editor.getByRole('combobox', { name: '选择统一员工', exact: true, includeHidden: true }).isDisabled());
  await editor.getByText('已关联统一员工，不能更换或解绑。', { exact: true }).waitFor();
  await screenshot(page, 'linked_identity_locked');
  await editor.getByRole('button', { name: '取消', exact: true }).click();
  const detail = await api(page, detailPath);
  check('配置详情提供ETag', detail.status === 200 && Boolean(detail.etag));
  for (const [name, body] of [
    ['换人', { employee: target.second.id }], ['解除关联', { employee: null }], ['修改历史姓名', { name: '禁止改名' }],
  ]) {
    const response = await api(page, detailPath, { method: 'PATCH', body, etag: detail.etag });
    check(`服务端拒绝${name}`, response.status === 400);
  }
  const noCsrf = await api(page, detailPath, { method: 'PATCH', body: { is_supervisor: false }, etag: detail.etag, csrf: false });
  check('真实Session缺少CSRF时拒绝修改', noCsrf.status === 403);
  // 同值保存也更新版本，旧 ETag 随后必须失效；主管值始终保持 true。
  const saved = await api(page, detailPath, { method: 'PATCH', body: { is_supervisor: true }, etag: detail.etag });
  check('有效CSRF与ETag允许修改', saved.status === 200 && saved.etag && saved.etag !== detail.etag);
  const stale = await api(page, detailPath, { method: 'PATCH', body: { is_supervisor: false }, etag: detail.etag });
  check('旧ETag被真实服务端拒绝', stale.status === 412);
  const final = await api(page, detailPath);
  check('所有拒绝请求均未更换身份或主管值', final.body.data.employee === target.first.id && final.body.data.is_supervisor === true);
  await screenshot(page, 'employee_list_after_link');
  const readerContext = await protectContext(await browser.newContext({ viewport: { width: 1440, height: 960 }, serviceWorkers: 'block' }));
  activePage = await readerContext.newPage();
  await login(activePage, fixture.accounts.reader);
  const readerManager = activePage.getByTestId('workshop-manager-employees');
  await readerManager.getByText(`${target.first.name}（${target.first.code}）`, { exact: true }).waitFor();
  await checkLayout(activePage, '只读员工管理页');
  check('只读账号没有新增与编辑入口', await readerManager.getByRole('button', { name: '新增员工', exact: true }).count() === 0
    && await readerManager.getByRole('button', { name: '更多操作', exact: true }).count() === 0);
  check('只读账号不能读取全员候选', (await api(activePage, listPath + 'employee-options/')).status === 403);
  check('只读账号直接提交新增仍被拒绝', (await api(activePage, listPath, { method: 'POST', body: {
    workshop: target.workshop_id, employee: target.first.id, position: '只读禁止写入', is_supervisor: false, status: 'ACTIVE',
  } })).status === 403);
  await screenshot(activePage, 'readonly_employee_list');
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
      not_covered: ['主业务库、历史数据回填与正式发布', '报工和领料由本单元后端业务测试覆盖', '主管不授角色及无账号主档保持不变由夹具数据库断言验证'],
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

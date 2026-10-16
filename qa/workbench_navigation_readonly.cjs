/**
 * 工作台双入口：真实 Session、真实 dashboard API、headless 只读验收。
 * 唯一允许的非 GET/HEAD/OPTIONS 请求为脚本自身的 POST /api/auth/login/。
 * 不创建账号、员工、授权或业务记录，不输出或保存密码、Cookie、完整业务响应。
 * 临时资源预登记：本项目 qa/_tmp/workbench-navigation-20261016/browser（浏览器临时目录及下载目录）。
 * 根目录及已有 session-state.json 由主任务管理；脚本仅创建、清理独占 browser 子目录。
 * 仅在 browser 确切目录不存在时创建；finally 关闭浏览器后核对边界、精确删除并复查。
 * 保留证据：本项目 qa/artifacts/workbench-navigation-20261016/ 的截图与最终 JSON。
 * 认证：QA_USERNAME/QA_PASSWORD，或 WORKBENCH_QA_STORAGE_STATE / QA_STORAGE_STATE（已有文件只读）。
 * 可选 QA_RESTRICTED_USERNAME/QA_RESTRICTED_PASSWORD 或 QA_RESTRICTED_STORAGE_STATE 覆盖低权限账号。
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const root = path.resolve(__dirname, '..');
const tempParent = path.join(root, 'qa', '_tmp', 'workbench-navigation-20261016');
const browserTemp = path.join(tempParent, 'browser');
const evidenceDir = path.join(root, 'qa', 'artifacts', 'workbench-navigation-20261016');
const stamp = new Date().toISOString().replace(/[:.]/g, '-') + '-' + process.pid;
const reportPath = path.join(evidenceDir, 'readonly-report-' + stamp + '.json');
const routes = [
  { key: 'manager', mode: 'MANAGER', name: 'manager-workbench', path: '/workbench/manager', title: '主管工作台', api: '/api/v1/dashboard/manager/', content: '.manager-workbench', section: '团队绩效', scope: 'MANAGER' },
  { key: 'sales', mode: 'SALES', name: 'sales-workbench', path: '/workbench/sales', title: '业务员工作台', api: '/api/v1/dashboard/me/', content: '.sales-workbench', section: '今日工作清单', scope: 'ME' },
];
const previousTemp = { TEMP: process.env.TEMP, TMP: process.env.TMP, TMPDIR: process.env.TMPDIR };
const report = {
  schemaVersion: 1, startedAt: new Date().toISOString(), status: 'RUNNING', mode: 'real-api-read-only',
  checks: [], screenshots: [], apiReads: [], dashboardResponses: [], blockedWrites: [], pageErrors: [], httpErrors: [], notCovered: [],
  resources: { browserTemp, parentManagedBy: '主任务', purpose: '本任务独占浏览器临时文件；关闭后精确删除', created: false, browserClosed: false, removed: false, verifiedAbsent: false },
};
let base, browser, ownsTemp = false, evidenceVerified = false, stage = 'preconditions', failureCaptured = false, escapeHypothesisChecked = false;

function stop(code, message, blocked = false) { const error = new Error(message); Object.assign(error, { code, safeQaMessage: true, blocked }); throw error; }
function check(condition, code, message) { if (!condition) stop(code, message); }
function digest(value) { return crypto.createHash('sha256').update(String(value)).digest('hex').slice(0, 16); }
function samePath(left, right) { const normalize = value => process.platform === 'win32' ? path.resolve(value).toLowerCase() : path.resolve(value); return normalize(left) === normalize(right); }
function safePath(value) { try { return new URL(value, base).pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, ':id'); } catch { return 'invalid-url'; } }
function note(message) { if (!report.notCovered.includes(message)) report.notCovered.push(message); }
function record(id, evidence = {}) { report.checks.push({ id, ...evidence }); }
function saveReport() { if (evidenceVerified) fs.writeFileSync(reportPath, JSON.stringify(report, null, 2)); }

function errorDetails(error) {
  const message = String(error?.message || '');
  const stack = String(error?.stack || '');
  const locations = [];
  for (const line of stack.split('\n').slice(1)) {
    const match = line.match(/((?:qa[\\/]workbench_navigation_readonly\.cjs|src[\\/]frontend[\\/]node_modules[\\/]playwright[^():\s]*|\/src\/[^():?\s]+)(?:\?[^():\s]*)?):(\d+):(\d+)/);
    if (match) locations.push({ file: match[1].split('?')[0].replaceAll('\\', '/'), line: Number(match[2]), column: Number(match[3]) });
  }
  const operation = message.match(/^((?:locator|page|browser|browserContext|apiRequestContext)\.[A-Za-z]+):/)?.[1];
  const runtime = message.match(/Cannot (?:read|set) properties of (?:undefined|null)(?: \(reading '[A-Za-z_$][\w$]*'\))?|[A-Za-z_$][\w$]* is not (?:a function|defined)|Cannot access '[A-Za-z_$][\w$]*' before initialization/)?.[0];
  return {
    category: /^[A-Za-z]+Error$/.test(error?.name || '') ? error.name : 'Error',
    ...(operation ? { operation } : {}), ...(runtime ? { runtime } : {}),
    ...(message.includes('intercepts pointer events') ? { reason: 'pointer-events-intercepted' } : message.includes('Timeout') ? { reason: 'timeout' } : {}),
    locations: locations.slice(0, 8), digest: digest(message),
  };
}

async function captureFailure(page, error) {
  if (failureCaptured || !page || page.isClosed()) return;
  failureCaptured = true;
  report.failureScene = { stage, error: errorDetails(error) };
  try {
    report.failureScene.dom = await page.evaluate(() => {
      const flyout = document.querySelector('[data-sidebar-flyout]');
      const rect = node => { const bounds = node.getBoundingClientRect(); return { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height }; };
      const titles = ['工作台', '主管工作台', '业务员工作台'];
      return {
        path: location.pathname, focusTag: document.activeElement?.tagName || '',
        focusInsideNavigation: Boolean(document.querySelector('.app-sidebar')?.contains(document.activeElement)),
        flyout: flyout ? { rect: rect(flyout), ariaHidden: flyout.getAttribute('aria-hidden'), display: getComputedStyle(flyout).display, opacity: getComputedStyle(flyout).opacity } : null,
        tabs: [...document.querySelectorAll('.global-page-tab')].map(node => {
          const button = node.querySelector('[data-tab-open]');
          const bounds = button?.getBoundingClientRect() || node.getBoundingClientRect();
          const target = document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
          const label = node.getAttribute('aria-label');
          return { title: titles.includes(label) ? label : ':other-page', selected: node.getAttribute('aria-selected'), rect: rect(node), disabled: button?.disabled ?? null, centerInsideTab: node.contains(target), centerInsideFlyout: Boolean(flyout?.contains(target)) };
        }),
      };
    });
    await screenshot(page, 'failure-' + stage.replace(/[^a-z0-9-]/gi, '-'), false);
  } catch (captureError) { report.failureScene.captureError = errorDetails(captureError); }
}

function credentials(restricted = false) {
  const prefix = restricted ? 'QA_RESTRICTED_' : 'QA_';
  return { username: process.env[prefix + 'USERNAME'], password: process.env[prefix + 'PASSWORD'], statePath: (!restricted && process.env.WORKBENCH_QA_STORAGE_STATE) || process.env[prefix + 'STORAGE_STATE'] };
}

async function readApi(context, api, kind, expectedStatus = 200) {
  let response;
  try { response = await context.request.get(new URL(api, base).href, { maxRedirects: 0 }); }
  catch { stop('API_UNREACHABLE', kind + ' 请求不可达；未保存请求细节。', true); }
  report.apiReads.push({ kind, path: api, status: response.status() });
  if (expectedStatus !== null) check(response.status() === expectedStatus, 'API_STATUS', kind + ' HTTP 状态不符合预期。');
  return response;
}

async function jsonBody(response, kind) {
  try { return await response.json(); } catch { stop('API_JSON', kind + ' 未返回有效 JSON。'); }
}

async function authenticate(context, auth, label) {
  let me = await jsonBody(await readApi(context, '/api/auth/me/', label + '-session-state'), '认证状态');
  if (auth.statePath) {
    if (!me.authenticated) stop('SESSION_EXPIRED', label + ' 已有 Session 失效。', true);
    record(label + '-authentication', { source: 'provided-session' });
  } else {
    const csrf = (await context.cookies(base.origin)).find(cookie => cookie.name === 'csrftoken')?.value;
    check(Boolean(csrf), 'CSRF_MISSING', '普通登录前没有取得 CSRF Cookie。');
    let response;
    try {
      response = await context.request.post(new URL('/api/auth/login/', base).href, {
        data: { username: auth.username, password: auth.password },
        headers: { 'X-CSRFToken': csrf, Referer: base.origin + '/' }, maxRedirects: 0,
      });
    } catch { stop('LOGIN_UNREACHABLE', label + ' 普通登录请求失败；未保存凭据。', true); }
    if (response.status() !== 200) stop('LOGIN_REJECTED', label + ' 普通登录被拒绝，请检查真实账号状态。', true);
    me = await jsonBody(await readApi(context, '/api/auth/me/', label + '-authenticated-state'), '登录后认证状态');
    if (!me.authenticated) stop('SESSION_MISSING', '普通登录后没有有效 Session。', true);
    record(label + '-authentication', { source: 'normal-session-csrf-login' });
  }
  check(Boolean(me.user), 'USER_CONTRACT', '有效 Session 没有用户信息。');
}

async function newContext(auth) {
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, locale: 'zh-CN', timezoneId: 'Asia/Shanghai',
    serviceWorkers: 'block', acceptDownloads: false, ...(auth?.statePath ? { storageState: path.resolve(auth.statePath) } : {}),
  });
  await context.route('**/*', async route => {
    const request = route.request();
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      report.blockedWrites.push({ method: request.method(), path: safePath(request.url()) });
      await route.abort('blockedbyclient'); return;
    }
    await route.continue();
  });
  return context;
}

function watchPage(page, label) {
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => report.pageErrors.push({ label, stage, kind: 'pageerror', ...errorDetails(error) }));
  page.on('console', message => { if (message.type() === 'error') report.pageErrors.push({ label, kind: 'console', digest: digest(message.text()) }); });
  page.on('response', response => {
    const pathname = safePath(response.url());
    if (response.status() >= 400 && new URL(response.url()).origin === base.origin) report.httpErrors.push({ label, path: pathname, status: response.status() });
    if (routes.some(route => route.api === pathname)) report.dashboardResponses.push({ label, path: pathname, status: response.status() });
  });
}

async function screenshot(page, name, settled = true) {
  if (settled) {
    await page.evaluate(() => document.fonts.ready);
    await page.waitForFunction(() => [...document.querySelectorAll('[data-workbench-page] [aria-busy="true"], [data-workbench-page] .el-loading-mask')].every(node => {
      const style = getComputedStyle(node), bounds = node.getBoundingClientRect();
      return style.display === 'none' || style.visibility === 'hidden' || bounds.width === 0 || bounds.height === 0;
    }));
  }
  const file = stamp + '-' + name + '.png';
  await page.screenshot({ path: path.join(evidenceDir, file), fullPage: true });
  report.screenshots.push(file);
}

async function openMenu(page, access, active) {
  const parent = page.locator('.app-sidebar [data-menu-key="workbench"]').first();
  await parent.hover();
  await page.locator('.app-sidebar__flyout-menu').waitFor({ state: 'visible' });
  await page.waitForFunction(() => {
    const node = document.querySelector('[data-sidebar-flyout]');
    return node && getComputedStyle(node).opacity === '1' && node.getAnimations().length === 0;
  });
  for (const route of routes) {
    const link = page.locator('.app-sidebar__flyout-menu a').filter({ hasText: route.title });
    if (access[route.key]) {
      check(await link.count() === 1 && await link.getAttribute('href') === route.path, 'MENU_ENTRY', route.title + ' 应有唯一合法入口。');
      if (active) check((await link.getAttribute('aria-current') === 'page') === (active.key === route.key), 'MENU_CURRENT', route.title + ' 菜单高亮错误。');
    } else check(await link.count() === 0, 'MENU_PERMISSION', route.title + ' 在 API 拒绝时仍显示入口。');
  }
  if (active) {
    check((await parent.getAttribute('class')).includes('is-active'), 'MENU_PARENT_ACTIVE', '工作台一级菜单没有高亮。');
    const link = page.locator('.app-sidebar__flyout-menu a[aria-current="page"]');
    check(await link.count() === 1 && (await link.getAttribute('class')).includes('is-active'), 'MENU_CHILD_ACTIVE', '工作台子菜单没有唯一选中态。');
    record('menu-highlight', { route: active.name, styles: await link.evaluate(node => { const style = getComputedStyle(node); return { color: style.color, backgroundColor: style.backgroundColor }; }) });
  }
}

async function closeMenu(page) {
  // hover 打开菜单不会转移焦点，Escape 仅在焦点位于导航内时由导航处理。
  if (!escapeHypothesisChecked) {
    const focusInsideNavigation = await page.evaluate(() => Boolean(document.querySelector('.app-sidebar')?.contains(document.activeElement)));
    await page.keyboard.press('Escape');
    record('hover-escape-diagnostic', { focusInsideNavigation, menuStillExpanded: await page.locator('.app-sidebar [data-menu-key="workbench"]').first().getAttribute('aria-expanded') === 'true' });
    escapeHypothesisChecked = true;
  }
  const viewport = page.viewportSize();
  await page.mouse.move(viewport.width - 20, viewport.height - 20);
  await page.locator('[data-sidebar-flyout]').waitFor({ state: 'hidden' });
}

async function checkPage(page, route, label) {
  await page.locator(route.content).waitFor();
  check(new URL(page.url()).pathname === route.path, 'ROUTE_PATH', route.title + ' 地址错误。');
  check(await page.locator('[data-workbench-page]').getAttribute('data-workbench-mode') === route.mode, 'ROUTE_MODE', route.title + ' 模式错误。');
  check((await page.locator('.workbench-page__heading h1').innerText()).trim() === route.title, 'PAGE_TITLE', route.title + ' 页面标题错误。');
  check(await page.locator(route.content).getByText(route.section, { exact: true }).count() === 1, 'PAGE_CONTENT', route.title + ' 内容区不匹配。');
  check(await page.locator('.workbench-inline-error').count() === 0, 'DASHBOARD_ERROR', route.title + ' 显示汇总 API 错误。');
  const other = routes.find(item => item.key !== route.key);
  check(await page.locator(other.content).count() === 0, 'MODE_ISOLATION', '同时显示两种工作台内容。');
  const tab = page.getByRole('tab', { name: route.title, exact: true });
  check(await tab.count() === 1 && await tab.getAttribute('aria-selected') === 'true', 'PAGE_TAB', route.title + ' 页签没有唯一选中。');
  record(label, { route: route.name, path: route.path });
}

async function discoverAccess(context, label) {
  const access = {};
  for (const route of routes) {
    const response = await readApi(context, route.api, label + '-' + route.key + '-dashboard', null);
    if ([401, 403].includes(response.status())) access[route.key] = false;
    else {
      if (response.status() === 404) stop('DASHBOARD_NOT_READY', route.title + ' 真实 API 尚不可用。', true);
      check(response.status() === 200, 'DASHBOARD_STATUS', route.title + ' 真实 API 发生错误。');
      const body = await jsonBody(response, route.title);
      check(body.meta?.scope === route.scope && body.data?.counts && Object.values(body.data.counts).every(value => Number.isSafeInteger(value) && value >= 0), 'DASHBOARD_CONTRACT', route.title + ' 真实 API 契约错误。');
      access[route.key] = true;
    }
  }
  record(label + '-api-permissions', { access });
  return access;
}

async function verifyUnauthenticated() {
  const context = await newContext();
  let page;
  try {
    const me = await jsonBody(await readApi(context, '/api/auth/me/', 'unauthenticated-session'), '未登录状态');
    check(me.authenticated === false, 'UNAUTH_SESSION', '全新浏览器上下文意外带有登录会话。');
    page = await context.newPage(); watchPage(page, 'unauthenticated');
    for (const route of routes) {
      const before = report.dashboardResponses.length;
      await page.goto(new URL(route.path, base).href, { waitUntil: 'networkidle' });
      check(new URL(page.url()).pathname === '/login', 'UNAUTH_ROUTE', '未登录访问工作台未进入登录页。');
      check(new URL(page.url()).searchParams.get('redirect') === route.path, 'UNAUTH_REDIRECT', '登录页未保留原始工作台地址。');
      check(report.dashboardResponses.length === before && await page.locator('[data-workbench-page]').count() === 0, 'UNAUTH_DATA', '未登录页面尝试加载工作台数据。');
      record('unauthenticated-route', { route: route.name });
    }
    await screenshot(page, 'unauthenticated-login');
  } catch (error) { await captureFailure(page, error); throw error; }
  finally { await context.close(); }
}

async function verifyDenied(page, route, label) {
  const before = report.dashboardResponses.length;
  await page.goto(new URL(route.path, base).href, { waitUntil: 'networkidle' });
  check(await page.locator(route.content).count() === 0, 'DENIED_CONTENT', '无权限账号仍显示 ' + route.title + ' 内容。');
  check(new URL(page.url()).pathname !== route.path || await page.locator('.workbench-forbidden').isVisible(), 'DENIED_ROUTE', '无权限地址没有跳转或权限说明。');
  check(!report.dashboardResponses.slice(before).some(item => item.path === route.api), 'DENIED_API_READ', '前端路由未阻止无权限 dashboard 请求。');
  record(label + '-denied-route', { route: route.name });
  await screenshot(page, label + '-denied-' + route.key);
}

async function verifyAccount(auth, label, positive) {
  const context = await newContext(auth);
  let page;
  try {
    await authenticate(context, auth, label);
    const access = await discoverAccess(context, label);
    const allowed = routes.filter(route => access[route.key]);
    if (positive && !allowed.length) stop('NO_WORKBENCH_PERMISSION', '当前真实账号没有任一工作台访问权限。', true);
    page = await context.newPage(); watchPage(page, label);
    if (positive) {
      await page.goto(new URL('/', base).href, { waitUntil: 'networkidle' });
      check(new URL(page.url()).pathname === '/' && await page.locator('[data-workbench-page]').count() === 1, 'HOME_COMPATIBILITY', '原 / 地址未保持工作台兼容。');
      record('legacy-home-compatible');
      for (const route of allowed) {
        stage = label + '-' + route.key;
        await openMenu(page, access);
        const start = report.dashboardResponses.length;
        await Promise.all([
          page.waitForResponse(response => safePath(response.url()) === route.api && response.request().method() === 'GET'),
          page.locator('.app-sidebar__flyout-menu a[href="' + route.path + '"]').click(),
        ]);
        await page.waitForLoadState('networkidle');
        await checkPage(page, route, 'menu-route-content');
        check(report.dashboardResponses.slice(start).some(item => item.path === route.api && item.status === 200), 'PAGE_REAL_API', route.title + ' 没有读取正确的真实 dashboard。');
        check(!report.dashboardResponses.slice(start).some(item => item.path !== route.api), 'PAGE_WRONG_API', route.title + ' 加载了另一工作台 dashboard。');
        await screenshot(page, label + '-' + route.key + '-route');
        await openMenu(page, access, route); await screenshot(page, label + '-' + route.key + '-menu');
        await closeMenu(page);
        stage = label + '-' + route.key + '-reload';
        const reloadStart = report.dashboardResponses.length;
        await page.reload({ waitUntil: 'networkidle' });
        await checkPage(page, route, 'refresh-retains-route');
        check(report.dashboardResponses.slice(reloadStart).some(item => item.path === route.api && item.status === 200)
          && !report.dashboardResponses.slice(reloadStart).some(item => item.path !== route.api), 'REFRESH_REAL_API', '刷新后没有保持正确的真实 dashboard。');
        await openMenu(page, access, route); await closeMenu(page);
      }
      if (allowed.length === 2) {
        stage = label + '-tab-identities';
        const tabs = await Promise.all(routes.map(route => page.getByRole('tab', { name: route.title, exact: true }).getAttribute('data-tab-id')));
        check(tabs.every(Boolean) && tabs[0] !== tabs[1], 'TAB_IDENTITY', '两个工作台共用了同一个页签。');
        for (const route of routes) {
          stage = label + '-tab-switch-' + route.key;
          await page.getByRole('tab', { name: route.title, exact: true }).locator('[data-tab-open]').click();
          await page.waitForLoadState('networkidle'); await checkPage(page, route, 'tab-switch-retains-mode');
        }
        record('distinct-workbench-tabs', { count: tabs.length });
        await screenshot(page, label + '-distinct-tabs');
      } else note('UNKNOWN：当前账号仅能合法访问一个工作台，另一个合法入口及两个页签并存未覆盖；不创建授权补齐。');
    } else {
      await page.goto(new URL('/', base).href, { waitUntil: 'networkidle' });
      if (allowed.length) { await openMenu(page, access); await screenshot(page, label + '-menu-permissions'); await closeMenu(page); }
      else check(await page.locator('.app-sidebar [data-menu-key="workbench"]').count() === 0, 'NO_PERMISSION_MENU', '没有任何工作台权限时仍显示一级菜单。');
    }
    const denied = routes.filter(route => !access[route.key]);
    for (const route of denied) await verifyDenied(page, route, label);
    if (!positive && denied.length === 0) note('UNKNOWN：提供的第二账号可访问两个工作台，未覆盖真实低权限拒绝。');
    check(!report.pageErrors.some(item => item.label === label) && !report.httpErrors.some(item => item.label === label), 'PAGE_ERRORS', '页面存在控制台、脚本或 HTTP 错误，报告仅保存脱敏诊断。');
    return denied.length;
  } catch (error) { await captureFailure(page, error); throw error; }
  finally { await context.close(); }
}

async function main() {
  try { base = new URL(process.env.WORKBENCH_QA_BASE_URL || process.env.QA_BASE_URL || 'http://localhost:8080'); } catch { stop('BASE_URL_INVALID', 'QA_BASE_URL 无效。', true); }
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.pathname !== '/' || base.search || base.hash) stop('BASE_URL_INVALID', 'QA_BASE_URL 应为不含凭据、路径、查询参数的 HTTP(S) 源地址。', true);
  fs.mkdirSync(evidenceDir, { recursive: true });
  check(samePath(fs.realpathSync(evidenceDir), evidenceDir), 'EVIDENCE_BOUNDARY', '证据目录存在未确认的重定向。');
  evidenceVerified = true; saveReport();
  const auth = credentials(), restricted = credentials(true);
  if (!(auth.statePath || auth.username && auth.password)) stop('AUTH_REQUIRED', '缺少 QA_USERNAME/QA_PASSWORD 或 WORKBENCH_QA_STORAGE_STATE / QA_STORAGE_STATE；未启动浏览器，不自动创建账号。', true);
  for (const source of [auth, restricted]) if (source.statePath && (!fs.existsSync(source.statePath) || !fs.statSync(source.statePath).isFile())) stop('STATE_NOT_FOUND', '指定的已有 Session 文件不可读取。', true);
  if ((restricted.username || restricted.password) && !(restricted.username && restricted.password)) stop('RESTRICTED_AUTH_INCOMPLETE', '第二账号的 QA_RESTRICTED_USERNAME/PASSWORD 必须成对设置。', true);
  const executablePath = process.env.QA_BROWSER_PATH || process.env.QA_CHROME_PATH || [
    'C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  ].find(candidate => fs.existsSync(candidate));
  if (!executablePath || !fs.existsSync(executablePath)) stop('BROWSER_MISSING', '没有可用的已安装 Chrome/Edge；不会安装新依赖。', true);
  let chromium;
  try { ({ chromium } = require('../src/frontend/node_modules/playwright-core')); } catch { stop('PLAYWRIGHT_MISSING', '项目现有 playwright-core 不可用；不会安装新依赖。', true); }
  if (fs.existsSync(browserTemp)) stop('TEMP_EXISTS', '登记的浏览器临时目录已存在，拒绝覆盖或清理来源不明资源。', true);
  if (!fs.existsSync(tempParent) || !fs.statSync(tempParent).isDirectory()) stop('TEMP_ROOT_MISSING', '请先按任务登记创建工作台临时根目录；脚本只管理 browser 子目录。', true);
  check(samePath(fs.realpathSync(tempParent), tempParent), 'TEMP_BOUNDARY', '浏览器临时目录父路径存在未确认的重定向。');
  saveReport(); // 创建前保存资源登记。
  fs.mkdirSync(browserTemp); ownsTemp = true; report.resources.created = true;
  for (const key of Object.keys(previousTemp)) process.env[key] = browserTemp;
  browser = await chromium.launch({ executablePath, headless: true, downloadsPath: path.join(browserTemp, 'downloads'), env: { ...process.env, TEMP: browserTemp, TMP: browserTemp, TMPDIR: browserTemp } });
  stage = 'unauthenticated'; await verifyUnauthenticated();
  stage = 'primary-account'; let deniedCount = await verifyAccount(auth, 'primary', true);
  if (restricted.statePath || restricted.username && restricted.password) { stage = 'restricted-account'; deniedCount += await verifyAccount(restricted, 'restricted', false); }
  if (!deniedCount) note('UNKNOWN：未提供已有低权限账号，未验证真实低权限菜单隐藏及路由拒绝；未创建员工或修改授权。');
  check(report.blockedWrites.length === 0, 'BUSINESS_WRITE_ATTEMPT', '页面尝试了非只读请求，已拦截并判失败。');
  check(report.pageErrors.length === 0 && report.httpErrors.length === 0, 'PAGE_ERRORS', '页面存在控制台、脚本或 HTTP 错误，报告仅保存摘要。');
  record('read-only-boundary', { blockedWrites: 0, pageErrors: 0, httpErrors: 0 });
  report.status = report.notCovered.length ? 'PASS_WITH_GAPS' : 'PASS';
}

(async () => {
  try { await main(); }
  catch (error) {
    report.status = error.blocked ? 'BLOCKED' : 'FAIL'; process.exitCode = 1;
    report.failure = { stage, code: error.safeQaMessage ? error.code : 'UNEXPECTED', message: error.safeQaMessage ? error.message : '执行异常；未输出可能含业务值的原始错误。', ...errorDetails(error) };
  } finally {
    let canRemove = !browser;
    if (browser) {
      try { await browser.close(); report.resources.browserClosed = true; canRemove = true; }
      catch { report.resources.closeFailed = true; report.status = 'FAIL'; process.exitCode = 1; }
    }
    for (const key of Object.keys(previousTemp)) { if (previousTemp[key] === undefined) delete process.env[key]; else process.env[key] = previousTemp[key]; }
    if (ownsTemp && canRemove) {
      try {
        check(samePath(path.dirname(browserTemp), tempParent) && samePath(fs.realpathSync(browserTemp), browserTemp) && !fs.lstatSync(browserTemp).isSymbolicLink(), 'CLEANUP_BOUNDARY', '临时目录归属或边界核验失败。');
        fs.rmSync(browserTemp, { recursive: true, force: false }); report.resources.removed = true;
      } catch { report.resources.cleanupFailed = true; report.status = 'FAIL'; process.exitCode = 1; }
    }
    report.resources.verifiedAbsent = !fs.existsSync(browserTemp);
    if (ownsTemp && !report.resources.verifiedAbsent) { report.status = 'FAIL'; process.exitCode = 1; }
    report.finishedAt = new Date().toISOString(); saveReport();
    console.log(JSON.stringify({ qa_result_version: 1, status: report.status, not_covered: report.notCovered, checks: report.checks.length, failure: report.failure, report: evidenceVerified ? reportPath : null, cleanup: report.resources.verifiedAbsent && !report.resources.cleanupFailed }));
  }
})();

/** 采购来源与产品列：真实 API、已有 Session、headless；禁止所有非 GET/HEAD 请求及保存。 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('../src/frontend/node_modules/playwright-core');
const root = path.resolve(__dirname, '..');
const taskRoot = path.join(root, '.tmp', 'purchase_source_columns_20261016');
const profile = path.join(taskRoot, 'profile');
const output = process.env.QA_REPORT_DIR ? path.resolve(process.env.QA_REPORT_DIR, 'purchase-source-columns') : path.join(root, 'output', 'playwright', 'purchase-source-columns-20261016');
const base = new URL(process.env.PURCHASE_SOURCE_QA_BASE_URL || 'http://localhost:8080');
const expectedHeaders = ['选择', '产品编码', '货号', '产品名称', '规格', '颜色', '材质', '订单数量', 'BOM状态'];
const report = { qa_result_version: 1, mode: 'real-api-read-only', startedAt: new Date().toISOString(), status: 'RUNNING',
  checks: [], observations: [], measurements: [], screenshots: [], apiReads: [], blockedWrites: [], httpErrors: [], pageErrors: [], hashComparisons: [], notCovered: [],
  resources: { profile, output, created: false, browserClosed: false, removed: false, verifiedAbsent: false } };
let context, outputReady = false, step = 'startup';
function requireCondition(condition, code, message) { if (!condition) { const error = new Error(message); error.code = code; error.qaSafe = true; throw error; } }
function check(condition, code, detail = {}) { report.checks.push({ code, passed: Boolean(condition), ...detail }); }
function gap(message) { if (!report.notCovered.includes(message)) report.notCovered.push(message); }
function digest(value) { return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex'); }
function safeRoute(value) { try { return new URL(value, base).pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, ':id'); } catch { return 'invalid-url'; } }
function inside(candidate, parent) { const relative = path.relative(fs.realpathSync(parent), fs.realpathSync(candidate)); return relative !== '' && !relative.startsWith('..') && !path.isAbsolute(relative); }
function failure(error, fallback) { check(false, error.code || fallback, { step, message: error.qaSafe ? error.message : '检查未完成；未输出请求正文、会话凭据或响应正文。', errorType: error.name }); }
async function getJson(route, kind) {
  const url = new URL(route, base);
  requireCondition(url.origin === base.origin && url.pathname.startsWith('/api/'), 'API_SCOPE', '只允许读取指定本机 API。');
  const response = await context.request.get(url.href, { maxRedirects: 0 });
  report.apiReads.push({ kind, route: safeRoute(url.href), status: response.status() });
  requireCondition(response.status() === 200, 'API_UNAVAILABLE', '只读 API 不可用：' + kind + '，HTTP ' + response.status());
  return response.json();
}
function stableSource(data) { return { production_task: data.production_task, bom_options: data.bom_options, selected_bom_id: data.selected_bom_id, can_create: data.can_create, blockers: data.blockers, lines: data.lines, preview_lines: data.preview_lines }; }
async function screenshot(page, name) { const file = path.join(output, name + '.png'); await page.screenshot({ path: file, fullPage: true }); report.screenshots.push(file); }
async function measure(page, scope) {
  const value = await page.evaluate(() => {
    function item(node) {
      if (!node?.getClientRects().length) return null;
      const r = node.getBoundingClientRect(), s = getComputedStyle(node);
      const pseudo = name => { const p = getComputedStyle(node, name); return { content: p.content, border: [p.borderTop, p.borderRight, p.borderBottom, p.borderLeft], background: p.backgroundColor }; };
      return { text: node.textContent.trim(), x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height, clientWidth: node.clientWidth, scrollWidth: node.scrollWidth, clientHeight: node.clientHeight, scrollHeight: node.scrollHeight,
        background: s.backgroundColor, border: [s.borderTop, s.borderRight, s.borderBottom, s.borderLeft], padding: [s.paddingTop, s.paddingRight, s.paddingBottom, s.paddingLeft], fontSize: s.fontSize, fontWeight: s.fontWeight, lineHeight: s.lineHeight, radius: s.borderRadius, grid: s.gridTemplateColumns, overflow: [s.overflowX, s.overflowY], shadow: s.boxShadow, before: pseudo('::before'), after: pseudo('::after') };
    }
    const heading = document.querySelector('.selected-product-row--heading');
    const rows = [...document.querySelectorAll('.selected-product-row--option')];
    return { viewport: { width: innerWidth, height: innerHeight }, documentWidth: document.documentElement.scrollWidth,
      card: item(document.querySelector('.task-card')), container: item(document.querySelector('.selected-product-list')), heading: item(heading), headings: heading ? [...heading.children].map(item) : [],
      rows: rows.map(node => ({ selected: node.dataset.selected, disabled: node.getAttribute('aria-disabled'), row: item(node), cells: [...node.children].map(item) })),
      popups: [...document.querySelectorAll('.purchase-source-popper')].filter(node => node.getClientRects().length).map(item) };
  });
  report.measurements.push({ scope, value });
  check(value.documentWidth <= value.viewport.width + 1, 'NO_PAGE_HORIZONTAL_OVERFLOW', { scope });
  check(value.popups.every(p => p.x >= -1 && p.right <= value.viewport.width + 1 && p.y >= -1 && p.bottom <= value.viewport.height + 1), 'POPUP_WITHIN_VIEWPORT', { scope });
  return value;
}
function checkProductLayout(value, scope, hovered = false) {
  const { card, container, heading, headings, rows } = value;
  requireCondition(Boolean(card && container && heading && rows.length), 'PRODUCT_LAYOUT_MISSING', '产品表缺少可测量布局。');
  const near = (a, b) => Math.abs(a - b) <= 1;
  const noBorder = node => node.border.every(border => border.startsWith('0px'));
  const noPseudoBorder = node => [node.before, node.after].every(pseudo => ['none', 'normal'].includes(pseudo.content) && pseudo.border.every(border => border.startsWith('0px')));
  check(near(heading.height, 42) && rows.every(row => near(row.row.height, 43)), 'HEADER_42_AND_ROWS_43_PIXELS', { scope, heading: heading.height, rows: rows.map(row => row.row.height) });
  check(headings.length === 9 && headings.every(cell => cell.width > 0 && cell.scrollWidth <= cell.clientWidth + 1), 'ALL_NINE_HEADERS_FULLY_VISIBLE', { scope });
  check(headings.every(cell => cell.padding[1] === '8px' && cell.padding[3] === '8px') && rows.every(row => row.cells.slice(1).every(cell => cell.padding[1] === '8px' && cell.padding[3] === '8px')), 'CELL_HORIZONTAL_PADDING_8_PIXELS', { scope });
  check(heading.background === 'rgb(240, 234, 223)', 'HEADER_BACKGROUND_PRESERVED', { scope });
  check(rows.every(row => row.row.background === (hovered ? 'rgb(255, 246, 234)' : 'rgb(247, 229, 220)')), 'PRODUCT_STATE_BACKGROUND', { scope, state: hovered ? 'hover' : 'selected' });
  check(card.border.every(border => border === '1px solid rgb(221, 214, 201)') && noBorder(container) && noBorder(heading) && noPseudoBorder(container) && noPseudoBorder(heading), 'CARD_OWNS_SINGLE_OUTER_BORDER', { scope });
  check(rows.every(row => row.row.border[0] === '1px solid rgb(234, 228, 218)' && row.row.border.slice(1).every(border => border.startsWith('0px')) && noPseudoBorder(row.row) && row.cells.slice(1).every(cell => noBorder(cell) && noPseudoBorder(cell))), 'SINGLE_ROW_SEPARATOR_WITHOUT_CELL_BORDER_OVERLAP', { scope });
  check(rows.every(row => row.cells.length === headings.length && row.cells.slice(1).every((cell, index) => near(cell.x, headings[index + 1].x) && near(cell.width, headings[index + 1].width)) && near(row.cells[0].x + row.cells[0].width / 2, headings[0].x + headings[0].width / 2)), 'HEADER_DATA_COLUMNS_ALIGNED', { scope });
  check(container.scrollWidth <= container.clientWidth + 1 && container.scrollHeight <= container.clientHeight + 1 && container.x >= card.x && container.right <= card.right && rows.every(row => row.cells[0].x >= container.x && row.cells.at(-1).right <= container.right + 1 && row.row.y >= heading.bottom - 1 && row.row.bottom <= container.bottom + 1), 'FIRST_LAST_CELLS_WITHIN_CARD_WITHOUT_EXTRA_SCROLL', { scope });
  const quantityIndex = expectedHeaders.indexOf('订单数量'), statusIndex = expectedHeaders.indexOf('BOM状态');
  check(rows.every(row => [quantityIndex, statusIndex].every(index => row.cells[index] && row.cells[index].scrollWidth <= row.cells[index].clientWidth + 1)), 'QUANTITY_AND_BOM_STATUS_FULLY_VISIBLE', { scope });
}
async function openSources(page) {
  const combo = page.getByRole('combobox', { name: '选择采购来源', exact: true });
  await combo.click();
  const id = await combo.getAttribute('aria-controls');
  requireCondition(Boolean(id), 'SOURCE_LIST_MISSING', '采购来源下拉列表缺少关联。');
  const list = page.locator('[id="' + id + '"]');
  await list.waitFor({ state: 'visible' });
  return { combo, list };
}
async function inspectViewport(task, source, viewport) {
  const scope = viewport.width + 'x' + viewport.height;
  step = scope + '-open';
  const page = await context.newPage();
  page.on('pageerror', error => report.pageErrors.push({ scope, type: error.name }));
  await page.setViewportSize(viewport);
  await page.goto(new URL('/purchase-orders/new', base).href, { waitUntil: 'networkidle' });
  await page.getByTestId('purchase-order-form-page').waitFor({ state: 'visible' });
  const { combo, list } = await openSources(page);
  await list.locator('.task-select-option[data-task-id="' + task.id + '"]').waitFor({ state: 'visible' });
  const candidates = await list.locator('.task-select-option strong').allTextContents();
  report.observations.push({ scope, candidates });
  check(!candidates.some(value => value.trim() === 'HT26003'), 'NO_BOM_TASK_EXCLUDED_FROM_DROPDOWN', { scope });
  await measure(page, scope + '-source-popup');
  await screenshot(page, 'source-popup-' + scope);
  await combo.fill('HT26003');
  await page.waitForTimeout(350);
  check(await list.locator('.task-select-option:visible').count() === 0, 'NO_BOM_TASK_SEARCH_HAS_NO_OPTION', { scope });
  await screenshot(page, 'source-search-no-bom-' + scope);
  await combo.fill('HT26001');
  const candidate = list.locator('.task-select-option[data-task-id="' + task.id + '"]');
  await candidate.waitFor({ state: 'visible' });
  const option = candidate.locator('..');
  check((await option.getAttribute('aria-disabled')) !== 'true' && !(await option.getAttribute('class') || '').includes('is-disabled'), 'VALID_BOM_TASK_SELECTABLE', { scope });
  step = scope + '-select-existing-task';
  await candidate.click();
  await page.locator('.selected-product-row--option').first().waitFor({ state: 'visible' });
  await page.locator('.el-loading-mask').waitFor({ state: 'hidden' });
  await page.locator('.selected-product-row--heading').hover();
  const measured = await measure(page, scope + '-selected');
  checkProductLayout(measured, scope + '-selected');
  await screenshot(page, 'product-columns-' + scope);
  const headings = measured.headings.map(cell => cell.text);
  report.observations.push({ scope, headers: headings, rows: measured.rows.map(row => ({ selected: row.selected, cells: row.cells.map(cell => cell.text) })) });
  check(JSON.stringify(headings) === JSON.stringify(expectedHeaders), 'EXPECTED_NINE_PRODUCT_HEADERS', { scope, actual: headings });
  check(measured.rows.length === source.production_task.products.length, 'PRODUCT_ROW_COUNT_MATCHES_REAL_API', { scope, count: measured.rows.length });
  const product = source.production_task.products[0];
  const cells = measured.rows[0]?.cells || [];
  const cell = label => cells[headings.indexOf(label)]?.text;
  check(cell('产品编码') === product.product_code, 'PRODUCT_CODE_PRESERVED', { scope });
  check(!headings.includes('产品编号'), 'DUPLICATE_PRODUCT_NUMBER_COLUMN_REMOVED', { scope });
  check(cell('规格') === '47*55*79', 'SPECIFICATION_SHOWN_SEPARATELY', { scope, actual: cell('规格') });
  check(cell('颜色') === '酒红色', 'COLOR_NAME_SHOWN_SEPARATELY', { scope, actual: cell('颜色') });
  check(cell('材质') === 'PE', 'MATERIAL_SHOWN_SEPARATELY', { scope, actual: cell('材质') });
  const colorCell = page.locator('.selected-product-row--option').first().locator(':scope > span').nth(expectedHeaders.indexOf('颜色'));
  const colorTitle = await colorCell.getAttribute('title');
  check([product.color_card, product.color_name, product.color_code].filter(Boolean).every(value => colorTitle?.includes(value)), 'FULL_COLOR_REFERENCE_PRESERVED_IN_TITLE', { scope });
  check(await page.getByTestId('purchase-source-next').isDisabled(), 'UNRESOLVED_ACCESSORIES_KEEP_NEXT_DISABLED', { scope });
  report.observations.push({ scope, caption: await page.locator('.product-selection-caption').innerText() });
  const row = page.locator('.selected-product-row--option').first();
  await row.hover();
  checkProductLayout(await measure(page, scope + '-hover'), scope + '-hover', true);
  await screenshot(page, 'product-hover-' + scope);
  gap('真实订单只有一个已默认选中的产品；未选中行的 default 状态、多产品首末行分别显示未覆盖，未改 DOM 或伪造数据。');
  await page.close();
}
async function main() {
  const stateFile = process.env.PURCHASE_SOURCE_QA_STORAGE_STATE;
  requireCondition(Boolean(stateFile) && fs.existsSync(stateFile), 'STORAGE_STATE_REQUIRED', '需要已登记的现有 Session 文件，禁止自动登录。');
  const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
  requireCondition(Array.isArray(state.cookies), 'INVALID_STORAGE_STATE', '现有会话格式无效。');
  requireCondition(/^https?:$/.test(base.protocol) && ['localhost', '127.0.0.1'].includes(base.hostname), 'TARGET_SCOPE', '只允许本机开发服务。');
  const executablePath = [process.env.PURCHASE_SOURCE_QA_BROWSER_PATH, 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'].filter(Boolean).find(file => fs.existsSync(file));
  requireCondition(Boolean(executablePath), 'BROWSER_MISSING', '没有可用的已安装浏览器。');
  requireCondition(!fs.existsSync(profile), 'PROFILE_ALREADY_EXISTS', '独占 profile 已存在，禁止覆盖既有目录。');
  requireCondition(fs.existsSync(taskRoot) && inside(taskRoot, root), 'PROFILE_ROOT_SCOPE', '登记的临时父目录不存在或越界。');
  fs.mkdirSync(output, { recursive: true }); outputReady = true;
  fs.mkdirSync(profile); report.resources.created = true;
  requireCondition(inside(profile, taskRoot) && fs.realpathSync(profile) === path.join(fs.realpathSync(taskRoot), 'profile'), 'PROFILE_SCOPE', 'profile 不在登记范围。');
  process.env.TEMP = profile; process.env.TMP = profile; process.env.TMPDIR = profile;
  context = await chromium.launchPersistentContext(profile, { executablePath, headless: true, locale: 'zh-CN', serviceWorkers: 'block', env: { ...process.env, TEMP: profile, TMP: profile, TMPDIR: profile } });
  context.setDefaultTimeout(15000);
  await context.addCookies(state.cookies);
  await context.addInitScript(({ origins }) => { const match = (origins || []).find(item => item.origin === location.origin); for (const entry of match?.localStorage || []) localStorage.setItem(entry.name, entry.value); }, { origins: state.origins || [] });
  await context.route('**/*', async route => {
    const request = route.request();
    if (!['GET', 'HEAD'].includes(request.method())) { report.blockedWrites.push({ method: request.method(), route: safeRoute(request.url()) }); await route.abort('blockedbyclient'); }
    else await route.continue();
  });
  context.on('response', response => { if (!new URL(response.url()).pathname.startsWith('/api/')) return; const value = { method: response.request().method(), route: safeRoute(response.url()), status: response.status() }; report.apiReads.push(value); if (value.status >= 400) report.httpErrors.push(value); });
  const auth = await getJson('/api/auth/me/', 'existing-session');
  requireCondition(auth.authenticated === true, 'SESSION_EXPIRED', '现有 Session 已过期，禁止自动登录。');
  const options = (await getJson('/api/v1/purchase-orders/options/?scope=sources', 'source-options')).data;
  requireCondition(Array.isArray(options?.production_tasks), 'OPTIONS_CONTRACT', '采购来源接口结构不符合契约。');
  const task = options.production_tasks.find(item => item.task_number === 'HT26001');
  requireCondition(Boolean(task), 'TARGET_TASK_MISSING', '真实 HT26001 来源不存在，未创建替代记录。');
  check(!options.production_tasks.some(item => item.task_number === 'HT26003'), 'NO_BOM_TASK_EXCLUDED_FROM_API');
  check(task.can_create === true, 'VALID_BOM_TASK_AVAILABLE_IN_LIGHTWEIGHT_OPTIONS');
  const sourceRoute = '/api/v1/purchase-orders/source/?production_task_id=' + encodeURIComponent(task.id);
  const source = (await getJson(sourceRoute, 'source-preview')).data;
  requireCondition(source?.production_task?.products?.length > 0, 'TARGET_PRODUCTS_MISSING', '真实订单缺少产品数据。');
  const invalidLines = (source.blockers || []).filter(item => item.code === 'BOM_MATERIAL_IDENTITY_INVALID').flatMap(item => item.invalid_lines || []);
  report.observations.push({ products: source.production_task.products.map(p => ({ product_number: p.product_number, product_code: p.product_code, specification: p.specification, specification_display: p.specification_display, color_name: p.color_name, material: p.material })), blockers: source.blockers?.map(b => ({ code: b.code, message: b.message, invalid_line_count: b.invalid_line_count })), invalidLines: invalidLines.map(line => ({ reason: line.reason, section_title: line.section_title })), can_create: source.can_create });
  const product = source.production_task.products[0];
  check(product.specification === '47*55*79；颜色：酒红色；材质：PE', 'ORIGINAL_SPECIFICATION_SNAPSHOT_PRESERVED');
  check(product.specification_display === '47*55*79' && product.material === 'PE', 'API_SEPARATE_DISPLAY_FIELDS');
  check(source.can_create === false && invalidLines.length === 6 && invalidLines.every(line => line.reason === 'MATERIAL_IDENTITY_UNRESOLVED' && line.section_title.includes('辅料')), 'EXISTING_SIX_ACCESSORY_BLOCKERS_PRESERVED');
  for (const viewport of [{ width: 1101, height: 884 }, { width: 1440, height: 900 }]) await inspectViewport(task, source, viewport);
  const after = (await getJson(sourceRoute, 'source-after-readonly-flow')).data;
  const beforeHash = digest(stableSource(source)), afterHash = digest(stableSource(after));
  report.hashComparisons.push({ scope: 'purchase-source-business-fields-excluding-dynamic-token', beforeHash, afterHash, equal: beforeHash === afterHash });
  check(beforeHash === afterHash, 'SERVER_SOURCE_BUSINESS_FIELDS_UNCHANGED');
  check(report.blockedWrites.length === 0, 'NO_NETWORK_WRITE_ATTEMPTS', { count: report.blockedWrites.length });
  check(report.httpErrors.length === 0, 'NO_API_HTTP_ERRORS', { count: report.httpErrors.length });
  check(report.pageErrors.length === 0, 'NO_BROWSER_RUNTIME_ERRORS', { count: report.pageErrors.length });
  gap('真实空产品、多产品、接口错误和权限不足状态没有现成目标数据，未 Mock、造数或修改权限。');
  gap('本脚本只读，不保存采购单，也不修复或绕过六条辅料原料身份阻断；不声称采购写入链路通过。');
}
main().catch(error => { failure(error, 'QA_ABORTED'); report.status = ['STORAGE_STATE_REQUIRED', 'SESSION_EXPIRED', 'BROWSER_MISSING', 'PROFILE_ALREADY_EXISTS', 'TARGET_TASK_MISSING', 'TARGET_PRODUCTS_MISSING', 'API_UNAVAILABLE'].includes(error.code) ? 'BLOCKED' : 'FAIL'; }).finally(async () => {
  if (context) { try { await context.close(); report.resources.browserClosed = true; } catch { check(false, 'BROWSER_CLOSE_FAILED'); } }
  if (report.resources.created) {
    try {
      requireCondition(!context || report.resources.browserClosed, 'PROFILE_IN_USE', '浏览器未关闭，停止清理。');
      requireCondition(inside(profile, taskRoot) && fs.realpathSync(profile) === path.join(fs.realpathSync(taskRoot), 'profile'), 'CLEANUP_SCOPE', 'profile 不在登记范围，停止清理。');
      fs.rmSync(profile, { recursive: true, force: false }); report.resources.removed = true; report.resources.verifiedAbsent = !fs.existsSync(profile);
      check(report.resources.verifiedAbsent, 'PROFILE_CLEANED_AND_VERIFIED');
    } catch (error) { failure(error, 'PROFILE_CLEANUP_FAILED'); }
  }
  if (report.status === 'RUNNING') report.status = report.checks.some(item => !item.passed) ? 'FAIL' : report.notCovered.length ? 'PASS_WITH_GAPS' : 'PASS';
  if (report.resources.created && !report.resources.verifiedAbsent) report.status = 'FAIL';
  report.finishedAt = new Date().toISOString();
  if (outputReady) fs.writeFileSync(path.join(output, 'readonly-report.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ qa_result_version: 1, mode: report.mode, status: report.status, not_covered: report.notCovered, cleanup: !report.resources.created || report.resources.verifiedAbsent, checks: report.checks.length, failed: report.checks.filter(item => !item.passed).length, failure: report.checks.find(item => !item.passed), report: outputReady ? path.join(output, 'readonly-report.json') : null }));
  process.exitCode = ['PASS', 'PASS_WITH_GAPS'].includes(report.status) ? 0 : report.status === 'BLOCKED' ? 2 : 1;
});

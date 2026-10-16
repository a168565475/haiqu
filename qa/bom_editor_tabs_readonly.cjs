/** BOM 双页签只读验收：只使用已有 Session，拒绝所有非 GET/HEAD API 请求。 */
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('../src/frontend/node_modules/playwright-core');

const root = path.resolve(__dirname, '..');
const output = path.join(root, 'output', 'playwright', 'bom-editor-tabs-20261015');
const browserRoot = path.join(root, '.tmp', 'bom_editor_tabs_20261015', 'browser');
const profile = path.join(browserRoot, 'profile');
const base = new URL(process.env.BOM_TABS_QA_BASE_URL || 'http://localhost:8080');
const bomId = process.env.BOM_TABS_QA_BOM_ID || 'dbe06399-b6f0-40b1-bdba-9e0d9b2861da';
const viewports = [{ width: 1920, height: 1080 }, { width: 1101, height: 884 }];
const report = {
  schemaVersion: 1, startedAt: new Date().toISOString(), mode: 'real-api-read-only', status: 'RUNNING',
  checks: [], apiReads: [], httpErrors: [], blockedWrites: [], pageErrors: [], screenshots: [],
  measurements: [], notCovered: [],
  resources: { profile, created: false, browserClosed: false, removed: false, verifiedAbsent: false },
};
let context;
let outputReady = false;
let profileCreated = false;

function requireCondition(condition, code, message) {
  if (!condition) { const error = new Error(message); error.code = code; error.qaSafe = true; throw error; }
}
function check(condition, code, detail = {}) {
  report.checks.push({ code, passed: Boolean(condition), ...detail });
  return Boolean(condition);
}
function safeRoute(raw) {
  try { return new URL(raw, base).pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, ':id'); }
  catch { return 'invalid-url'; }
}
function inside(candidate, parent) {
  const relative = path.relative(fs.realpathSync(parent), fs.realpathSync(candidate));
  return relative !== '' && !relative.startsWith('..') && !path.isAbsolute(relative);
}
function failure(error, code) {
  report.checks.push({ code: error.code || code, passed: false, message: error.qaSafe ? error.message : '检查无法继续；未输出请求、响应或凭据。', errorType: error.name });
}
async function readJson(route, kind) {
  const url = new URL(route, base);
  requireCondition(url.origin === base.origin && url.pathname.startsWith('/api/'), 'API_SCOPE', '只允许读取指定服务的 API。');
  const response = await context.request.get(url.href, { maxRedirects: 0 });
  report.apiReads.push({ kind, route: safeRoute(url.href), status: response.status() });
  if (response.status() !== 200) return { status: response.status(), data: null };
  try { return { status: 200, data: await response.json() }; }
  catch { requireCondition(false, 'API_INVALID_JSON', 'API 未返回有效 JSON。'); }
}
async function screenshot(page, name) {
  const file = path.join(output, name + '.png');
  await page.screenshot({ path: file, fullPage: true });
  report.screenshots.push(file);
}
async function noHorizontalOverflow(page, scope) {
  const value = await page.evaluate(() => ({
    viewport: window.innerWidth, documentWidth: document.documentElement.scrollWidth,
    bodyWidth: document.body.scrollWidth,
  }));
  check(value.documentWidth <= value.viewport + 1 && value.bodyWidth <= value.viewport + 1, 'NO_PAGE_HORIZONTAL_OVERFLOW', { scope, measured: value });
}
async function tabStyles(page, scope) {
  const measured = await page.locator('.bom-editor-tabs [role="tab"]').evaluateAll(nodes => nodes.map(node => {
    const s = getComputedStyle(node);
    return { id: node.id, selected: node.getAttribute('aria-selected'), height: node.getBoundingClientRect().height,
      fontSize: s.fontSize, lineHeight: s.lineHeight, bottomWidth: s.borderBottomWidth, bottomColor: s.borderBottomColor };
  }));
  check(measured.length === 2, 'TWO_EDITOR_TABS', { scope });
  for (const item of measured) {
    check(Math.abs(item.height - 32) < 0.5 && item.fontSize === '13px' && item.lineHeight === '20px', 'TAB_TYPOGRAPHY', { scope, measured: item });
    if (item.selected === 'true') check(item.bottomWidth === '2px' && item.bottomColor === 'rgb(200, 78, 40)', 'TAB_SELECTED_BORDER', { scope, measured: item });
  }
}
async function productChecks(page, bom, scope) {
  const panel = page.locator('#bom-product-panel');
  const fields = await panel.locator('.product-details dl > div').evaluateAll(nodes => nodes.map(node => ({
    label: node.querySelector('dt')?.textContent.trim(), value: node.querySelector('dd')?.textContent.trim(),
  })));
  const expectedLabels = ['BOM 编号', '订单号', '产品编号', '货号', '产品名称', '产品规格', '单位', '颜色', '材质', '当前订单数量', 'BOM 订单数量', '原表数量', '批次合计'];
  check(fields.length === 13 && expectedLabels.every((label, index) => fields[index]?.label === label), 'PRODUCT_THIRTEEN_FIELDS', { scope, count: fields.length, labels: fields.map(item => item.label) });
  check(await panel.locator('input, textarea, select, [contenteditable="true"]').count() === 0, 'PRODUCT_PANEL_READ_ONLY', { scope });
  const expectedValues = [bom.bom_number, bom.order_number || '—', bom.product_code_snapshot || bom.product_number_snapshot || '—', bom.item_number_snapshot || '—', bom.product_name_snapshot, bom.specification_snapshot || '—', bom.product_unit_name || '—', bom.product_color_snapshot || '—', bom.material_snapshot || '—'];
  check(expectedValues.every((value, index) => fields[index]?.value === value), 'PRODUCT_FIELDS_MATCH_REAL_BOM', { scope });
  const card = await panel.evaluate(node => {
    const s = getComputedStyle(node);
    return { borders: ['Top', 'Right', 'Bottom', 'Left'].map(side => ({ side, width: s['border' + side + 'Width'], color: s['border' + side + 'Color'], style: s['border' + side + 'Style'] })), radius: s.borderRadius, background: s.backgroundColor };
  });
  check(card.borders.every(item => item.width === '1px' && item.style === 'solid' && item.color === 'rgb(221, 214, 201)') && card.radius === '5px' && card.background === 'rgb(252, 251, 247)', 'PRODUCT_CARD_STYLE', { scope, measured: card });
  const stage = page.locator('.bom-product-image__stage');
  await page.waitForFunction(() => document.querySelector('.bom-product-image__stage')?.getAttribute('aria-busy') === 'false');
  const imageState = await stage.evaluate(node => {
    const s = getComputedStyle(node), button = node.querySelector('.product-image'), image = node.querySelector('img');
    const b = button && getComputedStyle(button);
    return { borders: ['Top', 'Right', 'Bottom', 'Left'].map(side => s['border' + side + 'Width']),
      buttonBorders: b && ['Top', 'Right', 'Bottom', 'Left'].map(side => b['border' + side + 'Width']),
      source: image?.getAttribute('src') || '', complete: image?.complete || false, naturalWidth: image?.naturalWidth || 0,
      fit: image && getComputedStyle(image).objectFit, message: image ? '' : node.textContent.trim() };
  });
  check(imageState.borders.every(value => value === '1px'), 'IMAGE_SINGLE_OUTER_BORDER', { scope, widths: imageState.borders });
  if (imageState.source) {
    const image = stage.locator('img');
    await image.evaluate(node => node.complete ? undefined : new Promise(resolve => { node.addEventListener('load', resolve, { once: true }); node.addEventListener('error', resolve, { once: true }); setTimeout(resolve, 10000); }));
    const loaded = await image.evaluate(node => ({ complete: node.complete, naturalWidth: node.naturalWidth, naturalHeight: node.naturalHeight }));
    check(imageState.source.includes('/production-tasks/' + bom.production_task_id + '/business-files/'), 'REAL_PRODUCTION_IMAGE_SOURCE', { scope, source: safeRoute(imageState.source) });
    check(loaded.complete && loaded.naturalWidth > 0, 'REAL_PRODUCT_IMAGE_LOADED', { scope, measured: loaded });
    check(imageState.buttonBorders?.every(value => value === '0px') && imageState.fit === 'contain', 'IMAGE_INNER_BORDER_AND_FIT', { scope, borders: imageState.buttonBorders, objectFit: imageState.fit });
  } else {
    report.notCovered.push({ scope, item: '真实产品图片加载', reason: imageState.message || '未返回图片；不得将缺图记为加载通过。' });
    check(Boolean(imageState.message), 'IMAGE_EMPTY_OR_ERROR_EXPLAINED', { scope, message: imageState.message });
    if (imageState.message !== '暂无产品图片') check(false, 'PRODUCT_IMAGE_UNAVAILABLE', { scope, message: imageState.message });
  }
}
async function tableMeasurements(page, scope) {
  const table = page.locator('#bom-material-panel .section-editor .el-table:visible').first();
  if (!await table.count()) { report.notCovered.push({ scope, item: '用料表格', reason: '当前真实分区未显示表格。' }); return; }
  const measured = await table.evaluate(node => {
    function style(element, pseudo = null) {
      if (!element) return null;
      const s = getComputedStyle(element, pseudo), box = element.getBoundingClientRect();
      return { tag: element.tagName, classes: element.className, pseudo, width: box.width, height: box.height,
        borders: ['Top', 'Right', 'Bottom', 'Left'].map(side => ({ side, width: s['border' + side + 'Width'], color: s['border' + side + 'Color'], style: s['border' + side + 'Style'] })),
        background: s.backgroundColor, boxShadow: s.boxShadow, content: s.content, cssWidth: s.width, cssHeight: s.height,
        position: s.position, top: s.top, right: s.right, bottom: s.bottom, left: s.left,
        overflowX: s.overflowX, overflowY: s.overflowY, clientWidth: element.clientWidth, scrollWidth: element.scrollWidth,
        padding: s.padding, paddingTop: s.paddingTop, paddingBottom: s.paddingBottom, boxSizing: s.boxSizing, lineHeight: s.lineHeight };
    }
    const rows = [...node.querySelectorAll('.el-table__body tr')];
    const first = rows[0], last = rows.at(-1);
    const cells = row => row ? [...new Set([0, 1, row.children.length - 2, row.children.length - 1])].filter(index => index >= 0 && index < row.children.length).map(index => ({ index, ...style(row.children[index]) })) : [];
    const scroll = node.querySelector('.el-scrollbar__wrap');
    return { verticalOverflow: node.getBoundingClientRect().bottom > window.innerHeight || Boolean(scroll && scroll.scrollHeight > scroll.clientHeight + 1),
      table: style(node), before: style(node, '::before'), after: style(node, '::after'),
      inner: style(node.querySelector('.el-table__inner-wrapper')), innerBefore: style(node.querySelector('.el-table__inner-wrapper'), '::before'),
      innerAfter: style(node.querySelector('.el-table__inner-wrapper'), '::after'),
      parent: style(node.parentElement), header: cells(node.querySelector('.el-table__header tr')),
      firstRow: cells(first), lastRow: cells(last), rowHeights: rows.map(row => row.getBoundingClientRect().height),
      rowBoxes: rows.map(row => ({ height: row.getBoundingClientRect().height, cells: [...row.children].map(cell => {
        const s = getComputedStyle(cell);
        const contentHeight = Math.max(0, ...[...cell.children].map(child => {
          const childStyle = getComputedStyle(child);
          return child.getBoundingClientRect().height + parseFloat(childStyle.marginTop) + parseFloat(childStyle.marginBottom);
        }));
        return { contentHeight, paddingTop: parseFloat(s.paddingTop), paddingBottom: parseFloat(s.paddingBottom),
          borderTop: parseFloat(s.borderTopWidth), borderBottom: parseFloat(s.borderBottomWidth), boxSizing: s.boxSizing };
      }) })),
      bodyWrapper: style(node.querySelector('.el-table__body-wrapper')), scrollWrapper: style(node.querySelector('.el-scrollbar__wrap')) };
  });
  report.measurements.push({ scope, kind: 'table-edges-grid-rows', measured });
  // Element Plus table.scss:28-34/274-323：table 的 before/after 画左右边，inner 的 after/before 画上下边。
  const gridColor = 'rgb(227, 223, 215)';
  const edge = (item, axis, position) => item && item.position === 'absolute' && item.content !== 'none'
    && item.background === gridColor && item[axis] === '1px' && item[position] === '0px';
  check(edge(measured.before, 'cssWidth', 'left') && edge(measured.after, 'cssWidth', 'right')
    && edge(measured.innerAfter, 'cssHeight', 'top') && edge(measured.innerBefore, 'cssHeight', 'bottom'), 'TABLE_FOUR_PSEUDO_BORDERS_1PX', { scope });
  check([measured.table, measured.inner, measured.parent].every(item => item.borders.every(border => border.width === '0px') && item.boxShadow === 'none'), 'TABLE_NO_DUPLICATE_CONTAINER_BORDER', { scope });
  const gridCells = [...measured.header, ...measured.firstRow, ...measured.lastRow];
  check(gridCells.length > 0 && gridCells.every(cell => cell.borders.every(border => ['Right', 'Bottom'].includes(border.side)
    ? border.width === '1px' && border.style === 'solid' && border.color === gridColor
    : border.width === '0px')), 'TABLE_FIRST_LAST_AND_INNER_GRID_1PX', { scope, sampledCells: gridCells.length });
  // 正式密度来源：operational-management-density.scss:69-77/131-144 覆盖旧局部 42px。
  // 表头为 44px；BOM 编辑行允许按内容增高、上下各 4px。当前序号容器 32px + 8px padding + 1px 底边 = 41px。
  // 因此核对实际内容盒模型，不把可增高的行一律硬编码成 41px，也不为通过测试改变业务表格。
  if (measured.rowHeights.length) {
    const rows = measured.rowBoxes.map(row => ({ actual: row.height, expected: Math.max(40, ...row.cells.map(cell => cell.contentHeight + cell.paddingTop + cell.paddingBottom + cell.borderTop + cell.borderBottom)) }));
    check(rows.every(row => Math.abs(row.actual - row.expected) < 0.5), 'MATERIAL_ROW_CONTENT_BOX_HEIGHT', { scope, rows });
    check(measured.rowBoxes.every(row => row.cells.every(cell => cell.paddingTop === 4 && cell.paddingBottom === 4 && cell.boxSizing === 'border-box')), 'MATERIAL_ROW_DENSITY_PADDING', { scope });
  } else {
    const empty = table.locator('.el-table__empty-text');
    check(await empty.isVisible() && Boolean((await empty.innerText()).trim()), 'TABLE_EMPTY_STATE', { scope });
  }
  check(measured.header.length > 0 && measured.header.every(cell => Math.abs(cell.height - 44) < 0.5), 'MATERIAL_HEADER_HEIGHT_44', { scope, heights: measured.header.map(cell => cell.height) });
  if (measured.verticalOverflow && measured.rowHeights.length > 1) {
    const lastRow = table.locator('.el-table__body tr').last();
    await lastRow.scrollIntoViewIfNeeded();
    check(await lastRow.evaluate(node => { const box = node.getBoundingClientRect(); return box.top >= 0 && box.bottom <= window.innerHeight; }), 'OVERFLOW_LAST_ROW_REACHABLE', { scope });
    await screenshot(page, 'table-last-row-' + scope);
  }
}
async function checkLocked(page, dialog, scope) {
  check(await dialog.getByRole('button', { name: '关闭', exact: true }).count() === 0, 'LOCKED_CLOSE_HIDDEN', { scope });
  check(await dialog.getByRole('button', { name: '最小化', exact: true }).count() === 0, 'LOCKED_MINIMIZE_HIDDEN', { scope });
  check(await dialog.getByRole('button', { name: '取消', exact: true }).isDisabled(), 'LOCKED_CANCEL_DISABLED', { scope });
  await page.keyboard.press('Escape');
  check(await dialog.isVisible(), 'LOCKED_ESCAPE_BLOCKED', { scope });
  const overlay = page.locator('.app-window-overlay').filter({ has: dialog });
  await overlay.click({ position: { x: 2, y: 2 } });
  check(await dialog.isVisible(), 'LOCKED_OVERLAY_BLOCKED', { scope });
}
async function waitDialogReady(dialog, scope) {
  await dialog.locator('.picker-state[aria-busy="true"]').waitFor({ state: 'hidden' });
  const errors = await dialog.locator('.picker-state[role="alert"], .entry-error[role="alert"]').count();
  check(errors === 0, 'PRODUCT_DIALOG_CATALOG_READY', { scope, errors });
}
async function dialogChecks(page, scope) {
  const open = page.getByRole('button', { name: '查看产品信息', exact: true });
  await open.click();
  const dialog = page.locator('.inquiry-product-window.app-window-dialog');
  await dialog.waitFor({ state: 'visible' });
  await waitDialogReady(dialog, scope + '-unchanged');
  check(await dialog.getByRole('button', { name: '关闭', exact: true }).count() === 1 && await dialog.getByRole('button', { name: '最小化', exact: true }).count() === 1, 'REVIEWED_UNCHANGED_WINDOW_DISMISSIBLE', { scope });
  const cancel = dialog.getByRole('button', { name: '取消', exact: true });
  requireCondition(await cancel.isEnabled(), 'REVIEWED_CANCEL_DISABLED', '已核对且未修改的产品窗口不能取消。');
  await cancel.click();
  await dialog.waitFor({ state: 'hidden' });
  check(true, 'REVIEWED_UNCHANGED_CANCEL_CLOSES', { scope });
  await open.click();
  await dialog.waitFor({ state: 'visible' });
  await waitDialogReady(dialog, scope + '-changed');
  const material = dialog.getByRole('textbox', { name: '材质', exact: true });
  const original = await material.inputValue();
  try {
    await material.fill(original === 'QA只读锁定检查' ? 'QA只读锁定检查2' : 'QA只读锁定检查');
    await checkLocked(page, dialog, scope);
    await screenshot(page, 'locked-' + scope);
    await noHorizontalOverflow(page, scope + '-locked');
  } finally {
    if (await dialog.isVisible()) {
      await material.fill(original);
      check(await cancel.isEnabled(), 'RESTORED_DRAFT_DISMISSIBLE', { scope });
      if (await cancel.isEnabled()) { await cancel.click(); await dialog.waitFor({ state: 'hidden' }); }
    }
  }
}
async function viewportChecks(bom, viewport) {
  const scope = viewport.width + 'x' + viewport.height;
  const page = await context.newPage();
  page.on('pageerror', error => report.pageErrors.push({ scope, type: error.name }));
  try {
    await page.setViewportSize(viewport);
    await page.goto(new URL('/boms/' + bomId + '/edit', base).href, { waitUntil: 'domcontentloaded' });
    await page.locator('#bom-material-tab').waitFor({ state: 'visible' });
    await page.locator('#bom-material-tab').click();
    await page.locator('#bom-material-panel').waitFor({ state: 'visible' });
    await tabStyles(page, scope + '-materials');
    await tableMeasurements(page, scope);
    await noHorizontalOverflow(page, scope + '-materials');
    await screenshot(page, 'materials-' + scope);
    const categories = page.locator('#bom-material-panel .section-sidebar .section-tabs button:not([disabled])');
    if (await categories.count() > 1) {
      await categories.nth(1).click();
      await tableMeasurements(page, scope + '-second-category');
    }
    const activeCategory = await page.locator('#bom-material-panel .section-sidebar .section-tabs button.active').innerText();
    await page.locator('#bom-material-tab').focus();
    await page.keyboard.press('ArrowLeft');
    check(await page.evaluate(() => document.activeElement?.id === 'bom-product-tab'), 'KEYBOARD_LEFT_FOCUSES_PRODUCT', { scope });
    check(await page.locator('#bom-material-tab').getAttribute('aria-selected') === 'true', 'ARROW_DOES_NOT_ACTIVATE_TAB', { scope });
    await page.keyboard.press('Enter');
    await page.locator('#bom-product-panel').waitFor({ state: 'visible' });
    await tabStyles(page, scope + '-product');
    await productChecks(page, bom, scope);
    await noHorizontalOverflow(page, scope + '-product');
    await screenshot(page, 'product-' + scope);
    await page.locator('#bom-product-tab').focus();
    await page.keyboard.press('ArrowRight');
    check(await page.evaluate(() => document.activeElement?.id === 'bom-material-tab'), 'KEYBOARD_RIGHT_FOCUSES_MATERIALS', { scope });
    await page.keyboard.press('Enter');
    await page.locator('#bom-material-panel').waitFor({ state: 'visible' });
    check(await page.locator('#bom-material-panel .section-sidebar .section-tabs button.active').innerText() === activeCategory, 'MATERIAL_CATEGORY_PRESERVED', { scope });
    await page.locator('#bom-product-tab').click();
    await dialogChecks(page, scope);
    for (const tabId of ['bom-product-tab', 'bom-material-tab']) {
      await page.locator('#' + tabId).click();
      await page.emulateMedia({ media: 'print' });
      check(await page.locator('#bom-product-panel').isVisible() && await page.locator('#bom-material-panel').isVisible(), 'PRINT_BOTH_PANELS_VISIBLE', { scope, activeTab: tabId });
      check(!await page.locator('.bom-editor-tabs').isVisible(), 'PRINT_TAB_CONTROLS_HIDDEN', { scope, activeTab: tabId });
      await page.emulateMedia({ media: 'screen' });
    }
  } catch (error) {
    failure(error, 'VIEWPORT_CHECK_ABORTED');
    await screenshot(page, 'failure-' + scope).catch(() => report.notCovered.push({ scope, item: '失败现场截图', reason: '页面不可截图。' }));
  } finally { await page.close(); }
}
async function initialLockCoverage() {
  let candidates = process.env.BOM_TABS_QA_UNREVIEWED_ID ? [{ id: process.env.BOM_TABS_QA_UNREVIEWED_ID }] : [];
  if (!candidates.length) {
    const list = await readJson('/api/v1/boms/?status=PENDING_CONFIRMATION&page_size=100', 'unreviewed-candidates');
    if (list.status === 200 && Array.isArray(list.data?.data)) candidates = list.data.data.slice(0, 5);
  }
  let target;
  for (const candidate of candidates) {
    if (!/^[0-9a-f-]{36}$/i.test(candidate.id) || candidate.id === bomId) continue;
    const detail = await readJson('/api/v1/boms/' + candidate.id + '/', 'unreviewed-candidate-detail');
    if (detail.status === 200 && detail.data?.data?.product_information_confirmed === false) { target = candidate.id; break; }
  }
  if (!target) { report.notCovered.push({ item: '未核对产品初始锁定', reason: '有界只读查询未找到可用真实记录；未创建测试数据。' }); return; }
  const page = await context.newPage();
  try {
    await page.setViewportSize(viewports[0]);
    await page.goto(new URL('/boms/' + target + '/edit', base).href, { waitUntil: 'domcontentloaded' });
    const dialog = page.locator('.inquiry-product-window.app-window-dialog');
    await dialog.waitFor({ state: 'visible' });
    await waitDialogReady(dialog, 'unreviewed-initial');
    await checkLocked(page, dialog, 'unreviewed-initial');
    await screenshot(page, 'unreviewed-initial-locked-1920x1080');
  } catch (error) { failure(error, 'UNREVIEWED_INITIAL_CHECK_ABORTED'); }
  finally { await page.close(); }
}
async function main() {
  fs.mkdirSync(output, { recursive: true });
  requireCondition(inside(output, root), 'OUTPUT_SCOPE', '证据目录必须在本项目内。');
  outputReady = true;
  const stateFile = process.env.BOM_TABS_QA_STORAGE_STATE;
  requireCondition(Boolean(stateFile) && fs.existsSync(stateFile), 'STORAGE_STATE_REQUIRED', '缺少 BOM_TABS_QA_STORAGE_STATE；禁止自动登录。');
  const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
  requireCondition(Array.isArray(state.cookies), 'INVALID_STORAGE_STATE', '已有会话文件格式无效。');
  requireCondition(/^https?:$/.test(base.protocol) && ['localhost', '127.0.0.1'].includes(base.hostname), 'TARGET_SCOPE', '此条目仅允许指定本机开发服务。');
  requireCondition(/^[0-9a-f-]{36}$/i.test(bomId), 'INVALID_BOM_ID', 'BOM 编号参数格式无效。');
  const executablePath = [process.env.BOM_TABS_QA_BROWSER_PATH, 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'].filter(Boolean).find(file => fs.existsSync(file));
  requireCondition(Boolean(executablePath), 'BROWSER_MISSING', '未找到已安装的 Chrome 或 Edge。');
  requireCondition(!fs.existsSync(profile), 'PROFILE_ALREADY_EXISTS', '登记的临时 profile 已存在；拒绝覆盖或删除来源不明目录。');
  fs.mkdirSync(browserRoot, { recursive: true });
  requireCondition(inside(browserRoot, root), 'PROFILE_ROOT_SCOPE', '浏览器目录必须位于本任务范围。');
  fs.mkdirSync(profile);
  profileCreated = true;
  report.resources.created = true;
  context = await chromium.launchPersistentContext(profile, {
    executablePath, headless: true, viewport: viewports[0], locale: 'zh-CN', serviceWorkers: 'block',
    env: { ...process.env, TEMP: profile, TMP: profile, TMPDIR: profile },
  });
  context.setDefaultTimeout(12000);
  await context.addCookies(state.cookies);
  await context.addInitScript(({ origins }) => {
    const match = (origins || []).find(item => item.origin === window.location.origin);
    for (const entry of match?.localStorage || []) localStorage.setItem(entry.name, entry.value);
  }, { origins: state.origins || [] });
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.pathname.startsWith('/api/') && !['GET', 'HEAD'].includes(request.method())) {
      report.blockedWrites.push({ method: request.method(), route: safeRoute(request.url()) });
      await route.abort('blockedbyclient');
    } else await route.continue();
  });
  context.on('response', response => {
    const url = new URL(response.url());
    if (!url.pathname.startsWith('/api/')) return;
    const record = { method: response.request().method(), route: safeRoute(response.url()), status: response.status() };
    report.apiReads.push(record);
    if (record.status >= 400) report.httpErrors.push(record);
  });
  const me = await readJson('/api/auth/me/', 'existing-session');
  requireCondition(me.status === 200 && me.data?.authenticated === true, 'SESSION_EXPIRED', '已有会话失效；禁止自动登录。');
  const detail = await readJson('/api/v1/boms/' + bomId + '/', 'target-bom');
  requireCondition(detail.status === 200 && detail.data?.data?.product_information_confirmed === true, 'TARGET_BOM_UNAVAILABLE', '目标必须为真实可读且产品已核对的 BOM。');
  report.coverage = { persistedBomLineCount: (detail.data.data.sections || []).reduce((total, section) => total + (section.lines || []).length, 0),
    note: '表格量测记录真实页面渲染行；若持久化明细为零，自动出现的空白编辑行仅覆盖占位行布局。' };
  for (const viewport of viewports) await viewportChecks(detail.data.data, viewport);
  await initialLockCoverage();
  if (!report.measurements.some(item => item.measured.verticalOverflow && item.measured.rowHeights.length > 1)) {
    report.notCovered.push({ item: '超出可视区域的多行用料表格', reason: '本次真实用料行仍可完整容纳；多于一行不能代表已覆盖超量滚动。未制造数据或修改 DOM。' });
  }
  check(report.blockedWrites.length === 0, 'NO_BUSINESS_WRITE_ATTEMPTS', { count: report.blockedWrites.length });
  check(report.pageErrors.length === 0, 'NO_BROWSER_RUNTIME_ERRORS', { count: report.pageErrors.length });
}
main().catch(error => {
  failure(error, 'QA_ABORTED');
  report.status = ['STORAGE_STATE_REQUIRED', 'SESSION_EXPIRED', 'BROWSER_MISSING', 'PROFILE_ALREADY_EXISTS', 'TARGET_BOM_UNAVAILABLE'].includes(error.code) ? 'BLOCKED' : 'FAIL';
}).finally(async () => {
  if (context) {
    try { await context.close(); report.resources.browserClosed = true; }
    catch { check(false, 'BROWSER_CLOSE_FAILED'); }
  }
  if (profileCreated) {
    try {
      requireCondition(!context || report.resources.browserClosed, 'PROFILE_IN_USE', '浏览器未确认关闭，保留 profile 并报告。');
      requireCondition(inside(profile, browserRoot) && fs.realpathSync(profile) === path.join(fs.realpathSync(browserRoot), 'profile'), 'CLEANUP_SCOPE', 'profile 解析路径不符合登记范围，停止删除。');
      fs.rmSync(profile, { recursive: true, force: false });
      report.resources.removed = true;
      report.resources.verifiedAbsent = !fs.existsSync(profile);
      check(report.resources.verifiedAbsent, 'PROFILE_CLEANED_AND_VERIFIED');
    } catch (error) { failure(error, 'PROFILE_CLEANUP_FAILED'); }
  }
  if (report.status === 'RUNNING') report.status = report.checks.some(item => !item.passed) ? 'FAIL' : report.notCovered.length ? 'PARTIAL' : 'PASS';
  if (profileCreated && !report.resources.verifiedAbsent) report.status = 'FAIL';
  report.finishedAt = new Date().toISOString();
  if (outputReady) fs.writeFileSync(path.join(output, 'readonly-report.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ status: report.status, checks: report.checks.length, failed: report.checks.filter(item => !item.passed).length, notCovered: report.notCovered.length, report: outputReady ? path.join(output, 'readonly-report.json') : null }));
  process.exitCode = report.status === 'PASS' ? 0 : report.status === 'BLOCKED' ? 2 : 1;
});

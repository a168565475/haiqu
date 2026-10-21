/** 企业微信考勤真实只读验收：不登录、不写库、不读取外部企微规则、不伪造接口。 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const root = path.resolve(__dirname, '..');
const stamp = new Date().toISOString().replace(/[:.]/g, '-');
const runtimeParent = path.join(root, '.tmp', 'wecom-attendance-readonly');
const runtime = path.join(runtimeParent, `browser-${stamp}-${process.pid}`);
const evidence = path.join(root, 'output', 'playwright', 'wecom-attendance-20261020');
const reportPath = path.join(evidence, `readonly-${stamp}.json`);
const focus = process.env.ATTENDANCE_QA_FOCUS || '';
const filtersOnly = focus === 'filters';
const viewports = filtersOnly ? [[1101, 884], [1440, 900], [390, 844]] : [[1920, 1080], [1440, 900], [390, 844]];
const apiRoot = '/api/v1/attendance/';
const report = { qa_result_version: 1, status: 'RUNNING', started_at: new Date().toISOString(), mode: 'real-api-read-only', layout: filtersOnly ? 'attendance-filters-20261020' : 'attendance-table-20261020', checks: [], api_reads: [], blocked_requests: [], page_errors: [], http_errors: [], screenshots: [], not_covered: [], resources: { runtime, created: false, removed: false, verified_absent: false } };
const tempBefore = { TEMP: process.env.TEMP, TMP: process.env.TMP, TMPDIR: process.env.TMPDIR };
let base, browser, context, page, defaultRecords, ownsRuntime = false, stage = 'preconditions';
const digest = value => crypto.createHash('sha256').update(String(value)).digest('hex').slice(0, 12);
function fail(code, message, blocked = false) { throw Object.assign(new Error(message), { qaSafe: true, code, blocked }); }
function assert(value, code, message) { if (!value) fail(code, message); }
function record(id, data = {}) { report.checks.push({ id, ...data }); }
function gap(message) { if (!report.not_covered.includes(message)) report.not_covered.push(message); }
function save() { fs.writeFileSync(reportPath, JSON.stringify(report, null, 2)); }
function safePath(value) { const url = new URL(value); return url.pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, ':id'); }
function normalized(value) { const result = path.resolve(value); return process.platform === 'win32' ? result.toLowerCase() : result; }
function currentMonth() { return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit' }).format(new Date()); }
function monthBeforeNow() { const [year, month] = currentMonth().split('-').map(Number); return `${month === 1 ? year - 1 : year}-${String(month === 1 ? 12 : month - 1).padStart(2, '0')}`; }
const month = process.env.ATTENDANCE_QA_MONTH || monthBeforeNow();

async function api(route, kind) {
  const url = new URL(route, base);
  assert(url.origin === base.origin && !url.pathname.startsWith(apiRoot + 'rules/'), 'READ_BOUNDARY', '请求超出只读 ERP 范围。');
  let response;
  try { response = await context.request.get(url.href, { maxRedirects: 0, timeout: 20000 }); }
  catch { fail('API_UNREACHABLE', `${kind} 不可访问。`, true); }
  report.api_reads.push({ kind, status: response.status() });
  if ([401, 403].includes(response.status())) fail('SESSION_OR_PERMISSION', `${kind} 缺少有效会话或权限。`, true);
  if ([404, 409, 503].includes(response.status())) fail('API_NOT_READY', `${kind} 尚未具备可验收的数据或部署条件。`, true);
  assert(response.status() === 200, 'API_STATUS', `${kind} 未返回 200。`);
  let body;
  try { body = await response.json(); } catch { fail('API_JSON', `${kind} 未返回 JSON。`); }
  return { body, etag: response.headers().etag || '' };
}
async function screenshot(name) {
  const filename = `${stamp}-${name}.png`;
  await page.screenshot({ path: path.join(evidence, filename), fullPage: true, style: '.table-frame tbody td:nth-child(-n+3) { color: transparent !important; } .table-frame tbody td:nth-child(-n+3) * { visibility: hidden !important; }', mask: [page.locator('.app-header__user-name, .attendance-page [aria-label="人员"], .member-filter, .attendance-calendar .detail-subtitle, .attendance-calendar [aria-label="月历人员"]')] });
  report.screenshots.push(filename);
}
async function tableReady() { await page.waitForFunction(() => document.querySelector('[data-testid="attendance-records"]')?.getAttribute('aria-busy') === 'false'); }
function displayMonth(value) { const parts = value.match(/\d+/g); return parts?.length >= 2 ? `${parts[0]}-${String(Number(parts[1])).padStart(2, '0')}` : ''; }
async function selectMonth(target) {
  const editor = page.locator('.attendance-page .el-date-editor').first();
  await editor.click();
  const panel = page.locator('.el-picker-panel:visible').filter({ has: page.locator('.el-month-table') });
  await panel.locator('.el-month-table').waitFor();
  const targetYear = Number(target.slice(0, 4));
  for (let attempts = 0; attempts < 101; attempts++) {
    const shownYear = Number((await panel.locator('.el-date-picker__header-label').first().innerText()).match(/\d{4}/)?.[0]);
    assert(Number.isInteger(shownYear), 'MONTH_PICKER_YEAR', '月份控件缺少可读取的年份。');
    if (shownYear === targetYear) break;
    await panel.locator(shownYear > targetYear ? 'button.d-arrow-left' : 'button.d-arrow-right').click();
    if (attempts === 100) fail('MONTH_PICKER_RANGE', '月份控件未能切换到目标年份。');
  }
  if (await page.evaluate(() => innerWidth) === 1440) await screenshot('1440-month-picker');
  await panel.locator('.el-month-table td').nth(Number(target.slice(5)) - 1).click();
  await panel.waitFor({ state: 'hidden' });
  assert(displayMonth(await editor.locator('input').inputValue()) === target, 'MONTH_PICKER_VALUE', 'Element Plus月选择器未切换到目标月份。');
  await page.getByRole('button', { name: '查询', exact: true }).click(); await tableReady();
}
async function openPage() {
  await page.goto(new URL('/attendance/wecom', base).href, { waitUntil: 'networkidle' });
  if (!await page.locator('.attendance-page').count()) fail('PAGE_NOT_READY', '考勤页面不可访问，未执行登录或创建会话。', true);
  await tableReady();
  await page.evaluate(() => document.fonts.ready);
  const editor = page.locator('.attendance-page .el-date-editor').first();
  assert(await editor.count() === 1 && await page.locator('.attendance-page input[type="month"]').count() === 0, 'MONTH_COMPONENT', '主列表月份应使用Element Plus月份选择器。');
  assert(displayMonth(await editor.locator('input').inputValue()) === currentMonth(), 'DEFAULT_CURRENT_MONTH', '首次打开必须默认北京时间当月。');
  assert(await page.locator('.table-frame tbody tr').count() === defaultRecords.data.length, 'DEFAULT_MONTH_DATA', '默认当月列表与真实API不一致，不能显示上月数据冒充当月。');
  if (defaultRecords.count === 0) assert(await page.locator('.empty-state').isVisible(), 'DEFAULT_MONTH_EMPTY', '真实当月无快照时应明确显示空态。');
  assert(await page.getByTestId('sync-progress').count() === 0, 'SYNC_HIDDEN', '未操作时同步过程不应常驻首屏。');
  assert(await page.getByLabel('ERP绑定', { exact: true }).count() === 0 && await page.locator('.attendance-page .data-note, .attendance-page > .footnote').count() === 0, 'REMOVED_EXPLANATION', '绑定筛选或底部解释仍在列表中。');
  await screenshot(`${await page.evaluate(() => innerWidth)}-default-current`);
  if (month !== currentMonth()) await selectMonth(month);
  record('default-month-and-picker', { width: await page.evaluate(() => innerWidth), defaultMonth: currentMonth(), selectedMonth: month });
}
async function checkSummaryAndActions(width, overview) {
  await page.waitForFunction(() => document.querySelector('[data-testid="attendance-summary"]')?.getAttribute('aria-busy') === 'false');
  assert(await page.getByTestId('attendance-summary').count() === 1 && await page.getByTestId('attendance-stat-value').count() === 4, 'SUMMARY_CARD', '统计应为同一张卡内四个数字。');
  const values = (await page.getByTestId('attendance-stat-value').allTextContents()).map(value => Number(value.replace(/[,\s]/g, '')));
  assert(JSON.stringify(values) === JSON.stringify([overview.attendance_members, overview.raw_count, overview.daily_count, overview.scanned_members]), 'SUMMARY_REAL_COUNTS', '四项统计必须与所选月份真实API口径一致。');
  const measurement = await page.locator('.attendance-page').evaluate(node => {
    const summary = node.querySelector('[data-testid="attendance-summary"]'), heading = node.querySelector('h1'), filters = node.querySelector('.filters'), actions = filters.querySelector('.heading-actions'), reset = [...filters.querySelectorAll('button')].find(button => button.textContent.trim() === '重置');
    const box = item => { const rect = item.getBoundingClientRect(); return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom }; };
    return { summary: box(summary), heading: box(heading), filters: box(filters), actions: box(actions), reset: box(reset), buttons: [...actions.querySelectorAll('button')].map(box), afterReset: Boolean(reset.compareDocumentPosition(actions) & Node.DOCUMENT_POSITION_FOLLOWING), chartElements: summary.querySelectorAll('svg, canvas, [class*="trend"], [class*="sparkline"]').length };
  });
  assert(measurement.chartElements === 0 && measurement.afterReset, 'SUMMARY_ACTION_STRUCTURE', '统计不应绘制趋势，操作按钮应在查询/重置之后。');
  if (width >= 1440) {
    assert(measurement.summary.left >= measurement.heading.right + 8 && measurement.summary.top < measurement.heading.bottom, 'SUMMARY_TOP_RIGHT', '统计卡应位于标题右上方。');
    assert(Math.abs(measurement.actions.right - measurement.filters.right) <= 1, 'ACTIONS_RIGHT', '操作按钮组须在筛选行右侧对齐。');
    assert(Math.abs(measurement.summary.right - measurement.actions.right) <= 1, 'SUMMARY_ACTIONS_ALIGN', '统计卡和操作按钮组的右边缘须对齐。');
    assert(measurement.actions.left >= measurement.reset.right + 8 && measurement.buttons.every(button => Math.abs(button.top - measurement.reset.top) <= 1 && Math.abs(button.bottom - measurement.reset.bottom) <= 1), 'ACTIONS_SAME_ROW', '桌面操作按钮须在查询重置右侧同一行，不得折行。');
  }
  record('summary-actions', { width, values, measurement });
}
async function checkRowIdentities(rows) {
  const accounts = await page.locator('.table-frame tbody tr').evaluateAll(elements => elements.map(row => row.children[1]?.textContent.trim()));
  assert(JSON.stringify(accounts) === JSON.stringify(rows.map(row => row.user_id)), 'ACCOUNT_API_ROWS', '独立账号列与当前真实API页内容不一致。');
}
async function checkScrollAndFooter(width, kind) {
  const before = await page.locator('.table-footer').boundingBox();
  const measurement = await page.locator('.table-frame').evaluate(frame => {
    frame.scrollTop = frame.scrollHeight; frame.scrollLeft = frame.scrollWidth;
    const box = frame.getBoundingClientRect(), header = frame.querySelector('thead th').getBoundingClientRect(), last = frame.querySelector('tbody tr:last-child')?.getBoundingClientRect();
    return { scrollTop: frame.scrollTop, scrollLeft: frame.scrollLeft, clientHeight: frame.clientHeight, scrollHeight: frame.scrollHeight, headerOffset: header.top - box.top, lastRowBottom: last?.bottom, frameBottom: box.bottom };
  });
  const after = await page.locator('.table-footer').boundingBox();
  assert(before && after && Math.abs(before.y - after.y) <= 1, 'FOOTER_SCROLLS_WITH_TABLE', '表格内部滚动不应移动分页。');
  if (measurement.scrollTop > 0) assert(Math.abs(measurement.headerOffset - 1) <= 1 && measurement.lastRowBottom <= measurement.frameBottom + 1, 'STICKY_HEADER_AND_LAST_ROW', '表内滚动后表头应固定且最后一行可达。');
  await page.locator('.table-frame').evaluate(frame => { frame.scrollTop = 0; frame.scrollLeft = 0; });
  record('table-scroll-footer', { width, kind, measurement });
  if (width <= 640) {
    await page.locator('.table-footer').scrollIntoViewIfNeeded();
    const footer = await page.locator('.table-footer').boundingBox();
    assert(footer && footer.y >= 0 && footer.y + footer.height <= await page.evaluate(() => innerHeight), 'MOBILE_FOOTER_REACHABLE', '窄屏滚动后必须能完整到达分页。');
    record('mobile-pagination-reachable', { width, kind, footer });
    if (kind === 'monthly') await screenshot(`${width}-pagination`);
    await page.locator('.attendance-page').evaluate(node => { node.scrollTop = 0; });
  }
}
async function measureTable(width, kind, expectedRows) {
  const value = await page.locator('.attendance-page').evaluate(node => {
    const style = element => { const css = getComputedStyle(element); const rect = element.getBoundingClientRect(); return { width: rect.width, height: rect.height, top: rect.top, left: rect.left, right: rect.right, font: css.fontSize, weight: css.fontWeight, lineHeight: css.lineHeight, padding: css.padding, radius: css.borderRadius, background: css.backgroundColor, border: ['Top', 'Right', 'Bottom', 'Left'].map(side => ({ width: css[`border${side}Width`], color: css[`border${side}Color`] })), before: getComputedStyle(element, '::before').content, after: getComputedStyle(element, '::after').content }; };
    const frame = node.querySelector('.table-frame'), table = frame.querySelector('table'), cells = table.querySelectorAll('tbody td'), header = table.querySelector('thead tr');
    const firstRow = table.querySelector('tbody tr'), lastRow = table.querySelector('tbody tr:last-child');
    const departments = [...table.querySelectorAll('tbody td:nth-child(3)')];
    const footer = node.querySelector('.table-footer'), monthEditor = node.querySelector('.el-date-editor');
    return { heading: style(node.querySelector('h1')), frame: { ...style(frame), clientWidth: frame.clientWidth, scrollWidth: frame.scrollWidth, clientHeight: frame.clientHeight, scrollHeight: frame.scrollHeight, overflowX: getComputedStyle(frame).overflowX, overflowY: getComputedStyle(frame).overflowY }, table: style(table), header: style(header), headerLabels: [...header.children].map(cell => cell.textContent.trim()), firstHeader: style(header.firstElementChild), lastHeader: style(header.lastElementChild), rows: table.querySelectorAll('tbody tr').length, rowHeights: [...table.querySelectorAll('tbody tr')].map(row => row.getBoundingClientRect().height), first: cells.length ? style(cells[0]) : null, last: cells.length ? style(cells[cells.length - 1]) : null, firstLast: firstRow ? style(firstRow.lastElementChild) : null, lastFirst: lastRow ? style(lastRow.firstElementChild) : null, input: style(monthEditor.classList.contains('el-input__wrapper') ? monthEditor : monthEditor.querySelector('.el-input__wrapper')), search: style(node.querySelector('.person')), departments: { nowrap: departments.every(cell => getComputedStyle(cell).whiteSpace === 'nowrap'), fullTextAvailable: departments.every(cell => cell.hasAttribute('title') || cell.querySelector('[title], [aria-describedby]')) }, footer: style(footer), page: { ...style(node), clientWidth: node.clientWidth, scrollWidth: node.scrollWidth }, viewport: { width: innerWidth, height: innerHeight, client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth } };
  });
  assert(value.rows === expectedRows, 'TABLE_API_ROWS', `${kind} 页面行数与真实接口不一致。`);
  assert(value.heading.font === (width <= 640 ? '28px' : '34px') && value.heading.lineHeight === (width <= 640 ? '38px' : '44px'), 'HEADING_SIZE', '主标题尺寸偏离本轮列表原型。');
  assert(JSON.stringify(value.headerLabels.slice(0, 3)) === JSON.stringify(['成员', '企业微信账号', '部门']), 'IDENTITY_COLUMNS', '三类报表必须拆分成员、企业微信账号与部门列。');
  assert(value.frame.border.every(side => side.width === '1px'), 'TABLE_FRAME_BORDER', '表格四边必须由外围单一 1px 边框绘制。');
  assert(value.firstHeader.border[0].width === '0px' && value.firstHeader.border[3].width === '0px' && value.lastHeader.border[1].width === '0px', 'HEADER_BORDER', '表头外围出现重复边线。');
  assert(value.header.height === 38 && value.firstHeader.weight === '500', 'HEADER_SIZE', '表头需符合38px高、500字重。');
  assert(value.input.height === 32 && value.input.radius === '8px', 'FILTER_SIZE', '月份控件需为 32px 高、8px 圆角。');
  assert(value.viewport.scroll <= value.viewport.client + 1 && value.page.scrollWidth <= value.page.clientWidth + 1, 'PAGE_OVERFLOW', '出现页面级横向溢出，滚动应限制于表格。');
  if (width >= 1440) {
    assert(Math.abs(value.page.left - 108) <= 1 && Math.abs(value.page.top - 62) <= 1 && Math.abs(value.page.width - (width - 122)) <= 1, 'STANDARD_PAGE_BOUNDS', '桌面内容须对齐x108/y62及视口宽减122px。');
    assert(Math.abs(value.search.width - 220) <= 1, 'SEARCH_WIDTH', '桌面人员搜索须为220px。');
    assert(value.frame.scrollWidth <= value.frame.clientWidth + 1, 'WIDE_TABLE_OVERFLOW', '桌面表格出现多余横向滚动。');
    assert(value.footer.top + value.footer.height <= value.viewport.height - 12 && value.footer.top >= value.frame.top, 'PAGINATION_VISIBLE', '分页必须在桌面视口内、表格底部可见。');
  }
  if (value.first) {
    assert(value.first.border[0].width === '0px' && value.first.border[3].width === '0px' && value.last.border[1].width === '0px' && value.last.border[2].width === '0px' && value.firstLast.border[1].width === '0px' && value.lastFirst.border[2].width === '0px', 'CELL_BORDER', '首末行列边线叠加。');
    assert(value.rowHeights.every(height => Math.abs(height - 34) <= 0.5) && value.first.padding === '0px 10px', 'ROW_SIZE', '真实数据行必须单行34px高、左右10px内边距。');
    assert(value.departments.nowrap && value.departments.fullTextAvailable, 'DEPARTMENT_ELLIPSIS', '部门须单行且可读取完整title或tooltip。');
    if (expectedRows > 1) assert(value.first.border[2].width === '1px', 'INNER_ROW_BORDER', '内部行线应为 1px。');
    assert(value.first.border[1].width === '1px', 'INNER_COL_BORDER', '内部列线应为 1px。');
    await page.locator('.table-frame tbody tr').first().hover();
    const hover = await page.locator('.table-frame tbody td').first().evaluate(node => getComputedStyle(node).backgroundColor);
    record('table-hover', { width, kind, color: hover });
    await page.mouse.move(0, 0);
  }
  record('table-dom', { width, kind, measurement: value });
}
const departmentTokens = value => [...new Set(String(value || '').split(/[;；]/).map(item => item.trim()).filter(Boolean))];
async function filterRead(kind, expected, action) {
  report.last_filter_activity = { kind, expectedKeys: Object.keys(expected), expectsMember: Boolean(expected.user_id), expectsSearch: Boolean(expected.search) };
  const pending = page.waitForResponse(response => {
    const url = new URL(response.url());
    return url.origin === base.origin && url.pathname === `${apiRoot}records/${kind}/` && url.searchParams.get('month') === month && Object.entries(expected).every(([key, value]) => (url.searchParams.get(key) || null) === value);
  }, { timeout: 15000 });
  let response;
  try { await action(); response = await pending; }
  catch (error) {
    report.filter_diagnostic = await page.evaluate(() => ({ activeTab: document.querySelector('[role="tab"][aria-selected="true"]')?.getAttribute('data-testid'), busy: document.querySelector('[data-testid="attendance-records"]')?.getAttribute('aria-busy'), month: document.querySelector('.month-field input')?.value, memberFilterPresent: Boolean(document.querySelector('.member-filter')) }));
    throw error;
  }
  assert(response.request().method() === 'GET' && response.status() === 200, 'FILTER_READ_ONLY', '筛选或成员联动必须仅通过成功的GET读取。');
  const body = await response.json(); await tableReady();
  await checkRowIdentities(body.data);
  assert(await page.locator('.table-frame tbody tr').count() === body.data.length, 'FILTER_ROWS', '筛选后列表行数与真实响应不一致。');
  record('filter-read', { kind, keys: Object.keys(expected), count: body.count, rows: body.data.length, method: 'GET', status: 200 });
  return body;
}
async function openFilterSelect(field, width) {
  const control = page.locator(`.filters .${field}-field .el-select`);
  assert(await control.count() === 1, 'EL_SELECT_REQUIRED', '部门和状态必须采用项目ElSelect组件。');
  await control.locator('.el-select__wrapper').click();
  const popup = page.locator('.el-select__popper:visible');
  await popup.waitFor();
  const measurement = await popup.evaluate(node => {
    const css = getComputedStyle(node), rect = node.getBoundingClientRect(), list = node.querySelector('.el-select-dropdown__list');
    const probe = document.createElement('i'); probe.style.cssText = 'position:absolute;visibility:hidden;width:0;height:0;background:var(--erp-dropdown-background);border:1px solid var(--erp-dropdown-border)'; node.appendChild(probe);
    const expected = getComputedStyle(probe), theme = { background: expected.backgroundColor, border: expected.borderTopColor }; probe.remove();
    return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width, background: css.backgroundColor, radius: css.borderRadius, borders: ['Top', 'Right', 'Bottom', 'Left'].map(side => ({ width: css[`border${side}Width`], color: css[`border${side}Color`] })), theme, listClientWidth: list.clientWidth, listScrollWidth: list.scrollWidth, viewportWidth: innerWidth, pageWidth: document.documentElement.scrollWidth };
  });
  const wrapper = await control.locator('.el-select__wrapper').evaluate(node => { const css = getComputedStyle(node), rect = node.getBoundingClientRect(); return { width: rect.width, height: rect.height, radius: css.borderRadius, background: css.backgroundColor }; });
  record('filter-select-dom', { width, field, measurement, wrapper });
  assert(wrapper.height === 32 && wrapper.radius === '8px', 'SELECT_CONTROL_STYLE', 'ElSelect控件必须保持项目32px高、8px圆角。');
  assert(measurement.left >= 0 && measurement.right <= width + 1 && measurement.pageWidth <= width + 1 && measurement.listScrollWidth <= measurement.listClientWidth + 1, 'SELECT_POPUP_OVERFLOW', '下拉弹层或长部门路径造成横向溢出。');
  if (field === 'department') assert(Math.abs(measurement.width - Math.min(320, width - 32)) <= 1, 'DEPARTMENT_POPUP_WIDTH', '部门弹层须保持320px，宽度上限为视口减32px。');
  assert(measurement.background === measurement.theme.background && measurement.borders.every(border => border.width === '1px' && border.color === measurement.theme.border), 'SELECT_POPUP_THEME', '下拉弹层背景和四边须沿用项目主题。');
  if (!report.screenshots.includes(`${stamp}-${width}-${field}-expanded.png`)) await screenshot(`${width}-${field}-expanded`);
  return popup;
}
async function focusedFilters(overview, pages) {
  const allMonthly = [];
  for (let number = 1; allMonthly.length < pages.monthly.count; number++) {
    const result = (await api(`${apiRoot}records/monthly/?month=${month}&page=${number}&page_size=100`, 'department-source-monthly')).body;
    assert(result.data.length > 0, 'DEPARTMENT_SOURCE_PAGE', '真实部门来源分页提前结束。'); allMonthly.push(...result.data);
  }
  const departments = overview.departments;
  assert(Array.isArray(departments) && departments.length === new Set(departments).size && departments.every(value => departmentTokens(value).length === 1 && value === value.trim()), 'DEPARTMENT_TOKENS', '部门候选必须按完整路径拆分、去重，不能出现分号组合项。');
  const usable = departments.filter(value => allMonthly.some(row => departmentTokens(row.department_name).includes(value))).sort((a, b) => b.length - a.length);
  if (!usable.length) fail('DEPARTMENT_DATA_REQUIRED', '真实月报没有可核对的部门路径，未制造数据。', true);
  const rawMembers = new Set(pages.raw.data.map(row => row.user_id));
  const department = usable.find(value => allMonthly.filter(row => departmentTokens(row.department_name).includes(value)).slice(0, 20).some(row => rawMembers.has(row.user_id)));
  if (!department) fail('MEMBER_RAW_DATA_REQUIRED', '真实首屏来源缺少同时有部门月报与原始打卡的可核对成员，未制造数据。', true);
  const expectedDepartmentRows = allMonthly.filter(row => departmentTokens(row.department_name).includes(department));
  const departmentResult = (await api(`${apiRoot}records/monthly/?month=${month}&department=${encodeURIComponent(department)}&page=1&page_size=20`, 'exact-department-token')).body;
  assert(departmentResult.count === expectedDepartmentRows.length && departmentResult.data.every(row => departmentTokens(row.department_name).includes(department)), 'DEPARTMENT_EXACT_MATCH', '部门筛选必须匹配完整路径token，不能按拼接字符串或子串匹配。');
  record('department-source', { options: departments.length, sourceRows: allMonthly.length, multiDepartmentRows: allMonthly.filter(row => departmentTokens(row.department_name).length > 1).length, selectedPathLength: department.length, filteredCount: departmentResult.count });
  for (const [width, height] of viewports) {
    stage = `filters-${width}`; await page.setViewportSize({ width, height }); await openPage();
    assert(await page.locator('.filters .field > span:visible').count() === 0 && await page.locator('.filters select').count() === 0, 'VISIBLE_FILTER_LABELS', '四个可见标签和原生部门/状态下拉应移除。');
    await checkSummaryAndActions(width, overview); await measureTable(width, 'monthly-filters', pages.monthly.data.length);
    let popup = await openFilterSelect('department', width);
    const optionPaths = await popup.locator('.el-select-dropdown__item').evaluateAll(items => items.map(item => item.getAttribute('title') || item.querySelector('[title]')?.getAttribute('title')).filter(Boolean));
    assert(JSON.stringify([...new Set(optionPaths)].sort()) === JSON.stringify([...departments].sort()), 'DEPARTMENT_OPTIONS', '部门选项必须保留每个真实完整路径供读取。');
    const shortLabel = await popup.getByTitle(department, { exact: true }).innerText();
    await page.locator('.department-field .el-select input').fill(shortLabel);
    await page.waitForFunction(keyword => {
      const popup = [...document.querySelectorAll('.el-select__popper')].find(node => node.getBoundingClientRect().width > 0 && getComputedStyle(node).visibility !== 'hidden');
      const options = popup ? [...popup.querySelectorAll('.el-select-dropdown__item[title]')] : [];
      return options.length > 0 && options.every(option => `${option.textContent} ${option.title}`.toLowerCase().includes(keyword.toLowerCase()));
    }, shortLabel);
    assert(await popup.getByTitle(department, { exact: true }).isVisible(), 'DEPARTMENT_SHORT_SEARCH', '输入实际短label后应保留对应完整路径选项。');
    record('department-short-label-search', { width, labelLength: shortLabel.length, matchingOptions: await popup.locator('.el-select-dropdown__item[title]').count() });
    await popup.getByTitle(department, { exact: true }).click();
    const filtered = await filterRead('monthly', { department, user_id: null }, () => page.getByRole('button', { name: '查询', exact: true }).click());
    assert(filtered.count === departmentResult.count && filtered.data.every(row => departmentTokens(row.department_name).includes(department)), 'DEPARTMENT_UI_RESULT', '页面部门查询与真实完整路径结果不一致。');
    await screenshot(`${width}-department-result`);
    const memberIndex = filtered.data.findIndex(row => rawMembers.has(row.user_id));
    assert(memberIndex >= 0, 'MEMBER_RAW_SOURCE', '部门筛选结果缺少已核对的真实打卡成员。');
    const member = filtered.data[memberIndex], person = page.getByLabel('人员', { exact: true });
    const selected = await filterRead('monthly', { user_id: member.user_id, search: null, department: null, status: null, date: null }, () => page.getByTestId('select-member').nth(memberIndex).click());
    assert(await person.inputValue() === (member.name || member.user_id) && selected.data.every(row => row.user_id === member.user_id), 'MEMBER_SELECT', '点击成员后人员框与真实user_id限定不一致。');
    assert((await page.locator('.department-field .el-select').innerText()).includes('全部部门'), 'MEMBER_CLEARS_DEPARTMENT', '点成员后部门控件须同步全部部门，不能继续隐藏限制原始打卡。');
    for (const kind of ['daily', 'raw', 'monthly']) {
      const result = await filterRead(kind, { user_id: member.user_id, search: null, department: null, status: null, date: null }, () => page.getByTestId(`tab-${kind}`).click());
      assert(await person.inputValue() === (member.name || member.user_id) && result.data.every(row => row.user_id === member.user_id), 'MEMBER_TAB_PRESERVE', '切换报表后丢失人员框或限定成员。');
      if (kind === 'raw') assert(result.count > 0, 'MEMBER_RAW_VISIBLE', '点成员后必须可见已知真实打卡，不得被残留部门筛选清空。');
    }
    await screenshot(`${width}-member-linked`);
    const other = allMonthly.find(row => row.user_id !== member.user_id);
    assert(other, 'SECOND_MEMBER_REQUIRED', '真实快照缺少其他成员，无法验证手动改人。');
    await person.fill(other.user_id);
    const changed = await filterRead('monthly', { user_id: null, search: other.user_id }, () => page.getByRole('button', { name: '查询', exact: true }).click());
    assert(changed.data.some(row => row.user_id === other.user_id), 'MANUAL_MEMBER_CHANGE', '手动修改人员后旧user_id仍阻碍新查询。');
    await person.fill('');
    const cleared = await filterRead('monthly', { user_id: null, search: null }, () => page.getByRole('button', { name: '查询', exact: true }).click());
    assert(cleared.count === pages.monthly.count, 'MANUAL_MEMBER_CLEAR', '清空人员查询后未恢复完整列表。');
    popup = await openFilterSelect('status', width); await popup.getByRole('option', { name: '有返回记录', exact: true }).click();
    const returned = await filterRead('monthly', { department: null, user_id: null, status: 'RETURNED' }, () => page.getByRole('button', { name: '查询', exact: true }).click());
    assert(returned.data.every(row => row.record_status === 'RETURNED'), 'STATUS_UI_RESULT', '状态下拉查询返回了不匹配记录。');
    popup = await openFilterSelect('status', width); await popup.getByRole('option', { name: '全部状态', exact: true }).click();
    const restored = await filterRead('monthly', { department: null, user_id: null, status: null, search: null }, () => page.getByRole('button', { name: '查询', exact: true }).click());
    assert(restored.count === pages.monthly.count, 'STATUS_CLEAR', '清除状态后未恢复真实月报总数。');
    const daily = await filterRead('daily', { user_id: cleared.data[0].user_id, search: null }, () => page.getByRole('button', { name: '查看日报', exact: true }).first().click());
    assert(await person.inputValue() === (cleared.data[0].name || cleared.data[0].user_id) && daily.data.every(row => row.user_id === cleared.data[0].user_id), 'VIEW_DAILY_LINK', '查看日报未同步人员框和真实成员过滤。');
    await measureTable(width, 'daily-member-linked', daily.data.length); await checkScrollAndFooter(width, 'daily-member-linked');
    await screenshot(`${width}-daily-linked`);
    await person.fill('');
    const unlinked = await filterRead('raw', { user_id: null, search: null }, () => page.getByTestId('tab-raw').click());
    assert(unlinked.count === pages.raw.count, 'CLEAR_THEN_TAB', '手动清空后切换报表不得恢复旧user_id。');
    await measureTable(width, 'raw-cleared', unlinked.data.length); await screenshot(`${width}-cleared`);
  }
  assert(report.blocked_requests.length === 0 && report.page_errors.length === 0 && report.http_errors.length === 0, 'FILTER_PAGE_ERRORS', '定向筛选检查出现越界请求、页面或HTTP错误。');
  gap('本轮仅验证筛选与人员联动；未重复月历/安排业务、未调用同步、规则读取或保存。');
  gap('未制造真实API失败、撤权或改写来源数据；对应单元/API测试由主线程独立汇总。');
  report.status = 'PASS_WITH_GAPS';
}
async function calendarChecks(width, member) {
  const result = (await api(`${apiRoot}calendar/?month=${month}&user_id=${encodeURIComponent(member.user_id)}`, 'personal-calendar')).body.data;
  await page.getByTestId('open-calendar').first().click();
  const expectedDays = new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5)), 0)).getUTCDate();
  await page.waitForFunction(({ expectedMonth, userId, count }) => {
    const calendar = document.querySelector('.attendance-calendar');
    if (!calendar || calendar.querySelector('[role="status"], [role="alert"]')) return false;
    const user = calendar.querySelector('[aria-label="月历人员"]');
    const monthInput = calendar.querySelector('[aria-label="月历月份"]');
    const days = [...calendar.querySelectorAll('.calendar-day')];
    return user?.value === userId && monthInput?.value === expectedMonth && days.length === count && days.every(day => day.getAttribute('data-date')?.startsWith(expectedMonth + '-'));
  }, { expectedMonth: month, userId: member.user_id, count: expectedDays });
  assert(await page.locator('.attendance-calendar .calendar-day').count() === expectedDays, 'CALENDAR_DAYS', '个人月历日期数量不完整。');
  const measured = await page.locator('.attendance-calendar').evaluate(node => {
    const layout = getComputedStyle(node.querySelector('.calendar-layout')); const grid = getComputedStyle(node.querySelector('.calendar-grid')); const day = getComputedStyle(node.querySelector('.calendar-day')); const rect = node.getBoundingClientRect();
    return { columns: grid.gridTemplateColumns.split(' ').length, layout: layout.gridTemplateColumns, gap: layout.gap, dayMinHeight: day.minHeight, dayRadius: day.borderRadius, clientWidth: node.clientWidth, scrollWidth: node.scrollWidth, left: rect.left, right: rect.right, viewportWidth: innerWidth };
  });
  assert(measured.columns === 7 && measured.scrollWidth <= measured.clientWidth + 1 && measured.left >= 0 && measured.right <= measured.viewportWidth, 'CALENDAR_LAYOUT', '月历必须保持 7 列并在视口内显示。');
  const visibleStates = new Set();
  for (const day of result.days) {
    const button = page.locator(`.attendance-calendar [data-date="${day.date}"]`);
    const label = await button.getAttribute('aria-label');
    if (day.checkin_count === 0) assert(label.includes('明确未打卡') || label.includes('未打卡'), 'ZERO_STATUS', '明确零次未显示独立状态。');
    for (const state of day.states) visibleStates.add(state);
    if ((day.states || []).includes('late')) assert(label.includes('迟到'), 'LATE_STATUS', '企微迟到未显示。');
    if ((day.states || []).includes('early')) assert(label.includes('早退'), 'EARLY_STATUS', '企微早退未显示。');
    if (day.schedule?.kind === 'REST') assert(label.includes('休息'), 'REST_STATUS', 'ERP休息安排未显示。');
  }
  await page.locator('.attendance-calendar .calendar-day').first().click();
  assert(await page.getByTestId('day-detail').getByText('ERP 全员月度安排', { exact: true }).count() === 1, 'SCHEDULE_SOURCE_LABEL', '个人详情未分别显示 ERP 全员安排。');
  await page.locator('.attendance-calendar .calendar-day').first().press('ArrowRight');
  assert(await page.locator('.attendance-calendar .calendar-day[aria-pressed="true"]').getAttribute('data-date') === `${month}-02`, 'CALENDAR_KEYBOARD', '月历方向键切换失败。');
  record('calendar-dom', { width, measurement: measured, sourceStates: [...visibleStates], sourceMemberHash: digest(member.user_id) });
  for (const state of ['normal', 'zero', 'late', 'early', 'rest', 'unknown']) if (!visibleStates.has(state)) gap(`真实所选成员没有 ${state} 状态，未伪造数据补齐月历状态。`);
  await screenshot(`${width}-calendar`);
  await page.locator('.app-window-dialog:visible').getByRole('button', { name: '关闭', exact: true }).last().click();
}
async function main() {
  fs.mkdirSync(evidence, { recursive: true });
  save(); // 创建临时浏览器目录前记录所属任务与完整路径。
  const state = process.env.ATTENDANCE_QA_STORAGE_STATE;
  assert(focus === '' || filtersOnly, 'FOCUS', 'ATTENDANCE_QA_FOCUS只允许留空或filters。');
  if (!state || !fs.existsSync(state)) fail('SESSION_REQUIRED', '缺少 ATTENDANCE_QA_STORAGE_STATE 指向的既有有效登录会话；未访问页面、未创建账号。', true);
  try { base = new URL(process.env.ATTENDANCE_QA_BASE_URL || 'http://localhost:8080'); } catch { fail('BASE_URL', '验收地址格式无效。', true); }
  assert(!base.username && !base.password && !base.search && !base.hash && base.pathname === '/' && (base.protocol === 'https:' || base.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(base.hostname)), 'BASE_URL', '验收地址须为无凭据的 HTTPS 源或本地 HTTP 源。');
  assert(/^20\d{2}-(0[1-9]|1[0-2])$/.test(month), 'MONTH', '月份必须为 2000—2099 范围内的 YYYY-MM。');
  const browserPath = [process.env.ATTENDANCE_QA_BROWSER_PATH, 'C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(value => value && fs.existsSync(value));
  if (!browserPath) fail('BROWSER_MISSING', '未找到已安装的 Chrome/Edge；未安装依赖。', true);
  assert(!fs.existsSync(runtime), 'RESOURCE_EXISTS', '临时目录已存在，拒绝覆盖。');
  fs.mkdirSync(runtime, { recursive: true }); ownsRuntime = true; report.resources.created = true;
  for (const key of Object.keys(tempBefore)) process.env[key] = runtime;
  save();
  const { chromium } = require('../src/frontend/node_modules/playwright-core');
  browser = await chromium.launch({ executablePath: browserPath, headless: true, downloadsPath: runtime, args: ['--disable-background-networking', '--disable-component-update'] });
  context = await browser.newContext({ storageState: state, serviceWorkers: 'block', acceptDownloads: false });
  await context.routeWebSocket('**/*', socket => {
    const url = new URL(socket.url());
    if (url.host !== base.host) { report.blocked_requests.push({ method: 'WEBSOCKET', kind: 'external-origin' }); socket.close(); }
    else socket.connectToServer();
  });
  await context.route('**/*', route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== base.origin || !['GET', 'HEAD'].includes(request.method()) || url.pathname.startsWith(apiRoot + 'rules/')) {
      report.blocked_requests.push({ method: request.method(), kind: url.origin === base.origin ? safePath(url.href) : 'external-origin' });
      return route.abort('blockedbyclient');
    }
    return route.continue();
  });
  stage = 'real-api';
  const me = (await api('/api/auth/me/', 'session')).body;
  if (!me.authenticated || me.user?.employee?.status !== 'ACTIVE' || !me.user?.permissions?.includes('attendance.view_attendance')) fail('SESSION_PERMISSION', '会话失效、员工无效或没有考勤查看权限。', true);
  const overview = (await api(`${apiRoot}overview/?month=${month}`, 'overview')).body.data;
  if (!overview.has_data) fail('SNAPSHOT_REQUIRED', '所选月份尚无成功真实同步快照；未调用同步或写库。', true);
  const pages = {};
  for (const kind of ['monthly', 'daily', 'raw']) {
    const body = (await api(`${apiRoot}records/${kind}/?month=${month}&page=1&page_size=20`, kind)).body;
    assert(Array.isArray(body.data) && Number.isInteger(body.count), 'LIST_CONTRACT', `${kind} 分页结构无效。`);
    pages[kind] = body;
  }
  const schedule = filtersOnly ? null : await api(`${apiRoot}schedule/?month=${month}`, 'erp-schedule');
  if (schedule) assert(Array.isArray(schedule.body.data?.days) && Boolean(schedule.etag || schedule.body.data.etag), 'SCHEDULE_CONTRACT', 'ERP安排缺少完整日期或版本。');
  if (!pages.monthly.data.length) fail('MEMBER_REQUIRED', '月报没有可查看月历的真实成员。', true);
  let singleRecord;
  for (const member of filtersOnly ? [] : pages.monthly.data.slice(0, 3)) {
    const candidate = (await api(`${apiRoot}records/monthly/?month=${month}&search=${encodeURIComponent(member.user_id)}&page=1&page_size=20`, 'monthly-single-search')).body;
    if (candidate.count === 1) { singleRecord = candidate.data[0]; break; }
  }
  if (!filtersOnly && !singleRecord) gap('现有真实成员搜索未取得单行结果，未创建数据补齐单行状态。');
  defaultRecords = (await api(`${apiRoot}records/monthly/?month=${currentMonth()}&page=1&page_size=20`, 'default-current-month')).body;
  page = await context.newPage(); page.setDefaultTimeout(15000);
  page.on('pageerror', error => report.page_errors.push(digest(error.message)));
  page.on('response', response => { if (response.status() >= 400 && new URL(response.url()).origin === base.origin) report.http_errors.push({ status: response.status(), path: safePath(response.url()) }); });
  if (filtersOnly) page.on('request', request => { const url = new URL(request.url()); if (url.pathname.startsWith(apiRoot + 'records/')) { report.recent_filter_reads = [...(report.recent_filter_reads || []), { method: request.method(), path: url.pathname, month: url.searchParams.get('month'), keys: [...url.searchParams.keys()], member: url.searchParams.has('user_id'), search: url.searchParams.has('search') }].slice(-6); } });
  if (filtersOnly) { await focusedFilters(overview, pages); return; }
  for (const [width, height] of viewports) {
    stage = `page-${width}`; await page.setViewportSize({ width, height }); await openPage();
    await checkSummaryAndActions(width, overview);
    for (const kind of ['monthly', 'daily', 'raw']) {
      await page.getByTestId(`tab-${kind}`).click(); await tableReady();
      await checkRowIdentities(pages[kind].data); await measureTable(width, kind, pages[kind].data.length); await checkScrollAndFooter(width, kind); await screenshot(`${width}-${kind}`);
    }
    await page.getByTestId('tab-monthly').click(); await tableReady();
    if (width === 1920) {
      const large = (await api(`${apiRoot}records/monthly/?month=${month}&page=1&page_size=100`, 'monthly-100')).body;
      await page.getByLabel('每页条数', { exact: true }).selectOption('100'); await tableReady();
      await checkRowIdentities(large.data); await measureTable(width, 'monthly-100', large.data.length); await checkScrollAndFooter(width, 'monthly-100'); await screenshot(`${width}-monthly-100`);
      await page.getByLabel('每页条数', { exact: true }).selectOption('20'); await tableReady();
      if (pages.monthly.count > 20) {
        const next = (await api(`${apiRoot}records/monthly/?month=${month}&page=2&page_size=20`, 'monthly-next-page')).body;
        await page.getByTestId('next-page').click(); await tableReady(); await checkRowIdentities(next.data);
        await page.getByRole('button', { name: '上一页', exact: true }).click(); await tableReady(); await checkRowIdentities(pages.monthly.data);
        record('real-pagination', { width, pageTwoRows: next.data.length, returnedToPageOne: true });
      }
    }
    await calendarChecks(width, pages.monthly.data[0]);
    if (me.user.permissions.includes('attendance.manage_schedule')) {
      await page.getByRole('button', { name: '设置当月上班时间', exact: true }).click();
      await page.locator('.schedule-fields').waitFor();
      assert(await page.locator('[data-schedule-date]').count() === schedule.body.data.days.length, 'SCHEDULE_DAYS', 'ERP安排日期数量与真实接口不一致。');
      const scheduleDom = await page.locator('.schedule-dialog').evaluate(node => {
        const rect = node.getBoundingClientRect(), grid = getComputedStyle(node.querySelector('.calendar-grid')), layout = getComputedStyle(node.querySelector('.schedule-grid-layout'));
        return { columns: grid.gridTemplateColumns.split(' ').length, layout: layout.gridTemplateColumns, clientWidth: node.clientWidth, scrollWidth: node.scrollWidth, left: rect.left, right: rect.right, viewportWidth: innerWidth };
      });
      assert(scheduleDom.columns === 7 && scheduleDom.scrollWidth <= scheduleDom.clientWidth + 1 && scheduleDom.left >= 0 && scheduleDom.right <= scheduleDom.viewportWidth, 'SCHEDULE_LAYOUT', '全员月度安排须保留7列日历，且不超出视口。');
      await screenshot(`${width}-schedule-readonly`);
      await page.getByTestId('cancel-schedule').click();
      record('schedule-readonly', { width, configured: schedule.body.data.configured, measurement: scheduleDom });
    } else gap('真实账号没有月度安排管理权限，已只读核对安排API和月历详情，未打开编辑窗口。');
    if (width === 1920 && singleRecord) {
      await page.getByLabel('人员', { exact: true }).fill(singleRecord.user_id);
      await page.getByRole('button', { name: '查询', exact: true }).click(); await tableReady();
      await checkRowIdentities([singleRecord]); await measureTable(width, 'single-monthly', 1); await checkScrollAndFooter(width, 'single-monthly'); await screenshot(`${width}-single`);
    }
    await page.getByLabel('人员', { exact: true }).fill(`QA_EMPTY_${crypto.randomUUID()}`);
    await page.getByRole('button', { name: '查询', exact: true }).click(); await tableReady();
    assert(await page.locator('.table-frame tbody tr').count() === 0 && await page.locator('.empty-state').isVisible(), 'EMPTY_STATE', '真实唯一筛选未返回空状态。');
    await measureTable(width, 'empty-monthly', 0); await screenshot(`${width}-empty`);
  }
  assert(report.blocked_requests.length === 0, 'REQUEST_BOUNDARY', '页面尝试写入、外部请求或规则读取，已阻止。');
  assert(report.page_errors.length === 0 && report.http_errors.length === 0, 'PAGE_ERRORS', '真实页面出现脚本或HTTP错误。');
  gap('本脚本仅验收既有真实数据读取；未执行同步、规则导入、安排保存、CSRF写入或并发修改。');
  gap('没有制造真实API失败或撤权；这些状态需独立测试与授权环境补验。');
  report.status = 'PASS_WITH_GAPS';
}
(async () => {
  try { await main(); }
  catch (error) { report.status = error.blocked ? 'BLOCKED' : 'FAIL'; process.exitCode = 1; report.failure = { stage, code: error.qaSafe ? error.code : 'UNEXPECTED', message: error.qaSafe ? error.message : '运行异常；未输出可能含会话或真实数据的原始错误。', operation: error.message.match(/^(locator|page)\.[a-zA-Z]+/)?.[0], timeout: /Timeout.*exceeded/.test(error.message), digest: digest(error.message) }; }
  finally {
    let closed = !browser;
    if (browser) { try { await browser.close(); closed = true; report.resources.browser_closed = true; } catch { report.resources.close_failed = true; report.status = 'FAIL'; process.exitCode = 1; } }
    for (const key of Object.keys(tempBefore)) { if (tempBefore[key] === undefined) delete process.env[key]; else process.env[key] = tempBefore[key]; }
    if (ownsRuntime && closed) {
      try {
        assert(normalized(path.dirname(runtime)) === normalized(runtimeParent) && normalized(fs.realpathSync(runtime)) === normalized(runtime) && !fs.lstatSync(runtime).isSymbolicLink(), 'CLEANUP_BOUNDARY', '临时目录清理边界不符。');
        fs.rmSync(runtime, { recursive: true, force: false }); report.resources.removed = true;
      } catch { report.resources.cleanup_failed = true; report.status = 'FAIL'; process.exitCode = 1; }
    }
    report.resources.verified_absent = !fs.existsSync(runtime);
    if (!report.resources.verified_absent) { report.status = 'FAIL'; process.exitCode = 1; }
    report.finished_at = new Date().toISOString(); if (fs.existsSync(evidence)) save();
    console.log(JSON.stringify({ qa_result_version: 1, status: report.status, checks: report.checks.length, not_covered: report.not_covered, failure: report.failure, report: reportPath, cleanup: report.resources.verified_absent }));
  }
})();

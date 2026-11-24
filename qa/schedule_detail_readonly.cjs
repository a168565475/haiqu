// 真实 Session、真实 API、只读页面；不创建业务数据，不伪造状态或页面内容。
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '..');
const output = path.join(root, 'output', 'playwright', 'schedule-detail-20261020');
const reportPath = path.join(output, 'report.json');
const runId = `${new Date().toISOString().replace(/[:.]/g, '-')}-${process.pid}`;
const temporaryRoot = path.join(root, '.tmp');
const profile = path.join(temporaryRoot, `schedule-detail-01a1591e-${process.pid}`);
const ownerPath = path.join(profile, 'qa-owner.json');
const viewports = [{ width: 1920, height: 1080 }, { width: 1440, height: 900 }, { width: 1102, height: 884 }];
const countRoutes = {
  schedules: '/api/v1/production-schedules/?page_size=1',
  reports: '/api/v1/workshop-reporting/work-reports/?page_size=1',
  materials: '/api/v1/material-issues/?page_size=1',
  outsourcing: '/api/v1/unified-outsourcing-orders/?page_size=1',
};
const report = {
  qa_result_version: 1, task: 'schedule-detail-01a1591e', runId, status: 'BLOCKED',
  startedAt: new Date().toISOString(), checks: [], coverage_gap: [], evidence: [],
  businessWrites: 0, authenticationWrites: 0, blockedRequests: [], pageErrors: [], consoleErrors: [],
  resources: { profile: { path: profile, ownership: 'this-run-only', created: false,
    purpose: 'headless Chromium profile', cleanup: '关闭浏览器后验证绝对路径及归属标记，仅删除本次目录' } },
  cleanup: { browserClosed: true, profile: 'NOT_CREATED', inputFiles: 'UNMODIFIED', session: 'NOT_CREATED' },
  visualReference: 'docs/designs/schedule_internal_plans_20261020/schedule_detail_amounts_preview_v3.png',
};
let context, page, base, createdProfile = false, ownSession = false, authenticated = false, baselineCounts;
const secretValues = [];
class Blocked extends Error {}
function safeError(error) {
  let message = error instanceof Error ? error.message : String(error);
  for (const value of secretValues) if (value) message = message.replaceAll(value, '[REDACTED]');
  return message;
}
function save() { fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), 'utf8'); }
function gap(message) { if (!report.coverage_gap.includes(message)) report.coverage_gap.push(message); }
function check(name, passed, actual) {
  report.checks.push({ name, passed: Boolean(passed), ...(actual === undefined ? {} : { actual }) });
  assert(passed, name);
}
function inputJson(filename, label) {
  const absolute = path.resolve(filename);
  if (!fs.existsSync(absolute) || !fs.statSync(absolute).isFile()) throw new Blocked(`${label}不存在或不是文件`);
  try { return JSON.parse(fs.readFileSync(absolute, 'utf8').replace(/^\uFEFF/, '')); }
  catch { throw new Blocked(`${label}不是有效 JSON`); }
}
function validAmount(value) { return typeof value === 'string' && /^\d+(?:\.\d+)?$/.test(value); }
function money(value, digits = 2, trim = false) {
  if (!validAmount(value)) return '—';
  const [integer, fraction = ''] = value.split('.');
  const scale = 10n ** BigInt(digits);
  let total = BigInt(integer) * scale + BigInt(fraction.slice(0, digits).padEnd(digits, '0'));
  if ((fraction[digits] || '0') >= '5') total += 1n;
  let decimals = (total % scale).toString().padStart(digits, '0');
  if (trim) decimals = decimals.replace(/0+$/, '');
  return `¥${(total / scale).toLocaleString('zh-CN')}${decimals ? `.${decimals}` : ''}`;
}
function positive(value) { return validAmount(value) && BigInt(value.replace('.', '')) > 0n; }
function sumAmounts(values) {
  if (!values.length || values.some(value => !validAmount(value))) return null;
  const digits = Math.max(...values.map(value => (value.split('.')[1] || '').length));
  const scale = 10n ** BigInt(digits);
  const total = values.reduce((sum, value) => {
    const [integer, fraction = ''] = value.split('.');
    return sum + BigInt(integer) * scale + BigInt(fraction.padEnd(digits, '0') || '0');
  }, 0n);
  return `${total / scale}${digits ? `.${String(total % scale).padStart(digits, '0')}` : ''}`;
}
async function request(route, method = 'GET', data) {
  const url = new URL(route, base.origin);
  assert.equal(url.origin, base.origin, 'API 不允许跨域请求');
  const authWrite = method === 'POST' && ['/api/auth/login/', '/api/auth/logout/'].includes(url.pathname);
  assert(['GET', 'HEAD'].includes(method) || authWrite, '禁止业务写请求');
  const options = { maxRedirects: 0, timeout: 30000 };
  if (authWrite) {
    const csrf = (await context.cookies(base.origin)).find(cookie => cookie.name === 'csrftoken');
    if (!csrf) throw new Blocked('正常认证未取得 CSRF Cookie');
    secretValues.push(csrf.value);
    options.headers = { 'X-CSRFToken': csrf.value, Origin: base.origin, Referer: `${base.origin}/login` };
    options.data = data;
    report.authenticationWrites += 1;
  }
  return context.request.fetch(url.toString(), { ...options, method });
}
async function json(route) {
  const response = await request(route);
  if ([401, 403].includes(response.status())) throw new Blocked(`读取 ${new URL(route, base.origin).pathname} 缺少有效身份或权限`);
  check(`API ${new URL(route, base.origin).pathname}`, response.status() === 200, response.status());
  return response.json();
}
async function counts() {
  const values = {};
  for (const [name, route] of Object.entries(countRoutes)) {
    const response = await request(route);
    if ([401, 403].includes(response.status())) { values[name] = null; gap(`${name} 列表无权限，无法完成该类记录数量前后核对`); continue; }
    check(`${name} 数量读取状态`, response.status() === 200, response.status());
    const body = await response.json();
    const total = body.meta?.total;
    check(`${name} 数量是有效整数`, Number.isInteger(total) && total >= 0);
    values[name] = total;
  }
  return values;
}
async function comparePage(detail, summary, label) {
  const cards = page.locator('article[data-schedule-product-id]');
  check(`${label} 真实产品数`, await cards.count() === detail.products.length, detail.products.length);
  const totals = [
    ['schedule-estimated-total', summary.totals.estimated_wage],
    ['schedule-reported-total', summary.totals.reported_amount],
    ['schedule-outsourcing-total', summary.totals.outsourcing_planned_amount],
  ];
  for (const [id, value] of totals) check(`${label} ${id}`, (await page.getByTestId(id).innerText()).trim() === money(value));
  let rowsSeen = 0, nonzeroMoney = false;
  const rowCounts = { 内部计划: [], 外发: [], 领料: [] };
  for (const product of detail.products) {
    const card = page.locator(`article[data-schedule-product-id="${product.id}"]`);
    const data = summary.products.find(item => item.schedule_product_id === product.id);
    check(`${label} 产品关联汇总存在`, Boolean(data));
    for (const [field, expected] of [
      ['specification', (product.product.specification_display ?? product.product.specification) || '—'],
      ['color', product.product.color_name || '—'], ['material', product.product.material || '—'],
    ]) {
      const cell = card.locator(`[data-field="${field}"]`);
      check(`${label} ${field} 独立显示`, await cell.count() === 1 && (await cell.innerText()).trim() === expected);
    }
    const plans = card.locator('[data-testid="internal-plans-table"] tbody tr');
    check(`${label} 内部计划真实行数`, await plans.count() === data.internal_plans.length, data.internal_plans.length);
    for (const record of data.internal_plans) {
      const row = card.locator(`tr[data-craft-id="${record.craft_id}"]`);
      const values = await row.locator('td').allTextContents();
      check(`${label} 内部计划独立列`, values.length === 12);
      check(`${label} 内部计划工艺一致`, values[1].trim() === (record.craft_name || '—'));
      check(`${label} 内部预计报工金额`, values[6].trim() === money(record.estimated_wage));
      check(`${label} 内部已报金额`, values[7].trim() === money(record.reported_amount));
      if (record.progress_percent !== null) check(`${label} 报工进度`, values[5].includes(`${record.progress_percent}%`));
      nonzeroMoney ||= positive(record.estimated_wage) || positive(record.reported_amount);
      if (record.estimated_wage === null || record.reported_amount === null) gap('真实内部计划含缺失或无权限金额，已核对“—”；非零完整金额覆盖仍依赖现有记录');
    }
    const outsourcing = card.locator('[data-testid="outsourcing-records-table"] tbody tr');
    const externalRows = data.outsourcing.allowed ? data.outsourcing.records : [];
    const externalOrders = new Map();
    for (const record of externalRows) {
      const key = `${record.order_kind}:${record.order_id}`;
      if (!externalOrders.has(key)) externalOrders.set(key, new Map());
      externalOrders.get(key).set(record.id, record);
    }
    check(`${label} 每张外发单仅一行`, await outsourcing.count() === externalOrders.size, externalOrders.size);
    if (externalOrders.size) check(`${label} 外发表不展开物料部位`,
      !(await card.locator('[data-testid="outsourcing-records-table"] th').allTextContents()).includes('部位'));
    for (const [key, byRecord] of externalOrders) {
      const records = [...byRecord.values()];
      const values = await card.locator(`tr[data-record-id="${key}"] td`).allTextContents();
      check(`${label} 外发单独立列`, values.length === 13);
      check(`${label} 外发单号`, values[0].trim() === records[0].order_number);
      check(`${label} 每张外发单仅一个查看入口`, await card.locator(`tr[data-record-id="${key}"] button`).count() === 1);
      const knownPrices = new Set(records.map(record => `${money(record.unit_price, 4, true)}:${record.price_unit}`));
      const expectedPrice = records.some(record => record.unit_price === null) ? '—'
        : knownPrices.size > 1 ? '多种单价' : money(records[0].unit_price, 4, true);
      check(`${label} 外发单加工单价不取首行或平均价`, values[7].trim() === expectedPrice);
      const amount = sumAmounts(records.map(record => record.planned_amount));
      check(`${label} 外发单本产品计划金额`, values[9].trim() === money(amount));
      nonzeroMoney ||= positive(amount);
      if (amount === null) gap('真实外发单存在缺失金额，已核对“—”，完整外发金额未覆盖该单');
    }
    const materials = card.locator('[data-testid="material-issue-records-table"] tbody tr');
    const materialRows = data.material_issues.allowed ? data.material_issues.records : [];
    check(`${label} 领料真实行数`, await materials.count() === materialRows.length, materialRows.length);
    for (const record of materialRows) {
      const values = await card.locator(`tr[data-issue-id="${record.id}"] td`).allTextContents();
      check(`${label} 领料独立列`, values.length === 8);
      check(`${label} 领料单号及项数`, values[0].trim() === record.issue_number && values[3].trim() === `${record.line_count} 项`);
    }
    rowsSeen += data.internal_plans.length + externalOrders.size + materialRows.length;
    for (const [kind, count] of [['内部计划', data.internal_plans.length], ['外发', externalOrders.size], ['领料', materialRows.length]]) {
      rowCounts[kind].push(count);
    }
  }
  for (const [kind, counts] of Object.entries(rowCounts)) {
    if (!counts.some(count => count > 0)) gap(`${kind}全部为零行或无权限，未完成该表有数据验收`);
    if (!counts.includes(0)) gap(`${kind}空数据边界未由当前真实数据覆盖`);
    if (!counts.includes(1)) gap(`${kind}单行边界未由当前真实数据覆盖`);
    if (!counts.some(count => count > 1)) gap(`${kind}多行边界未由当前真实数据覆盖`);
  }
  if (!rowsSeen) throw new Blocked('当前排产没有任何可验收的真实关联行；不能以空表判通过');
  if (!nonzeroMoney) throw new Blocked('当前排产没有任何可验收的非零金额；不能以空值或全零判金额验收通过');
  report.realData = { products: detail.products.length, relatedRows: rowsSeen, hasNonzeroAmount: nonzeroMoney, rowCounts };
}
async function inspectVisual(label) {
  const evidence = await page.locator('[data-testid="production-scheduling-detail"]').evaluate(section => {
    const styles = element => getComputedStyle(element);
    const border = element => {
      const style = styles(element);
      return ['Top', 'Right', 'Bottom', 'Left'].map(side => ({
        width: parseFloat(style[`border${side}Width`]), color: style[`border${side}Color`],
      }));
    };
    // 离屏颜色解析只规范化 CSS 色值，不插入或改写页面 DOM。
    const colorParser = new OffscreenCanvas(1, 1).getContext('2d');
    const normalized = value => { colorParser.fillStyle = '#010203'; colorParser.fillStyle = value.trim(); return colorParser.fillStyle; };
    const tables = [...section.querySelectorAll('.schedule-execution__table')].map(table => {
      const wrapper = table.parentElement, css = styles(table), wrapperCss = styles(wrapper);
      const heads = [...table.querySelectorAll('th')], cells = [...table.querySelectorAll('td')];
      const rows = [...table.querySelectorAll('tbody tr')];
      const outerCells = [...heads, ...rows.flatMap(row => [...row.children])];
      return {
        kind: table.dataset.testid, rows: rows.length, headers: heads.map(item => item.getBoundingClientRect().height),
        cellHeights: cells.map(item => item.getBoundingClientRect().height),
        singleLine: [...heads, ...cells].every(item => styles(item).whiteSpace === 'nowrap' && item.querySelectorAll('br').length === 0),
        outerBorder: border(wrapper), tableBorder: border(table),
        frameColor: wrapperCss.getPropertyValue('--erp-table-frame-border').trim(),
        frameColorMatches: border(wrapper).every(edge => normalized(edge.color)
          === normalized(wrapperCss.getPropertyValue('--erp-table-frame-border'))),
        innerGrid: outerCells.every(cell => {
          const edges = border(cell), isLastCell = cell === cell.parentElement.lastElementChild;
          const isLastRow = cell.tagName === 'TD' && cell.parentElement === rows.at(-1);
          const gridColor = normalized(styles(cell).getPropertyValue('--erp-table-border'));
          return edges[0].width === 0 && edges[3].width === 0
            && edges[1].width === (isLastCell ? 0 : 1) && edges[2].width === (isLastRow ? 0 : 1)
            && (!edges[1].width || normalized(edges[1].color) === gridColor)
            && (!edges[2].width || normalized(edges[2].color) === gridColor);
        }),
        pseudoBordersAbsent: [table, wrapper].every(element => ['::before', '::after'].every(pseudo => {
          const value = getComputedStyle(element, pseudo);
          return value.content === 'none' || value.content === 'normal' || value.display === 'none';
        })),
        headerColorMatches: heads.every(cell => normalized(styles(cell).backgroundColor)
          === normalized(styles(cell).getPropertyValue('--erp-table-header-background'))),
        padding: heads.concat(cells).every(cell => styles(cell).paddingLeft === '12px' && styles(cell).paddingRight === '12px'),
        overflowX: wrapperCss.overflowX, clientWidth: wrapper.clientWidth, scrollWidth: wrapper.scrollWidth,
        verticalOverflow: wrapper.scrollHeight > wrapper.clientHeight + 1,
        tableFontSize: css.fontSize,
      };
    });
    const tags = [...section.querySelectorAll('.erp-list-tag')].map(tag => {
      const css = styles(tag), tone = [...tag.classList].find(value => value.startsWith('erp-list-tag--'))?.replace('erp-list-tag--', '') || 'info';
      return { height: tag.getBoundingClientRect().height, radius: css.borderRadius, border: border(tag),
        fontSize: css.fontSize, lineHeight: css.lineHeight, weight: css.fontWeight,
        background: css.backgroundColor, color: css.color, tone,
        tokenMatches: normalized(css.backgroundColor) === normalized(css.getPropertyValue(`--erp-tag-${tone}-background`))
          && normalized(css.color) === normalized(css.getPropertyValue(`--erp-tag-${tone}-text`))
          && border(tag).every(edge => normalized(edge.color) === normalized(css.getPropertyValue(`--erp-tag-${tone}-border`))),
      };
    });
    return { tables, tags, documentWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth, pageWidth: section.getBoundingClientRect().width };
  });
  check(`${label} 整页无横向溢出`, evidence.documentWidth <= evidence.viewportWidth + 1);
  check(`${label} 实际存在表格与Tag`, evidence.tables.length > 0 && evidence.tags.length > 0);
  for (const table of evidence.tables) {
    check(`${label} ${table.kind} 表头38px`, table.headers.every(value => Math.abs(value - 38) < 0.6));
    check(`${label} ${table.kind} 行44px`, table.cellHeights.every(value => Math.abs(value - 44) < 0.6));
    check(`${label} ${table.kind} 单行及左右padding12`, table.singleLine && table.padding);
    check(`${label} ${table.kind} 四边仅父容器1px及主题色`, table.outerBorder.every(edge => edge.width === 1)
      && table.tableBorder.every(edge => edge.width === 0) && table.frameColorMatches);
    check(`${label} ${table.kind} 首末行列及内部单边线`, table.innerGrid && table.pseudoBordersAbsent);
    check(`${label} ${table.kind} 表头主题色`, table.headerColorMatches);
    check(`${label} ${table.kind} 仅局部横向滚动`, ['auto', 'scroll'].includes(table.overflowX) && !table.verticalOverflow);
  }
  check(`${label} Tag24px实色主题及圆角`, evidence.tags.every(tag => Math.abs(tag.height - 24) < 0.6
    && parseFloat(tag.radius) === 999 && tag.border.every(edge => edge.width === 1) && tag.tokenMatches
    && tag.fontSize === '12px' && tag.lineHeight === '18px' && tag.weight === '500'));
  report.viewports ||= [];
  report.viewports.push({ viewport: label, ...evidence });
  const tables = page.locator('.schedule-execution__table');
  for (let index = 0; index < await tables.count(); index += 1) {
    const table = tables.nth(index), wrapper = table.locator('..');
    await wrapper.scrollIntoViewIfNeeded();
    const firstCell = table.locator('tbody tr:first-child td:first-child');
    await firstCell.hover();
    const hover = await firstCell.evaluate(cell => {
      const css = getComputedStyle(cell), token = css.getPropertyValue('--erp-table-hover').trim();
      const parser = new OffscreenCanvas(1, 1).getContext('2d');
      const normalized = value => { parser.fillStyle = '#010203'; parser.fillStyle = value.trim(); return parser.fillStyle; };
      return { background: css.backgroundColor, token, matches: normalized(css.backgroundColor) === normalized(token) };
    });
    check(`${label} 表${index + 1}悬停主题色`, hover.matches, hover);
    const before = await wrapper.evaluate(element => ({ scrollLeft: element.scrollLeft, scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth, ancestors: [...(function* () { for (let node = element.parentElement; node; node = node.parentElement) yield node; })()].map(node => node.scrollLeft) }));
    if (before.scrollWidth > before.clientWidth + 1) {
      await wrapper.hover();
      await page.mouse.wheel(20000, 0);
      await page.waitForFunction(element => element.scrollLeft >= element.scrollWidth - element.clientWidth - 1, await wrapper.elementHandle(), { timeout: 5000 });
    } else check(`${label} 表${index + 1}内容完整容纳无需横滚`, before.scrollWidth <= before.clientWidth + 1);
    const after = await wrapper.evaluate(element => ({ scrollLeft: element.scrollLeft,
      ancestors: [...(function* () { for (let node = element.parentElement; node; node = node.parentElement) yield node; })()].map(node => node.scrollLeft) }));
    check(`${label} 表${index + 1}横滚不带动祖先`, JSON.stringify(before.ancestors) === JSON.stringify(after.ancestors));
    const last = table.locator('tbody tr:last-child td:last-child');
    await last.scrollIntoViewIfNeeded();
    const reach = await last.evaluate(cell => {
      const rect = cell.getBoundingClientRect(), container = cell.closest('.schedule-execution__scroll').getBoundingClientRect();
      return rect.right <= container.right + 1 && rect.left >= container.left - 1 && rect.bottom <= innerHeight + 1 && rect.top >= 0;
    });
    check(`${label} 表${index + 1}末行末列可达`, reach);
    const filename = `${runId}-${label}-table-${index + 1}.png`;
    await wrapper.screenshot({ path: path.join(output, filename) });
    report.evidence.push(path.relative(root, path.join(output, filename)).replaceAll('\\', '/'));
  }
}
async function cleanup() {
  if (context && authenticated && baselineCounts) {
    try {
      report.countsAfter = await counts();
      check('排产/报工/领料/外发记录数量前后不变', JSON.stringify(baselineCounts) === JSON.stringify(report.countsAfter),
        { before: baselineCounts, after: report.countsAfter });
    } catch (error) { report.status = 'FAIL'; report.cleanup.countVerification = safeError(error); }
  }
  if (context && ownSession) {
    try { const result = await request('/api/auth/logout/', 'POST', {}); check('注销本次创建Session', result.status() === 200); report.cleanup.session = 'LOGGED_OUT'; }
    catch (error) { report.status = 'FAIL'; report.cleanup.session = `FAILED: ${safeError(error)}`; }
  }
  if (context) {
    try { await context.close(); report.cleanup.browserClosed = true; }
    catch (error) { report.status = 'FAIL'; report.cleanup.browserClosed = false; report.cleanup.browserError = safeError(error); }
  }
  if (createdProfile) {
    try {
      assert(report.cleanup.browserClosed, '浏览器未关闭，不删除profile');
      assert.equal(path.dirname(path.resolve(profile)), path.resolve(temporaryRoot));
      assert.equal(path.basename(profile), `schedule-detail-01a1591e-${process.pid}`);
      if (fs.existsSync(profile)) {
        assert(!fs.lstatSync(profile).isSymbolicLink(), 'profile不能是链接');
        assert.equal(fs.realpathSync(profile), path.join(fs.realpathSync(temporaryRoot), path.basename(profile)));
        assert.equal(inputJson(ownerPath, 'profile归属标记').runId, runId);
        fs.rmSync(profile, { recursive: true, force: false, maxRetries: 3, retryDelay: 100 });
      }
      assert(!fs.existsSync(profile), 'profile删除后仍存在');
      report.cleanup.profile = 'REMOVED_AND_VERIFIED';
    } catch (error) { report.status = 'FAIL'; report.cleanup.profile = `FAILED: ${safeError(error)}`; }
  }
  if (report.pageErrors.length || report.consoleErrors.length || report.blockedRequests.length) {
    report.status = 'FAIL';
    report.failure ||= '发现页面异常、控制台错误或被阻止的业务写/外部请求';
  }
  report.finishedAt = new Date().toISOString();
  save();
  process.exitCode = report.status === 'FAIL' ? 1 : report.status === 'BLOCKED' ? 2 : 0;
  console.log(JSON.stringify({ qa_result_version: 1, status: report.status,
    passed: report.checks.filter(item => item.passed).length, failed: report.checks.filter(item => !item.passed).length,
    businessWrites: report.businessWrites, not_covered: report.coverage_gap,
    failure: report.failure ? { message: report.failure } : undefined,
    cleanup: report.cleanup.browserClosed && ['NOT_CREATED', 'REMOVED_AND_VERIFIED'].includes(report.cleanup.profile),
    evidence: [path.relative(root, reportPath).replaceAll('\\', '/')] }));
}

async function inspectCompletionPreview(detail) {
  const response = await request(`/api/v1/production-schedules/${detail.id}/completion-preview/`);
  if ([403, 404].includes(response.status())) {
    gap('当前身份不能读取完成预览，未覆盖数量与状态弹窗');
    return;
  }
  check('完成预览真实GET成功', response.status() === 200, response.status());
  const preview = (await response.json()).data;
  const keys = ['MATERIAL', 'METAL', 'SEWING', 'ASSEMBLY'];
  if (preview.task.status !== 'IN_PRODUCTION' || keys.some(key => preview.progress[key]?.percentage !== 100)) {
    gap('当前真实样本未满足完成弹窗入口条件，未更改业务状态来构造样本');
    return;
  }
  for (const viewport of viewports) {
    const label = `${viewport.width}x${viewport.height}`;
    await page.setViewportSize(viewport);
    await page.goto(`${base.origin}/workshop/scheduling`, { waitUntil: 'networkidle' });
    await page.getByPlaceholder('搜索排产单号、生产任务单号、产品').fill(detail.schedule_number);
    await Promise.all([
      page.waitForResponse(res => res.url().includes('/schedule-progress-statuses/') && res.status() === 200),
      page.getByRole('button', { name: '应用筛选', exact: true }).click(),
    ]);
    const row = page.getByRole('row').filter({ hasText: detail.schedule_number });
    await row.getByRole('button', { name: '更多', exact: true }).click();
    const menu = page.getByRole('menuitem', { name: '完成订单', exact: true });
    check(`${label} 完成项可用`, await menu.getAttribute('aria-disabled') !== 'true');
    await menu.click();
    const dialog = page.getByRole('dialog', { name: '完成订单', exact: true });
    await dialog.waitFor({ state: 'visible' });
    check(`${label} 显示生产任务状态`, (await dialog.getByTestId('completion-task-status').innerText()) === preview.task.status_display);
    const table = dialog.getByTestId('completion-products');
    check(`${label} 数量表为7个独立列`, await table.locator('thead th').count() === 7);
    check(`${label} 数量表与真实产品数一致`, await table.locator('tbody tr[data-product-id]').count() === preview.products.length);
    for (const product of preview.products) {
      const cells = table.locator(`tr[data-product-id="${product.schedule_product_id}"] td`);
      check(`${label} 任务要求量来自预览API`, await cells.nth(4).innerText() === product.required_quantity.toLocaleString('zh-CN'));
      check(`${label} 累计成品入库量来自预览API`, await cells.nth(5).innerText() === product.received_quantity.toLocaleString('zh-CN'));
      check(`${label} 单位独立显示`, await cells.nth(6).innerText() === product.unit_name);
    }
    check(`${label} 所有数量单元格保持单行`, await table.locator('th,td').evaluateAll(nodes => nodes.every(node => getComputedStyle(node).whiteSpace === 'nowrap')));
    const filename = `${runId}-${label}-completion-preview.png`;
    await page.screenshot({ path: path.join(output, filename), fullPage: false });
    report.evidence.push(path.relative(root, path.join(output, filename)).replaceAll('\\', '/'));
    await dialog.getByRole('button', { name: '取消', exact: true }).click();
  }
  gap('完成提交后的实际生产/销售更新过程未执行；本脚本禁止业务写入');
}

(async () => {
  fs.mkdirSync(output, { recursive: true });
  // 固定报告入口保留，旧报告原文另存，不清理此前证据或输入文件。
  if (fs.existsSync(reportPath)) fs.copyFileSync(reportPath, path.join(output, `report-before-${runId}.json`), fs.constants.COPYFILE_EXCL);
  save();
  base = new URL(process.env.SCHEDULE_DETAIL_QA_BASE_URL || 'http://localhost:8080');
  if (!['http:', 'https:'].includes(base.protocol) || !['localhost', '127.0.0.1', '[::1]'].includes(base.hostname)) throw new Blocked('仅允许明确的本机HTTP目标');
  const stateFile = process.env.SCHEDULE_DETAIL_QA_STORAGE_STATE;
  const credentialsFile = process.env.SCHEDULE_DETAIL_QA_CREDENTIALS_FILE;
  let storage, credentials;
  if (stateFile) {
    storage = inputJson(stateFile, 'Session storageState');
    if (!Array.isArray(storage.cookies) || !Array.isArray(storage.origins)) throw new Blocked('storageState结构无效');
    if (!storage.cookies.every(cookie => cookie && typeof cookie.name === 'string'
      && typeof cookie.value === 'string' && typeof cookie.domain === 'string')) throw new Blocked('storageState的Cookie结构无效');
    secretValues.push(...storage.cookies.map(cookie => cookie.value));
    storage = { cookies: storage.cookies.filter(cookie => cookie.domain.replace(/^\./, '') === base.hostname),
      origins: storage.origins.filter(origin => origin.origin === base.origin) };
    if (!storage.cookies.some(cookie => cookie.name === 'sessionid' && cookie.value)) throw new Blocked('storageState没有目标主机的现有Session');
    report.authentication = { source: 'EXISTING_STORAGE_STATE' };
    report.cleanup.session = 'EXISTING_SESSION_UNMODIFIED';
  } else if (credentialsFile) {
    credentials = inputJson(credentialsFile, '正常登录凭据文件');
    if (typeof credentials.username !== 'string' || !credentials.username || typeof credentials.password !== 'string' || !credentials.password) throw new Blocked('凭据必须包含非空username和password');
    secretValues.push(credentials.username, credentials.password);
    report.authentication = { source: 'NORMAL_LOGIN' };
  } else throw new Blocked('缺少 SCHEDULE_DETAIL_QA_STORAGE_STATE 或 SCHEDULE_DETAIL_QA_CREDENTIALS_FILE；未创建浏览器或Session');
  const { chromium } = require('../src/frontend/node_modules/playwright-core');
  const executable = process.env.SCHEDULE_DETAIL_QA_BROWSER_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
  if (!fs.existsSync(executable)) throw new Blocked('指定Chromium浏览器不存在');
  if (fs.existsSync(profile)) throw new Blocked('目标临时profile已存在，归属不明；未覆盖或删除');
  if (fs.existsSync(temporaryRoot) && fs.lstatSync(temporaryRoot).isSymbolicLink()) throw new Blocked('临时资源根目录是链接，不能安全创建或清理profile');
  fs.mkdirSync(temporaryRoot, { recursive: true });
  if (fs.realpathSync(temporaryRoot) !== path.join(fs.realpathSync(root), '.tmp')) throw new Blocked('临时资源根目录超出工作区边界');
  save(); // 资源先登记，随后才创建。
  fs.mkdirSync(profile, { recursive: true });
  createdProfile = true;
  report.resources.profile.created = true;
  fs.writeFileSync(ownerPath, JSON.stringify({ task: report.task, runId, pid: process.pid }), { flag: 'wx' });
  save();
  context = await chromium.launchPersistentContext(profile, { headless: true, executablePath: executable,
    viewport: viewports[0], serviceWorkers: 'block' });
  report.cleanup.browserClosed = false;
  await context.route('**/*', route => {
    const req = route.request(), url = new URL(req.url());
    if (url.origin !== base.origin || !['GET', 'HEAD'].includes(req.method()) || /\/(?:rules|vacation)\//.test(url.pathname)) {
      report.blockedRequests.push({ method: req.method(), pathname: url.pathname, sameOrigin: url.origin === base.origin });
      return route.abort('blockedbyclient');
    }
    return route.continue();
  });
  if (context.routeWebSocket) await context.routeWebSocket('**/*', socket => {
    const url = new URL(socket.url());
    if (url.host === base.host && url.protocol === (base.protocol === 'https:' ? 'wss:' : 'ws:')) socket.connectToServer();
    else { report.blockedRequests.push({ method: 'WEBSOCKET', pathname: url.pathname, sameOrigin: false }); socket.close(); }
  });
  if (storage) await context.setStorageState(storage);
  if (credentials) {
    await request('/api/auth/me/');
    const login = await request('/api/auth/login/', 'POST', { username: credentials.username, password: credentials.password });
    if (login.status() !== 200) throw new Blocked(`正常Session登录失败，HTTP ${login.status()}`);
    ownSession = true;
    report.cleanup.session = 'CREATED_PENDING_LOGOUT';
  }
  const auth = await (await request('/api/auth/me/')).json();
  if (!auth.authenticated) throw new Blocked('现有Session无效或过期，未伪造或替换Session');
  if (credentials) check('正常登录身份与输入一致', auth.user?.username === credentials.username);
  authenticated = true;
  report.authentication.superuser = Boolean(auth.user?.is_superuser);
  if (report.authentication.superuser) gap('当前为管理员身份，普通角色真实页面与金额遮蔽未覆盖');
  baselineCounts = await counts(); report.countsBefore = baselineCounts;
  const specified = process.env.SCHEDULE_DETAIL_QA_SCHEDULE_ID;
  if (specified && !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(specified)) throw new Blocked('指定排产ID不是有效UUID');
  const listed = specified ? null : await json('/api/v1/production-schedules/?page_size=1');
  const id = specified || listed.data?.[0]?.id;
  if (!id) throw new Blocked('当前身份没有真实排产数据；不能用空页面验收');
  report.scheduleId = id;
  const detail = (await json(`/api/v1/production-schedules/${id}/`)).data;
  const summary = (await json(`/api/v1/production-schedules/${id}/detail-summary/`)).data;
  if (!detail.products?.length) throw new Blocked('目标排产没有可见真实产品');
  page = await context.newPage();
  page.on('pageerror', error => report.pageErrors.push(safeError(error)));
  page.on('console', message => { if (message.type() === 'error') report.consoleErrors.push(safeError(message.text()).slice(0, 500)); });
  for (const viewport of viewports) {
    const label = `${viewport.width}x${viewport.height}`;
    await page.setViewportSize(viewport);
    await page.goto(`${base.origin}/workshop/scheduling/${id}`, { waitUntil: 'networkidle', timeout: 60000 });
    await page.getByTestId('schedule-estimated-total').waitFor();
    await page.waitForFunction(() => ![...document.querySelectorAll('[data-testid="schedule-estimated-total"]')].some(node => node.textContent.includes('加载中')));
    check(`${label} 未被跳转登录`, !new URL(page.url()).pathname.startsWith('/login'));
    check(`${label} 无页面异常/失败状态`, await page.locator('.schedule-detail .el-alert--error, .schedule-amount-summary .el-alert').count() === 0
      && !await page.locator('.schedule-execution__state').filter({ hasText: '未能加载' }).count());
    await comparePage(detail, summary, label);
    const filename = `${runId}-${label}-page.png`;
    await page.screenshot({ path: path.join(output, filename), fullPage: true });
    report.evidence.push(path.relative(root, path.join(output, filename)).replaceAll('\\', '/'));
    await inspectVisual(label);
    save();
  }
  await inspectCompletionPreview(detail);
  check('没有页面JS异常', report.pageErrors.length === 0, report.pageErrors);
  check('没有控制台错误', report.consoleErrors.length === 0, report.consoleErrors);
  check('没有业务写尝试或外部请求', report.blockedRequests.length === 0, report.blockedRequests);
  check('业务写入为0', report.businessWrites === 0);
  gap('未制造空数据、缺工价、权限拒绝或错误响应；未遇到的状态属于真实数据覆盖缺口');
  report.status = report.coverage_gap.length ? 'PASS_WITH_GAPS' : 'PASS';
})().catch(error => {
  report.status = error instanceof Blocked ? 'BLOCKED' : 'FAIL';
  report.failure = safeError(error);
}).finally(cleanup);

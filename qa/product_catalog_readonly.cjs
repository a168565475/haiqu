/* 独立产品管理：真实Session/API、只读headless页面验收；草稿不提交。 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('../src/frontend/node_modules/playwright-core');

const root = path.resolve(__dirname, '..');
const stamp = new Date().toISOString().replace(/[:.]/g, '-');
const evidence = path.join(root, 'output/product-catalog-20261016-2ebd7b22');
const tempParent = path.join(root, '.tmp/product-catalog-20261016-2ebd7b22');
const temp = path.join(tempParent, `readonly-browser-${stamp}-${process.pid}`);
const reportPath = path.join(evidence, `readonly-${stamp}.json`);
const report = { startedAt: new Date().toISOString(), status: 'RUNNING', checks: [], screenshots: [], notCovered: [], blockedWrites: [], errors: [], resources: { temp, created: false, removed: false } };
const api = '/api/v1/product-catalog/';
let browser, page, context, base, stage = 'preconditions', options, permissions, viewOnly;
const digest = value => crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
const check = (value, message) => { if (!value) throw new Error(message); };
const record = (id, details = {}) => report.checks.push({ id, ...details });
const save = () => fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
const visiblePanel = () => page.locator('.material-catalog-select-popper.el-popper:visible');
const selectRoot = trigger => trigger.locator('xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), " material-catalog-select ")][1]');

async function get(route) {
  const response = await context.request.get(new URL(route, base).href);
  check(response.status() === 200, `真实API状态异常: ${new URL(route, base).pathname} ${response.status()}`);
  return { body: await response.json(), etag: response.headers().etag };
}
async function allProducts() {
  const first = (await get(api + '?page=1&page_size=100')).body;
  const rows = [...first.data];
  for (let number = 2; number <= first.meta.total_pages; number++) rows.push(...(await get(api + `?page=${number}&page_size=100`)).body.data);
  check(rows.length === first.meta.total && new Set(rows.map(item => item.id)).size === rows.length, '分页产品数量不完整或重复');
  return { rows, meta: first.meta };
}
async function shot(label) {
  const file = `${stamp}-${label}.png`;
  await page.screenshot({ path: path.join(evidence, file), fullPage: true });
  report.screenshots.push(file);
}
async function openPage() {
  await page.goto(new URL('/product-catalog', base).href, { waitUntil: 'networkidle' });
  await page.locator('.product-catalog-page').waitFor();
  await page.getByRole('combobox', { name: '产品类别', exact: true }).waitFor();
  await page.evaluate(() => document.fonts.ready);
}
async function openSelect(trigger) {
  if (await trigger.getAttribute('aria-expanded') !== 'true') await selectRoot(trigger).locator('.el-select__wrapper').click();
  await visiblePanel().waitFor();
  await page.waitForFunction(node => node.getAnimations({ subtree: true }).every(animation => animation.playState !== 'running'), await visiblePanel().elementHandle());
}
async function selectValue(trigger, value) {
  await openSelect(trigger);
  await visiblePanel().locator(`[role="option"][data-value="${value}"]`).click();
  await visiblePanel().waitFor({ state: 'hidden' });
}
async function chooseName(name) {
  await openPage();
  const category = page.getByRole('combobox', { name: '产品类别', exact: true });
  if (await selectRoot(category).getAttribute('data-model-value') !== name.category_id) {
    const loaded = page.waitForResponse(response => response.request().method() === 'GET' && new URL(response.url()).pathname === api + 'names/' && new URL(response.url()).searchParams.get('category_id') === name.category_id);
    await selectValue(category, name.category_id);
    check((await loaded).status() === 200, '类别切换读取失败');
  }
  const item = page.locator(`[data-testid="product-names"] [data-name-id="${name.id}"]`);
  await item.waitFor();
  const matchingRows = page.locator(`.product-catalog-page [data-product-id]`);
  await item.click();
  if (name.product_count) await matchingRows.first().waitFor();
  await page.waitForLoadState('networkidle');
}
async function assertRealData(name, names, products, viewport) {
  const expectedNames = names.filter(item => item.category_id === name.category_id);
  const actualNames = await page.locator('[data-testid="product-names"] > button[data-name-id]').evaluateAll(nodes => nodes.map(node => ({ id: node.getAttribute('data-name-id'), name: node.querySelector('.product-name-label').textContent, count: node.querySelector('.product-name-count').textContent })));
  check(actualNames.length === expectedNames.length && actualNames.every(item => expectedNames.some(expected => expected.id === item.id && expected.name === item.name)), '品名列表未完整展示真实类别名称');
  check(actualNames.every(item => item.count === String(expectedNames.find(expected => expected.id === item.id).product_count)), '品名产品数量与真实API不符');
  check(await page.locator('main.catalog-detail').getAttribute('data-name-id') === name.id, '右区未展示当前所选品名');
  const expectedProducts = products.filter(item => item.name_id === name.id);
  const currentRows = await page.locator('tr[data-product-id]').evaluateAll(nodes => nodes.map(node => ({ id: node.getAttribute('data-product-id'), fields: Object.fromEntries([...node.querySelectorAll('td[data-field] .field-value')].map(field => [field.closest('td').getAttribute('data-field'), field.textContent])), colors: [...node.querySelectorAll('[data-color-id]')].map(color => ({ id: color.getAttribute('data-color-id'), value: color.querySelector('span').textContent })) })));
  check(currentRows.length === Math.min(50, expectedProducts.length), '当前品名下产品行被截断或重复');
  for (const actual of currentRows) {
    const expected = expectedProducts.find(item => item.id === actual.id);
    check(expected, '页面产品不属于所选品名');
    for (const field of ['product_code', 'item_number', 'specification', 'unit', 'scale']) check(actual.fields[field] === (expected[field] || (field === 'unit' ? '无单位' : field === 'scale' ? '未填写' : '—')), `${field}页面展示与真实API原文不符`);
    check(JSON.stringify(actual.colors) === JSON.stringify(expected.colors), '产品颜色与真实API不符');
  }
  const longName = await page.locator(`[data-testid="product-names"] > button[data-name-id="${name.id}"]`).evaluate(node => {
    const css = getComputedStyle(node), rect = node.getBoundingClientRect();
    return { height: rect.height, whiteSpace: css.whiteSpace, overflowWrap: css.overflowWrap, textOverflow: css.textOverflow, overflowX: node.scrollWidth - node.clientWidth, textLength: node.textContent.length };
  });
  check(longName.whiteSpace !== 'nowrap' && longName.textOverflow !== 'ellipsis' && longName.overflowX <= 1, '完整品名被截断');
  if (!permissions.add) check(await page.getByRole('button', { name: /^(新增品名|新增产品)$/ }).count() === 0, '仅查看账号出现新增入口');
  if (!permissions.change) check(await page.locator('.product-catalog-page button[aria-label^="编辑"], .product-catalog-page button[aria-label^="删除颜色"], .product-catalog-page button[aria-label="添加颜色"]').count() === 0, '仅查看账号出现编辑或颜色操作入口');
  record('real-names-products-permissions', { viewport, nameId: name.id, completeCategoryNames: actualNames.length, products: currentRows.length, longName, permissions });
}
async function dropdown(trigger, label, viewport) {
  await trigger.focus();
  await page.waitForFunction(node => node.getAnimations({ subtree: true }).every(animation => animation.playState !== 'running'), await selectRoot(trigger).locator('.el-select__wrapper').elementHandle());
  const focusStyle = await selectRoot(trigger).locator('.el-select__wrapper').evaluate(node => {
    const style = getComputedStyle(node);
    return { border: style.borderColor, outline: style.outlineColor, width: style.outlineWidth, offset: style.outlineOffset };
  });
  check(focusStyle.border === 'rgb(56, 152, 236)' && focusStyle.outline === 'rgb(56, 152, 236)' && focusStyle.width === '2px' && focusStyle.offset === '2px', `${label}键盘焦点样式不符: ${JSON.stringify(focusStyle)}`);
  await openSelect(trigger);
  await page.mouse.move(0, 0);
  const panel = visiblePanel();
  const m = await panel.evaluate(node => {
    const css = getComputedStyle(node), box = node.getBoundingClientRect();
    const list = node.querySelector('.el-select-dropdown__wrap');
    return { background: css.backgroundColor, borders: [css.borderTopWidth, css.borderRightWidth, css.borderBottomWidth, css.borderLeftWidth], borderColor: css.borderColor, radius: css.borderRadius, x: box.x, y: box.y, width: box.width, height: box.height, placement: node.getAttribute('data-popper-placement'), listHeight: list?.getBoundingClientRect().height, options: [...node.querySelectorAll('[role="option"]')].map(option => ({ height: option.getBoundingClientRect().height, selected: option.getAttribute('aria-selected') === 'true', color: getComputedStyle(option).color, background: getComputedStyle(option).backgroundColor })) };
  });
  const triggerBox = await selectRoot(trigger).boundingBox();
  check(m.background === 'rgb(252, 251, 247)' && m.borders.every(value => value === '1px') && m.borderColor === 'rgb(221, 214, 201)' && m.radius === '5px', `${label}弹层表面/边框不符`);
  check(m.listHeight <= 240.5 && m.width + 1 >= triggerBox.width && m.x >= 0 && m.y >= 0 && m.x + m.width <= viewport.width + 1 && m.y + m.height <= viewport.height + 1, `${label}弹层位置或滚动区域不符`);
  check(m.options.every(option => Math.abs(option.height - 32) < 0.5), `${label}选项非32px`);
  check(m.options.every(option => option.color === (option.selected ? 'rgb(200, 78, 40)' : 'rgb(31, 29, 24)')), `${label}选项文字颜色不符`);
  const selected = panel.locator('[role="option"][aria-selected="true"]');
  if (await selected.count()) {
    await selected.first().hover();
    check(await selected.first().evaluate(node => getComputedStyle(node).backgroundColor) === 'rgb(255, 244, 230)', `${label}选中悬停底色变化`);
  }
  const ordinary = panel.locator('[role="option"]:not([aria-selected="true"]):not(.is-disabled)').first();
  if (await ordinary.count()) {
    await ordinary.hover();
    check(await ordinary.evaluate(node => getComputedStyle(node).backgroundColor) === 'rgb(255, 246, 234)', `${label}悬停色不符`);
    check(await ordinary.evaluate(node => { const box = node.getBoundingClientRect(); const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2); return node === hit || node.contains(hit); }), `${label}选项被其他浮层遮挡`);
  }
  await shot(`${viewport.width}-${label}-expanded`);
  const priorValue = await selectRoot(trigger).getAttribute('data-model-value');
  await trigger.press('ArrowDown');
  check(await selectRoot(trigger).getAttribute('data-model-value') === priorValue, `${label}方向键提前提交`);
  await trigger.press('Escape');
  await panel.waitFor({ state: 'hidden' });
  await openSelect(trigger); await trigger.press('Tab'); await panel.waitFor({ state: 'hidden' });
  check(await selectRoot(trigger).getAttribute('data-model-value') === priorValue, `${label}关闭意外改值`);
  await openSelect(trigger); await trigger.press('ArrowDown');
  const active = panel.locator('[role="option"].is-hovering');
  check(await active.count() === 1, `${label}键盘活动项不唯一`);
  const activeValue = await active.getAttribute('data-value');
  await trigger.press('Enter'); await panel.waitFor({ state: 'hidden' });
  check(await selectRoot(trigger).getAttribute('data-model-value') === activeValue, `${label}Enter没有提交活动项`);
  await page.waitForLoadState('networkidle');
  record('dropdown', { label, viewport, measurement: m, focusStyle, keyboard: ['ArrowDown-no-commit', 'Escape', 'Tab', 'ArrowDown-Enter-commit'] });
}
async function disabledCategory(viewport) {
  const trigger = page.getByRole('combobox', { name: '产品类别', exact: true });
  check(await trigger.isDisabled(), '加载或编辑期间类别未禁用');
  const wrapper = selectRoot(trigger).locator('.el-select__wrapper');
  await wrapper.hover();
  await page.waitForFunction(node => node.getAnimations({ subtree: true }).every(animation => animation.playState !== 'running'), await wrapper.elementHandle());
  const styles = await wrapper.evaluate(node => {
    const css = getComputedStyle(node);
    return { background: css.backgroundColor, border: css.borderColor, opacity: css.opacity, outline: css.outlineWidth, outlineStyle: css.outlineStyle, outlineColor: css.outlineColor, className: node.className, height: node.getBoundingClientRect().height };
  });
  check(styles.background === 'rgb(232, 225, 213)' && styles.border === 'rgb(221, 214, 201)' && styles.opacity === '1' && (styles.outlineStyle === 'none' || styles.outline === '0px') && styles.height === 32, '禁用类别控件样式不符: ' + JSON.stringify(styles));
  await wrapper.click({ force: true });
  check(await trigger.getAttribute('aria-expanded') !== 'true', '禁用类别仍可展开');
  record('disabled-category', { viewport, styles });
}
async function loadingAndError(viewport) {
  const routePattern = '**/api/v1/product-catalog/options/';
  let release, arrived, pending;
  const gate = new Promise(resolve => { release = resolve; });
  const received = new Promise(resolve => { arrived = resolve; });
  const delay = route => { arrived(); pending = (async () => { await gate; await route.continue(); })(); return pending; };
  await page.route(routePattern, delay);
  try {
    await page.goto(new URL('/product-catalog', base).href, { waitUntil: 'domcontentloaded' });
    await received;
    await page.getByRole('combobox', { name: '产品类别', exact: true }).waitFor();
    await disabledCategory(viewport);
    check(await page.getByText('加载中…', { exact: true }).isVisible(), '真实请求未完成时未显示加载状态');
    await shot(`${viewport.width}-loading-real-response-delayed`);
  } finally { release(); if (pending) await pending; await page.unroute(routePattern, delay); }
  await page.waitForLoadState('networkidle');
  const fail = route => route.abort('failed');
  await page.route(routePattern, fail);
  await page.reload({ waitUntil: 'networkidle' });
  await page.locator('.product-catalog-page > [role="alert"]').waitFor();
  await shot(`${viewport.width}-load-network-failure`);
  await page.unroute(routePattern, fail);
  await page.getByRole('button', { name: '重新加载', exact: true }).click();
  await page.locator('[data-product-id]').first().waitFor();
  record('loading-error-retry', { viewport, faultInjection: '延迟真实GET响应及中断GET网络；不提供替身响应' });
}
async function measure(label, viewport) {
  const measured = await page.evaluate(() => {
    const rootNode = document.querySelector('.product-catalog-page');
    const c = getComputedStyle(rootNode), r = rootNode.getBoundingClientRect();
    const controls = [...rootNode.querySelectorAll('button,input,.el-select__wrapper')].filter(node => node.getClientRects().length && getComputedStyle(node).visibility !== 'hidden' && !node.classList.contains('el-select__input')).map(node => { const s = getComputedStyle(node), b = node.getBoundingClientRect(); return { tag: node.tagName, role: node.getAttribute('role'), isNameItem: node.hasAttribute('data-name-id'), label: node.getAttribute('aria-label') || node.textContent.trim().slice(0, 32), height: b.height, background: s.backgroundColor, border: s.borderColor, color: s.color, font: s.fontFamily, size: s.fontSize }; });
    const shell = ['.erp-layout__sidebar', '.erp-layout__header'].map(selector => { const el = document.querySelector(selector), s = getComputedStyle(el), b = el.getBoundingClientRect(); return { selector, width: b.width, height: b.height, x: b.x, y: b.y, fontFamily: s.fontFamily, fontSize: s.fontSize, lineHeight: s.lineHeight, color: s.color, background: s.backgroundColor }; });
    const h = rootNode.querySelector('h2');
    const table = rootNode.querySelector('.product-table');
    const cssOf = node => { const style = getComputedStyle(node), rect = node.getBoundingClientRect(); return { height: rect.height, width: rect.width, borders: [style.borderTopWidth, style.borderRightWidth, style.borderBottomWidth, style.borderLeftWidth], color: style.borderColor, background: style.backgroundColor, text: style.color, size: style.fontSize, weight: style.fontWeight, padding: [style.paddingLeft, style.paddingRight] }; };
    const cells = table ? [...table.querySelectorAll('tbody tr[data-product-id] td')] : [];
    const bodyRows = table ? [...table.querySelectorAll('tbody tr[data-product-id]')] : [];
    const tableEvidence = table ? { surface: cssOf(table), header: [...table.querySelectorAll('th')].map(cssOf), firstCell: cells[0] && cssOf(cells[0]), lastCell: cells.length && cssOf(cells[cells.length - 1]), rowHeights: bodyRows.map(node => node.getBoundingClientRect().height) } : null;
    const scroll = rootNode.querySelector('.product-table-scroll');
    return { root: { x: r.x, y: r.y, width: r.width, height: r.height, font: c.fontFamily, size: c.fontSize, background: c.backgroundColor }, bodyFont: getComputedStyle(document.body).fontFamily, headingSize: h ? getComputedStyle(h).fontSize : null, documentOverflow: { x: document.documentElement.scrollWidth - innerWidth, y: document.documentElement.scrollHeight - innerHeight }, controls, shell, tableEvidence, localOverflow: scroll && { x: scroll.scrollWidth - scroll.clientWidth, y: scroll.scrollHeight - scroll.clientHeight }, nativeSelects: rootNode.querySelectorAll('select').length, rows: bodyRows.length };
  });
  check(measured.nativeSelects === 0, '存在原生select');
  check(measured.documentOverflow.x <= 1 && measured.documentOverflow.y <= 1, '出现整页无必要滚动');
  check(measured.root.size === '13px' && (measured.headingSize === null || measured.headingSize === '17px'), '页面字体大小改变');
  if (measured.tableEvidence) {
    const table = measured.tableEvidence;
    check(table.surface.borders.every(value => value === '1px') && table.surface.color === 'rgb(221, 214, 201)', '表格四边不是单层1px暖灰边');
    check(table.header.every(cell => cell.height === 44 && cell.background === 'rgb(240, 234, 223)' && cell.text === 'rgb(111, 106, 97)' && cell.size === '12px' && cell.weight === '500' && cell.padding.every(value => value === '16px')), '表头高度/颜色/文字/内边距不符');
    if (table.lastCell && label !== 'new-product') check(table.lastCell.borders[2] === '0px', '末行单元格与外框重复绘制底边');
    if (table.firstCell) check(table.firstCell.borders[0] === '0px' && table.firstCell.borders[3] === '0px' && table.lastCell.borders[1] === '0px', '首行/首列/末列存在叠加边框');
    check(table.rowHeights.every(height => height >= 34), '数据行小于紧凑34px基准');
    if (viewport.width === 1920) check(measured.localOverflow.x <= 1, '1920桌面出现无必要横向滚动');
  }
  const baseline = JSON.parse(fs.readFileSync(path.join(evidence, 'visual-baseline.json'), 'utf8')).viewports.find(item => item.width === viewport.width);
  check(measured.bodyFont === baseline.bodyFont, '外壳字体改变');
  for (const actual of measured.shell) check(JSON.stringify(actual) === JSON.stringify(baseline.elements.find(item => item.selector === actual.selector)), '外部侧栏/顶栏样式改变');
  const wrong = measured.controls.filter(control => Math.abs(control.height - 32) > 0.5 && control.role !== 'option' && !control.isNameItem);
  // 品名列表允许长名换行，不把列表项误当成单行表单控件。
  const wrongSingle = wrong.filter(control => !control.label.includes('选择品名'));
  check(wrongSingle.length === 0, '单行控件不是32px: ' + wrongSingle.map(item => item.label + '=' + item.height).join(','));
  record('layout-and-controls', { label, viewport, measured });
}
async function scrollTable(viewport) {
  const scroll = page.locator('.product-table-scroll');
  const overflow = await scroll.evaluate(node => ({ x: node.scrollWidth - node.clientWidth, y: node.scrollHeight - node.clientHeight }));
  if (overflow.x <= 1 && overflow.y <= 1) return;
  await scroll.evaluate(node => node.scrollTo({ left: node.scrollWidth, top: node.scrollHeight, behavior: 'instant' }));
  const position = await scroll.evaluate(node => {
    const area = node.getBoundingClientRect(), cell = node.querySelector('tr[data-product-id]:last-child td:last-child').getBoundingClientRect();
    return { scrollLeft: node.scrollLeft, scrollTop: node.scrollTop, cell: { left: cell.left, right: cell.right, top: cell.top, bottom: cell.bottom }, area: { left: area.left, right: area.right, top: area.top, bottom: area.bottom }, documentX: document.documentElement.scrollWidth - innerWidth, documentY: document.documentElement.scrollHeight - innerHeight };
  });
  check(position.cell.left >= position.area.left && position.cell.right <= position.area.right && position.cell.top >= position.area.top && position.cell.bottom <= position.area.bottom, '局部滚动后末产品颜色列仍不可达');
  check(position.documentX <= 1 && position.documentY <= 1, '局部滚动引发整页溢出');
  await shot(`${viewport.width}-multi-product-scrolled-bottom-right`);
  record('local-table-scroll-last-cell', { viewport, overflow, position });
  await scroll.evaluate(node => node.scrollTo({ left: 0, top: 0, behavior: 'instant' }));
}
async function main() {
  const state = process.env.PRODUCT_CATALOG_QA_STORAGE_STATE;
  check(state && fs.existsSync(state), '需要既有有效Session文件');
  base = new URL(process.env.PRODUCT_CATALOG_QA_BASE_URL || 'http://localhost:8080');
  check(['http:', 'https:'].includes(base.protocol) && !base.username && !base.password && base.pathname === '/', '目标URL无效');
  check(!fs.existsSync(temp), '本任务浏览器目录已存在');
  fs.mkdirSync(evidence, { recursive: true }); save();
  fs.mkdirSync(tempParent, { recursive: true }); fs.mkdirSync(temp); report.resources.created = true;
  save();
  process.env.TEMP = temp; process.env.TMP = temp; process.env.TMPDIR = temp;
  const executablePath = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
  check(executablePath, '没有可用的现有浏览器');
  browser = await chromium.launch({ headless: true, executablePath, downloadsPath: temp });
  context = await browser.newContext({ storageState: state, locale: 'zh-CN', timezoneId: 'Asia/Shanghai', serviceWorkers: 'block' });
  await context.route('**/*', async route => {
    if (!['GET', 'HEAD'].includes(route.request().method())) { report.blockedWrites.push({ method: route.request().method(), path: new URL(route.request().url()).pathname }); await route.abort('blockedbyclient'); return; }
    await route.continue();
  });
  const auth = (await get('/api/auth/me/')).body;
  check(auth.authenticated, 'Session无效');
  const allowed = new Set(auth.user?.permissions || []);
  permissions = { view: allowed.has('product_catalog.view_productcatalog'), add: allowed.has('product_catalog.add_productcatalog'), change: allowed.has('product_catalog.change_productcatalog') };
  check(permissions.view, '真实账号缺少产品查看权限');
  const requestedMode = process.env.PRODUCT_CATALOG_QA_MODE || 'auto';
  check(['auto', 'view-only'].includes(requestedMode), 'PRODUCT_CATALOG_QA_MODE只能为auto或view-only');
  viewOnly = requestedMode === 'view-only' || !permissions.add || !permissions.change;
  report.mode = viewOnly ? 'view-only' : 'unsaved-drafts';
  record('real-permission-mode', { mode: report.mode, permissions, source: '/api/auth/me/' });
  if (viewOnly) report.notCovered.push('本次为真实view-only分支：未打开或验收新增品名、新增产品、字段编辑、常规/定制编辑下拉、草稿导航锁、编辑错误气泡及保存中宽度/焦点/重复提交；需具备写权限的会话继续。');
  options = (await get(api + 'options/')).body.data;
  const names = (await get(api + 'names/')).body.data;
  check(options.categories.length >= 34 && names.length >= 119, '导入数据尚未就绪');
  const catalog = await allProducts();
  check(catalog.rows.length === 207, '本次来源导入207条产品数量不符');
  check(names.reduce((total, name) => total + name.product_count, 0) === catalog.rows.length, '品名产品数量合计与产品分页结果不符');
  record('real-catalog-inventory', { categories: options.categories.length, names: names.length, products: catalog.rows.length, pages: catalog.meta.total_pages, pageSize: catalog.meta.page_size, uniqueProducts: new Set(catalog.rows.map(item => item.id)).size });
  if (!names.some(name => name.product_count > 50)) report.notCovered.push('真实导入品名组均未超过50条：全局207条API分页已覆盖，但单品名超过50条的页面翻页没有真实数据前提，未伪造数据。');
  const samples = [names.reduce((a, b) => a.product_count >= b.product_count ? a : b), names.reduce((a, b) => a.name.length >= b.name.length ? a : b)];
  const before = new Map();
  for (const name of samples) {
    const list = (await get(api + '?name_id=' + name.id + '&page_size=100')).body;
    for (const row of list.data) { const detail = await get(api + row.id + '/'); before.set(row.id, digest(detail)); }
  }
  page = await context.newPage();
  page.on('pageerror', error => report.errors.push({ type: 'pageerror', message: error.message }));
  for (const viewport of [{ width: 1920, height: 1080 }, { width: 1440, height: 900 }]) {
    stage = `desktop-${viewport.width}`;
    await page.setViewportSize(viewport);
    await loadingAndError(viewport);
    await chooseName(samples[0]);
    await assertRealData(samples[0], names, catalog.rows, viewport);
    await measure('multi-product', viewport); await shot(`${viewport.width}-multi-product`);
    await scrollTable(viewport);
    await dropdown(page.getByRole('combobox', { name: '产品类别', exact: true }), 'category', viewport);
    await chooseName(samples[1]); await assertRealData(samples[1], names, catalog.rows, viewport); await measure('long-name', viewport); await shot(`${viewport.width}-long-name`);
    if (!viewOnly) {
      const row = page.locator('[data-product-id]').first();
      const edit = row.getByRole('button', { name: '编辑常规/定制', exact: true });
      await edit.click();
      await dropdown(row.getByRole('combobox'), 'scale-edit', viewport);
      await measure('scale-edit', viewport); await shot(`${viewport.width}-scale-edit`);
      await openPage();
      await page.getByRole('button', { name: '新增品名', exact: true }).click();
      await disabledCategory(viewport);
      const visibleSelectors = page.getByRole('combobox');
      const count = await visibleSelectors.count();
      if (count > 1) await dropdown(visibleSelectors.nth(count - 1), 'new-name-category', viewport);
      await measure('new-name', viewport); await shot(`${viewport.width}-new-name`);
      await chooseName(samples[0]);
      await page.getByRole('button', { name: '新增产品', exact: true }).click();
      const selectors = page.getByRole('combobox');
      await dropdown(selectors.nth(await selectors.count() - 1), 'new-product-scale', viewport);
      await measure('new-product', viewport); await shot(`${viewport.width}-new-product`);
    }
    await openPage();
    const query = 'QA_NO_MATCH_' + crypto.randomUUID();
    const empty = page.waitForResponse(response => new URL(response.url()).pathname === api + 'names/' && new URL(response.url()).searchParams.get('q') === query);
    await page.getByLabel('搜索品名', { exact: true }).fill(query);
    check((await (await empty).json()).data.length === 0, '真实搜索应无结果');
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="product-names"] [data-name-id]').length === 0);
    check(await page.locator('[data-product-id]').count() === 0, '无结果仍显示旧产品');
    await measure('no-match', viewport); await shot(`${viewport.width}-no-match`);
  }
  stage = 'unchanged';
  for (const [id, fingerprint] of before) check(digest(await get(api + id + '/')) === fingerprint, '只读验收期间记录变化');
  check(digest((await allProducts()).rows) === digest(catalog.rows), '只读验收期间207条产品列表发生变化');
  record('unchanged-and-no-writes', { products: catalog.rows.length, sampleDetails: before.size, blockedWrites: report.blockedWrites.length });
  check(report.blockedWrites.length === 0 && report.errors.length === 0, '只读验收出现写请求或页面错误');
  report.notCovered.push('本脚本不提交写操作；新增/字段保存/颜色增删/过期版本/权限拒绝/保存失败由独立授权写库验收覆盖。', '禁用与错误控件、超长及多颜色等状态仅在实际存在时验证，不以只读草稿或截图代替写入验收。');
  report.status = 'PASS_WITH_GAPS';
}
(async () => {
  try { await main(); }
  catch (error) { report.status = 'FAIL'; process.exitCode = 1; report.failure = { stage, message: error.message, stack: error.stack }; if (page && !page.isClosed()) try { await shot('failure'); } catch (shotError) { report.diagnosticError = shotError.message; } }
  finally {
    report.cleanupErrors = [];
    let browserClosed = !browser;
    try { if (browser) await browser.close(); browserClosed = true; }
    catch (error) { report.cleanupErrors.push({ stage: 'browser-close', message: error.message }); }
    if (report.resources.created && browserClosed) {
      try {
        check(path.dirname(temp) === tempParent && !fs.lstatSync(temp).isSymbolicLink() && fs.realpathSync(temp).toLowerCase() === temp.toLowerCase(), '临时目录清理边界不符');
        fs.rmSync(temp, { recursive: true }); report.resources.removed = !fs.existsSync(temp);
      } catch (error) { report.cleanupErrors.push({ stage: 'browser-files', path: temp, message: error.message }); }
    }
    if (report.cleanupErrors.length) { report.status = 'FAIL'; process.exitCode = 1; }
    report.finishedAt = new Date().toISOString();
    try { fs.mkdirSync(evidence, { recursive: true }); save(); }
    catch (error) { report.status = 'FAIL'; process.exitCode = 1; console.error(JSON.stringify({ stage: 'save-cleanup-report', message: error.message, report })); }
    console.log(JSON.stringify({ qa_result_version: 1, status: report.status, not_covered: report.notCovered, checks: report.checks.length, report: reportPath, cleanup: report.resources.removed, failure: report.failure?.message }));
  }
})();

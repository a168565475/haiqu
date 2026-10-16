/**
 * 生产任务单查看页 B：真实 API + headless 只读验收。
 * 只允许认证 POST /api/auth/login/；拒绝所有其他非 GET/HEAD 请求。
 * 不生成业务记录，不保存凭据、Cookie 或完整 API 响应。
 * 临时路径已登记于 docs/production-task-detail-design-b-2026-10-15.md。
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('../src/frontend/node_modules/playwright-core');

const root = path.resolve(__dirname, '..');
const evidenceDir = path.join(root, 'output', 'production-task-detail-b-20261015', 'width-380');
const browserTemp = path.join(evidenceDir, 'browser_temp');
const base = new URL(process.env.TASK_DETAIL_QA_BASE_URL || 'http://localhost:8080');
const statePath = process.env.TASK_DETAIL_QA_STORAGE_STATE;
const username = process.env.TASK_DETAIL_QA_USERNAME;
const password = process.env.TASK_DETAIL_QA_PASSWORD;
const requestedId = process.env.TASK_DETAIL_QA_TASK_ID;
const allStates = ['DRAFT', 'PENDING_VALIDATION', 'READY', 'IN_PRODUCTION', 'COMPLETED', 'PAUSED', 'CANCELLED'];
const labels = { DRAFT: '草稿', PENDING_VALIDATION: '待PMC确认', READY: '已接单', IN_PRODUCTION: '生产中', COMPLETED: '已完成', PAUSED: '已暂停', CANCELLED: '已取消' };
const report = {
  schemaVersion: 1, startedAt: new Date().toISOString(), mode: 'real-api-read-only',
  status: 'RUNNING', apiReads: [], blockedWrites: [], pageErrors: [], httpErrors: [],
  checks: [], screenshots: [], coverage: { states: [], productCounts: [] }, notCovered: [],
  resources: { browserTemp, created: false, browserClosed: false, removed: false, verifiedAbsent: false },
};
let browser;
let browserTempCreated = false;
let evidencePathVerified = false;
const oldTemp = { TEMP: process.env.TEMP, TMP: process.env.TMP, TMPDIR: process.env.TMPDIR };

function fail(code, message) {
  const error = new Error(message);
  error.code = code;
  error.safeQaMessage = true;
  throw error;
}
function check(condition, code, message) { if (!condition) fail(code, message); }
function compact(value) { return String(value ?? '').replace(/\s+/g, ''); }
function hash(value) { return crypto.createHash('sha256').update(String(value)).digest('hex').slice(0, 16); }
function taskRef(task) { return hash(task.id); }
function safePath(raw) {
  try {
    return new URL(raw, base).pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, ':id');
  } catch { return 'invalid-url'; }
}
function safeSamePath(a, b) {
  const normalize = p => process.platform === 'win32' ? path.resolve(p).toLowerCase() : path.resolve(p);
  return normalize(a) === normalize(b);
}
function number(value) {
  if (value === null || value === undefined || value === '') return '—';
  const parsed = Number(value);
  return Number.isFinite(parsed) ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(parsed) : String(value);
}
function dateTime(value) {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(parsed).replaceAll('/', '-');
}
function quantity(products) {
  const groups = new Map();
  for (const product of products) {
    const key = product.unit_id || product.unit_name || 'UNKNOWN';
    const row = groups.get(key) || { name: product.unit_name || product.unit_code || '单位未知', value: 0 };
    if (!Number.isFinite(Number(product.quantity))) return '数量待确认';
    row.value += Number(product.quantity);
    groups.set(key, row);
  }
  return [...groups.values()].map(row => number(row.value) + ' ' + row.name).join(' / ') || '—';
}
function amount(products) {
  let sum = 0n;
  for (const product of products) {
    const value = String(product.local_total_amount ?? '');
    if (!/^-?\d+(?:\.\d{1,4})?$/.test(value)) return '—';
    const [whole, fraction = ''] = value.replace('-', '').split('.');
    sum += (BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'))) * (value.startsWith('-') ? -1n : 1n);
  }
  const absolute = sum < 0n ? -sum : sum;
  return (sum < 0n ? '-' : '') + (absolute / 10000n).toLocaleString('zh-CN') + '.' + String(absolute % 10000n).padStart(4, '0');
}
async function getJson(context, route, kind) {
  let response;
  try { response = await context.request.get(new URL(route, base).href, { maxRedirects: 0 }); }
  catch { fail('API_UNREACHABLE', kind + '请求失败；未保存请求细节。'); }
  report.apiReads.push({ kind, status: response.status() });
  check(response.status() === 200, 'API_STATUS', kind + '未返回 200。');
  try { return await response.json(); }
  catch { fail('API_JSON', kind + '没有返回有效 JSON。'); }
}
async function authenticate(context) {
  let me = await getJson(context, '/api/auth/me/', 'authentication-state');
  if (statePath) {
    check(me.authenticated === true, 'SESSION_EXPIRED', '指定会话无效或已过期，请提供可用会话。');
    report.authentication = 'existing-session';
    return me.user;
  }
  check(Boolean(username && password), 'AUTH_REQUIRED', '需要账号密码，或 TASK_DETAIL_QA_STORAGE_STATE。');
  const cookie = (await context.cookies(base.origin)).find(item => item.name === 'csrftoken');
  check(Boolean(cookie?.value), 'CSRF_MISSING', '认证初始化未取得 CSRF Cookie。');
  let response;
  try {
    response = await context.request.post(new URL('/api/auth/login/', base).href, {
      headers: { 'X-CSRFToken': cookie.value, Referer: base.origin + '/' },
      data: { username, password }, maxRedirects: 0,
    });
  } catch { fail('LOGIN_REQUEST', '正常登录请求失败；未保存请求细节或凭据。'); }
  report.authentication = 'normal-session-csrf-login';
  report.authenticationPostCount = 1;
  check(response.status() === 200, 'LOGIN_REJECTED', '正常登录未成功，请检查账号状态及访问权限。');
  me = await getJson(context, '/api/auth/me/', 'authenticated-state');
  check(me.authenticated === true, 'LOGIN_NO_SESSION', '登录后没有有效 Session。');
  return me.user;
}
async function fieldPairs(locator) {
  return locator.evaluate(rootNode => {
    const pairs = [];
    for (const node of rootNode.querySelectorAll('dl > div, .info-grid > label, .info-grid > div, .file-fields > label, .summary-bar > div')) {
      const label = node.querySelector(':scope > dt, :scope > span');
      const value = node.querySelector(':scope > dd, :scope > strong');
      if (label && value) pairs.push([label.textContent.trim(), value.textContent.trim()]);
    }
    return pairs;
  });
}
function checkPairs(actual, expected, group) {
  for (const [label, value] of expected) {
    const row = actual.find(([key]) => compact(key).replace('（按单位）', '') === compact(label));
    check(Boolean(row), 'FIELD_MISSING', group + '缺少字段：' + label);
    check(compact(row[1]) === compact(value), 'FIELD_VALUE', group + '字段与真实 API 不一致：' + label);
  }
}
function expectedBasic(task) {
  return [
    ['来源销售订单', task.source_sales_order_number || '手动创建（未关联销售订单）'],
    ['业务员', task.salesperson?.display_name || ''],
    ['跟单员', (task.followers || []).map(person => person.display_name).join('、') || '待选择'],
    ['下单日期', task.order_date || ''], ['交期日期', task.delivery_date || ''],
    ['计划员', task.planner?.display_name || '—'], ['是否含税', task.includes_tax ? '含税' : '不含税'],
    ['税率', task.tax_rate ? task.tax_rate + '%' : '—'],
    ['订单误差', (task.order_tolerance_percent || '0') + '%'],
    ['是否返单', task.is_repeat_order ? '是' : '否'],
    ['交货方式', task.delivery_method === 'SPLIT' ? '分批交货' : '一次交货'],
    ['生产优先级', ({ URGENT: '紧急', HIGH: '高', LOW: '低' })[task.production_priority] || '普通'],
    ['生产数量', quantity(task.products)], ['人民币金额合计', '¥ ' + amount(task.products)],
    ['生产批号', task.production_batch_number || task.source_delivery_batch_number || '—'],
  ];
}
function expectedProduct(task, product) {
  return [
    ['产品', product.customer_product_name || product.product_name || '—'],
    ['货号', product.item_number || '—'],
    ['颜色', product.customer_color || product.color_name || product.color_code || '—'],
    ['规格', product.specification_display || product.customer_specification || product.specification || '—'],
    ['材质', product.material || '—'],
    ['数量', number(product.quantity) + ' ' + (product.unit_name || product.unit_code || '单位未知')],
    ['人民币单价', '¥ ' + (product.local_unit_price ?? '—')], ['人民币金额', '¥ ' + (product.local_total_amount ?? '—')],
    ['计划开工', task.planned_start_date || '—'], ['计划完工', task.planned_end_date || '—'],
    ['包装要求', product.packaging_method || '—'], ['备注', product.special_requirements || '—'],
  ];
}
async function checkFields(page, task) {
  const rootNode = page.locator('.task-detail-page');
  checkPairs(await fieldPairs(rootNode), expectedBasic(task), '基本信息及顶部汇总');
  const summary = compact(await rootNode.locator('.summary-bar').innerText());
  for (const [label, value] of [['生产数量', quantity(task.products)], ['人民币金额合计', '¥ ' + amount(task.products)], ['交期日期', task.delivery_date || '—']]) {
    check(summary.includes(compact(value)), 'SUMMARY_VALUE', '顶部汇总与真实 API 不一致：' + label);
  }
  const files = rootNode.locator('details.product-file');
  check(await files.count() === task.products.length, 'PRODUCT_COUNT', '产品档案数量与真实 API 不一致。');
  for (let index = 0; index < task.products.length; index++) {
    const product = task.products[index];
    const file = files.nth(index);
    const productId = await file.getAttribute('data-product-id');
    if (productId) check(productId === product.id, 'PRODUCT_ID', '产品档案 ID 顺序与真实 API 不一致。');
    checkPairs(await fieldPairs(file.locator('.file-fields')), expectedProduct(task, product), '产品档案第 ' + (index + 1) + ' 项');
    const imageSources = await file.locator('img').evaluateAll(nodes => nodes.map(node => node.getAttribute('src') || ''));
    for (const image of product.images || []) {
      check(imageSources.some(source => source.includes('/production-tasks/' + task.id + '/business-files/' + image.id + '/')),
        'PRODUCT_IMAGE', '产品图片未使用当前任务的真实业务文件地址。');
    }
    if (!product.images?.length) check((await file.locator('.product-photo').innerText()).includes('暂无产品图片'), 'IMAGE_EMPTY', '无产品图片时缺少真实空状态。');
  }
  const productionText = await page.evaluate(html => {
    const holder = document.createElement('div');
    holder.innerHTML = html || '';
    return (holder.textContent || '').replace(/\s+/g, ' ').trim() || '—';
  }, task.special_requirements_html);
  const packaging = [...new Set(task.products.map(product => String(product.packaging_method || '').trim()).filter(Boolean))].join('；') || '—';
  checkPairs(await fieldPairs(rootNode.locator('.requirements-card')), [
    ['包装要求', packaging], ['生产说明', productionText],
    ['产前样', task.preproduction_sample_required ? '需要产前确认样' : '不需要产前确认样'],
    ['其他要求', task.status_reason || '—'],
  ], '详细要求');
  const activityText = compact(await rootNode.locator('.activity-card').innerText());
  for (const event of task.audit_timeline || []) {
    for (const text of [dateTime(event.occurred_at), event.action_display, event.actor_name || '系统', event.reason].filter(Boolean)) {
      check(activityText.includes(compact(text)), 'AUDIT_VALUE', '操作记录文本未完整保留。');
    }
  }
  if (!task.audit_timeline?.length) check(activityText.includes('暂无操作记录'), 'AUDIT_EMPTY', '空操作记录缺少说明。');
  const sidebarText = compact(await rootNode.locator('.task-sidebar').innerText());
  for (const bom of task.current_boms || []) {
    for (const text of [bom.bom_number, 'V' + bom.version_number, bom.status_display]) {
      check(sidebarText.includes(compact(text)), 'BOM_VALUE', 'BOM 信息未完整保留。');
    }
  }
  if (!task.current_boms?.length) check(sidebarText.includes('尚未建立'), 'BOM_EMPTY', '无 BOM 时缺少真实空状态。');
  check(sidebarText.includes(task.pmc_confirmation ? '已通过' : '尚未确认'), 'PMC_VALUE', 'PMC 确认状态不符。');
  if (task.pmc_confirmation) check(sidebarText.includes(compact(dateTime(task.pmc_confirmation.confirmed_at))), 'PMC_TIME', 'PMC 确认时间未保留。');
  checkPairs(await fieldPairs(rootNode.locator('.task-sidebar')), [['计划开工', task.planned_start_date || '—'], ['计划完工', task.planned_end_date || '—']], '生产计划');
}
async function checkStatus(page, task, user) {
  const rootNode = page.locator('.task-detail-page');
  check(compact(await rootNode.locator('.task-number').innerText()) === compact(task.task_number), 'TASK_NUMBER', '任务单号与真实 API 不一致。');
  check(compact(await rootNode.locator('.task-status').innerText()) === compact(task.status_display), 'TASK_STATUS', '任务状态标签与真实 API 不一致。');
  const current = rootNode.locator('.status-steps .is-current');
  check(await current.count() === 1, 'STATE_CURRENT', '流程必须恰有一个当前节点。');
  check(compact(await current.locator('span').last().innerText()) === compact(labels[task.status]), 'STATE_LABEL', '当前流程节点与真实状态不一致。');
  const completed = { DRAFT: 0, PENDING_VALIDATION: 1, READY: 2, IN_PRODUCTION: 3, COMPLETED: 4, PAUSED: 4, CANCELLED: 0 }[task.status];
  check(await rootNode.locator('.status-steps .is-done').count() === completed, 'STATE_DONE', '已完成流程节点数量发生回归。');
  const permissions = new Set(user.permissions || []);
  const canFinish = user.module_access_enabled ? permissions.has('access_control.finish_productiontask') : permissions.has('production_tasks.change_productiontask');
  const expected = [
    ['编辑', permissions.has('production_tasks.change_productiontask') && ['DRAFT', 'PENDING_VALIDATION', 'READY', 'IN_PRODUCTION', 'PAUSED'].includes(task.status)],
    ['返回', true],
    ['提交 PMC 确认', permissions.has('production_tasks.submit_productiontask') && task.status === 'DRAFT'],
    ['PMC 确认通过', permissions.has('production_tasks.confirm_productiontask') && task.status === 'PENDING_VALIDATION'],
    ['退回修改', permissions.has('production_tasks.confirm_productiontask') && task.status === 'PENDING_VALIDATION'],
    ['计划排产', permissions.has('production_scheduling.view_productionschedule') && permissions.has('production_scheduling.add_productionschedule') && task.status === 'READY'],
    ['完成生产', canFinish && task.status === 'IN_PRODUCTION'],
  ];
  for (const [name, visible] of expected) {
    check(await rootNode.getByRole('button', { name, exact: true }).count() === (visible ? 1 : 0), 'ACTION_PERMISSION', '原有权限/状态按钮发生变化：' + name);
  }
}
async function measure(page, width) {
  const result = await page.locator('.task-detail-page').evaluate(rootNode => {
    const visible = element => {
      const closed = element.closest('details:not([open])');
      if (closed && element !== closed && element.tagName !== 'SUMMARY') return false;
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && getComputedStyle(element).visibility !== 'hidden';
    };
    const rect = element => {
      const box = element.getBoundingClientRect();
      return { x: box.x, y: box.y, width: box.width, height: box.height, right: box.right, bottom: box.bottom };
    };
    const background = element => {
      for (let node = element; node; node = node.parentElement) {
        const color = getComputedStyle(node).backgroundColor;
        if (color !== 'rgba(0, 0, 0, 0)' && color !== 'transparent') return color;
      }
      return 'transparent';
    };
    const main = rootNode.closest('.erp-layout__main');
    const header = document.querySelector('.erp-layout__header');
    const rail = document.querySelector('.erp-layout__sidebar');
    const boxes = [...rootNode.querySelectorAll('.summary-bar,.dossier-layout,.task-sidebar,.products-card,details.product-file,.file-content,.file-fields,.requirements-card,.activity-card')].filter(visible).map(element => ({ className: element.className, ...rect(element) }));
    const cards = [...rootNode.querySelectorAll('.summary-bar,.task-sidebar,.detail-card,details.product-file')].filter(visible).map(element => {
      const style = getComputedStyle(element);
      return { className: element.className, radius: style.borderRadius, background: background(element), ownBackground: style.backgroundColor,
        borders: ['Top', 'Right', 'Bottom', 'Left'].map(side => ({ side, width: style['border' + side + 'Width'], color: style['border' + side + 'Color'] })) };
    });
    const productBorders = [...rootNode.querySelectorAll('details.product-file')].map(element => {
      const borders = style => ['Top', 'Right', 'Bottom', 'Left'].map(side => ({ side, width: style['border' + side + 'Width'], color: style['border' + side + 'Color'] }));
      return { open: element.open, summary: borders(getComputedStyle(element.querySelector('summary'))),
        pseudoElements: ['::before', '::after'].map(pseudo => { const style = getComputedStyle(element, pseudo); return { pseudo, content: style.content, borders: borders(style) }; }) };
    });
    const heading = rootNode.querySelector('h1');
    const headingStyle = getComputedStyle(heading);
    const layout = rootNode.querySelector('.dossier-layout');
    const taskSidebar = rootNode.querySelector('.task-sidebar');
    const dossierMain = rootNode.querySelector('.dossier-main');
    const headingBox = rect(rootNode.querySelector('.detail-heading'));
    const summaryBox = rect(rootNode.querySelector('.summary-bar'));
    const productsBox = rect(rootNode.querySelector('.products-card'));
    const bottomBox = rect(rootNode.querySelector('.bottom-grid'));
    const layoutStyle = getComputedStyle(layout);
    const layoutMetrics = { columnGap: layoutStyle.columnGap, rowGap: layoutStyle.rowGap, leftWidth: rect(taskSidebar).width, betweenColumns: rect(dossierMain).x - rect(taskSidebar).right,
      headingToSummary: summaryBox.y - headingBox.bottom, summaryToDossier: rect(layout).y - summaryBox.bottom, productsToBottom: bottomBox.y - productsBox.bottom };
    const photos = [...rootNode.querySelectorAll('.product-photo')].filter(visible).map(element => rect(element));
    const tags = [...rootNode.querySelectorAll('.task-status,.status-tag,.detail-heading__title > span')].filter(element => visible(element) && /status-/.test(element.className)).map(element => ({ height: rect(element).height, radius: getComputedStyle(element).borderRadius, color: getComputedStyle(element).color }));
    const buttonHeights = [...rootNode.querySelectorAll('button')].filter(visible).map(element => ({ height: rect(element).height, className: element.className }));
    const clippedText = [...rootNode.querySelectorAll('.file-fields dd,.requirements-card dd,.activity-card p,.info-grid strong')].filter(visible).filter(element => element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1).map(element => ({ tag: element.tagName, className: element.className }));
    return { viewport: innerWidth, documentWidth: document.documentElement.scrollWidth, root: rect(rootNode), main: main ? { ...rect(main), clientWidth: main.clientWidth, scrollWidth: main.scrollWidth } : null,
      header: header ? rect(header) : null, rail: rail ? rect(rail) : null,
      boxes, cards, productBorders, tags, buttonHeights, clippedText, photos, layoutMetrics, pageBackground: background(rootNode),
      heading: { fontSize: headingStyle.fontSize, lineHeight: headingStyle.lineHeight } };
  });
  check(result.documentWidth <= width + 1, 'DOCUMENT_OVERFLOW', '整页出现横向溢出。');
  check(result.root.width >= width * 0.6 && result.root.right <= width + 1, 'CONTENT_COLLAPSED', '主内容实际宽度不足或被侧向裁切。');
  check(!result.main || result.main.scrollWidth <= result.main.clientWidth + 1, 'MAIN_OVERFLOW', '主内容区出现横向溢出。');
  for (const box of result.boxes) check(box.width > 50 && box.x >= result.root.x - 1 && box.right <= result.root.right + 1, 'BOX_OVERFLOW', '分区内容裁切或越过查看页边界：' + box.className);
  for (const button of result.buttonHeights) check(Math.abs(button.height - 32) < 1, 'BUTTON_HEIGHT', '查看页按钮高度不是 32px：' + button.className);
  check(result.tags.length > 0, 'STATUS_TAG_MISSING', '未找到当前任务状态标签。');
  for (const tag of result.tags) check(Math.abs(tag.height - 24) < 1 && tag.color === 'rgb(250, 249, 245)', 'TAG_STYLE', '状态标签高度或反白文字不符。');
  check(result.cards.length > 0, 'CARDS_MISSING', '未找到卡片边框。');
  for (const card of result.cards) {
    check(card.radius === '5px', 'CARD_RADIUS', '卡片圆角不是 5px：' + card.className);
    check(card.background === 'rgb(252, 251, 247)', 'CARD_BACKGROUND', '卡片表面色不符：' + card.className);
    for (const border of card.borders) check(border.width === '1px' && border.color === 'rgb(221, 214, 201)', 'CARD_BORDER', '卡片四边宽度或颜色不符：' + card.className + ' ' + border.side);
  }
  for (const product of result.productBorders) {
    for (const pseudo of product.pseudoElements) check(pseudo.borders.every(border => border.width === '0px'), 'PRODUCT_PSEUDO_BORDER', '产品档案伪元素重复绘制边框：' + pseudo.pseudo);
    for (const border of product.summary) {
      const separator = product.open && border.side === 'Bottom';
      check(border.width === (separator ? '1px' : '0px') && (!separator || border.color === 'rgb(221, 214, 201)'), 'PRODUCT_SUMMARY_BORDER', '产品标题仅允许展开时绘制底部分隔线：' + border.side);
    }
  }
  check(result.clippedText.length === 0, 'TEXT_CLIPPED', '字段或段落存在不可达的裁切。');
  check(result.heading.fontSize === '34px' && result.heading.lineHeight === '44px', 'TITLE_STYLE', '页面标题不符合 34/44px。');
  check(result.pageBackground === 'rgb(246, 243, 236)', 'PAGE_BACKGROUND', '查看页底色不符。');
  for (const key of ['headingToSummary', 'summaryToDossier', 'productsToBottom']) check(Math.abs(result.layoutMetrics[key] - 14) < 1, 'SECTION_GAP', '区块间距不是 14px：' + key);
  check(result.layoutMetrics.columnGap === '14px' && result.layoutMetrics.rowGap === '14px', 'DOSSIER_GAP', '任务资料与产品档案布局间距不是 14px。');
  if (width > 1100) check(Math.abs(result.layoutMetrics.leftWidth - 380) < 1 && Math.abs(result.layoutMetrics.betweenColumns - 14) < 1, 'DOSSIER_COLUMNS', '左侧资料栏不是 380px 或栏间距不符。');
  for (const photo of result.photos) check(Math.abs(photo.width - 118) < 1 && Math.abs(photo.height - 98) < 1, 'PRODUCT_PHOTO_SIZE', '产品展示图不是 118×98px。');
  if (width >= 1100) {
    check(result.header && Math.abs(result.header.height - 64) < 1, 'SHELL_HEADER', '现有壳层顶栏不是 64px。');
    check(result.rail && Math.abs(result.rail.width - 80) < 1, 'SHELL_RAIL', '现有壳层主栏不是 80px。');
  }
  return result;
}
async function screenshot(page, name) {
  const file = path.join(evidenceDir, name);
  await page.screenshot({ path: file, fullPage: true });
  report.screenshots.push(name);
}
async function loadPage(page, task) {
  await page.goto(new URL('/production-tasks/' + encodeURIComponent(task.id), base).href, { waitUntil: 'networkidle' });
  await page.locator('.task-detail-page h1').filter({ hasText: /^生产任务单$/ }).waitFor({ timeout: 20000 });
  await page.locator('.products-card').waitFor();
  await page.evaluate(() => document.fonts.ready);
  check(await page.locator('.load-error').count() === 0, 'DETAIL_LOAD', '真实详情加载失败。');
}
async function expandAndCheck(page, task) {
  const files = page.locator('details.product-file');
  const count = task.products.length;
  check(await page.locator('.products-heading p').count() === 0, 'PRODUCT_HINT_REMOVED', '产品档案标题下不应保留数量和展开提示文案。');
  for (const name of ['展开全部', '收起全部']) {
    check(await page.getByRole('button', { name, exact: true, includeHidden: true }).count() === 0, 'BULK_EXPANSION_REMOVED', '不应保留产品档案批量按钮：' + name);
  }
  check(await files.count() === count, 'PRODUCT_COUNT', '产品档案数量不符。');
  check(await files.locator('xpath=self::*[@open]').count() === (count ? 1 : 0), 'DEFAULT_OPEN', '默认必须只展开第一个产品。');
  let collapsedBorders = [];
  if (count) {
    check(await files.first().getAttribute('open') !== null, 'FIRST_OPEN', '默认展开的不是第一个产品。');
    for (let index = 1; index < count; index++) {
      await files.nth(index).locator('summary').click();
      check(await files.nth(index).getAttribute('open') !== null, 'PRODUCT_OPEN', '点击标题未展开第 ' + (index + 1) + ' 项产品。');
    }
    check(await page.locator('details.product-file[open]').count() === count, 'ALL_PRODUCTS_OPEN', '逐项点击后仍有产品未展开。');
    await checkFields(page, task);
    for (let index = 0; index < count; index++) {
      await files.nth(index).locator('summary').click();
      check(await files.nth(index).getAttribute('open') === null, 'PRODUCT_CLOSE', '点击标题未收起第 ' + (index + 1) + ' 项产品。');
    }
    check(await page.locator('details.product-file[open]').count() === 0, 'ALL_PRODUCTS_CLOSED', '逐项点击后仍有产品未收起。');
    collapsedBorders = (await measure(page, page.viewportSize().width)).productBorders;
    const summary = files.first().locator('summary');
    await summary.focus();
    await summary.press('Enter');
    check(await page.locator('details.product-file[open]').count() === 1, 'KEYBOARD_OPEN', 'Enter 未能单独展开产品。');
    await summary.press('Space');
    check(await page.locator('details.product-file[open]').count() === 0, 'KEYBOARD_CLOSE', 'Space 未能单独收起产品。');
    await summary.click();
    check(await files.first().getAttribute('open') !== null, 'SINGLE_OPEN', '单项展开失败。');
    for (let index = 1; index < count; index++) await files.nth(index).locator('summary').click();
    check(await page.locator('details.product-file[open]').count() === count, 'FINAL_PRODUCTS_OPEN', '后续测量前必须展开全部产品。');
  } else {
    check((await page.locator('.products-card').innerText()).includes('暂无产品'), 'EMPTY_PRODUCTS', '空产品档案没有明确说明。');
    await checkFields(page, task);
  }
  return collapsedBorders;
}
async function checkImagePreview(page) {
  const button = page.locator('.product-images button:not(:disabled)').first();
  if (await button.count() === 0) {
    report.notCovered.push('未覆盖主真实任务的图片预览；没有可用的产品图片按钮，未创建图片样例。');
    return { readOnly: true, status: 'NOT_COVERED' };
  }
  await button.click();
  const preview = page.locator('.product-image-preview-window');
  await preview.waitFor({ state: 'visible' });
  await page.waitForFunction(() => {
    const image = document.querySelector('.product-image-preview-window .product-image-stage img');
    return image && image.complete && image.naturalWidth > 0;
  });
  const naturalWidth = await preview.locator('.product-image-stage img').evaluate(image => image.naturalWidth);
  check(naturalWidth > 0, 'IMAGE_PREVIEW_LOAD', '产品图片预览未成功加载真实图片。');
  await screenshot(page, 'detail-1920-image-preview.png');
  await preview.locator('footer').getByRole('button', { name: '关闭', exact: true }).click();
  await preview.waitFor({ state: 'hidden' });
  check(report.blockedWrites.length === 0, 'IMAGE_PREVIEW_WRITE', '图片预览触发了业务写请求，已拦截。');
  return { readOnly: true, status: 'PASS', visible: true, naturalWidth, closed: true };
}
async function scrollToEnd(page) {
  await page.locator('.activity-card').scrollIntoViewIfNeeded();
  const result = await page.locator('.activity-card').evaluate(last => {
    const main = last.closest('.erp-layout__main');
    if (main) main.scrollTop = main.scrollHeight;
    const r = last.getBoundingClientRect();
    const boundary = main ? main.getBoundingClientRect().bottom : innerHeight;
    return { bottom: r.bottom, boundary, reachable: r.bottom <= boundary + 1, mainAtEnd: !main || main.scrollTop + main.clientHeight >= main.scrollHeight - 2 };
  });
  check(result.reachable && result.mainAtEnd, 'BOTTOM_UNREACHABLE', '末尾操作记录不能完整滚动到达。');
  return result;
}
async function main() {
  check(['http:', 'https:'].includes(base.protocol) && !base.username && !base.password, 'BASE_URL', '目标地址必须是没有内嵌凭据的 HTTP(S) 地址。');
  check(Boolean(statePath) || Boolean(username && password), 'AUTH_REQUIRED', '缺少认证前提：提供账号密码，或已有 Session 状态文件。');
  if (statePath) check(fs.existsSync(path.resolve(statePath)) && fs.statSync(path.resolve(statePath)).isFile(), 'STORAGE_STATE', '指定的 Session 状态文件不可读取。');
  check(!requestedId || /^[a-zA-Z0-9_-]+$/.test(requestedId), 'TASK_ID', '任务 ID 含非法字符。');
  fs.mkdirSync(evidenceDir, { recursive: true });
  check(safeSamePath(fs.realpathSync(evidenceDir), evidenceDir), 'EVIDENCE_LINK', '证据目录实际路径与登记路径不一致。');
  evidencePathVerified = true;
  check(!fs.existsSync(browserTemp), 'TEMP_EXISTS', 'browser_temp 已存在，归属未核实，拒绝覆盖或清理。');
  fs.mkdirSync(browserTemp);
  browserTempCreated = true;
  report.resources.created = true;
  process.env.TEMP = browserTemp; process.env.TMP = browserTemp; process.env.TMPDIR = browserTemp;
  const executable = process.env.TASK_DETAIL_QA_BROWSER_PATH || [
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
  ].find(candidate => fs.existsSync(candidate));
  check(Boolean(executable) && fs.existsSync(executable), 'BROWSER_MISSING', '缺少现成浏览器，请提供 TASK_DETAIL_QA_BROWSER_PATH；脚本不安装依赖。');
  browser = await chromium.launch({ headless: true, executablePath: executable, downloadsPath: browserTemp });
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, locale: 'zh-CN', timezoneId: 'Asia/Shanghai', serviceWorkers: 'block', ...(statePath ? { storageState: path.resolve(statePath) } : {}) });
  await context.route('**/*', async route => {
    const request = route.request();
    const method = request.method();
    const url = new URL(request.url());
    const permittedLogin = method === 'POST' && url.origin === base.origin && url.pathname === '/api/auth/login/';
    if (!['GET', 'HEAD'].includes(method) && !permittedLogin) {
      report.blockedWrites.push({ method, path: safePath(url.href) });
      await route.abort('blockedbyclient');
      return;
    }
    await route.continue();
  });
  const user = await authenticate(context);
  const list = await getJson(context, '/api/v1/production-tasks/?page=1&page_size=100', 'readable-task-list');
  check(Array.isArray(list.data), 'LIST_SHAPE', '生产任务列表契约不符。');
  report.discovery = { readableOnFirstPage: list.data.length, total: list.meta?.total ?? null, pages: list.meta?.total_pages ?? null };
  if ((list.meta?.total_pages || 1) > 1) report.notCovered.push('仅检查首 100 条可读记录，其他页的数据状态未枚举。');
  const candidates = list.data;
  const chosen = requestedId ? { id: requestedId } : candidates.find(task => (task.products || []).length > 1) || candidates[0];
  check(Boolean(chosen), 'NO_REAL_DATA', '没有可读取的真实任务；未创建演示数据。');
  const task = (await getJson(context, '/api/v1/production-tasks/' + encodeURIComponent(chosen.id) + '/', 'primary-task-detail')).data;
  check(Boolean(task?.id) && Array.isArray(task.products), 'DETAIL_SHAPE', '生产任务详情契约不符。');
  report.primary = { reference: taskRef(task), status: task.status, productCount: task.products.length };
  const page = await context.newPage();
  page.on('pageerror', error => report.pageErrors.push({ name: error.name, digest: hash(error.message) }));
  page.on('response', response => {
    if (response.status() >= 400 && new URL(response.url()).origin === base.origin) report.httpErrors.push({ status: response.status(), path: safePath(response.url()) });
  });
  for (const [width, height] of [[1920, 1080], [1440, 900], [1100, 850], [390, 844]]) {
    await page.setViewportSize({ width, height });
    await loadPage(page, task);
    await checkStatus(page, task, user);
    const baseline = await measure(page, width);
    await screenshot(page, 'detail-' + width + '-default.png');
    const collapsedBorders = await expandAndCheck(page, task);
    const expanded = await measure(page, width);
    const imagePreview = width === 1920 ? await checkImagePreview(page) : null;
    await page.locator('.summary-bar').scrollIntoViewIfNeeded();
    await screenshot(page, 'detail-' + width + '-expanded.png');
    const bottom = await scrollToEnd(page);
    await screenshot(page, 'detail-' + width + '-bottom.png');
    report.checks.push({ width, height, reference: taskRef(task), fieldMatch: true, baseline, collapsedBorders, expanded, imagePreview, bottom });
    check(report.blockedWrites.length === 0, 'BUSINESS_WRITE_BLOCKED', '验收期间检测到业务写请求，已拦截。');
  }
  const seen = new Set([task.id]);
  report.coverage.states.push(task.status);
  report.coverage.productCounts.push(task.products.length);
  const supplemental = [];
  for (const status of allStates) {
    const sample = candidates.find(item => item.status === status);
    if (sample && !seen.has(sample.id)) { supplemental.push(sample); seen.add(sample.id); }
  }
  for (const count of [0, 1]) {
    const sample = candidates.find(item => (item.products || []).length === count);
    if (sample && !seen.has(sample.id)) { supplemental.push(sample); seen.add(sample.id); }
  }
  await page.setViewportSize({ width: 1920, height: 1080 });
  for (const sample of supplemental) {
    const item = (await getJson(context, '/api/v1/production-tasks/' + encodeURIComponent(sample.id) + '/', 'supplemental-task-detail')).data;
    await loadPage(page, item);
    await checkStatus(page, item, user);
    const collapsedBorders = await expandAndCheck(page, item);
    const geometry = await measure(page, 1920);
    await screenshot(page, 'detail-state-' + item.status.toLowerCase() + '-' + taskRef(item) + '.png');
    report.coverage.states.push(item.status);
    report.coverage.productCounts.push(item.products.length);
    report.checks.push({ width: 1920, reference: taskRef(item), state: item.status, productCount: item.products.length, fieldMatch: true, collapsedBorders, geometry });
  }
  report.coverage.states = [...new Set(report.coverage.states)];
  report.coverage.productCounts = [...new Set(report.coverage.productCounts)];
  for (const state of allStates) if (!report.coverage.states.includes(state)) report.notCovered.push('未覆盖真实状态：' + labels[state] + '；可读样本中没有该状态，未造数据。');
  if (!report.coverage.productCounts.includes(1)) report.notCovered.push('未覆盖真实单产品任务；未创建样例。');
  if (!report.coverage.productCounts.some(count => count > 1)) report.notCovered.push('未覆盖真实多产品任务；本次读取的真实任务没有多产品档案，未创建样例。');
  if (!report.coverage.productCounts.includes(0)) report.notCovered.push('未覆盖真实空产品档案；未创建样例。');
  report.notCovered.push('真实未登录/无权限账号、真实网络失败与重试未构造；本次只使用授权会话，不伪造响应。');
  check(report.blockedWrites.length === 0, 'BUSINESS_WRITE_BLOCKED', '验收期间检测到业务写请求，已拦截。');
  check(report.pageErrors.length === 0, 'PAGE_ERRORS', '页面发生 JavaScript 错误；报告仅保存错误摘要哈希。');
  check(report.httpErrors.length === 0, 'HTTP_ERRORS', '页面真实请求出现 HTTP 错误；报告仅保存状态码及脱敏路径。');
  report.status = report.notCovered.length ? 'PASS_WITH_GAPS' : 'PASS';
}
(async () => {
  try { await main(); }
  catch (error) {
    report.status = error.safeQaMessage && ['AUTH_REQUIRED', 'STORAGE_STATE', 'SESSION_EXPIRED', 'LOGIN_REJECTED', 'LOGIN_NO_SESSION', 'BROWSER_MISSING', 'TEMP_EXISTS', 'NO_REAL_DATA'].includes(error.code) ? 'BLOCKED' : 'FAIL';
    report.failure = { code: error.safeQaMessage ? error.code : 'UNEXPECTED', message: error.safeQaMessage ? error.message : '执行异常；未保存可能包含凭据或业务内容的原始异常。' };
    process.exitCode = 1;
  } finally {
    let mayRemove = !browser;
    if (browser) {
      try { await browser.close(); report.resources.browserClosed = true; mayRemove = true; }
      catch { report.resources.closeFailed = true; report.status = 'FAIL'; process.exitCode = 1; }
    }
    for (const key of Object.keys(oldTemp)) {
      if (oldTemp[key] === undefined) delete process.env[key]; else process.env[key] = oldTemp[key];
    }
    if (browserTempCreated && mayRemove) {
      try {
        check(safeSamePath(path.dirname(browserTemp), evidenceDir) && safeSamePath(fs.realpathSync(browserTemp), browserTemp) && !fs.lstatSync(browserTemp).isSymbolicLink(), 'CLEANUP_BOUNDARY', '临时路径边界或归属核对失败。');
        fs.rmSync(browserTemp, { recursive: true, force: false });
        report.resources.removed = true;
        report.resources.verifiedAbsent = !fs.existsSync(browserTemp);
        check(report.resources.verifiedAbsent, 'CLEANUP_REMAINS', '临时浏览器目录仍存在。');
      } catch { report.resources.cleanupFailed = true; report.status = 'FAIL'; process.exitCode = 1; }
    } else if (!browserTempCreated) report.resources.verifiedAbsent = !fs.existsSync(browserTemp);
    report.finishedAt = new Date().toISOString();
    if (evidencePathVerified) fs.writeFileSync(path.join(evidenceDir, 'readonly-report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ status: report.status, checks: report.checks.length, blockedWrites: report.blockedWrites.length, gaps: report.notCovered.length, report: evidencePathVerified ? path.join(evidenceDir, 'readonly-report.json') : null, failure: report.failure, cleanup: report.resources.verifiedAbsent }));
  }
})();


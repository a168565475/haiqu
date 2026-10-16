/**
 * 原料管理：真实 Session/API 的只读桌面验收。
 * 只允许脚本通过普通登录取得 Session；页面发出的所有写请求均拦截并判失败。
 * 不保存凭据、Cookie、完整业务响应；不提交行内草稿，不修改喷塑状态。
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('../src/frontend/node_modules/playwright-core');

const root = path.resolve(__dirname, '..');
const evidenceDir = path.join(root, 'output/playwright/material-catalog-20261016');
const stamp = new Date().toISOString().replace(/[:.]/g, '-');
const browserTemp = path.join(root, '.tmp/material-catalog', `readonly-browser-${stamp}-${process.pid}`);
const reportPath = path.join(evidenceDir, `readonly-report-${stamp}.json`);
const username = process.env.MATERIAL_CATALOG_QA_USERNAME;
const password = process.env.MATERIAL_CATALOG_QA_PASSWORD;
const statePath = process.env.MATERIAL_CATALOG_QA_STORAGE_STATE;
const visualBaselinePath = process.env.MATERIAL_CATALOG_QA_VISUAL_BASELINE;
const apiPrefix = '/api/v1/material-catalog/';
const viewports = [[1673, 941], [1920, 1080], [1440, 900]];
const report = {
  schemaVersion: 1, startedAt: new Date().toISOString(), status: 'RUNNING', mode: 'real-api-read-only',
  apiReads: [], checks: [], screenshots: [], blockedWrites: [], pageErrors: [], httpErrors: [], notCovered: [],
  resources: { browserTemp, created: false, browserClosed: false, removed: false, verifiedAbsent: false },
};
const snapshots = new Map();
const previousTemp = { TEMP: process.env.TEMP, TMP: process.env.TMP, TMPDIR: process.env.TMPDIR };
let base, browser, page, visualBaseline, catalogOptions, ownsTemp = false, evidenceVerified = false, stage = 'preconditions';

function stop(code, message, blocked = false) { const error = new Error(message); Object.assign(error, { code, safeQaMessage: true, blocked }); throw error; }
function check(condition, code, message) { if (!condition) stop(code, message); }
function digest(value) { return crypto.createHash('sha256').update(String(value)).digest('hex').slice(0, 16); }
function samePath(left, right) { const normalize = value => process.platform === 'win32' ? path.resolve(value).toLowerCase() : path.resolve(value); return normalize(left) === normalize(right); }
function safePath(url) { return new URL(url, base).pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, ':id'); }
function note(message) { if (!report.notCovered.includes(message)) report.notCovered.push(message); }
function record(id, evidence = {}) { report.checks.push({ id, ...evidence }); }
function saveReport() { if (evidenceVerified) fs.writeFileSync(reportPath, JSON.stringify(report, null, 2)); }

function checkFixedFields(options) {
  // 期望来自已确认需求，不能从被测 options 反推，避免接口与页面同时漏字段时误过。
  const expectedBase = [
    ['HARDWARE', 'flow_unit', '流转单位'], ['FABRIC_SEMI', 'width', '门幅'],
    ['CARTON', 'box_type', '箱子形状'], ['BAG', 'box_type', '箱子形状'], ['PACKAGING_GENERAL', 'box_type', '箱子形状'],
    ['CARTON', 'model', '型号'], ['BAG', 'model', '型号'], ['PACKAGING_GENERAL', 'model', '型号'],
    ['PLASTIC', 'specification', '规格描述'], ['FABRIC_SEMI', 'specification', '规格描述'],
    ['TAPE', 'specification', '规格描述'], ['COTTON', 'specification', '规格描述'],
  ];
  const templates = options.categories.flatMap(category => category.templates);
  for (const [templateKey, key, label] of expectedBase) {
    const template = templates.find(item => item.key === templateKey);
    check(Array.isArray(template?.fields), 'FIXED_BASE_FIELD_CONTRACT', `${templateKey} 缺少 BASE 固定字段定义。`);
    const matches = template.fields.filter(field => field?.key === key);
    check(matches.length === 1 && matches[0].label === label && matches[0].kind === 'text', 'FIXED_BASE_FIELD_CONTRACT', `${templateKey} 的 BASE/${key} 必须唯一、名称为“${label}”、类型为 text。`);
  }
  const expectedSpray = [['color', '颜色', 'text'], ['length', '长度', 'text'], ['unit', '可用单位', 'unit']];
  check(options.spray_fields.length === expectedSpray.length, 'FIXED_SPRAY_FIELD_CONTRACT', 'SPRAY 只能包含颜色、长度和可用单位三个固定字段。');
  for (const [key, label, kind] of expectedSpray) {
    const matches = options.spray_fields.filter(field => field?.key === key);
    check(matches.length === 1 && matches[0].label === label && matches[0].kind === kind, 'FIXED_SPRAY_FIELD_CONTRACT', `SPRAY/${key} 必须唯一、名称为“${label}”、类型为 ${kind}。`);
  }
  record('confirmed-field-definitions', { baseFields: expectedBase.length, sprayFields: expectedSpray.length });
}

async function readApi(context, route, kind) {
  let response;
  try { response = await context.request.get(new URL(route, base).href, { maxRedirects: 0 }); }
  catch { stop('API_UNREACHABLE', `${kind} 请求不可达；未保存请求细节。`, true); }
  report.apiReads.push({ kind, status: response.status() });
  if ([401, 403].includes(response.status())) stop('API_PERMISSION', `${kind} 缺少有效 Session 或读取权限。`, true);
  if (response.status() === 404) stop('API_NOT_READY', `${kind} 路由未上线或记录已不可访问。`, true);
  check(response.status() === 200, 'API_STATUS', `${kind} 未返回 200。`);
  let body;
  try { body = await response.json(); } catch { stop('API_JSON', `${kind} 没有返回有效 JSON。`); }
  return { body, etag: response.headers().etag || '' };
}

async function authenticate(context) {
  let me = (await readApi(context, '/api/auth/me/', 'session-state')).body;
  if (statePath) {
    if (!me.authenticated) stop('SESSION_EXPIRED', '提供的 Session 已失效，请通过正常登录更新。', true);
    report.authentication = 'provided-session';
  } else {
    const csrf = (await context.cookies(base.origin)).find(cookie => cookie.name === 'csrftoken')?.value;
    check(Boolean(csrf), 'CSRF_MISSING', '普通登录前没有取得 CSRF Cookie。');
    let response;
    try {
      response = await context.request.post(new URL('/api/auth/login/', base).href, {
        data: { username, password }, headers: { 'X-CSRFToken': csrf, Referer: base.origin + '/' }, maxRedirects: 0,
      });
    } catch { stop('LOGIN_REQUEST', '普通登录请求失败；未保存凭据。', true); }
    if (response.status() !== 200) stop('LOGIN_REJECTED', '普通登录未成功，请核对真实账号状态。', true);
    me = (await readApi(context, '/api/auth/me/', 'authenticated-state')).body;
    if (!me.authenticated) stop('SESSION_MISSING', '普通登录后没有有效 Session。', true);
    report.authentication = 'normal-session-csrf-login';
  }
  if (!(me.user?.permissions || []).includes('material_catalog.view_materialcatalog')) stop('VIEW_PERMISSION', '真实账号没有原料管理读取权限。', true);
  return me.user;
}

async function screenshot(name) {
  const filename = `${stamp}-${name}.png`;
  await page.screenshot({ path: path.join(evidenceDir, filename), fullPage: true });
  report.screenshots.push(filename);
}

async function openPage() {
  await page.goto(new URL('/material-catalog', base).href, { waitUntil: 'networkidle' });
  if (await page.locator('.material-catalog-page').count() !== 1) stop('PAGE_NOT_READY', '原料管理页面未上线或当前会话无法进入。', true);
  await page.getByRole('combobox', { name: '原料类别', exact: true }).waitFor();
  await page.evaluate(() => document.fonts.ready);
}

function selectRoot(trigger) { return trigger.locator('xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), " material-catalog-select ")][1]'); }
function selectPanel() { return page.locator('.material-catalog-select-popper.el-popper:visible'); }
async function openSelect(trigger) {
  if (await trigger.getAttribute('aria-expanded') !== 'true') await selectRoot(trigger).locator('.el-select__wrapper').click();
  await selectPanel().waitFor();
  check(await selectPanel().count() === 1, 'SELECT_SINGLE_PANEL', '下拉应只有一个可见选项面板。');
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.waitForFunction(node => node.getAnimations({ subtree: true }).every(animation => animation.playState !== 'running'), await selectPanel().elementHandle());
}
async function selectValue(trigger, value) {
  if (await selectRoot(trigger).getAttribute('data-model-value') === '') {
    const color = await selectRoot(trigger).locator('.el-select__placeholder').evaluate(node => getComputedStyle(node).color);
    check(color === 'rgb(150, 143, 132)', 'SELECT_EMPTY_PLACEHOLDER', '空选择器应使用 #968F84 占位文字。');
    record('select-empty-placeholder', { label: await trigger.getAttribute('aria-label'), color });
  }
  await openSelect(trigger);
  await selectPanel().locator(`[role="option"][data-value="${value}"]`).click();
  await selectPanel().waitFor({ state: 'hidden' });
  check(await selectRoot(trigger).getAttribute('data-model-value') === value, 'SELECT_VALUE', '选择后控件真实值未更新。');
}

async function checkDropdown(trigger, expected, width, height, kind) {
  const root = selectRoot(trigger);
  await trigger.evaluate(node => node.scrollIntoView({ block: 'end', inline: 'nearest' }));
  const before = await page.locator('.material-catalog-page').boundingBox();
  await openSelect(trigger); await page.mouse.move(0, 0);
  const panel = selectPanel();
  const actual = await panel.locator('[role="option"]').evaluateAll(items => items.map(item => ({ value: item.dataset.value, label: item.textContent.trim() })));
  check(actual.length === expected.length && actual.every(item => expected.some(option => option.value === item.value && option.label === item.label)), 'SELECT_REAL_OPTIONS', `${kind} 面板选项与真实 API 不一致。`);
  const measurement = await panel.evaluate(node => {
    const style = item => { const css = getComputedStyle(item), box = item.getBoundingClientRect(); return { x: box.x, y: box.y, right: box.right, bottom: box.bottom, width: box.width, height: box.height, background: css.backgroundColor, color: css.color, radius: css.borderRadius, shadow: css.boxShadow, overflow: css.overflow, borders: ['Top', 'Right', 'Bottom', 'Left'].map(side => ({ width: css[`border${side}Width`], color: css[`border${side}Color`], style: css[`border${side}Style`] })) }; };
    const wrap = node.querySelector('.el-select-dropdown__wrap');
    const rect = node.getBoundingClientRect();
    return { ...style(node), placement: node.getAttribute('data-popper-placement'), layers: [...node.querySelectorAll('.el-select-dropdown')].map(style), wrap: { clientHeight: wrap.clientHeight, scrollHeight: wrap.scrollHeight, maxHeight: getComputedStyle(wrap).maxHeight, overflowY: getComputedStyle(wrap).overflowY }, items: [...node.querySelectorAll('[role="option"]')].map(item => ({ ...style(item), selected: item.getAttribute('aria-selected') === 'true', disabled: item.getAttribute('aria-disabled') === 'true', checked: Boolean(item.querySelector('.material-catalog-select-check')?.getClientRects().length) })), unclipped: [[rect.left + 3, rect.top + 3], [rect.right - 3, rect.top + 3], [rect.left + 3, rect.bottom - 3], [rect.right - 3, rect.bottom - 3]].every(([x, y]) => node.contains(document.elementFromPoint(x, y))) };
  });
  const triggerBox = await root.locator('.el-select__wrapper').boundingBox(), after = await page.locator('.material-catalog-page').boundingBox();
  const triggerLabelColor = await root.locator('.el-select__placeholder').evaluate(node => getComputedStyle(node).color);
  report.failedDropdown = { width, height, kind, measurement, triggerBox, triggerLabelColor };
  await screenshot(`${width}-dropdown-${kind}`);
  check(triggerLabelColor === 'rgb(31, 29, 24)', 'SELECT_VALUE_TEXT', `${kind} 展开时已有值应保留 #1F1D18，不应使用占位灰。`);
  check(measurement.background === 'rgb(252, 251, 247)' && measurement.radius === '5px' && measurement.borders.every(item => item.width === '1px' && item.style === 'solid' && item.color === 'rgb(221, 214, 201)'), 'SELECT_PANEL_STYLE', `${kind} 面板底色、四边或圆角不符。`);
  check(measurement.shadow === 'none' && measurement.overflow === 'hidden' && measurement.layers.every(item => item.shadow === 'none' && item.borders.every(border => border.width === '0px')), 'SELECT_SINGLE_BORDER_OWNER', `${kind} 面板只能由外层绘制一圈边框，首末行背景应受5px圆角裁切。`);
  check(measurement.items.every(item => Math.abs(item.height - 32) < 1) && measurement.wrap.clientHeight <= 240 && parseFloat(measurement.wrap.maxHeight) <= 240 && measurement.wrap.overflowY === 'auto', 'SELECT_OPTION_ROWS', `${kind} 选项应为32px，列表最高240px并内部滚动。`);
  check(triggerBox && measurement.width >= triggerBox.width - 1 && measurement.x >= 0 && measurement.right <= width + 1 && measurement.y >= 0 && measurement.bottom <= height + 1 && measurement.unclipped && JSON.stringify(before) === JSON.stringify(after), 'SELECT_PANEL_BOUNDS', `${kind} 面板宽度、视口避让或浮层裁切不符，或推挤了正文。`);
  check(measurement.items.filter(item => item.selected).length === 1 && measurement.items.filter(item => item.selected).every(item => item.background === 'rgb(255, 244, 230)' && item.color === 'rgb(200, 78, 40)' && item.checked), 'SELECT_SELECTED_STYLE', `${kind} 应有唯一选中项，需浅橙底、品牌字色和勾。`);
  check(measurement.items.filter(item => !item.selected && !item.disabled).every(item => item.color === 'rgb(31, 29, 24)'), 'SELECT_OPTION_TEXT', `${kind} 普通选项文字应为 #1F1D18。`);
  check(measurement.placement?.startsWith('top') ? measurement.bottom <= triggerBox.y + 1 : measurement.placement?.startsWith('bottom') && measurement.y >= triggerBox.y + triggerBox.height - 1, 'SELECT_PLACEMENT', `${kind} 弹层应位于触发框上方或下方，不遮住触发框。`);
  const ordinary = panel.locator('[role="option"]:not([aria-selected="true"]):not([aria-disabled="true"])').first();
  if (await ordinary.count()) {
    await ordinary.hover();
    check(await ordinary.evaluate(node => getComputedStyle(node).backgroundColor) === 'rgb(255, 246, 234)', 'SELECT_HOVER', `${kind} 普通选项悬停颜色不符。`);
  }
  const selected = panel.locator('[role="option"][aria-selected="true"]').first();
  if (await selected.count()) {
    await selected.hover();
    check(await selected.evaluate(node => getComputedStyle(node).backgroundColor) === 'rgb(255, 244, 230)', 'SELECT_SELECTED_HOVER', `${kind} 选中项悬停不应覆盖选中底色。`);
  }
  await page.mouse.move(0, 0);
  const valueBefore = await root.getAttribute('data-model-value');
  await trigger.press('ArrowDown');
  check(await root.getAttribute('data-model-value') === valueBefore && await trigger.getAttribute('aria-expanded') === 'true', 'SELECT_ARROW_NO_COMMIT', `${kind} 方向键不应直接修改值或关闭面板。`);
  const active = panel.locator('[role="option"].is-hovering');
  check(await active.count() === 1 && await active.getAttribute('aria-disabled') !== 'true', 'SELECT_KEYBOARD_ACTIVE', `${kind} 方向键未移动到可选活动项。`);
  const downValue = await active.getAttribute('data-value');
  await trigger.press('ArrowUp');
  check(await root.getAttribute('data-model-value') === valueBefore && await active.count() === 1 && await active.getAttribute('data-value') !== downValue && await active.getAttribute('aria-disabled') !== 'true', 'SELECT_ARROW_UP_NO_COMMIT', `${kind} 上方向键应只移动活动项，不应改值。`);
  await trigger.press('ArrowDown');
  const activeValue = await active.getAttribute('data-value');
  const activeColor = await active.evaluate(node => getComputedStyle(node).backgroundColor);
  check(await root.getAttribute('data-model-value') === valueBefore && activeColor === (await active.getAttribute('aria-selected') === 'true' ? 'rgb(255, 244, 230)' : 'rgb(255, 246, 234)'), 'SELECT_KEYBOARD_COLOR', `${kind} 键盘活动项应使用规定的活动色，选中项保留选中色。`);
  await trigger.press('Enter'); await selectPanel().waitFor({ state: 'hidden' });
  check(await root.getAttribute('data-model-value') === activeValue, 'SELECT_ENTER', `${kind} Enter 未确认活动选项。`);
  for (const key of ['Escape', 'Tab']) {
    await openSelect(trigger); await trigger.press(key); await selectPanel().waitFor({ state: 'hidden' });
    check(await root.getAttribute('data-model-value') === activeValue, 'SELECT_DISMISS', `${kind} ${key} 关闭时意外改值。`);
  }
  check(report.blockedWrites.length === 0, 'SELECT_BUSINESS_WRITE', `${kind} 仅选草稿却触发业务写请求。`);
  record('dropdown-real-panel', { width, height, kind, optionCount: actual.length, triggerLabelColor, activeColor, keyboard: ['ArrowDown', 'ArrowUp', 'ArrowDown', 'Enter', 'Escape', 'Tab'], measurement });
  delete report.failedDropdown;
}

async function chooseCategory(key) {
  const selector = page.getByRole('combobox', { name: '原料类别', exact: true });
  if (await selectRoot(selector).getAttribute('data-model-value') === key) return;
  const response = page.waitForResponse(item => {
    const url = new URL(item.url());
    return url.pathname === apiPrefix && url.searchParams.get('category') === key && item.request().method() === 'GET';
  });
  await selectValue(selector, key);
  check((await response).status() === 200, 'CATEGORY_REQUEST', '分类切换未返回真实列表。');
  await page.waitForFunction(() => !document.querySelector('.catalog-sidebar [aria-busy="true"]'));
}

async function chooseDetail(detail) {
  await chooseCategory(detail.category_key);
  const search = page.getByLabel('搜索品名', { exact: true });
  if (await search.inputValue() !== detail.name) {
    const response = page.waitForResponse(item => {
      const url = new URL(item.url());
      return url.pathname === apiPrefix && url.searchParams.get('q') === detail.name && item.request().method() === 'GET';
    });
    await search.fill(detail.name);
    check((await response).status() === 200, 'SEARCH_REQUEST', '搜索未返回真实列表。');
  }
  const item = page.locator(`[data-testid="material-names"] [data-catalog-id="${detail.id}"]`);
  await item.waitFor();
  await item.click();
  await page.locator(`.catalog-detail[data-catalog-id="${detail.id}"]`).waitFor();
  await page.waitForFunction(() => document.querySelector('.catalog-detail')?.getAttribute('aria-busy') !== 'true');
}

async function checkDetail(detail, options) {
  const template = options.categories.flatMap(category => category.templates).find(item => item.key === detail.template_key);
  check(Boolean(template), 'TEMPLATE_CONTRACT', '真实详情引用了未定义的模板。');
  const rows = [];
  const expected = [...template.fields.map(field => ({ scope: 'BASE', field })), ...(detail.spray_enabled ? options.spray_fields.map(field => ({ scope: 'SPRAY', field })) : [])];
  for (const { scope, field } of expected) {
    const parents = field.kind === 'dimension' ? detail.values.filter(value => value.scope === 'BASE' && value.field_key === 'shape').map(value => value.id) : [''];
    if (!parents.length) { note('缺少真实截面形状时，截面尺寸分组展示未覆盖。'); continue; }
    for (const parent of parents) {
      const row = page.locator(`[data-field="${scope}:${field.key}:${parent}"]`);
      check(await row.count() === 1, 'FIELD_MISSING', `详情缺少固定属性行：${scope}/${field.key}。`);
      if (field.kind === 'shape') {
        const group = row.locator('xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), " section-group ")]');
        check(JSON.stringify(await group.locator('.section-labels > span').allTextContents()) === JSON.stringify(['截面形状', '截面尺寸']), 'SHAPE_SEPARATE_LABELS', '截面形状与截面尺寸应分别显示，不能合并成一个标题。');
        check(!await row.locator('.attribute-label').isVisible(), 'SHAPE_DUPLICATE_LABEL', '右侧添加形状区域不应重复显示属性标题。');
        const expectedShapes = detail.values.filter(value => value.scope === scope && value.field_key === field.key);
        const actualShapes = await page.locator('.shape-dimensions [data-shape-id]').evaluateAll(items => items.map(item => {
          const label = item.querySelector('.shape-label')?.cloneNode(true);
          label?.querySelectorAll('button').forEach(button => button.remove());
          return { id: item.getAttribute('data-shape-id'), value: label?.textContent.trim() };
        }));
        check(actualShapes.length === expectedShapes.length && actualShapes.every(actual => expectedShapes.some(expectedShape => expectedShape.id === actual.id && expectedShape.value === actual.value)), 'SHAPE_GROUPS', '真实截面形状没有按左标签与右尺寸分组完整展示。');
        check(await row.locator('.option-chip').count() === 0, 'DUPLICATE_SHAPE_CHIPS', '形状在分组标题下又重复展示成属性值条目。');
        rows.push({ scope, field: field.key, parentPresent: false, count: actualShapes.length, display: 'dimension-group-label' });
        continue;
      }
      const values = field.kind === 'unit' ? detail.units.filter(unit => unit.scope === scope).map(unit => unit.unit_name) : detail.values.filter(value => value.scope === scope && value.field_key === field.key && (value.parent_id || '') === parent).map(value => value.value);
      const actual = await row.locator('.option-label').allTextContents();
      check(JSON.stringify([...actual].sort()) === JSON.stringify([...values].sort()), 'VALUES_MISMATCH', `真实 API 与属性显示不一致：${scope}/${field.key}。`);
      rows.push({ scope, field: field.key, parentPresent: Boolean(parent), count: actual.length });
    }
  }
  const spray = page.getByTestId('spray-enabled');
  check(await spray.count() === (template.supports_spray ? 1 : 0), 'SPRAY_VISIBILITY', '喷塑入口与模板支持范围不一致。');
  if (template.supports_spray) check(await spray.isChecked() === detail.spray_enabled, 'SPRAY_STATE', '喷塑勾选与真实 API 不一致。');
  record('detail-fields', { reference: digest(detail.id), template: detail.template_key, sprayEnabled: detail.spray_enabled, rows });
}

async function measure(width, height, state) {
  await page.mouse.move(0, 0); // 普通布局态与独立的 hover 验证分开，避免刚点击的品名仍处于悬停态。
  const measurement = await page.locator('.material-catalog-page').evaluate(element => {
    const rect = node => { const box = node.getBoundingClientRect(); return { x: box.x, y: box.y, width: box.width, height: box.height, right: box.right, bottom: box.bottom }; };
    const visible = node => node.getClientRects().length > 0 && getComputedStyle(node).visibility !== 'hidden';
    const styles = node => { const css = getComputedStyle(node); return { ...rect(node), fontFamily: css.fontFamily, fontSize: css.fontSize, fontWeight: css.fontWeight, lineHeight: css.lineHeight, color: css.color, background: css.backgroundColor, radius: css.borderRadius, padding: css.padding, margin: css.margin, minHeight: css.minHeight, opacity: css.opacity, gap: css.gap, textAlign: css.textAlign, justifyContent: css.justifyContent, overflowX: css.overflowX, overflowY: css.overflowY, shadow: css.boxShadow, borders: ['Top', 'Right', 'Bottom', 'Left'].map(side => ({ side, width: css[`border${side}Width`], color: css[`border${side}Color`], style: css[`border${side}Style`] })), pseudo: ['::before', '::after'].map(pseudo => { const rule = getComputedStyle(node, pseudo); return { pseudo, content: rule.content, display: rule.display, width: rule.width, border: rule.borderWidth, topWidth: rule.borderTopWidth, topStyle: rule.borderTopStyle, topColor: rule.borderTopColor, shadow: rule.boxShadow }; }) }; };
    const sidebar = element.querySelector('.catalog-sidebar'), detail = element.querySelector('.catalog-detail');
    const controls = [...element.querySelectorAll('button:not([data-catalog-id]),input:not([type="checkbox"]):not(.el-select__input),select,.el-input__wrapper,.el-select__wrapper')].filter(visible).map(node => ({ tag: node.tagName, className: node.className, action: node.dataset.action || node.dataset.testid || null, isSelect: node.matches('.el-select__wrapper'), disabled: node.disabled === true || node.classList.contains('is-disabled'), readOnly: node.readOnly === true, invalid: node.getAttribute('aria-invalid') === 'true' || node.closest('.material-catalog-select')?.classList.contains('is-invalid') === true, focused: node === document.activeElement || (node.matches('.el-select__wrapper') && node.contains(document.activeElement)), placeholderColor: node.hasAttribute('placeholder') ? getComputedStyle(node, '::placeholder').color : null, hovered: node.matches(':hover'), expectedHeight: 32, ...styles(node) }));
    const names = [...element.querySelectorAll('[data-testid="material-names"] [data-catalog-id]')].map(node => ({ selected: node.classList.contains('selected'), ...styles(node) }));
    const heads = [...element.querySelectorAll('h1,h2,h3')].map(node => ({ tag: node.tagName, text: node.textContent.trim(), ...styles(node) }));
    const chips = [...element.querySelectorAll('.option-chip')].map(styles);
    const labels = [...element.querySelectorAll('.attribute-label')].filter(node => visible(node) && !node.closest('.shape-dimensions')).map(styles);
    const rows = [...element.querySelectorAll('.attribute-row')].filter(visible).map(styles);
    const shapeLabels = [...element.querySelectorAll('.shape-dimensions .attribute-label')].filter(visible).map(styles);
    const groups = [...element.querySelectorAll('.section-group')].map(node => ({ margin: getComputedStyle(node).margin, labels: styles(node.querySelector('.section-labels')), leaders: [...node.querySelectorAll('.section-labels > span')].map(styles), dimensions: styles(node.querySelector('.shape-dimensions')), heading: styles(node.querySelector('.shape-heading')), headingVisible: visible(node.querySelector('.shape-heading')), shapeRows: [...node.querySelectorAll('[data-shape-id]')].map(rect), firstShapeLabel: node.querySelector('.shape-label') ? rect(node.querySelector('.shape-label')) : null }));
    const optionLines = [...element.querySelectorAll('.option-line')].filter(visible).map(node => ({ gap: getComputedStyle(node).gap, wrap: getComputedStyle(node).flexWrap }));
    const scrollState = node => ({ className: node.className, clientHeight: node.clientHeight, scrollHeight: node.scrollHeight, clientWidth: node.clientWidth, scrollWidth: node.scrollWidth, overflowY: getComputedStyle(node).overflowY });
    const scrolls = [element, sidebar, detail, element.querySelector('.material-names')].filter(Boolean).map(scrollState);
    const parentScrolls = [...new Set([element.parentElement, element.closest('#erp-main-content')])].filter(Boolean).map(scrollState);
    // 与修改前基线采用同一结构；不保存外部导航文本、用户信息或 HTML。
    const shellStyle = node => { const css = getComputedStyle(node), box = node.getBoundingClientRect(); return { fontFamily: css.fontFamily, fontSize: css.fontSize, fontWeight: css.fontWeight, lineHeight: css.lineHeight, color: css.color, background: css.backgroundColor, border: css.border, borderRadius: css.borderRadius, padding: css.padding, margin: css.margin, display: css.display, x: box.x, y: box.y, width: box.width, height: box.height }; };
    const outer = ['.erp-layout__sidebar', '.erp-layout__header'].map(selector => { const node = document.querySelector(selector); if (!node) return { selector, missing: true }; const nodes = [node, ...node.querySelectorAll('*')]; return { selector, root: shellStyle(node), dom: nodes.map(item => ({ tag: item.tagName, className: typeof item.className === 'string' ? item.className : item.getAttribute('class'), role: item.getAttribute('role'), childCount: item.children.length })), styles: nodes.map(shellStyle) }; });
    return { viewport: [innerWidth, innerHeight], bodyFontFamily: getComputedStyle(document.body).fontFamily, main: element.closest('#erp-main-content') ? rect(element.closest('#erp-main-content')) : null, page: styles(element), sidebar: sidebar ? styles(sidebar) : null, detail: detail ? styles(detail) : null, controls, names, heads, chips, labels, shapeLabels, rows, groups, optionLines, outer, scrolls, parentScrolls, documentOverflow: document.documentElement.scrollWidth > innerWidth + 1, documentVerticalOverflow: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight) > innerHeight + 1, globalSave: [...element.querySelectorAll('button')].some(node => visible(node) && node.textContent.trim() === '保存' && !node.closest('.inline-editor') && node.dataset.testid !== 'save-name') };
  });
  for (const item of measurement.outer) {
    check(!item.missing, 'OUTER_NAVIGATION_MISSING', '现有外部导航或顶栏不存在。');
    item.domDigest = crypto.createHash('sha256').update(JSON.stringify(item.dom)).digest('hex');
    item.styleDigest = crypto.createHash('sha256').update(JSON.stringify(item.styles)).digest('hex');
    item.nodeCount = item.dom.length; delete item.dom; delete item.styles;
  }
  report.failedMeasurement = { width, height, state, measurement };
  if (visualBaseline) {
    const expected = visualBaseline.viewports.find(item => JSON.stringify(item.viewport) === JSON.stringify([width, height]));
    check(measurement.bodyFontFamily === expected.bodyFontFamily, 'FONT_BASELINE_CHANGED', '全局字体族与修改前基线不一致。');
    check(measurement.outer.every(item => { const before = expected.outer.find(value => value.selector === item.selector); return before.domDigest === item.domDigest && before.styleDigest === item.styleDigest; }), 'OUTER_NAVIGATION_CHANGED', '外部导航或顶栏的 DOM、几何或计算样式与修改前基线不一致。');
  }
  check(await page.locator('.material-catalog-page select').count() === 0, 'NATIVE_SELECT_REMAINS', '原料管理不应残留原生下拉。');
  const borderIs = (node, color) => node.borders.every(border => border.width === '1px' && border.style === 'solid' && border.color === color);
  const noPseudoBorder = node => node.pseudo.every(pseudo => ['none', 'normal'].includes(pseudo.content) || (pseudo.border.split(' ').every(value => value === '0px') && pseudo.shadow === 'none'));
  check(JSON.stringify(measurement.viewport) === JSON.stringify([width, height]), 'VIEWPORT', '浏览器实际视口与目标不符。');
  check(measurement.sidebar && Math.abs(measurement.sidebar.width - 240) < 1, 'SIDEBAR_WIDTH', '桌面品名卡片应为 240px。');
  // 外层 PageContainer 已提供 14px；核对最终几何，避免把留白的实现层级当作视觉要求。
  check(measurement.main && [measurement.sidebar.x - measurement.main.x, measurement.sidebar.y - measurement.main.y, measurement.main.right - measurement.detail.right, measurement.main.bottom - measurement.sidebar.bottom, measurement.main.bottom - measurement.detail.bottom].every(value => Math.abs(value - 14) < 1) && Math.abs(measurement.detail.x - measurement.sidebar.right - 8) < 1, 'CARD_SPACING', '主内容区至卡片四边应留白 14px，左右卡片间隔应为 8px。');
  check(!measurement.documentOverflow && measurement.scrolls.every(item => item.scrollWidth <= item.clientWidth + 1), 'HORIZONTAL_OVERFLOW', '原料管理出现整页或内容区横向溢出。');
  check(!measurement.documentVerticalOverflow && measurement.page.bottom <= height + 1 && [measurement.scrolls[0], ...measurement.parentScrolls].every(item => item.scrollHeight <= item.clientHeight + 1), 'PARENT_VERTICAL_OVERFLOW', '内容撑开页面或父容器，未限制在独立内容区内滚动。');
  check(measurement.scrolls.slice(1).every(item => item.overflowY === 'auto'), 'INDEPENDENT_SCROLL', '目录与属性区应按实际内容自动滚动，不能强制显示滚动条或截断溢出内容。');
  check(measurement.page.background === 'rgb(247, 245, 242)' && measurement.page.color === 'rgb(23, 25, 28)', 'PAGE_COLORS', '页面背景或正文颜色与 V2 参数不符。');
  check([measurement.page, ...measurement.controls, ...measurement.names, ...measurement.heads, ...measurement.labels, ...measurement.chips].every(item => item.fontFamily === measurement.bodyFontFamily), 'FONT_INHERITANCE', '原料管理字体族应继续继承现有全局字体。');
  check(measurement.page.fontSize === '13px' && measurement.controls.every(item => item.fontSize === '13px') && measurement.names.every(item => item.fontSize === '13px'), 'BODY_FONT_SIZE', '正文、控件与品名行应使用 13px 字号。');
  check(measurement.heads.every(item => item.fontSize === '17px' && item.fontWeight === '600' && item.lineHeight === '24px'), 'SECTION_HEADING', '属性区标题应使用 17px、600 字重、24px 行高。');
  check([measurement.sidebar, measurement.detail].every(item => borderIs(item, 'rgb(236, 232, 226)') && item.background === 'rgb(252, 251, 249)' && item.radius === '5px' && item.padding === '16px'), 'CARD_BORDERS', '两侧卡片四边应为单层 1px #ECE8E2，背景 #FCFBF9、圆角 5px、内边距 16px。');
  check(measurement.page.borders.every(border => border.width === '0px') && [measurement.page, measurement.sidebar, measurement.detail, ...measurement.chips].every(item => item.shadow === 'none' && noPseudoBorder(item)), 'SINGLE_BORDER_OWNER', '页面、卡片、属性框或伪元素出现重复边线或阴影。');
  check(measurement.chips.every(item => item.width >= 83.5 && item.height >= 31.5 && item.radius === '5px' && borderIs(item, 'rgb(218, 220, 224)') && item.textAlign === 'center' && item.justifyContent === 'center'), 'OPTION_CHIPS', '已存属性框应至少 84×32px、单层实线边框且值居中。');
  check(measurement.optionLines.every(item => item.gap === '8px' && item.wrap === 'wrap'), 'OPTION_WRAP', '属性选项应以 8px 间距自然换行。');
  check(measurement.rows.every(item => item.minHeight === '40px' && item.height >= 39.5) && measurement.groups.every(group => group.margin === '12px 0px') && measurement.shapeLabels.every(item => Math.abs(item.width - 84) < 1), 'COMPACT_ATTRIBUTE_ROWS', '属性行至少40px、分组间距12px、形状子标签84px。');
  const leaders = [...measurement.labels, ...measurement.groups.flatMap(group => group.leaders)];
  check(measurement.labels.every(item => Math.abs(item.width - 120) < 1) && measurement.groups.every(group => Math.abs(group.labels.width - 120) < 1), 'ATTRIBUTE_LABEL_WIDTH', '属性标签区应为 120px。');
  check(leaders.every(item => item.pseudo.some(pseudo => pseudo.pseudo === '::after' && pseudo.display !== 'none' && parseFloat(pseudo.width) > 0 && pseudo.topWidth === '1px' && pseudo.topStyle === 'dashed' && pseudo.topColor === 'rgb(218, 220, 224)')), 'ATTRIBUTE_LEADERS', '属性标签后应显示单层浅灰虚线。');
  check(measurement.groups.every(group => group.dimensions.borders.every(border => border.side === 'Left' ? border.width === '1px' && border.style === 'solid' && border.color === 'rgb(220, 216, 210)' : border.width === '0px') && (!group.headingVisible || (Math.abs(group.heading.x - (group.firstShapeLabel?.x ?? group.dimensions.x + 13)) < 1 && (!group.shapeRows.length || (group.heading.y >= group.shapeRows[group.shapeRows.length - 1].bottom - 1 && group.heading.y <= group.shapeRows[group.shapeRows.length - 1].bottom + 12)) && group.heading.right <= group.dimensions.right + 1))), 'SHAPE_GROUP_LAYOUT', '形状尺寸组应有左侧细竖线；添加形状及草稿应紧接列表底部，与形状名称左对齐。');
  check(measurement.controls.filter(item => item.action === 'add' && !item.disabled && !item.hovered).every(item => borderIs(item, 'rgb(236, 229, 220)') && item.background === 'rgb(248, 245, 240)'), 'ADD_SOLID_BORDER', '添加按钮应使用浅色背景和实线边框。');
  check(measurement.controls.filter(item => ['save', 'save-name', 'create-name'].includes(item.action) && !item.disabled).every(item => borderIs(item, 'rgb(255, 81, 10)') && item.color === 'rgb(240, 75, 9)' && ['rgb(255, 255, 255)', 'rgba(0, 0, 0, 0)', 'rgb(255, 240, 226)'].includes(item.background)), 'ORANGE_OUTLINE_ACTION', '保存与新品名按钮应为橙色描边，不能填成实心橙色。');
  check(measurement.names.filter(item => item.selected).every(item => item.background === 'rgb(255, 240, 226)' && item.fontWeight === '600' && item.color === 'rgb(23, 25, 28)' && item.borders.some(border => border.side === 'Left' && border.width === '4px' && border.color === 'rgb(255, 81, 10)')), 'SELECTED_NAME', '选中品名应为浅橙背景、左侧 4px 橙线和深色粗体文字。');
  check(!measurement.globalSave, 'GLOBAL_SAVE', '出现未确认的页面总保存按钮。');
  check(!measurement.heads.some(item => item.tag === 'H1' || parseFloat(item.fontSize) > 20 || ['品名目录', '选择分类'].includes(item.text)), 'GIANT_HEADER', '页面保留了被取消的大标题或冗余目录标题。');
  for (const control of measurement.controls) {
    check(Math.abs(control.height - control.expectedHeight) < 1, 'CONTROL_HEIGHT', `控件实际高度不是 ${control.expectedHeight}px：${control.tag}/${control.action || control.className}。`);
  }
  check(measurement.names.every(item => Math.abs(item.height - 32) < 1), 'NAME_ROW_HEIGHT', '品名行实际高度不是 32px。');
  check([...measurement.controls, ...measurement.names].every(item => item.radius === '5px'), 'CONTROL_RADIUS', '输入、选择器和按钮圆角应统一为5px。');
  for (const control of measurement.controls.filter(item => ['INPUT', 'SELECT'].includes(item.tag) || item.isSelect)) {
    const background = control.disabled ? 'rgb(232, 225, 213)' : control.readOnly ? 'rgb(240, 234, 223)' : 'rgb(252, 251, 247)';
    const color = control.disabled ? 'rgb(111, 106, 97)' : control.readOnly ? 'rgb(77, 76, 72)' : 'rgb(31, 29, 24)';
    const border = control.disabled || control.readOnly ? 'rgb(221, 214, 201)' : control.invalid ? 'rgb(181, 51, 51)' : control.focused ? 'rgb(56, 152, 236)' : 'rgb(221, 214, 201)';
    check(control.background === background && control.color === color && borderIs(control, border) && control.opacity === '1', 'INPUT_STATE_COLORS', '输入框或选择器的底色、字色、边框或透明度不符合 DESIGN 状态规范。');
    if (control.placeholderColor) check(control.placeholderColor === 'rgb(150, 143, 132)', 'INPUT_PLACEHOLDER', '输入占位文字应为 #968F84。');
  }
  record('desktop-layout', { width, height, state, measurement });
  delete report.failedMeasurement;
}

async function safeInlineChecks(detail, width, height, sprayDetail) {
  const row = page.locator('[data-field="BASE:material:"]');
  const add = row.locator('[data-action="add"]');
  if (!await add.count() || !await add.isEnabled()) { note('当前账号没有修改权限，行内输入与删除悬停未覆盖。'); return; }
  const chip = row.locator('.option-chip').first();
  if (await chip.count()) {
    await page.mouse.move(0, 0);
    await page.getByLabel('搜索品名', { exact: true }).focus();
    const geometry = () => chip.evaluate(node => { const remove = node.querySelector('[data-action="delete"]'), box = node.getBoundingClientRect(); return { width: box.width, height: box.height, x: box.x, opacity: remove ? getComputedStyle(remove).opacity : null, buttonWidth: remove?.getBoundingClientRect().width || 0 }; });
    const before = await geometry();
    await chip.hover();
    const remove = chip.locator('[data-action="delete"]');
    await remove.waitFor();
    await page.waitForFunction(node => getComputedStyle(node).opacity === '1', await remove.elementHandle());
    const hover = await geometry();
    await page.mouse.move(0, 0); await remove.focus();
    await page.waitForFunction(node => getComputedStyle(node).opacity === '1', await remove.elementHandle());
    const focus = await geometry();
    check(before.opacity === '0' && hover.opacity === '1' && focus.opacity === '1', 'DELETE_VISIBILITY', '删除图标未按悬停与键盘聚焦展示。');
    check(Math.abs(before.buttonWidth - 32) < 0.5 && [hover, focus].every(item => Math.abs(item.width - before.width) < 0.5 && Math.abs(item.height - before.height) < 0.5 && Math.abs(item.x - before.x) < 0.5), 'DELETE_LAYOUT_SHIFT', '删除按钮未预留 32px 位置，悬停或聚焦导致条目跳动。');
    record('delete-hover-focus', { before, hover, focus });
  } else note('缺少真实材质选项，删除悬停与键盘焦点未覆盖。');
  await add.click();
  const editor = row.locator('.inline-editor'), input = editor.locator('input'), save = editor.locator('[data-action="save"]');
  await input.fill('QA 未保存草稿');
  await page.getByLabel('搜索品名', { exact: true }).focus();
  await page.waitForTimeout(450);
  check(await input.inputValue() === 'QA 未保存草稿', 'DRAFT_LOST_ON_BLUR', '输入失焦后草稿被清除。');
  check(report.blockedWrites.length === 0, 'AUTO_SAVE_ON_BLUR', '输入失焦触发了业务写请求，已拦截。');
  const positions = { input: await input.boundingBox(), save: await save.boundingBox() };
  check(positions.input && positions.save && positions.save.x >= positions.input.x + positions.input.width - 1 && Math.abs(positions.save.y - positions.input.y) < 1, 'INLINE_SAVE_POSITION', '小保存按钮不在输入框右侧同一行。');
  record('inline-draft-no-autosave', positions);
  await input.focus();
  await measure(width, height, `inline-material-${digest(detail.id)}`);
  await screenshot(`${width}-inline-draft-${digest(detail.id)}`);
  await openPage(); // 丢弃未保存的浏览器草稿，不调用保存接口。
  for (const [scope, sample] of [['BASE', detail], ['SPRAY', sprayDetail]]) {
    if (!sample) { note('缺少真实喷塑样本，SPRAY 单位下拉未覆盖。'); continue; }
    await chooseDetail(sample);
    const unitRow = page.locator('[data-field="' + scope + ':unit:"]'), unitAdd = unitRow.locator('[data-action="add"]');
    if (await unitAdd.count() && await unitAdd.isEnabled()) {
      await unitAdd.click();
      const trigger = unitRow.getByRole('combobox', { name: '添加可用单位', exact: true });
      const available = catalogOptions.units.map(unit => ({ value: unit.id, label: unit.unit_name }));
      check(available.length > 1, 'UNIT_OPTIONS_REQUIRED', '真实单位不足两项，无法验收方向键移动与确认。');
      await selectValue(trigger, available[0].value);
      await checkDropdown(trigger, available, width, height, scope.toLowerCase() + '-unit');
      await measure(width, height, 'inline-' + scope.toLowerCase() + '-unit-' + digest(sample.id));
      await screenshot(width + '-inline-' + scope.toLowerCase() + '-unit-' + digest(sample.id));
      record('unit-draft-readonly', { width, scope, availableCount: available.length });
      await openPage();
    } else note('当前账号无法打开 ' + scope + ' 可用单位选择器，相关草稿布局未覆盖。');
  }

  const shapes = detail.values.filter(value => value.scope === 'BASE' && value.field_key === 'shape');
  const shape = shapes.find(value => value.value === '圆管') || shapes[0];
  if (shape) {
    await chooseDetail(detail);
    const shapeLabel = page.locator('.shape-dimensions [data-shape-id="' + shape.id + '"] .shape-label'), remove = shapeLabel.locator('.delete-shape');
    if (await remove.count()) {
      await page.mouse.move(0, 0); await page.getByLabel('搜索品名', { exact: true }).focus();
      const geometry = () => shapeLabel.evaluate(node => { const button = node.querySelector('.delete-shape'), box = node.getBoundingClientRect(); return { width: box.width, height: box.height, opacity: getComputedStyle(button).opacity, buttonWidth: button.getBoundingClientRect().width, buttonHeight: button.getBoundingClientRect().height }; });
      const before = await geometry(); await shapeLabel.hover(); const hover = await geometry();
      await page.mouse.move(0, 0); await remove.focus(); const focus = await geometry();
      check(before.opacity === '0' && hover.opacity === '1' && focus.opacity === '1' && before.buttonWidth === 32 && before.buttonHeight === 32 && [hover, focus].every(item => Math.abs(item.width - before.width) < 0.5 && Math.abs(item.height - before.height) < 0.5), 'SHAPE_DELETE_LAYOUT_SHIFT', '形状删除应预留 32px 点击区，悬停与键盘聚焦显示且不跳动。');
      record('shape-delete-hover-focus', { width, before, hover, focus });
    }
    const fields = ['BASE:shape:', 'BASE:section_size:' + shape.id];
    let opened = 0;
    for (const field of fields) {
      const target = page.locator('[data-field="' + field + '"]'), targetAdd = target.locator('[data-action="add"]');
      if (!await targetAdd.count() || !await targetAdd.isEnabled()) { note('当前账号无法同时打开形状和尺寸输入，相关草稿布局未覆盖。'); break; }
      await targetAdd.click();
      await target.locator('.inline-editor input').fill('QA 未保存草稿');
      opened += 1;
    }
    if (opened === fields.length) {
      await page.getByLabel('搜索品名', { exact: true }).focus();
      await page.waitForTimeout(150);
      for (const field of fields) check(await page.locator('[data-field="' + field + '"] .inline-editor input').inputValue() === 'QA 未保存草稿', 'SHAPE_DRAFT_SAFETY', '同时展开的形状或尺寸草稿在失焦后丢失。');
      const geometry = await page.locator('.section-group').evaluate(node => {
        const rect = item => { const box = item.getBoundingClientRect(); return { x: box.x, y: box.y, right: box.right, bottom: box.bottom, width: box.width, height: box.height }; };
        const card = node.closest('.catalog-detail');
        return { card: rect(card), editors: [...node.querySelectorAll('.inline-editor')].map(form => ({ form: rect(form), input: rect(form.querySelector('input')), save: rect(form.querySelector('[data-action="save"]')), clientWidth: form.clientWidth, scrollWidth: form.scrollWidth })), containers: [node, node.querySelector('.section-body'), node.querySelector('.shape-dimensions')].map(item => ({ className: item.className, clientWidth: item.clientWidth, scrollWidth: item.scrollWidth })) };
      });
      check(geometry.editors.length === 2 && geometry.editors.every(item => item.form.x >= geometry.card.x && item.form.right <= geometry.card.right + 1 && item.form.y >= geometry.card.y && item.form.bottom <= geometry.card.bottom + 1 && item.scrollWidth <= item.clientWidth + 1 && item.save.x >= item.input.right - 1 && Math.abs(item.save.y - item.input.y) < 1) && geometry.containers.every(item => item.scrollWidth <= item.clientWidth + 1), 'SIMULTANEOUS_DRAFT_LAYOUT', '形状与尺寸同时展开时应在卡片内、无横向溢出，小保存与各输入同行。');
      check(report.blockedWrites.length === 0, 'SHAPE_DRAFT_SAFETY', '形状或尺寸草稿尝试自动写入，已拦截。');
      await measure(width, height, 'inline-simultaneous-' + digest(detail.id));
      await screenshot(width + '-inline-simultaneous-' + digest(detail.id));
      record('simultaneous-shape-dimension-drafts', { width, geometry });
    }
    await openPage();
  } else note('当前行内验收样本没有真实形状，形状/尺寸草稿布局未覆盖。');

  // 包材有多个真实模板，验证新品名文本输入与模板选择器，不提交草稿。
  await chooseCategory('PACKAGING');
  const create = page.getByTestId('create-name');
  if (await create.count() && await create.isEnabled()) {
    await create.click();
    const name = page.getByLabel('新品名', { exact: true }), template = page.getByRole('combobox', { name: '品名模板', exact: true });
    await name.fill('QA 未保存品名');
    check(await template.count() === 1, 'NEW_NAME_TEMPLATE', '包材新品名表单缺少真实模板选择器。');
    const choices = catalogOptions.categories.find(item => item.key === 'PACKAGING').templates.map(item => ({ value: item.key, label: item.label }));
    check(choices.length > 1, 'NEW_NAME_TEMPLATE', '包材新品名表单应返回多个真实模板。');
    await selectValue(template, choices[0].value);
    await checkDropdown(template, choices, width, height, 'new-name-template');
    await measure(width, height, 'new-name-template-draft');
    await screenshot(width + '-new-name-template-draft');
    check(await name.inputValue() === 'QA 未保存品名' && report.blockedWrites.length === 0, 'NEW_NAME_DRAFT_SAFETY', '新品名草稿失焦后丢失，或触发自动写入。');
    record('new-name-draft-readonly', { width, templateCount: choices.length });
    await openPage();
  } else note('当前账号没有新增权限，新品名表单控件未覆盖。');
}

async function main() {
  let extraIds = [];
  if (process.env.MATERIAL_CATALOG_QA_EXTRA_IDS !== undefined) {
    try { extraIds = JSON.parse(process.env.MATERIAL_CATALOG_QA_EXTRA_IDS); }
    catch { stop('EXTRA_IDS_INVALID', 'MATERIAL_CATALOG_QA_EXTRA_IDS 必须是 JSON 数组，最多包含 5 个唯一 UUID。', true); }
    if (!Array.isArray(extraIds) || extraIds.length > 5 || !extraIds.every(id => typeof id === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id))) stop('EXTRA_IDS_INVALID', 'MATERIAL_CATALOG_QA_EXTRA_IDS 必须是 JSON 数组，最多包含 5 个唯一 UUID。', true);
    extraIds = extraIds.map(id => id.toLowerCase());
    if (new Set(extraIds).size !== extraIds.length) stop('EXTRA_IDS_INVALID', 'MATERIAL_CATALOG_QA_EXTRA_IDS 不能包含重复 UUID（不区分大小写）。', true);
  }
  if (!process.env.MATERIAL_CATALOG_QA_BASE_URL) stop('BASE_URL_REQUIRED', '请明确设置 MATERIAL_CATALOG_QA_BASE_URL 指向已准备好的目标环境。', true);
  try { base = new URL(process.env.MATERIAL_CATALOG_QA_BASE_URL); } catch { stop('BASE_URL_INVALID', '目标环境地址无效。', true); }
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.pathname !== '/' || base.search || base.hash) stop('BASE_URL_INVALID', '目标地址应为不含凭据、路径、查询参数的 HTTP(S) 源地址。', true);
  if (!(statePath || (username && password))) stop('AUTH_REQUIRED', '需要已有 Session 状态文件或真实账号和密码；脚本不会自动创建账号。', true);
  if (statePath && (!fs.existsSync(statePath) || !fs.statSync(statePath).isFile())) stop('STATE_NOT_FOUND', '指定 Session 文件不存在或不可读。', true);
  if (visualBaselinePath) {
    try { visualBaseline = JSON.parse(fs.readFileSync(path.resolve(visualBaselinePath), 'utf8')); }
    catch { stop('VISUAL_BASELINE_INVALID', '指定字体/导航基线不存在、不可读或不是有效 JSON。', true); }
    const valid = visualBaseline?.mode === 'real-session-readonly-font-navigation-baseline' && visualBaseline.status === 'PASS' && visualBaseline.capturedBeforeTargetCss === true && Array.isArray(visualBaseline.viewports) && viewports.every(viewport => {
      const entries = visualBaseline.viewports.filter(item => JSON.stringify(item?.viewport) === JSON.stringify(viewport));
      return entries.length === 1 && typeof entries[0].bodyFontFamily === 'string' && entries[0].bodyFontFamily && Array.isArray(entries[0].outer) && ['.erp-layout__sidebar', '.erp-layout__header'].every(selector => {
        const nodes = entries[0].outer.filter(item => item?.selector === selector);
        return nodes.length === 1 && /^[0-9a-f]{64}$/.test(nodes[0].domDigest) && /^[0-9a-f]{64}$/.test(nodes[0].styleDigest);
      });
    });
    if (!valid) stop('VISUAL_BASELINE_INVALID', '字体/导航基线缺少已确认的三视口、正常采集状态或完整指纹。', true);
    report.visualBaseline = { digest: digest(JSON.stringify(visualBaseline)), viewports: viewports.length };
  } else note('未提供修改前字体/外导航基线，仅核对当前字体继承；不宣称外部导航与修改前完全一致。');
  const executablePath = process.env.MATERIAL_CATALOG_QA_BROWSER_PATH || ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(candidate => fs.existsSync(candidate));
  if (!executablePath || !fs.existsSync(executablePath)) stop('BROWSER_MISSING', '找不到已安装浏览器；脚本不会安装依赖。', true);
  fs.mkdirSync(evidenceDir, { recursive: true });
  check(samePath(fs.realpathSync(evidenceDir), evidenceDir), 'EVIDENCE_BOUNDARY', '证据目录存在未确认的重定向。');
  evidenceVerified = true;
  saveReport(); // 创建临时目录前登记确切路径及用途。
  if (fs.existsSync(browserTemp)) stop('TEMP_EXISTS', '独占浏览器目录已存在，拒绝覆盖或清理未知资源。', true);
  fs.mkdirSync(path.dirname(browserTemp), { recursive: true });
  check(samePath(fs.realpathSync(path.dirname(browserTemp)), path.dirname(browserTemp)), 'TEMP_BOUNDARY', '临时目录父路径存在未确认的重定向。');
  fs.mkdirSync(browserTemp); ownsTemp = true; report.resources.created = true;
  for (const key of Object.keys(previousTemp)) process.env[key] = browserTemp;
  browser = await chromium.launch({ headless: true, executablePath, downloadsPath: browserTemp });
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, locale: 'zh-CN', timezoneId: 'Asia/Shanghai', serviceWorkers: 'block', ...(statePath ? { storageState: path.resolve(statePath) } : {}) });
  await context.route('**/*', async route => {
    if (!['GET', 'HEAD'].includes(route.request().method())) {
      report.blockedWrites.push({ method: route.request().method(), path: safePath(route.request().url()) });
      await route.abort('blockedbyclient'); return;
    }
    await route.continue();
  });
  stage = 'authentication'; await authenticate(context);
  stage = 'real-api';
  const options = (await readApi(context, apiPrefix + 'options/', 'options')).body.data;
  catalogOptions = options;
  check(Array.isArray(options?.categories) && Array.isArray(options?.spray_fields) && Array.isArray(options?.units), 'OPTIONS_CONTRACT', '类别、属性或单位选项契约不符。');
  const categoryKeys = ['TUBE', 'FABRIC', 'HARDWARE', 'PLASTIC', 'PACKAGING', 'AUXILIARY', 'FABRIC_SEMI'];
  const templateKeys = ['TUBE', 'FABRIC', 'HARDWARE', 'PLASTIC', 'CARTON', 'BAG', 'PACKAGING_GENERAL', 'TAPE', 'COTTON', 'AUXILIARY_GENERAL', 'FABRIC_SEMI'];
  check(JSON.stringify(options.categories.map(item => item.key).sort()) === JSON.stringify(categoryKeys.sort()), 'CATEGORY_DEFINITIONS', '新模块没有完整返回已确认的七个类别。');
  check(options.categories.every(item => Array.isArray(item.templates)) && JSON.stringify(options.categories.flatMap(item => item.templates.map(template => template.key)).sort()) === JSON.stringify(templateKeys.sort()), 'TEMPLATE_DEFINITIONS', '新模块没有完整返回已确认的属性模板。');
  checkFixedFields(options);
  const samples = [], categories = [];
  for (const category of options.categories) {
    const candidates = new Map(), seenIds = new Set();
    const templateKeys = new Set(category.templates.map(template => template.key));
    let firstMeta, firstPageCount = 0, pagesRead = 0;
    for (let requestedPage = 1; !firstMeta || requestedPage <= firstMeta.total_pages; requestedPage += 1) {
      const list = (await readApi(context, `${apiPrefix}?category=${encodeURIComponent(category.key)}&page=${requestedPage}&page_size=100`, `category-${category.key}-page-${requestedPage}`)).body;
      const meta = list.meta;
      check(Array.isArray(list.data) && Number.isSafeInteger(meta?.total) && meta.total >= 0 && meta.page === requestedPage && Number.isInteger(meta.page_size) && meta.page_size > 0 && meta.page_size <= 100 && Number.isSafeInteger(meta.total_pages) && meta.total_pages === Math.max(1, Math.ceil(meta.total / meta.page_size)), 'LIST_CONTRACT', '原料管理列表分页契约不符。');
      if (!firstMeta) { firstMeta = meta; firstPageCount = list.data.length; }
      check(meta.total === firstMeta.total && meta.total_pages === firstMeta.total_pages && meta.page_size === firstMeta.page_size, 'PAGINATION_CHANGED', '取样期间列表总数或分页发生变化，请重新验收，不追随变化无限翻页。');
      check(list.data.length === Math.min(meta.page_size, Math.max(0, meta.total - (requestedPage - 1) * meta.page_size)), 'PAGE_LENGTH', '原料管理分页条数与真实 meta 不一致。');
      check(list.data.every(item => item.category_key === category.key), 'CATEGORY_FILTER', '类别筛选返回了其他类别。');
      for (const item of list.data) {
        check(typeof item.id === 'string' && item.id && templateKeys.has(item.template_key), 'LIST_ITEM_CONTRACT', '列表记录缺少身份或引用了其他类别的模板。');
        check(!seenIds.has(item.id), 'DUPLICATE_PAGE_ITEM', '分页重复返回已读取的档案，请核查分页或并发变更。');
        seenIds.add(item.id);
        if (!candidates.has(item.template_key)) candidates.set(item.template_key, item);
      }
      pagesRead += 1;
      if (candidates.size === templateKeys.size || requestedPage === firstMeta.total_pages) break;
    }
    categories.push({ key: category.key, total: firstMeta.total, firstPage: firstPageCount, pagesRead, totalPages: firstMeta.total_pages });
    for (const template of category.templates) {
      const candidate = candidates.get(template.key);
      if (!candidate) { note(`已读完 ${category.key} 类别的真实列表，未找到 ${template.key} 模板；未创建演示数据补齐。`); continue; }
      const before = await readApi(context, apiPrefix + candidate.id + '/', `detail-${template.key}`);
      const detail = before.body.data;
      check(detail?.id === candidate.id && Array.isArray(detail.values) && Array.isArray(detail.units) && Boolean(before.etag), 'DETAIL_CONTRACT', '真实详情数据或 ETag 缺失。');
      snapshots.set(detail.id, { etag: before.etag, hash: digest(JSON.stringify(detail)) });
      samples.push(detail);
    }
  }
  for (const id of extraIds) {
    if (snapshots.has(id)) continue;
    const before = await readApi(context, apiPrefix + id + '/', `extra-detail-${digest(id)}`);
    const detail = before.body.data;
    check(detail?.id === id && Array.isArray(detail.values) && Array.isArray(detail.units) && Boolean(before.etag), 'DETAIL_CONTRACT', '指定样本的真实详情数据或 ETag 缺失。');
    check(options.categories.some(category => category.key === detail.category_key && category.templates.some(template => template.key === detail.template_key)), 'TEMPLATE_CONTRACT', '指定样本引用了未定义的类别或模板。');
    snapshots.set(detail.id, { etag: before.etag, hash: digest(JSON.stringify(detail)) });
    samples.push(detail);
  }
  report.discovery = categories;
  page = await context.newPage(); page.setDefaultTimeout(15000);
  page.on('pageerror', error => report.pageErrors.push({ name: error.name, digest: digest(error.message) }));
  page.on('response', response => { if (response.status() >= 400 && new URL(response.url()).origin === base.origin) report.httpErrors.push({ status: response.status(), path: safePath(response.url()) }); });
  for (const [width, height] of viewports) {
    stage = `viewport-${width}`; await page.setViewportSize({ width, height }); await openPage();
    await screenshot(`${width}-initial`); await measure(width, height, 'initial');
    await checkDropdown(page.getByRole('combobox', { name: '原料类别', exact: true }), options.categories.map(item => ({ value: item.key, label: item.label })), width, height, 'category');
    await openPage();
    const ordinaryName = page.locator('[data-testid="material-names"] [data-catalog-id]:not(.selected)').first();
    if (await ordinaryName.count()) {
      await ordinaryName.hover();
      check(await ordinaryName.evaluate(node => getComputedStyle(node).backgroundColor) === 'rgb(245, 242, 237)', 'NAME_HOVER', '普通品名悬停应使用 #F5F2ED 背景。');
      await page.mouse.move(0, 0); record('name-hover', { width });
    }
    const selectedName = page.locator('[data-testid="material-names"] [data-catalog-id].selected').first();
    if (await selectedName.count()) {
      await selectedName.hover();
      check(await selectedName.evaluate(node => getComputedStyle(node).backgroundColor) === 'rgb(255, 240, 226)', 'SELECTED_NAME_HOVER', '选中品名悬停时应保留浅橙选中背景。');
      await page.mouse.move(0, 0); record('selected-name-hover', { width });
    }
    for (const detail of samples) {
      await chooseDetail(detail); await checkDetail(detail, options);
      const sampleState = `${detail.template_key}-${digest(detail.id)}`;
      await measure(width, height, sampleState); await screenshot(`${width}-${sampleState}`);
    }
    const empty = categories.find(category => category.total === 0);
    if (empty) {
      await page.getByLabel('搜索品名', { exact: true }).fill(''); await chooseCategory(empty.key);
      await page.waitForFunction(() => document.querySelector('[data-testid="material-names"]')?.getAttribute('aria-busy') === 'false');
      check(await page.locator('[data-testid="material-names"] [data-catalog-id]').count() === 0, 'EMPTY_LIST', '真实空类别仍显示旧品名。');
      check(await page.locator('.catalog-sidebar').getByText(/暂无|没有|无匹配/).count() > 0, 'EMPTY_EXPLANATION', '空列表缺少可理解的说明。');
      await measure(width, height, 'empty-category'); await screenshot(`${width}-empty-category`);
    } else note('当前真实类别均非空，未删除数据制造空类别。');
    const search = page.getByLabel('搜索品名', { exact: true });
    const noMatch = `QA_EMPTY_${crypto.randomUUID()}`;
    const filtered = page.waitForResponse(item => {
      const url = new URL(item.url());
      return url.pathname === apiPrefix && url.searchParams.get('q') === noMatch && item.request().method() === 'GET';
    });
    await search.fill(noMatch);
    const response = await filtered;
    check(response.status() === 200, 'FILTER_REQUEST', '筛选无结果请求未返回真实响应。');
    const result = await response.json();
    check(result.meta?.total === 0 && result.data?.length === 0, 'FILTER_EMPTY_API', '唯一查询词应返回真实空列表；接口可能未应用筛选。');
    await page.waitForFunction(() => document.querySelector('[data-testid="material-names"]')?.getAttribute('aria-busy') === 'false');
    check(await page.locator('[data-testid="material-names"] [data-catalog-id]').count() === 0 && await page.locator('.catalog-detail[data-catalog-id]').count() === 0, 'FILTER_EMPTY_UI', '真实无结果筛选后仍残留品名或旧详情。');
    check(await page.locator('.catalog-sidebar').getByText(/暂无|没有|无匹配/).count() > 0, 'FILTER_EMPTY_EXPLANATION', '筛选无结果缺少说明。');
    await measure(width, height, 'filter-no-results'); await screenshot(`${width}-filter-no-results`);
  }
  const editable = samples.filter(detail => detail.template_key === 'TUBE' && detail.values.some(value => value.scope === 'BASE' && value.field_key === 'shape')).sort((left, right) => right.values.length - left.values.length)[0] || samples.find(detail => detail.values.some(value => value.scope === 'BASE' && value.field_key === 'material')) || samples[0];
  if (editable) for (const [width, height] of viewports) { stage = `inline-readonly-${width}`; await page.setViewportSize({ width, height }); await chooseDetail(editable); await safeInlineChecks(editable, width, height, samples.find(item => item.spray_enabled)); }
  else note('真实档案为空，详情与行内交互均未覆盖。');
  stage = 'unchanged-check';
  for (const [id, before] of snapshots) {
    const after = await readApi(context, apiPrefix + id + '/', 'unchanged-detail');
    check(before.etag === after.etag && before.hash === digest(JSON.stringify(after.body.data)), 'DATA_CHANGED', '只读验收期间真实详情发生变化，需排查并发编辑，不能声称未变。');
  }
  const dropdowns = report.checks.filter(item => item.id === 'dropdown-real-panel');
  check(viewports.every(([width]) => ['category', 'new-name-template', 'base-unit', 'spray-unit'].every(kind => dropdowns.some(item => item.width === width && item.kind === kind))), 'DROPDOWN_MATRIX_REQUIRED', '三视口必须覆盖分类、模板、BASE与SPRAY单位的真实展开面板，不能以未覆盖代替。');
  check(['top', 'bottom'].every(direction => dropdowns.some(item => item.measurement.placement?.startsWith(direction))), 'DROPDOWN_PLACEMENT_REQUIRED', '真实面板需覆盖向下展开与空间不足向上避让。');
  check(report.blockedWrites.length === 0, 'BUSINESS_WRITE_BLOCKED', '页面尝试了业务写入，已全部拦截。');
  check(report.pageErrors.length === 0 && report.httpErrors.length === 0, 'PAGE_ERRORS', '页面出现脚本或 HTTP 错误，报告只保存摘要。');
  note('未提交新建、属性保存、删除、喷塑切换；写入、权限拒绝、CSRF、412/428 恢复由独立业务/API 验收负责。');
  note('未伪造加载失败、无权限、超长值及大量数据；仅覆盖目标环境已有真实状态，不宣称完整视觉验收。');
  note('错误提示气泡、未自然出现的禁用/只读输入状态未做本轮视觉验收；真实下拉面板已单独验证。');
  if (!samples.some(item => item.spray_enabled)) note('没有已启用喷塑的真实样本，喷塑选项展示未覆盖。');
  report.status = 'PASS_WITH_GAPS';
}

(async () => {
  try { await main(); }
  catch (error) {
    report.status = error.blocked ? 'BLOCKED' : 'FAIL'; process.exitCode = 1;
    report.failure = { stage, code: error.safeQaMessage ? error.code : 'UNEXPECTED', message: error.safeQaMessage ? error.message : '执行异常；未输出可能含业务值的原始错误。', sourceLine: Number(error.stack?.match(/material_catalog_readonly\.cjs:(\d+)/)?.[1]) || null, digest: digest(error.message) };
    if (page && !page.isClosed()) {
      try {
        report.failureDom = await page.locator('.material-catalog-select,.material-catalog-select-popper,[role="combobox"]').evaluateAll(nodes => nodes.map(node => ({ tag: node.tagName, className: node.className, role: node.getAttribute('role'), expanded: node.getAttribute('aria-expanded'), visible: Boolean(node.getClientRects().length) && getComputedStyle(node).visibility !== 'hidden', options: node.querySelectorAll('[role="option"]').length, selected: node.querySelectorAll('[role="option"][aria-selected="true"]').length })));
        await screenshot('failure-state');
      } catch { report.failureDiagnosticsUnavailable = true; }
    }
  } finally {
    let canRemove = !browser;
    if (browser) {
      try { await browser.close(); report.resources.browserClosed = true; canRemove = true; }
      catch { report.resources.closeFailed = true; report.status = 'FAIL'; process.exitCode = 1; }
    }
    for (const key of Object.keys(previousTemp)) { if (previousTemp[key] === undefined) delete process.env[key]; else process.env[key] = previousTemp[key]; }
    if (ownsTemp && canRemove) {
      try {
        check(samePath(path.dirname(browserTemp), path.join(root, '.tmp/material-catalog')) && samePath(fs.realpathSync(browserTemp), browserTemp) && !fs.lstatSync(browserTemp).isSymbolicLink(), 'CLEANUP_BOUNDARY', '临时浏览器目录归属核验失败。');
        fs.rmSync(browserTemp, { recursive: true, force: false }); report.resources.removed = true;
        report.resources.verifiedAbsent = !fs.existsSync(browserTemp);
        check(report.resources.verifiedAbsent, 'CLEANUP_REMAINS', '临时浏览器目录仍存在。');
      } catch { report.resources.cleanupFailed = true; report.status = 'FAIL'; process.exitCode = 1; }
    } else if (!ownsTemp) report.resources.verifiedAbsent = !fs.existsSync(browserTemp);
    report.finishedAt = new Date().toISOString(); saveReport();
    console.log(JSON.stringify({ qa_result_version: 1, status: report.status, not_covered: report.notCovered, checks: report.checks.length, gaps: report.notCovered.length, blockedWrites: report.blockedWrites.length, failure: report.failure, report: evidenceVerified ? reportPath : null, cleanup: report.resources.verifiedAbsent }));
  }
})();

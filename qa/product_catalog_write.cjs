/* 仅专项授权后执行。真实API/页面写入仅限登记的独立产品管理QA记录。 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { chromium } = require('../src/frontend/node_modules/playwright-core');

const root = path.resolve(__dirname, '..');
const task = '2ebd7b22';
const prefix = 'QA_PRODUCT_20261016_' + task;
const evidence = path.join(root, 'output/product-catalog-20261016-' + task);
const resourceDir = path.join(root, 'src/backend/.tmp/product-catalog-20261016-' + task);
const manifestPath = path.join(resourceDir, 'created-records.json');
const accountsPath = path.join(resourceDir, 'accounts.json');
const stamp = new Date().toISOString().replace(/[:.]/g, '-');
const temp = path.join(root, '.tmp/product-catalog-20261016-' + task, 'write-browser-' + stamp);
const api = '/api/v1/product-catalog/';
const reportPath = path.join(evidence, 'write-' + stamp + '.json');
const report = { status: 'RUNNING', startedAt: new Date().toISOString(), checks: [], screenshots: [], resources: { temp, created: false, removed: false }, notCovered: [], unexpectedWrites: [], pageErrors: [], designExceptions: ['小保存按钮维持原宽度；加载完整文字通过悬浮提示及无障碍播报提供，不在48px按钮内同时铺开。'] };
const manifest = { task, name_ids: [], product_ids: [], expected_names: {}, expected_products: {} };
let browser, context, page, base, stage = 'preconditions', ownsResources = false;
const pendingReleases = new Set();
const check = (value, message) => { if (!value) throw new Error(message); };
const record = (id, detail = {}) => report.checks.push({ id, ...detail });
const persist = () => fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
function rememberProduct(product) {
  check(manifest.product_ids.includes(product.id), '不能登记未归属本任务的产品快照');
  manifest.expected_products[product.id] = {
    name_id: product.name_id,
    updated_at: product.updated_at,
    fields: Object.fromEntries(['product_code', 'item_number', 'specification', 'unit', 'scale'].map(key => [key, product[key]])),
    colors: product.colors.map(color => ({ id: color.id, value: color.value })),
    color_ids: [...new Set([...(manifest.expected_products[product.id]?.color_ids ?? []), ...product.colors.map(color => color.id)])],
  };
  persist();
}
async function acceptProductResponse(response, expected, message) {
  check(response.status() === expected, message);
  const body = await response.json();
  if (response.ok() && manifest.product_ids.includes(body.data?.id)) rememberProduct(body.data);
  return body;
}
const saveReport = () => fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
async function screenshot(label) { const file = `${stamp}-write-${label}.png`; await page.screenshot({ path: path.join(evidence, file), fullPage: true }); report.screenshots.push(file); }
async function csrf(ctx) { return (await ctx.cookies(base.origin)).find(cookie => cookie.name === 'csrftoken')?.value; }
async function request(method, route, data, etag, ctx = context) {
  const target = new URL(route, base);
  check(target.origin === base.origin, 'API写入目标越界');
  if (!['GET', 'HEAD'].includes(method)) {
    const allowed = (ctx !== context && method === 'POST' && target.pathname === '/api/auth/login/')
      || (method === 'POST' && target.pathname === api && manifest.name_ids.includes(data?.name_id))
      || manifest.product_ids.some(id => target.pathname === api + id + '/' || target.pathname.startsWith(api + id + '/colors/'));
    check(allowed, 'API写入不属于本任务登记资源');
  }
  const headers = { Referer: base.origin + '/' };
  const token = await csrf(ctx);
  if (token) headers['X-CSRFToken'] = token;
  if (etag) headers['If-Match'] = etag;
  const response = await ctx.request.fetch(new URL(route, base).href, { method, data, headers });
  const body = await response.json();
  if (!['GET', 'HEAD'].includes(method) && response.ok() && manifest.product_ids.includes(body.data?.id)) rememberProduct(body.data);
  return { status: response.status(), body, etag: response.headers().etag };
}
async function read(id) { const r = await request('GET', api + id + '/'); check(r.status === 200, '读取QA产品失败'); return r; }
function rememberName(name) {
  check(manifest.name_ids.includes(name.id), '不能登记未归属本任务的品名');
  manifest.expected_names[name.id] = { name: name.name, category_id: name.category_id };
  persist();
}
async function nextFrame() { await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))); }
async function settleVisual(locator) {
  await nextFrame();
  await page.waitForFunction(node => node.getAnimations({ subtree: true }).every(animation => animation.playState !== 'running' || animation.effect?.getTiming().iterations === Infinity), await locator.elementHandle());
}
async function noExtraVerticalScroll(label) {
  const measured = await page.locator('.product-table-scroll').evaluate(node => ({ scroll: node.scrollHeight, client: node.clientHeight }));
  check(measured.scroll <= measured.client + 1, label + '出现多余纵向滚动');
  record('short-content-no-extra-scroll', { label, measured });
}
// 暂缓真实请求，不提供成功替身；任何断言失败也释放请求，响应仍由调用方登记。
async function pendingSave(button, pathname, method) {
  const pattern = new URL(pathname, base).href;
  let release, requests = 0, responsePromise;
  const gate = new Promise(resolve => { release = resolve; });
  pendingReleases.add(release);
  const handlers = new Set(), routeFailures = [];
  const delayed = route => {
    const handling = (async () => {
      if (route.request().method() !== method) return route.fallback();
      requests += 1; await gate; await route.fallback();
    })();
    handlers.add(handling);
    handling.then(() => handlers.delete(handling), error => { handlers.delete(handling); routeFailures.push(error); });
    return handling;
  };
  await page.mouse.move(0, 0); await button.focus();
  await settleVisual(button);
  const before = await button.evaluate(node => { const b = node.getBoundingClientRect(), s = getComputedStyle(node); return { width: b.width, height: b.height, background: s.backgroundColor, color: s.color, border: s.borderColor }; });
  await page.route(pattern, delayed);
  try {
    responsePromise = page.waitForResponse(response => new URL(response.url()).pathname === pathname && response.request().method() === method);
    responsePromise.catch(() => undefined);
    const arrived = page.waitForRequest(req => new URL(req.url()).pathname === pathname && req.method() === method);
    await button.click(); await arrived;
    await page.waitForFunction(node => node.getAttribute('aria-busy') === 'true', await button.elementHandle());
    await settleVisual(button);
    const during = await button.evaluate(node => { const b = node.getBoundingClientRect(), s = getComputedStyle(node); return { width: b.width, height: b.height, background: s.backgroundColor, color: s.color, border: s.borderColor, focused: document.activeElement === node, nativeDisabled: node.disabled, blocked: node.getAttribute('aria-disabled') }; });
    check(before.height === 32 && Math.abs(before.width - during.width) < 0.5 && during.height === 32, '保存中按钮尺寸变化');
    check(during.focused && !during.nativeDisabled && during.blocked === 'true', '保存中未保留焦点或未声明阻止操作');
    check(['background', 'color', 'border'].every(key => before[key] === during[key]), '保存中配色变为普通禁用态');
    check(await button.locator('[data-save-spinner]').count() === 1 && await button.locator('[role="status"]').textContent() === '处理中…', '保存中图标或状态说明缺失');
    await page.locator('.product-catalog-saving-popper:visible').waitFor();
    await button.click({ force: true }); await button.press('Enter'); await button.press('Space');
    await button.evaluate(node => node.closest('form')?.requestSubmit()); await nextFrame();
    check(requests === 1, '保存中重复点击/键盘/表单触发额外写请求');
    const disabledSelects = page.locator('.product-catalog-page .el-select__wrapper.is-disabled');
    for (const wrapper of await disabledSelects.all()) {
      await wrapper.click({ force: true });
      check(await wrapper.locator('input[role="combobox"]').getAttribute('aria-expanded') !== 'true', '保存期间禁用选择器仍可展开');
    }
    await screenshot('pending-' + report.checks.length);
    record('real-save-pending', { pathname, method, before, during, requests, compactLoadingText: '完整文字保留在悬浮提示与无障碍播报' });
  } finally {
    release(); pendingReleases.delete(release);
    while (handlers.size) await Promise.allSettled([...handlers]);
    await page.unroute(pattern, delayed);
    // 即使保存中视觉断言失败，已放行的成功写入仍必须登记，供 finally 精确清理。
    if (requests && responsePromise) {
      const response = await responsePromise;
      if (response.ok()) {
        const item = (await response.json()).data;
        if (pathname.startsWith(api + 'names/')) {
          if (pathname === api + 'names/' && item.name.startsWith(prefix) && !manifest.name_ids.includes(item.id)) manifest.name_ids.push(item.id);
          rememberName(item);
        } else {
          if (pathname === api && manifest.name_ids.includes(item.name_id) && !manifest.product_ids.includes(item.id)) manifest.product_ids.push(item.id);
          rememberProduct(item);
        }
      }
    }
    if (routeFailures.length) throw routeFailures[0];
  }
}
async function failedDraft(button, pathname, method, input, expectedValue) {
  const pattern = new URL(pathname, base).href;
  const fail = async route => route.request().method() === method ? route.abort('failed') : route.fallback();
  await page.route(pattern, fail);
  try {
    await button.click(); await page.locator('.product-catalog-field-error').last().waitFor();
    check(await input.inputValue() === expectedValue, '失败提交丢失草稿');
    await page.waitForFunction(node => node.getAttribute('aria-busy') !== 'true', await button.elementHandle());
  } finally { await page.unroute(pattern, fail); }
  record('failed-create-keeps-draft', { pathname });
}
async function exerciseDropdown(root, targetValue, label) {
  const trigger = root.getByRole('combobox'), wrapper = root.locator('.el-select__wrapper');
  await trigger.waitFor();
  await page.waitForFunction(node=>!node.disabled, await trigger.elementHandle());
  const panel = page.locator('.material-catalog-select-popper:visible');
  const open = async () => { await wrapper.click(); await panel.waitFor(); await settleVisual(panel); };
  const before = await root.getAttribute('data-model-value');
  await trigger.focus(); await open();
  const measured = await panel.evaluate(node => { const b = node.getBoundingClientRect(), s = getComputedStyle(node); return { x: b.x, y: b.y, right: b.right, bottom: b.bottom, width: b.width, background: s.backgroundColor, border: s.borderColor, borders: [s.borderTopWidth,s.borderRightWidth,s.borderBottomWidth,s.borderLeftWidth], radius: s.borderRadius, listHeight: node.querySelector('.el-select-dropdown__wrap').getBoundingClientRect().height, optionHeights: [...node.querySelectorAll('[role="option"]')].map(item=>item.getBoundingClientRect().height) }; });
  const viewport = page.viewportSize(), box = await wrapper.boundingBox();
  check(measured.borders.every(value=>value==='1px') && measured.border==='rgb(221, 214, 201)' && measured.background==='rgb(252, 251, 247)' && measured.radius==='5px', label+'下拉样式不符');
  check(measured.width >= box.width - 1 && measured.x >= 0 && measured.y >= 0 && measured.right <= viewport.width + 1 && measured.bottom <= viewport.height + 1 && measured.listHeight <= 240.5 && measured.optionHeights.every(height=>Math.abs(height-32)<0.5), label+'下拉尺寸或避让不符');
  const selected = panel.locator('[aria-selected="true"]');
  if (await selected.count()) { await selected.first().hover(); await settleVisual(selected.first()); check(await selected.first().evaluate(node=>getComputedStyle(node).backgroundColor)==='rgb(255, 244, 230)', label+'选中悬停色错误'); }
  const ordinary = panel.locator('[role="option"]:not([aria-selected="true"]):not(.is-disabled)').first();
  if (await ordinary.count()) { await ordinary.hover(); await settleVisual(ordinary); check(await ordinary.evaluate(node=>getComputedStyle(node).backgroundColor)==='rgb(255, 246, 234)', label+'普通悬停色错误'); }
  await screenshot('expanded-' + label);
  await trigger.press('ArrowDown'); check(await root.getAttribute('data-model-value')===before, label+'方向键提前提交');
  await trigger.press('Escape'); await panel.waitFor({state:'hidden'});
  await open(); await trigger.press('Tab'); await panel.waitFor({state:'hidden'});
  await open();
  // 业务值精确匹配，避免文字包含关系选择错误选项。
  const option = panel.locator(`[role="option"][data-value="${targetValue}"]`);
  await option.scrollIntoViewIfNeeded(); await option.hover(); await settleVisual(option);
  check(await option.evaluate(node=>{const b=node.getBoundingClientRect(), hit=document.elementFromPoint(b.x+b.width/2,b.y+b.height/2);return node===hit||node.contains(hit);}),label+'选项被遮挡');
  await trigger.press('Enter'); await panel.waitFor({state:'hidden'});
  check(await root.getAttribute('data-model-value')===targetValue,label+'Enter未确认实际选项');
  record('real-dropdown', { label, measured, selected: targetValue });
}
async function errorBubbles(scope, input) {
  const icons = scope.locator('.product-catalog-field-error');
  const poppers = page.locator('.product-catalog-error-popper:visible');
  const before = await scope.boundingBox();
  await icons.first().focus(); await poppers.waitFor(); await settleVisual(poppers);
  if (await icons.count() > 1) await icons.last().hover();
  await page.waitForFunction(() => [...document.querySelectorAll('.product-catalog-error-popper')].filter(node => getComputedStyle(node).display !== 'none' && getComputedStyle(node).visibility !== 'hidden').length === 1);
  await settleVisual(poppers); check(await poppers.count() === 1, '同时显示多个字段错误气泡');
  const measured = await poppers.evaluate(node=>{const b=node.getBoundingClientRect(),s=getComputedStyle(node);return {x:b.x,y:b.y,right:b.right,bottom:b.bottom,width:b.width,background:s.backgroundColor,border:s.borderColor,color:s.color,radius:s.borderRadius,size:s.fontSize,line:s.lineHeight,padding:[s.paddingTop,s.paddingRight,s.paddingBottom,s.paddingLeft]};});
  const viewport=page.viewportSize();
  check(measured.background==='rgb(252, 251, 247)' && measured.border==='rgb(181, 51, 51)' && measured.color==='rgb(181, 51, 51)' && measured.radius==='5px' && measured.size==='12px' && measured.line==='18px' && measured.padding.join(',')==='8px,12px,8px,12px','错误气泡计算样式不符');
  check(measured.width<=300.5 && measured.x>=0 && measured.y>=0 && measured.right<=viewport.width+1 && measured.bottom<=viewport.height+1,'错误气泡被视口截断');
  await poppers.hover(); check(await poppers.count()===1,'移入错误气泡后无法阅读');
  await screenshot('error-bubble-' + report.checks.length);
  await page.keyboard.press('Escape'); await poppers.waitFor({state:'hidden'}); await nextFrame(); check(await poppers.count()===0,'Esc后气泡立即重开');
  await icons.first().click(); await poppers.waitFor();
  await page.locator('.catalog-detail').click({position:{x:4,y:4}}); await poppers.waitFor({state:'hidden'});
  await input.focus(); await settleVisual(input);
  const errorStyle=await input.evaluate(node=>{const s=getComputedStyle(node);return {border:s.borderColor,outline:s.outlineColor,style:s.outlineStyle,width:s.outlineWidth,offset:s.outlineOffset};});
  check(errorStyle.border==='rgb(181, 51, 51)' && errorStyle.style!=='none' && errorStyle.outline==='rgb(56, 152, 236)' && errorStyle.width==='2px' && errorStyle.offset==='2px','错误输入焦点样式不符');
  check(Math.abs((await scope.boundingBox()).height-before.height)<0.5,'错误气泡挤高内容');
  record('real-error-bubbles',{count:await icons.count(),measured,errorStyle});
}
async function addProduct(nameId, values = {}) {
  check(manifest.name_ids.includes(nameId), '不得向未登记品名建产品');
  const r = await request('POST', api, { name_id: nameId, product_code: '', item_number: 'QA-SAME', specification: 'QA规格', unit: '', scale: '定制', ...values });
  check(r.status === 201, '真实API新增QA产品失败');
  manifest.product_ids.push(r.body.data.id); rememberProduct(r.body.data); return r.body.data;
}
async function editField(row, field, label, value) {
  const cell = row.locator(`[data-field="${field}"]`);
  await cell.getByRole('button', { name: '编辑' + label, exact: true }).click();
  await cell.getByLabel(label, { exact: true }).fill(value);
  return cell;
}
async function saveField(cell, label, id, expected = 200, inspectPending = false) {
  const response = page.waitForResponse(item => item.request().method() === 'PATCH' && new URL(item.url()).pathname === api + id + '/');
  const button = cell.locator('[data-action="save"]');
  if (inspectPending) await pendingSave(button, api + id + '/', 'PATCH');
  else await button.click();
  await acceptProductResponse(await response, expected, '字段保存响应不符合预期');
}
async function loginAccount(account) {
  const ctx = await browser.newContext({ locale: 'zh-CN', timezoneId: 'Asia/Shanghai' });
  await ctx.request.get(new URL('/api/auth/me/', base).href);
  const login = await request('POST', '/api/auth/login/', { username: account.username, password: account.password }, null, ctx);
  check(login.status === 200, '临时权限账号正常登录失败');
  return ctx;
}
async function main() {
  check(process.env.QA_ALLOW_REAL_DB_WRITE === 'I_UNDERSTAND', '缺少本任务专项真实写库授权');
  const state = process.env.PRODUCT_CATALOG_QA_STORAGE_STATE;
  check(state && fs.existsSync(state) && fs.existsSync(accountsPath), '缺少既有Session或本任务临时账号');
  check(!fs.existsSync(manifestPath), '已存在QA记录清单，拒绝覆盖');
  const accounts = JSON.parse(fs.readFileSync(accountsPath, 'utf8'));
  check(accounts.task === task && accounts.accounts.length === 2, '账号清单任务不符');
  base = new URL(process.env.PRODUCT_CATALOG_QA_BASE_URL || 'http://localhost:8080');
  check(['localhost', '127.0.0.1'].includes(base.hostname) && base.protocol === 'http:' && !base.username && !base.password && base.pathname === '/', '写QA只允许本机HTTP目标');
  fs.mkdirSync(evidence, { recursive: true }); saveReport();
  check(!fs.existsSync(temp), '浏览器临时路径已存在'); fs.mkdirSync(path.dirname(temp), { recursive: true }); fs.mkdirSync(temp); report.resources.created = true;
  process.env.TEMP = temp; process.env.TMP = temp; process.env.TMPDIR = temp;
  const executablePath = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
  check(executablePath, '没有现有可用浏览器');
  browser = await chromium.launch({ headless: true, executablePath, downloadsPath: temp });
  context = await browser.newContext({ storageState: state, viewport: { width: 1920, height: 1080 }, locale: 'zh-CN', timezoneId: 'Asia/Shanghai', serviceWorkers: 'block' });
  stage = 'session-permissions';
  const authenticated = await request('GET', '/api/auth/me/');
  const required = ['view', 'add', 'change'].map(action => `product_catalog.${action}_productcatalog`);
  if (authenticated.status !== 200 || !authenticated.body.authenticated || !required.every(permission => authenticated.body.user?.permissions?.includes(permission))) {
    const error = new Error('现有Session无效或缺少独立产品管理查看/新增/编辑权限；未创建业务清单，保留既有低权账号供主任务处理。');
    error.code = 'QA_BLOCKED'; throw error;
  }
  record('existing-session-has-required-permissions');
  context.on('page', opened => opened.on('pageerror', error => report.pageErrors.push(error.message)));
  await context.route('**/*', async route => {
    const req = route.request(), target = new URL(req.url()), pathname = target.pathname;
    if (['GET', 'HEAD'].includes(req.method())) return route.continue();
    const payload = req.postDataJSON();
    const allowed = target.origin === base.origin && ((pathname === api + 'names/' && req.method() === 'POST' && payload?.name?.startsWith(prefix))
      || (req.method() === 'PATCH' && manifest.name_ids.some(id => pathname === api + 'names/' + id + '/') && payload?.name?.startsWith(prefix))
      || (pathname === api && req.method() === 'POST' && manifest.name_ids.includes(payload?.name_id))
      || manifest.product_ids.some(id => pathname === api + id + '/' || pathname.startsWith(api + id + '/colors/')));
    if (allowed) return route.continue();
    report.unexpectedWrites.push({ method: req.method(), path: pathname }); return route.abort('blockedbyclient');
  });
  const opts = (await request('GET', api + 'options/')).body.data;
  check(opts.categories.length >= 34, '真实导入尚未完成');
  persist(); ownsResources = true;
  page = await context.newPage();
  await page.goto(new URL('/product-catalog', base).href, { waitUntil: 'networkidle' });
  await page.locator('.product-catalog-page').waitFor();
  const categorySelect = page.locator('.catalog-sidebar > .material-catalog-select');
  await page.waitForFunction(node=>!!node.getAttribute('data-model-value') && !node.querySelector('[role="combobox"]').disabled, await categorySelect.elementHandle());
  await exerciseDropdown(categorySelect, await categorySelect.getAttribute('data-model-value'), 'category');
  stage = 'ui-create-name';
  const name = prefix + '（完整长品名与多产品验收）'.repeat(5);
  await page.getByRole('button', { name: '新增品名', exact: true }).click();
  await page.getByLabel('新品名', { exact: true }).fill(name);
  await failedDraft(page.locator('[data-action="save-name"]'), api + 'names/', 'POST', page.getByLabel('新品名', { exact: true }), name);
  const newNameResponse = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === api + 'names/');
  await pendingSave(page.locator('[data-action="save-name"]'), api + 'names/', 'POST');
  const createdNameResponse = await newNameResponse;
  check(createdNameResponse.status() === 201, 'UI新增品名失败');
  const createdName = (await createdNameResponse.json()).data;
  rememberName(createdName);
  await page.getByText('暂无产品，可在下方新增。', { exact: true }).waitFor();
  await noExtraVerticalScroll('empty-products');
  await screenshot('empty-products'); record('ui-name-create-empty-products');
  // 空品名下先改名；避免随后改名刷新所有子产品版本，清理不以GET接管该变化。
  stage = 'ui-rename';
  await page.getByRole('button', { name: '编辑品名', exact: true }).click();
  const renamed = name + ' 原文尾空格 ';
  await page.getByLabel('品名', { exact: true }).fill(renamed);
  const renameResponse = page.waitForResponse(r => r.request().method() === 'PATCH' && new URL(r.url()).pathname === api + 'names/' + createdName.id + '/');
  await pendingSave(page.locator('.detail-heading [data-action="save"]'), api + 'names/' + createdName.id + '/', 'PATCH');
  const renamedResponse = await renameResponse; check(renamedResponse.status() === 200, '品名真实改名失败');
  rememberName((await renamedResponse.json()).data);
  check((await request('GET', api + 'names/' + createdName.id + '/')).body.data.name === renamed, '改名未保留原文');
  await page.locator(`.product-names [data-name-id="${createdName.id}"]`).filter({ hasText: renamed.trim() }).waitFor();
  record('real-name-rename-verbatim');
  stage = 'ui-create-product';
  await page.getByRole('button', { name: '新增产品', exact: true }).click();
  await page.getByLabel('新产品货号', { exact: true }).fill('QA-SAME');
  await page.getByLabel('新产品规格', { exact: true }).fill('规格一（原文 / 保留）');
  await exerciseDropdown(page.locator('[data-new-product] .material-catalog-select'), '常规', 'new-product-scale');
  await failedDraft(page.locator('[data-action="save-product"]'), api, 'POST', page.getByLabel('新产品规格', { exact: true }), '规格一（原文 / 保留）');
  const productResponse = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === api);
  await pendingSave(page.locator('[data-action="save-product"]'), api, 'POST');
  const pr = await productResponse; check(pr.status() === 201, 'UI新增产品失败');
  const first = (await pr.json()).data; rememberProduct(first);
  check(first.product_code === '' && first.unit === '' && first.colors.length === 1 && first.colors[0].value === '无颜色', '空编码/单单位/默认无颜色不符');
  let row = page.locator(`[data-product-id="${first.id}"]`); await row.waitFor();
  check(first.scale === '常规', '新增规模选择没有保存');
  await noExtraVerticalScroll('single-product');
  record('ui-product-create-empty-code-unit');
  stage = 'field-save';
  const longSpec = '完整规格（保留括号、空格与 /）'.repeat(12);
  const specCell = await editField(row, 'specification', '规格', longSpec);
  await saveField(specCell, '规格', first.id, 200, true); check((await read(first.id)).body.data.specification === longSpec, '规格未真实保存');
  const unitCell = await editField(row, 'unit', '单位', 'SET'); await saveField(unitCell, '单位', first.id);
  check((await read(first.id)).body.data.unit === 'SET', '单位不是单值SET');
  const itemCell = await editField(row, 'item_number', '货号', ' QA-SAME '); await saveField(itemCell, '货号', first.id);
  check((await read(first.id)).body.data.item_number === ' QA-SAME ', '货号未保留原文');
  await row.getByRole('button', { name: '编辑常规/定制', exact: true }).click();
  const scaleCell = row.locator('[data-field="scale"]');
  await exerciseDropdown(scaleCell.locator('.material-catalog-select'), '定制', 'edit-product-scale');
  const scalePath = new URL(api + first.id + '/', base).href;
  const failScale = async route => route.request().method() === 'PATCH' ? route.abort('failed') : route.fallback();
  await page.route(scalePath, failScale);
  try {
    await scaleCell.locator('[data-action="save"]').click();
    await scaleCell.locator('.product-catalog-field-error').waitFor();
    check(await scaleCell.locator('.material-catalog-select').getAttribute('data-model-value')==='定制','规模保存失败丢失选择');
    await scaleCell.getByRole('combobox').focus(); await settleVisual(scaleCell.locator('.el-select__wrapper'));
    const invalidStyle = await scaleCell.locator('.el-select__wrapper').evaluate(node=>{const s=getComputedStyle(node);return {border:s.borderColor,outline:s.outlineColor,style:s.outlineStyle,width:s.outlineWidth,offset:s.outlineOffset};});
    check(invalidStyle.border==='rgb(181, 51, 51)' && invalidStyle.style!=='none' && invalidStyle.outline==='rgb(56, 152, 236)' && invalidStyle.width==='2px' && invalidStyle.offset==='2px','错误选择器没有红边及蓝焦点圈');
    record('real-scale-error-keeps-value',{invalidStyle});
  } finally { await page.unroute(scalePath, failScale); }
  await saveField(scaleCell, '常规/定制', first.id, 200, true);
  check((await read(first.id)).body.data.scale === '定制', '编辑规模未真实保存');
  record('ui-fields-real-save');
  stage = 'ui-color-and-duplicate';
  await row.getByRole('button', { name: '添加颜色', exact: true }).click();
  await row.getByLabel('新颜色', { exact: true }).fill('QA红色');
  const colorLayout = await row.locator('[data-field="colors"]').evaluate(cell => {
    const bounds = cell.getBoundingClientRect(), controls = [...cell.querySelectorAll('.color-editor input,.color-editor button')].map(node => { const b = node.getBoundingClientRect(); return { x: b.x, y: b.y, right: b.right, bottom: b.bottom, height: b.height }; });
    return { bounds: { x: bounds.x, right: bounds.right }, controls };
  });
  check(colorLayout.controls.every(control => control.height === 32 && control.x >= colorLayout.bounds.x && control.right <= colorLayout.bounds.right) && colorLayout.controls.every(control => Math.abs(control.y - colorLayout.controls[0].y) < 1), '颜色输入/保存按钮超出本格或未同行');
  const colorResponse = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === api + first.id + '/colors/');
  await pendingSave(row.locator('[data-action="save-color"]'), api + first.id + '/colors/', 'POST'); await acceptProductResponse(await colorResponse, 200, 'UI添加颜色失败');
  check((await read(first.id)).body.data.colors.map(color=>color.value).join('|') === '无颜色|QA红色' && (await request('GET', api + '?name_id=' + createdName.id)).body.meta.total === 1, '添加颜色改变产品数量或丢失原颜色');
  await row.getByRole('button', { name: '添加颜色', exact: true }).click(); await row.getByLabel('新颜色', { exact: true }).fill('QA红色');
  const duplicate = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === api + first.id + '/colors/');
  await row.getByRole('button', { name: '保存颜色', exact: true }).click(); check((await duplicate).status() === 400, '重复颜色未明确拒绝');
  check(await row.getByLabel('新颜色', { exact: true }).inputValue() === 'QA红色', '失败颜色草稿丢失');
  await errorBubbles(row, row.getByLabel('新颜色', { exact: true }));
  await screenshot('duplicate-color-error'); record('duplicate-color-keeps-input');
  stage = 'stale-version';
  const current = await read(first.id); const external = await request('PATCH', api + first.id + '/', { unit: 'PCS' }, current.etag); check(external.status === 200, '并发前置更新失败');
  await row.getByLabel('新颜色', { exact: true }).fill('QA冲突草稿');
  const stale = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === api + first.id + '/colors/');
  await row.getByRole('button', { name: '保存颜色', exact: true }).click(); check((await stale).status() === 412, '旧版本没有拒绝');
  check(await row.getByLabel('新颜色', { exact: true }).inputValue() === 'QA冲突草稿', '版本冲突丢失输入');
  await screenshot('version-conflict');
  await row.getByRole('button', { name: '重新读取', exact: true }).click();
  await row.getByRole('button', { name: '保存颜色', exact: true }).waitFor({ state: 'visible' });
  const recovered = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === api + first.id + '/colors/');
  await row.getByRole('button', { name: '保存颜色', exact: true }).click(); await acceptProductResponse(await recovered, 200, '冲突重新读取后无法恢复');
  record('stale-version-recovery-keeps-input');
  // 保留一次真实重复颜色错误，与字段网络错误一起检查单气泡互斥。
  await row.locator('[data-action="add-color"]').click();
  await row.getByLabel('新颜色', { exact: true }).fill('QA红色');
  const duplicateAgain = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === api + first.id + '/colors/');
  await row.locator('[data-action="save-color"]').click(); check((await duplicateAgain).status() === 400, '重复颜色错误准备失败');
  stage = 'network-failure';
  const codeCell = await editField(row, 'product_code', '产品编码', 'QA AFTER FAILURE');
  const failWrite = async route => route.request().method() === 'PATCH' ? route.abort('failed') : route.fallback();
  await page.route('**/api/v1/product-catalog/' + first.id + '/', failWrite);
  await codeCell.getByRole('button', { name: '保存产品编码', exact: true }).click();
  await codeCell.locator('[role="alert"]').waitFor();
  check(await codeCell.getByLabel('产品编码', { exact: true }).inputValue() === 'QA AFTER FAILURE', '网络失败丢失输入');
  check(await row.locator('.product-catalog-field-error').count() === 2, '未准备两处真实字段错误');
  await errorBubbles(row, codeCell.getByLabel('产品编码', { exact: true }));
  await screenshot('network-save-failure'); await page.unroute('**/api/v1/product-catalog/' + first.id + '/', failWrite);
  await row.getByRole('button', { name: '取消添加颜色', exact: true }).click();
  await saveField(codeCell, '产品编码', first.id); record('network-failure-and-retry');
  stage = 'color-delete';
  const toDelete = row.getByRole('button', { name: '删除颜色QA红色', exact: true });
  await page.mouse.move(0, 0); await page.locator('.product-table-scroll').focus();
  check(await toDelete.evaluate(node => getComputedStyle(node).opacity) === '0', '颜色删除按钮默认没有隐藏');
  await toDelete.locator('..').hover();
  check(await toDelete.evaluate(node => getComputedStyle(node).opacity) === '1', '颜色悬停未显示删除按钮');
  const deleteGeometry = await toDelete.evaluate(node => { const b=node.getBoundingClientRect(), icon=node.querySelector('svg').getBoundingClientRect(); return { width:b.width,height:b.height,iconWidth:icon.width,iconHeight:icon.height,dx:Math.abs((b.left+b.right-icon.left-icon.right)/2),dy:Math.abs((b.top+b.bottom-icon.top-icon.bottom)/2) }; });
  check(deleteGeometry.width===32 && deleteGeometry.height===32 && deleteGeometry.iconWidth===16 && deleteGeometry.iconHeight===16 && deleteGeometry.dx<0.5 && deleteGeometry.dy<0.5,'颜色删除按钮/图标尺寸或居中不符');
  await page.mouse.move(0, 0); check(await toDelete.evaluate(node => getComputedStyle(node).opacity) === '0', '移开颜色后删除按钮未隐藏');
  await toDelete.focus();
  check(await toDelete.evaluate(node => getComputedStyle(node).opacity) === '1', '键盘聚焦未显示颜色删除按钮');
  const deleted = page.waitForResponse(r => r.request().method() === 'DELETE' && new URL(r.url()).pathname.startsWith(api + first.id + '/colors/'));
  await toDelete.click(); await acceptProductResponse(await deleted, 200, '颜色删除失败');
  check((await read(first.id)).body.data.colors.map(color=>color.value).join('|') === '无颜色|QA冲突草稿', '颜色删除未落库或误删其他颜色');
  check((await request('GET', api + '?name_id=' + createdName.id)).body.meta.total === 1,'删除颜色改变了产品数量');
  record('keyboard-color-delete', { deleteGeometry, colorLayout });
  stage = 'large-data';
  for (let index = 0; index < 51; index += 1) await addProduct(createdName.id, { specification: index === 0 ? '规格二' : '相同业务规格', unit: 'PCS' });
  for (let index = 0; index < 8; index += 1) { const version = await read(first.id); const added = await request('POST', api + first.id + '/colors/', { value: 'QA多颜色-' + (index + 1) }, version.etag); check(added.status === 200, '多颜色前置创建失败'); }
  await page.reload({ waitUntil: 'networkidle' });
  await page.locator(`[data-testid="product-names"] [data-name-id="${createdName.id}"]`).click();
  await page.locator(`[data-product-id="${first.id}"]`).waitFor();
  for (const viewport of [{ width: 1920, height: 1080 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport); await page.evaluate(() => document.fonts.ready);
    check(await page.locator('[data-product-id]').count() === 50, '第一页未显示50条产品');
    const firstPageIds = await page.locator('[data-product-id]').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('data-product-id')));
    check(await row.locator('[data-color-id]').count() === 10,'多个颜色未完整显示');
    check(await row.locator('[data-field="specification"] .field-value').textContent() === longSpec,'长规格文字被截断');
    check(await row.locator('.field-value,.product-color').evaluateAll(nodes=>nodes.every(node=>node.scrollWidth<=node.clientWidth+1)),'长字段或颜色超出自身容器');
    const geometry = await page.evaluate(() => { const rootNode = document.querySelector('.product-catalog-page'), scroll = document.querySelector('.product-table-scroll'), table = document.querySelector('.product-table'); return { documentX: document.documentElement.scrollWidth - innerWidth, documentY: document.documentElement.scrollHeight - innerHeight, rootWidth: rootNode.getBoundingClientRect().width, tableWidth: table.getBoundingClientRect().width, localScrollHeight: scroll.scrollHeight, localClientHeight: scroll.clientHeight, localScrollWidth: scroll.scrollWidth, localClientWidth: scroll.clientWidth }; });
    check(geometry.documentX <= 1 && geometry.documentY <= 1 && geometry.localScrollHeight > geometry.localClientHeight, '长内容没有正确局部滚动');
    check((geometry.localScrollWidth > geometry.localClientWidth + 1) === (geometry.tableWidth > geometry.localClientWidth - 8 + 1),'横向滚动与表格真实宽度不符');
    await screenshot(viewport.width + '-long-multicolor-many-products');
    const lastRow = page.locator('[data-product-id]').last();
    await lastRow.getByRole('button', {name:'编辑常规/定制',exact:true}).click();
    await exerciseDropdown(lastRow.locator('[data-field="scale"] .material-catalog-select'), '定制', `${viewport.width}-last-row-scale`);
    await lastRow.getByRole('button',{name:'取消编辑常规/定制',exact:true}).click();
    await page.locator('[data-action="add-product"]').scrollIntoViewIfNeeded();
    check(await page.locator('[data-action="add-product"]').isVisible(), '滚到底后新增入口不可见');
    const footer = await page.locator('.product-pagination').boundingBox();
    check(footer.y>=0 && footer.y+footer.height<=viewport.height+1,'分页被视口裁切');
    await page.getByRole('button', { name: '下一页产品', exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll('[data-product-id]').length === 2);
    const lastPageIds=await page.locator('[data-product-id]').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('data-product-id')));
    check(new Set([...firstPageIds,...lastPageIds]).size===52 && [...firstPageIds,...lastPageIds].every(id=>manifest.product_ids.includes(id)), '分页重复、缺失或混入未登记产品');
    await noExtraVerticalScroll(`${viewport.width}-two-products-last-page`);
    await screenshot(viewport.width + '-last-page');
    await page.getByRole('button', { name: '上一页产品', exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll('[data-product-id]').length === 50);
    record('large-data-scroll-pagination', { viewport, geometry });
  }
  const all = await request('GET', api + '?name_id=' + createdName.id + '&page_size=100');
  check(all.body.data.length === 52 && new Set(all.body.data.map(item => item.id)).size === 52, '相同业务字段记录被合并'); record('same-item-and-same-values-independent');
  stage = 'real-permissions-csrf';
  const detail = await read(first.id);
  const missingVersion = await request('PATCH', api + first.id + '/', { unit: 'TEST' }); check(missingVersion.status === 428, '缺版本未拒绝');
  const noCsrf = await context.request.patch(new URL(api + first.id + '/', base).href, { data: { unit: 'TEST' }, headers: { 'If-Match': detail.etag, Referer: base.origin + '/' } }); check(noCsrf.status() === 403, '缺CSRF未拒绝');
  for (const account of accounts.accounts) {
    const ctx = await loginAccount(account);
    try {
      const view = await request('GET', api, undefined, undefined, ctx); check(view.status === (account.mode === 'read' ? 200 : 403), '真实查看权限不符');
      const change = await request('PATCH', api + first.id + '/', { unit: 'TEST' }, detail.etag, ctx); check(change.status === 403, '低权限真实写请求未拒绝');
      const restrictedPage = await ctx.newPage(); await restrictedPage.goto(new URL('/product-catalog', base).href, { waitUntil: 'networkidle' });
      if (account.mode === 'read') {
        await restrictedPage.locator('.product-catalog-page').waitFor();
        check(await restrictedPage.locator('[data-action="add-name"],[data-action="add-product"],[data-action="edit"],[data-action="add-color"],.color-delete').count() === 0, '只读用户仍显示写入口');
      } else {
        await restrictedPage.getByText('无权查看产品管理',{exact:true}).waitFor();
        check(await restrictedPage.locator('[data-product-id],.product-names').count()===0,'无权限页面仍呈现产品数据');
      }
      const file = `${stamp}-write-permission-${account.mode}.png`; await restrictedPage.screenshot({ path: path.join(evidence, file), fullPage: true }); report.screenshots.push(file);
      record('real-permissions', { mode: account.mode, viewStatus: view.status, writeStatus: change.status });
    } finally { await ctx.close(); }
  }
  check((await read(first.id)).body.data.unit === detail.body.data.unit, '被拒绝的权限/CSRF请求改变了数据');
  check(report.unexpectedWrites.length === 0, '出现超出登记范围的页面写请求');
  check(report.pageErrors.length === 0, '页面出现未处理脚本异常');
  record('csrf-and-version-required'); report.status = 'PASS';
}
(async () => {
  try { await main(); }
  catch (error) { report.status = error.code === 'QA_BLOCKED' ? 'BLOCKED' : 'FAIL'; process.exitCode = 1; report.failure = { stage, message: error.message, stack: error.stack }; if (page && !page.isClosed()) try { await screenshot('failure'); } catch (shotError) { report.diagnosticError = shotError.message; } }
  finally {
    for (const release of pendingReleases) release();
    pendingReleases.clear();
    report.cleanupErrors = [];
    let browserClosed = !browser;
    try { if (browser) await browser.close(); browserClosed = true; }
    catch (error) { report.cleanupErrors.push({ stage: 'browser-close', message: error.message }); }
    if (ownsResources && browserClosed) {
      report.created = { nameIds: manifest.name_ids, productIds: manifest.product_ids };
      try {
        const cleanup = spawnSync('docker', ['compose', 'exec', '-T', '-e', 'QA_ALLOW_REAL_DB_WRITE=I_UNDERSTAND', '-e', 'PRODUCT_CATALOG_QA_ACTION=cleanup', 'backend', 'python', 'manage.py', 'shell'], { cwd: root, encoding: 'utf8', input: fs.readFileSync(path.join(root, 'qa/product_catalog_qa_resources.py'), 'utf8'), timeout: 60000 });
        report.databaseCleanup = { exitCode: cleanup.status, output: cleanup.stdout, errors: cleanup.stderr, executionError: cleanup.error?.message };
        check(cleanup.status === 0, '数据库资源清理失败，保留清单以便恢复');
        for (const filename of [manifestPath, accountsPath]) {
          try { fs.unlinkSync(filename); }
          catch (error) { report.cleanupErrors.push({ stage: 'credential-file', path: filename, message: error.message }); }
        }
        report.credentialsRemoved = !fs.existsSync(accountsPath) && !fs.existsSync(manifestPath);
      } catch (error) { report.cleanupErrors.push({ stage: 'database-cleanup', message: error.message }); }
    } else if (ownsResources) {
      report.cleanupErrors.push({ stage: 'database-cleanup', message: '无法确认浏览器已关闭，保留数据及清单，停止依赖清理。' });
    }
    if (report.resources.created && browserClosed) {
      try {
        check(path.dirname(temp) === path.join(root, '.tmp/product-catalog-20261016-' + task) && !fs.lstatSync(temp).isSymbolicLink() && fs.realpathSync(temp).toLowerCase() === temp.toLowerCase(), '浏览器清理路径不符');
        fs.rmSync(temp, { recursive: true }); report.resources.removed = !fs.existsSync(temp);
      } catch (error) { report.cleanupErrors.push({ stage: 'browser-files', path: temp, message: error.message }); }
    }
    if (report.cleanupErrors.length) { report.status = 'FAIL'; process.exitCode = 1; }
    report.finishedAt = new Date().toISOString();
    try { fs.mkdirSync(evidence, { recursive: true }); saveReport(); }
    catch (error) { report.status = 'FAIL'; process.exitCode = 1; console.error(JSON.stringify({ stage: 'save-cleanup-report', message: error.message, report })); }
    console.log(JSON.stringify({ qa_result_version: 1, status: report.status, not_covered: report.notCovered, checks: report.checks.length, report: reportPath, cleanup: (!ownsResources || report.databaseCleanup?.exitCode === 0) && (!report.resources.created || report.resources.removed) && !report.cleanupErrors.length, failure: report.failure?.message }));
  }
})();

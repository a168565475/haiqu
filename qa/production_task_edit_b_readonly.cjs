/**
 * 编辑 B：真实 Session / API 的 headless 只读检查。
 * 唯一允许的写请求为正常登录；业务请求不提交，页面临时修改最终丢弃。
 * 不保存账号、Cookie、完整 API 响应；browser_temp 已由本任务文档登记。
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('../src/frontend/node_modules/playwright-core');

const root = path.resolve(__dirname, '..');
const evidenceDir = path.join(root, 'output/production-task-edit-b-20261015');
const browserTemp = path.join(evidenceDir, 'browser_temp');
const base = new URL(process.env.TASK_EDIT_QA_BASE_URL || 'http://localhost:8080');
const username = process.env.TASK_EDIT_QA_USERNAME;
const password = process.env.TASK_EDIT_QA_PASSWORD;
const statePath = process.env.TASK_EDIT_QA_STORAGE_STATE;
const requestedId = process.env.TASK_EDIT_QA_TASK_ID || 'c0622b08-31a7-4dfa-9338-960e106e1151';
const viewports = [[1920, 1080], [1440, 900], [1075, 884], [390, 844]];
const report = {
  schemaVersion: 1, startedAt: new Date().toISOString(), status: 'RUNNING', mode: 'real-api-read-only',
  apiReads: [], checks: [], screenshots: [], blockedWrites: [], pageErrors: [], httpErrors: [], notCovered: [],
  resources: { browserTemp, created: false, browserClosed: false, removed: false, verifiedAbsent: false },
};
let browser;
let activePage;
let currentStage = 'preconditions';
let evidenceVerified = false;
let ownsTemp = false;
const previousTemp = { TEMP: process.env.TEMP, TMP: process.env.TMP, TMPDIR: process.env.TMPDIR };

function fail(code, message) { const error = new Error(message); error.code = code; error.safeQaMessage = true; throw error; }
function check(condition, code, message) { if (!condition) fail(code, message); }
function compact(value) { return String(value ?? '').replace(/\s+/g, ''); }
function digest(value) { return crypto.createHash('sha256').update(String(value)).digest('hex').slice(0, 16); }
function samePath(a, b) { const normalize = value => process.platform === 'win32' ? path.resolve(value).toLowerCase() : path.resolve(value); return normalize(a) === normalize(b); }
function safePath(url) { try { return new URL(url, base).pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, ':id'); } catch { return 'invalid-url'; } }
function safeErrorDetail(error) {
  let message = String(error?.message || error?.name || 'unknown');
  for (const secret of [username, password].filter(Boolean)) message = message.split(secret).join('[redacted]');
  return message.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, ':id').replace(/https?:\/\/[^\s)"']+/g, value => safePath(value)).replace(/(cookie|authorization|password|csrf)[^\n]*/gi, '$1 [redacted]').slice(0, 1600);
}
const sourceLocked = task => Boolean(task.sales_order_id || task.products.some(product => product.source_delivery_batch_line_id));
const terminal = task => ['COMPLETED', 'CANCELLED'].includes(task.status);
function moneyUnits(value) {
  const text = String(value ?? '');
  check(/^\d+(?:\.\d{1,4})?$/.test(text), 'MONEY_CONTRACT', '真实人民币金额不符合四位小数契约。');
  const [whole, fraction = ''] = text.split('.'); return BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'));
}
function money(value) { return (value / 10000n).toString() + '.' + String(value % 10000n).padStart(4, '0'); }
function quantity(products) {
  const totals = new Map();
  products.forEach(product => totals.set(product.unit_name, (totals.get(product.unit_name) || 0) + Number(product.quantity)));
  return [...totals].map(([unit, value]) => value.toLocaleString('zh-CN') + ' ' + unit).join(' / ');
}
async function getJson(context, route, kind) {
  let response;
  try { response = await context.request.get(new URL(route, base).href, { maxRedirects: 0 }); }
  catch { fail('API_UNREACHABLE', kind + '请求失败；未保存请求细节。'); }
  report.apiReads.push({ kind, status: response.status() });
  check(response.status() === 200, 'API_STATUS', kind + '未返回 200。');
  let body; try { body = await response.json(); } catch { fail('API_JSON', kind + '没有返回有效 JSON。'); }
  return { body, etag: response.headers().etag || '' };
}
async function authenticate(context) {
  let me = (await getJson(context, '/api/auth/me/', 'authentication-state')).body;
  if (statePath) {
    check(me.authenticated === true, 'SESSION_EXPIRED', '指定会话无效或已过期。');
    report.authentication = 'existing-session'; return me.user;
  }
  const csrf = (await context.cookies(base.origin)).find(cookie => cookie.name === 'csrftoken')?.value;
  check(Boolean(csrf), 'CSRF_MISSING', '认证初始化未取得 CSRF Cookie。');
  let response;
  try {
    response = await context.request.post(new URL('/api/auth/login/', base).href, {
      headers: { 'X-CSRFToken': csrf, Referer: base.origin + '/' }, data: { username, password }, maxRedirects: 0,
    });
  } catch { fail('LOGIN_REQUEST', '正常登录失败；未保存请求细节或凭据。'); }
  report.authentication = 'normal-session-csrf-login'; report.authenticationPostCount = 1;
  check(response.status() === 200, 'LOGIN_REJECTED', '正常登录未成功，请检查账号状态。');
  me = (await getJson(context, '/api/auth/me/', 'authenticated-state')).body;
  check(me.authenticated === true, 'LOGIN_NO_SESSION', '登录后没有有效 Session。');
  return me.user;
}
async function screenshot(page, name) {
  const uniqueName=name.replace(/\.png$/, '-'+report.startedAt.replace(/[:.]/g,'-')+'.png');
  await page.screenshot({ path: path.join(evidenceDir, uniqueName), fullPage: true }); report.screenshots.push(uniqueName);
}
async function loadPage(page, task) {
  await page.goto(new URL('/production-tasks/' + encodeURIComponent(task.id) + '/edit', base).href, { waitUntil: 'networkidle' });
  await page.locator('.production-task-edit-page .editor-layout').waitFor({ timeout: 25000 });
  await page.waitForFunction(() => document.querySelector('.production-task-edit-page')?.getAttribute('aria-busy') !== 'true');
  await page.evaluate(() => document.fonts.ready);
  check(await page.locator('.production-task-edit-page .el-result').count() === 0, 'LOAD_ERROR', '真实编辑页加载失败。');
}
async function expandAll(page) {
  for (const file of await page.locator('details.product-file').all()) if (!await file.evaluate(element => element.open)) await file.locator('summary').click();
}
async function fieldValues(page) {
  return page.locator('.task-sidebar').evaluate(sidebar => [...sidebar.querySelectorAll('label')].map(label => {
    const title = label.querySelector(':scope > span');
    if (!title) return null;
    const input = label.querySelector('.el-input__inner');
    const selected = [...label.querySelectorAll('.el-select__selected-item:not(.is-transparent)')].map(element => element.textContent.trim()).join('');
    return { label: title.textContent.replace(/[\s*＊]/g, ''), value: input ? input.value : selected };
  }).filter(Boolean));
}
async function checkFields(page, task) {
  const values = await fieldValues(page);
  const field = (names, expected) => {
    const row = values.find(value => names.includes(value.label));
    check(Boolean(row), 'TASK_FIELD_MISSING', '任务资料缺少字段：' + names[0]);
    check(compact(row.value) === compact(expected), 'TASK_FIELD_VALUE', '任务资料与真实 API 不一致：' + names[0]);
  };
  field(['生产任务单号'], task.task_number); field(['来源订单', '来源销售订单'], task.source_sales_order_number || '手动创建（未关联销售订单）');
  field(['业务员'], task.salesperson?.display_name || ''); field(['下单日期'], task.order_date);
  field(['预计交期', '交期日期'], task.delivery_date); field(['计划开工'], task.planned_start_date || ''); field(['计划完工'], task.planned_end_date || '');
  field(['生产批号'], task.production_batch_number || ''); field(['订单误差'], task.order_tolerance_percent || '0');
  field(['含税', '是否含税'], task.includes_tax ? '含税' : '不含税');
  if (task.includes_tax) field(['税率'], task.tax_rate ? task.tax_rate + '%' : '请选择税率');
  field(['返单', '是否返单'], task.is_repeat_order ? '是' : '否');
  field(['交货方式'], task.delivery_method === 'SPLIT' ? '分批交付' : '一次交付');
  field(['生产优先级', '优先级'], ({ URGENT:'紧急', HIGH:'高', LOW:'低' })[task.production_priority] || '普通');
  if (task.planner?.display_name) field(['计划员'], task.planner.display_name);
  if (!sourceLocked(task)) field(['产前样'], task.preproduction_sample_required ? '需要' : '不需要');
  if (!terminal(task)) {
    const followers = page.locator('.task-sidebar label').filter({ has:page.locator(':scope > span', {hasText:/^跟单员\s*\*?$/}) });
    await followers.locator('.el-select').click();
    const dropdown=page.locator('.el-select-dropdown:visible'); await dropdown.waitFor({state:'visible'});
    if (task.followers?.length) await dropdown.locator('[role="option"][aria-selected="true"]').first().waitFor();
    const selected = await dropdown.locator('[role="option"][aria-selected="true"]').allTextContents();
    report.lastFieldCheck={field:'followers',expectedCount:task.followers?.length || 0,selectedCount:selected.length};
    check(JSON.stringify(selected.map(compact).sort()) === JSON.stringify((task.followers || []).map(person => compact(person.display_name)).sort()), 'FOLLOWERS_VALUE', '跟单员真实多选回填不完整。');
    await page.keyboard.press('Escape');
  }
  check(compact(await page.locator('.heading-title').innerText()).includes(compact(task.task_number)), 'TASK_NUMBER', '标题未显示真实任务号。');
  const files = page.locator('details.product-file');
  check(await files.count() === task.products.length, 'PRODUCT_COUNT', '产品档案数量与真实 API 不一致。');
  for (let index = 0; index < task.products.length; index++) {
    const product = task.products[index], file = files.nth(index);
    check(await file.getAttribute('data-product-id') === product.id, 'PRODUCT_ID', '产品档案顺序或真实 ID 不一致。');
    const name = product.customer_product_name || product.product_name;
    const text = compact(await file.locator('.product-fields').innerText());
    for (const value of [name, product.item_number, product.customer_color || product.color_name || product.color_code, product.customer_specification || product.specification, product.material].filter(Boolean)) {
      check(text.includes(compact(value)), 'PRODUCT_FIELD_VALUE', '产品静态资料与真实 API 不一致：第 ' + (index + 1) + ' 项。');
    }
    const productionQuantity = file.locator('input[aria-label$="本次生产量"]');
    check(await productionQuantity.inputValue() === String(product.quantity), 'QUANTITY_VALUE', '本次生产量未回填真实值。');
    const price = file.locator('input[aria-label="人民币单价"]');
    if (await price.count()) check(await price.inputValue() === String(product.local_unit_price), 'PRICE_VALUE', '人民币单价未回填真实值。');
    else check(compact(await file.locator('.price-fields').innerText()).includes(compact(product.local_unit_price)), 'PRICE_LOCKED_VALUE', '来源锁定单价缺失。');
    check(await file.locator('[aria-label="包装要求"]').inputValue() === (product.packaging_method || ''), 'PACKAGING_VALUE', '包装要求未完整回填。');
    check(await file.locator('[aria-label="产品生产要求"]').inputValue() === (product.special_requirements || ''), 'REQUIREMENTS_VALUE', '产品生产要求未完整回填。');
    const imageSources = await file.locator('.product-media img').evaluateAll(elements => elements.map(element => element.getAttribute('src') || ''));
    for (const image of product.images || []) check(imageSources.some(source => source.includes('/production-tasks/' + task.id + '/business-files/' + image.id + '/')), 'IMAGE_PATH', '产品图片未使用当前任务真实业务文件路径。');
    if (product.images?.length) {
      await file.locator('.product-media img').first().waitFor();
      await page.waitForFunction(id => [...document.querySelectorAll('details.product-file')].find(element => element.getAttribute('data-product-id') === id)?.querySelector('.product-media img')?.complete, product.id);
      check(await file.locator('.product-media img').evaluateAll(images => images.every(image => image.complete && image.naturalWidth > 0)), 'IMAGE_LOAD', '真实产品图片未成功加载。');
    } else check((await file.locator('.product-media').innerText()).includes('暂无产品图片'), 'IMAGE_EMPTY', '无真实图片时缺少空状态。');
  }
  const summary = compact(await page.locator('.edit-summary').innerText()).replaceAll(',', '');
  const expectedAmount = money(task.products.reduce((sum, product) => sum + moneyUnits(product.local_total_amount), 0n));
  check(summary.includes(expectedAmount), 'TOTAL_AMOUNT', '人民币合计与真实 API 不一致。');
  check(summary.includes(compact(quantity(task.products)).replaceAll(',', '')), 'TOTAL_QUANTITY', '按单位汇总与真实 API 不一致。');
}
async function measure(page, width) {
  const result = await page.locator('.production-task-edit-page').evaluate(rootNode => {
    const rect = element => { const r = element.getBoundingClientRect(); return { x:r.x, y:r.y, width:r.width, height:r.height, right:r.right, bottom:r.bottom }; };
    const visible = element => {
      const closed = element.closest('details:not([open])');
      return (!closed || element === closed || element.tagName === 'SUMMARY') && element.getClientRects().length > 0 && getComputedStyle(element).visibility !== 'hidden';
    };
    const sides = style => ['Top','Right','Bottom','Left'].map(side => ({ side, width:style['border'+side+'Width'], color:style['border'+side+'Color'] }));
    const main = rootNode.closest('.erp-layout__main'), layout = rootNode.querySelector('.editor-layout');
    const sidebar = rootNode.querySelector('.task-sidebar'), content = rootNode.querySelector('.editor-main');
    const cards = [...rootNode.querySelectorAll('.edit-summary,.task-sidebar,.editor-main > section,.product-file')].filter(visible).map(element => ({ className:element.className, borders:sides(getComputedStyle(element)), shadow:getComputedStyle(element).boxShadow }));
    const summaries = [...rootNode.querySelectorAll('.product-summary')].map(element => ({ open:element.parentElement.open, borders:sides(getComputedStyle(element)) }));
    const controls = [...rootNode.querySelectorAll('.el-input__wrapper,.el-select__wrapper,.el-button')].filter(element => visible(element) && !element.closest('.w-e-bar')).map(element => ({ className:element.className, height:rect(element).height, border:getComputedStyle(element).borderWidth, shadow:getComputedStyle(element).boxShadow }));
    const headingStyle = getComputedStyle(rootNode.querySelector('h1'));
    const visual = { heading:{fontFamily:headingStyle.fontFamily,fontSize:headingStyle.fontSize,lineHeight:headingStyle.lineHeight}, tags:[...rootNode.querySelectorAll('.task-status')].filter(visible).map(rect), photos:[...rootNode.querySelectorAll('.product-media .product-image.large')].filter(visible).map(element => ({...rect(element), imageFit:element.querySelector('img') ? getComputedStyle(element.querySelector('img')).objectFit : null})), openProducts:rootNode.querySelectorAll('.product-file[open]').length, textareas:[...rootNode.querySelectorAll('.pack-fields textarea')].filter(visible).map(rect), toolbar:[...rootNode.querySelectorAll('.requirements-field .w-e-bar-item button')].map(button=>({key:button.getAttribute('data-menu-key'),height:rect(button).height})) };
    const clipped = [...rootNode.querySelectorAll('.product-file')].filter(visible).flatMap(file => {
      const bounds = rect(file);
      return [...file.querySelectorAll('.product-summary,button,.el-input,.el-textarea,small')].filter(visible).filter(element => { const r=rect(element); return r.x < bounds.x - 1 || r.right > bounds.right + 1; }).map(element => ({ className:element.className, tag:element.tagName }));
    });
    return { documentOverflow:document.documentElement.scrollWidth > innerWidth + 1, mainOverflow:main ? main.scrollWidth > main.clientWidth + 1 : false, mainPadding:main ? getComputedStyle(main).padding : null, shell:{main:main?rect(main):null,header:document.querySelector('.erp-layout__header')?rect(document.querySelector('.erp-layout__header')):null,rail:document.querySelector('.erp-layout__sidebar')?rect(document.querySelector('.erp-layout__sidebar')):null}, gap:getComputedStyle(layout).gap, sidebar:rect(sidebar), content:rect(content), scheduleBorders:sides(getComputedStyle(rootNode.querySelector('.task-schedule'))), cards, summaries, controls, visual, clipped, root:rect(rootNode), background:getComputedStyle(rootNode).backgroundColor };
  });
  report.lastMeasurement = {stage:currentStage,width,result};
  check(!result.documentOverflow && !result.mainOverflow, 'HORIZONTAL_OVERFLOW', '整页或主工作区横向溢出。');
  check(result.shell.main && Math.abs(result.root.x-result.shell.main.x-14)<1 && Math.abs(result.shell.main.right-result.root.right-14)<1,'CONTENT_PADDING','内容左右14px边距未保持或被重复叠加。');
  check(result.shell.header?.height===64 && result.shell.rail?.width===80,'SHELL_SIZE','现有壳层不是64px顶栏和80px侧栏。');
  check(result.gap === '14px', 'LAYOUT_GAP', '资料栏与产品栏间距不是 14px。');
  if (width > 1100) check(Math.abs(result.sidebar.width - 380) < 1 && Math.abs(result.content.x - result.sidebar.right - 14) < 1, 'LEFT_COLUMN', '桌面左栏不是 380px 或栏距不符。');
  else check(result.content.y >= result.sidebar.bottom + 13, 'SMALL_WINDOW_LAYOUT', '小窗口未纵向堆叠。');
  for(const border of result.scheduleBorders){const separator=width>650&&width<=1100?'Left':'Top';check(border.width===(border.side===separator?'1px':'0px'),'SCHEDULE_BORDER','生产安排区域存在重复外框或缺少内部单线分隔：'+border.side);}
  for (const card of result.cards) for (const border of card.borders) check(border.width === '1px' && border.color === 'rgb(221, 214, 201)', 'CARD_BORDER', '卡片四边应为 1px #DDD6C9：' + card.className + '/' + border.side);
  for (const summary of result.summaries) for (const border of summary.borders) check(border.width === (summary.open && border.side === 'Bottom' ? '1px' : '0px'), 'SUMMARY_BORDER', '产品标题与外框边界叠加。');
  for (const control of result.controls) {
    check(Math.abs(control.height - 32) < 1, 'CONTROL_HEIGHT', '页面控件高度不是 32px：' + control.className);
    if (control.className.includes('__wrapper')) check(control.border === '0px' || control.shadow === 'none', 'CONTROL_DOUBLE_BORDER', '输入控件同时绘制实线边框与阴影边框。');
  }
  check(result.clipped.length === 0, 'PRODUCT_CLIPPED', '产品字段或操作存在横向裁切。');
  const titleSize = ['34px','44px'];
  check(result.visual.heading.fontSize === titleSize[0] && result.visual.heading.lineHeight === titleSize[1] && result.visual.heading.fontFamily.includes('Noto Serif SC'), 'HEADING_STYLE', '标题字体/字号/行高与确认原型不一致。');
  check(result.visual.tags.every(tag => Math.abs(tag.height - 24) < 1), 'STATUS_TAG_SIZE', '状态 Tag 高度不是 24px。');
  check(result.visual.photos.length===result.visual.openProducts && result.visual.photos.every(photo => Math.abs(photo.width - 118) < 1 && Math.abs(photo.height - 98) < 1 && (!photo.imageFit || photo.imageFit === 'contain')), 'PHOTO_SIZE', '产品主图不是 118×98px 等比完整展示，或实际主图DOM缺失。');
  check(result.visual.textareas.every(textarea => Math.abs(textarea.height - 78) < 1), 'TEXTAREA_SIZE', '产品文本域高度不是 78px。');
  check(JSON.stringify(result.visual.toolbar.map(button=>button.key).sort())===JSON.stringify(['bold','bulletedList','italic']) && result.visual.toolbar.every(button=>button.height===32),'RICH_TOOLBAR','生产要求工具条未严格限制为3个32px格式按钮。');
  return result;
}
async function folding(page, task) {
  const files = page.locator('details.product-file');
  check(await files.count() === task.products.length, 'PRODUCT_COUNT', '产品档案数量不符。');
  check(await page.locator('details.product-file[open]').count() === (task.products.length ? 1 : 0), 'FIRST_OPEN', '默认没有只展开首个产品。');
  if (!task.products.length) { report.notCovered.push('主任务没有真实产品，折叠和产品编辑未覆盖。'); return; }
  check(await files.first().evaluate(element => element.open), 'FIRST_OPEN', '默认展开的不是首个产品。');
  const summary = files.first().locator('summary'); await summary.click();
  check(!await files.first().evaluate(element => element.open), 'COLLAPSE', '点击标题未收起。');
  await summary.focus(); await summary.press('Enter'); check(await files.first().evaluate(element => element.open), 'KEYBOARD_ENTER', 'Enter 未展开产品。');
  await summary.press('Space'); check(!await files.first().evaluate(element => element.open), 'KEYBOARD_SPACE', 'Space 未收起产品。');
  await expandAll(page);
}
async function bottom(page) {
  await page.locator('.save-bar').scrollIntoViewIfNeeded();
  const result = await page.locator('.production-task-edit-page').evaluate(rootNode => {
    const main = rootNode.closest('.erp-layout__main'); if (main) main.scrollTop = main.scrollHeight;
    const footer = rootNode.querySelector('.save-bar').getBoundingClientRect();
    const last = rootNode.querySelector('.comparison-card .impact-note') || rootNode.querySelector('.editor-main > section:last-child');
    return { footerBottom:footer.bottom, footerTop:footer.top, boundary:main ? main.getBoundingClientRect().bottom : innerHeight, lastBottom:last?.getBoundingClientRect().bottom, atEnd:!main || main.scrollTop + main.clientHeight >= main.scrollHeight - 2 };
  });
  check(result.atEnd && result.footerBottom <= result.boundary + 1, 'BOTTOM_UNREACHABLE', '保存操作栏不能完整滚动到达。');
  if (result.lastBottom !== undefined) check(result.lastBottom <= result.footerTop + 1, 'FOOTER_OVERLAP', '保存操作栏遮挡末尾说明。');
  return result;
}
async function comparisonTable(page, width) {
  const table = page.locator('.comparison-table');
  await table.scrollIntoViewIfNeeded();
  const geometry = await table.evaluate(element => {
    const borders = style => ['Top','Right','Bottom','Left'].map(side => ({side,width:style['border'+side+'Width'],color:style['border'+side+'Color']}));
    const item = node => {const style=getComputedStyle(node),range=document.createRange();range.selectNodeContents(node);const lines=new Set([...range.getClientRects()].filter(rect=>rect.width>0&&rect.height>0).map(rect=>Math.round(rect.top)));return {tag:node.tagName,height:node.getBoundingClientRect().height,textLines:lines.size,borders:borders(style),background:style.backgroundColor,padding:style.padding,pseudo:['::before','::after'].map(pseudo=>{const computed=getComputedStyle(node,pseudo);return {pseudo,content:computed.content,borders:borders(computed)};})};};
    return {wrapper:item(element.parentElement),table:item(element),head:[...element.querySelectorAll('thead th')].map(item),rows:[...element.querySelectorAll('tbody tr')].map(row=>({height:row.getBoundingClientRect().height,cells:[...row.cells].map(item)})),firstRow:item(element.querySelector('tbody tr')),lastRow:item(element.querySelector('tbody tr:last-child'))};
  });
  report.lastMeasurement = {stage:currentStage,width,comparison:geometry};
  for (const side of geometry.wrapper.borders) check(side.width==='1px' && side.color==='rgb(221, 214, 201)','COMPARISON_OUTER_BORDER','变更对照表外框四边不是单层 1px 暖灰边。');
  for (const side of geometry.table.borders) check(side.width==='0px','COMPARISON_TABLE_BORDER','变更表与容器重复绘制外框。');
  const allCells=[...geometry.head,...geometry.rows.flatMap(row=>row.cells)];
  for (const cell of allCells) for (const border of cell.borders.filter(side=>side.side!=='Bottom')) check(border.width==='0px','COMPARISON_CELL_BORDER','变更表首末列或单元格叠加外边线。');
  for (const head of geometry.head) check(Math.abs(head.height-44)<1 && head.background==='rgb(240, 234, 223)' && head.borders.find(side=>side.side==='Bottom').width==='1px','COMPARISON_HEADER','变更对照表表头高度/底色/分隔线不符。');
  geometry.rows.forEach((row,index)=>{
    row.wrapped=row.cells.some(cell=>cell.textLines>1);
    check(row.wrapped ? row.height>=33 : Math.abs(row.height-34)<1,'COMPARISON_ROW_HEIGHT','变更对照表单行内容应34px，换行内容至少34px；视口 '+width+'，第 '+(index+1)+' 行实际 '+row.height+'px，换行='+row.wrapped+'。');
    row.cells.forEach(cell=>check(cell.borders.find(side=>side.side==='Bottom').width===(index===geometry.rows.length-1?'0px':'1px'),'COMPARISON_LAST_ROW','变更表末行或内部横向分隔线重复/缺失。'));
  });
  for (const node of [geometry.wrapper,geometry.table,geometry.firstRow,geometry.lastRow,...allCells]) for (const pseudo of node.pseudo) if(!['none','normal'].includes(pseudo.content)) check(pseudo.borders.every(border=>border.width==='0px'),'COMPARISON_PSEUDO_BORDER','变更对照表伪元素叠加边框。');
  await table.locator('tbody tr').first().hover();
  const hovered=await table.locator('tbody tr').first().locator('td').evaluateAll(cells=>cells.map(cell=>getComputedStyle(cell).backgroundColor));
  check(hovered.every(color=>color==='rgb(255, 246, 234)'),'COMPARISON_HOVER','变更对照表悬停底不是 #FFF6EA。');
  await screenshot(page,'edit-'+width+'-comparison-hover.png');
  await page.mouse.move(0,0);
  return {...geometry,hovered};
}
async function temporaryEdit(page, task, width) {
  if (terminal(task) || !task.products.length) { report.notCovered.push('主任务终态或没有产品，页面临时编辑未覆盖。'); return { status:'NOT_COVERED' }; }
  const first = task.products[0], file = page.locator('details.product-file').first();
  const input = file.locator('input[aria-label$="本次生产量"]'), original = await input.inputValue();
  const current = Number(original), maximum = Number(first.max_production_quantity);
  const changed = sourceLocked(task) && Number.isFinite(maximum) && current >= maximum ? Math.max(1, current - 1) : current + 1;
  check(changed !== current, 'QUANTITY_SAMPLE', '真实产品没有安全的页面数量调整空间。');
  await input.fill(String(changed)); await input.blur();
  const batch = page.locator('.task-sidebar input[aria-label="生产批号"]'), originalBatch=await batch.inputValue();
  await batch.fill(originalBatch.slice(0,90)+'-QA'); await batch.blur();
  const comparison = page.locator('.comparison-table'); await comparison.waitFor();
  const rows = await comparison.locator('tbody tr').allTextContents();
  check(rows.some(text => compact(text).includes(compact(original + ' ' + first.unit_name)) && compact(text).includes(compact(changed + ' ' + first.unit_name))), 'CHANGE_COMPARISON', '临时数量修改未显示前后对照。');
  await file.locator('summary').click(); await file.locator('summary').click();
  check(await input.inputValue() === String(changed), 'EDIT_RETAINED', '产品收起再展开丢失临时修改。');
  const expectedAmount = task.products.reduce((sum, product, index) => sum + (index === 0 ? moneyUnits(first.local_unit_price) * BigInt(changed) : moneyUnits(product.local_total_amount)), 0n);
  const summary = compact(await page.locator('.edit-summary').innerText()).replaceAll(',', '');
  check(summary.includes(money(expectedAmount)), 'EDIT_TOTAL', '临时修改后人民币合计计算不正确。');
  check(await page.locator('.save-bar').getByRole('button', { name:'保存修改', exact:true }).isEnabled(), 'DIRTY_SAVE', '临时修改后保存按钮未启用。');
  const tableGeometry=await comparisonTable(page,width);
  await screenshot(page, 'edit-'+width+'-local-change.png');
  await batch.fill(originalBatch); await batch.blur();
  await input.fill(original); await input.blur();
  check(await page.locator('.save-bar').getByRole('button', { name:'保存修改', exact:true }).isDisabled(), 'RESTORE_CLEAN', '恢复真实原值后页面仍有虚假待保存状态。');
  return { status:'PASS', quantityChange:true, comparison:tableGeometry, collapseRetained:true, restored:true, submitted:false };
}
async function productDialog(page, task, options, width) {
  const editable = page.locator('.product-file').getByRole('button', { name:'编辑产品', exact:true });
  let button;
  for (const candidate of await editable.all()) if (await candidate.isVisible() && await candidate.isEnabled()) { button = candidate; break; }
  if (!button) { report.notCovered.push('真实主任务没有可编辑手动产品，选品弹窗未覆盖。'); return { status:'NOT_COVERED' }; }
  const productId = await button.locator('xpath=ancestor::details').getAttribute('data-product-id');
  const product = task.products.find(item => item.id === productId);
  await button.click();
  const dialog = page.locator('.el-dialog').filter({ has:page.locator('.product-detail-editor') }); await dialog.waitFor({ state:'visible' });
  const rowCount = await dialog.locator('.product-detail-editor tbody tr:not(:has(td[colspan]))').count();
  check(rowCount === product.details.length, 'DETAIL_ROWS', '生产明细没有完整使用真实产品配置。');
  if (!rowCount) check((await dialog.locator('.product-detail-editor .empty-products').innerText()).includes('暂无生产明细'),'DETAIL_EMPTY','真实空生产明细缺少说明。');
  const descriptions = await dialog.locator('.product-detail-editor tbody tr input.el-input__inner').evaluateAll(inputs => inputs.map(input => input.value));
  check(descriptions.every((value, index) => value === (product.details[index]?.description || '')), 'DETAIL_VALUES', '生产明细描述未完整回填。');
  check(await dialog.getByRole('tab', { name:'选择已有产品', exact:true }).count() === 1, 'PICKER_TAB', '缺少真实产品选择入口。');
  await dialog.getByRole('tab', { name:'选择已有产品', exact:true }).click();
  check(await dialog.locator('.identity-zone').count() === 1, 'PICKER_BODY', '真实产品选择组件未呈现。');
  check(await dialog.locator('.entry-error:visible').count() === 0, 'PICKER_ERROR', '真实选品组件加载错误。');
  const picked = await dialog.locator('.picked').innerText();
  check(!/undefined|null/.test(picked), 'PICKED_NUMBER', '产品选择结果包含未回填的品号。');
  const imageSelector='.image-row .product-image img';
  if (product.images?.length) await dialog.locator(imageSelector).waitFor({state:'attached'});
  if (await dialog.locator(imageSelector).count()) await page.waitForFunction(selector=>[...document.querySelectorAll(selector)].every(image=>image.complete),'.production-product-editor '+imageSelector);
  const images=await dialog.locator(imageSelector).evaluateAll(nodes=>nodes.map(image=>({source:image.currentSrc||image.src,complete:image.complete,naturalWidth:image.naturalWidth,naturalHeight:image.naturalHeight,width:image.getBoundingClientRect().width,height:image.getBoundingClientRect().height})));
  const imageEvidence=images.map(image=>({...image,source:safePath(image.source),queryPresent:Boolean(new URL(image.source,base).search)}));
  report.lastMeasurement={stage:currentStage,width,dialogImages:imageEvidence,imageResponses:report.imageResponses||[]};
  check(!product.images?.length || images.length>0,'DIALOG_IMAGE_MISSING','真实产品有主图，但产品窗口主图DOM缺失。');
  check(images.every(image=>image.complete && image.naturalWidth>0 && image.naturalHeight>0),'DIALOG_IMAGE_LOAD','产品窗口主图未成功解码；详见dialogImages与imageResponses。');
  const geometry = await dialog.evaluate(element => {
    const r=element.getBoundingClientRect(), header=element.querySelector('.app-window-dialog__header'), footer=element.querySelector('.app-window-dialog__footer'), title=element.querySelector('.el-dialog__title'), body=element.querySelector('.app-window-dialog__body');
    const border=getComputedStyle(element), titleStyle=getComputedStyle(title);
    const controls=[...element.querySelectorAll('.el-button,.el-input__wrapper,.el-select__wrapper,.app-window-dialog__actions button,[role="tab"],.quantity-control')].filter(control=>control.getClientRects().length && (!control.closest('.quantity-control') || control.matches('.quantity-control'))).map(control=>({className:control.className,height:control.getBoundingClientRect().height}));
    const fileButtons=[...element.querySelectorAll('.product-detail-editor input[type="file"]')].map(input=>({height:getComputedStyle(input,'::file-selector-button').height}));
    return { left:r.left,right:r.right,top:r.top,bottom:r.bottom,viewportWidth:innerWidth,viewportHeight:innerHeight,scrollWidth:element.scrollWidth,clientWidth:element.clientWidth,borders:['Top','Right','Bottom','Left'].map(side=>({side,width:border['border'+side+'Width'],color:border['border'+side+'Color']})),radius:border.borderRadius,padding:border.padding,bodyPadding:getComputedStyle(body).padding,footerPadding:getComputedStyle(footer).padding,title:{fontSize:titleStyle.fontSize,lineHeight:titleStyle.lineHeight,fontWeight:titleStyle.fontWeight},headerHeight:header.getBoundingClientRect().height,headerTop:header.getBoundingClientRect().top,footerTop:footer.getBoundingClientRect().top,footerBottom:footer.getBoundingClientRect().bottom,controls,fileButtons};
  });
  report.lastMeasurement={stage:currentStage,width,dialog:geometry};
  check(geometry.left >= 16 && geometry.right <= geometry.viewportWidth - 16 && geometry.top >= 16 && geometry.bottom <= geometry.viewportHeight - 16, 'DIALOG_BOUNDS', '产品弹窗四边安全距离不足16px：left='+geometry.left+'，right='+(geometry.viewportWidth-geometry.right)+'，top='+geometry.top+'，bottom='+(geometry.viewportHeight-geometry.bottom)+'。');
  check(geometry.scrollWidth <= geometry.clientWidth + 1, 'DIALOG_OVERFLOW', '产品弹窗整体横向溢出。');
  check(geometry.borders.every(border=>border.width==='1px'&&border.color==='rgb(221, 214, 201)'),'DIALOG_BORDER','产品弹窗四边不是单层 1px #DDD6C9。');
  check(geometry.padding==='0px' && geometry.radius==='5px','DIALOG_FRAME','产品弹窗根节点间距或圆角不符合规范。');
  check(geometry.bodyPadding==='16px' && geometry.footerPadding==='12px 24px','DIALOG_PADDING','当前产品窗口内容/底部间距与16px、12px24px规范不一致。');
  check(Math.abs(geometry.headerHeight-44)<1 && geometry.title.fontSize==='16px' && geometry.title.lineHeight==='22px' && geometry.title.fontWeight==='600','DIALOG_TITLE','弹窗标题栏须44px，标题16/22px与600字重。');
  check(geometry.controls.every(control=>Math.abs(control.height-32)<1),'DIALOG_CONTROLS','产品弹窗单行控件或按钮不是32px。');
  check(geometry.fileButtons.every(button=>button.height==='32px'),'DIALOG_FILE_BUTTON','生产明细原生文件选择按钮不是32px。');
  await screenshot(page, 'edit-' + width + '-product-dialog.png');
  await dialog.locator('.app-window-dialog__body').evaluate(element=>{element.scrollTop=element.scrollHeight;});
  const end=await dialog.evaluate(element=>{
    const body=element.querySelector('.app-window-dialog__body'),header=element.querySelector('.app-window-dialog__header'),footer=element.querySelector('.app-window-dialog__footer'),last=element.querySelector('.product-detail-editor tbody tr:last-child');
    return {headerTop:header.getBoundingClientRect().top,footerTop:footer.getBoundingClientRect().top,footerBottom:footer.getBoundingClientRect().bottom,lastRowBottom:last.getBoundingClientRect().bottom,bodyBottom:body.getBoundingClientRect().bottom,atEnd:body.scrollTop+body.clientHeight>=body.scrollHeight-2};
  });
  check(end.atEnd && end.lastRowBottom<=end.bodyBottom+1 && end.lastRowBottom<=end.footerTop+1,'DIALOG_LAST_ROW','生产明细末行不能滚动到达或被底栏遮挡。');
  check(Math.abs(end.headerTop-geometry.headerTop)<1 && Math.abs(end.footerTop-geometry.footerTop)<1 && Math.abs(end.footerBottom-geometry.footerBottom)<1,'DIALOG_FIXED_BARS','产品弹窗内容滚动时标题/底栏发生位移。');
  await screenshot(page, 'edit-' + width + '-production-details.png');
  const cancel = dialog.getByRole('button', { name:'取消', exact:true });
  if (await cancel.count()) await cancel.last().click(); else await dialog.getByRole('button', { name:/close|关闭/i }).first().click();
  await dialog.waitFor({ state:'hidden' });
  check(await page.locator('.save-bar').getByRole('button', { name:'保存修改', exact:true }).isDisabled(), 'DIALOG_CANCEL', '取消产品弹窗后修改污染了主表单。');
  return { status:'PASS', detailCount:rowCount, configuredTemplates:options.detail_template?.length ?? null, cancelled:true, pickedNumberDefined:true,images:imageEvidence,geometry,end };
}
async function localProductApply(page,task) {
  const candidates=await page.locator('.product-file').getByRole('button',{name:'编辑产品',exact:true}).all();
  let button; for (const candidate of candidates) if(await candidate.isVisible() && await candidate.isEnabled()){button=candidate;break;}
  if(!button){report.notCovered.push('没有可编辑的真实手动产品，产品弹窗本地应用链路未覆盖。');return {status:'NOT_COVERED'};}
  const productId=await button.locator('xpath=ancestor::details').getAttribute('data-product-id');
  const product=task.products.find(item=>item.id===productId);
  await button.click();
  const dialog=page.locator('.production-product-editor.app-window-dialog');await dialog.waitFor({state:'visible'});
  const material=dialog.locator('input[aria-label="材质"]'), original=await material.inputValue();
  const changed=original.slice(0,1900)+' / QA本地验收';
  await material.fill(changed);await dialog.locator('.app-window-dialog__footer').getByRole('button',{name:'保存产品信息',exact:true}).click();
  await dialog.waitFor({state:'hidden'});
  const file=page.locator('details.product-file[data-product-id="'+productId+'"]');
  check((await file.locator('.product-fields').innerText()).includes(changed),'PRODUCT_APPLY_VALUE','外层保存产品信息未更新本地档案材质。');
  check((await page.locator('.comparison-table').innerText()).includes('产品资料已修改'),'PRODUCT_APPLY_CHANGE','外层保存产品信息未生成本地变更对照。');
  check(report.blockedWrites.length===0,'PRODUCT_APPLY_WRITE','产品弹窗本地应用触发了业务写请求，已拦截。');
  await screenshot(page,'edit-1920-product-local-apply.png');
  await page.reload({waitUntil:'networkidle'});await page.locator('.production-task-edit-page .editor-layout').waitFor({timeout:25000});
  await expandAll(page);
  check(compact(await page.locator('details.product-file[data-product-id="'+productId+'"] .product-fields').innerText()).includes(compact(product.material || '—')),'PRODUCT_RELOAD_VALUE','重载后真实产品材质未恢复。');
  check(!(await page.locator('.product-fields').allTextContents()).some(text=>text.includes('QA本地验收')),'PRODUCT_LOCAL_DISCARDED','重载未丢弃本地材质验收修改。');
  check(await page.locator('.save-bar').getByRole('button',{name:'保存修改',exact:true}).isDisabled(),'PRODUCT_RELOAD_CLEAN','重载真实数据后仍有虚假变更。');
  return {status:'PASS',localApply:true,comparison:true,reloadRestored:true,businessSubmitted:false};
}
async function localRichText(page,task) {
  if(terminal(task))return {status:'NOT_COVERED'};
  const editor=page.locator('.requirements-field [data-slate-editor][contenteditable="true"]');
  await editor.fill('QA本地格式检查');await editor.press('Control+A');
  await page.locator('.requirements-field button[data-menu-key="bold"]').click();
  check(await editor.evaluate(element=>[...element.querySelectorAll('*')].some(node=>node.textContent.includes('QA本地格式检查') && Number(getComputedStyle(node).fontWeight)>=600)),'RICH_FORMAT','真实富文本编辑器加粗未生效。');
  check((await page.locator('.comparison-table').innerText()).includes('生产要求'),'RICH_CHANGE','本地富文本修改没有进入变更对照。');
  await screenshot(page,'edit-1920-rich-text-local.png');
  await page.reload({waitUntil:'networkidle'});await page.locator('.production-task-edit-page .editor-layout').waitFor({timeout:25000});
  const original=await page.evaluate(html=>{const element=document.createElement('div');element.innerHTML=html||'';return element.textContent||'';},task.special_requirements_html);
  check(compact(await editor.innerText())===compact(original),'RICH_RELOAD','重载后真实生产要求未恢复。');
  if(!compact(original))report.notCovered.push('真实生产要求为空；已验证本地文字加粗及重载恢复，已有正文的纯格式修改由单元测试覆盖。');
  await expandAll(page);
  return {status:'PASS',formatApplied:true,reloadRestored:true,businessSubmitted:false,pureFormatExistingSample:Boolean(compact(original))};
}
async function main() {
  check(['http:','https:'].includes(base.protocol) && !base.username && !base.password, 'BASE_URL', '目标地址必须是无内嵌凭据的 HTTP(S) 地址。');
  check(Boolean(statePath) || Boolean(username && password), 'AUTH_REQUIRED', '提供 TASK_EDIT_QA_USERNAME/PASSWORD，或 TASK_EDIT_QA_STORAGE_STATE。');
  if (statePath) check(fs.existsSync(path.resolve(statePath)) && fs.statSync(path.resolve(statePath)).isFile(), 'STORAGE_STATE', '指定的 Session 状态文件不可读取。');
  check(/^[0-9a-f-]{36}$/i.test(requestedId), 'TASK_ID', '真实任务 ID 格式不正确。');
  fs.mkdirSync(evidenceDir, { recursive:true });
  check(samePath(fs.realpathSync(evidenceDir), evidenceDir), 'EVIDENCE_LINK', '证据目录实际路径与登记路径不一致。'); evidenceVerified = true;
  check(!fs.existsSync(browserTemp), 'TEMP_EXISTS', 'browser_temp 已存在，拒绝覆盖或清理来源未确认的目录。');
  fs.mkdirSync(browserTemp); ownsTemp = true; report.resources.created = true;
  process.env.TEMP = browserTemp; process.env.TMP = browserTemp; process.env.TMPDIR = browserTemp;
  const executablePath = process.env.TASK_EDIT_QA_BROWSER_PATH || ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Microsoft/Edge/Application/msedge.exe','C:/Program Files/Google/Chrome/Application/chrome.exe'].find(candidate => fs.existsSync(candidate));
  check(Boolean(executablePath) && fs.existsSync(executablePath), 'BROWSER_MISSING', '缺少现有浏览器；脚本不会安装依赖。');
  browser = await chromium.launch({ headless:true, executablePath, downloadsPath:browserTemp });
  const context = await browser.newContext({ viewport:{width:1920,height:1080}, locale:'zh-CN', timezoneId:'Asia/Shanghai', serviceWorkers:'block', ...(statePath ? {storageState:path.resolve(statePath)} : {}) });
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    const login = request.method() === 'POST' && url.origin === base.origin && url.pathname === '/api/auth/login/';
    if (!['GET','HEAD'].includes(request.method()) && !login) { report.blockedWrites.push({method:request.method(), path:safePath(url.href)}); await route.abort('blockedbyclient'); return; }
    await route.continue();
  });
  const user = await authenticate(context);
  check((user.permissions || []).includes('production_tasks.change_productiontask'), 'EDIT_PERMISSION', '真实账号没有编辑生产任务单权限。');
  const list = (await getJson(context, '/api/v1/production-tasks/?page=1&page_size=100', 'readable-task-list')).body;
  check(Array.isArray(list.data), 'LIST_CONTRACT', '真实任务列表契约不符。');
  report.discovery = { firstPageCount:list.data.length, total:list.meta?.total ?? null };
  const before = await getJson(context, '/api/v1/production-tasks/' + requestedId + '/', 'primary-task-detail');
  const task = before.body.data;
  check(task?.id === requestedId && Array.isArray(task.products), 'TASK_CONTRACT', '真实任务详情契约不符。');
  check(Boolean(before.etag), 'ETAG_MISSING', '真实任务详情缺少 ETag。');
  const options = (await getJson(context, '/api/v1/production-tasks/options/', 'real-product-options')).body.data;
  check(Array.isArray(options?.products) && Array.isArray(options?.detail_template), 'OPTIONS_CONTRACT', '真实产品或生产明细配置缺失。');
  report.primary = { reference:digest(task.id), status:task.status, productCount:task.products.length, sourceLocked:sourceLocked(task), etagHash:digest(before.etag) };
  const page = await context.newPage(); activePage=page; page.setDefaultTimeout(25000);
  page.on('pageerror', error => report.pageErrors.push({name:error.name,digest:digest(error.message)}));
  page.on('response', response => { if (response.status() >= 400 && new URL(response.url()).origin === base.origin) report.httpErrors.push({status:response.status(),path:safePath(response.url())}); if(response.request().resourceType()==='image'){(report.imageResponses ||= []).push({status:response.status(),path:safePath(response.url()),queryPresent:Boolean(new URL(response.url()).search)});} });
  for (const [width,height] of viewports) {
    currentStage='viewport-'+width+'-load';
    await page.setViewportSize({width,height}); await loadPage(page, task);
    currentStage='viewport-'+width+'-baseline';
    const baseline = await measure(page,width); await screenshot(page,'edit-' + width + '-default.png');
    currentStage='viewport-'+width+'-fields-folding';
    await folding(page,task); await checkFields(page,task);
    currentStage='viewport-'+width+'-expanded';
    const expanded = await measure(page,width); await screenshot(page,'edit-' + width + '-expanded.png');
    currentStage='viewport-'+width+'-local-edit';
    const localEdit = await temporaryEdit(page,task,width);
    currentStage='viewport-'+width+'-product-dialog';
    const dialog = await productDialog(page,task,options,width);
    currentStage='viewport-'+width+'-product-local-apply';
    const applied=width===1920?await localProductApply(page,task):null;
    if(applied)report.localProductApply=applied;
    currentStage='viewport-'+width+'-rich-text';
    const richText=width===1920?await localRichText(page,task):null;
    currentStage='viewport-'+width+'-bottom';
    const end = await bottom(page); await screenshot(page,'edit-' + width + '-bottom.png');
    report.checks.push({width,height,fieldMatch:true,baseline,expanded,localEdit,dialog,applied,richText,bottom:end});
    check(report.blockedWrites.length === 0, 'BUSINESS_WRITE_BLOCKED', '验收期间出现业务写请求，已拦截。');
  }
  const after = await getJson(context, '/api/v1/production-tasks/' + requestedId + '/', 'primary-task-unchanged');
  check(before.etag === after.etag && digest(JSON.stringify(task)) === digest(JSON.stringify(after.body.data)), 'TASK_CHANGED', '真实任务在只读验收期间发生变化；需排查并发编辑，不能声明未变。');
  report.taskUnchanged = { etagMatched:true, contentDigestMatched:true };
  if (task.products.length < 2) report.notCovered.push('主真实任务不足两项产品，未造数据补齐多产品覆盖。');
  report.notCovered.push('未提交保存、上传或删除；真实写入、412并发冲突恢复不在本次只读浏览器验收范围。');
  report.notCovered.push('真实加载失败、空数据和无权限账户未伪造；由相关单元测试覆盖页面分支。');
  if (!terminal(task)) report.notCovered.push('主真实任务不是终态，终态禁用由相关单元测试覆盖。');
  if (!sourceLocked(task)) report.notCovered.push('主真实任务不是销售来源，来源锁定与数量上限由相关单元测试覆盖。');
  report.notCovered = [...new Set(report.notCovered)];
  check(report.blockedWrites.length === 0, 'BUSINESS_WRITE_BLOCKED', '存在已拦截的业务写请求。');
  check(report.pageErrors.length === 0, 'PAGE_ERROR', '页面出现脚本错误，报告仅保存摘要。');
  check(report.httpErrors.length === 0, 'HTTP_ERROR', '真实页面请求出现 HTTP 错误，报告仅保存状态及脱敏路径。');
  report.status = report.notCovered.length ? 'PASS_WITH_GAPS' : 'PASS';
}
(async () => {
  try { await main(); }
  catch (error) {
    report.status = error.safeQaMessage && ['AUTH_REQUIRED','STORAGE_STATE','SESSION_EXPIRED','LOGIN_REJECTED','LOGIN_NO_SESSION','BROWSER_MISSING','TEMP_EXISTS','EDIT_PERMISSION'].includes(error.code) ? 'BLOCKED' : 'FAIL';
    report.failure = { code:error.safeQaMessage ? error.code : 'UNEXPECTED',stage:currentStage,message:error.safeQaMessage ? error.message : '执行异常；见脱敏诊断。',detail:safeErrorDetail(error) }; process.exitCode = 1;
    if (activePage && !activePage.isClosed()) {
      try {
        await screenshot(activePage,'failure-'+currentStage+'.png');
        report.failure.dom=await activePage.evaluate(()=>['.production-task-edit-page','.editor-layout','.task-sidebar','.product-file','.comparison-table','.production-product-editor','.app-window-dialog__body','.save-bar'].map(selector=>({selector,elements:[...document.querySelectorAll(selector)].map(element=>{const r=element.getBoundingClientRect();return {width:r.width,height:r.height,x:r.x,y:r.y,visible:element.getClientRects().length>0,scrollWidth:element.scrollWidth,clientWidth:element.clientWidth,scrollHeight:element.scrollHeight,clientHeight:element.clientHeight};})})));
      } catch { report.failure.screenshotUnavailable=true; }
    }
  } finally {
    let canRemove = !browser;
    if (browser) { try { await browser.close(); report.resources.browserClosed = true; canRemove = true; } catch { report.resources.closeFailed = true; report.status='FAIL'; process.exitCode=1; } }
    for (const key of Object.keys(previousTemp)) { if (previousTemp[key] === undefined) delete process.env[key]; else process.env[key] = previousTemp[key]; }
    if (ownsTemp && canRemove) {
      try {
        check(samePath(path.dirname(browserTemp),evidenceDir) && samePath(fs.realpathSync(browserTemp),browserTemp) && !fs.lstatSync(browserTemp).isSymbolicLink(), 'CLEANUP_BOUNDARY', '临时目录边界核验失败。');
        fs.rmSync(browserTemp,{recursive:true,force:false}); report.resources.removed=true; report.resources.verifiedAbsent=!fs.existsSync(browserTemp);
        check(report.resources.verifiedAbsent,'CLEANUP_REMAINS','临时浏览器目录仍存在。');
      } catch { report.resources.cleanupFailed=true; report.status='FAIL'; process.exitCode=1; }
    } else if (!ownsTemp) report.resources.verifiedAbsent=!fs.existsSync(browserTemp);
    report.finishedAt=new Date().toISOString();
    if (evidenceVerified) {
      const serialized=JSON.stringify(report,null,2);
      fs.writeFileSync(path.join(evidenceDir,'readonly-report.json'),serialized);
      fs.writeFileSync(path.join(evidenceDir,'readonly-report-'+report.startedAt.replace(/[:.]/g,'-')+'.json'),serialized);
    }
    console.log(JSON.stringify({status:report.status,checks:report.checks.length,blockedWrites:report.blockedWrites.length,gaps:report.notCovered.length,report:evidenceVerified?path.join(evidenceDir,'readonly-report.json'):null,failure:report.failure,cleanup:report.resources.verifiedAbsent}));
  }
})();

/** BOM 新增原料预览：真实 Session + API + headless，仅预检和取消，禁止实际建档与保存。 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('../src/frontend/node_modules/playwright-core');
const root = path.resolve(__dirname, '..');
const taskRoot = path.join(root, '.tmp', 'bom_material_confirm_20261016');
const profile = path.join(taskRoot, 'profile');
// 稳定截图复验使用独立证据目录，保留首轮过渡态截图和报告供追溯。
const output = process.env.QA_REPORT_DIR ? path.resolve(process.env.QA_REPORT_DIR, 'bom-material-save-preview-stable') : path.join(root, 'output', 'playwright', 'bom-material-save-confirm-20261016', 'stable-dialog');
const base = new URL(process.env.BOM_MATERIAL_PREVIEW_QA_BASE_URL || 'http://localhost:8080');
const bomId = 'be2ec136-6e0f-4780-8a5c-53d2956ee0bf';
const bomRoute = '/api/v1/boms/' + bomId + '/';
const previewRoute = bomRoute + 'material-save-preview/';
const expectedAuxiliaryNames = ['冰包铝膜', '椅面棉', '枕头棉', '加厚-摇篮网', '直角方皮塑件', '坐垫膜'];
const report = { qa_result_version: 1, startedAt: new Date().toISOString(), status: 'RUNNING', mode: 'real-api-read-only-preview-and-cancel',
  checks: [], cases: [], apiReads: [], previewRequests: [], blockedWrites: [], httpErrors: [], pageErrors: [], measurements: [], screenshots: [], stateComparisons: [], notCovered: [],
  resources: { profile, output, created: false, browserClosed: false, removed: false, verifiedAbsent: false } };
let context, outputReady = false, step = 'startup', allowedIntent = null, initialServerState = null;
function requireCondition(condition, code, message) { if (!condition) { const error = new Error(message); error.code = code; error.qaSafe = true; throw error; } }
function check(condition, code, detail = {}) { report.checks.push({ code, passed: Boolean(condition), ...detail }); }
function gap(message) { if (!report.notCovered.includes(message)) report.notCovered.push(message); }
function digest(value) { return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex'); }
function safeRoute(value) { try { return new URL(value, base).pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, ':id'); } catch { return 'invalid-url'; } }
function inside(candidate, parent) { const relative = path.relative(fs.realpathSync(parent), fs.realpathSync(candidate)); return relative !== '' && !relative.startsWith('..') && !path.isAbsolute(relative); }
function failure(error, fallback) { check(false, error.code || fallback, { step, message: error.qaSafe ? error.message : '检查未完成；未输出会话凭据、确认令牌或完整请求响应。', errorType: error.name }); }
async function getJson(route, kind) {
  const url = new URL(route, base);
  requireCondition(url.origin === base.origin && url.pathname.startsWith('/api/'), 'API_SCOPE', '只允许读取指定本机 API。');
  const response = await context.request.get(url.href, { maxRedirects: 0 });
  report.apiReads.push({ kind, route: safeRoute(url.href), status: response.status() });
  requireCondition(response.status() === 200, 'API_UNAVAILABLE', kind + '不可读，HTTP ' + response.status());
  return { body: await response.json(), etag: response.headers().etag || null };
}
async function inventorySnapshot() {
  const rows = [];
  let total = null, totalPages = 1;
  for (let page = 1; page <= totalPages; page += 1) {
    const { body } = await getJson('/api/v1/raw-materials/?page_size=100&page=' + page + '&ordering=material_number', 'active-inventory-page-' + page);
    requireCondition(Array.isArray(body.data) && body.data.length <= 100 && body.meta?.page === page && Number.isInteger(body.meta.total) && Number.isInteger(body.meta.total_pages), 'INVENTORY_PAGE_CONTRACT', '原料分页响应不符合契约。');
    if (total === null) { total = body.meta.total; totalPages = body.meta.total_pages; }
    requireCondition(body.meta.total === total && body.meta.total_pages === totalPages, 'INVENTORY_CHANGED_DURING_READ', '读取分页时原料列表发生变化，不能声称不变。');
    rows.push(...body.data);
  }
  requireCondition(rows.length === total && new Set(rows.map(row => row.id)).size === total, 'INVENTORY_PAGE_INCOMPLETE', '原料分页读取不完整或存在重复。');
  rows.sort((left, right) => left.id.localeCompare(right.id));
  return { total, types: rows.reduce((counts, row) => { counts[row.item_type] = (counts[row.item_type] || 0) + 1; return counts; }, {}), hash: digest(rows), updatedHash: digest(rows.map(row => [row.id, row.updated_at])) };
}
async function readState(label) {
  const response = await getJson(bomRoute, 'bom-' + label);
  requireCondition(response.body?.data?.id === bomId, 'TARGET_BOM_MISSING', '真实目标 BOM 不可读。');
  const bom = response.body.data;
  const state = { bomHash: digest(bom), bomUpdatedAt: bom.updated_at, bomEtag: response.etag, inventory: await inventorySnapshot() };
  return { bom, state };
}
function compareState(before, after, scope) {
  const equal = before.bomHash === after.bomHash && before.bomUpdatedAt === after.bomUpdatedAt && before.bomEtag === after.bomEtag && before.inventory.hash === after.inventory.hash && before.inventory.updatedHash === after.inventory.updatedHash && before.inventory.total === after.inventory.total;
  report.stateComparisons.push({ scope, before, after, equal });
  check(equal, 'BOM_AND_ACTIVE_INVENTORY_UNCHANGED', { scope });
}
async function screenshot(page, name) { const file = path.join(output, name + '.png'); await page.screenshot({ path: file, fullPage: true, animations: 'disabled' }); report.screenshots.push(file); }
async function waitForDialogStable(page, scope) {
  const stable = await page.waitForFunction(() => {
    const marker = document.querySelector('[data-testid="bom-material-save-preview"]');
    const dialog = marker?.closest('.el-dialog') || marker;
    if (!dialog?.getClientRects().length) return false;
    const overlay = dialog.closest('.el-overlay');
    const ancestors = [];
    for (let node = dialog; node; node = node.parentElement) {
      ancestors.push({ node: node.className, opacity: Number(getComputedStyle(node).opacity) });
      if (node === overlay) break;
    }
    const animations = (overlay || dialog).getAnimations({ subtree: true }).map(animation => ({
      state: animation.playState, pending: animation.pending,
      finite: !animation.effect || Number.isFinite(animation.effect.getComputedTiming().endTime),
    }));
    const finiteAnimations = animations.filter(animation => animation.finite);
    const activeFiniteCount = finiteAnimations.filter(animation => animation.pending || !['finished', 'idle'].includes(animation.state)).length;
    if (ancestors.some(node => node.opacity !== 1) || activeFiniteCount) return false;
    return { dialogOpacity: Number(getComputedStyle(dialog).opacity), ancestors, finiteAnimations, activeFiniteCount, ignoredInfiniteCount: animations.length - finiteAnimations.length };
  }, undefined, { timeout: 15000 });
  const motion = await stable.jsonValue();
  await stable.dispose();
  report.measurements.push({ scope: scope + '-stable-motion', motion });
  check(motion.dialogOpacity === 1 && motion.ancestors.every(node => node.opacity === 1), 'PREVIEW_OPACITY_FULLY_RESTORED', { scope });
  check(motion.activeFiniteCount === 0, 'PREVIEW_FINITE_ANIMATIONS_FINISHED', { scope });
}
async function measureDialog(page, scope) {
  const measured = await page.evaluate(() => {
    const measure = node => { if (!node?.getClientRects().length) return null; const r = node.getBoundingClientRect(), s = getComputedStyle(node); return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height, clientWidth: node.clientWidth, scrollWidth: node.scrollWidth, clientHeight: node.clientHeight, scrollHeight: node.scrollHeight, overflow: [s.overflowX, s.overflowY], opacity: Number(s.opacity), fontSize: s.fontSize, background: s.backgroundColor, border: [s.borderTop, s.borderRight, s.borderBottom, s.borderLeft] }; };
    const marker = document.querySelector('[data-testid="bom-material-save-preview"]');
    const dialog = marker?.closest('.el-dialog') || marker;
    const table = measure(dialog?.querySelector('.material-save-table'));
    const tableScroll = measure(dialog?.querySelector('.material-save-table-scroll'));
    return { width: innerWidth, height: innerHeight, documentWidth: document.documentElement.scrollWidth, dialog: measure(dialog),
      table, tableScroll,
      blankSpaceBelowTable: table && tableScroll ? Math.max(0, tableScroll.bottom - table.bottom) : null,
      footer: measure(dialog?.querySelector('.el-dialog__footer')), headings: [...(dialog?.querySelectorAll('thead th') || [])].map(measure),
      buttons: [...(dialog?.querySelectorAll('.el-dialog__footer button') || [])].map(measure) };
  });
  report.measurements.push({ scope, measured });
  check(measured.documentWidth <= measured.width + 1, 'NO_PAGE_HORIZONTAL_OVERFLOW', { scope });
  check(Boolean(measured.dialog) && measured.dialog.x >= -1 && measured.dialog.y >= -1 && measured.dialog.right <= measured.width + 1 && measured.dialog.bottom <= measured.height + 1, 'PREVIEW_DIALOG_WITHIN_VIEWPORT', { scope });
  check(measured.buttons.length >= 2 && measured.buttons.every(button => button && button.x >= -1 && button.right <= measured.width + 1 && button.y >= -1 && button.bottom <= measured.height + 1), 'PREVIEW_FOOTER_BUTTONS_VISIBLE', { scope });
  check(measured.dialog?.opacity === 1, 'PREVIEW_MEASURED_AT_FULL_OPACITY', { scope });
  check(Boolean(measured.table && measured.tableScroll) && measured.table.height > 0 && measured.tableScroll.scrollWidth <= measured.tableScroll.clientWidth + 1, 'PREVIEW_TABLE_VISIBLE_WITHOUT_HORIZONTAL_OVERFLOW', { scope });
  check(measured.blankSpaceBelowTable !== null && measured.blankSpaceBelowTable <= 2, 'PREVIEW_TABLE_NO_EXTRA_BLANK_AREA', { scope });
  const fitsVertically = measured.table && measured.tableScroll && measured.table.height <= measured.tableScroll.clientHeight + 1;
  check(fitsVertically ? measured.tableScroll.scrollHeight <= measured.tableScroll.clientHeight + 1 : measured.tableScroll?.overflow[1] === 'auto', 'PREVIEW_TABLE_SCROLL_ONLY_WHEN_NEEDED', { scope, fitsVertically });
}
async function previewAndCancel(page, bom, intent, scope, initialState) {
  step = scope + '-' + intent;
  const trigger = page.getByRole('button', { name: intent === 'draft' ? '保存草稿' : '确认BOM', exact: true });
  const triggerAvailable = await trigger.count() === 1 && await trigger.isEnabled();
  if (intent === 'verify' && bom.status === 'VERIFIED') {
    check(!triggerAvailable, 'VERIFIED_BOM_CONFIRM_ACTION_UNAVAILABLE', { scope });
    gap(scope + '：HT26001 已确认，既有页面规则隐藏确认BOM；确认入口预检取消未做真实页面覆盖，未改变正式状态。');
    report.cases.push({ scope, intent, status: 'NOT_COVERED', reason: 'verified-bom-confirm-action-unavailable' });
    return;
  }
  requireCondition(triggerAvailable, 'SAVE_ACTION_UNAVAILABLE', '当前真实账号或 BOM 不允许触发保存预检。');
  allowedIntent = intent;
  const beforeRequestCount = report.previewRequests.length;
  const [response] = await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === previewRoute && response.request().method() === 'POST'),
    trigger.click(),
  ]);
  allowedIntent = null;
  const payload = await response.json();
  requireCondition(response.status() === 200, 'PREVIEW_API_FAILED', '新增原料预检未成功，HTTP ' + response.status());
  const preview = payload.data;
  requireCondition(Array.isArray(preview?.new_materials) && preview.new_materials.length > 0 && typeof preview.confirmation_token === 'string' && preview.confirmation_token.length > 0, 'NEW_MATERIAL_PREVIEW_REQUIRED', '真实目标未返回待新增原料及确认令牌，不得继续保存。');
  check(report.previewRequests.length === beforeRequestCount + 1, 'ONE_PREVIEW_REQUEST_PER_ACTION', { scope, intent });
  check(new Set(preview.new_materials.map(item => item.key)).size === preview.new_materials.length, 'PREVIEW_MATERIAL_KEYS_DEDUPLICATED', { scope, intent, count: preview.new_materials.length });
  check(expectedAuxiliaryNames.every(name => preview.new_materials.some(item => item.material_name === name && item.locations?.some(location => location.section_title === '辅料类'))), 'SIX_REAL_AUXILIARY_MATERIALS_IN_PREVIEW', { scope, intent });
  const dialog = page.getByTestId('bom-material-save-preview');
  await dialog.waitFor({ state: 'visible' });
  await waitForDialogStable(page, scope + '-' + intent);
  const rows = dialog.getByTestId('bom-material-save-preview-row');
  check(await rows.count() === preview.new_materials.length, 'PREVIEW_ROW_COUNT_MATCHES_API', { scope, intent });
  check(JSON.stringify(await dialog.locator('thead th').allTextContents()) === JSON.stringify(['分区', '行号', '品名', '规格', '颜色', '材质', '单位', '仓库']), 'PREVIEW_EIGHT_COLUMNS_PRESENT', { scope, intent });
  for (const [index, item] of preview.new_materials.entries()) {
    const cells = await rows.nth(index).locator('td').evaluateAll(nodes => nodes.map(node => ({
      text: node.textContent.trim(), main: [...node.childNodes].filter(child => child.nodeType === Node.TEXT_NODE).map(child => child.textContent).join('').trim(),
      details: [...node.querySelectorAll('small')].map(detail => detail.textContent.trim()),
    })));
    const shown = [item.material_name, item.specification, item.color_label || item.color_name, item.material, item.unit_name, item.warehouse_name].map(value => String(value || '—'));
    check(typeof item.width === 'string' && typeof item.color_label === 'string', 'PREVIEW_WIDTH_AND_COLOR_LABEL_CONTRACT', { scope, intent, material: item.material_name });
    check(cells.length === 8 && shown.every((value, fieldIndex) => cells[fieldIndex + 2].main === value) && item.locations.every(location => cells[0].text.includes(location.section_title) && cells[1].text.includes(String(location.line_number))), 'PREVIEW_FIELDS_MATCH_REAL_API', { scope, intent, material: item.material_name });
    check(item.width ? cells[3]?.details.length === 1 && cells[3].details[0].replace(/\s+/g, '') === '门幅' + item.width.replace(/\s+/g, '') : cells[3]?.details.length === 0, 'PREVIEW_WIDTH_DETAIL_MATCHES_API', { scope, intent, material: item.material_name });
  }
  if (preview.new_materials.every(item => !item.width)) gap('真实待新增清单没有面料门幅；已核对空门幅不显示附加文字，非空门幅展示由后端及组件测试覆盖，未造数。');
  report.cases.push({ scope, intent, status: 'PREVIEW_DISPLAYED', newMaterialCount: preview.new_materials.length, materials: preview.new_materials.map(item => ({ item_type: item.item_type, category_name: item.category_name, material_name: item.material_name, locations: item.locations })) });
  await measureDialog(page, scope + '-' + intent);
  await screenshot(page, 'new-materials-' + intent + '-' + scope);
  // 此处仅取消；“确认新增并保存”等任何写入按钮均不点击。
  await dialog.getByTestId('bom-material-save-cancel').click();
  await dialog.waitFor({ state: 'hidden' });
  check(await trigger.isEnabled(), 'CANCEL_RESTORES_ACTION_BUTTON', { scope, intent });
  check(report.blockedWrites.length === 0, 'CANCEL_DID_NOT_ATTEMPT_SAVE', { scope, intent });
  compareState(initialState, (await readState(scope + '-' + intent + '-cancel')).state, scope + '-' + intent + '-cancel');
  await screenshot(page, 'cancelled-' + intent + '-' + scope);
}
async function main() {
  const stateFile = process.env.BOM_MATERIAL_PREVIEW_QA_STORAGE_STATE;
  requireCondition(Boolean(stateFile) && fs.existsSync(stateFile), 'STORAGE_STATE_REQUIRED', '需要已登记的现有 Session 文件，禁止自动登录。');
  const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
  requireCondition(Array.isArray(state.cookies), 'INVALID_STORAGE_STATE', '现有 Session 格式无效。');
  requireCondition(/^https?:$/.test(base.protocol) && ['localhost', '127.0.0.1'].includes(base.hostname), 'TARGET_SCOPE', '只允许指定本机开发服务。');
  const executablePath = [process.env.BOM_MATERIAL_PREVIEW_QA_BROWSER_PATH, 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'].filter(Boolean).find(file => fs.existsSync(file));
  requireCondition(Boolean(executablePath), 'BROWSER_MISSING', '没有可用的已安装浏览器。');
  requireCondition(!fs.existsSync(profile), 'PROFILE_ALREADY_EXISTS', '独占 profile 已存在，禁止覆盖或清理既有目录。');
  requireCondition(fs.existsSync(taskRoot) && inside(taskRoot, root), 'PROFILE_ROOT_SCOPE', '已登记临时父目录不存在或越界。');
  fs.mkdirSync(output, { recursive: true }); outputReady = true;
  fs.mkdirSync(profile); report.resources.created = true;
  requireCondition(inside(profile, taskRoot) && fs.realpathSync(profile) === path.join(fs.realpathSync(taskRoot), 'profile'), 'PROFILE_SCOPE', 'profile 不在登记范围。');
  process.env.TEMP = profile; process.env.TMP = profile; process.env.TMPDIR = profile;
  context = await chromium.launchPersistentContext(profile, { executablePath, headless: true, locale: 'zh-CN', serviceWorkers: 'block', env: { ...process.env, TEMP: profile, TMP: profile, TMPDIR: profile } });
  context.setDefaultTimeout(15000);
  await context.addCookies(state.cookies);
  await context.addInitScript(({ origins }) => { const match = (origins || []).find(item => item.origin === location.origin); for (const entry of match?.localStorage || []) localStorage.setItem(entry.name, entry.value); }, { origins: state.origins || [] });
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (['GET', 'HEAD'].includes(request.method())) { await route.continue(); return; }
    // 唯一允许的 POST 是已审查且通过零写入 API 测试的目标 BOM 预检；真正保存 PATCH 与 verify 始终阻断。
    if (request.method() === 'POST' && url.origin === base.origin && url.pathname === previewRoute && allowedIntent) {
      let body;
      try { body = request.postDataJSON(); } catch { body = null; }
      if (body?.intent === allowedIntent && Array.isArray(body.sections) && request.headers()['if-match'] && !body.confirmation_token) {
        report.previewRequests.push({ intent: body.intent, route: safeRoute(request.url()), sectionCount: body.sections.length, payloadHash: digest(body), hasIfMatch: true });
        await route.continue(); return;
      }
    }
    report.blockedWrites.push({ method: request.method(), route: safeRoute(request.url()) });
    await route.abort('blockedbyclient');
  });
  context.on('response', response => {
    const url = new URL(response.url());
    if (!url.pathname.startsWith('/api/')) return;
    const item = { method: response.request().method(), route: safeRoute(response.url()), status: response.status() };
    report.apiReads.push(item);
    if (item.status >= 400 && url.pathname !== previewRoute) report.httpErrors.push(item);
  });
  const auth = await getJson('/api/auth/me/', 'existing-session');
  requireCondition(auth.body.authenticated === true, 'SESSION_EXPIRED', '现有 Session 已失效，禁止自动登录。');
  const initial = await readState('before');
  initialServerState = initial.state;
  requireCondition(initial.bom.product_information_confirmed === true && !initial.bom.is_order_quantity_outdated && !initial.bom.is_order_product_outdated, 'TARGET_BOM_PREREQUISITE', '真实 BOM 尚未核对产品或订单信息已变化，不代替用户确认和同步。');
  requireCondition(initial.state.bomEtag, 'BOM_ETAG_MISSING', '真实 BOM 缺少并发版本信息。');
  for (const viewport of [{ width: 1101, height: 884 }, { width: 1440, height: 900 }]) {
    const scope = viewport.width + 'x' + viewport.height;
    const page = await context.newPage();
    page.on('pageerror', error => report.pageErrors.push({ scope, type: error.name }));
    await page.setViewportSize(viewport);
    await page.goto(new URL('/boms/' + bomId + '/edit', base).href, { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: '保存草稿', exact: true }).waitFor({ state: 'visible' });
    for (const intent of ['draft', 'verify']) await previewAndCancel(page, initial.bom, intent, scope, initial.state);
    await page.close();
  }
  check(report.blockedWrites.length === 0, 'NO_SAVE_OR_OTHER_WRITE_ATTEMPTS', { count: report.blockedWrites.length });
  check(report.httpErrors.length === 0, 'NO_UNEXPECTED_API_ERRORS', { count: report.httpErrors.length });
  check(report.pageErrors.length === 0, 'NO_BROWSER_RUNTIME_ERRORS', { count: report.pageErrors.length });
  gap('真实业务库不确认新增或保存；无新增直接保存、原子建档、失败回滚及并发等写入分支由独占测试库 API 验证。');
  gap('真实目标的待新增资料覆盖范围以预检返回为准；未伪造其他分区、空数据、权限不足或错误数据，不能声称所有分区均完成真实页面验收。');
  gap('原料前后数量及哈希覆盖真实 API 可见的全部活动原料与半成品；归档记录和审计表零写入由后端测试覆盖。');
}
main().catch(error => { failure(error, 'QA_ABORTED'); report.status = ['STORAGE_STATE_REQUIRED', 'SESSION_EXPIRED', 'BROWSER_MISSING', 'PROFILE_ALREADY_EXISTS', 'TARGET_BOM_MISSING', 'TARGET_BOM_PREREQUISITE', 'SAVE_ACTION_UNAVAILABLE', 'API_UNAVAILABLE'].includes(error.code) ? 'BLOCKED' : 'FAIL'; }).finally(async () => {
  allowedIntent = null;
  if (context && initialServerState) {
    try { compareState(initialServerState, (await readState('after-all-cases-or-failure')).state, 'entire-readonly-flow'); }
    catch (error) { failure(error, 'FINAL_SERVER_STATE_CHECK_FAILED'); }
  }
  if (context) { try { await context.close(); report.resources.browserClosed = true; } catch { check(false, 'BROWSER_CLOSE_FAILED'); } }
  if (report.resources.created) {
    try {
      requireCondition(!context || report.resources.browserClosed, 'PROFILE_IN_USE', '浏览器未关闭，停止 profile 清理。');
      requireCondition(inside(profile, taskRoot) && fs.realpathSync(profile) === path.join(fs.realpathSync(taskRoot), 'profile'), 'CLEANUP_SCOPE', 'profile 不在登记范围，停止清理。');
      fs.rmSync(profile, { recursive: true, force: false }); report.resources.removed = true; report.resources.verifiedAbsent = !fs.existsSync(profile);
      check(report.resources.verifiedAbsent, 'PROFILE_CLEANED_AND_VERIFIED');
    } catch (error) { failure(error, 'PROFILE_CLEANUP_FAILED'); }
  }
  if (report.status === 'RUNNING') report.status = report.checks.some(item => !item.passed) ? 'FAIL' : report.notCovered.length ? 'PASS_WITH_GAPS' : 'PASS';
  if (report.resources.created && !report.resources.verifiedAbsent) report.status = 'FAIL';
  report.finishedAt = new Date().toISOString();
  if (outputReady) fs.writeFileSync(path.join(output, 'readonly-report.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ qa_result_version: 1, status: report.status, not_covered: report.notCovered, cleanup: !report.resources.created || report.resources.verifiedAbsent, checks: report.checks.length, failed: report.checks.filter(item => !item.passed).length, failure: report.checks.find(item => !item.passed), report: outputReady ? path.join(output, 'readonly-report.json') : null }));
  process.exitCode = ['PASS', 'PASS_WITH_GAPS'].includes(report.status) ? 0 : report.status === 'BLOCKED' ? 2 : 1;
});

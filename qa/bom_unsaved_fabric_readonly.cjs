/** 未保存面料 -> 裁剪来源：真实 API + headless，只使用已有 Session，禁止任何网络写请求。 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('../src/frontend/node_modules/playwright-core');
const root = path.resolve(__dirname, '..');
const taskRoot = path.join(root, '.tmp', 'bom_unsaved_fabric_20261015');
const profile = path.join(taskRoot, 'profile');
const output = process.env.QA_REPORT_DIR ? path.resolve(process.env.QA_REPORT_DIR, 'bom-unsaved-fabric')
  : path.join(root, 'output', 'playwright', 'bom-unsaved-fabric-20261015');
const base = new URL(process.env.BOM_FABRIC_QA_BASE_URL || 'http://localhost:8080');
const bomId = 'dbe06399-b6f0-40b1-bdba-9e0d9b2861da';
const report = { schemaVersion: 1, startedAt: new Date().toISOString(), mode: 'real-api-read-only', status: 'RUNNING',
  checks: [], apiReads: [], blockedWrites: [], httpErrors: [], pageErrors: [], screenshots: [], measurements: [], notCovered: [],
  resources: { profile, created: false, browserClosed: false, removed: false, verifiedAbsent: false } };
let context, outputReady = false, profileCreated = false, currentStep = 'startup';
function requireCondition(condition, code, message) { if (!condition) { const error = new Error(message); error.code = code; error.qaSafe = true; throw error; } }
function check(condition, code, detail = {}) { report.checks.push({ code, passed: Boolean(condition), ...detail }); }
function gap(scope, reason) { report.notCovered.push({ scope, reason }); }
function failure(error, fallback) { report.checks.push({ code: error.code || fallback, passed: false, step: currentStep, message: error.qaSafe ? error.message : '检查未完成；未输出请求内容、响应正文或凭据。', errorType: error.name }); }
function safeRoute(raw) { try { return new URL(raw, base).pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, ':id'); } catch { return 'invalid-url'; } }
function inside(candidate, parent) { const relative = path.relative(fs.realpathSync(parent), fs.realpathSync(candidate)); return relative !== '' && !relative.startsWith('..') && !path.isAbsolute(relative); }
function digest(value) { return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex'); }
function validMaterial(value) { const text = String(value || '').trim(); return Boolean(text && text !== '/'); }
function originalMaterial(line) { return Object.hasOwn(line, 'cutting_material_original') ? line.cutting_material_original : line.material; }
async function getJson(route, kind) {
  const url = new URL(route, base);
  requireCondition(url.origin === base.origin && url.pathname.startsWith('/api/'), 'API_SCOPE', '只允许读取指定服务的 API。');
  const response = await context.request.get(url.href, { maxRedirects: 0 });
  report.apiReads.push({ kind, route: safeRoute(url.href), status: response.status() });
  if (response.status() >= 400) report.httpErrors.push({ kind, route: safeRoute(url.href), status: response.status() });
  if (response.status() !== 200) return { status: response.status(), body: null };
  return { status: 200, body: await response.json() };
}
async function screenshot(page, name) { const file = path.join(output, name + '.png'); await page.screenshot({ path: file, fullPage: true }); report.screenshots.push(file); }
async function geometry(page, scope) {
  const value = await page.evaluate(() => {
    const box = selector => { const node = document.querySelector(selector); if (!node || !node.getClientRects().length) return null; const r = node.getBoundingClientRect(), s = getComputedStyle(node); return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom, clientWidth: node.clientWidth, scrollWidth: node.scrollWidth, clientHeight: node.clientHeight, scrollHeight: node.scrollHeight, overflowX: s.overflowX, overflowY: s.overflowY }; };
    return { width: innerWidth, height: innerHeight, documentWidth: document.documentElement.scrollWidth,
      panel: box('#bom-material-panel'), table: box('#bom-material-panel .el-table'), dialog: box('.bom-line-editor-dialog'),
      dropdowns: [...document.querySelectorAll('.el-select-dropdown')].filter(node => node.getClientRects().length).map(node => { const r = node.getBoundingClientRect(); return { x: r.x, right: r.right, y: r.y, bottom: r.bottom }; }) };
  });
  report.measurements.push({ scope, measured: value });
  check(value.documentWidth <= value.width + 1, 'NO_PAGE_HORIZONTAL_OVERFLOW', { scope });
  if (value.dialog) check(value.dialog.x >= -1 && value.dialog.right <= value.width + 1 && value.dialog.y >= -1 && value.dialog.bottom <= value.height + 1, 'EDITOR_DIALOG_WITHIN_VIEWPORT', { scope });
  check(value.dropdowns.every(item => item.x >= -1 && item.right <= value.width + 1 && item.y >= -1 && item.bottom <= value.height + 1), 'DROPDOWN_WITHIN_VIEWPORT', { scope });
}
function navigation(page, label) { return page.locator('#bom-material-panel .section-sidebar .section-tabs').getByText(label, { exact: true }); }
async function waitTable(table) { await table.waitFor({ state: 'visible' }); await table.locator('.el-loading-mask').waitFor({ state: 'hidden' }); }
async function selectOption(page, select, label) {
  await select.click();
  const option = page.getByRole('option', { name: label, exact: true }).filter({ visible: true }).last();
  await option.waitFor({ state: 'visible' });
  await option.click();
}
async function editCuttingRow(page, index) {
  const table = page.locator('.cutting-table');
  await waitTable(table);
  const row = table.locator('.el-table__body tr').nth(index);
  await row.hover();
  await row.getByRole('button', { name: '编辑当前行', exact: true }).click();
  await page.locator('.bom-line-editor-dialog').waitFor({ state: 'visible' });
}
async function openCuttingEditor(page, bom, semiFinished, scope) {
  await navigation(page, '裁剪明细').click();
  const lines = bom.sections.find(section => section.title === '裁剪明细')?.lines || [];
  const eligibleLine = line => !`${line.category || ''} ${line.cutting_category || ''}`.includes('管材');
  const used = new Set(lines.map(line => line.source_cutting_material_id));
  const candidates = semiFinished.filter(item => !item.category_name?.includes('管材') && item.material_number && item.material_name && !used.has(item.id));
  let existingIndex = lines.findIndex(line => eligibleLine(line) && !validMaterial(originalMaterial(line)));
  let candidate = candidates.find(item => !validMaterial(item.material));
  if (existingIndex < 0 && !candidate) {
    gap(scope, '未找到真实材质为空或“/”的非管材裁剪资料；仅验证裁剪自身有效材质优先，材质回退待验。');
    existingIndex = lines.findIndex(eligibleLine);
    candidate = candidates[0];
  }
  if (existingIndex >= 0) { await editCuttingRow(page, existingIndex); return { index: existingIndex, material: originalMaterial(lines[existingIndex]) }; }
  if (!candidate) { gap(scope, '没有可用的真实非管材裁剪行或半成品，未创建业务数据；来源联动待验。'); return null; }
  const table = page.locator('.cutting-table');
  await waitTable(table);
  const index = await table.locator('.el-table__body tr').count();
  await page.getByRole('button', { name: '选择裁剪', exact: true }).click();
  const picker = page.getByRole('dialog', { name: '选择裁剪数据', exact: true });
  await picker.waitFor({ state: 'visible' });
  await waitTable(picker.locator('.cutting-picker-table'));
  await picker.getByPlaceholder('搜索品号、品名、材质、颜色或规格').fill(candidate.material_number);
  await picker.getByRole('button', { name: '查询', exact: true }).click();
  currentStep = 'find-real-cutting-candidate';
  const chosen = picker.locator('.el-table__body tr').filter({ has: page.getByText(candidate.material_number, { exact: true }) }).first();
  await chosen.waitFor({ state: 'visible' });
  currentStep = 'select-real-cutting-candidate';
  await chosen.getByText(candidate.material_number, { exact: true }).click();
  // confirmCuttingSelection 仅把真实半成品复制进浏览器草稿并打开编辑，不调用保存/确认 API。
  currentStep = 'add-cutting-to-local-draft';
  await picker.getByRole('button', { name: /^确认添加/ }).click();
  await page.locator('.bom-line-editor-dialog').waitFor({ state: 'visible' });
  check(true, 'REAL_SEMI_FINISHED_SELECTED_IN_LOCAL_DRAFT', { scope });
  return { index, material: candidate.material };
}
async function checkSource(page, expected, baselineCount, scope, cutting, fabricMaterial) {
  currentStep = 'select-unsaved-fabric-source-' + scope;
  const dialog = page.locator('.bom-line-editor-dialog');
  const select = dialog.getByRole('combobox', { name: '来源面料', exact: true });
  await select.click();
  const listId = await select.getAttribute('aria-controls');
  requireCondition(Boolean(listId), 'SOURCE_LISTBOX_MISSING', '来源面料选择器缺少候选列表关联。');
  const list = page.locator('[id="' + listId + '"]');
  await list.waitFor({ state: 'visible' });
  const options = list.getByRole('option');
  check(await options.count() === baselineCount + 1, 'UNSAVED_FABRIC_IS_ADDITIONAL_SOURCE', { scope, before: baselineCount, after: await options.count() });
  const option = list.getByRole('option', { name: expected, exact: true }).last();
  requireCondition(await option.count() === 1, 'NEW_FABRIC_SOURCE_MISSING', '未保存面料没有出现在来源候选中。');
  check((await option.innerText()).trim() === expected, 'SOURCE_LABEL_MATCHES_REAL_REFERENCES', { scope });
  await geometry(page, scope + '-options');
  await screenshot(page, 'source-options-' + scope);
  await option.click();
  await list.waitFor({ state: 'hidden' });
  check(await select.evaluate((node, label) => node.closest('.el-select')?.textContent.includes(label), expected), 'UNSAVED_FABRIC_SOURCE_SELECTED', { scope });
  // 只能依据真实 API 的原材质判断优先级；不把裁剪材质人为清空来冒充回退验收。
  const materialField = dialog.locator('label.drawer-field').filter({ has: page.locator('span').filter({ hasText: /^(裁剪)?材质$/ }) });
  const input = materialField.locator('input');
  const displayedMaterial = (await input.count() ? await input.inputValue() : await materialField.locator('.drawer-readonly-value').innerText()).trim();
  if (validMaterial(cutting.material)) check(displayedMaterial === String(cutting.material).trim(), 'CUTTING_OWN_MATERIAL_TAKES_PRIORITY', { scope });
  else if (validMaterial(fabricMaterial)) check(displayedMaterial === String(fabricMaterial).trim(), 'CUTTING_EMPTY_MATERIAL_USES_UNSAVED_FABRIC', { scope });
  else gap(scope, '真实面料材质字典没有有效材质，无法验证裁剪空材质回退。');
  await geometry(page, scope + '-selected');
  await screenshot(page, 'source-selected-' + scope);
  // 不点击“应用修改”或任何保存动作；取消编辑并保留页面面料草稿，最后关页丢弃。
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await dialog.waitFor({ state: 'hidden' });
}
async function viewportChecks(bom, refs, fabrics, semiFinished, viewport) {
  const scope = viewport.width + 'x' + viewport.height;
  const page = await context.newPage();
  page.on('pageerror', error => report.pageErrors.push({ scope, type: error.name }));
  try {
    await page.setViewportSize(viewport);
    await page.goto(new URL('/boms/' + bomId + '/edit', base).href, { waitUntil: 'domcontentloaded' });
    await page.locator('#bom-material-tab').click();
    const labels = await page.locator('#bom-material-panel .section-sidebar .section-tabs button > span').allTextContents();
    check(JSON.stringify(labels) === JSON.stringify(['型材', '五金', '塑料', '面料', '裁剪明细', '辅料', '包材']), 'MATERIAL_CATEGORY_ORDER', { scope, labels });
    await navigation(page, '面料').click();
    const table = page.locator('.fabric-table');
    await waitTable(table);
    const beforeCount = await table.locator('.el-table__body tr').count();
    await page.getByRole('button', { name: '添加面料', exact: true }).click();
    await page.waitForFunction(count => document.querySelectorAll('.fabric-table .el-table__body tr').length === count + 1, beforeCount);
    const row = table.locator('.el-table__body tr').last();
    const material = refs.fabric_materials?.find(item => validMaterial(item.material_name)), specification = refs.fabric_specifications?.[0];
    if (!material && !specification) { gap(scope, '真实规格和材质字典均为空，无法验证不填裁片名但已选择资料的来源候选。'); await screenshot(page, 'fabric-missing-references-' + scope); return; }
    if (specification) await selectOption(page, row.getByRole('combobox').nth(0), specification.specification_name);
    if (material) await selectOption(page, row.getByRole('combobox').nth(1), material.material_name);
    check(await row.getByPlaceholder('填写裁片').inputValue() === '', 'SOURCE_DOES_NOT_REQUIRE_FABRIC_PART_NAME', { scope });
    check(await table.locator('.el-table__body tr').count() === beforeCount + 1, 'FABRIC_ADDED_ONLY_TO_BROWSER_DRAFT', { scope });
    await geometry(page, scope + '-fabric');
    await screenshot(page, 'fabric-unsaved-no-name-' + scope);
    const fabricLines = bom.sections.filter(section => section.title === '面料类').flatMap(section => section.lines);
    const baselineCount = fabricLines.filter(line => line.id && line.unit === '米').length;
    const cutting = await openCuttingEditor(page, bom, semiFinished, scope);
    if (cutting === null) return;
    const attributes = ` · ${material?.material_name || ''} · ${specification?.specification_name || ''}`;
    await checkSource(page, '面料' + attributes, baselineCount, scope + '-no-name', cutting, material?.material_name);
    const actualName = fabrics.find(item => item.material_name)?.material_name || fabricLines.find(line => line.part_name)?.part_name;
    if (!actualName) { gap(scope, '真实面料原料与已有面料行都没有可用名称；无名称来源已验，具名来源未验。'); return; }
    await navigation(page, '面料').click();
    await table.locator('.el-table__body tr').last().getByPlaceholder('填写裁片').fill(actualName);
    await navigation(page, '裁剪明细').click();
    await editCuttingRow(page, cutting.index);
    await checkSource(page, actualName + attributes, baselineCount, scope + '-named', cutting, material?.material_name);
    check(report.blockedWrites.length === 0, 'FLOW_COMPLETED_WITHOUT_SAVE_OR_CONFIRM_REQUEST', { scope });
  } catch (error) { failure(error, 'VIEWPORT_CHECK_ABORTED'); await screenshot(page, 'failure-' + scope).catch(() => gap(scope, '失败现场无法截图。')); }
  finally { await page.close(); }
}
async function main() {
  fs.mkdirSync(output, { recursive: true }); requireCondition(inside(output, root), 'OUTPUT_SCOPE', '证据目录必须在项目内。'); outputReady = true;
  const stateFile = process.env.BOM_FABRIC_QA_STORAGE_STATE;
  requireCondition(Boolean(stateFile) && fs.existsSync(stateFile), 'STORAGE_STATE_REQUIRED', '缺少 BOM_FABRIC_QA_STORAGE_STATE，禁止自动登录。');
  const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
  requireCondition(Array.isArray(state.cookies), 'INVALID_STORAGE_STATE', '已有会话文件格式无效。');
  requireCondition(/^https?:$/.test(base.protocol) && ['localhost', '127.0.0.1'].includes(base.hostname), 'TARGET_SCOPE', '只允许指定本机开发服务。');
  const executablePath = [process.env.BOM_FABRIC_QA_BROWSER_PATH, 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'].filter(Boolean).find(file => fs.existsSync(file));
  requireCondition(Boolean(executablePath), 'BROWSER_MISSING', '未找到已安装 Chrome 或 Edge。');
  requireCondition(!fs.existsSync(profile), 'PROFILE_ALREADY_EXISTS', '登记的 profile 已存在，拒绝覆盖或清理既有目录。');
  fs.mkdirSync(taskRoot, { recursive: true }); requireCondition(inside(taskRoot, root), 'PROFILE_ROOT_SCOPE', '临时目录不在登记范围。');
  fs.mkdirSync(profile); profileCreated = true; report.resources.created = true;
  context = await chromium.launchPersistentContext(profile, { executablePath, headless: true, viewport: { width: 1920, height: 1080 }, locale: 'zh-CN', serviceWorkers: 'block', env: { ...process.env, TEMP: profile, TMP: profile, TMPDIR: profile } });
  context.setDefaultTimeout(15000);
  await context.addCookies(state.cookies);
  await context.addInitScript(({ origins }) => { const match = (origins || []).find(item => item.origin === location.origin); for (const entry of match?.localStorage || []) localStorage.setItem(entry.name, entry.value); }, { origins: state.origins || [] });
  await context.route('**/*', async route => {
    const request = route.request();
    if (!['GET', 'HEAD'].includes(request.method())) { report.blockedWrites.push({ method: request.method(), route: safeRoute(request.url()) }); await route.abort('blockedbyclient'); }
    else await route.continue();
  });
  context.on('response', response => { if (!new URL(response.url()).pathname.startsWith('/api/')) return; const item = { method: response.request().method(), route: safeRoute(response.url()), status: response.status() }; report.apiReads.push(item); if (item.status >= 400) report.httpErrors.push(item); });
  const me = await getJson('/api/auth/me/', 'existing-session');
  requireCondition(me.status === 200 && me.body?.authenticated === true, 'SESSION_EXPIRED', '已有会话不可用，禁止自动登录。');
  const target = await getJson('/api/v1/boms/' + bomId + '/', 'target-bom');
  requireCondition(target.status === 200 && target.body?.data?.product_information_confirmed === true, 'TARGET_BOM_UNAVAILABLE', '目标必须可读且产品已核对。');
  const refs = await getJson('/api/v1/boms/editor-reference-options/', 'real-fabric-references');
  requireCondition(refs.status === 200, 'REFERENCE_API_UNAVAILABLE', '真实编辑资料接口不可读，无法完成输入。');
  const fabrics = await getJson('/api/v1/boms/fabric-materials/?page_size=100', 'real-fabric-materials');
  const semiFinished = await getJson('/api/v1/boms/semi-finished-materials/?page_size=100', 'real-semi-finished-materials');
  if (fabrics.status !== 200) gap('真实面料名称资料', '接口不可读；仅在目标 BOM 有真实面料名称时验证具名路径。');
  if (semiFinished.status !== 200) gap('真实裁剪半成品资料', '接口不可读；仅在目标 BOM 有可用裁剪行时验证联动。');
  for (const viewport of [{ width: 1920, height: 1080 }, { width: 1102, height: 884 }]) await viewportChecks(target.body.data, refs.body.data, fabrics.body?.data || [], semiFinished.body?.data || [], viewport);
  const after = await getJson('/api/v1/boms/' + bomId + '/', 'target-bom-after-readonly-flow');
  if (after.status === 200 && digest(after.body?.data) === digest(target.body.data)) check(true, 'SERVER_BOM_UNCHANGED');
  else gap('服务器数据复核', '前后读取不同或复核失败；可能存在并行操作。自身写请求另行断言，不能据此声称服务器未变。');
  check(report.blockedWrites.length === 0, 'NO_NETWORK_WRITE_ATTEMPTS', { count: report.blockedWrites.length });
  check(report.pageErrors.length === 0, 'NO_BROWSER_RUNTIME_ERRORS', { count: report.pageErrors.length });
  check(report.httpErrors.length === 0, 'NO_API_HTTP_ERRORS', { count: report.httpErrors.length });
}
main().catch(error => { failure(error, 'QA_ABORTED'); report.status = ['STORAGE_STATE_REQUIRED', 'SESSION_EXPIRED', 'BROWSER_MISSING', 'PROFILE_ALREADY_EXISTS', 'TARGET_BOM_UNAVAILABLE', 'REFERENCE_API_UNAVAILABLE'].includes(error.code) ? 'BLOCKED' : 'FAIL'; }).finally(async () => {
  if (context) { try { await context.close(); report.resources.browserClosed = true; } catch { check(false, 'BROWSER_CLOSE_FAILED'); } }
  if (profileCreated) {
    try {
      requireCondition(!context || report.resources.browserClosed, 'PROFILE_IN_USE', '未确认浏览器关闭，保留 profile 并报告。');
      requireCondition(inside(profile, taskRoot) && fs.realpathSync(profile) === path.join(fs.realpathSync(taskRoot), 'profile'), 'CLEANUP_SCOPE', 'profile 不在登记范围，停止清理。');
      fs.rmSync(profile, { recursive: true, force: false }); report.resources.removed = true; report.resources.verifiedAbsent = !fs.existsSync(profile); check(report.resources.verifiedAbsent, 'PROFILE_CLEANED_AND_VERIFIED');
    } catch (error) { failure(error, 'PROFILE_CLEANUP_FAILED'); }
  }
  if (report.status === 'RUNNING') report.status = report.checks.some(item => !item.passed) ? 'FAIL' : report.notCovered.length ? 'PARTIAL' : 'PASS';
  if (profileCreated && !report.resources.verifiedAbsent) report.status = 'FAIL';
  report.finishedAt = new Date().toISOString();
  if (outputReady) fs.writeFileSync(path.join(output, 'readonly-report.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ status: report.status, checks: report.checks.length, failed: report.checks.filter(item => !item.passed).length, notCovered: report.notCovered.length, report: outputReady ? path.join(output, 'readonly-report.json') : null }));
  process.exitCode = report.status === 'PASS' ? 0 : report.status === 'BLOCKED' ? 2 : 1;
});

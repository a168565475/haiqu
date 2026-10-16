/** 面料自动同步页面：真实只读 API + 已有 Session + headless；仅应用本地草稿，禁止保存或建档。 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('../src/frontend/node_modules/playwright-core');
const root = path.resolve(__dirname, '..');
const taskRoot = path.join(root, '.tmp', 'fabric_auto_sync_20261016');
const profile = path.join(taskRoot, 'profile');
const output = process.env.QA_REPORT_DIR ? path.resolve(process.env.QA_REPORT_DIR, 'fabric-auto-sync')
  : path.join(root, 'output', 'playwright', 'fabric-auto-sync-20261016');
const base = new URL(process.env.BOM_FABRIC_SYNC_QA_BASE_URL || 'http://localhost:8080');
const bomId = 'dbe06399-b6f0-40b1-bdba-9e0d9b2861da';
const report = { schemaVersion: 1, startedAt: new Date().toISOString(), status: 'RUNNING', mode: 'real-api-read-only',
  scope: { excluded: '真实保存、自动复用或新增原料、并发建档不在本脚本执行范围；本脚本不声称真实建档通过。' },
  hashComparisons: [], checks: [], apiReads: [], readonlyPreviewRequests: [], sourcePickerRequests: [], blockedWrites: [], pageErrors: [], httpErrors: [], screenshots: [], measurements: [], notCovered: [],
  resources: { profile, output, created: false, browserClosed: false, removed: false, verifiedAbsent: false, taskRootCreated: false, taskRootRemoved: false } };
let context, outputReady = false, currentStep = 'startup';
function requireCondition(condition, code, message) { if (!condition) { const error = new Error(message); error.code = code; error.qaSafe = true; throw error; } }
function check(condition, code, detail = {}) { report.checks.push({ code, passed: Boolean(condition), ...detail }); }
function gap(scope, reason) { report.notCovered.push({ scope, reason }); }
function failure(error, fallback) { check(false, error.code || fallback, { step: currentStep, message: error.qaSafe ? error.message : '检查未完成；未输出请求正文、响应正文或会话凭据。', errorType: error.name }); }
function safeRoute(raw) { try { return new URL(raw, base).pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, ':id'); } catch { return 'invalid-url'; } }
function inside(candidate, parent) { const relative = path.relative(fs.realpathSync(parent), fs.realpathSync(candidate)); return relative !== '' && !relative.startsWith('..') && !path.isAbsolute(relative); }
function digest(value) { return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex'); }
function text(value) { return String(value ?? '').trim(); }
function dimensions(value) { return text(value).replace(/\s+/g, '').replace(/[×xX]/g, '*'); }
function decimal(value) { const raw = text(value); return /^\d+(?:\.\d+)?$/.test(raw) ? String(Number(raw)) : raw; }
function validMaterial(value) { return Boolean(text(value) && text(value) !== '/'); }
function originalMaterial(line) { return line.cutting_material_original ?? line.material; }
function fabricLines(bom) { return bom.sections.filter(section => section.title === '面料类').flatMap(section => section.lines); }
function cuttingLines(bom) { return bom.sections.filter(section => section.title === '裁剪明细').flatMap(section => section.lines); }
function colorLabel(line) { return [line.fabric_color_card, line.fabric_color_name, line.fabric_color_code].filter(Boolean).join(' / '); }
function sourceLabel(line) { return [line.part_name || '面料', line.fabric_color_name || line.material, line.specification].join(' · '); }
async function getJson(route, kind) {
  const url = new URL(route, base);
  requireCondition(url.origin === base.origin && url.pathname.startsWith('/api/'), 'API_SCOPE', '只允许读取指定本机服务 API。');
  const response = await context.request.get(url.href, { maxRedirects: 0 });
  report.apiReads.push({ kind, route: safeRoute(url.href), status: response.status() });
  if (response.status() !== 200) {
    report.httpErrors.push({ kind, route: safeRoute(url.href), status: response.status() });
    return { status: response.status(), body: null };
  }
  return { status: 200, body: await response.json() };
}
async function screenshot(page, name) { const file = path.join(output, name + '.png'); await page.screenshot({ path: file, fullPage: true }); report.screenshots.push(file); }
async function geometry(page, scope) {
  const measured = await page.evaluate(() => {
    const measure = selector => { const node = document.querySelector(selector); if (!node?.getClientRects().length) return null; const r = node.getBoundingClientRect(), s = getComputedStyle(node); return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height, clientWidth: node.clientWidth, scrollWidth: node.scrollWidth, clientHeight: node.clientHeight, scrollHeight: node.scrollHeight, overflowX: s.overflowX, overflowY: s.overflowY }; };
    return { width: innerWidth, height: innerHeight, documentWidth: document.documentElement.scrollWidth, dialog: measure('.bom-line-editor-dialog'),
      dropdowns: [...document.querySelectorAll('.el-select-dropdown')].filter(node => node.getClientRects().length).map(node => { const r = node.getBoundingClientRect(); return { x: r.x, right: r.right, y: r.y, bottom: r.bottom }; }) };
  });
  report.measurements.push({ scope, measured });
  check(measured.documentWidth <= measured.width + 1, 'NO_PAGE_HORIZONTAL_OVERFLOW', { scope });
  if (measured.dialog) check(measured.dialog.x >= -1 && measured.dialog.y >= -1 && measured.dialog.right <= measured.width + 1 && measured.dialog.bottom <= measured.height + 1, 'DIALOG_WITHIN_VIEWPORT', { scope });
  check(measured.dropdowns.every(item => item.x >= -1 && item.y >= -1 && item.right <= measured.width + 1 && item.bottom <= measured.height + 1), 'REFERENCE_OPTIONS_WITHIN_VIEWPORT', { scope });
}
async function fieldValue(dialog, name) {
  const labelText = new RegExp('^' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$');
  const field = dialog.locator('label.drawer-field').filter({ has: dialog.page().locator('span').filter({ hasText: labelText }) });
  const select = field.locator('.el-select__selected-item:not(.el-select__input-wrapper):not(.is-transparent)');
  if (await select.count()) return text(await select.first().innerText());
  const input = field.locator('input');
  return await input.count() ? text(await input.first().inputValue()) : text(await field.locator('.drawer-readonly-value').innerText());
}
async function selectReference(page, dialog, name, label) {
  const select = dialog.getByRole('combobox', { name, exact: true });
  await select.click();
  const listId = await select.getAttribute('aria-controls');
  requireCondition(Boolean(listId), 'REFERENCE_LISTBOX_MISSING', '面料属性缺少候选列表关联。');
  const list = page.locator('[id="' + listId + '"]');
  const option = list.getByRole('option', { name: label, exact: true });
  await option.waitFor({ state: 'visible' });
  await option.click();
  await list.waitFor({ state: 'hidden' });
}
async function noSourcePrompt(dialog, scope) {
  check(await dialog.getByRole('combobox', { name: '来源原材料', exact: true }).count() === 0, 'NO_MANUAL_FABRIC_SOURCE_SELECTOR', { scope });
  check(!/来源原材料（材质、规格以所选原料为准）|请选择有效米制面料原料|请关联有效原材料/.test(await dialog.innerText()), 'NO_MANUAL_FABRIC_SOURCE_PROMPT', { scope });
}
function navigation(page, label) { return page.locator('#bom-material-panel .section-sidebar .section-tabs').getByText(label, { exact: true }); }
async function waitTable(page, type) { const table = page.locator('.' + type + '-table'); await table.waitFor({ state: 'visible' }); await table.locator('.el-loading-mask').waitFor({ state: 'hidden' }); return table; }
async function closeEditor(page) { const dialog = page.locator('.bom-line-editor-dialog'); await dialog.getByRole('button', { name: '取消', exact: true }).click(); await dialog.waitFor({ state: 'hidden' }); }
async function openRow(page, type, index) {
  const table = await waitTable(page, type), row = table.locator('.el-table__body tr').nth(index);
  await row.hover();
  await row.getByRole('button', { name: '编辑当前行', exact: true }).click();
  const dialog = page.locator('.bom-line-editor-dialog'); await dialog.waitFor({ state: 'visible' }); return dialog;
}
async function compareFabricFields(dialog, line, scope) {
  for (const [label, value, normalize] of [['规格', line.specification, dimensions], ['材质', line.material, text], ['门幅', line.fabric_width, decimal], ['色卡', colorLabel(line), text], ['单个用量', line.unit_consumption, decimal], ['裁片', line.part_name, text]]) {
    check(normalize(await fieldValue(dialog, label)) === normalize(value), 'FABRIC_PARAMETER_PRESERVED', { scope, field: label });
  }
  check(text(await fieldValue(dialog, '单位')) === '米', 'FABRIC_UNIT_IS_METERS', { scope });
  for (const label of ['面料规格', '面料材质', '面料色卡颜色色号', '面料门幅']) {
    const control = dialog.getByRole('combobox', { name: label, exact: true });
    check(await control.count() === 1 && await control.isEnabled() && await control.isEditable(), 'FABRIC_REFERENCE_EDITABLE', { scope, field: label, hasSource: Boolean(line.source_inventory_material_id) });
  }
  await noSourcePrompt(dialog, scope);
}
async function checkCancelledMaterialChange(page, bom, refs, scope) {
  const line = fabricLines(bom)[0];
  const alternative = refs.fabric_materials.find(item => validMaterial(item.material_name) && text(item.material_name) !== text(line.material));
  if (!alternative) { gap(scope + '-修改取消', '真实材质字典缺少不同有效值，未伪造资料或声称取消恢复通过。'); return; }
  currentStep = scope + '-cancel-fabric-material';
  const dialog = await openRow(page, 'fabric', 0);
  await selectReference(page, dialog, '面料材质', alternative.material_name);
  check(text(await fieldValue(dialog, '材质')) === text(alternative.material_name), 'REAL_ALTERNATIVE_FABRIC_MATERIAL_SELECTED', { scope });
  await screenshot(page, 'changed-fabric-before-cancel-' + scope);
  await closeEditor(page);
  const reopened = await openRow(page, 'fabric', 0);
  await compareFabricFields(reopened, line, scope + '-after-cancel');
  check(text(await fieldValue(reopened, '材质')) === text(line.material), 'CANCEL_RESTORES_ORIGINAL_FABRIC_MATERIAL', { scope });
  const persisted = await getJson('/api/v1/boms/' + bomId + '/', 'bom-after-cancel');
  const persistedLine = persisted.body?.data?.sections?.flatMap(section => section.lines).find(item => item.id === line.id);
  check(persisted.status === 200 && persistedLine?.source_inventory_material_id === line.source_inventory_material_id, 'CANCEL_PRESERVES_SERVER_FABRIC_SOURCE', { scope });
  await screenshot(page, 'original-fabric-after-cancel-' + scope);
  await closeEditor(page);
}
function chooseDraftReferences(bom, refs) {
  const line = fabricLines(bom).find(item => text(item.part_name) && Number(item.unit_consumption) > 0);
  if (!line) return null;
  const material = refs.fabric_materials.find(item => validMaterial(item.material_name) && text(item.material_name) !== text(line.material)) || refs.fabric_materials.find(item => validMaterial(item.material_name));
  const specification = refs.fabric_specifications.find(item => item.id === line.source_fabric_specification_id) || refs.fabric_specifications.find(item => text(item.specification_name));
  const width = refs.fabric_widths.find(item => item.id === line.source_fabric_width_id) || refs.fabric_widths.find(item => Number(item.width_value) > 0);
  const color = refs.product_colors.find(item => item.id === line.source_product_color_id) || refs.product_colors.find(item => text(item.color_name));
  if (!material || !specification || !width || !color) return null;
  return { part_name: line.part_name, material: material.material_name, specification: specification.specification_name, fabric_width: width.width_value,
    fabric_color_card: color.color_card, fabric_color_name: color.color_name, fabric_color_code: color.color_code, unit_consumption: line.unit_consumption };
}
async function addLocalFabric(page, bom, refs, scope) {
  currentStep = scope + '-new-fabric-local-draft';
  const draft = chooseDraftReferences(bom, refs);
  if (!draft) { gap(scope + '-未保存面料', '真实现有行或有效字典不完整，未伪造面料与裁剪来源。'); return null; }
  await navigation(page, '面料').click();
  const table = await waitTable(page, 'fabric'), beforeCount = await table.locator('.el-table__body tr').count();
  await page.getByRole('button', { name: '添加面料', exact: true }).click();
  await page.waitForFunction(count => document.querySelectorAll('.fabric-table .el-table__body tr').length === count + 1, beforeCount);
  const dialog = await openRow(page, 'fabric', beforeCount);
  for (const [label, value] of [['面料规格', draft.specification], ['面料材质', draft.material], ['面料色卡颜色色号', colorLabel(draft)], ['面料门幅', draft.fabric_width]]) await selectReference(page, dialog, label, text(value));
  await dialog.getByRole('textbox', { name: '裁片', exact: true }).fill(text(draft.part_name));
  await dialog.getByRole('textbox', { name: '单个用量', exact: true }).fill(text(draft.unit_consumption));
  await compareFabricFields(dialog, draft, scope + '-draft-before-apply');
  await geometry(page, scope + '-draft-before-apply');
  await screenshot(page, 'unsaved-fabric-before-apply-' + scope);
  // 已审查该按钮仅执行纯计算预览和本地应用；不点击顶部保存、确认或上传。
  await dialog.getByRole('button', { name: '应用修改', exact: true }).click();
  await dialog.waitFor({ state: 'hidden' });
  check(await table.locator('.el-table__body tr').count() === beforeCount + 1, 'NEW_FABRIC_APPLIED_ONLY_TO_LOCAL_DRAFT', { scope });
  const reopened = await openRow(page, 'fabric', beforeCount);
  await compareFabricFields(reopened, draft, scope + '-draft-after-apply');
  await screenshot(page, 'unsaved-fabric-after-apply-' + scope);
  await closeEditor(page);
  return draft;
}
function cuttingExpectation(line, bom) {
  const original = originalMaterial(line);
  if (validMaterial(original)) return { value: text(original), mode: 'own' };
  const source = fabricLines(bom).find(item => item.id === line.fabric_source_line_id);
  return source && validMaterial(source.material) ? { value: text(source.material), mode: 'inherited' } : null;
}
async function inspectExistingCutting(page, bom, scope) {
  currentStep = scope + '-current-cutting';
  await navigation(page, '裁剪明细').click();
  const table = await waitTable(page, 'cutting'), lines = cuttingLines(bom);
  check(await table.locator('.el-table__body tr').count() === lines.length, 'CURRENT_CUTTING_ROWS_MATCH_API', { scope, count: lines.length });
  const candidates = [];
  for (const [index, line] of lines.entries()) {
    if (text(line.category + ' ' + line.cutting_category).includes('管材')) continue;
    const expected = cuttingExpectation(line, bom);
    if (!expected) { gap(scope + '-裁剪第' + (index + 1) + '行', '当前裁剪无有效自有材质与来源面料，未冒充材质继承通过。'); continue; }
    const dialog = await openRow(page, 'cutting', index);
    check(text(await fieldValue(dialog, '材质')) === expected.value, expected.mode === 'own' ? 'CURRENT_CUTTING_OWN_MATERIAL_PRESERVED' : 'CURRENT_CUTTING_INHERITS_FABRIC_MATERIAL', { scope, row: index + 1 });
    candidates.push({ line, index, expected });
    if (!candidates.slice(0, -1).some(item => item.expected.mode === expected.mode)) { await geometry(page, scope + '-cutting-' + expected.mode); await screenshot(page, 'current-cutting-' + expected.mode + '-' + scope); }
    await closeEditor(page);
  }
  for (const mode of ['own', 'inherited']) if (!candidates.some(item => item.expected.mode === mode)) gap(scope + '-裁剪' + mode, '当前真实裁剪资料没有此材质场景，未造数据。');
  return candidates;
}
async function chooseUnsavedFabric(page, bom, draft, candidates, scope) {
  await navigation(page, '裁剪明细').click();
  const baselineCount = fabricLines(bom).filter(line => line.id && line.unit === '米').length;
  for (const mode of ['inherited', 'own']) {
    const candidate = candidates.find(item => item.expected.mode === mode);
    if (!candidate) continue;
    currentStep = scope + '-unsaved-source-' + mode;
    const dialog = await openRow(page, 'cutting', candidate.index);
    const control = dialog.getByRole('combobox', { name: '来源面料', exact: true });
    await control.click();
    const listId = await control.getAttribute('aria-controls');
    requireCondition(Boolean(listId), 'FABRIC_SOURCE_LISTBOX_MISSING', '来源面料缺少候选列表关联。');
    const list = page.locator('[id="' + listId + '"]'); await list.waitFor({ state: 'visible' });
    check(await list.getByRole('option').count() === baselineCount + 1, 'UNSAVED_FABRIC_ADDS_SOURCE_OPTION', { scope, mode, expectedCount: baselineCount + 1 });
    const expectedLabel = sourceLabel(draft), option = list.getByRole('option', { name: expectedLabel, exact: true }).last();
    requireCondition(await option.count() === 1, 'UNSAVED_FABRIC_SOURCE_MISSING', '当前未保存的面料没有出现在来源面料下拉。');
    await geometry(page, currentStep + '-options');
    await screenshot(page, 'unsaved-source-options-' + mode + '-' + scope);
    await option.click(); await list.waitFor({ state: 'hidden' });
    check(text(await fieldValue(dialog, '来源面料')) === expectedLabel, 'UNSAVED_FABRIC_SELECTED_WITHOUT_SAVE', { scope, mode });
    const expectedMaterial = mode === 'own' ? candidate.expected.value : text(draft.material);
    check(text(await fieldValue(dialog, '材质')) === expectedMaterial, mode === 'own' ? 'CUTTING_OWN_MATERIAL_OVERRIDES_UNSAVED_FABRIC' : 'CUTTING_INHERITS_UNSAVED_FABRIC_MATERIAL', { scope });
    await screenshot(page, 'unsaved-source-selected-' + mode + '-' + scope);
    await closeEditor(page);
    const reopened = await openRow(page, 'cutting', candidate.index);
    check(text(await fieldValue(reopened, '材质')) === candidate.expected.value, 'CANCEL_RESTORES_CUTTING_MATERIAL', { scope, mode });
    const originalSource = fabricLines(bom).find(item => item.id === candidate.line.fabric_source_line_id);
    if (originalSource) check(text(await fieldValue(reopened, '来源面料')) === sourceLabel(originalSource), 'CANCEL_RESTORES_CUTTING_FABRIC_SOURCE', { scope, mode });
    await closeEditor(page);
  }
}
async function viewportChecks(bom, refs, viewport) {
  const scope = viewport.width + 'x' + viewport.height, page = await context.newPage();
  page.on('pageerror', error => report.pageErrors.push({ scope, type: error.name }));
  try {
    await page.setViewportSize(viewport);
    await page.goto(new URL('/boms/' + bomId + '/edit', base).href, { waitUntil: 'domcontentloaded' });
    await page.locator('#bom-material-tab').click();
    await navigation(page, '面料').click();
    const table = await waitTable(page, 'fabric'), lines = fabricLines(bom);
    check(await table.locator('.el-table__body tr').count() === lines.length, 'CURRENT_FABRIC_ROWS_MATCH_API', { scope, count: lines.length });
    for (const [index, line] of lines.entries()) {
      currentStep = scope + '-current-fabric-' + (index + 1);
      const dialog = await openRow(page, 'fabric', index);
      await compareFabricFields(dialog, line, currentStep);
      await geometry(page, currentStep);
      await screenshot(page, 'current-fabric-' + (index + 1) + '-' + scope);
      await closeEditor(page);
    }
    await checkCancelledMaterialChange(page, bom, refs, scope);
    const candidates = await inspectExistingCutting(page, bom, scope);
    const draft = await addLocalFabric(page, bom, refs, scope);
    if (draft) await chooseUnsavedFabric(page, bom, draft, candidates, scope);
  } catch (error) { failure(error, 'VIEWPORT_CHECK_ABORTED'); await screenshot(page, 'failure-' + scope).catch(() => gap(scope, '失败现场无法截图。')); }
  finally { await page.close(); }
}
async function main() {
  fs.mkdirSync(output, { recursive: true }); requireCondition(inside(output, root), 'OUTPUT_SCOPE', '证据目录必须在项目内。'); outputReady = true;
  const stateFile = process.env.BOM_FABRIC_SYNC_QA_STORAGE_STATE;
  requireCondition(Boolean(stateFile) && fs.existsSync(stateFile), 'STORAGE_STATE_REQUIRED', '缺少 BOM_FABRIC_SYNC_QA_STORAGE_STATE，禁止自动登录。');
  const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
  requireCondition(Array.isArray(state.cookies), 'INVALID_STORAGE_STATE', '已有会话格式无效。');
  requireCondition(/^https?:$/.test(base.protocol) && ['localhost', '127.0.0.1'].includes(base.hostname), 'TARGET_SCOPE', '只允许指定本机开发服务。');
  const executablePath = [process.env.BOM_FABRIC_SYNC_QA_BROWSER_PATH, 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'].filter(Boolean).find(file => fs.existsSync(file));
  requireCondition(Boolean(executablePath), 'BROWSER_MISSING', '没有可用的已安装浏览器。');
  requireCondition(!fs.existsSync(profile), 'PROFILE_ALREADY_EXISTS', '独占 profile 已存在，禁止覆盖或清理既有目录。');
  report.resources.taskRootCreated = !fs.existsSync(taskRoot);
  fs.mkdirSync(taskRoot, { recursive: true }); requireCondition(inside(taskRoot, root), 'PROFILE_ROOT_SCOPE', '临时目录不在登记范围。');
  fs.mkdirSync(profile); report.resources.created = true;
  requireCondition(inside(profile, taskRoot) && fs.realpathSync(profile) === path.join(fs.realpathSync(taskRoot), 'profile'), 'PROFILE_SCOPE', 'profile 不在登记范围，停止启动。');
  // 同时约束 Playwright 所在 Node 子进程的临时产物；进程退出后不会修改父进程环境。
  process.env.TEMP = profile;
  process.env.TMP = profile;
  process.env.TMPDIR = profile;
  context = await chromium.launchPersistentContext(profile, { executablePath, headless: true, locale: 'zh-CN', serviceWorkers: 'block', env: { ...process.env, TEMP: profile, TMP: profile, TMPDIR: profile } });
  context.setDefaultTimeout(15000);
  await context.addCookies(state.cookies);
  await context.addInitScript(({ origins }) => { const match = (origins || []).find(item => item.origin === location.origin); for (const entry of match?.localStorage || []) localStorage.setItem(entry.name, entry.value); }, { origins: state.origins || [] });
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.pathname === '/api/v1/boms/fabric-materials/') report.sourcePickerRequests.push({ method: request.method(), route: url.pathname });
    // 唯一非 GET/HEAD 例外：views.material_flow_preview 只执行纯计算，已有无写入后端测试覆盖。
    const readonlyPreview = request.method() === 'POST' && url.origin === base.origin && url.pathname === '/api/v1/boms/material-flow-preview/';
    if (readonlyPreview) report.readonlyPreviewRequests.push({ method: 'POST', route: url.pathname });
    if (!['GET', 'HEAD'].includes(request.method()) && !readonlyPreview) { report.blockedWrites.push({ method: request.method(), route: safeRoute(request.url()) }); await route.abort('blockedbyclient'); }
    else await route.continue();
  });
  context.on('response', response => { if (!new URL(response.url()).pathname.startsWith('/api/')) return; const item = { method: response.request().method(), route: safeRoute(response.url()), status: response.status() }; report.apiReads.push(item); if (item.status >= 400) report.httpErrors.push(item); });
  const me = await getJson('/api/auth/me/', 'existing-session'); requireCondition(me.status === 200 && me.body?.authenticated === true, 'SESSION_EXPIRED', '已有会话不可用，禁止自动登录。');
  const target = await getJson('/api/v1/boms/' + bomId + '/', 'target-bom');
  requireCondition(target.status === 200 && target.body?.data?.product_information_confirmed === true, 'TARGET_BOM_UNAVAILABLE', '目标 BOM 必须可读且产品已核对。');
  const lines = fabricLines(target.body.data);
  requireCondition(lines.length > 0, 'TARGET_FABRIC_LINES_MISSING', '目标 BOM 没有可核验面料行。');
  const reference = await getJson('/api/v1/boms/editor-reference-options/', 'fabric-references');
  requireCondition(reference.status === 200 && reference.body?.data, 'REFERENCE_API_UNAVAILABLE', '真实面料字典接口不可读。');
  const refs = reference.body.data;
  requireCondition(['fabric_materials', 'fabric_specifications', 'fabric_widths', 'product_colors'].every(key => Array.isArray(refs[key])), 'REFERENCE_CONTRACT_INVALID', '真实面料字典结构不符合当前契约。');
  const archives = new Map();
  for (const [index, line] of lines.entries()) {
    if (!line.source_inventory_material_id) { gap('已关联面料第' + (index + 1) + '行', '真实记录尚未关联库存来源，已关联面料解锁编辑和档案读回未覆盖；未写库制造场景。'); continue; }
    const source = await getJson('/api/v1/raw-materials/' + line.source_inventory_material_id + '/', 'existing-fabric-source');
    requireCondition(source.status === 200 && source.body?.data?.id === line.source_inventory_material_id, 'EXISTING_SOURCE_UNAVAILABLE', '已有面料来源不可读。');
    check(source.body.data.item_type === 'MATERIAL' && source.body.data.category_name === '面料' && source.body.data.unit_name === '米' && !source.body.data.archived_at, 'EXISTING_SOURCE_IS_ACTIVE_METRIC_FABRIC', { row: index + 1 });
    archives.set(line.source_inventory_material_id, digest(source.body.data));
  }
  gap('真实保存/自动建档', '本脚本只验证浏览器草稿与只读接口，不执行真实保存、复用或新增原料，不声称真实写入链路通过。');
  for (const viewport of [{ width: 1102, height: 884 }, { width: 1440, height: 900 }]) await viewportChecks(target.body.data, refs, viewport);
  const after = await getJson('/api/v1/boms/' + bomId + '/', 'bom-after-readonly-flow');
  const beforeHash = digest(target.body.data), afterHash = after.status === 200 ? digest(after.body?.data) : null;
  report.hashComparisons.push({ scope: 'bom', beforeHash, afterHash, equal: beforeHash === afterHash });
  check(beforeHash === afterHash, 'SERVER_BOM_UNCHANGED');
  for (const [id, beforeHash] of archives) {
    const afterSource = await getJson('/api/v1/raw-materials/' + id + '/', 'existing-fabric-source-after');
    const afterHash = afterSource.status === 200 ? digest(afterSource.body?.data) : null;
    report.hashComparisons.push({ scope: 'fabric-source', beforeHash, afterHash, equal: beforeHash === afterHash });
    check(beforeHash === afterHash, 'SERVER_FABRIC_SOURCE_UNCHANGED');
  }
  check(report.sourcePickerRequests.length === 0, 'NO_MANUAL_FABRIC_PICKER_API_DEPENDENCY', { count: report.sourcePickerRequests.length });
  check(report.blockedWrites.length === 0, 'NO_NETWORK_WRITE_ATTEMPTS', { count: report.blockedWrites.length });
  check(report.pageErrors.length === 0, 'NO_BROWSER_RUNTIME_ERRORS', { count: report.pageErrors.length });
  check(report.httpErrors.length === 0, 'NO_API_HTTP_ERRORS', { count: report.httpErrors.length });
}
main().catch(error => { failure(error, 'QA_ABORTED'); report.status = ['STORAGE_STATE_REQUIRED', 'SESSION_EXPIRED', 'BROWSER_MISSING', 'PROFILE_ALREADY_EXISTS', 'TARGET_BOM_UNAVAILABLE', 'TARGET_FABRIC_LINES_MISSING', 'REFERENCE_API_UNAVAILABLE', 'EXISTING_SOURCE_UNAVAILABLE'].includes(error.code) ? 'BLOCKED' : 'FAIL'; }).finally(async () => {
  if (context) { try { await context.close(); report.resources.browserClosed = true; } catch { check(false, 'BROWSER_CLOSE_FAILED'); } }
  if (report.resources.created) {
    try {
      requireCondition(!context || report.resources.browserClosed, 'PROFILE_IN_USE', '浏览器未确认关闭，保留 profile。');
      requireCondition(inside(profile, taskRoot) && fs.realpathSync(profile) === path.join(fs.realpathSync(taskRoot), 'profile'), 'CLEANUP_SCOPE', 'profile 不在登记范围，停止清理。');
      fs.rmSync(profile, { recursive: true, force: false }); report.resources.removed = true; report.resources.verifiedAbsent = !fs.existsSync(profile); check(report.resources.verifiedAbsent, 'PROFILE_CLEANED_AND_VERIFIED');
      // Session 和父目录由主任务清理，此脚本只清理自身独占 profile。
    } catch (error) { failure(error, 'PROFILE_CLEANUP_FAILED'); }
  }
  if (report.status === 'RUNNING') report.status = report.checks.some(item => !item.passed) ? 'FAIL' : report.notCovered.length ? 'PASS_WITH_GAPS' : 'PASS';
  if (report.resources.created && !report.resources.verifiedAbsent) report.status = 'FAIL';
  report.finishedAt = new Date().toISOString();
  if (outputReady) fs.writeFileSync(path.join(output, 'readonly-report.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ qa_result_version: 1, status: report.status, not_covered: report.notCovered.map(item => item.scope + '：' + item.reason), cleanup: !report.resources.created || report.resources.verifiedAbsent,
    checks: report.checks.length, failed: report.checks.filter(item => !item.passed).length, failure: report.checks.find(item => !item.passed), report: outputReady ? path.join(output, 'readonly-report.json') : null }));
  process.exitCode = ['PASS', 'PASS_WITH_GAPS'].includes(report.status) ? 0 : report.status === 'BLOCKED' ? 2 : 1;
});

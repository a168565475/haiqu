/** 管材自动建档页面：已有 Session + 真实只读 API + headless；仅应用本地草稿，禁止保存或建档。 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('../src/frontend/node_modules/playwright-core');
const root = path.resolve(__dirname, '..');
const taskRoot = path.join(root, '.tmp', 'pipe_auto_sync_20261016');
const profile = path.join(taskRoot, 'profile');
const output = process.env.QA_REPORT_DIR ? path.resolve(process.env.QA_REPORT_DIR, 'pipe-auto-sync')
  : path.join(root, 'output', 'playwright', 'pipe-auto-sync-20261016');
const base = new URL(process.env.BOM_PIPE_QA_BASE_URL || 'http://localhost:8080');
const bomId = 'dbe06399-b6f0-40b1-bdba-9e0d9b2861da';
const report = { schemaVersion: 1, startedAt: new Date().toISOString(), status: 'RUNNING', mode: 'real-api-read-only',
  scope: { excluded: '保存 BOM 时自动复用或新增原料属于写入路径，由后端业务/API 测试覆盖；本脚本不声称真实建档通过。' },
  checks: [], apiReads: [], readonlyPreviewRequests: [], matchRequests: [], blockedWrites: [], pageErrors: [], httpErrors: [], screenshots: [], measurements: [], notCovered: [],
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
function dimensions(value) { return text(value).replace(/\s+/g, '').replace(/[×xX]/g, '*').replace(/[ΦφФ]/g, 'φ'); }
function decimal(value) { const raw = text(value); return /^\d+(?:\.\d+)?$/.test(raw) ? String(Number(raw)) : raw; }
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
  requireCondition(Boolean(listId), 'REFERENCE_LISTBOX_MISSING', '管材属性缺少候选列表关联。');
  const list = page.locator('[id="' + listId + '"]');
  const option = list.getByRole('option', { name: label, exact: true });
  await option.waitFor({ state: 'visible' });
  await option.click();
  await list.waitFor({ state: 'hidden' });
}
async function noSourcePrompt(dialog, scope) {
  check(await dialog.getByTestId('pipe-material-match').count() === 0, 'NO_SOURCE_MATCH_STATUS', { scope });
  check(await dialog.getByRole('combobox', { name: '对应原料', exact: true }).count() === 0, 'NO_SOURCE_SELECTOR', { scope });
  check(await dialog.getByRole('button', { name: '重新匹配', exact: true }).count() === 0, 'NO_SOURCE_RETRY', { scope });
  check(!/该规格尚未建立原料档案|请核对原料档案后确认选择|原料匹配中|对应原料/.test(await dialog.innerText()), 'NO_SOURCE_MATCH_PROMPT', { scope });
}
async function closeEditor(page) { const dialog = page.locator('.bom-line-editor-dialog'); await dialog.getByRole('button', { name: '取消', exact: true }).click(); await dialog.waitFor({ state: 'hidden' }); }
async function openRow(page, index) {
  const row = page.locator('.tube-table .el-table__body tr').nth(index);
  await row.hover();
  await row.getByRole('button', { name: '编辑当前行', exact: true }).click();
  const dialog = page.locator('.bom-line-editor-dialog'); await dialog.waitFor({ state: 'visible' }); return dialog;
}
async function checkCancelledThicknessChange(page, line, index, scope) {
  currentStep = scope + '-cancel-changed-thickness';
  const dialog = await openRow(page, index);
  const thickness = dialog.getByRole('combobox', { name: '厚度', exact: true });
  await thickness.click();
  const listId = await thickness.getAttribute('aria-controls');
  requireCondition(Boolean(listId), 'THICKNESS_LISTBOX_MISSING', '厚度缺少真实候选列表关联。');
  const list = page.locator('[id="' + listId + '"]');
  await list.waitFor({ state: 'visible' });
  const options = await list.getByRole('option').evaluateAll(nodes => nodes.filter(node => node.getAttribute('aria-disabled') !== 'true' && !node.classList.contains('is-disabled')).map(node => node.textContent.trim()));
  const alternative = options.find(value => /^\d+(?:\.\d+)?$/.test(value) && Number(value) > 0 && decimal(value) !== decimal(line.tube_thickness));
  if (!alternative) {
    gap(scope + '-修改后取消', '真实厚度下拉没有其他有效数值，未伪造厚度，也未声称取消恢复已验收。');
    await thickness.press('Escape');
    await closeEditor(page);
    return;
  }
  await list.getByRole('option', { name: alternative, exact: true }).click();
  await list.waitFor({ state: 'hidden' });
  check(decimal(await fieldValue(dialog, '厚度')) === decimal(alternative), 'REAL_ALTERNATIVE_THICKNESS_SELECTED', { scope, row: index + 1 });
  await screenshot(page, 'changed-thickness-before-cancel-' + scope);
  await closeEditor(page);
  const reopened = await openRow(page, index);
  check(decimal(await fieldValue(reopened, '厚度')) === decimal(line.tube_thickness), 'CANCEL_RESTORES_ORIGINAL_THICKNESS', { scope, row: index + 1 });
  await noSourcePrompt(reopened, currentStep + '-reopened');
  const persisted = await getJson('/api/v1/boms/' + bomId + '/', 'target-bom-after-cancel');
  const persistedLine = persisted.body?.data?.sections?.flatMap(section => section.lines).find(item => item.id === line.id);
  check(persisted.status === 200 && persistedLine?.source_inventory_material_id === line.source_inventory_material_id, 'CANCEL_PRESERVES_SERVER_SOURCE', { scope, row: index + 1 });
  await screenshot(page, 'original-thickness-after-cancel-' + scope);
  await closeEditor(page);
}
async function viewportChecks(bom, viewport) {
  const scope = viewport.width + 'x' + viewport.height;
  const page = await context.newPage();
  page.on('pageerror', error => report.pageErrors.push({ scope, type: error.name }));
  try {
    await page.setViewportSize(viewport);
    await page.goto(new URL('/boms/' + bomId + '/edit', base).href, { waitUntil: 'domcontentloaded' });
    await page.locator('#bom-material-tab').click();
    await page.locator('#bom-material-panel .section-sidebar .section-tabs').getByText('型材', { exact: true }).click();
    await page.locator('.tube-table').waitFor({ state: 'visible' });
    const lines = bom.sections.find(section => section.section_type === 'PROFILE')?.lines || [];
    check(await page.locator('.tube-table .el-table__body tr').count() === lines.length, 'CURRENT_ROWS_MATCH_REAL_BOM', { scope, count: lines.length });
    for (let index = 0; index < lines.length; index++) {
      currentStep = scope + '-current-pipe-' + (index + 1);
      const line = lines[index], detail = { scope, row: index + 1, hasSource: Boolean(line.source_inventory_material_id) };
      const dialog = await openRow(page, index);
      await noSourcePrompt(dialog, currentStep);
      for (const [label, value, normalize] of [
        ['形状', line.tube_shape, text], ['品名', line.part_name, text], ['材质', line.material, text], ['规格', line.tube_diameter, dimensions], ['厚度', line.tube_thickness, decimal],
        ['切割长度（mm）', line.length_value, decimal], ['单个用量', line.unit_consumption, decimal], ['切割支数', line.tube_cut_piece_count, decimal],
      ]) check(normalize(await fieldValue(dialog, label)) === normalize(value), 'CURRENT_PARAMETER_UNCHANGED', { ...detail, field: label });
      for (const label of ['形状', '品名', '材质', '规格', '厚度']) {
        const control = dialog.getByRole('combobox', { name: label, exact: true });
        check(await control.count() === 1 && await control.isEnabled() && await control.isEditable(), 'LINKED_PIPE_ATTRIBUTE_EDITABLE', { ...detail, field: label });
      }
      if (index === 0) { await geometry(page, scope + '-current'); await screenshot(page, 'current-pipe-' + scope); }
      await closeEditor(page);
    }
    const linkedIndex = lines.findIndex(line => line.source_inventory_material_id && text(line.tube_thickness));
    if (linkedIndex >= 0) await checkCancelledThicknessChange(page, lines[linkedIndex], linkedIndex, scope);
    else gap(scope + '-修改后取消', '当前没有可核验的已关联管材行，未声称取消恢复已验收。');
    currentStep = scope + '-incomplete-archive-draft';
    const sourceLine = lines.find(line => line.part_name && Number(line.length_value) > 0 && Number(line.unit_consumption) > 0 && Number(line.tube_cut_piece_count) > 0);
    requireCondition(Boolean(sourceLine), 'REAL_DRAFT_VALUES_MISSING', '缺少可复用的真实管材品名与切割参数，禁止伪造测试资料。');
    await page.getByRole('button', { name: '添加材料', exact: true }).click();
    const dialog = page.locator('.bom-line-editor-dialog'); await dialog.waitFor({ state: 'visible' });
    await selectReference(page, dialog, '品名', sourceLine.part_name);
    for (const [label, value] of [['切割长度（mm）', sourceLine.length_value], ['单个用量', sourceLine.unit_consumption], ['切割支数', sourceLine.tube_cut_piece_count]]) await dialog.getByRole('textbox', { name: label, exact: true }).fill(text(value));
    for (const label of ['形状', '材质', '规格', '厚度']) check(!text(await fieldValue(dialog, label)), 'DRAFT_ARCHIVE_ATTRIBUTE_LEFT_EMPTY', { scope, field: label });
    await noSourcePrompt(dialog, currentStep);
    await geometry(page, currentStep);
    await screenshot(page, 'incomplete-draft-' + scope);
    // 品名和切割参数沿用真实行，仅缺少建档属性；纯计算预览后只应用到浏览器草稿，不保存 BOM。
    await dialog.getByRole('button', { name: '应用修改', exact: true }).click();
    await dialog.waitFor({ state: 'hidden' });
    check(await page.locator('.tube-table .el-table__body tr').count() === lines.length + 1, 'INCOMPLETE_ARCHIVE_DRAFT_APPLIED_LOCALLY', { scope });
    const applied = await openRow(page, lines.length);
    check(text(await fieldValue(applied, '品名')) === text(sourceLine.part_name), 'LOCAL_DRAFT_NAME_PRESERVED', { scope });
    for (const [label, value] of [['切割长度（mm）', sourceLine.length_value], ['单个用量', sourceLine.unit_consumption], ['切割支数', sourceLine.tube_cut_piece_count]]) check(decimal(await fieldValue(applied, label)) === decimal(value), 'LOCAL_DRAFT_CUTTING_PARAMETER_PRESERVED', { scope, field: label });
    for (const label of ['形状', '材质', '规格', '厚度']) check(!text(await fieldValue(applied, label)), 'LOCAL_DRAFT_MISSING_ATTRIBUTE_NOT_SUBSTITUTED', { scope, field: label });
    await noSourcePrompt(applied, scope + '-applied');
    await screenshot(page, 'applied-local-draft-' + scope);
    await closeEditor(page);
  } catch (error) { failure(error, 'VIEWPORT_CHECK_ABORTED'); await screenshot(page, 'failure-' + scope).catch(() => gap(scope, '失败现场无法截图。')); }
  finally { await page.close(); }
}
async function main() {
  fs.mkdirSync(output, { recursive: true }); requireCondition(inside(output, root), 'OUTPUT_SCOPE', '证据目录必须在项目内。'); outputReady = true;
  const stateFile = process.env.BOM_PIPE_QA_STORAGE_STATE;
  requireCondition(Boolean(stateFile) && fs.existsSync(stateFile), 'STORAGE_STATE_REQUIRED', '缺少 BOM_PIPE_QA_STORAGE_STATE，禁止自动登录。');
  const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
  requireCondition(Array.isArray(state.cookies), 'INVALID_STORAGE_STATE', '已有会话格式无效。');
  requireCondition(/^https?:$/.test(base.protocol) && ['localhost', '127.0.0.1'].includes(base.hostname), 'TARGET_SCOPE', '只允许指定本机开发服务。');
  const executablePath = [process.env.BOM_PIPE_QA_BROWSER_PATH, 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'].filter(Boolean).find(file => fs.existsSync(file));
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
    if (url.pathname === '/api/v1/boms/pipe-material-matches/') report.matchRequests.push({ method: request.method(), route: url.pathname });
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
  const lines = target.body.data.sections.find(section => section.section_type === 'PROFILE')?.lines || [];
  requireCondition(lines.length > 0, 'TARGET_PIPE_LINES_MISSING', '当前 BOM 没有管材行，主体场景阻断。');
  const archives = new Map();
  for (const [index, line] of lines.entries()) {
    if (!line.source_inventory_material_id) { gap('当前管材第 ' + (index + 1) + ' 行', '当前真实记录未关联来源；不能声称其已有来源已读回。'); continue; }
    const source = await getJson('/api/v1/raw-materials/' + line.source_inventory_material_id + '/', 'existing-pipe-source');
    requireCondition(source.status === 200 && source.body?.data?.id === line.source_inventory_material_id, 'EXISTING_SOURCE_UNAVAILABLE', '已有管材来源不可读。');
    check(source.body.data.item_type === 'MATERIAL' && source.body.data.category_name === '管材' && source.body.data.unit_name === '根' && !source.body.data.archived_at, 'EXISTING_SOURCE_IS_ACTIVE_PIPE', { row: index + 1 });
    check(text(source.body.data.material) === text(line.material), 'EXISTING_SOURCE_MATERIAL_MATCHES_BOM', { row: index + 1 });
    archives.set(line.source_inventory_material_id, digest(source.body.data));
  }
  for (const viewport of [{ width: 1920, height: 1080 }, { width: 1102, height: 884 }]) await viewportChecks(target.body.data, viewport);
  const after = await getJson('/api/v1/boms/' + bomId + '/', 'target-bom-after-readonly');
  if (after.status === 200 && digest(after.body?.data) === digest(target.body.data)) check(true, 'SERVER_BOM_UNCHANGED');
  else gap('服务器前后核对', '前后读取不同或失败，可能存在并行操作；不能声称服务器数据未变。');
  for (const [id, before] of archives) { const afterSource = await getJson('/api/v1/raw-materials/' + id + '/', 'existing-pipe-source-after'); check(afterSource.status === 200 && digest(afterSource.body?.data) === before, 'SERVER_SOURCE_UNCHANGED'); }
  check(report.matchRequests.length === 0, 'NO_PIPE_MATCH_API_DEPENDENCY', { count: report.matchRequests.length });
  check(report.blockedWrites.length === 0, 'NO_NETWORK_WRITE_ATTEMPTS', { count: report.blockedWrites.length });
  check(report.pageErrors.length === 0, 'NO_BROWSER_RUNTIME_ERRORS', { count: report.pageErrors.length });
  check(report.httpErrors.length === 0, 'NO_API_HTTP_ERRORS', { count: report.httpErrors.length });
}
main().catch(error => { failure(error, 'QA_ABORTED'); report.status = ['STORAGE_STATE_REQUIRED', 'SESSION_EXPIRED', 'BROWSER_MISSING', 'PROFILE_ALREADY_EXISTS', 'TARGET_BOM_UNAVAILABLE', 'TARGET_PIPE_LINES_MISSING', 'EXISTING_SOURCE_UNAVAILABLE'].includes(error.code) ? 'BLOCKED' : 'FAIL'; }).finally(async () => {
  if (context) { try { await context.close(); report.resources.browserClosed = true; } catch { check(false, 'BROWSER_CLOSE_FAILED'); } }
  if (report.resources.created) {
    try {
      requireCondition(!context || report.resources.browserClosed, 'PROFILE_IN_USE', '浏览器未确认关闭，保留 profile。');
      requireCondition(inside(profile, taskRoot) && fs.realpathSync(profile) === path.join(fs.realpathSync(taskRoot), 'profile'), 'CLEANUP_SCOPE', 'profile 不在登记范围，停止清理。');
      fs.rmSync(profile, { recursive: true, force: false }); report.resources.removed = true; report.resources.verifiedAbsent = !fs.existsSync(profile); check(report.resources.verifiedAbsent, 'PROFILE_CLEANED_AND_VERIFIED');
      if (report.resources.taskRootCreated && fs.readdirSync(taskRoot).length === 0) { fs.rmdirSync(taskRoot); report.resources.taskRootRemoved = !fs.existsSync(taskRoot); }
    } catch (error) { failure(error, 'PROFILE_CLEANUP_FAILED'); }
  }
  if (report.status === 'RUNNING') report.status = report.checks.some(item => !item.passed) ? 'FAIL' : report.notCovered.length ? 'PARTIAL' : 'PASS';
  if (report.resources.created && !report.resources.verifiedAbsent) report.status = 'FAIL';
  report.finishedAt = new Date().toISOString();
  if (outputReady) fs.writeFileSync(path.join(output, 'readonly-report.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ status: report.status, checks: report.checks.length, failed: report.checks.filter(item => !item.passed).length, notCovered: report.notCovered.length, report: outputReady ? path.join(output, 'readonly-report.json') : null }));
  process.exitCode = report.status === 'PASS' ? 0 : report.status === 'BLOCKED' ? 2 : 1;
});

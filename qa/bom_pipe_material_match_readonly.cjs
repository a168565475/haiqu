/** 管材属性匹配：已有 Session + 真实 GET API + headless；只改浏览器草稿，禁止网络写入。 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('../src/frontend/node_modules/playwright-core');
const root = path.resolve(__dirname, '..');
const taskRoot = path.join(root, '.tmp', 'bom_pipe_material_match_20261015');
const profile = path.join(taskRoot, 'profile');
const output = process.env.QA_REPORT_DIR ? path.resolve(process.env.QA_REPORT_DIR, 'bom-pipe-material-match')
  : path.join(root, 'output', 'playwright', 'bom-pipe-material-match-20261015');
const base = new URL(process.env.BOM_PIPE_QA_BASE_URL || 'http://localhost:8080');
const bomId = 'dbe06399-b6f0-40b1-bdba-9e0d9b2861da';
const report = { schemaVersion: 1, startedAt: new Date().toISOString(), status: 'RUNNING', mode: 'real-api-read-only',
  checks: [], apiReads: [], blockedWrites: [], pageErrors: [], httpErrors: [], screenshots: [], measurements: [], domDiagnostics: [], notCovered: [],
  resources: { profile, created: false, browserClosed: false, removed: false, verifiedAbsent: false, taskRootCreated: false, taskRootRemoved: false } };
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
function paramsFor(line) { return { material: text(line.material), diameter: text(line.tube_diameter), thickness: text(line.tube_thickness), tube_shape: text(line.tube_shape), raw_bar_length_m: text(line.tube_cut_length_m || line.raw_bar_length_m) }; }
async function getJson(route, kind, optional = false) {
  const url = new URL(route, base);
  requireCondition(url.origin === base.origin && url.pathname.startsWith('/api/'), 'API_SCOPE', '只允许读取指定本机服务 API。');
  const response = await context.request.get(url.href, { maxRedirects: 0 });
  report.apiReads.push({ kind, route: safeRoute(url.href), status: response.status() });
  if (response.status() !== 200) {
    if (!optional) report.httpErrors.push({ kind, route: safeRoute(url.href), status: response.status() });
    return { status: response.status(), body: null };
  }
  return { status: 200, body: await response.json() };
}
async function matches(params) {
  const query = { ...params };
  if (!/^\d+(?:\.\d+)?$/.test(text(query.raw_bar_length_m)) || Number(query.raw_bar_length_m) <= 0) delete query.raw_bar_length_m;
  const result = await getJson('/api/v1/boms/pipe-material-matches/?' + new URLSearchParams(query), 'pipe-material-match');
  requireCondition(result.status === 200 && Array.isArray(result.body?.data?.candidates), 'MATCH_API_UNAVAILABLE', '真实管材匹配接口不可用。');
  const data = result.body.data;
  requireCondition(['unique', 'multiple', 'no_match', 'incomplete', 'needs_review'].includes(data.reason), 'MATCH_CONTRACT_INVALID', '匹配接口状态不符合已确认契约。');
  check(data.reason !== 'unique' || (data.candidates.length === 1 && data.automatic_source_id === data.candidates[0].id), 'UNIQUE_API_RESULT_HAS_ONE_STABLE_SOURCE');
  check(data.reason === 'unique' || data.automatic_source_id === null, 'AMBIGUOUS_API_RESULT_NEVER_AUTO_SELECTS');
  return data;
}
async function getReferences(resource) {
  const all = [];
  for (let page = 1; page <= 20; page++) {
    const result = await getJson(`/api/v1/reference-data/${resource}/?status=ACTIVE&page_size=100&page=${page}`, 'pipe-reference-' + resource);
    requireCondition(result.status === 200 && Array.isArray(result.body?.data), 'REFERENCE_API_UNAVAILABLE', '真实管材字典不可读。');
    all.push(...result.body.data);
    if (page >= Number(result.body.meta?.total_pages || 1)) return all;
  }
  gap(resource, '字典超过 20 页；只使用已读取的真实记录，未声称全量覆盖。');
  return all;
}
async function screenshot(page, name) { const file = path.join(output, name + '.png'); await page.screenshot({ path: file, fullPage: true }); report.screenshots.push(file); }
async function matchSelectorDiagnostics(page, scope) {
  const region = page.getByTestId('pipe-material-match');
  if (await region.count() !== 1) return;
  const diagnostic = await region.evaluate(node => ({
    role: node.getAttribute('role'), ariaLive: node.getAttribute('aria-live'), reason: node.getAttribute('data-match-reason'),
    controls: [...node.querySelectorAll('.el-select, .el-select__wrapper, input[role="combobox"]')].map(control => ({
      tag: control.tagName, role: control.getAttribute('role'), ariaLabel: control.getAttribute('aria-label'),
      ariaLabelledby: control.getAttribute('aria-labelledby'), ariaControls: control.getAttribute('aria-controls'),
      ariaExpanded: control.getAttribute('aria-expanded'), ariaHidden: control.getAttribute('aria-hidden'),
      ariaDisabled: control.getAttribute('aria-disabled'), hasLayoutBox: control.getClientRects().length > 0,
    })),
  }));
  report.domDiagnostics.push({ scope, step: currentStep, ...diagnostic });
}
async function geometry(page, scope) {
  const measured = await page.evaluate(() => {
    const measure = selector => { const node = document.querySelector(selector); if (!node?.getClientRects().length) return null; const r = node.getBoundingClientRect(), s = getComputedStyle(node); return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height, clientWidth: node.clientWidth, scrollWidth: node.scrollWidth, clientHeight: node.clientHeight, scrollHeight: node.scrollHeight, overflowX: s.overflowX, overflowY: s.overflowY }; };
    return { width: innerWidth, height: innerHeight, documentWidth: document.documentElement.scrollWidth, dialog: measure('.bom-line-editor-dialog'), match: measure('[data-testid="pipe-material-match"]'),
      dropdowns: [...document.querySelectorAll('.el-select-dropdown')].filter(node => node.getClientRects().length).map(node => { const r = node.getBoundingClientRect(); return { x: r.x, right: r.right, y: r.y, bottom: r.bottom }; }) };
  });
  report.measurements.push({ scope, measured });
  check(measured.documentWidth <= measured.width + 1, 'NO_PAGE_HORIZONTAL_OVERFLOW', { scope });
  if (measured.dialog) check(measured.dialog.x >= -1 && measured.dialog.y >= -1 && measured.dialog.right <= measured.width + 1 && measured.dialog.bottom <= measured.height + 1, 'DIALOG_WITHIN_VIEWPORT', { scope });
  check(measured.dropdowns.every(item => item.x >= -1 && item.y >= -1 && item.right <= measured.width + 1 && item.bottom <= measured.height + 1), 'CANDIDATES_WITHIN_VIEWPORT', { scope });
}
async function fieldValue(dialog, name) {
  const labelText = new RegExp('^' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$');
  const field = dialog.locator('label.drawer-field').filter({ has: dialog.page().locator('span').filter({ hasText: labelText }) });
  const select = field.locator('.el-select__selected-item:not(.el-select__input-wrapper)');
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
async function waitMatch(page, expected) {
  const region = page.getByTestId('pipe-material-match');
  await region.waitFor({ state: 'visible' });
  const expectedText = expected.reason === 'unique' ? '已关联' : expected.reason === 'no_match' ? '该规格尚未建立原料档案' : expected.candidates.length ? '对应原料' : '';
  await page.waitForFunction(({ reason, expectedText }) => {
    const region = document.querySelector('[data-testid="pipe-material-match"]');
    if (!region || region.textContent.includes('匹配中')) return false;
    if (region.dataset.matchReason) return region.dataset.matchReason === (reason === 'unique' ? 'linked' : reason) && region.dataset.loading !== 'true';
    return Boolean(expectedText) && region.textContent.includes(expectedText);
  }, { reason: expected.reason, expectedText });
  return region;
}
async function closeEditor(page) { const dialog = page.locator('.bom-line-editor-dialog'); await dialog.getByRole('button', { name: '取消', exact: true }).click(); await dialog.waitFor({ state: 'hidden' }); }
async function openRow(page, index) {
  const row = page.locator('.tube-table .el-table__body tr').nth(index);
  await row.hover();
  await row.getByRole('button', { name: '编辑当前行', exact: true }).click();
  const dialog = page.locator('.bom-line-editor-dialog'); await dialog.waitFor({ state: 'visible' }); return dialog;
}
async function discoverScenarios(refs, currentLines) {
  const result = await getJson('/api/v1/boms/pipe-materials/?page_size=100', 'real-pipe-catalog', true);
  if (result.status !== 200) { gap('真实候选', '管材列表不可读，未创建测试资料。'); return []; }
  const scenarios = [], tried = new Set();
  const shapeLabels = [...new Set([...currentLines.map(line => line.tube_shape), ...refs.shapes.map(item => item.shape_name)].filter(Boolean))]
    .filter(label => refs.shapes.some(item => item.shape_name === label)).slice(0, 4);
  for (const brief of (result.body?.data || []).slice(0, 30)) {
    const details = await getJson('/api/v1/raw-materials/' + brief.id + '/', 'real-pipe-attributes', true);
    if (details.status !== 200) { gap('真实原料字段', '原料详情不可读，无法依据真实截面、厚度进行草稿验证。'); break; }
    const item = details.body?.data;
    if (!item) continue;
    const material = refs.materials.find(ref => text(ref.material_name) === text(item.material));
    const diameter = refs.diameters.find(ref => dimensions(ref.diameter_value) === dimensions(item.diameter));
    const thickness = refs.thicknesses.find(ref => decimal(ref.thickness_value) === decimal(item.thickness));
    if (!material || !diameter || !thickness || !text(item.diameter) || !text(item.thickness)) continue;
    for (const shape of shapeLabels) {
      const params = { material: material.material_name, diameter: diameter.diameter_value, thickness: thickness.thickness_value, tube_shape: shape };
      const key = JSON.stringify(params); if (tried.has(key)) continue; tried.add(key);
      const match = await matches(params);
      if (!match.candidates.some(candidate => candidate.id === brief.id)) continue;
      if (!scenarios.some(scenario => scenario.match.reason === match.reason)) scenarios.push({ params, match });
      if (scenarios.some(scenario => scenario.match.reason === 'multiple') && scenarios.some(scenario => scenario.match.reason === 'needs_review')) return scenarios;
    }
  }
  return scenarios;
}
async function viewportChecks(bom, scenarios, viewport) {
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
    let noMatchSeen = 0;
    for (let index = 0; index < lines.length; index++) {
      currentStep = scope + '-current-pipe-' + (index + 1);
      const line = lines[index];
      const dialog = await openRow(page, index);
      if (line.source_inventory_material_id) {
        const region = page.getByTestId('pipe-material-match');
        await region.getByText(/已关联/).waitFor({ state: 'visible' });
        check(await region.getAttribute('data-source-id') === line.source_inventory_material_id, 'EXISTING_STABLE_SOURCE_PRESERVED', { scope, row: index + 1 });
      } else {
        const params = paramsFor(line);
        params.raw_bar_length_m = await fieldValue(dialog, '原材料长度（m）');
        const expected = await matches(params);
        const region = await waitMatch(page, expected);
        check(await region.getAttribute('data-source-id') === (expected.automatic_source_id || ''), 'CURRENT_MATCH_EQUALS_REAL_API', { scope, row: index + 1, reason: expected.reason });
        check(text(await fieldValue(dialog, '材质')) === text(line.material), 'CURRENT_MATERIAL_UNCHANGED', { scope, row: index + 1 });
        check(dimensions(await fieldValue(dialog, '规格')) === dimensions(line.tube_diameter), 'CURRENT_DIAMETER_UNCHANGED', { scope, row: index + 1 });
        check(decimal(await fieldValue(dialog, '厚度')) === decimal(line.tube_thickness), 'CURRENT_THICKNESS_UNCHANGED', { scope, row: index + 1, thickness: line.tube_thickness });
        if (expected.reason === 'no_match') { noMatchSeen++; check((await region.innerText()).includes('该规格尚未建立原料档案'), 'CURRENT_NO_MATCH_EXPLICIT', { scope, row: index + 1 }); }
      }
      if (index === 0) { await geometry(page, scope + '-current'); await screenshot(page, 'current-pipe-' + scope); }
      await closeEditor(page);
    }
    if (noMatchSeen) check(true, 'CURRENT_UNMATCHED_ROWS_CHECKED', { scope, count: noMatchSeen });
    else gap(scope + '-当前未建档管材', '读取时现有行已无 no_match 状态，可能资料已被并行修改；未按旧记录硬编码结果。');
    for (const scenario of scenarios) {
      currentStep = scope + '-draft-' + scenario.match.reason;
      await page.getByRole('button', { name: '添加材料', exact: true }).click();
      const dialog = page.locator('.bom-line-editor-dialog'); await dialog.waitFor({ state: 'visible' });
      for (const [label, value] of [['形状', scenario.params.tube_shape], ['材质', scenario.params.material], ['规格', scenario.params.diameter], ['厚度', scenario.params.thickness]]) await selectReference(page, dialog, label, value);
      const params = { ...scenario.params, raw_bar_length_m: await fieldValue(dialog, '原材料长度（m）') };
      const expected = await matches(params);
      const region = await waitMatch(page, expected);
      if (expected.reason === 'unique') check(await region.getAttribute('data-source-id') === expected.automatic_source_id, 'UNIQUE_REAL_PIPE_AUTO_ASSOCIATED', { scope });
      else {
        requireCondition(expected.candidates.length > 0, 'DRAFT_CANDIDATES_CHANGED', '浏览器草稿实际匹配不再包含真实原料候选，请核对并行变更。');
        check(!(await region.getAttribute('data-source-id')), 'REVIEW_REQUIRED_NO_IMPLICIT_ASSOCIATION', { scope, reason: expected.reason });
        currentStep = scope + '-draft-' + expected.reason + '-locate-candidate-trigger';
        await matchSelectorDiagnostics(page, scope);
        const select = region.locator('.el-select');
        requireCondition(await select.count() === 1, 'PIPE_SELECT_AMBIGUOUS', '匹配状态区须有且只有一个对应原料选择器。');
        // 非 filterable 的 Element Plus Select 将 combobox input 隐藏；点击可见 wrapper，仅读隐藏 input 的 ARIA 关联。
        const trigger = select.locator('.el-select__wrapper');
        await trigger.waitFor({ state: 'visible' });
        currentStep = scope + '-draft-' + expected.reason + '-open-candidate-options';
        await trigger.click();
        await matchSelectorDiagnostics(page, scope);
        const listId = await select.locator('input[role="combobox"]').getAttribute('aria-controls');
        requireCondition(Boolean(listId), 'PIPE_LISTBOX_MISSING', '对应原料选择器缺少候选列表关联。');
        currentStep = scope + '-draft-' + expected.reason + '-read-candidate-options';
        const list = page.locator('[id="' + listId + '"]'); await list.waitFor({ state: 'visible' });
        check(await list.getByRole('option').count() === expected.candidates.length, 'CANDIDATES_EQUAL_REAL_MATCH_API', { scope, reason: expected.reason });
        const candidate = expected.candidates[0];
        const option = list.getByRole('option').filter({ hasText: candidate.material_number });
        requireCondition(await option.count() === 1, 'CANDIDATE_LABEL_AMBIGUOUS', '真实原料编码在候选中缺失或重复。');
        await geometry(page, scope + '-' + scenario.match.reason + '-options');
        await screenshot(page, 'draft-' + scenario.match.reason + '-options-' + scope);
        currentStep = scope + '-draft-' + expected.reason + '-choose-real-candidate';
        await option.click();
        await page.waitForFunction(id => document.querySelector('[data-testid="pipe-material-match"]')?.dataset.sourceId === id, candidate.id);
        check(await region.getAttribute('data-source-id') === candidate.id, 'REAL_PIPE_MANUALLY_ASSOCIATED', { scope, reason: expected.reason });
      }
      check(decimal(await fieldValue(dialog, '厚度')) === decimal(scenario.params.thickness), 'MATCH_NEVER_SUBSTITUTES_THICKNESS', { scope, reason: scenario.match.reason });
      await geometry(page, scope + '-' + scenario.match.reason);
      await screenshot(page, 'draft-' + scenario.match.reason + '-selected-' + scope);
      await closeEditor(page);
    }
  } catch (error) { failure(error, 'VIEWPORT_CHECK_ABORTED'); await matchSelectorDiagnostics(page, scope).catch(() => gap(scope, '失败现场选择器属性无法读取。')); await screenshot(page, 'failure-' + scope).catch(() => gap(scope, '失败现场无法截图。')); }
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
  await context.route('**/*', async route => { const request = route.request(); if (!['GET', 'HEAD'].includes(request.method())) { report.blockedWrites.push({ method: request.method(), route: safeRoute(request.url()) }); await route.abort('blockedbyclient'); } else await route.continue(); });
  context.on('response', response => { if (!new URL(response.url()).pathname.startsWith('/api/')) return; const item = { method: response.request().method(), route: safeRoute(response.url()), status: response.status() }; report.apiReads.push(item); if (item.status >= 400) report.httpErrors.push(item); });
  const me = await getJson('/api/auth/me/', 'existing-session'); requireCondition(me.status === 200 && me.body?.authenticated === true, 'SESSION_EXPIRED', '已有会话不可用，禁止自动登录。');
  const target = await getJson('/api/v1/boms/' + bomId + '/', 'target-bom');
  requireCondition(target.status === 200 && target.body?.data?.product_information_confirmed === true, 'TARGET_BOM_UNAVAILABLE', '目标 BOM 必须可读且产品已核对。');
  const lines = target.body.data.sections.find(section => section.section_type === 'PROFILE')?.lines || [];
  requireCondition(lines.length > 0, 'TARGET_PIPE_LINES_MISSING', '当前 BOM 没有管材行，主体场景阻断。');
  const refs = { shapes: await getReferences('tube-shapes'), materials: await getReferences('tube-materials'), diameters: await getReferences('tube-diameters'), thicknesses: await getReferences('tube-thicknesses') };
  const scenarios = await discoverScenarios(refs, lines);
  for (const viewport of [{ width: 1920, height: 1080 }, { width: 1102, height: 884 }]) await viewportChecks(target.body.data, scenarios, viewport);
  const after = await getJson('/api/v1/boms/' + bomId + '/', 'target-bom-after-readonly');
  if (after.status === 200 && digest(after.body?.data) === digest(target.body.data)) check(true, 'SERVER_BOM_UNCHANGED');
  else gap('服务器前后核对', '前后读取不同或失败，可能存在并行操作；不能声称服务器数据未变。');
  check(report.blockedWrites.length === 0, 'NO_NETWORK_WRITE_ATTEMPTS', { count: report.blockedWrites.length });
  check(report.pageErrors.length === 0, 'NO_BROWSER_RUNTIME_ERRORS', { count: report.pageErrors.length });
  check(report.httpErrors.length === 0, 'NO_API_HTTP_ERRORS', { count: report.httpErrors.length });
  if (!report.checks.some(item => item.code === 'UNIQUE_REAL_PIPE_AUTO_ASSOCIATED' && item.passed)) gap('真实自动关联页面', '本次真实数据缺少可自动匹配证据，未出现可靠唯一自动关联路径；本脚本不声称该路径通过。');
  for (const reason of ['multiple', 'needs_review']) if (!report.checks.some(item => item.code === 'REAL_PIPE_MANUALLY_ASSOCIATED' && item.reason === reason && item.passed)) gap(reason, scenarios.some(scenario => scenario.match.reason === reason)
    ? '已发现真实候选，但页面验证中断或未通过；详见失败检查，不记为通过。'
    : '已读取的真实库存和字典未覆盖该类手选场景；未造数据或伪造接口。');
}
main().catch(error => { failure(error, 'QA_ABORTED'); report.status = ['STORAGE_STATE_REQUIRED', 'SESSION_EXPIRED', 'BROWSER_MISSING', 'PROFILE_ALREADY_EXISTS', 'TARGET_BOM_UNAVAILABLE', 'TARGET_PIPE_LINES_MISSING', 'REFERENCE_API_UNAVAILABLE', 'MATCH_API_UNAVAILABLE'].includes(error.code) ? 'BLOCKED' : 'FAIL'; }).finally(async () => {
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

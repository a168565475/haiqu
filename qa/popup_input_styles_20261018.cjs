/** 弹窗输入样式回归：真实 Element Plus 渲染，headless；不调用业务 API。 */
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const root = path.resolve(__dirname, '..');
const frontend = path.join(root, 'src/frontend');
const fromFrontend = createRequire(path.join(frontend, 'package.json'));
const { createSSRApp, h } = fromFrontend('vue');
const { renderToString } = fromFrontend('@vue/server-renderer');
const { ElInput, ElInputNumber, ElSelect, ElForm, ElFormItem, ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } = fromFrontend('element-plus');
const { chromium } = fromFrontend('playwright-core');
const sass = fromFrontend('sass');
const runtime = path.join(root, 'qa/_tmp/popup-input-styles-20261018');
const output = path.join(root, 'docs/superpowers/reports/2026-10-18-popup-input-states');
const result = { kind: 'isolated-component-style-regression', checks: [], resources: { runtime, created: false, removed: false } };
let browser;
function check(name, passed, evidence) { result.checks.push({ name, passed, evidence }); }
async function run() {
  if (fs.existsSync(runtime)) throw new Error('本次临时目录已存在，不复用来源未知资源');
  fs.mkdirSync(runtime, { recursive: true }); result.resources.created = true;
  try {
    const row = (id, component, props) => h('div', { id }, [h(component, props)]);
    const app = createSSRApp({ render: () => h('main', { class: 'app-window-dialog' }, [
      row('normal', ElInput, { modelValue: '普通输入' }),
      row('readonly', ElInput, { modelValue: '只读值', readonly: true }),
      row('disabled', ElInput, { modelValue: '禁用值', disabled: true }),
      row('select', ElSelect, { placeholder: '请选择' }),
      row('number', ElInputNumber, { modelValue: 123456 }),
      row('number-right', ElInputNumber, { modelValue: 123456, controlsPosition: 'right' }),
      row('number-no-controls', ElInputNumber, { modelValue: 123456, controls: false }),
      row('textarea', ElInput, { modelValue: '备注', type: 'textarea', maxlength: 200, showWordLimit: true, rows: 3 }),
      h('input', { id: 'native-input', value: '原生文本' }),
      h('select', { id: 'native-select' }, [h('option', '原生选择')]),
      h('textarea', { id: 'native-textarea', 'aria-invalid': 'true', style: 'padding-bottom:34px' }, '原生备注'),
      h(ElForm, {}, { default: () => h(ElFormItem, { id: 'error', error: '必填' }, { default: () => h(ElInput) }) }),
      h('div', { class: 'el-table' }, [row('table-input', ElInput, { modelValue: '表格例外' })]),
      h('div', { class: 'paper' }, [row('paper-input', ElInput, { modelValue: '纸面例外' })]),
    ]) });
    app.provide(ID_INJECTION_KEY, { prefix: 100, current: 0 });
    app.provide(ZINDEX_INJECTION_KEY, { current: 0 });
    const markup = await renderToString(app);
    const executablePath = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
    if (!executablePath) throw new Error('未找到已安装浏览器');
    browser = await chromium.launch({ executablePath, headless: true, env: { ...process.env, TEMP: runtime, TMP: runtime, TMPDIR: runtime } });
    const page = await browser.newPage({ viewport: { width: 1102, height: 884 } });
    const theme = sass.compile(path.join(frontend, 'src/styles/theme.scss')).css;
    const library = fs.readFileSync(fromFrontend.resolve('element-plus/dist/index.css'), 'utf8');
    await page.setContent(`<style>${library}\n${theme}\nmain{padding:24px;width:700px;display:grid;grid-template-columns:1fr 1fr;gap:24px} .el-table .el-input__wrapper,.paper .el-input__wrapper{height:24px;padding:0 6px;border-radius:3px}</style>${markup}`);
    const measure = selector => page.locator(selector).evaluate(el => {
      const s = getComputedStyle(el), r = el.getBoundingClientRect();
      return { height: r.height, paddingLeft: s.paddingLeft, paddingRight: s.paddingRight, paddingBottom: s.paddingBottom, radius: s.borderRadius, background: s.backgroundColor, image: s.backgroundImage, shadow: s.boxShadow, danger: s.getPropertyValue('--erp-color-danger').trim(), readonly: s.getPropertyValue('--erp-input-readonly-background').trim(), disabled: s.getPropertyValue('--erp-input-disabled-background').trim() };
    });
    const normal = await measure('#normal .el-input__wrapper');
    check('normal-32-12-8', normal.height === 32 && normal.paddingLeft === '12px' && normal.paddingRight === '12px' && normal.radius === '8px', normal);
    const select = await measure('#select .el-select__wrapper');
    check('select-shares-normal-surface', select.height === 32 && select.image === normal.image && select.shadow === normal.shadow, select);
    const readonly = await measure('#readonly .el-input__wrapper');
    const disabled = await measure('#disabled .el-input__wrapper');
    check('readonly-disabled-distinct', readonly.image === 'none' && disabled.image === 'none' && readonly.background !== disabled.background, { readonly, disabled });
    for (const id of ['number', 'number-right']) {
      const positions = await page.locator(`#${id} .el-input-number`).evaluate(el => {
        const input = el.querySelector('input').getBoundingClientRect();
        return [...el.querySelectorAll('.el-input-number__increase,.el-input-number__decrease')].map(n => {
          const button = n.getBoundingClientRect();
          return { input: { left: input.left, right: input.right }, button: { left: button.left, right: button.right }, overlap: Math.min(button.right, input.right) - Math.max(button.left, input.left) > 0 };
        });
      });
      check(`${id}-text-clear-of-buttons`, positions.every(p => !p.overlap), positions);
    }
    const without = await measure('#number-no-controls .el-input__wrapper');
    check('number-no-controls-12px', without.paddingLeft === '12px' && without.paddingRight === '12px', without);
    const textarea = await measure('#textarea textarea');
    check('textarea-counter-space', parseFloat(textarea.paddingBottom) >= 22, textarea);
    for (const id of ['native-input', 'native-select']) {
      const value = await measure(`#${id}`);
      check(`${id}-shares-normal-surface`, value.height === 32 && value.radius === '8px' && value.image === normal.image, value);
    }
    const nativeTextarea = await measure('#native-textarea');
    check('native-textarea-surface-and-counter-space', nativeTextarea.radius === '8px' && nativeTextarea.image === normal.image && nativeTextarea.paddingBottom === '34px', nativeTextarea);
    const error = await measure('#error .el-input__wrapper');
    const danger = await page.locator('#error').evaluate(el => { const n = document.createElement('span'); n.style.color = 'var(--erp-color-danger)'; el.append(n); const color = getComputedStyle(n).color; n.remove(); return color; });
    check('error-border-retained', error.shadow.includes(danger), error);
    await page.locator('#error input').focus();
    // SSR 后直接聚焦实际 DOM，并补上组件在客户端聚焦时使用的状态类。
    await page.locator('#error .el-input__wrapper').evaluate(el => el.classList.add('is-focus'));
    const focusedError = await measure('#error .el-input__wrapper');
    check('focused-error-border-retained', focusedError.shadow.includes(danger), focusedError);
    for (const id of ['table-input', 'paper-input']) {
      const value = await measure(`#${id} .el-input__wrapper`);
      check(`${id}-retains-local-geometry`, value.height === 24 && value.paddingLeft === '6px' && value.radius === '3px', value);
    }
    await page.screenshot({ path: `${output}.png` });
  } finally {
    if (browser) await browser.close();
    if (result.resources.created && path.resolve(runtime) === path.resolve(root, 'qa/_tmp/popup-input-styles-20261018')) {
      fs.rmSync(runtime, { recursive: true }); result.resources.removed = !fs.existsSync(runtime);
    }
  }
  result.passed = result.checks.every(c => c.passed) && result.resources.removed;
  fs.writeFileSync(`${output}.json`, JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ passed: result.passed, checks: result.checks.map(({ name, passed }) => ({ name, passed })), cleaned: result.resources.removed }));
  if (!result.passed) process.exitCode = 1;
}
run().catch(error => { console.error(error); process.exitCode = 1; });

// 只读记录字体及既有外壳；不保存会话或完整业务数据。
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('../src/frontend/node_modules/playwright-core');

const root = path.resolve(__dirname, '..');
const evidence = path.join(root, 'output/product-catalog-20261016-2ebd7b22');
const temp = path.join(root, '.tmp/product-catalog-20261016-2ebd7b22/baseline-browser');
const state = process.env.PRODUCT_CATALOG_QA_STORAGE_STATE;
const report = { mode: 'read-only-baseline', resources: { path: temp, created: false, removed: false }, viewports: [] };
let browser;

(async () => {
  try {
    if (!state || !fs.existsSync(state)) throw new Error('需要既有有效Session文件');
    if (fs.existsSync(temp)) throw new Error('浏览器临时目录已存在');
    fs.mkdirSync(evidence, { recursive: true });
    fs.writeFileSync(path.join(evidence, 'visual-baseline.json'), JSON.stringify(report, null, 2));
    fs.mkdirSync(temp); report.resources.created = true;
    process.env.TEMP = temp; process.env.TMP = temp; process.env.TMPDIR = temp;
    const executablePath = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);
    if (!executablePath) throw new Error('找不到现有浏览器');
    browser = await chromium.launch({ headless: true, executablePath, downloadsPath: temp });
    const context = await browser.newContext({ storageState: state, locale: 'zh-CN', timezoneId: 'Asia/Shanghai', serviceWorkers: 'block' });
    await context.route('**/*', route => ['GET', 'HEAD'].includes(route.request().method()) ? route.continue() : route.abort('blockedbyclient'));
    const page = await context.newPage();
    for (const [width, height] of [[1920, 1080], [1440, 900]]) {
      await page.setViewportSize({ width, height });
      await page.goto('http://localhost:8080/material-catalog', { waitUntil: 'networkidle' });
      await page.locator('.material-catalog-page').waitFor();
      await page.evaluate(() => document.fonts.ready);
      report.viewports.push(await page.evaluate(() => {
        const measure = selector => {
          const node = document.querySelector(selector);
          if (!node) throw new Error('Missing baseline element: ' + selector);
          const c = getComputedStyle(node), r = node.getBoundingClientRect();
          return { selector, width: r.width, height: r.height, x: r.x, y: r.y, fontFamily: c.fontFamily, fontSize: c.fontSize, lineHeight: c.lineHeight, color: c.color, background: c.backgroundColor };
        };
        return { width: innerWidth, height: innerHeight, bodyFont: getComputedStyle(document.body).fontFamily, elements: ['.erp-layout__sidebar', '.erp-layout__header', '.material-catalog-page', '.material-catalog-page h2'].map(measure) };
      }));
      await page.screenshot({ path: path.join(evidence, `baseline-${width}.png`) });
    }
    report.status = 'PASS';
  } catch (error) {
    report.status = 'FAIL'; report.error = error.message; process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    if (report.resources.created) {
      if (path.dirname(temp) !== path.join(root, '.tmp/product-catalog-20261016-2ebd7b22') || fs.lstatSync(temp).isSymbolicLink() || fs.realpathSync(temp).toLowerCase() !== temp.toLowerCase()) throw new Error('清理路径校验失败');
      fs.rmSync(temp, { recursive: true }); report.resources.removed = !fs.existsSync(temp);
    }
    fs.writeFileSync(path.join(evidence, 'visual-baseline.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ status: report.status, viewports: report.viewports.length, temporaryDirectoryRemoved: report.resources.removed }));
  }
})();

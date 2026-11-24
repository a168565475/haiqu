/** Playwright MCP filename 执行；后台真实会话只读检查，调用方核实并清理登记的浏览器目录。 */
async (sessionPage) => {
  const runtime = 'E:/workspace/_project/project001_haiqu_ERP_CRM/qa/_tmp/bom-print-20261018';
  const output = 'E:/workspace/_project/project001_haiqu_ERP_CRM/docs/superpowers/reports/bom-print-20261018';
  const report = { headless: true, checks: [], pdfs: [], blockedWrites: [], pageErrors: [], runtime };
  const check = (name, passed, details) => report.checks.push({ name, passed, details });
  let context;
  try {
    const state = await sessionPage.context().storageState();
    context = await sessionPage.context().browser().browserType().launchPersistentContext(runtime, { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, viewport: { width: 1102, height: 884 } });
    await context.addCookies(state.cookies);
    await context.addInitScript(origins => { const origin = origins.find(item => item.origin === location.origin); for (const item of origin?.localStorage || []) localStorage.setItem(item.name, item.value); }, state.origins);
    await context.route('**/api/**', route => {
      if (['GET', 'HEAD', 'OPTIONS'].includes(route.request().method())) return route.continue();
      report.blockedWrites.push({ method: route.request().method(), path: new URL(route.request().url()).pathname });
      return route.abort();
    });
    const page = await context.newPage();
    page.on('pageerror', error => report.pageErrors.push(error.message));
    const list = await context.request.get('http://localhost:8080/api/v1/boms/?page_size=100');
    if (!list.ok()) throw new Error(`BOM API ${list.status()}`);
    const records = (await list.json()).data;
    if (!records.length) throw new Error('没有真实 BOM 可验收');
    for (const [index, record] of records.entries()) {
      const api = `http://localhost:8080/api/v1/boms/${record.id}/`;
      const before = await (await context.request.get(api)).json();
      const expectedRows = before.data.sections.reduce((sum, section) => sum + section.lines.length, 0);
      const expectedTitles = before.data.sections.map(section => section.title).sort();
      let printedPreview;
      for (const view of ['preview', 'edit']) {
        const label = `${index + 1}/${view}`;
        await page.emulateMedia({ media: 'screen' });
        await page.goto(`http://localhost:8080/boms/${record.id}/${view}`);
        await page.locator('.bom-print-document').waitFor({ state: 'attached' });
        await page.waitForLoadState('networkidle');
        check(`${label}/屏幕隐藏打印副本`, await page.locator('.bom-print-document').evaluate(el => getComputedStyle(el).display === 'none'));
        await page.emulateMedia({ media: 'print' });
        await page.evaluate(() => document.fonts.ready);
        const document = await page.locator('.bom-print-document').evaluate(root => ({
          text: root.textContent.replace(/\s+/g, ' ').trim(),
          titles: [...root.querySelectorAll('table')].map(table => table.getAttribute('aria-label')).sort(),
          rows: root.querySelectorAll('tbody tr:has([data-field])').length,
          headers: [...root.querySelectorAll('thead')].map(el => getComputedStyle(el).display),
          first: [...root.querySelectorAll('thead tr:last-child th:first-child')].map(el => ({ height: el.getBoundingClientRect().height, text: el.textContent, width: el.getBoundingClientRect().width })),
          font: getComputedStyle(root.querySelector('td')).fontSize,
          titleFont: getComputedStyle(root.querySelector('.bom-print-title')).fontSize,
          background: getComputedStyle(window.document.documentElement).backgroundColor,
          siblings: [...root.parentElement.children].filter(el => el !== root).map(el => getComputedStyle(el).display),
          cellsFit: [...root.querySelectorAll('th,td')].every(el => el.scrollWidth <= el.clientWidth + 1),
        }));
        check(`${label}/七区与真实行数`, document.rows === expectedRows && JSON.stringify(document.titles) === JSON.stringify(expectedTitles), { rows: document.rows, sections: document.titles });
        check(`${label}/字号纸色和布局`, document.font === '12px' && document.titleFont === '16px' && document.background === 'rgb(255, 255, 255)' && document.siblings.every(display => display === 'none') && document.cellsFit, { font: document.font, titleFont: document.titleFont, background: document.background, siblings: document.siblings, cellsFit: document.cellsFit });
        check(`${label}/仅物料明细`, !/生产任务单|销售订单|产品编码|产品规格|BOM计算数量/.test(document.text));
        check(`${label}/跨页重复表头`, document.headers.every(display => display === 'table-header-group'));
        check(`${label}/无原料编号列`, !await page.locator('.bom-print-document thead').evaluateAll(nodes => nodes.some(el => /原料编号|品号/.test(el.textContent))));
        if (view === 'preview') printedPreview = document.text;
        else check(`${label}/两个入口内容一致`, document.text === printedPreview);
        const pdf = `${output}/${index === 0 ? view : `${view}-second`}-after.pdf`;
        await page.pdf({ path: pdf, preferCSSPageSize: true, printBackground: true });
        report.pdfs.push({ path: pdf, rows: expectedRows });
      }
      const after = await (await context.request.get(api)).json();
      check(`${index + 1}/业务数据未改动`, JSON.stringify(before) === JSON.stringify(after));
    }
    // 仅在隔离 DOM 构造长表，验证分页边界；不保存到业务 API。
    await page.goto(`http://localhost:8080/boms/${records[0].id}/preview`);
    await page.locator('.bom-print-document').waitFor({ state: 'attached' });
    await page.emulateMedia({ media: 'print' });
    await page.evaluate(async () => {
      await document.fonts.ready;
      const root = document.querySelector('.bom-print-document');
      root.querySelector('.bom-print-heading').textContent = '分页边界测试（非业务数据）';
      const sections = [...root.querySelectorAll('.bom-print-section')];
      sections.slice(1).forEach(section => section.remove());
      sections[0].classList.remove('bom-print-section--short');
      const body = sections[0].querySelector('tbody');
      const template = body.firstElementChild.cloneNode(true);
      body.replaceChildren();
      for (let i = 1; i <= 60; i++) {
        const row = template.cloneNode(true);
        row.querySelector('td').textContent = String(i);
        row.querySelector('[data-field=part_name]').textContent = '分页测试行' + String(i).padStart(2, '0');
        body.append(row);
      }
      sections[0].querySelector('.bom-print-section-title').textContent = '管材类（60 条测试行）';
    });
    await page.pdf({ path: `${output}/pagination-fixture.pdf`, preferCSSPageSize: true, printBackground: true });
    report.pdfs.push({ path: `${output}/pagination-fixture.pdf`, rows: 60, fixtureOnly: true });
    check('无业务写入请求', !report.blockedWrites.length);
    check('无页面运行错误', !report.pageErrors.length);
  } catch (error) {
    report.error = String(error);
    check('执行完成', false);
  } finally {
    if (context) await context.close();
    report.browserClosed = true;
  }
  return report;
}

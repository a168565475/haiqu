/** Playwright MCP filename 执行；独立 headless、真实会话仅在内存中传递。运行前检查登记目录不存在，结束由调用方清理并保存返回报告。 */
async (sessionPage) => {
  const runtime = 'E:/workspace/_project/project001_haiqu_ERP_CRM/qa/_tmp/bom-preview-20261018';
  const output = 'E:/workspace/_project/project001_haiqu_ERP_CRM/docs/superpowers/reports';
  const navigation = [['管材类', '型材'], ['五金件', '五金'], ['塑料件类', '塑料'], ['面料类', '面料'], ['裁剪明细', '裁剪明细'], ['辅料类', '辅料'], ['包材类', '包材']];
  const report = { headless: true, checks: [], mismatches: [], blockedWrites: [], pageErrors: [], resources: { runtime, removed: false } };
  let context;
  const check = (name, passed, detail) => report.checks.push({ name, passed, detail });
  const digest = value => JSON.stringify(value);
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
    if (list.status() !== 200) throw new Error('真实 BOM 列表 API 不可读');
    const records = (await list.json()).data;
    if (!records.length) throw new Error('没有真实 BOM 可验收');
    for (const [recordIndex, record] of records.entries()) {
      const url = `http://localhost:8080/boms/${record.id}`;
      const api = `http://localhost:8080/api/v1/boms/${record.id}/`;
      const before = await (await context.request.get(api)).json();
      const editor = {};
      await page.goto(`${url}/edit`);
      await page.locator('.section-sidebar').waitFor();
      await page.waitForLoadState('networkidle');
      for (const [title, label] of navigation) {
        await page.locator('.section-sidebar button').filter({ hasText: new RegExp('^' + label) }).click();
        const table = page.locator('.material-card .el-table:visible');
        await table.waitFor();
        editor[title] = await table.evaluate(element => {
          const labels = [...element.querySelectorAll('.el-table__header-wrapper th')].map((node, i) => i === 0 ? '序号' : node.textContent.trim().replace(/^\*/, ''));
          const indexes = labels.flatMap((label, i) => label === '品号' ? [] : [i]);
          const rows = [...element.querySelectorAll('.el-table__body-wrapper tbody tr')].map((row, rowIndex) => indexes.map(index => {
            if (!index) return String(rowIndex + 1);
            const cell = row.children[index];
            const selected = cell.querySelector('.el-select__selected-item:not(.el-select__input-wrapper)');
            if (selected) return selected.textContent.trim();
            const input = cell.querySelector('input:not([type=checkbox]), textarea');
            if (input) return input.value.trim() || '—';
            const content = cell.cloneNode(true);
            content.querySelectorAll('button').forEach(button => button.remove());
            return content.textContent.trim() || '—';
          }));
          return { labels: indexes.map(index => labels[index]), rows };
        });
      }
      await page.goto(`${url}/preview`);
      await page.locator('.paper-section').first().waitFor();
      const tables = await page.locator('.paper-section').evaluateAll(sections => sections.map(section => ({ title: section.dataset.sectionTitle, labels: [...section.querySelectorAll('th')].map(th => th.textContent.trim()), rows: [...section.querySelectorAll('tbody tr')].filter(tr => !tr.querySelector('.empty-row')).map(tr => [...tr.querySelectorAll('td')].map(td => { const clone = td.cloneNode(true); clone.querySelectorAll('.line-note').forEach(n => n.remove()); return clone.textContent.trim() || '—'; })) })));
      for (const table of tables) {
        const expected = editor[table.title];
        check(`${recordIndex + 1}/${table.title}/表头`, JSON.stringify(table.labels) === JSON.stringify(expected.labels));
        const mismatches = [];
        table.rows.forEach((row, rowIndex) => row.forEach((value, col) => {
          if (value !== expected.rows[rowIndex]?.[col]) mismatches.push({ row: rowIndex + 1, field: table.labels[col], preview: value, editor: expected.rows[rowIndex]?.[col] });
        }));
        check(`${recordIndex + 1}/${table.title}/逐行数据`, !mismatches.length && table.rows.length === expected.rows.length, { rowCount: table.rows.length });
        report.mismatches.push(...mismatches.map(item => ({ bom: recordIndex + 1, section: table.title, ...item })));
      }
      const rawCodes = before.data.sections.flatMap(s => s.lines).flatMap(l => [l.hardware_material_number, l.plastic_material_number, l.packaging_material_number, l.cutting_material_number, l.raw_material]).filter(v => v && v.length > 5);
      const cellText = await page.locator('.bom-table').allTextContents();
      check(`${recordIndex + 1}/不显示原料编号`, rawCodes.every(code => cellText.every(text => !text.includes(code))));
      const after = await (await context.request.get(api)).json();
      check(`${recordIndex + 1}/API内容未改变`, digest(before) === digest(after));
      if (recordIndex === 0) {
        for (const [width, height, suffix] of [[1102, 884, 'after'], [1920, 1080, 'wide']]) {
          await page.setViewportSize({ width, height });
          await page.locator('.paper-scroll').evaluate(el => { el.scrollTop = 0; });
          const geometry = await page.evaluate(() => {
            const main = document.querySelector('.erp-layout__main'), scroller = document.querySelector('.paper-scroll');
            const first = document.querySelector('.table-frame'), th = first.querySelector('th'), td = first.querySelector('td');
            const border = el => ['Top', 'Right', 'Bottom', 'Left'].map(side => getComputedStyle(el)['border' + side + 'Width']);
            return { width: innerWidth, documentWidth: document.documentElement.scrollWidth, main: [main.clientHeight, main.scrollHeight], scroller: [scroller.clientWidth, scroller.scrollWidth], outerBorders: border(first), headerBorders: border(th), lastColumnBorders: border(first.querySelector('th:last-child')), lastRowBorders: border(first.querySelector('tbody tr:last-child td:last-child')), header: getComputedStyle(th).backgroundColor, background: getComputedStyle(td).backgroundColor, font: getComputedStyle(td).fontSize, padding: getComputedStyle(td).padding, rowHeight: td.getBoundingClientRect().height, frames: [...document.querySelectorAll('.table-frame')].map(el => ({ width: el.clientWidth, scroll: el.scrollWidth, overflow: getComputedStyle(el).overflowX })) };
          });
          check(`${width}/仅文档纵向滚动`, geometry.main[0] === geometry.main[1] && geometry.scroller[0] === geometry.scroller[1] && geometry.documentWidth <= width, geometry);
          check(`${width}/表格单层边框`, geometry.outerBorders.every(v => v === '1px') && JSON.stringify(geometry.headerBorders) === JSON.stringify(['0px', '1px', '1px', '0px']) && geometry.lastColumnBorders[1] === '0px' && geometry.lastRowBorders[1] === '0px' && geometry.lastRowBorders[2] === '0px');
          check(`${width}/表格主题与尺寸`, geometry.header === 'rgb(216, 233, 247)' && geometry.background === 'rgb(239, 247, 252)' && geometry.font === '12px' && geometry.rowHeight === 40);
          await page.screenshot({ path: `${output}/bom-preview-${suffix}-20261018.png` });
        }
        await page.setViewportSize({ width: 1102, height: 884 });
        await page.locator('.document-outline button').filter({ hasText: '包材类' }).click();
        await page.waitForFunction(() => document.querySelector('.paper-scroll').scrollTop > 0);
        // 按实际滚动终点等待，避免固定延时在平滑滚动中途误判。
        await page.waitForFunction(() => {
          const el = document.querySelector('.paper-scroll');
          return el.scrollTop + el.clientHeight >= el.scrollHeight - 2 && document.querySelector('.document-outline button.active')?.textContent.includes('包材类');
        });
        const navigationState = await page.evaluate(() => {
          const e = document.querySelector('.paper-scroll');
          return { active: document.querySelector('.document-outline button.active').textContent, top: e.scrollTop, height: e.clientHeight, total: e.scrollHeight, sections: [...document.querySelectorAll('.paper-section')].map(s => [s.dataset.sectionTitle, s.getBoundingClientRect().top, s.getBoundingClientRect().bottom]), scrollerTop: e.getBoundingClientRect().top };
        });
        check('目录选中同步', navigationState.active.includes('包材类'), navigationState);
        await page.emulateMedia({ media: 'print' });
        const printing = await page.evaluate(() => ({ tables: [...document.querySelectorAll('.bom-print-document table')].map(el => [el.clientWidth, el.scrollWidth]), header: getComputedStyle(document.querySelector('.preview-header')).display, body: getComputedStyle(document.querySelector('.bom-print-document')).backgroundColor }));
        check('打印白底且全部列可见', printing.header === 'none' && printing.body === 'rgb(255, 255, 255)' && printing.tables.every(([a, b]) => b <= a + 1), printing);
        await page.screenshot({ path: output + '/bom-preview-print-20261018.png', fullPage: true });
        await page.emulateMedia({ media: 'screen' });
      }
    }
    check('无业务写入请求', !report.blockedWrites.length);
    check('无页面运行错误', !report.pageErrors.length);
  } catch (error) {
    report.error = String(error);
    check('执行完成', false);
  } finally {
    if (context) await context.close();
    report.resources.browserClosed = true;
  }
  return report;
}

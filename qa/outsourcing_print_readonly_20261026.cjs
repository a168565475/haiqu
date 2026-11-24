/** 使用现有登录Session，只读后台验收；不在磁盘保存Cookie。运行目录在实施记录中登记。 */
async (sessionPage) => {
  const runtime = 'E:/workspace/_project/project001_haiqu_ERP_CRM/qa/_tmp/outsourcing-print-20261026';
  const output = 'E:/workspace/_project/project001_haiqu_ERP_CRM/docs/superpowers/reports/outsourcing-print-20261026';
  const report = { headless: true, checks: [], pdfs: [], blockedWrites: [], pageErrors: [], runtime };
  const check = (name, passed, details) => report.checks.push({ name, passed, ...(details === undefined ? {} : { details }) });
  let context;
  try {
    // 调用方先以PowerShell检查登记目录不存在；MCP执行环境不提供Node文件系统模块。
    const state = await sessionPage.context().storageState();
    context = await sessionPage.context().browser().browserType().launchPersistentContext(runtime, {
      executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true,
      viewport: { width: 1440, height: 1000 },
    });
    await context.addCookies(state.cookies);
    await context.addInitScript(origins => {
      const origin = origins.find(value => value.origin === location.origin);
      for (const item of origin?.localStorage || []) localStorage.setItem(item.name, item.value);
      window.__printCalls = 0;
      window.print = () => { window.__printCalls += 1; };
    }, state.origins);
    await context.route('**/api/**', route => {
      if (['GET', 'HEAD', 'OPTIONS'].includes(route.request().method())) return route.continue();
      report.blockedWrites.push({ method: route.request().method(), path: new URL(route.request().url()).pathname });
      return route.abort();
    });
    const base = 'http://localhost:8080';
    const response = await context.request.get(`${base}/api/v1/unified-outsourcing-orders/?page_size=50`);
    if (!response.ok()) throw new Error(`真实列表API ${response.status()}`);
    const records = (await response.json()).data.filter(row => row.record_type === 'TUBE');
    if (!records.length) throw new Error('没有真实管材或裁片外发单');
    const page = await context.newPage();
    page.on('pageerror', error => report.pageErrors.push(error.message));
    await page.goto(`${base}/workshop/outsourcing`);
    await page.locator('.outsourcing-order-list-page .el-table__body').waitFor();
    await page.getByRole('button', { name: `${records[0].order_number} 更多操作`, exact: true }).waitFor();
    const openPrintMenu = row => page.getByRole('button', { name: `${row.order_number} 更多操作`, exact: true }).click();
    const printItem = (row, kind) => page.getByRole('menuitem', { name: `${row.order_number} ${kind === 'spray' ? '管材喷塑打印' : '加工单打印'}`, exact: true });
    await page.screenshot({ path: `${output}/list-1440.png`, fullPage: true });
    check('列表无页面级横向溢出', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    let screenshotTaken = false;
    for (const [index, row] of records.entries()) {
      const api = `${base}/api/v1/tube-outsourcing-orders/${encodeURIComponent(row.id)}/`;
      const detailResponse = await context.request.get(api);
      if (!detailResponse.ok()) throw new Error(`真实详情API ${detailResponse.status()}`);
      const before = (await detailResponse.json()).data;
      check(`${index}/真实详情提供新增字段`, typeof before.planned_quantity === 'string' && 'specification' in before && 'updated_at' in before && before.lines.every(line => 'pieces_per_product' in line && 'tube_diameter' in line));
      const isTube = ['RAW_PIPE', 'PUBLIC_SEMI', 'TUBE_METAL'].includes(row.source_kind);
      await openPrintMenu(row);
      await printItem(row, 'processing').waitFor();
      check(`${index}/喷塑按钮适用范围`, await printItem(row, 'spray').count() === (isTube ? 1 : 0));
      await page.keyboard.press('Escape');
      await printItem(row, 'processing').waitFor({ state: 'hidden' });
      for (const kind of isTube ? ['processing', 'spray'] : ['processing']) {
        const priorCalls = await page.evaluate(() => window.__printCalls);
        await openPrintMenu(row);
        await printItem(row, kind).click();
        const doc = page.locator('.outsourcing-print-document');
        await doc.waitFor();
        await page.waitForFunction(count => window.__printCalls === count + 1, priorCalls);
        check(`${index}/${kind}/只调用一次打印`, await page.evaluate(count => window.__printCalls === count + 1, priorCalls));
        const text = await doc.innerText();
        check(`${index}/${kind}/真实订单产品及数量`, text.includes(before.product_name) && text.includes(before.task_order_number) && before.lines.every(line => text.includes(line.part_name) && text.includes(line.quantity)));
        if (kind === 'processing') check(`${index}/${kind}/随单材料完整`, (before.materials || []).every(line => text.includes(line.name) && text.includes(line.quantity)));
        if (kind === 'processing' && isTube) check(`${index}/${kind}/材料规格包含截长`, before.lines.every(line => !line.cutting_length_mm || text.replace(/\s+/g, '').includes(`${line.cutting_length_mm}mm`)));
        if (!screenshotTaken && isTube) {
          await page.locator('.outsourcing-print-paper').screenshot({ path: `${output}/${kind}-preview.png` });
          if (kind === 'spray') screenshotTaken = true;
        }
        await page.emulateMedia({ media: 'print' });
        await page.evaluate(() => document.fonts.ready);
        const styles = await doc.evaluate(root => {
          const cells = [...root.querySelectorAll('th,td')];
          return {
            tables: [...root.querySelectorAll('table')].map(table => ({ section: table.dataset.section, collapse: getComputedStyle(table).borderCollapse })),
            cellsFit: cells.every(cell => cell.scrollWidth <= cell.clientWidth + 1),
            borders: cells.every(cell => ['Top', 'Right', 'Bottom', 'Left'].every(side => getComputedStyle(cell)[`border${side}Width`] === '1px' && getComputedStyle(cell)[`border${side}Color`] === 'rgb(0, 0, 0)')),
            bodyFont: getComputedStyle(root).fontSize, titleFont: getComputedStyle(root.querySelector('h1')).fontSize,
            background: getComputedStyle(root).backgroundColor,
            headersRepeat: [...root.querySelectorAll('thead')].every(head => getComputedStyle(head).display === 'table-header-group'),
            noApp: getComputedStyle(document.getElementById('app')).display === 'none',
            noFixedDialog: getComputedStyle(root.closest('.app-window-dialog')).position === 'static',
          };
        });
        check(`${index}/${kind}/字号与四边单层黑线`, styles.bodyFont === '12px' && styles.titleFont === '24px' && styles.borders && styles.tables.every(table => table.collapse === 'collapse'), styles);
        check(`${index}/${kind}/打印仅纸面且明细不裁切`, styles.cellsFit && styles.headersRepeat && styles.noApp && styles.noFixedDialog);
        const path = `${output}/real-${index + 1}-${kind}.pdf`;
        await page.pdf({ path, preferCSSPageSize: true, printBackground: true });
        report.pdfs.push({ path, kind, rows: before.lines.length, fixtureOnly: false });
        await page.emulateMedia({ media: 'screen' });
        await page.locator('.outsourcing-print-overlay .app-window-dialog__footer').getByRole('button', { name: '关闭', exact: true }).click();
        await doc.waitFor({ state: 'detached' });
      }
      const after = (await (await context.request.get(api)).json()).data;
      check(`${index}/打印前后真实单据未变`, JSON.stringify(before) === JSON.stringify(after));
    }
    // 仅改隔离浏览器DOM验证分页，不保存至API，不属于真实业务验收。
    const tube = records.find(row => ['RAW_PIPE', 'PUBLIC_SEMI', 'TUBE_METAL'].includes(row.source_kind));
    if (tube) {
      await openPrintMenu(tube);
      await printItem(tube, 'spray').click();
      await page.locator('.outsourcing-print-document table[data-section="spray"] tbody tr').first().waitFor();
      const boundaries = await page.evaluate(() => {
        const root = document.querySelector('.outsourcing-print-document');
        const body = root.querySelector('table[data-section="spray"] tbody');
        const rows = [...body.querySelectorAll('[data-spray-row]')];
        rows.slice(1).forEach(row => row.remove());
        const fits = () => [...body.querySelectorAll('td')].every(cell => cell.scrollWidth <= cell.clientWidth + 1);
        const single = fits();
        const row = rows[0];
        row.style.display = 'none';
        const empty = document.createElement('tr');
        empty.innerHTML = '<td colspan="8" class="print-empty">暂无明细</td>';
        body.insertBefore(empty, row);
        const emptyFits = fits();
        empty.remove(); row.style.display = '';
        return { single, emptyFits };
      });
      check('DOM边界：喷塑单行与空态没有横向裁切', boundaries.single && boundaries.emptyFits, boundaries);
      await page.evaluate(() => {
        const root = document.querySelector('.outsourcing-print-document');
        root.querySelector('h1').textContent = '分页边界测试（非业务数据）';
        const body = root.querySelector('table[data-section="spray"] tbody');
        const template = body.querySelector('tr').cloneNode(true);
        const footer = body.querySelector('.print-spray-footer').cloneNode(true);
        body.replaceChildren();
        for (let i = 1; i <= 80; i++) {
          const row = template.cloneNode(true);
          row.querySelectorAll('td')[1].textContent = `分页测试行${String(i).padStart(3, '0')}`;
          body.appendChild(row);
        }
        body.appendChild(footer);
      });
      await page.emulateMedia({ media: 'print' });
      await page.pdf({ path: `${output}/pagination-fixture.pdf`, preferCSSPageSize: true, printBackground: true });
      report.pdfs.push({ path: `${output}/pagination-fixture.pdf`, kind: 'spray', rows: 80, fixtureOnly: true });
      await page.emulateMedia({ media: 'screen' });
      await page.locator('.outsourcing-print-overlay .app-window-dialog__footer').getByRole('button', { name: '关闭', exact: true }).click();
      await page.locator('.outsourcing-print-document').waitFor({ state: 'detached' });
      await openPrintMenu(tube);
      await printItem(tube, 'processing').click();
      await page.locator('.outsourcing-print-document [data-material-row]').first().waitFor();
      await page.evaluate(() => {
        const root = document.querySelector('.outsourcing-print-document');
        root.querySelector('h1').textContent = '加工单分页边界测试（非业务数据）';
        const body = root.querySelector('table[data-section="materials"] tbody');
        const main = body.querySelector('[data-material-row]').cloneNode(true);
        const attribute = body.querySelector('[data-material-attributes]').cloneNode(true);
        const heading = body.querySelector('.print-attribute-heading').cloneNode(true);
        heading.querySelectorAll('td').forEach(cell => cell.rowSpan = 51);
        body.replaceChildren();
        for (let i = 1; i <= 50; i++) {
          const row = main.cloneNode(true);
          row.querySelectorAll('td')[1].textContent = `材料测试行${String(i).padStart(3, '0')}`;
          body.appendChild(row);
        }
        body.appendChild(heading);
        for (let i = 1; i <= 50; i++) {
          const row = attribute.cloneNode(true);
          row.querySelectorAll('td')[1].textContent = `材质测试行${String(i).padStart(3, '0')}`;
          body.appendChild(row);
        }
      });
      await page.emulateMedia({ media: 'print' });
      await page.pdf({ path: `${output}/processing-pagination-fixture.pdf`, preferCSSPageSize: true, printBackground: true });
      report.pdfs.push({ path: `${output}/processing-pagination-fixture.pdf`, kind: 'processing', rows: 50, fixtureOnly: true });
    }
    check('无业务写请求', report.blockedWrites.length === 0, report.blockedWrites);
    check('无页面脚本错误', report.pageErrors.length === 0, report.pageErrors);
  } catch (error) {
    report.error = String(error);
    check('执行完成', false);
  } finally {
    if (context) await context.close();
    report.browserClosed = true;
  }
  return report;
}

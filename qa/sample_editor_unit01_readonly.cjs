// 单元01真实页面只读检查；仅正常登录可写，所有业务写请求都阻止并计为失败。
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('../src/frontend/node_modules/playwright-core')

const output = path.resolve(process.env.SAMPLE_EDITOR_QA_OUTPUT || path.resolve(__dirname, '../docs/plans/sample_editor_20261021/reports/evidence'))
const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:8080'
async function main() {
  fs.mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' })
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, ...(process.env.E2E_STORAGE_STATE ? { storageState: process.env.E2E_STORAGE_STATE } : {}) })
  const errors = [], writes = [], results = []
  let report = { status: 'UNKNOWN', reason: '尚未完成', errors, writes, results }
  try {
    await context.route('**/api/**', route => {
      const request = route.request()
      const pathname = new URL(request.url()).pathname
      if (['GET', 'HEAD'].includes(request.method()) || pathname === '/api/auth/login/') return route.continue()
      writes.push(`${request.method()} ${pathname}`)
      return route.abort('blockedbyclient')
    })
    let auth = await context.request.get(`${base}/api/auth/me/`)
    if (!(await auth.json()).authenticated && process.env.E2E_USERNAME && process.env.E2E_PASSWORD) {
      const csrf = (await context.cookies()).find(cookie => cookie.name === 'csrftoken')?.value
      auth = await context.request.post(`${base}/api/auth/login/`, { headers: { 'X-CSRFToken': csrf || '' }, data: { username: process.env.E2E_USERNAME, password: process.env.E2E_PASSWORD } })
      assert.equal(auth.status(), 200, '正常 Session 登录必须成功')
    }
    if (!(await auth.json()).authenticated) {
      const anonymous = await context.request.get(`${base}/api/v1/sample-requests/`)
      report.reason = `缺少可用登录会话/凭据；匿名样品API返回${anonymous.status()}。未注入身份或业务数据。`
      process.exitCode = 2
      return
    }
    const response = await context.request.get(`${base}/api/v1/sample-requests/?page_size=100`)
    assert.equal(response.status(), 200)
    const listing = (await response.json()).data
    assert(listing.length, '需要当前账号可访问的真实申请')
    const page = await context.newPage()
    page.on('pageerror', error => errors.push(error.message))
    // 每种实际可用阶段最多一条；不构造数据补齐缺失状态。
    const records = [...new Map(listing.map(item => [item.status, item])).values()]
    for (const record of records) {
      await page.goto(`${base}/samples/${record.id}/edit`, { waitUntil: 'networkidle' })
      await page.locator('.sample-editor-page > .el-loading-mask').waitFor({ state: 'hidden' })
      assert.equal(await page.locator('[role="tablist"][aria-label="打样编辑内容"] [role="tab"]').count(), 2)
      assert.equal(new URL(page.url()).pathname, `/samples/${record.id}/edit`)
      for (const viewport of [{ width: 1920, height: 1080 }, { width: 1440, height: 900 }]) {
        await page.setViewportSize(viewport)
        await page.evaluate(() => document.fonts.ready)
        const product = await page.evaluate(() => {
          const tab = document.querySelector('#sample-product-tab')
          const card = document.querySelector('.product-card')
          const heading = document.querySelector('.title-line h1')
          const style = card && getComputedStyle(card)
          return { tabHeight: tab.getBoundingClientRect().height, tabFont: getComputedStyle(tab).fontSize,
            headingFont: getComputedStyle(heading).fontSize, border: style && [style.borderTopWidth, style.borderRightWidth, style.borderBottomWidth, style.borderLeftWidth],
            overflow: document.documentElement.scrollWidth > window.innerWidth }
        })
        assert.equal(product.tabHeight, 32); assert.equal(product.tabFont, '13px'); assert.equal(product.headingFont, '26px'); assert.equal(product.overflow, false)
        assert.equal(await page.locator('.product-card .el-form').count(), 0, '概览不常驻编辑表单')
        await page.getByRole('button', { name: /^(编辑产品信息|查看产品信息)$/ }).first().click()
        const productWindow = page.getByRole('dialog').filter({ has: page.locator('#sample-purpose') })
        await productWindow.waitFor({ state: 'visible' })
        await productWindow.getByRole('button', { name: '返回概览', exact: true }).click()
        await page.getByRole('tab', { name: '材料需求', exact: true }).click()
        assert.equal(await page.locator('.material-editor .section-sidebar .section-tabs button').count(), 6)
        assert.equal(await page.locator('.material-editor .material-main .material-table').count(), 1)
        assert.equal(await page.locator('.material-editor .material-tabs').count(), 0)
        const sidebar = await page.locator('.material-editor').evaluate(element => {
          const left = element.querySelector('.section-sidebar').getBoundingClientRect()
          const right = element.querySelector('.material-main').getBoundingClientRect()
          return { leftWidth: left.width, gap: right.left - left.right, isLeftOfTable: left.right <= right.left }
        })
        assert.equal(sidebar.leftWidth, 176); assert.equal(sidebar.gap, 14); assert.equal(sidebar.isLeftOfTable, true)
        await page.getByRole('button', { name: '全屏填写', exact: true }).click()
        assert.equal(await page.locator('.sample-editor-page.is-fullscreen').count(), 1)
        await page.keyboard.press('Escape')
        assert.equal(await page.locator('.sample-editor-page.is-fullscreen').count(), 0)
        const table = await page.locator('.material-table table').evaluate(element => {
          const row = element.querySelector('tbody tr')
          return { columns: element.querySelectorAll('thead th').length, rows: element.querySelectorAll('tbody tr').length,
            headerHeight: element.querySelector('thead').getBoundingClientRect().height, rowHeight: row?.getBoundingClientRect().height,
            borderCollapse: getComputedStyle(element).borderCollapse }
        })
        assert.equal(table.columns, 9)
        await page.screenshot({ path: path.join(output, `sample-editor-${record.status}-${viewport.width}.png`), fullPage: true })
        results.push({ stage: record.status, viewport, product, sidebar, table })
        await page.getByRole('tab', { name: '申请与产品', exact: true }).click()
      }
    }
    assert.deepEqual(errors, []); assert.deepEqual(writes, [])
    report.status = 'PASS'; report.reason = '仅覆盖 results 中真实存在且当前会话可访问的阶段；没有执行业务保存。'
  } catch (error) { report.status = 'FAIL'; report.reason = error.message; process.exitCode = 1 }
  finally {
    await context.close(); await browser.close()
    fs.writeFileSync(path.join(output, 'headless-readonly.json'), JSON.stringify(report, null, 2))
    console.log(JSON.stringify(report))
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1 })

const assert = require('node:assert/strict')
const path = require('node:path')
const { chromium } = require('playwright-core')

const baseUrl = process.env.UI_E2E_BASE_URL || 'http://localhost:8080'
const executablePath = process.env.UI_E2E_BROWSER_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const outputDir = process.env.QA_OUTPUT_DIR || path.resolve('outputs/production_bom_v3_acceptance/20260911_layout_only')

const productionRows = Array.from({ length: 10 }, (_, index) => ({
  id: `10000000-0000-0000-0000-${String(index + 1).padStart(12, '0')}`,
  task_number: `HT-2609-${String(128 - index).padStart(6, '0')}`,
  contract_number: `HTC-2609-${String(128 - index).padStart(6, '0')}`,
  order_source: 'NEW',
  order_source_display: '新订单',
  order_number: `SO-202609-${String(88 - index).padStart(6, '0')}`,
  customer_id: `customer-${index + 1}`,
  customer_code: `CUS-${index + 1}`,
  customer_name: `验收客户${index + 1}`,
  order_date: '2026-09-01',
  delivery_date: `2026-09-${String(18 + index).padStart(2, '0')}`,
  salesperson: { id: 'employee-1', employee_code: 'QA', display_name: index % 2 ? '王静' : '张涛' },
  followers: [],
  delivery_method: 'SINGLE',
  delivery_method_display: '一次交货',
  freight_amount: '0.0000', other_fee_amount: '0.0000', product_total_amount: '0.0000', total_amount: '0.0000',
  status: ['DRAFT', 'PENDING_VALIDATION', 'READY', 'IN_PRODUCTION', 'COMPLETED'][index % 5],
  status_display: ['草稿', '待 PMC 确认', '已确认', '生产中', '已完成'][index % 5],
  total_quantity: String(800 + index * 400), batch_total_quantity: '0.0000', quantity_difference: '0.0000',
  products: [{ id: `line-${index}`, product_id: `product-${index}`, product_name: ['户外扶手椅', '露营折叠桌', '帐篷（三人）'][index % 3] }],
  created_at: '2026-09-01T08:00:00+08:00', updated_at: '2026-09-11T08:00:00+08:00',
  source_sales_order_number: `SO-202609-${String(88 - index).padStart(6, '0')}`,
  is_historical_unlinked: false,
}))

const bomRows = Array.from({ length: 8 }, (_, index) => ({
  id: `20000000-0000-0000-0000-${String(index + 1).padStart(12, '0')}`,
  bom_number: `BOM-2609-${String(128 - index).padStart(6, '0')}`,
  production_task_number: productionRows[index].task_number,
  order_number: productionRows[index].order_number,
  source_sales_order_number: productionRows[index].order_number,
  is_historical_unlinked: false,
  product_number_snapshot: `HTY-${String(index + 18).padStart(3, '0')}`,
  product_code_snapshot: `HTY-${String(index + 18).padStart(3, '0')}`,
  product_name_snapshot: productionRows[index].products[0].product_name,
  specification_snapshot: '52×52×85cm',
  product_category_snapshot: '户外家具',
  order_quantity: productionRows[index].total_quantity,
  current_order_quantity: productionRows[index].total_quantity,
  is_order_quantity_outdated: false,
  is_order_product_outdated: false,
  source_quantity: null, batch_quantity: null, batch_quantity_breakdown: [], quantity_difference: '0.0000', quantity_requires_confirmation: false,
  status: index % 2 ? 'PENDING_CONFIRMATION' : 'VERIFIED',
  status_display: index % 2 ? '待确认' : '已确认',
  creation_method: 'BLANK', creation_method_display: '空白创建',
  section_count: 3, line_count: 12,
  section_summary: [{ type: 'PROFILE', label: '型材', count: 4 }, { type: 'ACCESSORY', label: '配件', count: 5 }, { type: 'FABRIC', label: '面辅料', count: 3 }],
  maintenance_match_count: 12, maintenance_unmatched_count: 0, source_original_name: '', source_sheet_name: '',
  updated_by_name: index % 2 ? '王静' : '李素清', created_at: '2026-09-01T08:00:00+08:00', updated_at: '2026-09-11T08:00:00+08:00',
}))

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath })
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 })
  const page = await context.newPage()
  const pageErrors = []
  page.on('pageerror', (error) => pageErrors.push(error.message))

  await page.route('**/api/auth/me/', (route) => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ authenticated: true, user: { id: 1, username: 'layout-qa', display_name: '布局验收', is_superuser: true, employee: { id: 'employee-1', employee_code: 'QA', display_name: '布局验收', status: 'ACTIVE' }, permissions: ['production_tasks.view_productiontask', 'production_tasks.add_productiontask', 'production_tasks.change_productiontask', 'production_tasks.confirm_productiontask', 'production_tasks.start_productiontask', 'boms.view_bom', 'boms.add_bom', 'boms.change_bom', 'boms.delete_bom'], data_scope: 'ALL' } }),
  }))
  await page.route('**/api/v1/production-tasks/**', (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith('/stats/')) return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ data: { all: 128, draft: 12, pending_validation: 23, ready: 36, in_production: 34, completed: 18, split_delivery: 0 } }) })
    if (pathname.endsWith('/options/')) return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ data: { order_sources: [], delivery_methods: [], statuses: [], boolean_options: [], customers: [], employees: [{ id: 'employee-1', employee_code: 'QA', display_name: '张涛' }], products: [], currencies: [], units: [], colors: [], detail_template: [] } }) })
    if (pathname.endsWith('/production-tasks/')) return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ data: productionRows, meta: { page: 1, page_size: 50, total: 128, total_pages: 3 } }) })
    return route.abort()
  })
  await page.route('**/api/v1/boms/**', (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith('/stats/')) return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ data: { total: 86, pending_confirmation: 18, verified: 68, maintenance_reference_count: 0 } }) })
    if (pathname.endsWith('/options/')) return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ data: { production_task_products: [], product_categories: [], updated_date_presets: [], products: [], currencies: [], units: [], colors: [], detail_template: [] } }) })
    if (pathname.endsWith('/boms/')) return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ data: bomRows, meta: { page: 1, page_size: 50, total: 86, total_pages: 2 } }) })
    return route.abort()
  })

  for (const item of [
    { route: 'production-tasks', selector: '.production-list-page', file: 'production_list_1920.png', statusCount: 6 },
    { route: 'boms', selector: '.bom-list-page', file: 'bom_list_1920.png', statusCount: 3 },
  ]) {
    await page.goto(`${baseUrl}/${item.route}`, { waitUntil: 'networkidle' })
    await page.locator(item.selector).waitFor()
    const geometry = await page.evaluate((selector) => {
      const root = document.querySelector(selector)
      const status = root?.querySelector('.status-tabs')
      const tableRows = root?.querySelectorAll('.el-table__body tr') || []
      return {
        viewport: innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
        rootWidth: root?.getBoundingClientRect().width || 0,
        statusHeight: status?.getBoundingClientRect().height || 0,
        firstRowHeight: tableRows[0]?.getBoundingClientRect().height || 0,
      }
    }, item.selector)
    assert.ok(geometry.scrollWidth <= geometry.viewport + 1, JSON.stringify(geometry))
    assert.ok(Math.abs(geometry.statusHeight - 53) <= 1, JSON.stringify(geometry))
    assert.ok(Math.abs(geometry.firstRowHeight - 52) <= 1, JSON.stringify(geometry))
    assert.equal(await page.locator(`${item.selector} .status-tab`).count(), item.statusCount)
    if (item.route === 'production-tasks') {
      const operationGeometry = await page.evaluate(() => {
        const trigger = document.querySelector('.production-list-page .row-action-trigger')
        const dots = [...document.querySelectorAll('.production-list-page .row-action-trigger i')]
        const tag = document.querySelector('.production-list-page .status-tag--success')
        const operationHeader = [...document.querySelectorAll('.production-list-page .el-table__header-wrapper th')]
          .find((element) => element.textContent?.trim() === '操作')
        const triggerRect = trigger?.getBoundingClientRect()
        const tagRect = tag?.getBoundingClientRect()
        const tagStyle = tag ? getComputedStyle(tag) : null
        return {
          triggerCount: document.querySelectorAll('.production-list-page .row-action-trigger').length,
          triggerWidth: triggerRect?.width || 0,
          dotCount: dots.length,
          dotGap: dots.length >= 2 ? dots[1].getBoundingClientRect().left - dots[0].getBoundingClientRect().right : 0,
          operationWidth: operationHeader?.getBoundingClientRect().width || 0,
          tagWidth: tagRect?.width || 0,
          tagHeight: tagRect?.height || 0,
          tagBackground: tagStyle?.backgroundColor || '',
          tagColor: tagStyle?.color || '',
        }
      })
      assert.equal(operationGeometry.triggerCount, productionRows.length, JSON.stringify(operationGeometry))
      assert.equal(operationGeometry.dotCount, productionRows.length * 3, JSON.stringify(operationGeometry))
      assert.ok(Math.abs(operationGeometry.triggerWidth - 30) <= 1, JSON.stringify(operationGeometry))
      assert.ok(Math.abs(operationGeometry.dotGap - 3) <= 1, JSON.stringify(operationGeometry))
      assert.ok(Math.abs(operationGeometry.operationWidth - 80) <= 1, JSON.stringify(operationGeometry))
      assert.ok(operationGeometry.tagWidth >= 56, JSON.stringify(operationGeometry))
      assert.ok(Math.abs(operationGeometry.tagHeight - 24) <= 1, JSON.stringify(operationGeometry))
      assert.equal(operationGeometry.tagBackground, 'rgb(79, 125, 75)', JSON.stringify(operationGeometry))
      assert.equal(operationGeometry.tagColor, 'rgb(250, 249, 245)', JSON.stringify(operationGeometry))
      await page.locator('.production-list-page .row-action-trigger').first().click()
      await page.getByRole('menuitem', { name: '查看', exact: true }).waitFor()
      assert.equal(await page.getByRole('menuitem', { name: '查看', exact: true }).count(), 1)
      await page.locator('.production-list-page .page-heading h1').click()
      await page.getByRole('menuitem', { name: '查看', exact: true }).waitFor({ state: 'hidden' })
    }
    await page.screenshot({ path: path.join(outputDir, item.file), fullPage: true })
    console.log(item.route, JSON.stringify(geometry))
  }

  assert.deepEqual(pageErrors, [])
  await browser.close()
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})

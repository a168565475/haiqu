const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')
const { pathToFileURL } = require('node:url')
const { randomUUID } = require('node:crypto')

const project = path.resolve(__dirname, '..')
const frontend = path.join(project, 'src/frontend')
const design = path.join(project, 'docs/designs/supplier_payment_20261119')
const runtime = path.join(design, '.unit-2-runtime')
const evidence = path.join(design, 'evidence/unit-2')
const origin = 'http://127.0.0.1:18774'
const financeApi = '/api/v1/finance/'
const pagePath = '/finance/supplier-payments'
const applicationApi = financeApi + 'supplier-payment-applications/'
const paymentApi = financeApi + 'supplier-payments/'
const ledgerApi = financeApi + 'supplier-ledger/'

const button = (root, name) => root.getByRole('button', { name, exact: true })
const capture = (node, name) => node.screenshot({ path: path.join(evidence, name + '.png'), animations: 'disabled' })

async function openRole(browser, identity, viewport, expectedAccess) {
  const context = await browser.newContext({ viewport, reducedMotion: 'reduce' })
  await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort())
  await context.request.get(origin + '/api/auth/me/')
  const token = (await context.cookies()).find(cookie => cookie.name === 'csrftoken')?.value
  assert.ok(token)
  const result = await context.request.post(origin + '/api/auth/login/', {
    data: identity, headers: { 'X-CSRFToken': token, Origin: origin },
  })
  assert.equal(result.status(), 200)
  const profile = (await (await context.request.get(origin + '/api/auth/me/')).json()).user
  assert.equal(profile.is_superuser, false)
  assert.equal(profile.permissions.includes('finance.view_supplierpayment'), expectedAccess)
  const page = await context.newPage()
  const errors = []
  const requests = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('response', response => {
    const pathname = new URL(response.url()).pathname
    if (pathname.startsWith('/api/') || response.status() >= 400) requests.push([pathname, response.status()])
  })
  return { context, page, errors, requests }
}

async function choose(page, root, field, choice) {
  await root.locator('.el-select').filter({ has: page.getByRole('combobox', { name: field, exact: true }) })
    .locator('.el-select__wrapper').click()
  await page.getByRole('listbox', { name: field, exact: true }).getByRole('option', { name: choice }).click()
}

async function submit(page, target, action) {
  const response = page.waitForResponse(result => new URL(result.url()).pathname === target && result.request().method() === 'POST')
  await action.click()
  const result = await response
  const body = await result.json()
  assert.equal(result.status(), 201, JSON.stringify(body.error ?? {}))
  return body.data
}

async function pageLayout(page) {
  const metrics = await page.locator('.supplier-payment-page').evaluate(root => {
    const frame = root.querySelector('.erp-list-table-frame')
    const area = frame.querySelector('.el-scrollbar__wrap')
    const header = frame.querySelector('.el-table__header th')
    const row = frame.querySelector('.el-table__body tr')
    const style = element => getComputedStyle(element)
    const height = element => element.getBoundingClientRect().height
    return {
      viewport: innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      border: ['Top', 'Right', 'Bottom', 'Left'].map(side => style(frame)['border' + side + 'Width']),
      patch: getComputedStyle(frame.querySelector('.el-table__inner-wrapper'), '::before').display,
      header: height(header), row: height(row),
      lastCellRight: style(row.cells[row.cells.length - 1]).borderRightWidth,
      singleLine: [...frame.querySelectorAll('th .cell, td .cell')].every(cell => style(cell).whiteSpace === 'nowrap'),
      controls: [...root.querySelectorAll('.payment-filter .el-input__wrapper, .payment-filter .el-select__wrapper, .payment-filter button')]
        .map(height),
      footer: height(root.querySelector('.erp-list-footer')),
      pager: height(root.querySelector('.erp-list-footer .btn-prev')),
      scrolls: area.scrollWidth > area.clientWidth,
    }
  })
  assert.equal(metrics.viewport, metrics.documentWidth)
  assert.deepEqual(metrics.border, ['1px', '1px', '1px', '1px'])
  assert.equal(metrics.patch, 'none')
  assert.equal(metrics.header, 38)
  assert.equal(metrics.row, 40)
  assert.equal(metrics.lastCellRight, '0px')
  assert.equal(metrics.singleLine, true)
  assert.ok(metrics.controls.length >= 4 && metrics.controls.every(height => height === 32))
  assert.equal(metrics.footer, 40)
  assert.equal(metrics.pager, 28)
  assert.equal(metrics.scrolls, metrics.viewport === 1024)
  return metrics
}

async function runBrowser(browser, fixture) {
  const finance = await openRole(browser, fixture.identities.finance, { width: 1920, height: 1080 }, true)
  const cashier = await openRole(browser, fixture.identities.cashier, { width: 1024, height: 768 }, true)
  const viewer = await openRole(browser, fixture.identities.viewer, { width: 1024, height: 768 }, false)
  try {
    await finance.page.goto(origin + pagePath)
    const financeRoot = finance.page.getByRole('region', { name: '供应商付款', exact: true })
    const current = await finance.context.request.get(origin + applicationApi)
    assert.equal(current.status(), 200)
    const existing = (await current.json()).data
    let application
    if (existing.length) {
      assert.equal(existing.length, 1)
      assert.equal(existing[0].supplier_id, fixture.supplier_id)
      assert.equal(existing[0].paid_amount, '0.00')
      const previous = await finance.context.request.get(origin + applicationApi + existing[0].id + '/')
      assert.equal(previous.status(), 200)
      application = (await previous.json()).data
      await button(financeRoot, '查看 ' + application.number).click()
    } else {
      await financeRoot.getByText('暂无付款申请').waitFor()
      await button(financeRoot, '新建申请').click()
      const form = finance.page.getByRole('dialog', { name: '新建付款申请' })
      assert.equal(await form.getByRole('combobox', { name: '申请日期' }).inputValue(), fixture.today)
      await choose(finance.page, form, '申请供应商', fixture.supplier_name)
      await button(form, '2026-08').click()
      const august = form.getByRole('table', { name: '2026-08 采购应付明细' })
      await august.locator('tbody tr').first().locator('.el-checkbox').click()
      await august.getByRole('textbox', { name: fixture.payable_number + ' 本次申请金额' }).fill('200.00')
      await form.locator('.month-row').last().locator('.el-checkbox').click()
      assert.match(await form.locator('.application-actions').innerText(), /700\.00/)
      assert.deepEqual(await august.locator('tbody tr').evaluateAll(rows => rows.map(row => row.getBoundingClientRect().height)), [40, 40])
      await capture(form, 'selection-1920')
      application = await submit(finance.page, applicationApi, button(form, '提交申请'))
    }
    assert.equal(application.amount, '700.00')
    assert.equal(application.department_name, '隔离财务部')
    assert.deepEqual(application.lines.map(line => line.month), ['2026-08', '2026-09'])
    const financeDetail = finance.page.getByRole('dialog', { name: '付款申请详情' })
    await financeDetail.getByText(application.number, { exact: true }).waitFor()
    assert.equal(await button(financeDetail, '登记付款').count(), 0)
    await button(financeDetail, '关闭').last().click()
    await button(financeRoot, '查看 ' + application.number).waitFor()
    const applicationLayout = await pageLayout(finance.page)
    await capture(finance.page, 'applications-1920')

    assert.equal((await cashier.context.request.get(origin + ledgerApi)).status(), 403)
    assert.equal((await cashier.context.request.post(origin + paymentApi, { data: {} })).status(), 403)
    await cashier.page.goto(origin + '/')
    await cashier.page.locator('[data-menu-key="finance-management"]').focus()
    const financeMenu = cashier.page.locator('[data-sidebar-flyout][data-flyout-menu-key="finance-management"]')
    const paymentLink = financeMenu.getByRole('link', { name: '供应商付款', exact: true })
    await paymentLink.locator('[data-confirmed-secondary-sidebar-icon="finance-supplier-payments"]').waitFor()
    assert.equal(await financeMenu.getByRole('link', { name: '供应商往来明细', exact: true }).count(), 0)
    await paymentLink.click()
    const cashierRoot = cashier.page.getByRole('region', { name: '供应商付款', exact: true })
    await button(cashierRoot, '查看 ' + application.number).click()
    assert.equal(await button(cashierRoot, '新建申请').count(), 0)
    const cashierDetail = cashier.page.getByRole('dialog', { name: '付款申请详情' })
    await button(cashierDetail, '登记付款').click()
    const paymentForm = cashier.page.getByRole('dialog', { name: '登记付款' })
    await choose(cashier.page, paymentForm, '公司付款账户', /隔离公司付款账户/)
    await paymentForm.getByRole('textbox', { name: '实付金额' }).fill('125.00')
    await paymentForm.getByRole('textbox', { name: '付款凭证编号' }).fill('QA-U02-REAL-RECEIPT')
    await capture(paymentForm, 'registration-1024')
    const payment = await submit(cashier.page, paymentApi, button(paymentForm, '保存'))
    assert.equal(payment.application_id, application.id)
    assert.equal(payment.amount, '125.00')
    await cashierDetail.getByText('575.00', { exact: true }).waitFor()
    await button(cashierDetail, '关闭').last().click()
    await button(cashierRoot, '付款记录').click()
    await button(cashierRoot, payment.number).waitFor()
    const paymentLayout = await pageLayout(cashier.page)
    await capture(cashier.page, 'payments-1024')
    await button(cashierRoot, payment.number).click()
    const paymentDetail = cashier.page.getByRole('dialog', { name: '付款单 ' + payment.number })
    await paymentDetail.getByText('QA-U02-REAL-RECEIPT').waitFor()
    await button(paymentDetail, application.number).waitFor()

    const ledgerPath = '/finance/supplier-ledger?month=' + fixture.today.slice(0, 7)
    await finance.page.goto(origin + ledgerPath)
    const ledger = finance.page.locator('.supplier-ledger')
    await ledger.getByText('1,500.00', { exact: true }).last().waitFor()
    await button(ledger, '抵账').click()
    const offset = finance.page.getByRole('dialog', { name: '抵账' })
    await choose(finance.page, offset, '付款单号', new RegExp(payment.number))
    await offset.getByRole('textbox', { name: fixture.payable_number + ' 本次抵账金额' }).fill('125.00')
    const settlement = await submit(finance.page, ledgerApi + 'offsets/', button(offset, '保存'))
    assert.equal(settlement.payment_id, payment.id)
    assert.equal(settlement.allocations[0].amount, '125.00')
    await ledger.getByText('1,375.00', { exact: true }).waitFor()
    assert.ok((await ledger.getByText('125.00', { exact: true }).count()) >= 2)
    await capture(finance.page, 'ledger-after-offset-1920')

    assert.equal((await viewer.context.request.get(origin + paymentApi)).status(), 403)
    await viewer.page.goto(origin + pagePath)
    await viewer.page.waitForURL(url => url.pathname !== pagePath)
    assert.equal(await viewer.page.getByRole('heading', { name: '供应商付款' }).count(), 0)

    const csrf = (await finance.context.cookies()).find(cookie => cookie.name === 'csrftoken')?.value
    assert.ok(csrf)
    const concurrent = await Promise.all([1, 2].map(() => finance.context.request.post(origin + applicationApi, {
      headers: { Origin: origin, 'X-CSRFToken': csrf, 'Idempotency-Key': randomUUID() },
      data: { supplier_id: fixture.supplier_id, applied_on: fixture.today, payee: '隔离并发测试',
        lines: [{ payable_id: fixture.race_payable_id, amount: '400.00' }] },
    })))
    assert.deepEqual(concurrent.map(response => response.status()).sort(), [201, 409])
    for (const role of [finance, cashier, viewer]) assert.deepEqual(role.errors, [])
    return { applicationLayout, paymentLayout, applicationAmount: '700.00', paid: '125.00', offset: '125.00',
      balanceBefore: '1500.00', balanceAfter: '1375.00', independentCashier: true, csrfChecked: true,
      unauthorizedDenied: true, concurrentApplicationStatuses: [201, 409] }
  } catch (error) {
    for (const [name, role] of [['finance', finance], ['cashier', cashier], ['viewer', viewer]]) {
      console.error(JSON.stringify({ name, url: role.page.url(), requests: role.requests.slice(-16), errors: role.errors,
        text: (await role.page.locator('body').innerText({ timeout: 2000 })).slice(0, 300) }))
      await role.page.screenshot({ path: path.join(runtime, name + '-failure.png'), timeout: 3000 })
    }
    throw error
  } finally {
    await Promise.all([finance.context.close(), cashier.context.close(), viewer.context.close()])
  }
}

async function main() {
  assert.equal(process.env.SUPPLIER_PAYMENT_BROWSER, '1')
  const fixture = JSON.parse(await fs.readFile(path.join(runtime, 'ready.json'), 'utf8'))
  assert.equal(fixture.database, 'test_supplier_payment_u02_browser_20261119')
  await fs.mkdir(evidence, { recursive: true })
  process.env.TEMP = runtime
  process.env.TMP = runtime
  process.env.VITE_API_BASE_URL = 'same-origin'
  process.env.VITE_PROXY_TARGET = 'http://127.0.0.1:18773'
  let server, browser, passed = false
  try {
    const { createServer } = await import(pathToFileURL(path.join(frontend, 'node_modules/vite/dist/node/index.js')).href)
    server = await createServer({
      root: frontend, cacheDir: path.join(runtime, 'vite'),
      server: { host: '127.0.0.1', port: 18774, strictPort: true, open: false },
    })
    await server.listen()
    const { chromium } = require(path.join(frontend, 'node_modules/playwright-core'))
    browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
    const result = await runBrowser(browser, fixture)
    await fs.writeFile(path.join(evidence, 'layout.json'), JSON.stringify(result, null, 2) + '\n')
    passed = true
    console.log(JSON.stringify(result))
  } finally {
    await browser?.close()
    await server?.close()
    if (passed) await fs.writeFile(path.join(runtime, 'done.json'), JSON.stringify({ passed }))
  }
}

main().catch(error => {
  console.error(error)
  process.exitCode = 1
})

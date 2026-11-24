const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')
const { randomUUID } = require('node:crypto')
const { pathToFileURL } = require('node:url')
const { setTimeout: delay } = require('node:timers/promises')

const project = path.resolve(__dirname, '..')
const frontend = path.join(project, 'src/frontend')
const acceptance = process.env.SUPPLIER_LEDGER_ACCEPTANCE_BROWSER === '1'
const unit = acceptance ? 4 : process.env.SUPPLIER_LEDGER_SETTLEMENT_BROWSER === '1' ? 3 : 2
const label = `supplier-ledger-u0${unit}-20261119`
const control = path.join(project, `src/backend/_tmp/${label}`)
const runtime = path.join(__dirname, `_tmp/${label}`)
const output = path.join(project, `docs/designs/supplier_ledger_20261119/evidence/unit-${unit}`)
const origin = 'http://127.0.0.1:18764'
const api = '/api/v1/finance/supplier-ledger/'
const pagePath = '/finance/supplier-ledger'

async function loadFixture() {
  const deadline = Date.now() + 600_000
  while (Date.now() < deadline) {
    try {
      return JSON.parse(await fs.readFile(path.join(control, 'ready.json'), 'utf8'))
    } catch (error) {
      if (error.code !== 'ENOENT' && !(error instanceof SyntaxError)) throw error
      await delay(500)
    }
  }
  throw new Error('隔离数据库夹具未就绪')
}

async function login(context, identity, canViewLedger) {
  await context.request.get(`${origin}/api/auth/me/`)
  const token = (await context.cookies()).find(item => item.name === 'csrftoken')?.value
  assert.ok(token, '缺少会话 CSRF Cookie')
  const result = await context.request.post(`${origin}/api/auth/login/`, {
    data: identity, headers: { 'X-CSRFToken': token, Origin: origin },
  })
  assert.equal(result.status(), 200, '隔离账号实际登录')
  const response = await context.request.get(`${origin}/api/auth/me/`)
  assert.equal(response.status(), 200)
  const user = (await response.json()).user
  assert.equal(user.is_superuser, false)
  assert.equal(user.permissions.includes('finance.view_supplierledger'), canViewLedger)
}

async function layout(page) {
  const metrics = await page.locator('.supplier-ledger').evaluate(root => {
    const frame = root.querySelector('.erp-list-table-frame')
    const header = frame.querySelector('.el-table__header th')
    const cell = frame.querySelector('.el-table__body td')
    const area = frame.querySelector('.el-scrollbar__wrap')
    return {
      width: innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      title: getComputedStyle(root.querySelector('h1')).fontSize,
      border: ['Top', 'Right', 'Bottom', 'Left'].map(side => getComputedStyle(frame)[`border${side}Width`]),
      patch: getComputedStyle(frame.querySelector('.el-table__inner-wrapper'), '::before').display,
      headHeight: header.getBoundingClientRect().height,
      rowHeight: cell.getBoundingClientRect().height,
      footerHeight: root.querySelector('.erp-list-footer').getBoundingClientRect().height,
      localScroll: area.scrollWidth > area.clientWidth,
      singleLine: getComputedStyle(cell.firstElementChild).whiteSpace,
    }
  })
  assert.equal(metrics.width, metrics.documentWidth)
  assert.equal(metrics.title, '36px')
  assert.deepEqual(metrics.border, ['1px', '1px', '1px', '1px'])
  assert.equal(metrics.patch, 'none')
  assert.equal(metrics.headHeight, 38)
  assert.equal(metrics.rowHeight, 40)
  assert.equal(metrics.footerHeight, 40)
  assert.equal(metrics.singleLine, 'nowrap')
  return metrics
}

async function checkFinance(browser, fixture) {
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, reducedMotion: 'reduce' })
  const errors = []
  await context.route('**/*', route => {
    const request = route.request()
    return new URL(request.url()).origin === origin && ['GET', 'HEAD', 'OPTIONS'].includes(request.method())
      ? route.continue() : route.abort()
  })
  try {
    await login(context, fixture.identities.finance, true)
    const page = await context.newPage()
    page.on('pageerror', error => errors.push(error.message))
    page.setDefaultTimeout(20_000)
    await page.goto(`${origin}${pagePath}?month=2026-10`, { waitUntil: 'domcontentloaded' })
    const ledger = page.locator('.supplier-ledger')
    const supplier = ledger.getByRole('link', { name: fixture.supplier_name, exact: true })
    try {
      await supplier.waitFor()
    } catch (error) {
      const location = new URL(page.url()).pathname
      const alerts = await page.getByRole('alert').allInnerTexts()
      throw new Error(`往来页未显示供应商，当前页面 ${location}，页面提示 ${alerts.join(' / ')}，JS 错误 ${errors.join(' / ')}`, { cause: error })
    }
    assert.equal(await supplier.count(), 1)
    const summary = await layout(page)
    const texts = await ledger.locator('.el-table__body td').allInnerTexts()
    assert.deepEqual(texts.map(text => text.trim()), [fixture.supplier_name, '0.00', '1,000.00', '0.00', '0.00', '1,000.00', '0.00', '1'])
    assert.equal(await ledger.getByRole('button', { name: '登记付款' }).count(), 0)
    await page.screenshot({ path: path.join(output, 'summary-1920.png') })

    await supplier.click()
    const pending = ledger.locator('.el-table__body tr').filter({ hasText: '待核价' })
    await pending.waitFor()
    assert.equal((await pending.locator('td').nth(4).innerText()).trim(), '—')
    assert.equal((await ledger.locator('.el-table__body tr').count()), 3)
    assert.equal(await ledger.getByText('2026-11-02', { exact: true }).count(), 2)
    const wideDetail = await layout(page)
    assert.equal(wideDetail.localScroll, true)
    await page.screenshot({ path: path.join(output, 'detail-1920.png') })
    await page.setViewportSize({ width: 1024, height: 768 })
    const narrowDetail = await layout(page)
    assert.equal(narrowDetail.localScroll, true)
    await page.screenshot({ path: path.join(output, 'detail-1024.png') })

    const receipt = ledger.getByRole('button', { name: fixture.inbound_number, exact: true }).first()
    const horizontal = ledger.locator('.el-scrollbar__wrap').first()
    await horizontal.evaluate(node => { node.scrollLeft = 1350 })
    await receipt.click()
    const original = page.getByRole('dialog', { name: fixture.inbound_number })
    await original.getByText('125.0000', { exact: true }).first().waitFor()
    await page.screenshot({ path: path.join(output, 'receipt-1024.png') })
    await original.getByRole('button', { name: '关闭', exact: true }).last().click()

    await horizontal.evaluate(node => { node.scrollLeft = 0 })
    await ledger.getByRole('link', { name: fixture.pending_number, exact: true }).click()
    await page.getByRole('dialog', { name: `采购应付 ${fixture.pending_number}` }).waitFor()
    await page.goBack({ waitUntil: 'domcontentloaded' })
    await pending.waitFor()
    await ledger.getByRole('button', { name: '返回列表' }).click()
    await supplier.waitFor()
    await ledger.getByRole('button', { name: '更多筛选' }).waitFor()
    assert.equal(new URL(page.url()).searchParams.get('month'), '2026-10')
    if (acceptance) {
      await page.goto(`${origin}${pagePath}?month=2026-08`)
      await ledger.getByText('暂无往来记录', { exact: true }).waitFor()
    }
    assert.deepEqual(errors, [])
    return { summary, wideDetail, narrowDetail, pageErrors: errors }
  } finally {
    await context.close()
  }
}

async function capture(page, name) {
  await page.locator('.el-loading-mask:visible').first().waitFor({ state: 'hidden' })
  await page.screenshot({ path: path.join(output, `${name}.png`), animations: 'disabled' })
}

async function checkRoleAccess(cashier, finance, fixture, paid, offset) {
  const paymentPath = `payments/${paid.id}/`
  const offsetPath = `offsets/${offset.id}/`
  const payablePath = `/api/v1/finance/purchase-payables/${fixture.confirmed_id}/`
  const inboundPath = `/api/v1/material-inventory/receipts/?inbound_id=${fixture.inbound_id}`
  const month = paid.business_date.slice(0, 7)
  const entries = `entries/?supplier_id=${fixture.supplier_id}&month=2026-10`
  const roles = {}
  const options = await cashier.context.request.get(origin + api + 'payment-options/')
  assert.equal(options.status(), 200)
  const account = (await options.json()).data.accounts.find(item => item.id === paid.account_id)
  const paymentData = { supplier_id: fixture.supplier_id, account_id: paid.account_id, paid_on: paid.business_date,
    nature: paid.nature, amount: '1.00', payee: '隔离收款人', voucher: 'QA-U04-PERMISSION' }
  for (const [role, { page, context }] of Object.entries({ cashier, finance })) {
    const isCashier = role === 'cashier'
    const access = roles[role] = {}
    const token = (await context.cookies()).find(cookie => cookie.name === 'csrftoken').value
    async function read(label, suffix, expected) {
      const response = await context.request.get(origin + (suffix.startsWith('/') ? suffix : api + suffix))
      assert.equal(response.status(), expected, `${role} GET ${label}`)
      access[label] = response.status()
      return response
    }
    async function rejectedWrite(label, suffix, data, etag, csrfToken = token) {
      const response = await context.request.post(origin + api + suffix, {
        data,
        headers: { Origin: origin, 'X-CSRFToken': csrfToken, 'If-Match': etag, 'Idempotency-Key': randomUUID() },
      })
      assert.equal(response.status(), 403, `${role} POST ${label}`)
      access[label] = response.status()
    }

    if (isCashier) await page.goto(`${origin}${pagePath}?month=${month}`)
    await page.locator('[data-menu-key="finance-management"]').hover()
    const menu = page.locator('[data-menu-key="finance-supplier-ledger"]')
    await menu.waitFor()
    assert.equal(await menu.getAttribute('href'), pagePath)
    assert.equal(await page.locator('[data-menu-key="finance-purchase-payables"]').count(), isCashier ? 0 : 1)
    access.menu = true
    access.purchasePayableMenu = !isCashier
    await page.mouse.move(page.viewportSize().width - 10, 70)
    await menu.waitFor({ state: 'hidden' })
    await read('summary', `?month=${month}`, 200)
    const october = await read('entries', entries, 200)
    const row = (await october.json()).data.find(item => item.number === fixture.confirmed_number)
    assert.ok(row)
    assert.equal(row.payable_id, isCashier ? null : fixture.confirmed_id)
    assert.equal(row.inbound_id, isCashier ? null : fixture.inbound_id)
    assert.equal(Boolean(row.purchase_order_id), !isCashier)
    assert.equal(Boolean(row.production_task_id), !isCashier)
    access.sourceLinks = !isCashier
    await read('payableOriginal', payablePath, isCashier ? 403 : 200)
    await read('inboundOriginal', inboundPath, isCashier ? 403 : 200)
    const payment = await read('paymentOriginal', paymentPath, 200)
    const offsetDoc = await read('offsetOriginal', offsetPath, 200)
    await read('paymentOptions', 'payment-options/', isCashier ? 200 : 403)
    await read('offsetOptions', 'offset-options/', isCashier ? 403 : 200)
    await read('offsetPayables', `offset-payables/?payment_id=${paid.id}`, isCashier ? 403 : 200)

    if (isCashier) {
      const summary = page.locator('.supplier-ledger')
      await summary.getByRole('link', { name: fixture.supplier_name }).click()
      for (const document of [paid, offset]) {
        await summary.getByRole('button', { name: document.number, exact: true }).click()
        const dialog = page.getByRole('dialog', { name: new RegExp(document.number) })
        await dialog.getByRole('button', { name: '关闭', exact: true }).last().waitFor()
        assert.equal(await dialog.getByRole('button', { name: '更正', exact: true }).count(), 0)
        assert.equal(await dialog.getByRole('link', { name: fixture.confirmed_number, exact: true }).count(), 0)
        await dialog.getByRole('button', { name: '关闭', exact: true }).last().click()
      }
      access.correctionButtons = false
      await rejectedWrite('paymentWithInvalidCsrf', 'payments/', paymentData, account.etag, 'invalid')
      await rejectedWrite('createOffset', 'offsets/', { payment_id: paid.id, offset_on: paid.business_date,
        allocations: [{ payable_id: fixture.confirmed_id, amount: '1.00' }] }, payment.headers().etag)
      await rejectedWrite('voidPayment', `${paymentPath}void/`, { reason: '隔离权限探测' }, payment.headers().etag)
      await rejectedWrite('voidOffset', `${offsetPath}void/`, { reason: '隔离权限探测' }, offsetDoc.headers().etag)
    } else {
      await rejectedWrite('createPayment', 'payments/', paymentData, account.etag)
    }
  }
  return roles
}

async function settlementBrowser(browser, fixture) {
  async function openRole(role) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' })
    await context.route('**/*', route => {
      const request = route.request()
      const url = new URL(request.url())
      const ledgerWrite = request.method() === 'POST'
        && /^\/api\/v1\/finance\/supplier-ledger\/(payments|offsets)(\/[a-f0-9-]+\/void)?\/$/.test(url.pathname)
      return url.origin === origin && (ledgerWrite || ['GET', 'HEAD', 'OPTIONS'].includes(request.method()))
        ? route.continue() : route.abort()
    })
    await login(context, fixture.identities[role], true)
    const page = await context.newPage()
    page.setDefaultTimeout(20_000)
    return { context, page }
  }
  async function post(page, suffix, button, status) {
    const pending = page.waitForResponse(response => new URL(response.url()).pathname === api + suffix
      && response.request().method() === 'POST')
    await button.click()
    const response = await pending
    const body = await response.json()
    assert.equal(response.status(), status, body.error?.message ?? suffix)
    return body.data
  }
  async function choose(page, dialog, field, choice) {
    await dialog.locator('.el-select').filter({ has: page.getByRole('combobox', { name: field, exact: true }) })
      .locator('.el-select__wrapper').click()
    await page.getByRole('option', { name: choice }).click()
  }

  const cashier = await openRole('cashier')
  let finance
  try {
    await cashier.page.goto(origin + pagePath)
    const registry = cashier.page.locator('.supplier-ledger')
    await registry.getByRole('button', { name: '登记付款', exact: true }).click()
    assert.equal(await registry.getByRole('button', { name: '抵账', exact: true }).count(), 0)
    const payment = cashier.page.getByRole('dialog', { name: '登记付款', exact: true })
    await payment.locator('.el-loading-mask').first().waitFor({ state: 'hidden' })
    await choose(cashier.page, payment, '供应商', fixture.supplier_name)
    await choose(cashier.page, payment, '款项性质', '预付款')
    await choose(cashier.page, payment, '公司付款账户', /隔离付款账户/)
    await payment.getByRole('textbox', { name: '收款人', exact: true }).fill('隔离收款人')
    await payment.getByRole('textbox', { name: '实付金额', exact: true }).fill('300.00')
    await payment.getByRole('textbox', { name: '付款凭证编号', exact: true }).fill(`QA-U0${unit}-RECEIPT`)
    await capture(cashier.page, 'register-payment')
    const paid = await post(cashier.page, 'payments/', payment.getByRole('button', { name: '保存', exact: true }), 201)
    await payment.waitFor({ state: 'hidden' })
    assert.equal(paid.amount, '300.00')
    assert.equal(paid.nature, 'PREPAYMENT')

    finance = await openRole('finance')
    const month = paid.business_date.slice(0, 7)
    await finance.page.goto(`${origin}${pagePath}?month=${month}`)
    const ledger = finance.page.locator('.supplier-ledger')
    await ledger.getByRole('button', { name: '抵账', exact: true }).click()
    assert.equal(await ledger.getByRole('button', { name: '登记付款', exact: true }).count(), 0)
    const offset = finance.page.getByRole('dialog', { name: '抵账', exact: true })
    await offset.locator('.el-loading-mask').first().waitFor({ state: 'hidden' })
    await choose(finance.page, offset, '付款单号', new RegExp(paid.number))
    const amount = offset.getByRole('textbox', { name: `${fixture.confirmed_number} 本次抵账金额`, exact: true })
    await amount.fill('125.00')
    await capture(finance.page, 'allocate-payment')
    const receipt = await post(finance.page, 'offsets/', offset.getByRole('button', { name: '保存', exact: true }), 201)
    await offset.waitFor({ state: 'hidden' })
    assert.equal(receipt.allocations[0].amount, '125.00')
    await ledger.getByText('875.00', { exact: true }).waitFor()
    const roleAccess = acceptance ? await checkRoleAccess(cashier, finance, fixture, paid, receipt) : undefined
    const supplier = ledger.getByRole('link', { name: fixture.supplier_name })
    await supplier.click()
    await ledger.getByRole('button', { name: receipt.number, exact: true }).click()
    const correction = finance.page.getByRole('dialog', { name: `抵账单 ${receipt.number}` })
    await correction.getByRole('button', { name: '更正', exact: true }).click()
    await correction.getByRole('textbox', { name: '更正原因' }).fill('隔离验证抵账更正')
    const voided = await post(finance.page, `offsets/${receipt.id}/void/`, correction.getByRole('button', { name: '确认更正' }), 200)
    assert.equal(voided.status, 'VOID')
    await capture(finance.page, 'offset-correction')
    await correction.getByRole('button', { name: '关闭', exact: true }).last().click()
    const original = ledger.getByRole('button', { name: paid.number, exact: true })
    await original.click()
    const paymentDetail = finance.page.getByRole('dialog', { name: `付款单 ${paid.number}` })
    await paymentDetail.getByRole('button', { name: '更正', exact: true }).click()
    await paymentDetail.getByRole('textbox', { name: '更正原因' }).fill('隔离验证付款更正')
    const voidPayment = await post(finance.page, `payments/${paid.id}/void/`, paymentDetail.getByRole('button', { name: '确认更正' }), 200)
    assert.equal(voidPayment.status, 'VOID')
    await paymentDetail.getByRole('button', { name: '关闭', exact: true }).last().click()
    await ledger.getByRole('button', { name: '返回列表', exact: true }).click()
    await supplier.waitFor()
    const finalCells = await ledger.locator('.el-table__body td').allInnerTexts()
    assert.deepEqual(finalCells.map(text => text.trim()).slice(2, 7), ['0.00', '0.00', '0.00', '1,000.00', '0.00'])

    const options = await cashier.context.request.get(origin + api + 'payment-options/')
    const account = (await options.json()).data.accounts.find(row => row.id === paid.account_id)
    const token = (await cashier.context.cookies()).find(cookie => cookie.name === 'csrftoken').value
    for (let index = 1; index <= 21; index++) {
      const payment = await cashier.context.request.post(origin + api + 'payments/', {
        headers: { Origin: origin, 'X-CSRFToken': token, 'If-Match': account.etag, 'Idempotency-Key': randomUUID() },
        data: { supplier_id: fixture.supplier_id, account_id: account.id, paid_on: '2026-08-01',
          nature: 'GOODS', amount: '1.00', payee: '隔离分页收款人', voucher: `QA-U0${unit}-PAGE-${index}` },
      })
      assert.equal(payment.status(), 201)
    }
    await finance.page.goto(`${origin}${pagePath}?month=2026-08&supplier_id=${fixture.supplier_id}`)
    await ledger.getByText('21.00', { exact: true }).waitFor()
    await supplier.click()
    const detailRows = ledger.locator('.el-table__body tr')
    await detailRows.first().waitFor()
    assert.equal(await detailRows.count(), 21)
    await ledger.locator('.erp-list-footer .el-select').click()
    await finance.page.getByRole('option', { name: '20条/页' }).click()
    await finance.page.waitForFunction(() => document.querySelectorAll('.supplier-ledger .el-table__body tr').length === 20)
    await ledger.locator('.btn-next').click()
    await finance.page.waitForFunction(() => document.querySelectorAll('.supplier-ledger .el-table__body tr').length === 1)
    await ledger.getByRole('button', { name: '返回列表', exact: true }).click()
    await ledger.getByText('21.00', { exact: true }).waitFor()
    assert.equal(new URL(finance.page.url()).searchParams.get('supplier_id'), fixture.supplier_id)
    assert.equal(new URL(finance.page.url()).searchParams.get('month'), '2026-08')
    return { cashierPayment: 201, financeOffset: 201, offsetCorrection: 200, paymentCorrection: 200, closingAmount: '1000.00', paginatedEntries: 21, roleAccess }
  } finally {
    await cashier.context.close()
    await finance?.context.close()
  }
}

async function run() {
  if (process.argv.includes('--unit-4')) assert.ok(acceptance, '第四单元必须使用 SUPPLIER_LEDGER_ACCEPTANCE_BROWSER=1')
  const fixture = await loadFixture()
  assert.equal(fixture.database, `test_supplier_ledger_u0${unit}_20261119`)
  let server
  let browser
  let createdRuntime = false
  let passed = false
  try {
    await fs.mkdir(runtime)
    createdRuntime = true
    await fs.mkdir(output, { recursive: true })
    process.env.VITE_API_BASE_URL = 'same-origin'
    process.env.VITE_PROXY_TARGET = 'http://127.0.0.1:18763'
    process.env.TEMP = runtime
    process.env.TMP = runtime
    const { createServer } = await import(pathToFileURL(path.join(frontend, 'node_modules/vite/dist/node/index.js')).href)
    server = await createServer({
      root: frontend, cacheDir: path.join(runtime, 'vite'),
      server: { host: '127.0.0.1', port: 18764, strictPort: true, open: false },
    })
    await server.listen()
    const { chromium } = require(path.join(frontend, 'node_modules/playwright-core'))
    browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
    const metrics = await checkFinance(browser, fixture)
    let settlement
    if (unit >= 3) {
      settlement = await settlementBrowser(browser, fixture)
    } else {
      const cashier = await browser.newContext()
      await login(cashier, fixture.identities.cashier, false)
      const denied = await cashier.request.get(origin + api)
      assert.equal(denied.status(), 403)
      await cashier.close()
      settlement = { cashierStatus: denied.status() }
    }
    await fs.writeFile(path.join(output, 'layout.json'), JSON.stringify({ ...metrics, ...settlement }, null, 2))
    console.log(unit >= 3 ? '出纳登记、财务抵账及两类更正页面通过' : '普通财务身份页面、入库原单、应付原单、出纳权限通过')
    passed = true
  } finally {
    try {
      await browser?.close()
      await server?.close()
    } finally {
      if (createdRuntime) await fs.rm(runtime, { recursive: true, maxRetries: 3, retryDelay: 50 })
      await fs.writeFile(path.join(control, 'done.json'), JSON.stringify({ passed }))
    }
  }
}

run().catch(error => {
  console.error(error)
  process.exitCode = 1
})

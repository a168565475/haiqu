// 显式运行；仅允许本任务 18015/18016 隔离服务，禁止指向正式开发服务。
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')
const { chromium, request } = require('playwright-core')

const apiUrl = 'http://127.0.0.1:18015'
const baseUrl = 'http://127.0.0.1:18016'
const reportDir = path.resolve('output/playwright/order-correction-20261015')
const seedPath = path.resolve('.tmp/order-correction-20261015/seed.json')
const phase = process.argv[2] || 'api'
const checks = []
const calls = []
const sourcePng = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=', 'base64')
const today = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' })
const futureDate = days => new Date(Date.now() + days * 86400000).toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' })

async function responseSummary(response) {
  if (!response.headers()['content-type']?.includes('application/json')) return `HTTP ${response.status()}（非 JSON 响应正文不写入日志）`
  const body = await response.json()
  return JSON.stringify({ status: response.status(), code: body.error?.code, message: body.error?.message || body.detail, fields: body.error?.field_errors })
}

async function login(context, username, password) {
  const me = await context.get(`${apiUrl}/api/auth/me/`)
  assert.equal(me.status(), 200)
  const state = await context.storageState()
  const csrf = state.cookies.find(cookie => cookie.name === 'csrftoken')
  assert.ok(csrf, '登录前必须有 CSRF Cookie')
  const response = await context.post(`${apiUrl}/api/auth/login/`, {
    data: { username, password }, headers: { 'X-CSRFToken': csrf.value, Referer: baseUrl },
  })
  assert.equal(response.status(), 200, `正常账号密码登录失败：${await responseSummary(response)}`)
  assert.equal((await response.json()).authenticated, true)
}

async function call(context, method, route, expected, data, etag, extra = {}) {
  const state = await context.storageState()
  const csrf = state.cookies.find(cookie => cookie.name === 'csrftoken')?.value
  const headers = { Referer: baseUrl, ...(etag ? { 'If-Match': etag } : {}), ...(method === 'get' ? {} : { 'X-CSRFToken': csrf }) }
  const response = await context[method](`${apiUrl}${route}`, { headers, ...(data === undefined ? {} : { data }), ...extra })
  calls.push({ method, route, status: response.status() })
  assert.ok((Array.isArray(expected) ? expected : [expected]).includes(response.status()), `${method} ${route}: ${await responseSummary(response)}`)
  return { data: (await response.json()).data, etag: response.headers().etag }
}

function pdfEvidence() {
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]
  const stream = 'BT /F1 12 Tf 20 150 Td (Isolated order correction acceptance evidence) Tj ET'
  objects.push(`<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`)
  let body = '%PDF-1.4\n'
  const offsets = [0]
  objects.forEach((object, i) => { offsets.push(Buffer.byteLength(body)); body += `${i + 1} 0 obj\n${object}\nendobj\n` })
  const xref = Buffer.byteLength(body)
  body += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return Buffer.from(body)
}

async function apiPhase(seed, password) {
  const context = await request.newContext()
  const restricted = await request.newContext()
  const factory = await request.newContext()
  try {
    await login(context, seed.username, password)
    checks.push('正常登录建立 Session/CSRF')
    const options = (await call(context, 'get', '/api/v1/production-tasks/options/', 200)).data
    assert.ok(options.products.some(product => product.id === seed.product_id), '产品必须来自真实产品 API')
    const numberBase = `HT${Date.now()}`
    async function manualPayload(number) {
      const reserved = (await call(context, 'post', '/api/v1/production-tasks/reserve-contract-number/', 200, { order_date: today })).data
      return {
        contract_number: reserved.contract_number, contract_number_token: reserved.token,
        task_number: number, order_source: 'NEW', order_date: today, delivery_date: futureDate(5),
        salesperson_id: seed.salesperson_id, follower_ids: [seed.production_follower_id],
        currency_id: seed.currency_id, includes_tax: true, tax_rate: 3, order_tolerance_percent: '5.00',
        is_repeat_order: false, preproduction_sample_required: false, delivery_method: 'SINGLE',
        freight_amount: '0', other_fee_amount: '0', products: [{
          client_key: 'manual-product', product_id: seed.product_id, quantity: 1,
          product_color_id: options.colors[0]?.id, color_code: options.colors[0]?.color_code,
          unit_id: seed.unit_id, currency_id: seed.currency_id, unit_price: '20.0000', exchange_rate: '1.000',
          special_requirements: '隔离验收品质要求', packaging_method: '隔离验收纸箱',
          details: options.detail_template.map((item, index) => ({ client_key: `manual-detail-${index}`,
            template_key: item.key, detail_type: item.type, category_label: item.category,
            is_selected: index === 0, description: index === 0 ? '隔离验收生产明细' : '' })), retained_image_ids: [],
        }], delivery_batches: [],
      }
    }
    const payload = await manualPayload(`${numberBase}-1`)
    const noCsrf = await context.post(`${apiUrl}/api/v1/production-tasks/`, { data: payload })
    assert.equal(noCsrf.status(), 403, 'Session 写入必须校验 CSRF')
    for (const changes of [{ follower_ids: [] }, { customer_account_id: seed.customer_id }, { company_id: seed.customer_id }, { tax_rate: null }, { includes_tax: false, tax_rate: 3 }, { task_number: 'HT26/1' }]) {
      await call(context, 'post', '/api/v1/production-tasks/', 400, { ...payload, ...changes })
    }
    checks.push('CSRF 与手动跟单员/客户/公司/税率/编号边界')
    const manual = await call(context, 'post', '/api/v1/production-tasks/', 201, payload)
    assert.equal(manual.data.sales_order_id, null)
    assert.equal(manual.data.customer_id, null)
    assert.equal(manual.data.followers[0].id, seed.production_follower_id)
    assert.equal(manual.data.products[0].product_id, seed.product_id)
    await call(context, 'post', '/api/v1/production-tasks/', 400, await manualPayload(`${numberBase}-1`))
    checks.push('手动无来源建单成功、真实产品ID、HT唯一性')
    const patched = await call(context, 'patch', `/api/v1/production-tasks/${manual.data.id}/`, 200, { delivery_date: futureDate(6) }, manual.etag)
    await call(context, 'patch', `/api/v1/production-tasks/${manual.data.id}/`, 412, { delivery_date: futureDate(7) }, manual.etag)
    assert.equal(patched.data.delivery_date, futureDate(6))
    checks.push('手动交期可改、旧ETag拒绝覆盖')

    async function createSalesOrder(quantity) {
      const created = await call(context, 'post', '/api/v1/sales-orders/', 201, {
        source_type: 'DIRECT', customer_account_id: seed.customer_id, transaction_entity_id: seed.entity_id,
        buyer_address_id: seed.address_id, salesperson_id: seed.salesperson_id, merchandiser_id: seed.sales_follower_id,
        customer_po_number: `${numberBase}-${quantity}`, contract_number: `${numberBase}-${quantity}`,
        order_date: today, direct_order_reason: '隔离验收客户书面下单', currency_code: 'CNY', exchange_rate: '1.000000',
        payment_terms: '隔离验收条款', deposit_required: false, includes_tax: true, tax_basis: '含税',
        order_tolerance_percent: '5.00', preproduction_sample_required: false,
        seller_snapshot: { template_config: { seller_company_name: 'ISOLATED ACCEPTANCE SELLER' } },
        confirmation_method: 'CUSTOMER_PO', customer_confirmer: '隔离验收联系人', customer_confirmed_at: new Date().toISOString(),
        confirmation_summary: '确认产品、数量、价格和交期', evidence_file_ids: [],
        lines: [{ client_key: 'sales-line', product_id: seed.product_id, quantity: String(quantity), unit_price: '20.0000',
          quality_requirements: '来源品质要求', packaging_requirements: '来源纸箱要求', shipping_mark_requirements: '来源唛头' }],
        delivery_batches: [{ planned_delivery_date: futureDate(5), lines: [{ sales_order_line_client_key: 'sales-line', quantity: String(quantity) }] }],
      })
      const proof = await call(context, 'post', `/api/v1/sales-orders/${created.data.id}/evidence/`, 201, undefined, created.etag,
        { multipart: { file: { name: 'isolated-acceptance.pdf', mimeType: 'application/pdf', buffer: pdfEvidence() } } })
      const image = await call(context, 'post', `/api/v1/sales-orders/${created.data.id}/lines/${created.data.lines[0].id}/product-image/`, 201, undefined, proof.etag,
        { multipart: { file: { name: 'isolated-product.png', mimeType: 'image/png', buffer: sourcePng } } })
      return call(context, 'post', `/api/v1/sales-orders/${created.data.id}/confirm/`, 200, {}, image.etag)
    }
    const sourceOrder = await createSalesOrder(100)
    await login(factory, seed.factory_username, password)
    await call(factory, 'get', `/api/v1/sales-orders/${sourceOrder.data.id}/`, [403, 404])
    await call(factory, 'get', `/api/v1/production-tasks/sales-order-sources/?sales_order_id=${sourceOrder.data.id}`, 200)
    const factoryImage = await factory.get(`${apiUrl}/api/v1/production-tasks/sales-order-source-image/?sales_order_id=${sourceOrder.data.id}&line_id=${sourceOrder.data.lines[0].id}`)
    assert.equal(factoryImage.status(), 200, await responseSummary(factoryImage))
    assert.deepEqual(await factoryImage.body(), sourcePng)
    calls.push({ method: 'get', route: 'production sales source image', status: factoryImage.status() })
    const factoryOptions = (await call(factory, 'get', '/api/v1/production-tasks/options/', 200)).data
    assert.ok(factoryOptions.products.some(product => product.id === seed.product_id))
    checks.push('仅生产权限账号可读来源/真实图片/产品选项，不能读取完整销售订单')
    const sourceCreated = await call(factory, 'post', '/api/v1/production-tasks/create-from-sales-order/', 201, {
      task_number: `${numberBase}-2`, delivery_batch_line_id: sourceOrder.data.delivery_batches[0].lines[0].id, quantity: 100,
    })
    const source = await call(factory, 'post', `/api/v1/production-tasks/${sourceCreated.data.id}/submit/`, 200, {}, sourceCreated.etag)
    assert.equal(source.data.salesperson.id, seed.salesperson_id)
    assert.deepEqual(source.data.followers, [])
    assert.equal(source.data.delivery_date, futureDate(5))
    assert.equal(source.data.products[0].product_id, seed.product_id)
    assert.equal(source.data.products[0].special_requirements, '来源品质要求')
    assert.equal(source.data.products[0].packaging_method, '来源纸箱要求')
    const sourceTaskImage = source.data.products[0].images.find(image => image.name === 'isolated-product.png')
    assert.ok(sourceTaskImage, '来源图片须进入生产产品明细图片关联')
    const copiedImage = await factory.get(`${apiUrl}/api/v1/production-tasks/${source.data.id}/business-files/${sourceTaskImage.id}/`)
    assert.equal(copiedImage.status(), 200, await responseSummary(copiedImage))
    assert.deepEqual(await copiedImage.body(), sourcePng)
    calls.push({ method: 'get', route: 'production copied product image', status: copiedImage.status() })
    const fullyAllocated = await call(context, 'get', `/api/v1/sales-orders/${sourceOrder.data.id}/`, 200)
    assert.equal(fullyAllocated.data.has_remaining_production_capacity, false)
    checks.push('来源只带业务员与产品日期；100/100按名义数量分配完成')
    const pmc = { decision: 'CONFIRM', follower_ids: [seed.production_follower_id], planned_start_date: today,
      planned_end_date: futureDate(4), delivery_date: futureDate(8), includes_tax: true, tax_rate: 5,
      order_tolerance_percent: '7.00', is_repeat_order: true, delivery_method: 'SPLIT' }
    await call(factory, 'post', `/api/v1/production-tasks/${source.data.id}/pmc-decision/`, 400, { ...pmc, follower_ids: [] }, source.etag)
    const confirmed = await call(factory, 'post', `/api/v1/production-tasks/${source.data.id}/pmc-decision/`, 200, pmc, source.etag)
    assert.equal(confirmed.data.followers[0].id, seed.production_follower_id)
    assert.equal(confirmed.data.tax_rate, 5)
    assert.equal(confirmed.data.delivery_method, 'SPLIT')
    const afterPmcOrder = await call(context, 'get', `/api/v1/sales-orders/${sourceOrder.data.id}/`, 200)
    assert.equal(afterPmcOrder.data.merchandiser.id, seed.sales_follower_id)
    assert.equal(afterPmcOrder.data.delivery_batches[0].planned_delivery_date, futureDate(8))
    assert.notEqual(afterPmcOrder.etag, fullyAllocated.etag, '交期回写必须更新销售订单 ETag')
    checks.push('PMC独立选跟单员、生产税率交货方式保存、交期回写且销售跟单员不变')
    const changedSource = await call(factory, 'patch', `/api/v1/production-tasks/${source.data.id}/`, 200,
      { delivery_date: futureDate(10) }, confirmed.etag)
    assert.equal(changedSource.data.delivery_date, futureDate(10))
    const afterEditOrder = await call(context, 'get', `/api/v1/sales-orders/${sourceOrder.data.id}/`, 200)
    assert.equal(afterEditOrder.data.delivery_batches[0].planned_delivery_date, futureDate(10))
    assert.notEqual(afterEditOrder.etag, afterPmcOrder.etag)
    checks.push('生产确认后修改交期继续回写销售交期与ETag')
    const pendingOrder = await createSalesOrder(10)
    const pendingCreated = await call(context, 'post', '/api/v1/production-tasks/create-from-sales-order/', 201, {
      task_number: `${numberBase}-3`, delivery_batch_line_id: pendingOrder.data.delivery_batches[0].lines[0].id, quantity: 10,
    })
    const pending = await call(context, 'post', `/api/v1/production-tasks/${pendingCreated.data.id}/submit/`, 200, {}, pendingCreated.etag)
    for (const suffix of [5, 6, 7]) {
      await call(context, 'post', '/api/v1/production-tasks/', 201, await manualPayload(`${numberBase}-${suffix}`))
    }
    const recentOptions = (await call(context, 'get', '/api/v1/production-tasks/options/', 200)).data
    assert.deepEqual(recentOptions.recent_task_numbers, [2, 3, 5, 6, 7].map(suffix => `${numberBase}-${suffix}`).sort())
    checks.push('最近五笔编号来自刚刚真实保存记录并按编号排序')
    await login(restricted, seed.restricted_username, password)
    await call(restricted, 'post', '/api/v1/production-tasks/', 403, payload)
    checks.push('无权限员工被后端拒绝创建')
    await fs.writeFile(path.join(reportDir, 'api-state.json'), JSON.stringify({
      numberBase, manualTaskId: manual.data.id, sourceTaskId: source.data.id, sourceOrderId: sourceOrder.data.id,
      sourceOrderNumber: sourceOrder.data.order_number, pendingTaskId: pending.data.id, seed,
    }, null, 2))
  } finally {
    await context.dispose()
    await restricted.dispose()
    await factory.dispose()
  }
}

async function pagePhase(seed, password) {
  const state = JSON.parse(await fs.readFile(path.join(reportDir, 'api-state.json'), 'utf8'))
  const browserTemp = path.resolve('.tmp/order-correction-20261015/browser')
  await fs.mkdir(browserTemp, { recursive: true })
  const previousTemp = process.env.TEMP
  const previousTmp = process.env.TMP
  process.env.TEMP = browserTemp
  process.env.TMP = browserTemp
  let browser
  try {
    browser = await chromium.launch({ executablePath: process.env.UI_E2E_CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', headless: true })
    const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } })
    await login(context.request, seed.factory_username, password)
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(`${baseUrl}/production-tasks/new`, { waitUntil: 'networkidle' })
    await page.getByText('手动创建', { exact: false }).first().waitFor()
    assert.equal(await page.getByText(state.sourceOrderNumber, { exact: true }).count(), 0, '已分配100/100销售订单不能仍可选')
    checks.push('来源创建页面包含手动入口并隐藏已分配完成订单')
    await page.goto(`${baseUrl}/production-tasks/new/manual`, { waitUntil: 'networkidle' })
    await page.getByText('跟单员', { exact: true }).first().waitFor()
    assert.equal(await page.getByText('客户名称', { exact: true }).count(), 0)
    await page.getByRole('button', { name: '选择产品', exact: true }).first().click()
    await page.getByPlaceholder('搜索产品编码、货号、品名或规格').fill(seed.product_number)
    await page.locator('label.el-radio').filter({ has: page.getByRole('radio', { name: `选择 ${seed.product_name}`, exact: true }) }).click()
    await page.locator('.fixed-product-name').filter({ hasText: seed.product_name }).waitFor()
    const options = (await call(context.request, 'get', '/api/v1/production-tasks/options/', 200)).data
    const formField = label => page.locator('.el-form-item').filter({ has: page.locator('.el-form-item__label', { hasText: label }) })
    async function selectOption(select, option) {
      await select.click()
      const listId = await select.getByRole('combobox').getAttribute('aria-controls')
      assert.ok(listId, '下拉框应指向自己的选项列表')
      await page.locator(`[id="${listId}"]`).getByRole('option', { name: option, exact: true }).click()
      await page.keyboard.press('Escape')
    }
    const selectField = (field, option) => selectOption(field.locator('.el-select'), option)
    await page.getByPlaceholder('例如 26199 或 26199-1').fill(`${Date.now()}-4`)
    await selectField(formField(/^业务员$/), '隔离验收业务员')
    await selectField(formField(/^跟单员$/), '隔离生产跟单李四')
    const cny = options.currencies.find(item => item.id === seed.currency_id)
    await selectField(formField(/^币种$/), `${cny.code} · ${cny.name}`)
    await selectField(formField(/^交货方式$/), '一次交货')
    await page.getByPlaceholder('请选择交期日期').fill(futureDate(5))
    await page.getByPlaceholder('请选择交期日期').press('Tab')
    const color = options.colors[0]
    const colorSelects = page.locator('.product-line-table .el-select')
    for (const [index, value] of [[0, color.color_card], [1, color.color_name], [2, color.color_code]]) {
      await selectOption(colorSelects.nth(index), value)
    }
    await page.locator('.product-line-table').getByPlaceholder('整数').fill('3')
    await page.locator('.product-line-table').getByPlaceholder('0.0000', { exact: true }).fill('20.0000')
    await page.screenshot({ path: path.join(reportDir, 'manual-form.png'), fullPage: true })
    const manualSave = page.waitForResponse(response => response.url().endsWith('/api/v1/production-tasks/') && response.request().method() === 'POST')
    await page.getByRole('button', { name: '保存草稿', exact: true }).click()
    const manualSavedResponse = await manualSave
    assert.equal(manualSavedResponse.status(), 201, await responseSummary(manualSavedResponse))
    const manualSaved = (await manualSavedResponse.json()).data
    assert.equal(manualSaved.sales_order_id, null)
    assert.equal(manualSaved.customer_id, null)
    assert.equal(manualSaved.products[0].product_id, seed.product_id)
    assert.equal(manualSaved.followers[0].id, seed.production_follower_id)
    await page.waitForURL(`**/production-tasks/${manualSaved.id}`)
    checks.push('仅生产权限账号无需销售订单可手动建单、真实产品选择并页面保存成功')
    await page.goto(`${baseUrl}/production-tasks/${state.sourceTaskId}`, { waitUntil: 'networkidle' })
    await page.getByText('隔离生产跟单李四', { exact: false }).first().waitFor()
    assert.equal(await page.getByText('隔离验收客户', { exact: true }).count(), 0)
    await page.screenshot({ path: path.join(reportDir, 'source-task-detail.png'), fullPage: true })
    checks.push('生产详情展示独立跟单员，隐藏客户')
    await page.goto(`${baseUrl}/production-tasks/${state.pendingTaskId}`, { waitUntil: 'networkidle' })
    await page.getByRole('button', { name: 'PMC 确认通过', exact: true }).click()
    await page.getByRole('button', { name: '确认通过', exact: true }).click()
    await page.getByText('请选择生产跟单员。', { exact: true }).waitFor()
    const pmcField = text => page.locator('.pmc-form label').filter({ has: page.locator('span', { hasText: text }) })
    await selectOption(pmcField(/^跟单员/).locator('.el-select'), '隔离生产跟单李四')
    if (await pmcField(/^税率/).count()) {
      await selectOption(pmcField(/^税率/).locator('.el-select'), '7%')
    }
    for (const [field, value] of [[/^计划开始日期/, today], [/^计划完工日期/, futureDate(3)], [/^交期日期/, futureDate(9)]]) {
      const input = pmcField(field).locator('input')
      await input.fill(value)
      await input.press('Tab')
    }
    await page.screenshot({ path: path.join(reportDir, 'pmc-confirmation-form.png'), fullPage: true })
    const confirmationResponse = page.waitForResponse(response => response.url().includes(`/production-tasks/${state.pendingTaskId}/pmc-decision/`) && response.request().method() === 'POST')
    await page.getByRole('button', { name: '确认通过', exact: true }).click()
    const confirmed = await confirmationResponse
    assert.equal(confirmed.status(), 200, await responseSummary(confirmed))
    const confirmedData = (await confirmed.json()).data
    assert.equal(confirmedData.followers[0].id, seed.production_follower_id)
    assert.equal(confirmedData.delivery_date, futureDate(9))
    await page.getByText('PMC 已确认。', { exact: true }).waitFor()
    checks.push('真实PMC弹窗拦截空跟单员，选择独立跟单员后确认保存成功')
    assert.deepEqual(errors, [], `页面 JS 异常：${errors.join('; ')}`)
    await context.close()
  } finally {
    await browser?.close()
    if (previousTemp === undefined) delete process.env.TEMP; else process.env.TEMP = previousTemp
    if (previousTmp === undefined) delete process.env.TMP; else process.env.TMP = previousTmp
  }
}

async function main() {
  assert.ok(['api', 'pages'].includes(phase), '阶段只允许 api 或 pages')
  const password = process.env.ORDER_CORRECTION_QA_PASSWORD
  assert.ok(password, '必须显式提供隔离账号密码')
  const seed = JSON.parse(await fs.readFile(seedPath, 'utf8'))
  assert.equal(seed.database, 'order_correction_20261015')
  await fs.mkdir(reportDir, { recursive: true })
  let failure
  try { await (phase === 'api' ? apiPhase(seed, password) : pagePhase(seed, password)) } catch (error) { failure = error }
  await fs.writeFile(path.join(reportDir, `${phase}-report.json`), JSON.stringify({ phase, status: failure ? 'FAIL' : 'PASS', checks, calls, error: failure?.message }, null, 2))
  console.log(JSON.stringify({ phase, status: failure ? 'FAIL' : 'PASS', checks, callCount: calls.length }))
  if (failure) throw failure
}
main().catch(error => { console.error(error.message); process.exitCode = 1 })

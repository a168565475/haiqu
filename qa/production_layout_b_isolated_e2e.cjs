// 显式运行；仅允许本任务 18195/18196 隔离服务，禁止指向正式开发服务。
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')
const { chromium, request } = require('playwright-core')

const apiUrl = 'http://127.0.0.1:18195'
const baseUrl = 'http://127.0.0.1:18196'
const reportDir = path.resolve('output/playwright/production-layout-b-20261015')
const seedPath = path.resolve('.tmp/production-layout-b/seed.json')
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
          product_color_id: seed.color_id, color_code: seed.color_code,
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
    const manual = await call(context, 'post', '/api/v1/production-tasks/', 201, undefined, undefined,
      {multipart:{payload:JSON.stringify(payload),'product_image_manual-product':{name:'manual-product.png',mimeType:'image/png',buffer:sourcePng}}})
    assert.equal(manual.data.products[0].exchange_rate_snapshot.rate,'1.00000000')
    assert.equal(manual.data.products[0].exchange_rate_snapshot.base_currency_code,'CNY')
    const manualImage=manual.data.products[0].images.find(image=>image.name==='manual-product.png')
    assert.ok(manualImage)
    const manualImageResponse=await context.get(`${apiUrl}/api/v1/production-tasks/${manual.data.id}/business-files/${manualImage.id}/`)
    assert.equal(manualImageResponse.status(),200)
    assert.deepEqual(await manualImageResponse.body(),sourcePng)
    checks.push('手动真实产品multipart主图保存且真实文件字节一致，CNY快照恒等1')
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

    async function createSalesOrder(quantity, currency = 'CNY') {
      const created = await call(context, 'post', '/api/v1/sales-orders/', 201, {
        source_type: 'DIRECT', customer_account_id: seed.customer_id, transaction_entity_id: seed.entity_id,
        buyer_address_id: seed.address_id, salesperson_id: seed.salesperson_id, merchandiser_id: seed.sales_follower_id,
        customer_po_number: `${numberBase}-${quantity}`, contract_number: `${numberBase}-${quantity}`,
        order_date: today, direct_order_reason: '隔离验收客户书面下单', currency_code: currency, exchange_rate: '1.000000',
        payment_terms: '隔离验收条款', deposit_required: false, includes_tax: true, tax_basis: '含税',
        order_tolerance_percent: '5.00', preproduction_sample_required: false,
        seller_snapshot: { template_config: { seller_company_name: 'ISOLATED ACCEPTANCE SELLER' } },
        confirmation_method: 'CUSTOMER_PO', customer_confirmer: '隔离验收联系人', customer_confirmed_at: new Date().toISOString(),
        confirmation_summary: '确认产品、数量、价格和交期', evidence_file_ids: [],
        lines: [{ client_key: 'sales-line', product_id: seed.product_id, product_color_id: seed.color_id, color_code: seed.color_code, material: '隔离来源铝合金', quantity: String(quantity), unit_price: '20.0000',
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
    await call(factory,'get',`/api/v1/products/selection-options/?category_id=${seed.category_id}`,403)
    for(const route of ['product-categories','production-units','product-colors'])
      await call(factory,'get',`/api/v1/reference-data/${route}/`,403)
    checks.push('仅生产权限从安全production/options读产品及字典，直接产品库与基础维护接口仍403')
    await call(factory, 'get', `/api/v1/sales-orders/${sourceOrder.data.id}/`, [403, 404])
    await call(factory, 'get', `/api/v1/production-tasks/sales-order-sources/?sales_order_id=${sourceOrder.data.id}`, 200)
    const factoryImage = await factory.get(`${apiUrl}/api/v1/production-tasks/sales-order-source-image/?sales_order_id=${sourceOrder.data.id}&line_id=${sourceOrder.data.lines[0].id}`)
    assert.equal(factoryImage.status(), 200, await responseSummary(factoryImage))
    assert.deepEqual(await factoryImage.body(), sourcePng)
    calls.push({ method: 'get', route: 'production sales source image', status: factoryImage.status() })
    const factoryOptions = (await call(factory, 'get', '/api/v1/production-tasks/options/', 200)).data
    assert.ok(factoryOptions.products.some(product => product.id === seed.product_id && product.category_id === seed.category_id && product.default_unit_id === seed.unit_id))
    assert.ok(factoryOptions.categories.some(category => category.id === seed.category_id))
    checks.push('仅生产权限账号可读来源/真实图片/产品选项，不能读取完整销售订单')
    const common = { follower_ids: [seed.production_follower_id], delivery_date: futureDate(5),
      includes_tax: true, tax_rate: 7, order_tolerance_percent: '6.00', is_repeat_order: true, delivery_method: 'SPLIT' }
    const preview = (await call(factory, 'get', `/api/v1/production-tasks/sales-order-sources/?sales_order_id=${sourceOrder.data.id}`, 200)).data
    assert.equal(Number(preview.total_amount),2000)
    assert.equal(preview.currency_code,'CNY')
    const sourceLine = preview.lines[0]
    assert.equal(sourceLine.specification_snapshot,seed.specification)
    assert.equal(sourceLine.unit_id, seed.unit_id)
    assert.equal(sourceLine.unit_code, '03')
    assert.equal(sourceLine.unit_name, seed.unit_name)
    assert.equal(sourceLine.item_number_snapshot, seed.item_number)
    assert.equal(sourceLine.product_color_id, seed.color_id)
    assert.equal(sourceLine.material_snapshot, '隔离来源铝合金')
    assert.equal(Number(sourceLine.unit_price), 20)
    assert.equal(Number(sourceLine.line_total), 2000)
    assert.ok(sourceLine.product_image_id)
    checks.push('真实来源图片/货号/颜色/规格/材质/原价/03字典单位齐全')
    const sourcePayload = {...common, request_key: require('node:crypto').randomUUID(), task_number: `${numberBase}-2`, delivery_batch_line_id: sourceOrder.data.delivery_batches[0].lines[0].id, quantity: 100}
    await call(factory, 'post', '/api/v1/production-tasks/create-from-sales-order/', 400, {...sourcePayload, quantity:101})
    await call(factory, 'post', '/api/v1/production-tasks/create-from-sales-order/', 400, {...sourcePayload, product_color_id:null})
    const sourceCreated = await call(factory, 'post', '/api/v1/production-tasks/create-from-sales-order/', 201, sourcePayload)
    const retried = await call(factory, 'post', '/api/v1/production-tasks/create-from-sales-order/', 201, sourcePayload)
    assert.equal(retried.data.id, sourceCreated.data.id)
    await call(factory, 'post', '/api/v1/production-tasks/create-from-sales-order/', 409, {...sourcePayload, tax_rate:3})
    await call(factory, 'post', '/api/v1/production-tasks/create-from-sales-order/', 409, {...sourcePayload, product_color_id:null})
    checks.push('名义量不得使用误差扩单、禁止来源颜色更换、同key重试与异内容冲突')
    const source = await call(factory, 'post', `/api/v1/production-tasks/${sourceCreated.data.id}/submit/`, 200, {}, sourceCreated.etag)
    assert.equal(source.data.salesperson.id, seed.salesperson_id)
    assert.equal(source.data.followers[0].id, seed.production_follower_id); assert.equal(source.data.tax_rate, 7)
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
    const unlinkedPayload = await manualPayload(`${numberBase}-4`)
    Object.assign(unlinkedPayload.products[0], {product_id: null, product_category_id:seed.category_id, product_color_id:null,color_code:'',customer_product_name: '隔离未关联产品', customer_specification: '未关联规格', material: '钢', customer_color: '隔离文本浅灰'})
    const unlinked = await call(context, 'post', '/api/v1/production-tasks/', 201, unlinkedPayload)
    assert.equal(unlinked.data.products[0].product_id, null)
    assert.equal(unlinked.data.products[0].product_number, '')
    assert.equal(unlinked.data.products[0].item_number, '')
    const unlinkedPatched = await call(context, 'patch', `/api/v1/production-tasks/${unlinked.data.id}/`, 200, {delivery_date: futureDate(7)}, unlinked.etag)
    assert.equal(unlinkedPatched.data.products[0].product_id, null)
    assert.equal(unlinkedPatched.data.products[0].product_category_id,seed.category_id)
    const quantityPatched=await call(context,'patch',`/api/v1/production-tasks/${unlinked.data.id}/`,200,
      {products:[{...unlinkedPayload.products[0],id:unlinked.data.products[0].id,quantity:3}]},unlinkedPatched.etag)
    assert.equal(quantityPatched.data.products[0].quantity,3)
    assert.equal(quantityPatched.data.products[0].customer_color,'隔离文本浅灰')
    checks.push('未关联产品类别真实保存，文本颜色行PATCH修改数量成功')
    checks.push('手动无销售未关联产品创建及PATCH，不伪造产品ID/货号')
    const usdOrder = await createSalesOrder(8, 'USD')
    const usdPreview = (await call(factory, 'get', `/api/v1/production-tasks/sales-order-sources/?sales_order_id=${usdOrder.data.id}`, 200)).data
    assert.equal(usdPreview.production_exchange_rate.record_id, seed.rate_id)
    assert.equal(usdPreview.production_exchange_rate.rate, seed.rate)
    const usdPayload = {...common, task_number: `${numberBase}-8`, delivery_batch_line_id: usdOrder.data.delivery_batches[0].lines[0].id, quantity: 8}
    await call(factory, 'post', '/api/v1/production-tasks/create-from-sales-order/', [400,409], usdPayload)
    const usdTask = await call(factory, 'post', '/api/v1/production-tasks/create-from-sales-order/', 201, {...usdPayload, exchange_rate_record_id: seed.rate_id})
    assert.equal(usdTask.data.products[0].exchange_rate, seed.rate)
    assert.equal(usdTask.data.products[0].exchange_rate_record_id, seed.rate_id)
    assert.equal(Number(usdTask.data.products[0].unit_price), 20)
    assert.equal(Number(usdTask.data.products[0].unit_price_base), 142.4691)
    assert.equal(Number(usdTask.data.products[0].line_amount_base), 1139.7531)
    checks.push('USD真实汇率记录/8位冻结/原币价格/人民币4位换算')
    const staleOrder = await createSalesOrder(11, 'USD')
    const rateDetail = await call(context, 'get', `/api/v1/reference-data/exchange-rates/${seed.rate_id}/`, 200)
    await call(context, 'post', `/api/v1/reference-data/exchange-rates/${seed.rate_id}/correct/`, 201,
      {rate:'7.23456789',effective_date:today,source_name:'隔离人工更正',source_version:'LB-v2'}, rateDetail.etag)
    await call(factory, 'post', '/api/v1/production-tasks/create-from-sales-order/', [400,409],
      {...common, task_number:`${numberBase}-10`, delivery_batch_line_id:staleOrder.data.delivery_batches[0].lines[0].id,quantity:11,exchange_rate_record_id:seed.rate_id})
    const frozen = (await call(factory, 'get', `/api/v1/production-tasks/${usdTask.data.id}/`, 200)).data.products[0]
    assert.equal(frozen.exchange_rate,seed.rate)
    assert.equal(frozen.exchange_rate_snapshot.source_version,'LB-20261015-v1')
    assert.equal(Number(frozen.line_amount_base),1139.7531)
    checks.push('基础汇率真实更正后旧预览拒绝，已保存8位生产价格快照不重算')
    const missingOrder = await createSalesOrder(9, 'EUR')
    const missing = (await call(factory, 'get', `/api/v1/production-tasks/sales-order-sources/?sales_order_id=${missingOrder.data.id}`, 200)).data
    assert.equal(missing.production_exchange_rate, null)
    assert.ok(missing.production_exchange_rate_error)
    await call(factory, 'post', '/api/v1/production-tasks/create-from-sales-order/', 400, {...common, task_number: `${numberBase}-9`, delivery_batch_line_id: missingOrder.data.delivery_batches[0].lines[0].id, quantity: 9})
    checks.push('EUR缺汇率阻止创建，不能默认1')
    const pendingOrder = await createSalesOrder(10)
    const pendingCreated = await call(context, 'post', '/api/v1/production-tasks/create-from-sales-order/', 201, {
      ...common, task_number: `${numberBase}-3`, delivery_batch_line_id: pendingOrder.data.delivery_batches[0].lines[0].id, quantity: 10,
    })
    const pending = await call(context, 'post', `/api/v1/production-tasks/${pendingCreated.data.id}/submit/`, 200, {}, pendingCreated.etag)
    for (const suffix of [5, 6, 7]) {
      await call(context, 'post', '/api/v1/production-tasks/', 201, await manualPayload(`${numberBase}-${suffix}`))
    }
    const recentOptions = (await call(context, 'get', '/api/v1/production-tasks/options/', 200)).data
    assert.deepEqual(recentOptions.recent_task_numbers, [3, 5, 6, 7, 8].map(suffix => `${numberBase}-${suffix}`).sort())
    checks.push('最近五笔编号来自刚刚真实保存记录并按编号排序')
    await login(restricted, seed.restricted_username, password)
    await call(restricted, 'post', '/api/v1/production-tasks/', 403, payload)
    checks.push('无权限员工被后端拒绝创建')
    const pageOrder = await createSalesOrder(30)
    await fs.writeFile(path.join(reportDir, 'api-state.json'), JSON.stringify({
      numberBase, manualTaskId: manual.data.id, sourceTaskId: source.data.id, sourceOrderId: sourceOrder.data.id,
      pageOrderId: pageOrder.data.id, pageOrderNumber: pageOrder.data.order_number, sourceOrderNumber: sourceOrder.data.order_number, pendingTaskId: pending.data.id, pendingOrderId: pendingOrder.data.id, pendingOrderNumber: pendingOrder.data.order_number, missingOrderId: missingOrder.data.id, missingOrderNumber: missingOrder.data.order_number, usdTaskId: usdTask.data.id, seed,
    }, null, 2))
  } finally {
    await context.dispose()
    await restricted.dispose()
    await factory.dispose()
  }
}

async function pagePhase(seed, password) {
  const state = JSON.parse(await fs.readFile(path.join(reportDir, 'api-state.json'), 'utf8'))
  const browserTemp = path.resolve('.tmp/production-layout-b/browser')
  await fs.mkdir(browserTemp, {recursive:true})
  const previousTemp = process.env.TEMP, previousTmp = process.env.TMP
  process.env.TEMP = browserTemp; process.env.TMP = browserTemp
  let browser, activePage
  const pageErrors=[], browserApiCalls=[], unexpectedApi=[], networkFailures=[]
  try {
    browser = await chromium.launch({executablePath: process.env.UI_E2E_CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', headless: true})
    const context = await browser.newContext({viewport:{width:1920,height:1080}})
    await context.route('**/api/**',async route=>{
      const url=new URL(route.request().url())
      if(![apiUrl,baseUrl].includes(url.origin)) {unexpectedApi.push(url.origin+url.pathname); await route.abort('blockedbyclient');return}
      await route.continue()
    })
    await login(context.request, seed.factory_username, password)
    const page = await context.newPage(); activePage=page
    const errors = pageErrors
    page.on('pageerror', error => errors.push(error.message))
    page.on('request',request=>{const url=new URL(request.url());if(url.pathname.startsWith('/api/')) browserApiCalls.push({method:request.method(),origin:url.origin,path:url.pathname})})
    page.on('requestfailed',request=>networkFailures.push({url:request.url(),failure:request.failure()?.errorText}))
    async function choose(select, name) {
      await select.click()
      const controls = await select.getByRole('combobox').getAttribute('aria-controls')
      await page.locator(`#${controls}`).getByText(name, {exact:true}).click()
      await page.keyboard.press('Escape')
    }
    async function source() {
      await page.goto(`${baseUrl}/production-tasks/new`, {waitUntil:'networkidle'})
      await page.getByRole('heading',{name:'选择销售订单及交付来源'}).waitFor()
      assert.equal(await page.getByText(state.sourceOrderNumber,{exact:true}).count(),0)
      const row = page.locator('.source-order-table .el-table__row').filter({hasText:state.pageOrderNumber})
      const sourceButton=row.getByRole('button',{name:/^(选择|已选择)$/})
      if((await sourceButton.innerText())==='选择') await sourceButton.click()
      await page.locator('.product-table').getByText(seed.item_number,{exact:true}).waitFor()
      assert.ok((await page.locator('.source-context strong').innerText()).includes('600.00'),'订单总金额必须来自真实600元来源')
      assert.ok((await page.locator('.product-table').innerText()).includes(seed.unit_name),'单位必须解析真实名称')
      assert.ok((await page.locator('.product-table').innerText()).includes(seed.color_name),'客户颜色文本空时按真实正式颜色ID显示名称')
      await page.waitForFunction(()=>[...document.querySelectorAll('.product-table img')].some(image=>image.complete && image.naturalWidth>0),null,{timeout:5000})
      assert.ok(await page.locator('.product-table img').evaluateAll(images=>images.some(image=>image.complete && image.naturalWidth>0)),'真实来源图片须成功加载')
      assert.equal(await page.getByPlaceholder('例如 26199 或 26199-1').count(),0)
    }
    for (const viewport of [{width:1920,height:1080},{width:1440,height:900}]) {
      await page.setViewportSize(viewport)
      if(viewport.width===1440) {
        const collapse=page.getByRole('button',{name:/折叠|收起/}).first()
        if(await collapse.count()) await collapse.click()
      }
      await source()
      const dom = await page.evaluate(() => {
        const style = (el,pseudo=null) => {const s=getComputedStyle(el,pseudo); return {border:[s.borderTopWidth,s.borderRightWidth,s.borderBottomWidth,s.borderLeftWidth],borderColor:s.borderTopColor,background:s.backgroundColor,height:s.height,padding:s.padding,overflowX:s.overflowX,overflowY:s.overflowY,display:s.display,fontSize:s.fontSize,lineHeight:s.lineHeight,fontWeight:s.fontWeight}}
        const table=document.querySelector('.product-table'), frame=table.closest('.table-frame')
        const th=table.querySelector('th'), td=table.querySelector('td'), body=table.querySelector('.el-table__body-wrapper')
        return {viewport:[innerWidth,innerHeight],pageWidth:document.documentElement.scrollWidth,steps:document.querySelector('.steps').getBoundingClientRect().width,
          card:style(document.querySelector('.creation-card')),frame:style(frame),table:style(table),before:style(table.querySelector('.el-table__inner-wrapper'),'::before'),after:style(table,'::after'),th:style(th),cell:style(th.querySelector('.cell')),td:style(td),tdCell:style(td.querySelector('.cell')),lastHeader:style(table.querySelector('thead th:last-child')),sourceOrderFirstRow:style(document.querySelector('.source-order-table tbody tr:first-child td')),control:style(document.querySelector('.search-row .el-input__wrapper')),lastRow:style(table.querySelector('tbody tr:last-child td:last-child')),body:{client:body.clientWidth,scroll:body.scrollWidth}, row:table.querySelector('tbody tr').getBoundingClientRect().height}
      })
      assert.equal(dom.steps,160)
      assert.ok(dom.pageWidth<=viewport.width+1,'宽表只能在内部滚动，不得撑宽页面')
      assert.deepEqual(dom.frame.border,['1px','1px','1px','1px'])
      assert.equal(dom.before.display,'none','组件伪元素不得叠加底边')
      assert.equal(dom.th.height,'44px')
      assert.equal(dom.cell.padding.split(' ')[1],'16px')
      assert.equal(dom.row,34,'普通产品行34px')
      assert.equal(dom.td.padding,'0px','普通行不得被全局padding覆盖')
      assert.equal(dom.tdCell.fontSize,'13px')
      assert.equal(dom.tdCell.lineHeight,'22px')
      assert.equal(dom.control.height,'32px')
      assert.equal(dom.frame.borderColor,'rgb(221, 214, 201)')
      assert.equal(dom.th.background,'rgb(240, 234, 223)')
      assert.equal(dom.td.border[1],'0px')
      assert.equal(dom.td.border[3],'0px')
      assert.equal(dom.lastHeader.border[1],'0px')
      assert.equal(dom.sourceOrderFirstRow.border[2],'1px','多行表保留内部横线')
      assert.equal(dom.lastRow.border[2],'0px')
      await page.locator('.product-table .el-table__row').first().hover()
      await page.waitForFunction(()=>getComputedStyle(document.querySelector('.product-table tbody td')).backgroundColor==='rgb(255, 246, 234)',null,{timeout:2000})
      const hoverColor=await page.locator('.product-table tbody td').first().evaluate(el=>getComputedStyle(el).backgroundColor)
      assert.equal(hoverColor,'rgb(255, 246, 234)')
      dom.hoverColor=hoverColor
      await page.locator('.page-heading h1').hover()
      await fs.writeFile(path.join(reportDir,`dom-${viewport.width}.json`),JSON.stringify(dom,null,2))
      await page.screenshot({path:path.join(reportDir,`source-${viewport.width}.png`),fullPage:true})
      await page.getByRole('button',{name:'选择并继续',exact:true}).click()
      await page.getByRole('heading',{name:'核对产品及本次数量价格'}).waitFor()
      assert.equal(await page.locator('.product-table .el-select').count(),0,'来源颜色固定')
      await page.locator('.product-table .el-input-number input').fill('1')
      await page.locator('.product-table .el-input-number input').press('Tab')
      const pricingDom=await page.locator('.product-table tbody tr').first().evaluate(row=>({height:row.getBoundingClientRect().height,cellHeight:getComputedStyle(row.querySelector('td')).height,padding:getComputedStyle(row.querySelector('td')).padding}))
      assert.equal(pricingDom.height,52,'双币行52px')
      assert.equal(pricingDom.padding,'0px')
      await fs.writeFile(path.join(reportDir,`pricing-dom-${viewport.width}.json`),JSON.stringify(pricingDom,null,2))
      await page.screenshot({path:path.join(reportDir,`pricing-${viewport.width}.png`),fullPage:true})
      await page.getByRole('button',{name:'下一步',exact:true}).click()
      await page.getByRole('heading',{name:'生产安排',exact:true}).waitFor()
      const grid=page.locator('.plan-grid')
      await grid.getByPlaceholder('例如 26199 或 26199-1').fill(`${Date.now()}-${viewport.width}`)
      await page.getByText('最近五个真实编号',{exact:true}).waitFor()
      assert.equal(await page.locator('.recent-numbers li').count(),5)
      await page.keyboard.press('Escape')
      await choose(grid.locator('label').filter({has:page.locator('span',{hasText:'生产跟单员 *'})}).locator('.el-select'),'隔离生产跟单李四')
      assert.equal(await grid.locator('label').filter({has:page.locator('span',{hasText:'业务员 *'})}).locator('input').isDisabled(),true)
      await choose(grid.locator('label').filter({has:page.locator('span',{hasText:'是否含税 *'})}).locator('.el-select'),'含税')
      await choose(grid.locator('label').filter({has:page.locator('span',{hasText:'税率 *'})}).locator('.el-select'),'7%')
      await page.screenshot({path:path.join(reportDir,`plan-${viewport.width}.png`),fullPage:true})
      checks.push(`${viewport.width}×${viewport.height} B左步骤/单层边框/表头44/单元格16/内部滚动/四步字段`)
    }
    await page.getByRole('button',{name:'下一步',exact:true}).click()
    await page.getByRole('heading',{name:'核对并提交'}).waitFor()
    const saveResponse = page.waitForResponse(response => response.url().endsWith('/production-tasks/create-from-sales-order/') && response.request().method()==='POST')
    await page.getByRole('button',{name:'保存并提交 PMC',exact:true}).click()
    const saved = await saveResponse
    assert.equal(saved.status(),201,await responseSummary(saved))
    const savedTask = (await saved.json()).data
    assert.equal(savedTask.tax_rate,7)
    assert.equal(savedTask.followers[0].id,seed.production_follower_id)
    await page.getByRole('button',{name:'PMC 确认通过',exact:true}).waitFor()
    await page.getByRole('button',{name:'PMC 确认通过',exact:true}).click()
    const pmcField = text => page.locator('.pmc-form label').filter({has:page.locator('span',{hasText:text})})
    await pmcField(/^跟单员/).getByText('隔离生产跟单李四',{exact:true}).waitFor()
    assert.ok((await pmcField(/^跟单员/).innerText()).includes('隔离生产跟单李四'))
    assert.ok((await pmcField(/^税率/).innerText()).includes('7%'))
    for(const [label,value] of [[/^计划开始日期/,today],[/^计划完工日期/,futureDate(3)]]) {
      const input=pmcField(label).locator('input'); await input.fill(value); await input.press('Tab')
    }
    await page.screenshot({path:path.join(reportDir,'pmc-prefilled.png'),fullPage:true})
    const pmcResponse=page.waitForResponse(response=>response.url().includes('/pmc-decision/') && response.request().method()==='POST')
    await page.getByRole('button',{name:'确认通过',exact:true}).click()
    const confirmed=await pmcResponse
    assert.equal(confirmed.status(),200,await responseSummary(confirmed))
    const confirmedTask=(await confirmed.json()).data
    assert.equal(confirmedTask.tax_rate,7)
    assert.equal(confirmedTask.followers[0].id,seed.production_follower_id)
    checks.push('真实浏览器四步保存提交，PMC预填并沿用独立跟单员与税率')
    await page.goto(`${baseUrl}/production-tasks/new`,{waitUntil:'networkidle'})
    await page.getByPlaceholder('搜索销售订单号').fill('LB-EMPTY-NONEXISTENT')
    await page.getByRole('button',{name:'查询',exact:true}).click()
    await page.getByText('没有可分配的销售订单',{exact:true}).waitFor()
    await page.screenshot({path:path.join(reportDir,'source-empty.png'),fullPage:true})
    await page.getByPlaceholder('搜索销售订单号').fill(state.missingOrderNumber)
    await page.getByRole('button',{name:'查询',exact:true}).click()
    await page.locator('.source-order-table .el-table__row').filter({hasText:state.missingOrderNumber}).getByRole('button',{name:'选择',exact:true}).click()
    await page.getByRole('button',{name:'选择并继续',exact:true}).click()
    await page.getByRole('heading',{name:'核对产品及本次数量价格'}).waitFor()
    await page.getByRole('button',{name:'下一步',exact:true}).click()
    assert.equal(await page.getByRole('heading',{name:'生产安排',exact:true}).count(),0)
    await page.screenshot({path:path.join(reportDir,'missing-rate-blocked.png'),fullPage:true})
    checks.push('真实搜索空数据、EUR缺汇率页面错误及下一步阻断')
    await page.goto(`${baseUrl}/production-tasks/new/manual`,{waitUntil:'networkidle'})
    await page.getByRole('heading',{name:'录入本次生产产品'}).waitFor()
    assert.equal(await page.getByText('客户名称',{exact:true}).count(),0)
    await page.getByRole('tab',{name:'手工录入定制产品'}).click()
    await choose(page.locator('.product-entry label').filter({has:page.getByRole('combobox',{name:'类别',exact:true})}).locator('.el-select'),seed.category_name)
    await page.getByRole('textbox',{name:'品名',exact:true}).fill('浏览器未关联定制产品')
    await page.getByRole('combobox',{name:'规格',exact:true}).fill('浏览器规格')
    await page.getByRole('combobox',{name:'规格',exact:true}).press('Enter')
    await choose(page.locator('.product-entry label').filter({has:page.getByRole('combobox',{name:'单位',exact:true})}).locator('.el-select'),seed.unit_name)
    await page.getByRole('combobox',{name:'颜色',exact:true}).fill('浏览器文本颜色')
    await page.getByRole('combobox',{name:'颜色',exact:true}).press('Enter')
    await page.getByRole('textbox',{name:'数量',exact:true}).fill('2')
    await page.getByRole('textbox',{name:'订单单价',exact:true}).fill('9.8765')
    await page.getByRole('button',{name:'添加产品',exact:true}).click()
    await page.getByText('浏览器未关联定制产品',{exact:true}).first().waitFor()
    await page.screenshot({path:path.join(reportDir,'manual-unlinked.png'),fullPage:true})
    checks.push('手动内嵌销售同源录入，真实未关联产品名称/规格/单位/数量/人民币价格')

    await page.getByRole('tab',{name:'选择已有产品',exact:true}).click()
    const entrySelect=name=>page.locator('.product-entry label').filter({has:page.getByRole('combobox',{name,exact:true})}).locator('.el-select')
    await choose(entrySelect('类别'),seed.category_name)
    await choose(entrySelect('品名'),seed.product_name)
    await choose(entrySelect('规格'),seed.specification)
    await page.getByRole('radio',{name:`选择 ${seed.product_number}`,exact:true}).check()
    await choose(entrySelect('颜色'),seed.color_name)
    await page.getByRole('textbox',{name:'数量',exact:true}).fill('3')
    await page.getByRole('textbox',{name:'订单单价',exact:true}).fill('12.3456')
    await page.getByLabel('上传产品图片',{exact:true}).setInputFiles({name:'browser-manual.png',mimeType:'image/png',buffer:sourcePng})
    await page.getByRole('button',{name:'添加产品',exact:true}).click()
    const manualRow=page.locator('.el-table__row').filter({hasText:seed.product_name})
    await manualRow.locator('img').waitFor()
    assert.ok((await manualRow.locator('img').getAttribute('src')).startsWith('blob:'))
    await manualRow.getByRole('button',{name:'编辑',exact:true}).click()
    await page.locator('.product-entry img').waitFor()
    await page.getByRole('button',{name:'保存产品信息',exact:true}).click()
    await manualRow.locator('img').waitFor()
    await page.screenshot({path:path.join(reportDir,'manual-linked-image-preview.png'),fullPage:true})
    await page.getByRole('button',{name:'选择并继续',exact:true}).click()
    await page.getByRole('button',{name:'下一步',exact:true}).click()
    const manualGrid=page.locator('.plan-grid')
    await manualGrid.getByPlaceholder('例如 26199 或 26199-1').fill(`${Date.now()}-99`)
    await choose(manualGrid.locator('label').filter({has:page.locator('span',{hasText:'生产跟单员 *'})}).locator('.el-select'),'隔离生产跟单李四')
    await choose(manualGrid.locator('label').filter({has:page.locator('span',{hasText:'业务员 *'})}).locator('.el-select'),'隔离验收业务员')
    for(const [label,value] of [[/^下单日期/,today],[/^交期/,futureDate(6)]]) {
      const input=manualGrid.locator('label').filter({has:page.locator('span',{hasText:label})}).locator('input'); await input.fill(value); await input.press('Tab')
    }
    for(const input of await page.getByPlaceholder('明细类型（必填）').all()) if(!(await input.inputValue())) await input.fill('隔离验收明细')
    await page.getByRole('button',{name:'下一步',exact:true}).click()
    const manualSaved=page.waitForResponse(response=>response.url().endsWith('/production-tasks/') && response.request().method()==='POST')
    await page.getByRole('button',{name:'保存草稿',exact:true}).click()
    const manualResponse=await manualSaved
    assert.equal(manualResponse.status(),201,await responseSummary(manualResponse))
    const manualTask=(await manualResponse.json()).data
    const linkedProduct=manualTask.products.find(product=>product.product_id===seed.product_id)
    const unlinkedProduct=manualTask.products.find(product=>product.product_id===null)
    assert.ok(linkedProduct)
    assert.equal(unlinkedProduct.product_category_id,seed.category_id)
    assert.equal(unlinkedProduct.customer_color,'浏览器文本颜色')
    const browserImage=linkedProduct.images.find(image=>image.name==='browser-manual.png')
    assert.ok(browserImage,'手动保存不能丢失主图')
    const storedImage=await context.request.get(`${apiUrl}/api/v1/production-tasks/${manualTask.id}/business-files/${browserImage.id}/`)
    assert.equal(storedImage.status(),200)
    assert.deepEqual(await storedImage.body(),sourcePng)
    await page.getByRole('heading',{name:'生产任务单详情',exact:true}).waitFor()
    await page.getByText(manualTask.task_number,{exact:true}).first().waitFor()
    const detailImage=page.locator(`.products-card .product-images img[src*="${browserImage.id}"]`)
    await detailImage.waitFor()
    await detailImage.evaluate(image=>image.decode())
    assert.ok(await detailImage.evaluate(image=>image.complete && image.naturalWidth>0),'详情真实主图必须加载成功')
    await detailImage.click()
    await page.locator('.product-image-preview-window img').waitFor()
    await page.locator('.product-image-preview-window').getByRole('contentinfo').getByRole('button',{name:'关闭',exact:true}).click()
    await page.screenshot({path:path.join(reportDir,'manual-saved-image-detail.png'),fullPage:true})
    checks.push('生产-only真实产品选择/单位字典成功，上传主图→已录入→重编辑→保存→详情及文件字节一致')
    await page.goto(`${baseUrl}/production-tasks/${manualTask.id}/edit`,{waitUntil:'networkidle'})
    await page.getByRole('heading',{name:'编辑生产任务单',exact:true}).waitFor()
    const textColorGroup=page.locator('.products-section tbody tr').filter({hasText:'浏览器未关联定制产品'})
    await textColorGroup.locator('input').fill('5')
    const editedResponse=page.waitForResponse(response=>response.url().endsWith(`/production-tasks/${manualTask.id}/`) && response.request().method()==='PATCH')
    await page.getByRole('button',{name:'保存修改',exact:true}).click()
    await page.getByRole('button',{name:'确认保存',exact:true}).click()
    const edited=await editedResponse
    assert.equal(edited.status(),200,await responseSummary(edited))
    const editedTask=(await edited.json()).data
    const editedUnlinked=editedTask.products.find(product=>product.id===unlinkedProduct.id)
    assert.equal(editedUnlinked.quantity,5)
    assert.equal(editedUnlinked.customer_color,'浏览器文本颜色')
    assert.equal(editedUnlinked.product_category_id,seed.category_id)
    assert.equal(editedTask.products.find(product=>product.id===linkedProduct.id).images[0].id,browserImage.id)
    checks.push('未关联产品类别与文本颜色保存，真实编辑页修改数量5并保留另一真实产品主图')
    assert.deepEqual(unexpectedApi,[],'浏览器API必须只访问本任务18195/18196')
    assert.deepEqual(errors,[])
    await context.close()
  } catch(error) {
    if(activePage) {
      await activePage.screenshot({path:path.join(reportDir,'failure.png'),fullPage:true}).catch(()=>{})
      await fs.writeFile(path.join(reportDir,'failure-state.json'),JSON.stringify({url:activePage.url(),text:(await activePage.locator('body').innerText()).slice(0,12000),errors:pageErrors,unexpectedApi,networkFailures},null,2))
    }
    throw error
  } finally {
    await fs.writeFile(path.join(reportDir,'browser-api-calls.json'),JSON.stringify({calls:browserApiCalls,unexpectedApi,networkFailures},null,2))
    await browser?.close()
    if(previousTemp===undefined) delete process.env.TEMP; else process.env.TEMP=previousTemp
    if(previousTmp===undefined) delete process.env.TMP; else process.env.TMP=previousTmp
    await fs.rm(browserTemp,{recursive:true,force:true})
  }
}
async function main() {
  assert.ok(['api', 'pages'].includes(phase), '阶段只允许 api 或 pages')
  const password = process.env.LAYOUT_B_QA_PASSWORD
  assert.ok(password, '必须显式提供隔离账号密码')
  const seed = JSON.parse(await fs.readFile(seedPath, 'utf8'))
  assert.equal(seed.database, 'haiqu_layout_b')
  await fs.mkdir(reportDir, { recursive: true })
  let failure
  try { await (phase === 'api' ? apiPhase(seed, password) : pagePhase(seed, password)) } catch (error) { failure = error }
  await fs.writeFile(path.join(reportDir, `${phase}-report.json`), JSON.stringify({ phase, status: failure ? 'FAIL' : 'PASS', checks, calls, error: failure?.message }, null, 2))
  console.log(JSON.stringify({ phase, status: failure ? 'FAIL' : 'PASS', checks, callCount: calls.length }))
  if (failure) throw failure
}
main().catch(error => { console.error(error.message); process.exitCode = 1 })
































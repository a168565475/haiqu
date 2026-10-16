// 显式运行；仅允许本任务 18205/18206 隔离服务，禁止指向正式开发服务。
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')
const { chromium, request } = require('playwright-core')

const apiUrl = 'http://127.0.0.1:18205'
const baseUrl = 'http://127.0.0.1:18206'
const reportDir = path.resolve('output/playwright/sales-cny-followups-20261015')
const seedPath = path.resolve('.tmp/sales-cny-followups/seed.json')
const phase = process.argv[2] || 'api'
const resumeManual = process.argv.includes('--resume-manual')
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
  const admin = await request.newContext(), factory = await request.newContext(), restricted = await request.newContext()
  try {
    await login(admin, seed.username, password)
    await login(factory, seed.factory_username, password)
    await login(restricted, seed.restricted_username, password)
    const numberBase = `HT${Date.now()}`
    const preview = (await call(admin, 'get', '/api/v1/sales-orders/exchange-rate-preview/?currency_code=USD', 200)).data
    assert.equal(preview.exchange_rate_record_id, seed.rate_id)
    assert.equal(Number(preview.exchange_rate), Number(seed.rate))
    await call(restricted, 'get', '/api/v1/sales-orders/exchange-rate-preview/?currency_code=USD', 403)
    await call(factory, 'get', '/api/v1/sales-orders/exchange-rate-preview/?currency_code=USD', 403)
    await call(admin, 'get', '/api/v1/sales-orders/exchange-rate-preview/?currency_code=EUR', 400)
    checks.push('真实系统汇率预览、销售权限与缺失汇率校验')
    function payload(currency = 'USD', record = seed.rate_id, quantity = 10) {
      return {
        source_type: 'DIRECT', customer_account_id: seed.customer_id, transaction_entity_id: seed.entity_id,
        buyer_address_id: seed.address_id, salesperson_id: seed.salesperson_id, merchandiser_id: seed.sales_follower_id,
        customer_po_number: `SC-${Date.now()}`, contract_number: `SC-${Date.now()}`, order_date: today,
        direct_order_reason: '独占隔离真实API验收', currency_code: currency, exchange_rate: '99.00000000', exchange_rate_record_id: record,
        payment_terms: '隔离条款', deposit_required: false, includes_tax: true, tax_basis: '含税',
        order_tolerance_percent: '0', preproduction_sample_required: false,
        seller_snapshot: {template_config: {seller_company_name: 'ISOLATED SELLER'}},
        confirmation_method: 'CUSTOMER_PO', customer_confirmer: '隔离联系人', customer_confirmed_at: new Date().toISOString(), confirmation_summary: '确认产品数量价格交期', evidence_file_ids: [],
        lines: [{client_key: 'line-1', product_id: seed.product_id, product_color_id: seed.color_id,
          color_code: seed.color_code, customer_color_snapshot: seed.color_name, material: '尼龙', quantity: String(quantity), unit_price: '20.0000',
          quality_requirements: '隔离品质要求', packaging_requirements: '隔离纸箱', shipping_mark_requirements: '隔离唛头'}],
        delivery_batches: [{planned_delivery_date: futureDate(5), lines: [{sales_order_line_client_key: 'line-1', quantity: String(quantity)}]}],
      }
    }
    async function createOrder(data, confirm = true) {
      const created = await call(admin, 'post', '/api/v1/sales-orders/', 201, data)
      if (!confirm) return created
      const evidence = await call(admin, 'post', `/api/v1/sales-orders/${created.data.id}/evidence/`, 201, undefined, created.etag,
        {multipart: {file: {name: 'cny-acceptance.pdf', mimeType: 'application/pdf', buffer: pdfEvidence()}}})
      const image = await call(admin, 'post', `/api/v1/sales-orders/${created.data.id}/lines/${created.data.lines[0].id}/product-image/`, 201, undefined, evidence.etag,
        {multipart: {file: {name: 'cny-product.png', mimeType: 'image/png', buffer: sourcePng}}})
      return call(admin, 'post', `/api/v1/sales-orders/${created.data.id}/confirm/`, 200, {}, image.etag)
    }
    const noCsrf = await admin.post(`${apiUrl}/api/v1/sales-orders/`, {data: payload()})
    assert.equal(noCsrf.status(), 403)
    const source = await createOrder(payload())
    const unitCny = 142.4691, totalCny = 1424.691
    assert.equal(Number(source.data.exchange_rate), 7.12345678)
    assert.equal(source.data.exchange_rate_record_id, seed.rate_id)
    assert.equal(Number(source.data.lines[0].unit_price_cny), unitCny)
    assert.equal(Number(source.data.lines[0].line_total_cny), totalCny)
    assert.equal(Number(source.data.total_amount_cny), totalCny)
    checks.push('销售创建按系统8位汇率冻结人民币，忽略手填99，先单价四位再乘数量')
    const draft = await createOrder(payload(), false)
    const rateDetail = await call(admin, 'get', `/api/v1/reference-data/exchange-rates/${seed.rate_id}/`, 200)
    const newRate = await call(admin, 'post', `/api/v1/reference-data/exchange-rates/${seed.rate_id}/correct/`, 201,
      {rate: '7.23456789', effective_date: today, source_name: '隔离人工更正', source_version: 'SC-v2'}, rateDetail.etag)
    await call(admin, 'post', '/api/v1/sales-orders/', [400,409], payload())
    const savedDraft = await call(admin, 'patch', `/api/v1/sales-orders/${draft.data.id}/`, 200, payload('USD', seed.rate_id, 12), draft.etag)
    assert.equal(Number(savedDraft.data.exchange_rate), 7.12345678)
    assert.equal(Number(savedDraft.data.total_amount_cny), 1709.6292)
    await call(admin, 'patch', `/api/v1/sales-orders/${draft.data.id}/`, 412, payload(), draft.etag)
    const sourcePreview = (await call(factory, 'get', `/api/v1/production-tasks/sales-order-sources/?sales_order_id=${source.data.id}`, 200)).data
    assert.equal(Number(sourcePreview.total_amount_cny), totalCny)
    assert.equal(Number(sourcePreview.lines[0].unit_price_cny), unitCny)
    const common = {follower_ids: [seed.production_follower_id], delivery_date: futureDate(5), includes_tax: true, tax_rate: 3,
      order_tolerance_percent: '0', is_repeat_order: false, delivery_method: 'SINGLE'}
    const prodPayload = {...common, task_number: `${numberBase}-1`, delivery_batch_line_id: source.data.delivery_batches[0].lines[0].id, quantity: 2}
    const created = await call(factory, 'post', '/api/v1/production-tasks/create-from-sales-order/', 201, prodPayload)
    const product = created.data.products[0]
    assert.equal(product.currency_code, 'CNY')
    assert.equal(Number(product.exchange_rate), 1)
    assert.equal(Number(product.unit_price), unitCny)
    assert.equal(Number(product.total_amount), 284.9382)
    checks.push('系统汇率更正后旧草稿/销售快照不重算；生产使用销售人民币价格，部分生产金额一致；旧ETag拒绝')
    const complete = await createOrder(payload('CNY', null, 1))
    await call(factory, 'post', '/api/v1/production-tasks/create-from-sales-order/', 201,
      {...common, task_number: `${numberBase}-2`, delivery_batch_line_id: complete.data.delivery_batches[0].lines[0].id, quantity: 1})
    const pageOrder = await createOrder(payload('USD', newRate.data.id, 20))
    const otherOrder = await createOrder(payload('CNY', null, 4))
    const legacyOrder = await createOrder(payload('USD', newRate.data.id, 3))
    await call(admin, 'post', '/api/v1/sales-orders/', 400, payload('EUR', null))
    const list = (await call(factory, 'get', '/api/v1/production-tasks/sales-order-sources/', 200)).data
    const items = list.results || list.items || list
    assert.ok(items.find(item => item.id === source.data.id).product_names.includes(seed.product_name))
    assert.ok(!items.some(item => item.id === complete.data.id))
    await fs.writeFile(path.join(reportDir, 'api-state.json'), JSON.stringify({numberBase, sourceOrderId: source.data.id,
      sourceOrderNumber: source.data.order_number, sourceTaskId: created.data.id, sourceTaskNumber: created.data.task_number,
      pageOrderId: pageOrder.data.id, pageOrderNumber: pageOrder.data.order_number, pageOrderLineId: pageOrder.data.lines[0].id,
      pageBatchId: pageOrder.data.delivery_batches[0].id, otherOrderId: otherOrder.data.id, otherOrderNumber: otherOrder.data.order_number,
      completeOrderId: complete.data.id, legacyOrderId: legacyOrder.data.id, legacyOrderNumber: legacyOrder.data.order_number,
      draftOrderId: draft.data.id, currentRateId: newRate.data.id, seed}, null, 2))
    checks.push('来源列表真实产品名；名义量全分配订单隐藏；缺汇率销售不允许保存')
  } finally { await admin.dispose(); await factory.dispose(); await restricted.dispose() }
}

async function pagePhase(seed, password) {
  const state = JSON.parse(await fs.readFile(path.join(reportDir, 'api-state.json'), 'utf8'))
  const browserTemp = path.resolve('.tmp/sales-cny-followups/browser')
  assert.ok(browserTemp.startsWith(path.resolve('.tmp/sales-cny-followups') + path.sep))
  await fs.mkdir(browserTemp, {recursive:true})
  const previousTemp=process.env.TEMP, previousTmp=process.env.TMP
  process.env.TEMP=browserTemp; process.env.TMP=browserTemp
  let browser, activePage
  const errors=[], browserCalls=[], unexpectedApi=[], networkFailures=[]
  try {
    browser = await chromium.launch({executablePath:process.env.UI_E2E_CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true})
    const context=await browser.newContext({viewport:{width:1102,height:884}})
    await context.route('**/api/**', async route => {
      const url=new URL(route.request().url())
      if (![apiUrl,baseUrl].includes(url.origin)) {unexpectedApi.push(url.origin+url.pathname); await route.abort('blockedbyclient'); return}
      await route.continue()
    })
    await login(context.request,seed.username,password)
    const page=await context.newPage(); activePage=page
    page.on('pageerror',error=>errors.push(error.message))
    page.on('request',req=>{const url=new URL(req.url());if(url.pathname.startsWith('/api/')) browserCalls.push({method:req.method(),path:url.pathname,query:url.search,origin:url.origin})})
    page.on('requestfailed',req=>{if(req.failure()?.errorText!=='net::ERR_ABORTED')networkFailures.push({url:req.url(),error:req.failure()?.errorText})})
    async function onlyCny(label, requireCurrency = true) {
      const content=await page.locator('.page-container').count() ? await page.locator('.page-container').innerText() : await page.locator('main').first().innerText()
      assert.ok(!/\b(?:USD|EUR|HKD|GBP|JPY)\b|美元|欧元|原币单价|汇率/.test(content),`${label} 不得展示其他币种和换算控件`)
      if(requireCurrency) assert.ok(/CNY|人民币/.test(content),`${label} 应明确人民币`)
    }
    async function sourceRestricted() {
      const before=browserCalls.length
      await page.goto(`${baseUrl}/production-tasks/new?sales_order_id=${state.pageOrderId}&delivery_batch_id=${state.pageBatchId}`,{waitUntil:'networkidle'})
      await page.getByRole('heading',{name:'选择销售订单及交付来源'}).waitFor()
      await page.locator('.product-table tbody tr').first().waitFor()
      assert.equal(await page.locator('.source-order-table tbody tr').count(),1)
      assert.ok((await page.locator('.source-order-table').innerText()).includes(state.pageOrderNumber))
      assert.ok(!(await page.locator('.source-order-table').innerText()).includes(state.otherOrderNumber))
      assert.equal(await page.locator('.search-row').count(),0)
      assert.ok(!browserCalls.slice(before).some(call=>call.path.endsWith('/sales-order-sources/')&&!new URLSearchParams(call.query).has('sales_order_id')),'当前订单入口不得请求其他订单列表')
      await onlyCny('当前来源页')
      const headers=await page.locator('.product-table th').allTextContents()
      const specIndex=headers.findIndex(text=>text.trim()==='规格')
      assert.ok(specIndex>=0)
      assert.equal((await page.locator('.product-table tbody tr').first().locator('td').nth(specIndex).innerText()).trim(),seed.specification)
      const names=await page.locator('.source-order-table').innerText()
      assert.ok(names.includes(seed.product_name)); assert.ok(!/共\s*\d+\s*项产品/.test(names))
    }
    if(!resumeManual) {
    for(const viewport of [{width:1102,height:884},{width:1920,height:1080}]) {
      await page.setViewportSize(viewport)
      await sourceRestricted()
      const dom=await page.evaluate(()=>{
        const style=(el,pseudo=null)=>{const s=getComputedStyle(el,pseudo);return {border:[s.borderTopWidth,s.borderRightWidth,s.borderBottomWidth,s.borderLeftWidth],borderColor:s.borderTopColor,background:s.backgroundColor,height:s.height,padding:s.padding,fontSize:s.fontSize,fontWeight:s.fontWeight,lineHeight:s.lineHeight,display:s.display,overflowX:s.overflowX,overflowY:s.overflowY}}
        const table=document.querySelector('.product-table'),frame=table.closest('.table-frame')
        return {viewport:[innerWidth,innerHeight],pageWidth:document.documentElement.scrollWidth,steps:document.querySelector('.steps').getBoundingClientRect().width,
          frame:style(frame),card:style(document.querySelector('.creation-card')),before:style(table.querySelector('.el-table__inner-wrapper'),'::before'),after:style(table,'::after'),
          th:style(table.querySelector('th')),cell:style(table.querySelector('th .cell')),td:style(table.querySelector('td')),
          first:style(table.querySelector('tbody tr:first-child td:first-child')),last:style(table.querySelector('tbody tr:last-child td:last-child')),
          rowHeight:table.querySelector('tbody tr').getBoundingClientRect().height,bodyWidth:table.querySelector('.el-scrollbar__wrap').clientWidth,bodyScroll:table.querySelector('.el-scrollbar__wrap').scrollWidth}
      })
      assert.ok(dom.pageWidth<=viewport.width+1)
      assert.equal(dom.steps,160)
      assert.deepEqual(dom.frame.border,['1px','1px','1px','1px'])
      assert.equal(dom.before.display,'none')
      assert.equal(dom.th.height,'44px'); assert.equal(dom.cell.padding.split(' ')[1],'16px')
      assert.equal(dom.th.background,'rgb(240, 234, 223)'); assert.equal(dom.frame.borderColor,'rgb(221, 214, 201)')
      assert.equal(dom.first.border[3],'0px'); assert.equal(dom.last.border[1],'0px'); assert.equal(dom.last.border[2],'0px')
      await fs.writeFile(path.join(reportDir,`dom-source-${viewport.width}.json`),JSON.stringify(dom,null,2))
      await page.screenshot({path:path.join(reportDir,`source-${viewport.width}.png`),fullPage:true})
      await page.getByRole('button',{name:'选择并继续',exact:true}).click()
      await page.getByRole('heading',{name:'核对产品及本次数量价格'}).waitFor()
      await onlyCny('核对产品价格页')
      assert.equal(await page.locator('.product-table .el-select').count(),0)
      await page.screenshot({path:path.join(reportDir,`pricing-${viewport.width}.png`),fullPage:true})
      checks.push(`${viewport.width}×${viewport.height} 当前单据独占来源、纯规格、真实产品名、人民币、B布局计算样式`)
    }
    await page.locator('.product-table .el-input-number input').first().fill('1')
    await page.locator('.product-table .el-input-number input').first().press('Tab')
    await page.getByRole('button',{name:'下一步',exact:true}).click()
    await page.getByRole('heading',{name:'生产安排',exact:true}).waitFor()
    await page.getByPlaceholder('例如 26199 或 26199-1').fill(`${Date.now()}-99`)
    const follower=page.locator('.plan-grid label').filter({has:page.locator('span',{hasText:'生产跟单员 *'})}).locator('.el-select')
    await follower.click()
    const followerControls=await follower.getByRole('combobox').getAttribute('aria-controls')
    await page.locator(`#${followerControls}`).getByText('隔离生产跟单李四',{exact:true}).click();await page.keyboard.press('Escape')
    await page.screenshot({path:path.join(reportDir,'plan-cny.png'),fullPage:true})
    await page.getByRole('button',{name:'下一步',exact:true}).click()
    await page.getByRole('heading',{name:'核对并提交'}).waitFor();await onlyCny('提交核对页')
    await page.screenshot({path:path.join(reportDir,'review-cny.png'),fullPage:true})
    const saveResponse=page.waitForResponse(response=>response.url().endsWith('/production-tasks/create-from-sales-order/')&&response.request().method()==='POST')
    await page.getByRole('button',{name:'保存草稿',exact:true}).click()
    const saved=await saveResponse;assert.equal(saved.status(),201,await responseSummary(saved))
    const savedTask=(await saved.json()).data
    assert.equal(savedTask.products[0].currency_code,'CNY');assert.equal(Number(savedTask.products[0].unit_price),144.6914)
    checks.push('真实浏览器四步创建生产任务单保存人民币价格，与销售系统汇率快照一致')
    await sourceRestricted()
    await page.getByRole('button',{name:'手动创建',exact:true}).click()
    await page.getByRole('heading',{name:'录入本次生产产品'}).waitFor()
    await onlyCny('手动创建页')
    await page.getByRole('button',{name:'从销售订单创建',exact:true}).click()
    await page.getByRole('heading',{name:'选择销售订单及交付来源'}).waitFor()
    await page.locator('.source-order-table .el-table__row').filter({hasText:state.pageOrderNumber}).waitFor()
    assert.equal(await page.locator('.source-order-table tbody tr').count(),1)
    assert.ok(page.url().includes(state.pageOrderId))
    checks.push('切换手动再切回保持当前销售订单上下文，手动创建只人民币')
    } else {
      const previous=JSON.parse(await fs.readFile(path.join(reportDir,'pages-fourth-report.json'),'utf8'))
      assert.equal(previous.checks.length,4,'续跑必须有前四项真实通过证据')
      checks.push(...previous.checks)
    }
    await page.setViewportSize({width:1102,height:884})
    await page.goto(`${baseUrl}/production-tasks/new/manual`,{waitUntil:'networkidle'})
    await page.getByRole('heading',{name:'录入本次生产产品'}).waitFor()
    const scrollPositions=()=>page.evaluate(()=>[...document.querySelectorAll('*')].filter(el=>el.scrollHeight>el.clientHeight+2 && /auto|scroll/.test(getComputedStyle(el).overflowY)).map(el=>({tag:el.tagName,cls:el.className,top:el.scrollTop,height:el.clientHeight,scroll:el.scrollHeight})))
    const beforeWheel=await scrollPositions()
    await page.mouse.move(1000,700);await page.mouse.wheel(0,1800);await page.waitForTimeout(250)
    const afterWheel=await scrollPositions()
    assert.ok(afterWheel.some((el,index)=>el.top>(beforeWheel[index]?.top||0)),'手动第一页真实滚轮必须移动页面')
    const mainScroll=await page.locator('main').first().evaluate(el=>({overflowY:getComputedStyle(el).overflowY,top:el.scrollTop}))
    assert.ok(['auto','scroll'].includes(mainScroll.overflowY));assert.ok(mainScroll.top>0)
    const emptyContinue=page.getByRole('button',{name:'选择并继续',exact:true})
    const emptyBox=await emptyContinue.boundingBox();assert.ok(emptyBox && emptyBox.y>=0 && emptyBox.y+emptyBox.height<=884)
    if (!(await emptyContinue.isDisabled())) {
      await emptyContinue.click()
      await page.getByText('请先录入至少一条产品。',{exact:true}).waitFor()
      assert.equal(await page.getByRole('heading',{name:'录入本次生产产品'}).count(),1)
    }
    assert.equal(await page.getByRole('button',{name:'继续添加产品',exact:true}).count(),0)
    await page.screenshot({path:path.join(reportDir,'manual-empty-scroll-bottom-1102.png'),fullPage:false})
    await page.mouse.wheel(0,-2200);await page.waitForTimeout(200)
    await page.getByRole('tab',{name:'手工录入定制产品'}).click()
    async function choose(select,name) {
      await select.click();const controls=await select.getByRole('combobox').getAttribute('aria-controls')
      await page.locator(`#${controls}`).getByText(name,{exact:true}).click();await page.keyboard.press('Escape')
    }
    for(const [name,qty] of [['滚动验收产品一','2'],['滚动验收产品二','3']]) {
      await page.getByRole('tab',{name:'手工录入定制产品'}).click()
      await choose(page.locator('.product-entry label').filter({has:page.getByRole('combobox',{name:'类别',exact:true})}).locator('.el-select'),seed.category_name)
      await page.getByRole('textbox',{name:'品名',exact:true}).fill(name)
      await page.getByRole('combobox',{name:'规格',exact:true}).fill('110×60×70');await page.getByRole('combobox',{name:'规格',exact:true}).press('Enter')
      await choose(page.locator('.product-entry label').filter({has:page.getByRole('combobox',{name:'单位',exact:true})}).locator('.el-select'),seed.unit_name)
      await page.getByRole('combobox',{name:'颜色',exact:true}).fill('浅灰');await page.getByRole('combobox',{name:'颜色',exact:true}).press('Enter')
      await page.getByRole('textbox',{name:'数量',exact:true}).fill(qty)
      await page.getByRole('textbox',{name:'订单单价',exact:true}).fill('12.3456')
      await page.getByRole('button',{name:'添加产品',exact:true}).click()
      await page.getByText(name,{exact:true}).first().waitFor()
    }
    await page.mouse.move(1000,700);await page.mouse.wheel(0,2200);await page.waitForTimeout(250)
    const filledBox=await emptyContinue.boundingBox();assert.ok(filledBox && filledBox.y>=0 && filledBox.y+filledBox.height<=884)
    assert.equal(await emptyContinue.isDisabled(),false)
    await fs.writeFile(path.join(reportDir,'manual-scroll-dom-1102.json'),JSON.stringify({beforeWheel,afterWheel,mainScroll,emptyButton:emptyBox,filledButton:filledBox,filledScroll:await scrollPositions()},null,2))
    await page.screenshot({path:path.join(reportDir,'manual-filled-scroll-bottom-1102.png'),fullPage:false})
    await emptyContinue.click();await page.getByRole('heading',{name:'核对产品及本次数量价格'}).waitFor()
    assert.ok((await page.locator('.workspace .el-table').innerText()).includes('滚动验收产品二'))
    await onlyCny('手动多产品第二步')
    checks.push('1102×884手动第一页滚轮可用、空态到底按钮可达且阻止空提交，连续真实录入两产品后可点下一步')
    await page.goto(`${baseUrl}/production-tasks/new`,{waitUntil:'networkidle'})
    const listText=await page.locator('.source-order-table').innerText()
    assert.ok(!/共\s*\d+\s*项产品/.test(listText))
    assert.ok(listText.includes(state.otherOrderNumber)); await onlyCny('全部来源页')
    await page.getByPlaceholder('搜索销售订单号').fill('SC-NONEXISTENT')
    await page.getByRole('button',{name:'查询',exact:true}).click()
    await page.getByText('没有可分配的销售订单',{exact:true}).waitFor()
    await page.screenshot({path:path.join(reportDir,'source-empty.png'),fullPage:true})
    for(const orderId of [state.completeOrderId,'00000000-0000-0000-0000-000000000000']) {
      await page.goto(`${baseUrl}/production-tasks/new?sales_order_id=${orderId}`,{waitUntil:'networkidle'})
      await page.locator('.source-load-error').waitFor()
      assert.equal(await page.locator('.source-order-table .el-table__row').count(),0)
      assert.equal(await page.locator('.search-row').count(),0)
    }
    await page.screenshot({path:path.join(reportDir,'invalid-current-source.png'),fullPage:true})
    checks.push('独立入口显示所有真实产品名；空数据与当前订单无效/已全分配不回退其他订单')
    await page.goto(`${baseUrl}/sales-orders/${state.pageOrderId}`,{waitUntil:'networkidle'})
    await page.getByRole('button',{name:'创建生产任务单',exact:true}).first().click()
    await page.getByRole('heading',{name:'选择销售订单及交付来源'}).waitFor()
    await page.locator('.source-order-table .el-table__row').filter({hasText:state.pageOrderNumber}).waitFor()
    assert.ok(page.url().includes(`sales_order_id=${state.pageOrderId}`))
    assert.equal(await page.locator('.source-order-table .el-table__row').count(),1)
    checks.push('销售详情真实创建入口只显示当前销售订单')
    for(const [name,url,wait] of [
      ['list','/production-tasks','.production-list-page'],
      ['detail',`/production-tasks/${state.sourceTaskId}`,'.products-card'],
      ['edit',`/production-tasks/${state.sourceTaskId}/edit`,'.products-section'],
    ]) {
      await page.goto(baseUrl+url,{waitUntil:'networkidle'}); await page.locator(wait).waitFor(); await onlyCny(`生产${name}`,name!=='list')
      await page.screenshot({path:path.join(reportDir,`production-${name}.png`),fullPage:true})
    }
    checks.push('历史外币生产任务单列表/详情/编辑均只显示保存快照换算的人民币')
    await page.setViewportSize({width:1102,height:884})
    await page.goto(`${baseUrl}/sales-orders/${state.draftOrderId}/edit`,{waitUntil:'networkidle'})
    await page.locator('.editor-tabs').getByRole('button',{name:'订单产品',exact:true}).click()
    await page.locator('.system-exchange-rate').waitFor()
    assert.ok((await page.locator('.system-exchange-rate').innerText()).includes('7.12345678'))
    assert.equal(await page.locator('.system-exchange-rate input:not([readonly]):not([disabled])').count(),0)
    const actions=page.locator('.product-row-actions').first(); await actions.scrollIntoViewIfNeeded()
    const actionDom=await actions.evaluate(el=>{
      const rect=r=>({x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom})
      const cell=el.closest('.cell'),s=getComputedStyle(cell)
      return {cell:rect(cell.getBoundingClientRect()),container:rect(el.getBoundingClientRect()),scroll:el.scrollWidth,client:el.clientWidth,
        display:getComputedStyle(el).display,gap:getComputedStyle(el).gap,textOverflow:s.textOverflow,overflow:s.overflow,
        buttons:[...el.querySelectorAll('button')].map(b=>({text:b.textContent.trim(),rect:rect(b.getBoundingClientRect()),scroll:b.scrollWidth,client:b.clientWidth}))}
    })
    assert.equal(actionDom.display,'flex'); assert.equal(actionDom.buttons.length,2)
    assert.deepEqual(actionDom.buttons.map(b=>b.text),['编辑产品','删除'])
    assert.ok(actionDom.scroll<=actionDom.client+1)
    for(const button of actionDom.buttons) {assert.ok(button.rect.x>=actionDom.cell.x-1);assert.ok(button.rect.right<=actionDom.cell.right+1);assert.ok(button.scroll<=button.client+1)}
    await fs.writeFile(path.join(reportDir,'sales-actions-dom-1102.json'),JSON.stringify(actionDom,null,2))
    await page.screenshot({path:path.join(reportDir,'sales-actions-1102.png'),fullPage:true})
    checks.push('销售产品编辑操作列两个按钮均完整；旧草稿系统汇率只读且人民币合计冻结')
    await page.goto(`${baseUrl}/sales-orders/new`,{waitUntil:'networkidle'})
    await page.locator('.editor-tabs').getByRole('button',{name:'订单产品',exact:true}).click()
    await page.locator('.system-exchange-rate').waitFor()
    assert.ok((await page.locator('.system-exchange-rate').innerText()).includes('7.23456789'))
    await page.screenshot({path:path.join(reportDir,'new-sales-system-rate.png'),fullPage:true})
    checks.push('新建销售订单读取当前系统更正后的汇率，旧订单保持旧值')
    assert.deepEqual(unexpectedApi,[]);assert.deepEqual(errors,[]);assert.deepEqual(networkFailures,[])
    await context.close()
  } catch(error) {
    if(activePage) {
      await activePage.screenshot({path:path.join(reportDir,'failure.png'),fullPage:true})
      await fs.writeFile(path.join(reportDir,'failure-state.json'),JSON.stringify({url:activePage.url(),text:(await activePage.locator('body').innerText()).slice(0,14000),errors,unexpectedApi,networkFailures},null,2))
    }
    throw error
  } finally {
    await fs.writeFile(path.join(reportDir,'browser-api-calls.json'),JSON.stringify({calls:browserCalls,errors,unexpectedApi,networkFailures},null,2))
    await browser?.close()
    if(previousTemp===undefined) delete process.env.TEMP;else process.env.TEMP=previousTemp
    if(previousTmp===undefined) delete process.env.TMP;else process.env.TMP=previousTmp
    await fs.rm(browserTemp,{recursive:true,force:true})
  }
}

async function staleRatePhase(seed,password) {
  const state=JSON.parse(await fs.readFile(path.join(reportDir,'api-state.json'),'utf8'))
  const context=await request.newContext()
  let browser,page
  try {
    await login(context,seed.username,password)
    const rate=await call(context,'post','/api/v1/reference-data/exchange-rates/',201,{
      base_currency:seed.eur_id,quote_currency:seed.currency_id,rate:'8.00000000',effective_date:today,
      source_name:'隔离并发汇率测试',source_version:'SC-EUR-v1',
    })
    browser=await chromium.launch({executablePath:process.env.UI_E2E_CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true})
    const browserContext=await browser.newContext({viewport:{width:1102,height:884}})
    await login(browserContext.request,seed.username,password)
    page=await browserContext.newPage()
    await page.goto(`${baseUrl}/sales-orders/${state.draftOrderId}/edit`,{waitUntil:'networkidle'})
    const currencyField=page.locator('.el-form-item').filter({has:page.locator('.el-form-item__label').filter({hasText:/^币种/})}).locator('.el-select')
    await currencyField.click()
    const controls=await currencyField.getByRole('combobox').getAttribute('aria-controls')
    const preview=page.waitForResponse(response=>response.url().includes('/exchange-rate-preview/')&&response.url().includes('currency_code=EUR'))
    await page.locator(`#${controls}`).getByText('EUR',{exact:true}).click()
    assert.equal((await preview).status(),200)
    const confirmer='保留尚未保存的确认人'
    await page.getByPlaceholder('客户确认人',{exact:true}).fill(confirmer)
    const rateDetail=await call(context,'get',`/api/v1/reference-data/exchange-rates/${rate.data.id}/`,200)
    const corrected=await call(context,'post',`/api/v1/reference-data/exchange-rates/${rate.data.id}/correct/`,201,
      {rate:'8.20000000',effective_date:today,source_name:'隔离并发更正',source_version:'SC-EUR-v2'},rateDetail.etag)
    const staleSave=page.waitForResponse(response=>response.url().endsWith(`/sales-orders/${state.draftOrderId}/`)&&response.request().method()==='PATCH')
    await page.getByRole('button',{name:'保存草稿',exact:true}).click()
    const rejected=await staleSave;assert.equal(rejected.status(),409)
    const error=await rejected.json();assert.equal(error.error.code,'SALES_EXCHANGE_RATE_CHANGED')
    await page.locator('.editor-tabs').getByRole('button',{name:'订单产品',exact:true}).click()
    await page.waitForFunction(()=>document.querySelector('.system-exchange-rate')?.textContent.includes('8.20000000'))
    assert.equal(await page.getByRole('dialog',{name:/订单.*更新|并发|冲突/}).count(),0)
    await page.locator('.editor-tabs').getByRole('button',{name:'基础信息',exact:true}).click()
    assert.equal(await page.getByPlaceholder('客户确认人',{exact:true}).inputValue(),confirmer)
    await page.locator('.editor-tabs').getByRole('button',{name:'订单产品',exact:true}).click()
    assert.ok((await page.locator('.product-table').innerText()).includes(seed.product_name))
    await page.screenshot({path:path.join(reportDir,'stale-rate-refreshed-form-retained.png'),fullPage:true})
    const retry=page.waitForResponse(response=>response.url().endsWith(`/sales-orders/${state.draftOrderId}/`)&&response.request().method()==='PATCH')
    await page.getByRole('button',{name:'保存草稿',exact:true}).click()
    const saved=await retry;assert.equal(saved.status(),200,await responseSummary(saved))
    const order=(await saved.json()).data
    assert.equal(order.exchange_rate_record_id,corrected.data.id);assert.equal(Number(order.exchange_rate),8.2)
    assert.equal(order.customer_confirmer,confirmer);assert.equal(Number(order.total_amount_cny),1968)
    checks.push('真实编辑换币后系统汇率更正：409专用错误码，保留完整表单并刷新预览，第二次人工保存成功')
    await browserContext.close()
  } catch(error) {
    if(page){await page.screenshot({path:path.join(reportDir,'stale-rate-failure.png'),fullPage:true});await fs.writeFile(path.join(reportDir,'stale-rate-failure-state.json'),JSON.stringify({url:page.url(),text:(await page.locator('body').innerText()).slice(0,14000)},null,2))}
    throw error
  } finally {await browser?.close();await context.dispose()}
}

async function main() {
  assert.ok(['api','pages','stale'].includes(phase))
  const password=process.env.SALES_CNY_QA_PASSWORD; assert.ok(password)
  const seed=JSON.parse(await fs.readFile(seedPath,'utf8'));assert.equal(seed.database,'haiqu_sales_cny')
  await fs.mkdir(reportDir,{recursive:true})
  let failure
  try {await (phase==='api'?apiPhase(seed,password):phase==='pages'?pagePhase(seed,password):staleRatePhase(seed,password))}catch(error){failure=error}
  await fs.writeFile(path.join(reportDir,`${phase}-report.json`),JSON.stringify({phase,status:failure?'FAIL':'PASS',resumed_from:resumeManual?'pages-fourth-report.json':null,checks,calls,error:failure?.stack},null,2))
  console.log(JSON.stringify({phase,status:failure?'FAIL':'PASS',checks,callCount:calls.length}))
  if(failure)throw failure
}
main().catch(error=>{console.error(error.message);process.exitCode=1})


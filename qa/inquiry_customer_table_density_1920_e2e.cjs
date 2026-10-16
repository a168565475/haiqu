const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const path = require('node:path')
const { chromium } = require('playwright-core')

const baseUrl = process.env.UI_E2E_BASE_URL || 'http://localhost:8080'
const apiUrl = process.env.UI_E2E_API_URL || 'http://localhost:8000'
const chromePath = process.env.UI_E2E_CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const reportDir = path.resolve(process.env.QA_REPORT_DIR || path.join('output', 'playwright', 'inquiry-readonly'))

async function login(context, username, password) {
  const current = await context.request.get(`${apiUrl}/api/auth/me/`).catch(() => {
    throw new Error('无法读取登录会话状态，请检查 API 地址和网络。')
  })
  assert.equal(current.status(), 200, `读取登录会话状态失败（HTTP ${current.status()}）。`)
  const csrf = (await context.cookies(apiUrl)).find(cookie => cookie.name === 'csrftoken')
  assert.ok(csrf, '未获取到 CSRF Cookie')
  const response = await context.request.post(`${apiUrl}/api/auth/login/`, {
    headers: { 'X-CSRFToken': csrf.value, Referer: baseUrl },
    data: { username, password },
  }).catch(() => {
    throw new Error('登录请求未完成，请检查 API 地址和网络。')
  })
  assert.equal(response.status(), 200, `登录失败（HTTP ${response.status()}），请检查账号、密码和权限。`)
  const result = await response.json().catch(() => { throw new Error('登录接口返回了无效数据。') })
  assert.ok(result.authenticated === true, '登录接口未确认有效 Session。')
}

async function waitForIdle(page) {
  await page.waitForFunction(() => !Array.from(document.querySelectorAll('.el-loading-mask')).some((node) => {
    const style = window.getComputedStyle(node)
    const rect = node.getBoundingClientRect()
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0
  }), { timeout: 20000 })
}

async function tableMetrics(page, surfaceSelector, tableSelector) {
  await page.locator(`${tableSelector} .el-table__body tr`).first().waitFor({ timeout: 20000 })
  await waitForIdle(page)
  return page.evaluate(({ surfaceSelector, tableSelector }) => {
    const surface = document.querySelector(surfaceSelector)
    const table = document.querySelector(tableSelector)
    const header = table?.querySelector('th.el-table__cell')
    const rowCell = table?.querySelector('.el-table__body td.el-table__cell')
    const headerCell = header?.querySelector('.cell')
    const bodyCell = rowCell?.querySelector('.cell')
    const size = element => Math.round(element?.getBoundingClientRect().height || 0)
    const styles = element => element ? window.getComputedStyle(element) : null
    return {
      surfaceClasses: surface?.className || '',
      tableClasses: table?.className || '',
      headerHeight: size(header),
      rowHeight: size(rowCell),
      headerFontSize: styles(headerCell)?.fontSize || '',
      headerLineHeight: styles(headerCell)?.lineHeight || '',
      bodyFontSize: styles(bodyCell)?.fontSize || '',
      bodyLineHeight: styles(bodyCell)?.lineHeight || '',
      cellPaddingInline: styles(bodyCell)?.paddingInline || '',
      headerBackground: styles(header)?.backgroundColor || '',
      bodyBackground: styles(rowCell)?.backgroundColor || '',
      borderBottomColor: styles(rowCell)?.borderBottomColor || '',
    }
  }, { surfaceSelector, tableSelector })
}

async function main() {
  const username = process.env.E2E_USERNAME
  const password = process.env.E2E_PASSWORD
  assert.ok(username && password, '缺少 E2E_USERNAME 或 E2E_PASSWORD，未启动浏览器。')
  await fs.mkdir(reportDir, { recursive: true })
  const screenshotSuffix = `${new Date().toISOString().replace(/[:.]/g, '-')}-${process.pid}`
  const artifacts = []
  const browser = await chromium.launch({ executablePath: chromePath, headless: true })
  let context
  try {
    context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 })
    await login(context, username, password)
    await context.route('**/api/**', route => ['POST', 'PUT', 'PATCH', 'DELETE'].includes(route.request().method())
      ? route.abort('blockedbyclient') : route.continue())
    const page = await context.newPage()
    const pageErrors = []
    const apiErrors = []
    const businessWrites = []
    page.on('pageerror', error => pageErrors.push(error.message))
    page.on('console', message => { if (message.type() === 'error') pageErrors.push(message.text()) })
    page.on('response', response => {
      if (response.url().includes('/api/') && response.status() >= 400) apiErrors.push(`${response.status()} ${response.url()}`)
    })
    page.on('request', request => {
      if (request.url().includes('/api/') && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method())) {
        businessWrites.push(`${request.method()} ${request.url()}`)
      }
    })

    await page.goto(`${baseUrl}/inquiries`, { waitUntil: 'domcontentloaded' })
    const inquiry = await tableMetrics(page, '.inquiry-page .data-surface', '.inquiry-table')
    assert.match(inquiry.tableClasses, /is-compact/, '询盘表格没有默认进入紧凑模式')
    assert.equal(inquiry.rowHeight, 40, `询盘紧凑行高异常：${JSON.stringify(inquiry)}`)
    const inquiryScreenshot = path.join(reportDir, `inquiry-table-default-compact-1920x1080-${screenshotSuffix}.png`)
    await page.screenshot({ path: inquiryScreenshot, fullPage: true })
    artifacts.push(inquiryScreenshot)
    console.log(JSON.stringify({ artifact: inquiryScreenshot }))

    await page.goto(`${baseUrl}/customers`, { waitUntil: 'domcontentloaded' })
    const customer = await tableMetrics(page, '.customer-list-page .data-surface', '.customer-list-page .el-table')
    assert.match(customer.surfaceClasses, /is-dense/, '客户列表没有进入紧凑模式')
    for (const key of ['headerHeight', 'rowHeight', 'headerFontSize', 'headerLineHeight', 'bodyFontSize', 'bodyLineHeight', 'cellPaddingInline']) {
      assert.equal(customer[key], inquiry[key], `客户列表 ${key} 未与询盘超紧凑样式一致：${JSON.stringify({ inquiry, customer })}`)
    }
    const customerScreenshot = path.join(reportDir, `customer-table-compact-reference-1920x1080-${screenshotSuffix}.png`)
    await page.screenshot({ path: customerScreenshot, fullPage: true })
    artifacts.push(customerScreenshot)
    console.log(JSON.stringify({ artifact: customerScreenshot }))

    assert.deepEqual(pageErrors, [], `页面错误：${pageErrors.join(' | ')}`)
    assert.deepEqual(apiErrors, [], `接口错误：${apiErrors.join(' | ')}`)
    assert.deepEqual(businessWrites, [], `验收期间发生业务写入：${businessWrites.join(' | ')}`)
    console.log(JSON.stringify({ inquiry, customer, pageErrors, apiErrors, businessWrites, artifacts }, null, 2))
  } finally {
    try { await context?.close() } finally { await browser.close() }
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})

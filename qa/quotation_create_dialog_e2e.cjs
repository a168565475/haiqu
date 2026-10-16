const assert = require('node:assert/strict')
const path = require('node:path')
const { chromium } = require('playwright-core')

const baseUrl = process.env.UI_E2E_BASE_URL || 'http://localhost:8080'
const apiUrl = process.env.UI_E2E_API_URL || 'http://localhost:8000'
const chromePath = process.env.UI_E2E_CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const viewportWidth = Number(process.env.UI_E2E_WIDTH || 1920)
const viewportHeight = Number(process.env.UI_E2E_HEIGHT || 1080)

async function developmentLogin(context) {
  await context.request.get(`${apiUrl}/api/auth/me/`)
  const csrf = (await context.cookies()).find(cookie => cookie.name === 'csrftoken')
  assert.ok(csrf, '未获取到 CSRF Cookie')
  const response = await context.request.post(`${apiUrl}/api/auth/development-auto-login/`, {
    headers: { 'X-CSRFToken': csrf.value, Referer: baseUrl },
    data: {},
  })
  assert.equal(response.status(), 200, await response.text())
}

async function main() {
  const browser = await chromium.launch({ executablePath: chromePath, headless: true })
  const context = await browser.newContext({ viewport: { width: viewportWidth, height: viewportHeight }, deviceScaleFactor: 1 })
  try {
    await developmentLogin(context)
    const page = await context.newPage()
    const businessWrites = []
    page.on('request', request => {
      if (request.url().includes('/api/') && !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
        businessWrites.push(`${request.method()} ${request.url()}`)
      }
    })
    await page.goto(`${baseUrl}/quotations`, { waitUntil: 'domcontentloaded' })
    await page.getByRole('heading', { name: '报价列表' }).waitFor({ timeout: 20000 })
    await page.getByRole('button', { name: '＋ 新建报价', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '新建报价' })
    await dialog.waitFor({ timeout: 20000 })
    const metrics = await dialog.evaluate(element => {
      const body = element.querySelector('.app-window-dialog__body')
      const header = element.querySelector('.app-window-dialog__header')
      const footer = element.querySelector('.app-window-dialog__footer')
      const size = node => Math.round(node?.getBoundingClientRect().height || 0)
      const controlHeights = [...element.querySelectorAll('.el-input__wrapper, .el-select__wrapper')]
        .filter(node => node.getBoundingClientRect().height > 0)
        .map(node => Math.round(node.getBoundingClientRect().height))
      return {
        viewport: { width: window.innerWidth, height: window.innerHeight },
        dialog: { width: Math.round(element.getBoundingClientRect().width), height: size(element) },
        headerHeight: size(header),
        bodyHeight: size(body),
        bodyClientHeight: body?.clientHeight || 0,
        bodyScrollHeight: body?.scrollHeight || 0,
        bodyOverflowY: body ? getComputedStyle(body).overflowY : '',
        footerHeight: size(footer),
        controlHeights,
      }
    })
    await page.screenshot({ path: path.join('qa', `quotation-create-window-${viewportWidth}x${viewportHeight}.png`), fullPage: true })
    assert.deepEqual(businessWrites, [], `验收期间发生业务写入：${businessWrites.join(' | ')}`)
    if (process.env.EXPECT_NO_SCROLL === '1') {
      assert.ok(metrics.bodyScrollHeight <= metrics.bodyClientHeight + 1, `新增报价内容区仍有滚动：${JSON.stringify(metrics)}`)
    }
    if (process.env.EXPECT_CONTROL_HEIGHT === '1') {
      assert.ok(metrics.controlHeights.length > 0, '未找到新增报价表单控件')
      assert.ok(metrics.controlHeights.every(height => height === 32), `新增报价控件高度不是 32px：${JSON.stringify(metrics.controlHeights)}`)
    }
    console.log(JSON.stringify({ metrics, businessWrites }, null, 2))
  } finally {
    await context.close()
    await browser.close()
  }
}

main().catch(error => {
  console.error(error)
  process.exitCode = 1
})

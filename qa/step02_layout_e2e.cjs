const assert = require('node:assert/strict')
const { chromium } = require('playwright')

const frontendUrl = 'http://127.0.0.1:5173'
const apiUrl = 'http://127.0.0.1:8000'

function requiredEnvironment(name) {
  const value = process.env[name]
  if (!value) {
    throw new Error(`缺少测试环境变量：${name}`)
  }
  return value
}

function assertNear(actual, expected, label) {
  assert.ok(Math.abs(actual - expected) <= 1, `${label} 应为 ${expected}，实际为 ${actual}`)
}

async function run() {
  const username = requiredEnvironment('E2E_ACTIVE')
  const password = requiredEnvironment('E2E_PASSWORD')
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  })
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } })
  const page = await context.newPage()
  const pageErrors = []
  const results = {}
  page.on('pageerror', (error) => pageErrors.push(error.message))

  await page.goto(`${frontendUrl}/login`)
  assert.equal(await page.locator('.erp-layout').count(), 0)
  results.login_isolated = true

  await page.getByLabel('账号').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL((url) => url.pathname === '/')
  await page.locator('.erp-layout').waitFor()

  const layout = await page.locator('.erp-layout').boundingBox()
  const sidebar = await page.locator('.erp-layout__sidebar').boundingBox()
  const brand = await page.locator('.erp-layout__brand').boundingBox()
  const workspace = await page.locator('.erp-layout__workspace').boundingBox()
  const header = await page.locator('.erp-layout__header').boundingBox()
  const main = await page.locator('.erp-layout__main').boundingBox()
  assert.ok(layout && sidebar && brand && workspace && header && main)

  assertNear(layout.width, 1920, 'Layout 宽度')
  assertNear(layout.height, 1080, 'Layout 高度')
  assertNear(sidebar.width, 240, 'Sidebar 宽度')
  assertNear(sidebar.height, 1080, 'Sidebar 高度')
  assertNear(brand.height, 56, '品牌区高度')
  assertNear(workspace.x, 240, '工作区起始位置')
  assertNear(workspace.width, 1680, '工作区宽度')
  assertNear(header.height, 56, 'Header 高度')
  assertNear(main.y, 56, '主内容区起始位置')
  assertNear(main.height, 1024, '主内容区高度')
  results.desktop_geometry = true

  const desktopStyles = await page.evaluate(() => {
    const mainElement = document.querySelector('.erp-layout__main')
    const sidebarElement = document.querySelector('.erp-layout__sidebar')
    const headerElement = document.querySelector('.erp-layout__header')
    if (!mainElement || !sidebarElement || !headerElement) {
      throw new Error('Layout 元素不存在')
    }
    return {
      mainBackground: getComputedStyle(mainElement).backgroundColor,
      mainOverflow: getComputedStyle(mainElement).overflowY,
      sidebarBackground: getComputedStyle(sidebarElement).backgroundColor,
      headerBackground: getComputedStyle(headerElement).backgroundColor,
      documentScrollWidth: document.documentElement.scrollWidth,
      documentClientWidth: document.documentElement.clientWidth,
    }
  })
  assert.equal(desktopStyles.mainBackground, 'rgb(245, 246, 248)')
  assert.equal(desktopStyles.mainOverflow, 'auto')
  assert.equal(desktopStyles.sidebarBackground, 'rgb(255, 255, 255)')
  assert.equal(desktopStyles.headerBackground, 'rgb(255, 255, 255)')
  assert.equal(desktopStyles.documentScrollWidth, desktopStyles.documentClientWidth)
  results.desktop_styles = true

  await page.screenshot({ path: 'qa/step02_layout_desktop.png', fullPage: true })

  await page.reload()
  await page.waitForURL((url) => url.pathname === '/')
  await page.locator('.erp-layout').waitFor()
  results.refresh_session_restored = true

  await page.setViewportSize({ width: 390, height: 844 })
  const mobileLayout = await page.locator('.erp-layout').boundingBox()
  const mobileSidebarDisplay = await page
    .locator('.erp-layout__sidebar')
    .evaluate((element) => getComputedStyle(element).display)
  const mobileWorkspace = await page.locator('.erp-layout__workspace').boundingBox()
  const mobileHeader = await page.locator('.erp-layout__header').boundingBox()
  const mobileMain = await page.locator('.erp-layout__main').boundingBox()
  assert.ok(mobileLayout && mobileWorkspace && mobileHeader && mobileMain)
  assert.equal(mobileSidebarDisplay, 'none')
  assertNear(mobileLayout.width, 390, '移动端 Layout 宽度')
  assertNear(mobileWorkspace.x, 0, '移动端工作区起始位置')
  assertNear(mobileWorkspace.width, 390, '移动端工作区宽度')
  assertNear(mobileHeader.height, 56, '移动端 Header 高度')
  assertNear(mobileMain.y, 56, '移动端主内容区起始位置')
  const mobileWidths = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  assert.equal(mobileWidths.scrollWidth, mobileWidths.clientWidth)
  results.mobile_safe_fallback = true
  await page.screenshot({ path: 'qa/step02_layout_mobile.png', fullPage: true })

  const csrfCookie = (await context.cookies(apiUrl)).find(
    (cookie) => cookie.name === 'csrftoken',
  )
  assert.ok(csrfCookie)
  const logoutResponse = await context.request.post(`${apiUrl}/api/auth/logout/`, {
    headers: { 'X-CSRFToken': csrfCookie.value, Origin: frontendUrl },
  })
  assert.equal(logoutResponse.status(), 200)
  await page.reload()
  await page.waitForURL((url) => url.pathname === '/login')
  assert.equal(await page.locator('.erp-layout').count(), 0)
  results.layout_removed_after_logout = true

  assert.deepEqual(pageErrors, [])
  results.page_errors = pageErrors.length

  await context.close()
  await browser.close()
  process.stdout.write(JSON.stringify(results, null, 2))
}

run().catch((error) => {
  console.error(error)
  process.exit(1)
})

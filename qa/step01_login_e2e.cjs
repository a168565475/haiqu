const assert = require('node:assert/strict')
const { chromium, request } = require('playwright')

const frontendUrl = 'http://127.0.0.1:5173'
const apiUrl = 'http://127.0.0.1:8000'

function requiredEnvironment(name) {
  const value = process.env[name]
  if (!value) {
    throw new Error(`缺少测试环境变量：${name}`)
  }
  return value
}

async function retryConnection(operation, attempts = 3) {
  let lastError
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await operation()
    } catch (error) {
      lastError = error
      if (attempt < attempts) {
        await new Promise((resolve) => setTimeout(resolve, 500 * attempt))
      }
    }
  }
  throw lastError
}

async function run() {
  const activeUsername = requiredEnvironment('E2E_ACTIVE')
  const disabledUsername = requiredEnvironment('E2E_DISABLED')
  const inactiveEmployeeUsername = requiredEnvironment('E2E_INACTIVE_EMP')
  const missingUsername = requiredEnvironment('E2E_MISSING')
  const password = requiredEnvironment('E2E_PASSWORD')
  const results = {}

  const csrfRequest = await request.newContext({ baseURL: apiUrl })
  const csrfResponse = await retryConnection(() => csrfRequest.get('/api/auth/me/'))
  assert.equal(csrfResponse.status(), 200)
  const noCsrfResponse = await csrfRequest.post('/api/auth/login/', {
    data: { username: activeUsername, password },
    headers: { Origin: frontendUrl },
  })
  assert.equal(noCsrfResponse.status(), 403)
  results.csrf_without_header = noCsrfResponse.status()
  await csrfRequest.dispose()

  const anonymousRequest = await request.newContext({ baseURL: apiUrl })
  const protectedResponse = await retryConnection(() => anonymousRequest.get('/api/v1/'))
  assert.equal(protectedResponse.status(), 401)
  results.anonymous_protected_api = protectedResponse.status()
  await anonymousRequest.dispose()

  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  })
  const context = await browser.newContext({ viewport: { width: 1440, height: 810 } })
  const page = await context.newPage()
  const pageErrors = []
  page.on('pageerror', (error) => pageErrors.push(error.message))

  await retryConnection(() => page.goto(`${frontendUrl}/`))
  await page.waitForURL(
    (url) => url.pathname === '/login' && url.searchParams.get('redirect') === '/',
  )
  results.anonymous_page_redirect = true
  await page.screenshot({ path: 'qa/step01_login_final.png', fullPage: true })

  await page.getByRole('button', { name: '登录' }).click()
  await page.locator('.el-form-item__error').first().waitFor()
  assert.equal(await page.locator('.el-form-item__error').count(), 2)
  results.empty_form_errors = 2

  async function expectRejectedLogin(username, attemptedPassword) {
    await page.getByLabel('账号').fill(username)
    await page.getByLabel('密码').fill(attemptedPassword)
    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/auth/login/') && response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: '登录' }).click()
    const response = await responsePromise
    assert.equal(response.status(), 400)
    await page
      .locator('.el-message__content', { hasText: '用户名或密码错误' })
      .last()
      .waitFor()
    assert.equal(new URL(page.url()).pathname, '/login')
    return response.status()
  }

  results.unknown_user = await expectRejectedLogin(missingUsername, password)
  results.wrong_password = await expectRejectedLogin(activeUsername, `${password}-wrong`)
  results.disabled_user = await expectRejectedLogin(disabledUsername, password)
  results.inactive_employee = await expectRejectedLogin(inactiveEmployeeUsername, password)

  await page.route(
    '**/api/auth/login/',
    async (route) => {
      await route.fulfill({ status: 500, contentType: 'application/json', body: '{}' })
    },
    { times: 1 },
  )
  await page.getByLabel('账号').fill(activeUsername)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await page
    .locator('.el-message__content', { hasText: '服务器暂时无法处理登录，请稍后重试' })
    .last()
    .waitFor()
  results.frontend_500_message = true

  await page.route(
    '**/api/auth/login/',
    async (route) => {
      await route.abort('connectionfailed')
    },
    { times: 1 },
  )
  await page.getByRole('button', { name: '登录' }).click()
  await page
    .locator('.el-message__content', { hasText: '无法连接服务器，请确认系统服务已启动' })
    .last()
    .waitFor()
  results.frontend_network_message = true

  await page.route(
    '**/api/auth/login/',
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 350))
      await route.continue()
    },
    { times: 1 },
  )
  const loginResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/auth/login/') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '登录' }).click()
  await page.locator('button.login-button.is-loading').waitFor()
  results.loading_state = true
  const loginResponse = await loginResponsePromise
  assert.equal(loginResponse.status(), 200)
  await page.waitForURL((url) => url.pathname === '/')
  results.correct_login = loginResponse.status()

  const cookiesAfterLogin = await context.cookies(apiUrl)
  assert.ok(cookiesAfterLogin.some((cookie) => cookie.name === 'sessionid'))
  assert.ok(cookiesAfterLogin.some((cookie) => cookie.name === 'csrftoken'))
  results.session_cookie = true
  results.csrf_cookie = true

  const authenticatedApi = await context.request.get(`${apiUrl}/api/v1/`)
  assert.equal(authenticatedApi.status(), 200)
  results.authenticated_protected_api = authenticatedApi.status()

  await page.reload()
  await page.waitForURL((url) => url.pathname === '/')
  results.refresh_session_restored = true

  await page.goto(`${frontendUrl}/login`)
  await page.waitForURL((url) => url.pathname === '/')
  results.authenticated_login_redirect = true

  const csrfCookie = (await context.cookies(apiUrl)).find(
    (cookie) => cookie.name === 'csrftoken',
  )
  assert.ok(csrfCookie)
  const logoutResponse = await context.request.post(`${apiUrl}/api/auth/logout/`, {
    headers: { 'X-CSRFToken': csrfCookie.value, Origin: frontendUrl },
  })
  assert.equal(logoutResponse.status(), 200)
  results.logout = logoutResponse.status()

  const meAfterLogout = await context.request.get(`${apiUrl}/api/auth/me/`)
  assert.deepEqual(await meAfterLogout.json(), { authenticated: false, user: null })
  results.me_after_logout = false

  await page.reload()
  await page.waitForURL(
    (url) => url.pathname === '/login' && url.searchParams.get('redirect') === '/',
  )
  results.protected_page_after_logout = true

  const cookiesAfterLogout = await context.cookies(apiUrl)
  assert.ok(!cookiesAfterLogout.some((cookie) => cookie.name === 'sessionid'))
  results.session_removed = true

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

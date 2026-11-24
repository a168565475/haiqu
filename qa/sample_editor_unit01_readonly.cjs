// 已登录实页只读验收：仅正常认证可写，业务写入一律拦截并判失败。
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('../src/frontend/node_modules/playwright-core')
const output = path.resolve(process.env.SAMPLE_EDITOR_QA_OUTPUT || path.resolve(__dirname, '../docs/plans/sample_editor_20261021/reports/evidence'))
const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:8080'
const categories = [ ['tube', '管材类'], ['hardware', '五金件'], ['plastic', '塑料件类'], ['accessory', '辅料类'], ['fabric', '面料类'], ['packaging', '包材类'] ]
const stages = ['DIRECTOR_REVIEW', 'APPLICATION_RETURNED', 'PENDING_COMPLETION', 'MATERIALS_PENDING', 'WAREHOUSE_PENDING', 'PROCUREMENT_PENDING', 'MATERIAL_ISSUE_PENDING', 'MATERIAL_ISSUE_REVIEW', 'PRODUCTION_PENDING', 'FINISHED']
const critical = /\/api\/v1\/sample-requests\/(?:form-options|material-units|material-reference-options|material-candidates|[^/]+\/(?:materials|application-product-options))\/|\/api\/v1\/sample-requests\/[0-9a-f-]{36}\/$/
const safePath = url => new URL(url).pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, ':id')
async function main() {
  fs.mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' })
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, ...(process.env.E2E_STORAGE_STATE ? { storageState: process.env.E2E_STORAGE_STATE } : {}) })
  const report = { status: 'UNKNOWN', reason: '尚未完成', identity: null, sampling: null, errors: [], writes: [], criticalReads: [], notCovered: [], results: [] }
  async function read(url) {
    const response = await context.request.get(`${base}${url}`)
    assert.equal(response.status(), 200, `关键只读API失败：${safePath(response.url())}`)
    return (await response.json()).data
  }
  async function screenshot(page, name) { const file = path.join(output, `${name}.png`); await page.screenshot({ path: file, fullPage: true }); return file }
  async function noVisibleErrors(page) {
    assert.equal(await page.locator('.sample-editor-page .el-alert--error:visible, .reference-error:visible, .picker-error:visible, .drawer-error:visible').count(), 0, '页面捕获并显示了读取错误')
    assert.equal(report.criticalReads.some(item => item.status === 0 || item.status >= 400), false, '存在失败的关键读取响应')
  }
  try {
    await context.route('**/api/**', route => {
      const request = route.request()
      if (['GET', 'HEAD'].includes(request.method()) || new URL(request.url()).pathname === '/api/auth/login/') return route.continue()
      report.writes.push(`${request.method()} ${safePath(request.url())}`); return route.abort('blockedbyclient')
    })
    let auth = await (await context.request.get(`${base}/api/auth/me/`)).json()
    if (!auth.authenticated && process.env.E2E_USERNAME && process.env.E2E_PASSWORD) {
      const csrf = (await context.cookies()).find(cookie => cookie.name === 'csrftoken')?.value
      const response = await context.request.post(`${base}/api/auth/login/`, { headers: { 'X-CSRFToken': csrf || '' }, data: { username: process.env.E2E_USERNAME, password: process.env.E2E_PASSWORD } })
      assert.equal(response.status(), 200, '正常Session登录失败'); auth = await response.json()
    }
    if (!auth.authenticated) { report.reason = '缺少有效登录会话，未注入身份或业务数据。'; process.exitCode = 2; return }
    report.identity = { isSuperuser: auth.user.is_superuser, moduleAccessEnabled: Boolean(auth.user.module_access_enabled), permissions: Object.fromEntries(['samples.view_samplerequest', 'samples.complete_sample_requirements', 'samples.edit_sample_materials', 'products.view_productinformation'].map(code => [code, auth.user.permissions.includes(code)])) }
    const listing = await read('/api/v1/sample-requests/?page_size=100')
    assert(listing.length, '需要当前会话可访问的真实申请')
    const records = [...listing.reduce((map, row) => map.has(row.status) ? map : map.set(row.status, row), new Map()).values()]
    report.sampling = { requestedPageSize: 100, returned: listing.length, sampledPerStage: 1, stageCounts: listing.reduce((counts, row) => ({ ...counts, [row.status]: (counts[row.status] || 0) + 1 }), {}), sampledStages: records.map(row => row.status), missingStages: stages.filter(stage => !records.some(row => row.status === stage)) }
    report.notCovered.push('仅前100条中每状态首条，不代表全量记录；缺失阶段为UNKNOWN。', '未执行任何产品/材料保存、提交或无需用料。')
    if (auth.user.is_superuser) report.notCovered.push('当前会话为管理员，普通岗位真实权限验收UNKNOWN。')
    const page = await context.newPage(); page.setDefaultTimeout(15000)
    page.on('pageerror', error => report.errors.push(error.message))
    page.on('response', response => { if (critical.test(new URL(response.url()).pathname)) report.criticalReads.push({ route: safePath(response.url()), status: response.status() }) })
    page.on('requestfailed', request => { if (critical.test(new URL(request.url()).pathname)) report.criticalReads.push({ route: safePath(request.url()), status: 0 }) })
    for (const record of records) {
      const sample = await read(`/api/v1/sample-requests/${record.id}/`)
      const materials = await read(`/api/v1/sample-requests/${record.id}/materials/`)
      const lines = materials.available ? materials.draft.lines : []
      const canProduct = Boolean(sample.application_actions?.is_application && sample.edit_capabilities?.can_complete)
      const canMaterial = Boolean(materials.available && materials.canEdit)
      const readsStart = report.criticalReads.length
      await page.goto(`${base}/samples/${record.id}/edit`, { waitUntil: 'networkidle' })
      await page.locator('.sample-editor-page > .el-loading-mask').waitFor({ state: 'hidden' })
      assert.equal(new URL(page.url()).pathname, `/samples/${record.id}/edit`)
      await noVisibleErrors(page)
      const initialReads = report.criticalReads.slice(readsStart)
      for (const fragment of ['/materials/', '/material-units/', ...(canProduct ? ['/form-options/', '/application-product-options/'] : []), ...(canMaterial ? ['/material-reference-options/'] : [])]) assert(initialReads.some(item => item.route.includes(fragment) && item.status === 200), `缺少成功读取：${fragment}`)
      for (const viewport of [{ width: 1920, height: 1080 }, { width: 1440, height: 900 }]) {
        await page.setViewportSize(viewport); await page.evaluate(() => document.fonts.ready)
        const result = { stage: record.status, viewport, productMode: sample.edit_capabilities?.mode, canProduct, canMaterial, actualMaterialLineCount: lines.length, completed: false, categories: [], screenshots: [] }
        report.results.push(result)
        assert.equal(await page.getByRole('tablist', { name: '打样编辑内容' }).getByRole('tab').count(), 2)
        result.product = await page.locator('.sample-editor-page').evaluate(node => {
          const tab = node.querySelector('#sample-product-tab'), heading = node.querySelector('.title-line h1'), card = node.querySelector('.product-card'), s = card && getComputedStyle(card)
          return { tabHeight: tab.getBoundingClientRect().height, tabFont: getComputedStyle(tab).fontSize, headingFont: getComputedStyle(heading).fontSize, headingLineHeight: getComputedStyle(heading).lineHeight,
            border: s && [s.borderTopWidth, s.borderRightWidth, s.borderBottomWidth, s.borderLeftWidth], overflow: document.documentElement.scrollWidth > innerWidth }
        })
        // 当前BOM实页36px/44px，由glass-form-layout主题规则覆盖局部26px；见style-probe.json。
        assert.equal(result.product.headingFont, '36px'); assert.equal(result.product.headingLineHeight, '44px')
        assert.equal(result.product.tabHeight, 32); assert.equal(result.product.tabFont, '13px'); assert.equal(result.product.overflow, false)
        assert.equal(await page.locator('.product-card .el-form').count(), 0)
        result.screenshots.push(await screenshot(page, `sample-${record.status}-${viewport.width}-product`))
        await page.getByRole('button', { name: /^(编辑产品信息|查看产品信息)$/ }).first().click()
        const productWindow = page.getByRole('dialog').filter({ has: page.locator('#sample-purpose') })
        await productWindow.waitFor({ state: 'visible' })
        const fields = await productWindow.locator('input:not([type="hidden"]), textarea').evaluateAll(nodes => nodes.map(node => ({ disabled: node.disabled, readonly: node.readOnly })))
        assert(fields.length > 0, '产品窗口缺少字段')
        if (!canProduct) { assert(fields.every(field => field.disabled || field.readonly), '只读产品窗口有可输入字段'); assert.equal(await productWindow.getByRole('button', { name: '保存产品需求', exact: true }).count(), 0) }
        result.productWindow = { inputCount: fields.length, allReadonlyOrDisabled: fields.every(field => field.disabled || field.readonly) }
        if (canProduct) {
          assert(fields.some(field => !field.disabled && !field.readonly), '允许完善时产品窗口没有可编辑字段')
          await productWindow.locator('.el-select').first().click()
          await page.locator('.el-select-dropdown:visible').waitFor()
          result.productWindow.candidateOptions = await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').count()
          result.productWindow.openedCandidateSelector = true
          await productWindow.locator('.field-hint').click()
        }
        result.screenshots.push(await screenshot(page, `sample-${record.status}-${viewport.width}-product-window`))
        result.productWindow.geometry = await productWindow.evaluate(node => {
          const box = node.getBoundingClientRect(), body = node.querySelector('.app-window-dialog__body')
          return { left: box.left, top: box.top, right: box.right, bottom: box.bottom, bodyClientHeight: body.clientHeight, bodyScrollHeight: body.scrollHeight, bodyOverflow: getComputedStyle(body).overflowY }
        })
        const geometry = result.productWindow.geometry
        assert(geometry.left >= 0 && geometry.top >= 0 && geometry.right <= viewport.width && geometry.bottom <= viewport.height, '产品窗口超出视口')
        if (geometry.bodyScrollHeight > geometry.bodyClientHeight) {
          assert(['auto', 'scroll'].includes(geometry.bodyOverflow), '产品窗口溢出内容不可滚动')
          await productWindow.locator('#sample-purpose').scrollIntoViewIfNeeded()
          const purposeBox = await productWindow.locator('#sample-purpose').boundingBox()
          assert(purposeBox && purposeBox.y >= 0 && purposeBox.y + purposeBox.height <= viewport.height, '产品窗口底部要求字段不可达')
          result.screenshots.push(await screenshot(page, `sample-${record.status}-${viewport.width}-product-window-bottom`))
        }
        await productWindow.getByRole('button', { name: '返回概览', exact: true }).click(); await productWindow.waitFor({ state: 'hidden' })
        await page.getByRole('tab', { name: '材料需求', exact: true }).click()
        assert.equal(await page.locator('.material-editor .section-sidebar button').count(), 6)
        assert.equal(await page.locator('.material-main .material-table').count(), 1); assert.equal(await page.locator('.material-editor .material-tabs').count(), 0)
        result.sidebar = await page.locator('.material-editor').evaluate(node => { const left = node.querySelector('.section-sidebar').getBoundingClientRect(), right = node.querySelector('.material-main').getBoundingClientRect(); return { width: left.width, gap: right.left - left.right, leftOfTable: left.right <= right.left } })
        assert.equal(result.sidebar.width, 176); assert.equal(result.sidebar.gap, 14); assert.equal(result.sidebar.leftOfTable, true)
        let lineWindowChecked = false, pickerChecked = false
        for (const [key, label] of categories) {
          await page.locator('.section-sidebar button').filter({ hasText: label }).click()
          const expected = lines.filter(line => line.category === key).length
          const rows = page.locator('.material-main tbody tr[data-line-key]')
          assert.equal(await rows.count(), expected, `分类${key}真实行数不匹配`)
          assert.equal(await page.locator('.material-main .empty-row').count(), expected ? 0 : 1)
          const entry = { key, actualRows: expected, emptyPlaceholder: expected === 0 }
          result.categories.push(entry)
          const expand = rows.locator('[aria-label="放大编辑当前行"]')
          if (!canMaterial) {
            assert.equal(await page.locator('#sample-material-notes').isDisabled(), true)
            for (let i = 0; i < await expand.count(); i++) assert.equal(await expand.nth(i).isDisabled(), true)
            assert.equal(await page.getByRole('button', { name: '提交仓库', exact: true }).count(), 0)
            const enabledEdits = await page.locator('.material-main input, .material-main textarea').evaluateAll(nodes => nodes.filter(node => !node.disabled && !node.readOnly).length)
            assert.equal(enabledEdits, 0, '只读材料存在可编辑输入')
            const pickerButtons = page.locator('.material-toolbar button').filter({ hasText: /选择管材|选择数据|选择辅料|选择包材|选择面料/ })
            for (let i = 0; i < await pickerButtons.count(); i++) assert.equal(await pickerButtons.nth(i).isDisabled(), true, '只读材料的库存选择入口未禁用')
          } else {
            if (expected && !lineWindowChecked) {
              await expand.first().click()
              const lineWindow = page.getByRole('dialog').filter({ has: page.locator('.material-line-drawer') })
              await lineWindow.waitFor({ state: 'visible' })
              assert.equal(await lineWindow.locator('input[aria-label="放大编辑需求数量"]').isDisabled(), false)
              assert.equal(await page.locator('.section-sidebar button:disabled').count(), 6)
              await lineWindow.getByRole('button', { name: '取消', exact: true }).click(); await lineWindow.waitFor({ state: 'hidden' })
              lineWindowChecked = true
            }
            const pick = page.locator('.material-toolbar button').filter({ hasText: /选择管材|选择数据|选择辅料|选择包材|选择面料/ }).first()
            if (await pick.count() && !pickerChecked) {
              assert.equal(await pick.isDisabled(), false)
              const pending = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/sample-requests/material-candidates/')
              await pick.click(); assert.equal((await pending).status(), 200)
              const picker = page.getByRole('dialog').filter({ has: page.locator('.material-picker') })
              await picker.waitFor({ state: 'visible' }); await noVisibleErrors(page)
              await picker.getByRole('button', { name: '取消', exact: true }).click(); await picker.waitFor({ state: 'hidden' })
              pickerChecked = true
            }
          }
          await noVisibleErrors(page)
        }
        if (canMaterial && !lineWindowChecked) {
          // 当前服务端无可编辑需求行时，仅从真实候选生成浏览器草稿；取消后精确移除，不写API。
          await page.locator('.section-sidebar button').filter({ hasText: '管材类' }).click()
          const beforeKeys = await page.locator('.material-main tr[data-line-key]').evaluateAll(nodes => nodes.map(node => node.getAttribute('data-line-key')))
          const candidateRead = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/sample-requests/material-candidates/')
          await page.getByRole('button', { name: '选择管材', exact: true }).click()
          const candidateResponse = await candidateRead; assert.equal(candidateResponse.status(), 200)
          const candidateData = await candidateResponse.json()
          const picker = page.getByRole('dialog').filter({ has: page.locator('.material-picker') })
          await picker.waitFor({ state: 'visible' }); await noVisibleErrors(page)
          await picker.locator('.el-loading-mask').waitFor({ state: 'hidden' })
          if (candidateData.data.length) {
            result.screenshots.push(await screenshot(page, `sample-${record.status}-${viewport.width}-inventory-picker`))
            await picker.locator('.el-table__body .el-checkbox').first().click()
            await picker.getByRole('button', { name: /^添加所选/ }).click(); await picker.waitFor({ state: 'hidden' })
            const afterKeys = await page.locator('.material-main tr[data-line-key]').evaluateAll(nodes => nodes.map(node => node.getAttribute('data-line-key')))
            const localKeys = afterKeys.filter(key => !beforeKeys.includes(key)); assert.equal(localKeys.length, 1)
            const localRow = page.locator(`.material-main tr[data-line-key="${localKeys[0]}"]`)
            await localRow.getByRole('button', { name: '放大编辑当前行', exact: true }).click()
            const lineWindow = page.getByRole('dialog').filter({ has: page.locator('.material-line-drawer') })
            await lineWindow.waitFor({ state: 'visible' })
            const quantity = lineWindow.locator('input[aria-label="放大编辑需求数量"]')
            await quantity.fill('1.25')
            result.screenshots.push(await screenshot(page, `sample-${record.status}-${viewport.width}-local-draft-line-window`))
            await lineWindow.getByRole('button', { name: '取消', exact: true }).click()
            await page.locator('.el-message-box:visible').getByRole('button', { name: '继续填写', exact: true }).click()
            assert.equal(await quantity.inputValue(), '1.25')
            await lineWindow.getByRole('button', { name: '取消', exact: true }).click()
            await page.locator('.el-message-box:visible').getByRole('button', { name: '放弃修改', exact: true }).click(); await lineWindow.waitFor({ state: 'hidden' })
            await localRow.locator('input[aria-label$="需求数量"]').fill('1')
            const notes = page.locator('#sample-material-notes'), originalNotes = await notes.inputValue()
            await notes.fill('只读检查：未保存临时材料备注')
            if (canProduct) {
              await page.getByRole('tab', { name: '申请与产品', exact: true }).click()
              await page.getByRole('button', { name: '编辑产品信息', exact: true }).first().click()
              const productDialog = page.getByRole('dialog').filter({ has: page.locator('#sample-purpose') })
              const purpose = productDialog.locator('#sample-purpose'), originalPurpose = await purpose.inputValue()
              await purpose.fill('只读检查：未保存临时产品要求')
              await productDialog.getByRole('button', { name: '返回概览', exact: true }).click()
              for (const action of ['提交仓库', '无需用料']) {
                await page.getByRole('tab', { name: '材料需求', exact: true }).click()
                await page.getByRole('button', { name: action, exact: true }).click()
                const confirmation = page.locator('.el-message-box:visible')
                await confirmation.waitFor({ state: 'visible' })
                assert.equal((await confirmation.innerText()).includes('可能推进阶段'), true)
                await confirmation.getByRole('button', { name: '返回产品', exact: true }).click()
                await productDialog.waitFor({ state: 'visible' })
                assert.equal(await purpose.inputValue() === '只读检查：未保存临时产品要求', true)
                assert.equal(await notes.inputValue() === '只读检查：未保存临时材料备注', true)
                await productDialog.getByRole('button', { name: '返回概览', exact: true }).click()
              }
              await page.getByRole('button', { name: '编辑产品信息', exact: true }).first().click()
              await purpose.fill(originalPurpose)
              await productDialog.getByRole('button', { name: '返回概览', exact: true }).click()
            }
            await page.getByRole('tab', { name: '材料需求', exact: true }).click()
            await page.getByRole('button', { name: '查看详情', exact: true }).click()
            await page.locator('.el-message-box:visible').getByRole('button', { name: '继续填写', exact: true }).click()
            assert.equal(new URL(page.url()).pathname, `/samples/${record.id}/edit`)
            assert.equal(await notes.inputValue() === '只读检查：未保存临时材料备注', true)
            await notes.fill(originalNotes)
            await localRow.getByRole('button', { name: '删除当前行', exact: true }).click()
            await page.locator('.el-message-box:visible').getByRole('button', { name: '删除', exact: true }).click()
            await localRow.waitFor({ state: 'hidden' })
            const restored = await page.locator('.material-main tr[data-line-key]').evaluateAll(nodes => nodes.map(node => node.getAttribute('data-line-key')))
            assert.equal(JSON.stringify(restored) === JSON.stringify(beforeKeys), true, '临时草稿行未精确移除')
            const readback = await read(`/api/v1/sample-requests/${record.id}/materials/`)
            assert.equal(JSON.stringify(readback) === JSON.stringify(materials), true, '只读交互后服务端材料发生变化')
            result.localDraftProbe = { source: 'real-inventory-api', addedBrowserOnlyRows: 1, restored: true, serverUnchanged: true, dirtyConfirmationCancelled: canProduct, lineCancelPreservedInput: true, routeLeaveCancelled: true }
            lineWindowChecked = true; pickerChecked = true
          } else {
            await picker.getByRole('button', { name: '取消', exact: true }).click()
            report.notCovered.push(`${record.status}/${viewport.width}：真实库存候选为空，未造材料行。`)
          }
        }
        result.interactions = { switchedCategories: 6, openedLineWindow: lineWindowChecked, openedInventoryPicker: pickerChecked }
        if (!lineWindowChecked) report.notCovered.push(`${record.status}/${viewport.width}：材料行窗口UNKNOWN（当前无可编辑行或只读）。`)
        if (!pickerChecked) report.notCovered.push(`${record.status}/${viewport.width}：库存选择器窗口UNKNOWN（当前材料阶段只读，已核对入口禁用）。`)
        if (!canProduct) report.notCovered.push(`${record.status}/${viewport.width}：产品完善编辑及候选浏览UNKNOWN（当前阶段只读）。`)
        await page.locator('.section-sidebar button').filter({ hasText: '管材类' }).click()
        await page.getByRole('button', { name: '全屏填写', exact: true }).click()
        await page.locator('.sample-editor-page.is-fullscreen').waitFor(); await page.keyboard.press('Escape')
        await page.locator('.sample-editor-page.is-fullscreen').waitFor({ state: 'hidden' })
        result.table = await page.locator('.material-main table').evaluate(node => ({ columns: node.querySelectorAll('thead th').length, actualRows: node.querySelectorAll('tbody tr[data-line-key]').length,
          emptyPlaceholders: node.querySelectorAll('tbody .empty-row').length, headerHeight: node.querySelector('thead').getBoundingClientRect().height, rowHeight: node.querySelector('tbody tr[data-line-key]')?.getBoundingClientRect().height || null,
          scrollNeeded: node.scrollWidth > node.parentElement.clientWidth, horizontalOverflow: document.documentElement.scrollWidth > innerWidth }))
        assert.equal(result.table.columns, 9); assert.equal(result.table.horizontalOverflow, false)
        await noVisibleErrors(page)
        result.screenshots.push(await screenshot(page, `sample-${record.status}-${viewport.width}-materials`))
        await page.getByRole('tab', { name: '申请与产品', exact: true }).click()
        result.completed = true
      }
    }
    assert.deepEqual(report.errors, []); assert.deepEqual(report.writes, [])
    report.status = 'PASS_WITH_GAPS'; report.reason = '当前真实取样的只读页面/交互通过；缺失阶段、普通岗位和真实保存保持UNKNOWN。'
  } catch (error) { report.status = 'FAIL'; report.reason = error.message; process.exitCode = 1 }
  finally {
    await context.close(); await browser.close()
    fs.writeFileSync(path.join(output, 'headless-readonly.json'), JSON.stringify(report, null, 2))
    console.log(JSON.stringify({ status: report.status, reason: report.reason, identity: report.identity, sampling: report.sampling, completed: report.results.filter(item => item.completed).length, errorCount: report.errors.length, writes: report.writes, criticalReadFailures: report.criticalReads.filter(item => item.status >= 400) }))
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1 })

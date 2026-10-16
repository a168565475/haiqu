const assert = require('node:assert/strict')
const { chromium } = require('playwright-core')

const baseUrl = process.env.UI_E2E_BASE_URL || 'http://localhost:8080'
const executablePath = process.env.UI_E2E_BROWSER_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath })
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 })
  const page = await context.newPage()
  const pageErrors = []
  const httpErrors = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  page.on('response', (response) => {
    if (response.status() >= 400) httpErrors.push(`${response.status()} ${response.url()}`)
  })
  try {
    await page.goto(`${baseUrl}/production-tasks`, { waitUntil: 'networkidle' })
    await page.getByRole('heading', { name: '生产任务单', exact: true }).waitFor({ timeout: 15000 })
    assert.equal((await page.locator('[data-header-title]').innerText()).trim(), '生产管理 / 生产订单')
    const listText = await page.locator('body').innerText()
    for (const expected of ['生产任务单', '全部', '待校验', '草稿', '可投产', '生产中', '分批交货', '新增生产任务单']) {
      assert.ok(listText.includes(expected), `list missing ${expected}`)
    }
    assert.equal(await page.locator('.status-tab').count(), 6)
    const listHeaders = await page.locator('.table-card .el-table__header th').allTextContents()
    for (const expected of ['任务单', '客户 / 订单', '产品信息', '数量 / 金额', '交期', '业务 / 跟单', '状态', '操作']) {
      assert.ok(listHeaders.some((item) => item.trim() === expected), `list header missing ${expected}`)
    }
    const productionGroup = page.locator('[data-menu-key="production-management"]')
    const productionOrderMenu = page.locator('[data-menu-key="production-tasks"]')
    assert.equal((await productionGroup.locator('.app-sidebar__menu-label').innerText()).trim(), '生产管理')
    assert.equal((await productionGroup.getAttribute('aria-expanded')), 'true')
    assert.equal((await productionOrderMenu.innerText()).trim(), '生产订单')
    assert.ok(await productionOrderMenu.evaluate((node) => node.classList.contains('is-active')))
    const listGeometry = await page.evaluate(() => ({
      viewport: innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      contentWidth: document.querySelector('.production-list-page')?.getBoundingClientRect().width || 0,
    }))
    assert.ok(listGeometry.scrollWidth <= listGeometry.viewport + 1, JSON.stringify(listGeometry))
    await page.screenshot({ path: 'qa/production_tasks_list_1920.png', fullPage: true })

    await page.getByRole('button', { name: /^更多筛选/ }).click()
    await page.locator('.production-filter-popper').waitFor()
    for (const expected of ['合同编号', '客户', '产品', '业务员', '跟单员', '交期范围', '订单来源', '交货方式']) {
      assert.ok((await page.locator('.production-filter-popper').innerText()).includes(expected), `advanced filter missing ${expected}`)
    }
    await page.waitForTimeout(250)
    await page.screenshot({ path: 'qa/production_tasks_list_more_filters_1920.png', fullPage: true })
    await page.getByRole('button', { name: /^更多筛选/ }).click()
    await page.locator('.production-filter-popper').waitFor({ state: 'hidden' })

    await page.getByRole('button', { name: '列设置' }).click()
    const columnsPanel = page.locator('.production-columns-popper')
    await columnsPanel.waitFor()
    assert.ok((await columnsPanel.innerText()).includes('锁定'))
    await page.waitForTimeout(250)
    await page.screenshot({ path: 'qa/production_tasks_list_columns_1920.png', fullPage: true })
    await page.getByRole('button', { name: '列设置' }).click()
    await columnsPanel.waitFor({ state: 'hidden' })

    await page.getByRole('button', { name: '密度' }).click()
    const densityMenu = page.locator('.el-dropdown__popper:visible')
    await densityMenu.waitFor()
    assert.ok((await densityMenu.innerText()).includes('默认'))
    await page.waitForTimeout(250)
    await page.screenshot({ path: 'qa/production_tasks_list_density_1920.png', fullPage: true })
    await page.getByRole('button', { name: '密度' }).click()
    await densityMenu.waitFor({ state: 'hidden' })

    const firstRowMore = page.locator('.el-table__body').getByRole('button', { name: /更多/ }).first()
    if (await firstRowMore.count()) {
      await firstRowMore.click()
      const rowMenu = page.locator('.el-dropdown__popper:visible').filter({ hasText: '取消订单' })
      await rowMenu.waitFor()
      assert.equal(await rowMenu.locator('.el-dropdown-menu__item').count(), 2)
      for (const expected of ['取消订单', '结束订单']) {
        assert.ok((await rowMenu.innerText()).includes(expected), `row menu missing ${expected}`)
      }
      await page.waitForTimeout(250)
      await page.screenshot({ path: 'qa/production_tasks_list_row_more_1920.png', fullPage: true })

      await rowMenu.getByText('取消订单', { exact: true }).click()
      const cancelDialog = page.locator('.el-dialog:visible').filter({ hasText: '取消订单' })
      await cancelDialog.waitFor()
      assert.ok((await cancelDialog.innerText()).includes('取消原因'))
      await cancelDialog.locator('textarea').fill('客户取消采购')
      await page.waitForTimeout(350)
      await page.screenshot({ path: 'qa/production_tasks_list_cancel_dialog_1920.png', fullPage: true })
      await cancelDialog.getByRole('button', { name: '暂不操作' }).click()
      await cancelDialog.waitFor({ state: 'hidden' })
      await page.waitForTimeout(200)

      await firstRowMore.click()
      const finishMenu = page.locator('.el-dropdown__popper:visible').filter({ hasText: '结束订单' })
      await finishMenu.getByText('结束订单', { exact: true }).click()
      const finishDialog = page.locator('.el-dialog:visible').filter({ hasText: '结束订单' })
      await finishDialog.waitFor()
      assert.ok((await finishDialog.innerText()).includes('结束原因'))
      await finishDialog.locator('textarea').fill('订单已全部交付')
      await page.waitForTimeout(350)
      await page.screenshot({ path: 'qa/production_tasks_list_finish_dialog_1920.png', fullPage: true })
      await finishDialog.getByRole('button', { name: '暂不操作' }).click()
      await finishDialog.waitFor({ state: 'hidden' })
    }

    await page.getByRole('button', { name: '新增生产任务单' }).click()
    await page.getByRole('heading', { name: '新增生产任务单' }).waitFor()
    const formText = await page.locator('body').innerText()
    for (const expected of ['基础信息', '合同编号', '订单来源', '订单号', '选择客户', '跟单员', '订单特殊要求', '产品信息']) {
      assert.ok(formText.includes(expected), `form missing ${expected}`)
    }
    assert.ok(!formText.includes('包装方式'), 'task-level packaging method should be removed')
    for (const removed of ['合同编号自动生成；客户、人员和币种使用系统数据', '跟单员（可多选）', '请先在“产品信息”中选择产品']) {
      assert.ok(!formText.includes(removed), `form still contains removed copy: ${removed}`)
    }
    const contractInput = page.locator('.field-grid .el-form-item').first().locator('input')
    await page.waitForFunction(
      (selector) => /^HTC-\d{6}-\d{6}$/.test(document.querySelector(selector)?.value || ''),
      '.field-grid .el-form-item:first-child input',
      { timeout: 15000 },
    )
    const generatedContractNumber = await contractInput.inputValue()
    assert.match(generatedContractNumber, /^HTC-\d{6}-\d{6}$/)
    assert.equal(await contractInput.isEditable(), true)
    await contractInput.fill(`${generatedContractNumber}-A`)
    const contractNumber = await contractInput.inputValue()
    assert.equal(contractNumber, `${generatedContractNumber}-A`)
    const basicGeometry = await page.locator('.field-grid .el-form-item').evaluateAll((nodes) => nodes.map((node) => {
      const rect = node.getBoundingClientRect()
      return { x: rect.x, y: rect.y, width: rect.width }
    }))
    assert.equal(new Set(basicGeometry.slice(0, 4).map((item) => Math.round(item.y))).size, 1)
    assert.ok(Math.max(...basicGeometry.map((item) => item.width)) - Math.min(...basicGeometry.map((item) => item.width)) <= 2)
    assert.ok(Math.abs(basicGeometry[12].width - basicGeometry[0].width) <= 2)
    assert.ok(Math.abs(basicGeometry[13].width - basicGeometry[1].width) <= 2)
    const baseCurrencySelect = page.locator('.field-grid .el-form-item').nth(8).locator('.el-select')
    await baseCurrencySelect.click()
    await baseCurrencySelect.locator('input').fill('CNY')
    const baseCnyOption = page.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter({ hasText: /^CNY/ }).first()
    await baseCnyOption.waitFor()
    await baseCnyOption.evaluate((node) => node.dispatchEvent(new MouseEvent('click', { bubbles: true })))
    await page.waitForFunction(() => document.querySelectorAll('.el-loading-mask').length === 0, null, { timeout: 15000 })
    await page.screenshot({ path: 'qa/production_task_create_base_1920.png', fullPage: true })

    assert.equal(await page.getByRole('button', { name: '添加产品' }).count(), 0)
    assert.equal(await page.locator('.product-toolbar').count(), 0)
    assert.equal(await page.locator('.product-line-table tbody tr').count(), 1)
    assert.ok((await page.locator('.fixed-product-card').innerText()).includes('请选择产品'))
    const productHeaders = await page.locator('.product-line-table thead th').allTextContents()
    assert.equal(productHeaders[0].trim(), '明细图片')
    assert.equal(productHeaders.at(-2).trim(), '生产任务单明细')
    assert.equal(productHeaders.at(-1).trim(), '操作')
    assert.ok(!productHeaders.some((item) => item.trim() === '币种'))
    assert.ok(!productHeaders.some((item) => item.includes('订单特殊要求')))
    await page.getByRole('button', { name: '选择产品' }).click()
    const productDialog = page.getByRole('dialog', { name: '选择产品' })
    await productDialog.waitFor()
    const dialogText = await productDialog.innerText()
    for (const expected of ['产品编码', '货号', '品名', '规格', '单位']) {
      assert.ok(dialogText.includes(expected), `product dialog missing ${expected}`)
    }
    await page.screenshot({ path: 'qa/production_task_product_picker_1920.png', fullPage: true })
    await productDialog.locator('.el-table__body tbody tr').first().click()
    await productDialog.waitFor({ state: 'hidden' })
    const productSummaryText = await page.locator('.fixed-product-card').innerText()
    for (const expected of ['产品编码', '货号', '规格', '单位']) {
      assert.ok(productSummaryText.includes(expected), `selected product missing ${expected}`)
    }
    assert.equal(await page.locator('.product-block').count(), 0)
    assert.equal(await page.getByRole('button', { name: '添加产品', exact: true }).count(), 0)
    assert.equal(await page.getByRole('button', { name: '删除产品', exact: true }).count(), 0)
    const productLayout = await page.evaluate(() => {
      const card = document.querySelector('.fixed-product-card')
      const actions = document.querySelector('.fixed-product-actions')
      return {
        cardDisplay: card ? getComputedStyle(card).display : '',
        cardColumns: card ? getComputedStyle(card).gridTemplateColumns : '',
        actionsDisplay: actions ? getComputedStyle(actions).display : '',
        actionsAlign: actions ? getComputedStyle(actions).alignItems : '',
      }
    })
    assert.equal(productLayout.cardDisplay, 'grid')
    assert.equal(productLayout.actionsDisplay, 'flex')
    assert.equal(productLayout.actionsAlign, 'center')
    const productSummaryGeometry = await page.locator('.fixed-product-card').evaluate((node) => ({
      width: node.getBoundingClientRect().width,
      height: node.getBoundingClientRect().height,
    }))
    assert.equal(Math.round(productSummaryGeometry.height), 64)
    await page.locator('.fixed-product-card').screenshot({ path: 'qa/production_task_fixed_product_summary_1920.png' })

    await page.getByRole('button', { name: '明细', exact: true }).click()
    const detailDialog = page.getByRole('dialog', { name: /生产任务单明细/ })
    await detailDialog.waitFor()
    const detailText = await detailDialog.innerText()
    for (const expected of ['特殊要求', '包装方式', '明细表', '序号', '类型', '类别项', '是否', '描述', '图片']) {
      assert.ok(detailText.includes(expected), `detail dialog missing ${expected}`)
    }
    assert.ok(!detailText.includes('订单特殊要求'), 'color detail requirement should use the shorter optional label')
    const firstDetailRow = detailDialog.locator('.detail-table-wrap tbody tr').first()
    const selectionControl = firstDetailRow.locator('td').nth(3).locator('.el-select')
    const descriptionInput = firstDetailRow.locator('td').nth(4).locator('input')
    assert.ok((await selectionControl.innerText()).includes('否'))
    assert.ok(!(await selectionControl.locator('.el-select__wrapper').getAttribute('class')).includes('is-disabled'))
    await descriptionInput.fill('自动判断测试')
    assert.ok((await selectionControl.innerText()).includes('是'))
    await descriptionInput.fill('')
    assert.ok((await selectionControl.innerText()).includes('否'))
    await selectionControl.click()
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter({ hasText: /^是$/ }).click()
    assert.ok((await selectionControl.innerText()).includes('是'))
    const detailGeometry = await detailDialog.locator('.detail-table-wrap tbody tr').first().evaluate((row) => {
      const input = row.querySelector('.el-input__wrapper, .el-select__wrapper')
      return {
        rowHeight: row.getBoundingClientRect().height,
        inputHeight: input?.getBoundingClientRect().height || 0,
      }
    })
    assert.ok(detailGeometry.rowHeight <= 36, JSON.stringify(detailGeometry))
    assert.ok(detailGeometry.inputHeight <= 28.5, JSON.stringify(detailGeometry))
    await detailDialog.locator('.product-task-requirements textarea').first().fill('第一条颜色要求')
    await detailDialog.screenshot({ path: 'qa/production_task_product_details_dialog_1920.png' })
    await detailDialog.getByRole('button', { name: '完成' }).click()
    await detailDialog.waitFor({ state: 'hidden' })

    await page.locator('.fixed-product-actions').getByRole('button', { name: '添加', exact: true }).click()
    assert.equal(await page.locator('.product-line-table tbody tr').count(), 2)
    await page.locator('.product-line-table tbody tr').nth(1).getByRole('button', { name: '明细', exact: true }).click()
    await detailDialog.waitFor()
    const secondRequirement = detailDialog.locator('.product-task-requirements textarea').first()
    assert.equal(await secondRequirement.inputValue(), '')
    await secondRequirement.fill('第二条颜色要求')
    await detailDialog.getByRole('button', { name: '完成' }).click()
    await detailDialog.waitFor({ state: 'hidden' })
    await page.locator('.product-line-table tbody tr').first().getByRole('button', { name: '明细', exact: true }).click()
    await detailDialog.waitFor()
    assert.equal(
      await detailDialog.locator('.product-task-requirements textarea').first().inputValue(),
      '第一条颜色要求',
    )
    await detailDialog.getByRole('button', { name: '完成' }).click()
    await detailDialog.waitFor({ state: 'hidden' })
    await page.locator('.product-line-table tbody tr').nth(1).getByRole('button', { name: '删除', exact: true }).click()
    assert.equal(await page.locator('.product-line-table tbody tr').count(), 1)

    const firstProductRow = page.locator('.product-line-table tbody tr').first()
    for (let selectIndex = 0; selectIndex < 3; selectIndex += 1) {
      await firstProductRow.locator('.el-select').nth(selectIndex).click()
      const option = page.locator('.el-select-dropdown:visible .el-select-dropdown__item:not(.is-disabled)').first()
      await option.waitFor()
      await option.evaluate((node) => node.dispatchEvent(new MouseEvent('click', { bubbles: true })))
      await page.waitForFunction(() => Array.from(document.querySelectorAll('.el-select__popper')).every((node) => (
        getComputedStyle(node).display === 'none' || node.getAttribute('aria-hidden') === 'true'
      )))
      assert.ok(!(await firstProductRow.locator('.el-select').nth(selectIndex).locator('.el-select__wrapper').innerText()).includes('请选择'))
    }
    await firstProductRow.locator('td').nth(4).locator('input').fill('2.5')
    assert.equal(await firstProductRow.locator('td').nth(4).locator('input').inputValue(), '2')
    await firstProductRow.locator('td').nth(5).locator('input').fill('3')
    assert.equal(await firstProductRow.locator('td').nth(6).locator('input').inputValue(), '6.0000')
    assert.equal(await firstProductRow.locator('td').nth(7).locator('input').inputValue(), '1.000')
    assert.equal(await firstProductRow.locator('td').nth(8).locator('input').inputValue(), '3.0000')
    assert.equal(await firstProductRow.locator('td').nth(9).locator('input').inputValue(), '6.0000')
    const productSummary = page.locator('.product-summary-card')
    for (const expected of ['费用与汇总', '运费', '其他费用', '合计数量', '合计金额']) {
      assert.ok((await productSummary.innerText()).includes(expected), `product summary missing ${expected}`)
    }
    await productSummary.locator('input').nth(0).fill('10')
    await productSummary.locator('input').nth(1).fill('2')
    assert.equal(await productSummary.locator('input').nth(2).inputValue(), '2')
    assert.equal(await productSummary.locator('input').nth(3).inputValue(), '18.0000')
    await page.locator('.product-group').first().getByRole('button', { name: '添加', exact: true }).click()
    assert.equal(await page.locator('.product-line-table tbody tr').count(), 2)
    const alignmentGeometry = await page.evaluate(() => {
      const image = document.querySelector('.fixed-product-image')?.getBoundingClientRect()
      const firstHeader = document.querySelector('.product-line-table thead th:first-child')?.getBoundingClientRect()
      return {
        imageLeft: image?.left || 0,
        imageRight: image?.right || 0,
        headerLeft: firstHeader?.left || 0,
        headerRight: firstHeader?.right || 0,
      }
    })
    assert.ok(Math.abs(alignmentGeometry.imageLeft - alignmentGeometry.headerLeft) <= 1, JSON.stringify(alignmentGeometry))
    assert.ok(Math.abs(alignmentGeometry.imageRight - alignmentGeometry.headerRight) <= 1, JSON.stringify(alignmentGeometry))
    await page.locator('.product-line-table tbody tr').first().getByRole('button', { name: '管理明细图片' }).click()
    const imageDialog = page.getByRole('dialog', { name: '明细图片管理' })
    await imageDialog.waitFor()
    const imageDialogText = await imageDialog.innerText()
    for (const expected of ['点击或拖拽上传图片', '单张不超过 10MB', '暂无明细图片']) {
      assert.ok(imageDialogText.includes(expected), `image dialog missing ${expected}`)
    }
    const onePixelPng = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64')
    await imageDialog.locator('input[type="file"]').setInputFiles([
      { name: 'front.png', mimeType: 'image/png', buffer: onePixelPng },
      { name: 'detail.png', mimeType: 'image/png', buffer: onePixelPng },
    ])
    assert.equal(await imageDialog.locator('.image-item').count(), 2)
    assert.ok((await imageDialog.innerText()).includes('2 / 20 张'))
    await page.screenshot({ path: 'qa/production_task_detail_image_manager_1920.png', fullPage: true })
    await imageDialog.getByRole('button', { name: '查看图片' }).first().click()
    const previewDialog = page.getByRole('dialog', { name: 'front.png' })
    await previewDialog.waitFor()
    assert.equal(await previewDialog.locator('.image-preview img').count(), 1)
    await previewDialog.locator('.el-dialog__headerbtn').click()
    await previewDialog.waitFor({ state: 'hidden' })
    await imageDialog.getByRole('button', { name: '删除图片' }).last().click()
    assert.equal(await imageDialog.locator('.image-item').count(), 1)
    await imageDialog.getByRole('button', { name: '完成' }).click()
    await imageDialog.waitFor({ state: 'hidden' })
    assert.equal((await firstProductRow.getByRole('button', { name: '管理明细图片' }).innerText()).trim(), '图片')

    const productTableGeometry = await page.locator('.product-line-table').first().evaluate((node) => ({
      clientWidth: node.clientWidth,
      scrollWidth: node.scrollWidth,
    }))
    assert.ok(productTableGeometry.scrollWidth <= productTableGeometry.clientWidth + 1, JSON.stringify(productTableGeometry))
    await page.screenshot({ path: 'qa/production_task_create_products_1920.png', fullPage: true })
    const formGeometry = await page.evaluate(() => ({
      viewport: innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      pageWidth: document.querySelector('.production-form-page')?.getBoundingClientRect().width || 0,
    }))
    assert.ok(formGeometry.scrollWidth <= formGeometry.viewport + 1, JSON.stringify(formGeometry))
    assert.deepEqual(pageErrors, [])
    assert.deepEqual(httpErrors, [])
    console.log(JSON.stringify({ listGeometry, formGeometry, contractNumber, basicGeometry, detailGeometry, productLayout, productSummaryGeometry, alignmentGeometry, productTableGeometry }, null, 2))
  } finally {
    await browser.close()
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})

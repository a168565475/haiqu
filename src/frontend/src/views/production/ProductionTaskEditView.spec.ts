import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '@/api/productionTasks'
import type { ProductionTask } from '@/types/productionTask'
import ProductionTaskEditView from './ProductionTaskEditView.vue'

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { taskId: 'task-1' } }),
  useRouter: () => router,
  onBeforeRouteLeave: vi.fn(),
}))
vi.mock('@/components/InquiryWangEditor.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/api/productionTasks', () => ({
  productionTaskBusinessFileUrl: (taskId: string, fileId: string) => `/api/production/${taskId}/files/${fileId}/`,
  fetchProductionTask: vi.fn(),
  fetchProductionTaskOptions: vi.fn(),
  updateProductionTask: vi.fn(),
}))

interface EditPage {
  form: { delivery_date: string; follower_ids: string[]; special_requirements_html: string; salesperson_id: string; order_date: string; includes_tax: boolean; tax_rate: 3 | 5 | 7 | null; order_tolerance_percent: string; is_repeat_order: boolean; preproduction_sample_required: boolean; delivery_method: 'SINGLE' | 'SPLIT'; planned_start_date: string; planned_end_date: string; production_priority: string; production_batch_number: string }
  products: Array<{ quantity: string }>
  dirty: boolean
  save: () => Promise<void>
}

function legacyTask(): ProductionTask {
  return {
    id: 'task-1', task_number: 'HT-TEST', status: 'READY', status_display: '已确认',
    contract_number: 'HT-TEST', order_source: 'NEW', order_source_display: '新订单',
    customer_id: 'customer-1', delivery_method: 'SINGLE', delivery_method_display: '一次交付',
    customer_code: 'CUSTOMER-TEST', customer_name: '测试客户', order_number: 'ORDER-TEST',
    order_date: '2026-09-01', delivery_date: '2026-09-20',
    salesperson: { id: 'salesperson-1', employee_code: 'EMP-1', display_name: '业务员' },
    followers: [{ id: 'follower-old', employee_code: 'EMP-2', display_name: '跟单员' }], special_requirements_html: '',
    products: [{
      id: 'product-line-1', line_number: 1, product_id: 'product-1', product_code: 'PRODUCT-TEST',
      product_number: 'PRODUCT-TEST', item_number: '', color_card: '', image_name: null,
      product_name: '测试产品', specification: '测试规格', product_color_id: null,
      color_name: '', color_code: '', quantity: 100, unit_id: 'unit-1', unit_name: '件', unit_code: 'PCS',
      currency_id: 'currency-1', currency_code: 'CNY', unit_price: '1.0000', exchange_rate: '1.0000',
      total_amount: '100.0000', local_unit_price: '1.0000', local_total_amount: '100.0000',
      special_requirements: '', packaging_method: '', source_sales_order_line_id: null,
      source_delivery_batch_line_id: null, images: [], details: [],
    }],
    delivery_batches: [{ id: 'batch-1', line_number: 1, quantity: '100', delivery_date: '2026-09-20', note: '' }],
    freight_amount: '0', other_fee_amount: '0', product_total_amount: '100.0000', total_amount: '100.0000',
    total_quantity: '100', batch_total_quantity: '100', quantity_difference: '0',
    created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z', current_boms: [],
  }
}

async function mountPage(interactive = false) {
  const wrapper = shallowMount(ProductionTaskEditView, { global: { plugins: [ElementPlus], stubs: interactive ? { ElInput: false, ElButton: false, ElResult: false } : {} } })
  await flushPromises()
  return { wrapper, page: wrapper.vm as unknown as EditPage }
}

describe('生产任务编辑页精确保存', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.clearAllMocks()
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: legacyTask(), etag: '"task-v1"' })
    vi.mocked(api.fetchProductionTaskOptions).mockResolvedValue({ employees: [] } as never)
    vi.mocked(api.updateProductionTask).mockResolvedValue({ data: legacyTask(), etag: '"task-v2"' })
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: vi.fn() }))
    vi.spyOn(ElMessage, 'info').mockImplementation(() => ({ close: vi.fn() }))
    vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
  })

  it('旧产品缺颜色和明细时只改头日期仍仅提交日期与当前 ETag', async () => {
    const { wrapper, page } = await mountPage()
    page.form.delivery_date = '2026-09-30'

    await page.save()

    expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', { delivery_date: '2026-09-30' }, {}, {}, '"task-v1"')
    expect(ElMessageBox.confirm).toHaveBeenCalledWith(
      '保存后，待确认或已确认的任务将回到草稿，需要重新提交 PMC。',
      '确认保存修改', expect.any(Object),
    )
    expect(router.replace).toHaveBeenCalledWith({ name: 'production-task-detail', params: { taskId: 'task-1' } })
    wrapper.unmount()
  })

  it('没有修改时不发请求，改日期再还原也不保存', async () => {
    const { wrapper, page } = await mountPage()
    expect(page.dirty).toBe(false)
    await page.save()
    page.form.delivery_date = '2026-09-30'
    expect(page.dirty).toBe(true)
    page.form.delivery_date = '2026-09-20'
    expect(page.dirty).toBe(false)
    await page.save()

    expect(api.updateProductionTask).not.toHaveBeenCalled()
    expect(ElMessageBox.confirm).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('富文本编辑器初始化空段落不应误判为生产要求修改', async () => {
    const { wrapper, page } = await mountPage()
    page.form.special_requirements_html = '<p><br></p>'

    expect(page.dirty).toBe(false)
    await page.save()
    expect(api.updateProductionTask).not.toHaveBeenCalled()

    page.form.delivery_date = '2026-09-30'
    await page.save()
    expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', { delivery_date: '2026-09-30' }, {}, {}, '"task-v1"')
    wrapper.unmount()
  })

  it('清空已有生产要求时仍提交空值', async () => {
    const task = legacyTask()
    task.special_requirements_html = '<p>已有生产要求</p>'
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage()
    page.form.special_requirements_html = '<p><br></p>'

    expect(page.dirty).toBe(true)
    await page.save()
    expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', { special_requirements_html: '' }, {}, {}, '"task-v1"')
    wrapper.unmount()
  })

  it('只有勾选项的生产要求不应被当成空白', async () => {
    const { wrapper, page } = await mountPage()
    page.form.special_requirements_html = '<p><input type="checkbox"></p>'

    expect(page.dirty).toBe(true)
    await page.save()
    expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', {
      special_requirements_html: '<p><input type="checkbox"></p>',
    }, {}, {}, '"task-v1"')
    wrapper.unmount()
  })

  it('旧纯文本被编辑器包成段落不算修改，加粗后仍能保存', async () => {
    const task = legacyTask()
    task.special_requirements_html = '原有生产要求'
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage()
    page.form.special_requirements_html = '<p>原有生产要求</p>'

    expect(page.dirty).toBe(false)
    await page.save()
    expect(api.updateProductionTask).not.toHaveBeenCalled()

    page.form.special_requirements_html = '<p style="text-align:center">原有生产要求</p>'
    expect(page.dirty).toBe(true)
    await page.save()
    expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', {
      special_requirements_html: '<p style="text-align:center">原有生产要求</p>',
    }, {}, {}, '"task-v1"')

    page.form.special_requirements_html = '<p><strong>原有生产要求</strong></p>'
    expect(page.dirty).toBe(true)
    await page.save()
    expect(api.updateProductionTask).toHaveBeenLastCalledWith('task-1', {
      special_requirements_html: '<p><strong>原有生产要求</strong></p>',
    }, {}, {}, '"task-v1"')
    wrapper.unmount()
  })

  it('日期与跟单员和生产要求同时改变时保留全部修改', async () => {
    const { wrapper, page } = await mountPage()
    page.form.delivery_date = '2026-09-30'
    page.form.follower_ids = ['follower-1']
    page.form.special_requirements_html = '<p>新的生产要求</p>'

    await page.save()

    expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', {
      delivery_date: '2026-09-30', follower_ids: ['follower-1'],
      special_requirements_html: '<p>新的生产要求</p>',
    }, {}, {}, '"task-v1"')
    wrapper.unmount()
  })

  it('旧产品缺颜色时日期与数量混合修改仍受产品校验约束', async () => {
    const { wrapper, page } = await mountPage()
    page.form.delivery_date = '2026-09-30'
    page.products[0].quantity = '101'

    await page.save()

    expect(api.updateProductionTask).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalledWith('存在缺少有效颜色的历史产品行，暂不能批量修改数量。')
    expect(page.products[0].quantity).toBe('101')
    wrapper.unmount()
  })

  it('未关联手动产品使用文本颜色时可改数量并保留类别、价格和完整快照', async () => {
    const task = legacyTask()
    Object.assign(task.products[0], { product_id: null, product_category_id: 'category-1', customer_product_name: '定制面板', customer_specification: '100×200', customer_color: '自由文本红', material: '铝', exchange_rate: '1.00000000', details: [{ id: 'detail-1', client_key: 'detail-1', template_key: 'material', detail_type: '材料', category_label: '面板', is_selected: false, description: '', line_number: 1, image_name: null }] })
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage()
    page.products[0].quantity = '101'
    await page.save()
    expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', { products: [expect.objectContaining({ product_id: null, product_category_id: 'category-1', product_color_id: null, customer_product_name: '定制面板', customer_specification: '100×200', customer_color: '自由文本红', material: '铝', quantity: '101', exchange_rate: '1.00000000' })] }, {}, {}, '"task-v1"')
    wrapper.unmount()
  })

  it('合法空颜色文本不会被旧主档颜色覆盖，销售来源数量受可分配上限约束', async () => {
    const task = legacyTask()
    Object.assign(task.products[0], { customer_color: '', color_name: '旧色名', source_delivery_batch_line_id: 'source-1', max_production_quantity: 100 })
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage()
    const payload = (wrapper.vm as unknown as { productPayload: (row: ProductionTask['products'][number], quantity: string) => { customer_color: string } }).productPayload(task.products[0], '100')
    expect(payload.customer_color).toBe('')
    page.products[0].quantity = '101'
    await page.save()
    expect(api.updateProductionTask).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.stringContaining('本次生产量不能超过 100'))
    wrapper.unmount()
  })

  it('旧外币任务只展示人民币，数量保存保留原币种单价与冻结汇率', async () => {
    const task = legacyTask()
    Object.assign(task.products[0], { product_color_id: 'color', currency_id: 'usd-id', currency_code: 'USD', unit_price: '2.3456', exchange_rate: '7.12345678', local_unit_price: '16.7088', local_total_amount: '1670.8780' })
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage()
    expect(wrapper.text()).not.toContain('USD')
    expect(wrapper.text()).not.toContain('7.12345678')
    expect(wrapper.text()).toContain('1670.8780')
    page.products[0].quantity = '101'
    await flushPromises()
    expect(wrapper.text()).toContain('1687.5888')
    await page.save()
    expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', { products: [expect.objectContaining({ currency_id: 'usd-id', unit_price: '2.3456', exchange_rate: '7.12345678', quantity: '101' })] }, {}, {}, '"task-v1"')
    wrapper.unmount()
  })

  it.each(['', '2026-08-31'])('空日期或早于下单日期不能保存：%s', async (date) => {
    const { wrapper, page } = await mountPage()
    page.form.delivery_date = date

    await page.save()

    expect(api.updateProductionTask).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('请求失败时保留未保存修改，不跳走', async () => {
    vi.mocked(api.updateProductionTask).mockRejectedValueOnce(new Error('保存失败'))
    const { wrapper, page } = await mountPage()
    page.form.delivery_date = '2026-09-30'

    await page.save()

    expect(ElMessage.error).toHaveBeenCalledWith('保存失败')
    expect(page.dirty).toBe(true)
    expect(router.replace).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('旧跟单员不在候选岗位时保留姓名且不可重新选择，不自动改写原授权人', async () => {
    vi.mocked(api.fetchProductionTaskOptions).mockResolvedValue({ employees: [{ id: 'current-follower', display_name: '当前跟单', employee_code: 'E3' }] } as never)
    const { wrapper, page } = await mountPage()
    const state = wrapper.vm as unknown as { followerOptions: Array<{ id: string; display_name: string }> }
    expect(state.followerOptions.find(entry => entry.id === 'follower-old')?.display_name).toBe('跟单员')
    expect(page.form.follower_ids).toEqual(['follower-old'])
    expect(page.dirty).toBe(false)
    page.form.follower_ids = []
    await flushPromises()
    expect(state.followerOptions.map(entry => entry.id)).toEqual(['current-follower'])
    wrapper.unmount()
  })

  it('生产中任务补齐创建同名字段并保留状态，不发送编号或来源身份', async () => {
    const task = legacyTask()
    task.status = 'IN_PRODUCTION'
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage()
    Object.assign(page.form, { salesperson_id: 'sales-new', order_date: '2026-09-02', includes_tax: true, tax_rate: 5, order_tolerance_percent: '2', is_repeat_order: true, preproduction_sample_required: true, delivery_method: 'SPLIT', planned_start_date: '2026-09-03', planned_end_date: '2026-09-18', production_priority: 'HIGH', production_batch_number: 'B-01' })
    await page.save()
    expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', expect.objectContaining({ salesperson_id: 'sales-new', order_date: '2026-09-02', includes_tax: true, tax_rate: 5, order_tolerance_percent: '2', is_repeat_order: true, preproduction_sample_required: true, delivery_method: 'SPLIT', planned_start_date: '2026-09-03', planned_end_date: '2026-09-18', production_priority: 'HIGH', production_batch_number: 'B-01' }), {}, {}, '"task-v1"')
    const patch = vi.mocked(api.updateProductionTask).mock.calls[0][1]
    expect(patch).not.toHaveProperty('planner_id')
    expect(patch).not.toHaveProperty('task_number')
    expect(patch).not.toHaveProperty('sales_order_id')
    expect(ElMessageBox.confirm).toHaveBeenCalledWith(expect.stringContaining('保留当前生产状态'), '确认保存修改', expect.any(Object))
    wrapper.unmount()
  })

  it('含税必须选择税率，切回不含税清空税率并提交null', async () => {
    const task = legacyTask()
    task.includes_tax = true
    task.tax_rate = 3
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage()
    page.form.tax_rate = null
    await page.save()
    expect(api.updateProductionTask).not.toHaveBeenCalled()
    page.form.includes_tax = false
    await flushPromises()
    expect(page.form.tax_rate).toBeNull()
    await page.save()
    expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', { includes_tax: false, tax_rate: null }, {}, {}, '"task-v1"')
    wrapper.unmount()
  })

  it('跟单员必填，生产暂停任务仍可编辑', async () => {
    const task = legacyTask()
    task.status = 'PAUSED'
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage()
    page.form.follower_ids = []
    await page.save()
    expect(api.updateProductionTask).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalledWith('请选择至少一名跟单员。')
    page.form.follower_ids = ['new-follower']
    await page.save()
    expect(api.updateProductionTask).toHaveBeenCalled()
    expect(ElMessageBox.confirm).toHaveBeenCalledWith(expect.stringContaining('保留当前生产状态'), '确认保存修改', expect.any(Object))
    wrapper.unmount()
  })

  it('手动产品修改人民币单价仍保留原行、全部图片与19类明细标识', async () => {
    const task = legacyTask()
    task.products[0].product_color_id = 'color'
    task.products[0].images = [{ id: 'image-1', name: '原图', content_type: 'image/png', size_bytes: 10 }, { id: 'image-2', name: '次图', content_type: 'image/png', size_bytes: 10 }]
    task.products[0].details = Array.from({ length: 19 }, (_, index) => ({ id: `detail-${index}`, client_key: `detail-${index}`, template_key: `template-${index}`, detail_type: `类型${index}`, category_label: '类别', is_selected: true, description: `要求${index}`, line_number: index + 1, image_name: '已有明细图' }))
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage()
    ;(page.products[0] as unknown as { unitPriceCny: string }).unitPriceCny = '3.0000'
    await page.save()
    const payload = vi.mocked(api.updateProductionTask).mock.calls[0][1].products![0]
    expect(payload).toMatchObject({ client_key: 'product-line-1', unit_price: '3.0000', retained_image_ids: ['image-1', 'image-2'] })
    expect(payload.details).toHaveLength(19)
    expect(payload.details[18]).toMatchObject({ client_key: 'detail-18', template_key: 'template-18', description: '要求18' })
    wrapper.unmount()
  })

  it('销售来源仅提交数量变化，产品与价格继续使用原始快照', async () => {
    const task = legacyTask()
    task.sales_order_id = 'sales-1'
    Object.assign(task.products[0], { product_color_id: 'color', source_delivery_batch_line_id: 'source', max_production_quantity: 120 })
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage()
    page.products[0].quantity = '110'
    Object.assign(page.form, { salesperson_id: 'tamper', order_date: '2026-09-02' })
    await page.save()
    const patch = vi.mocked(api.updateProductionTask).mock.calls[0][1]
    expect(patch).not.toHaveProperty('salesperson_id')
    expect(patch).not.toHaveProperty('order_date')
    expect(patch.products![0]).toMatchObject({ client_key: 'product-line-1', quantity: '110', unit_price: '1.0000' })
    wrapper.unmount()
  })

  it('复用产品选择器保存资料时沿用原行ID并保留图片和未改动明细', async () => {
    const task = legacyTask()
    Object.assign(task.products[0], { product_number: 'PRODUCT-SNAPSHOT-001', product_category_id: 'category-1', product_color_id: 'color', images: [{ id: 'old-image', name: '旧图', content_type: 'image/png', size_bytes: 10 }], details: [{ id: 'detail-1', client_key: 'detail-1', template_key: 'type-1', detail_type: '生产', category_label: '项目', is_selected: true, description: '原要求', line_number: 1, image_name: '原明细图片' }] })
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    vi.mocked(api.fetchProductionTaskOptions).mockResolvedValue({ employees: [], currencies: [{ id: 'currency-1', code: 'CNY', name: '人民币', symbol: '¥' }], units: [{ id: 'unit-1', unit_code: 'PCS', unit_name: '件' }], colors: [], products: [{ id: 'product-2', product_number: 'PRODUCT-CURRENT-002', product_name: '更新产品名称', specification: '100×200', item_number: 'ITEM-002' }], detail_template: [] } as never)
    const { wrapper, page } = await mountPage()
    const editor = wrapper.vm as unknown as { editProduct: (row: unknown) => void; editorDetails: Array<{ description: string }>; editorItem: import('@/types/inquiry').InquiryItem; confirmProduct: (value: unknown) => void }
    editor.editProduct(page.products[0])
    expect(editor.editorItem.product_number_snapshot).toBe('PRODUCT-SNAPSHOT-001')
    editor.editorDetails[0].description = '新的生产要求'
    editor.confirmProduct({ item: { ...editor.editorItem, product_id: 'product-2', product_description: '更新产品名称', specification: '100×200', material: '铝', color: '红', target_unit_price: '4.5' }, imageChanged: false, imageFile: null, removeImage: false })
    editor.editProduct(page.products[0])
    expect(editor.editorItem.product_number_snapshot).toBe('PRODUCT-CURRENT-002')
    await page.save()
    const payload = vi.mocked(api.updateProductionTask).mock.calls[0][1].products![0]
    expect(payload).toMatchObject({ client_key: 'product-line-1', product_id: 'product-2', customer_product_name: '更新产品名称', customer_specification: '100×200', material: '铝', customer_color: '红', unit_id: 'unit-1', currency_id: 'currency-1', unit_price: '4.5', retained_image_ids: ['old-image'] })
    expect(payload).not.toHaveProperty('product_number_snapshot')
    expect(payload.details).toEqual([{ client_key: 'detail-1', template_key: 'type-1', detail_type: '生产', category_label: '项目', is_selected: true, description: '新的生产要求' }])
    wrapper.unmount()
  })

  it('存在下游约束的手动行禁止删除，并展示接口真实原因', async () => {
    const task = legacyTask()
    task.products[0].deletion_blocked_reason = '该产品已有排产记录，不能删除。'
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage()
    expect(wrapper.text()).toContain('该产品已有排产记录，不能删除。')
    ;(wrapper.vm as unknown as { removeProduct: (row: unknown) => void }).removeProduct(page.products[0])
    expect(page.products).toHaveLength(1)
    expect(page.dirty).toBe(false)
    wrapper.unmount()
  })

  it('真实销售建单的文本颜色和空生产明细允许在上限内修改数量', async () => {
    const task = legacyTask()
    task.sales_order_id = 'sales-1'
    Object.assign(task.products[0], { source_delivery_batch_line_id: 'source-batch-line', source_sales_order_line_id: 'source-order-line', product_color_id: null, customer_product_name: '销售定制产品', customer_specification: '100×200', customer_color: '深宝蓝', details: [], max_production_quantity: 120 })
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage()
    page.products[0].quantity = '110'
    await page.save()
    expect(ElMessage.warning).not.toHaveBeenCalled()
    expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', { products: [expect.objectContaining({ client_key: 'product-line-1', quantity: '110', product_color_id: null, customer_color: '深宝蓝', details: [], unit_price: '1.0000', exchange_rate: '1.0000' })] }, {}, {}, '"task-v1"')
    wrapper.unmount()
  })

  it('多图产品未保存时连续更换主图仍保留附图并发送主图替换标记', async () => {
    const task = legacyTask()
    Object.assign(task.products[0], { product_color_id: 'color', images: [{ id: 'main-A', name: '主图A', content_type: 'image/png', size_bytes: 10 }, { id: 'extra-B', name: '附图B', content_type: 'image/png', size_bytes: 10 }] })
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    vi.mocked(api.fetchProductionTaskOptions).mockResolvedValue({ employees: [], currencies: [{ id: 'currency-1', code: 'CNY' }], units: [{ id: 'unit-1', unit_code: 'PCS', unit_name: '件' }], colors: [], products: [], detail_template: [] } as never)
    const originalCreate = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
    const originalRevoke = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL')
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: () => 'blob:new-image' })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    const { wrapper, page } = await mountPage()
    try {
      const editor = wrapper.vm as unknown as { editProduct: (row: unknown) => void; editorItem: import('@/types/inquiry').InquiryItem; confirmProduct: (value: unknown) => void }
      editor.editProduct(page.products[0])
      const firstImage = new File(['first-image'], 'C.png', { type: 'image/png' })
      editor.confirmProduct({ item: editor.editorItem, imageChanged: true, imageFile: firstImage, removeImage: false })
      editor.editProduct(page.products[0])
      const image = new File(['new-image'], 'D.png', { type: 'image/png' })
      editor.confirmProduct({ item: editor.editorItem, imageChanged: true, imageFile: image, removeImage: false })
      await page.save()
      expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', { products: [expect.objectContaining({ client_key: 'product-line-1', replace_primary_image: true, retained_image_ids: ['extra-B'] })] }, { 'product-line-1': [image] }, {}, '"task-v1"')
    } finally {
      wrapper.unmount()
      if (originalCreate) Object.defineProperty(URL, 'createObjectURL', originalCreate)
      else Reflect.deleteProperty(URL, 'createObjectURL')
      if (originalRevoke) Object.defineProperty(URL, 'revokeObjectURL', originalRevoke)
      else Reflect.deleteProperty(URL, 'revokeObjectURL')
    }
  })

  it('真实JSON数字人民币金额进入编辑时转四位字符串，未修改时不误报dirty', async () => {
    const task = legacyTask()
    Object.assign(task.products[0], { local_unit_price: 15, local_total_amount: 40 })
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage()
    expect(page.dirty).toBe(false)
    expect((page.products[0] as unknown as { unitPriceCny: string }).unitPriceCny).toBe('15.0000')
    expect(wrapper.text()).toContain('40.0000')
    expect(wrapper.find('.page-heading').text()).not.toContain('保存修改')
    expect(wrapper.find('.edit-footer').exists()).toBe(true)
    await page.save()
    expect(api.updateProductionTask).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('数字金额15和40的真实响应修改数量后能保存且人民币合计2040', async () => {
    const task = legacyTask()
    Object.assign(task.products[0], { product_color_id: 'color-1', unit_price: '15.0000', local_unit_price: 15, local_total_amount: 1500 })
    task.products.push({ ...task.products[0], id: 'line-2', line_number: 2, product_color_id: 'color-2', quantity: 12, unit_price: '40.0000', local_unit_price: 40, local_total_amount: 480 } as unknown as ProductionTask['products'][number])
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage()
    expect(page.dirty).toBe(false)
    page.products[0].quantity = '104'
    await flushPromises()
    expect(wrapper.find('.edit-summary').text()).toContain('2040.0000')
    await page.save()
    expect(ElMessage.warning).not.toHaveBeenCalled()
    expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', { products: [expect.objectContaining({ client_key: 'product-line-1', quantity: '104', unit_price: '15.0000' }), expect.objectContaining({ client_key: 'line-2', quantity: '12', unit_price: '40.0000' })] }, {}, {}, '"task-v1"')
    wrapper.unmount()
  })

  it('产品档案默认只展开首项，逐项操作不出现索引或展开全部入口', async () => {
    const task = legacyTask()
    task.products.push({ ...task.products[0], id: 'product-line-2', line_number: 2, product_name: '测试桌' })
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper } = await mountPage(true)
    try {
      const files = wrapper.findAll('details.product-file')
      expect(files).toHaveLength(2)
      expect(files.map(file => (file.element as HTMLDetailsElement).open)).toEqual([true, false])
      expect(files.map(file => file.get('summary.product-summary').text())).toEqual([
        expect.stringContaining('测试产品'), expect.stringContaining('测试桌'),
      ])
      expect(wrapper.find('.product-index').exists()).toBe(false)
      expect(wrapper.text()).not.toContain('产品索引')
      expect(wrapper.findAll('button').some(button => /展开全部|全部展开|收起全部|全部收起/.test(button.text()))).toBe(false)
    } finally { wrapper.unmount() }
  })

  it('逐项收合和展开保留数量价格包装输入、变更对照及保存内容', async () => {
    const task = legacyTask()
    task.products[0].product_color_id = 'color-1'
    task.products.push({ ...task.products[0], id: 'product-line-2', line_number: 2, product_name: '测试桌' })
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage(true)
    try {
      expect(wrapper.findAll('details.product-file')).toHaveLength(2)
      const [first, second] = wrapper.findAll('details.product-file')
      await first.get('input[aria-label="测试产品本次生产量"]').setValue('101')
      await first.get('input[aria-label="人民币单价"]').setValue('2.5000')
      await first.get('[aria-label="包装要求"]').setValue('每箱两件，增加护角')
      const changesBefore = wrapper.get('.comparison-card').text()
      expect(changesBefore).toContain('101 件')
      expect(changesBefore).toContain('产品资料已修改')

      await first.get('summary.product-summary').trigger('click')
      await second.get('summary.product-summary').trigger('click')
      await flushPromises()
      expect([first, second].map(file => (file.element as HTMLDetailsElement).open)).toEqual([false, true])
      await first.get('summary.product-summary').trigger('click')
      await flushPromises()

      expect((first.get('input[aria-label="测试产品本次生产量"]').element as HTMLInputElement).value).toBe('101')
      expect((first.get('input[aria-label="人民币单价"]').element as HTMLInputElement).value).toBe('2.5000')
      expect((first.get('[aria-label="包装要求"]').element as HTMLInputElement).value).toBe('每箱两件，增加护角')
      expect(wrapper.get('.comparison-card').text()).toBe(changesBefore)
      expect(page.dirty).toBe(true)
      await page.save()
      expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', {
        products: [
          expect.objectContaining({ client_key: 'product-line-1', quantity: '101', unit_price: '2.5000', packaging_method: '每箱两件，增加护角' }),
          expect.objectContaining({ client_key: 'product-line-2', quantity: '100', unit_price: '1.0000' }),
        ],
      }, {}, {}, '"task-v1"')
    } finally { wrapper.unmount() }
  })

  it('新增产品确认后展开新档案，原有未保存输入继续保留', async () => {
    vi.mocked(api.fetchProductionTaskOptions).mockResolvedValue({ employees: [], currencies: [{ id: 'currency-1', code: 'CNY' }], units: [{ id: 'unit-1', unit_code: 'PCS', unit_name: '件' }], colors: [], products: [], detail_template: [] } as never)
    const { wrapper, page } = await mountPage(true)
    try {
      expect(wrapper.findAll('details.product-file')).toHaveLength(1)
      await wrapper.get('details.product-file [aria-label="包装要求"]').setValue('保留原产品包装修改')
      await wrapper.findAll('button').find(button => button.text().includes('添加产品'))!.trigger('click')
      const editor = wrapper.vm as unknown as { editorVisible: boolean; editorItem: import('@/types/inquiry').InquiryItem; confirmProduct: (value: unknown) => void }
      expect(editor.editorVisible).toBe(true)
      editor.confirmProduct({ item: { ...editor.editorItem, product_description: '新增生产产品', specification: '60×80', unit_code: 'PCS', quantity: '5', target_unit_price: '8.0000' }, imageChanged: false, imageFile: null, removeImage: false })
      await flushPromises()

      const files = wrapper.findAll('details.product-file')
      expect(files).toHaveLength(2)
      expect(files[1].get('summary.product-summary').text()).toContain('新增生产产品')
      expect((files[1].element as HTMLDetailsElement).open).toBe(true)
      expect((files[1].get('input[aria-label="新增生产产品本次生产量"]').element as HTMLInputElement).value).toBe('5')
      expect((files[0].get('[aria-label="包装要求"]').element as HTMLInputElement).value).toBe('保留原产品包装修改')
      expect(page.dirty).toBe(true)
      expect(api.updateProductionTask).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })

  it('销售来源档案仍锁定价格包装和增删，只允许上限内数量调整', async () => {
    const task = legacyTask()
    task.sales_order_id = 'sales-1'
    Object.assign(task.products[0], { product_color_id: 'color-1', source_delivery_batch_line_id: 'source-1', max_production_quantity: 120 })
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage(true)
    try {
      expect(wrapper.findAll('details.product-file')).toHaveLength(1)
      const file = wrapper.get('details.product-file')
      const quantity = file.get('input[aria-label="测试产品本次生产量"]')
      expect((quantity.element as HTMLInputElement).disabled).toBe(false)
      expect(file.find('input[aria-label="人民币单价"]').exists()).toBe(false)
      expect((file.get('[aria-label="包装要求"]').element as HTMLInputElement).disabled).toBe(true)
      expect((file.get('[aria-label="产品生产要求"]').element as HTMLInputElement).disabled).toBe(true)
      expect(wrapper.findAll('button').some(button => /添加产品|编辑产品|删除产品/.test(button.text()))).toBe(false)
      await quantity.setValue('121')
      await page.save()
      expect(api.updateProductionTask).not.toHaveBeenCalled()
      expect(ElMessage.warning).toHaveBeenCalledWith(expect.stringContaining('本次生产量不能超过 120'))
      await quantity.setValue('120')
      await page.save()
      expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', { products: [expect.objectContaining({ client_key: 'product-line-1', quantity: '120', unit_price: '1.0000' })] }, {}, {}, '"task-v1"')
    } finally { wrapper.unmount() }
  })

  it.each(['COMPLETED', 'CANCELLED'] as const)('终态 %s 档案可查看但产品输入和修改操作保持禁用', async status => {
    const task = legacyTask()
    task.status = status
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage(true)
    try {
      expect(wrapper.findAll('details.product-file')).toHaveLength(1)
      const file = wrapper.get('details.product-file')
      for (const label of ['测试产品本次生产量', '人民币单价', '包装要求', '产品生产要求']) {
        expect((file.get(`[aria-label="${label}"]`).element as HTMLInputElement).disabled).toBe(true)
      }
      const actions = wrapper.findAll('button').filter(button => /添加产品|编辑产品|删除|保存修改/.test(button.text()))
      expect(actions.length).toBeGreaterThanOrEqual(3)
      expect(actions.every(button => (button.element as HTMLButtonElement).disabled)).toBe(true)
      page.form.delivery_date = '2026-09-30'
      await page.save()
      expect(api.updateProductionTask).not.toHaveBeenCalled()
      expect(ElMessage.warning).toHaveBeenCalledWith('已完成或已取消的任务不能编辑。')
    } finally { wrapper.unmount() }
  })

  it('空产品接口响应显示明确空态，修改其他字段后仍不能保存无产品任务', async () => {
    // 组件测试响应覆盖空列表边界，不代表真实环境已有该业务样本。
    const task = legacyTask()
    Object.assign(task, { products: [], delivery_batches: [], total_quantity: '0', product_total_amount: '0.0000', total_amount: '0.0000' })
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage(true)
    try {
      expect(wrapper.get('.empty-products').text()).toContain('暂无产品，请添加真实产品或自定义产品。')
      expect(wrapper.findAll('details.product-file')).toHaveLength(0)
      expect(wrapper.findAll('button').some(button => button.text() === '添加产品' && !(button.element as HTMLButtonElement).disabled)).toBe(true)
      page.form.delivery_date = '2026-09-30'
      await flushPromises()
      await wrapper.findAll('.edit-footer button').find(button => button.text() === '保存修改')!.trigger('click')
      await flushPromises()
      expect(api.updateProductionTask).not.toHaveBeenCalled()
      expect(ElMessageBox.confirm).not.toHaveBeenCalled()
      expect(ElMessage.warning).toHaveBeenCalledWith('请至少保留一个产品。')
      expect(page.form.delivery_date).toBe('2026-09-30')
    } finally { wrapper.unmount() }
  })

  it('初始读取失败显示错误和重试入口，重试成功恢复首产品默认展开', async () => {
    const task = legacyTask()
    task.products.push({ ...task.products[0], id: 'product-line-2', line_number: 2, product_name: '重试返回的第二产品' })
    vi.mocked(api.fetchProductionTask)
      .mockRejectedValueOnce(new Error('任务读取失败，请重试。'))
      .mockResolvedValueOnce({ data: task, etag: '"task-v2"' })
    const { wrapper } = await mountPage(true)
    try {
      expect(wrapper.get('.el-result').text()).toContain('生产任务单加载失败')
      expect(wrapper.get('.el-result').text()).toContain('任务读取失败，请重试。')
      expect(wrapper.find('.edit-summary').exists()).toBe(false)
      expect(wrapper.findAll('details.product-file')).toHaveLength(0)
      expect(api.fetchProductionTask).toHaveBeenCalledTimes(1)
      await wrapper.findAll('button').find(button => button.text() === '重新加载')!.trigger('click')
      await flushPromises()

      expect(api.fetchProductionTask).toHaveBeenCalledTimes(2)
      expect(api.fetchProductionTask).toHaveBeenLastCalledWith('task-1')
      expect(wrapper.find('.el-result').exists()).toBe(false)
      const files = wrapper.findAll('details.product-file')
      expect(files).toHaveLength(2)
      expect(files.map(file => (file.element as HTMLDetailsElement).open)).toEqual([true, false])
      expect(files[1].get('summary.product-summary').text()).toContain('重试返回的第二产品')
      expect(api.updateProductionTask).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })

})

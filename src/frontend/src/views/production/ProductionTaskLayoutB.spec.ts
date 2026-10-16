import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, it, expect, vi } from 'vitest'
import * as api from '@/api/productionTasks'
import ProductionTaskCreateView from './ProductionTaskCreateView.vue'
const route = vi.hoisted(() => ({ query: {} as Record<string, string>, name: 'production-task-create' }))
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => router }))
vi.mock('@/api/productionTasks', async original => ({ ...await original<typeof import('@/api/productionTasks')>(), fetchProductionTaskOptions: vi.fn().mockResolvedValue({ employees: [], currencies: [], colors: [], units: [] }), fetchProductionSalesOrderSource: vi.fn(), fetchProductionSalesOrderSources: vi.fn().mockResolvedValue({ data: [] }), reserveProductionTaskContractNumber: vi.fn().mockResolvedValue({ contract_number: 'CONTRACT-1', token: 'reserved' }), createProductionTask: vi.fn().mockResolvedValue({ data: { id: 'saved' }, etag: 'v1' }) }))
vi.mock('@/api/productionData', () => ({ fetchAllProductionDataRecords: vi.fn().mockResolvedValue([]) }))
describe('B布局创建行为', () => {
  beforeEach(() => { route.name = 'production-task-create'; route.query = {}; vi.clearAllMocks() })
  it('从销售订单进入只读取当前订单，未选择订单仍显示真实名称', async () => {
    route.query = { sales_order_id: 'source-order', delivery_batch_id: 'batch' }
    vi.mocked(api.fetchProductionSalesOrderSource).mockResolvedValue({ data: { id: 'source-order', status: 'CONFIRMED', product_names: ['真实产品'], total_amount_cny: '7.0000', lines: [], delivery_batches: [{ id: 'batch', status: 'ACTIVE', lines: [] }] } } as never)
    const wrapper = shallowMount(ProductionTaskCreateView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const page = wrapper.vm as any
    expect(api.fetchProductionSalesOrderSources).not.toHaveBeenCalled()
    expect(page.orderChoices.map((item: any) => item.id)).toEqual(['source-order'])
    expect(wrapper.find('.search-row').exists()).toBe(false)
    expect(page.sourceProductText({ id: 'other', product_names: ['另一产品'] })).toBe('另一产品')
    await page.selectSourceOrder('other')
    expect(page.selectedOrderId).toBe('source-order')
    wrapper.unmount()
  })
  it('当前来源已分配完成时明确报错，不回退其他订单', async () => {
    route.query = { sales_order_id: 'completed-order' }
    vi.mocked(api.fetchProductionSalesOrderSource).mockResolvedValue({ data: { id: 'completed-order', status: 'CONFIRMED', has_remaining_production_capacity: false } } as never)
    const wrapper = shallowMount(ProductionTaskCreateView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const page = wrapper.vm as any
    expect(page.orderChoices).toEqual([])
    expect(page.sourceLoadError).toContain('已分配完成')
    expect(api.fetchProductionSalesOrderSources).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('切换手动创建再返回时保留当前销售订单上下文', async () => {
    route.name = 'production-task-manual-create'
    route.query = { sales_order_id: 'current-order', delivery_batch_id: 'current-batch' }
    const wrapper = shallowMount(ProductionTaskCreateView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    await wrapper.findAll('.creation-modes button')[0]!.trigger('click')
    expect(router.push).toHaveBeenCalledWith({ name: 'production-task-create', query: { sales_order_id: 'current-order', delivery_batch_id: 'current-batch' } })
    await wrapper.findAll('.creation-modes button')[1]!.trigger('click')
    expect(router.push).toHaveBeenLastCalledWith({ name: 'production-task-manual-create', query: { sales_order_id: 'current-order', delivery_batch_id: 'current-batch' } })
    wrapper.unmount()
  })
  it('生产金额使用已保存人民币单价，不能再次乘外币汇率', async () => {
    const wrapper = shallowMount(ProductionTaskCreateView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const page = wrapper.vm as any
    page.order = { currency_code: 'USD', total_amount_cny: '14', production_exchange_rate: { rate: '7' }, lines: [{ id: 'line', unit_price: '1', unit_price_cny: '7' }], delivery_batches: [{ id: 'batch', status: 'ACTIVE', lines: [{ id: 'source', sales_order_line_id: 'line' }] }] }
    page.selectedBatchId = 'batch'
    page.colorLines = [{ sourceLineId: 'source', quantity: 2 }]
    expect(page.currentAmount).toBe('14.0000')
    expect(page.sourceAmountsReady).toBe(true)
    wrapper.unmount()
  })
  it('来源第一步不要求提前填写HT', async () => {
    const wrapper = shallowMount(ProductionTaskCreateView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const page = wrapper.vm as any
    page.order = { id: 'order', lines: [], delivery_batches: [{ id: 'batch', status: 'ACTIVE', lines: [] }] }
    page.selectedBatchId = 'batch'
    page.nextStep()
    expect(page.activeStep).toBe(2)
    expect(page.money(undefined)).toBe('—')
    expect(page.money('0')).toBe('0.00')
    wrapper.unmount()
  })
  it('来源客户颜色为空时只读显示真实主档颜色，客户快照优先且不被改写', async () => {
    const wrapper = shallowMount(ProductionTaskCreateView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const page = wrapper.vm as any
    page.options = { colors: [{ id: 'color-real', color_name: '正式红' }], employees: [] }
    page.order = { id: 'order', lines: [{ id: 'line', customer_color_snapshot: '', product_color_id: 'color-real' }], delivery_batches: [{ id: 'batch', status: 'ACTIVE', lines: [{ id: 'source', sales_order_line_id: 'line', product_name: '面板' }] }] }
    page.selectedBatchId = 'batch'
    page.colorLines = [{ key: 'draft', sourceLineId: 'source', quantity: 1, specialRequirements: '', packagingMethod: '' }]
    page.activeStep = 3
    await flushPromises()
    expect(wrapper.text()).toContain('正式红')
    expect(page.order.lines[0].customer_color_snapshot).toBe('')
    expect(page.order.lines[0].product_color_id).toBe('color-real')
    page.order.lines[0].customer_color_snapshot = '客户指定红'
    await flushPromises()
    expect(wrapper.text()).toContain('客户指定红')
    expect(wrapper.text()).not.toContain('正式红')
    wrapper.unmount()
  })
  it('来源未保存人民币金额时不进入生产安排', async () => {
    const wrapper = shallowMount(ProductionTaskCreateView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const page = wrapper.vm as any
    page.order = { currency_code: 'USD', production_exchange_rate: null, lines: [], delivery_batches: [{ id: 'b', status: 'ACTIVE', lines: [{ id: 'l', remaining_quantity: 10 }] }] }
    page.selectedBatchId = 'b'; page.activeStep = 2
    page.colorLines = [{ key: 'k', sourceLineId: 'l', quantity: 1, specialRequirements: '', packagingMethod: '' }]
    page.nextStep()
    expect(page.activeStep).toBe(2)
    wrapper.unmount()
  })
})

describe('内嵌销售产品录入保存', () => {
  it('未关联产品可保存真实单位、人民币价格、图片及计划安排', async () => {
    route.name = 'production-task-manual-create'
    const wrapper = shallowMount(ProductionTaskCreateView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const page = wrapper.vm as any
    page.catalogUnits = [{ id: 'unit-1', unit_code: '03', unit_name: '张' }]
    page.options = { currencies: [{ id: 'cny', code: 'CNY' }], detail_template: [{ key: 'material', type: '材料', category: '面料' }] }
    URL.createObjectURL = vi.fn().mockReturnValue('blob:test-product')
    URL.revokeObjectURL = vi.fn()
    const file = new File(['image'], 'product.png', { type: 'image/png' })
    const item = { product_category_id: 'category-real', product_id: null, product_description: '定制面板', specification: '100×200', color: '红', material: '铝', quantity: '3', product_unit_id: 'unit-1', unit_code: '03', target_unit_price: '12.3456', notes: '无毛刺' }
    page.confirmManual({ item, imageChanged: true, imageFile: file, removeImage: false })
    expect(page.manualProducts).toHaveLength(1)
    page.editManual(page.manualProducts[0])
    page.confirmManual({ item: { ...item, material: '铝合金' }, imageChanged: false, imageFile: null, removeImage: false })
    expect(page.manualProducts).toHaveLength(1)
    expect(page.manualProducts[0].file).toBe(file)
    page.taskNumberSuffix = '26201'
    Object.assign(page.plan, { orderDate: '2026-10-15', deliveryDate: '2026-11-15', followerIds: ['follower'], salespersonId: 'sales', includesTax: true, taxRate: 5, plannedStartDate: '2026-10-16', plannedEndDate: '2026-11-10' })
    await page.saveManual()
    expect(api.createProductionTask).toHaveBeenCalledWith(expect.objectContaining({ task_number: 'HT26201', follower_ids: ['follower'], tax_rate: 5, planned_start_date: '2026-10-16', products: [expect.objectContaining({ product_id: null, product_category_id: 'category-real', customer_product_name: '定制面板', material: '铝合金', unit_id: 'unit-1', unit_price: '12.3456', exchange_rate: '1.00000000', details: [expect.objectContaining({ template_key: 'material', detail_type: '材料', category_label: '面料', is_selected: false, description: '' })] })] }), expect.any(Object), {})
    const imagePayload = vi.mocked(api.createProductionTask).mock.calls.at(-1)![1]!
    expect(Object.values(imagePayload)[0]).toEqual([file])
    wrapper.unmount()
  })
  it('不把自由文本单位或小数生产数量伪装为已确认产品', async () => {
    route.name = 'production-task-manual-create'
    const wrapper = shallowMount(ProductionTaskCreateView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const page = wrapper.vm as any
    page.catalogUnits = [{ id: 'unit-1', unit_code: '03', unit_name: '张' }]
    page.confirmManual({ item: { unit_code: '未知单位', quantity: '2' }, imageChanged: false, imageFile: null })
    expect(page.manualProducts).toHaveLength(0)
    page.confirmManual({ item: { product_unit_id: 'unit-1', quantity: '1.5' }, imageChanged: false, imageFile: null })
    expect(page.manualProducts).toHaveLength(0)
    wrapper.unmount()
  })
})

it('生产候选只使用有权限的生产options真实产品，不依赖产品管理接口', async () => {
  route.name = 'production-task-manual-create'
  const wrapper = shallowMount(ProductionTaskCreateView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  const page = wrapper.vm as any
  page.options = { categories: [{ id: 'category', category_name: '成品' }], units: [{ id: 'unit', unit_code: '03', unit_name: '张' }], colors: [], products: [{ id: 'real-product', category_id: 'category', product_number: 'P1', product_code: 'CODE', item_number: 'ITEM', product_name: '面板', specification: '20×30', default_unit_id: 'unit', unit_code: '03', unit_name: '张' }] }
  await page.loadCatalog()
  const result = await page.loadProductionCandidates('category')
  expect(result.groups[0].specifications[0].products[0]).toMatchObject({ id: 'real-product', category_id: 'category', unit_id: 'unit', unit_name: '张', item_number: 'ITEM' })
  expect(page.catalogError).toBe('')
  wrapper.unmount()
})

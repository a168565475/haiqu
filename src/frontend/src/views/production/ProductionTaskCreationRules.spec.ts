import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/productionTasks'
import * as salesApi from '@/api/salesOrders'
import ProductionTaskFormView from './ProductionTaskFormView.vue'
import ProductionTaskDetailView from './ProductionTaskDetailView.vue'
import ProductionTaskCreateView from './ProductionTaskCreateView.vue'

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: {}, query: {}, name: 'production-task-create' }), useRouter: () => router }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/components/InquiryWangEditor.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/api/salesOrders', () => ({ fetchSalesOrders: vi.fn().mockResolvedValue({ data: [] }), fetchSalesOrder: vi.fn() }))
vi.mock('@/api/productionTasks', async original => ({
  ...await original<typeof import('@/api/productionTasks')>(),
  fetchProductionTaskOptions: vi.fn(), reserveProductionTaskContractNumber: vi.fn(),
  fetchProductionSalesOrderSources: vi.fn(), fetchProductionSalesOrderSource: vi.fn(),
  createProductionTask: vi.fn(), createProductionOrderFromSalesOrder: vi.fn(), fetchProductionTask: vi.fn(), decideProductionTaskByPmc: vi.fn(),
}))

describe('生产建单与独立跟单员', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchProductionTaskOptions).mockResolvedValue({ employees: [], products: [], colors: [], currencies: [], units: [], detail_template: [], recent_task_numbers: ['HT26198'] } as never)
    vi.mocked(api.reserveProductionTaskContractNumber).mockResolvedValue({ contract_number: 'HT-2026-001', token: 'reservation' })
    vi.mocked(api.fetchProductionSalesOrderSources).mockResolvedValue({ data: [] } as never)
    vi.mocked(api.fetchProductionSalesOrderSources).mockResolvedValue({ data: [] } as never)
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: vi.fn() }))
  })

  it('没有销售订单时仍展示手动创建入口', async () => {
    const wrapper = shallowMount(ProductionTaskCreateView, { global: { plugins: [ElementPlus], stubs: { ElButton: { name: 'ElButton', template: '<button><slot /></button>' } } } })
    await flushPromises()
    const manual = wrapper.findAll('button').find(button => button.text().includes('手动创建'))
    expect(manual).toBeDefined()
    await manual!.trigger('click')
    expect(router.push).toHaveBeenCalledWith({ name: 'production-task-manual-create', query: {} })
    wrapper.unmount()
  })

  it('只有工厂权限时通过生产专用来源接口读取，不调用销售订单接口', async () => {
    vi.mocked(salesApi.fetchSalesOrders).mockRejectedValue(new Error('无销售模块权限'))
    vi.mocked(api.fetchProductionSalesOrderSources).mockResolvedValue({ data: [] } as never)
    const wrapper = shallowMount(ProductionTaskCreateView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(api.fetchProductionSalesOrderSources).toHaveBeenCalledWith(undefined)
    expect(salesApi.fetchSalesOrders).not.toHaveBeenCalled()
    expect(salesApi.fetchSalesOrder).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('手动建单不要求客户，必须填写自己的跟单员', async () => {
    const wrapper = shallowMount(ProductionTaskFormView, { global: { plugins: [ElementPlus], stubs: { ElButton: { name: 'ElButton', template: '<button><slot /></button>' } } } })
    await flushPromises()
    const page = wrapper.vm as unknown as { form: Record<string, unknown>; validate: () => string }
    Object.assign(page.form, { task_number_suffix: '26199', order_number: 'HT26199', order_date: '2026-10-15', delivery_date: '2026-11-15', salesperson_id: 'sales-1', currency_id: 'cny', delivery_method: 'SINGLE' })
    expect(page.validate()).toBe('请选择跟单员。')
    expect(wrapper.findAllComponents({ name: 'ElFormItem' }).some(item => item.props('label') === '选择客户')).toBe(false)
    wrapper.unmount()
  })

  it('手动单只填写是否返单，并据此派生订单来源', async () => {
    const wrapper = shallowMount(ProductionTaskFormView, { global: { plugins: [ElementPlus], stubs: { ElForm: { template: '<form><slot /></form>' } } } })
    await flushPromises()
    const page = wrapper.vm as unknown as { form: { is_repeat_order: boolean }; payload: () => { is_repeat_order: boolean; order_source: string } }
    expect(wrapper.findAllComponents({ name: 'ElFormItem' }).some(item => item.props('label') === '订单来源')).toBe(false)
    page.form.is_repeat_order = true
    expect(page.payload()).toEqual(expect.objectContaining({ is_repeat_order: true, order_source: 'REPEAT' }))
    page.form.is_repeat_order = false
    expect(page.payload()).toEqual(expect.objectContaining({ is_repeat_order: false, order_source: 'NEW' }))
    wrapper.unmount()
  })

  it('手动单可独立选择同一员工兼任业务员和生产跟单员', async () => {
    vi.mocked(api.fetchProductionTaskOptions).mockResolvedValue({ employees: [{ id: 'same-employee', display_name: '兼任员工' }], products: [], colors: [], currencies: [], units: [], detail_template: [] } as never)
    const wrapper = shallowMount(ProductionTaskFormView, { global: { plugins: [ElementPlus], stubs: {
      ElForm: { template: '<form><slot /></form>' },
      ElFormItem: { props: ['label'], template: '<section :data-label="label"><slot /></section>' },
      ElSelect: { template: '<div><slot /></div>' },
      ElOption: { props: ['label'], template: '<span>{{ label }}</span>' },
    } } })
    await flushPromises()
    const page = wrapper.vm as unknown as { form: { salesperson_id: string } }
    page.form.salesperson_id = 'same-employee'
    await flushPromises()
    expect(wrapper.find('[data-label="跟单员"]').text()).toContain('兼任员工')
    wrapper.unmount()
  })

  it('仅显示尚未按原数量分配完成的销售订单', async () => {
    vi.mocked(api.fetchProductionSalesOrderSources).mockResolvedValue({ data: [
      { id: 'full', has_remaining_production_capacity: false },
      { id: 'remaining', has_remaining_production_capacity: true },
    ] } as never)
    vi.mocked(api.fetchProductionSalesOrderSource).mockResolvedValue({ data: { id: 'remaining', status: 'CONFIRMED', delivery_batches: [], lines: [] } } as never)
    const wrapper = shallowMount(ProductionTaskCreateView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const page = wrapper.vm as unknown as { orderChoices: Array<{ id: string }> }
    expect(page.orderChoices.map(item => item.id)).toEqual(['remaining'])
    wrapper.unmount()
  })

  it('手动单拒绝仅填名称的产品，并以真实产品ID及完整HT编号保存', async () => {
    const wrapper = shallowMount(ProductionTaskFormView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const page = wrapper.vm as unknown as {
      form: Record<string, unknown>; products: Array<Record<string, unknown>>;
      lineTaskDrafts: Record<string, unknown>; validate: () => string; payload: () => Record<string, unknown>;
    }
    Object.assign(page.form, { task_number_suffix: '26199-1', order_date: '2026-10-15', delivery_date: '2026-11-15', salesperson_id: 'sales-1', follower_ids: ['factory-1'], currency_id: 'cny', delivery_method: 'SINGLE' })
    expect(page.validate()).toContain('名称、规格和单位')
    const product = page.products[0]!
    Object.assign(product, { product_id: 'real-product-id', customer_product_name: '产品', customer_specification: '规格', product_color_id: 'color-1', color_card: '色卡', color_name: '红', color_code: 'RED', quantity: '100', currency_id: 'cny', unit_id: 'pcs', unit_price: '3', exchange_rate: '1' })
    page.lineTaskDrafts[String(product.clientKey)] = { special_requirements: '', packaging_method: '', details: [{ client_key: 'detail', detail_type: '材料', category_label: '', description: '', is_selected: false }] }
    expect(page.validate()).toBe('')
    const payload = page.payload()
    expect(payload).toEqual(expect.objectContaining({ task_number: 'HT26199-1', follower_ids: ['factory-1'], tax_rate: null, products: [expect.objectContaining({ product_id: 'real-product-id' })] }))
    expect(payload).not.toHaveProperty('customer_account_id')
    expect(payload).not.toHaveProperty('sales_order_id')
    expect(payload).not.toHaveProperty('task_number_suffix')
    page.form.includes_tax = true
    expect(page.validate()).toBe('含税时请选择税率。')
    page.form.tax_rate = 7
    expect(page.validate()).toBe('')
    page.form.task_number_suffix = 'HT26199'
    expect(page.validate()).toContain('有效生产任务单号')
    wrapper.unmount()
  })

  it('销售来源建单提交人工HT编号，不带销售跟单员或默认计划员', async () => {
    vi.mocked(api.createProductionOrderFromSalesOrder).mockResolvedValue({ data: { id: 'new-task', task_number: 'HT26200' }, etag: 'v1' } as never)
    const wrapper = shallowMount(ProductionTaskCreateView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const page = wrapper.vm as unknown as {
      taskNumberSuffix: string; selectedBatchId: string; order: unknown; colorLines: unknown[]; plan: Record<string, unknown>;
      save: (submit: boolean) => Promise<void>;
    }
    page.taskNumberSuffix = '26200'
    page.order = { id: 'sales-1', currency_code: 'CNY', total_amount_cny: '100', salesperson: { id: 'salesperson' }, merchandiser: { id: 'sales-follower' }, delivery_batches: [{ id: 'batch-1', status: 'ACTIVE', planned_delivery_date: '2026-11-15', lines: [{ id: 'batch-line-1', sales_order_line_id: 'line-1', quantity: '100', remaining_quantity: '100' }] }], lines: [{ id: 'line-1', unit_price_cny: '1.0000', quality_requirements: '质量要求', packaging_requirements: '包装要求' }] }
    page.selectedBatchId = 'batch-1'
    page.colorLines = [{ key: 'draft-1', sourceLineId: 'batch-line-1', productColorId: 'color-1', quantity: 100, specialRequirements: '', packagingMethod: '' }]
    Object.assign(page.plan, { followerIds: ['factory-follower'], orderDate: '2026-10-15', deliveryDate: '2026-11-15', salespersonId: 'salesperson' })
    await page.save(false)
    expect(api.createProductionOrderFromSalesOrder).toHaveBeenCalledWith(expect.objectContaining({ task_number: 'HT26200', delivery_batch_id: 'batch-1', planner_id: null }))
    const payload = vi.mocked(api.createProductionOrderFromSalesOrder).mock.calls[0]![0]
    expect(payload).toHaveProperty('follower_ids', ['factory-follower'])
    expect(payload).not.toHaveProperty('factory_merchandiser_id')
    wrapper.unmount()
  })

  it('PMC确认不能沿用空跟单员；明确选择后才提交完整确认字段', async () => {
    const task = { id: 'task-1', task_number: 'HT26199', status: 'PENDING_VALIDATION', order_date: '2026-10-15', delivery_date: '2026-11-15', salesperson: { id: 'sales-1', display_name: '销售业务员' }, followers: [], products: [], current_boms: [], audit_timeline: [], includes_tax: false, delivery_method: 'SINGLE' }
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: 'v1' } as never)
    vi.mocked(api.decideProductionTaskByPmc).mockResolvedValue({ data: task, etag: 'v2' } as never)
    const wrapper = shallowMount(ProductionTaskDetailView, { global: { plugins: [ElementPlus], stubs: { ElButton: { name: 'ElButton', template: '<button><slot /></button>' } } } })
    await flushPromises()
    const page = wrapper.vm as unknown as { openPmcDialog: (mode: 'CONFIRM') => void; pmcForm: Record<string, unknown>; decideByPmc: () => Promise<void> }
    page.openPmcDialog('CONFIRM')
    await flushPromises()
    Object.assign(page.pmcForm, { planned_start_date: '2026-10-16', planned_end_date: '2026-11-10' })
    await page.decideByPmc()
    expect(api.decideProductionTaskByPmc).not.toHaveBeenCalled()
    Object.assign(page.pmcForm, { follower_ids: ['factory-1'], includes_tax: true, tax_rate: 5 })
    await page.decideByPmc()
    expect(api.decideProductionTaskByPmc).toHaveBeenCalledWith('task-1', expect.objectContaining({ follower_ids: ['factory-1'], includes_tax: true, tax_rate: 5, delivery_date: '2026-11-15', delivery_method: 'SINGLE' }), 'v1')
    wrapper.unmount()
  })
})

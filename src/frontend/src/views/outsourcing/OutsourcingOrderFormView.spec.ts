import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import OutsourcingOrderFormView from './OutsourcingOrderFormView.vue'

const route = vi.hoisted(() => ({ query: {} as Record<string, string> }))
const api = vi.hoisted(() => ({ source: vi.fn(), options: vi.fn(), plans: vi.fn(), bom: vi.fn(), create: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: true }, hasPermission: () => true }) }))
vi.mock('@/api/metalProcessingP4', () => ({ fetchP4Source: api.source }))
vi.mock('@/api/outsourcing', () => ({ createOutsourcingFactory: vi.fn(), createOutsourcingOrder: api.create,
  fetchOutsourcingOptions: api.options, fetchOutsourcingSourceBom: api.bom, fetchOutsourcingSourcePlans: api.plans }))
const wrappers: ReturnType<typeof mount>[] = []
async function render() {
  const wrapper = mount(OutsourcingOrderFormView, { global: { plugins: [ElementPlus], stubs: {
    FactoryFormDialog: true, OutsourcingMaterialDialog: true, OutsourcingProcessingDialog: true, OutsourcingSourcePlanDialog: true,
  } } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
beforeEach(() => {
  vi.resetAllMocks()
  route.query = { source_issue_line_id: 'line-1' }
  api.source.mockResolvedValue({ issue_line_id: 'line-1', issue_number: '领料001', part_name: '前脚管', status: 'OPEN',
    available_pieces: 20, etag: 'source-1', source_snapshot: { plan_source: { schedule_product_id: 'product-1' } } })
  api.options.mockResolvedValue({ crafts: [{ id: 'craft-1', name: '喷塑', outsourcing_code: 'POWDER_COATING' }], factories: [] })
  api.plans.mockResolvedValue({ data: [{ id: 'schedule-1', schedule_number: '排产001', production_task_number: '任务001',
    products: [{ id: 'product-1', product_name: '折叠椅' }] }] })
  api.bom.mockResolvedValue({ bom: { id: 'bom-1' }, material_items: [], processing_items: [] })
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('统一入口金工来源新建上下文', () => {
  it('从真实来源冻结排产带入产品，锁定选择且加载过程没有写入', async () => {
    const wrapper = await render()
    expect(api.source).toHaveBeenCalledWith('line-1')
    expect(api.plans).toHaveBeenCalledWith(expect.objectContaining({ schedule_product_id: 'product-1', craft_id: 'craft-1' }))
    expect(wrapper.get('[data-testid="metal-source-context"]').text()).toContain('可交接 20 支')
    expect(wrapper.get('[aria-label="选择排产计划"]').attributes('disabled')).toBeDefined()
    expect(api.create).not.toHaveBeenCalled()
  })
  it('来源已结清或没有可外发数量时阻止继续创建', async () => {
    api.source.mockResolvedValue({ status: 'CLOSED', available_pieces: 0 })
    const wrapper = await render()
    expect(wrapper.text()).toContain('当前没有可外发数量')
    expect(api.plans).not.toHaveBeenCalled()
    const save = wrapper.findAll('button').find(button => button.text() === '保存外发单')!
    expect(save.attributes('disabled')).toBeDefined()
    expect(api.create).not.toHaveBeenCalled()
  })
  it('普通原料新建不读取金工来源', async () => {
    route.query = { source_kind: 'RAW' }
    const wrapper = await render()
    expect(api.source).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="metal-source-context"]').exists()).toBe(false)
    expect(wrapper.get('[aria-label="选择排产计划"]').attributes('disabled')).toBeUndefined()
  })
})

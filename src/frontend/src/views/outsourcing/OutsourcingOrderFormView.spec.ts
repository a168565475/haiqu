import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElDatePicker } from 'element-plus'
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

describe('车缝加工套数与实际发料米数分开', () => {
  async function prepare() {
    route.query = { craft_id: 'craft-sewing', schedule_product_id: 'product-1' }
    api.options.mockResolvedValue({ crafts: [{ id: 'craft-sewing', name: '车缝', outsourcing_code: 'SEWING' }],
      factories: [{ id: 'factory-1', name: '甲厂', crafts: [{ id: 'craft-sewing' }] }, { id: 'factory-2', name: '乙厂', crafts: [{ id: 'craft-sewing' }] }] })
    const processing = { id: 'cutting-1', part_name: '椅套', specification: '20', required_quantity: '100',
      available_quantity: '100', unit: '套', input_unit: '套', technical_reference: '',
      conversion_snapshot: { schema_version: 2, kind: 'FABRIC', quantity_basis: 'OUTPUT_SETS', material_line_id: 'fabric-1', raw_input_unit: '米' } }
    api.bom.mockResolvedValue({ bom: { id: 'bom-1' }, processing_items: [processing], material_items: [
      { id: 'fabric-1', name: '牛津布', category: 'FABRIC', specification: '600D', unit: '米', procurement_unit: '米' },
    ] })
    api.create.mockResolvedValue({ data: { id: 'saved-order' } })
    const wrapper = await render()
    wrapper.getComponent({ name: 'OutsourcingProcessingDialog' }).vm.$emit('confirm', [processing])
    await flushPromises()
    const vm = wrapper.vm as any
    vm.processingRows[0].factory_id = 'factory-1'
    wrapper.getComponent(ElDatePicker).vm.$emit('update:modelValue', '2026-10-30')
    await flushPromises()
    return { wrapper, vm }
  }

  it('80套不会自动变成80米，独立填写12.5米后按两个字段保存', async () => {
    const { wrapper, vm } = await prepare()
    await wrapper.get('input[aria-label="本次加工套数"]').setValue('80')
    expect((wrapper.get('input[aria-label="牛津布发料数量"]').element as HTMLInputElement).value).toBe('')
    expect(vm.readyToSave).toBe(false)
    await wrapper.get('input[aria-label="牛津布发料数量"]').setValue('12.5')
    await wrapper.findAll('button').find(button => button.text() === '保存外发单')!.trigger('click')
    await flushPromises()
    expect(api.create).toHaveBeenCalledTimes(1)
    const product = api.create.mock.calls[0]![0].products[0]
    expect(product.processing_items[0]).toMatchObject({ quantity: '80', allocations: [{ allocated_quantity: '80', input_quantity: null }] })
    expect(product.materials).toEqual([{ bom_line_id: 'fabric-1', processing_bom_line_id: 'cutting-1', factory_id: 'factory-1', planned_issue_quantity: '12.5', difference_reason: '', remark: '' }])
  })

  it('分厂后保留各厂独立发料米数，合计加工套数不能超过剩余套数', async () => {
    const { wrapper, vm } = await prepare()
    await wrapper.get('input[aria-label="本次加工套数"]').setValue('60')
    await wrapper.get('input[aria-label="牛津布发料数量"]').setValue('7.25')
    vm.addFactoryRow(vm.processingRows[0])
    vm.processingRows[1].factory_id = 'factory-2'
    await flushPromises()
    const inputs = wrapper.findAll('input[aria-label="本次加工套数"]')
    const materials = wrapper.findAll('input[aria-label="牛津布发料数量"]')
    expect((materials[0]!.element as HTMLInputElement).value).toBe('7.25')
    expect((materials[1]!.element as HTMLInputElement).value).toBe('')
    await inputs[1]!.setValue('41')
    await materials[1]!.setValue('4.125')
    expect(() => vm.createPayload()).toThrow('各厂加工套数合计超过当前剩余可外发套数')
    await inputs[1]!.setValue('40')
    const product = vm.createPayload().products[0]
    expect(product.processing_items[0].quantity).toBe('100')
    expect(product.materials.map((row: { planned_issue_quantity: string }) => row.planned_issue_quantity)).toEqual(['7.25', '4.125'])
    expect(api.create).not.toHaveBeenCalled()
  })
})

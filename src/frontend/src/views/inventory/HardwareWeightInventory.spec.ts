import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/inventory'
import MaterialPurchaseInboundView from './MaterialPurchaseInboundView.vue'
import MaterialQualityConfirmationView from './MaterialQualityConfirmationView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { purchaseOrderId: 'order-1' } }), useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/router', () => ({ router: { push: vi.fn() } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 0, identityRequestGeneration: 0, hasPermission: () => true }) }))
vi.mock('@/api/inventory', () => ({
  fetchMaterialReceivingOptions: vi.fn(), fetchEligibleMaterialPurchaseOrders: vi.fn(), fetchEligibleMaterialLinesWithVersion: vi.fn(),
  createMaterialReceiving: vi.fn(), createSampleMaterialReceiving: vi.fn(),
  fetchMaterialQualityBatches: vi.fn(), fetchMaterialQualityBatch: vi.fn(), confirmMaterialQuality: vi.fn(),
}))

const materials = [
  { name: '铆钉', unit: '个', weight: '0.00396000', received: '1136' },
  { name: '垫片', unit: '片', weight: '0.00101645', received: '4427' },
]
const mounted: VueWrapper[] = []
function render(component: typeof MaterialPurchaseInboundView | typeof MaterialQualityConfirmationView) {
  // 输入框、按钮和页面逻辑使用真实组件，独立屏蔽日期浮层和无关历史查询。
  const wrapper = mount(component, { global: { plugins: [ElementPlus], stubs: { ElSelect: true, ElOption: true, ElDatePicker: true, ElTooltip: true, PurchaseInboundHistory: true } } })
  mounted.push(wrapper)
  return wrapper
}
async function receiving(material = materials[0]!, overrides: Record<string, unknown> = {}) {
  vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [{
    id: 'line-1', line_number: 1, category: '五金', part_name: material.name, unit: 'KG',
    measurement_kind: 'HARDWARE_WEIGHT', quantity_unit: material.unit, piece_unit: material.unit,
    unit_weight_kg: material.weight, purchased_quantity: '6', remaining_quantity: '4.5', remaining_weight_kg: '4.5',
    suggested_warehouse_id: 'wh', ...overrides,
  }], etag: '"receiving-v1"' } as never)
  const wrapper = render(MaterialPurchaseInboundView)
  await flushPromises()
  return wrapper
}
async function quality(material = materials[0]!, overrides: Record<string, unknown> = {}) {
  vi.mocked(api.fetchMaterialQualityBatches).mockResolvedValue([{ id: 'batch-1', inbound_number: 'RK01', status: 'PENDING_QUALITY', lines: [{
    id: 'line-1', part_name_snapshot: material.name, source_unit_text_snapshot: 'KG', measurement_kind: 'HARDWARE_WEIGHT',
    piece_unit: material.unit, quantity_unit: material.unit, received_piece_count: material.received,
    received_quantity: material.received, received_weight_kg: '4.5', return_weight_kg: '0', quality_remark: '',
    calculation_snapshot: { measurement_kind: 'HARDWARE_WEIGHT', piece_unit: material.unit, hardware_unit_weight_kg: material.weight }, ...overrides,
  }] }] as never)
  const wrapper = render(MaterialQualityConfirmationView)
  await flushPromises()
  return wrapper
}
const submit = (wrapper: VueWrapper) => wrapper.get<HTMLButtonElement>('.submit-bar .el-button--primary')
const quantityCells = (wrapper: VueWrapper) => wrapper.findAll('td.quantity-cell').map(cell => cell.text())

describe('铆钉垫片按公斤入库和质检', () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.clear()
    vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue({ warehouses: [{ id: 'wh', warehouse_number: 'CK01', warehouse_name: '材料仓' }], zones: [{ id: 'zone', warehouse: 'wh', zone_name: '五金区' }] })
    vi.mocked(api.fetchEligibleMaterialPurchaseOrders).mockResolvedValue([{ id: 'order-1', order_number: 'CG01', supplier_names: ['供应商'], remaining_line_count: 1 }] as never)
    vi.mocked(api.createMaterialReceiving).mockResolvedValue({} as never)
    vi.mocked(api.confirmMaterialQuality).mockResolvedValue({} as never)
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>)
  })
  afterEach(() => { mounted.splice(0).forEach(wrapper => wrapper.unmount()); ElMessage.closeAll(); vi.restoreAllMocks() })

  it.each(materials)('$name只显示和输入采购KG，不再展示参考$unit数，提交不含件数', async material => {
    const wrapper = await receiving(material)
    const input = wrapper.get<HTMLInputElement>('input[aria-label="第 1 项到货重量"]')
    expect(input.element.value).toBe('4.5')
    expect(wrapper.find('.hardware-reference').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('（参考')
    expect(wrapper.find('input[aria-label*="实收"]').exists()).toBe(false)
    expect(wrapper.get('.purchase-quantity-cell').text()).toBe('6 KG')
    await input.setValue('1'); await flushPromises()
    expect(wrapper.find('.hardware-reference').exists()).toBe(false)
    expect(submit(wrapper).element.disabled).toBe(false)
    await submit(wrapper).trigger('click'); await flushPromises()
    const payload = vi.mocked(api.createMaterialReceiving).mock.calls[0]![0]
    expect(payload.items).toEqual([{ purchase_order_line_id: 'line-1', zone_id: 'zone', received_weight_kg: '1', expected_remaining_quantity: '4.5', remark: '' }])
  })

  it.each(materials)('$name缺少单重时明确阻止折算和提交', async material => {
    const wrapper = await receiving(material, { unit_weight_kg: null })
    expect(wrapper.get('input[aria-label="第 1 项到货重量"]').attributes('title')).toContain('单件重量未记录或无效')
    expect(wrapper.find('.hardware-reference').exists()).toBe(false)
    expect(submit(wrapper).element.disabled).toBe(true)
    await submit(wrapper).trigger('click')
    expect(api.createMaterialReceiving).not.toHaveBeenCalled()
  })

  it.each(materials)('$name超量或超精度重量不提交，改回有效值可恢复', async material => {
    const wrapper = await receiving(material)
    const input = wrapper.get('input[aria-label="第 1 项到货重量"]')
    for (const invalid of ['0', '-1', '4.5001', '0.12345', 'abc']) {
      await input.setValue(invalid); await flushPromises()
      expect(submit(wrapper).element.disabled).toBe(true)
    }
    await input.setValue('1'); await flushPromises()
    expect(submit(wrapper).element.disabled).toBe(false)
  })

  it.each(materials)('$name正公斤数折算为参考0个时仍可收货、质检入库', async material => {
    const received = await receiving(material, { remaining_quantity: '0.0001', remaining_weight_kg: '0.0001' })
    expect(received.find('.hardware-reference').exists()).toBe(false)
    expect(submit(received).element.disabled).toBe(false)
    await submit(received).trigger('click'); await flushPromises()
    expect(vi.mocked(api.createMaterialReceiving).mock.calls[0]![0]).toMatchObject({ items: [{ received_weight_kg: '0.0001' }] })
    const checked = await quality(material, { received_piece_count: '0', received_quantity: '0', received_weight_kg: '0.0001' })
    expect(quantityCells(checked)).toEqual(['0.0001 kg', '0.0001 kg'])
    expect(submit(checked).element.disabled).toBe(false)
    await submit(checked).trigger('click'); await flushPromises()
    expect(api.confirmMaterialQuality).toHaveBeenCalledExactlyOnceWith('batch-1', { items: [{
      line_id: 'line-1', expected_received_quantity: '0.0001', return_weight_kg: '0', quality_remark: '',
    }] })
  })

  it.each(materials)('$name质检收退和合格量只显示KG，提交保持采购重量口径', async material => {
    const wrapper = await quality(material)
    expect(wrapper.find('input[aria-label*="实退"]').exists()).toBe(false)
    const input = wrapper.get('input[aria-label="第 1 项退货重量"]')
    await input.setValue('0.6'); await flushPromises()
    expect(quantityCells(wrapper)).toEqual(['4.5 kg', '3.9 kg'])
    expect(wrapper.find('.hardware-reference').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('（参考）')
    expect(submit(wrapper).element.disabled).toBe(false)
    await submit(wrapper).trigger('click'); await flushPromises()
    expect(api.confirmMaterialQuality).toHaveBeenCalledExactlyOnceWith('batch-1', { items: [{
      line_id: 'line-1', expected_received_quantity: '4.5', return_weight_kg: '0.6', quality_remark: '',
    }] })
  })

  it.each(materials)('$name微小退货允许参考数量为零，整批退货显示零合格数', async material => {
    const wrapper = await quality(material)
    const input = wrapper.get('input[aria-label="第 1 项退货重量"]')
    await input.setValue('0.0001'); await flushPromises()
    expect(wrapper.find('.hardware-reference').exists()).toBe(false)
    expect(submit(wrapper).element.disabled).toBe(false)
    await input.setValue('4.5'); await flushPromises()
    expect(quantityCells(wrapper)[1]).toBe('0 kg')
    expect(wrapper.find('.hardware-reference').exists()).toBe(false)
    expect(submit(wrapper).element.disabled).toBe(false)
  })

  it.each(materials)('$name剩余重量参考0个允许入库，单重缺失仍阻止质检', async material => {
    const wrapper = await quality(material)
    const input = wrapper.get('input[aria-label="第 1 项退货重量"]')
    await input.setValue('4.4999'); await flushPromises()
    expect(quantityCells(wrapper)[1]).toBe('0.0001 kg')
    expect(wrapper.find('.hardware-reference').exists()).toBe(false)
    expect(submit(wrapper).element.disabled).toBe(false)
    await submit(wrapper).trigger('click'); await flushPromises()
    expect(api.confirmMaterialQuality).toHaveBeenCalledExactlyOnceWith('batch-1', { items: [{
      line_id: 'line-1', expected_received_quantity: '4.5', return_weight_kg: '4.4999', quality_remark: '',
    }] })
    const missing = await quality(material, { calculation_snapshot: { measurement_kind: 'HARDWARE_WEIGHT' } })
    expect(missing.get('input[aria-label="第 1 项退货重量"]').attributes('title')).toContain('单件重量未记录或无效')
    expect(submit(missing).element.disabled).toBe(true)
    await missing.get('input[aria-label="第 1 项退货重量"]').setValue('4.5'); await flushPromises()
    expect(submit(missing).element.disabled).toBe(true)
  })

  it.each(['KG', '千克', '公斤'])('原单位为%s时保留公斤小数，不出现件数参考或单重要求', async unit => {
    const received = await receiving(materials[0]!, { quantity_unit: unit, piece_unit: unit, unit_weight_kg: null })
    await received.get('input[aria-label="第 1 项到货重量"]').setValue('0.0001'); await flushPromises()
    expect(received.find('.hardware-reference').exists()).toBe(false)
    expect(submit(received).element.disabled).toBe(false)
    await submit(received).trigger('click'); await flushPromises()
    expect(vi.mocked(api.createMaterialReceiving).mock.calls[0]![0]).toMatchObject({ items: [{ received_weight_kg: '0.0001' }] })
    const checked = await quality(materials[0]!, { piece_unit: unit, quantity_unit: unit, received_piece_count: null, received_quantity: '4.5', calculation_snapshot: { measurement_kind: 'HARDWARE_WEIGHT', piece_unit: unit } })
    await checked.get('input[aria-label="第 1 项退货重量"]').setValue('0.6'); await flushPromises()
    expect(checked.find('.hardware-reference').exists()).toBe(false)
    expect(quantityCells(checked)).toEqual(['4.5 kg', '3.9 kg'])
    expect(submit(checked).element.disabled).toBe(false)
  })
})

import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElInput } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/purchaseOrders'
import PurchaseOrderFormView from './PurchaseOrderFormView.vue'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ name: 'purchase-order-create-details', query: { source_type: 'SAMPLE', source_id: 'sample-source' } }),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: true }, hasPermission: () => true }) }))
vi.mock('@/api/purchaseOrders', () => ({
  fetchPurchaseOrderOptions: vi.fn(), fetchSamplePurchaseOrderSource: vi.fn(),
  fetchPurchaseOrderSource: vi.fn(), createPurchaseOrder: vi.fn(),
}))

let wrapper: VueWrapper | undefined
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchPurchaseOrderOptions).mockResolvedValue({
    production_tasks: [], sample_requests: [{ id: 'sample-source', source_id: 'sample-source', source_type: 'SAMPLE', source_number: 'S-1', can_create: true }],
    suppliers: [], currencies: [], default_currency_id: null,
  } as never)
  vi.mocked(api.fetchSamplePurchaseOrderSource).mockResolvedValue({
    can_create: true, bom_options: [], blockers: [], preview_lines: [], selected_bom_id: null,
    lines: [{ sample_line_key: 'pipe-1', section_type: 'PROFILE', category: '管材', part_name: '铁管', material: '铁', raw_material: '铁', specification: '20×28', product_color: '白色',
      material_selection_snapshot: { schema_version: 1, name: '铁管', template_key: 'TUBE', unit_name: '根', attributes: { section_size: '20×28', thickness: '2.0', material: '铁', color: '白色' } },
      sample_demand_quantity: '20', sample_supply_quantity: '8', required_quantity: '12', source_quantity_text: '12', source_unit_text: '米', quantity_parse_status: 'READY' }],
  } as never)
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

async function render() {
  wrapper = mount(PurchaseOrderFormView, { attachTo: document.body, global: { plugins: [ElementPlus], stubs: { ElDatePicker: true } } })
  await flushPromises()
  return wrapper
}

describe('样品管材采购浮层', () => {
  it('KG管材输入采购重量且金额按重量计算，不提交旧根数或显示根米', async () => {
    const source = await api.fetchSamplePurchaseOrderSource('sample-source')
    vi.mocked(api.fetchSamplePurchaseOrderSource).mockResolvedValue({ ...source, lines: [{ ...source.lines[0],
      source_unit_text: 'KG', required_quantity: null, suggested_purchase_weight_kg: null,
      raw_bar_weight_kg: null, raw_bar_length_m: null, suggested_bar_count: null,
      sample_demand_unit: '米', calculation_snapshot: { schema_version: 4, source: 'SAMPLE', measurement_kind: 'PIPE', measurement_unit: 'kg', shortage_meters: '12' },
    }] } as never)
    vi.mocked(api.fetchPurchaseOrderOptions).mockResolvedValue({ production_tasks: [], sample_requests: [{ id: 'sample-source', source_id: 'sample-source', source_type: 'SAMPLE', source_number: 'S-1', can_create: true }], suppliers: [], currencies: [{ id: 'cny', code: 'CNY' }], default_currency_id: 'cny' } as never)
    const page = await render()
    expect(page.text()).toContain('待填写重量')
    expect(page.text()).toContain('见打样需求')
    expect(page.text()).not.toContain('20 kg')
    await page.get('[aria-label="填写管材单根参数"]').trigger('click'); await flushPromises()
    const length = page.findAllComponents(ElInput).find(input => input.props('ariaLabel') === '采购每根长度（米）')!
    const unitWeight = page.findAllComponents(ElInput).find(input => input.props('ariaLabel') === '采购每根标准重量（kg）')!
    await length.get('input').setValue('3.05')
    await unitWeight.get('input').setValue('2.5')
    expect(page.text()).toContain('10 kg')
    const weight = page.get('input[aria-label="实际采购重量（kg）"]')
    await weight.setValue('12.3456')
    await flushPromises()
    const vm = page.vm as unknown as { form: { currencyId: string }; lines: Array<{ actual_bar_count: string; actual_purchase_quantity: string; unit_price: string; supplier_id: string; delivery_date: string }>; effectivePurchaseQuantity: (line: unknown) => string; lineAmount: (line: unknown) => string; createOrder: (nextStep: 'confirm') => Promise<void> }
    Object.assign(vm.lines[0]!, { unit_price: '2', supplier_id: 'supplier', delivery_date: '2026-12-01' }); vm.form.currencyId = 'cny'
    expect(vm.lines[0]!.actual_purchase_quantity).toBe('12.3456')
    expect(vm.effectivePurchaseQuantity(vm.lines[0])).toBe('12.3456')
    expect(vm.lineAmount(vm.lines[0])).toBe('24.69')
    expect(page.find('[aria-label="实际采购根数"]').exists()).toBe(false)
    expect(page.text()).not.toMatch(/折算采购米数|换算采购根数|换算根数|11 根|66 米/)
    expect(page.get('[data-testid="purchase-line-unit-price"]').text()).toBe('元/kg')
    expect(page.text()).toContain('重量物料金额＝采购重量 × 元/kg 单价')
    expect(page.text()).not.toContain('米制管材金额')
    vi.mocked(api.createPurchaseOrder).mockResolvedValue({ data: { id: 'draft-1' }, etag: 'version-1' } as never)
    await vm.createOrder('confirm')
    const payload = vi.mocked(api.createPurchaseOrder).mock.calls[0]![0]
    expect(payload.lines[0]).toMatchObject({ actual_purchase_quantity: '12.3456', raw_bar_length_m: '3.05', raw_bar_weight_kg: '2.5' })
    expect(payload.lines[0]).not.toHaveProperty('actual_purchase_weight_kg')
    expect(payload.lines[0]).not.toHaveProperty('actual_bar_count')
  })
  it('新打样KG可保存参数未齐草稿，不把空标准重量补成零或覆盖已填KG', async () => {
    const source = await api.fetchSamplePurchaseOrderSource('sample-source')
    vi.mocked(api.fetchSamplePurchaseOrderSource).mockResolvedValue({ ...source, lines: [{ ...source.lines[0],
      source_unit_text: 'KG', required_quantity: null, suggested_purchase_weight_kg: null, raw_bar_weight_kg: null, raw_bar_length_m: null,
      calculation_snapshot: { schema_version: 4, source: 'SAMPLE', measurement_kind: 'PIPE', measurement_unit: 'kg', shortage_meters: '12' },
    }] } as never)
    const page = await render()
    const vm = page.vm as unknown as { lines: Array<{ raw_bar_length_m: string }>; createOrder: (nextStep: 'list') => Promise<void> }
    vm.lines[0]!.raw_bar_length_m = '6'
    await page.get('input[aria-label="实际采购重量（kg）"]').setValue('7.2512')
    vi.mocked(api.createPurchaseOrder).mockResolvedValue({ data: { id: 'partial-draft' }, etag: 'version-partial' } as never)
    await vm.createOrder('list')
    expect(vi.mocked(api.createPurchaseOrder).mock.calls[0]![0].lines[0]).toMatchObject({ actual_purchase_quantity: '7.2512', raw_bar_length_m: '6', raw_bar_weight_kg: null })
    expect(page.text()).toContain('待填写重量')
  })
  it('保留材质规格颜色列，鼠标经过显示含厚度的保存属性，待采购量保留缺口', async () => {
    const page = await render()
    expect(page.get('[data-testid="purchase-line-unit-price"]').text()).toBe('元/米')
    expect(page.text()).toContain('米制管材金额＝采购米数 × 元/米 单价')
    expect(page.text()).not.toContain('元/kg')
    const headers = page.findAll('.el-table__header th').map(cell => cell.text())
    expect(headers).toEqual(expect.arrayContaining(['材质', '规格', '颜色', '待采购量']))
    expect(headers).not.toContain('厚度')
    expect(headers).not.toContain('材质规格')
    const cells = page.findAll('.el-table__body tbody tr')[0]!.findAll('td')
    for (const [label, value] of [['规格', '20×28'], ['材质', '铁'], ['颜色', '白色']]) {
      expect(cells[headers.indexOf(label!)]!.text()).toBe(value)
    }
    await cells[headers.indexOf('规格')]!.trigger('mouseenter')
    await flushPromises()
    const attributes = document.querySelector('.material-attribute-tooltip')?.textContent || ''
    for (const value of ['规格20×28', '厚度2.0', '材质铁', '颜色白色']) expect(attributes).toContain(value)
    expect(cells[headers.indexOf('待采购量')]!.text()).toBe('12 米')
    expect(page.get('[data-pipe-quantity-trigger]').text()).toBe('米')
  })

  it('米制采购填写米数，按每根长度精确折算原根数字段并保留金额计算', async () => {
    const page = await render()
    await page.get('[data-pipe-quantity-trigger]').trigger('click')
    await flushPromises()
    const meters = page.findAllComponents(ElInput).find(input => input.props('ariaLabel') === '实际采购数量（米）')!
    const length = page.findAllComponents(ElInput).find(input => input.props('ariaLabel') === '采购每根长度（米）')!
    length.vm.$emit('update:modelValue', '3.05')
    meters.vm.$emit('update:modelValue', '12.20')
    await flushPromises()
    expect(page.get('[data-pipe-quantity-trigger]').text()).toBe('12.20米')
    expect(page.find('[aria-label="实际采购根数"]').exists()).toBe(false)
    const vm = page.vm as unknown as { lines: Array<{ actual_bar_count: string; raw_bar_length_m: string; unit_price: string }>; effectivePurchaseQuantity: (line: unknown) => string; lineAmount: (line: unknown) => string; createOrder: (nextStep: 'list') => Promise<void> }
    expect(vm.lines[0]).toMatchObject({ actual_bar_count: '4', raw_bar_length_m: '3.05' })
    expect(vm.effectivePurchaseQuantity(vm.lines[0])).toBe('12.20')
    vm.lines[0]!.unit_price = '2'
    expect(vm.lineAmount(vm.lines[0])).toContain('24.4')
    vi.mocked(api.createPurchaseOrder).mockResolvedValue({ data: { id: 'draft-1' }, etag: 'version-1' } as never)
    await vm.createOrder('list')
    expect(api.createPurchaseOrder).toHaveBeenCalledWith(expect.objectContaining({
      source_type: 'SAMPLE',
      lines: [expect.objectContaining({ actual_bar_count: '4', raw_bar_length_m: '3.05', actual_purchase_quantity: null })],
    }))
  })

  it('米数不满整根时阻止保存，改变原长后重新校验且不擅自取整', async () => {
    const page = await render()
    await page.get('[data-pipe-quantity-trigger]').trigger('click')
    await flushPromises()
    const meters = page.findAllComponents(ElInput).find(input => input.props('ariaLabel') === '实际采购数量（米）')!
    const length = page.findAllComponents(ElInput).find(input => input.props('ariaLabel') === '采购每根长度（米）')!
    await length.get('input').setValue('3.05')
    await meters.get('input').setValue('12')
    const vm = page.vm as unknown as { lines: Array<{ actual_bar_count: string; actual_purchase_quantity: string }>; validateDraft: () => string; createOrder: (step: 'list') => Promise<void> }
    expect(vm.lines[0]!.actual_bar_count).toBe('')
    expect(vm.validateDraft()).toContain('每根长度的整数倍')
    await vm.createOrder('list')
    expect(api.createPurchaseOrder).not.toHaveBeenCalled()
    await length.get('input').setValue('3')
    expect(vm.lines[0]).toMatchObject({ actual_purchase_quantity: '12', actual_bar_count: '4' })
    expect(vm.validateDraft()).toBe('')
  })
})

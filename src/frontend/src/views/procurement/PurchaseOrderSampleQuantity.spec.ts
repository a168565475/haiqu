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
  it('材质规格颜色独立显示，待采购量保留缺口而非原始总需求', async () => {
    const page = await render()
    const headers = page.findAll('.el-table__header th').map(cell => cell.text())
    expect(headers).toEqual(expect.arrayContaining(['材质', '规格', '颜色', '待采购量']))
    expect(headers).not.toContain('材质规格')
    const cells = page.findAll('.el-table__body tbody tr')[0]!.findAll('td')
    expect(cells[headers.indexOf('待采购量')]!.text()).toBe('12 米')
    expect(page.get('[data-pipe-quantity-trigger]').text()).toBe('根/米')
  })

  it('浮层填写根数与每根长度，收起后显示总米数并保留原金额计算', async () => {
    const page = await render()
    await page.get('[data-pipe-quantity-trigger]').trigger('click')
    await flushPromises()
    const roots = page.findAllComponents(ElInput).find(input => input.props('ariaLabel') === '实际采购根数')!
    const length = page.findAllComponents(ElInput).find(input => input.props('ariaLabel') === '采购每根长度（米）')!
    roots.vm.$emit('update:modelValue', '4')
    length.vm.$emit('update:modelValue', '3.05')
    await flushPromises()
    expect(page.get('[data-pipe-quantity-trigger]').text()).toBe('4根 / 12.20米')
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
})

import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/inventory'
import MaterialPurchaseInboundView from './MaterialPurchaseInboundView.vue'
import PurchaseInboundListView from '../procurement/PurchaseInboundListView.vue'

vi.mock('@/router', () => ({ router: { push: vi.fn() } }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { purchaseOrderId: 'order-1' } }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))
vi.mock('@/api/inventory', async original => ({ ...await original<typeof import('@/api/inventory')>(),
  fetchProcurementInboundOrders: vi.fn(), fetchMaterialInventoryOptions: vi.fn(), fetchMaterialReceivingOptions: vi.fn(),
  fetchEligibleMaterialPurchaseOrders: vi.fn(), fetchEligibleMaterialLines: vi.fn(), createMaterialReceiving: vi.fn(),
}))
const options = { warehouses: [{ id: 'wh', warehouse_number: 'CK01', warehouse_name: '材料仓' }], zones: [{ id: 'zone', warehouse: 'wh', zone_name: '库区' }] }
const order = { id: 'order-1', order_number: 'CGDD2026091601', supplier_names: ['供应商'], remaining_line_count: 1 }
const line = { id: 'line-1', line_number: 1, part_name: '管材', purchased_quantity: '10', remaining_quantity: '6', unit: '支' }
const mount = (component: typeof MaterialPurchaseInboundView | typeof PurchaseInboundListView) => shallowMount(component, { global: { plugins: [ElementPlus] } })
describe('采购入库读取', () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.clear()
    vi.mocked(api.fetchMaterialInventoryOptions).mockResolvedValue({ ...options, locations: [], sections: [], production_orders: [] } as never)
    vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue(options)
    vi.mocked(api.fetchEligibleMaterialPurchaseOrders).mockResolvedValue([order] as never)
    vi.mocked(api.fetchEligibleMaterialLines).mockResolvedValue([line] as never)
    vi.mocked(api.fetchProcurementInboundOrders).mockResolvedValue([])
  })
  it('采购入库搜索支持回车、放大镜和清空，并保留入库状态', async () => {
    vi.mocked(api.fetchProcurementInboundOrders).mockResolvedValue([
      { ...order, id: 'pending', workflow_status: 'PENDING_QUALITY', pending_quality_count: 1 },
      { ...order, id: 'completed', workflow_status: 'COMPLETED', pending_quality_count: 0 },
    ] as never)
    const wrapper = shallowMount(PurchaseInboundListView, { global: { plugins: [ElementPlus], stubs: { ElInput: false } } })
    await flushPromises()
    wrapper.getComponent({ name: 'ElSelect' }).vm.$emit('update:modelValue', 'PENDING_QUALITY')
    await flushPromises()
    vi.mocked(api.fetchProcurementInboundOrders).mockClear()
    const input = wrapper.get('input')
    await input.setValue('  CGDD001  ')
    await input.trigger('keydown', { key: 'Enter', isComposing: true })
    expect(api.fetchProcurementInboundOrders).not.toHaveBeenCalled()
    const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
    input.element.dispatchEvent(enter); await flushPromises()
    expect(enter.defaultPrevented).toBe(true)
    expect(api.fetchProcurementInboundOrders).toHaveBeenCalledExactlyOnceWith({ q: 'CGDD001' })
    vi.mocked(api.fetchProcurementInboundOrders).mockClear()
    await input.setValue('  CGDD002  ')
    const button = wrapper.get('button[aria-label="搜索采购入库列表"]')
    expect(button.attributes('type')).toBe('button')
    await button.trigger('click'); await flushPromises()
    expect(api.fetchProcurementInboundOrders).toHaveBeenCalledExactlyOnceWith({ q: 'CGDD002' })
    vi.mocked(api.fetchProcurementInboundOrders).mockClear()
    await wrapper.get('.el-input').trigger('mouseenter')
    await wrapper.get('.el-input__clear').trigger('click'); await flushPromises()
    expect(api.fetchProcurementInboundOrders).toHaveBeenCalledExactlyOnceWith({ q: undefined })
    const vm = wrapper.vm as unknown as { workflowStatus: string; filteredRows: Array<{ id: string }> }
    expect(vm.workflowStatus).toBe('PENDING_QUALITY')
    expect(vm.filteredRows.map(row => row.id)).toEqual(['pending'])
    wrapper.unmount()
  })
  it('慢选项期间明细请求已发出，必要数据未齐时不可提交', async () => {
    vi.mocked(api.fetchMaterialInventoryOptions).mockReturnValue(new Promise(() => {}))
    vi.mocked(api.fetchMaterialReceivingOptions).mockReturnValue(new Promise(() => {}))
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    expect(api.fetchEligibleMaterialLines).toHaveBeenCalledExactlyOnceWith('order-1')
    expect(api.fetchMaterialInventoryOptions).not.toHaveBeenCalled()
    const vm = wrapper.vm as unknown as { loading: boolean; readyToSubmit: boolean }
    expect(vm.loading).toBe(true); expect(vm.readyToSubmit).toBe(false)
    wrapper.unmount()
  })
  it('并行读取恢复有效草稿，剔除失效库区，刷新保留当前输入', async () => {
    localStorage.setItem('material-receiving-draft:v2:order-1', JSON.stringify({ purchaseOrderId: 'order-1', rows: { 'line-1': { receivedQuantity: '2', warehouseId: 'wh', zoneId: 'obsolete' } } }))
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    const vm = wrapper.vm as unknown as { rows: Array<{ receivedQuantity: string; warehouseId: string; zoneId: string }>; loadBase: () => Promise<void>; readyToSubmit: boolean }
    expect(vm.rows[0]).toMatchObject({ receivedQuantity: '2', warehouseId: 'wh', zoneId: '' })
    vm.rows[0]!.receivedQuantity = '3'; vm.rows[0]!.zoneId = 'zone'
    await vm.loadBase()
    expect(vm.rows[0]).toMatchObject({ receivedQuantity: '3', warehouseId: 'wh', zoneId: 'zone' })
    expect(vm.readyToSubmit).toBe(true)
    expect(api.fetchEligibleMaterialLines).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
  it('必要读取失败时禁止提交，刷新可恢复且卸载回包失效', async () => {
    vi.mocked(api.fetchEligibleMaterialLines).mockRejectedValueOnce(new Error('明细失败'))
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    const vm = wrapper.vm as unknown as { rows: unknown[]; loadBase: () => Promise<void>; readyToSubmit: boolean; loadError: string }
    expect(vm.loadError).not.toBe(''); expect(vm.readyToSubmit).toBe(false)
    await vm.loadBase(); expect(vm.rows).toHaveLength(1); expect(vm.loadError).toBe('')
    let finish!: (value: never) => void
    vi.mocked(api.fetchEligibleMaterialLines).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const pending = vm.loadBase(); wrapper.unmount(); finish([] as never); await pending
    expect(vm.rows).toHaveLength(1); expect(api.createMaterialReceiving).not.toHaveBeenCalled()
  })
  it('列表旧请求不覆盖新搜索，失败显示未知并可重试', async () => {
    const wrapper = mount(PurchaseInboundListView); await flushPromises()
    const vm = wrapper.vm as unknown as { loadRows: () => Promise<void>; rows: Array<{id:string}>; loading: boolean; listReady: boolean; loadError: string }
    let finish!: (value: never) => void
    vi.mocked(api.fetchProcurementInboundOrders).mockReturnValueOnce(new Promise(resolve => { finish = resolve })).mockResolvedValueOnce([{ ...order, id: 'new', pending_quality_count: 0 }] as never)
    const old = vm.loadRows(); await vm.loadRows(); finish([{ ...order, id: 'old', pending_quality_count: 0 }] as never); await old
    expect(vm.rows[0]?.id).toBe('new'); expect(vm.loading).toBe(false)
    vi.mocked(api.fetchProcurementInboundOrders).mockRejectedValueOnce(new Error('读取失败'))
    await vm.loadRows(); expect(vm.listReady).toBe(false); expect(vm.loadError).not.toBe('')
    await vm.loadRows(); expect(vm.listReady).toBe(true); expect(vm.loadError).toBe('')
    wrapper.unmount()
  })
  it('已完成采购单不可再办理，已收货订单显示再次入库', async () => {
    const wrapper = mount(PurchaseInboundListView); await flushPromises()
    const vm = wrapper.vm as unknown as {
      canOpenReceiving: (row: Record<string, unknown>) => boolean
      receivingActionLabel: (row: Record<string, unknown>) => string
    }
    const completed = { ...order, source_type: 'PRODUCTION', source_number: 'HT001', sales_order_number: 'DD001', workflow_status: 'COMPLETED', remaining_line_count: 2 }
    expect(vm.canOpenReceiving(completed)).toBe(false)
    expect(vm.receivingActionLabel({ ...order, received_quantity: '0.0000' })).toBe('办理入库')
    expect(vm.receivingActionLabel({ ...order, received_quantity: '1.0000' })).toBe('再次入库')
    wrapper.unmount()
  })
  it('多产品资料保持对应顺序，缺值不挤掉后续产品的位置', async () => {
    const wrapper = mount(PurchaseInboundListView); await flushPromises()
    const vm = wrapper.vm as unknown as { displayProductField: (row: Record<string, unknown>, field: string) => string }
    const multiple = { ...order, product_summary: [
      { product_name: '折叠椅', item_number: '', specification: '47*55*79', color_name: '酒红色', material: 'PE' },
      { product_name: '三折床', item_number: 'XY-212', specification: '186*55*24cm', color_name: '深宝蓝', material: '' },
    ] }
    expect(vm.displayProductField(multiple, 'product_name')).toBe('折叠椅、三折床')
    expect(vm.displayProductField(multiple, 'item_number')).toBe('—、XY-212')
    expect(vm.displayProductField(multiple, 'specification')).toBe('47*55*79、186*55*24cm')
    expect(vm.displayProductField(multiple, 'color_name')).toBe('酒红色、深宝蓝')
    expect(vm.displayProductField(multiple, 'material')).toBe('PE、—')
    expect(vm.displayProductField({ ...order, product_summary: [] }, 'product_name')).toBe('—')
    expect(vm.displayProductField(order, 'product_name')).toBe('—')
    wrapper.unmount()
  })
  it('无退货且品质确认完成后不再提供二次入库操作', async () => {
    const completed = {
      ...order, workflow_status: 'COMPLETED', workflow_status_display: '已完成',
      pending_quality_count: 0, received_quantity: '10.0000', return_status: 'NONE',
    }
    vi.mocked(api.fetchProcurementInboundOrders).mockResolvedValue([completed] as never)
    const wrapper = mount(PurchaseInboundListView); await flushPromises()
    const vm = wrapper.vm as unknown as {
      canOpenReceiving: (row: Record<string, unknown>) => boolean
      hasRowActions: (row: Record<string, unknown>) => boolean
    }
    expect(vm.canOpenReceiving(completed)).toBe(false)
    expect(vm.hasRowActions(completed)).toBe(false)
    expect(vm.hasRowActions({ ...completed, workflow_status: 'PENDING_QUALITY' })).toBe(true)
    wrapper.unmount()
  })
})

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
  it('已完成采购单不可再办理，打样采购的订单编号显示打样单号', async () => {
    const wrapper = mount(PurchaseInboundListView); await flushPromises()
    const vm = wrapper.vm as unknown as {
      canOpenReceiving: (row: Record<string, unknown>) => boolean
      displayOrderNumber: (row: Record<string, unknown>) => string
      receivingActionLabel: (row: Record<string, unknown>) => string
    }
    const completed = { ...order, source_type: 'PRODUCTION', source_number: 'HT001', sales_order_number: 'DD001', workflow_status: 'COMPLETED', remaining_line_count: 2 }
    const sample = { ...order, source_type: 'SAMPLE', source_number: 'DY202609160001', sales_order_number: '' }
    expect(vm.canOpenReceiving(completed)).toBe(false)
    expect(vm.displayOrderNumber(sample)).toBe('DY202609160001')
    expect(vm.displayOrderNumber(completed)).toBe('DD001')
    expect(vm.receivingActionLabel({ ...order, received_quantity: '0.0000' })).toBe('办理入库')
    expect(vm.receivingActionLabel({ ...order, received_quantity: '1.0000' })).toBe('再次入库')
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

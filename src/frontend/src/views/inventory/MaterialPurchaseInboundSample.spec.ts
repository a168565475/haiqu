import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/inventory'
import { router } from '@/router'
import MaterialPurchaseInboundView from './MaterialPurchaseInboundView.vue'

const permissions = vi.hoisted(() => ({ receive: true }))
vi.mock('@/router', () => ({ router: { push: vi.fn() } }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { purchaseOrderId: 'sample-order' } }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: (permission: string) => permission !== 'inventory.receive_material' || permissions.receive }) }))
vi.mock('@/api/inventory', () => ({
  fetchMaterialReceivingOptions: vi.fn(), fetchEligibleMaterialPurchaseOrders: vi.fn(),
  fetchEligibleMaterialLinesWithVersion: vi.fn(), createMaterialReceiving: vi.fn(), createSampleMaterialReceiving: vi.fn(),
}))

const options = {
  warehouses: [{ id: 'warehouse', warehouse_number: 'CK01', warehouse_name: '材料仓' }],
  zones: [{ id: 'zone', warehouse: 'warehouse', zone_name: '管材区' }],
}
const order = { id: 'sample-order', order_number: 'CG-SAMPLE', source_type: 'SAMPLE', source_number: 'SRQ-1', supplier_names: ['供应商'], remaining_line_count: 2 }
const lines = [
  { id: 'pipe', line_number: 1, part_name: '样品管材', unit: '米', purchased_quantity: '12', remaining_quantity: '12', raw_bar_length_m: '6', actual_bar_count: 2, remaining_bar_count: 2 },
  { id: 'screw', line_number: 2, part_name: '样品螺丝', unit: '个', purchased_quantity: '4', remaining_quantity: '4' },
]
const receipt = { id: 'inbound', status: 'CONFIRMED', inbound_number: 'CLRK-1' }
type View = {
  rows: Array<{ included: boolean; receivedQuantity: string; warehouseId: string; zoneId: string }>
  selectedRows: unknown[]; allSelected: boolean; readyToSubmit: boolean; receiptCreated: boolean
  bulk: { warehouseId: string; zoneId: string }; form: { remark: string }
  applyBulkZone: () => void; submitReceiving: () => Promise<void>
}
const mount = () => shallowMount(MaterialPurchaseInboundView, { global: { plugins: [ElementPlus] } })
function assignZone(vm: View) {
  vm.bulk.warehouseId = 'warehouse'
  vm.bulk.zoneId = 'zone'
  vm.applyBulkZone()
}

describe('样品采购全部入库', () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.clear(); permissions.receive = true
    vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
    vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
    vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue(options)
    vi.mocked(api.fetchEligibleMaterialPurchaseOrders).mockResolvedValue([order] as never)
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: lines, etag: '"sample-v1"' } as never)
    vi.mocked(api.createSampleMaterialReceiving).mockResolvedValue(receipt as never)
  })
  afterEach(() => { vi.restoreAllMocks() })

  it('忽略旧草稿的部分选择和数量，全部明细只读显示根米或原单位', async () => {
    localStorage.setItem('material-receiving-draft:v2:sample-order', JSON.stringify({ purchaseOrderId: 'sample-order',
      rows: { pipe: { included: false, receivedQuantity: '1', warehouseId: 'warehouse', zoneId: 'zone' } } }))
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as View
    expect(vm.rows.map(row => row.included)).toEqual([true, true])
    expect(vm.rows.map(row => row.receivedQuantity)).toEqual(['2', '4.00'])
    expect(wrapper.find('.quantity-input').exists()).toBe(false)
    expect(wrapper.findAll('[data-testid="sample-receiving-quantity"]').map(cell => cell.text())).toEqual(['2 根 × 6 米/根 = 12 米', '4 个'])
    expect(wrapper.findAllComponents({ name: 'ElCheckbox' }).every(input => input.props('disabled') === true)).toBe(true)
    vm.allSelected = false
    expect(vm.selectedRows).toHaveLength(2)
    wrapper.unmount()
  })

  it('全部库区齐备才提交，新接口带版本和全部行且不带数量，成功返回采购入库列表', async () => {
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as View
    expect(vm.readyToSubmit).toBe(false)
    assignZone(vm)
    expect(vm.readyToSubmit).toBe(true)
    await vm.submitReceiving(); await flushPromises()
    const [payload, etag] = vi.mocked(api.createSampleMaterialReceiving).mock.calls[0]!
    expect(etag).toBe('"sample-v1"')
    expect(payload.purchase_order_id).toBe('sample-order')
    expect(payload.client_request_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(payload.items).toEqual([
      { purchase_order_line_id: 'pipe', zone_id: 'zone', remark: '' },
      { purchase_order_line_id: 'screw', zone_id: 'zone', remark: '' },
    ])
    expect(api.createMaterialReceiving).not.toHaveBeenCalled()
    expect(router.push).toHaveBeenCalledExactlyOnceWith({ name: 'purchase-inbounds' })
    expect(ElMessage.success).toHaveBeenCalledWith('样品采购材料已全部入库。')
    expect(vm.receiptCreated).toBe(true)
    expect(vm.readyToSubmit).toBe(false)
    await vm.submitReceiving()
    expect(api.createSampleMaterialReceiving).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('网络失败后同内容重试复用请求标识，修改内容后使用新标识', async () => {
    vi.mocked(api.createSampleMaterialReceiving).mockRejectedValue(new Error('网络失败'))
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as View
    assignZone(vm)
    await vm.submitReceiving()
    expect(vm.receiptCreated).toBe(false)
    expect(vm.readyToSubmit).toBe(true)
    await vm.submitReceiving()
    vm.form.remark = '补充到货备注'
    await vm.submitReceiving()
    const requests = vi.mocked(api.createSampleMaterialReceiving).mock.calls.map(([payload]) => payload)
    expect(requests[0]!.client_request_id).toBe(requests[1]!.client_request_id)
    expect(requests[2]!.client_request_id).not.toBe(requests[0]!.client_request_id)
    expect(router.push).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('缺少版本、没有剩余明细或没有收货权限时禁止提交', async () => {
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValueOnce({ data: lines, etag: '' } as never)
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as View
    assignZone(vm); expect(vm.readyToSubmit).toBe(false)
    wrapper.unmount()
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValueOnce({ data: [], etag: '"sample-v1"' })
    const empty = mount(); await flushPromises()
    expect((empty.vm as unknown as View).readyToSubmit).toBe(false)
    empty.unmount()
    permissions.receive = false
    const forbidden = mount(); await flushPromises()
    expect(forbidden.text()).toContain('无权进行采购入库')
    expect(api.createSampleMaterialReceiving).not.toHaveBeenCalled()
    forbidden.unmount()
  })
})

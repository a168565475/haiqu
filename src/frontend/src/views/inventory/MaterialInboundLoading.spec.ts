import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/inventory'
import MaterialPurchaseInboundView from './MaterialPurchaseInboundView.vue'
import PurchaseInboundListView from '../procurement/PurchaseInboundListView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { purchaseOrderId: 'order-1' } }), useRouter: () => ({ push: vi.fn() }) }))
const identity = vi.hoisted(() => ({ user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 0, identityRequestGeneration: 0, hasPermission: () => true }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => identity }))
vi.mock('@/api/inventory', async original => ({ ...await original<typeof import('@/api/inventory')>(),
  fetchProcurementInboundOrders: vi.fn(), fetchMaterialInventoryOptions: vi.fn(), fetchMaterialReceivingOptions: vi.fn(),
  fetchEligibleMaterialPurchaseOrders: vi.fn(), fetchEligibleMaterialLinesWithVersion: vi.fn(), createMaterialReceiving: vi.fn(),
}))
const options = { warehouses: [{ id: 'wh', warehouse_number: 'CK01', warehouse_name: '材料仓' }], zones: [{ id: 'zone', warehouse: 'wh', zone_name: '库区' }] }
const order = { id: 'order-1', order_number: 'CGDD2026091601', supplier_names: ['供应商'], remaining_line_count: 1 }
const line = { id: 'line-1', line_number: 1, part_name: '管材', purchased_quantity: '10', remaining_quantity: '6', unit: '支' }
const typedWarehouseOptions = {
  warehouses: [
    { id: 'raw', warehouse_number: 'CK01', warehouse_name: '原料管材仓', warehouse_type: 'MATERIAL' as const },
    { id: 'semi', warehouse_number: 'CK02', warehouse_name: '管材喷塑仓', warehouse_type: 'SEMI_FINISHED' as const },
  ],
  zones: [{ id: 'raw-zone', warehouse: 'raw', zone_name: '原料区' }, { id: 'semi-zone', warehouse: 'semi', zone_name: '喷塑区' }],
}
type WarehouseView = {
  rows: Array<{ included: boolean; receivedQuantity: string; warehouseId: string; zoneId: string }>
  bulk: { category: string; warehouseId: string; zoneId: string }
  bulkWarehouses: Array<{ id: string }>; bulkReadyToApply: boolean; zoneReadyCount: number; readyToSubmit: boolean
  applyBulkZone: () => void; loadBase: () => Promise<void>; submitReceiving: () => Promise<void>
}
const mount = (component: typeof MaterialPurchaseInboundView | typeof PurchaseInboundListView) => shallowMount(component, { global: { plugins: [ElementPlus] } })
describe('采购入库读取', () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.clear()
    Object.assign(identity, { user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 0, identityRequestGeneration: 0 })
    vi.mocked(api.fetchMaterialInventoryOptions).mockResolvedValue({ ...options, locations: [], sections: [], production_orders: [] } as never)
    vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue(options)
    vi.mocked(api.fetchEligibleMaterialPurchaseOrders).mockResolvedValue([order] as never)
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [line], etag: '"receiving-v1"' } as never)
    vi.mocked(api.fetchProcurementInboundOrders).mockResolvedValue([])
  })
  it('管材采购和累计到货显示根，输入整数根数且提交根数字段', async () => {
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [{ ...line, unit: '米', purchased_quantity: '33.5', remaining_quantity: '20.1', raw_bar_length_m: '3.35', actual_bar_count: 10, remaining_bar_count: 6 }], etag: '"receiving-v1"' } as never)
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    const vm = wrapper.vm as unknown as { rows: Array<{ receivedQuantity: string; warehouseId: string; zoneId: string }>; readyToSubmit: boolean; submitReceiving: () => Promise<void> }
    const purchaseCell = wrapper.get('.purchase-quantity-cell')
    expect(purchaseCell.text()).toBe('10 根'); expect(purchaseCell.element.nextElementSibling?.textContent).toBe('4 根')
    expect(purchaseCell.attributes('title')).toContain('33.5 米')
    expect(vm.rows[0]!.receivedQuantity).toBe('6')
    vm.rows[0]!.warehouseId = 'wh'; vm.rows[0]!.zoneId = 'zone'
    vm.rows[0]!.receivedQuantity = '1.5'; expect(vm.readyToSubmit).toBe(false)
    vm.rows[0]!.receivedQuantity = '7'; expect(vm.readyToSubmit).toBe(false)
    vm.rows[0]!.receivedQuantity = '2'; expect(vm.readyToSubmit).toBe(true)
    await vm.submitReceiving()
    expect(api.createMaterialReceiving).toHaveBeenCalledWith(expect.objectContaining({ items: [expect.objectContaining({ received_bar_count: '2', raw_bar_length_m: '3.35', expected_remaining_quantity: '20.1' })] }))
    const payload = vi.mocked(api.createMaterialReceiving).mock.calls[0]![0] as { items: Record<string, unknown>[] }
    expect(payload.items[0]).not.toHaveProperty('received_quantity')
    wrapper.unmount()
  })
  it.each([
    ['6.0000', '6', '套'],
    ['2.1250', '2.125', '米'],
    ['0.0001', '0.0001', '米'],
  ])('到货初值%s显示为%s（单位%s）且提交数量不变', async (remaining, expected, unit) => {
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [{ ...line, unit, material_catalog_id: 'catalog-id', remaining_quantity: remaining }], etag: '"receiving-v1"' } as never)
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    const vm = wrapper.vm as unknown as { rows: Array<{ receivedQuantity: string; warehouseId: string; zoneId: string }>; readyToSubmit: boolean; submitReceiving: () => Promise<void> }
    expect(vm.rows[0]!.receivedQuantity).toBe(expected)
    vm.rows[0]!.warehouseId = 'wh'; vm.rows[0]!.zoneId = 'zone'
    expect(vm.readyToSubmit).toBe(true)
    await vm.submitReceiving()
    expect(api.createMaterialReceiving).toHaveBeenCalledWith(expect.objectContaining({ items: [expect.objectContaining({ received_quantity: expected, expected_remaining_quantity: remaining })] }))
    expect(Number(expected)).toBe(Number(remaining))
    wrapper.unmount()
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
    expect(api.fetchEligibleMaterialLinesWithVersion).toHaveBeenCalledExactlyOnceWith('order-1')
    expect(api.fetchMaterialInventoryOptions).not.toHaveBeenCalled()
    const vm = wrapper.vm as unknown as { loading: boolean; readyToSubmit: boolean }
    expect(vm.loading).toBe(true); expect(vm.readyToSubmit).toBe(false)
    wrapper.unmount()
  })
  it('历史无主普通草稿不恢复、认领或删除，新保存只写当前UID', async () => {
    const key = 'material-receiving-draft:v2:order-1'
    const raw = JSON.stringify({ purchaseOrderId: 'order-1', rows: { 'line-1': { receivedQuantity: '2', warehouseId: 'wh', zoneId: 'zone' } } })
    localStorage.setItem(key, raw)
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    const vm = wrapper.vm as unknown as { rows: Array<{ warehouseId: string; zoneId: string }>; saveDraft: () => void }
    expect(vm.rows[0]).toMatchObject({ warehouseId: '', zoneId: '' })
    vm.saveDraft()
    expect(localStorage.getItem(key)).toBe(raw)
    expect(localStorage.getItem(`${key}:user:7`)).not.toBeNull()
    wrapper.unmount()
  })
  it('并行读取恢复有效草稿，剔除失效库区，刷新保留当前输入', async () => {
    localStorage.setItem('material-receiving-draft:v2:order-1:user:7', JSON.stringify({ purchaseOrderId: 'order-1', rows: { 'line-1': { receivedQuantity: '2.5000', warehouseId: 'wh', zoneId: 'obsolete' } } }))
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    const vm = wrapper.vm as unknown as { rows: Array<{ receivedQuantity: string; warehouseId: string; zoneId: string }>; loadBase: () => Promise<void>; readyToSubmit: boolean }
    expect(vm.rows[0]).toMatchObject({ receivedQuantity: '2.5000', warehouseId: 'wh', zoneId: 'zone' })
    vm.rows[0]!.receivedQuantity = '3'; vm.rows[0]!.zoneId = 'zone'
    await vm.loadBase()
    expect(vm.rows[0]).toMatchObject({ receivedQuantity: '3', warehouseId: 'wh', zoneId: 'zone' })
    expect(vm.readyToSubmit).toBe(true)
    expect(api.fetchEligibleMaterialLinesWithVersion).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
  it('必要读取失败时禁止提交，刷新可恢复且卸载回包失效', async () => {
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockRejectedValueOnce(new Error('明细失败'))
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    const vm = wrapper.vm as unknown as { rows: unknown[]; loadBase: () => Promise<void>; readyToSubmit: boolean; loadError: string }
    expect(vm.loadError).not.toBe(''); expect(vm.readyToSubmit).toBe(false)
    await vm.loadBase(); expect(vm.rows).toHaveLength(1); expect(vm.loadError).toBe('')
    let finish!: (value: never) => void
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
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

  it('批量收货按分类只应用到该分类的已勾选明细', async () => {
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValueOnce({ data: [
      { ...line, id: 'pipe', category: '管材' },
      { ...line, id: 'hardware', category: '五金', part_name: '螺丝' },
      { ...line, id: 'unselected-pipe', category: '管材', part_name: '备用管' },
    ], etag: '"receiving-v2"' } as never)
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    const vm = wrapper.vm as unknown as {
      rows: Array<{ included: boolean; warehouseId: string; zoneId: string }>
      bulk: { category: string; warehouseId: string; zoneId: string }
      applyBulkZone: () => void
    }
    vm.rows[2]!.included = false
    vm.bulk.category = '管材'; vm.bulk.warehouseId = 'wh'; vm.bulk.zoneId = 'zone'
    vm.applyBulkZone()
    expect(vm.rows.map(row => [row.warehouseId, row.zoneId])).toEqual([
      ['wh', 'zone'], ['', ''], ['', ''],
    ])
    expect(wrapper.find('[aria-label="批量分类"]').exists()).toBe(true)
    expect(wrapper.find('.page-title-row p').exists()).toBe(false)
    wrapper.unmount()
  })
  it.each([['RAW', 'raw', 'raw-zone'], ['PROCESSED', 'semi', 'semi-zone']])('按%s材料建议自动填写仓库与唯一库区并提交该库区', async (processingState, warehouseId, zoneId) => {
    vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue(typedWarehouseOptions)
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [{ ...line,
      material_selection_snapshot: { processing_state: processingState }, suggested_warehouse_id: warehouseId,
    }], etag: 'v1' } as never)
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    const vm = wrapper.vm as unknown as WarehouseView
    expect(vm.rows[0]).toMatchObject({ warehouseId, zoneId })
    expect(vm.readyToSubmit).toBe(true)
    expect(wrapper.find('.warehouse-hint').exists()).toBe(false)
    await vm.submitReceiving()
    expect(api.createMaterialReceiving).toHaveBeenCalledWith(expect.objectContaining({ items: [expect.objectContaining({ zone_id: zoneId, received_quantity: '6' })] }))
    wrapper.unmount()
  })
  it('建议仓有多个有效库区时仅填仓库，库区仍需选择', async () => {
    vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue({ ...typedWarehouseOptions,
      zones: [...typedWarehouseOptions.zones, { id: 'raw-zone-2', warehouse: 'raw', zone_name: '原料二区' }],
    })
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [{ ...line, suggested_warehouse_id: 'raw' }], etag: 'v1' } as never)
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    const vm = wrapper.vm as unknown as WarehouseView
    expect(vm.rows[0]).toMatchObject({ warehouseId: 'raw', zoneId: '' })
    expect(vm.readyToSubmit).toBe(false)
    vm.rows[0]!.zoneId = 'raw-zone-2'
    expect(vm.readyToSubmit).toBe(true)
    wrapper.unmount()
  })
  it.each([undefined, null, 'missing', 'semi', 'no-zone'])('缺失或不适用的建议仓%s不回退到任意仓库', async suggested => {
    vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue({ ...typedWarehouseOptions,
      warehouses: [...typedWarehouseOptions.warehouses, { id: 'no-zone', warehouse_number: 'CK03', warehouse_name: '无库区仓', warehouse_type: 'MATERIAL' }],
    })
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [{ ...line,
      material_selection_snapshot: { processing_state: 'RAW' }, suggested_warehouse_id: suggested,
    }], etag: 'v1' } as never)
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    const vm = wrapper.vm as unknown as WarehouseView
    expect(vm.rows[0]).toMatchObject({ warehouseId: '', zoneId: '' })
    expect(vm.readyToSubmit).toBe(false)
    expect(wrapper.get('.warehouse-hint').text()).toBe('未找到匹配的默认仓库，请手动选择。')
    wrapper.unmount()
  })
  it('合法草稿和刷新前用户改选优先于建议仓库', async () => {
    vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue({
      warehouses: [...typedWarehouseOptions.warehouses, { id: 'manual', warehouse_number: 'CK03', warehouse_name: '原料备用仓', warehouse_type: 'MATERIAL' }],
      zones: [...typedWarehouseOptions.zones, { id: 'manual-zone', warehouse: 'manual', zone_name: '备用区' }],
    })
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [{ ...line, suggested_warehouse_id: 'raw' }], etag: 'v1' } as never)
    localStorage.setItem('material-receiving-draft:v2:order-1:user:7', JSON.stringify({ purchaseOrderId: 'order-1', rows: { 'line-1': { receivedQuantity: '2.5000', warehouseId: 'manual', zoneId: 'manual-zone' } } }))
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    const vm = wrapper.vm as unknown as WarehouseView
    expect(vm.rows[0]).toMatchObject({ receivedQuantity: '2.5000', warehouseId: 'manual', zoneId: 'manual-zone' })
    vm.rows[0]!.receivedQuantity = '3'; vm.rows[0]!.warehouseId = 'raw'; vm.rows[0]!.zoneId = 'raw-zone'
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [{ ...line, suggested_warehouse_id: 'manual' }], etag: 'v2' } as never)
    await vm.loadBase()
    expect(vm.rows[0]).toMatchObject({ receivedQuantity: '3', warehouseId: 'raw', zoneId: 'raw-zone' })
    wrapper.unmount()
  })
  it('不存在的旧仓库按既有规则清理后可带入当前有效建议', async () => {
    vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue(typedWarehouseOptions)
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [{ ...line, suggested_warehouse_id: 'raw' }], etag: 'v1' } as never)
    localStorage.setItem('material-receiving-draft:v2:order-1:user:7', JSON.stringify({ purchaseOrderId: 'order-1', rows: { 'line-1': { warehouseId: 'obsolete', zoneId: 'obsolete-zone' } } }))
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    expect((wrapper.vm as unknown as WarehouseView).rows[0]).toMatchObject({ warehouseId: 'raw', zoneId: 'raw-zone' })
    wrapper.unmount()
  })
  it.each([['RAW', 'raw', 'raw-zone'], ['PROCESSED', 'semi', 'semi-zone'], [undefined, 'raw', 'raw-zone']])('批量仓库按保存状态%s提供对应库型，历史无快照保持原料规则', async (processingState, warehouseId, zoneId) => {
    vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue(typedWarehouseOptions)
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [{ ...line, material_selection_snapshot: processingState ? { processing_state: processingState } : {} }], etag: 'v1' } as never)
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    const vm = wrapper.vm as unknown as WarehouseView
    expect(vm.bulkWarehouses.map(item => item.id)).toEqual([warehouseId])
    vm.bulk.warehouseId = warehouseId!; vm.bulk.zoneId = zoneId!
    expect(vm.bulkReadyToApply).toBe(true)
    vm.applyBulkZone()
    expect(vm.rows[0]).toMatchObject({ warehouseId, zoneId })
    expect(vm.readyToSubmit).toBe(true)
    wrapper.unmount()
  })
  it('同分类原料和半成品混选提示逐行分配，防御校验不部分应用', async () => {
    vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue(typedWarehouseOptions)
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [
      { ...line, id: 'raw-line', category: '管材', material_selection_snapshot: { processing_state: 'RAW' } },
      { ...line, id: 'semi-line', category: '管材', material_selection_snapshot: { processing_state: 'PROCESSED' } },
    ], etag: 'v1' } as never)
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    const vm = wrapper.vm as unknown as WarehouseView
    expect(vm.bulkWarehouses).toEqual([])
    expect(wrapper.get('.bulk-warehouse-hint').text()).toContain('请逐行分配仓库和库区')
    expect(vm.bulkReadyToApply).toBe(false)
    const warning = vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: vi.fn() }))
    vm.bulk.warehouseId = 'raw'; vm.bulk.zoneId = 'raw-zone'; vm.applyBulkZone()
    expect(warning).toHaveBeenCalledWith('所选仓库与勾选材料的原料或半成品状态不匹配。')
    expect(vm.rows.map(row => [row.warehouseId, row.zoneId])).toEqual([['', ''], ['', '']])
    warning.mockRestore(); wrapper.unmount()
  })
  it('分类或勾选变化清除失效批量仓区，但不清除每行用户输入', async () => {
    vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue(typedWarehouseOptions)
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [
      { ...line, id: 'raw-line', category: '管材', material_selection_snapshot: { processing_state: 'RAW' } },
      { ...line, id: 'semi-line', category: '面料', material_selection_snapshot: { processing_state: 'PROCESSED' } },
    ], etag: 'v1' } as never)
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    const vm = wrapper.vm as unknown as WarehouseView
    vm.rows[0]!.warehouseId = 'raw'; vm.rows[0]!.zoneId = 'raw-zone'
    vm.rows[1]!.warehouseId = 'semi'; vm.rows[1]!.zoneId = 'semi-zone'
    vm.bulk.category = '管材'; await flushPromises()
    vm.bulk.warehouseId = 'raw'; vm.bulk.zoneId = 'raw-zone'
    vm.bulk.category = '面料'; await flushPromises()
    expect(vm.bulk).toMatchObject({ warehouseId: '', zoneId: '' })
    expect(vm.bulkWarehouses.map(item => item.id)).toEqual(['semi'])
    vm.bulk.warehouseId = 'semi'; vm.bulk.zoneId = 'semi-zone'
    vm.rows[1]!.included = false; await flushPromises()
    expect(vm.bulk).toMatchObject({ warehouseId: '', zoneId: '' })
    expect(vm.bulkWarehouses).toEqual([]); expect(vm.bulkReadyToApply).toBe(false)
    expect(wrapper.findAllComponents({ name: 'ElSelect' }).find(select => select.attributes('aria-label') === '批量材料仓')!.props('disabled')).toBe(true)
    expect(vm.rows.map(row => [row.warehouseId, row.zoneId])).toEqual([['raw', 'raw-zone'], ['semi', 'semi-zone']])
    wrapper.unmount()
  })
  it('草稿库型不匹配时保留用户输入，但不再显示库区已完成或行已完善', async () => {
    vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue(typedWarehouseOptions)
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [{ ...line, suggested_warehouse_id: 'raw' }], etag: 'v1' } as never)
    localStorage.setItem('material-receiving-draft:v2:order-1:user:7', JSON.stringify({ purchaseOrderId: 'order-1', rows: { 'line-1': { receivedQuantity: '2.5000', warehouseId: 'semi', zoneId: 'semi-zone' } } }))
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    const vm = wrapper.vm as unknown as WarehouseView
    expect(vm.rows[0]).toMatchObject({ receivedQuantity: '2.5000', warehouseId: 'semi', zoneId: 'semi-zone' })
    expect(vm.zoneReadyCount).toBe(0); expect(vm.readyToSubmit).toBe(false)
    expect(wrapper.get('footer strong').text()).toBe('库区完成 0/1')
    expect(wrapper.findAllComponents({ name: 'ElTag' }).at(-1)!.props('type')).toBe('warning')
    vm.rows[0]!.warehouseId = 'raw'; vm.rows[0]!.zoneId = 'raw-zone'; await flushPromises()
    expect(vm.zoneReadyCount).toBe(1); expect(vm.readyToSubmit).toBe(true)
    expect(wrapper.findAllComponents({ name: 'ElTag' }).at(-1)!.props('type')).toBe('success')
    wrapper.unmount()
  })
  it('无warehouse_type的历史选项继续沿用既有兼容规则', async () => {
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [
      { ...line, id: 'raw-line', material_selection_snapshot: { processing_state: 'RAW' } },
      { ...line, id: 'semi-line', material_selection_snapshot: { processing_state: 'PROCESSED' } },
    ], etag: 'v1' } as never)
    const wrapper = mount(MaterialPurchaseInboundView); await flushPromises()
    const vm = wrapper.vm as unknown as WarehouseView
    expect(vm.bulkWarehouses.map(item => item.id)).toEqual(['wh'])
    vm.bulk.warehouseId = 'wh'; vm.bulk.zoneId = 'zone'; vm.applyBulkZone()
    expect(vm.rows.map(row => row.warehouseId)).toEqual(['wh', 'wh'])
    wrapper.unmount()
  })
})

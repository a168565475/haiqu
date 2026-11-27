import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElCheckbox, ElMessage } from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/inventory'
import { router } from '@/router'
import MaterialPurchaseInboundView from './MaterialPurchaseInboundView.vue'

const permissions = vi.hoisted(() => ({ receive: true }))
const route = vi.hoisted(() => ({ params: { purchaseOrderId: 'sample-order' }, query: {} as Record<string, string> }))
vi.mock('@/router', () => ({ router: { push: vi.fn() } }))
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => router }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 0, identityRequestGeneration: 0, hasPermission: (permission: string) => permission !== 'inventory.receive_material' || permissions.receive }) }))
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
  rows: Array<{ included: boolean; receivedQuantity: string; warehouseId: string; zoneId: string; remark: string }>
  selectedRows: unknown[]; allSelected: boolean; readyToSubmit: boolean; receiptCreated: boolean
  bulk: { warehouseId: string; zoneId: string }; form: { remark: string }
  applyBulkZone: () => void; submitReceiving: () => Promise<void>
}
const mount = () => shallowMount(MaterialPurchaseInboundView, {
  global: { plugins: [ElementPlus], stubs: { ElTooltip: { inheritAttrs: false, template: '<slot />' } } },
})
function assignZone(vm: View) {
  vm.bulk.warehouseId = 'warehouse'
  vm.bulk.zoneId = 'zone'
  vm.applyBulkZone()
}

describe('采购收货和样品采购全部入库', () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.clear(); permissions.receive = true
    route.query = {}
    vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
    vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
    vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue(options)
    vi.mocked(api.fetchEligibleMaterialPurchaseOrders).mockResolvedValue([order] as never)
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: lines, etag: '"sample-v1"' } as never)
    vi.mocked(api.createSampleMaterialReceiving).mockResolvedValue(receipt as never)
  })
  afterEach(() => { vi.restoreAllMocks() })

  it.each([
    { section: 'A', template: 'TUBE', fields: { material: '铁', shape: '方管', section_size: '25×25', thickness: '0.6' },
      extra: { unit: 'KG', remaining_quantity: '675.0000', actual_bar_count: 700, raw_bar_length_m: '6.000', receipt_quantity_mode: 'ROOTS' },
      expected: { 材质: '铁', 截面形状: '方管', 规格: '25×25', 厚度: '0.6', 单根长度: '6 米', 待收数量: '675 根' } },
    { section: 'D', template: 'CARTON', fields: { model: '半盖纸箱', printing: '唛头1' },
      extra: { unit: '个', remaining_quantity: '12' }, expected: { '型号/图号': '半盖纸箱', 印刷版本: '唛头1', 待收数量: '12 个' } },
    { section: 'C', template: 'FABRIC', fields: { fabric_spec: '600D', width: '150 cm', gram_weight: '240 g/m²' },
      extra: { unit: '米', remaining_quantity: '25.5' }, expected: { 面料规格: '600D', 门幅: '150 cm', 克重: '240 g/m²', 待收数量: '25.5 米' } },
  ])('$section 分区的材料属性和待收数量各在独立列', async ({ section, template, fields, extra, expected }) => {
    route.query = { material_section: section }
    vi.mocked(api.fetchEligibleMaterialPurchaseOrders).mockResolvedValue([{ ...order, source_type: 'PRODUCTION' }] as never)
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [{ ...lines[1], ...extra,
      material_selection_snapshot: { schema_version: 1, template_key: template, name: '材料', attributes: fields },
    }], etag: '"production-v1"' } as never)
    const wrapper = mount(); await flushPromises()
    const headers = wrapper.findAll('thead th').map(cell => cell.text())
    const cells = wrapper.findAll('tbody tr:first-child td')
    expect(cells).toHaveLength(headers.length)
    for (const [label, value] of Object.entries(expected)) {
      expect(headers).toContain(label)
      expect(cells[headers.indexOf(label)]?.text()).toBe(value)
    }
    expect(headers.indexOf('待收数量')).toBe(headers.indexOf('本次到货数量') - 1)
    expect(headers.slice(4, -8)).toEqual(Object.keys(expected).filter(label => label !== '待收数量'))
    expect(cells[headers.indexOf('本次到货数量')]?.text()).not.toContain('待收')
    expect(wrapper.find('.specification-cell').exists()).toBe(false)
    expect(api.fetchEligibleMaterialLinesWithVersion).toHaveBeenCalledWith(order.id, section)
    wrapper.unmount()
  })

  it('五金件和塑料件按顺序分表并只提交所勾选的材料', async () => {
    route.query = { material_section: 'B' }
    vi.mocked(api.fetchEligibleMaterialPurchaseOrders).mockResolvedValue([{ ...order, source_type: 'PRODUCTION' }] as never)
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [
      { ...lines[1], id: 'plastic', section_title: '塑料件类', material_attributes_snapshot: { fields: [{ key: 'tube_size', label: '适配管材尺寸', value: '25×25' }] } },
      { ...lines[1], id: 'hardware', section_title: '五金件', material_attributes_snapshot: { fields: [{ key: 'thread', label: '螺纹规格', value: 'M6' }] } },
    ] } as never)
    vi.mocked(api.createMaterialReceiving).mockResolvedValue(receipt as never)
    const wrapper = mount(); await flushPromises()
    const tables = wrapper.findAll('.receipt-material-group')
    expect(tables.map(table => table.get('h3').text())).toEqual(['五金件', '塑料件'])
    const headers = tables.map(table => table.findAll('thead th').map(cell => cell.text()))
    expect(headers.map(columns => columns.slice(0, 4))).toEqual(Array.from({ length: 2 }, () => ['', '序号', '物料信息', '供应商']))
    expect(headers.map(columns => columns.slice(4, -8))).toEqual([['螺纹规格'], ['适配管材尺寸']])
    expect(headers.map(columns => columns.slice(-8, -4))).toEqual(Array.from({ length: 2 }, () => [
      '采购数量', '累计已收', '待收数量', '本次到货数量',
    ]))
    tables[1]!.findComponent(ElCheckbox).vm.$emit('update:modelValue', false)
    await flushPromises()
    const vm = wrapper.vm as unknown as View
    assignZone(vm); expect(vm.readyToSubmit).toBe(true)
    await vm.submitReceiving()
    expect(api.createMaterialReceiving).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
      material_section: 'B', items: [expect.objectContaining({ purchase_order_line_id: 'hardware' })],
    }))
    wrapper.unmount()
  })

  it('包材分区保留颜色与包装属性，并通过独立分区提交', async () => {
    route.query = { material_section: 'D' }
    vi.mocked(api.fetchEligibleMaterialPurchaseOrders).mockResolvedValue([{ ...order, source_type: 'PRODUCTION' }] as never)
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [
      { ...lines[1], id: 'box', category: '包材类', material_selection_snapshot: {
        schema_version: 1, category_key: 'PACKAGING', template_key: 'CARTON', color_card: '潘通色卡', color_code: '5445 C',
        attributes: { color: '蓝灰色', layers: '5', box_type: '半盖' },
      } },
    ], materialSectionDisplay: '包材' } as never)
    vi.mocked(api.createMaterialReceiving).mockResolvedValue(receipt as never)
    const wrapper = mount(); await flushPromises()
    const table = wrapper.get('.receipt-material-group')
    expect(table.get('h3').text()).toBe('包材')
    const headers = table.findAll('thead th').map(cell => cell.text())
    expect(headers.slice(4, -8)).toEqual(['色卡', '色号', '颜色', '层数', '箱子形状'])
    expect(table.findAll('colgroup col')[headers.indexOf('颜色')]?.attributes('style')).toContain('width: 192px')
    const vm = wrapper.vm as unknown as View
    assignZone(vm); expect(vm.readyToSubmit).toBe(true)
    await vm.submitReceiving()
    expect(api.createMaterialReceiving).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
      material_section: 'D', items: [expect.objectContaining({ purchase_order_line_id: 'box' })],
    }))
    wrapper.unmount()
  })

  it('新打样KG一次全入，只显示采购重量并自动折算根数提交', async () => {
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [
      { ...lines[0], unit: 'KG', weight_unit: true, purchased_quantity: '7.2500', remaining_quantity: '7.2500',
        remaining_weight_kg: '7.2500', raw_bar_weight_kg: '2.5', actual_bar_count: 3, remaining_bar_count: 3 }, lines[1],
    ], etag: '"sample-weight-v1"' } as never)
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as View
    expect(wrapper.find('.receiving-notice').text()).not.toContain('根数可核实修改')
    expect(wrapper.findComponent({ name: 'PurchaseInboundHistory' }).props('showPipeRoots')).toBe(false)
    expect(wrapper.findAll('[data-testid="sample-receiving-quantity"]').map(cell => cell.text())).toEqual(['7.25 kg', '4 个'])
    expect(wrapper.find('[aria-label="第 1 项到货重量"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="第 1 项实收根数"]').exists()).toBe(false)
    assignZone(vm); expect(vm.readyToSubmit).toBe(true)
    await vm.submitReceiving(); await flushPromises()
    const [payload, etag] = vi.mocked(api.createSampleMaterialReceiving).mock.calls[0]!
    expect(etag).toBe('"sample-weight-v1"')
    expect(payload.items).toEqual([
      { purchase_order_line_id: 'pipe', zone_id: 'zone', remark: '', received_weight_kg: '7.2500', received_bar_count: '3' },
      { purchase_order_line_id: 'screw', zone_id: 'zone', remark: '' },
    ])
    expect(api.createMaterialReceiving).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('生产采购待收100件时，登记到货105件须填写该行备注', async () => {
    vi.mocked(api.fetchEligibleMaterialPurchaseOrders).mockResolvedValue([{ ...order, order_number: 'CG-001', source_type: 'PRODUCTION', production_task_number: 'HT-001', batch_number: 2 }] as never)
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [
      { ...lines[1], purchased_quantity: '100', remaining_quantity: '100' },
    ] } as never)
    vi.mocked(api.createMaterialReceiving).mockResolvedValue(receipt as never)
    const wrapper = mount(); await flushPromises()
    try {
      const fields = wrapper.findAll('.table-order-meta > span')
      expect(fields.slice(0, 3).map(field => field.text())).toEqual(['生产任务单号 HT-001', '采购单号 CG-001', '采购批次 第 2 批'])
      expect(wrapper.get('.table-order-meta strong').text()).toBe('HT-001')
      const vm = wrapper.vm as unknown as View
      assignZone(vm)
      expect(vm.readyToSubmit).toBe(true)
      vm.rows[0]!.receivedQuantity = '105'
      await flushPromises()
      expect(wrapper.get('.remark-cell').text()).toContain('超出待收量，备注必填')
      expect(vm.readyToSubmit).toBe(false)
      vm.rows[0]!.remark = '   '
      expect(vm.readyToSubmit).toBe(false)
      vm.rows[0]!.remark = '供应商实际送来105件'
      expect(vm.readyToSubmit).toBe(true)
      await vm.submitReceiving()
      expect(api.createMaterialReceiving).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
        items: [expect.objectContaining({ received_quantity: '105', expected_remaining_quantity: '100', remark: '供应商实际送来105件' })],
      }))
    } finally { wrapper.unmount() }
  })

  it('忽略旧草稿的部分选择和数量，全部明细只读显示采购单位', async () => {
    localStorage.setItem('material-receiving-draft:v2:sample-order', JSON.stringify({ purchaseOrderId: 'sample-order',
      rows: { pipe: { included: false, receivedQuantity: '1', warehouseId: 'warehouse', zoneId: 'zone' } } }))
    const legacy = localStorage.getItem('material-receiving-draft:v2:sample-order')
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as View
    expect(wrapper.findAll('.table-order-meta > span').slice(0, 2).map(field => field.text())).toEqual(['打样单号 SRQ-1', '采购单号 CG-SAMPLE'])
    expect(wrapper.get('.table-order-meta strong').text()).toBe('SRQ-1')
    expect(localStorage.getItem('material-receiving-draft:v2:sample-order')).toBe(legacy)
    expect(localStorage.getItem('material-receiving-draft:v2:sample-order:user:7')).toBeNull()
    expect(vm.rows.map(row => row.included)).toEqual([true, true])
    expect(wrapper.find('.receiving-notice').text()).not.toContain('根数可核实修改')
    expect(vm.rows.map(row => row.receivedQuantity)).toEqual(['12', '4'])
    expect(wrapper.find('.quantity-input').exists()).toBe(false)
    expect(wrapper.findAll('[data-testid="sample-receiving-quantity"]').map(cell => cell.text())).toEqual(['12 米', '4 个'])
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

  it('样品各行按加工状态带入建议仓区，仍全量提交且不携带数量', async () => {
    vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue({
      warehouses: [
        { id: 'raw', warehouse_number: 'CK01', warehouse_name: '原料仓', warehouse_type: 'MATERIAL' },
        { id: 'semi', warehouse_number: 'CK02', warehouse_name: '半成品仓', warehouse_type: 'SEMI_FINISHED' },
      ],
      zones: [{ id: 'raw-zone', warehouse: 'raw', zone_name: '原料区' }, { id: 'semi-zone', warehouse: 'semi', zone_name: '半成品区' }],
    })
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [
      { ...lines[0], material_selection_snapshot: { processing_state: 'RAW' }, suggested_warehouse_id: 'raw' },
      { ...lines[1], material_selection_snapshot: { processing_state: 'PROCESSED' }, suggested_warehouse_id: 'semi' },
    ], etag: '"sample-v1"' } as never)
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as View
    expect(vm.rows.map(row => [row.warehouseId, row.zoneId])).toEqual([['raw', 'raw-zone'], ['semi', 'semi-zone']])
    expect(vm.readyToSubmit).toBe(true)
    await vm.submitReceiving()
    expect(vi.mocked(api.createSampleMaterialReceiving).mock.calls[0]![0].items).toEqual([
      { purchase_order_line_id: 'pipe', zone_id: 'raw-zone', remark: '' },
      { purchase_order_line_id: 'screw', zone_id: 'semi-zone', remark: '' },
    ])
    expect(api.createMaterialReceiving).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('生产收货回执超时后用同一提交标识取回原单', async () => {
    vi.mocked(api.fetchEligibleMaterialPurchaseOrders).mockResolvedValue([{ ...order, source_type: 'PRODUCTION' }] as never)
    vi.mocked(api.fetchEligibleMaterialLinesWithVersion).mockResolvedValue({ data: [lines[1]], etag: '' } as never)
    const receive = vi.mocked(api.createMaterialReceiving)
    receive.mockRejectedValueOnce(new AxiosError('timeout', 'ECONNABORTED'))
      .mockResolvedValueOnce({ ...receipt, status: 'PENDING_QUALITY' } as never)
    const wrapper = mount(); await flushPromises()
    try {
      const vm = wrapper.vm as unknown as View
      assignZone(vm)
      vm.rows[0]!.receivedQuantity = '4'
      expect(vm.readyToSubmit).toBe(true)
      await vm.submitReceiving()
      const [first, retry] = receive.mock.calls
      expect(first?.[0]).toEqual(expect.objectContaining({ client_request_id: expect.any(String) }))
      expect(retry?.[0]).toEqual(first?.[0])
      expect(receive).toHaveBeenCalledTimes(2)
      expect(vm.receiptCreated).toBe(true)
      expect(ElMessage.error).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
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

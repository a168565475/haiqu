import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { AxiosError, CanceledError } from 'axios'
import { useAuthStore } from '@/stores/auth'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/tubeOutsourcing'
import * as receipts from '@/api/tubeReceipts'
import type { TubeOrderDetail, TubePlanPendingAction, TubePlanRecordCorrectionDraft, TubePlanRecordCorrectionInput, TubeSourceContext } from '@/types/tubeOutsourcing'
import TubeOutsourcingPlanDetail from './TubeOutsourcingPlanDetail.vue'
import ProcessingMaterialDetails from '@/components/inventory/ProcessingMaterialDetails.vue'
import type { MaterialSelectionSnapshot } from '@/types/materialCatalog'

vi.mock('@/stores/auth', async () => {
  const { reactive } = await import('vue')
  const state = reactive({ user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 1, identityRequestGeneration: 1 })
  return { useAuthStore: () => state }
})
const auth = useAuthStore()
function resetIdentity() { Object.assign(auth, { user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 1, identityRequestGeneration: 1 }) }
vi.mock('@/api/tubeOutsourcing', () => ({ fetchTubeOrder: vi.fn(), fetchTubeSource: vi.fn(), dispatchTubePlan: vi.fn(), receiveTubePlan: vi.fn(), correctTubePlanRecord: vi.fn(), findTubePlanRecordCorrection: vi.fn(), updateTubePlanQuantity: vi.fn() }))
vi.mock('@/api/tubeReceipts', () => ({ fetchTubeReceiptPreview: vi.fn() }))
vi.mock('element-plus', async original => ({ ...await original<typeof import('element-plus')>(), ElMessage: { success: vi.fn() } }))

const line = { id: 'line-1', component_identity: 'part-1', part_name: '横管', factory_id: 'factory-1', factory_name: '加工厂', quantity: '900', unit_price: '0.25', planned_amount: '225', stock_quantity: null, meters: null, material: '钢', specification: 'Φ22', thickness: '1', cutting_length_mm: '400', raw_color: '本色', spray_color: '黑', pieces_per_bar: '10', raw_bar_length_m: '6', current_reported_minimum: null, operations: [], basis_blockers: [], bom_quantity: '1000', dispatched_quantity: '1200', received_quantity: '800', receivable_quantity: '400' }
const order: TubeOrderDetail = {
  id: 'plan-1', is_plan: true, order_number: 'WF-test', status: 'PROCESSING', version: 1, etag: 'v1', created: false, client_request_id: 'create-1', source_kind: 'PUBLIC_SEMI', source_label: '未喷塑半成品', schedule_product_id: 'schedule-1', product_line_id: 'product-1',
  planned_dispatch_date: '2026-10-29', expected_return_date: '2026-11-05', total_quantity: '900', total_stock_quantity: null, total_meters: null, planned_amount: '225', task_order_number: 'DD-test', task_number: 'SC-test', schedule_number: 'PC-test', product_number: 'CP-test', item_number: '', product_name: '测试产品', quantity: '500', unit: '把', color: '黑', zone_id: 'zone-1', zone_name: '未喷塑区', warehouse_name: '半成品仓', craft_name: '喷塑', remark: '', created_at: '', created_by_name: '', actual_dispatch_date: null, dispatched_at: null, dispatched_by_name: '', cancelled_at: null, cancelled_by_name: '', cancel_remark: '',
  permissions: { can_dispatch: true, can_receive: true, can_cancel: false }, lines: [line, { ...line, id: 'line-2', component_identity: 'part-2', part_name: '竖管', quantity: '100', bom_quantity: '100', dispatched_quantity: '0', received_quantity: '0', receivable_quantity: '0' }],
  plan_summary: { bom_quantity: '1100', planned_quantity: '1000', dispatched_quantity: '1200', received_quantity: '800', dispatch_progress: 109.1, receipt_progress: 72.7 }, dispatch_records: [], receipt_records: [],
  plan_options: { source_kinds: [{ value: 'PUBLIC_SEMI', label: '未喷塑半成品' }, { value: 'METAL', label: '金工直发' }], factories: [{ id: 'factory-1', name: '加工厂' }], zones: [{ id: 'zone-1', name: '未喷塑区', warehouse_id: 'warehouse-1', warehouse_name: '半成品仓', warehouse_type: 'SEMI_FINISHED' }] },
}
const auxiliarySnapshot: MaterialSelectionSnapshot = {
  schema_version: 1, catalog_id: 'aux-catalog', catalog_version: 'saved-version', name: '保存织带',
  category_key: 'AUXILIARY', template_key: 'AUXILIARY', scope: 'BASE', processing_state: 'RAW', processing_stage: 'RAW',
  unit_id: 'meter', unit_name: '米', attributes: { material: '涤纶', color: '黑色' }, display_name: '保存织带',
}
const key = 'tube-outsourcing-plan-action:v1:7:plan-1'
const sourceContext: TubeSourceContext = {
  ...order, source_revision: 'source-v1', task_id: 'task-1', specification: '测试规格', specification_display: '测试规格', material: '钢', image_file_id: null, image_url: '',
  ready: true, blockers: [], tasks: [], zones: order.plan_options!.zones, factories: order.plan_options!.factories,
  rows: order.lines.map(row => ({ ...row, bom_line_id: `bom-${row.id}`, order_required: row.bom_quantity!, stock_unit: '支', max_quantity: '2400', blockers: [] })),
}
function receivedResult(requestId: string): TubeOrderDetail {
  return { ...structuredClone(order), etag: 'v2', receipt_records: [{ id: 'receipt-1', client_request_id: requestId, receipt_number: 'RK-test', receipt_date: '2026-10-29', created_at: '', actor_name: '经办人', warehouse_id: 'warehouse-1', warehouse_name: '半成品仓', total_received_quantity: '200', lines: [{ order_line_id: 'line-1', component_identity: 'part-1', received_quantity: '200', zone_id: 'received-zone', zone_name: '喷塑区' }] }] }
}
interface ViewModel {
  entries: Array<{ quantity: string; zone: string; factory: string; price: string }>
  materialEntries: Array<{ id: string; quantity: string; zone: string; factory: string }>
  mode: string; pending: TubePlanPendingAction | null; message: string; canReceive: boolean
  open: (kind: 'DISPATCH' | 'RECEIPT') => Promise<void>; submit: () => Promise<void>; postPending: () => Promise<void>
  close: () => void; reloadAction: () => Promise<void>
  correctionActive: boolean; correctionRefreshRequired: boolean
  preparedCorrection: (order: TubeOrderDetail) => void
  submitCorrection: (input: TubePlanRecordCorrectionDraft, etag: string) => Promise<void>
  checkCorrection: () => Promise<void>
  quantityEditing: boolean; quantityValues: Record<string, string>; quantityError: string; quantityRefreshRequired: boolean
  openQuantityEditor: () => Promise<void>; loadQuantityEditor: () => Promise<void>; closeQuantityEditor: () => void; saveQuantity: () => Promise<void>
}
const wrappers: ReturnType<typeof shallowMount>[] = []
async function mountPage(value = structuredClone(order), warehouse = true, props: { actionOnly?: boolean; entryAction?: string; blocked?: boolean } = {}, renderTables = false) {
  const wrapper = shallowMount(TubeOutsourcingPlanDetail, { props: { order: value, warehouse, ...props }, global: { plugins: [ElementPlus], stubs: {
    ProcessingMaterialDetails: { props: ['materials'], template: '<span><slot/></span>' },
    TubeOutsourcingDetailTable: !renderTables,
    TubeOutsourcingPlanRecords: { name: 'TubeOutsourcingPlanRecords', props: ['order', 'warehouse', 'blocked', 'busy', 'pending', 'writeBlocked', 'message', 'refreshRequired', 'requestConflict'], template: '<section><slot name="dispatch-action"/><slot name="receipt-action"/></section>' },
    ElButton: { props: ['disabled', 'loading'], template: '<button :disabled="disabled || loading"><slot/></button>' },
    ElAlert: { name: 'ElAlert', props: ['title'], template: '<div role="alert">{{ title }}</div>' },
    AppWindowDialog: { props: ['modelValue', 'title', 'width'], template: '<section v-if="modelValue" :aria-label="title" :data-width="width"><slot/><slot name="footer"/></section>' },
  } } })
  wrappers.push(wrapper); await flushPromises()
  return { wrapper, vm: wrapper.vm as unknown as ViewModel }
}
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); resetIdentity()
  vi.mocked(api.fetchTubeSource).mockResolvedValue(structuredClone(sourceContext))
  vi.mocked(api.fetchTubeOrder).mockResolvedValue(structuredClone(order))
  vi.mocked(receipts.fetchTubeReceiptPreview).mockResolvedValue({ order: structuredClone(order), etag: 'v1', can_receive: true, blockers: [], actor_name: '经办人', today: '2026-10-29', warehouses: [{ id: 'warehouse-1', name: '半成品仓' }], zones: [{ id: 'received-zone', warehouse_id: 'warehouse-1', warehouse: '半成品仓', name: '喷塑区' }], receipt: null })
  vi.mocked(api.receiveTubePlan).mockImplementation(async (_, payload) => receivedResult(payload.client_request_id))
  vi.mocked(api.dispatchTubePlan).mockImplementation(async (_, payload) => ({ ...structuredClone(order), etag: 'v2', dispatch_records: [{ id: 'dispatch-1', client_request_id: payload.client_request_id, order_number: 'WF-batch', actual_dispatch_date: payload.actual_dispatch_date, created_at: '', actor_name: '经办人', source_kind: payload.source_kind, zone_name: '未喷塑区', total_quantity: payload.lines[0]!.quantity, lines: payload.lines.map(item => ({ ...item, factory_name: '加工厂' })) }] }))
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('车间编辑委外总单计划数量', () => {
  function editableOrder() {
    const value = structuredClone(order); value.permissions.can_edit_quantity = true; value.etag = 'quantity-v2'
    value.lines[0]!.quantity = '1400'
    value.lines[0]!.purchase_reference = { quantity: '2000', unit: '支', purchased_quantity: '200', purchase_unit: '根', conversion_note: '按采购实际入库数量换算' }
    return value
  }
  it('仅车间有权限时显示编辑，打开取最新版本，未改数量不提交', async () => {
    const value = editableOrder(); vi.mocked(api.fetchTubeOrder).mockResolvedValue(value)
    const warehouse = await mountPage(value, true)
    expect(warehouse.wrapper.text()).not.toContain('编辑计划数量'); await warehouse.vm.openQuantityEditor()
    const forbidden = await mountPage(structuredClone(order), false)
    expect(forbidden.wrapper.text()).not.toContain('编辑计划数量'); await forbidden.vm.openQuantityEditor()
    expect(api.fetchTubeOrder).not.toHaveBeenCalled()
    const { wrapper, vm } = await mountPage(value, false, {}, true); await vm.openQuantityEditor()
    expect(api.fetchTubeOrder).toHaveBeenCalledWith(order.id, false)
    expect(wrapper.getComponent({ name: 'TubeOutsourcingPlanRecords' }).props('blocked')).toBe(true)
    const table = wrapper.findAllComponents({ name: 'TubeOutsourcingDetailTable' }).find(item => item.classes().includes('plan-quantity-table'))!
    const columns = table.props('columns') as Array<{ key: string; label: string; num?: boolean }>
    expect(columns.filter(item => ['purchase_reference', 'dispatched_quantity', 'quantity'].includes(item.key)).every(item => item.num)).toBe(true)
    expect(columns.find(item => item.key === 'purchase_reference')!.label).toBe('采购入库参考（支）')
    const detail = wrapper.getComponent({ name: 'TubeOutsourcingDetailTable' })
    expect(detail.text()).toContain('采购入库参考（支）'); expect(detail.text()).toContain('2,000')
    expect(table.text()).toContain('2,000'); expect(table.find('[title="按采购实际入库数量换算"]').exists()).toBe(true)
    expect(columns.some(item => /根|单价|金额/.test(item.label))).toBe(false)
    await vm.saveQuantity(); expect(vm.quantityEditing).toBe(false); expect(api.updateTubePlanQuantity).not.toHaveBeenCalled()
  })
  it.each(['2000', '0', null])('采购参考%s不禁用数量编辑或限制计划，只检查正整数及累计已发下限', async purchaseQuantity => {
    const value = editableOrder(); value.lines[1]!.quantity = '100'; value.lines[1]!.dispatched_quantity = '150'
    value.lines[0]!.purchase_reference!.quantity = purchaseQuantity
    vi.mocked(api.fetchTubeOrder).mockResolvedValue(value)
    const result = structuredClone(value); result.etag = 'quantity-v3'; result.lines[0]!.quantity = '2501'; result.lines[1]!.quantity = '160'
    vi.mocked(api.updateTubePlanQuantity).mockResolvedValue(result)
    const { wrapper, vm } = await mountPage(value, false, {}, true); await vm.openQuantityEditor(); await flushPromises()
    const inputs = wrapper.findAllComponents({ name: 'ElInput' })
    expect(inputs.find(item => item.attributes('aria-label') === '横管计划数量')!.props('disabled')).toBe(false)
    expect(inputs.find(item => item.attributes('aria-label') === '竖管计划数量')!.props('disabled')).toBe(false)
    for (const quantity of ['0', '1.5']) { vm.quantityValues['line-1'] = quantity; await vm.saveQuantity(); expect(vm.quantityError).toContain('正整数') }
    vm.quantityValues['line-1'] = '1199'; await vm.saveQuantity(); expect(vm.quantityError).toContain('不能小于累计已发')
    expect(api.updateTubePlanQuantity).not.toHaveBeenCalled()
    vm.quantityValues['line-1'] = '2501'; vm.quantityValues['line-2'] = '160'; await vm.saveQuantity()
    expect(api.updateTubePlanQuantity).toHaveBeenCalledWith(order.id, { lines: [{ order_line_id: 'line-1', quantity: '2501' }, { order_line_id: 'line-2', quantity: '160' }] }, 'quantity-v2')
    expect(wrapper.emitted('updated')!.at(-1)).toEqual([result]); expect(vm.quantityEditing).toBe(false)
  })
  it.each([412, undefined])('保存%s冲突或网络未知时保留填写，重新加载后才允许保存', async status => {
    const value = editableOrder(); vi.mocked(api.fetchTubeOrder).mockResolvedValue(value)
    const failure = status ? Object.assign(new AxiosError('版本变化'), { response: { status, data: { detail: '版本变化' } } }) : new Error('网络中断')
    vi.mocked(api.updateTubePlanQuantity).mockRejectedValueOnce(failure).mockResolvedValue({ ...value, etag: 'quantity-v4' })
    const { vm } = await mountPage(value, false); await vm.openQuantityEditor(); vm.quantityValues['line-1'] = '1500'
    await vm.saveQuantity(); expect(vm.quantityRefreshRequired).toBe(true); expect(vm.quantityValues['line-1']).toBe('1500')
    await vm.saveQuantity(); expect(api.updateTubePlanQuantity).toHaveBeenCalledTimes(1)
    vi.mocked(api.fetchTubeOrder).mockResolvedValue({ ...value, etag: 'quantity-v3' })
    await vm.loadQuantityEditor(); expect(vm.quantityValues['line-1']).toBe('1500'); await vm.saveQuantity()
    expect(api.updateTubePlanQuantity).toHaveBeenLastCalledWith(order.id, expect.anything(), 'quantity-v3')
  })
  it('关闭编辑后忽略迟到读取，不重新打开弹窗或更新总单', async () => {
    const value = editableOrder(); let resolve!: (result: TubeOrderDetail) => void
    vi.mocked(api.fetchTubeOrder).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const { wrapper, vm } = await mountPage(value, false); const opening = vm.openQuantityEditor(); vm.closeQuantityEditor()
    resolve(value); await opening
    expect(vm.quantityEditing).toBe(false); expect(wrapper.emitted('updated')).toBeUndefined()
  })
})

describe('委外总单分次收发', () => {
  it('列表直接打开材料发出，沿用总单厂家单价但不提供编辑或金额展示', async () => {
    const value = structuredClone(order); value.source_kind = 'METAL'; value.zone_id = null
    value.lines[0]!.quantity = '2700'
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(sourceContext), source_kind: 'METAL', rows: sourceContext.rows.map(row => ({ ...row, max_quantity: '99999999999999' })) })
    const { wrapper, vm } = await mountPage(value, true, { actionOnly: true, entryAction: 'dispatch' })
    expect(wrapper.find('.plan-detail').exists()).toBe(false)
    expect(wrapper.get('[aria-label="材料发出"]').attributes('data-width')).toBe('1800')
    const headers = wrapper.findAll('.plan-entry-table th').map(item => item.text())
    expect(headers).toEqual(['部位', '材质', '规格', '形状', '厚度 mm', '喷塑颜色', '切割长度 mm', '需要外发（支）', '累计已发', '累计入库', '本次外发（支）', '加工厂'])
    expect(wrapper.findAll('.plan-entry-table tbody tr')[0]!.findAll('td')[headers.indexOf('需要外发（支）')]!.text()).toBe('2,700')
    expect(wrapper.text()).not.toContain('本次可外发'); expect(wrapper.text()).not.toContain('99,999,999,999,999')
    expect(wrapper.find('[aria-label="横管加工厂"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="横管加工单价"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('单价'); expect(wrapper.text()).not.toContain('元/支')
    expect(wrapper.findAll('.plan-entry-table tbody tr')[0]!.text()).toContain('Φ22')
    expect(wrapper.findAll('.plan-entry-table tbody tr')[0]!.text()).toContain('400')
    vm.entries[0]!.quantity = '1500'; await vm.submit()
    expect(api.dispatchTubePlan).toHaveBeenCalledWith('plan-1', expect.objectContaining({ lines: [{ component_identity: 'part-1', quantity: '1500', factory_id: 'factory-1', unit_price: '0.25' }] }), 'v1')
    expect(wrapper.emitted('closed')).toHaveLength(1)
  })
  it('列表外发入库保留真实可入数量、材料属性和只读计划厂家', async () => {
    const { wrapper, vm } = await mountPage(structuredClone(order), true, { actionOnly: true, entryAction: 'return' })
    expect(vm.mode).toBe('RECEIPT'); expect(wrapper.find('[aria-label="外发入库"]').exists()).toBe(true)
    const headers = wrapper.findAll('.plan-entry-table th').map(item => item.text())
    expect(headers).toContain('材质'); expect(headers).toContain('规格'); expect(headers).toContain('切割长度 mm')
    expect(headers).toContain('计划加工厂'); expect(headers).not.toContain('加工单价')
    const cells = wrapper.findAll('.plan-entry-table tbody tr')[0]!.findAll('td')
    expect(cells[headers.indexOf('本次最多可入')]!.text()).toBe('400')
    expect(cells[headers.indexOf('计划加工厂')]!.text()).toBe('加工厂')
    expect(wrapper.emitted('closed')).toBeUndefined()
  })
  it('库存来源的需要外发显示总单计划，仓库详情和记录隐藏价款，车间保留', async () => {
    const value = structuredClone(order)
    value.dispatch_records = [{ id: 'batch', client_request_id: 'old', order_number: 'WF-batch', actual_dispatch_date: '2026-11-02', created_at: '', actor_name: '经办人', source_kind: 'PUBLIC_SEMI', zone_name: '未喷塑区', total_quantity: '10', lines: [{ component_identity: 'part-1', factory_id: 'factory-1', factory_name: '加工厂', quantity: '10', unit_price: '0.25' }] }]
    const { wrapper, vm } = await mountPage(value)
    expect(wrapper.getComponent({ name: 'TubeOutsourcingDetailTable' }).props('columns').some((column: { key: string }) => column.key === 'unit_price')).toBe(false)
    expect(wrapper.text()).not.toContain('元/支')
    await vm.open('DISPATCH')
    const headers = wrapper.findAll('.plan-entry-table th').map(item => item.text())
    expect(headers).not.toContain('本次可外发')
    expect(wrapper.findAll('.plan-entry-table tbody tr')[0]!.findAll('td')[headers.indexOf('需要外发（支）')]!.text()).toBe('900')
    const workshop = await mountPage(value, false)
    expect(workshop.wrapper.getComponent({ name: 'TubeOutsourcingDetailTable' }).props('columns').some((column: { key: string }) => column.key === 'unit_price')).toBe(true)
    expect(workshop.wrapper.getComponent({ name: 'TubeOutsourcingPlanRecords' }).props()).toMatchObject({ order: value, warehouse: false })
  })
  it.each([
    ['PUBLIC_CUTTING', 'DISPATCH'], ['SEWING', 'DISPATCH'],
    ['PUBLIC_CUTTING', 'RECEIPT'], ['SEWING', 'RECEIPT'],
  ] as const)('裁片%s的%s保留材料属性和套单位，厂家只读且隐藏价款', async (sourceKind, mode) => {
    const value = structuredClone(order)
    value.source_kind = sourceKind; value.craft_name = '裁剪'
    value.lines = [{ ...value.lines[0]!, part_name: '座面', material: '涤纶', fabric_material: '涤纶', specification: '40×50',
      fabric_color: '保存蓝色', pieces_per_set: '4', thickness: '', cutting_length_mm: '', spray_color: '' }]
    value.plan_options!.source_kinds = [{ value: 'PUBLIC_CUTTING', label: '已入库裁片半成品' }, { value: 'SEWING', label: '车缝完成未入库直发' }]
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(sourceContext), source_kind: sourceKind, rows: [{
      ...sourceContext.rows[0]!, ...value.lines[0]!, specification: '45×60', fabric_color: '来源蓝色', pieces_per_set: '6',
      order_required: sourceContext.rows[0]!.order_required, stock_unit: '套', max_quantity: sourceKind === 'SEWING' ? '99999999999999' : '120',
    }] })
    vi.mocked(receipts.fetchTubeReceiptPreview).mockResolvedValue({ order: value, etag: 'v1', can_receive: true, blockers: [], actor_name: '经办人', today: '2026-11-02', warehouses: [{ id: 'warehouse-1', name: '半成品仓' }], zones: [], receipt: null })
    const { wrapper, vm } = await mountPage(value)
    const detailColumns = wrapper.getComponent({ name: 'TubeOutsourcingDetailTable' }).props('columns') as Array<{ key: string; num?: boolean }>
    expect(detailColumns).toEqual(expect.arrayContaining([{ key: 'fabric_color', label: '颜色', width: 90 }, { key: 'pieces_per_set', label: '每套片数', width: 90, num: true }]))
    expect(detailColumns).toContainEqual({ key: 'purchase_reference', label: '采购入库参考（套）', width: 150, num: true })
    await vm.open(mode)
    const headers = wrapper.findAll('.plan-entry-table th').map(item => item.text())
    expect(headers).toContain('每套片数'); expect(headers).toContain('颜色')
    expect(headers).toContain(mode === 'DISPATCH' ? '本次外发（套）' : '本次入库（套）')
    expect(headers).not.toContain('切割长度 mm'); expect(headers).not.toContain('喷塑颜色')
    expect(headers.some(label => /单价|金额/.test(label))).toBe(false)
    const cells = wrapper.findAll('.plan-entry-table tbody tr')[0]!.findAll('td')
    expect(cells[headers.indexOf('材质')]!.text()).toBe('涤纶')
    expect(cells[headers.indexOf('规格')]!.text()).toBe(mode === 'DISPATCH' ? '45×60' : '40×50')
    expect(cells[headers.indexOf('颜色')]!.text()).toBe(mode === 'DISPATCH' ? '来源蓝色' : '保存蓝色')
    expect(cells[headers.indexOf('每套片数')]!.text()).toBe(mode === 'DISPATCH' ? '6' : '4')
    expect(cells[headers.indexOf('每套片数')]!.classes()).toContain('num')
    expect(wrapper.find('[aria-label="座面加工厂"]').exists()).toBe(false)
    if (mode === 'DISPATCH') {
      expect(cells[headers.indexOf('需要外发（套）')]!.text()).toBe('900')
      expect(headers).not.toContain('本次可外发')
    } else {
      expect(headers).not.toContain('需要外发（套）')
      expect(cells[headers.indexOf('本次最多可入')]!.text()).toBe('400')
      expect(api.fetchTubeSource).not.toHaveBeenCalled()
    }
  })

  it.each(['permission', 'identity', 'blocked'] as const)('列表入口在%s受阻时仍显示可关闭和重新加载的弹窗', async reason => {
    const value = structuredClone(order)
    if (reason === 'permission') value.permissions.can_dispatch = false
    if (reason === 'identity') Object.assign(auth, { identityReady: false })
    const { wrapper, vm } = await mountPage(value, true, { actionOnly: true, entryAction: 'dispatch', blocked: reason === 'blocked' })
    expect(wrapper.find('[aria-label="材料发出"]').exists()).toBe(true)
    expect(wrapper.find('.plan-action-status').text()).not.toBe('')
    expect(wrapper.findAll('button').map(button => button.text())).toEqual(['关闭', '重新加载'])
    expect(api.fetchTubeSource).not.toHaveBeenCalled()
    await vm.reloadAction(); expect(wrapper.emitted('refresh')).toHaveLength(1)
    vm.close(); expect(wrapper.emitted('closed')).toHaveLength(1)
  })
  it('列表待核对请求显示核对入口，关闭不清除请求且按原厂家和原单价重放', async () => {
    const action: TubePlanPendingAction = { kind: 'DISPATCH', order_id: order.id, etag: 'old-etag', payload: { client_request_id: 'pending-old', actual_dispatch_date: '2026-11-01', source_kind: 'METAL', zone_id: null, remark: '', lines: [{ component_identity: 'part-1', quantity: '100', factory_id: 'original-factory', unit_price: '0.19' }] } }
    const raw = JSON.stringify(action); localStorage.setItem(key, raw)
    const { wrapper, vm } = await mountPage(structuredClone(order), true, { actionOnly: true, entryAction: 'return' })
    expect(wrapper.find('[aria-label="材料发出"]').exists()).toBe(true)
    expect(wrapper.findAll('button').map(button => button.text())).toContain('核对本次提交')
    vm.close(); expect(localStorage.getItem(key)).toBe(raw)
    await vm.postPending()
    expect(api.dispatchTubePlan).toHaveBeenCalledWith(order.id, action.payload, 'old-etag')
  })
  it('列表读取发货来源失败后保留可关闭弹窗并可重试，保存中不能关闭', async () => {
    vi.mocked(api.fetchTubeSource).mockRejectedValueOnce(new Error('来源读取失败'))
    const value = structuredClone(order); value.lines[0]!.quantity = '1300'
    const { wrapper, vm } = await mountPage(value, true, { actionOnly: true, entryAction: 'dispatch' })
    expect(wrapper.text()).toContain('来源读取失败'); expect(wrapper.find('[aria-label="材料发出"]').exists()).toBe(true)
    await vm.reloadAction(); expect(api.fetchTubeSource).toHaveBeenCalledTimes(2)
    let resolve!: (value: TubeOrderDetail) => void
    vi.mocked(api.dispatchTubePlan).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    vm.entries[0]!.quantity = '100'; const saving = vm.submit(); vm.close()
    expect(wrapper.emitted('closed')).toBeUndefined()
    const action = JSON.parse(localStorage.getItem(key)!) as Extract<TubePlanPendingAction, { kind: 'DISPATCH' }>
    resolve({ ...structuredClone(order), etag: 'v2', dispatch_records: [{ id: 'batch', client_request_id: action.payload.client_request_id, order_number: 'WF-batch', actual_dispatch_date: '2026-11-02', created_at: '', actor_name: '经办人', source_kind: 'PUBLIC_SEMI', zone_name: '未喷塑区', total_quantity: '100', lines: [] }] })
    await saving; expect(wrapper.emitted('closed')).toHaveLength(1)
  })
  it.each(['unique', 'missing', 'multiple'] as const)('辅料厂家%s时只沿用总单唯一厂家，无法确定则禁用且拒绝提交', async mode => {
    const value = structuredClone(order); value.source_kind = 'SEWING'
    value.lines[0]!.quantity = '1300'
    const planned = { bom_line_id: 'bom-material-1', quantity: '3', factory_id: 'factory-1', zone_id: 'material-zone', factory_name: '加工厂', name: auxiliarySnapshot.name, unit: '米' }
    value.planned_materials = mode === 'missing' ? [] : mode === 'multiple' ? [planned, { ...planned, factory_id: 'factory-2', factory_name: '其他厂' }] : [planned]
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(sourceContext), source_kind: 'SEWING', material_source_revision: 'revision', material_rows: [{ bom_line_id: 'bom-material-1', material_number: 'FL-1', name: auxiliarySnapshot.name, specification: '30mm', material: '涤纶', color: '黑', unit: '米', required_quantity: '10', order_remaining: '8', available_stock: '8', max_quantity: '8', blockers: [], zones: [{ zone_id: 'material-zone', zone_name: '辅料区', warehouse_id: 'material-warehouse', warehouse_name: '辅料仓', available_quantity: '8' }] }] })
    const { wrapper, vm } = await mountPage(value, true, { actionOnly: true, entryAction: 'dispatch' })
    expect(wrapper.find('[aria-label="保存织带辅料加工厂"]').exists()).toBe(false)
    const input = wrapper.findAllComponents({ name: 'ElInput' }).find(item => item.attributes('aria-label') === '保存织带本次辅料数量')!
    expect(input.props('disabled')).toBe(mode !== 'unique')
    expect(vm.materialEntries[0]!.factory).toBe(mode === 'unique' ? 'factory-1' : '')
    if (mode !== 'unique') expect(wrapper.text()).toContain('总单未指定唯一加工厂')
    vm.entries[0]!.quantity = '100'; vm.materialEntries[0]!.quantity = '2'; await vm.submit()
    if (mode === 'unique') expect(api.dispatchTubePlan).toHaveBeenCalledWith(order.id, expect.objectContaining({ materials: [{ bom_line_id: 'bom-material-1', quantity: '2', factory_id: 'factory-1', zone_id: 'material-zone' }] }), order.etag)
    else { expect(api.dispatchTubePlan).not.toHaveBeenCalled(); expect(vm.message).toContain('总单未指定唯一加工厂') }
  })

  it.each(['uid', 'generation', 'request', 'ready'] as const)('入库在%s边界后迟到成功不emit、不清记录', async boundary => {
    const { wrapper, vm } = await mountPage(); await vm.open('RECEIPT'); vm.entries[0]!.quantity = '200'; vm.entries[0]!.zone = 'received-zone'
    let resolve!: (value: TubeOrderDetail) => void
    vi.mocked(api.receiveTubePlan).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const submitting = vm.submit(); const raw = localStorage.getItem(key)!
    if (boundary === 'uid') auth.user!.id = 8
    else if (boundary === 'generation') auth.identityGeneration += 1
    else if (boundary === 'request') auth.identityRequestGeneration += 1
    else Object.assign(auth, { identityReady: false })
    resolve(receivedResult((JSON.parse(raw) as TubePlanPendingAction).payload.client_request_id)); await submitting
    expect(localStorage.getItem(key)).toBe(raw); expect(vm.pending).not.toBeNull(); expect(wrapper.emitted('updated')).toBeUndefined(); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it.each([new AxiosError('超时'), Object.assign(new AxiosError('拒绝'), { response: { status: 412 } }), new CanceledError('取消')])('旧入库拒绝或取消不启动刷新GET或清记录', async cause => {
    const { wrapper, vm } = await mountPage(); await vm.open('RECEIPT'); vm.entries[0]!.quantity = '200'; vm.entries[0]!.zone = 'received-zone'
    let reject!: (cause: unknown) => void
    vi.mocked(api.receiveTubePlan).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail }))
    const submitting = vm.submit(); const raw = localStorage.getItem(key)!
    if (cause.code !== 'ERR_CANCELED') auth.identityRequestGeneration += 1
    reject(cause); await submitting
    expect(localStorage.getItem(key)).toBe(raw); expect(api.fetchTubeOrder).not.toHaveBeenCalled(); expect(wrapper.emitted('updated')).toBeUndefined(); expect(vm.message).toBe('')
  })
  it('卸载后迟到入库不emit、不清记录或提示', async () => {
    const { wrapper, vm } = await mountPage(); await vm.open('RECEIPT'); vm.entries[0]!.quantity = '200'; vm.entries[0]!.zone = 'received-zone'
    let resolve!: (value: TubeOrderDetail) => void
    vi.mocked(api.receiveTubePlan).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const submitting = vm.submit(); const raw = localStorage.getItem(key)!
    wrapper.unmount(); resolve(receivedResult((JSON.parse(raw) as TubePlanPendingAction).payload.client_request_id)); await submitting
    expect(localStorage.getItem(key)).toBe(raw); expect(wrapper.emitted('updated')).toBeUndefined(); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it('订单props切换后不能清旧单pending或emit旧单结果', async () => {
    const { wrapper, vm } = await mountPage(); await vm.open('RECEIPT'); vm.entries[0]!.quantity = '200'; vm.entries[0]!.zone = 'received-zone'
    let resolve!: (value: TubeOrderDetail) => void
    vi.mocked(api.receiveTubePlan).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const submitting = vm.submit(); const raw = localStorage.getItem(key)!
    await wrapper.setProps({ order: { ...structuredClone(order), id: 'another-plan' } })
    resolve(receivedResult((JSON.parse(raw) as TubePlanPendingAction).payload.client_request_id)); await submitting
    expect(localStorage.getItem(key)).toBe(raw); expect(wrapper.emitted('updated')).toBeUndefined(); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it.each(['', '{broken', '{"payload":{"client_request_id":"unknown"}}'])('unknown历史总单动作原样隔离：%s', async raw => {
    const unknownKey = 'tube-outsourcing-plan-action:v1:unknown:plan-1'; localStorage.setItem(unknownKey, raw)
    const { wrapper, vm } = await mountPage(); await vm.open('RECEIPT'); await vm.submit(); await vm.postPending()
    expect(localStorage.getItem(unknownKey)).toBe(raw); expect(localStorage.getItem(key)).toBeNull()
    expect(receipts.fetchTubeReceiptPreview).not.toHaveBeenCalled(); expect(api.fetchTubeOrder).not.toHaveBeenCalled(); expect(api.receiveTubePlan).not.toHaveBeenCalled()
    expect(wrapper.findAllComponents({ name: 'ElAlert' }).some(alert => String(alert.props('title')).includes('身份不明'))).toBe(true)
  })
  it('未核验身份不访问存储或API且显示原因', async () => {
    Object.assign(auth, { identityReady: false })
    const storage = vi.spyOn(Storage.prototype, 'getItem')
    const { wrapper, vm } = await mountPage(); await vm.open('RECEIPT'); await vm.submit()
    expect(storage).not.toHaveBeenCalled(); expect(receipts.fetchTubeReceiptPreview).not.toHaveBeenCalled(); expect(api.receiveTubePlan).not.toHaveBeenCalled()
    expect(wrapper.findAllComponents({ name: 'ElAlert' }).some(alert => String(alert.props('title')).includes('身份尚未核验'))).toBe(true)
    storage.mockRestore()
  })
  it('存储不可用时显示原因且不加载或提交', async () => {
    const storage = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('存储禁用') })
    const { wrapper, vm } = await mountPage(); await vm.open('RECEIPT'); await vm.submit()
    expect(api.fetchTubeOrder).not.toHaveBeenCalled(); expect(api.receiveTubePlan).not.toHaveBeenCalled()
    expect(wrapper.findAllComponents({ name: 'ElAlert' }).some(alert => String(alert.props('title')).includes('存储不可用'))).toBe(true)
    storage.mockRestore()
  })
  it('保存请求编号失败时显示阻断且不入库', async () => {
    const { vm } = await mountPage(); await vm.open('RECEIPT'); vm.entries[0]!.quantity = '200'; vm.entries[0]!.zone = 'received-zone'
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('存储禁用') }); await vm.submit()
    expect(vm.message).toContain('无法保存请求编号'); expect(vm.pending).toBeNull(); expect(api.receiveTubePlan).not.toHaveBeenCalled()
  })
  it('清理存储失败保留原请求，不emit或成功提示', async () => {
    const { wrapper, vm } = await mountPage(); await vm.open('RECEIPT'); vm.entries[0]!.quantity = '200'; vm.entries[0]!.zone = 'received-zone'
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('存储禁用') }); await vm.submit()
    expect(localStorage.getItem(key)).not.toBeNull(); expect(vm.pending).not.toBeNull(); expect(wrapper.emitted('updated')).toBeUndefined(); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it.each(['', '{broken'])('当前账号损坏或空raw保留且不加载API：%s', async raw => {
    localStorage.setItem(key, raw); const { wrapper, vm } = await mountPage(); await vm.open('RECEIPT'); await vm.submit()
    expect(localStorage.getItem(key)).toBe(raw); expect(api.fetchTubeOrder).not.toHaveBeenCalled(); expect(receipts.fetchTubeReceiptPreview).not.toHaveBeenCalled(); expect(api.receiveTubePlan).not.toHaveBeenCalled()
    expect(wrapper.findAllComponents({ name: 'ElAlert' }).length).toBeGreaterThan(0)
  })
  it('拒绝后刷新GET迟到时不emit新身份页面', async () => {
    const { wrapper, vm } = await mountPage(); await vm.open('RECEIPT'); vm.entries[0]!.quantity = '200'; vm.entries[0]!.zone = 'received-zone'
    vi.mocked(api.receiveTubePlan).mockRejectedValueOnce(Object.assign(new AxiosError('版本变化'), { response: { status: 412 } }))
    let resolve!: (value: TubeOrderDetail) => void
    vi.mocked(api.fetchTubeOrder).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const submitting = vm.submit(); await flushPromises(); expect(api.fetchTubeOrder).toHaveBeenCalledTimes(1)
    auth.identityRequestGeneration += 1; resolve(structuredClone(order)); await submitting
    expect(wrapper.emitted('updated')).toBeUndefined(); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it('清理只删除本页原raw，保留另一页面替换记录', async () => {
    const { wrapper, vm } = await mountPage(); await vm.open('RECEIPT'); vm.entries[0]!.quantity = '200'; vm.entries[0]!.zone = 'received-zone'
    let resolve!: (value: TubeOrderDetail) => void
    vi.mocked(api.receiveTubePlan).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const submitting = vm.submit(); const original = localStorage.getItem(key)!
    const newer = '{"payload":{"client_request_id":"new-page"}}'; localStorage.setItem(key, newer)
    resolve(receivedResult((JSON.parse(original) as TubePlanPendingAction).payload.client_request_id)); await submitting
    expect(localStorage.getItem(key)).toBe(newer); expect(vm.pending).not.toBeNull(); expect(wrapper.emitted('updated')).toBeUndefined(); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it('普通同身份核验不改变代次，原总单操作正常完成', async () => {
    const { wrapper, vm } = await mountPage(); await vm.open('RECEIPT'); vm.entries[0]!.quantity = '200'; vm.entries[0]!.zone = 'received-zone'
    let resolve!: (value: TubeOrderDetail) => void
    vi.mocked(api.receiveTubePlan).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const submitting = vm.submit(); const raw = localStorage.getItem(key)!
    auth.user = { ...auth.user! }; resolve(receivedResult((JSON.parse(raw) as TubePlanPendingAction).payload.client_request_id)); await submitting
    expect(localStorage.getItem(key)).toBeNull(); expect(wrapper.emitted('updated')).toHaveLength(1); expect(ElMessage.success).toHaveBeenCalledTimes(1)
  })
  it('实际外发记录保留裁片辅料实际数量、加工厂和来源库区', async () => {
    const value = structuredClone(order)
    value.source_kind = 'SEWING'
    value.dispatch_records = [{ id: 'dispatch-1', client_request_id: 'dispatch-request', order_number: 'WF-batch', actual_dispatch_date: '2026-10-29', created_at: '', actor_name: '经办人', source_kind: 'SEWING', zone_name: '', total_quantity: '100', lines: [], materials: [{
      id: 'material-1', bom_line_id: 'bom-material-1', material_number: 'FL-1', name: '织唛', specification: '30mm', material: '涤纶', color: '黑', unit: '个', quantity: '12.5',
      component_identity: null, order_line_id: null, part_name: '', factory_id: 'factory-1', factory_name: '加工厂', zone_id: 'material-zone', zone_name: '辅料区', warehouse_id: 'material-warehouse', warehouse_name: '辅料仓',
    }] }]
    const { wrapper } = await mountPage(value)
    expect(wrapper.getComponent({ name: 'TubeOutsourcingPlanRecords' }).props('order').dispatch_records[0].materials).toEqual(value.dispatch_records[0]!.materials)
  })
  it('计划辅料和实发记录保留各自快照，登记外发只读取本次来源材料', async () => {
    const value = structuredClone(order)
    value.source_kind = 'SEWING'
    const planned = { ...auxiliarySnapshot, name: '计划保存织带', unit_name: '卷' }
    const dispatched = { ...auxiliarySnapshot, name: '实发保存织带', unit_name: '盒' }
    value.planned_materials = [{ bom_line_id: 'bom-material-1', quantity: '3', factory_id: 'factory-1', zone_id: 'material-zone', factory_name: '加工厂',
      name: planned.name, unit: planned.unit_name, material_catalog_id: planned.catalog_id, material_selection_snapshot: planned }]
    value.dispatch_records = [{ id: 'dispatch-1', client_request_id: 'dispatch-request', order_number: 'WF-batch', actual_dispatch_date: '2026-10-29', created_at: '', actor_name: '经办人', source_kind: 'SEWING', zone_name: '', total_quantity: '100', lines: [], materials: [{
      id: 'material-1', bom_line_id: 'bom-material-1', material_number: 'FL-1', name: dispatched.name, specification: '30mm', material: '涤纶', color: '黑', unit: dispatched.unit_name, quantity: '2',
      component_identity: null, order_line_id: null, part_name: '', factory_id: 'factory-1', factory_name: '加工厂', zone_id: 'material-zone', zone_name: '辅料区', warehouse_id: 'material-warehouse', warehouse_name: '辅料仓',
      material_catalog_id: dispatched.catalog_id, material_selection_snapshot: dispatched,
    }] }]
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(sourceContext), source_kind: 'SEWING', material_rows: [{
      bom_line_id: 'bom-material-1', material_number: 'FL-1', name: auxiliarySnapshot.name, specification: '30mm', material: '涤纶', color: '黑', unit: auxiliarySnapshot.unit_name,
      required_quantity: '10', order_remaining: '8', available_stock: '8', max_quantity: '8', blockers: [], zones: [],
      material_catalog_id: auxiliarySnapshot.catalog_id, material_selection_snapshot: auxiliarySnapshot,
    }] })
    const { wrapper, vm } = await mountPage(value)
    expect(wrapper.text()).toContain('计划保存织带 3 卷')
    expect(wrapper.getComponent({ name: 'TubeOutsourcingPlanRecords' }).props('order').dispatch_records[0].materials[0].material_selection_snapshot).toEqual(dispatched)
    expect(wrapper.findAllComponents(ProcessingMaterialDetails).map(item => item.props('materials'))).toEqual([
      { input_material_selection_snapshot: planned },
    ])
    await vm.open('DISPATCH'); await flushPromises()
    expect(wrapper.findAllComponents(ProcessingMaterialDetails).map(item => item.props('materials'))).toEqual([
      { input_material_selection_snapshot: planned }, ...sourceContext.rows, { input_material_selection_snapshot: auxiliarySnapshot },
    ])
  })
  it('计划可超过BOM，累计实发在总单数量内时仍可分批外发', async () => {
    const value = structuredClone(order); value.lines[0]!.quantity = '2700'
    const { vm } = await mountPage(value)
    await vm.open('DISPATCH'); vm.entries[0]!.quantity = '1500'; await vm.submit()
    expect(api.fetchTubeSource).toHaveBeenCalledWith(expect.objectContaining({ plan_id: 'plan-1', source_kind: 'PUBLIC_SEMI' }))
    expect(api.dispatchTubePlan).toHaveBeenCalledWith('plan-1', expect.objectContaining({ lines: [{ component_identity: 'part-1', quantity: '1500', factory_id: 'factory-1', unit_price: '0.25' }] }), 'v1')
    expect(localStorage.getItem(key)).toBeNull()
  })
  it.each(['METAL', 'SEWING', 'PUBLIC_SEMI', 'PUBLIC_CUTTING'] as const)('%s按总单数量减累计已发限制本次外发', async sourceKind => {
    const value = structuredClone(order); value.source_kind = sourceKind; value.lines[0]!.quantity = '1500'
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(sourceContext), source_kind: sourceKind })
    const { vm } = await mountPage(value)
    await vm.open('DISPATCH'); vm.entries[0]!.quantity = '301'; await vm.submit()
    expect(api.dispatchTubePlan).not.toHaveBeenCalled()
    expect(vm.message).toContain(`最多可发 300 ${sourceKind === 'SEWING' || sourceKind === 'PUBLIC_CUTTING' ? '套' : '支'}`)
    vm.entries[0]!.quantity = '300'; await vm.submit()
    expect(api.dispatchTubePlan).toHaveBeenCalledWith('plan-1', expect.objectContaining({ lines: [expect.objectContaining({ quantity: '300' })] }), 'v1')
  })
  it('历史累计已发超过总单时不能继续增加外发', async () => {
    const { vm } = await mountPage()
    await vm.open('DISPATCH'); vm.entries[0]!.quantity = '1'; await vm.submit()
    expect(api.dispatchTubePlan).not.toHaveBeenCalled(); expect(vm.message).toContain('最多可发 0 支')
  })
  it('发货仍受当前实际库存约束，不把计划额度当库存', async () => {
    const { vm } = await mountPage()
    await vm.open('DISPATCH'); vm.entries[0]!.quantity = '2401'; await vm.submit()
    expect(api.dispatchTubePlan).not.toHaveBeenCalled(); expect(vm.message).toContain('最多可发2400')
  })
  it('按总单独立入库，支持部分部件且禁止超过累计实发', async () => {
    const { vm } = await mountPage()
    await vm.open('RECEIPT'); vm.entries[0]!.quantity = '401'; vm.entries[0]!.zone = 'received-zone'; await vm.submit()
    expect(api.receiveTubePlan).not.toHaveBeenCalled(); expect(vm.message).toContain('累计入库不能超过')
    vm.entries[0]!.quantity = '200'; await vm.submit()
    const payload = vi.mocked(api.receiveTubePlan).mock.calls[0]![1]
    expect(payload.lines).toEqual([{ order_line_id: 'line-1', received_quantity: '200', zone_id: 'received-zone' }])
    expect(payload).not.toHaveProperty('dispatch_id'); expect(payload).not.toHaveProperty('batch_id')
  })
  it('已达BOM目标仍可继续收剩余外发，数量不截断到BOM', async () => {
    const value = structuredClone(order)
    value.plan_summary!.receipt_progress = 100; value.lines[0]!.received_quantity = '1000'; value.lines[0]!.receivable_quantity = '200'
    const { vm } = await mountPage(value)
    expect(vm.canReceive).toBe(true)
    await vm.open('RECEIPT'); vm.entries[0]!.quantity = '200'; vm.entries[0]!.zone = 'received-zone'; await vm.submit()
    expect(api.receiveTubePlan).toHaveBeenCalledOnce()
  })
  it('超时保留原请求，重试相同编号及ETag后才清理', async () => {
    vi.mocked(api.receiveTubePlan).mockRejectedValueOnce(new AxiosError('超时'))
    const { vm } = await mountPage()
    await vm.open('RECEIPT'); vm.entries[0]!.quantity = '200'; vm.entries[0]!.zone = 'received-zone'; await vm.submit()
    const original = JSON.parse(localStorage.getItem(key)!) as TubePlanPendingAction
    expect(vm.pending).not.toBeNull(); await vm.postPending()
    expect(api.receiveTubePlan).toHaveBeenLastCalledWith('plan-1', original.payload, original.etag)
    expect(api.receiveTubePlan).toHaveBeenCalledTimes(2); expect(vm.pending).toBeNull(); expect(localStorage.getItem(key)).toBeNull()
  })
  it('刷新查到原请求已成功时不再次POST', async () => {
    localStorage.setItem(key, JSON.stringify({ order_id: 'plan-1', etag: 'v1', kind: 'RECEIPT', payload: { client_request_id: 'previous', receipt_date: '2026-10-29', warehouse_id: 'warehouse-1', remark: '', lines: [{ order_line_id: 'line-1', received_quantity: '200', zone_id: 'received-zone' }] } }))
    vi.mocked(api.fetchTubeOrder).mockResolvedValue(receivedResult('previous'))
    const { vm } = await mountPage()
    expect(vm.pending).toBeNull(); expect(api.receiveTubePlan).not.toHaveBeenCalled(); expect(localStorage.getItem(key)).toBeNull()
  })
  it('挂载恢复查询未完成时禁止手动重放，GET确认成功只清理一次', async () => {
    const action: TubePlanPendingAction = { order_id: 'plan-1', etag: 'v1', kind: 'RECEIPT', payload: { client_request_id: 'recovering', receipt_date: '2026-11-02', warehouse_id: 'warehouse-1', remark: '', lines: [{ order_line_id: 'line-1', received_quantity: '200', zone_id: 'received-zone' }] } }
    const raw = JSON.stringify(action); localStorage.setItem(key, raw)
    let resolve!: (value: TubeOrderDetail) => void
    vi.mocked(api.fetchTubeOrder).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const remove = vi.spyOn(Storage.prototype, 'removeItem')
    const { wrapper, vm } = await mountPage(structuredClone(order), true, { actionOnly: true, entryAction: 'return' })
    try {
      const verify = wrapper.findAll('button').find(button => button.text() === '核对本次提交')!
      expect(verify.attributes('disabled')).toBeDefined()
      await vm.postPending()
      expect(api.receiveTubePlan).not.toHaveBeenCalled(); expect(localStorage.getItem(key)).toBe(raw)
    } finally { resolve(receivedResult('recovering')); await flushPromises() }
    expect(vm.pending).toBeNull(); expect(localStorage.getItem(key)).toBeNull()
    expect(remove.mock.calls.filter(([storageKey]) => storageKey === key)).toHaveLength(1)
    expect(vm.message).not.toContain('本地待核对记录已被其他页面更新')
    await vm.postPending(); expect(api.receiveTubePlan).not.toHaveBeenCalled()
  })
  it('挂载恢复GET失败后释放查询锁，原请求仍可核对', async () => {
    const action: TubePlanPendingAction = { order_id: 'plan-1', etag: 'v1', kind: 'RECEIPT', payload: { client_request_id: 'recover-failed', receipt_date: '2026-11-02', warehouse_id: 'warehouse-1', remark: '', lines: [{ order_line_id: 'line-1', received_quantity: '200', zone_id: 'received-zone' }] } }
    const raw = JSON.stringify(action); localStorage.setItem(key, raw)
    let reject!: (cause: unknown) => void
    vi.mocked(api.fetchTubeOrder).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail }))
    const { wrapper, vm } = await mountPage(structuredClone(order), true, { actionOnly: true, entryAction: 'return' })
    try {
      await vm.postPending(); expect(api.receiveTubePlan).not.toHaveBeenCalled()
    } finally { reject(new AxiosError('恢复查询失败')); await flushPromises() }
    expect(localStorage.getItem(key)).toBe(raw); expect(vm.pending).toEqual(action)
    expect(vm.message).toContain('待核对记录读取失败')
    const verify = wrapper.findAll('button').find(button => button.text() === '核对本次提交')!
    expect(verify.attributes('disabled')).toBeUndefined()
    await vm.postPending()
    expect(api.receiveTubePlan).toHaveBeenCalledWith(order.id, action.payload, 'v1')
    expect(localStorage.getItem(key)).toBeNull()
  })
  it.each([403, 404])('未知提交再次核对遭%s拒绝时不遗忘原请求', async status => {
    vi.mocked(api.receiveTubePlan).mockRejectedValueOnce(new AxiosError('超时')).mockRejectedValueOnce(Object.assign(new AxiosError('权限变化'), { response: { status, data: { error: { message: '无权限' } } } }))
    const { vm } = await mountPage()
    await vm.open('RECEIPT'); vm.entries[0]!.quantity = '200'; vm.entries[0]!.zone = 'received-zone'; await vm.submit()
    const saved = localStorage.getItem(key)
    await vm.postPending()
    expect(localStorage.getItem(key)).toBe(saved); expect(vm.pending).not.toBeNull(); expect(vm.message).toContain('保留请求编号')
  })
  it('无实际收发权限或非仓库页面不打开写入流程', async () => {
    const { vm } = await mountPage(structuredClone(order), false)
    await vm.open('DISPATCH'); await vm.open('RECEIPT'); await vm.submit()
    expect(vm.mode).toBe(''); expect(api.dispatchTubePlan).not.toHaveBeenCalled(); expect(api.receiveTubePlan).not.toHaveBeenCalled()
  })
})

function correctionOrder(): TubeOrderDetail {
  const result = receivedResult('original-create')
  return { ...result, etag: 'fresh-v3', permissions: { ...result.permissions, can_correct_dispatch: true, can_correct_receive: true }, receipt_records: result.receipt_records!.map(record => ({ ...record, remark: '已保存入库备注' })) }
}
const correctionDraft: TubePlanRecordCorrectionDraft = { record_kind: 'RECEIPT', record_id: 'receipt-1', operation: 'UPDATE', business_date: '2026-11-02', lines: [{ component_identity: 'part-1', quantity: '180' }] }
function correctionResult(input: TubePlanRecordCorrectionInput): TubeOrderDetail {
  return { ...correctionOrder(), etag: 'corrected-v4', record_correction: {
    id: 'correction-id', client_request_id: input.client_request_id, record_kind: input.record_kind, record_id: input.record_id, operation: input.operation, created_at: '2026-11-02T10:00:00+08:00',
  } }
}
function correctionError(status: number, code = 'VALIDATION_ERROR') {
  return Object.assign(new AxiosError('更正拒绝'), { response: { status, data: { error: { code, message: '库存或版本需核对' } } } })
}
async function readyCorrection() {
  const mounted = await mountPage(correctionOrder())
  mounted.vm.correctionActive = true
  mounted.vm.preparedCorrection(correctionOrder())
  return mounted
}
describe('总单记录更正的持久请求协调', () => {
  it('真实父子组件联动：保留编辑窗提交，回执成功后关闭并更新实际入库记录', async () => {
    vi.mocked(api.fetchTubeOrder).mockResolvedValue(correctionOrder())
    let resolve!: (result: TubeOrderDetail) => void
    vi.mocked(api.correctTubePlanRecord).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const wrapper = mount(TubeOutsourcingPlanDetail, { props: { order: correctionOrder(), warehouse: true, onUpdated: value => { void wrapper.setProps({ order: value }) } }, global: { plugins: [ElementPlus], stubs: {
      AppWindowDialog: { props: ['modelValue', 'title', 'width'], template: '<section v-if="modelValue" role="dialog" :aria-label="title"><slot/><slot name="footer"/></section>' },
    } } })
    wrappers.push(wrapper); await flushPromises()
    await wrapper.get('button[aria-label="查看入库明细 RK-test"]').trigger('click'); await flushPromises()
    const click = async (label: string) => { await wrapper.get('[role="dialog"]').findAll('button').find(button => button.text() === label)!.trigger('click'); await flushPromises() }
    await click('调整记录'); await wrapper.get('input[aria-label="横管调整数量"]').setValue('180'); await click('保存调整')
    expect(wrapper.find('[aria-label="入库记录明细"]').exists()).toBe(true)
    expect(wrapper.get('input[aria-label="横管调整数量"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.plan-receipt-records').findAll('button').find(button => button.text() === '外发入库')!.attributes('disabled')).toBeDefined()
    const input = vi.mocked(api.correctTubePlanRecord).mock.calls[0]![1]
    const result = correctionResult(input)
    result.receipt_records![0]!.total_received_quantity = '180'; result.receipt_records![0]!.lines[0]!.received_quantity = '180'
    resolve(result); await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.get('.plan-receipt-records').text()).toContain('180'); expect(localStorage.getItem(key)).toBeNull()
  })
  it('用刚核对的父版本保存完整原部件，成功只认对应更正回执', async () => {
    vi.mocked(api.correctTubePlanRecord).mockImplementation(async (_, input) => {
      expect(JSON.parse(localStorage.getItem(key)!).payload).toEqual(input)
      return correctionResult(input)
    })
    const { vm, wrapper } = await readyCorrection()
    await vm.submitCorrection(structuredClone(correctionDraft), 'fresh-v3')
    expect(api.correctTubePlanRecord).toHaveBeenCalledWith('plan-1', { ...correctionDraft, client_request_id: expect.any(String) }, 'fresh-v3')
    expect(localStorage.getItem(key)).toBeNull(); expect(vm.pending).toBeNull(); expect(vm.correctionActive).toBe(false)
    expect(wrapper.emitted('updated')!.at(-1)![0]).toMatchObject({ etag: 'corrected-v4' })
  })
  it('整次删除请求不夹带明细或原因，不用记录消失判成功', async () => {
    vi.mocked(api.correctTubePlanRecord).mockResolvedValue({ ...correctionOrder(), receipt_records: [], record_correction: undefined })
    const { vm } = await readyCorrection()
    const input: TubePlanRecordCorrectionDraft = { record_kind: 'RECEIPT', record_id: 'receipt-1', operation: 'DELETE' }
    await vm.submitCorrection(input, 'fresh-v3')
    expect(api.correctTubePlanRecord).toHaveBeenCalledWith('plan-1', { ...input, client_request_id: expect.any(String) }, 'fresh-v3')
    expect(vm.pending).not.toBeNull(); expect(localStorage.getItem(key)).not.toBeNull(); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it.each(['client_request_id', 'record_kind', 'record_id', 'operation', 'id', 'created_at'] as const)('回执%s不符或缺失不清请求、不提示成功', async field => {
    vi.mocked(api.correctTubePlanRecord).mockImplementation(async (_, input) => {
      const result = correctionResult(input)
      Object.assign(result.record_correction!, { [field]: field === 'id' || field === 'created_at' ? '' : 'wrong' })
      return result
    })
    const { vm } = await readyCorrection(); await vm.submitCorrection(structuredClone(correctionDraft), 'fresh-v3')
    expect(vm.pending).not.toBeNull(); expect(localStorage.getItem(key)).not.toBeNull(); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it('超时后GET404保留原参数，随后同编号同ETag重放成功', async () => {
    vi.mocked(api.correctTubePlanRecord).mockRejectedValueOnce(new AxiosError('超时')).mockImplementationOnce(async (_, input) => correctionResult(input))
    vi.mocked(api.findTubePlanRecordCorrection).mockRejectedValueOnce(correctionError(404))
    const { vm } = await readyCorrection(); await vm.submitCorrection(structuredClone(correctionDraft), 'fresh-v3')
    const raw = localStorage.getItem(key)!, original = JSON.parse(raw) as Extract<TubePlanPendingAction, { kind: 'CORRECTION' }>
    await vm.checkCorrection()
    expect(localStorage.getItem(key)).toBe(raw); expect(vm.message).toContain('尚未查到')
    await vm.postPending()
    expect(api.correctTubePlanRecord).toHaveBeenLastCalledWith('plan-1', original.payload, original.etag)
    expect(localStorage.getItem(key)).toBeNull()
  })
  it.each([400, 409, 412, 428])('明确回滚%s保留编辑会话并要求重新核对，禁止沿旧版本再提交', async status => {
    vi.mocked(api.correctTubePlanRecord).mockRejectedValue(correctionError(status))
    const { vm } = await readyCorrection(); await vm.submitCorrection(structuredClone(correctionDraft), 'fresh-v3')
    expect(vm.pending).toBeNull(); expect(localStorage.getItem(key)).toBeNull(); expect(vm.correctionActive).toBe(true)
    expect(vm.correctionRefreshRequired).toBe(true); expect(vm.message).toContain('保留填写内容')
    await vm.submitCorrection(structuredClone(correctionDraft), 'fresh-v3')
    expect(api.correctTubePlanRecord).toHaveBeenCalledTimes(1)
  })
  it('UUID内容冲突409保留请求并GET核对，不当普通业务回滚清除', async () => {
    vi.mocked(api.correctTubePlanRecord).mockRejectedValue(correctionError(409, 'IDEMPOTENCY_CONFLICT'))
    vi.mocked(api.findTubePlanRecordCorrection).mockRejectedValue(correctionError(404))
    const { vm } = await readyCorrection(); await vm.submitCorrection(structuredClone(correctionDraft), 'fresh-v3')
    expect(api.findTubePlanRecordCorrection).toHaveBeenCalledOnce(); expect(vm.pending).not.toBeNull(); expect(localStorage.getItem(key)).not.toBeNull()
  })
  it('冲突回执即使共有字段相同也不认成功，刷新保留冲突标志且禁止POST重放', async () => {
    vi.mocked(api.correctTubePlanRecord).mockRejectedValue(correctionError(409, 'IDEMPOTENCY_CONFLICT'))
    vi.mocked(api.findTubePlanRecordCorrection).mockImplementation(async () => correctionResult((JSON.parse(localStorage.getItem(key)!) as Extract<TubePlanPendingAction, { kind: 'CORRECTION' }>).payload))
    const first = await readyCorrection(); await first.vm.submitCorrection(structuredClone(correctionDraft), 'fresh-v3')
    const raw = localStorage.getItem(key)!, stored = JSON.parse(raw) as Extract<TubePlanPendingAction, { kind: 'CORRECTION' }>
    expect(stored.request_conflict).toBe(true); expect(stored.payload).toMatchObject(correctionDraft)
    expect(ElMessage.success).not.toHaveBeenCalled(); expect(first.vm.message).toContain('不能据此确认')
    first.wrapper.unmount()
    const restored = await mountPage(correctionOrder(), true, { actionOnly: true, entryAction: 'dispatch' })
    expect(localStorage.getItem(key)).toBe(raw); expect(restored.vm.message).toContain('不会自动重放')
    expect(restored.wrapper.text()).not.toContain('按原请求重试')
    await restored.vm.postPending(); expect(api.correctTubePlanRecord).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(key)).toBe(raw); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it('冲突标记无法保存时停止自动核对，不清原请求或发起新的写入', async () => {
    vi.mocked(api.correctTubePlanRecord).mockImplementation(async () => {
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('存储失效') })
      throw correctionError(409, 'IDEMPOTENCY_CONFLICT')
    })
    const { vm, wrapper } = await readyCorrection(); await vm.submitCorrection(structuredClone(correctionDraft), 'fresh-v3')
    expect(localStorage.getItem(key)).not.toBeNull(); expect(wrapper.text()).toContain('冲突标记未能写入')
    await vm.checkCorrection(); await vm.postPending()
    expect(api.findTubePlanRecordCorrection).not.toHaveBeenCalled(); expect(api.correctTubePlanRecord).toHaveBeenCalledTimes(1)
  })
  it.each([403, 404, 500])('更正%s或未知结果不清待核对请求', async status => {
    vi.mocked(api.correctTubePlanRecord).mockRejectedValue(correctionError(status))
    const { vm } = await readyCorrection(); await vm.submitCorrection(structuredClone(correctionDraft), 'fresh-v3')
    expect(localStorage.getItem(key)).not.toBeNull(); expect(vm.pending?.kind).toBe('CORRECTION')
  })
  it('保存中更正记录组件保持打开，仅busy和pending锁定；普通收发互斥', async () => {
    let resolve!: (result: TubeOrderDetail) => void
    vi.mocked(api.correctTubePlanRecord).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const { vm, wrapper } = await readyCorrection()
    const saving = vm.submitCorrection(structuredClone(correctionDraft), 'fresh-v3'); await flushPromises()
    const record = wrapper.findComponent({ name: 'TubeOutsourcingPlanRecords' })
    expect(record.props('blocked')).toBe(false); expect(record.props('busy')).toBe(true); expect(record.props('pending')).toBe(true)
    await vm.open('DISPATCH'); await vm.open('RECEIPT'); await vm.submitCorrection(structuredClone(correctionDraft), 'fresh-v3')
    expect(vm.mode).toBe(''); expect(api.correctTubePlanRecord).toHaveBeenCalledOnce(); expect(api.fetchTubeSource).not.toHaveBeenCalled()
    const action = vm.pending as Extract<TubePlanPendingAction, { kind: 'CORRECTION' }>
    resolve(correctionResult(action.payload)); await saving
  })
  it.each(['zero', 'missing', 'extra', 'duplicate'] as const)('拒绝%s部件集合或数量，不把0当删除明细', async reason => {
    const { vm } = await readyCorrection()
    const input = structuredClone(correctionDraft)
    if (input.operation !== 'UPDATE') throw new Error('fixture')
    if (reason === 'zero') input.lines[0]!.quantity = '0'
    else if (reason === 'missing') input.lines = []
    else input.lines.push({ component_identity: reason === 'extra' ? 'other' : 'part-1', quantity: '1' })
    await vm.submitCorrection(input, 'fresh-v3')
    expect(api.correctTubePlanRecord).not.toHaveBeenCalled(); expect(localStorage.getItem(key)).toBeNull()
  })
  it('存储失败不发送更正，另一页面已有待核对记录也不覆盖', async () => {
    const { vm } = await readyCorrection()
    localStorage.setItem(key, 'other-window')
    await vm.submitCorrection(structuredClone(correctionDraft), 'fresh-v3')
    expect(localStorage.getItem(key)).toBe('other-window'); expect(api.correctTubePlanRecord).not.toHaveBeenCalled()
    localStorage.removeItem(key)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => { throw new Error('存储不可用') })
    await vm.submitCorrection(structuredClone(correctionDraft), 'fresh-v3')
    expect(api.correctTubePlanRecord).not.toHaveBeenCalled(); expect(vm.message).toContain('尚未提交')
  })
  it.each(['identity', 'order', 'warehouse', 'blocked', 'unmount'] as const)('%s变化后更正迟到成功不清所属请求或覆盖页面', async boundary => {
    let resolve!: (result: TubeOrderDetail) => void
    vi.mocked(api.correctTubePlanRecord).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const { vm, wrapper } = await readyCorrection(); const saving = vm.submitCorrection(structuredClone(correctionDraft), 'fresh-v3')
    const raw = localStorage.getItem(key)!, action = JSON.parse(raw) as Extract<TubePlanPendingAction, { kind: 'CORRECTION' }>
    const count = wrapper.emitted('updated')?.length
    if (boundary === 'identity') auth.identityGeneration += 1
    else if (boundary === 'order') await wrapper.setProps({ order: { ...correctionOrder(), id: 'other-plan' } })
    else if (boundary === 'warehouse') await wrapper.setProps({ warehouse: false })
    else if (boundary === 'blocked') await wrapper.setProps({ blocked: true })
    else wrapper.unmount()
    resolve(correctionResult(action.payload)); await saving
    expect(localStorage.getItem(key)).toBe(raw)
    if (boundary === 'unmount') expect(wrapper.emitted('updated')).toBeUndefined()
    else expect(wrapper.emitted('updated')?.length).toBe(count)
    expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it('刷新恢复更正先GET查询，actionOnly宿主能核对且不再打开新的收发', async () => {
    const action: TubePlanPendingAction = { kind: 'CORRECTION', order_id: 'plan-1', etag: 'fresh-v3', payload: { record_kind: 'RECEIPT', record_id: 'receipt-1', operation: 'DELETE', client_request_id: 'previous-correction' } }
    const raw = JSON.stringify(action); localStorage.setItem(key, raw)
    vi.mocked(api.findTubePlanRecordCorrection).mockRejectedValueOnce(correctionError(404)).mockResolvedValueOnce(correctionResult(action.payload))
    const { vm, wrapper } = await mountPage(correctionOrder(), true, { actionOnly: true, entryAction: 'dispatch' })
    expect(wrapper.find('[aria-label="收发记录更正核对"]').exists()).toBe(true)
    expect(api.fetchTubeSource).not.toHaveBeenCalled(); expect(api.correctTubePlanRecord).not.toHaveBeenCalled(); expect(localStorage.getItem(key)).toBe(raw)
    await vm.checkCorrection()
    expect(localStorage.getItem(key)).toBeNull(); expect(wrapper.emitted('closed')).toHaveLength(1)
  })
  it('恢复核对GET在途时禁止POST，确认回执后只清一次', async () => {
    const action: TubePlanPendingAction = { kind: 'CORRECTION', order_id: 'plan-1', etag: 'fresh-v3', payload: { ...structuredClone(correctionDraft), client_request_id: 'previous-correction' } }
    localStorage.setItem(key, JSON.stringify(action))
    let resolve!: (result: TubeOrderDetail) => void
    vi.mocked(api.findTubePlanRecordCorrection).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const { vm } = await mountPage(correctionOrder())
    await vm.postPending(); await vm.checkCorrection()
    expect(api.correctTubePlanRecord).not.toHaveBeenCalled(); expect(api.findTubePlanRecordCorrection).toHaveBeenCalledOnce()
    resolve(correctionResult(action.payload)); await flushPromises(); expect(localStorage.getItem(key)).toBeNull()
  })
})

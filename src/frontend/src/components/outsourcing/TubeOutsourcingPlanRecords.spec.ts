import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import * as api from '@/api/tubeOutsourcing'
import type { TubeDetailLine, TubeOrderDetail, TubePlanDispatchRecord, TubePlanReceiptRecord } from '@/types/tubeOutsourcing'
import type { MaterialSelectionSnapshot } from '@/types/materialCatalog'
import ProcessingMaterialDetails from '@/components/inventory/ProcessingMaterialDetails.vue'
import TubeOutsourcingPlanRecords from './TubeOutsourcingPlanRecords.vue'

vi.mock('@/stores/auth', async () => {
  const { reactive } = await import('vue')
  const state = reactive({ user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 1, identityRequestGeneration: 1 })
  return { useAuthStore: () => state }
})
vi.mock('@/api/tubeOutsourcing', () => ({ fetchTubeOrder: vi.fn() }))

const auth = useAuthStore()
function resetIdentity() {
  Object.assign(auth, { user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 1, identityRequestGeneration: 1 })
}
const savedMaterial: MaterialSelectionSnapshot = {
  schema_version: 1, catalog_id: 'saved-pipe', catalog_version: 'saved-v1', name: '批次保存方管',
  category_key: 'PIPE', template_key: 'PIPE', scope: 'BASE', processing_state: 'RAW', processing_stage: 'RAW',
  unit_id: 'root', unit_name: '根', attributes: { material: '批次钢', shape: '方管', thickness: '1.5' }, display_name: '批次保存方管',
}
const actualAuxiliarySnapshot: MaterialSelectionSnapshot = {
  ...savedMaterial, catalog_id: 'actual-auxiliary', name: '本批保存织带', display_name: '本批保存织带',
  category_key: 'AUXILIARY', template_key: 'AUXILIARY', unit_id: 'meter', unit_name: '米', attributes: { material: '尼龙', color: '白' },
}
const planLine: TubeDetailLine = {
  id: 'plan-line-1', component_identity: 'component-1', part_name: '总单横管', factory_id: 'planned-factory', factory_name: '计划加工厂',
  quantity: '8000', price_unit: 'SQUARE_METER', unit_area_sqm: '0.125', line_area_sqm: '1000', unit_price: '0.25', planned_amount: '250', stock_quantity: null, meters: null,
  material: '总单钢', specification: '总单Φ22', thickness: '1', cutting_length_mm: '400', raw_color: '本色', spray_color: '总单黑',
  pieces_per_bar: '10', raw_bar_length_m: '6', current_reported_minimum: null, operations: [], basis_blockers: [],
  bom_quantity: '8000', dispatched_quantity: '160', received_quantity: '110', receivable_quantity: '50',
}
const dispatchRecords: TubePlanDispatchRecord[] = [
  { id: 'batch-1', client_request_id: 'dispatch-request-1', order_number: 'WF-BATCH-001', actual_dispatch_date: '2026-11-01', created_at: '2026-11-01T08:00:00+08:00', actor_name: '发出经办甲', source_kind: 'RAW_PIPE', zone_name: '原料一区', total_quantity: '100',
    lines: [{ component_identity: 'component-1', quantity: '100', factory_id: 'batch-factory-1', factory_name: '实际加工厂甲', price_unit: 'SQUARE_METER', unit_area_sqm: '0.125', line_area_sqm: '12.5', unit_price: '0.75', planned_amount: '9.38' }] },
  { id: 'batch-2', client_request_id: 'dispatch-request-2', order_number: 'WF-BATCH-002', actual_dispatch_date: '2026-11-02', created_at: '2026-11-02T08:00:00+08:00', actor_name: '发出经办乙', source_kind: 'PUBLIC_SEMI', zone_name: '半成品二区', total_quantity: '60',
    lines: [{ component_identity: 'component-1', quantity: '60', factory_id: 'batch-factory-2', factory_name: '实际加工厂乙', price_unit: 'PIECE', unit_area_sqm: '0.125', line_area_sqm: '7.5', unit_price: '0.95', planned_amount: '57' }] },
]
const receiptRecords: TubePlanReceiptRecord[] = [
  { id: 'receipt-1', client_request_id: 'receipt-request-1', receipt_number: 'RK-001', receipt_date: '2026-11-02', created_at: '2026-11-02T09:00:00+08:00', actor_name: '入库经办甲', warehouse_id: 'receipt-warehouse', warehouse_name: '已加工仓', total_received_quantity: '90',
    lines: [{ order_line_id: 'plan-line-1', component_identity: 'component-1', received_quantity: '90', zone_id: 'received-zone-1', zone_name: '本次入库一区' }] },
  { id: 'receipt-2', client_request_id: 'receipt-request-2', receipt_number: 'RK-002', receipt_date: '2026-11-02', created_at: '2026-11-02T10:00:00+08:00', actor_name: '入库经办乙', warehouse_id: 'receipt-warehouse', warehouse_name: '已加工仓', total_received_quantity: '20',
    lines: [{ order_line_id: 'plan-line-1', component_identity: 'component-1', received_quantity: '20', zone_id: 'received-zone-2', zone_name: '本次入库二区' }] },
]
const plan: TubeOrderDetail = {
  id: 'plan-1', is_plan: true, order_number: 'WF-PLAN', status: 'PROCESSING', version: 1, etag: '"plan-v1"', created: false,
  client_request_id: 'plan-request', source_kind: 'PUBLIC_SEMI', source_label: '未喷塑半成品', schedule_product_id: 'schedule-product', product_line_id: 'product-line',
  planned_dispatch_date: '2026-11-01', expected_return_date: '2026-11-10', total_quantity: '8000', total_area_sqm: '1000', planned_amount: '250', total_stock_quantity: null, total_meters: null,
  task_order_number: 'DD-PLAN', task_number: 'SC-PLAN', schedule_number: 'PC-PLAN', product_number: 'CP-PLAN', item_number: '', product_name: '测试产品', quantity: '4000', unit: '把', color: '黑',
  zone_id: 'planned-zone', zone_name: '总单库区', warehouse_name: '半成品仓', craft_name: '喷塑', remark: '总单备注', created_at: '', created_by_name: '制单人',
  actual_dispatch_date: null, dispatched_at: null, dispatched_by_name: '', cancelled_at: null, cancelled_by_name: '', cancel_remark: '',
  permissions: { can_dispatch: true, can_cancel: false, can_receive: true, can_correct_dispatch: true, can_correct_receive: true }, lines: [planLine],
  dispatch_records: dispatchRecords, receipt_records: receiptRecords,
  planned_materials: [{ bom_line_id: 'bom-attached', factory_id: 'planned-factory', factory_name: '计划加工厂', quantity: '999', zone_id: 'planned-zone',
    name: '计划用织带', unit: '卷', material_catalog_id: 'planned-auxiliary',
    material_selection_snapshot: { ...actualAuxiliarySnapshot, catalog_id: 'planned-auxiliary', name: '计划用织带', display_name: '计划用织带', unit_id: 'roll', unit_name: '卷' } }],
}
function batch(id = 'batch-1'): TubeOrderDetail {
  const second = id === 'batch-2'
  const value = structuredClone(plan)
  return { ...value, id, plan_id: plan.id, is_plan: false, order_number: second ? 'WF-BATCH-002' : 'WF-BATCH-001',
    source_kind: second ? 'PUBLIC_SEMI' : 'RAW_PIPE', source_label: second ? '未喷塑半成品' : '原材料',
    actual_dispatch_date: second ? '2026-11-02' : '2026-11-01', dispatched_by_name: second ? '发出经办乙' : '发出经办甲',
    zone_name: second ? '半成品二区' : '原料一区', total_quantity: second ? '60' : '100', total_area_sqm: second ? '7.5' : '12.5', planned_amount: second ? '57' : '9.38',
    total_stock_quantity: second ? null : '10', total_meters: second ? null : '60', remark: '本批交接备注',
    lines: [{ ...value.lines[0]!, id: `${id}-line`, part_name: second ? '批次乙横管' : '批次甲横管', material: '批次钢',
      specification: second ? '批次Φ32' : '批次Φ28', cutting_length_mm: second ? '700' : '600', thickness: '1.5', spray_color: second ? '批次蓝' : '批次红',
      quantity: second ? '60' : '100', factory_id: second ? 'batch-factory-2' : 'batch-factory-1', factory_name: second ? '实际加工厂乙' : '实际加工厂甲',
      price_unit: second ? 'PIECE' : 'SQUARE_METER', unit_area_sqm: '0.125', line_area_sqm: second ? '7.5' : '12.5',
      unit_price: second ? '0.95' : '0.75', planned_amount: second ? '57' : '9.38', stock_quantity: second ? null : '10', meters: second ? null : '60',
      input_material_selection_snapshot: savedMaterial,
    }], dispatch_records: [], receipt_records: [],
    materials: [{ id: 'attached-1', bom_line_id: 'bom-attached', component_identity: null, order_line_id: null, part_name: '',
      factory_id: 'batch-factory-1', factory_name: '实际加工厂甲', quantity: '12.5', unit: '米', material_number: 'FL-001', name: '本批保存织带',
      material_catalog_id: 'actual-auxiliary', material_selection_snapshot: actualAuxiliarySnapshot,
      specification: '20mm', material: '尼龙', color: '白', zone_id: 'attached-zone', zone_name: '辅料一区', warehouse_id: 'attached-warehouse', warehouse_name: '辅料仓' }],
  }
}
function httpError(status: number) {
  return Object.assign(new AxiosError('读取失败'), { response: { status, data: { error: { message: `读取被拒绝 ${status}` } } } })
}
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
const wrappers: ReturnType<typeof mount>[] = []
async function mountRecords(order = structuredClone(plan), warehouse = true, blocked = false) {
  const wrapper = mount(TubeOutsourcingPlanRecords, {
    props: { order, warehouse, blocked }, slots: { 'dispatch-action': '<button>宿主材料发出</button>', 'receipt-action': '<button>宿主外发入库</button>' },
    global: { plugins: [ElementPlus], stubs: {
      AppWindowDialog: { props: ['modelValue', 'title', 'width'], template: '<section v-if="modelValue" role="dialog" :aria-label="title" :data-width="width"><slot/><slot name="footer"/></section>' },
    } },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
async function openDispatch(wrapper: ReturnType<typeof mount>, number = 'WF-BATCH-001') {
  await wrapper.get(`button[aria-label="查看外发明细 ${number}"]`).trigger('click')
  await flushPromises()
}
async function openReceipt(wrapper: ReturnType<typeof mount>, number = 'RK-001') {
  await wrapper.get(`button[aria-label="查看入库明细 ${number}"]`).trigger('click')
  await flushPromises()
}
async function closeDialog(wrapper: ReturnType<typeof mount>) {
  const button = wrapper.get('[role="dialog"]').findAll('button').find(item => item.text() === '关闭')!
  expect(button).toBeDefined()
  await button.trigger('click')
  await flushPromises()
}
function records(wrapper: ReturnType<typeof mount>, selector: string) {
  const headers = wrapper.get(selector).findAll('th').map(cell => cell.text())
  return wrapper.get(selector).findAll('tbody tr').map(row => Object.fromEntries(row.findAll('td').map((cell, index) => [headers[index]!, cell.text()])))
}
beforeEach(() => {
  vi.resetAllMocks(); resetIdentity()
  vi.mocked(api.fetchTubeOrder).mockImplementation(async id => id === plan.id
    ? { ...structuredClone(plan), etag: 'fresh-v3', receipt_records: structuredClone(receiptRecords).map(record => ({ ...record, remark: '入库保存备注' })) }
    : batch(id))
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('委外总单历史收发表格', () => {
  it('空记录显示两张真实表格和宿主操作槽，不预读批次', async () => {
    const wrapper = await mountRecords({ ...structuredClone(plan), dispatch_records: [], receipt_records: [] })
    expect(wrapper.get('.plan-dispatch-records').find('table').exists()).toBe(true)
    expect(wrapper.get('.plan-receipt-records').find('table').exists()).toBe(true)
    expect(wrapper.get('.plan-dispatch-records').text()).toContain('宿主材料发出')
    expect(wrapper.get('.plan-receipt-records').text()).toContain('宿主外发入库')
    expect(wrapper.findAll('button[aria-label^="查看外发明细"]')).toHaveLength(0)
    expect(wrapper.findAll('button[aria-label^="查看入库明细"]')).toHaveLength(0)
    expect(api.fetchTubeOrder).not.toHaveBeenCalled()
  })
  it('列表保留每次单号日期数量经办人，按行查看且仓库不显示钱', async () => {
    const wrapper = await mountRecords()
    const dispatch = wrapper.get('.plan-dispatch-records')
    expect(dispatch.findAll('tbody tr')).toHaveLength(2)
    for (const text of ['WF-BATCH-001', 'WF-BATCH-002', '2026-11-01', '2026-11-02', '发出经办甲', '发出经办乙', '100', '60']) expect(dispatch.text()).toContain(text)
    const receipts = wrapper.get('.plan-receipt-records')
    expect(receipts.findAll('tbody tr')).toHaveLength(2)
    for (const text of ['RK-001', 'RK-002', '入库经办甲', '入库经办乙', '90', '20']) expect(receipts.text()).toContain(text)
    expect(wrapper.findAll('th').some(cell => /单价|金额/.test(cell.text()))).toBe(false)
    expect(api.fetchTubeOrder).not.toHaveBeenCalled()
  })
  it('管材外发读真实批次冻结属性与实发厂家，不套用总单；附带料只读', async () => {
    const wrapper = await mountRecords()
    await openDispatch(wrapper)
    expect(api.fetchTubeOrder).toHaveBeenCalledWith('batch-1', true)
    expect(wrapper.get('[aria-label="外发记录明细"]').attributes('data-width')).toBe('1800')
    const table = wrapper.get('.dispatch-record-lines')
    for (const text of ['批次甲横管', '批次钢', '批次Φ28', '方管', '1.5', '批次红', '600', '100', '实际加工厂甲']) expect(table.text()).toContain(text)
    for (const text of ['总单Φ22', '总单钢', '总单黑', '计划加工厂']) expect(table.text()).not.toContain(text)
    expect(table.findAll('th').some(cell => cell.text().includes('支'))).toBe(true)
    expect(table.findAll('th').some(cell => /喷塑面积|计价方式|单价|金额/.test(cell.text()))).toBe(false)
    const materials = wrapper.get('.dispatch-record-materials')
    for (const text of ['本批保存织带', '12.5', '米', '实际加工厂甲', '辅料一区']) expect(materials.text()).toContain(text)
    expect(materials.text()).not.toContain('计划用织带')
    expect(materials.text()).not.toContain('999')
    expect(materials.text()).not.toContain('计划加工厂')
    expect(materials.getComponent(ProcessingMaterialDetails).props('materials')).toEqual({ input_material_selection_snapshot: actualAuxiliarySnapshot })
    expect(wrapper.get('[role="dialog"]').find('input, select').exists()).toBe(false)
  })
  it.each(['PUBLIC_CUTTING', 'SEWING'] as const)('裁片%s外发显示本批颜色片数和裁片规格，不把面料规格混入或套用总单', async sourceKind => {
    const value = structuredClone(plan); value.source_kind = sourceKind
    value.lines[0] = { ...value.lines[0]!, fabric_material: '总单棉布', specification: '总单40×50', fabric_specification: '总单600D', fabric_color: '总单蓝', pieces_per_set: '2' }
    value.dispatch_records![0]!.source_kind = sourceKind
    const saved = batch(); saved.source_kind = sourceKind
    saved.lines[0] = { ...saved.lines[0]!, part_name: '本批座面', fabric_material: '本批涤纶', specification: '本批45×60', fabric_specification: '本批900D', fabric_color: '本批红', pieces_per_set: '4' }
    vi.mocked(api.fetchTubeOrder).mockResolvedValue(saved)
    const wrapper = await mountRecords(value)
    await openDispatch(wrapper)
    const table = wrapper.get('.dispatch-record-lines')
    const headers = table.findAll('th').map(cell => cell.text())
    expect(headers).toEqual(expect.arrayContaining(['材质', '规格', '颜色', '每套片数']))
    expect(headers.some(label => label.includes('套'))).toBe(true)
    expect(headers.some(label => /切割长度|喷塑颜色|厚度/.test(label))).toBe(false)
    expect(records(wrapper, '.dispatch-record-lines')[0]).toMatchObject({ 材质: '本批涤纶', 规格: '本批45×60', 颜色: '本批红', 每套片数: '4' })
    expect(table.text()).not.toContain('总单40×50')
  })
  it('车间外发明细显示批次冻结面积、计价方式、动态单价和金额，仓库不同价款规则不影响只读查询', async () => {
    const wrapper = await mountRecords(structuredClone(plan), false)
    await openDispatch(wrapper)
    expect(api.fetchTubeOrder).toHaveBeenCalledWith('batch-1', false)
    const table = wrapper.get('.dispatch-record-lines')
    expect(table.findAll('th').map(cell => cell.text())).toEqual(expect.arrayContaining(['单支喷塑面积（㎡）', '本批喷塑面积（㎡）', '计价方式', '单价', '金额']))
    for (const text of ['0.125', '12.5', '按㎡', '0.75 元/㎡', '9.38']) expect(table.text()).toContain(text)
    expect(table.text()).not.toContain('0.25')
  })
  it('每次外发独立读取，第二批不遗留第一批厂家规格数量', async () => {
    const wrapper = await mountRecords()
    await openDispatch(wrapper); await closeDialog(wrapper)
    await openDispatch(wrapper, 'WF-BATCH-002')
    expect(vi.mocked(api.fetchTubeOrder).mock.calls).toEqual([['batch-1', true], ['batch-2', true]])
    const table = wrapper.get('.dispatch-record-lines')
    expect(table.text()).toContain('批次乙横管'); expect(table.text()).toContain('实际加工厂乙'); expect(table.text()).toContain('批次Φ32')
    expect(table.text()).not.toContain('批次甲横管'); expect(table.text()).not.toContain('实际加工厂甲')
  })
  it('入库属性来自总单保存部件，数量库区来自本次记录，不关联批次或实际厂家', async () => {
    const wrapper = await mountRecords()
    await openReceipt(wrapper)
    expect(wrapper.get('[aria-label="入库记录明细"]').attributes('data-width')).toBe('1800')
    const table = wrapper.get('.receipt-record-lines')
    expect(table.text()).toContain('总单横管'); expect(table.text()).toContain('总单钢'); expect(table.text()).toContain('总单Φ22')
    expect(table.text()).toContain('90'); expect(table.text()).toContain('本次入库一区')
    expect(table.findAll('th').some(cell => /实际.*厂|加工厂|单价|金额/.test(cell.text()))).toBe(false)
    expect(table.text()).not.toContain('实际加工厂甲'); expect(table.text()).not.toContain('实际加工厂乙')
    expect(api.fetchTubeOrder).not.toHaveBeenCalled()
    await closeDialog(wrapper); await openReceipt(wrapper, 'RK-002')
    expect(wrapper.get('.receipt-record-lines').text()).toContain('20')
    expect(wrapper.get('.receipt-record-lines').text()).toContain('本次入库二区')
    expect(wrapper.get('.receipt-record-lines').text()).not.toContain('本次入库一区')
    expect(api.fetchTubeOrder).not.toHaveBeenCalled()
  })
  it('裁片入库保留总单裁片颜色片数及套单位', async () => {
    const value = structuredClone(plan); value.source_kind = 'PUBLIC_CUTTING'
    value.lines[0] = { ...value.lines[0]!, fabric_material: '保存涤纶', specification: '40×50', fabric_color: '保存紫色', pieces_per_set: '6' }
    const wrapper = await mountRecords(value)
    await openReceipt(wrapper)
    expect(records(wrapper, '.receipt-record-lines')[0]).toMatchObject({ 材质: '保存涤纶', 规格: '40×50', 颜色: '保存紫色', 每套片数: '6' })
    const headers = wrapper.get('.receipt-record-lines').findAll('th').map(cell => cell.text())
    expect(headers.some(label => label.includes('套'))).toBe(true)
    expect(headers.some(label => /切割长度|喷塑颜色|厚度/.test(label))).toBe(false)
    expect(api.fetchTubeOrder).not.toHaveBeenCalled()
  })
  it('入库找不到总单部件时明确缺资料，不按相同component或名称猜测', async () => {
    const value = structuredClone(plan)
    value.receipt_records![0]!.lines[0]!.order_line_id = 'missing-line'
    const wrapper = await mountRecords(value)
    await openReceipt(wrapper)
    const dialog = wrapper.get('[role="dialog"]')
    expect(dialog.text()).toContain('历史部件资料未找到')
    expect(dialog.text()).not.toContain('总单钢')
    expect(api.fetchTubeOrder).not.toHaveBeenCalled()
  })
})

describe('记录读取的权限、错误和迟到保护', () => {
  it.each([403, 500])('读取失败%s不展示批次，重试读取原ID成功', async status => {
    vi.mocked(api.fetchTubeOrder).mockRejectedValueOnce(httpError(status))
    const wrapper = await mountRecords()
    await openDispatch(wrapper)
    expect(wrapper.get('[role="dialog"]').text()).toContain(`读取被拒绝 ${status}`)
    expect(wrapper.find('.dispatch-record-lines').exists()).toBe(false)
    await wrapper.get('[role="dialog"]').findAll('button').find(button => button.text() === '重新加载')!.trigger('click')
    await flushPromises()
    expect(vi.mocked(api.fetchTubeOrder).mock.calls).toEqual([['batch-1', true], ['batch-1', true]])
    expect(wrapper.get('.dispatch-record-lines').text()).toContain('批次甲横管')
  })
  it.each(['id', 'plan_id', 'is_plan'] as const)('批次响应%s不匹配时拒绝展示，不能借用其他单据', async field => {
    const wrong = batch()
    if (field === 'id') wrong.id = 'other-batch'
    else if (field === 'plan_id') wrong.plan_id = 'other-plan'
    else wrong.is_plan = true
    vi.mocked(api.fetchTubeOrder).mockResolvedValue(wrong)
    const wrapper = await mountRecords()
    await openDispatch(wrapper)
    expect(wrapper.find('.dispatch-record-lines').exists()).toBe(false)
    expect(wrapper.get('[role="dialog"]').text()).toMatch(/不匹配|不属于|不一致|无效|核对|不完整/)
  })
  it.each(['blocked', 'identity'] as const)('%s状态不能打开记录或发起请求', async reason => {
    if (reason === 'identity') Object.assign(auth, { identityReady: false })
    const wrapper = await mountRecords(structuredClone(plan), true, reason === 'blocked')
    if (reason === 'blocked') { await openDispatch(wrapper); await openReceipt(wrapper) }
    else {
      expect(wrapper.findAll('button[aria-label^="查看外发明细"]')).toHaveLength(0)
      expect(wrapper.findAll('button[aria-label^="查看入库明细"]')).toHaveLength(0)
    }
    expect(api.fetchTubeOrder).not.toHaveBeenCalled()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })
  it('关闭后迟到的旧批次不能打开弹窗或覆盖随后打开的批次', async () => {
    const first = deferred<TubeOrderDetail>()
    vi.mocked(api.fetchTubeOrder).mockReturnValueOnce(first.promise)
    const wrapper = await mountRecords()
    await openDispatch(wrapper)
    await closeDialog(wrapper)
    await openDispatch(wrapper, 'WF-BATCH-002')
    first.resolve(batch()); await flushPromises()
    expect(wrapper.get('.dispatch-record-lines').text()).toContain('批次乙横管')
    expect(wrapper.get('.dispatch-record-lines').text()).not.toContain('批次甲横管')
  })
  it('同一总单直接切换外发记录，迟到第一批不能覆盖第二批', async () => {
    const first = deferred<TubeOrderDetail>()
    vi.mocked(api.fetchTubeOrder).mockReturnValueOnce(first.promise)
    const wrapper = await mountRecords()
    await openDispatch(wrapper)
    await openDispatch(wrapper, 'WF-BATCH-002')
    first.resolve(batch()); await flushPromises()
    expect(vi.mocked(api.fetchTubeOrder).mock.calls).toEqual([['batch-1', true], ['batch-2', true]])
    expect(wrapper.get('.dispatch-record-lines').text()).toContain('批次乙横管')
    expect(wrapper.get('.dispatch-record-lines').text()).not.toContain('批次甲横管')
  })
  it('第二批加载和失败时清除第一批内容，晚到旧错误不能盖住新记录', async () => {
    const second = deferred<TubeOrderDetail>()
    const wrapper = await mountRecords()
    await openDispatch(wrapper)
    expect(wrapper.get('.dispatch-record-lines').text()).toContain('批次甲横管')
    vi.mocked(api.fetchTubeOrder).mockReturnValueOnce(second.promise)
    await openDispatch(wrapper, 'WF-BATCH-002')
    expect(wrapper.find('.dispatch-record-lines').exists()).toBe(false)
    expect(wrapper.get('[role="status"]').text()).toContain('正在读取')
    await openReceipt(wrapper)
    second.reject(httpError(500)); await flushPromises()
    expect(wrapper.get('.receipt-record-lines').text()).toContain('本次入库一区')
    expect(wrapper.get('[role="dialog"]').text()).not.toContain('读取被拒绝 500')
    expect(wrapper.find('.dispatch-record-lines').exists()).toBe(false)
  })
  it.each(['user', 'generation', 'request', 'ready'] as const)('身份%s改变后迟到批次不能显示', async boundary => {
    const request = deferred<TubeOrderDetail>()
    vi.mocked(api.fetchTubeOrder).mockReturnValueOnce(request.promise)
    const wrapper = await mountRecords()
    await openDispatch(wrapper)
    if (boundary === 'user') auth.user!.id = 8
    else if (boundary === 'generation') auth.identityGeneration += 1
    else if (boundary === 'request') auth.identityRequestGeneration += 1
    else Object.assign(auth, { identityReady: false })
    await flushPromises(); request.resolve(batch()); await flushPromises()
    expect(wrapper.find('.dispatch-record-lines').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('批次甲横管')
  })
  it.each(['order', 'workspace', 'blocked'] as const)('%s变化撤销旧查看上下文，迟到响应不能泄入新界面', async boundary => {
    const request = deferred<TubeOrderDetail>()
    vi.mocked(api.fetchTubeOrder).mockReturnValueOnce(request.promise)
    const wrapper = await mountRecords()
    await openDispatch(wrapper)
    if (boundary === 'order') await wrapper.setProps({ order: { ...structuredClone(plan), id: 'another-plan' } })
    else if (boundary === 'workspace') await wrapper.setProps({ warehouse: false })
    else await wrapper.setProps({ blocked: true })
    request.resolve(batch()); await flushPromises()
    expect(wrapper.find('.dispatch-record-lines').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('批次甲横管')
  })
  it('已打开入库记录后身份失效立即隐藏原总单资料', async () => {
    const wrapper = await mountRecords()
    await openReceipt(wrapper)
    expect(wrapper.get('.receipt-record-lines').text()).toContain('总单钢')
    auth.identityGeneration += 1
    await flushPromises()
    expect(wrapper.find('.receipt-record-lines').exists()).toBe(false)
  })
  it('卸载后迟到响应不产生新的读取或异常', async () => {
    const request = deferred<TubeOrderDetail>()
    vi.mocked(api.fetchTubeOrder).mockReturnValueOnce(request.promise)
    const wrapper = await mountRecords()
    await openDispatch(wrapper)
    wrapper.unmount()
    request.resolve(batch()); await flushPromises()
    expect(api.fetchTubeOrder).toHaveBeenCalledTimes(1)
  })
})

async function clickRecordButton(wrapper: ReturnType<typeof mount>, label: string) {
  const button = wrapper.get('[role="dialog"]').findAll('button').find(item => item.text() === label)
  expect(button).toBeDefined(); await button!.trigger('click'); await flushPromises()
}
describe('实际收发记录调整与整次删除', () => {
  it.each(['170', '100'])('总单数量%s时，增加受累计上限限制，历史超发仍可减量', async planned => {
    const value = structuredClone(plan); value.lines[0]!.quantity = planned
    vi.mocked(api.fetchTubeOrder).mockImplementation(async id => id === plan.id ? { ...value, etag: 'fresh-v3' } : batch(id))
    const wrapper = await mountRecords(value); await openDispatch(wrapper); await clickRecordButton(wrapper, '调整记录')
    await wrapper.get('input[aria-label="批次甲横管调整数量"]').setValue('120')
    await clickRecordButton(wrapper, '保存调整')
    expect(wrapper.emitted('correct')).toBeUndefined(); expect(wrapper.text()).toContain('累计外发不能超过总单填写数量')
    const quantity = planned === '170' ? '110' : '90'
    await wrapper.get('input[aria-label="批次甲横管调整数量"]').setValue(quantity)
    await clickRecordButton(wrapper, '保存调整')
    expect(wrapper.emitted('correct')!.at(-1)![0]).toMatchObject({ operation: 'UPDATE', lines: [{ component_identity: 'component-1', quantity }] })
  })
  it('调整外发先重新取父版本和实际批次，仅数量日期可填，辅料和厂家只读', async () => {
    const wrapper = await mountRecords(); await openDispatch(wrapper)
    await clickRecordButton(wrapper, '调整记录')
    expect(vi.mocked(api.fetchTubeOrder).mock.calls).toEqual([['batch-1', true], ['plan-1', true], ['batch-1', true]])
    expect(wrapper.emitted('prepared')!.at(-1)![0]).toMatchObject({ etag: 'fresh-v3' })
    const quantity = wrapper.get('input[aria-label="批次甲横管调整数量"]')
    expect((quantity.element as HTMLInputElement).value).toBe('100')
    expect(wrapper.find('textarea').exists()).toBe(false)
    await quantity.setValue('120')
    expect(wrapper.find('.el-select').exists()).toBe(false)
    expect(wrapper.get('.dispatch-record-materials').find('input').exists()).toBe(false)
    expect(wrapper.findAll('th').some(cell => /单价|金额/.test(cell.text()))).toBe(false)
    await clickRecordButton(wrapper, '保存调整')
    expect(wrapper.emitted('correct')!.at(-1)).toEqual([{ record_kind: 'DISPATCH', record_id: 'batch-1', operation: 'UPDATE', business_date: '2026-11-01', lines: [{ component_identity: 'component-1', quantity: '120' }] }, 'fresh-v3'])
  })
  it('入库调整保留本次库区且不提交备注，不关联外发批次', async () => {
    const wrapper = await mountRecords(); await openReceipt(wrapper)
    await clickRecordButton(wrapper, '调整记录')
    expect(vi.mocked(api.fetchTubeOrder).mock.calls).toEqual([['plan-1', true]])
    expect(wrapper.find('textarea').exists()).toBe(false)
    expect(wrapper.get('.receipt-record-lines').text()).toContain('本次入库一区')
    expect(wrapper.find('.el-select').exists()).toBe(false)
    await wrapper.get('input[aria-label="总单横管调整数量"]').setValue('80')
    await clickRecordButton(wrapper, '保存调整')
    expect(wrapper.emitted('correct')!.at(-1)).toEqual([{ record_kind: 'RECEIPT', record_id: 'receipt-1', operation: 'UPDATE', business_date: '2026-11-02', lines: [{ component_identity: 'component-1', quantity: '80' }] }, 'fresh-v3'])
  })
  it.each(['0', '-1', '2.5', ''])('数量%s不能提交，也不出现单行删除入口', async quantity => {
    const wrapper = await mountRecords(); await openReceipt(wrapper); await clickRecordButton(wrapper, '调整记录')
    await wrapper.get('input[aria-label="总单横管调整数量"]').setValue(quantity)
    await clickRecordButton(wrapper, '保存调整')
    expect(wrapper.emitted('correct')).toBeUndefined(); expect(wrapper.text()).toContain('正整数')
    expect(wrapper.get('.receipt-record-lines').findAll('button')).toHaveLength(0)
  })
  it('原管按保存的每根可切数校验，不能悄悄改成零散根', async () => {
    const wrapper = await mountRecords(); await openDispatch(wrapper); await clickRecordButton(wrapper, '调整记录')
    await wrapper.get('input[aria-label="批次甲横管调整数量"]').setValue('115')
    await clickRecordButton(wrapper, '保存调整')
    expect(wrapper.emitted('correct')).toBeUndefined(); expect(wrapper.text()).toContain('整根数量')
  })
  it.each(['dispatch', 'receipt'] as const)('%s删除确认显示整次单号和数量，不要求新增原因或发送明细', async kind => {
    const wrapper = await mountRecords()
    if (kind === 'dispatch') await openDispatch(wrapper); else await openReceipt(wrapper)
    await clickRecordButton(wrapper, '删除整次记录')
    expect(wrapper.get('[role="dialog"]').text()).toContain(kind === 'dispatch' ? 'WF-BATCH-001（100 支）' : 'RK-001（90 支）')
    expect(wrapper.get('[role="dialog"]').find('input,textarea,select').exists()).toBe(false)
    await clickRecordButton(wrapper, '确认删除整次记录')
    expect(wrapper.emitted('correct')!.at(-1)).toEqual([{ record_kind: kind === 'dispatch' ? 'DISPATCH' : 'RECEIPT', record_id: kind === 'dispatch' ? 'batch-1' : 'receipt-1', operation: 'DELETE' }, 'fresh-v3'])
  })
  it('保存busy及pending不关窗或丢草稿，关闭和重复提交被禁用，未知结果保留核对入口', async () => {
    const wrapper = await mountRecords(); await openReceipt(wrapper); await clickRecordButton(wrapper, '调整记录')
    await wrapper.get('input[aria-label="总单横管调整数量"]').setValue('75')
    await wrapper.setProps({ busy: true, pending: true })
    await closeDialog(wrapper)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    expect(wrapper.get('input[aria-label="总单横管调整数量"]').attributes('disabled')).toBeDefined()
    expect((wrapper.get('input[aria-label="总单横管调整数量"]').element as HTMLInputElement).value).toBe('75')
    await wrapper.setProps({ busy: false, message: '结果未知，已保留请求编号' })
    await clickRecordButton(wrapper, '核对本次提交'); await clickRecordButton(wrapper, '按原请求重试')
    expect(wrapper.emitted('check')).toHaveLength(1); expect(wrapper.emitted('retry')).toHaveLength(1)
  })
  it('明确失败后重新核对保留已填日期数量，需父确认新版本才可保存', async () => {
    const wrapper = await mountRecords(); await openReceipt(wrapper); await clickRecordButton(wrapper, '调整记录')
    await wrapper.get('input[aria-label="总单横管调整数量"]').setValue('75')
    await wrapper.setProps({ refreshRequired: true, message: '库存不足' })
    await clickRecordButton(wrapper, '保存调整'); expect(wrapper.emitted('correct')).toBeUndefined()
    await clickRecordButton(wrapper, '重新核对')
    expect((wrapper.get('input[aria-label="总单横管调整数量"]').element as HTMLInputElement).value).toBe('75')
    await wrapper.setProps({ refreshRequired: false, message: '' }); await clickRecordButton(wrapper, '保存调整')
    expect(wrapper.emitted('correct')).toHaveLength(1)
  })
  it('入库调整不依赖原备注，提交只带日期和数量', async () => {
    vi.mocked(api.fetchTubeOrder).mockResolvedValue(structuredClone(plan))
    const wrapper = await mountRecords(); await openReceipt(wrapper); await clickRecordButton(wrapper, '调整记录')
    expect(wrapper.find('textarea').exists()).toBe(false)
    await clickRecordButton(wrapper, '保存调整')
    expect(wrapper.emitted('correct')).toHaveLength(1)
    expect(wrapper.emitted('correct')![0]![0]).not.toHaveProperty('remark')
  })
  it.each(['permission', 'office', 'cancelled', 'legacy-api'] as const)('%s页面仍能看明细但无更正入口', async reason => {
    const value = structuredClone(plan)
    if (reason === 'permission') value.permissions.can_receive = false
    if (reason === 'cancelled') value.status = 'CANCELLED'
    if (reason === 'legacy-api') { delete value.permissions.can_correct_dispatch; delete value.permissions.can_correct_receive }
    const wrapper = await mountRecords(value, reason !== 'office'); await openReceipt(wrapper)
    expect(wrapper.find('.receipt-record-lines').exists()).toBe(true)
    expect(wrapper.get('[role="dialog"]').text()).not.toContain('调整记录')
  })
  it('更正准备GET在途关闭后不回填旧草稿或激活旧编辑', async () => {
    const request = deferred<TubeOrderDetail>()
    const wrapper = await mountRecords(); await openReceipt(wrapper)
    vi.mocked(api.fetchTubeOrder).mockReturnValueOnce(request.promise)
    await clickRecordButton(wrapper, '调整记录'); await closeDialog(wrapper)
    request.resolve({ ...structuredClone(plan), receipt_records: receiptRecords.map(record => ({ ...record, remark: '' })) }); await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false); expect(wrapper.emitted('prepared')).toBeUndefined()
  })
})

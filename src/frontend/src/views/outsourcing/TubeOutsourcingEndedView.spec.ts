import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { AxiosError } from 'axios'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as orderApi from '@/api/tubeOutsourcing'
import * as receiptApi from '@/api/tubeReceipts'
import type { TubeDetailLine, TubeOrderDetail, TubeSourceKind } from '@/types/tubeOutsourcing'
import type { TubeReceipt, TubeReceiptPreview } from '@/types/tubeReceipts'
import TubeOutsourcingDetailView from './TubeOutsourcingDetailView.vue'

const routing = vi.hoisted(() => ({ push: vi.fn() }))
const permission = vi.hoisted(() => ({ canReceive: true }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { id: 'order-1' }, query: {} }), useRouter: () => routing }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 7, is_superuser: false }, hasPermission: (name: string) => name === 'outsourcing.confirm_return_outsourcingorder' ? permission.canReceive : true }) }))
vi.mock('@/api/tubeOutsourcing', () => ({ fetchTubeOrder: vi.fn(), createTubeOrder: vi.fn(), dispatchTubeOrder: vi.fn(), cancelTubeOrder: vi.fn(), findTubeAction: vi.fn(), fetchTubeSource: vi.fn(), fetchTubeOptions: vi.fn() }))
vi.mock('@/api/tubeReceipts', () => ({ fetchTubeReceiptPreview: vi.fn(), fetchTubeReceipt: vi.fn(), fetchTubeReceiptCandidates: vi.fn(), confirmTubeReceipt: vi.fn(), findTubeReceipt: vi.fn() }))
vi.mock('element-plus', async original => ({ ...await original<typeof import('element-plus')>(), ElMessage: { closeAll: vi.fn(), warning: vi.fn(), success: vi.fn() } }))

const labels: Record<TubeSourceKind, string> = { RAW_PIPE: '原材料', PUBLIC_SEMI: '未喷塑半成品', METAL: '未入库半成品' }
const order: TubeOrderDetail = {
  id: 'order-1', order_number: 'WF-ended-real', status: 'COMPLETED', version: 3, etag: '"order-1:v3"', created: false,
  client_request_id: 'creation-id', source_kind: 'RAW_PIPE', source_label: labels.RAW_PIPE, schedule_product_id: 'plan-1', product_line_id: 'product-1',
  planned_dispatch_date: '2026-09-30', expected_return_date: '2026-10-15', total_quantity: '35', total_stock_quantity: '4', total_meters: '23.74',
  task_order_number: 'DD-ended-real', task_number: 'SC-ended-real', schedule_number: 'PC-ended-real', product_number: 'CP-real', item_number: 'HT-real', product_name: '测试产品', quantity: '1000', unit: '把', color: '黑色',
  zone_id: 'raw-zone', zone_name: '原料区', warehouse_name: '原料仓', craft_name: '喷塑', remark: '发出时原单备注', created_at: '2026-09-30T08:00:00+08:00', created_by_name: '建单员工',
  actual_dispatch_date: '2026-09-30', dispatched_at: '2026-09-30T09:00:00+08:00', dispatched_by_name: '发出员工', cancelled_at: null, cancelled_by_name: '', cancel_remark: '',
  permissions: { can_dispatch: false, can_cancel: false },
  lines: [],
}
const firstLine: TubeDetailLine = {
  id: 'line-1', component_identity: 'component-1', part_name: '同名腿管', factory_id: 'factory-1', factory_name: '加工厂甲', quantity: '20', stock_quantity: '2', meters: '13.10',
  material: 'Q195', specification: 'Φ22', thickness: '0.8', cutting_length_mm: '650', raw_color: '本色', spray_color: '黑色', pieces_per_bar: '10', raw_bar_length_m: '6.55', current_reported_minimum: null, operations: [], basis_blockers: [],
}
order.lines = [
  firstLine,
  { ...firstLine, id: 'line-2', component_identity: 'component-2', factory_id: 'factory-2', factory_name: '加工厂乙', quantity: '10', stock_quantity: '1', meters: '6.55', specification: 'Φ18' },
  { ...firstLine, id: 'line-3', component_identity: 'component-3', part_name: '支撑管', quantity: '5', stock_quantity: '1', meters: '4.09', pieces_per_bar: '5', raw_bar_length_m: '4.09' },
]

function makePreview(source: TubeSourceKind = 'RAW_PIPE', quantities = ['18', '10', '0']): TubeReceiptPreview {
  const original = structuredClone(order)
  original.source_kind = source; original.source_label = labels[source]
  if (source !== 'RAW_PIPE') {
    original.total_stock_quantity = source === 'PUBLIC_SEMI' ? original.total_quantity : null
    original.total_meters = null
    original.lines.forEach(line => { line.stock_quantity = source === 'PUBLIC_SEMI' ? line.quantity : null; line.meters = null; line.pieces_per_bar = null; line.raw_bar_length_m = null })
  }
  const totalReceived = quantities.reduce((sum, value) => sum + Number(value), 0)
  const receipt: TubeReceipt = {
    id: 'receipt-1', receipt_number: 'PSRK-ended-real', order_id: original.id, order_number: original.order_number, status: 'COMPLETED', source_kind: source, source_label: labels[source],
    client_request_id: 'receipt-request', receipt_date: '2026-09-30', warehouse_id: totalReceived ? 'warehouse-1' : null, warehouse_name: totalReceived ? '半成品管材仓' : '',
    confirmed_at: '2026-09-30T10:00:00+08:00', actor_name: '入库员工', remark: '最终入库备注', total_dispatched_quantity: original.total_quantity, total_received_quantity: String(totalReceived),
    total_shortage_quantity: String(Number(original.total_quantity) - totalReceived), etag: original.etag, created: false,
    lines: original.lines.map((line, index) => {
      const received = quantities[index]!
      return { id: `receipt-${line.id}`, order_line_id: line.id, component_identity: line.component_identity, part_name: line.part_name,
        material: line.material, specification: line.specification, thickness: line.thickness, cutting_length_mm: line.cutting_length_mm, raw_color: line.raw_color, spray_color: line.spray_color,
        factory_id: line.factory_id, factory_name: line.factory_name, dispatched_quantity: line.quantity, received_quantity: received, shortage_quantity: String(Number(line.quantity) - Number(received)),
        shortage_reason: Number(received) < Number(line.quantity) ? `${line.id}未交回` : '', zone_id: Number(received) ? `zone-${index + 1}` : null,
        zone_name: Number(received) ? `成品${index + 1}区` : '', stock_movement_id: Number(received) ? `movement-${line.id}` : null }
    }),
  }
  // 同名部位且凭证顺序与原单不同，验证必须按稳定编号对应。
  receipt.lines = [receipt.lines[2]!, receipt.lines[0]!, receipt.lines[1]!]
  return { order: original, etag: original.etag, can_receive: false, blockers: [], actor_name: '当前用户', today: '2026-09-30', warehouses: [], zones: [], receipt }
}

const httpError = (status: number) => Object.assign(new AxiosError('接口错误'), { response: { status, data: { error: { message: `状态 ${status}` } } } })
interface ViewModel { detail: TubeOrderDetail | null; receipt: TubeReceipt | null; dialog: string; loading: boolean; canDispatch: boolean; canCancel: boolean; loadDetail: () => Promise<void> }
const wrappers: VueWrapper[] = []
async function mountPage() {
  const wrapper = mount(TubeOutsourcingDetailView, { global: { plugins: [ElementPlus], stubs: {
    AppWindowDialog: { props: ['modelValue', 'title', 'width'], template: '<div v-if="modelValue" :aria-label="title" :data-width="width"><slot /><slot name="footer" /></div>' },
  } } })
  wrappers.push(wrapper); await flushPromises()
  return { wrapper, vm: wrapper.vm as unknown as ViewModel }
}
function button(wrapper: VueWrapper, label: string) {
  const found = wrapper.findAll('button').find(item => item.text() === label)
  expect(found, `缺少按钮：${label}`).toBeDefined()
  return found!
}
function records(wrapper: VueWrapper, selector = '.d4-ended-lines') {
  const headers = wrapper.findAll(`${selector} th`).map(item => item.text())
  return wrapper.findAll(`${selector} tbody tr`).map(row => Object.fromEntries(row.findAll('td').map((cell, index) => [headers[index]!, cell.text()])))
}
function assertNoWriteRequests() {
  expect(orderApi.createTubeOrder).not.toHaveBeenCalled(); expect(orderApi.dispatchTubeOrder).not.toHaveBeenCalled(); expect(orderApi.cancelTubeOrder).not.toHaveBeenCalled()
  expect(receiptApi.confirmTubeReceipt).not.toHaveBeenCalled()
}
function assertReceiptUnavailable(wrapper: VueWrapper) {
  expect(button(wrapper, '查看入库凭证').attributes('disabled')).toBeDefined()
  expect(wrapper.find('.d4-ended-receipt').exists()).toBe(false)
}
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); permission.canReceive = true
  vi.mocked(receiptApi.fetchTubeReceiptPreview).mockResolvedValue(makePreview())
  vi.mocked(orderApi.fetchTubeOrder).mockResolvedValue(structuredClone(order))
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('D4已结束原单详情与只读入库凭证', () => {
  it.each(['RAW_PIPE', 'PUBLIC_SEMI', 'METAL'] as const)('%s按批准列显示全部结果，凭证使用同一列且仅能关闭', async source => {
    vi.mocked(receiptApi.fetchTubeReceiptPreview).mockResolvedValue(makePreview(source))
    const { wrapper, vm } = await mountPage()
    const expected = ['部位', '材质', '规格', '厚度 mm', '切割长度 mm', '原料颜色', '喷塑颜色', '加工厂',
      ...(source === 'RAW_PIPE' ? ['切割支数 支/根', '原材料长度 米/根'] : []), '实发（支）', ...(source === 'RAW_PIPE' ? ['发出扣根', '发出扣米'] : []), '实收（支）', '差额（支）', '差额原因', '入库库区']
    expect(wrapper.findAll('.d4-ended-lines th').map(item => item.text())).toEqual(expected)
    expect(wrapper.text()).toContain(labels[source]); expect(wrapper.text()).toContain('当前订单量')
    expect(wrapper.findAll('.d4-ended-context .info-cell')).toHaveLength(12)
    expect(wrapper.findAll('.d4-ended-meta .info-cell')).toHaveLength(8)
    expect(wrapper.find('.d4-ended-lines input').exists()).toBe(false)
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
    expect(vm.canDispatch).toBe(false); expect(vm.canCancel).toBe(false)
    expect(wrapper.findAll('button').some(item => ['喷塑入库', '确认实际发出', '取消外发单', '退回', '重新加工', '结清'].includes(item.text()))).toBe(false)
    await button(wrapper, '查看入库凭证').trigger('click')
    expect(wrapper.get('[aria-label="喷塑入库凭证 · 只读"]').attributes('data-width')).toBe('1640')
    expect(wrapper.findAll('.d4-ended-receipt-lines th').map(item => item.text())).toEqual(expected)
    expect(records(wrapper, '.d4-ended-receipt-lines')).toEqual(records(wrapper))
    expect(wrapper.find('.d4-ended-receipt input').exists()).toBe(false)
    expect(wrapper.find('.d4-ended-receipt select').exists()).toBe(false)
    expect(wrapper.get('[aria-label="喷塑入库凭证 · 只读"]').findAll('button').map(item => item.text())).toEqual(['关闭'])
    expect(wrapper.text()).toContain('PSRK-ended-real'); expect(wrapper.text()).toContain('发出时原单备注'); expect(wrapper.text()).toContain('最终入库备注')
    await button(wrapper, '关闭').trigger('click')
    expect(wrapper.find('.d4-ended-receipt').exists()).toBe(false)
    expect(receiptApi.fetchTubeReceiptPreview).toHaveBeenCalledWith('order-1')
    expect(orderApi.fetchTubeOrder).not.toHaveBeenCalled(); expect(receiptApi.fetchTubeReceipt).not.toHaveBeenCalled()
    expect(orderApi.fetchTubeSource).not.toHaveBeenCalled(); expect(orderApi.fetchTubeOptions).not.toHaveBeenCalled()
    assertNoWriteRequests()
  })

  it('同名部位和乱序凭证按原单明细编号匹配，零行保留且显示未入库', async () => {
    const { wrapper } = await mountPage()
    const displayed = records(wrapper)
    expect(displayed).toHaveLength(3)
    expect(displayed[0]).toEqual(expect.objectContaining({ 部位: '同名腿管', 规格: 'Φ22', '实发（支）': '20', '实收（支）': '18', '差额（支）': '2', 差额原因: 'line-1未交回', 入库库区: '成品1区' }))
    expect(displayed[1]).toEqual(expect.objectContaining({ 部位: '同名腿管', 规格: 'Φ18', '实发（支）': '10', '实收（支）': '10', '差额（支）': '0', 入库库区: '成品2区' }))
    expect(displayed[2]).toEqual(expect.objectContaining({ 部位: '支撑管', '实发（支）': '5', '实收（支）': '0', '差额（支）': '5', 差额原因: 'line-3未交回', 入库库区: '未入库' }))
    const footer = wrapper.get('.d4-ended-footer').text()
    expect(footer).toContain('实发 35'); expect(footer).toContain('实收 28'); expect(footer).toContain('差额 7')
  })

  it('原材料扣根扣米沿用发出历史，缺失值显示破折号且不按换算值补算', async () => {
    const current = makePreview(); const line = current.order.lines[0]!
    line.pieces_per_bar = '5'; line.raw_bar_length_m = '9.90'
    current.order.lines[1]!.stock_quantity = null; current.order.lines[1]!.meters = null
    vi.mocked(receiptApi.fetchTubeReceiptPreview).mockResolvedValue(current)
    const { wrapper } = await mountPage(); const displayed = records(wrapper)
    expect(displayed[0]).toEqual(expect.objectContaining({ 发出扣根: '2', 发出扣米: '13.10' }))
    expect(displayed[1]).toEqual(expect.objectContaining({ 发出扣根: '—', 发出扣米: '—' }))
    expect(orderApi.fetchTubeOrder).not.toHaveBeenCalled(); expect(orderApi.fetchTubeSource).not.toHaveBeenCalled()
  })

  it('凭证冻结的材料属性和加工厂覆盖已变化的原单关联资料', async () => {
    const current = makePreview('METAL')
    const changed = current.order.lines[0]!
    changed.part_name = '当前更名'; changed.material = '当前材质'; changed.specification = '当前规格'; changed.thickness = '9.9'; changed.cutting_length_mm = '9999'
    changed.raw_color = '当前原料色'; changed.spray_color = '当前喷塑色'; changed.factory_name = '当前加工厂'
    changed.current_reported_minimum = '999'; changed.operations = [{ work_item_id: 'work-now', operation_id: 'bend', name: '当前动态工序', scheme_id: 'scheme-now', scheme_revision: 9, quantity: '999' }]
    vi.mocked(receiptApi.fetchTubeReceiptPreview).mockResolvedValue(current)
    const { wrapper } = await mountPage(); const frozen = records(wrapper)[0]!
    expect(frozen).toEqual(expect.objectContaining({ 部位: '同名腿管', 材质: 'Q195', 规格: 'Φ22', '厚度 mm': '0.8', '切割长度 mm': '650', 原料颜色: '本色', 喷塑颜色: '黑色', 加工厂: '加工厂甲' }))
    expect(wrapper.find('.d4-ended-lines').text()).not.toContain('当前')
    expect(wrapper.text()).not.toContain('当前动态工序'); expect(wrapper.text()).not.toContain('当前最低报工')
    await button(wrapper, '查看入库凭证').trigger('click')
    expect(records(wrapper, '.d4-ended-receipt-lines')[0]).toEqual(frozen)
    expect(orderApi.fetchTubeOrder).not.toHaveBeenCalled()
  })

  it.each(['RAW_PIPE', 'PUBLIC_SEMI', 'METAL'] as const)('%s整单零实收仍保留凭证与全部零行，没有库存存放位置', async source => {
    vi.mocked(receiptApi.fetchTubeReceiptPreview).mockResolvedValue(makePreview(source, ['0', '0', '0']))
    const { wrapper } = await mountPage()
    expect(records(wrapper)).toHaveLength(3)
    expect(records(wrapper).every(row => row['实收（支）'] === '0' && row.入库库区 === '未入库')).toBe(true)
    expect(wrapper.text()).toContain('未新增库存')
    expect(wrapper.get('.d4-ended-meta').text()).not.toContain('半成品管材仓')
    await button(wrapper, '查看入库凭证').trigger('click')
    expect(wrapper.get('.d4-ended-receipt').text()).toContain('无实收，无需仓库')
    expect(wrapper.get('.d4-ended-receipt').text()).not.toContain('成品1区')
    expect(records(wrapper, '.d4-ended-receipt-lines')).toHaveLength(3)
    assertNoWriteRequests()
  })

  it('整单全回差额为零，未添加少回处理或数量编辑入口', async () => {
    vi.mocked(receiptApi.fetchTubeReceiptPreview).mockResolvedValue(makePreview('PUBLIC_SEMI', ['20', '10', '5']))
    const { wrapper } = await mountPage()
    expect(records(wrapper).every(row => row['差额（支）'] === '0')).toBe(true)
    expect(wrapper.get('.d4-ended-footer').text()).toContain('差额 0')
    expect(wrapper.findAll('input')).toHaveLength(0)
    assertNoWriteRequests()
  })

  const invalidReceipts: Array<[string, (preview: TubeReceiptPreview) => void]> = [
    ['缺少最终凭证', current => { current.receipt = null }],
    ['凭证属于其他原单', current => { current.receipt!.order_id = 'other-order' }],
    ['凭证来源与原单不符', current => { current.receipt!.source_kind = 'METAL' }],
    ['凭证缺少原单部位', current => { current.receipt!.lines = current.receipt!.lines.filter(line => line.order_line_id !== 'line-2') }],
    ['凭证明细编号重复', current => { current.receipt!.lines.push(structuredClone(current.receipt!.lines[0]!)) }],
    ['原单明细编号重复', current => { current.order.lines[1]!.id = 'line-1' }],
    ['凭证带有外来明细', current => { current.receipt!.lines[0]!.order_line_id = 'unknown-line' }],
    ['凭证实发与原单数量不同', current => { current.receipt!.lines[1]!.dispatched_quantity = '21' }],
    ['凭证行差额不等于实发减实收', current => { current.receipt!.lines[1]!.shortage_quantity = '1' }],
    ['凭证汇总实收与行合计不符', current => { current.receipt!.total_received_quantity = '29' }],
    ['凭证冻结规格缺失', current => { current.receipt!.lines[1]!.specification = '' }],
  ]
  it.each(invalidReceipts)('%s时不能打开完整凭证，未知量不能当作零', async (_, change) => {
    const current = makePreview(); change(current)
    vi.mocked(receiptApi.fetchTubeReceiptPreview).mockResolvedValue(current)
    const { wrapper } = await mountPage()
    expect(button(wrapper, '查看入库凭证').attributes('disabled')).toBeDefined()
    await button(wrapper, '查看入库凭证').trigger('click')
    expect(wrapper.find('.d4-ended-receipt').exists()).toBe(false)
    if (!current.receipt || current.receipt.order_id !== current.order.id || current.receipt.source_kind !== current.order.source_kind) {
      expect(wrapper.get('.d4-ended-footer').text()).toContain('—')
    }
    expect(orderApi.fetchTubeOrder).not.toHaveBeenCalled()
    assertNoWriteRequests()
  })

  it.each([null, '错误结构'])('原单明细为%s时显示结构错误，不崩溃或开放凭证', async invalid => {
    const current = makePreview()
    const lines = current.order.lines as unknown[]
    lines[0] = invalid
    vi.mocked(receiptApi.fetchTubeReceiptPreview).mockResolvedValue(current)
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('原单历史明细结构不完整')
    expect(wrapper.find('.d4-ended-lines').exists()).toBe(false)
    expect(wrapper.findAll('.d4-ended-footer strong').map(item => item.text())).toEqual(['—', '—', '—'])
    assertReceiptUnavailable(wrapper)
    expect(orderApi.fetchTubeOrder).not.toHaveBeenCalled()
    assertNoWriteRequests()
  })

  it('不能唯一对应的部位数量显示破折号，真实零实收部位继续显示零', async () => {
    const current = makePreview()
    current.receipt!.lines.push(structuredClone(current.receipt!.lines.find(line => line.order_line_id === 'line-1')!))
    vi.mocked(receiptApi.fetchTubeReceiptPreview).mockResolvedValue(current)
    const { wrapper } = await mountPage(); const displayed = records(wrapper)
    expect(displayed).toHaveLength(3)
    expect(displayed[0]).toEqual(expect.objectContaining({ '实发（支）': '—', '实收（支）': '—', '差额（支）': '—', 入库库区: '—' }))
    expect(displayed[2]).toEqual(expect.objectContaining({ '实收（支）': '0', '差额（支）': '5', 入库库区: '未入库' }))
    expect(wrapper.findAll('.d4-ended-footer strong').map(item => item.text())).toEqual(['—', '—', '—'])
    assertReceiptUnavailable(wrapper)
    assertNoWriteRequests()
  })

  it('刷新立即隐藏旧单号、数量和凭证；失败后只通过重新加载恢复', async () => {
    const { wrapper, vm } = await mountPage()
    await button(wrapper, '查看入库凭证').trigger('click')
    let rejectRequest!: (reason: unknown) => void
    vi.mocked(receiptApi.fetchTubeReceiptPreview).mockReturnValueOnce(new Promise((_, reject) => { rejectRequest = reject }))
    const refresh = vm.loadDetail(); await nextTick()
    expect(vm.loading).toBe(true)
    expect(wrapper.text()).not.toContain('WF-ended-real'); expect(wrapper.text()).not.toContain('PSRK-ended-real')
    expect(wrapper.find('.d4-ended-lines').exists()).toBe(false); expect(wrapper.find('.d4-ended-receipt').exists()).toBe(false)
    expect(wrapper.findAll('.footer-bar strong').map(item => item.text())).toEqual(['—', '—', '—'])
    rejectRequest(httpError(500)); await refresh; await flushPromises()
    expect(wrapper.text()).not.toContain('WF-ended-real'); expect(wrapper.text()).not.toContain('PSRK-ended-real')
    assertReceiptUnavailable(wrapper)
    vi.mocked(receiptApi.fetchTubeReceiptPreview).mockResolvedValueOnce(makePreview())
    await button(wrapper, '重新加载').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('WF-ended-real'); expect(records(wrapper)).toHaveLength(3)
    expect(button(wrapper, '查看入库凭证').attributes('disabled')).toBeUndefined()
    expect(orderApi.fetchTubeOrder).not.toHaveBeenCalled(); assertNoWriteRequests()
  })

  it('较旧的预览响应不能覆盖后来刷新取得的凭证', async () => {
    const { vm } = await mountPage()
    let finishOld!: (value: TubeReceiptPreview) => void
    const latest = makePreview(); latest.receipt!.receipt_number = 'PSRK-latest'
    vi.mocked(receiptApi.fetchTubeReceiptPreview).mockReturnValueOnce(new Promise(resolve => { finishOld = resolve })).mockResolvedValueOnce(latest)
    const oldRequest = vm.loadDetail(); await vm.loadDetail()
    finishOld(makePreview()); await oldRequest
    expect(vm.receipt?.receipt_number).toBe('PSRK-latest')
  })

  it.each([404, 500])('只读预览%s不回退普通详情，也不显示固定单号或已结束状态', async status => {
    vi.mocked(receiptApi.fetchTubeReceiptPreview).mockRejectedValue(httpError(status))
    const { wrapper } = await mountPage()
    expect(orderApi.fetchTubeOrder).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('WF-ended-real'); expect(wrapper.text()).not.toContain('PSRK-ended-real')
    expect(wrapper.find('.title-row').text()).not.toContain('已结束')
    expect(wrapper.find('.d4-ended-lines').exists()).toBe(false)
    assertReceiptUnavailable(wrapper)
    assertNoWriteRequests()
  })

  it('预览403回退原详情发现已结束，再次凭证授权仍403时隐藏全部原单内容', async () => {
    vi.mocked(receiptApi.fetchTubeReceiptPreview).mockRejectedValue(httpError(403))
    const { wrapper } = await mountPage()
    expect(orderApi.fetchTubeOrder).toHaveBeenCalledWith('order-1')
    expect(receiptApi.fetchTubeReceiptPreview).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).not.toContain('WF-ended-real'); expect(wrapper.text()).not.toContain('同名腿管')
    expect(wrapper.find('.title-row').text()).not.toContain('已结束')
    assertReceiptUnavailable(wrapper)
    expect(wrapper.find('.d4-ended-receipt').exists()).toBe(false)
    assertNoWriteRequests()
  })

  it('预览403仍能沿原详情查看加工中，回货按钮沿既有权限禁用', async () => {
    permission.canReceive = false
    vi.mocked(receiptApi.fetchTubeReceiptPreview).mockRejectedValue(httpError(403))
    vi.mocked(orderApi.fetchTubeOrder).mockResolvedValue({ ...structuredClone(order), status: 'PROCESSING' })
    const { wrapper } = await mountPage()
    expect(orderApi.fetchTubeOrder).toHaveBeenCalledWith('order-1')
    expect(receiptApi.fetchTubeReceiptPreview).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('WF-ended-real'); expect(wrapper.text()).toContain('加工中')
    expect(button(wrapper, '喷塑入库').attributes('disabled')).toBeDefined()
    assertNoWriteRequests()
  })

  it('预览与原详情均403时不显示原单内容，也没有可办理入口', async () => {
    vi.mocked(receiptApi.fetchTubeReceiptPreview).mockRejectedValue(httpError(403))
    vi.mocked(orderApi.fetchTubeOrder).mockRejectedValue(httpError(403))
    const { wrapper } = await mountPage()
    expect(wrapper.text()).not.toContain('WF-ended-real'); expect(wrapper.text()).not.toContain('同名腿管')
    expect(wrapper.findAll('button').some(item => ['喷塑入库', '确认实际发出', '取消外发单'].includes(item.text()))).toBe(false)
    assertReceiptUnavailable(wrapper)
    assertNoWriteRequests()
  })

  it('非终态预览仍读取原有动态详情，保留加工中回货入口', async () => {
    const processing = makePreview('METAL'); processing.order.status = 'PROCESSING'; processing.receipt = null
    vi.mocked(receiptApi.fetchTubeReceiptPreview).mockResolvedValue(processing)
    vi.mocked(orderApi.fetchTubeOrder).mockResolvedValue(processing.order)
    const { wrapper } = await mountPage()
    expect(orderApi.fetchTubeOrder).toHaveBeenCalledWith('order-1')
    expect(wrapper.find('.d4-ended-lines').exists()).toBe(false)
    await button(wrapper, '喷塑入库').trigger('click')
    expect(routing.push).toHaveBeenCalledWith({ name: 'workshop-outsourcing-tube-return', params: { id: 'order-1' } })
    assertNoWriteRequests()
  })

  it('缺少回货办理权限仍能在既有查看权限下读取已结束凭证', async () => {
    permission.canReceive = false
    const { wrapper } = await mountPage()
    expect(button(wrapper, '查看入库凭证').attributes('disabled')).toBeUndefined()
    await button(wrapper, '查看入库凭证').trigger('click')
    expect(wrapper.find('.d4-ended-receipt').exists()).toBe(true)
    expect(orderApi.fetchTubeOrder).not.toHaveBeenCalled(); assertNoWriteRequests()
  })
})

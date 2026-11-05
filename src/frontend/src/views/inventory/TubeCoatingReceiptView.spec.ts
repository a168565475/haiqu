import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { AxiosError, CanceledError } from 'axios'
import { useAuthStore } from '@/stores/auth'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/tubeReceipts'
import type { TubeOrderDetail } from '@/types/tubeOutsourcing'
import type { TubeReceipt, TubeReceiptInput, TubeReceiptPending, TubeReceiptPreview } from '@/types/tubeReceipts'
import TubeCoatingReceiptView from './TubeCoatingReceiptView.vue'

const routing = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), route: { name: 'warehouse-outsourcing-tube-return', params: { id: 'order-1' }, query: {} as Record<string, string>, meta: { outsourcingWorkspace: 'warehouse' } } }))
const permission = vi.hoisted(() => ({ canReceive: true }))
vi.mock('vue-router', () => ({ useRoute: () => routing.route, useRouter: () => routing }))
vi.mock('@/stores/auth', async () => {
  const { reactive } = await import('vue')
  const state = reactive({ user: { id: 7, is_superuser: false }, initialized: true, identityReady: true, identityGeneration: 1, identityRequestGeneration: 1, hasPermission: (name: string) => name === 'outsourcing.confirm_return_outsourcingorder' ? permission.canReceive : true })
  return { useAuthStore: () => state }
})
const auth = useAuthStore()
function resetIdentity() { Object.assign(auth, { user: { id: 7, is_superuser: false }, initialized: true, identityReady: true, identityGeneration: 1, identityRequestGeneration: 1 }) }
vi.mock('@/api/tubeReceipts', () => ({ fetchTubeReceiptPreview: vi.fn(), fetchTubeReceiptCandidates: vi.fn(), confirmTubeReceipt: vi.fn(), findTubeReceipt: vi.fn(), fetchTubeReceipt: vi.fn() }))
vi.mock('element-plus', async original => ({ ...await original<typeof import('element-plus')>(), ElMessage: { closeAll: vi.fn(), warning: vi.fn(), success: vi.fn() } }))

const key = 'tube-coating-receipt:v1:7:order-1'
const order: TubeOrderDetail = {
  id: 'order-1', order_number: 'WF-real', status: 'PROCESSING', version: 2, etag: '"order-1:v2"', created: false,
  client_request_id: 'creation-id', source_kind: 'RAW_PIPE', source_label: '原材料', schedule_product_id: 'plan-1', product_line_id: 'product-1',
  planned_dispatch_date: '2026-09-30', expected_return_date: '2026-10-15', total_quantity: '20', total_area_sqm: '2.5000', planned_amount: '5.00', total_stock_quantity: '2', total_meters: '13.10',
  task_order_number: 'DD-real', task_number: 'SC-real', schedule_number: 'PC-real', product_number: 'CP-real', item_number: 'HT-real', product_name: '真实测试产品', quantity: '1000', unit: '把', color: '黑色',
  zone_id: 'raw-zone', zone_name: '原料区', warehouse_name: '原料仓', craft_name: '喷塑', remark: '', created_at: '2026-09-30T08:00:00+08:00', created_by_name: '建单员工',
  actual_dispatch_date: '2026-09-30', dispatched_at: '2026-09-30T09:00:00+08:00', dispatched_by_name: '发出员工', cancelled_at: null, cancelled_by_name: '', cancel_remark: '',
  permissions: { can_dispatch: false, can_cancel: false },
  lines: [{ id: 'line-1', component_identity: 'component-1', part_name: '前腿管', factory_id: 'factory-1', factory_name: '加工厂甲', quantity: '20', price_unit: 'PIECE', unit_area_sqm: '0.1250', line_area_sqm: '2.5000', unit_price: '0.25', planned_amount: '5.00', stock_quantity: '2', meters: '13.10',
    material: 'Q195', specification: 'Φ22', thickness: '0.8', cutting_length_mm: '650', raw_color: '本色', spray_color: '黑色', pieces_per_bar: '10', raw_bar_length_m: '6.55', current_reported_minimum: null, operations: [], basis_blockers: [] }],
}
const base: TubeReceiptPreview = { order, etag: order.etag, can_receive: true, blockers: [], actor_name: '真实收货经办人', today: '2026-09-30',
  warehouses: [{ id: 'warehouse-1', name: '半成品管材仓' }, { id: 'warehouse-2', name: '半成品暂存仓' }],
  zones: [{ id: 'zone-1', warehouse_id: 'warehouse-1', warehouse: '半成品管材仓', name: 'A区' }, { id: 'zone-2', warehouse_id: 'warehouse-2', warehouse: '半成品暂存仓', name: 'B区' }], receipt: null }
const httpError = (status: number) => Object.assign(new AxiosError('接口错误'), { response: { status, data: { error: { message: `状态 ${status}` } } } })
function makeReceipt(payload: TubeReceiptInput): TubeReceipt {
  const sent = order.lines.reduce((sum, line) => sum + Number(line.quantity), 0), received = payload.lines.reduce((sum, line) => sum + Number(line.received_quantity), 0)
  return { id: 'receipt-1', receipt_number: 'PSRK-real', order_id: 'order-1', order_number: order.order_number, status: 'COMPLETED', source_kind: order.source_kind, source_label: order.source_label,
    client_request_id: payload.client_request_id, receipt_date: payload.receipt_date, warehouse_id: payload.warehouse_id, warehouse_name: payload.warehouse_id ? '半成品管材仓' : '', confirmed_at: '2026-09-30T10:00:00+08:00',
    actor_name: '真实收货经办人', remark: payload.remark, total_dispatched_quantity: String(sent), total_received_quantity: String(received), total_shortage_quantity: String(sent - received), etag: '"order-1:v3"', created: true,
    lines: payload.lines.map(line => { const original = order.lines.find(item => item.id === line.order_line_id) || order.lines[0]!; return { ...original,
      id: `receipt-${line.order_line_id}`, order_line_id: line.order_line_id, dispatched_quantity: original.quantity, received_quantity: line.received_quantity,
      shortage_quantity: String(Number(original.quantity) - Number(line.received_quantity)), shortage_reason: line.shortage_reason,
      zone_id: line.zone_id, zone_name: line.zone_id ? 'A区' : '', stock_movement_id: Number(line.received_quantity) > 0 ? `movement-${line.order_line_id}` : null } }) }
}
function savedRequest(): TubeReceiptPending { return { order_id: 'order-1', etag: order.etag, payload: { client_request_id: 'existing-uuid', receipt_date: base.today, warehouse_id: null, remark: '', lines: [{ order_line_id: 'line-1', received_quantity: '0', shortage_reason: '未收到', zone_id: null }] } } }
interface Row { order_line_id: string; dispatched_quantity: string; received: string; reason: string; zone: string; zone_name: string }
interface ViewModel {
  preview: TubeReceiptPreview | null; rows: Row[]; pending: TubeReceiptPending | null; storageError: boolean; readError: string; canEdit: boolean; isEnded: boolean
  receiptDate: string; warehouse: string; remark: string; dialog: string
  finishReceipt: () => Promise<void>; openConfirm: () => void; recoverPending: (retry?: boolean) => Promise<void>; showReceipt: () => Promise<void>
  requestWarehouseChange: (value: string) => void; confirmWarehouseChange: () => void
  returnToSource: () => void
}
const wrappers: ReturnType<typeof mount>[] = []
async function mountPage(props: { orderId?: string; embedded?: boolean } = {}) {
  const wrapper = mount(TubeCoatingReceiptView, { props, global: { plugins: [ElementPlus], stubs: { AppWindowDialog: { props: ['modelValue', 'title'], template: '<div v-if="modelValue" :aria-label="title"><slot /><slot name="footer" /></div>' } } } })
  wrappers.push(wrapper); await flushPromises()
  return { wrapper, vm: wrapper.vm as unknown as ViewModel }
}
function receive(vm: ViewModel, quantity = '20') { vm.rows[0]!.received = quantity; vm.rows[0]!.reason = quantity === '20' ? '' : '实物少回'; vm.warehouse = 'warehouse-1'; vm.rows[0]!.zone = 'zone-1' }
beforeEach(() => {
  routing.route.meta.outsourcingWorkspace = 'warehouse'
  vi.resetAllMocks(); localStorage.clear(); resetIdentity(); permission.canReceive = true; routing.route.name = 'warehouse-outsourcing-tube-return'; routing.route.params.id = 'order-1'; routing.route.query = {}
  vi.mocked(api.fetchTubeReceiptPreview).mockResolvedValue(structuredClone(base))
  vi.mocked(api.confirmTubeReceipt).mockImplementation(async (_, payload) => makeReceipt(payload))
  vi.mocked(api.findTubeReceipt).mockRejectedValue(httpError(404))
  vi.mocked(api.fetchTubeReceiptCandidates).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
})

it('旧车间表单上下文不能确认入库或重放旧请求', async () => {
  routing.route.meta.outsourcingWorkspace = 'workshop'
  routing.route.name = 'workshop-outsourcing-tube-return'
  const { vm } = await mountPage()
  receive(vm)
  vm.openConfirm(); await vm.finishReceipt()
  expect(vm.canEdit).toBe(false)
  expect(api.confirmTubeReceipt).not.toHaveBeenCalled()
  vm.pending = savedRequest()
  await vm.recoverPending(true)
  expect(api.findTubeReceipt).toHaveBeenCalled()
  expect(api.confirmTubeReceipt).not.toHaveBeenCalled()
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks(); vi.useRealTimers() })

describe('D3整单喷塑回货', () => {
  it.each(['uid', 'generation', 'request', 'ready'] as const)('确认在%s边界后迟到成功不清记录、不提示', async boundary => {
    const { vm } = await mountPage(); receive(vm)
    let resolve!: (value: TubeReceipt) => void
    vi.mocked(api.confirmTubeReceipt).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const submitting = vm.finishReceipt(); const raw = localStorage.getItem(key)!
    if (boundary === 'uid') auth.user!.id = 8
    else if (boundary === 'generation') auth.identityGeneration += 1
    else if (boundary === 'request') auth.identityRequestGeneration += 1
    else Object.assign(auth, { identityReady: false })
    resolve(makeReceipt((JSON.parse(raw) as TubeReceiptPending).payload)); await submitting
    expect(localStorage.getItem(key)).toBe(raw); expect(vm.pending).not.toBeNull(); expect(vm.isEnded).toBe(false)
    expect(api.findTubeReceipt).not.toHaveBeenCalled(); expect(ElMessage.success).not.toHaveBeenCalled(); expect(ElMessage.warning).not.toHaveBeenCalled()
  })
  it.each([new AxiosError('超时'), httpError(404), new CanceledError('取消')])('旧确认拒绝或取消不启动原UUID查询或刷新', async cause => {
    const { vm } = await mountPage(); receive(vm)
    let reject!: (cause: unknown) => void
    vi.mocked(api.confirmTubeReceipt).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail }))
    const submitting = vm.finishReceipt(); const raw = localStorage.getItem(key)!
    if (cause.code !== 'ERR_CANCELED') auth.identityRequestGeneration += 1
    reject(cause); await submitting
    expect(localStorage.getItem(key)).toBe(raw); expect(api.findTubeReceipt).not.toHaveBeenCalled()
    expect(api.fetchTubeReceiptPreview).toHaveBeenCalledTimes(1); expect(ElMessage.warning).not.toHaveBeenCalled()
  })
  it('卸载后迟到确认不清原记录或提示', async () => {
    const { wrapper, vm } = await mountPage(); receive(vm)
    let resolve!: (value: TubeReceipt) => void
    vi.mocked(api.confirmTubeReceipt).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const submitting = vm.finishReceipt(); const raw = localStorage.getItem(key)!
    wrapper.unmount(); resolve(makeReceipt((JSON.parse(raw) as TubeReceiptPending).payload)); await submitting
    expect(localStorage.getItem(key)).toBe(raw); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it.each(['', '{broken', '{"payload":{"client_request_id":"unknown"}}'])('unknown历史回货记录原样隔离：%s', async raw => {
    const unknownKey = 'tube-coating-receipt:v1:unknown:order-1'; localStorage.setItem(unknownKey, raw)
    const { wrapper, vm } = await mountPage(); await vm.finishReceipt()
    expect(localStorage.getItem(unknownKey)).toBe(raw); expect(localStorage.getItem(key)).toBeNull()
    expect(api.fetchTubeReceiptPreview).not.toHaveBeenCalled(); expect(api.findTubeReceipt).not.toHaveBeenCalled(); expect(api.confirmTubeReceipt).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('身份不明')
  })
  it('未核验身份不访问存储、不加载API且显示原因', async () => {
    Object.assign(auth, { identityReady: false })
    const storage = vi.spyOn(Storage.prototype, 'getItem')
    const { wrapper, vm } = await mountPage(); await vm.finishReceipt()
    expect(storage).not.toHaveBeenCalled(); expect(api.fetchTubeReceiptPreview).not.toHaveBeenCalled(); expect(api.confirmTubeReceipt).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('身份尚未核验')
  })
  it('存储不可用时显示原因且不加载或提交', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('存储禁用') })
    const { wrapper, vm } = await mountPage(); await vm.finishReceipt()
    expect(api.fetchTubeReceiptPreview).not.toHaveBeenCalled(); expect(api.confirmTubeReceipt).not.toHaveBeenCalled(); expect(wrapper.text()).toContain('存储不可用')
  })
  it('保存请求编号失败时锁定且不确认入库', async () => {
    const { vm } = await mountPage(); receive(vm); vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('存储禁用') }); await vm.finishReceipt()
    expect(vm.storageError).toBe(true); expect(vm.pending).toBeNull(); expect(api.confirmTubeReceipt).not.toHaveBeenCalled()
  })
  it('清理存储失败保留原请求，不显示成功', async () => {
    const { vm } = await mountPage(); receive(vm); vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('存储禁用') }); await vm.finishReceipt()
    expect(vm.storageError).toBe(true); expect(vm.pending).not.toBeNull(); expect(localStorage.getItem(key)).not.toBeNull(); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it.each(['', '{broken'])('当前账号损坏或空raw保留且不加载API：%s', async raw => {
    localStorage.setItem(key, raw); const { vm } = await mountPage(); await vm.finishReceipt()
    expect(localStorage.getItem(key)).toBe(raw); expect(vm.storageError).toBe(true); expect(api.fetchTubeReceiptPreview).not.toHaveBeenCalled(); expect(api.confirmTubeReceipt).not.toHaveBeenCalled()
  })
  it('晚到的原UUID404不能在新代次继续预览或重放', async () => {
    const raw = JSON.stringify(savedRequest()); localStorage.setItem(key, raw)
    let reject!: (cause: unknown) => void
    vi.mocked(api.findTubeReceipt).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail }))
    await mountPage(); auth.identityRequestGeneration += 1; reject(httpError(404)); await flushPromises()
    expect(api.fetchTubeReceiptPreview).toHaveBeenCalledTimes(1); expect(api.confirmTubeReceipt).not.toHaveBeenCalled(); expect(localStorage.getItem(key)).toBe(raw)
  })
  it('清理只删除本页原raw，不移除另一页面替换的请求', async () => {
    const { vm } = await mountPage(); receive(vm)
    let resolve!: (value: TubeReceipt) => void
    vi.mocked(api.confirmTubeReceipt).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const submitting = vm.finishReceipt(); const original = localStorage.getItem(key)!
    const newer = '{"payload":{"client_request_id":"new-page"}}'; localStorage.setItem(key, newer)
    resolve(makeReceipt((JSON.parse(original) as TubeReceiptPending).payload)); await submitting
    expect(localStorage.getItem(key)).toBe(newer); expect(vm.pending).not.toBeNull(); expect(vm.storageError).toBe(true); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it('普通同身份核验不改变代次，原确认继续成功', async () => {
    const { vm } = await mountPage(); receive(vm)
    let resolve!: (value: TubeReceipt) => void
    vi.mocked(api.confirmTubeReceipt).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const submitting = vm.finishReceipt(); const raw = localStorage.getItem(key)!
    auth.user = { ...auth.user! }; resolve(makeReceipt((JSON.parse(raw) as TubeReceiptPending).payload)); await submitting
    expect(localStorage.getItem(key)).toBeNull(); expect(ElMessage.success).toHaveBeenCalledTimes(1)
  })
  it.each(['PUBLIC_CUTTING', 'SEWING'] as const)('%s裁片复用回货页，按套收货且少回仍须原因', async source => {
    const current = structuredClone(base)
    current.order.source_kind = source; current.order.craft_name = '丝印'
    Object.assign(current.order.lines[0]!, { fabric_material: '涤纶', specification: '420×380', fabric_specification: '600D', fabric_color: '蓝色', pieces_per_set: '2' })
    vi.mocked(api.fetchTubeReceiptPreview).mockResolvedValue(current)
    const { wrapper, vm } = await mountPage()
    expect(wrapper.get('h1').text()).toBe('裁片回货入库')
    expect(wrapper.get('.d3-lines').text()).toContain('实收（套）')
    expect(wrapper.get('.d3-lines').text()).toContain('涤纶')
    expect(wrapper.get('.d3-lines').text()).not.toContain('喷塑颜色')
    expect(wrapper.text()).toContain('已丝印')
    receive(vm, '18'); vm.rows[0]!.reason = ''; vm.openConfirm()
    expect(vm.dialog).toBe('')
    vm.rows[0]!.reason = '损耗'; vm.openConfirm(); await flushPromises()
    expect(vm.dialog).toBe('confirm')
    expect(wrapper.get('.d3-confirm-lines').text()).toContain('实收（套）')
    expect(api.confirmTubeReceipt).not.toHaveBeenCalled()
  })
  it('车间只读保留原单计划金额，不重算成实收结算额', async () => {
    routing.route.meta.outsourcingWorkspace = 'workshop'
    const { wrapper, vm } = await mountPage(); receive(vm, '18'); await flushPromises()
    expect(wrapper.get('.d3-lines').text()).toContain('0.25')
    expect(wrapper.get('.d3-footer').text()).toContain('计划加工金额 5 元')
    expect(api.confirmTubeReceipt).not.toHaveBeenCalled()
  })
  it('真实日期经办人、13独立属性列，无勾选、批次、实际颜色或根米换算', async () => {
    const { wrapper, vm } = await mountPage()
    expect(vm.receiptDate).toBe(base.today); expect(wrapper.get('[aria-label="入库经办人"]').attributes('readonly')).toBeDefined()
    expect(wrapper.get('[aria-label="入库经办人"]').attributes('value')).toBeUndefined()
    expect(wrapper.findAll('.d3-context .info-cell')).toHaveLength(12)
    expect(wrapper.findAll('.d3-lines th').map(item => item.text())).toEqual(['部位', '材质', '形状', '规格', '厚度 mm', '切割长度 mm', '原料颜色', '喷塑颜色', '加工厂', '实发（支）', '实收（支）', '差额（支）', '差额原因', '入库库区'])
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false); expect(wrapper.text()).not.toContain('批次'); expect(wrapper.text()).not.toContain('实发（根）')
    expect(vm.rows[0]!.received).toBe(''); expect(vm.warehouse).toBe('')
  })
  it.each(['RAW_PIPE', 'PUBLIC_SEMI', 'METAL'] as const)('%s三来源采用同一支数入库页面', async source => {
    const current = structuredClone(base); current.order.source_kind = source; vi.mocked(api.fetchTubeReceiptPreview).mockResolvedValue(current)
    const { wrapper } = await mountPage(); expect(wrapper.text()).toContain({ RAW_PIPE: '原材料', PUBLIC_SEMI: '未喷塑半成品', METAL: '未入库半成品' }[source])
    expect(wrapper.findAll('.d3-lines th')).toHaveLength(14)
  })
  it('全回只增加实收，保存UUID及原版本，结束后只读且不能追加', async () => {
    const { wrapper, vm } = await mountPage(); receive(vm); vm.openConfirm(); await flushPromises()
    expect(wrapper.find('.d3-confirm-lines').text()).toContain('20'); expect(wrapper.text()).toContain('整单只登记一次')
    await vm.finishReceipt()
    expect(api.confirmTubeReceipt).toHaveBeenCalledWith('order-1', expect.objectContaining({ receipt_date: base.today, warehouse_id: 'warehouse-1', lines: [{ order_line_id: 'line-1', received_quantity: '20', shortage_reason: '', zone_id: 'zone-1' }] }), order.etag)
    expect(vm.isEnded).toBe(true); expect(vm.canEdit).toBe(false); expect(vm.pending).toBeNull(); expect(localStorage.getItem(key)).toBeNull()
    expect(wrapper.find('[aria-label="前腿管实收支数"]').exists()).toBe(false)
    await vm.finishReceipt(); expect(api.confirmTubeReceipt).toHaveBeenCalledTimes(1)
  })
  it('空白和0包含整单每行，逐行少回原因必填；全0免仓库库区', async () => {
    const current = structuredClone(base); current.order.lines.push({ ...current.order.lines[0]!, id: 'line-2', part_name: '后腿管' }); vi.mocked(api.fetchTubeReceiptPreview).mockResolvedValue(current)
    const { wrapper, vm } = await mountPage(); vm.rows[1]!.received = '0'; vm.rows[0]!.reason = '前腿未收到'
    await vm.finishReceipt(); expect(api.confirmTubeReceipt).not.toHaveBeenCalled(); expect(ElMessage.warning).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('后腿管') }))
    vm.rows[1]!.reason = '后腿未收到'; vm.openConfirm(); await flushPromises(); expect(wrapper.find('.d3-confirm-lines tbody').findAll('tr')).toHaveLength(2)
    await vm.finishReceipt(); const payload = vi.mocked(api.confirmTubeReceipt).mock.calls[0]![1]
    expect(payload.warehouse_id).toBeNull(); expect(payload.lines.map(line => [line.received_quantity, line.zone_id])).toEqual([['0', null], ['0', null]])
    expect(vm.rows).toHaveLength(2); expect(vm.rows.every(row => row.received === '0')).toBe(true); expect(vm.isEnded).toBe(true)
    expect(ElMessage.success).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('未增加库存') }))
  })
  it.each(['-1', '0.5', 'abc', '21', '9007199254740992'])('无效实收%s只气泡拦截并保留填写内容', async value => {
    const { vm } = await mountPage(); receive(vm, value); await vm.finishReceipt()
    expect(api.confirmTubeReceipt).not.toHaveBeenCalled(); expect(vm.rows[0]!.received).toBe(value); expect(ElMessage.warning).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('整数') }))
  })
  it('少回原因去空白保存，正数库区必须属于所选目标仓库', async () => {
    const { vm } = await mountPage(); receive(vm, '18'); vm.rows[0]!.zone = 'zone-2'
    await vm.finishReceipt(); expect(api.confirmTubeReceipt).not.toHaveBeenCalled()
    vm.rows[0]!.zone = 'zone-1'; vm.rows[0]!.reason = '  实收18，另2未回  '; vm.remark = '  存A区  '; await vm.finishReceipt()
    expect(vi.mocked(api.confirmTubeReceipt).mock.calls[0]![1]).toEqual(expect.objectContaining({ remark: '存A区', lines: [{ order_line_id: 'line-1', received_quantity: '18', shortage_reason: '实收18，另2未回', zone_id: 'zone-1' }] }))
  })
  it('换仓须确认，仅清库区，数量原因备注保留', async () => {
    const { vm } = await mountPage(); receive(vm, '18'); vm.remark = '备注保留'; vm.requestWarehouseChange('warehouse-2')
    expect(vm.dialog).toBe('warehouse'); expect(vm.warehouse).toBe('warehouse-1'); vm.confirmWarehouseChange()
    expect(vm.warehouse).toBe('warehouse-2'); expect(vm.rows[0]).toEqual(expect.objectContaining({ received: '18', reason: '实物少回', zone: '' })); expect(vm.remark).toBe('备注保留')
    await vm.finishReceipt(); expect(api.confirmTubeReceipt).not.toHaveBeenCalled(); vm.rows[0]!.zone = 'zone-2'; await vm.finishReceipt(); expect(api.confirmTubeReceipt).toHaveBeenCalledTimes(1)
  })
  it.each([400, 403, 404, 409, 412, 428])('明确拒绝%s刷新依据并保留本次输入，不伪造成功', async status => {
    const { vm } = await mountPage(); receive(vm, '18'); vi.mocked(api.confirmTubeReceipt).mockRejectedValueOnce(httpError(status)); await vm.finishReceipt()
    expect(vm.pending).toBeNull(); expect(localStorage.getItem(key)).toBeNull(); expect(vm.rows[0]!.received).toBe('18'); expect(vm.rows[0]!.reason).toBe('实物少回')
    expect(api.fetchTubeReceiptPreview).toHaveBeenCalledTimes(2); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it('POST回包丢失时只查原UUID恢复，不二次入库', async () => {
    const { vm } = await mountPage(); receive(vm)
    vi.mocked(api.confirmTubeReceipt).mockImplementationOnce(async (_, payload) => { vi.mocked(api.findTubeReceipt).mockResolvedValue(makeReceipt(payload)); throw new AxiosError('超时', 'ECONNABORTED') })
    await vm.finishReceipt(); expect(api.confirmTubeReceipt).toHaveBeenCalledTimes(1); expect(vm.pending).toBeNull(); expect(vm.isEnded).toBe(true)
    expect(api.findTubeReceipt).toHaveBeenCalledWith('order-1', vi.mocked(api.confirmTubeReceipt).mock.calls[0]![1].client_request_id, true)
  })
  it('未知结果锁内容；人工同版本重试只使用原UUID原payload原If-Match', async () => {
    const { vm } = await mountPage(); receive(vm, '18'); vi.mocked(api.confirmTubeReceipt).mockRejectedValueOnce(new AxiosError('超时')); await vm.finishReceipt()
    const original = JSON.parse(localStorage.getItem(key)!) as TubeReceiptPending; expect(vm.canEdit).toBe(false)
    vm.receiptDate = '2099-01-01'; await vm.finishReceipt(); expect(api.confirmTubeReceipt).toHaveBeenCalledTimes(1)
    await vm.recoverPending(true); expect(vi.mocked(api.confirmTubeReceipt).mock.calls[1]).toEqual(['order-1', original.payload, original.etag]); expect(vm.pending).toBeNull()
  })
  it('重载恢复仅GET原UUID，404不自动写入，原输入完整恢复', async () => {
    const saved = savedRequest(); localStorage.setItem(key, JSON.stringify(saved)); const { vm } = await mountPage()
    expect(api.confirmTubeReceipt).not.toHaveBeenCalled(); expect(api.findTubeReceipt).toHaveBeenCalledWith('order-1', 'existing-uuid', true); expect(vm.pending).toEqual(saved); expect(vm.rows[0]!.reason).toBe('未收到')
  })
  it('首次原单读取失败但原UUID已确认，补齐真实预览后恢复', async () => {
    const saved = savedRequest(), result = makeReceipt(saved.payload); localStorage.setItem(key, JSON.stringify(saved))
    vi.mocked(api.fetchTubeReceiptPreview).mockRejectedValueOnce(new AxiosError('断线')).mockResolvedValue({ ...structuredClone(base), order: { ...structuredClone(order), status: 'COMPLETED' }, can_receive: false, receipt: result })
    vi.mocked(api.findTubeReceipt).mockResolvedValue(result); const { vm } = await mountPage()
    expect(api.fetchTubeReceiptPreview).toHaveBeenCalledTimes(2); expect(vm.pending).toBeNull(); expect(vm.isEnded).toBe(true); expect(vm.readError).toBe('')
  })
  it('原请求404后真实终态属于另一操作，再查404后显示真实结果并释放本地记录', async () => {
    const saved = savedRequest(), other = makeReceipt({ ...saved.payload, client_request_id: 'other-uuid' }); localStorage.setItem(key, JSON.stringify(saved))
    vi.mocked(api.fetchTubeReceiptPreview).mockResolvedValue({ ...structuredClone(base), order: { ...structuredClone(order), status: 'COMPLETED' }, can_receive: false, receipt: other })
    const { vm } = await mountPage(); expect(api.findTubeReceipt).toHaveBeenCalledTimes(2); expect(vm.pending).toBeNull(); expect(vm.preview?.receipt?.client_request_id).toBe('other-uuid'); expect(ElMessage.success).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('已由其他操作完成回货') }))
  })
  it('原UUID首次404但原POST刚完成，终态再次查询找到本人结果，不误称他人', async () => {
    const saved = savedRequest(), result = makeReceipt(saved.payload); localStorage.setItem(key, JSON.stringify(saved))
    vi.mocked(api.fetchTubeReceiptPreview).mockResolvedValue({ ...structuredClone(base), order: { ...structuredClone(order), status: 'COMPLETED' }, can_receive: false, receipt: result })
    vi.mocked(api.findTubeReceipt).mockRejectedValueOnce(httpError(404)).mockResolvedValueOnce(result)
    const { vm } = await mountPage(); expect(vm.pending).toBeNull(); expect(vm.isEnded).toBe(true); expect(api.confirmTubeReceipt).not.toHaveBeenCalled(); expect(ElMessage.success).toHaveBeenCalled()
    expect(ElMessage.warning).not.toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('已由其他操作') }))
  })
  it('终态二次查询断线仍保留待核对原UUID，不写入', async () => {
    const saved = savedRequest(), result = makeReceipt(saved.payload); localStorage.setItem(key, JSON.stringify(saved))
    vi.mocked(api.fetchTubeReceiptPreview).mockResolvedValue({ ...structuredClone(base), order: { ...structuredClone(order), status: 'COMPLETED' }, can_receive: false, receipt: result })
    vi.mocked(api.findTubeReceipt).mockRejectedValueOnce(httpError(404)).mockRejectedValueOnce(new AxiosError('断线'))
    const { vm } = await mountPage(); expect(vm.pending).toEqual(saved); expect(localStorage.getItem(key)).not.toBeNull(); expect(vm.canEdit).toBe(false); expect(api.confirmTubeReceipt).not.toHaveBeenCalled()
  })
  it.each([403, 404])('原请求404后预览%s不证明旧POST失败，保留请求锁定', async status => {
    const saved = savedRequest(); localStorage.setItem(key, JSON.stringify(saved)); vi.mocked(api.fetchTubeReceiptPreview).mockRejectedValue(httpError(status))
    const { vm } = await mountPage(); expect(vm.pending).toEqual(saved); expect(localStorage.getItem(key)).not.toBeNull(); expect(api.confirmTubeReceipt).not.toHaveBeenCalled()
  })
  it.each([403, 404])('未知请求人工重放%s，再次原UUID仍404时保留记录', async status => {
    const saved = savedRequest(); localStorage.setItem(key, JSON.stringify(saved)); const { vm } = await mountPage()
    vi.mocked(api.confirmTubeReceipt).mockRejectedValueOnce(httpError(status)); await vm.recoverPending(true)
    expect(vm.pending).toEqual(saved); expect(localStorage.getItem(key)).not.toBeNull(); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it('原版本变化或权限丢失时不自动重新办理', async () => {
    const saved = savedRequest(); localStorage.setItem(key, JSON.stringify(saved)); const { vm } = await mountPage()
    vi.mocked(api.fetchTubeReceiptPreview).mockResolvedValue({ ...structuredClone(base), etag: '"order-1:v9"', can_receive: false }); await vm.recoverPending(true)
    expect(vm.pending).toEqual(saved); expect(api.confirmTubeReceipt).not.toHaveBeenCalled()
  })
  it('只读查看入库记录使用真实receipt接口，保留0行及历史库区', async () => {
    const saved = savedRequest(), result = makeReceipt(saved.payload); vi.mocked(api.fetchTubeReceiptPreview).mockResolvedValue({ ...structuredClone(base), order: { ...structuredClone(order), status: 'COMPLETED' }, can_receive: false, receipt: result })
    vi.mocked(api.fetchTubeReceipt).mockResolvedValue(result); const { vm } = await mountPage(); await vm.showReceipt()
    expect(api.fetchTubeReceipt).toHaveBeenCalledWith('order-1', true); expect(vm.rows[0]).toEqual(expect.objectContaining({ received: '0', reason: '未收到', zone: '' })); expect(routing.push).not.toHaveBeenCalled()
  })
  it('只有查看权限时后端已完成预览可只读，无办理入口', async () => {
    permission.canReceive = false; const result = makeReceipt(savedRequest().payload)
    vi.mocked(api.fetchTubeReceiptPreview).mockResolvedValue({ ...structuredClone(base), order: { ...structuredClone(order), status: 'COMPLETED' }, can_receive: false, receipt: result })
    const { wrapper, vm } = await mountPage(); expect(vm.isEnded).toBe(true); expect(vm.canEdit).toBe(false); expect(wrapper.text()).toContain('整单回货结果')
    expect(wrapper.find('[aria-label="前腿管实收支数"]').exists()).toBe(false); await vm.finishReceipt(); expect(api.confirmTubeReceipt).not.toHaveBeenCalled()
  })
  it('原单缺失实发数量不能把空白错误当作可结单0', async () => {
    const current = structuredClone(base); current.order.lines[0]!.quantity = ''; vi.mocked(api.fetchTubeReceiptPreview).mockResolvedValue(current)
    const { vm } = await mountPage(); expect(vm.canEdit).toBe(false); expect(vm.readError).toContain('实发数量不完整'); await vm.finishReceipt(); expect(api.confirmTubeReceipt).not.toHaveBeenCalled()
  })
  it('已结束但缺最终凭证不能显示假成功结果', async () => {
    vi.mocked(api.fetchTubeReceiptPreview).mockResolvedValue({ ...structuredClone(base), order: { ...structuredClone(order), status: 'COMPLETED' }, can_receive: false })
    const { vm } = await mountPage(); expect(vm.isEnded).toBe(false); expect(vm.canEdit).toBe(false); expect(vm.readError).toContain('最终回货凭证缺失')
  })
  it('原UUID回查结果不匹配时保留原请求，不能按别人数量确认成功', async () => {
    const saved = savedRequest(); localStorage.setItem(key, JSON.stringify(saved)); vi.mocked(api.findTubeReceipt).mockResolvedValue(makeReceipt({ ...saved.payload, client_request_id: 'wrong-uuid' }))
    const { vm } = await mountPage(); expect(vm.pending).toEqual(saved); expect(ElMessage.success).not.toHaveBeenCalled(); expect(api.confirmTubeReceipt).not.toHaveBeenCalled()
  })
  it.each(['PENDING_DISPATCH', 'CANCELLED'])('%s只读不适用，不新增业务按钮', async status => {
    vi.mocked(api.fetchTubeReceiptPreview).mockResolvedValue({ ...structuredClone(base), order: { ...structuredClone(order), status }, can_receive: false })
    const { vm, wrapper } = await mountPage(); expect(vm.canEdit).toBe(false); expect(wrapper.find('.d3-lines').exists()).toBe(false); await vm.finishReceipt(); expect(api.confirmTubeReceipt).not.toHaveBeenCalled()
  })
  it('缺少外发单时返回仓库委外管理，不再提供选单入口或弹窗', async () => {
    routing.route.params.id = ''
    const { vm, wrapper } = await mountPage()
    expect(api.fetchTubeReceiptPreview).not.toHaveBeenCalled()
    expect(api.fetchTubeReceiptCandidates).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请从仓库委外管理选择外发单办理入库')
    expect(wrapper.findAll('button').some(button => button.text() === '选择外发单')).toBe(false)
    expect(wrapper.find('.d3-select-order').exists()).toBe(false)
    vm.returnToSource()
    expect(routing.push).toHaveBeenCalledWith({ name: 'warehouse-outsourcing' })
  })
  it('损坏请求记录和另一页待核对记录不得覆盖并重新办理', async () => {
    localStorage.setItem(key, '{bad-json'); const { vm } = await mountPage(); expect(vm.storageError).toBe(true); expect(api.confirmTubeReceipt).not.toHaveBeenCalled()
    localStorage.clear(); const second = await mountPage(); receive(second.vm); localStorage.setItem(key, JSON.stringify(savedRequest())); await second.vm.finishReceipt()
    expect(api.confirmTubeReceipt).not.toHaveBeenCalled(); expect(JSON.parse(localStorage.getItem(key)!)).toEqual(savedRequest())
  })
})

it('列表内嵌沿用原入库表单，显式编号、在途关闭保护及成功事件有效', async () => {
  routing.route.params.id = ''
  const { wrapper, vm } = await mountPage({ orderId: 'order-1', embedded: true })
  expect(api.fetchTubeReceiptPreview).toHaveBeenCalledWith('order-1', true)
  expect(wrapper.find('.d3-heading').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('加工单价')
  expect(wrapper.text()).not.toContain('计划加工金额')
  expect(Number.parseFloat((wrapper.get('.d3-lines table').element as HTMLTableElement).style.minWidth)).toBeLessThanOrEqual(1300)
  receive(vm)
  let resolve!: (receipt: TubeReceipt) => void
  let payload!: TubeReceiptInput
  vi.mocked(api.confirmTubeReceipt).mockImplementationOnce(async (_, input) => { payload = input; return new Promise(done => { resolve = done }) })
  const submitting = vm.finishReceipt()
  expect((wrapper.vm as unknown as { canClose: () => boolean }).canClose()).toBe(false)
  resolve(makeReceipt(payload)); await submitting
  expect((wrapper.vm as unknown as { canClose: () => boolean }).canClose()).toBe(true)
  expect(wrapper.emitted('updated')?.[0]?.[0]).toMatchObject({ id: 'receipt-1', order_id: 'order-1' })
  vm.returnToSource()
  expect(wrapper.emitted('closed')).toHaveLength(1)
  expect(routing.push).not.toHaveBeenCalled()
})

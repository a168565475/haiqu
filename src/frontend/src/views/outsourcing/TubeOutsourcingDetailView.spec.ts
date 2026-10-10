import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/tubeOutsourcing'
import * as receiptApi from '@/api/tubeReceipts'
import type { TubeOrderDetail, TubePendingAction } from '@/types/tubeOutsourcing'
import TubeOutsourcingDetailView from './TubeOutsourcingDetailView.vue'

const routing = vi.hoisted(() => ({ push: vi.fn() }))
const permission = vi.hoisted(() => ({ canReceive: true }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { id: 'order-1' }, query: {} }), useRouter: () => routing }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 7, is_superuser: false, display_name: '真实经办人' }, hasPermission: (name: string) => name === 'outsourcing.confirm_return_outsourcingorder' ? permission.canReceive : true }) }))
vi.mock('@/api/tubeOutsourcing', () => ({ fetchTubeOrder: vi.fn(), dispatchTubeOrder: vi.fn(), cancelTubeOrder: vi.fn(), findTubeAction: vi.fn() }))
vi.mock('@/api/tubeReceipts', () => ({ fetchTubeReceiptPreview: vi.fn() }))
vi.mock('element-plus', async original => ({ ...await original<typeof import('element-plus')>(), ElMessage: { closeAll: vi.fn(), warning: vi.fn(), success: vi.fn() } }))

const key = 'tube-outsourcing-action:v1:7:order-1'
const base: TubeOrderDetail = {
  id: 'order-1', order_number: 'WF-real', status: 'PENDING_DISPATCH', version: 1, etag: '"order-1:v1"', created: false,
  client_request_id: 'creation-id', source_kind: 'RAW_PIPE', source_label: '原材料', schedule_product_id: 'plan-1', product_line_id: 'product-1',
  planned_dispatch_date: '2026-09-30', expected_return_date: '2026-10-15', total_quantity: '20', total_stock_quantity: '2', total_meters: '13.10',
  task_order_number: 'DD-real', task_number: 'SC-real', schedule_number: 'PC-real', product_number: 'CP-real', item_number: 'HT-real', product_name: '真实测试产品', quantity: '1000', unit: '把', color: '黑色',
  zone_id: 'zone-1', zone_name: 'A区', warehouse_name: '原料管材仓', craft_name: '喷塑', remark: '原单备注', created_at: '2026-09-30T08:00:00+08:00', created_by_name: '建单员工',
  actual_dispatch_date: null, dispatched_at: null, dispatched_by_name: '', cancelled_at: null, cancelled_by_name: '', cancel_remark: '',
  permissions: { can_dispatch: true, can_cancel: true },
  lines: [{ id: 'line-1', component_identity: 'component-1', part_name: '前腿管', factory_id: 'factory-1', factory_name: '加工厂甲', quantity: '20', stock_quantity: '2', meters: '13.10',
    material: 'Q195', specification: 'Φ22', thickness: '0.8', cutting_length_mm: '650', raw_color: '本色', spray_color: '黑色', pieces_per_bar: '10', raw_bar_length_m: '6.55', current_reported_minimum: null, operations: [], basis_blockers: [] }],
}
const httpError = (status: number) => Object.assign(new AxiosError('接口错误'), { response: { status, data: { error: { message: `状态 ${status}` } } } })
function result(kind: 'DISPATCH' | 'CANCEL', requestId: string): TubeOrderDetail {
  return { ...structuredClone(base), version: 2, etag: '"order-1:v2"', status: kind === 'DISPATCH' ? 'PROCESSING' : 'CANCELLED', action: { id: 'action-1', kind, client_request_id: requestId, confirmed_at: '2026-09-30T10:00:00+08:00', actor_name: '真实经办人' } }
}
interface ViewModel {
  detail: TubeOrderDetail | null; pending: TubePendingAction | null; dialog: string; dispatchDate: string; cancellationRemark: string
  recheckError: string; readError: string; storageError: boolean; canDispatch: boolean; canCancel: boolean
  submit: (kind: 'DISPATCH' | 'CANCEL') => Promise<void>; recoverPending: (allowRetry?: boolean) => Promise<void>
  loadDetail: () => Promise<void>; openBasis: (row: TubeOrderDetail['lines'][number]) => void; recreate: () => void
}
const wrappers: ReturnType<typeof mount>[] = []
async function mountPage() {
  const wrapper = mount(TubeOutsourcingDetailView, { global: { plugins: [ElementPlus], stubs: { AppWindowDialog: { props: ['modelValue', 'title'], template: '<div v-if="modelValue" :aria-label="title"><slot /><slot name="footer" /></div>' } } } })
  wrappers.push(wrapper); await flushPromises()
  return { wrapper, vm: wrapper.vm as unknown as ViewModel }
}
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear(); permission.canReceive = true
  vi.mocked(receiptApi.fetchTubeReceiptPreview).mockRejectedValue(httpError(403))
  vi.mocked(api.fetchTubeOrder).mockResolvedValue(structuredClone(base))
  vi.mocked(api.findTubeAction).mockRejectedValue(httpError(404))
  vi.mocked(api.dispatchTubeOrder).mockImplementation(async (_, payload) => result('DISPATCH', payload.client_request_id))
  vi.mocked(api.cancelTubeOrder).mockImplementation(async (_, payload) => result('CANCEL', payload.client_request_id))
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('管材外发详情与整单动作', () => {
  it('加工中喷塑入库接到D3，无回货权限则沿原按钮禁用', async () => {
    vi.mocked(api.fetchTubeOrder).mockResolvedValue({ ...structuredClone(base), status: 'PROCESSING' })
    const { wrapper } = await mountPage(); const button = wrapper.findAll('button').find(item => item.text() === '喷塑入库')!
    expect(button.attributes('disabled')).toBeUndefined(); await button.trigger('click')
    expect(routing.push).toHaveBeenCalledWith({ name: 'workshop-outsourcing-tube-return', params: { id: 'order-1' } })
    permission.canReceive = false; const denied = await mountPage(); expect(denied.wrapper.findAll('button').find(item => item.text() === '喷塑入库')!.attributes('disabled')).toBeDefined()
  })
  it('已结束缺少最终凭证时保留原单状态，凭证入口禁用且不能再办理发出或回货', async () => {
    const completed = { ...structuredClone(base), status: 'COMPLETED' }
    vi.mocked(receiptApi.fetchTubeReceiptPreview).mockResolvedValue({ order: completed, etag: completed.etag, can_receive: false, blockers: [], actor_name: '', today: '2026-09-30', warehouses: [], zones: [], receipt: null })
    const { wrapper, vm } = await mountPage(); expect(wrapper.text()).toContain('已结束'); expect(wrapper.text()).toContain('WF-real')
    expect(vm.canDispatch).toBe(false); expect(vm.canCancel).toBe(false)
    expect(wrapper.findAll('button').some(item => ['喷塑入库', '确认实际发出', '取消待发单', '查看入库记录'].includes(item.text()))).toBe(false)
    expect(wrapper.findAll('button').find(item => item.text() === '查看入库凭证')!.attributes('disabled')).toBeDefined()
    expect(api.fetchTubeOrder).not.toHaveBeenCalled()
  })
  it('原材料支根米在同一只读表，独立规格颜色厚度且不含勾选', async () => {
    const { wrapper, vm } = await mountPage()
    expect(wrapper.findAll('.d4-context .info-cell')).toHaveLength(12)
    expect(wrapper.findAll('.d4-lines th').map(cell => cell.text())).toEqual(['部位', '材质', '规格', '厚度 mm', '切割长度 mm', '原料颜色', '喷塑颜色', '加工厂', '切割支数 支/根', '原材料长度 m/根', '待发支数（支）', '待扣（根）', '待扣（米）'])
    expect(wrapper.find('.d4-lines input').exists()).toBe(false)
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
    vm.dialog = 'dispatch'; await flushPromises()
    expect(wrapper.find('.d4-dispatch-lines input').exists()).toBe(false)
    expect(wrapper.get('[aria-label="发出经办人"]').attributes('readonly')).toBeDefined()
    await vm.submit('DISPATCH')
    expect(api.dispatchTubeOrder).toHaveBeenCalledWith('order-1', { client_request_id: expect.any(String), actual_dispatch_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/) }, '"order-1:v1"')
    expect(vm.detail?.status).toBe('PROCESSING'); expect(vm.pending).toBeNull(); expect(localStorage.getItem(key)).toBeNull()
    expect(wrapper.text()).not.toContain('结清'); expect(wrapper.text()).not.toContain('重新加工')
  })
  it('取消备注可空，原单保留并出现带相同来源的重建入口', async () => {
    const { vm } = await mountPage(); vm.cancellationRemark = '   '
    await vm.submit('CANCEL')
    expect(api.cancelTubeOrder).toHaveBeenCalledWith('order-1', { client_request_id: expect.any(String), remark: '' }, '"order-1:v1"')
    expect(vm.detail?.status).toBe('CANCELLED'); expect(api.dispatchTubeOrder).not.toHaveBeenCalled()
    vm.recreate(); expect(routing.push).toHaveBeenCalledWith({ name: 'workshop-outsourcing-tube-new', query: { schedule_product_id: 'plan-1', source_kind: 'RAW_PIPE', zone_id: 'zone-1' } })
  })
  it('缺发出日期只气泡拦截，无请求', async () => {
    const { vm } = await mountPage(); vm.dispatchDate = ''; await vm.submit('DISPATCH')
    expect(api.dispatchTubeOrder).not.toHaveBeenCalled(); expect(vm.pending).toBeNull()
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.objectContaining({ message: '请选择实际发出日期。' }))
  })
  it.each(['PUBLIC_SEMI', 'METAL'] as const)('%s只按支展示，不带原管材换算', async source => {
    const data = structuredClone(base); data.source_kind = source; data.total_stock_quantity = source === 'METAL' ? null : '20'; data.total_meters = null
    data.lines[0]!.current_reported_minimum = source === 'METAL' ? '100' : null
    vi.mocked(api.fetchTubeOrder).mockResolvedValue(data)
    const { wrapper } = await mountPage()
    expect(wrapper.findAll('.d4-lines th').map(cell => cell.text())).not.toContain('待扣（根）')
    expect(wrapper.text()).toContain(source === 'METAL' ? '未入库半成品' : '未喷塑半成品')
  })
  it('真实最低报工为0与缺依据分别显示，点开读取真实必需工序', async () => {
    const data = structuredClone(base); data.source_kind = 'METAL'; const row = data.lines[0]!
    row.current_reported_minimum = '0'; row.operations = [{ work_item_id: 'work-1', operation_id: 'cut', name: '切管', scheme_id: 'scheme-real', scheme_revision: 2, quantity: '100' }, { work_item_id: 'work-2', operation_id: 'bend', name: '弯管', scheme_id: 'scheme-real', scheme_revision: 2, quantity: '0' }]
    vi.mocked(api.fetchTubeOrder).mockResolvedValue(data)
    const { wrapper, vm } = await mountPage()
    expect(wrapper.get('[aria-label="前腿管最低报工"]').text()).toBe('0')
    vm.openBasis(vm.detail!.lines[0]!); await flushPromises()
    expect(wrapper.find('.d4-operation-lines').text()).toContain('切管'); expect(wrapper.find('.d4-operation-lines').text()).toContain('弯管')
    expect(wrapper.find('.d4-basis-result').text()).toContain('0')
    row.current_reported_minimum = null; row.basis_blockers = ['当前没有已批准工价方案']; vi.mocked(api.fetchTubeOrder).mockResolvedValue(structuredClone(data))
    await vm.loadDetail(); vm.openBasis(vm.detail!.lines[0]!); await flushPromises()
    expect(wrapper.get('[aria-label="前腿管最低报工"]').text()).toBe('—'); expect(wrapper.find('.d4-basis').text()).toContain('当前没有已批准工价方案')
  })
  it.each([400, 409, 412])('实际发出明确拒绝%s时刷新真实版本并保留原单数量', async status => {
    const { vm } = await mountPage(); vi.mocked(api.dispatchTubeOrder).mockRejectedValueOnce(httpError(status))
    await vm.submit('DISPATCH')
    expect(vm.pending).toBeNull(); expect(localStorage.getItem(key)).toBeNull()
    expect(vm.detail?.lines[0]?.quantity).toBe('20'); expect(vm.recheckError).toBe(`状态 ${status}`)
    expect(api.fetchTubeOrder).toHaveBeenCalledTimes(2)
  })
  it('超时回查成功不第二次发出，仅按原请求核对', async () => {
    const { vm } = await mountPage()
    vi.mocked(api.dispatchTubeOrder).mockImplementationOnce(async (_, payload) => { vi.mocked(api.findTubeAction).mockResolvedValue(result('DISPATCH', payload.client_request_id)); throw new AxiosError('超时', 'ECONNABORTED') })
    await vm.submit('DISPATCH')
    expect(api.dispatchTubeOrder).toHaveBeenCalledTimes(1); expect(vm.pending).toBeNull(); expect(vm.detail?.status).toBe('PROCESSING')
  })
  it('超时未知锁定两动作，人工确认未登记时只重放原UUID和原内容原版本', async () => {
    const { vm } = await mountPage(); vi.mocked(api.dispatchTubeOrder).mockRejectedValueOnce(new AxiosError('超时', 'ECONNABORTED'))
    await vm.submit('DISPATCH'); const original = JSON.parse(JSON.stringify(vm.pending)) as TubePendingAction
    expect(vm.canDispatch).toBe(false); expect(vm.canCancel).toBe(false); expect(JSON.parse(localStorage.getItem(key)!)).toEqual(original)
    vm.dispatchDate = '2099-01-01'; await vm.submit('CANCEL'); expect(api.cancelTubeOrder).not.toHaveBeenCalled()
    await vm.recoverPending(true)
    expect(api.dispatchTubeOrder).toHaveBeenCalledTimes(2)
    expect(vi.mocked(api.dispatchTubeOrder).mock.calls[1]).toEqual(['order-1', original.payload, original.etag])
    expect(vm.pending).toBeNull()
  })
  it('刷新恢复只查询原UUID，404不自动再次写入', async () => {
    const action: TubePendingAction = { order_id: 'order-1', kind: 'DISPATCH', etag: '"order-1:v1"', payload: { client_request_id: 'existing-uuid', actual_dispatch_date: '2026-09-30' } }
    localStorage.setItem(key, JSON.stringify(action)); const { vm } = await mountPage()
    expect(api.findTubeAction).toHaveBeenCalledWith('order-1', 'existing-uuid'); expect(api.dispatchTubeOrder).not.toHaveBeenCalled()
    expect(vm.pending).toEqual(action); expect(vm.canDispatch).toBe(false)
  })
  it('核对时原单版本或权限已变不能重放写入', async () => {
    const { vm } = await mountPage(); vi.mocked(api.dispatchTubeOrder).mockRejectedValueOnce(new AxiosError('超时'))
    await vm.submit('DISPATCH'); const changed = structuredClone(base); changed.etag = '"order-1:v2"'; changed.permissions.can_dispatch = false
    vi.mocked(api.fetchTubeOrder).mockResolvedValue(changed); await vm.recoverPending(true)
    expect(api.dispatchTubeOrder).toHaveBeenCalledTimes(1); expect(vm.pending).not.toBeNull()
  })
  it.each(['PROCESSING', 'CANCELLED'])('原请求404但单已%s由其他动作完成，采用真实终态并清理本地不假报原请求成功', async status => {
    const action: TubePendingAction = { order_id: 'order-1', kind: 'DISPATCH', etag: '"order-1:v1"', payload: { client_request_id: 'existing-uuid', actual_dispatch_date: '2026-09-30' } }
    localStorage.setItem(key, JSON.stringify(action)); vi.mocked(api.fetchTubeOrder).mockResolvedValue({ ...structuredClone(base), status, etag: '"order-1:v2"' })
    const { vm } = await mountPage()
    expect(vm.detail?.status).toBe(status); expect(vm.pending).toBeNull(); expect(localStorage.getItem(key)).toBeNull()
    expect(api.dispatchTubeOrder).not.toHaveBeenCalled(); expect(api.cancelTubeOrder).not.toHaveBeenCalled(); expect(ElMessage.success).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('已由其他操作处理') }))
  })
  it('首次原请求404后单成终态，第二次已查到本人延迟提交，按原请求成功恢复且不重写', async () => {
    const action: TubePendingAction = { order_id: 'order-1', kind: 'DISPATCH', etag: '"order-1:v1"', payload: { client_request_id: 'delayed-uuid', actual_dispatch_date: '2026-09-30' } }
    localStorage.setItem(key, JSON.stringify(action))
    vi.mocked(api.fetchTubeOrder).mockResolvedValue({ ...structuredClone(base), status: 'PROCESSING', etag: '"order-1:v2"' })
    vi.mocked(api.findTubeAction).mockRejectedValueOnce(httpError(404)).mockResolvedValueOnce(result('DISPATCH', 'delayed-uuid'))
    const { vm } = await mountPage()
    expect(api.findTubeAction).toHaveBeenCalledTimes(2); expect(vm.detail?.action?.client_request_id).toBe('delayed-uuid')
    expect(vm.pending).toBeNull(); expect(localStorage.getItem(key)).toBeNull()
    expect(api.dispatchTubeOrder).not.toHaveBeenCalled(); expect(ElMessage.success).toHaveBeenCalled()
    expect(ElMessage.warning).not.toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('已由其他操作处理') }))
  })
  it('首次原请求404后单成终态但第二次查询断线，仍保留原请求核对且不重写', async () => {
    const action: TubePendingAction = { order_id: 'order-1', kind: 'DISPATCH', etag: '"order-1:v1"', payload: { client_request_id: 'delayed-uuid', actual_dispatch_date: '2026-09-30' } }
    localStorage.setItem(key, JSON.stringify(action))
    vi.mocked(api.fetchTubeOrder).mockResolvedValue({ ...structuredClone(base), status: 'PROCESSING', etag: '"order-1:v2"' })
    vi.mocked(api.findTubeAction).mockRejectedValueOnce(httpError(404)).mockRejectedValueOnce(new AxiosError('断线', 'ECONNABORTED'))
    const { vm } = await mountPage()
    expect(api.findTubeAction).toHaveBeenCalledTimes(2); expect(vm.pending).toEqual(action); expect(JSON.parse(localStorage.getItem(key)!)).toEqual(action)
    expect(api.dispatchTubeOrder).not.toHaveBeenCalled(); expect(api.cancelTubeOrder).not.toHaveBeenCalled(); expect(ElMessage.success).not.toHaveBeenCalled()
    expect(vm.canDispatch).toBe(false); expect(vm.canCancel).toBe(false)
  })
  it.each([403, 404])('原请求核对404后详情只读GET失败%s，不能当作POST拒绝清除原记录', async status => {
    const { vm } = await mountPage(); vi.mocked(api.dispatchTubeOrder).mockRejectedValueOnce(new AxiosError('超时'))
    await vm.submit('DISPATCH'); const original = JSON.parse(JSON.stringify(vm.pending)) as TubePendingAction
    vi.mocked(api.fetchTubeOrder).mockRejectedValue(httpError(status)); await vm.recoverPending(true)
    expect(api.dispatchTubeOrder).toHaveBeenCalledTimes(1); expect(vm.pending).toEqual(original); expect(JSON.parse(localStorage.getItem(key)!)).toEqual(original)
    expect(vm.canDispatch).toBe(false); expect(vm.canCancel).toBe(false); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it.each([403, 404])('未知原请求重放POST权限或入口拒绝%s，核对仍404时不能遗忘先前在途请求', async status => {
    const { vm } = await mountPage(); vi.mocked(api.dispatchTubeOrder).mockRejectedValueOnce(new AxiosError('超时'))
    await vm.submit('DISPATCH'); const original = JSON.parse(JSON.stringify(vm.pending)) as TubePendingAction
    vi.mocked(api.dispatchTubeOrder).mockRejectedValueOnce(httpError(status)); await vm.recoverPending(true)
    expect(api.dispatchTubeOrder).toHaveBeenCalledTimes(2); expect(vm.pending).toEqual(original); expect(JSON.parse(localStorage.getItem(key)!)).toEqual(original)
    expect(vm.canDispatch).toBe(false); expect(vm.canCancel).toBe(false); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it('未知原请求重放权限拒绝后原POST迟提交成功，再查原UUID恢复本人结果', async () => {
    const { vm } = await mountPage(); vi.mocked(api.dispatchTubeOrder).mockRejectedValueOnce(new AxiosError('超时'))
    await vm.submit('DISPATCH'); const original = JSON.parse(JSON.stringify(vm.pending)) as TubePendingAction
    vi.mocked(api.dispatchTubeOrder).mockRejectedValueOnce(httpError(403))
    vi.mocked(api.findTubeAction).mockRejectedValueOnce(httpError(404)).mockResolvedValueOnce(result('DISPATCH', original.payload.client_request_id))
    await vm.recoverPending(true)
    expect(vm.detail?.action?.client_request_id).toBe(original.payload.client_request_id); expect(vm.pending).toBeNull(); expect(localStorage.getItem(key)).toBeNull()
    expect(ElMessage.success).toHaveBeenCalled(); expect(api.dispatchTubeOrder).toHaveBeenCalledTimes(2)
  })
  it('没有操作权限不写入，错误读取不显示可办理详情', async () => {
    vi.mocked(api.fetchTubeOrder).mockResolvedValue({ ...structuredClone(base), permissions: { can_dispatch: false, can_cancel: false } })
    const { vm } = await mountPage(); await vm.submit('DISPATCH'); await vm.submit('CANCEL')
    expect(api.dispatchTubeOrder).not.toHaveBeenCalled(); expect(api.cancelTubeOrder).not.toHaveBeenCalled()
    vi.mocked(api.fetchTubeOrder).mockRejectedValue(httpError(403)); await vm.loadDetail(); expect(vm.readError).toBe('状态 403')
  })
  it('其他标签页已有原请求时不覆盖、不写入', async () => {
    const { vm } = await mountPage(); localStorage.setItem(key, 'another-page-pending'); await vm.submit('DISPATCH')
    expect(api.dispatchTubeOrder).not.toHaveBeenCalled(); expect(localStorage.getItem(key)).toBe('another-page-pending')
  })
  it('损坏本地请求记录阻止任何新操作', async () => {
    localStorage.setItem(key, JSON.stringify({ order_id: 'different-order' })); const { vm } = await mountPage()
    expect(vm.storageError).toBe(true); await vm.submit('DISPATCH'); expect(api.dispatchTubeOrder).not.toHaveBeenCalled()
    expect(localStorage.getItem(key)).not.toBeNull()
  })
  it('较旧详情请求不覆盖刷新后的新版', async () => {
    const { vm } = await mountPage(); let finish!: (value: TubeOrderDetail) => void
    vi.mocked(api.fetchTubeOrder).mockReturnValueOnce(new Promise(resolve => { finish = resolve })).mockResolvedValueOnce({ ...structuredClone(base), etag: '"order-1:v2"' })
    const old = vm.loadDetail(); await flushPromises(); await vm.loadDetail(); finish(structuredClone(base)); await old
    expect(vm.detail?.etag).toBe('"order-1:v2"')
  })
})

import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { AxiosError } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/tubeOutsourcing'
import type { TubeOptions, TubeOrderInput, TubeOrderResult, TubeSourceContext, TubeSourceRow } from '@/types/tubeOutsourcing'
import TubeOutsourcingFormView from './TubeOutsourcingFormView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ query: { schedule_product_id: 'schedule-product' } }), useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 'actor', is_superuser: true }, hasPermission: () => true }) }))
vi.mock('@/api/tubeOutsourcing', () => ({ fetchTubeOptions: vi.fn(), fetchTubeSource: vi.fn(), createTubeOrder: vi.fn(), findTubeOrder: vi.fn() }))
vi.mock('element-plus', async original => ({ ...await original<typeof import('element-plus')>(), ElMessage: { warning: vi.fn(), success: vi.fn() } }))

const key = 'tube-outsourcing-pending:v1:actor'
const options: TubeOptions = {
  tasks: [{ id: 'task', task_number: 'SC-test', order_number: 'DD-test', products: [{ id: 'product', schedule_product_id: 'schedule-product', schedule_number: 'PC-test', product_number: 'CP-test', item_number: 'HT-test', product_name: '测试椅', quantity: '1000', unit: '把', color: '黑色' }] }],
  factories: [{ id: 'factory', name: '测试加工厂' }],
  zones: [
    { id: 'zone', name: 'A区', warehouse_id: 'warehouse', warehouse_name: '材料仓', warehouse_type: 'MATERIAL' },
    { id: 'zone-other', name: 'B区', warehouse_id: 'other', warehouse_name: '另一材料仓', warehouse_type: 'MATERIAL' },
    { id: 'semi-empty', name: '无库存区', warehouse_id: 'semi-warehouse', warehouse_name: '半成品仓', warehouse_type: 'SEMI_FINISHED' },
    { id: 'semi-ready', name: '有库存区', warehouse_id: 'semi-warehouse-2', warehouse_name: '半成品备用仓', warehouse_type: 'SEMI_FINISHED' },
  ],
  source_kinds: [{ value: 'RAW_PIPE', label: '公共原管材' }, { value: 'PUBLIC_SEMI', label: '公共未喷塑半成品' }, { value: 'METAL', label: '厂内已加工件' }],
}
const row: TubeSourceRow = { component_identity: 'front', bom_line_id: 'bom-front', part_name: '前腿管', material: 'Q195', specification: 'Φ22', thickness: '0.8', cutting_length_mm: '650', raw_color: '原料本色', spray_color: '黑色', order_required: '2000', stock_quantity: '200', stock_unit: '根', max_quantity: '1200', pieces_per_bar: '6', raw_bar_length_m: '3.95', blockers: [] }
const context: TubeSourceContext = { source_revision: 'revision-1', source_kind: 'RAW_PIPE', schedule_product_id: 'schedule-product', product_line_id: 'product', task_id: 'task', task_number: 'SC-test', order_number: 'DD-test', schedule_number: 'PC-test', product_number: 'CP-test', item_number: 'HT-test', product_name: '测试椅', quantity: '1000', unit: '把', color: '黑色', craft_name: '喷塑', zone_id: 'zone', ready: true, blockers: [], tasks: options.tasks, factories: options.factories, zones: options.zones, rows: [row] }
const result = (payload: TubeOrderInput): TubeOrderResult => ({ ...payload, id: 'saved-order', order_number: 'WF-real-response', status: 'PENDING_DISPATCH', version: 1, etag: 'saved', created: true, product_line_id: 'product', total_quantity: '600', total_stock_quantity: '100', total_meters: '395.00' })
const httpError = (status: number) => Object.assign(new AxiosError('接口错误'), { response: { status, data: { error: { message: `状态 ${status}` } } } })
interface ViewModel {
  rows: Array<TubeSourceRow & { quantity: string; factoryId: string }>; returnDate: string
  dialog: string; pending: TubeOrderInput | null; error: string; sourceHint: string; warehouseId: string; zoneId: string
  context: TubeSourceContext | null
  checkDispatch: () => void; save: () => Promise<void>; loadSource: (preserve?: boolean) => Promise<void>
  requestChange: (kind: string, value: string) => void; applyChange: () => Promise<void>
}
async function mountPage() {
  const wrapper = shallowMount(TubeOutsourcingFormView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  const vm = wrapper.vm as unknown as ViewModel
  vm.returnDate = '2099-10-14'
  return { wrapper, vm }
}
function fill(vm: ViewModel) { vm.rows[0]!.quantity = '600'; vm.rows[0]!.factoryId = 'factory' }

describe('管材建单与异常恢复', () => {
  beforeEach(() => {
    vi.resetAllMocks(); localStorage.clear()
    vi.mocked(api.fetchTubeOptions).mockResolvedValue(structuredClone(options))
    vi.mocked(api.fetchTubeSource).mockResolvedValue(structuredClone(context))
    vi.mocked(api.findTubeOrder).mockRejectedValue(httpError(404))
    vi.mocked(api.createTubeOrder).mockImplementation(async payload => result(payload))
  })
  it('全空或全零不能进入保存确认，正数必须填写厂家', async () => {
    const { wrapper, vm } = await mountPage()
    vm.checkDispatch(); expect(vm.dialog).toBe('')
    vm.rows[0]!.quantity = '0'; vm.checkDispatch(); expect(vm.dialog).toBe('')
    vm.rows[0]!.quantity = '600'; vm.checkDispatch(); expect(vm.dialog).toBe('')
    vm.rows[0]!.factoryId = 'factory'; vm.checkDispatch(); expect(vm.dialog).toBe('confirm')
    expect(api.createTubeOrder).not.toHaveBeenCalled(); wrapper.unmount()
  })
  it('换来源在确认前保留输入，确认后清空', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    vm.requestChange('source', 'METAL')
    expect(vm.dialog).toBe('change'); expect(vm.rows[0]!.quantity).toBe('600')
    await vm.applyChange(); expect(vm.rows[0]!.quantity).toBe(''); expect(vm.rows[0]!.factoryId).toBe('')
    expect(api.createTubeOrder).not.toHaveBeenCalled(); wrapper.unmount()
  })
  it('超时后锁定原请求，回查未找到时也只使用原内容重试', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    vi.mocked(api.createTubeOrder).mockRejectedValueOnce(new AxiosError('超时', 'ECONNABORTED'))
    await vm.save()
    const first = JSON.parse(JSON.stringify(vi.mocked(api.createTubeOrder).mock.calls[0]![0])) as TubeOrderInput
    expect(vm.pending?.client_request_id).toBe(first.client_request_id)
    expect(JSON.parse(localStorage.getItem(key)!)).toEqual(first)
    expect(api.findTubeOrder).toHaveBeenCalledWith(first.client_request_id)
    await vm.save()
    expect(api.createTubeOrder).toHaveBeenCalledTimes(2)
    expect(vi.mocked(api.createTubeOrder).mock.calls[1]![0]).toEqual(first)
    expect(localStorage.getItem(key)).toBeNull(); expect(vm.pending).toBeNull()
    expect(vm.rows[0]!.quantity).toBe(''); wrapper.unmount()
  })
  it('超时后查到成功单据时不再次POST', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    vi.mocked(api.createTubeOrder).mockImplementationOnce(async payload => {
      vi.mocked(api.findTubeOrder).mockResolvedValue(result(payload))
      throw new AxiosError('超时', 'ECONNABORTED')
    })
    await vm.save()
    expect(api.createTubeOrder).toHaveBeenCalledTimes(1)
    expect(vm.pending).toBeNull(); expect(localStorage.getItem(key)).toBeNull(); wrapper.unmount()
  })
  it('412刷新额度并保留输入，下一次复核生成新编号', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    vi.mocked(api.createTubeOrder).mockRejectedValueOnce(httpError(412))
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...context, source_revision: 'revision-2' })
    await vm.save()
    const first = vi.mocked(api.createTubeOrder).mock.calls[0]![0]
    expect(vm.pending).toBeNull(); expect(localStorage.getItem(key)).toBeNull()
    expect(vm.rows[0]!.quantity).toBe('600'); expect(vm.error).toBe('')
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('重新核对') }))
    await vm.save()
    const next = vi.mocked(api.createTubeOrder).mock.calls[1]![0]
    expect(next.client_request_id).not.toBe(first.client_request_id); expect(next.source_revision).toBe('revision-2')
    wrapper.unmount()
  })
  it('服务端400校验仅显示气泡，不在页面顶部重复展示', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    vi.mocked(api.createTubeOrder).mockRejectedValueOnce(httpError(400))
    await vm.save(); await flushPromises()
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.objectContaining({ message: '状态 400' }))
    expect(vm.error).toBe(''); expect(wrapper.findComponent({ name: 'ElAlert' }).exists()).toBe(false)
    expect(vm.rows[0]!.quantity).toBe('600'); expect(vm.rows[0]!.factoryId).toBe('factory')
    expect(vm.pending).toBeNull(); expect(localStorage.getItem(key)).toBeNull()
    wrapper.unmount()
  })
  it('旧额度响应不覆盖较新响应', async () => {
    const { wrapper, vm } = await mountPage()
    let finish!: (value: TubeSourceContext) => void
    vi.mocked(api.fetchTubeSource).mockReturnValueOnce(new Promise(resolve => { finish = resolve })).mockResolvedValueOnce({ ...context, source_revision: 'latest', rows: [{ ...row, max_quantity: '600' }] })
    const old = vm.loadSource(); await vm.loadSource()
    finish(context); await old
    expect(vm.context?.source_revision).toBe('latest'); expect(vm.rows[0]!.max_quantity).toBe('600')
    wrapper.unmount()
  })
  it('未喷塑半成品自动跳过无库存库区并选中有库存库区', async () => {
    const empty = { ...context, source_kind: 'PUBLIC_SEMI' as const, zone_id: 'semi-empty', rows: [{ ...row, max_quantity: '0' }] }
    const ready = { ...empty, zone_id: 'semi-ready', rows: [{ ...row, max_quantity: '36' }] }
    const { wrapper, vm } = await mountPage()
    vi.mocked(api.fetchTubeSource).mockReset()
    vi.mocked(api.fetchTubeSource).mockResolvedValueOnce(empty).mockResolvedValueOnce(ready)
    vm.requestChange('source', 'PUBLIC_SEMI')
    await flushPromises()
    expect(api.fetchTubeSource).toHaveBeenNthCalledWith(1, { schedule_product_id: 'schedule-product', source_kind: 'PUBLIC_SEMI', zone_id: 'semi-empty' })
    expect(api.fetchTubeSource).toHaveBeenNthCalledWith(2, { schedule_product_id: 'schedule-product', source_kind: 'PUBLIC_SEMI', zone_id: 'semi-ready' })
    expect(vm.zoneId).toBe('semi-ready'); expect(vm.warehouseId).toBe('semi-warehouse-2')
    expect(vm.context?.rows[0]?.max_quantity).toBe('36'); expect(vm.sourceHint).toBe('')
    wrapper.unmount()
  })
  it('所有半成品库区均无库存时明确提示0支', async () => {
    const empty = { ...context, source_kind: 'PUBLIC_SEMI' as const, zone_id: 'semi-empty', rows: [{ ...row, max_quantity: '0' }] }
    const { wrapper, vm } = await mountPage()
    vi.mocked(api.fetchTubeSource).mockReset()
    vi.mocked(api.fetchTubeSource).mockResolvedValue(empty)
    vm.requestChange('source', 'PUBLIC_SEMI')
    await flushPromises()
    expect(vm.sourceHint).toContain('均为 0 支')
    wrapper.unmount()
  })
  it('刷新恢复待核对请求及原库区所属仓库，自动回查不自动再写', async () => {
    const payload: TubeOrderInput = { client_request_id: 'existing-request', source_revision: 'old-revision', schedule_product_id: 'schedule-product', source_kind: 'RAW_PIPE', zone_id: 'zone-other', planned_dispatch_date: '2026-09-29', expected_return_date: '2026-10-14', remark: '', lines: [{ component_identity: 'front', quantity: '600', factory_id: 'factory' }] }
    localStorage.setItem(key, JSON.stringify(payload))
    const { wrapper, vm } = await mountPage()
    expect(vm.pending).toEqual(payload); expect(vm.warehouseId).toBe('other'); expect(vm.zoneId).toBe('zone-other')
    expect(api.createTubeOrder).not.toHaveBeenCalled(); expect(api.findTubeOrder).toHaveBeenCalledWith('existing-request')
    wrapper.unmount()
  })
  it('不覆盖其他页面留下的未确认请求', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    localStorage.setItem(key, 'existing-record')
    await vm.save()
    expect(api.createTubeOrder).not.toHaveBeenCalled()
    expect(localStorage.getItem(key)).toBe('existing-record')
    wrapper.unmount()
  })
  it('损坏的本地待核对记录阻止新写入并给出错误', async () => {
    localStorage.setItem(key, JSON.stringify({ client_request_id: 'existing', lines: [{ quantity: 600 }] }))
    const { wrapper, vm } = await mountPage()
    expect(vm.error).toContain('待核对请求记录无法读取')
    await vm.save(); expect(api.createTubeOrder).not.toHaveBeenCalled()
    expect(localStorage.getItem(key)).not.toBeNull()
    wrapper.unmount()
  })
})

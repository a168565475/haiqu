import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/internalReceipts'
import type { InternalReceiptResult, MetalReceiptLine, MetalReceiptPayload, MetalReceiptPreview, ReceiptPayload } from '@/types/internalReceipt'
import MetalInternalReceiptView from './MetalInternalReceiptView.vue'

const access = vi.hoisted(() => ({ allowed: true }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: { schedule_product_id: 'plan-1', plan_category: 'METAL' } }), useRouter: () => ({ push: vi.fn(), back: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 'actor', is_superuser: false }, hasPermission: () => access.allowed }) }))
vi.mock('@/api/internalReceipts', () => ({ fetchMetalReceiptPreview: vi.fn(), confirmInternalReceipt: vi.fn(), findInternalReceipt: vi.fn() }))
vi.mock('element-plus', async original => ({ ...await original<typeof import('element-plus')>(), ElMessage: { closeAll: vi.fn(), warning: vi.fn(), success: vi.fn() } }))

const pendingKey = 'internal-receipt-pending:plan-1:METAL'
const line: MetalReceiptLine = {
  bom_line_id: 'front', component_identity: 'front-id', component_key: 'front-key', usage: '2', stage: '金工完成',
  specification: '圆管Φ22', attributes: { part_name: '前腿管', category: '型材', material: 'Q195', color: '本色', unit_name: '支', tube_thickness: '0.8', cutting_length_mm: 650 },
  required: '200', received: '10', can_receive: '80',
  metal_processing: {
    basis_ready: true, blockers: [], as_of: '2026-09-29', issued: '200', reported_minimum: '100', dispatched: '0', reserved: '10',
    first_output_limit: '100', current_remaining: '80', can_receive: '80', future_blockers: [],
    operations: [{ name: '切管', quantity: '120.0000', work_item_id: 'work-cut', operation_id: 'cut', scheme_id: 'scheme', scheme_revision: 2 }, { name: '弯管', quantity: '100', work_item_id: 'work-bend', operation_id: 'bend', scheme_id: 'scheme', scheme_revision: 2 }],
    schemes: [{ id: 'scheme', scheme_number: 'GJ-actual', version: 2, status: 'APPROVED', effective_from: '2026-09-28', effective_to: null }],
  },
}
function anotherLine(id: string, name: string): MetalReceiptLine {
  const copy = structuredClone(line)
  return { ...copy, bom_line_id: id, component_identity: `${id}-id`, attributes: { ...copy.attributes, part_name: name } }
}
const preview: MetalReceiptPreview = {
  schedule_product_id: 'plan-1', plan_category: 'METAL', etag: '"revision-1"', production_order: 'SC-actual',
  order_number: 'DD-actual', schedule_number: 'PC-actual', product: '真实测试产品', product_number: 'CP-actual', item_number: 'HT-actual',
  product_unit: '把', product_color: '黑色', order_quantity: '100', actor: '当前仓管', receipt_date: '2026-09-29', excluded: [],
  zones: [{ id: 'zone-1', warehouse_id: 'warehouse-1', warehouse: '半成品仓', name: 'A区' }, { id: 'zone-2', warehouse_id: 'warehouse-2', warehouse: '备用仓', name: 'B区' }],
  lines: [line, anotherLine('rear', '后腿管'), anotherLine('arm', '扶手管')],
  metal_processing: { as_of: '2026-09-29', blockers: [], future_blockers: [] },
}
const result: InternalReceiptResult = { receipt_id: 'receipt-real', receipt_number: 'RK-real-response', record_ids: ['record-real'], status: 'PENDING', replayed: false }
const httpError = (status: number) => Object.assign(new AxiosError('接口错误'), { response: { status, data: { error: { message: `状态 ${status}` } } } })
interface ViewModel {
  rows: Array<MetalReceiptLine & { quantity: string }>; remark: string; dialog: string; error: string
  preview: MetalReceiptPreview | null; warehouseId: string; zoneId: string
  pending: { payload: MetalReceiptPayload; etag: string } | null
  confirmReceipt: () => void; save: () => Promise<void>; reset: () => void; load: (preserve?: boolean) => Promise<void>
}
const wrappers: ReturnType<typeof mount>[] = []
async function mountPage() {
  const wrapper = mount(MetalInternalReceiptView, {
    global: { plugins: [ElementPlus], stubs: { AppWindowDialog: { props: ['modelValue', 'title'], template: '<div v-if="modelValue" :aria-label="title"><slot /><slot name="footer" /></div>' } } },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return { wrapper, vm: wrapper.vm as unknown as ViewModel }
}

beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear(); access.allowed = true
  vi.mocked(api.fetchMetalReceiptPreview).mockResolvedValue(structuredClone(preview))
  vi.mocked(api.confirmInternalReceipt).mockResolvedValue(structuredClone(result))
  vi.mocked(api.findInternalReceipt).mockRejectedValue(httpError(404))
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('金工半成品入库', () => {
  it('15列无勾选，先确认正数行，空白和0不提交', async () => {
    const { wrapper, vm } = await mountPage()
    expect(wrapper.findAll('.d1-lines th')).toHaveLength(15)
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
    vm.confirmReceipt(); expect(vm.dialog).toBe('')
    vm.rows[0]!.quantity = '0'; vm.confirmReceipt(); expect(vm.dialog).toBe('')
    vm.rows[2]!.quantity = '20'; vm.confirmReceipt(); expect(vm.dialog).toBe('confirm')
    expect(api.confirmInternalReceipt).not.toHaveBeenCalled()
    await vm.save()
    expect(api.confirmInternalReceipt).toHaveBeenCalledWith(expect.objectContaining({ lines: [{ bom_line_id: 'arm', quantity: '20' }], plan_category: 'METAL' }), '"revision-1"')
    expect(ElMessage.success).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('RK-real-response') }))
    expect(vm.rows.every(row => row.quantity === '')).toBe(true)
  })

  it.each(['-1', '1.5', '1e2', 'NaN', 'Infinity', '9007199254740992', '一百'])('阻止非法支数 %s，校验只出气泡', async value => {
    const { vm } = await mountPage(); vm.rows[0]!.quantity = value
    vm.confirmReceipt(); expect(vm.dialog).toBe(''); expect(vm.error).toBe('')
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('整数支数') }))
    expect(api.confirmInternalReceipt).not.toHaveBeenCalled()
  })

  it('使用后端包含未来约束的额度，不根据当前报工放大上限', async () => {
    const limited = structuredClone(preview)
    limited.lines[0]!.metal_processing.can_receive = '20'
    limited.lines[0]!.metal_processing.future_blockers = ['后续方案仅支持本次20支']
    vi.mocked(api.fetchMetalReceiptPreview).mockResolvedValue(limited)
    const { vm } = await mountPage(); vm.rows[0]!.quantity = '21'; vm.confirmReceipt()
    expect(vm.dialog).toBe(''); expect(ElMessage.warning).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('最多可入 20 支') }))
    vm.rows[0]!.quantity = '20'; vm.confirmReceipt(); expect(vm.dialog).toBe('confirm')
  })

  it('真实报工0和依据缺失分别展示，禁用输入不显示支后缀', async () => {
    const mixed = structuredClone(preview)
    mixed.lines[1]!.metal_processing = { ...mixed.lines[1]!.metal_processing, basis_ready: false, blockers: ['没有已批准方案'], reported_minimum: null, first_output_limit: null, can_receive: '0' }
    mixed.lines[2]!.metal_processing = { ...mixed.lines[2]!.metal_processing, reported_minimum: '0', can_receive: '0' }
    vi.mocked(api.fetchMetalReceiptPreview).mockResolvedValue(mixed)
    const { wrapper } = await mountPage()
    const missing = wrapper.get('[aria-label="后腿管本次入库"]')
    expect(missing.attributes('disabled')).toBeDefined(); expect(missing.attributes('placeholder')).toBe('依据不完整')
    expect(wrapper.get('[aria-label="后腿管最低报工"]').text()).toBe('— 查看原因')
    expect(wrapper.get('[aria-label="扶手管最低报工"]').text()).toBe('0')
    expect(wrapper.findAll('.d1-lines .d1-unit')).toHaveLength(1)
    await wrapper.get('[aria-label="后腿管最低报工"]').trigger('click')
    expect(wrapper.find('.d1-basis').text()).toContain('没有已批准方案')
  })

  it('重填只清数量，保留备注', async () => {
    const { vm } = await mountPage(); vm.rows[0]!.quantity = '20'; vm.remark = '放一楼右侧'
    vm.reset(); expect(vm.rows[0]!.quantity).toBe(''); expect(vm.remark).toBe('放一楼右侧')
  })

  it('仓库变化后未重新选库区不能提交', async () => {
    const { vm } = await mountPage(); vm.rows[0]!.quantity = '20'; vm.warehouseId = 'warehouse-2'
    vm.confirmReceipt(); expect(vm.dialog).toBe(''); expect(api.confirmInternalReceipt).not.toHaveBeenCalled()
  })

  it('服务端400只显示气泡，保留输入且清除待核对记录', async () => {
    const { wrapper, vm } = await mountPage(); vm.rows[0]!.quantity = '20'
    vi.mocked(api.confirmInternalReceipt).mockRejectedValueOnce(httpError(400))
    await vm.save(); await flushPromises()
    expect(vm.error).toBe(''); expect(wrapper.findComponent({ name: 'ElAlert' }).exists()).toBe(false)
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.objectContaining({ message: '状态 400' }))
    expect(vm.rows[0]!.quantity).toBe('20'); expect(vm.pending).toBeNull(); expect(sessionStorage.getItem(pendingKey)).toBeNull()
  })

  it('412刷新真实额度，保留填写，超出新额度不能再次提交', async () => {
    const { vm } = await mountPage(); vm.rows[0]!.quantity = '20'; vm.remark = '保留说明'
    vi.mocked(api.confirmInternalReceipt).mockRejectedValueOnce(httpError(412))
    const changed = structuredClone(preview); changed.etag = '"revision-2"'; changed.lines[0]!.metal_processing.can_receive = '10'
    vi.mocked(api.fetchMetalReceiptPreview).mockResolvedValue(changed)
    await vm.save()
    const first = vi.mocked(api.confirmInternalReceipt).mock.calls[0]![0]
    expect(vm.pending).toBeNull(); expect(vm.error).toBe(''); expect(vm.rows[0]!.quantity).toBe('20'); expect(vm.remark).toBe('保留说明')
    vm.confirmReceipt(); expect(vm.dialog).toBe(''); expect(api.confirmInternalReceipt).toHaveBeenCalledTimes(1)
    vm.rows[0]!.quantity = '10'; await vm.save()
    const next = vi.mocked(api.confirmInternalReceipt).mock.calls[1]!
    expect(next[0].request_id).not.toBe(first.request_id); expect(next[1]).toBe('"revision-2"')
  })

  it('旧预览响应不会覆盖较新额度', async () => {
    const { vm } = await mountPage()
    let finish!: (data: MetalReceiptPreview) => void
    vi.mocked(api.fetchMetalReceiptPreview).mockReturnValueOnce(new Promise(resolve => { finish = resolve })).mockResolvedValueOnce({ ...preview, etag: 'latest' })
    const old = vm.load(); await vm.load(); finish(preview); await old
    expect(vm.preview?.etag).toBe('latest')
  })

  it('超时回查成功不再POST，仅按真实入库结果清理原请求', async () => {
    const { vm } = await mountPage(); vm.rows[0]!.quantity = '20'
    vi.mocked(api.confirmInternalReceipt).mockRejectedValueOnce(new AxiosError('超时', 'ECONNABORTED'))
    vi.mocked(api.findInternalReceipt).mockResolvedValue(result)
    await vm.save()
    expect(api.confirmInternalReceipt).toHaveBeenCalledTimes(1); expect(api.findInternalReceipt).toHaveBeenCalledTimes(1)
    expect(vm.pending).toBeNull(); expect(sessionStorage.getItem(pendingKey)).toBeNull()
  })

  it('超时回查404保留原请求，用户核对时只用原payload和etag重试', async () => {
    const { vm } = await mountPage(); vm.rows[0]!.quantity = '20'; vm.remark = '原说明'
    vi.mocked(api.confirmInternalReceipt).mockRejectedValueOnce(new AxiosError('超时', 'ECONNABORTED'))
    await vm.save()
    const original = JSON.parse(JSON.stringify(vi.mocked(api.confirmInternalReceipt).mock.calls[0])) as [ReceiptPayload, string]
    expect(vm.pending?.payload.request_id).toBe(original[0].request_id); expect(sessionStorage.getItem(pendingKey)).not.toBeNull()
    vm.rows[0]!.quantity = '60'; vm.remark = '不可覆盖原请求'
    await vm.save()
    expect(vi.mocked(api.confirmInternalReceipt).mock.calls[1]).toEqual(original)
    expect(vm.pending).toBeNull()
  })

  it('恢复旧金工页记录，保留原日期备注库区且启动仅回查', async () => {
    const payload: ReceiptPayload = { request_id: 'original-request', schedule_product_id: 'plan-1', plan_category: 'METAL', zone_id: 'zone-2', receipt_date: '2026-09-28', remark: '旧备注', lines: [{ bom_line_id: 'front', quantity: '20' }] }
    sessionStorage.setItem(pendingKey, JSON.stringify({ payload, etag: 'original-etag' }))
    const { vm } = await mountPage()
    expect(vm.pending?.payload).toEqual(payload); expect(vm.zoneId).toBe('zone-2'); expect(vm.warehouseId).toBe('warehouse-2')
    expect(vm.remark).toBe('旧备注'); expect(vm.rows[0]!.quantity).toBe('20')
    expect(api.findInternalReceipt).toHaveBeenCalledWith('original-request'); expect(api.confirmInternalReceipt).not.toHaveBeenCalled()
  })

  it('兼容旧页数字型数量，保留原payload并回查已成功请求', async () => {
    const payload: MetalReceiptPayload = { request_id: 'old-number-request', schedule_product_id: 'plan-1', plan_category: 'METAL', zone_id: 'zone-1', receipt_date: '2026-09-28', remark: '', lines: [{ bom_line_id: 'front', quantity: 20 }] }
    sessionStorage.setItem(pendingKey, JSON.stringify({ payload, etag: 'old-etag' }))
    const { vm } = await mountPage()
    expect(vm.error).not.toContain('无法读取'); expect(vm.pending?.payload).toEqual(payload)
    expect(vm.rows[0]!.quantity).toBe('20'); expect(api.confirmInternalReceipt).not.toHaveBeenCalled()
    vi.mocked(api.findInternalReceipt).mockResolvedValue(result)
    await vm.save()
    expect(api.confirmInternalReceipt).not.toHaveBeenCalled(); expect(sessionStorage.getItem(pendingKey)).toBeNull()
  })

  it.each([400, 403, 404])('恢复时先回查404，再收到POST %s仍保留原请求，不当作确定未保存', async status => {
    const { vm } = await mountPage(); vm.rows[0]!.quantity = '20'
    vi.mocked(api.confirmInternalReceipt).mockRejectedValueOnce(new AxiosError('超时', 'ECONNABORTED'))
    await vm.save()
    const original = sessionStorage.getItem(pendingKey)
    vi.mocked(api.confirmInternalReceipt).mockRejectedValueOnce(httpError(status))
    await vm.save()
    expect(sessionStorage.getItem(pendingKey)).toBe(original)
    expect(vm.pending).not.toBeNull(); expect(vm.error).toContain('原提交结果仍待核对')
    expect(vi.mocked(api.confirmInternalReceipt).mock.calls[1]).toEqual(vi.mocked(api.confirmInternalReceipt).mock.calls[0])
  })

  it('409同请求内容冲突保留原编号，不把不同内容的回查结果当作本次成功', async () => {
    const { vm } = await mountPage(); vm.rows[0]!.quantity = '20'
    vi.mocked(api.confirmInternalReceipt).mockRejectedValueOnce(httpError(409))
    vi.mocked(api.findInternalReceipt).mockResolvedValue(result)
    await vm.save()
    expect(vm.pending).not.toBeNull(); expect(sessionStorage.getItem(pendingKey)).not.toBeNull()
    expect(api.findInternalReceipt).not.toHaveBeenCalled(); expect(ElMessage.success).not.toHaveBeenCalled()
    expect(vm.error).toContain('保存内容与本次内容不一致')
    await vm.save()
    expect(api.findInternalReceipt).not.toHaveBeenCalled(); expect(api.confirmInternalReceipt).toHaveBeenCalledTimes(1)
    const restored = await mountPage()
    expect(restored.vm.error).toContain('保存内容与本次内容不一致')
    expect(api.findInternalReceipt).not.toHaveBeenCalled(); expect(ElMessage.success).not.toHaveBeenCalled()
  })

  it('损坏的原请求不删除、不覆盖，也不发起新入库', async () => {
    sessionStorage.setItem(pendingKey, '{broken')
    const { vm } = await mountPage(); await vm.save()
    expect(vm.error).toContain('待核对请求记录无法读取'); expect(sessionStorage.getItem(pendingKey)).toBe('{broken')
    expect(api.confirmInternalReceipt).not.toHaveBeenCalled()
  })

  it('缺少新版契约时明确阻断，不使用旧额度代替加工依据', async () => {
    const legacy = { ...preview, metal_processing: undefined } as unknown as MetalReceiptPreview
    vi.mocked(api.fetchMetalReceiptPreview).mockResolvedValue(legacy)
    const { vm } = await mountPage(); await vm.save()
    expect(vm.error).toContain('尚未启用新版金工入库'); expect(vm.preview).toBeNull(); expect(api.confirmInternalReceipt).not.toHaveBeenCalled()
  })

  it('整体未来方案阻断时不能确认入库，无权限时不加载资料', async () => {
    const future = structuredClone(preview); future.metal_processing.future_blockers = ['后续方案不能覆盖本次入库']
    vi.mocked(api.fetchMetalReceiptPreview).mockResolvedValue(future)
    const { vm } = await mountPage(); vm.rows[0]!.quantity = '20'; vm.confirmReceipt()
    expect(vm.dialog).toBe(''); expect(api.confirmInternalReceipt).not.toHaveBeenCalled()
    vi.mocked(api.fetchMetalReceiptPreview).mockClear(); access.allowed = false
    const denied = await mountPage()
    expect(denied.wrapper.text()).toContain('没有半成品入库权限'); expect(api.fetchMetalReceiptPreview).not.toHaveBeenCalled()
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { reactive } from 'vue'
import { Cell, DatePicker } from 'vant'
import SemiReceiptPage from './semi-receipt.vue'
import type { PendingSemiReceipt, SemiReceiptCategory, SemiReceiptPreview, SemiReceiptResult } from '@/types/semiReceipts'

const mocks = vi.hoisted(() => ({
  route: { query: {} as Record<string, string> }, push: vi.fn(),
  auth: { user: { id: 1 }, generation: 1, hasPermission: vi.fn(), refresh: vi.fn() },
  guards: {} as Record<string, (to: { path: string }) => Promise<boolean>>,
  preview: vi.fn(), create: vi.fn(), find: vi.fn(),
}))
vi.mock('vue-router', () => ({ useRoute: () => mocks.route, useRouter: () => ({ push: mocks.push }),
  onBeforeRouteLeave: (guard: typeof mocks.guards[string]) => { mocks.guards.leave = guard },
  onBeforeRouteUpdate: (guard: typeof mocks.guards[string]) => { mocks.guards.update = guard },
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocks.auth }))
vi.mock('@/utils/requestId', () => ({ createRequestId: () => '77777777-7777-4777-8777-777777777777' }))
vi.mock('@/components/WorkPage.vue', () => ({ default: { template: '<main><slot /><slot name="footer" /></main>' } }))
vi.mock('@/api/semiReceipts', () => ({ fetchSemiReceiptPreview: mocks.preview, createSemiReceipt: mocks.create, findSemiReceipt: mocks.find }))
vi.mock('vant', async original => ({ ...await original<typeof import('vant')>(), showDialog: vi.fn().mockResolvedValue('confirm') }))
const planId = '11111111-1111-4111-8111-111111111111'
const zoneId = '22222222-2222-4222-8222-222222222222'
const lineId = '33333333-3333-4333-8333-333333333333'
const secondLineId = '44444444-4444-4444-8444-444444444444'
const saved: SemiReceiptResult = { receipt_id: '55555555-5555-4555-8555-555555555555', receipt_number: 'SEMI-TEST', status: 'PENDING', replayed: false, record_ids: [] }
function fixture(category: SemiReceiptCategory = 'METAL'): SemiReceiptPreview {
  const metal = { basis_ready: true, blockers: [], future_blockers: [], as_of: '2026-11-02 12:00', issued: '80', reported_minimum: '60', dispatched: '5', reserved: '5', first_output_limit: '60', current_remaining: '30', can_receive: '30',
    operations: [{ name: '弯管', quantity: '60', work_item_id: 'work', operation_id: 'operation', scheme_id: 'scheme', scheme_revision: 1 }], schemes: [] }
  return { schedule_product_id: planId, plan_category: category, etag: '"semi-one"', production_order: 'TASK-TEST', product: '测试产品', order_quantity: '100', actor: '申请人', receipt_date: '2026-11-02', excluded: ['排除部位'],
    zones: [{ id: zoneId, warehouse: '半成品一仓', name: '一区' }, { id: '66666666-6666-4666-8666-666666666666', warehouse: '半成品一仓', name: '二区' }],
    lines: [{ bom_line_id: lineId, component_key: 'one', usage: '2', stage: category === 'METAL' ? '未喷塑' : '车缝完成', required: '100.0000', received: '20.0000', can_receive: '30.0000',
      attributes: { part_name: '部位甲', material: '测试材料', color: '蓝色', unit_name: category === 'METAL' ? '支' : '套', specification: '测试规格' }, ...(category === 'METAL' ? { metal_processing: structuredClone(metal) } : {}) },
    { bom_line_id: secondLineId, component_key: 'two', usage: '1', stage: '完成', required: '100', received: '0', can_receive: '50', attributes: { part_name: '部位乙', material: '', color: '', unit_name: category === 'METAL' ? '支' : '套' }, ...(category === 'METAL' ? { metal_processing: { ...structuredClone(metal), can_receive: '50', current_remaining: '50' } } : {}) }],
    ...(category === 'METAL' ? { processing_state: '未喷塑', metal_processing: { blockers: [], future_blockers: [], as_of: '2026-11-02 12:00' } } : {}) }
}
const storageKey = (category = 'METAL', id = 1) => `internal-receipt-pending:${planId}:${category}:user:${id}`
function pendingValue(quantity: string | number = '10'): PendingSemiReceipt { return { etag: '"original-etag"', payload: { request_id: '77777777-7777-4777-8777-777777777777', schedule_product_id: planId, plan_category: 'METAL', zone_id: zoneId, receipt_date: '2020-01-02', remark: '原备注', lines: [{ bom_line_id: lineId, quantity }] } } }
let wrapper: VueWrapper | undefined
function cleanup() { for (const category of ['METAL', 'SEWING']) for (const key of [storageKey(category), storageKey(category, 2), `internal-receipt-pending:${planId}:${category}`]) sessionStorage.removeItem(key) }
async function openPage() { wrapper = mount(SemiReceiptPage); await flushPromises(); return wrapper }
async function button(view: VueWrapper, text: string) { const target = view.findAll('button').find(item => item.text() === text); expect(target).toBeTruthy(); await target!.trigger('click'); await flushPromises() }
async function selectZone(view: VueWrapper, name = '一区') { await view.get('.semi-zone').trigger('click'); await flushPromises(); await view.findAllComponents(Cell).find(cell => cell.props('title') === name)!.trigger('click'); await flushPromises() }
async function prepare() { const view = await openPage(); await view.get(`[data-line-id="${lineId}"] input`).setValue('10'); await selectZone(view); return view }
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] }); vi.resetAllMocks(); cleanup()
  mocks.route = reactive({ query: { schedule_product_id: planId, plan_category: 'METAL' } })
  mocks.auth = reactive({ user: { id: 1 }, generation: 1, hasPermission: vi.fn().mockReturnValue(true), refresh: vi.fn().mockResolvedValue(undefined) })
  mocks.preview.mockResolvedValue(fixture()); mocks.create.mockResolvedValue(saved); mocks.find.mockResolvedValue({ ...saved, replayed: true })
})
afterEach(async () => { wrapper?.unmount(); wrapper = undefined; try { await vi.runOnlyPendingTimersAsync() } finally { vi.useRealTimers(); vi.restoreAllMocks(); cleanup() } })

describe('手机金工和车缝半成品入库', () => {
  it.each(['METAL', 'SEWING'] as const)('%s按真实预览列出全部候选、单位和属性，产品折叠且唯一仓默认选中', async category => {
    mocks.route.query.plan_category = category; mocks.preview.mockResolvedValue(fixture(category))
    const view = await openPage()
    expect(mocks.preview).toHaveBeenCalledWith(planId, category, expect.any(AbortSignal))
    expect(view.findAll('.semi-material')).toHaveLength(2)
    expect(view.get('.semi-product').attributes('open')).toBeUndefined()
    expect(view.get('.semi-warehouse').text()).toContain('半成品一仓')
    expect(view.get('.semi-zone').text()).toContain('请选择库区')
    expect(view.text()).toContain('测试材料 · 蓝色'); expect(view.text()).toContain('测试规格')
    expect(view.text()).toContain('排除部位'); expect(view.text()).toContain(category === 'METAL' ? '累计已提交' : '累计入库/待确认')
    expect(view.get('.semi-quantity .van-field__button').text()).toBe(category === 'METAL' ? '支' : '套')
    if (category === 'METAL') { expect(view.text()).toContain('加工状态：未喷塑'); expect(view.text()).toContain('弯管：已报 60 支') }
    else { expect(view.text()).not.toContain('原料支持数量'); expect(view.text()).toContain('累计数量含外发同阶段入库和厂内入库') }
  })
  it('库区只列当前仓库，改仓清空库区，不会自动选择入库位置', async () => {
    const data = fixture(); data.zones.push({ id: '88888888-8888-4888-8888-888888888888', warehouse: '半成品二仓', name: '独立区' }); mocks.preview.mockResolvedValue(data)
    const view = await openPage()
    expect(view.get('.semi-zone').attributes('disabled')).toBeDefined()
    await view.get('.semi-warehouse').trigger('click'); await flushPromises()
    await view.findAllComponents(Cell).find(cell => cell.props('title') === '半成品一仓')!.trigger('click'); await flushPromises()
    await selectZone(view)
    await view.get('.semi-warehouse').trigger('click'); await flushPromises()
    await view.findAllComponents(Cell).find(cell => cell.props('title') === '半成品二仓')!.trigger('click'); await flushPromises()
    expect(view.get('.semi-zone').text()).toContain('请选择库区')
    await view.get('.semi-zone').trigger('click'); await flushPromises()
    const zoneTitles = view.findAllComponents(Cell).map(cell => cell.props('title'))
    expect(zoneTitles).toContain('独立区'); expect(zoneTitles).not.toContain('一区')
  })
  it.each(['METAL', 'SEWING'] as const)('%s仅提交正数量行、日期和真实库区，带原ETag，成功显示待仓库确认', async category => {
    mocks.route.query.plan_category = category; mocks.preview.mockResolvedValue(fixture(category))
    const view = await prepare(); await view.get(`[data-line-id="${secondLineId}"] input`).setValue('0')
    await button(view, '提交入库申请')
    expect(mocks.auth.refresh).toHaveBeenCalledWith(true)
    expect(mocks.create).toHaveBeenCalledExactlyOnceWith({ request_id: '77777777-7777-4777-8777-777777777777', schedule_product_id: planId, plan_category: category, zone_id: zoneId, receipt_date: '2026-11-02', remark: '', lines: [{ bom_line_id: lineId, quantity: '10' }] }, '"semi-one"')
    expect(mocks.find).not.toHaveBeenCalled(); expect(view.text()).toContain('申请已提交，待仓库确认'); expect(view.text()).toContain('SEMI-TEST')
    expect(sessionStorage.getItem(storageKey(category))).toBeNull()
  })
  it('整段拒绝小数、正负号、科学记数和粘贴非法字符，整数仍校验超量/14位/全空', async () => {
    const view = await prepare(), input = view.get<HTMLInputElement>(`[data-line-id="${lineId}"] input`)
    for (const invalid of ['1e3', '1.5', '-1', '+1', '中文', '１２']) { await input.setValue(invalid); expect(input.element.value).toBe('10') }
    await input.setValue('31'); await button(view, '提交入库申请'); expect(view.text()).toContain('本次最多可入 30 支')
    await input.setValue('100000000000000'); await button(view, '提交入库申请'); expect(view.text()).toContain('最多 14 位有效数字')
    await input.setValue(''); await button(view, '提交入库申请'); expect(view.text()).toContain('至少填写一项大于 0')
    expect(mocks.create).not.toHaveBeenCalled(); expect(sessionStorage.getItem(storageKey())).toBeNull()
  })
  it('日期取消不回写，闰年跨月确认保存纯日期', async () => {
    const view = await prepare(); await view.get('.semi-date').trigger('click'); await flushPromises()
    let picker = view.getComponent(DatePicker)
    picker.vm.$emit('update:modelValue', ['2028', '01', '31']); await flushPromises(); await picker.get('.van-picker__cancel').trigger('click'); await flushPromises()
    expect(view.get('.semi-date').text()).toContain('2026-11-02')
    await view.get('.semi-date').trigger('click'); await flushPromises(); picker = view.getComponent(DatePicker)
    picker.vm.$emit('update:modelValue', ['2028', '01', '31']); await flushPromises(); picker.vm.$emit('update:modelValue', ['2028', '02', '31']); await flushPromises()
    expect(picker.props('modelValue')).toEqual(['2028', '02', '29'])
    await picker.get('.van-picker__confirm').trigger('click'); await flushPromises(); await button(view, '提交入库申请')
    expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({ receipt_date: '2028-02-29' }), '"semi-one"')
  })
  it('双击只提交一次，未知结果锁定，刷新后即使预览失败仍先按原编号查单', async () => {
    let reject!: (error: Error) => void
    mocks.create.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail }))
    const view = await prepare(); await button(view, '提交入库申请'); await view.get('.van-button--primary').trigger('click'); await flushPromises()
    expect(mocks.create).toHaveBeenCalledTimes(1); expect(view.get('.semi-quantity input').attributes('disabled')).toBeDefined(); expect(view.get('.semi-date').attributes('disabled')).toBeDefined()
    const raw = sessionStorage.getItem(storageKey())!
    reject(new Error('网络中断')); await flushPromises()
    expect(await mocks.guards.leave!({ path: '/' })).toBe(false); expect(await mocks.guards.leave!({ path: '/login' })).toBe(true); expect(await mocks.guards.leave!({ path: '/auth/waiting-role' })).toBe(true)
    view.unmount(); wrapper = undefined; mocks.preview.mockRejectedValueOnce(new Error('计划已暂停'))
    const reopened = await openPage(); expect(reopened.text()).toContain('计划已暂停'); expect(sessionStorage.getItem(storageKey())).toBe(raw)
    await button(reopened, '核对本次提交'); expect(mocks.find).toHaveBeenCalledWith(JSON.parse(raw).payload.request_id); expect(mocks.create).toHaveBeenCalledTimes(1)
    expect(reopened.text()).toContain('SEMI-TEST'); expect(sessionStorage.getItem(storageKey())).toBeNull()
  })
  it.each([400, 403, 404])('原单查不到才原样重试，旧ERP数字quantity保留；重试返回%s仍保留pending', async status => {
    const original = pendingValue(10), raw = JSON.stringify(original); sessionStorage.setItem(storageKey(), raw)
    mocks.find.mockRejectedValueOnce({ response: { status: 404 } }); mocks.create.mockRejectedValueOnce({ response: { status } })
    const view = await openPage(); await button(view, '核对本次提交')
    expect(mocks.create).toHaveBeenCalledExactlyOnceWith(original.payload, original.etag); expect(sessionStorage.getItem(storageKey())).toBe(raw)
    expect(view.text()).toContain('本次提交结果尚未确认'); expect(view.get('.semi-quantity input').attributes('disabled')).toBeDefined()
  })
  it('查单403不重发POST，当前无add但仍有view时只允许查回原单', async () => {
    sessionStorage.setItem(storageKey(), JSON.stringify(pendingValue())); mocks.auth.hasPermission.mockImplementation(permission => permission.endsWith('view_internalsemifinishedreceipt'))
    mocks.find.mockRejectedValueOnce({ response: { status: 403 } })
    const view = await openPage(); await button(view, '核对本次提交')
    expect(mocks.create).not.toHaveBeenCalled(); expect(sessionStorage.getItem(storageKey())).not.toBeNull()
    await button(view, '核对本次提交'); expect(view.text()).toContain('SEMI-TEST'); expect(mocks.create).not.toHaveBeenCalled()
  })
  it('409冲突永久保留原内容并锁定，重新打开也不自动重试', async () => {
    mocks.create.mockRejectedValueOnce({ response: { status: 409, data: { error: { code: 'CONFLICT' } } } })
    const view = await prepare(); await button(view, '提交入库申请')
    const raw = sessionStorage.getItem(storageKey())!, stored = JSON.parse(raw)
    expect(stored.conflict).toBe(true); expect(stored.payload.lines).toEqual([{ bom_line_id: lineId, quantity: '10' }]); expect(view.text()).toContain('原请求编号存在内容冲突')
    view.unmount(); wrapper = undefined; const reopened = await openPage(); await button(reopened, '核对本次提交')
    expect(mocks.find).not.toHaveBeenCalled(); expect(mocks.create).toHaveBeenCalledTimes(1); expect(sessionStorage.getItem(storageKey())).toBe(raw)
  })
  it.each([412, 428, 'deleted'] as const)('%s明确拒绝后清理原请求，必须刷新额度才可新提交', async status => {
    mocks.create.mockRejectedValueOnce({ response: { status: status === 'deleted' ? 409 : status, data: { error: { code: status === 'deleted' ? 'RECEIPT_REQUEST_DELETED' : 'STALE' } } } })
    const view = await prepare(); await button(view, '提交入库申请')
    expect(sessionStorage.getItem(storageKey())).toBeNull(); expect(view.text()).toContain('请刷新入库额度后重新核对')
    await button(view, '提交入库申请'); expect(mocks.create).toHaveBeenCalledTimes(1)
    const changed = fixture(); changed.etag = '"semi-two"'; changed.lines[0]!.can_receive = '5'; mocks.preview.mockResolvedValueOnce(changed)
    await button(view, '刷新入库额度'); await button(view, '提交入库申请'); expect(view.text()).toContain('本次最多可入 5 支'); expect(mocks.create).toHaveBeenCalledTimes(1)
  })
  it('提交前身份变化不发送；发送后旧身份响应不能显示成功或消费原记录', async () => {
    const view = await prepare(); mocks.auth.refresh.mockImplementationOnce(async () => { mocks.auth.generation++ }); await button(view, '提交入库申请'); expect(mocks.create).not.toHaveBeenCalled()
    view.unmount(); wrapper = undefined
    let resolve!: (value: SemiReceiptResult) => void; mocks.create.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const fresh = await prepare(); await button(fresh, '提交入库申请'); const raw = sessionStorage.getItem(storageKey())
    mocks.auth.user.id = 2; mocks.auth.generation++; resolve(saved); await flushPromises()
    expect(fresh.text()).not.toContain('申请已提交，待仓库确认'); expect(sessionStorage.getItem(storageKey())).toBe(raw); expect(sessionStorage.getItem(storageKey('METAL', 2))).toBeNull()
  })
  it('身份核验暂时失败不抹掉原请求，也不永久封死再次核对', async () => {
    const raw = JSON.stringify(pendingValue()); sessionStorage.setItem(storageKey(), raw); mocks.auth.refresh.mockRejectedValueOnce(new Error('身份查询网络中断'))
    const view = await openPage(); await button(view, '核对本次提交'); expect(view.text()).toContain('身份查询网络中断'); expect(mocks.find).not.toHaveBeenCalled(); expect(sessionStorage.getItem(storageKey())).toBe(raw)
    await button(view, '核对本次提交'); expect(view.text()).toContain('SEMI-TEST')
  })
  it('页面卸载后迟到成功不消费原请求，下次仍可查询', async () => {
    let resolve!: (value: SemiReceiptResult) => void; mocks.create.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const view = await prepare(); await button(view, '提交入库申请'); const raw = sessionStorage.getItem(storageKey())
    view.unmount(); wrapper = undefined; resolve(saved); await flushPromises(); expect(sessionStorage.getItem(storageKey())).toBe(raw)
  })
  it.each(['损坏', '历史无主', '写入失败', '记录变化'] as const)('本地%s保留记录并禁止发送', async reason => {
    if (reason === '损坏') sessionStorage.setItem(storageKey(), '{broken')
    if (reason === '历史无主') sessionStorage.setItem(`internal-receipt-pending:${planId}:METAL`, '')
    if (reason === '记录变化') sessionStorage.setItem(storageKey(), JSON.stringify(pendingValue()))
    const view = reason === '写入失败' ? await prepare() : await openPage()
    if (reason === '写入失败') { vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage denied') }); await button(view, '提交入库申请'); expect(view.text()).toContain('storage denied') }
    if (reason === '记录变化') { sessionStorage.setItem(storageKey(), 'changed'); await button(view, '核对本次提交'); expect(view.text()).toContain('记录已变化'); expect(sessionStorage.getItem(storageKey())).toBe('changed') }
    if (reason === '损坏') expect(sessionStorage.getItem(storageKey())).toBe('{broken')
    if (reason === '历史无主') expect(sessionStorage.getItem(`internal-receipt-pending:${planId}:METAL`)).toBe('')
    expect(mocks.create).not.toHaveBeenCalled(); expect(mocks.find).not.toHaveBeenCalled()
  })
  it('成功后清理失败仍显示真实原单号，不能再次提交', async () => {
    const view = await prepare(); vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('blocked') }); await button(view, '提交入库申请')
    expect(view.text()).toContain('SEMI-TEST'); expect(view.text()).toContain('申请已提交，待仓库确认'); expect(view.text()).toContain('原请求记录未能清理'); expect(view.findAll('button').some(item => item.text() === '提交入库申请')).toBe(false)
  })
  it.each(['CUTTING', '缺少计划', '无view', '无add', '未来阻断', '依据未就绪'] as const)('%s保留真实阻断，不扩展来源和权限', async reason => {
    if (reason === 'CUTTING') mocks.route.query.plan_category = 'CUTTING'
    if (reason === '缺少计划') mocks.route.query.schedule_product_id = 'invalid'
    if (reason === '无view' || reason === '无add') mocks.auth.hasPermission.mockImplementation(permission => !permission.includes(reason === '无view' ? 'view_' : 'add_'))
    if (reason === '未来阻断') { const data = fixture(); data.metal_processing!.future_blockers = ['存在未来生效加工依据']; mocks.preview.mockResolvedValue(data) }
    if (reason === '依据未就绪') { const data = fixture(); for (const line of data.lines) { line.metal_processing!.basis_ready = false; line.metal_processing!.blockers = ['尚未完成必需工序报工'] }; mocks.preview.mockResolvedValue(data) }
    const view = await openPage()
    expect(view.text()).toContain(reason === 'CUTTING' || reason === '缺少计划' ? '入库来源参数无效' : reason === '无view' || reason === '无add' ? '没有半成品入库查看和申请权限' : reason === '未来阻断' ? '存在未来生效加工依据' : '尚未完成必需工序报工')
    expect(mocks.create).not.toHaveBeenCalled(); if (reason !== '未来阻断' && reason !== '依据未就绪') expect(mocks.preview).not.toHaveBeenCalled()
  })
  it('切换无效来源终止旧加载，迟到预览不能恢复旧表单', async () => {
    let resolve!: (value: SemiReceiptPreview) => void; mocks.preview.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const view = await openPage(); expect(view.find('.semi-loading').exists()).toBe(true)
    mocks.route.query = { schedule_product_id: 'invalid', plan_category: 'SEWING' }; await flushPromises(); expect(view.find('.semi-loading').exists()).toBe(false)
    resolve(fixture()); await flushPromises(); expect(view.find('.semi-product').exists()).toBe(false); expect(view.text()).toContain('入库来源参数无效')
  })
})

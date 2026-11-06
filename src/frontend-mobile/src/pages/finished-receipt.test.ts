import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { reactive } from 'vue'
import { Cell, DatePicker, Search } from 'vant'
import FinishedReceiptPage from './finished-receipt.vue'
import type { FinishedReceiptOptions, FinishedReceiptPreview, FinishedReceiptResult } from '@/types/finishedReceipts'

const mocks = vi.hoisted(() => ({
  route: { query: {} as Record<string, string> }, push: vi.fn(),
  auth: { user: { id: 1 }, generation: 1, hasPermission: vi.fn(), refresh: vi.fn() },
  guards: {} as Record<string, (to: { path: string }) => Promise<boolean>>,
  preview: vi.fn(), options: vi.fn(), create: vi.fn(),
}))
vi.mock('vue-router', () => ({ useRoute: () => mocks.route, useRouter: () => ({ push: mocks.push }),
  onBeforeRouteLeave: (guard: typeof mocks.guards[string]) => { mocks.guards.leave = guard },
  onBeforeRouteUpdate: (guard: typeof mocks.guards[string]) => { mocks.guards.update = guard },
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocks.auth }))
vi.mock('@/utils/requestId', () => ({ createRequestId: () => '77777777-7777-4777-8777-777777777777' }))
vi.mock('@/components/WorkPage.vue', () => ({ default: { template: '<main><slot /><slot name="footer" /></main>' } }))
vi.mock('@/api/finishedReceipts', () => ({ fetchFinishedReceiptPreview: mocks.preview, fetchFinishedReceiptOptions: mocks.options, createFinishedReceipt: mocks.create }))
vi.mock('vant', async original => ({ ...await original<typeof import('vant')>(), showDialog: vi.fn().mockResolvedValue('confirm') }))

const planId = '11111111-1111-4111-8111-111111111111'
const locationId = '22222222-2222-4222-8222-222222222222'
const storageKey = (id = 1) => `assembly-receipt:${planId}:user:${id}`
const preview: FinishedReceiptPreview = {
  schedule_product_id: planId, schedule_number: 'PLAN-TEST', production_task_product_id: 'product', task_number: 'TASK-TEST', order_number: 'ORDER-TEST',
  product_number: 'P-TEST', product_name: '测试成品', item_number: 'ITEM-TEST', specification: '测试规格', actual_color: '订单蓝色', unit_id: 'unit', unit_name: '件',
  order_quantity: 100, tolerance_percent: '5', maximum_receivable: 80, received_total: 20, remaining_receivable: 60, order_maximum: 105, reported_minimum: 80,
  reporting_basis_ready: true, reporting_operations: [{ work_item_id: 'work', operation: '装配', reported_quantity: '80' }], receipt_date: '2026-11-02', actor_name: '申请员工', etag: '"preview-one"',
}
const options: FinishedReceiptOptions = {
  warehouses: [{ id: 'warehouse', warehouse_number: 'W-01', warehouse_name: '成品仓', warehouse_type: 'FINISHED', status: 'ACTIVE' }],
  zones: [{ id: 'zone', warehouse: 'warehouse', zone_name: '一区', status: 'ACTIVE' }, { id: 'zone-two', warehouse: 'warehouse', zone_name: '二区', status: 'ACTIVE' }],
  locations: [{ id: locationId, zone: 'zone', warehouse_id: 'warehouse', location_number: 'A-01', status: 'ACTIVE', remaining_box_slots: 5 },
    { id: '33333333-3333-4333-8333-333333333333', zone: 'zone-two', warehouse_id: 'warehouse', location_number: 'B-01', status: 'ACTIVE', remaining_box_slots: null }],
}
const saved: FinishedReceiptResult = { id: 'receipt', receipt_number: 'FG-TEST', status: 'PENDING', replayed: false }
let wrapper: VueWrapper | undefined
function cleanup() { for (const key of [storageKey(), storageKey(2), `assembly-receipt:${planId}`]) sessionStorage.removeItem(key) }
async function openPage() { wrapper = mount(FinishedReceiptPage); await flushPromises(); return wrapper }
async function button(view: VueWrapper, text: string) {
  const target = view.findAll('button').find(item => item.text() === text)
  expect(target).toBeTruthy(); await target!.trigger('click'); await flushPromises()
}
async function selectPlace(view: VueWrapper) {
  await view.get('.receipt-location').trigger('click'); await flushPromises()
  await view.findAllComponents(Cell).find(cell => cell.props('title') === '一区')!.trigger('click'); await flushPromises()
  await view.findAllComponents(Cell).find(cell => cell.props('title') === 'A-01')!.trigger('click'); await flushPromises()
}
async function prepare() { const view = await openPage(); await view.get('.receipt-quantity input').setValue('10'); await selectPlace(view); return view }
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] }); vi.resetAllMocks(); cleanup()
  mocks.route = reactive({ query: { schedule_product_id: planId } })
  mocks.auth = reactive({ user: { id: 1 }, generation: 1, hasPermission: vi.fn().mockReturnValue(true), refresh: vi.fn().mockResolvedValue(undefined) })
  mocks.preview.mockResolvedValue(structuredClone(preview)); mocks.options.mockResolvedValue(structuredClone(options)); mocks.create.mockResolvedValue(saved)
})
afterEach(async () => {
  wrapper?.unmount(); wrapper = undefined
  try { await vi.runOnlyPendingTimersAsync() }
  finally { vi.useRealTimers(); vi.restoreAllMocks(); cleanup() }
})

describe('手机装配成品入库', () => {
  it('产品默认折叠、唯一仓自动选中，先库区再搜索库位，颜色只读', async () => {
    const view = await openPage()
    expect(view.get('details.receipt-product').attributes('open')).toBeUndefined()
    expect(view.get('.receipt-warehouse').text()).toContain('成品仓')
    expect(view.get('.receipt-location').text()).toContain('请选择库区、库位')
    expect(view.text()).toContain('累计已提交')
    expect(view.get('.receipt-product-details').text()).toContain('订单蓝色')
    expect(view.find('input[value="订单蓝色"]').exists()).toBe(false)
    await view.get('.receipt-location').trigger('click'); await flushPromises()
    expect(view.findAllComponents(Cell).some(cell => cell.props('title') === 'A-01')).toBe(false)
    await view.findAllComponents(Cell).find(cell => cell.props('title') === '一区')!.trigger('click'); await flushPromises()
    expect(view.findAllComponents(Cell).some(cell => cell.props('title') === 'B-01')).toBe(false)
    await view.getComponent(Search).get('input').setValue('missing')
    expect(document.body.textContent).toContain('没有匹配的可用库位')
    await view.getComponent(Search).get('input').setValue('A-01')
    await view.findAllComponents(Cell).find(cell => cell.props('title') === 'A-01')!.trigger('click'); await flushPromises()
    expect(view.get('.receipt-location').text()).toContain('一区 · A-01')
  })
  it('仅创建待仓库确认原单，发送日期、订单颜色、ETag和请求编号，成功清理原请求', async () => {
    const view = await prepare()
    await button(view, '提交入库申请')
    expect(mocks.auth.refresh).toHaveBeenCalledWith(true)
    expect(mocks.create).toHaveBeenCalledWith({ request_id: '77777777-7777-4777-8777-777777777777', schedule_product_id: planId, location_id: locationId,
      receipt_date: '2026-11-02', received_quantity: 10, quantity_per_box: null, actual_color: '订单蓝色', remark: '' }, '"preview-one"')
    expect(view.text()).toContain('申请已提交，待仓库确认')
    expect(view.text()).toContain('FG-TEST')
    expect(sessionStorage.getItem(storageKey())).toBeNull()
    await button(view, '返回生产入库')
    expect(mocks.push).toHaveBeenLastCalledWith('/production-receipt')
  })
  it('整段拒绝非法数量，正整数仍受剩余额度和包装箱位约束', async () => {
    const view = await prepare()
    const input = view.get<HTMLInputElement>('.receipt-quantity input')
    for (const invalid of ['1e3', '-10', '+10', '1.5', '中文', '１２']) { await input.setValue(invalid); expect(input.element.value).toBe('10') }
    await input.setValue('61'); await button(view, '提交入库申请')
    expect(view.text()).toContain('剩余可入库 60 件，不能超量')
    await input.setValue('10'); await view.get('.receipt-pack input').setValue('1'); await button(view, '提交入库申请')
    expect(view.text()).toContain('本次需要 10 箱位')
    expect(mocks.create).not.toHaveBeenCalled(); expect(sessionStorage.getItem(storageKey())).toBeNull()
  })
  it('日期取消不回写，闰年跨月确认后保存纯日期', async () => {
    const view = await prepare()
    await view.get('.receipt-date').trigger('click'); await flushPromises()
    let picker = view.getComponent(DatePicker)
    picker.vm.$emit('update:modelValue', ['2028', '01', '31']); await flushPromises()
    await picker.get('.van-picker__cancel').trigger('click'); await flushPromises()
    expect(view.get('.receipt-date').text()).toContain('2026-11-02')
    await view.get('.receipt-date').trigger('click'); await flushPromises()
    picker = view.getComponent(DatePicker)
    picker.vm.$emit('update:modelValue', ['2028', '01', '31']); await flushPromises()
    picker.vm.$emit('update:modelValue', ['2028', '02', '31']); await flushPromises()
    expect(picker.props('modelValue')).toEqual(['2028', '02', '29'])
    await picker.get('.van-picker__confirm').trigger('click'); await flushPromises()
    await button(view, '提交入库申请')
    expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({ receipt_date: '2028-02-29' }), '"preview-one"')
  })
  it('双击只发送一次，未知结果锁定并在刷新后用原编号和内容核对', async () => {
    let reject!: (error: Error) => void
    mocks.create.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail }))
    const view = await prepare()
    await button(view, '提交入库申请')
    expect(view.get('.van-button--primary').attributes('disabled')).toBeDefined()
    await view.get('.van-button--primary').trigger('click'); await flushPromises()
    expect(mocks.create).toHaveBeenCalledTimes(1)
    expect(view.get('.receipt-quantity input').attributes('disabled')).toBeDefined()
    const original = mocks.create.mock.calls[0]
    const raw = sessionStorage.getItem(storageKey())!
    reject(new Error('timeout')); await flushPromises()
    expect(await mocks.guards.leave!({ path: '/' })).toBe(false)
    expect(await mocks.guards.leave!({ path: '/login' })).toBe(true)
    expect(await mocks.guards.leave!({ path: '/auth/waiting-role' })).toBe(true)
    view.unmount(); wrapper = undefined
    mocks.preview.mockRejectedValueOnce(new Error('计划已暂停'))
    const reopened = await openPage()
    expect(reopened.text()).toContain('计划已暂停')
    expect(sessionStorage.getItem(storageKey())).toBe(raw)
    await button(reopened, '核对本次提交')
    expect(mocks.create.mock.calls[1]).toEqual(original)
    expect(reopened.text()).toContain('FG-TEST')
  })
  it('额度冲突清除被拒绝的请求并要求刷新，不能自动用旧ETag重建', async () => {
    mocks.create.mockRejectedValueOnce({ response: { status: 412 } })
    const view = await prepare()
    await button(view, '提交入库申请')
    expect(sessionStorage.getItem(storageKey())).toBeNull()
    expect(view.findAll('button').find(item => item.text() === '提交入库申请')!.attributes('disabled')).toBeDefined()
    expect(view.text()).toContain('请刷新额度后重新核对')
    mocks.preview.mockResolvedValueOnce({ ...preview, etag: '"preview-two"', remaining_receivable: 5 })
    await button(view, '刷新入库额度')
    await button(view, '提交入库申请')
    expect(view.text()).toContain('剩余可入库 5 件，不能超量')
    expect(mocks.create).toHaveBeenCalledTimes(1)
  })
  it.each(['损坏记录', '历史无主记录', '写入失败'])('%s时保留证据且不提交', async (reason) => {
    if (reason === '损坏记录') sessionStorage.setItem(storageKey(), '{broken')
    if (reason === '历史无主记录') sessionStorage.setItem(`assembly-receipt:${planId}`, 'legacy')
    const view = reason === '写入失败' ? await prepare() : await openPage()
    if (reason === '写入失败') {
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage denied') })
      await button(view, '提交入库申请')
      expect(view.text()).toContain('storage denied')
    }
    else expect(view.text()).toContain('保留并暂停提交')
    expect(mocks.create).not.toHaveBeenCalled()
    if (reason === '损坏记录') expect(sessionStorage.getItem(storageKey())).toBe('{broken')
    if (reason === '历史无主记录') expect(sessionStorage.getItem(`assembly-receipt:${planId}`)).toBe('legacy')
  })
  it('提交前身份切换不发送，旧身份响应也不能消费原请求或显示成功', async () => {
    const view = await prepare()
    mocks.auth.refresh.mockImplementationOnce(async () => { mocks.auth.generation++ })
    await button(view, '提交入库申请')
    expect(mocks.create).not.toHaveBeenCalled()
    view.unmount(); wrapper = undefined
    let resolve!: (value: FinishedReceiptResult) => void
    mocks.create.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const fresh = await prepare()
    await button(fresh, '提交入库申请')
    const raw = sessionStorage.getItem(storageKey())
    mocks.auth.user.id = 2; mocks.auth.generation++
    resolve(saved); await flushPromises()
    expect(fresh.text()).not.toContain('申请已提交，待仓库确认')
    expect(sessionStorage.getItem(storageKey())).toBe(raw)
    expect(sessionStorage.getItem(storageKey(2))).toBeNull()
  })
  it('成功后清理失败仍显示原单号和真实成功，禁止重复申请', async () => {
    const view = await prepare()
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('blocked') })
    await button(view, '提交入库申请')
    expect(view.text()).toContain('申请已提交，待仓库确认')
    expect(view.text()).toContain('FG-TEST')
    expect(view.text()).toContain('原请求记录未能清理')
    expect(view.findAll('button').some(item => item.text() === '提交入库申请')).toBe(false)
    expect(sessionStorage.getItem(storageKey())).not.toBeNull()
  })
  it('切换来源终止旧加载状态，旧预览迟到不能覆盖新页面', async () => {
    let resolve!: (value: FinishedReceiptPreview) => void
    mocks.preview.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const view = await openPage()
    expect(view.find('.receipt-loading').exists()).toBe(true)
    mocks.route.query = { schedule_product_id: 'invalid' }
    await flushPromises()
    expect(view.find('.receipt-loading').exists()).toBe(false)
    expect(view.text()).toContain('入库来源参数无效')
    resolve(preview); await flushPromises()
    expect(view.find('.receipt-product').exists()).toBe(false)
    expect(mocks.create).not.toHaveBeenCalled()
  })
  it.each(['缺少来源', '无权限', '未报工'])('%s明确阻断，不发起写入', async (reason) => {
    if (reason === '缺少来源') mocks.route.query = {}
    if (reason === '无权限') mocks.auth.hasPermission.mockReturnValue(false)
    if (reason === '未报工') mocks.preview.mockResolvedValueOnce({ ...preview, reported_minimum: 0, remaining_receivable: 0, maximum_receivable: 0 })
    const view = await openPage()
    expect(view.text()).toContain(reason === '缺少来源' ? '入库来源参数无效' : reason === '无权限' ? '没有成品入库申请权限' : '尚未全部报工')
    if (reason !== '未报工') expect(mocks.preview).not.toHaveBeenCalled()
    expect(mocks.create).not.toHaveBeenCalled()
  })
})

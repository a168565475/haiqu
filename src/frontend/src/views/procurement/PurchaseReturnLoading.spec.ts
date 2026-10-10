import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/purchaseReturns'
import PurchaseReturnListView from './PurchaseReturnListView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), useRoute: () => ({ query: {} }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/purchaseReturns', () => ({ fetchPurchaseReturns: vi.fn(), fetchReturnStats: vi.fn(), fetchReturnOptions: vi.fn(), fetchPurchaseReturn: vi.fn(), advancePurchaseReturn: vi.fn() }))
const record = { id: 'return-1', return_number: 'TH01', status: 'QUALITY_GENERATED', lines: [{ id: 'line-1', quantity: '1' }] }
const stats = { total: 3, QUALITY_GENERATED: 1, PROCUREMENT_CONFIRMED: 1, COMPLETED: 1 }
const mount = () => shallowMount(PurchaseReturnListView, { global: { plugins: [ElementPlus] } })
type View = { loading: boolean; rows: Array<{id:string}>; statsReady: boolean; statsError: string; rowsError: string; stats: typeof stats; loadRows: () => Promise<void>; loadStats: () => Promise<void>; search: () => void; changeTab: (status: string) => void; sort: () => void; advance: (row: never) => Promise<void>; answerConfirmation: (value: boolean) => void; confirmationVisible: boolean }
describe('退货明细分区加载', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.fetchPurchaseReturns).mockResolvedValue({ data: [record], meta: { total: 1 } } as never)
    vi.mocked(api.fetchReturnStats).mockResolvedValue(stats)
    vi.mocked(api.fetchReturnOptions).mockResolvedValue({ suppliers: [] })
    vi.mocked(api.fetchPurchaseReturn).mockResolvedValue({ data: record, etag: 'frozen-version' } as never)
  })
  it('慢统计不阻塞列表，统计失败不清空列表并可单独重试', async () => {
    let fail!: (error: Error) => void
    vi.mocked(api.fetchReturnStats).mockReturnValueOnce(new Promise((_, reject) => { fail = reject }))
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    expect(vm.loading).toBe(false); expect(vm.rows).toHaveLength(1); expect(vm.statsReady).toBe(false)
    fail(new Error('统计失败')); await flushPromises()
    expect(vm.rows).toHaveLength(1); expect(vm.statsError).not.toBe(''); expect(vm.rowsError).toBe('')
    await vm.loadStats(); expect(vm.statsReady).toBe(true); expect(vm.stats.total).toBe(3)
    expect(api.fetchPurchaseReturns).toHaveBeenCalledTimes(1); wrapper.unmount()
  })
  it('页签、排序和分页不重复取同范围统计，关键词搜索更新统计', async () => {
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    vm.changeTab('COMPLETED'); await flushPromises(); vm.sort(); await flushPromises(); await vm.loadRows()
    expect(api.fetchReturnStats).toHaveBeenCalledTimes(1)
    vm.search(); await flushPromises(); expect(api.fetchReturnStats).toHaveBeenCalledTimes(2)
    expect(api.fetchReturnOptions).toHaveBeenCalledTimes(1); wrapper.unmount()
  })
  it('未提交的关键词在切换页签时也更新统计范围', async () => {
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as View & { filters: { q: string } }
    vm.filters.q = ' TH02 '; vm.changeTab('COMPLETED'); await flushPromises()
    expect(api.fetchReturnStats).toHaveBeenLastCalledWith({ q: 'TH02', purchase_order_id: undefined, supplier_id: undefined })
    expect(api.fetchReturnStats).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
  it('统计单独重试沿用列表范围，不使用尚未提交的关键词', async () => {
    vi.mocked(api.fetchReturnStats).mockRejectedValueOnce(new Error('统计失败'))
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as View & { filters: { q: string } }
    vm.filters.q = '尚未提交'; await vm.loadStats()
    expect(api.fetchReturnStats).toHaveBeenLastCalledWith({ q: undefined, purchase_order_id: undefined, supplier_id: undefined })
    expect(api.fetchPurchaseReturns).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
  it('列表失败不覆盖成功统计，旧统计和卸载回包不能覆盖新结果', async () => {
    vi.mocked(api.fetchPurchaseReturns).mockRejectedValueOnce(new Error('列表失败'))
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    expect(vm.statsReady).toBe(true); expect(vm.stats.total).toBe(3); expect(vm.rowsError).not.toBe('')
    let finish!: (value: typeof stats) => void
    vi.mocked(api.fetchReturnStats).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const old = vm.loadStats(); await vm.loadStats(); finish({ ...stats, total: 99 }); await old
    expect(vm.stats.total).toBe(3)
    vi.mocked(api.fetchReturnStats).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const pending = vm.loadStats(); wrapper.unmount(); finish({ ...stats, total: 88 }); await pending
    expect(vm.stats.total).toBe(3)
  })
  it('确认操作保留冻结版本，取消不写入，接受后刷新列表与统计', async () => {
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    const cancelled = vm.advance(record as never); await flushPromises(); expect(vm.confirmationVisible).toBe(true)
    vm.answerConfirmation(false); await cancelled; expect(api.advancePurchaseReturn).not.toHaveBeenCalled()
    const confirmed = vm.advance(record as never); await flushPromises(); vm.answerConfirmation(true); await confirmed
    expect(api.advancePurchaseReturn).toHaveBeenCalledWith('return-1', 'confirm', 'frozen-version')
    expect(api.fetchPurchaseReturns).toHaveBeenCalledTimes(2); expect(api.fetchReturnStats).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
})

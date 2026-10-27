import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/purchaseReturns'
import PurchaseReturnListView from './PurchaseReturnListView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), useRoute: () => ({ name: 'purchase-return-records', query: { purchase_order_id: 'order-context', from: 'inbound' } }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/purchaseReturns', () => ({ fetchPurchaseReturns: vi.fn(), fetchReturnOptions: vi.fn(), fetchPurchaseReturn: vi.fn(), advancePurchaseReturn: vi.fn() }))
const record = { id: 'return-1', return_number: 'TH01', status: 'QUALITY_GENERATED', lines: [{ id: 'line-1', quantity: '1' }] }
const wrappers: ReturnType<typeof shallowMount>[] = []
const mount = () => {
  const wrapper = shallowMount(PurchaseReturnListView, { global: { plugins: [ElementPlus], stubs: { ElInput: false } } })
  wrappers.push(wrapper)
  return wrapper
}
type View = {
  loading: boolean; rows: Array<{ id: string }>; rowsError: string; optionsError: string; page: number
  filters: { q: string; supplier: string; status: string }
  loadRows: () => Promise<void>; loadOptions: () => Promise<void>
  advance: (row: never) => Promise<void>; answerConfirmation: (value: boolean) => void; confirmationVisible: boolean
}
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })
describe('退货明细加载与搜索', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.fetchPurchaseReturns).mockResolvedValue({ data: [record], meta: { total: 1 } } as never)
    vi.mocked(api.fetchReturnOptions).mockResolvedValue({ suppliers: [] })
    vi.mocked(api.fetchPurchaseReturn).mockResolvedValue({ data: record, etag: 'frozen-version' } as never)
  })
  it('供应商选项失败不清空列表，并可单独重试', async () => {
    vi.mocked(api.fetchReturnOptions).mockRejectedValueOnce(new Error('选项失败'))
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    expect(vm.loading).toBe(false); expect(vm.rows).toHaveLength(1)
    expect(vm.optionsError).not.toBe(''); expect(vm.rowsError).toBe('')
    await vm.loadOptions(); expect(vm.optionsError).toBe('')
    expect(api.fetchPurchaseReturns).toHaveBeenCalledTimes(1)
  })
  it('列表失败可重试，旧请求和卸载后的回包不能覆盖新结果', async () => {
    vi.mocked(api.fetchPurchaseReturns).mockRejectedValueOnce(new Error('列表失败'))
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    expect(vm.rowsError).not.toBe(''); await vm.loadRows(); expect(vm.rowsError).toBe('')
    let finish!: (value: Awaited<ReturnType<typeof api.fetchPurchaseReturns>>) => void
    vi.mocked(api.fetchPurchaseReturns).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const old = vm.loadRows(); await vm.loadRows()
    finish({ data: [{ ...record, id: 'old' }], meta: { total: 1 } } as never); await old
    expect(vm.rows[0]?.id).toBe('return-1')
    vi.mocked(api.fetchPurchaseReturns).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const pending = vm.loadRows(); wrapper.unmount()
    finish({ data: [], meta: { total: 0 } } as never); await pending
    expect(vm.rows[0]?.id).toBe('return-1')
  })
  it('回车重置分页、保留筛选和采购单上下文，中文输入确认不误查', async () => {
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    Object.assign(vm.filters, { supplier: 'supplier-1', status: 'COMPLETED' }); vm.page = 2
    await wrapper.get('input').setValue('  TH02  '); vi.mocked(api.fetchPurchaseReturns).mockClear()
    await wrapper.get('input').trigger('keydown', { key: 'Enter', isComposing: true })
    await wrapper.get('input').trigger('keydown', { key: 'Enter', keyCode: 229 })
    expect(api.fetchPurchaseReturns).not.toHaveBeenCalled()
    await wrapper.get('input').trigger('keydown', { key: 'Enter' }); await flushPromises()
    expect(api.fetchPurchaseReturns).toHaveBeenCalledTimes(1)
    expect(api.fetchPurchaseReturns).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'TH02', page: 1, supplier_id: 'supplier-1', status: 'COMPLETED', purchase_order_id: 'order-context' }))
  })
  it('放大镜与清空立即查询第一页，并保留其他筛选', async () => {
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    Object.assign(vm.filters, { supplier: 'supplier-1', status: 'COMPLETED' }); vm.page = 2
    await wrapper.get('input').setValue('  供应商  '); vi.mocked(api.fetchPurchaseReturns).mockClear()
    await wrapper.get('button[aria-label="搜索退货列表"]').trigger('click'); await flushPromises()
    expect(api.fetchPurchaseReturns).toHaveBeenLastCalledWith(expect.objectContaining({ q: '供应商', page: 1, supplier_id: 'supplier-1', status: 'COMPLETED' }))
    vm.page = 2
    await wrapper.get('.return-search').trigger('mouseenter')
    await wrapper.get('.el-input__clear').trigger('click'); await flushPromises()
    expect(api.fetchPurchaseReturns).toHaveBeenCalledTimes(2)
    expect(api.fetchPurchaseReturns).toHaveBeenLastCalledWith(expect.objectContaining({ q: undefined, page: 1, supplier_id: 'supplier-1', status: 'COMPLETED', purchase_order_id: 'order-context' }))
  })
  it('确认操作保留冻结版本，取消不写入，接受后刷新列表', async () => {
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    const cancelled = vm.advance(record as never); await flushPromises(); expect(vm.confirmationVisible).toBe(true)
    vm.answerConfirmation(false); await cancelled; expect(api.advancePurchaseReturn).not.toHaveBeenCalled()
    const confirmed = vm.advance(record as never); await flushPromises(); vm.answerConfirmation(true); await confirmed
    expect(api.advancePurchaseReturn).toHaveBeenCalledWith('return-1', 'confirm', 'frozen-version')
    expect(api.fetchPurchaseReturns).toHaveBeenCalledTimes(2)
  })
})

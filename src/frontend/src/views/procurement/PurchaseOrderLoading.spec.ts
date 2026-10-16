import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/purchaseOrders'
import PurchaseOrderListView from './PurchaseOrderListView.vue'
import PurchaseOrderConfirmView from './PurchaseOrderConfirmView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), useRoute: () => ({ params: { id: 'order-1' } }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/purchaseOrders', async original => ({ ...await original<typeof import('@/api/purchaseOrders')>(),
  fetchPurchaseOrders: vi.fn(), fetchPurchaseOrderFilterOptions: vi.fn(),
  fetchVersionedPurchaseOrder: vi.fn(), fetchPurchaseOrderOptions: vi.fn(), fetchPurchaseOrderSupplierOptions: vi.fn(),
  updatePurchaseOrder: vi.fn(),
}))
const order = { id: 'order-1', order_number: 'CGDD2026091601', status: 'DRAFT', currency_code: 'CNY', is_mailed: false, lines: [], product_summary: [] }
const options = { suppliers: [] }
const mount = (component: typeof PurchaseOrderListView | typeof PurchaseOrderConfirmView) => shallowMount(component, { global: { plugins: [ElementPlus] } })

describe('采购订单分区加载', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchPurchaseOrders).mockResolvedValue({ data: [], meta: { total: 4, total_pages: 1 } } as never)
    vi.mocked(api.fetchPurchaseOrderFilterOptions).mockResolvedValue({ ...options, production_tasks: [], statuses: [] })
    vi.mocked(api.fetchVersionedPurchaseOrder).mockResolvedValue({ data: order, etag: 'version-1' } as never)
    vi.mocked(api.fetchPurchaseOrderOptions).mockResolvedValue(options as never)
    vi.mocked(api.fetchPurchaseOrderSupplierOptions).mockResolvedValue(options)
  })
  it('搜索支持回车、放大镜和清空，返回第一页并保留采购状态', async () => {
    vi.mocked(api.fetchPurchaseOrders).mockResolvedValue({ data: [], meta: { total: 100, total_pages: 2 } } as never)
    const wrapper = shallowMount(PurchaseOrderListView, { global: { plugins: [ElementPlus], stubs: { ElInput: false } } })
    await flushPromises()
    const status = wrapper.findAllComponents({ name: 'ElSelect' }).find(item => item.attributes('aria-label') === '采购状态筛选')!
    status.vm.$emit('update:modelValue', 'SUBMITTED')
    const pagination = wrapper.getComponent({ name: 'ElPagination' })
    pagination.vm.$emit('update:current-page', 2); pagination.vm.$emit('current-change', 2)
    await flushPromises()
    expect(api.fetchPurchaseOrders).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, status: 'SUBMITTED' }))
    vi.mocked(api.fetchPurchaseOrders).mockClear()
    const input = wrapper.get('input')
    await input.setValue('  CGDD001  ')
    await input.trigger('keydown', { key: 'Enter', isComposing: true })
    expect(api.fetchPurchaseOrders).not.toHaveBeenCalled()
    const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
    input.element.dispatchEvent(enter); await flushPromises()
    expect(enter.defaultPrevented).toBe(true)
    expect(api.fetchPurchaseOrders).toHaveBeenCalledTimes(1)
    expect(api.fetchPurchaseOrders).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'CGDD001', page: 1, status: 'SUBMITTED' }))
    vi.mocked(api.fetchPurchaseOrders).mockClear()
    await input.setValue('  CGDD002  ')
    const button = wrapper.get('button[aria-label="搜索采购订单列表"]')
    expect(button.attributes('type')).toBe('button')
    await button.trigger('click'); await flushPromises()
    expect(api.fetchPurchaseOrders).toHaveBeenCalledTimes(1)
    expect(api.fetchPurchaseOrders).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'CGDD002', page: 1, status: 'SUBMITTED' }))
    vi.mocked(api.fetchPurchaseOrders).mockClear()
    await wrapper.get('.keyword-filter').trigger('mouseenter')
    await wrapper.get('.el-input__clear').trigger('click'); await flushPromises()
    expect(api.fetchPurchaseOrders).toHaveBeenCalledTimes(1)
    expect(api.fetchPurchaseOrders).toHaveBeenLastCalledWith(expect.objectContaining({ q: undefined, page: 1, status: 'SUBMITTED' }))
    wrapper.unmount()
  })
  it('慢筛选不拖住列表，搜索只刷新列表', async () => {
    vi.mocked(api.fetchPurchaseOrderFilterOptions).mockReturnValue(new Promise(() => {}))
    const wrapper = mount(PurchaseOrderListView); await flushPromises()
    const vm = wrapper.vm as unknown as { listReady: boolean; total: number; loading: boolean; search: () => void }
    expect(vm.listReady).toBe(true); expect(vm.total).toBe(4); expect(vm.loading).toBe(false)
    vm.search(); await flushPromises()
    expect(api.fetchPurchaseOrders).toHaveBeenCalledTimes(2)
    expect(api.fetchPurchaseOrderFilterOptions).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
  it('慢供应商不拖住订单显示，期间不能保存', async () => {
    vi.mocked(api.fetchPurchaseOrderOptions).mockReturnValue(new Promise(() => {}))
    vi.mocked(api.fetchPurchaseOrderSupplierOptions).mockReturnValue(new Promise(() => {}))
    const wrapper = mount(PurchaseOrderConfirmView); await flushPromises()
    const vm = wrapper.vm as unknown as { order: typeof order; etag: string; loading: boolean; optionsLoading: boolean; saveChanges: () => Promise<boolean> }
    expect(vm.order?.id).toBe('order-1'); expect(vm.etag).toBe('version-1')
    expect(vm.loading).toBe(false); expect(vm.optionsLoading).toBe(true)
    expect(await vm.saveChanges()).toBe(false); expect(api.updatePurchaseOrder).not.toHaveBeenCalled()
    expect(api.fetchPurchaseOrderOptions).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('供应商失败不隐藏订单，重试不覆盖编辑内容和版本', async () => {
    vi.mocked(api.fetchPurchaseOrderSupplierOptions).mockRejectedValueOnce(new Error('失败'))
    const wrapper = mount(PurchaseOrderConfirmView); await flushPromises()
    const vm = wrapper.vm as unknown as { order: typeof order; etag: string; optionsReady: boolean; optionsError: string; loadOptions: () => Promise<void> }
    expect(vm.order?.id).toBe('order-1'); expect(vm.optionsReady).toBe(false); expect(vm.optionsError).not.toBe('')
    vm.order.is_mailed = true
    await vm.loadOptions()
    expect(vm.optionsReady).toBe(true); expect(vm.optionsError).toBe('')
    expect(vm.order.is_mailed).toBe(true); expect(vm.etag).toBe('version-1')
    expect(api.fetchVersionedPurchaseOrder).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
  it('详情旧请求和卸载后回包不能覆盖当前数据', async () => {
    const wrapper = mount(PurchaseOrderConfirmView); await flushPromises()
    const vm = wrapper.vm as unknown as { loadOrder: () => Promise<void>; loadOptions: () => Promise<void>; order: typeof order | null; etag: string; optionsReady: boolean }
    let finishOrder!: (value: never) => void
    vi.mocked(api.fetchVersionedPurchaseOrder).mockReturnValueOnce(new Promise(resolve => { finishOrder = resolve }))
      .mockResolvedValueOnce({ data: { ...order, id: 'order-2' }, etag: 'version-2' } as never)
    const old = vm.loadOrder(); await vm.loadOrder()
    finishOrder({ data: order, etag: 'version-1' } as never); await old
    expect(vm.order?.id).toBe('order-2'); expect(vm.etag).toBe('version-2')
    let finishOptions!: (value: typeof options) => void
    vi.mocked(api.fetchPurchaseOrderSupplierOptions).mockReturnValueOnce(new Promise(resolve => { finishOptions = resolve }))
    vi.mocked(api.fetchVersionedPurchaseOrder).mockReturnValueOnce(new Promise(resolve => { finishOrder = resolve }))
    const pendingOrder = vm.loadOrder(), pendingOptions = vm.loadOptions()
    wrapper.unmount()
    finishOrder({ data: order, etag: 'late-version' } as never); finishOptions(options)
    await Promise.all([pendingOrder, pendingOptions])
    expect(vm.order).toBeNull(); expect(vm.etag).toBe(''); expect(vm.optionsReady).toBe(false)
  })
})

import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import { AxiosError } from 'axios'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/boms'
import type { VersionedBom } from '@/types/bom'
import * as productionDataApi from '@/api/productionData'
import * as productsApi from '@/api/products'
import InquiryProductDialog from '@/components/inquiries/InquiryProductDialog.vue'
import BomEditorView from './BomEditorView.vue'

const route = reactive({ params: { bomId: 'b1' } })
const router = { push: vi.fn(), replace: vi.fn() }
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => router }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/boms', async original => ({ ...await original<typeof import('@/api/boms')>(), fetchBomForEdit: vi.fn(), syncBomOrderQuantity: vi.fn() }))
vi.mock('@/api/productionData', async original => ({ ...await original<typeof import('@/api/productionData')>(), fetchAllProductionDataRecords: vi.fn().mockResolvedValue([]) }))
vi.mock('@/api/products', async original => ({ ...await original<typeof import('@/api/products')>(), fetchProductOptions: vi.fn() }))

function versioned(id = 'b1', overrides = {}): VersionedBom {
  return { data: {
    id, status: 'PENDING_CONFIRMATION', order_quantity: '1000', current_order_quantity: '1000',
    product_information_confirmed: true, sections: [], configured_field_labels: {},
    is_order_quantity_outdated: false, is_order_product_outdated: false, ...overrides,
  }, etag: `${id}-v1` } as unknown as VersionedBom
}
function deferred<T = VersionedBom>() {
  let resolve!: (result: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise; reject = rejectPromise
  })
  return { promise, resolve, reject }
}
function httpError(status: number) {
  return new AxiosError('加载失败', undefined, undefined, undefined, { status, data: {} } as never)
}
interface Editor {
  bom: VersionedBom['data'] | null
  loading: boolean
  errorMessage: string
  productConfirmVisible: boolean
  loadBom: () => Promise<void>
}
let wrapper: VueWrapper | undefined
function open() {
  wrapper = shallowMount(BomEditorView, { global: {
    plugins: [ElementPlus], renderStubDefaultSlot: true,
    stubs: { ElTableColumn: { template: '<div />' }, ElResult: { template: '<div><slot name="extra" /></div>' }, BomProductConfirmationDialogs: false },
  } })
  return wrapper.vm as unknown as Editor
}
function leave() { wrapper?.unmount(); wrapper = undefined }

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  vi.clearAllMocks()
  route.params.bomId = 'b1'
  vi.mocked(api.fetchBomForEdit).mockReset().mockResolvedValue(versioned())
  vi.mocked(api.syncBomOrderQuantity).mockReset().mockResolvedValue(versioned())
  vi.mocked(productionDataApi.fetchAllProductionDataRecords).mockResolvedValue([])
  vi.mocked(productsApi.fetchProductOptions).mockResolvedValue({ categories: [], units: [], items: [] })
  vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
  vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
  vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
})
afterEach(() => {
  leave()
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('BOM 编辑加载生命周期', () => {
  it('503 后离开页面会清掉等待中的重试，不再发请求', async () => {
    vi.mocked(api.fetchBomForEdit).mockRejectedValueOnce(httpError(503))
    open(); await flushPromises()
    leave()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(api.fetchBomForEdit).toHaveBeenCalledTimes(1)
  })

  it('在途请求离开后会取消请求，迟到成功不能写入或打开产品及数量确认', async () => {
    const pending = deferred()
    vi.mocked(api.fetchBomForEdit).mockReturnValueOnce(pending.promise)
    const vm = open()
    const signal = vi.mocked(api.fetchBomForEdit).mock.calls[0]?.[1]
    leave()
    pending.resolve(versioned('b1', { product_information_confirmed: false, is_order_quantity_outdated: true }))
    await flushPromises()
    expect(vm.bom).toBeNull()
    expect(vm.productConfirmVisible).toBe(false)
    expect(ElMessageBox.confirm).not.toHaveBeenCalled()
    expect(productsApi.fetchProductOptions).not.toHaveBeenCalled()
    expect(signal?.aborted).toBe(true)
  })

  it.each([403, 503])('离开后的迟到 %s 不显示错误也不重试', async status => {
    const pending = deferred()
    vi.mocked(api.fetchBomForEdit).mockReturnValueOnce(pending.promise)
    const vm = open(); leave()
    pending.reject(httpError(status))
    await flushPromises()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(vm.errorMessage).toBe('')
    expect(api.fetchBomForEdit).toHaveBeenCalledTimes(1)
  })

  it('仍在当前 BOM 时按原 750ms 延迟重试，恢复后保留产品核对和数量确认', async () => {
    vi.mocked(api.fetchBomForEdit).mockRejectedValueOnce(httpError(503))
      .mockResolvedValueOnce(versioned('b1', { product_information_confirmed: false, is_order_quantity_outdated: true }))
    const vm = open(); await flushPromises()
    expect(vm.loading).toBe(true)
    await vi.advanceTimersByTimeAsync(749)
    expect(api.fetchBomForEdit).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1); await flushPromises()
    expect(api.fetchBomForEdit).toHaveBeenCalledTimes(2)
    expect(vm.bom?.id).toBe('b1')
    expect(vm.loading).toBe(false)
    expect(wrapper!.findComponent(InquiryProductDialog).props('modelValue')).toBe(true)
    expect(ElMessageBox.confirm).toHaveBeenCalledOnce()
  })

  it('连续暂时失败最多请求四次，错误页允许手工重试恢复', async () => {
    vi.mocked(api.fetchBomForEdit).mockRejectedValue(httpError(503))
    const vm = open(); await flushPromises()
    for (const delay of [750, 1500, 2500]) { await vi.advanceTimersByTimeAsync(delay); await flushPromises() }
    expect(api.fetchBomForEdit).toHaveBeenCalledTimes(4)
    expect(vm.loading).toBe(false)
    expect(vm.errorMessage).toContain('BOM 请求失败')
    vi.mocked(api.fetchBomForEdit).mockResolvedValue(versioned())
    await wrapper!.get('.bom-error-state__retry').trigger('click'); await flushPromises()
    expect(api.fetchBomForEdit).toHaveBeenCalledTimes(5)
    expect(vm.errorMessage).toBe('')
    expect(vm.bom?.id).toBe('b1')
  })

  it('手工刷新取消前一轮等待，不留下额外自动重试', async () => {
    vi.mocked(api.fetchBomForEdit).mockRejectedValueOnce(httpError(503))
    const vm = open(); await flushPromises()
    await vm.loadBom(); await flushPromises()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(api.fetchBomForEdit).toHaveBeenCalledTimes(2)
    expect(vm.loading).toBe(false)
    expect(vm.bom?.id).toBe('b1')
  })

  it.each(['success', 'error'])('手工刷新后旧请求的 %s 不覆盖结果、不提前结束 loading', async outcome => {
    const old = deferred(); const current = deferred()
    vi.mocked(api.fetchBomForEdit).mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    const vm = open()
    const refresh = vm.loadBom()
    if (outcome === 'success') old.resolve(versioned('old', { product_information_confirmed: false, is_order_quantity_outdated: true }))
    else old.reject(httpError(403))
    await flushPromises()
    expect(vm.bom).toBeNull()
    expect(vm.errorMessage).toBe('')
    expect(vm.loading).toBe(true)
    expect(ElMessageBox.confirm).not.toHaveBeenCalled()
    current.resolve(versioned()); await refresh
    expect(vm.bom?.id).toBe('b1')
    expect(vm.loading).toBe(false)
  })

  it('同一组件切换 BOM 会加载新编号，旧响应不能覆盖新 BOM 或打开确认', async () => {
    const old = deferred()
    vi.mocked(api.fetchBomForEdit).mockReturnValueOnce(old.promise).mockResolvedValueOnce(versioned('b2'))
    const vm = open()
    route.params.bomId = 'b2'; await flushPromises()
    expect(vi.mocked(api.fetchBomForEdit).mock.calls.map(call => call[0])).toEqual(['b1', 'b2'])
    expect(vm.bom?.id).toBe('b2')
    old.resolve(versioned('b1', { product_information_confirmed: false, is_order_quantity_outdated: true }))
    await flushPromises()
    expect(vm.bom?.id).toBe('b2')
    expect(vm.productConfirmVisible).toBe(false)
    expect(ElMessageBox.confirm).not.toHaveBeenCalled()
  })

  it('等待重试时切换 BOM，不再请求旧编号', async () => {
    vi.mocked(api.fetchBomForEdit).mockRejectedValueOnce(httpError(503)).mockResolvedValueOnce(versioned('b2'))
    const vm = open(); await flushPromises()
    route.params.bomId = 'b2'; await flushPromises()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(vi.mocked(api.fetchBomForEdit).mock.calls.map(call => call[0])).toEqual(['b1', 'b2'])
    expect(vm.bom?.id).toBe('b2')
  })

  it('编号丢失时使在途请求失效并结束 loading', async () => {
    const pending = deferred()
    vi.mocked(api.fetchBomForEdit).mockReturnValueOnce(pending.promise)
    const vm = open()
    route.params.bomId = ''; await flushPromises()
    pending.resolve(versioned()); await flushPromises()
    expect(api.fetchBomForEdit).toHaveBeenCalledTimes(1)
    expect(vm.bom).toBeNull()
    expect(vm.loading).toBe(false)
    expect(vm.errorMessage).toBe('缺少 BOM 编号。')
  })

  it.each(['leave', 'switch'])('旧数量确认打开后 %s，迟到确认不发送同步', async action => {
    const confirmation = deferred<'confirm'>()
    vi.mocked(ElMessageBox.confirm).mockReturnValueOnce(confirmation.promise as never)
    vi.mocked(api.fetchBomForEdit).mockResolvedValueOnce(versioned('b1', { is_order_quantity_outdated: true }))
      .mockResolvedValueOnce(versioned('b2'))
    open(); await flushPromises()
    expect(ElMessageBox.confirm).toHaveBeenCalledOnce()
    if (action === 'leave') leave()
    else { route.params.bomId = 'b2'; await flushPromises() }
    confirmation.resolve('confirm'); await flushPromises()
    expect(api.syncBomOrderQuantity).not.toHaveBeenCalled()
  })

  it.each(['success', 'error'])('同步已发送后离开，迟到 %s 不写回、不导航也不弹消息', async outcome => {
    const sync = deferred()
    vi.mocked(ElMessageBox.confirm).mockResolvedValueOnce('confirm' as never)
    vi.mocked(api.fetchBomForEdit).mockResolvedValueOnce(versioned('b1', { is_order_quantity_outdated: true }))
    vi.mocked(api.syncBomOrderQuantity).mockReturnValueOnce(sync.promise)
    const vm = open(); await flushPromises()
    expect(api.syncBomOrderQuantity).toHaveBeenCalledWith('b1', 'b1-v1')
    leave()
    if (outcome === 'success') sync.resolve(versioned('b1-new-version'))
    else sync.reject(httpError(403))
    await flushPromises()
    expect(vm.bom?.id).toBe('b1')
    expect(router.replace).not.toHaveBeenCalled()
    expect(ElMessage.success).not.toHaveBeenCalled()
    expect(ElMessage.error).not.toHaveBeenCalled()
  })

  it('同步等待中切换 BOM，旧成功不能覆盖新页面且新页面仍能确认同步', async () => {
    const sync = deferred()
    vi.mocked(ElMessageBox.confirm).mockResolvedValue('confirm' as never)
    vi.mocked(api.fetchBomForEdit)
      .mockResolvedValueOnce(versioned('b1', { is_order_quantity_outdated: true }))
      .mockResolvedValueOnce(versioned('b2', { is_order_quantity_outdated: true }))
    vi.mocked(api.syncBomOrderQuantity).mockReturnValueOnce(sync.promise).mockResolvedValueOnce(versioned('b2'))
    const vm = open(); await flushPromises()
    route.params.bomId = 'b2'; await flushPromises()
    expect(api.syncBomOrderQuantity).toHaveBeenNthCalledWith(2, 'b2', 'b2-v1')
    sync.resolve(versioned('b1-new-version')); await flushPromises()
    expect(vm.bom?.id).toBe('b2')
    expect(router.replace).not.toHaveBeenCalled()
    expect(ElMessage.success).toHaveBeenCalledTimes(1)
  })

  it('切换到已核对 BOM 时关闭上一 BOM 的产品确认状态', async () => {
    vi.mocked(api.fetchBomForEdit).mockResolvedValueOnce(versioned('b1', { product_information_confirmed: false }))
      .mockResolvedValueOnce(versioned('b2'))
    const vm = open(); await flushPromises()
    expect(vm.productConfirmVisible).toBe(true)
    route.params.bomId = 'b2'; await flushPromises()
    expect(vm.bom?.id).toBe('b2')
    expect(vm.productConfirmVisible).toBe(false)
  })

  it('当前同步正常生成新版本时显示成功消息并导航到新 BOM', async () => {
    vi.mocked(ElMessageBox.confirm).mockResolvedValueOnce('confirm' as never)
    vi.mocked(api.fetchBomForEdit)
      .mockResolvedValueOnce(versioned('b1', { status: 'VERIFIED', is_order_quantity_outdated: true }))
      .mockResolvedValueOnce(versioned('b1-new-version'))
    vi.mocked(api.syncBomOrderQuantity).mockResolvedValueOnce(versioned('b1-new-version'))
    router.replace.mockImplementationOnce(async () => { route.params.bomId = 'b1-new-version' })
    const vm = open(); await flushPromises()
    expect(vm.bom?.id).toBe('b1-new-version')
    expect(router.replace).toHaveBeenCalledWith({ name: 'bom-edit', params: { bomId: 'b1-new-version' } })
    expect(ElMessage.success).toHaveBeenCalledOnce()
  })
})

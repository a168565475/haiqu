import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/purchaseOrders'
import PurchaseOrderConfirmView from './PurchaseOrderConfirmView.vue'

vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ params: { id: 'order-1' } }),
}))
vi.mock('@/api/purchaseOrders', async original => ({
  ...await original<typeof import('@/api/purchaseOrders')>(),
  fetchVersionedPurchaseOrder: vi.fn(),
  fetchPurchaseOrderSupplierOptions: vi.fn(),
  updatePurchaseOrder: vi.fn(),
  confirmVersionedPurchaseOrder: vi.fn(),
}))

describe('采购订单确认校验', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchPurchaseOrderSupplierOptions).mockResolvedValue({ suppliers: [] })
    vi.mocked(api.fetchVersionedPurchaseOrder).mockResolvedValue({
      etag: 'version-1',
      data: {
        id: 'order-1',
        order_number: 'CGDD2026091746',
        status: 'DRAFT',
        currency_code: 'CNY',
        is_mailed: false,
        product_summary: [],
        lines: [{
          id: 'line-1', line_number: 1, raw_bar_length_m: '2.96', suggested_bar_count: 96,
          actual_bar_count: 96, actual_purchase_quantity: null, quantity_difference_reason: '',
          supplier_id: 'supplier-1', delivery_date: '2026-10-08', unit_price: null,
          source_unit_text: '米',
        }],
      },
    } as never)
  })

  afterEach(() => vi.restoreAllMocks())

  it('管材填入根数后只提示真正缺少的字段，并在点击确认时弹窗', async () => {
    const alert = vi.spyOn(ElMessageBox, 'alert').mockResolvedValue('confirm' as never)
    const wrapper = shallowMount(PurchaseOrderConfirmView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const vm = wrapper.vm as unknown as { confirmationErrors: string[]; confirmAndContinue: () => Promise<void> }

    expect(vm.confirmationErrors).toEqual(['第 1 行缺少：采购单价'])
    expect(wrapper.find('.review-card').exists()).toBe(false)
    await vm.confirmAndContinue()
    expect(alert).toHaveBeenCalledTimes(1)
    expect(alert.mock.calls[0]?.[1]).toBe('请完善采购信息')
    expect(api.updatePurchaseOrder).not.toHaveBeenCalled()
    expect(api.confirmVersionedPurchaseOrder).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('保存时不回传已经隐藏的历史差异原因', async () => {
    const wrapper = shallowMount(PurchaseOrderConfirmView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const vm = wrapper.vm as unknown as {
      order: { lines: Array<{ quantity_difference_reason: string }> }
      saveChanges: (showSuccess: boolean) => Promise<boolean>
    }
    vm.order.lines[0]!.quantity_difference_reason = '历史记录'
    vi.mocked(api.updatePurchaseOrder).mockResolvedValue({ data: vm.order, etag: 'version-2' } as never)

    expect(await vm.saveChanges(false)).toBe(true)
    const payload = vi.mocked(api.updatePurchaseOrder).mock.calls[0]?.[1]
    expect(payload?.lines[0]).not.toHaveProperty('quantity_difference_reason')
    wrapper.unmount()
  })
})

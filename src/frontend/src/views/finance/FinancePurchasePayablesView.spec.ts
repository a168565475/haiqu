import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { expect, it, vi } from 'vitest'
import FinancePurchasePayablesView from './FinancePurchasePayablesView.vue'
import { fetchPurchasePayable, fetchPurchasePayables, updatePurchasePayablePricing } from '@/api/financePurchasePayables'
import type { PurchasePayable, PurchasePayableLine } from '@/types/financePurchasePayables'

vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: false }, hasPermission: () => true }) }))
vi.mock('@/api/financePurchasePayables', () => ({
  fetchPurchasePayables: vi.fn(), fetchPurchasePayable: vi.fn(), updatePurchasePayablePricing: vi.fn(),
  confirmPurchasePayable: vi.fn(), voidPurchasePayable: vi.fn(),
}))

const billable: PurchasePayableLine = {
  line_id: 'line-1', material: '测试管材', accepted_quantity: '95.0000', settlement_quantity: '95.0000',
  accepted_weight_kg: '95.0000', accepted_unit: 'KG', reference_unit_price: '2.5000', unit_price: null,
  price_unit_text: '', amount: null, price_source: '', price_remark: '', price_confirmed_at: null,
}
const payable: PurchasePayable = {
  id: 'payable-1', number: 'CGYF001', status: 'WAITING_FINANCE_CONFIRM', supplier_name: '测试供应商',
  amount: null, price_complete: false, tax_mode: null, freight_mode: null,
  blocked_reason: '本批入库仍待质检，可先核价，品质确认后再确认应付。',
  created_at: '', updated_at: '', confirmed_at: null, confirmed_by: null, voided_at: null, etag: '"v1"',
  can_price: true, can_confirm: false, can_void: true,
  lines: [billable, { ...billable, line_id: 'fully-returned', accepted_quantity: '0.0000', settlement_quantity: '0.0000' }],
}

it('待质检可以核价，确认按钮服从接口，只提交可结算明细', async () => {
  vi.mocked(fetchPurchasePayables).mockResolvedValue({ data: [payable], meta: { page: 1, page_size: 20, total: 1, total_pages: 1 } })
  vi.mocked(fetchPurchasePayable).mockResolvedValue(payable)
  vi.mocked(updatePurchasePayablePricing).mockResolvedValue(payable)
  const wrapper = mount(FinancePurchasePayablesView, { global: { plugins: [ElementPlus], stubs: {
    AppWindowDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot/><slot name="footer"/></div>' },
  } } })
  try {
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '详情')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('本批入库仍待质检')
    expect(wrapper.findAll('button').some(button => button.text() === '确认应付')).toBe(false)
    await wrapper.findAll('button').find(button => button.text() === '保存价格')!.trigger('click')
    await flushPromises()
    expect(updatePurchasePayablePricing).toHaveBeenCalledWith('payable-1', {
      tax_mode: '', freight_mode: '', lines: [expect.objectContaining({ line_id: 'line-1' })],
    }, '"v1"')
  } finally {
    wrapper.unmount()
  }
})

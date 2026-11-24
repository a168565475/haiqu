import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FinancePurchasePayablesView from './FinancePurchasePayablesView.vue'
import { fetchPurchasePayableLines, fetchPurchasePayableFilterOptions, fetchPurchasePayable, updatePurchasePayablePricing } from '@/api/financePurchasePayables'
import type { PurchasePayable, PurchasePayableListLine } from '@/types/financePurchasePayables'

const state = vi.hoisted(() => ({ allowed: true, query: {} as Record<string, string>, replace: vi.fn() }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: false }, hasPermission: () => state.allowed }) }))
vi.mock('vue-router', () => ({ useRoute: () => ({ name: 'finance-purchase-payables', query: state.query }), useRouter: () => ({ replace: state.replace }) }))
vi.mock('@/api/financePurchasePayables', () => ({ fetchPurchasePayableLines: vi.fn(), fetchPurchasePayableFilterOptions: vi.fn(), fetchPurchasePayable: vi.fn(), updatePurchasePayablePricing: vi.fn(), confirmPurchasePayable: vi.fn(), voidPurchasePayable: vi.fn() }))

const line: PurchasePayableListLine = {
  line_id: 'line-1', payable_id: 'payable-1', payable_number: 'CGYF001', supplier_id: 'supplier-1', supplier_name: '测试供应商',
  part_name: '测试管材', material: '铁', specification: '20×1', inbound_number: 'RK001', purchase_order_number: 'CG001', inbound_date: '2026-11-01',
  source_unit_text_snapshot: 'KG', accepted_quantity: '999.0000', settlement_quantity: '95.0000', accepted_weight_kg: '95.0000',
  received_quantity: '100.0000', return_quantity: '5.0000', received_weight_kg: '100.0000', return_weight_kg: '5.0000',
  reference_unit_price: '2.5000', unit_price: null, price_unit_text: '', currency_code: 'CNY', amount: null,
  price_source: '', price_remark: '', price_confirmed_by_name: '', price_confirmed_at: null, status: 'WAITING_PRICE', status_display: '待核价',
}
const detail: PurchasePayable = {
  id: line.payable_id, number: line.payable_number, status: line.status, supplier_name: line.supplier_name,
  purchase_order_number: line.purchase_order_number, inbound_number: line.inbound_number, inbound_date: line.inbound_date,
  payment_term_id: null, payment_term_months: null, due_month: null,
  amount: null, price_complete: false, tax_mode: null, freight_mode: null, blocked_reason: '尚有明细待确认价格。',
  created_at: '', updated_at: '', confirmed_at: null, confirmed_by: null, voided_at: null, etag: '"v1"',
  can_price: true, can_confirm: false, can_void: true, lines: [line],
}
const setup = () => mount(FinancePurchasePayablesView, { global: { plugins: [ElementPlus], stubs: {
  AppWindowDialog: { props: ['modelValue'], template: '<div v-if="modelValue" class="dialog-test"><slot/><slot name="footer"/></div>' },
} } })
const button = (w: ReturnType<typeof setup>, label: string) => w.findAll('button').find(item => item.text() === label)!

describe('采购应付物料明细列表', () => {
  beforeEach(() => {
    vi.clearAllMocks(); state.allowed = true; state.query = {}
    vi.mocked(fetchPurchasePayableLines).mockResolvedValue({ data: [line], meta: { page: 1, page_size: 20, total: 41, total_pages: 3 } })
    vi.mocked(fetchPurchasePayableFilterOptions).mockResolvedValue({ suppliers: [{ id: 'supplier-1', name: '测试供应商', number: 'GYS001' }] })
    vi.mocked(fetchPurchasePayable).mockResolvedValue(detail)
    vi.mocked(updatePurchasePayablePricing).mockResolvedValue(detail)
  })

  it('主表直接展示物料、结算数量和两种价格，数量与总数来自接口', async () => {
    const w = setup()
    try {
      await flushPromises()
      expect(w.find('.erp-glass-list').exists()).toBe(true)
      expect(w.find('.erp-list-count').text()).toBe('41 条明细')
      for (const text of ['测试管材', '铁', '材质', '20×1', '95 KG', '采购参考单价', '核定单价', '2.5000 CNY / KG', '待确认', 'RK001']) expect(w.text()).toContain(text)
      expect(w.text()).not.toContain('999')
      expect(fetchPurchasePayableLines).toHaveBeenCalledWith({ page: 1, page_size: 20 })
    } finally { w.unmount() }
  })

  it('应用与回车不误清空条件，翻页沿用已应用条件，重置清空全部筛选', async () => {
    const w = setup()
    try {
      await flushPromises()
      await w.get('input[aria-label="搜索采购应付"]').setValue('管材')
      const selects = w.findAllComponents({ name: 'ElSelect' })
      selects[0]!.vm.$emit('update:modelValue', 'supplier-1')
      selects[1]!.vm.$emit('update:modelValue', 'WAITING_PRICE')
      w.findComponent({ name: 'ElDatePicker' }).vm.$emit('update:modelValue', ['2026-11-01', '2026-11-30'])
      await button(w, '应用筛选').trigger('click'); await flushPromises()
      const expected = { q: '管材', supplier_id: 'supplier-1', status: 'WAITING_PRICE', inbound_date_from: '2026-11-01', inbound_date_to: '2026-11-30', page: 1, page_size: 20 }
      expect(fetchPurchasePayableLines).toHaveBeenLastCalledWith(expected)
      await w.get('input[aria-label="搜索采购应付"]').trigger('keyup', { key: 'Enter' }); await flushPromises()
      expect(fetchPurchasePayableLines).toHaveBeenLastCalledWith(expected)
      await w.get('input[aria-label="搜索采购应付"]').setValue('尚未应用')
      const pagination = w.findComponent({ name: 'ElPagination' })
      pagination.vm.$emit('update:current-page', 2); pagination.vm.$emit('current-change', 2); await flushPromises()
      expect(fetchPurchasePayableLines).toHaveBeenLastCalledWith({ ...expected, page: 2 })
      await button(w, '重置').trigger('click'); await flushPromises()
      expect(fetchPurchasePayableLines).toHaveBeenLastCalledWith({ page: 1, page_size: 20, q: '', supplier_id: undefined, status: undefined, inbound_date_from: undefined, inbound_date_to: undefined })
    } finally { w.unmount() }
  })

  it('按根入库的管材在应付详情中区分仓库收退根数和结算公斤', async () => {
    vi.mocked(fetchPurchasePayable).mockResolvedValue({ ...detail, lines: [{ ...line,
      received_quantity: '30', return_quantity: '6', receipt_bar_counts: { received: 5, returned: 1 },
      received_weight_kg: null, return_weight_kg: null, accepted_weight_kg: null, settlement_quantity: '9.6000',
    }] })
    const w = setup()
    try {
      await flushPromises(); await button(w, '核价详情').trigger('click'); await flushPromises()
      await w.get('.pricing-table .el-table__expand-icon').trigger('click')
      const facts = w.get('.line-facts').text()
      for (const value of ['收货数量5 根', '退货数量1 根', '合格结算数量9.6 KG']) expect(facts).toContain(value)
      expect(facts).not.toContain('收货重量')
    } finally { w.unmount() }
  })

  it('明细打开所属应付单，参考价不自动变成核定价，保存沿用 ETag', async () => {
    const w = setup()
    try {
      await flushPromises(); await button(w, '核价详情').trigger('click'); await flushPromises()
      expect(fetchPurchasePayable).toHaveBeenCalledWith('payable-1')
      const price = w.get('input[aria-label="第1行核定单价"]')
      expect((price.element as HTMLInputElement).value).toBe('')
      expect(w.find('.dialog-test').text()).toContain('2.5000 CNY / KG')
      await price.setValue('3.25')
      await button(w, '保存价格').trigger('click'); await flushPromises()
      expect(updatePurchasePayablePricing).toHaveBeenCalledWith('payable-1', { tax_mode: '', freight_mode: '', lines: [{ line_id: 'line-1', unit_price: '3.25', price_unit_text: 'KG', price_source: '', price_remark: '' }] }, '"v1"')
    } finally { w.unmount() }
  })

  it('保留从来源单通过 payable_id 打开详情的入口', async () => {
    state.query = { payable_id: 'payable-1' }
    const w = setup()
    try { await flushPromises(); expect(fetchPurchasePayable).toHaveBeenCalledWith('payable-1') } finally { w.unmount() }
  })

  it('加载失败不伪装成零条或空列表，无权限不发业务请求', async () => {
    vi.mocked(fetchPurchasePayableLines).mockRejectedValueOnce(new Error('加载失败测试'))
    const w = setup()
    try {
      await flushPromises(); expect(w.text()).toContain('加载失败测试'); expect(w.text()).not.toContain('暂无采购应付明细'); expect(w.text()).not.toContain('0 条明细')
    } finally { w.unmount() }
    vi.clearAllMocks(); state.allowed = false
    const denied = setup()
    try { await flushPromises(); expect(denied.text()).toContain('没有采购应付查看权限'); expect(fetchPurchasePayableLines).not.toHaveBeenCalled(); expect(fetchPurchasePayableFilterOptions).not.toHaveBeenCalled() } finally { denied.unmount() }
  })
})

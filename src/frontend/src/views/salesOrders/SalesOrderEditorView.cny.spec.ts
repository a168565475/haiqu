import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SalesOrderEditorView from './SalesOrderEditorView.vue'
import * as api from '@/api/salesOrders'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: {}, query: {} }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), onBeforeRouteLeave: vi.fn() }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { employee: { id: 'employee' } }, hasPermission: () => true }) }))
vi.mock('@/api/productionData', () => ({ fetchAllProductionDataRecords: vi.fn().mockResolvedValue([]) }))
vi.mock('@/api/salesOrders', async original => ({ ...await original<typeof import('@/api/salesOrders')>(), fetchSalesOrderOptions: vi.fn(), fetchSalesOrderExchangeRate: vi.fn(), createSalesOrder: vi.fn(), fetchSalesOrder: vi.fn() }))
const snapshot = { record_id: 'rate-current', rate: '7.12345678', base_currency_code: 'USD', quote_currency_code: 'CNY', effective_date: '2026-10-15', source_name: '系统已维护汇率', source_version: 'batch' }

describe('销售订单系统人民币快照', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchSalesOrderOptions).mockResolvedValue({ customers: [], transaction_entities: [], buyer_addresses: [], products: [], employees: [], currencies: [], accepted_quotation_versions: [] } as never)
    vi.mocked(api.fetchSalesOrderExchangeRate).mockResolvedValue({ exchange_rate_record_id: snapshot.record_id, exchange_rate: snapshot.rate, exchange_rate_snapshot: snapshot })
  })
  it('新订单读取系统记录，人民币金额先舍入单价再计算每行', async () => {
    const wrapper = shallowMount(SalesOrderEditorView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const page = wrapper.vm as any
    expect(api.fetchSalesOrderExchangeRate).toHaveBeenCalledWith('USD')
    expect(page.form.exchange_rate_record_id).toBe('rate-current')
    page.lines = [{ unit_price: '0.0007', quantity: '7' }]
    expect(page.localLineAmount(page.lines[0])).toBe('0.0350')
    expect(page.orderTotalCny).toBe('0.0350')
    expect(page.amountText(page.orderTotalCny)).toBe('0.035')
    wrapper.unmount()
  })
  it('旧订单同币种沿用冻结值，不请求今天的汇率；换币种重新读取', async () => {
    const wrapper = shallowMount(SalesOrderEditorView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const page = wrapper.vm as any
    page.existingOrder = { currency_code: 'USD', total_amount_cny: '65.0000', exchange_rate: '6.50000000', exchange_rate_record_id: 'frozen', exchange_rate_snapshot: { ...snapshot, record_id: 'frozen', rate: '6.50000000' } }
    vi.mocked(api.fetchSalesOrderExchangeRate).mockClear()
    await page.loadExchangeRate()
    expect(api.fetchSalesOrderExchangeRate).not.toHaveBeenCalled()
    expect(page.form.exchange_rate).toBe('6.50000000')
    page.form.currency_code = 'EUR'
    await flushPromises()
    expect(api.fetchSalesOrderExchangeRate).toHaveBeenCalledWith('EUR')
    wrapper.unmount()
  })
  it('读取失败清空旧汇率并阻止以假1保存', async () => {
    const wrapper = shallowMount(SalesOrderEditorView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const page = wrapper.vm as any
    vi.mocked(api.fetchSalesOrderExchangeRate).mockRejectedValue(new Error('未维护有效汇率'))
    page.form.currency_code = 'EUR'
    await flushPromises()
    expect(page.form.exchange_rate).toBe('')
    expect(page.exchangeRateSnapshot).toBeNull()
    expect(page.validate(false)).toBeTruthy()
    expect(page.localLineAmount({ quantity: '3', unit_price: '4' })).toBeNull()
    wrapper.unmount()
  })
  it('历史空快照不能冒充已保存人民币金额，零金额仍然有效', async () => {
    const wrapper = shallowMount(SalesOrderEditorView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const page = wrapper.vm as any
    page.existingOrder = { currency_code: 'USD', exchange_rate: '1', total_amount_cny: null, exchange_rate_snapshot: {} }
    await page.loadExchangeRate()
    expect(page.exchangeRateError).toContain('历史订单补算')
    expect(page.form.exchange_rate).toBe('')
    expect(page.localLineAmount({ quantity: '2', unit_price: '10' })).toBeNull()
    page.existingOrder = { currency_code: 'USD', exchange_rate: snapshot.rate, total_amount_cny: '0.0000', exchange_rate_snapshot: snapshot }
    await page.loadExchangeRate()
    expect(page.exchangeRateError).toBe('')
    wrapper.unmount()
  })
  it.each([false, true])('汇率过期保留新单输入并重读预览，重读失败=%s', async refreshFails => {
    const wrapper = shallowMount(SalesOrderEditorView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const page = wrapper.vm as any
    page.options.transaction_entities = [{ id: 'buyer', customer_account_id: 'customer' }]
    Object.assign(page.form, {
      customer_account_id: 'customer', transaction_entity_id: 'buyer', salesperson_id: 'employee',
      order_date: '2026-10-15', direct_order_reason: '直接下单', seller_snapshot: { legal_name: '卖方' },
      confirmation_method: 'CUSTOMER_PO', customer_confirmer: '确认人', customer_confirmed_at: '2026-10-15T10:00', confirmation_summary: '已确认',
    })
    page.lines = [{ client_key: 'keep-line', product_id: 'product', quantity: '3', unit_price: '20', customer_product_name_snapshot: '产品' }]
    page.batches = [{ key: 'keep-batch', planned_delivery_date: '2026-10-20', lines: [{ sales_order_line_client_key: 'keep-line', quantity: '3' }] }]
    const pendingImage = new File(['image'], 'product.png', { type: 'image/png' })
    page.pendingProductImages['keep-line'] = pendingImage
    await flushPromises()
    expect(page.validate(false)).toBe('')
    vi.mocked(api.createSalesOrder).mockRejectedValue({ response: { status: 409, data: { error: { code: 'SALES_EXCHANGE_RATE_CHANGED', message: '汇率已更新' } } } })
    if (refreshFails) vi.mocked(api.fetchSalesOrderExchangeRate).mockRejectedValueOnce(new Error('未维护有效汇率'))
    else vi.mocked(api.fetchSalesOrderExchangeRate).mockResolvedValueOnce({ exchange_rate_record_id: 'rate-new', exchange_rate: '8.00000000', exchange_rate_snapshot: { ...snapshot, record_id: 'rate-new', rate: '8.00000000' } })
    await page.save()
    expect(page.conflictVisible).toBe(false)
    expect(api.fetchSalesOrder).not.toHaveBeenCalled()
    expect(api.createSalesOrder).toHaveBeenCalledTimes(1)
    expect(page.lines[0].client_key).toBe('keep-line')
    expect(page.batches[0].key).toBe('keep-batch')
    expect(page.pendingProductImages['keep-line']).toBe(pendingImage)
    if (refreshFails) {
      expect(page.exchangeRateError).toBe('未维护有效汇率')
      expect(page.validate(false)).toBe('未维护有效汇率')
    } else {
      expect(page.form.exchange_rate_record_id).toBe('rate-new')
      expect(page.orderTotalCny).toBe('480.0000')
    }
    wrapper.unmount()
  })
})

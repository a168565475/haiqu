import { flushPromises, shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/purchaseOrderReadDetail'
import PurchaseOrderDetailView from './PurchaseOrderDetailView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), useRoute: () => ({ params: { id: 'order-1' }, name: 'purchase-order-detail' }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 'user-1', is_superuser: true }, hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/stores/pageTabs', () => ({ usePageTabsStore: () => ({ accountId: 'user-1', setTabTitle: vi.fn() }) }))
vi.mock('@/api/purchaseOrderReadDetail', () => ({ fetchPurchaseOrderReadDetail: vi.fn() }))

const line = { id: 'line-1', part_name: '上下脚管', raw_bar_length_m: '3.35', actual_bar_count: 808,
  source_unit_text: '米', actual_purchase_quantity: '2706.8000', unit_price: '2.5000', amount: '6767.0000',
  received_quantity: '2680.0000', accepted_quantity: '2646.5000', return_quantity: '33.5000',
  received_bar_count: 800, accepted_bar_count: 790, return_bar_count: 10 }
const inboundLine = { id: 'inbound-line-1', purchase_order_line_id: 'line-1', part_name_snapshot: '上下脚管',
  raw_bar_length_m: '3.35', source_unit_text_snapshot: '米', received_quantity: '2680.0000', accepted_quantity: '2646.5000',
  return_quantity: '33.5000', received_bar_count: 800, accepted_bar_count: 790, return_bar_count: 10 }
const order = { id: 'order-1', source_type: 'PRODUCTION', order_number: 'CGDD261020001', status: 'SUBMITTED', currency_code: 'CNY',
  total_amount: '6767.0000', lines: [line], inbounds: [{ id: 'inbound-1', status: 'CONFIRMED', lines: [inboundLine] }],
  returns: [{ id: 'return-1', status: 'COMPLETED', lines: [{ id: 'return-line-1', raw_bar_length_m: '3.35', quantity: '33.5000', unit: '米', return_bar_count: 10 }] }] }

describe('采购详情管材根数', () => {
  beforeEach(() => { vi.mocked(api.fetchPurchaseOrderReadDetail).mockResolvedValue(order as never) })
  it('采购和收退合计均用根数，金额和米单价保持原计价口径', async () => {
    const wrapper = shallowMount(PurchaseOrderDetailView); await flushPromises()
    const cells = wrapper.get('[data-testid="detail-table-materials"] tbody tr').findAll('td')
    expect(cells.slice(3).map(cell => cell.text())).toEqual(['808 根', '2.50 元/米', '6,767.00', '800 根', '790 根', '10 根'])
    const totals = wrapper.get('tfoot tr').findAll('td')
    expect(totals[3]!.text()).toBe('808 根'); expect(totals[6]!.text()).toBe('800 根')
    await wrapper.get('#purchase-detail-tab-inbounds').trigger('click')
    const inbound = wrapper.get('[data-testid="detail-table-inbounds"] tbody tr').findAll('td')
    expect(inbound.slice(5, 8).map(cell => cell.text())).toEqual(['800 根', '790 根', '10 根'])
    await wrapper.get('#purchase-detail-tab-returns').trigger('click')
    expect(wrapper.get('[data-testid="detail-table-returns"] tbody tr').findAll('td')[5]!.text()).toBe('10 根')
    wrapper.unmount()
  })
  it('管材与非管材不同显示单位不合计，缺失根数不伪造零', async () => {
    vi.mocked(api.fetchPurchaseOrderReadDetail).mockResolvedValue({ ...order, lines: [
      { ...line, received_bar_count: null },
      { ...line, id: 'fabric', raw_bar_length_m: null, actual_purchase_quantity: '10.0000' },
    ] } as never)
    const wrapper = shallowMount(PurchaseOrderDetailView); await flushPromises()
    const rows = wrapper.findAll('tbody tr')
    expect(rows[0]!.findAll('td')[6]!.text()).toBe('根数未记录')
    expect(rows[1]!.findAll('td')[3]!.text()).toBe('10 米')
    expect(wrapper.get('tfoot tr').findAll('td')[3]!.text()).toBe('—')
    wrapper.unmount()
  })
  it('待质检批次合格和退货保留未确认状态', async () => {
    vi.mocked(api.fetchPurchaseOrderReadDetail).mockResolvedValue({ ...order, inbounds: [{ ...order.inbounds[0], status: 'PENDING_QUALITY' }] } as never)
    const wrapper = shallowMount(PurchaseOrderDetailView); await flushPromises()
    await wrapper.get('#purchase-detail-tab-inbounds').trigger('click')
    const cells = wrapper.get('[data-testid="detail-table-inbounds"] tbody tr').findAll('td')
    expect(cells.slice(5, 8).map(cell => cell.text())).toEqual(['800 根', '—', '—'])
    wrapper.unmount()
  })
})

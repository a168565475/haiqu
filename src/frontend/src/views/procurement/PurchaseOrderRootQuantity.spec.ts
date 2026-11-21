import { flushPromises, shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/purchaseOrderReadDetail'
import PurchaseOrderDetailView from './PurchaseOrderDetailView.vue'
import PurchaseInboundHistory from '@/components/procurement/PurchaseInboundHistory.vue'

const route = vi.hoisted(() => ({ params: { id: 'order-1' }, name: 'purchase-order-detail' }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), useRoute: () => route }))
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

describe('采购详情按采购单位', () => {
  beforeEach(() => { route.name = 'purchase-order-detail'; vi.mocked(api.fetchPurchaseOrderReadDetail).mockResolvedValue(order as never) })
  it('按根点收的批次保留公斤价格，到货、合格和退货用实点根数合计', async () => {
    vi.mocked(api.fetchPurchaseOrderReadDetail).mockResolvedValue({ ...order, lines: [{
      ...line, receipt_quantity_mode: 'ROOTS', source_unit_text: 'KG', actual_purchase_weight_kg: '300',
      received_weight_kg: null, accepted_weight_kg: null, return_weight_kg: null,
    }], inbounds: [{ ...order.inbounds[0], lines: [{ ...inboundLine, source_unit_text_snapshot: 'KG',
      calculation_snapshot: { receipt_quantity_mode: 'ROOTS' } }] }] } as never)
    const wrapper = shallowMount(PurchaseOrderDetailView); await flushPromises()
    try {
      for (const selector of ['tbody tr', 'tfoot tr']) {
        const cells = wrapper.get(selector).findAll('td')
        expect(cells[3]!.text()).toBe('300 kg')
        expect(cells.slice(6).map(cell => cell.text())).toEqual(['800 根', '790 根', '10 根'])
      }
      await wrapper.get('#purchase-detail-tab-inbounds').trigger('click')
      expect(wrapper.get('tbody tr').findAll('td').slice(5, 8).map(cell => cell.text())).toEqual(['800 根', '790 根', '10 根'])
    } finally { wrapper.unmount() }
  })
  it('采购入库入口的材料、历史、退货和合计只显示采购KG', async () => {
    route.name = 'purchase-inbound-detail'
    vi.mocked(api.fetchPurchaseOrderReadDetail).mockResolvedValue({ ...order, total_amount: '750.0000',
      lines: [{ ...line, source_unit_text: 'KG', actual_purchase_weight_kg: '300.0000', amount: '750.0000',
        received_weight_kg: '250.5000', accepted_weight_kg: '240.2500', return_weight_kg: '10.2500' }],
      inbounds: [{ ...order.inbounds[0], lines: [{ ...inboundLine, source_unit_text_snapshot: 'KG', received_weight_kg: '250.5000', accepted_weight_kg: '240.2500', return_weight_kg: '10.2500' }] }],
      returns: [{ ...order.returns[0], lines: [{ ...order.returns[0]!.lines[0], quantity: '10.2500', unit: 'KG' }] }],
    } as never)
    const wrapper = shallowMount(PurchaseOrderDetailView); await flushPromises()
    try {
      expect(wrapper.findComponent(PurchaseInboundHistory).props('showPipeRoots')).toBe(false)
      await wrapper.get('#purchase-detail-tab-materials').trigger('click')
      const cells = wrapper.get('[data-testid="detail-table-materials"] tbody tr').findAll('td')
      expect(cells.slice(3).map(cell => cell.text())).toEqual(['300 kg', '2.5 元/kg', '750.00', '250.5 kg', '240.25 kg', '10.25 kg'])
      const totals = wrapper.get('tfoot tr').findAll('td')
      expect(totals[3]!.text()).toBe('300 kg')
      expect(totals.slice(6).map(cell => cell.text())).toEqual(['250.5 kg', '240.25 kg', '10.25 kg'])
      await wrapper.get('#purchase-detail-tab-returns').trigger('click')
      expect(wrapper.get('[data-testid="detail-table-returns"] tbody tr').findAll('td')[5]!.text()).toBe('10.25 kg')
    } finally { wrapper.unmount() }
  })
  it('采购入库缺失实收重量时明细与合计均不伪造零', async () => {
    route.name = 'purchase-inbound-detail'
    vi.mocked(api.fetchPurchaseOrderReadDetail).mockResolvedValue({ ...order, lines: [{ ...line, source_unit_text: 'KG',
      actual_purchase_weight_kg: '300', received_bar_count: null, received_weight_kg: null }] } as never)
    const wrapper = shallowMount(PurchaseOrderDetailView); await flushPromises()
    try {
      await wrapper.get('#purchase-detail-tab-materials').trigger('click')
      expect(wrapper.get('tbody tr').findAll('td')[6]!.text()).toBe('—')
      expect(wrapper.get('tfoot tr').findAll('td')[6]!.text()).toBe('—')
    } finally { wrapper.unmount() }
  })
  it('KG管材使用重量字段显示金额、到货、入库和合计，忽略不同值的米数字段', async () => {
    vi.mocked(api.fetchPurchaseOrderReadDetail).mockResolvedValue({ ...order, total_amount: '750.0000',
      lines: [{ ...line, source_unit_text: 'KG', actual_purchase_quantity: '2706.8000', actual_purchase_weight_kg: '300.0000',
        amount: '750.0000', received_weight_kg: '250.5000', accepted_weight_kg: '240.2500', return_weight_kg: '10.2500' }],
      inbounds: [{ ...order.inbounds[0], lines: [{ ...inboundLine, source_unit_text_snapshot: 'KG', received_weight_kg: '250.5000', accepted_weight_kg: '240.2500', return_weight_kg: '10.2500' }] }],
      returns: [{ ...order.returns[0], lines: [{ ...order.returns[0]!.lines[0], quantity: '10.2500', unit: 'KG' }] }],
    } as never)
    const wrapper = shallowMount(PurchaseOrderDetailView); await flushPromises()
    const cells = wrapper.get('[data-testid="detail-table-materials"] tbody tr').findAll('td')
    expect(cells.slice(3).map(cell => cell.text())).toEqual(['300 kg', '2.5 元/kg', '750.00', '250.5 kg', '240.25 kg', '10.25 kg'])
    const totals = wrapper.get('tfoot tr').findAll('td')
    expect(totals[3]!.text()).toBe('300 kg')
    expect(totals[5]!.text()).toBe('750.00')
    expect(totals.slice(6).map(cell => cell.text())).toEqual(['250.5 kg', '240.25 kg', '10.25 kg'])
    await wrapper.get('#purchase-detail-tab-inbounds').trigger('click')
    expect(wrapper.get('[data-testid="detail-table-inbounds"] tbody tr').findAll('td').slice(5, 8).map(cell => cell.text()))
      .toEqual(['250.5 kg', '240.25 kg', '10.25 kg'])
    await wrapper.get('#purchase-detail-tab-returns').trigger('click')
    expect(wrapper.get('[data-testid="detail-table-returns"] tbody tr').findAll('td')[5]!.text()).toBe('10.25 kg')
    wrapper.unmount()
  })
  it('KG管材缺实收重量显示未知，普通KG材料使用原数量', async () => {
    vi.mocked(api.fetchPurchaseOrderReadDetail).mockResolvedValue({ ...order, lines: [
      { ...line, source_unit_text: 'KG', actual_purchase_weight_kg: '300', received_weight_kg: null },
      { ...line, id: 'ordinary-kg', raw_bar_length_m: null, source_unit_text: 'KG', received_quantity: '12.25' },
    ] } as never)
    const wrapper = shallowMount(PurchaseOrderDetailView); await flushPromises()
    const rows = wrapper.findAll('tbody tr')
    expect(rows[0]!.findAll('td')[6]!.text()).toBe('—')
    expect(rows[1]!.findAll('td')[6]!.text()).toBe('12.25 kg')
    expect(wrapper.get('tfoot tr').findAll('td')[6]!.text()).toBe('—')
    wrapper.unmount()
  })
  it('新目录管材按采购米数和米单价显示', async () => {
    const physical = { material_catalog_id: 'catalog-1' }
    vi.mocked(api.fetchPurchaseOrderReadDetail).mockResolvedValue({ ...order,
      lines: [{ ...line, ...physical }],
      inbounds: [{ ...order.inbounds[0], lines: [{ ...inboundLine, ...physical, source_unit_text_snapshot: '米' }] }],
      returns: [{ ...order.returns[0], lines: [{ ...order.returns[0]!.lines[0], material_catalog_id: 'catalog-1', quantity: '33.5', unit: '米' }] }],
    } as never)
    const wrapper = shallowMount(PurchaseOrderDetailView); await flushPromises()
    const cells = wrapper.get('[data-testid="detail-table-materials"] tbody tr').findAll('td')
    expect(cells[3]!.text()).toBe('2,706.8 米')
    expect(cells[4]!.text()).toContain('元/米')
    expect(cells.slice(6).map(cell => cell.text())).toEqual(['2,680 米', '2,646.5 米', '33.5 米'])
    expect(wrapper.get('tfoot tr').findAll('td')[3]!.text()).toBe('2,706.8 米')
    await wrapper.get('#purchase-detail-tab-inbounds').trigger('click')
    expect(wrapper.get('[data-testid="detail-table-inbounds"] tbody tr').findAll('td').slice(5, 8).map(cell => cell.text()))
      .toEqual(['2,680 米', '2,646.5 米', '33.5 米'])
    await wrapper.get('#purchase-detail-tab-returns').trigger('click')
    expect(wrapper.get('[data-testid="detail-table-returns"] tbody tr').findAll('td')[5]!.text()).toBe('33.5 米')
    wrapper.unmount()
  })
  it('采购和收退合计均用采购米数，金额和米单价保持原计价口径', async () => {
    const wrapper = shallowMount(PurchaseOrderDetailView); await flushPromises()
    const cells = wrapper.get('[data-testid="detail-table-materials"] tbody tr').findAll('td')
    expect(cells.slice(3).map(cell => cell.text())).toEqual(['2,706.8 米', '2.5 元/米', '6,767.00', '2,680 米', '2,646.5 米', '33.5 米'])
    const totals = wrapper.get('tfoot tr').findAll('td')
    expect(totals[3]!.text()).toBe('2,706.8 米'); expect(totals[6]!.text()).toBe('2,680 米')
    await wrapper.get('#purchase-detail-tab-inbounds').trigger('click')
    const inbound = wrapper.get('[data-testid="detail-table-inbounds"] tbody tr').findAll('td')
    expect(inbound.slice(5, 8).map(cell => cell.text())).toEqual(['2,680 米', '2,646.5 米', '33.5 米'])
    await wrapper.get('#purchase-detail-tab-returns').trigger('click')
    expect(wrapper.get('[data-testid="detail-table-returns"] tbody tr').findAll('td')[5]!.text()).toBe('33.5 米')
    wrapper.unmount()
  })
  it('管材与计数物料不同采购单位不合计，缺根数不改变米数', async () => {
    vi.mocked(api.fetchPurchaseOrderReadDetail).mockResolvedValue({ ...order, lines: [
      { ...line, received_bar_count: null },
      { ...line, id: 'fabric', raw_bar_length_m: null, source_unit_text: '个', actual_purchase_quantity: '10.0000' },
    ] } as never)
    const wrapper = shallowMount(PurchaseOrderDetailView); await flushPromises()
    const rows = wrapper.findAll('tbody tr')
    expect(rows[0]!.findAll('td')[6]!.text()).toBe('2,680 米')
    expect(rows[1]!.findAll('td')[3]!.text()).toBe('10 个')
    expect(wrapper.get('tfoot tr').findAll('td')[3]!.text()).toBe('—')
    wrapper.unmount()
  })
  it('待质检批次合格和退货保留未确认状态', async () => {
    vi.mocked(api.fetchPurchaseOrderReadDetail).mockResolvedValue({ ...order, inbounds: [{ ...order.inbounds[0], status: 'PENDING_QUALITY' }] } as never)
    const wrapper = shallowMount(PurchaseOrderDetailView); await flushPromises()
    await wrapper.get('#purchase-detail-tab-inbounds').trigger('click')
    const cells = wrapper.get('[data-testid="detail-table-inbounds"] tbody tr').findAll('td')
    expect(cells.slice(5, 8).map(cell => cell.text())).toEqual(['2,680 米', '—', '—'])
    wrapper.unmount()
  })
})

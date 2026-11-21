import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as api from '@/api/inventory'
import MaterialInventoryDetailView from './MaterialInventoryDetailView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { stockItemId: 'stock' }, query: {} }) }))
vi.mock('@/router', () => ({ router: { replace: vi.fn(), push: vi.fn() } }))
vi.mock('@/api/inventory', () => ({ fetchMaterialInventorySummary: vi.fn(), fetchMaterialOrderIssues: vi.fn(), fetchMaterialOrderPurchases: vi.fn() }))

describe('库存数量与计量单位', () => {
  it.each(['个', '片'])('五金库存%s和KG独立展示，关联采购为KG、领料仍是原单位', async unit => {
    vi.mocked(api.fetchMaterialInventorySummary).mockResolvedValue({ measurement_kind: 'HARDWARE_WEIGHT',
      current_quantity: '900', available_quantity: '800', weight_quantity: '3.9', available_weight_quantity: '3.4667',
      cumulative_inbound_quantity: '1000', cumulative_issued_quantity: '100', unit,
      zones: [{ zone_id: 'zone', warehouse_number: 'CK01', warehouse_name: '材料仓', zone_name: '五金区', quality: '合格', quantity: '900', weight_quantity: '3.9' }] } as never)
    vi.mocked(api.fetchMaterialOrderIssues).mockResolvedValue([{ material_issue_id: 'issue', issue_number: 'LL01', issued_quantity: '100', unit }] as never)
    vi.mocked(api.fetchMaterialOrderPurchases).mockResolvedValue([{ purchase_order_id: 'order', purchase_order_number: 'CG01', purchase_quantity: '6', actual_inbound_quantity: '3.9', pending_inbound_quantity: '2.1', weight_unit: true, unit: 'KG' }] as never)
    const wrapper = mount(MaterialInventoryDetailView, { global: { plugins: [ElementPlus] } })
    try {
      await flushPromises()
      const cards = wrapper.findAll('.stock-cards article')
      expect(cards[0]!.text()).toContain(`900 ${unit}`)
      expect(cards[0]!.get('small').text()).toBe('3.9 kg')
      expect(cards[1]!.text()).toContain(`800 ${unit}`)
      expect(cards[1]!.get('small').text()).toBe('3.4667 kg')
      const purchaseText = wrapper.get('#pane-purchases').text()
      expect(purchaseText).toContain('6 kg'); expect(purchaseText).toContain('3.9 kg'); expect(purchaseText).toContain('2.1 kg')
      const issueText = wrapper.get('#pane-issues').text()
      expect(issueText).toContain(`100 ${unit}`); expect(issueText).not.toContain('kg')
      expect(wrapper.get('.zones').text()).toContain(`900 ${unit}`)
      expect(wrapper.get('.zones').text()).toContain('3.9')
    } finally { wrapper.unmount() }
  })
  it.each(['个', '片'])('五金库存保留%s数量和公斤，历史缺重明确待核对', async unit => {
    vi.mocked(api.fetchMaterialInventorySummary).mockResolvedValue({ measurement_kind: 'HARDWARE_WEIGHT',
      current_quantity: '900', available_quantity: '900', weight_quantity: null,
      cumulative_inbound_quantity: '1000', cumulative_issued_quantity: '100', unit, zones: [] } as never)
    vi.mocked(api.fetchMaterialOrderIssues).mockResolvedValue([])
    vi.mocked(api.fetchMaterialOrderPurchases).mockResolvedValue([])
    const wrapper = shallowMount(MaterialInventoryDetailView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const cards = wrapper.findAll('.stock-cards article')
    expect(cards[0]!.get('strong').text()).toBe(`900 ${unit}`)
    expect(cards[0]!.get('small').text()).toBe('重量待核对')
    expect(cards[1]!.get('small').text()).toBe('重量待核对')
    wrapper.unmount()
  })
  it('管材库存和订单到货只显示根数，包括有历史实重的库区', async () => {
    vi.mocked(api.fetchMaterialInventorySummary).mockResolvedValue({ measurement_kind: 'PIPE', current_quantity: '10', available_quantity: '6',
      weight_quantity: '20', available_weight_quantity: '12.5', cumulative_inbound_quantity: '10', cumulative_issued_quantity: '0', unit: '根',
      zones: [{ warehouse_name: '原料仓', zone_name: '管材区', quantity: '10', weight_quantity: '20', bar_weight_kg: '2' }] } as never)
    vi.mocked(api.fetchMaterialOrderIssues).mockResolvedValue([])
    vi.mocked(api.fetchMaterialOrderPurchases).mockResolvedValue([{ purchase_order_number: 'CG01', production_task_number: 'HT26205',
      purchase_quantity: '12', actual_inbound_quantity: '9.6', pending_inbound_quantity: '2.4', weight_unit: true, unit: 'KG',
      bar_counts: { ordered: 5, accepted: 4, pending: 1 } }] as never)
    const wrapper = mount(MaterialInventoryDetailView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    try {
      const cards = wrapper.findAll('.stock-cards article')
      expect(cards[0]!.get('strong').text()).toBe('10 根')
      expect(cards[1]!.get('strong').text()).toBe('6 根')
      expect(wrapper.text()).not.toMatch(/kg|重量/i)
      const purchases = wrapper.get('#pane-purchases').text()
      for (const value of ['HT26205', '5 根', '4 根', '1 根']) expect(purchases).toContain(value)
    } finally { wrapper.unmount() }
  })
})

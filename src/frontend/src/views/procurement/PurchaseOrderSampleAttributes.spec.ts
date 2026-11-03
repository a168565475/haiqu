import { flushPromises, mount, shallowMount, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as purchaseApi from '@/api/purchaseOrders'
import * as detailApi from '@/api/purchaseOrderReadDetail'
import PurchaseOrderConfirmView from './PurchaseOrderConfirmView.vue'
import PurchaseOrderDetailView from './PurchaseOrderDetailView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), useRoute: () => ({ params: { id: 'order-1' }, name: 'purchase-order-detail' }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 'user-1', is_superuser: true }, hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/stores/pageTabs', () => ({ usePageTabsStore: () => ({ accountId: 'user-1', setTabTitle: vi.fn() }) }))
vi.mock('@/api/purchaseOrders', () => ({ fetchVersionedPurchaseOrder: vi.fn(), fetchPurchaseOrderSupplierOptions: vi.fn(), updatePurchaseOrder: vi.fn(), confirmVersionedPurchaseOrder: vi.fn() }))
vi.mock('@/api/purchaseOrderReadDetail', () => ({ fetchPurchaseOrderReadDetail: vi.fn() }))

const snapshot = { schema_version: 1, name: '铁管', template_key: 'TUBE', unit_name: '根', attributes: {
  shape: '方管', section_size: '20*20', thickness: '2.0', material: '铁', color: '蓝色',
} }
const line = { id: 'line-1', part_name: '铁管', specification: '20*20', material: '铁', raw_material: '铁', product_color: '蓝色', color: '蓝色',
  material_selection_snapshot: snapshot, source_unit_text: '米', required_quantity: '12', actual_purchase_quantity: '12', unit_price: '2',
  received_quantity: '0', accepted_quantity: '0', return_quantity: '0', amount: '24' }
const order = { id: 'order-1', order_number: 'CGDD001', source_type: 'SAMPLE', status: 'DRAFT', currency_code: 'CNY', product_summary: [], lines: [line],
  inbounds: [{ id: 'inbound-1', status: 'CONFIRMED', lines: [{ ...line, id: 'inbound-line-1', purchase_order_line_id: 'line-1', part_name_snapshot: '铁管', specification_snapshot: '20*20', material_snapshot: '铁', source_unit_text_snapshot: '米' }] }],
  returns: [{ id: 'return-1', status: 'COMPLETED', lines: [{ ...line, id: 'return-line-1', unit: '米', quantity: '0' }] }],
}
const tooltipStub = { props: ['visible'], template: '<div><slot /><div v-if="visible"><slot name="content" /></div></div>' }
let wrapper: VueWrapper | undefined
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(purchaseApi.fetchVersionedPurchaseOrder).mockResolvedValue({ data: order, etag: 'version-1' } as never)
  vi.mocked(purchaseApi.fetchPurchaseOrderSupplierOptions).mockResolvedValue({ suppliers: [] })
  vi.mocked(detailApi.fetchPurchaseOrderReadDetail).mockResolvedValue(order as never)
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

function expectSavedAttributes(page: VueWrapper) {
  const attributes = page.get('.material-attribute-tooltip').findAll('div').map(field => field.text())
  expect(attributes).toEqual(expect.arrayContaining(['规格20*20', '厚度2.0', '材质铁', '颜色蓝色']))
}

describe('样品采购属性浮层（组件契约）', () => {
  it('确认页保持材质规格列和文字，鼠标经过显示已保存的完整属性', async () => {
    wrapper = mount(PurchaseOrderConfirmView, { global: { plugins: [ElementPlus], stubs: { ElTooltip: tooltipStub, ElDatePicker: true } } })
    await flushPromises()
    const headers = wrapper.findAll('.el-table__header th').map(cell => cell.text())
    expect(headers).toContain('材质规格')
    expect(headers).not.toContain('厚度')
    const row = wrapper.get('.el-table__body tbody tr')
    const specification = row.findAll('td')[headers.indexOf('材质规格')]!
    expect(specification.text()).toBe('铁 · 20*20 · 蓝色')
    expect(wrapper.find('.material-attribute-tooltip').exists()).toBe(false)
    await specification.trigger('mouseenter')
    await flushPromises()
    expectSavedAttributes(wrapper)
    await wrapper.get('.detail-table').trigger('mouseleave')
    expect(wrapper.find('.material-attribute-tooltip').exists()).toBe(false)
    expect(purchaseApi.updatePurchaseOrder).not.toHaveBeenCalled()
  })

  it('详情材料、入库及退货保持原列，经过规格时显示相应快照属性', async () => {
    wrapper = shallowMount(PurchaseOrderDetailView, { global: { stubs: { ElTooltip: tooltipStub } } })
    await flushPromises()
    for (const tab of ['materials', 'inbounds', 'returns']) {
      await wrapper.get(`#purchase-detail-tab-${tab}`).trigger('click')
      const table = wrapper.get(`[data-testid="detail-table-${tab}"]`)
      const headers = table.findAll('th').map(cell => cell.text())
      expect(headers).toEqual(expect.arrayContaining(['规格', '材质', '颜色']))
      expect(headers).not.toContain('厚度')
      const row = table.get('tbody tr')
      expect(row.findAll('td')[headers.indexOf('规格')]!.text()).toBe('20*20')
      await row.trigger('mouseenter')
      expectSavedAttributes(wrapper)
      await row.trigger('mouseleave')
      expect(wrapper.find('.material-attribute-tooltip').exists()).toBe(false)
    }
  })
})

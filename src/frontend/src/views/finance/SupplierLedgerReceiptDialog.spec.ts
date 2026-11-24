import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { expect, it, vi } from 'vitest'

import { fetchMaterialReceipts } from '@/api/inventory'
import SupplierLedgerReceiptDialog from './SupplierLedgerReceiptDialog.vue'

vi.mock('@/api/inventory', () => ({ fetchMaterialReceipts: vi.fn() }))

it('供应商对账打开按根收货单时，收退和合格数量沿用仓库根数', async () => {
  vi.mocked(fetchMaterialReceipts).mockResolvedValue([{
    id: 'receipt', inbound_number: 'RK101', purchase_order_id: 'order', purchase_order_number: 'CG101',
    inbound_date: '2026-11-21', source_type: 'PURCHASE', source_type_display: '采购入库',
    status: 'CONFIRMED', status_display: '已确认', received_by_name: '仓管', quality_confirmed_by_name: '质检',
    quality_confirmed_at: null, total_received_quantity: '5', total_return_quantity: '1', total_accepted_quantity: '4',
    remark: '', created_at: '', updated_at: '', lines: [{
      id: 'line', material_snapshot: '床头管', specification_snapshot: '圆管',
      purchase_order_line_id: 'order-line', raw_material_information_id: null, zone_id: 'zone', location_id: null,
      purchase_order_number_snapshot: 'CG101', production_task_number_snapshot: 'HT101', sales_order_number_snapshot: '',
      supplier_number_snapshot: '', supplier_name_snapshot: '', bom_number_snapshot: '', product_name_snapshot: '',
      section_type_snapshot: 'PROFILE', section_title_snapshot: '管材', category_snapshot: '管材',
      part_name_snapshot: '床头管', raw_material_snapshot: '', remark: '', quality_remark: '',
      warehouse_id: 'warehouse', warehouse_number: '', warehouse_name: '', zone_name: '', location_number: null,
      calculation_snapshot: { receipt_quantity_mode: 'ROOTS' }, source_unit_text_snapshot: 'KG',
      received_bar_count: 5, return_bar_count: 1, accepted_bar_count: 4,
      received_quantity: '30', return_quantity: '6', accepted_quantity: '24',
    }],
  }])
  const wrapper = mount(SupplierLedgerReceiptDialog, {
    props: { inboundId: 'receipt' },
    global: { plugins: [ElementPlus], stubs: { AppWindowDialog: { template: '<div><slot/></div>' } } },
  })
  try {
    await flushPromises()
    expect(wrapper.get('tbody tr').findAll('td .cell').map(cell => cell.text()))
      .toEqual(['床头管', '圆管', '5', '1', '4', '根'])
    expect(wrapper.text()).not.toContain('合格实重')
  } finally { wrapper.unmount() }
})

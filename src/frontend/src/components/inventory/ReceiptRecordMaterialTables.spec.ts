import { h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import type { MaterialTransferLineRecord, ReceiptRecordDetail } from '@/types/inventory'
import type { PurchaseReadInboundLine } from '@/types/purchaseOrderReadDetail'
import PurchaseInboundHistory from '@/components/procurement/PurchaseInboundHistory.vue'
import ReceiptRecordMaterialTables from './ReceiptRecordMaterialTables.vue'

vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ identityReady: true, user: { id: 'user', is_superuser: true } }) }))

function purchaseLine(id: string, section: string, fields: Array<[string, string]>, overrides: Partial<PurchaseReadInboundLine> = {}): PurchaseReadInboundLine {
  return {
    id, purchase_order_line_id: `po-${id}`, part_name_snapshot: id, specification_snapshot: '', material_snapshot: '',
    section_title_snapshot: section, supplier_name_snapshot: '测试供应商', source_unit_text_snapshot: '个',
    received_quantity: '10', return_quantity: '2', accepted_quantity: '8', quality_remark: '划伤',
    warehouse_name: '原料仓', zone_name: '一号库区', location_number: '01',
    material_attributes_snapshot: { fields: fields.map(([label, value]) => ({ key: label, label, value })) }, ...overrides,
  }
}

function mountPurchase(lines: PurchaseReadInboundLine[], status: 'CONFIRMED' | 'PENDING_QUALITY' = 'CONFIRMED') {
  const receipt = { source: 'PURCHASE', data: {
    id: 'inbound', purchase_order_id: 'order', inbound_number: 'RK01', inbound_date: '2026-11-21', status,
    status_display: status === 'CONFIRMED' ? '已入库' : '待质检', remark: '', received_by_name: '仓管',
    quality_confirmed_by_name: '', quality_confirmed_at: null, created_at: '2026-11-21', lines,
  } } satisfies ReceiptRecordDetail
  return mount(PurchaseInboundHistory, {
    props: { purchaseOrderId: 'order', inbounds: [receipt.data], embedded: true, expandSingle: true },
    slots: { 'material-details': ({ quantity }) => h(ReceiptRecordMaterialTables, {
      receipt: { ...receipt, productionTaskNumber: 'HT26205', formatQuantity: quantity },
    }) },
    global: { stubs: { ElIcon: true, ElTag: true, ElTooltip: true } },
  })
}

describe('入库记录只读明细', () => {
  it('按材料顺序分表，颜色留宽，数量在属性后，库区和库位随表格滚动', async () => {
    const wrapper = mountPurchase([
      purchaseLine('纸箱', '包材', [['尺寸', '600×450×300'], ['箱规', '4 套/箱']], { location_number: '' }),
      purchaseLine('辅料', '辅料类', [['宽度', '25 mm']]),
      purchaseLine('扣件', '塑料件', [], { supplier_name_snapshot: '武义县桐琴镇志斌日用品生产制造有限公司' }),
      purchaseLine('布面', '面料类', [['颜色', '潘通色卡 19-4052 TCX 经典蓝']]),
      purchaseLine('螺丝', '五金件', [['螺纹规格', 'M6']]),
    ])
    await flushPromises()

    expect(wrapper.findAll('[data-material-category]').map(group => group.get('h3').text()))
      .toEqual(['五金件', '塑料件', '包材', '面料', '辅料'])
    const hardware = wrapper.get('[data-material-category="HARDWARE"]')
    const carton = wrapper.get('[data-material-category="PACKAGING"]')
    const fabric = wrapper.get('[data-material-category="FABRIC"]')
    expect(hardware.text()).not.toContain('箱规')
    expect(carton.findAll('thead th').map(cell => cell.text()).slice(3, 8))
      .toEqual(['尺寸', '箱规', '到货数量', '退货数量', '合格入库数量'])
    expect(fabric.text()).toContain('潘通色卡 19-4052 TCX 经典蓝')
    const columns = wrapper.findAllComponents({ name: 'ElTableColumn' })
    const nameColumns = columns.filter(column => column.props('label') === '物料信息')
    expect(nameColumns.map(column => column.props('width'))).toEqual([180, 180, 180, 180, 180])
    expect(Number(columns.find(column => column.props('label') === '颜色')?.props('minWidth'))).toBeGreaterThanOrEqual(192)
    const supplierWidths = columns.filter(column => column.props('label') === '供应商').map(column => Number(column.props('width')))
    expect(new Set(supplierWidths).size).toBe(1)
    expect(supplierWidths[0]).toBeGreaterThan(200)
    const locationColumns = columns.filter(column => ['库区', '库位'].includes(column.props('label') || ''))
    expect(locationColumns).toHaveLength(10)
    expect(locationColumns.every(column => !column.props('fixed'))).toBe(true)
    expect(wrapper.findAll('.erp-list-table-frame')).toHaveLength(5)
    expect(carton.findAll('tbody td').slice(-2).map(cell => cell.text())).toEqual(['一号库区', '未登记'])
    expect(hardware.findAll('tbody td').slice(-2).map(cell => cell.text())).toEqual(['一号库区', '01'])
    expect(wrapper.findComponent({ name: 'ElTooltip' }).exists()).toBe(false)
    wrapper.unmount()
  })

  it.each(['CONFIRMED', 'PENDING_QUALITY'] as const)('旧称重生产管材按已保存根数显示，状态为 %s', async status => {
    const wrapper = mountPurchase([purchaseLine('圆管', '管材', [['材质', '钢']], {
      measurement_kind: 'PIPE', source_unit_text_snapshot: 'KG', raw_bar_length_m: '6', bar_weight_kg: '2.5152',
      received_bar_count: 4, return_bar_count: 1, accepted_bar_count: 3, received_weight_kg: '12',
      return_weight_kg: '2.75', accepted_weight_kg: '9.25',
    })], status)
    await flushPromises()
    expect(wrapper.findAll('tbody td.receipt-quantity').map(cell => cell.text()))
      .toEqual(status === 'CONFIRMED' ? ['4 根', '1 根', '3 根'] : ['4 根', '—', '待质检'])
    expect(wrapper.text()).toContain('单根长度')
    wrapper.unmount()
  })

  it('材料收发显示原入库数量、实重和库区，库位明确显示未登记', async () => {
    const line: MaterialTransferLineRecord = {
      line_key: 'line', material_catalog_id: 'catalog', catalog_name: '牛津布', unit_name: '米', zone_id: 'zone',
      warehouse_name: '面料仓', zone_name: '货架一', direction: 'IN', quantity: '15.5', weight_quantity: '2.25', raw_bar_length_m: null,
      material_selection_snapshot: { schema_version: 1, catalog_id: 'catalog', catalog_version: '1',
        category_key: 'FABRIC', template_key: 'FABRIC', scope: 'BASE', processing_state: 'RAW', processing_stage: '',
        name: '牛津布', display_name: '牛津布', unit_id: 'm', unit_name: '米', attributes: { fabric_spec: '600D', color: '藏青' } },
    }
    const wrapper = mount(ReceiptRecordMaterialTables, { props: { receipt: { source: 'TRANSFER', data: {
      id: 'transfer', transfer_number: 'RK02', transfer_date: '2026-11-21', created_at: '2026-11-21',
      direction: 'IN', direction_display: '入库', operated_by_name: '仓管', remark: '', lines: [line],
    } } } })
    await flushPromises()
    expect(wrapper.get('[data-material-category="FABRIC"]').get('h3').text()).toBe('面料')
    expect(wrapper.findAll('thead th').slice(-2).map(cell => cell.text())).toEqual(['库区', '库位'])
    expect(wrapper.findAll('.el-table-fixed-column--right')).toHaveLength(0)
    expect(wrapper.findAll('tbody td').map(cell => cell.text())).toEqual(['1', '牛津布', '600D', '藏青', '15.5 米', '2.25', '面料仓', '货架一', '未登记'])
    wrapper.unmount()
  })
})

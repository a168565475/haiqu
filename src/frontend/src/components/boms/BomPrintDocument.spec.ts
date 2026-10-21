import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { BomDetail, BomSection } from '@/types/bom'
import BomPrintDocument from './BomPrintDocument.vue'

describe('BOM 纸面打印文档', () => {
  it('裁剪打印仅按片套数量计算，旧米数不再出现在纸面', () => {
    const sections = [{ id: 'cutting', title: '裁剪明细', section_type: 'FABRIC', lines: [{ id: 'cut-1', part_name: '外袋', material: 'PU', cutting_color: '黑色', specification: '20', cutting_pieces_per_set: 2, cutting_sets_per_product: 3, fabric_meters_per_piece: '0.125', fabric_meters_per_set: '0.25', unit: '套', images: [] }] }] as unknown as BomSection[]
    const wrapper = shallowMount(BomPrintDocument, { props: { bom: { bom_number: 'BOM-PRINT', order_quantity: '100' } as BomDetail, sections } })
    try {
      expect(wrapper.get('[data-field="order_cutting_sets"]').text()).toBe('300')
      expect(wrapper.get('[data-field="order_cutting_pieces"]').text()).toBe('600')
      expect(wrapper.text()).not.toMatch(/米\/片|每套耗米|0\.125|0\.25/)
    } finally { wrapper.unmount() }
  })
  it('编辑页打印从只读BOM取得旧版本，修改参数后打印新规则', async () => {
    const source = { id: 'p1', cutting_length_mm: 500, pieces_per_product: 2, pieces_per_bar: 5, raw_values: {} }
    const line = { id: 'p1', part_name: '上下管', length_value: '500', unit_consumption: '2', tube_cut_piece_count: '5' }
    const sections = [{ id: 's1', title: '管材类', section_type: 'PROFILE', lines: [line] }] as unknown as BomSection[]
    const bom = { bom_number: 'BOM-PRINT', order_quantity: '2000', sections: [{ ...sections[0], lines: [source] }] } as unknown as BomDetail
    const wrapper = shallowMount(BomPrintDocument, { props: { bom, sections } })
    try {
      expect(wrapper.get('[data-field="branch_count"]').text()).toBe('808')
      await wrapper.setProps({ sections: [{ ...sections[0]!, lines: [{ ...line, length_value: '501' }] }] as never })
      expect(wrapper.get('[data-field="branch_count"]').text()).toBe('800')
    } finally { wrapper.unmount() }
  })

  it('每区独立表头，字段与预览共用，保留空分区且不打印原料编号', () => {
    const sections = [
      { id: 'p', title: '包材类', section_type: 'ACCESSORY', lines: [{ id: 'l', part_name: '纸箱', material: '牛皮纸', packaging_color: '/', unit: '只', units_per_box: '4', unit_consumption: '1', packaging_material_number: 'CODE-HIDDEN', images: [] }] },
      { id: 't', title: '管材类', section_type: 'PROFILE', lines: [] },
    ] as unknown as BomSection[]
    const wrapper = shallowMount(BomPrintDocument, { props: { bom: { bom_number: 'BOM-PRINT', order_quantity: '20', current_order_quantity: '20', customer_name: '不应打印客户', product_name_snapshot: '不应打印成品', order_number: 'ORDER-HIDDEN' } as BomDetail, sections } })
    try {
      expect(wrapper.findAll('table')).toHaveLength(2)
      expect(wrapper.findAll('thead .bom-print-section-title').map(node => node.text())).toEqual(['管材类（0 条）', '包材类（1 条）'])
      expect(wrapper.text()).not.toContain('CODE-HIDDEN')
      expect(wrapper.text()).not.toMatch(/不应打印客户|不应打印成品|ORDER-HIDDEN/)
      expect(wrapper.find('.bom-print-heading').text()).toContain('BOM-PRINT')
      expect(wrapper.text()).toContain('暂无明细')
      expect(wrapper.findAll('[data-field="units_per_box"]')[0]!.text()).toBe('4')
      expect(wrapper.find('button,input,select').exists()).toBe(false)
      const widths = wrapper.findAll('table')[1]!.findAll('col').map(col => Number(col.attributes('style')!.match(/([\d.]+)%/)![1]))
      expect(widths.reduce((a, b) => a + b, 0)).toBeCloseTo(100, 1)
      expect(widths[0]).toBeLessThan(widths[1]!)
    } finally { wrapper.unmount() }
  })
})

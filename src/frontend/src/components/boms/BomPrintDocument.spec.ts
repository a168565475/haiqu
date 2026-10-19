import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { BomDetail, BomSection } from '@/types/bom'
import BomPrintDocument from './BomPrintDocument.vue'

describe('BOM 纸面打印文档', () => {
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

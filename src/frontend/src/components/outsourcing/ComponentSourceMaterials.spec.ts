import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ComponentSourceMaterials from './ComponentSourceMaterials.vue'

describe('外发布料来源分组', () => {
  it('多来源的品名材质颜色规格保持逐组配对，不分字段拼接', () => {
    const wrapper = mount(ComponentSourceMaterials, { props: { field: 'name', sources: [
      { source_bom_line_id: 'fabric', name: '面布', material: '涤纶', color: '蓝色', color_code: 'B1', fabric_spec: '600D', width: '150', unit: '米' },
      { source_bom_line_id: 'cotton', name: '棉料', material: '无胶棉', color: '白色', color_code: '', fabric_spec: '200g', width: '', unit: '米' },
    ] } })
    const groups = wrapper.findAll('.component-source-value')
    expect(groups.map(group => group.text())).toEqual(['面布', '棉料'])
    expect(mount(ComponentSourceMaterials, { props: { field: 'fabric_spec', sources: [
      { source_bom_line_id: 'fabric', name: '面布', material: '涤纶', color: '蓝色', color_code: 'B1', fabric_spec: '600D', width: '150', unit: '米' },
      { source_bom_line_id: 'cotton', name: '棉料', material: '无胶棉', color: '白色', color_code: '', fabric_spec: '200g', width: '', unit: '米' },
    ] } }).findAll('.component-source-value').map(item => item.text())).toEqual(['600D', '200g'])
  })
  it('历史没保存的资料明确未记录，不推测材质或来源品名', () => {
    const wrapper = mount(ComponentSourceMaterials, { props: { field: 'material', sources: [{ source_bom_line_id: '',
      name: '历史布料', material: '', color: '蓝', color_code: '', fabric_spec: '600D', width: '', unit: '米' }] } })
    expect(wrapper.text()).toContain('未记录')
    const empty = mount(ComponentSourceMaterials, { props: { field: 'name' } })
    expect(empty.text()).toBe('来源布料未记录')
  })
})

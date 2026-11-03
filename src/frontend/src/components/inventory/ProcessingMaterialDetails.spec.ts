import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ProcessingMaterialDetails from './ProcessingMaterialDetails.vue'
import type { MaterialSelectionSnapshot } from '@/types/materialCatalog'

const input: MaterialSelectionSnapshot = {
  schema_version: 1, catalog_id: 'catalog', catalog_version: 'saved-version', name: '铁管',
  category_key: 'TUBE', template_key: 'TUBE', scope: 'BASE', processing_state: 'RAW', processing_stage: 'RAW',
  unit_id: 'kg', unit_name: '公斤', attributes: { section_size: '25', color: '黑色' }, display_name: '铁管',
}
const output: MaterialSelectionSnapshot = { ...input, processing_state: 'PROCESSED', processing_stage: 'METAL', unit_id: 'piece', unit_name: '支' }
// 单测核对快照与悬浮交互，不代替实际页面布局检查。
const global = { stubs: { ElPopover: { template: '<div><slot name="reference" /><slot /></div>' } } }

describe('加工材料详情', () => {
  it('旧单没有新材料快照时不增加空的材料说明', () => {
    const wrapper = mount(ProcessingMaterialDetails, { props: { materials: {} }, slots: { default: '前脚管' } })
    expect(wrapper.find('button').exists()).toBe(false)
    expect(wrapper.text()).toBe('前脚管')
  })
  it('分别显示投入与产出单位和工序，不把原料单位当成成品单位', () => {
    const wrapper = mount(ProcessingMaterialDetails, { global, slots: { default: '前脚管' }, props: { materials: {
      input_material_selection_snapshot: input, output_material_selection_snapshot: output,
    } } })
    expect(wrapper.text()).toContain('投入材料：铁管')
    expect(wrapper.text()).toContain('原料 · 公斤')
    expect(wrapper.text()).toContain('产出材料：铁管')
    expect(wrapper.text()).toContain('金工完成 · 支')
    expect(wrapper.text()).toContain('规格25')
    expect(wrapper.get('.processing-material-trigger').text()).toBe('前脚管')
    expect(wrapper.find('button').exists()).toBe(false)
  })
  it('悬停名称显示喷塑状态与颜色，移出关闭，键盘聚焦也可查看', async () => {
    const wrapper = mount(ProcessingMaterialDetails, { attachTo: document.body, slots: { default: '前脚管' }, props: { materials: {
      output_material_selection_snapshot: { ...output, processing_stage: 'POWDER_COATING', attributes: { color: '白色' } },
    } } })
    try {
      const trigger = wrapper.get('.processing-material-trigger')
      await trigger.trigger('mouseenter')
      await vi.waitFor(() => {
        const content = document.querySelector('.processing-material-details')!
        expect(content.textContent).toContain('喷塑完成 · 支')
        expect(content.textContent).toContain('颜色白色')
        expect(getComputedStyle(content.closest('.el-popper')!).display).not.toBe('none')
      })
      await trigger.trigger('mouseleave')
      await vi.waitFor(() => expect(getComputedStyle(document.querySelector('.processing-material-details')!.closest('.el-popper')!).display).toBe('none'))
      await trigger.trigger('focus')
      await vi.waitFor(() => expect(getComputedStyle(document.querySelector('.processing-material-details')!.closest('.el-popper')!).display).not.toBe('none'))
    } finally { wrapper.unmount() }
  })
})

import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import { blankLine } from './bomEditorHelpers'
import BomLineEditorForm from './BomLineEditorForm.vue'

vi.mock('@/api/boms', () => ({ previewBomHardwareWeight: vi.fn() }))

describe('五金重量表单真实 Element Plus 控件', () => {
  it('可选择平垫并填写明确参数，展示计算和错误状态，手动改重量退出自动', async () => {
    const line = reactive({ ...blankLine('个'), part_name: '平垫片', material: '钢', specification: 'M6' })
    const target = document.createElement('div')
    document.body.appendChild(target)
    const noop = () => {}
    const wrapper = mount(BomLineEditorForm, {
      attachTo: target,
      props: {
        displayLineImages: () => [], formatHardwareColor: String,
        editorReferenceOptionsError: '', ensureEditorReferenceOptions: noop,
        tubeCoatingColors: [], tubeOptionsLoading: false,
        normalizeTubeCutPieceCount: noop, openLineImageManager: noop, auxiliaryLineHasActiveProduct: () => false,
        auxiliarySpecificationOptions: () => [], setAuxiliarySpecification: noop, auxiliaryColorOptions: () => [], setAuxiliaryColor: noop,
        auxiliaryMaterialOptions: () => [], setAuxiliaryMaterial: noop, fabricSpecificationOptions: () => [], setFabricSpecification: noop,
        fabricColorSnapshot: () => ({}), fabricColorOptions: () => [], setFabricColor: noop, fabricMaterialOptions: () => [], setFabricMaterial: noop,
        fabricWidthOptions: () => [], setFabricWidth: noop, isPipeCuttingLine: () => false, editingFabricSourceKey: '', fabricSourceLines: [],
        legacyPipeCuttingValues: () => null, editingCuttingCalculation: null, bom: null, number: Number,
        catalogMode: false, editingSection: { title: '五金件', section_type: 'ACCESSORY', lines: [line] },
        editingLineDraft: line, editingLineCalculations: null,
      },
      global: { plugins: [ElementPlus], stubs: { MaterialSelectionPanel: true, BomCuttingCatalogSelect: true } },
    })
    try {
      await wrapper.find('[aria-label="重量计算方式"]').trigger('click')
      await flushPromises()
      const option = Array.from(document.body.querySelectorAll<HTMLElement>('.el-select-dropdown__item')).find(item => item.textContent === '普通平垫片')!
      expect(option).toBeTruthy()
      option.click()
      await flushPromises()
      expect(line.hardware_weight_mode).toBe('AUTO')
      for (const [label, value] of [['垫片外径', '12'], ['垫片内径', '6.4'], ['垫片厚度', '1.6'], ['垫片材料密度', '7.85']]) {
        await wrapper.find(`input[aria-label="${label}"]`).setValue(value)
      }
      expect(line.hardware_weight_input).toMatchObject({ kind: 'PLAIN_WASHER', outer_diameter_mm: '12', inner_diameter_mm: '6.4', thickness_mm: '1.6', density_g_cm3: '7.85' })
      await wrapper.setProps({ hardwareWeightLoading: true })
      expect(wrapper.text()).toContain('正在核算')
      await wrapper.setProps({ hardwareWeightLoading: false, hardwareWeightError: '内径必须小于外径' })
      expect(wrapper.find('[role="alert"]').text()).toBe('内径必须小于外径')
      const labels = wrapper.findAll('.drawer-field > span').map(item => item.text())
      expect(labels.indexOf('重量计算方式')).toBeLessThan(labels.indexOf('单个用量'))
      expect(wrapper.text()).not.toContain('按钢制 GB/T 873-1986 暂定类型计算理论单重')
      await wrapper.find('input[aria-label="单个材料重量"]').setValue('0.00102')
      expect(line.hardware_weight_mode).toBe('MANUAL')
      expect(line.unit_material_weight_kg).toBe('0.00102')
    } finally {
      wrapper.unmount()
      target.remove()
    }
  })
})

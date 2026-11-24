import { flushPromises, mount } from '@vue/test-utils'
import { nextTick, reactive } from 'vue'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import { blankLine } from './bomEditorHelpers'
import { hardwareWeightKey, selectHardwareWeight } from './useHardwareWeightPreview'
import type { BomLineInput } from '@/types/bom'
import BomLineEditorForm from './BomLineEditorForm.vue'

vi.mock('@/api/boms', () => ({ previewBomHardwareWeight: vi.fn() }))

function mountHardwareForm(line: BomLineInput) {
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
  return { wrapper, target }
}

describe('五金重量表单真实 Element Plus 控件', () => {
  it('可选择平垫并填写明确参数，展示计算和错误状态，手动改重量退出自动', async () => {
    const line = reactive({ ...blankLine('个'), part_name: '平垫片', material: '钢', specification: 'M6' })
    const { wrapper, target } = mountHardwareForm(line)
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

  it('表外铆钉在预览和重新打开时显示估算，切换规格或手填后移除标记', async () => {
    const line = reactive({ ...blankLine('个'), part_name: '铆钉', material: '铁', specification: '5*53' })
    selectHardwareWeight(line, 'RIVET_GB873_STEEL')
    const { wrapper, target } = mountHardwareForm(line)
    const input_key = hardwareWeightKey(line)
    const unit_material_weight_kg = '0.00828000'
    const snapshot = { method: 'RIVET_GEOMETRY_ESTIMATE' }
    const label = () => wrapper.get('input[aria-label="单个材料重量"]').element.closest('label')!.textContent
    try {
      line.unit_material_weight_kg = unit_material_weight_kg
      line.hardware_weight_preview = { input_key, unit_material_weight_kg, unit_weight_g: '8.28', calculation_snapshot: snapshot }
      await nextTick()
      expect(label()).toContain('估算')
      line.hardware_weight_preview = undefined
      line.hardware_weight_saved = { input_key, unit_material_weight_kg }
      line.hardware_weight_snapshot = snapshot
      await nextTick()
      expect(label()).toContain('估算')
      line.specification = '5*50'
      await nextTick()
      expect(label()).not.toContain('估算')
      line.hardware_weight_preview = { input_key: hardwareWeightKey(line), unit_material_weight_kg: '0.00773000', unit_weight_g: '7.73', calculation_snapshot: { method: 'STANDARD_TABLE' } }
      await nextTick()
      expect(label()).not.toContain('估算')
      line.specification = '5*53'
      await wrapper.get('input[aria-label="单个材料重量"]').setValue('0.008')
      expect(label()).not.toContain('估算')
    } finally {
      wrapper.unmount()
      target.remove()
    }
  })
})

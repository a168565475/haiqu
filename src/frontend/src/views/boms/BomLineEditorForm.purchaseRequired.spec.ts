import { shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { reactive } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import BomLineEditorForm from './BomLineEditorForm.vue'
import { blankLine, editableLine } from './bomEditorHelpers'

describe('BOM 行是否采购', () => {
  it('缺省需要采购，可以选择外供，重新打开沿用保存值，裁剪明细隐藏选项', async () => {
    const line = reactive(blankLine('个'))
    const wrapper = shallowMount(BomLineEditorForm, { props: {
      editingLineDraft: line, editingSection: { title: '塑料件类', section_type: 'ACCESSORY', lines: [] },
      catalogMode: true, displayLineImages: () => [], number: String, fabricSourceLines: [],
      isPipeCuttingLine: () => false, legacyPipeCuttingValues: () => null,
      formatHardwareColor: String,
      editorReferenceOptionsError: '', ensureEditorReferenceOptions: vi.fn(), tubeCoatingColors: [],
      tubeOptionsLoading: false, normalizeTubeCutPieceCount: vi.fn(), openLineImageManager: vi.fn(),
      editingLineCalculations: null, auxiliaryLineHasActiveProduct: () => false,
      auxiliarySpecificationOptions: () => [], setAuxiliarySpecification: vi.fn(),
      auxiliaryColorOptions: () => [], setAuxiliaryColor: vi.fn(), auxiliaryMaterialOptions: () => [],
      setAuxiliaryMaterial: vi.fn(), fabricSpecificationOptions: () => [], setFabricSpecification: vi.fn(),
      fabricColorSnapshot: () => '', fabricColorOptions: () => [], setFabricColor: vi.fn(),
      fabricMaterialOptions: () => [], setFabricMaterial: vi.fn(), fabricWidthOptions: () => [],
      setFabricWidth: vi.fn(), editingFabricSourceKey: '', editingCuttingCalculation: null, bom: null,
    } as never, global: { plugins: [ElementPlus], stubs: { BomPurchaseRequiredField: false }, renderStubDefaultSlot: true } })
    const field = () => wrapper.findAllComponents({ name: 'ElSelect' }).find(node => node.props('ariaLabel') === '是否采购')
    expect(field()?.props('modelValue')).toBe(true)
    field()!.vm.$emit('update:modelValue', false)
    await wrapper.vm.$nextTick()
    expect(line.purchase_required).toBe(false)
    expect(editableLine({ ...line, id: 'saved' } as never).purchase_required).toBe(false)
    for (const [title, section_type, usage] of [
      ['管材类', 'PROFILE', '单个用量'], ['五金件', 'ACCESSORY', '单个用量'],
      ['塑料件类', 'ACCESSORY', '单个用量'], ['辅料类', 'ACCESSORY', '单个用量'],
      ['面料类', 'FABRIC', '单耗'], ['包材类', 'ACCESSORY', '*用量（多少成品用一份）'],
      ['配件类', 'ACCESSORY', '单耗'],
    ] as const) {
      await wrapper.setProps({ editingSection: { title, section_type, lines: [] } })
      const labels = wrapper.findAll('.drawer-field > span').map(label => label.text())
      expect(labels[labels.indexOf('是否采购') - 1], title).toBe(usage)
    }
    await wrapper.setProps({ editingSection: { title: '裁剪明细', section_type: 'FABRIC', lines: [] } })
    expect(field()).toBeUndefined()
    wrapper.unmount()
  })
})

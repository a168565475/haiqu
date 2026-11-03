import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import Editor from './SampleMaterialEditor.vue'
import Drawer from './SampleMaterialLineDrawer.vue'
import Selection from './SampleCatalogSelection.vue'
import Panel from '@/components/products/MaterialSelectionPanel.vue'
import { applySampleSelection, sampleSelectionLine } from '@/utils/sampleCatalogSelection'
import { validateSampleMaterials } from '@/utils/sampleMaterial'
import type { SampleMaterialLine } from '@/types/sampleMaterial'

vi.mock('@/api/sampleMaterials', () => ({
  fetchSampleMaterialReferences: vi.fn(async () => ({ tube: {}, fabric: {}, accessory: {}, accessories: [] })),
  fetchSampleMaterialCandidates: vi.fn(),
}))

const row = (): SampleMaterialLine => ({ key: 'pipe', category: 'tube', name: '原管', specification: '25', material: '铁', color: '',
  quantity: '1.25', unitId: 'root', unitLabel: '根', pipeInputMode: 'TOTAL_METERS', notes: '', material_catalog_id: 'catalog',
  material_selection: { catalog_version: 'v1', scope: 'BASE', processing_state: 'RAW', attributes: { section_size: '25' }, unit_id: 'root' } })
const global = { plugins: [ElementPlus], renderStubDefaultSlot: true }

describe('已保存目录管材兼容：来源根与样品业务米分离', () => {
  it('已保存目录原管编辑入口传准确固定根身份参数', () => {
    const wrapper = shallowMount(Selection, { props: { modelValue: row() } })
    expect(wrapper.getComponent(Panel).props('fixedUnit')).toBe('根')
    wrapper.unmount()
    const other = shallowMount(Selection, { props: { modelValue: { ...row(), category: 'hardware' } } })
    expect(other.getComponent(Panel).props('fixedUnit')).toBeUndefined()
    other.unmount()
  })
  it('编辑表格显示需求米，不把根制来源当业务数量单位', () => {
    const wrapper = shallowMount(Editor, { props: { modelValue: [row()], units: [], fullscreen: false }, global })
    const unitColumn = wrapper.findAll('thead th').findIndex(cell => cell.text().startsWith('单位'))
    expect(wrapper.findAll('tbody td')[unitColumn]!.text()).toBe('米')
    wrapper.unmount()
  })
  it('放大数量输入仍显示米', () => {
    const wrapper = shallowMount(Drawer, { props: { line: row(), modelValue: true, units: [], references: null, hasNext: false },
      global: { ...global, stubs: { ElInput: { props: ['ariaLabel'], template: '<div :data-label="ariaLabel"><slot name="append" /></div>' } } } })
    expect(wrapper.find('[data-label="放大编辑需求数量"]').text()).toBe('米')
    wrapper.unmount()
  })
  it('换具体属性保持米数，保留TOTAL_METERS而不是改成根数', async () => {
    const original = { ...row(), unitLabel: '米', unitId: '' }
    const selected = sampleSelectionLine(original)
    selected.unit = '根'
    selected.material_selection!.attributes.section_size = '32'
    const result = applySampleSelection(original, selected)
    expect(result.quantity).toBe('1.25')
    expect(result.pipeInputMode).toBe('TOTAL_METERS')
    await flushPromises()
  })
  it('管材非根原管明确拒绝，其他材料所选公斤照常保留', () => {
    const pipe = { ...row(), unitId: 'kg', unitLabel: '公斤' }
    expect(validateSampleMaterials({ lines: [pipe], notes: '' }, [])).toContain('根制原管')
    expect(validateSampleMaterials({ lines: [{ ...pipe, category: 'hardware' }], notes: '' }, [])).toBe('')
  })
})

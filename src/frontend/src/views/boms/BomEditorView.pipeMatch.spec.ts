import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/boms'
import PinyinFilterSelect from '@/components/production/PinyinFilterSelect.vue'
import type { BomLineInput, BomSectionInput } from '@/types/bom'
import type { MaterialSelectionInput } from '@/types/materialCatalog'
import BomEditorView from './BomEditorView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { bomId: 'b1' } }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/boms', async original => ({ ...await original<typeof import('@/api/boms')>(), fetchBomForEdit: vi.fn(), fetchBomPipeMaterialMatches: vi.fn(), previewBomTubeCalculation: vi.fn(), previewBomMaterialFlow: vi.fn(), previewBomMaterialSave: vi.fn(), saveBomDraft: vi.fn() }))
vi.mock('@/api/productionData', async original => ({ ...await original<typeof import('@/api/productionData')>(), fetchAllProductionDataRecords: vi.fn().mockResolvedValue([]) }))

const versioned = { data: { id: 'b1', status: 'PENDING_CONFIRMATION', order_quantity: '1000', current_order_quantity: '1000', product_information_confirmed: true, sections: [], configured_field_labels: {} }, etag: 'v1' }
interface Editor {
  sections: BomSectionInput[]
  activeSectionIndex: number
  editingLineDraft: BomLineInput
  lineDrawerVisible: boolean
  blankLine: (unit?: string) => BomLineInput
  openLineDrawer: (index: number) => void
  cancelLineDrawer: () => Promise<void>
  applyLineDrawer: () => Promise<void>
  followingLineDraft: (section: BomSectionInput, current: BomLineInput) => BomLineInput
  saveAndEditNextLine: () => Promise<void>
  persistDraft: () => Promise<boolean>
  tubeCalculations: (line: BomLineInput) => Record<string, string>
}
async function open(values: Partial<BomLineInput> = {}) {
  const wrapper = shallowMount(BomEditorView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true, stubs: { ElTableColumn: { template: '<div />' }, BomLineEditorForm: false } } })
  await flushPromises()
  const vm = wrapper.vm as unknown as Editor
  vm.sections.forEach(section => { section.lines = [] })
  vm.activeSectionIndex = vm.sections.findIndex(section => section.section_type === 'PROFILE')
  const section = vm.sections[vm.activeSectionIndex]!
  section.lines = [{ ...vm.blankLine('根'), part_name: '后座管', material: '铁-硬管', tube_shape: '矩形', tube_diameter: '25×15', tube_thickness: '1.5', length_value: '710', unit_consumption: '2', tube_cut_piece_count: '8', notes: '保留备注', ...values }]
  vm.openLineDrawer(0)
  await flushPromises()
  return { wrapper, vm, section }
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchBomForEdit).mockResolvedValue(structuredClone(versioned) as never)
  vi.mocked(api.fetchBomPipeMaterialMatches).mockReset().mockResolvedValue({ candidates: [], automatic_source_id: null, reason: 'no_match' } as never)
  vi.mocked(api.previewBomMaterialFlow).mockReset().mockResolvedValue({} as never)
  vi.mocked(api.previewBomTubeCalculation).mockReset().mockResolvedValue({ formula_version: '2026-10-29T01:00:00+00:00', coating_unit_area_sqm: '0.0568', purchase_unit_weight_kg: '0.6296', long_material_unit_weight_kg: '5.0811' })
  vi.mocked(api.previewBomMaterialSave).mockResolvedValue({ confirmation_token: null, new_materials: [] })
  vi.mocked(api.saveBomDraft).mockReset()
})

describe('BOM 管材保存时自动关联原料', () => {
  it.each(['selection', 'snapshot'] as const)('连续新增管材仅从%s独立继承五项材料属性并清空行身份和用量', async source => {
    const { wrapper, vm, section } = await open()
    try {
      const selected: MaterialSelectionInput = {
        catalog_version: 'old-catalog-version', scope: 'SPRAY', processing_state: 'PROCESSED', unit_id: 'old-unit',
        attributes: { material: '不锈钢', color: '黑色', shape: '矩形管', section_size: '30×20', thickness: '1.8', length: '6.0' },
        completed_craft: { id: 'old-craft', craft_type: 'INTERNAL', code: 'BENDING' }, semi_kind: 'PIPE',
      }
      const current: BomLineInput = {
        ...vm.blankLine('米'), id: 'old-line', client_key: 'old-client', part_name: '旧品名', material_catalog_id: 'old-catalog',
        material_quantity: '100', source_inventory_material_id: 'old-source', tube_coating_color: '喷塑灰',
        length_value: '710', unit_consumption: '2', tube_cut_piece_count: '8', total_consumption: '2000',
        branch_count: '250', original_material_length: '5.73', total_purchase_quantity: '1432.5', notes: '旧备注',
        coating_unit_area_sqm: '0.2', purchase_unit_weight_kg: '0.5', manual_tube_metrics: true,
        recalculate_tube_metrics: true, expected_tube_formula_version: 'old-formula',
        images: [{ id: 'old-image' }] as never, draft_images: [{ id: 'old-draft-image' }] as never,
      }
      if (source === 'selection') current.material_selection = selected
      else current.material_selection_snapshot = {
        ...selected, schema_version: 1, catalog_id: 'old-catalog', category_key: 'TUBE', template_key: 'TUBE',
        name: '旧品名', unit_id: 'old-unit', unit_name: '米', processing_stage: 'BENDING', display_name: '旧显示',
      }
      const next = vm.followingLineDraft(section, current)
      expect(next).toMatchObject({ part_name: '', unit: '根', material: '不锈钢', tube_shape: '矩形管',
        tube_diameter: '30×20', tube_thickness: '1.8', tube_coating_color: '喷塑灰', source_inventory_material_id: null,
        length_value: '', unit_consumption: '', tube_cut_piece_count: '', total_consumption: '', branch_count: '',
        original_material_length: '', total_purchase_quantity: '', notes: '', coating_unit_area_sqm: '',
        purchase_unit_weight_kg: '', images: [], draft_images: [] })
      expect(next.material_selection).toEqual({ catalog_version: 'old-catalog-version', scope: 'BASE', processing_state: 'RAW',
        unit_name: '根', attributes: { material: '不锈钢', color: '黑色', shape: '矩形管', section_size: '30×20', thickness: '1.8' } })
      for (const key of ['id', 'material_catalog_id', 'material_selection_snapshot', 'material_quantity',
        'manual_tube_metrics', 'recalculate_tube_metrics', 'expected_tube_formula_version', 'tube_calculation_preview']) {
        expect(next).not.toHaveProperty(key)
      }
      expect(next.client_key).toBeTruthy()
      expect(next.client_key).not.toBe(current.client_key)
      expect(vm.followingLineDraft(section, current).client_key).not.toBe(next.client_key)
      expect(next.material_selection!.attributes).not.toBe(selected.attributes)
      next.material_selection!.attributes.material = '更改新行'
      expect(selected.attributes.material).toBe('不锈钢')
      expect(next.images).not.toBe(current.images)
      expect(next.draft_images).not.toBe(current.draft_images)
    } finally { wrapper.unmount() }
  })

  it('连续新增管材进入既有下一条时保留该行自己的材料和用量', async () => {
    const { wrapper, vm, section } = await open({ id: 'current-line' })
    try {
      const next: BomLineInput = { ...vm.blankLine('根'), id: 'next-line', client_key: 'next-client', part_name: '下一条自己的品名',
        material_catalog_id: 'next-catalog', material: '铝', tube_shape: '矩形', tube_diameter: '40×20', tube_thickness: '2',
        tube_coating_color: '白色', length_value: '320', unit_consumption: '3', tube_cut_piece_count: '10', notes: '下一条备注',
        material_selection: { catalog_version: 'next-version', scope: 'BASE', processing_state: 'RAW', unit_name: '根',
          attributes: { material: '铝', color: '银色', shape: '矩形', section_size: '40×20', thickness: '2' } } }
      section.lines.push(next)
      const before = JSON.parse(JSON.stringify(next))
      await vm.saveAndEditNextLine()
      expect(vm.editingLineDraft).toMatchObject({ id: 'next-line', client_key: 'next-client', part_name: '下一条自己的品名',
        material_catalog_id: 'next-catalog', material: '铝', tube_shape: '矩形', tube_diameter: '40×20', tube_thickness: '2',
        tube_coating_color: '白色', length_value: '320', unit_consumption: '3', tube_cut_piece_count: '10', notes: '下一条备注',
        material_selection: before.material_selection })
      expect(section.lines[1]).toEqual(before)
    } finally { wrapper.unmount() }
  })

  it('打开旧BOM和只改备注后仍显示原808根，保存不提交计算版本', async () => {
    const source = { id: 'saved-line', part_name: '后座管', length_value: '500', unit_consumption: '2', tube_cut_piece_count: '5',
      cutting_length_mm: 500, pieces_per_product: 2, pieces_per_bar: 5, raw_values: {}, images: [] }
    const legacy = { ...versioned, data: { ...versioned.data, order_quantity: '2000', current_order_quantity: '2000',
      sections: [{ id: 'pipe-section', title: '管材类', section_type: 'PROFILE', lines: [source] }] } }
    vi.mocked(api.fetchBomForEdit).mockResolvedValue(legacy as never)
    const { wrapper, vm, section } = await open({ id: source.id, length_value: '500', unit_consumption: '2', tube_cut_piece_count: '5' })
    try {
      expect(vm.tubeCalculations(section.lines[0]!).branch_count).toBe('808')
      vm.editingLineDraft.notes = '只改备注'
      await vm.applyLineDrawer()
      expect(vm.tubeCalculations(section.lines[0]!).branch_count).toBe('808')
      vi.mocked(api.saveBomDraft).mockImplementationOnce(async (_id, sections) => {
        const row = sections.find(item => item.section_type === 'PROFILE')!.lines[0]!
        expect(row).not.toHaveProperty('pipe_plan_version')
        expect(row).not.toHaveProperty('raw_values')
        return legacy as never
      })
      expect(await vm.persistDraft()).toBe(true)
      expect(vm.tubeCalculations(vm.sections.find(item => item.section_type === 'PROFILE')!.lines[0]!).branch_count).toBe('808')
    } finally { wrapper.unmount() }
  })

  it('旧行修改切割参数实时显示800根，恢复原参数回到808根；新增行用800根', async () => {
    vi.mocked(api.fetchBomForEdit).mockResolvedValue({ ...versioned, data: { ...versioned.data, order_quantity: '2000',
      sections: [{ id: 'pipe-section', title: '管材类', section_type: 'PROFILE', lines: [{ id: 'saved-line',
        cutting_length_mm: 500, pieces_per_product: 2, pieces_per_bar: 5, raw_values: {}, images: [] }] }] } } as never)
    const { wrapper, vm } = await open({ id: 'saved-line', length_value: '500', unit_consumption: '2', tube_cut_piece_count: '5' })
    try {
      expect(vm.tubeCalculations(vm.editingLineDraft).branch_count).toBe('808')
      vm.editingLineDraft.length_value = '501'
      expect(vm.tubeCalculations(vm.editingLineDraft).branch_count).toBe('800')
      vm.editingLineDraft.length_value = '500'
      expect(vm.tubeCalculations(vm.editingLineDraft).branch_count).toBe('808')
      expect(vm.tubeCalculations({ ...vm.editingLineDraft, id: undefined }).branch_count).toBe('800')
    } finally { wrapper.unmount() }
  })

  it('录入管材不要求查询或手选原料，应用行保留全部填写参数', async () => {
    const { wrapper, vm, section } = await open()
    try {
      expect(api.fetchBomPipeMaterialMatches).not.toHaveBeenCalled()
      expect(wrapper.find('[aria-label="对应原料"]').exists()).toBe(false)
      expect(wrapper.text()).not.toContain('对应原料')
      expect(wrapper.text()).not.toContain('尚未建立原料档案')
      await vm.applyLineDrawer()
      expect(vm.lineDrawerVisible).toBe(false)
      expect(section.lines[0]).toMatchObject({ source_inventory_material_id: null, unit: '根', part_name: '后座管', tube_diameter: '25×15', tube_thickness: '1.5', length_value: '710', unit_consumption: '2', tube_cut_piece_count: '8', notes: '保留备注' })
      expect(api.saveBomDraft).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })

  it('原料查询不可用也不会阻止应用管材，数量核算照常执行', async () => {
    vi.mocked(api.fetchBomPipeMaterialMatches).mockImplementation(() => new Promise(() => {}))
    const { wrapper, vm, section } = await open()
    try {
      vm.editingLineDraft.length_value = '720'
      await vm.applyLineDrawer()
      expect(vm.lineDrawerVisible).toBe(false)
      expect(section.lines[0]!.length_value).toBe('720')
      expect(api.previewBomMaterialFlow).toHaveBeenCalledWith(expect.objectContaining({ kind: 'PIPE', order_quantity: '1000', cutting_length_mm: '720', pieces_per_product: '2', pieces_per_bar: '8', purchase_allowance_mode: 'AUTO' }))
      expect(api.fetchBomPipeMaterialMatches).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })

  it('已关联原料的管材仍能改形状材质规格厚度，旧规格快照不覆盖新输入', async () => {
    const { wrapper, vm, section } = await open({ id: 'saved-line', source_inventory_material_id: 'saved-source', raw_material: 'OLD', specification: '25×15×1.5mm' })
    try {
      const shape = wrapper.findAllComponents(PinyinFilterSelect).find(item => item.attributes('aria-label') === '形状')
      const material = wrapper.findAllComponents(PinyinFilterSelect).find(item => item.attributes('aria-label') === '材质')
      const diameter = wrapper.findAllComponents(ElSelect).find(item => item.attributes('aria-label') === '规格')
      const thickness = wrapper.findAllComponents(ElSelect).find(item => item.attributes('aria-label') === '厚度')
      expect(shape).toBeDefined()
      expect(material).toBeDefined()
      expect(diameter).toBeDefined()
      expect(thickness).toBeDefined()
      shape!.vm.$emit('update:modelValue', '圆管')
      material!.vm.$emit('update:modelValue', '不锈钢')
      diameter!.vm.$emit('update:modelValue', '30')
      thickness!.vm.$emit('update:modelValue', '1.8')
      await flushPromises()
      expect(vm.editingLineDraft.specification).toBe('')
      expect(section.lines[0]!.tube_thickness).toBe('1.5')
      await vm.applyLineDrawer()
      expect(section.lines[0]).toMatchObject({ source_inventory_material_id: 'saved-source', tube_shape: '圆管', material: '不锈钢', tube_diameter: '30', tube_thickness: '1.8', specification: '', length_value: '710', tube_cut_piece_count: '8' })
      expect(api.fetchBomPipeMaterialMatches).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })

  it('取消修改保留原表格行和原料关联，不发起保存', async () => {
    const { wrapper, vm, section } = await open({ id: 'saved-line', source_inventory_material_id: 'saved-source', specification: '25×15×1.5mm' })
    try {
      vm.editingLineDraft.tube_thickness = '1.8'
      await flushPromises()
      await vm.cancelLineDrawer()
      expect(vm.lineDrawerVisible).toBe(false)
      expect(section.lines[0]).toMatchObject({ source_inventory_material_id: 'saved-source', tube_thickness: '1.5', specification: '25×15×1.5mm' })
      expect(api.saveBomDraft).not.toHaveBeenCalled()
      expect(api.fetchBomPipeMaterialMatches).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })

  it('只改切割参数保留尺寸展示，保存将新参数交给后端并采用返回的关联', async () => {
    const { wrapper, vm } = await open({ id: 'saved-line', source_inventory_material_id: 'saved-source', specification: '25×15×1.5mm' })
    try {
      vm.editingLineDraft.length_value = '720'
      await flushPromises()
      expect(vm.editingLineDraft.specification).toBe('25×15×1.5mm')
      await vm.applyLineDrawer()
      vi.mocked(api.saveBomDraft).mockImplementationOnce(async (_id, sections) => {
        expect(sections.find(item => item.section_type === 'PROFILE')!.lines[0]).toMatchObject({ source_inventory_material_id: 'saved-source', length_value: '720', tube_thickness: '1.5', unit_consumption: '2', tube_cut_piece_count: '8' })
        const saved: BomSectionInput[] = JSON.parse(JSON.stringify(sections))
        Object.assign(saved.find(item => item.section_type === 'PROFILE')!.lines[0]!, { source_inventory_material_id: 'new-source', raw_material: 'AUTO001' })
        return { data: { ...versioned.data, sections: saved }, etag: 'v2' } as never
      })
      expect(await vm.persistDraft()).toBe(true)
      expect(vm.sections.find(item => item.section_type === 'PROFILE')!.lines[0]).toMatchObject({ source_inventory_material_id: 'new-source', raw_material: 'AUTO001', length_value: '720', tube_thickness: '1.5' })
      expect(api.saveBomDraft).toHaveBeenCalledWith('b1', expect.any(Array), 'v1', { intent: 'draft' })
      expect(api.fetchBomPipeMaterialMatches).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })

  it('数量核算失败仍阻止应用，不把失败当成已保存', async () => {
    const { wrapper, vm, section } = await open()
    try {
      vm.editingLineDraft.length_value = '720'
      vi.mocked(api.previewBomMaterialFlow).mockRejectedValueOnce(new Error('核算失败'))
      await vm.applyLineDrawer()
      expect(vm.lineDrawerVisible).toBe(true)
      expect(section.lines[0]!.length_value).toBe('710')
      expect(api.saveBomDraft).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })
})

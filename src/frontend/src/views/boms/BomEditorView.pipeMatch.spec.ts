import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/boms'
import PinyinFilterSelect from '@/components/production/PinyinFilterSelect.vue'
import type { BomLineInput, BomSectionInput } from '@/types/bom'
import BomEditorView from './BomEditorView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { bomId: 'b1' } }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/boms', async original => ({ ...await original<typeof import('@/api/boms')>(), fetchBomForEdit: vi.fn(), fetchBomPipeMaterialMatches: vi.fn(), previewBomMaterialFlow: vi.fn(), previewBomMaterialSave: vi.fn(), saveBomDraft: vi.fn() }))
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
  persistDraft: () => Promise<boolean>
}
async function open(values: Partial<BomLineInput> = {}) {
  const wrapper = shallowMount(BomEditorView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true, stubs: { ElTableColumn: { template: '<div />' } } } })
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
  vi.mocked(api.previewBomMaterialSave).mockResolvedValue({ confirmation_token: null, new_materials: [] })
  vi.mocked(api.saveBomDraft).mockReset()
})

describe('BOM 管材保存时自动关联原料', () => {
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
      expect(api.previewBomMaterialFlow).toHaveBeenCalledWith({ kind: 'PIPE', order_quantity: '1000', cutting_length_mm: '720', pieces_per_product: '2', pieces_per_bar: '8' })
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

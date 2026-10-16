import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/boms'
import type { BomLineInput, BomSectionInput } from '@/types/bom'
import BomEditorView from './BomEditorView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { bomId: 'b1' } }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/boms', async original => ({ ...await original<typeof import('@/api/boms')>(), fetchBomForEdit: vi.fn(), fetchBomPipeMaterialMatches: vi.fn(), previewBomMaterialFlow: vi.fn() }))
vi.mock('@/api/productionData', async original => ({ ...await original<typeof import('@/api/productionData')>(), fetchAllProductionDataRecords: vi.fn().mockResolvedValue([]) }))

const material = { id: 'raw-1', material_number: 'CL001', material_name: '矩形管', material: '铁-硬管', specification: '25×15×1.5', unit_name: '根', diameter: '25×15', thickness: '1.5', length: '6' }
const unique = { candidates: [material], automatic_source_id: material.id, reason: 'unique' }
interface Editor {
  sections: BomSectionInput[]
  activeSectionIndex: number
  editingLineDraft: BomLineInput
  lineDrawerVisible: boolean
  pipeMaterialMatchStatus: string
  pipeMaterialCandidates: typeof material[]
  editingPipeSourceLocked: boolean
  blankLine: (unit?: string) => BomLineInput
  openLineDrawer: (index: number) => void
  cancelLineDrawer: () => Promise<void>
  applyLineDrawer: () => Promise<void>
  selectPipeMaterial: (id: string) => void
  matchPipeMaterial: () => Promise<void>
  pipeMaterialLabel: (item: typeof material) => string
}
async function open(values: Partial<BomLineInput> = {}) {
  const wrapper = shallowMount(BomEditorView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true, stubs: { ElTableColumn: { template: '<div />' } } } })
  await flushPromises()
  const vm = wrapper.vm as unknown as Editor
  vm.activeSectionIndex = vm.sections.findIndex(section => section.section_type === 'PROFILE')
  const section = vm.sections[vm.activeSectionIndex]!
  section.lines = [{ ...vm.blankLine('根'), part_name: '后座管', material: '铁-硬管', tube_shape: '矩形', tube_diameter: '25×15', tube_thickness: '1.5', length_value: '710', unit_consumption: '2', tube_cut_piece_count: '8', notes: '保留备注', ...values }]
  vm.openLineDrawer(0)
  await flushPromises()
  return { wrapper, vm, section }
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchBomPipeMaterialMatches).mockReset()
  vi.mocked(api.fetchBomForEdit).mockResolvedValue({ data: { id: 'b1', status: 'PENDING_CONFIRMATION', order_quantity: '1000', current_order_quantity: '1000', product_information_confirmed: true, sections: [], configured_field_labels: {} }, etag: 'v1' } as never)
  vi.mocked(api.fetchBomPipeMaterialMatches).mockResolvedValue(unique as never)
  vi.mocked(api.previewBomMaterialFlow).mockResolvedValue({} as never)
})

describe('BOM 管材对应原料', () => {
  it('原料档案长度没有统一单位时显示原文，不擅自把毫米文本标成米', async () => {
    const { wrapper, vm } = await open()
    try {
      expect(vm.pipeMaterialLabel({ ...material, length: '6250' })).toContain('档案长度：6250')
      expect(vm.pipeMaterialLabel({ ...material, length: '6250' })).not.toContain('6250 m')
    } finally { wrapper.unmount() }
  })

  it('只按后端可靠唯一匹配自动关联，原参数、部位名和用量不变，应用后才更新表格行', async () => {
    const { wrapper, vm, section } = await open()
    try {
      expect(api.fetchBomPipeMaterialMatches).toHaveBeenCalledWith(expect.objectContaining({ material: '铁-硬管', diameter: '25×15', thickness: '1.5', tube_shape: '矩形' }))
      expect(api.fetchBomPipeMaterialMatches).toHaveBeenCalledWith(expect.objectContaining({ raw_bar_length_m: '5.73' }))
      expect(vm.editingLineDraft).toMatchObject({ source_inventory_material_id: 'raw-1', raw_material: 'CL001', unit: '根', part_name: '后座管', tube_diameter: '25×15', tube_thickness: '1.5', length_value: '710', unit_consumption: '2', tube_cut_piece_count: '8', notes: '保留备注' })
      expect(vm.pipeMaterialMatchStatus).toBe('linked')
      expect(section.lines[0]!.source_inventory_material_id).toBeNull()
      await vm.applyLineDrawer()
      expect(section.lines[0]!.source_inventory_material_id).toBe('raw-1')
    } finally { wrapper.unmount() }
  })

  it('只有一条候选但后端要求复核时不自动关联，用户确认后才关联', async () => {
    vi.mocked(api.fetchBomPipeMaterialMatches).mockResolvedValue({ ...unique, automatic_source_id: null, reason: 'needs_review' } as never)
    const { wrapper, vm } = await open()
    try {
      expect(vm.pipeMaterialMatchStatus).toBe('needs_review')
      expect(vm.editingLineDraft.source_inventory_material_id).toBeNull()
      vm.selectPipeMaterial('raw-1')
      expect(vm.editingLineDraft.source_inventory_material_id).toBe('raw-1')
    } finally { wrapper.unmount() }
  })

  it('多个候选必须手选，不接受候选之外的原料ID', async () => {
    vi.mocked(api.fetchBomPipeMaterialMatches).mockResolvedValue({ candidates: [material, { ...material, id: 'raw-2' }], automatic_source_id: null, reason: 'multiple' } as never)
    const { wrapper, vm } = await open()
    try {
      expect(vm.pipeMaterialCandidates).toHaveLength(2)
      expect(vm.editingLineDraft.source_inventory_material_id).toBeNull()
      vm.selectPipeMaterial('other')
      expect(vm.editingLineDraft.source_inventory_material_id).toBeNull()
      vm.selectPipeMaterial('raw-2')
      expect(vm.editingLineDraft.source_inventory_material_id).toBe('raw-2')
    } finally { wrapper.unmount() }
  })

  it('无匹配不改厚度，并允许应用草稿', async () => {
    vi.mocked(api.fetchBomPipeMaterialMatches).mockResolvedValue({ candidates: [], automatic_source_id: null, reason: 'no_match' } as never)
    const { wrapper, vm, section } = await open()
    try {
      expect(vm.pipeMaterialMatchStatus).toBe('no_match')
      expect(vm.editingLineDraft.tube_thickness).toBe('1.5')
      await vm.applyLineDrawer()
      expect(section.lines[0]!.source_inventory_material_id).toBeNull()
      expect(vm.lineDrawerVisible).toBe(false)
    } finally { wrapper.unmount() }
  })

  it('缺少匹配参数时不发送请求', async () => {
    const { wrapper, vm } = await open({ tube_thickness: '' })
    try {
      expect(api.fetchBomPipeMaterialMatches).not.toHaveBeenCalled()
      expect(vm.pipeMaterialMatchStatus).toBe('incomplete')
    } finally { wrapper.unmount() }
  })

  it('原先已关联的行保持关联与只读，不发起自动替换', async () => {
    const { wrapper, vm } = await open({ source_inventory_material_id: 'saved-source', raw_material: 'OLD' })
    try {
      expect(api.fetchBomPipeMaterialMatches).not.toHaveBeenCalled()
      expect(vm.editingPipeSourceLocked).toBe(true)
      expect(vm.editingLineDraft.source_inventory_material_id).toBe('saved-source')
    } finally { wrapper.unmount() }
  })

  it('更改本次自动匹配行的参数会移除临时关联并重查，不保留过期候选', async () => {
    const { wrapper, vm } = await open()
    try {
      expect(vm.editingPipeSourceLocked).toBe(false)
      vi.mocked(api.fetchBomPipeMaterialMatches).mockResolvedValueOnce({ candidates: [], automatic_source_id: null, reason: 'no_match' } as never)
      vm.editingLineDraft.tube_thickness = '1.8'
      await flushPromises()
      expect(vm.editingLineDraft.source_inventory_material_id).toBeNull()
      expect(vm.pipeMaterialCandidates).toHaveLength(0)
      expect(api.fetchBomPipeMaterialMatches).toHaveBeenLastCalledWith(expect.objectContaining({ thickness: '1.8' }))
    } finally { wrapper.unmount() }
  })

  it('未关联旧行修改厚度后清除旧规格展示，未修改时保留原规格', async () => {
    vi.mocked(api.fetchBomPipeMaterialMatches).mockResolvedValue({ candidates: [], automatic_source_id: null, reason: 'no_match' } as never)
    const { wrapper, vm, section } = await open({ id: 'saved-line', specification: 'Φ25×15×1.5mm' })
    try {
      expect(vm.editingLineDraft.specification).toBe('Φ25×15×1.5mm')
      expect(vm.editingLineDraft.tube_thickness).toBe('1.5')
      vm.editingLineDraft.tube_thickness = '0.8'
      await flushPromises()
      expect(vm.editingLineDraft.specification).toBe('')
      await vm.applyLineDrawer()
      expect(section.lines[0]!).toMatchObject({ specification: '', tube_diameter: '25×15', tube_thickness: '0.8' })
    } finally { wrapper.unmount() }
  })

  it('已有稳定来源的规格快照不会因切割用量变化被清空', async () => {
    const { wrapper, vm } = await open({ id: 'saved-line', source_inventory_material_id: 'saved-source', specification: 'Φ25×15×1.5mm' })
    try {
      vm.editingLineDraft.length_value = '720'
      await flushPromises()
      expect(vm.editingLineDraft.specification).toBe('Φ25×15×1.5mm')
      expect(vm.editingLineDraft.source_inventory_material_id).toBe('saved-source')
      expect(api.fetchBomPipeMaterialMatches).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })

  it('较慢的旧参数响应不能覆盖最新匹配结果', async () => {
    let resolveOld!: (value: never) => void
    vi.mocked(api.fetchBomPipeMaterialMatches).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const { wrapper, vm } = await open()
    try {
      vm.editingLineDraft.tube_thickness = '1.8'
      vi.mocked(api.fetchBomPipeMaterialMatches).mockResolvedValueOnce({ candidates: [], automatic_source_id: null, reason: 'no_match' } as never)
      await flushPromises()
      resolveOld(unique as never)
      await flushPromises()
      expect(vm.pipeMaterialMatchStatus).toBe('no_match')
      expect(vm.editingLineDraft.source_inventory_material_id).toBeNull()
    } finally { wrapper.unmount() }
  })

  it('计算用料长度变化时重新核对自动匹配，但不修改切割参数', async () => {
    const { wrapper, vm } = await open()
    try {
      vi.mocked(api.fetchBomPipeMaterialMatches).mockResolvedValueOnce({ ...unique, automatic_source_id: null, reason: 'needs_review' } as never)
      vm.editingLineDraft.length_value = '720'
      await flushPromises()
      expect(api.fetchBomPipeMaterialMatches).toHaveBeenLastCalledWith(expect.objectContaining({ raw_bar_length_m: '5.81' }))
      expect(vm.editingLineDraft.source_inventory_material_id).toBeNull()
      expect(vm.editingLineDraft.length_value).toBe('720')
      expect(vm.pipeMaterialMatchStatus).toBe('needs_review')
    } finally { wrapper.unmount() }
  })

  it('手选确认后修改切割用量保留来源，仅修改管材属性才重新匹配', async () => {
    vi.mocked(api.fetchBomPipeMaterialMatches).mockResolvedValue({ ...unique, automatic_source_id: null, reason: 'needs_review' } as never)
    const { wrapper, vm } = await open()
    try {
      vm.selectPipeMaterial('raw-1')
      vm.editingLineDraft.length_value = '720'
      vm.editingLineDraft.tube_cut_piece_count = '7'
      await flushPromises()
      expect(api.fetchBomPipeMaterialMatches).toHaveBeenCalledTimes(1)
      expect(vm.editingLineDraft.source_inventory_material_id).toBe('raw-1')
      expect(vm.pipeMaterialMatchStatus).toBe('linked')
      vi.mocked(api.fetchBomPipeMaterialMatches).mockResolvedValueOnce({ candidates: [], automatic_source_id: null, reason: 'no_match' } as never)
      vm.editingLineDraft.tube_thickness = '1.8'
      await flushPromises()
      expect(vm.editingLineDraft.source_inventory_material_id).toBeNull()
      expect(api.fetchBomPipeMaterialMatches).toHaveBeenCalledTimes(2)
    } finally { wrapper.unmount() }
  })

  it('匹配失败可重试，匹配中不能提前应用漏掉关联', async () => {
    vi.mocked(api.fetchBomPipeMaterialMatches).mockRejectedValueOnce(new Error('offline'))
    const { wrapper, vm, section } = await open()
    try {
      expect(vm.pipeMaterialMatchStatus).toBe('error')
      let resolveRetry!: (value: never) => void
      vi.mocked(api.fetchBomPipeMaterialMatches).mockImplementationOnce(() => new Promise(resolve => { resolveRetry = resolve }))
      const pending = vm.matchPipeMaterial()
      await vm.applyLineDrawer()
      expect(vm.lineDrawerVisible).toBe(true)
      expect(section.lines[0]!.source_inventory_material_id).toBeNull()
      resolveRetry(unique as never)
      await pending
      expect(vm.editingLineDraft.source_inventory_material_id).toBe('raw-1')
    } finally { wrapper.unmount() }
  })

  it('取消弹窗后匹配结果不能回写，原表格数据不变', async () => {
    let resolveMatch!: (value: never) => void
    vi.mocked(api.fetchBomPipeMaterialMatches).mockImplementationOnce(() => new Promise(resolve => { resolveMatch = resolve }))
    const { wrapper, vm, section } = await open()
    try {
      await vm.cancelLineDrawer()
      resolveMatch(unique as never)
      await flushPromises()
      expect(vm.editingLineDraft.source_inventory_material_id).toBeNull()
      expect(section.lines[0]!.source_inventory_material_id).toBeNull()
    } finally { wrapper.unmount() }
  })
})

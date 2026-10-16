import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/boms'
import type { BomLineInput, BomSectionInput } from '@/types/bom'
import BomEditorView from './BomEditorView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { bomId: 'b1' } }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/boms', async original => ({ ...await original<typeof import('@/api/boms')>(), fetchBomForEdit: vi.fn(), saveBomDraft: vi.fn(), fetchBomEditorReferenceOptions: vi.fn() }))
vi.mock('@/api/productionData', async original => ({ ...await original<typeof import('@/api/productionData')>(), fetchAllProductionDataRecords: vi.fn().mockResolvedValue([]) }))

const versioned = { data: { id: 'b1', status: 'PENDING_CONFIRMATION', order_quantity: '1000', current_order_quantity: '1000', product_information_confirmed: true, sections: [], configured_field_labels: {} }, etag: 'v1' }
interface Editor {
  sections: BomSectionInput[]
  activeSectionIndex: number
  editingLineDraft: BomLineInput
  editingFabricSourceKey: string
  fabricSourceLines: BomLineInput[]
  addFabricLine: () => Promise<void>
  blankLine: (unit?: string) => BomLineInput
  followingLineDraft: (section: BomSectionInput, line: BomLineInput) => BomLineInput
  lineFieldError: (section: BomSectionInput, line: BomLineInput, index: number) => string
  cuttingMaterial: (line: BomLineInput) => string
  editableLine: (line: never) => BomLineInput
  persistDraft: () => Promise<boolean>
}
async function open() {
  const wrapper = shallowMount(BomEditorView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true, stubs: { ElTableColumn: { template: '<div />' } } } })
  await flushPromises()
  const vm = wrapper.vm as unknown as Editor
  vm.sections.forEach(section => { section.lines = [] })
  vm.activeSectionIndex = vm.sections.findIndex(section => section.title === '面料类')
  return { wrapper, vm, fabric: vm.sections[vm.activeSectionIndex]!, cutting: vm.sections.find(section => section.title === '裁剪明细')! }
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchBomForEdit).mockResolvedValue(structuredClone(versioned) as never)
  vi.mocked(api.fetchBomEditorReferenceOptions).mockResolvedValue({ auxiliary_products: [], accessory_materials: [], fabric_materials: [], fabric_specifications: [], fabric_widths: [], product_colors: [] } as never)
})

describe('BOM 未保存面料来源', () => {
  it('分类把裁剪明细紧接在面料下面', async () => {
    const { wrapper } = await open()
    try { expect(wrapper.findAll('.section-tabs button span').map(item => item.text())).toEqual(['型材', '五金', '塑料', '面料', '裁剪明细', '辅料', '包材']) }
    finally { wrapper.unmount() }
  })

  it('面料录入品名后立即可选，空白行不进入候选，也不提前保存', async () => {
    const { wrapper, vm, fabric } = await open()
    try {
      await vm.addFabricLine()
      expect(vm.fabricSourceLines).toHaveLength(0)
      fabric.lines[0]!.part_name = '牛津布'
      expect(vm.fabricSourceLines).toHaveLength(1)
      expect(fabric.lines[0]!.id).toBeUndefined()
      expect(fabric.lines[0]!.client_key).toMatch(/^[\da-f-]{36}$/)
      expect(api.saveBomDraft).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })

  it('只选择面料材质或规格而未填写裁片名称，也能成为来源', async () => {
    const { wrapper, vm, fabric } = await open()
    try {
      await vm.addFabricLine()
      const source = fabric.lines[0]!
      source.source_fabric_material_id = 'fabric-material'
      source.material = '牛津布'
      expect(source.part_name).toBe('')
      expect(vm.fabricSourceLines).toHaveLength(1)
      source.source_fabric_material_id = null
      source.source_fabric_specification_id = 'fabric-specification'
      expect(vm.fabricSourceLines).toHaveLength(1)
    } finally { wrapper.unmount() }
  })

  it('选择草稿面料后可校验并一起保存；移除来源后会提示重选', async () => {
    const { wrapper, vm, fabric, cutting } = await open()
    try {
      await vm.addFabricLine()
      const source = fabric.lines[0]!
      source.part_name = '牛津布'
      const line = { ...vm.blankLine('套'), part_name: '床面', source_cutting_material_id: 'cutting-material', cutting_pieces_per_set: 2, fabric_meters_per_piece: '0.5', cutting_sets_per_product: 1 }
      vm.editingLineDraft = line
      vm.editingFabricSourceKey = source.client_key!
      expect(vm.editingLineDraft.fabric_source_client_key).toBe(source.client_key)
      expect(vm.editingLineDraft.fabric_source_line_id).toBeNull()
      expect(vm.lineFieldError(cutting, vm.editingLineDraft, 0)).toBe('')
      cutting.lines.push(vm.editingLineDraft)
      vi.mocked(api.saveBomDraft).mockRejectedValueOnce(new Error('本次保存失败'))
      expect(await vm.persistDraft()).toBe(false)
      expect(api.saveBomDraft).toHaveBeenCalledTimes(1)
      expect(api.saveBomDraft).toHaveBeenCalledWith('b1', vm.sections, 'v1')
      expect(cutting.lines[0]!.fabric_source_client_key).toBe(source.client_key)
      fabric.lines.splice(0, 1)
      expect(vm.lineFieldError(cutting, cutting.lines[0]!, 0)).toContain('请选择当前 BOM 中的来源面料')
    } finally { wrapper.unmount() }
  })

  it('切换到已保存面料清掉草稿引用，连续新增不会复用行标识', async () => {
    const { wrapper, vm, fabric } = await open()
    try {
      await vm.addFabricLine()
      const source = fabric.lines[0]!
      source.part_name = '牛津布'
      fabric.lines.push({ ...vm.blankLine('米'), id: 'saved-fabric', part_name: '网布' })
      vm.editingLineDraft = vm.blankLine('套')
      vm.editingFabricSourceKey = source.client_key!
      vm.editingFabricSourceKey = 'saved-fabric'
      expect(vm.editingLineDraft.fabric_source_line_id).toBe('saved-fabric')
      expect(vm.editingLineDraft.fabric_source_client_key).toBeNull()
      const next = vm.followingLineDraft(fabric, source)
      expect(next.client_key).toBeTruthy()
      expect(next.client_key).not.toBe(source.client_key)
    } finally { wrapper.unmount() }
  })

  it('保存成功后采用服务端正式行 ID，重新打开时不再依赖临时标识', async () => {
    const { wrapper, vm, fabric, cutting } = await open()
    try {
      await vm.addFabricLine()
      fabric.lines[0]!.part_name = '牛津布'
      vm.editingLineDraft = { ...vm.blankLine('套'), part_name: '床面', source_cutting_material_id: 'cutting-material', cutting_pieces_per_set: 2, fabric_meters_per_piece: '0.5', cutting_sets_per_product: 1 }
      vm.editingFabricSourceKey = fabric.lines[0]!.client_key!
      cutting.lines.push(vm.editingLineDraft)
      vi.mocked(api.saveBomDraft).mockImplementationOnce(async (_id, sections) => {
        const saved: BomSectionInput[] = JSON.parse(JSON.stringify(sections))
        saved.find(section => section.title === '面料类')!.lines[0]!.id = 'saved-fabric'
        const savedCutting = saved.find(section => section.title === '裁剪明细')!.lines[0]!
        savedCutting.id = 'saved-cutting'
        savedCutting.fabric_source_line_id = 'saved-fabric'
        delete savedCutting.fabric_source_client_key
        return { data: { ...versioned.data, sections: saved }, etag: 'v2' } as never
      })
      expect(await vm.persistDraft()).toBe(true)
      const savedCutting = vm.sections.find(section => section.title === '裁剪明细')!.lines[0]!
      expect(savedCutting.fabric_source_line_id).toBe('saved-fabric')
      expect(savedCutting.fabric_source_client_key).toBeUndefined()
      expect(vm.fabricSourceLines[0]!.id).toBe('saved-fabric')
    } finally { wrapper.unmount() }
  })

  it('空或斜杠材质随来源面料变化，有效裁剪材质及手工输入优先', async () => {
    const { wrapper, vm, fabric } = await open()
    try {
      await vm.addFabricLine()
      const source = fabric.lines[0]!
      Object.assign(source, { material: '涤纶', source_fabric_material_id: 'polyester' })
      vm.editingLineDraft = { ...vm.blankLine('套'), material: ' / ' }
      vm.editingFabricSourceKey = source.client_key!
      expect(vm.cuttingMaterial(vm.editingLineDraft)).toBe('涤纶')
      expect(vm.editingLineDraft.material).toBe(' / ')
      source.material = '棉'
      expect(vm.cuttingMaterial(vm.editingLineDraft)).toBe('棉')
      vm.editingLineDraft.material = ''
      expect(vm.cuttingMaterial(vm.editingLineDraft)).toBe('棉')
      vm.editingLineDraft.material = '尼龙'
      expect(vm.cuttingMaterial(vm.editingLineDraft)).toBe('尼龙')
      fabric.lines = []
      vm.editingLineDraft.material = '/'
      expect(vm.cuttingMaterial(vm.editingLineDraft)).toBe('/')
    } finally { wrapper.unmount() }
  })

  it('重新打开已继承材质的裁剪行，保留原始空值以便再次换来源', async () => {
    const { wrapper, vm, fabric } = await open()
    try {
      fabric.lines.push({ ...vm.blankLine('米'), id: 'saved-fabric', part_name: '网布', material: '涤纶' })
      const reopened = vm.editableLine({ ...vm.blankLine('套'), id: 'saved-cutting', material: '涤纶', cutting_material_original: '/', fabric_source_line_id: 'saved-fabric' } as never)
      expect(reopened.material).toBe('/')
      fabric.lines[0]!.material = '棉'
      expect(vm.cuttingMaterial(reopened)).toBe('棉')
    } finally { wrapper.unmount() }
  })
})

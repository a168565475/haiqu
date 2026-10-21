import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElOption, ElSelect } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/boms'
import type { BomLineInput, BomSectionInput } from '@/types/bom'
import BomEditorView from './BomEditorView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { bomId: 'b1' } }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/boms', async original => ({ ...await original<typeof import('@/api/boms')>(), fetchBomForEdit: vi.fn(), previewBomMaterialSave: vi.fn(), saveBomDraft: vi.fn(), fetchBomEditorReferenceOptions: vi.fn(), fetchBomFlowMaterials: vi.fn(), previewBomMaterialFlow: vi.fn() }))
vi.mock('@/api/productionData', async original => ({ ...await original<typeof import('@/api/productionData')>(), fetchAllProductionDataRecords: vi.fn().mockResolvedValue([]) }))

const versioned = { data: { id: 'b1', status: 'PENDING_CONFIRMATION', order_quantity: '1000', current_order_quantity: '1000', product_information_confirmed: true, sections: [], configured_field_labels: {} }, etag: 'v1' }
interface Editor {
  sections: BomSectionInput[]
  activeSectionIndex: number
  editingLineDraft: BomLineInput
  editingFabricSourceKey: string
  fabricSourceLines: BomLineInput[]
  lineDrawerVisible: boolean
  addFabricLine: () => Promise<void>
  openLineDrawer: (index: number) => void
  applyLineDrawer: () => Promise<void>
  cancelLineDrawer: () => Promise<void>
  blankLine: (unit?: string) => BomLineInput
  followingLineDraft: (section: BomSectionInput, line: BomLineInput) => BomLineInput
  lineFieldError: (section: BomSectionInput, line: BomLineInput, index: number) => string
  syncCuttingSourceAttributes: (line: BomLineInput) => void
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
async function openFabricDrawer(values: Partial<BomLineInput> = {}) {
  const editor = await open()
  editor.fabric.lines.push({ ...editor.vm.blankLine('米'), part_name: '床面', material: '涤纶', specification: '400×300D',
    source_fabric_material_id: 'material-old', source_fabric_specification_id: 'spec-old',
    source_fabric_width_id: 'width-old', fabric_width: '150', source_product_color_id: 'color-old',
    fabric_color_card: 'A', fabric_color_name: '深宝蓝', fabric_color_code: '01', unit_consumption: '1.5', ...values })
  editor.vm.openLineDrawer(0)
  await flushPromises()
  return editor
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchBomForEdit).mockResolvedValue(structuredClone(versioned) as never)
  vi.mocked(api.fetchBomEditorReferenceOptions).mockResolvedValue({ auxiliary_products: [], accessory_materials: [],
    fabric_materials: [{ id: 'material-old', material_name: '涤纶' }, { id: 'material-new', material_name: '尼龙' }],
    fabric_specifications: [{ id: 'spec-old', specification_name: '400×300D' }, { id: 'spec-new', specification_name: '600D' }],
    fabric_widths: [{ id: 'width-old', width_value: '150' }, { id: 'width-new', width_value: '160' }],
    product_colors: [{ id: 'color-old', color_card: 'A', color_name: '深宝蓝', color_code: '01' }, { id: 'color-new', color_card: 'B', color_name: '黑色', color_code: '02' }],
  } as never)
  vi.mocked(api.fetchBomFlowMaterials).mockReset().mockResolvedValue({ data: [], meta: { page: 1, page_size: 100, total: 0, total_pages: 0 } })
  vi.mocked(api.previewBomMaterialFlow).mockReset().mockResolvedValue({ suggested_purchase_meters: '1500' })
  vi.mocked(api.previewBomMaterialSave).mockResolvedValue({ confirmation_token: null, new_materials: [] })
  vi.mocked(api.saveBomDraft).mockReset()
})

describe('BOM 面料保存时自动关联原料', () => {
  it('无需查询或手选库存原料即可应用面料，保留生产维护参数并核算用量', async () => {
    const { wrapper, vm, fabric } = await openFabricDrawer()
    try {
      expect(wrapper.find('[aria-label="来源原材料"]').exists()).toBe(false)
      expect(api.fetchBomFlowMaterials).not.toHaveBeenCalled()
      await vm.applyLineDrawer()
      expect(vm.lineDrawerVisible).toBe(false)
      expect(fabric.lines[0]).toMatchObject({ source_inventory_material_id: null, material: '涤纶', specification: '400×300D',
        source_fabric_material_id: 'material-old', source_fabric_specification_id: 'spec-old', unit: '米', unit_consumption: '1.5' })
      expect(api.previewBomMaterialFlow).toHaveBeenCalledWith({ kind: 'FABRIC', order_quantity: '1000', unit_consumption: '1.5' })
      expect(api.saveBomDraft).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })

  it('已关联面料仍能更换材质规格色卡门幅，保存完整参数并采用服务端新关联', async () => {
    const { wrapper, vm, fabric } = await openFabricDrawer({ id: 'saved-fabric', source_inventory_material_id: 'old-source', raw_material: 'ML-OLD' })
    try {
      for (const [label, value] of [['面料材质', 'material-new'], ['面料规格', 'spec-new'], ['面料色卡颜色色号', 'color-new'], ['面料门幅', 'width-new']]) {
        const select = wrapper.findAllComponents(ElSelect).find(item => item.attributes('aria-label') === label)
        expect(select, `${label}应可编辑`).toBeDefined()
        expect(select!.props('disabled')).not.toBe(true)
        select!.vm.$emit('update:modelValue', value)
        select!.vm.$emit('change', value)
      }
      await flushPromises()
      expect(fabric.lines[0]).toMatchObject({ material: '涤纶', specification: '400×300D', source_inventory_material_id: 'old-source' })
      await vm.applyLineDrawer()
      expect(vm.lineDrawerVisible).toBe(false)
      vi.mocked(api.saveBomDraft).mockImplementationOnce(async (_id, sections) => {
        const saved: BomSectionInput[] = JSON.parse(JSON.stringify(sections))
        Object.assign(saved.find(section => section.title === '面料类')!.lines[0]!, { source_inventory_material_id: 'new-source', raw_material: 'ML-NEW' })
        return { data: { ...versioned.data, sections: saved }, etag: 'v2' } as never
      })
      expect(await vm.persistDraft()).toBe(true)
      const submitted = vi.mocked(api.saveBomDraft).mock.calls[0]![1].find(section => section.title === '面料类')!.lines[0]
      expect(submitted).toMatchObject({ id: 'saved-fabric', part_name: '床面', source_inventory_material_id: 'old-source',
        source_fabric_material_id: 'material-new', material: '尼龙', source_fabric_specification_id: 'spec-new', specification: '600D',
        source_fabric_width_id: 'width-new', fabric_width: '160', source_product_color_id: 'color-new',
        fabric_color_card: 'B', fabric_color_name: '黑色', fabric_color_code: '02', unit_consumption: '1.5', unit: '米' })
      expect(vm.fabricSourceLines[0]).toMatchObject({ source_inventory_material_id: 'new-source', raw_material: 'ML-NEW',
        source_fabric_material_id: 'material-new', material: '尼龙', source_fabric_specification_id: 'spec-new', specification: '600D', fabric_width: '160' })
      expect(api.saveBomDraft).toHaveBeenCalledWith('b1', expect.any(Array), 'v1', { intent: 'draft' })
    } finally { wrapper.unmount() }
  })

  it('取消面料参数修改不回写本地行、不保存或重算', async () => {
    const { wrapper, vm, fabric } = await openFabricDrawer({ id: 'saved-fabric', source_inventory_material_id: 'old-source' })
    try {
      const material = wrapper.findAllComponents(ElSelect).find(item => item.attributes('aria-label') === '面料材质')
      expect(material).toBeDefined()
      material!.vm.$emit('update:modelValue', 'material-new')
      material!.vm.$emit('change', 'material-new')
      await flushPromises()
      expect(vm.editingLineDraft.material).toBe('尼龙')
      await vm.cancelLineDrawer()
      expect(vm.lineDrawerVisible).toBe(false)
      expect(fabric.lines[0]).toMatchObject({ source_inventory_material_id: 'old-source', source_fabric_material_id: 'material-old', material: '涤纶' })
      expect(api.previewBomMaterialFlow).not.toHaveBeenCalled()
      expect(api.saveBomDraft).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })

  it('缺少门幅快照时不会把库存原料编码显示为门幅', async () => {
    const { wrapper } = await openFabricDrawer({ source_inventory_material_id: 'old-source', raw_material: 'ML-OLD', source_fabric_width_id: 'inactive-width', fabric_width: '' })
    try {
      const width = wrapper.findAllComponents(ElSelect).find(item => item.attributes('aria-label') === '面料门幅')!
      expect(width.props('placeholder')).toBe('选择门幅')
      const snapshot = width.findAllComponents(ElOption).find(item => item.props('value') === 'inactive-width')
      expect(snapshot?.props('label')).toBe('已停用门幅')
    } finally { wrapper.unmount() }
  })

  it('面料用量核算失败仍阻止应用，保留原行及库存关联', async () => {
    const { wrapper, vm, fabric } = await openFabricDrawer({ id: 'saved-fabric', source_inventory_material_id: 'old-source' })
    try {
      vm.editingLineDraft.unit_consumption = '2'
      vi.mocked(api.previewBomMaterialFlow).mockRejectedValueOnce(new Error('核算失败'))
      await vm.applyLineDrawer()
      expect(vm.lineDrawerVisible).toBe(true)
      expect(fabric.lines[0]).toMatchObject({ source_inventory_material_id: 'old-source', unit_consumption: '1.5' })
      expect(api.saveBomDraft).not.toHaveBeenCalled()
    } finally { wrapper.unmount() }
  })
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
      const line = { ...vm.blankLine('套'), part_name: '床面', specification: '120×60cm', source_cutting_material_id: 'cutting-material', cutting_pieces_per_set: 2, cutting_sets_per_product: 1 }
      vm.editingLineDraft = line
      vm.editingFabricSourceKey = source.client_key!
      expect(vm.editingLineDraft.fabric_source_client_key).toBe(source.client_key)
      expect(vm.editingLineDraft.fabric_source_line_id).toBeNull()
      expect(vm.lineFieldError(cutting, vm.editingLineDraft, 0)).toBe('')
      cutting.lines.push(vm.editingLineDraft)
      vi.mocked(api.saveBomDraft).mockRejectedValueOnce(new Error('本次保存失败'))
      expect(await vm.persistDraft()).toBe(false)
      expect(api.saveBomDraft).toHaveBeenCalledTimes(1)
      expect(api.saveBomDraft).toHaveBeenCalledWith('b1', vm.sections, 'v1', { intent: 'draft' })
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
      vm.editingLineDraft = { ...vm.blankLine('套'), part_name: '床面', specification: '120×60cm', source_cutting_material_id: 'cutting-material', cutting_pieces_per_set: 2, cutting_sets_per_product: 1 }
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

  it('选择来源和再次同步时，裁剪材质与颜色始终采用面料值', async () => {
    const { wrapper, vm, fabric } = await open()
    try {
      await vm.addFabricLine()
      const source = fabric.lines[0]!
      Object.assign(source, { material: '涤纶', fabric_color_name: '黑色', source_fabric_material_id: 'polyester' })
      vm.editingLineDraft = { ...vm.blankLine('套'), material: '210D', cutting_color: '白色' }
      vm.editingFabricSourceKey = source.client_key!
      expect(vm.editingLineDraft).toMatchObject({ material: '涤纶', cutting_color: '黑色' })
      source.material = '棉'
      source.fabric_color_name = '蓝色'
      vm.syncCuttingSourceAttributes(vm.editingLineDraft)
      expect(vm.editingLineDraft).toMatchObject({ material: '棉', cutting_color: '蓝色' })
      source.fabric_color_name = ''
      source.fabric_color_code = 'BLUE-01'
      vm.syncCuttingSourceAttributes(vm.editingLineDraft)
      expect(vm.editingLineDraft.cutting_color).toBe('BLUE-01')
      fabric.lines = []
      vm.syncCuttingSourceAttributes(vm.editingLineDraft)
      expect(vm.editingLineDraft).toMatchObject({ material: '', cutting_color: '' })
    } finally { wrapper.unmount() }
  })

  it('重新打开裁剪行不再恢复旧材质，保存前采用最新来源属性', async () => {
    const { wrapper, vm, fabric } = await open()
    try {
      fabric.lines.push({ ...vm.blankLine('米'), id: 'saved-fabric', part_name: '网布', material: '涤纶', fabric_color_name: '黑色' })
      const reopened = vm.editableLine({ ...vm.blankLine('套'), id: 'saved-cutting', part_name: '外袋', specification: '20', material: '涤纶', cutting_material_original: '210D', fabric_source_line_id: 'saved-fabric', fabric_meters_per_set: '0.5' } as never)
      expect(reopened.material).toBe('涤纶')
      vm.sections.find(section => section.title === '裁剪明细')!.lines.push(reopened)
      Object.assign(fabric.lines[0]!, { material: '棉', fabric_color_name: '蓝色' })
      vi.mocked(api.saveBomDraft).mockImplementationOnce(async (_id, sections) => ({ data: { ...versioned.data, sections: JSON.parse(JSON.stringify(sections)) }, etag: 'v2' }) as never)
      expect(await vm.persistDraft()).toBe(true)
      const submitted = vi.mocked(api.saveBomDraft).mock.calls[0]![1].find(section => section.title === '裁剪明细')!.lines[0]
      expect(submitted).toMatchObject({ material: '棉', cutting_color: '蓝色' })
    } finally { wrapper.unmount() }
  })

  it('裁剪列表与行编辑不显示材质颜色输入，来源面料仍可选择', async () => {
    const { wrapper, vm, fabric, cutting } = await open()
    try {
      fabric.lines.push({ ...vm.blankLine('米'), id: 'saved-fabric', part_name: '网布', material: '涤纶', fabric_color_name: '黑色' })
      cutting.lines.push({ ...vm.blankLine('套'), id: 'saved-cutting', part_name: '外袋', specification: '20', fabric_source_line_id: 'saved-fabric' })
      vm.activeSectionIndex = vm.sections.indexOf(cutting)
      vm.openLineDrawer(0)
      await flushPromises()
      const labels = wrapper.get('.cutting-table').findAll('[label]').map(column => column.attributes('label'))
      expect(labels).not.toContain('材质')
      expect(labels).not.toContain('颜色')
      expect(wrapper.find('[aria-label="材质"]').exists()).toBe(false)
      expect(wrapper.find('[aria-label="来源面料"]').exists()).toBe(true)
    } finally { wrapper.unmount() }
  })
})

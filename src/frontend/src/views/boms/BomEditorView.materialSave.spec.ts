import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/boms'
import HardwareRawMaterialCreateDialog from '@/components/HardwareRawMaterialCreateDialog.vue'
import type { BomLineInput, BomSectionInput } from '@/types/bom'
import type { RawMaterialInput } from '@/types/rawMaterial'
import BomEditorView from './BomEditorView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { bomId: 'b1' } }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
const permissions = vi.hoisted(() => ({ editable: true }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: (permission: string) => permission !== 'boms.change_bom' || permissions.editable, moduleCan: () => true }) }))
vi.mock('@/api/boms', async original => ({ ...await original<typeof import('@/api/boms')>(), fetchBomForEdit: vi.fn(), previewBomMaterialSave: vi.fn(), saveBomDraft: vi.fn(), verifyBom: vi.fn(), fetchBomEditorReferenceOptions: vi.fn(), fetchBomHardwareMaterials: vi.fn(), fetchBomHardwareMaterialGroups: vi.fn(), fetchBomPlasticMaterials: vi.fn(), fetchBomPackagingMaterials: vi.fn(), fetchBomSemiFinishedMaterials: vi.fn() }))
vi.mock('@/api/productionData', async original => ({ ...await original<typeof import('@/api/productionData')>(), fetchAllProductionDataRecords: vi.fn().mockResolvedValue([]) }))

const versioned = { data: { id: 'b1', status: 'PENDING_CONFIRMATION', order_quantity: '1000', current_order_quantity: '1000', product_information_confirmed: true, sections: [], configured_field_labels: {} }, etag: 'v1' }
const additions = { confirmation_token: 'token-1', new_materials: [{ key: 'new-1', item_type: 'MATERIAL', category_name: '辅料', material_name: '织带', specification: '25mm', width: '', color_name: '黑色', color_label: '', material: '涤纶', unit_name: '米', warehouse_name: '原料仓', locations: [{ section_title: '辅料类', line_number: 1 }, { section_title: '辅料类', line_number: 2 }] }] }
interface Editor {
  sections: BomSectionInput[]
  quantityReason: string
  activeSectionIndex: number
  editingLineDraft: BomLineInput
  addCatalogLine: () => void
  followingLineDraft: (section: BomSectionInput, line: BomLineInput) => BomLineInput
  blankLine: (unit?: string) => BomLineInput
  persistDraft: () => Promise<boolean>
  submitVerification: () => Promise<void>
  confirmHardwareSelection: () => void
  confirmPlasticSelection: () => void
  confirmPackagingSelection: () => void
  confirmCuttingSelection: () => void
}
let wrapper: VueWrapper | undefined
async function open() {
  wrapper = shallowMount(BomEditorView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true, stubs: { ElTableColumn: { template: '<div />' }, BomMaterialCreateDialogs: false } } })
  await flushPromises()
  const vm = wrapper.vm as unknown as Editor
  vm.sections.forEach(section => { section.lines = [] })
  const auxiliary = vm.sections.find(section => section.title === '辅料类')!
  auxiliary.lines.push({ ...vm.blankLine('米'), part_name: '织带', material: '涤纶', specification: '25mm', unit_consumption: '1', source_accessory_product_name_id: 'name', source_accessory_specification_id: 'spec', source_accessory_color_id: 'color', source_accessory_material_id: 'material' })
  return { wrapper, vm, auxiliary }
}
beforeEach(() => {
  vi.clearAllMocks()
  permissions.editable = true
  vi.mocked(api.fetchBomForEdit).mockResolvedValue(structuredClone(versioned) as never)
  vi.mocked(api.fetchBomEditorReferenceOptions).mockResolvedValue({ auxiliary_products: [], accessory_materials: [], fabric_materials: [], fabric_specifications: [], fabric_widths: [], product_colors: [] })
  vi.mocked(api.previewBomMaterialSave).mockResolvedValue({ confirmation_token: null, new_materials: [] })
  for (const fetcher of [api.fetchBomHardwareMaterials, api.fetchBomPlasticMaterials, api.fetchBomPackagingMaterials, api.fetchBomSemiFinishedMaterials]) vi.mocked(fetcher).mockResolvedValue({ data: [], meta: { page: 1, page_size: 20, total: 0, total_pages: 0 } })
  vi.mocked(api.saveBomDraft).mockImplementation(async (_id, sections) => ({ data: { ...versioned.data, sections: JSON.parse(JSON.stringify(sections)) }, etag: 'v2' }) as never)
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

describe('整份 BOM 原料自动保存', () => {
  it('新建面料与复用空白行默认米，连续新增面料也使用米且不改原行', async () => {
    const { vm, auxiliary } = await open()
    vm.activeSectionIndex = vm.sections.findIndex(section => section.title === '面料类')
    const fabric = vm.sections[vm.activeSectionIndex]!
    vm.addCatalogLine()
    expect(vm.editingLineDraft.unit).toBe('米')
    expect(fabric.lines[0]!.unit).toBe('米')
    fabric.lines[0]!.unit = ''
    vm.addCatalogLine()
    expect(fabric.lines).toHaveLength(1)
    expect(vm.editingLineDraft.unit).toBe('米')
    const current = { ...vm.blankLine('码'), part_name: '旧面料', unit_consumption: '2.5' }
    const next = vm.followingLineDraft(fabric, current)
    expect(next).toMatchObject({ unit: '米', part_name: '', unit_consumption: '' })
    expect(current).toMatchObject({ unit: '码', part_name: '旧面料', unit_consumption: '2.5' })
    expect(vm.followingLineDraft(auxiliary, current).unit).toBe('码')
    expect(api.saveBomDraft).not.toHaveBeenCalled()
  })

  it('未重选的历史目录面料保存保留原单位和单耗，不改快照', async () => {
    const { vm } = await open()
    const fabric = vm.sections.find(section => section.title === '面料类')!
    const snapshot = { schema_version: 1 as const, catalog_id: 'fabric-a', catalog_version: 'old', category_key: 'FABRIC', template_key: 'FABRIC',
      name: '旧面料', scope: 'BASE' as const, processing_state: 'RAW' as const, processing_stage: 'RAW', display_name: '旧面料 / 码',
      attributes: { material: '涤纶' }, unit_id: 'yard', unit_name: '码' }
    fabric.lines.push({ ...vm.blankLine('码'), id: 'saved-fabric', material_catalog_id: 'fabric-a', material_selection_snapshot: snapshot,
      part_name: '旧面料', unit_consumption: '2.5' })
    expect(await vm.persistDraft()).toBe(true)
    const submitted = vi.mocked(api.saveBomDraft).mock.calls[0]![1].find(section => section.title === '面料类')!.lines[0]!
    expect(submitted).toMatchObject({ unit: '码', unit_consumption: '2.5', material_selection_snapshot: snapshot })
    expect(snapshot.unit_name).toBe('码')
  })

  it.each([
    [412, '原料品名选项已变化，请刷新该品名后重选；BOM草稿仍保留。', '原料品名选项已变化'],
    [412, '数据已被其他人修改，请刷新后重试。', '该 BOM 已被其他人修改'],
    [428, '请选择带内容版本的原料品名。', '请选择带内容版本的原料品名'],
    [428, '修改请求必须携带 If-Match。', '版本信息'],
  ])('版本错误%s按真实服务端原因显示且保留草稿：%s', async (status, message, expected) => {
    const notify = vi.spyOn(ElMessage, 'error')
    vi.mocked(api.previewBomMaterialSave).mockRejectedValueOnce(Object.assign(new AxiosError(message), {
      response: { status, data: { error: { code: status === 412 ? 'PRECONDITION_FAILED' : 'PRECONDITION_REQUIRED', message, field_errors: {} } } },
    }))
    const { vm, auxiliary } = await open()
    expect(await vm.persistDraft()).toBe(false)
    expect(notify).toHaveBeenLastCalledWith(expect.stringContaining(expected))
    expect(auxiliary.lines[0]!.part_name).toBe('织带')
    expect(api.saveBomDraft).not.toHaveBeenCalled()
    expect(api.previewBomMaterialSave).toHaveBeenCalledTimes(1)
    notify.mockRestore()
  })
  it('全部匹配时先预检，再直接保存，不调用旧确认接口', async () => {
    const { vm } = await open()
    expect(await vm.persistDraft()).toBe(true)
    expect(api.previewBomMaterialSave).toHaveBeenCalledWith('b1', expect.any(Array), 'v1', { intent: 'draft' })
    expect(api.saveBomDraft).toHaveBeenCalledWith('b1', expect.any(Array), 'v1', { intent: 'draft' })
    expect(vi.mocked(api.previewBomMaterialSave).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(api.saveBomDraft).mock.invocationCallOrder[0]!)
    expect(api.verifyBom).not.toHaveBeenCalled()
  })

  it('仅有确认权限时只确认已保存 BOM，不预检新增或提交编辑内容', async () => {
    permissions.editable = false
    vi.mocked(api.verifyBom).mockResolvedValue({ ...versioned, data: { ...versioned.data, status: 'VERIFIED' } } as never)
    const { vm } = await open()
    vm.quantityReason = '核对数量'
    await vm.submitVerification()
    expect(api.verifyBom).toHaveBeenCalledWith('b1', '核对数量', 'v1')
    expect(api.previewBomMaterialSave).not.toHaveBeenCalled()
    expect(api.saveBomDraft).not.toHaveBeenCalled()
  })

  it('需要新增时自动携带预检令牌保存，不再弹出确认清单', async () => {
    vi.mocked(api.previewBomMaterialSave).mockResolvedValue(additions)
    const { wrapper: page, vm } = await open()
    expect(await vm.persistDraft()).toBe(true)
    await flushPromises()
    expect(page.find('[data-testid="bom-material-save-preview"]').exists()).toBe(false)
    expect(api.saveBomDraft).toHaveBeenCalledTimes(1)
    expect(api.saveBomDraft).toHaveBeenCalledWith('b1', expect.any(Array), 'v1', { intent: 'draft', confirmation_token: 'token-1' })
  })

  it('确认 BOM 使用同一份预检参数和令牌进行一次原子 PATCH', async () => {
    vi.mocked(api.previewBomMaterialSave).mockResolvedValue(additions)
    const { vm } = await open()
    vm.quantityReason = '数量核对说明'
    await vm.submitVerification()
    const previewSections = vi.mocked(api.previewBomMaterialSave).mock.calls[0]![1]
    expect(api.saveBomDraft).toHaveBeenCalledTimes(1)
    expect(api.saveBomDraft).toHaveBeenCalledWith('b1', previewSections, 'v1', { intent: 'verify', quantity_confirmation_reason: '数量核对说明', confirmation_token: 'token-1' })
    expect(api.verifyBom).not.toHaveBeenCalled()
  })

  it.each(['empty', 'normal'] as const)('确认 BOM 遇到%s来源面料快照时继承可用属性并正常预检保存', async snapshotKind => {
    const { vm } = await open()
    const fabric = vm.sections.find(section => section.title === '面料类')!
    const cutting = vm.sections.find(section => section.title === '裁剪明细')!
    const snapshot = snapshotKind === 'empty' ? {} : {
      schema_version: 1, catalog_id: 'fabric-catalog', catalog_version: 'v1', category_key: 'FABRIC', template_key: 'FABRIC',
      name: '网布', scope: 'BASE', processing_state: 'RAW', processing_stage: 'RAW', display_name: '网布',
      attributes: { material: '快照涤纶', width: '1.6', color: '快照蓝色', fabric_spec: '600D' }, unit_id: 'meter', unit_name: '米',
    }
    // 旧面料可能已没有目录关联，接口仍返回空对象快照。
    fabric.lines.push({ ...vm.blankLine('米'), id: 'saved-fabric', part_name: '网布', material: '旧字段涤纶',
      specification: '600D', fabric_width: '1.5', fabric_color_name: '旧字段黑色', unit_consumption: '1.5',
      material_selection_snapshot: snapshot as never })
    cutting.lines.push({ ...vm.blankLine('套'), id: 'saved-cutting', part_name: '外袋', fabric_source_line_id: 'saved-fabric',
      cutting_pieces_per_set: 2, cutting_sets_per_product: 1 })
    vm.quantityReason = '确认用料'

    await vm.submitVerification()

    expect(api.previewBomMaterialSave).toHaveBeenCalledTimes(1)
    expect(api.saveBomDraft).toHaveBeenCalledTimes(1)
    const previewSections = vi.mocked(api.previewBomMaterialSave).mock.calls[0]![1]
    expect(api.saveBomDraft).toHaveBeenCalledWith('b1', previewSections, 'v1', { intent: 'verify', quantity_confirmation_reason: '确认用料' })
    expect(previewSections.find(section => section.title === '裁剪明细')!.lines[0]).toMatchObject({
      fabric_source_line_id: 'saved-fabric', specification: '600D',
      material: snapshotKind === 'empty' ? '旧字段涤纶' : '快照涤纶',
      fabric_width: snapshotKind === 'empty' ? '1.5' : '1.6',
      cutting_color: snapshotKind === 'empty' ? '旧字段黑色' : '快照蓝色',
    })
    expect(previewSections.find(section => section.title === '面料类')!.lines[0]!.material_selection_snapshot).toEqual(snapshot)
    expect(api.verifyBom).not.toHaveBeenCalled()
  })

  it('确认 BOM 时来源面料已丢失仍提示重新选择，不预检、不保存', async () => {
    const notify = vi.spyOn(ElMessage, 'warning')
    try {
      const { vm } = await open()
      const cutting = vm.sections.find(section => section.title === '裁剪明细')!
      cutting.lines.push({ ...vm.blankLine('套'), id: 'saved-cutting', part_name: '外袋', fabric_source_line_id: 'deleted-fabric',
        material: '旧材质', specification: '600D', cutting_color: '旧颜色', cutting_pieces_per_set: 2, cutting_sets_per_product: 1 })

      await vm.submitVerification()

      expect(notify).toHaveBeenCalledWith(expect.stringContaining('请选择当前 BOM 中的来源面料'))
      expect(api.previewBomMaterialSave).not.toHaveBeenCalled()
      expect(api.saveBomDraft).not.toHaveBeenCalled()
      expect(api.verifyBom).not.toHaveBeenCalled()
      expect(cutting.lines[0]!.fabric_source_line_id).toBe('deleted-fabric')
    } finally { notify.mockRestore() }
  })

  it('确认 BOM 时目录裁片缺少属性对象仍提示补齐，不补造属性或提交保存', async () => {
    const notify = vi.spyOn(ElMessage, 'warning')
    try {
      const { vm } = await open()
      const fabric = vm.sections.find(section => section.title === '面料类')!
      const cutting = vm.sections.find(section => section.title === '裁剪明细')!
      fabric.lines.push({ ...vm.blankLine('米'), id: 'saved-fabric', part_name: '网布', material: '涤纶', specification: '600D',
        fabric_width: '1.5', fabric_color_name: '黑色', unit_consumption: '1.5' })
      cutting.lines.push({ ...vm.blankLine('套'), id: 'saved-cutting', part_name: '外袋', fabric_source_line_id: 'saved-fabric',
        cutting_pieces_per_set: 2, cutting_sets_per_product: 1, material_catalog_id: 'cutting-catalog',
        material_selection: { catalog_version: 'v1', scope: 'BASE', processing_state: 'PROCESSED' } as never })

      await vm.submitVerification()

      expect(notify).toHaveBeenCalledWith('请选择具体属性和本次数量单位。')
      expect(cutting.lines[0]!.material_selection?.attributes).toBeUndefined()
      expect(api.previewBomMaterialSave).not.toHaveBeenCalled()
      expect(api.saveBomDraft).not.toHaveBeenCalled()
      expect(api.verifyBom).not.toHaveBeenCalled()
    } finally { notify.mockRestore() }
  })

  it('新增清单缺少令牌时仍停止保存，不绕过服务端确认凭据', async () => {
    vi.mocked(api.previewBomMaterialSave).mockResolvedValue({ ...additions, confirmation_token: null })
    const { vm } = await open()
    expect(await vm.persistDraft()).toBe(false)
    expect(api.saveBomDraft).not.toHaveBeenCalled()
  })

  it('预检失败时不保存，不覆盖页面行', async () => {
    vi.mocked(api.previewBomMaterialSave).mockRejectedValueOnce(new Error('预检失败'))
    const { vm, auxiliary } = await open()
    expect(await vm.persistDraft()).toBe(false)
    expect(auxiliary.lines[0]!.part_name).toBe('织带')
    expect(api.saveBomDraft).not.toHaveBeenCalled()
  })

  it('自动保存冲突时保留页面输入，不自动重试；用户重试时重新预检', async () => {
    vi.mocked(api.previewBomMaterialSave).mockResolvedValue(additions)
    vi.mocked(api.saveBomDraft).mockRejectedValueOnce(Object.assign(new AxiosError('新增清单已变化'), { response: { status: 409, data: { error: { message: '新增清单已变化，请重新检查。' } } } }))
    const { vm, auxiliary } = await open()
    expect(await vm.persistDraft()).toBe(false)
    await flushPromises()
    expect(auxiliary.lines[0]!.part_name).toBe('织带')
    expect(api.saveBomDraft).toHaveBeenCalledTimes(1)
    expect(api.previewBomMaterialSave).toHaveBeenCalledTimes(1)
    expect(await vm.persistDraft()).toBe(true)
    expect(api.previewBomMaterialSave).toHaveBeenCalledTimes(2)
    expect(api.saveBomDraft).toHaveBeenCalledTimes(2)
  })

  it('预检期间编辑内容变化时取消此次保存，保留新输入', async () => {
    let finish!: (value: typeof additions) => void
    vi.mocked(api.previewBomMaterialSave).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const { vm, auxiliary } = await open()
    const saving = vm.persistDraft()
    auxiliary.lines[0]!.notes = '刚刚补充'
    finish(additions)
    expect(await saving).toBe(false)
    expect(auxiliary.lines[0]!.notes).toBe('刚刚补充')
    expect(api.saveBomDraft).not.toHaveBeenCalled()
  })

  it.each([
    ['五金件', 'hardware-raw-material-create-dialog', '五金', 'confirmHardwareSelection', 'MATERIAL'],
    ['塑料件类', 'plastic-raw-material-create-dialog', '塑料件', 'confirmPlasticSelection', 'MATERIAL'],
    ['包材类', 'packaging-raw-material-create-dialog', '包材', 'confirmPackagingSelection', 'MATERIAL'],
    ['裁剪明细', 'cutting-raw-material-create-dialog', '面料', 'confirmCuttingSelection', 'SEMI_FINISHED'],
  ] as const)('BOM 内新增%s仅暂存，选入行时不提交临时库存 ID', async (title, testId, category, confirm, itemType) => {
    const { wrapper: page, vm } = await open()
    vm.activeSectionIndex = vm.sections.findIndex(section => section.title === title)
    const dialog = page.findAllComponents(HardwareRawMaterialCreateDialog).find(item => title === '五金件' ? item.props('categoryName') === '五金' : item.props('testId') === testId)!
    const stage = dialog.props('stageMaterial')
    expect(stage).toBeTypeOf('function')
    const payload: RawMaterialInput = { material_number: 'PENDING-001', item_type: itemType, category: 'category-id', material_name: '待新增资料', specification: '规格', unit: 'piece', color: null, material: '材质', is_packaging_auxiliary: false, box_shape: '', notes: '', warehouse_number: 'W1', warehouse_name: '原料仓' }
    await stage!(payload, { category_name: category, unit_name: '个', unit_code: 'PCS', color_name: '' })
    vm[confirm]()
    const line = vm.sections[vm.activeSectionIndex]!.lines[0]!
    expect(line.pending_raw_material).toEqual(payload)
    expect(line.source_raw_material_id).toBeNull()
    expect(line.source_inventory_material_id).toBeNull()
    expect(line.source_packaging_material_id).toBeNull()
    expect(line.source_cutting_material_id).toBeNull()
    expect(line.client_key).toMatch(/^[0-9a-f-]{36}$/)
    vm[confirm]()
    expect(vm.sections[vm.activeSectionIndex]!.lines).toHaveLength(1)
    expect(api.saveBomDraft).not.toHaveBeenCalled()
  })
})

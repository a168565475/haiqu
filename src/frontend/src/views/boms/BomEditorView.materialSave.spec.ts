import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
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
  blankLine: (unit?: string) => BomLineInput
  persistDraft: () => Promise<boolean>
  submitVerification: () => Promise<void>
  confirmMaterialSave: () => Promise<boolean>
  cancelMaterialSave: () => void
  confirmHardwareSelection: () => void
  confirmPlasticSelection: () => void
  confirmPackagingSelection: () => void
  confirmCuttingSelection: () => void
}
let wrapper: VueWrapper | undefined
async function open() {
  wrapper = shallowMount(BomEditorView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true, stubs: { ElTableColumn: { template: '<div />' } } } })
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

describe('整份 BOM 原料新增确认', () => {
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

  it('需要新增时列出合并的来源行，取消不写且保留编辑', async () => {
    vi.mocked(api.previewBomMaterialSave).mockResolvedValue(additions)
    const { wrapper: page, vm, auxiliary } = await open()
    await vm.persistDraft(); await flushPromises()
    const modal = page.get('[data-testid="bom-material-save-preview"]')
    expect(modal.text()).toContain('织带')
    expect(modal.text()).toContain('25mm')
    expect(modal.text()).toContain('黑色')
    expect(modal.findAll('th').map(cell => cell.text())).toEqual(['分区', '行号', '品名', '规格', '颜色', '材质', '单位', '仓库'])
    expect(modal.text()).toContain('原料仓')
    expect(modal.findAll('[data-testid="bom-material-save-preview-row"]')).toHaveLength(1)
    expect(modal.text()).toContain('1、2')
    expect(api.saveBomDraft).not.toHaveBeenCalled()
    vm.cancelMaterialSave(); await flushPromises()
    expect(auxiliary.lines[0]!.part_name).toBe('织带')
    expect(api.saveBomDraft).not.toHaveBeenCalled()
  })

  it('确认 BOM 使用同一份预检参数和令牌进行一次原子 PATCH', async () => {
    vi.mocked(api.previewBomMaterialSave).mockResolvedValue(additions)
    const { vm } = await open()
    vm.quantityReason = '数量核对说明'
    await vm.submitVerification()
    expect(api.saveBomDraft).not.toHaveBeenCalled()
    const previewSections = vi.mocked(api.previewBomMaterialSave).mock.calls[0]![1]
    await vm.confirmMaterialSave()
    expect(api.saveBomDraft).toHaveBeenCalledTimes(1)
    expect(api.saveBomDraft).toHaveBeenCalledWith('b1', previewSections, 'v1', { intent: 'verify', quantity_confirmation_reason: '数量核对说明', confirmation_token: 'token-1' })
    expect(api.verifyBom).not.toHaveBeenCalled()
  })

  it('新增面料清单同时显示规格、门幅和完整色卡身份', async () => {
    vi.mocked(api.previewBomMaterialSave).mockResolvedValue({ ...additions, new_materials: [{ ...additions.new_materials[0]!, category_name: '面料', specification: '400*300D', width: '150', color_label: '色卡 A / 001 / 黑色' }] })
    const { wrapper: page, vm } = await open()
    await vm.persistDraft(); await flushPromises()
    const cells = page.get('[data-testid="bom-material-save-preview-row"]').findAll('td')
    expect(cells[3]!.text()).toContain('400*300D')
    expect(cells[3]!.text()).toContain('门幅 150')
    expect(cells[4]!.text()).toBe('色卡 A / 001 / 黑色')
  })

  it('预检失败时不保存，不覆盖页面行', async () => {
    vi.mocked(api.previewBomMaterialSave).mockRejectedValueOnce(new Error('预检失败'))
    const { vm, auxiliary } = await open()
    expect(await vm.persistDraft()).toBe(false)
    expect(auxiliary.lines[0]!.part_name).toBe('织带')
    expect(api.saveBomDraft).not.toHaveBeenCalled()
  })

  it('确认保存失败保留弹窗与页面，不自动重试或显示成功', async () => {
    vi.mocked(api.previewBomMaterialSave).mockResolvedValue(additions)
    vi.mocked(api.saveBomDraft).mockRejectedValueOnce(Object.assign(new AxiosError('新增清单已变化'), { response: { status: 409, data: { error: { message: '新增清单已变化，请重新检查。' } } } }))
    const { wrapper: page, vm, auxiliary } = await open()
    await vm.persistDraft()
    expect(await vm.confirmMaterialSave()).toBe(false)
    await flushPromises()
    expect(page.get('[data-testid="bom-material-save-preview"]').text()).toContain('新增清单已变化')
    expect(auxiliary.lines[0]!.part_name).toBe('织带')
    expect(api.saveBomDraft).toHaveBeenCalledTimes(1)
    expect(api.previewBomMaterialSave).toHaveBeenCalledTimes(1)
    expect(await vm.confirmMaterialSave()).toBe(false)
    expect(api.saveBomDraft).toHaveBeenCalledTimes(1)
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

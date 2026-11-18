import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/boms'
import type { BomLineInput, BomSectionInput } from '@/types/bom'
import { calculateHardwareWeight, selectHardwareWeight } from './useHardwareWeightPreview'
import BomEditorView from './BomEditorView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { bomId: 'b1' } }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/boms', async original => ({ ...await original<typeof import('@/api/boms')>(), fetchBomForEdit: vi.fn(), previewBomHardwareWeight: vi.fn(), previewBomMaterialSave: vi.fn(), saveBomDraft: vi.fn() }))
vi.mock('@/api/productionData', async original => ({ ...await original<typeof import('@/api/productionData')>(), fetchAllProductionDataRecords: vi.fn().mockResolvedValue([]) }))

const versioned = { data: { id: 'b1', status: 'PENDING_CONFIRMATION', order_quantity: '100', current_order_quantity: '100', product_information_confirmed: true, sections: [], configured_field_labels: {} }, etag: 'v1' }
const result = { unit_material_weight_kg: '0.00312345', unit_weight_g: '3.12345', calculation_snapshot: { version: '1' } }
interface Editor {
  sections: BomSectionInput[]
  activeSectionIndex: number
  editingLineDraft: BomLineInput
  lineDrawerVisible: boolean
  blankLine: (unit?: string) => BomLineInput
  openLineDrawer: (index: number) => void
  applyLineDrawer: () => Promise<void>
  persistDraft: () => Promise<boolean>
  followingLineDraft: (section: BomSectionInput, line: BomLineInput) => BomLineInput
}
let wrapper: VueWrapper | undefined
async function open(values: Partial<BomLineInput> = {}) {
  wrapper = shallowMount(BomEditorView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true, stubs: { ElTableColumn: { template: '<div />' } } } })
  await flushPromises()
  const vm = wrapper.vm as unknown as Editor
  vm.sections.forEach(section => { section.lines = [] })
  vm.activeSectionIndex = vm.sections.findIndex(section => section.title === '五金件')
  const section = vm.sections[vm.activeSectionIndex]!
  section.lines = [{ ...vm.blankLine('个'), part_name: '铆钉', material: 'Q235', specification: 'Φ4×35', unit_consumption: '4', ...values }]
  return { vm, section }
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchBomForEdit).mockResolvedValue(structuredClone(versioned) as never)
  vi.mocked(api.previewBomHardwareWeight).mockReset().mockResolvedValue(result)
  vi.mocked(api.previewBomMaterialSave).mockReset().mockResolvedValue({ confirmation_token: null, new_materials: [] })
  vi.mocked(api.saveBomDraft).mockReset().mockResolvedValue(structuredClone(versioned) as never)
  for (const method of ['success', 'warning', 'info', 'error'] as const) vi.spyOn(ElMessage, method).mockImplementation(() => ({ close: vi.fn() }))
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks() })

describe('BOM 五金重量应用与保存', () => {
  it('连续新增五金清除旧计算状态，独立参数按当前公式重算且不改原行', async () => {
    const input = { kind: 'RIVET_GB873_STEEL' as const, material: 'Q235', specification: 'Φ4×35', diameter_mm: '4', length_mm: '35' }
    const saved = { input_key: JSON.stringify(input), unit_material_weight_kg: '0.009' }
    const snapshot = { version: 'old', dimensions: { diameter_mm: '4' } }
    const preview = { ...result, unit_material_weight_kg: '0.009', input_key: saved.input_key, calculation_snapshot: snapshot }
    const { vm, section } = await open({ id: 'old', unit_material_weight_kg: '0.009', hardware_weight_mode: 'AUTO',
      hardware_weight_input: input, hardware_weight_saved: saved, hardware_weight_snapshot: snapshot, hardware_weight_preview: preview })
    const current = section.lines[0]!
    const before = JSON.stringify(current)
    const next = vm.followingLineDraft(section, current)
    expect(next.id).toBeUndefined()
    expect(next.hardware_weight_mode).toBe('AUTO')
    expect(next.hardware_weight_input).toEqual(input)
    expect(next.hardware_weight_input).not.toBe(current.hardware_weight_input)
    expect(next.hardware_weight_saved).toBeUndefined()
    expect(next.hardware_weight_preview).toBeUndefined()
    expect(next.hardware_weight_snapshot).toBeUndefined()
    expect(await calculateHardwareWeight(next)).toBe(true)
    expect(api.previewBomHardwareWeight).toHaveBeenCalledWith(input)
    expect(next.unit_material_weight_kg).toBe(result.unit_material_weight_kg)
    next.hardware_weight_input!.diameter_mm = '5'
    expect(JSON.stringify(current)).toBe(before)
  })

  it('应用新行先算单重，单位与用量不变', async () => {
    const { vm, section } = await open()
    vm.openLineDrawer(0)
    await vm.applyLineDrawer()
    expect(vm.lineDrawerVisible).toBe(false)
    expect(section.lines[0]).toMatchObject({ unit_material_weight_kg: result.unit_material_weight_kg, unit: '个', unit_consumption: '4', hardware_weight_mode: 'AUTO' })
  })

  it('预览失败不应用抽屉，也不进入保存预检和保存请求', async () => {
    vi.mocked(api.previewBomHardwareWeight).mockRejectedValue(new Error('missing dimensions'))
    const { vm, section } = await open()
    vm.openLineDrawer(0)
    await vm.applyLineDrawer()
    expect(vm.lineDrawerVisible).toBe(true)
    expect(section.lines[0]!.unit_material_weight_kg).toBe('')
    selectHardwareWeight(section.lines[0]!, 'PLAIN_WASHER')
    expect(await vm.persistDraft()).toBe(false)
    expect(api.previewBomMaterialSave).not.toHaveBeenCalled()
    expect(api.saveBomDraft).not.toHaveBeenCalled()
  })

  it('打开已有手填行保持原重量，修改抽屉尺寸不提前写入表格行', async () => {
    const { vm, section } = await open({ id: 'old', unit_material_weight_kg: '0.009' })
    vm.openLineDrawer(0)
    await vm.applyLineDrawer()
    expect(api.previewBomHardwareWeight).not.toHaveBeenCalled()
    expect(section.lines[0]!.unit_material_weight_kg).toBe('0.009')
    selectHardwareWeight(section.lines[0]!, 'PLAIN_WASHER')
    section.lines[0]!.hardware_weight_input!.outer_diameter_mm = '12'
    vm.openLineDrawer(0)
    vm.editingLineDraft.hardware_weight_input!.outer_diameter_mm = '15'
    expect(section.lines[0]!.hardware_weight_input!.outer_diameter_mm).toBe('12')
  })
})

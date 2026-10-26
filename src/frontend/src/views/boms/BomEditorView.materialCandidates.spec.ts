import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/boms'
import type { BomHardwareMaterial, BomHardwareMaterialGroup, BomLineInput, BomSectionInput, PaginatedBomHardwareMaterials } from '@/types/bom'
import BomEditorView from './BomEditorView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { bomId: 'b1' } }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/boms', async original => ({ ...await original<typeof import('@/api/boms')>(),
  fetchBomForEdit: vi.fn(), fetchBomEditorReferenceOptions: vi.fn(),
  fetchBomHardwareMaterials: vi.fn(), fetchBomHardwareMaterialGroups: vi.fn(),
  fetchBomPlasticMaterials: vi.fn(), fetchBomPlasticMaterialGroups: vi.fn(),
  fetchBomPackagingMaterials: vi.fn(), fetchBomPackagingMaterialGroups: vi.fn(),
  fetchBomSemiFinishedMaterials: vi.fn(), fetchBomSemiFinishedMaterialGroups: vi.fn(),
}))
vi.mock('@/api/productionData', async original => ({ ...await original<typeof import('@/api/productionData')>(), fetchAllProductionDataRecords: vi.fn().mockResolvedValue([]) }))

const cases = [
  { kind: 'hardware', name: 'Hardware', title: '五金件', fetch: api.fetchBomHardwareMaterials, groups: api.fetchBomHardwareMaterialGroups,
    expected: { category: '五金', source_raw_material_id: 'm1', hardware_material_number: 'M-1', hardware_color: '黑色', hardware_flow_unit: '千件', unit_material_weight_kg: '0.25', unit: '个' } },
  { kind: 'plastic', name: 'Plastic', title: '塑料件类', fetch: api.fetchBomPlasticMaterials, groups: api.fetchBomPlasticMaterialGroups,
    expected: { category: '塑料件', source_raw_material_id: 'm1', plastic_material_number: 'M-1', plastic_color: '黑色', unit: '个' } },
  { kind: 'packaging', name: 'Packaging', title: '包材类', fetch: api.fetchBomPackagingMaterials, groups: api.fetchBomPackagingMaterialGroups,
    expected: { category: '包材', source_packaging_material_id: 'm1', packaging_material_number: 'M-1', packaging_color: '黑色', units_per_box: '', unit: '个' } },
  { kind: 'cutting', name: 'Cutting', title: '裁剪明细', fetch: api.fetchBomSemiFinishedMaterials, groups: api.fetchBomSemiFinishedMaterialGroups,
    expected: { category: '裁片', source_cutting_material_id: 'm1', cutting_material_number: 'M-1', cutting_color: '黑色', cutting_item_type: 'SEMI_FINISHED', cutting_category: '裁片', cutting_pieces_per_set: null, fabric_meters_per_piece: null, cutting_sets_per_product: 1, draft_images: [], unit: '套' } },
] as const
type PickerCase = typeof cases[number]
type Editor = Record<string, unknown> & { sections: BomSectionInput[]; activeSectionIndex: number; lineDrawerVisible: boolean; editingLineDraft: BomLineInput }
function call(vm: Editor, name: string, ...args: unknown[]) { return (vm[name] as (...values: unknown[]) => unknown)(...args) }
function material(id = 'm1'): BomHardwareMaterial {
  return { id, material_number: 'M-1', item_type: 'SEMI_FINISHED', item_type_display: '半成品', category_name: '裁片',
    material_name: '测试材料', material: '钢', color_name: '黑色', specification: '20×30cm', unit_code: 'piece', unit_name: '个', weight_kg: '0.25', flow_unit: '千件', number_value: '' }
}
function result(...rows: BomHardwareMaterial[]): PaginatedBomHardwareMaterials {
  return { data: rows, meta: { page: 1, page_size: 50, total: rows.length, total_pages: 1 } }
}
function group(name: string): BomHardwareMaterialGroup { return { material_name: name, count: 1, pinyin_search: name } }
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (reason: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
let wrapper: VueWrapper | undefined
async function open(entry: PickerCase) {
  wrapper = shallowMount(BomEditorView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true, stubs: { ElTableColumn: { template: '<div />' } } } })
  await flushPromises()
  const vm = wrapper.vm as unknown as Editor
  vm.sections.forEach(section => { section.lines = [] })
  vm.activeSectionIndex = vm.sections.findIndex(section => section.title === entry.title)
  call(vm, `open${entry.name}Picker`)
  await flushPromises()
  return vm
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchBomForEdit).mockResolvedValue({ data: { id: 'b1', status: 'PENDING_CONFIRMATION', order_quantity: '1000', current_order_quantity: '1000', product_information_confirmed: true, sections: [], configured_field_labels: {} }, etag: 'v1' } as never)
  vi.mocked(api.fetchBomEditorReferenceOptions).mockResolvedValue({ auxiliary_products: [], accessory_materials: [], fabric_materials: [], fabric_specifications: [], fabric_widths: [], product_colors: [] })
  for (const entry of cases) {
    vi.mocked(entry.fetch).mockReset().mockResolvedValue(result(material()))
    vi.mocked(entry.groups).mockReset().mockResolvedValue([group('当前分组')])
  }
  for (const method of ['success', 'warning', 'info', 'error'] as const) vi.spyOn(ElMessage, method).mockImplementation(() => ({ close: vi.fn() }))
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks() })

describe.each(cases)('$title 选料复用边界', entry => {
  it('保留各类行映射、去重与裁剪新增后编辑入口', async () => {
    const vm = await open(entry)
    call(vm, `toggle${entry.name}Candidate`, material(), true)
    call(vm, `confirm${entry.name}Selection`)
    const section = vm.sections[vm.activeSectionIndex]!
    expect(section.lines).toHaveLength(1)
    expect(section.lines[0]).toMatchObject({ ...entry.expected, part_name: '测试材料', material: '钢', specification: '20×30cm', raw_material: 'M-1' })
    expect(vm[`${entry.kind}PickerVisible`]).toBe(false)
    if (entry.kind === 'cutting') {
      expect(section.lines[0]?.draft_key).toBeTruthy()
      expect(vm.lineDrawerVisible).toBe(true)
    }
    call(vm, `open${entry.name}Picker`); await flushPromises()
    call(vm, `toggle${entry.name}Candidate`, material(), true)
    call(vm, `confirm${entry.name}Selection`)
    expect(section.lines).toHaveLength(1)
    expect(vm[`${entry.kind}PickerVisible`]).toBe(true)
  })

  it('跨页选择保留，本页取消不影响其他页，搜索重置页码并传筛选', async () => {
    const vm = await open(entry)
    call(vm, `toggle${entry.name}Page`, true)
    vi.mocked(entry.fetch).mockResolvedValueOnce(result(material('m2')))
    await call(vm, `change${entry.name}Page`, 2); await flushPromises()
    call(vm, `toggle${entry.name}Page`, true)
    expect(vm[`selected${entry.name}Count`]).toBe(2)
    call(vm, `toggle${entry.name}Page`, false)
    expect(Object.keys(vm[`selected${entry.name}`] as object)).toEqual(['m1'])
    vm[`${entry.kind}PickerKeyword`] = '  钢  '
    vm[`${entry.kind}PickerMaterialName`] = '测试材料'
    await call(vm, `search${entry.name}Candidates`); await flushPromises()
    expect(entry.fetch).toHaveBeenLastCalledWith({ page: 1, page_size: 50, q: '钢', material_name: '测试材料' })
  })

  it('旧候选失败不能覆盖新搜索及 loading', async () => {
    const old = deferred<PaginatedBomHardwareMaterials>(), current = deferred<PaginatedBomHardwareMaterials>()
    vi.mocked(entry.fetch).mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    const vm = await open(entry)
    call(vm, `search${entry.name}Candidates`)
    old.reject(new Error('旧请求失败')); await flushPromises()
    expect(vm[`${entry.kind}PickerLoading`]).toBe(true)
    expect(vm[`${entry.kind}PickerError`]).toBe('')
    current.resolve(result(material('new'))); await flushPromises()
    expect((vm[`${entry.kind}Candidates`] as BomHardwareMaterial[]).map(row => row.id)).toEqual(['new'])
    expect(vm[`${entry.kind}PickerLoading`]).toBe(false)
  })

  it('候选和分组失败可分别重试，不清掉已选择的跨页材料', async () => {
    const vm = await open(entry)
    call(vm, `toggle${entry.name}Candidate`, material(), true)
    vi.mocked(entry.fetch).mockRejectedValueOnce(new Error('请求失败'))
    vi.mocked(entry.groups).mockRejectedValueOnce(new Error('分组失败'))
    await call(vm, `load${entry.name}Candidates`); await call(vm, `load${entry.name}Groups`)
    expect(vm[`${entry.kind}PickerError`]).toBeTruthy()
    expect(vm[`${entry.kind}GroupError`]).toBeTruthy()
    expect(vm[`selected${entry.name}Count`]).toBe(1)
    await call(vm, `load${entry.name}Candidates`); await call(vm, `load${entry.name}Groups`)
    expect(vm[`${entry.kind}PickerError`]).toBe('')
    expect(vm[`${entry.kind}GroupError`]).toBe('')
    expect(vm[`${entry.kind}Candidates`]).toHaveLength(1)
  })

  it('重新打开后旧分组成功不能覆盖当前窗口', async () => {
    const old = deferred<BomHardwareMaterialGroup[]>()
    vi.mocked(entry.groups).mockReturnValueOnce(old.promise).mockResolvedValueOnce([group('新分组')])
    const vm = await open(entry)
    vm[`${entry.kind}PickerVisible`] = false
    call(vm, `reset${entry.name}Picker`)
    call(vm, `open${entry.name}Picker`); await flushPromises()
    old.resolve([group('旧分组')]); await flushPromises()
    expect(vm[`visible${entry.name}Groups`]).toEqual([group('新分组')])
  })

  it('关闭立即使在途候选与分组失效，不等待关闭动画', async () => {
    const rows = deferred<PaginatedBomHardwareMaterials>(), groups = deferred<BomHardwareMaterialGroup[]>()
    vi.mocked(entry.fetch).mockReturnValueOnce(rows.promise)
    vi.mocked(entry.groups).mockReturnValueOnce(groups.promise)
    const vm = await open(entry)
    vm[`${entry.kind}PickerVisible`] = false
    rows.resolve(result(material('late'))); groups.resolve([group('迟到分组')]); await flushPromises()
    expect(vm[`${entry.kind}Candidates`]).toEqual([])
    expect(vm[`visible${entry.name}Groups`]).toEqual([])
    expect(vm[`${entry.kind}PickerLoading`]).toBe(false)
  })

  it('卸载后忽略候选与分组迟到响应', async () => {
    const rows = deferred<PaginatedBomHardwareMaterials>(), groups = deferred<BomHardwareMaterialGroup[]>()
    vi.mocked(entry.fetch).mockReturnValueOnce(rows.promise)
    vi.mocked(entry.groups).mockReturnValueOnce(groups.promise)
    const vm = await open(entry)
    wrapper!.unmount(); wrapper = undefined
    rows.resolve(result(material('late'))); groups.resolve([group('迟到分组')]); await flushPromises()
    expect(vm[`${entry.kind}Candidates`]).toEqual([])
    expect(vm[`visible${entry.name}Groups`]).toEqual([])
  })

  it('分区改变后确认不能把材料添加到其他分区', async () => {
    const vm = await open(entry)
    call(vm, `toggle${entry.name}Candidate`, material(), true)
    vm.activeSectionIndex = vm.sections.findIndex(section => section.title === '管材类')
    call(vm, `confirm${entry.name}Selection`)
    expect(vm.sections.every(section => section.lines.length === 0)).toBe(true)
    expect(vm[`${entry.kind}PickerVisible`]).toBe(true)
  })

  it('请求失败仍回显本类型临时材料，重新选入时按临时标识去重', async () => {
    const vm = await open(entry)
    const payload = { material_number: 'PENDING-1', item_type: 'MATERIAL', category: 'category-1', material_name: '临时材料',
      specification: '10×20cm', unit: 'piece', color: null, material: '钢', is_packaging_auxiliary: false,
      box_shape: '', notes: '', warehouse_number: 'W1', warehouse_name: '原料仓' }
    vi.mocked(entry.fetch).mockRejectedValueOnce(new Error('目录失败'))
    await call(vm, 'stageRawMaterial', entry.kind, payload, { category_name: '当前类别', unit_name: '个', unit_code: 'PCS', color_name: '' })
    expect(vm[`${entry.kind}PickerError`]).toBeTruthy()
    expect(vm[`${entry.kind}Candidates`]).toEqual([expect.objectContaining({ material_name: '临时材料', material_number: 'PENDING-1' })])
    call(vm, `confirm${entry.name}Selection`)
    const section = vm.sections[vm.activeSectionIndex]!
    expect(section.lines).toHaveLength(1)
    expect(section.lines[0]).toMatchObject({ pending_raw_material: payload, source_raw_material_id: null, source_packaging_material_id: null, source_cutting_material_id: null })
    call(vm, `open${entry.name}Picker`); await flushPromises()
    call(vm, `toggle${entry.name}Page`, true)
    call(vm, `confirm${entry.name}Selection`)
    expect(section.lines).toHaveLength(2)
    expect(section.lines.filter(line => line.pending_raw_material)).toHaveLength(1)
    expect(section.lines[1]).toMatchObject(entry.expected)
  })
})

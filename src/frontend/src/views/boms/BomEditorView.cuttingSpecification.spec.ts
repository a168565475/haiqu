import { createRequire } from 'node:module'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElSelect, ElTooltip } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/boms'
import * as rawApi from '@/api/rawMaterials'
import * as catalogApi from '@/api/materialCatalog'
import type { BomLineInput, BomSectionInput } from '@/types/bom'
import BomEditorView from './BomEditorView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { bomId: 'b1' } }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/boms', async original => ({ ...await original<typeof import('@/api/boms')>(), fetchBomForEdit: vi.fn(), previewBomMaterialSave: vi.fn(), saveBomDraft: vi.fn(), fetchBomEditorReferenceOptions: vi.fn(), fetchBomSemiFinishedMaterials: vi.fn(), fetchBomSemiFinishedMaterialGroups: vi.fn(), fetchBomCatalogSelectionOptions: vi.fn().mockResolvedValue({ crafts: [] }) }))
vi.mock('@/api/productionData', async original => ({ ...await original<typeof import('@/api/productionData')>(), fetchAllProductionDataRecords: vi.fn().mockResolvedValue([]) }))
vi.mock('@/api/rawMaterials', () => ({ createRawMaterial: vi.fn(), fetchRawMaterialOptions: vi.fn() }))

vi.mock('@/api/materialCatalog', async original => ({ ...await original<typeof import('@/api/materialCatalog')>(), fetchMaterialCatalog: vi.fn(), fetchMaterialCatalogOptions: vi.fn(), fetchPublicMaterialOptions: vi.fn(), fetchMaterialCatalogs: vi.fn(), createMaterialCatalog: vi.fn() }))

const versioned = { data: { id: 'b1', status: 'PENDING_CONFIRMATION', order_quantity: '1000', current_order_quantity: '1000', product_information_confirmed: true, sections: [], configured_field_labels: {} }, etag: 'v1' }
// Node 直接加载 ESM 发行版时 async-validator 的默认导出不兼容；使用真实 CJS 发行版执行表单校验。
const elementPlusRuntime = createRequire(import.meta.url)('element-plus').default as typeof ElementPlus
const dialog = { props: ['modelValue', 'title'], template: '<section v-if="modelValue" :aria-label="title"><slot /><slot name="footer" /></section>' }
let wrapper: VueWrapper | undefined
let host: HTMLDivElement | undefined
interface Editor { sections: BomSectionInput[]; activeSectionIndex: number; blankLine: (unit?: string) => BomLineInput }
type TooltipWrapper = VueWrapper<InstanceType<typeof ElTooltip>>

async function open(specification?: string) {
  host = document.createElement('div')
  document.body.append(host)
  wrapper = mount(BomEditorView, { attachTo: host, global: { plugins: [elementPlusRuntime], stubs: {
    AppWindowDialog: dialog, BomPrintDocument: true, InquiryProductDialog: true, ProductCreateDialog: true,
    BomLineImageSummary: true, BomProductImage: true,
    ProductionDataView: { name: 'ProductionDataView', props: { initialCategory: String, embedded: Boolean }, template: '<div data-testid="production-maintenance" />' },
  } } })
  await flushPromises()
  const vm = wrapper.vm as unknown as Editor
  vm.sections.forEach(section => { section.lines = [] })
  vm.activeSectionIndex = vm.sections.findIndex(section => section.title === '裁剪明细')
  const cutting = vm.sections[vm.activeSectionIndex]!
  vm.sections.find(section => section.title === '面料类')!.lines.push({ ...vm.blankLine('米'), id: 'fabric-1', part_name: '牛津布', specification: '600D', material: '涤纶', unit_consumption: '1' })
  if (specification !== undefined) cutting.lines.push({ ...vm.blankLine('套'), id: 'cutting-1', category: '布片', part_name: '床面', specification, source_cutting_material_id: 'semi-1', fabric_source_line_id: 'fabric-1', cutting_pieces_per_set: 2, cutting_sets_per_product: 1 })
  await flushPromises()
  return { page: wrapper, cutting }
}

function button(page: VueWrapper, text: string) { return page.findAll('button').find(item => item.text() === text)! }

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchBomForEdit).mockResolvedValue(structuredClone(versioned) as never)
  vi.mocked(api.fetchBomEditorReferenceOptions).mockResolvedValue({ auxiliary_products: [], accessory_materials: [], fabric_materials: [], fabric_specifications: [], fabric_widths: [], product_colors: [] })
  vi.mocked(api.fetchBomSemiFinishedMaterials).mockResolvedValue({ data: [], meta: { page: 1, page_size: 50, total: 0, total_pages: 0 } })
  vi.mocked(api.fetchBomSemiFinishedMaterialGroups).mockResolvedValue([])
  vi.mocked(api.previewBomMaterialSave).mockResolvedValue({ confirmation_token: null, new_materials: [] })
  vi.mocked(catalogApi.fetchMaterialCatalogs).mockResolvedValue({ data: [], meta: { page: 1, page_size: 100, total: 0, total_pages: 0 } })
  vi.mocked(api.saveBomDraft).mockImplementation(async (_id, sections) => ({ data: { ...versioned.data, sections: JSON.parse(JSON.stringify(sections)) }, etag: 'v2' }) as never)
  vi.mocked(rawApi.fetchRawMaterialOptions).mockResolvedValue({ item_types: [], categories: [{ id: 'cut-category', item_type: 'SEMI_FINISHED', category_name: '布片' }], units: [{ id: 'set-unit', unit_code: 'SET', unit_name: '套' }], colors: [], warehouses: [{ warehouse_number: 'W1', warehouse_name: '半成品仓' }], box_shapes: [] })
})
afterEach(() => { wrapper?.unmount(); host?.remove(); wrapper = undefined; host = undefined; ElMessage.closeAll() })

describe('裁剪规格提醒和新增裁片', () => {
  it.each([
    ['cutting_pieces_per_set', '裁片量（片/套）', '请填写裁片量（片/套）。'],
    ['cutting_sets_per_product', '每成品套数（套/成品）', '请填写每成品套数（套/成品）。'],
  ] as const)('缺少 %s 时只在对应输入框悬浮提示，填写后关闭', async (field, label, message) => {
    const { page } = await open('600D')
    await page.get('.cutting-table button[aria-label="编辑当前行"]').trigger('click')
    await flushPromises()
    const vm = page.vm as unknown as Editor & { editingLineDraft: BomLineInput }
    vm.editingLineDraft[field] = null
    await page.vm.$nextTick()
    const form = page.get('.line-drawer-form')
    expect(form.find('[data-testid="cutting-calculation-error"]').exists()).toBe(false)
    const hints: TooltipWrapper[] = form.findAllComponents(ElTooltip).filter((item: TooltipWrapper) => item.props('content')?.startsWith('请填写'))
    expect(hints).toHaveLength(2)
    const missing = hints.find(item => item.props('content') === message)!
    expect(missing.props('disabled')).toBe(false)
    expect(hints.filter(item => item.props('disabled'))).toHaveLength(1)
    const inputRoot = form.get(`[aria-label="${label}"]`).element.closest('.el-input')!
    inputRoot.dispatchEvent(new MouseEvent('mouseenter'))
    await vi.waitFor(() => {
      const tips = Array.from(document.body.querySelectorAll('[role="tooltip"]'))
      expect(tips.some(item => item.getAttribute('aria-hidden') === 'false' && (item as HTMLElement).style.display !== 'none' && item.textContent === message)).toBe(true)
    })
    await form.get(`[aria-label="${label}"]`).setValue('2')
    expect(missing.props('disabled')).toBe(true)
    await vi.waitFor(() => {
      expect(Array.from(document.body.querySelectorAll('[role="tooltip"][aria-hidden="false"]')).some(item => (item as HTMLElement).style.display !== 'none' && item.textContent === message)).toBe(false)
    })
  })

  it('来源面料在品名前且与普通字段同列宽，两个计算结果在备注前，隐藏指定说明', async () => {
    const { page } = await open('120×60cm')
    await page.get('.cutting-table button[aria-label="编辑当前行"]').trigger('click')
    await flushPromises()
    const source = page.get('[aria-label="来源面料"]').element.closest('.drawer-field')!
    expect(source.classList.contains('drawer-field--wide')).toBe(false)
    const form = page.get('.line-drawer-form')
    expect(form.element.firstElementChild).toBe(source)
    const notes = page.get('[aria-label="备注"]').element.closest('.drawer-field')
    expect(page.get('.cutting-order-calculations').element.nextElementSibling).toBe(notes)
    expect(page.get('.cutting-order-calculations').findAll('.drawer-field')).toHaveLength(2)
    vi.mocked(catalogApi.fetchMaterialCatalogOptions).mockResolvedValue({ categories: [{ key: 'FABRIC_SEMI', label: '裁片', templates: [{ key: 'FABRIC_SEMI', label: '裁片', supports_spray: false, fields: [] }] }], spray_fields: [], units: [], warehouses: [] })
    vi.mocked(catalogApi.fetchMaterialCatalogs).mockResolvedValue({ data: [], meta: { page: 1, page_size: 50, total: 0, total_pages: 1 } })
    await button(page, '从新原料选择').trigger('click')
    await flushPromises()
    expect(form.element.children[1]).toBe(page.get('[aria-label="裁片品名"]').element.closest('.drawer-field'))
    expect(page.find('.material-selection-field').exists()).toBe(false)
    expect(page.text()).not.toContain('保留来源面料关联；实际材质和颜色保存本次裁片选项。')
    expect(page.text()).not.toContain('请选择实际尺寸或明确型号；缺少规格时请到生产维护新增。')
  })

  it.each(['', '   ', ' / ', '—', '-', '--', '–', 'N/A', 'n/a', 'NULL', 'null'])('来源面料规格无效 %j 时阻止保存，裁片不能另填规格绕过', async (specification) => {
    const { page, cutting } = await open(specification)
    const vm = page.vm as unknown as Editor
    vm.sections.find(section => section.title === '面料类')!.lines[0]!.specification = specification
    await button(page, '保存草稿').trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('请填写有效规格')
    expect(api.previewBomMaterialSave).not.toHaveBeenCalled()
    expect(api.saveBomDraft).not.toHaveBeenCalled()
    expect(cutting.lines[0]!.specification).toBe(specification)
  })

  it('裁片规格只读继承来源面料，应用保存不再要求单独填写', async () => {
    const { page, cutting } = await open('/')
    await page.get('.cutting-table button[aria-label="编辑当前行"]').trigger('click')
    await flushPromises()
    expect(page.find('input[aria-label="规格"]').exists()).toBe(false)
    expect(page.get('.line-drawer-form').text()).not.toContain('流转单位')
    expect(page.text()).toContain('面料规格600D')
    expect(page.find('[aria-label="单个用量（米/片）"]').exists()).toBe(false)
    expect(page.find('[aria-label="每套耗米（米/套）"]').exists()).toBe(false)
    expect(page.get('[data-testid="cutting-order-pieces"]').text()).toBe('2000 片')
    await button(page, '应用修改').trigger('click')
    await flushPromises()
    expect(cutting.lines[0]!.specification).toBe('600D')
    await button(page, '保存草稿').trigger('click')
    await flushPromises()
    const submitted = vi.mocked(api.saveBomDraft).mock.calls[0]![1].find(section => section.title === '裁剪明细')!.lines[0]!
    expect(submitted.specification).toBe('600D')
    expect(submitted).toMatchObject({ cutting_pieces_per_set: 2, cutting_sets_per_product: 1 })
  })

  it('裁片下拉不显示维护入口，关闭行编辑后可用主入口维护，不暂存旧组合档', async () => {
    vi.mocked(catalogApi.fetchMaterialCatalogOptions).mockResolvedValue({ categories: [{ key: 'FABRIC_SEMI', label: '裁片', templates: [{ key: 'FABRIC_SEMI', label: '裁片', supports_spray: false, fields: [{ key: 'material', label: '材质', kind: 'text' }, { key: 'unit', label: '可用单位', kind: 'unit' }] }] }], spray_fields: [], units: [], warehouses: [] })
    vi.mocked(catalogApi.fetchMaterialCatalogs).mockResolvedValue({ data: [], meta: { page: 1, page_size: 50, total: 0, total_pages: 1 } })
    const { page } = await open()
    expect(button(page, '选择裁剪')).toBeUndefined()
    await button(page, '添加材料').trigger('click')
    await flushPromises()
    await page.getComponent({ name: 'BomCuttingCatalogSelect' }).get('.el-select__wrapper').trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('暂无裁片品名，请到维护配置新增')
    const maintain = Array.from(document.body.querySelectorAll('.el-select-dropdown__footer button')).find(item => item.textContent?.trim() === '维护配置')
    expect(maintain).toBeUndefined()
    await button(page, '取消').trigger('click')
    await flushPromises()
    await button(page, '维护配置').trigger('click')
    await flushPromises()
    expect(page.get('[aria-label="生产维护"]').find('[data-testid="production-maintenance"]').exists()).toBe(true)
    expect(page.getComponent({ name: 'ProductionDataView' }).props()).toMatchObject({ initialCategory: 'FABRIC_SEMI', embedded: true })
    expect(catalogApi.createMaterialCatalog).not.toHaveBeenCalled()
    expect(rawApi.createRawMaterial).not.toHaveBeenCalled()
    expect(api.saveBomDraft).not.toHaveBeenCalled()
  })

  it('新增裁片普通下拉只选品名，自动使用内部裁剪和套，应用后提交完整来源数据', async () => {
    const catalog = { id: 'cutting-catalog', name: '床面', category_key: 'FABRIC_SEMI', template_key: 'FABRIC_SEMI',
      updated_at: 'catalog-v2', spray_enabled: false, base_warehouse_id: null, semi_warehouse_id: null, values: [], units: [] }
    vi.mocked(catalogApi.fetchMaterialCatalogs).mockResolvedValue({ data: [catalog], meta: { page: 1, page_size: 100, total: 1, total_pages: 1 } })
    vi.mocked(catalogApi.fetchMaterialCatalog).mockResolvedValue({ data: catalog, etag: 'catalog-v2' })
    vi.mocked(catalogApi.fetchPublicMaterialOptions).mockResolvedValue({ category_key: 'FABRIC_SEMI', template_key: 'FABRIC_SEMI', scope: 'BASE',
      fields: [], values: [], units: [{ id: 'set-unit', unit_name: '套' }] })
    vi.mocked(api.fetchBomCatalogSelectionOptions).mockResolvedValue({ crafts: [
      { id: 'external-cutting', name: '裁剪', craft_type: 'EXTERNAL', code: 'CUTTING' },
      { id: 'internal-cutting', name: '裁剪', craft_type: 'INTERNAL', code: 'CUTTING' },
    ] })
    const { page, cutting } = await open()
    await button(page, '添加材料').trigger('click')
    await flushPromises()
    const picker = page.getComponent({ name: 'BomCuttingCatalogSelect' })
    expect(page.find('.material-selection-field').exists()).toBe(false)
    picker.getComponent(ElSelect).vm.$emit('change', catalog.id)
    await flushPromises()
    expect(picker.find('[role="alert"]').exists(), picker.text()).toBe(false)
    const vm = page.vm as unknown as Editor & { editingLineDraft: BomLineInput; lineDrawerVisible: boolean }
    expect(vm.editingLineDraft.material_catalog_id).toBe(catalog.id)
    expect(vm.editingLineDraft.fabric_source_line_id).toBe('fabric-1')
    await page.get('.line-drawer-form [aria-label="裁片量（片/套）"]').setValue('2')
    await page.get('.line-drawer-form [aria-label="每成品套数（套/成品）"]').setValue('1')
    expect(String(vm.editingLineDraft.cutting_pieces_per_set)).toBe('2')
    expect(String(vm.editingLineDraft.cutting_sets_per_product)).toBe('1')
    await button(page, '应用修改').trigger('click')
    await flushPromises()
    expect(vm.lineDrawerVisible, Array.from(document.body.querySelectorAll('.el-message__content')).map(item => item.textContent).join('；')).toBe(false)
    expect(cutting.lines[0]).toMatchObject({ part_name: '床面', unit: '套', fabric_source_line_id: 'fabric-1',
      material: '涤纶', specification: '600D', material_selection: { unit_id: 'set-unit', processing_state: 'PROCESSED',
        semi_kind: 'CUTTING', attributes: { material: '涤纶', specification: '600D' },
        completed_craft: { id: 'internal-cutting', craft_type: 'INTERNAL', code: 'CUTTING' } } })
    await button(page, '保存草稿').trigger('click')
    await flushPromises()
    const submitted = vi.mocked(api.saveBomDraft).mock.calls[0]![1].find(section => section.title === '裁剪明细')!.lines[0]!
    expect(submitted.material_selection?.completed_craft?.craft_type).toBe('INTERNAL')
    expect(submitted.material_selection?.unit_id).toBe('set-unit')
    expect(submitted.material_selection?.unit_name).toBeUndefined()
  })
})

import { createRequire } from 'node:module'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/boms'
import * as rawApi from '@/api/rawMaterials'
import type { BomLineInput, BomSectionInput } from '@/types/bom'
import BomEditorView from './BomEditorView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { bomId: 'b1' } }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/boms', async original => ({ ...await original<typeof import('@/api/boms')>(), fetchBomForEdit: vi.fn(), previewBomMaterialSave: vi.fn(), saveBomDraft: vi.fn(), fetchBomEditorReferenceOptions: vi.fn(), fetchBomSemiFinishedMaterials: vi.fn(), fetchBomSemiFinishedMaterialGroups: vi.fn() }))
vi.mock('@/api/productionData', async original => ({ ...await original<typeof import('@/api/productionData')>(), fetchAllProductionDataRecords: vi.fn().mockResolvedValue([]) }))
vi.mock('@/api/rawMaterials', () => ({ createRawMaterial: vi.fn(), fetchRawMaterialOptions: vi.fn() }))

const versioned = { data: { id: 'b1', status: 'PENDING_CONFIRMATION', order_quantity: '1000', current_order_quantity: '1000', product_information_confirmed: true, sections: [], configured_field_labels: {} }, etag: 'v1' }
// Node 直接加载 ESM 发行版时 async-validator 的默认导出不兼容；使用真实 CJS 发行版执行表单校验。
const elementPlusRuntime = createRequire(import.meta.url)('element-plus').default as typeof ElementPlus
const dialog = { props: ['modelValue', 'title'], template: '<section v-if="modelValue" :aria-label="title"><slot /><slot name="footer" /></section>' }
let wrapper: VueWrapper | undefined
let host: HTMLDivElement | undefined
interface Editor { sections: BomSectionInput[]; activeSectionIndex: number; blankLine: (unit?: string) => BomLineInput }

async function open(specification?: string) {
  host = document.createElement('div')
  document.body.append(host)
  wrapper = mount(BomEditorView, { attachTo: host, global: { plugins: [elementPlusRuntime], stubs: {
    AppWindowDialog: dialog, BomPrintDocument: true, InquiryProductDialog: true, ProductCreateDialog: true,
    AuxiliaryReferenceCreateDialog: true, BomLineImageSummary: true, BomProductImage: true,
  } } })
  await flushPromises()
  const vm = wrapper.vm as unknown as Editor
  vm.sections.forEach(section => { section.lines = [] })
  vm.activeSectionIndex = vm.sections.findIndex(section => section.title === '裁剪明细')
  const cutting = vm.sections[vm.activeSectionIndex]!
  vm.sections.find(section => section.title === '面料类')!.lines.push({ ...vm.blankLine('米'), id: 'fabric-1', part_name: '牛津布', specification: '600D', material: '涤纶', unit_consumption: '1' })
  if (specification !== undefined) cutting.lines.push({ ...vm.blankLine('套'), id: 'cutting-1', category: '布片', part_name: '床面', specification, source_cutting_material_id: 'semi-1', fabric_source_line_id: 'fabric-1', cutting_pieces_per_set: 2, fabric_meters_per_piece: '0.5', cutting_sets_per_product: 1 })
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
  vi.mocked(api.saveBomDraft).mockImplementation(async (_id, sections) => ({ data: { ...versioned.data, sections: JSON.parse(JSON.stringify(sections)) }, etag: 'v2' }) as never)
  vi.mocked(rawApi.fetchRawMaterialOptions).mockResolvedValue({ item_types: [], categories: [{ id: 'cut-category', item_type: 'SEMI_FINISHED', category_name: '布片' }], units: [{ id: 'set-unit', unit_code: 'SET', unit_name: '套' }], colors: [], warehouses: [{ warehouse_number: 'W1', warehouse_name: '半成品仓' }], box_shapes: [] })
})
afterEach(() => { wrapper?.unmount(); host?.remove(); wrapper = undefined; host = undefined; ElMessage.closeAll() })

describe('裁剪规格提醒和新增裁片', () => {
  it.each(['', '   ', ' / ', '—', '-', '--', '–', 'N/A', 'n/a', 'NULL', 'null'])('保存时阻止无效规格 %j，并保留该行以便补填', async (specification) => {
    const { page, cutting } = await open(specification)
    await button(page, '保存草稿').trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('请填写有效规格')
    expect(api.previewBomMaterialSave).not.toHaveBeenCalled()
    expect(api.saveBomDraft).not.toHaveBeenCalled()
    expect(cutting.lines[0]!.specification).toBe(specification)
  })

  it('编辑行先提醒规格必填，补齐后应用并保存实际输入', async () => {
    const { page, cutting } = await open('/')
    await page.get('.cutting-table button[aria-label="编辑当前行"]').trigger('click')
    await flushPromises()
    expect(page.text()).toContain('规格必填')
    await button(page, '应用修改').trigger('click')
    await flushPromises()
    expect(page.find('input[aria-label="规格"]').exists()).toBe(true)
    expect(cutting.lines[0]!.specification).toBe('/')
    await page.get('input[aria-label="规格"]').setValue('120×60cm')
    await button(page, '应用修改').trigger('click')
    await flushPromises()
    expect(cutting.lines[0]!.specification).toBe('120×60cm')
    await button(page, '保存草稿').trigger('click')
    await flushPromises()
    const submitted = vi.mocked(api.saveBomDraft).mock.calls[0]![1].find(section => section.title === '裁剪明细')!.lines[0]!
    expect(submitted.specification).toBe('120×60cm')
  })

  it('找不到现有裁片时可打开新增入口，填写明确规格后才允许暂存', async () => {
    const { page } = await open()
    await button(page, '选择裁剪').trigger('click')
    await flushPromises()
    expect(page.text()).toContain('暂无符合条件的裁剪数据')
    expect(button(page, '新增裁片')).toBeDefined()
    await button(page, '新增裁片').trigger('click')
    await flushPromises()
    const create = page.get('[data-testid="cutting-raw-material-create-dialog"]')
    expect(create.text()).toContain('规格必填')
    await create.get('input[aria-label="裁片品号"]').setValue('CUT-NEW')
    await create.get('input[aria-label="裁片品名"]').setValue('新床面')
    await create.get('input[aria-label="裁片规格"]').setValue('/')
    const controls = create.findAllComponents({ name: 'ElSelect' })
    // 分类、单位和仓库使用真实 Element Plus 选项点击。
    for (const [index, label] of [[0, '布片'], [1, '套'], [2, 'W1 / 半成品仓']] as const) {
      await controls[index]!.get('.el-select__wrapper').trigger('click')
      await flushPromises()
      const option = Array.from(document.querySelectorAll<HTMLElement>('.el-select-dropdown__item')).find(item => item.textContent?.trim() === label)!
      option.click()
      await flushPromises()
    }
    const submit = create.findAll('button').find(item => item.text().includes('暂存'))!
    await submit.trigger('click')
    await flushPromises()
    await vi.waitFor(() => expect(create.text()).toContain('请填写有效规格'))
    expect(page.text()).not.toContain('已选择 1 条')
    await create.get('input[aria-label="裁片规格"]').setValue('120×60cm')
    await submit.trigger('click')
    await flushPromises()
    expect(page.find('[data-testid="cutting-raw-material-create-dialog"]').exists()).toBe(false)
    expect(page.text()).toContain('新床面')
    expect(page.text()).toContain('120×60cm')
    expect(page.text()).toContain('已选择 1 条')
    expect(rawApi.createRawMaterial).not.toHaveBeenCalled()
    expect(api.saveBomDraft).not.toHaveBeenCalled()
  })
})

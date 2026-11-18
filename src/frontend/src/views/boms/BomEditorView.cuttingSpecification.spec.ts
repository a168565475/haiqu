import { createRequire } from 'node:module'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElMessageBox, ElSelect, ElTooltip } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/boms'
import * as rawApi from '@/api/rawMaterials'
import * as catalogApi from '@/api/materialCatalog'
import type { BomLineInput, BomSectionInput } from '@/types/bom'
import BomEditorView from './BomEditorView.vue'
import BomCuttingCatalogSelect from './BomCuttingCatalogSelect.vue'
import MaterialSelectionPanel from '@/components/products/MaterialSelectionPanel.vue'

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
  vi.mocked(api.fetchBomEditorReferenceOptions).mockResolvedValue({ component_units: [{ id: 'unit', unit_name: '个', unit_code: 'PCS' }], auxiliary_products: [], accessory_materials: [], fabric_materials: [], fabric_specifications: [], fabric_widths: [], product_colors: [] })
  vi.mocked(api.fetchBomSemiFinishedMaterials).mockResolvedValue({ data: [], meta: { page: 1, page_size: 50, total: 0, total_pages: 0 } })
  vi.mocked(api.fetchBomSemiFinishedMaterialGroups).mockResolvedValue([])
  vi.mocked(api.previewBomMaterialSave).mockResolvedValue({ confirmation_token: null, new_materials: [] })
  vi.mocked(catalogApi.fetchMaterialCatalogs).mockResolvedValue({ data: [], meta: { page: 1, page_size: 100, total: 0, total_pages: 0 } })
  vi.mocked(api.saveBomDraft).mockImplementation(async (_id, sections) => ({ data: { ...versioned.data, sections: JSON.parse(JSON.stringify(sections)) }, etag: 'v2' }) as never)
  vi.mocked(rawApi.fetchRawMaterialOptions).mockResolvedValue({ item_types: [], categories: [{ id: 'cut-category', item_type: 'SEMI_FINISHED', category_name: '布片' }], units: [{ id: 'set-unit', unit_code: 'SET', unit_name: '套' }], colors: [], warehouses: [{ warehouse_number: 'W1', warehouse_name: '半成品仓' }], box_shapes: [] })
})
afterEach(() => { wrapper?.unmount(); host?.remove(); wrapper = undefined; host = undefined; ElMessage.closeAll() })

describe('裁剪规格提醒和新增裁片', () => {
  it('单位读取失败可在原表重试，不伪造默认单位', async () => {
    vi.mocked(api.fetchBomEditorReferenceOptions).mockRejectedValueOnce(new Error('offline'))
    const { page } = await open()
    expect(page.find('.reference-options-error').exists()).toBe(true)
    expect(page.getComponent({ name: 'BomMaterialSectionTables' }).props('componentUnits')).toEqual([])
    await button(page, '重新加载生产维护数据').trigger('click')
    await flushPromises()
    expect(page.find('.reference-options-error').exists()).toBe(false)
    expect(page.getComponent({ name: 'BomMaterialSectionTables' }).props('componentUnits')).toEqual([{ id: 'unit', unit_name: '个', unit_code: 'PCS' }])
  })

  it('表格切类型取消不丢资料，有子裁片的部位不能直接转裁片', async () => {
    const { page, cutting } = await open()
    const vm = page.vm as unknown as Editor
    const part = { ...vm.blankLine('个'), component_kind: 'SEWN_PART' as const, part_name: '床面', parts_per_product: 1, material_catalog_id: 'part' }
    const piece = { ...vm.blankLine('片'), component_kind: 'CUT_PIECE' as const, part_name: '布面', parent_part_client_key: part.client_key, material_catalog_id: 'piece', pieces_per_part: 2, specification: '30×40cm', fabric_source_line_id: 'fabric-1', notes: '保留备注' }
    cutting.lines.push(part, piece)
    await flushPromises()
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
    const notify = vi.spyOn(ElMessage, 'warning')
    try {
      const types = page.getComponent({ name: 'BomMaterialSectionTables' }).findAllComponents(ElSelect).filter(item => item.props('ariaLabel') === '类型')
      types[1]!.vm.$emit('change', 'SEWN_PART')
      await flushPromises()
      expect(confirm).toHaveBeenCalledOnce()
      expect(cutting.lines[1]).toMatchObject({ component_kind: 'CUT_PIECE', parent_part_client_key: part.client_key, fabric_source_line_id: 'fabric-1', pieces_per_part: 2, specification: '30×40cm', notes: '保留备注' })
      types[0]!.vm.$emit('change', 'CUT_PIECE')
      await flushPromises()
      expect(notify).toHaveBeenCalledWith(expect.stringContaining('该部位已有裁片'))
      expect(confirm).toHaveBeenCalledOnce()
      expect(cutting.lines[0]!.component_kind).toBe('SEWN_PART')
    } finally { confirm.mockRestore(); notify.mockRestore() }
  })

  it('部位抽屉选择归属面布并保存刷新，规格单位和子裁片来源保持，图片功能保留', async () => {
    const { page, cutting } = await open()
    const vm = page.vm as unknown as Editor
    const fabricSection = vm.sections.find(section => section.title === '面料类')!
    Object.assign(fabricSection.lines[0]!, { fabric_color_name: '蓝色', fabric_color_code: 'B01', fabric_width: '150cm' })
    const otherSource = { ...vm.blankLine('米'), part_name: '里布', material: '棉', specification: '300D', unit_consumption: '1', fabric_color_name: '米白', fabric_color_code: 'W01', fabric_width: '140cm' }
    fabricSection.lines.push(otherSource)
    vi.mocked(api.saveBomDraft).mockImplementationOnce(async (_id, sections) => {
      const saved = JSON.parse(JSON.stringify(sections)) as BomSectionInput[]
      // 写请求使用 client_key；真实保存响应只返回已解析的持久关联 ID。
      for (const section of saved) for (const line of section.lines) {
        if (line.client_key === otherSource.client_key) line.id = 'saved-face-fabric'
        if (line.fabric_source_client_key === otherSource.client_key) {
          line.fabric_source_line_id = 'saved-face-fabric'
          delete line.fabric_source_client_key
        }
      }
      return { data: { ...versioned.data, sections: saved }, etag: 'v2' } as never
    })
    const part = { ...vm.blankLine('套'), component_kind: 'SEWN_PART' as const, part_name: '椅面', parts_per_product: 1,
      material_catalog_id: 'part', specification: '成品50×60cm', material: '错误自身材质' }
    const piece = { ...vm.blankLine('片'), component_kind: 'CUT_PIECE' as const, part_name: '面片', parent_part_client_key: part.client_key,
      material_catalog_id: 'piece', fabric_source_line_id: 'fabric-1', pieces_per_part: 1, specification: '裁片55×65cm' }
    cutting.lines.push(part, piece)
    await flushPromises()
    await page.get('.cutting-table button[aria-label="编辑当前行"]').trigger('click')
    await flushPromises()
    const form = page.get('.line-drawer-form')
    expect(form.find('.component-fabric-sources').exists()).toBe(false)
    expect(form.text()).not.toContain('所属裁片的布料来源')
    expect(form.get('.drawer-image-action').text()).toContain('上传图片')
    const faceSelect = form.findAllComponents(ElSelect).find((item: VueWrapper<InstanceType<typeof ElSelect>>) => item.props('ariaLabel') === '归属面布')!
    expect(faceSelect.props('modelValue')).toBe('')
    faceSelect.vm.$emit('update:modelValue', otherSource.client_key)
    await flushPromises()
    expect(form.get('[aria-label="归属面布"]').element.closest('.drawer-field')!.getAttribute('title')).toContain('颜色：米白；色号：W01')
    expect(form.text()).not.toContain('错误自身材质')
    expect((form.get('input[aria-label="部位规格"]').element as HTMLInputElement).value).toBe('成品50×60cm')
    expect(piece.specification).toBe('裁片55×65cm')
    await button(page, '应用修改').trigger('click')
    await flushPromises()
    await button(page, '保存草稿').trigger('click')
    await flushPromises()
    const submitted = vi.mocked(api.saveBomDraft).mock.calls[0]![1].find(section => section.title === '裁剪明细')!.lines
    expect(submitted[0]).toMatchObject({ fabric_source_client_key: otherSource.client_key, specification: '成品50×60cm', unit: '套' })
    expect(submitted[1]).toMatchObject({ fabric_source_line_id: 'fabric-1', specification: '裁片55×65cm', unit: '片' })
    expect(vm.sections.find(section => section.title === '裁剪明细')!.lines[0]).toMatchObject({ fabric_source_line_id: 'saved-face-fabric', unit: '套' })
    expect(page.getComponent({ name: 'BomMaterialSectionTables' }).findAllComponents(ElSelect).find(item => item.props('ariaLabel') === '归属面布')!.props('modelValue')).toBe('saved-face-fabric')
  })

  it.each(['SEWN_PART', 'CUT_PIECE'] as const)('%s 抽屉选择真实单位后保存刷新，回显持久关联与所选单位', async kind => {
    vi.mocked(api.fetchBomEditorReferenceOptions).mockResolvedValue({ component_units: [
      { id: 'piece-unit', unit_name: '片', unit_code: 'PIECE' },
      { id: 'unit', unit_name: '个', unit_code: 'PCS' },
      { id: 'set-unit', unit_name: '套', unit_code: 'SET' },
    ], auxiliary_products: [], accessory_materials: [], fabric_materials: [], fabric_specifications: [], fabric_widths: [], product_colors: [] })
    const { page, cutting } = await open()
    const vm = page.vm as unknown as Editor
    const selection = { catalog_version: 'v1', scope: 'BASE' as const, processing_state: 'PROCESSED' as const, attributes: {}, unit_name: '片' }
    const part = { ...vm.blankLine('个'), component_kind: 'SEWN_PART' as const, part_name: '椅面', parts_per_product: 2,
      material_catalog_id: 'part', material_selection: { ...selection, unit_name: '个' } }
    const piece = { ...vm.blankLine('片'), component_kind: 'CUT_PIECE' as const, part_name: '面片', parent_part_client_key: part.client_key,
      material_catalog_id: 'piece', material_selection: { ...selection }, fabric_source_line_id: 'fabric-1', pieces_per_part: 3, specification: '30×40cm' }
    cutting.lines.push(part, piece)
    vi.mocked(api.saveBomDraft).mockImplementationOnce(async (_id, sections) => {
      const saved = JSON.parse(JSON.stringify(sections)) as BomSectionInput[]
      for (const section of saved) for (const line of section.lines) {
        if (!line.component_kind) continue
        line.id = line.component_kind === 'SEWN_PART' ? 'saved-part' : 'saved-piece'
        line.material_selection_snapshot = { ...line.material_selection, selection_kind: 'BOM_COMPONENT_REFERENCE', catalog_id: line.material_catalog_id } as never
        delete line.material_selection
        if (line.component_kind === 'CUT_PIECE') {
          line.parent_part_id = 'saved-part'
          delete line.parent_part_client_key
        }
      }
      return { data: { ...versioned.data, sections: saved }, etag: 'v2' } as never
    })
    await flushPromises()
    const rowIndex = kind === 'SEWN_PART' ? 0 : 1
    await page.findAll('.cutting-table button[aria-label="编辑当前行"]')[rowIndex]!.trigger('click')
    await flushPromises()
    const ariaLabel = kind === 'SEWN_PART' ? '部位单位' : '裁片单位'
    const unitSelect: VueWrapper<InstanceType<typeof ElSelect>> = page.get('.line-drawer-form').findAllComponents(ElSelect)
      .find((item: VueWrapper<InstanceType<typeof ElSelect>>) => item.props('ariaLabel') === ariaLabel)!
    expect(unitSelect.findAllComponents({ name: 'ElOption' }).map(item => item.props('value'))).toEqual(['片', '个', '套'])
    unitSelect.vm.$emit('change', '套')
    await flushPromises()
    await button(page, '应用修改').trigger('click')
    await flushPromises()
    await button(page, '保存草稿').trigger('click')
    await flushPromises()
    const submitted = vi.mocked(api.saveBomDraft).mock.calls[0]![1].find(section => section.title === '裁剪明细')!.lines[rowIndex]!
    expect(submitted).toMatchObject({ unit: '套', material_selection: { unit_name: '套' } })
    const savedLines = vm.sections.find(section => section.title === '裁剪明细')!.lines
    expect(savedLines[rowIndex]).toMatchObject({ id: kind === 'SEWN_PART' ? 'saved-part' : 'saved-piece', unit: '套', material_selection_snapshot: { unit_name: '套' } })
    expect(savedLines[1]).toMatchObject({ parent_part_id: 'saved-part', fabric_source_line_id: 'fabric-1', pieces_per_part: 3, specification: '30×40cm' })
    expect(savedLines[0]!.parts_per_product).toBe(2)
    expect(page.getComponent({ name: 'BomMaterialSectionTables' }).findAllComponents(ElSelect)
      .find(item => item.props('ariaLabel') === ariaLabel)!.props('modelValue')).toBe('套')
  })

  it('仅新 BOM 待完善时提醒，本地移除旧行后提示保存，保存后采用服务端新状态', async () => {
    vi.mocked(api.fetchBomForEdit).mockResolvedValue({ ...structuredClone(versioned), data: { ...versioned.data,
      component_structure: { required: true, pending: true, message: '请完善部位与裁片组成后再确认。' },
    } } as never)
    const { page, cutting } = await open('600D')
    expect(page.get('[data-testid="component-structure-notice"]').text()).toContain('请完善部位与裁片组成后再确认。')
    cutting.lines = []
    await flushPromises()
    expect(page.get('[data-testid="component-structure-notice"]').text()).toContain('请保存后重新确认 BOM')
    await button(page, '保存草稿').trigger('click')
    await flushPromises()
    expect(api.saveBomDraft).toHaveBeenCalled()
    expect(page.find('[data-testid="component-structure-notice"]').exists()).toBe(false)
  })

  it('历史未标记的旧 BOM 不显示新组成待完善提示', async () => {
    const { page } = await open('600D')
    expect(page.find('[data-testid="component-structure-notice"]').exists()).toBe(false)
  })

  it.each([
    [{ G: '裁片量' }, { cut_piece_quantity: '12' }],
    [{ D: '裁片 名称' }, { raw_values: { D: '床面布片' } }],
  ])('导入的非标准分区存在明确未归属裁片时，不因清空标准分区误报已调整', async (headers, values) => {
    vi.mocked(api.fetchBomForEdit).mockResolvedValue({ ...structuredClone(versioned), data: { ...versioned.data,
      component_structure: { required: true, pending: true, message: '请完善导入裁片的所属部位。' },
      sections: [{ id: 'import-fabric', section_type: 'FABRIC', title: '面辅料清单', headers,
        lines: [{ id: 'import-piece', part_name: '床面布片', images: [], ...values }] }],
    } } as never)
    const { page, cutting } = await open()
    expect(cutting.lines).toHaveLength(0)
    expect(page.get('[data-testid="component-structure-notice"]').text()).toContain('请完善导入裁片的所属部位。')
    expect(page.get('[data-testid="component-structure-notice"]').text()).not.toContain('已调整')
  })

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
    expect(form.element.children[1]).toBe(source)
    const notes = page.get('[aria-label="备注"]').element.closest('.drawer-field')
    expect(page.get('.cutting-order-calculations').element.nextElementSibling).toBe(notes)
    expect(page.get('.cutting-order-calculations').findAll('.drawer-field')).toHaveLength(2)
    vi.mocked(catalogApi.fetchMaterialCatalogOptions).mockResolvedValue({ categories: [{ key: 'FABRIC_SEMI', label: '裁片', templates: [{ key: 'FABRIC_SEMI', label: '裁片', supports_spray: false, fields: [] }] }], spray_fields: [], units: [], warehouses: [] })
    vi.mocked(catalogApi.fetchMaterialCatalogs).mockResolvedValue({ data: [], meta: { page: 1, page_size: 50, total: 0, total_pages: 1 } })
    await button(page, '从新原料选择').trigger('click')
    await flushPromises()
    expect(form.element.children[2]).toBe(page.get('[aria-label="裁片品名"]').element.closest('.drawer-field'))
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

  it('原表格添加材料和维护入口保留，没有独立部位卡片且不创建材料档案', async () => {
    const { page } = await open()
    expect(button(page, '添加材料')).toBeDefined()
    expect(button(page, '添加部位')).toBeUndefined()
    expect(page.find('.composition-editor').exists()).toBe(false)
    await button(page, '维护配置').trigger('click')
    await flushPromises()
    expect(page.get('[aria-label="生产维护"]').find('[data-testid="production-maintenance"]').exists()).toBe(true)
    expect(catalogApi.createMaterialCatalog).not.toHaveBeenCalled()
    expect(rawApi.createRawMaterial).not.toHaveBeenCalled()
    expect(api.saveBomDraft).not.toHaveBeenCalled()
  })

  it('原抽屉选现有部位档案后可先应用，表格中选裁片与所属部位再保存刷新', async () => {
    const { page, cutting } = await open()
    vi.mocked(catalogApi.fetchMaterialCatalogOptions).mockResolvedValue({ categories: [{ key: 'FABRIC_SEMI', label: '裁片', templates: [{ key: 'FABRIC_SEMI', label: '裁片', supports_spray: false, fields: [] }] }], spray_fields: [], units: [], warehouses: [] })
    vi.mocked(catalogApi.fetchPublicMaterialOptions).mockResolvedValue({ category_key: 'FABRIC_SEMI', template_key: 'FABRIC_SEMI', scope: 'BASE', values: [], fields: [], units: [] })
    vi.mocked(catalogApi.fetchMaterialCatalog).mockImplementation(async id => ({ data: {
      id, name: id === 'part-catalog' ? '床面' : '布面', category_key: 'FABRIC_SEMI', template_key: 'FABRIC_SEMI',
      updated_at: 'v1', values: [], units: [], spray_enabled: false, base_warehouse_id: null, semi_warehouse_id: null,
    }, etag: 'v1' }))
    await button(page, '添加材料').trigger('click')
    await flushPromises()
    const form = page.getComponent({ name: 'BomLineEditorForm' })
    form.findAllComponents(ElSelect).find(item => item.props('ariaLabel') === '类型')!.vm.$emit('change', 'SEWN_PART')
    await flushPromises()
    await (form.getComponent(BomCuttingCatalogSelect).getComponent(MaterialSelectionPanel).vm as unknown as { pickName: (id: string) => Promise<void> }).pickName('part-catalog')
    await flushPromises()
    form.findAllComponents(ElSelect).find(item => item.props('ariaLabel') === '部位单位')!.vm.$emit('change', '个')
    await form.get('input[aria-label="部位规格"]').setValue('120×60cm')
    await button(page, '应用修改').trigger('click')
    await flushPromises()
    expect(cutting.lines[0]).toMatchObject({ component_kind: 'SEWN_PART', material_catalog_id: 'part-catalog', unit: '个' })
    const vm = page.vm as unknown as Editor
    cutting.lines.push({ ...vm.blankLine('片'), component_kind: 'CUT_PIECE', pieces_per_part: 2, specification: '212.5×86cm', fabric_source_line_id: 'fabric-1' })
    await flushPromises()
    const table = page.getComponent({ name: 'BomMaterialSectionTables' })
    await (table.findAllComponents(BomCuttingCatalogSelect)[1]!.getComponent(MaterialSelectionPanel).vm as unknown as { pickName: (id: string) => Promise<void> }).pickName('piece-catalog')
    table.findAllComponents(ElSelect).find(item => item.props('ariaLabel') === '所属部位')!.vm.$emit('change', cutting.lines[0]!.client_key)
    await flushPromises()
    await button(page, '保存草稿').trigger('click')
    await flushPromises()
    const submitted = vi.mocked(api.saveBomDraft).mock.calls[0]![1].find(section => section.title === '裁剪明细')!.lines
    expect(submitted[0]).toMatchObject({ component_kind: 'SEWN_PART', part_name: '床面', specification: '120×60cm', parts_per_product: 1, unit: '个' })
    expect(submitted[1]).toMatchObject({ component_kind: 'CUT_PIECE', parent_part_client_key: submitted[0]!.client_key,
      part_name: '布面', specification: '212.5×86cm', fabric_source_line_id: 'fabric-1', pieces_per_part: 2, unit: '片' })
    expect(submitted[1]!.cutting_sets_per_product).toBeUndefined()
    expect(submitted[0]!.material_catalog_id).toBe('part-catalog')
    expect(submitted[1]!.material_catalog_id).toBe('piece-catalog')
    expect(submitted[0]!.material_selection).toMatchObject({ scope: 'BASE', processing_state: 'PROCESSED', attributes: {}, unit_name: '个' })
    expect(submitted[1]!.material_selection?.completed_craft).toBeUndefined()
    expect(page.find('.cutting-table').exists()).toBe(true)
    expect(catalogApi.createMaterialCatalog).not.toHaveBeenCalled()
  })
})

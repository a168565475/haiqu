import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { createPinia } from 'pinia'
import AiImportBomForm from './AiImportBomForm.vue'
import { makeAiBomDrafts } from './AiImportBomFormData'

const api = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn(), options: vi.fn(), definitions: vi.fn() }))
const calculation = vi.hoisted(() => ({ tube: vi.fn(), hardware: vi.fn() }))
vi.mock('@/api/materialCatalog', () => ({ fetchMaterialCatalogs: api.list, fetchMaterialCatalog: api.detail, fetchMaterialCatalogOptions: api.definitions, fetchPublicMaterialOptions: api.options, materialCatalogError: (error: Error) => error.message }))
vi.mock('@/api/boms', async importOriginal => ({ ...await importOriginal<typeof import('@/api/boms')>(), previewBomTubeCalculation: calculation.tube, previewBomHardwareWeight: calculation.hardware }))
const field = (value: string) => ({ value, status: 'EXTRACTED', source_ids: ['sheet:4'], note: '' })
const result = { products: [{ product_key: 'p1', name: field('椅子'), quantity: field('300') }, { product_key: 'p2', name: field('桌子'), quantity: field('200') }], boms: [
  { product_key: 'p1', lines: [{ line_key: 'line1', section: '待确认', part_name: field('扶手'), material: field(''), specification: field('A型'), quantity: field('600'), unit: field('个'), notes: field(''), raw_content: field('扶手 / A型 / 600个') }] },
  { product_key: 'p2', lines: [{ line_key: 'line2', section: '五金件', part_name: field('螺丝'), material: field('钢'), specification: field('M6'), quantity: field('800'), unit: field('个'), notes: field('') }] },
] }
const global = { plugins: [ElementPlus, createPinia()], stubs: { MaterialSelectionPanel: { name: 'MaterialSelectionPanel', props: ['line', 'presentation', 'fixedUnit', 'catalogOnly'], emits: ['loaded'], template: '<div>材料选择器</div>' }, BomCuttingCatalogSelect: true } }
beforeEach(() => {
  vi.clearAllMocks()
  api.list.mockResolvedValue({ data: [], meta: { page: 1, total_pages: 1, total: 0, page_size: 100 } })
  calculation.tube.mockResolvedValue({ formula_version: 'v1', coating_unit_area_sqm: '0.0481', purchase_unit_weight_kg: '0.2201', long_material_unit_weight_kg: '1.9980' })
  calculation.hardware.mockResolvedValue({ unit_material_weight_kg: '0.0052', unit_weight_g: '5.2', calculation_snapshot: {} })
})
afterEach(() => { document.body.innerHTML = '' })

describe('AI BOM 表单预览', () => {
  it('管材自动对应只用该品名的属性及单位，缺少规格的行留给人工调整', async () => {
    const pipe = (name: string) => ({ line_key: name, section: '管材类', part_name: field(name), material: field('铁'),
      unit: field('根'), erp_fields: { tube_shape: field('圆管'), tube_diameter: field('22'), tube_thickness: field('0.6') } })
    const input = { products: result.products.slice(0, 1), boms: [{ product_key: 'p1', lines: [pipe('甲管'), pipe('乙管')] }] }
    const catalogs = ['甲管', '乙管'].map(name => ({ id: name, name, category_key: 'TUBE', template_key: 'TUBE', updated_at: 'v1', spray_enabled: false }))
    const values = Object.entries({ material: '铁', shape: '圆管', section_size: '22', thickness: '0.6' }).map(([key, value]) =>
      ({ id: key, scope: 'BASE', field_key: key, value, parent_id: key === 'section_size' ? 'shape' : null }))
    api.list.mockImplementation(async ({ q }) => ({ data: catalogs.filter(item => item.name === q), meta: { total_pages: 1 } }))
    api.detail.mockImplementation(async id => ({ data: { ...catalogs.find(item => item.id === id),
      values: id === '甲管' ? values : values.filter(item => item.field_key !== 'section_size'),
      units: [{ id: '关联编号', scope: 'BASE', unit_id: '根编号', unit_name: '根' }] } }))
    const fields = values.map(item => ({ key: item.field_key, label: item.field_key, kind: 'text' }))
    api.definitions.mockResolvedValue({ categories: [{ key: 'TUBE', templates: [{ key: 'TUBE', fields }] }] })
    api.options.mockResolvedValue({ fields, values, units: [{ id: '公共单位编号', unit_name: '根' }] })
    const wrapper = mount(AiImportBomForm, { props: { result: input, modelValue: null, taskProducts: [] }, global })
    await flushPromises()
    const drafts = wrapper.emitted('update:modelValue')!.at(-1)![0] as ReturnType<typeof makeAiBomDrafts>
    const [first, second] = drafts[0]!.sections.find(section => section.title === '管材类')!.lines
    expect(first).toMatchObject({ material_catalog_id: '甲管', material_selection: { attributes: { section_size: '22' }, unit_id: '根编号' } })
    expect(second?.material_catalog_id).toBeFalsy()
    expect(second?.tube_diameter).toBe('22')
    expect(api.options).not.toHaveBeenCalled()
    await wrapper.findAll('button').find(button => button.text() === '调整材料')!.trigger('click')
    expect(wrapper.findComponent({ name: 'MaterialSelectionPanel' }).props()).toMatchObject({ presentation: 'panel', catalogOnly: true })
    wrapper.unmount()
  })

  const matchedSource = (name = '原表螺钉') => ({ ...result.boms[1]!.lines[0]!, part_name: field(name), erp_fields: { unit_consumption: field('4') },
    erp_match: { status: 'MATCHED', note: '已核验', section: '五金件', unit_name: '件',
      catalog: { id: 'catalog-matched', category_key: 'HARDWARE', template_key: 'HARDWARE', name: '标准螺丝', spray_enabled: false, updated_at: 'v1', base_warehouse_id: null, semi_warehouse_id: null, values: [], units: [] },
      selection: { catalog_version: 'v1', scope: 'BASE', processing_state: 'RAW', attributes: { material: '钢', specification: 'M6' }, unit_id: 'unit-piece' } } })

  it('已核验的ERP结果直接填表，部分匹配保留原值，汇总只显示为来源说明', async () => {
    const input = { products: result.products.slice(0, 1), boms: [{ product_key: 'p1', lines: [matchedSource(),
      { ...matchedSource('需核对螺丝'), line_key: 'partial', specification: field('M7'), erp_match: { status: 'PARTIAL', note: '规格需确认', section: '五金件', catalog: null, selection: null } },
      { ...matchedSource('总用量'), line_key: 'reference', raw_content: field('总用量600件，已计入上方材料'), erp_match: { status: 'REFERENCE', note: '汇总不重复计算', section: '', catalog: null, selection: null } },
    ] }] }
    const wrapper = mount(AiImportBomForm, { props: { result: reactive(input), modelValue: null, taskProducts: [] }, global })
    await flushPromises()
    expect(api.list).not.toHaveBeenCalled()
    const drafts = wrapper.emitted('update:modelValue')!.at(-1)![0] as ReturnType<typeof makeAiBomDrafts>
    const lines = drafts[0]!.sections.find(section => section.title === '五金件')!.lines
    expect(lines).toHaveLength(2)
    expect(lines[0]).toMatchObject({ part_name: '原表螺钉', material_catalog_id: 'catalog-matched', unit: '件', unit_consumption: '4' })
    expect(lines[1]).toMatchObject({ specification: 'M7' })
    expect(lines[1]!.material_catalog_id).toBeUndefined()
    expect(drafts[0]!.reference_lines).toHaveLength(1)
    await wrapper.find('.review-toggle').trigger('click')
    expect(wrapper.find('.review-content').text()).toContain('规格需确认')
    expect(wrapper.find('.review-content').text()).toContain('来源说明')
    expect(wrapper.find('.review-content').text()).toContain('总用量600件')
    expect(wrapper.find('.section-table').text()).not.toContain('总用量600件')
    wrapper.unmount()
  })

  it('已存草稿重开不改人工身份，点击现有按钮才补用后端对应结果', async () => {
    const input = { products: result.products.slice(0, 1), boms: [{ product_key: 'p1', lines: [result.boms[1]!.lines[0]!] }] }
    const drafts = makeAiBomDrafts(input, null)
    const lines = drafts[0]!.sections.find(section => section.title === '五金件')!.lines
    lines[0]!.ai_original_text = '用户已经调整的原文'
    const manual = JSON.parse(JSON.stringify(lines[0]!)) as typeof lines[number]
    manual.client_key = 'manual-line'; manual.ai_line_key = 'manual-line'; manual.material_catalog_id = 'manual-catalog'; manual.specification = '用户选定的M8'
    lines.push(manual)
    const latest = { ...input, boms: [{ product_key: 'p1', lines: [matchedSource()] }] }
    const wrapper = mount(AiImportBomForm, { props: { result: latest, modelValue: drafts, taskProducts: [] }, global })
    await flushPromises()
    let emitted = wrapper.emitted('update:modelValue')!.at(-1)![0] as ReturnType<typeof makeAiBomDrafts>
    expect(emitted[0]!.sections.find(section => section.title === '五金件')!.lines[0]!.material_catalog_id).toBeUndefined()
    expect(api.list).not.toHaveBeenCalled()
    await wrapper.findAll('button').find(button => button.text() === '对应 ERP 材料')!.trigger('click')
    await flushPromises()
    emitted = wrapper.emitted('update:modelValue')!.at(-1)![0] as ReturnType<typeof makeAiBomDrafts>
    const updated = emitted[0]!.sections.find(section => section.title === '五金件')!.lines
    expect(updated[0]).toMatchObject({ material_catalog_id: 'catalog-matched', ai_original_text: '用户已经调整的原文' })
    expect(updated[1]).toMatchObject({ material_catalog_id: 'manual-catalog', specification: '用户选定的M8' })
    expect(api.list).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('旧记录按钮请求父页面AI对应，不继续同名字面匹配，结果watch不触发AI', async () => {
    const wrapper = mount(AiImportBomForm, { props: { result, modelValue: makeAiBomDrafts(result, null), taskProducts: [] }, global })
    await flushPromises()
    const button = wrapper.findAll('button').find(button => button.text() === '对应 ERP 材料')!
    await button.trigger('click')
    expect(wrapper.emitted('match-materials')).toHaveLength(1)
    expect(api.list).not.toHaveBeenCalled()
    await wrapper.setProps({ matchingMaterials: true })
    expect(button.attributes('disabled')).toBeDefined()
    await button.trigger('click')
    expect(wrapper.emitted('match-materials')).toHaveLength(1)
    await wrapper.setProps({ result: { ...result, recognition_meta: { version: 3 } } })
    await flushPromises()
    expect(wrapper.emitted('match-materials')).toHaveLength(1)
    wrapper.unmount()
  })

  it('全部已有人工材料身份时不重复查询AI并保留原身份', async () => {
    const drafts = makeAiBomDrafts(result, null)
    for (const draft of drafts) for (const line of [...draft.pending_lines, ...draft.sections.flatMap(section => section.lines)]) line.material_catalog_id = '人工已选材料'
    const wrapper = mount(AiImportBomForm, { props: { result, modelValue: drafts, taskProducts: [] }, global })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '对应 ERP 材料')!.trigger('click')
    expect(wrapper.emitted('match-materials')).toBeUndefined()
    expect(api.list).not.toHaveBeenCalled()
    expect(JSON.stringify(wrapper.emitted('update:modelValue')!.at(-1)![0])).toContain('人工已选材料')
    wrapper.unmount()
  })

  it('已有管材身份也可由按钮应用规范颜色，原制造字段和身份保持', async () => {
    const original = { products: result.products.slice(0, 1), boms: [{ product_key: 'p1', lines: [{ ...result.boms[1]!.lines[0]!, section: '管材类', erp_fields: { tube_coating_color: field('黑色亮光喷塑') } }] }] }
    const drafts = makeAiBomDrafts(original, null), line = drafts[0]!.sections[0]!.lines[0]!
    line.material_catalog_id = 'tube-id'; line.unit_consumption = '6'; line.length_value = '540'; line.tube_cut_piece_count = '11'
    const matched = { ...matchedSource().erp_match, section: '管材类', catalog: { ...matchedSource().erp_match.catalog, id: 'tube-id', category_key: 'TUBE', template_key: 'TUBE', spray_enabled: true }, field_updates: { tube_coating_color: '黑色亮光', powder_coating_color: '黑色亮光' } }
    const current = { ...original, boms: [{ product_key: 'p1', lines: [{ ...original.boms[0]!.lines[0]!, erp_match: matched }] }] }
    const wrapper = mount(AiImportBomForm, { props: { result: current, modelValue: drafts, taskProducts: [] }, global })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '对应 ERP 材料')!.trigger('click'); await flushPromises()
    const after = (wrapper.emitted('update:modelValue')!.at(-1)![0] as typeof drafts)[0]!.sections[0]!.lines[0]!
    expect(after).toMatchObject({ material_catalog_id: 'tube-id', unit_consumption: '6', length_value: '540', tube_cut_piece_count: '11', tube_coating_color: '黑色亮光', powder_coating_color: '黑色亮光' })
    expect(after.notes).toContain('黑色亮光喷塑')
    expect(wrapper.emitted('match-materials')).toBeUndefined()
    wrapper.unmount()
  })

  it.each(['pending', 'failed'])('材料对应阶段%s时不自动字面匹配或调用AI，只接受用户点击', async status => {
    const input = { ...result, recognition_meta: { erp_assistant: { status } } }
    const wrapper = mount(AiImportBomForm, { props: { result: input, modelValue: null, taskProducts: [] }, global })
    await flushPromises()
    expect(api.list).not.toHaveBeenCalled()
    expect(wrapper.emitted('match-materials')).toBeUndefined()
    await wrapper.findAll('button').find(button => button.text() === '对应 ERP 材料')!.trigger('click')
    expect(wrapper.emitted('match-materials')).toHaveLength(1)
    wrapper.unmount()
  })

  it.each(['PARTIAL', 'NOT_FOUND', 'CONFLICT'])('新%s建议先本地应用，维护资料后再次点击才重查，忙碌时不重复发起', async status => {
    const original = { products: result.products.slice(0, 1), boms: [{ product_key: 'p1', lines: [result.boms[1]!.lines[0]!] }] }
    const current = { ...original, boms: [{ product_key: 'p1', lines: [{ ...matchedSource(), erp_match: { status, note: '请补齐材料属性', catalog: null, selection: null, section: '五金件' } }] }] }
    const wrapper = mount(AiImportBomForm, { props: { result: current, modelValue: makeAiBomDrafts(original, null), taskProducts: [] }, global })
    await flushPromises()
    const button = wrapper.findAll('button').find(button => button.text() === '对应 ERP 材料')!
    await button.trigger('click'); await flushPromises()
    expect(wrapper.emitted('match-materials')).toBeUndefined()
    let plans = wrapper.emitted('update:modelValue')!.at(-1)![0] as ReturnType<typeof makeAiBomDrafts>
    expect(plans[0]!.sections.find(section => section.title === '五金件')!.lines[0]!.ai_source.erp_match).toMatchObject({ status })
    await button.trigger('click')
    expect(wrapper.emitted('match-materials')).toHaveLength(1)
    await wrapper.setProps({ matchingMaterials: true })
    await button.trigger('click')
    expect(wrapper.emitted('match-materials')).toHaveLength(1)
    const resolved = { ...original, boms: [{ product_key: 'p1', lines: [matchedSource()] }] }
    await wrapper.setProps({ result: resolved, matchingMaterials: false }); await flushPromises()
    expect(wrapper.emitted('match-materials')).toHaveLength(1)
    await button.trigger('click'); await flushPromises()
    plans = wrapper.emitted('update:modelValue')!.at(-1)![0] as ReturnType<typeof makeAiBomDrafts>
    expect(plans[0]!.sections.find(section => section.title === '五金件')!.lines[0]!.material_catalog_id).toBe('catalog-matched')
    await button.trigger('click')
    expect(wrapper.emitted('match-materials')).toHaveLength(1)
    expect(api.list).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('只有参考说明时先应用新说明，后续点击不启动AI', async () => {
    const original = { products: result.products.slice(0, 1), boms: [{ product_key: 'p1', lines: [result.boms[1]!.lines[0]!] }] }
    const current = { ...original, boms: [{ product_key: 'p1', lines: [{ ...matchedSource(), erp_match: { status: 'REFERENCE', note: '材料汇总，不重复采购' } }] }] }
    const wrapper = mount(AiImportBomForm, { props: { result: current, modelValue: makeAiBomDrafts(original, null), taskProducts: [] }, global })
    await flushPromises()
    const button = wrapper.findAll('button').find(button => button.text() === '对应 ERP 材料')!
    await button.trigger('click'); await flushPromises()
    await button.trigger('click'); await flushPromises()
    expect(wrapper.emitted('match-materials')).toBeUndefined()
    expect((wrapper.emitted('update:modelValue')!.at(-1)![0] as ReturnType<typeof makeAiBomDrafts>)[0]!.reference_lines).toHaveLength(1)
    wrapper.unmount()
  })

  it('来源说明可沿现有调整弹窗改为材料，重开及再次对应不撤销人工纠正', async () => {
    const input = { products: result.products.slice(0, 1), boms: [{ product_key: 'p1', lines: [
      { ...matchedSource('被误判的螺丝'), raw_content: field('实际是独立材料，单耗4件'), erp_match: { status: 'REFERENCE', note: '待核对的汇总判断', section: '', catalog: null, selection: null } },
    ] }] }
    const wrapper = mount(AiImportBomForm, { props: { result: input, modelValue: makeAiBomDrafts(input, null), taskProducts: [] }, global })
    await flushPromises()
    await wrapper.find('.review-toggle').trigger('click')
    expect(wrapper.find('.review-content').text()).toContain('实际是独立材料')
    await wrapper.find('.review-content button').trigger('click')
    await flushPromises()
    const sectionSelect = wrapper.findComponent({ name: 'ElDialog' }).findComponent({ name: 'ElSelect' })
    sectionSelect.vm.$emit('update:modelValue', '五金件')
    sectionSelect.vm.$emit('change', '五金件')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '保留调整')!.trigger('click')
    await flushPromises()
    let saved = wrapper.emitted('update:modelValue')!.at(-1)![0] as ReturnType<typeof makeAiBomDrafts>
    expect(saved[0]!.reference_lines).toHaveLength(0)
    expect(saved[0]!.sections.find(section => section.title === '五金件')!.lines[0]).toMatchObject({ ai_reference_override: true, part_name: '被误判的螺丝', unit_consumption: '4' })
    await wrapper.findAll('button').find(button => button.text() === '对应 ERP 材料')!.trigger('click')
    await flushPromises()
    expect(api.list).not.toHaveBeenCalled()
    saved = wrapper.emitted('update:modelValue')!.at(-1)![0] as ReturnType<typeof makeAiBomDrafts>
    const restored = makeAiBomDrafts(input, saved)
    expect(restored[0]!.reference_lines).toHaveLength(0)
    const material = restored[0]!.sections.find(section => section.title === '五金件')!.lines[0]!
    expect(material.ai_source.erp_match).toMatchObject({ status: 'REFERENCE' })
    expect(material.ai_original_text).toContain('实际是独立材料')
    wrapper.unmount()
  })

  it('旧结果仅找同分区材料，跨类别同名及属性不完整都不迁移分区', async () => {
    const input = { products: result.products.slice(0, 1), boms: [{ product_key: 'p1', lines: [
      { ...result.boms[1]!.lines[0]!, line_key: 'cloth', section: '裁剪明细', part_name: field('管套'), specification: field('13*13CM') },
      { ...result.boms[1]!.lines[0]!, line_key: 'plastic', section: '塑料件类', part_name: field('扶手'), specification: field('Ф16') },
    ] }] }
    const plastic = { id: 'plastic-1', category_key: 'PLASTIC', template_key: 'PLASTIC', name: '扶手', spray_enabled: false, updated_at: 'v1' }
    api.list.mockImplementation(async ({ q }: { q: string }) => ({ data: [{ ...plastic, name: q }], meta: { page: 1, total_pages: 1, total: 1, page_size: 100 } }))
    api.detail.mockResolvedValue({ data: { ...plastic, values: [], units: [], base_warehouse_id: null, semi_warehouse_id: null } })
    api.definitions.mockResolvedValue({ categories: [{ key: 'PLASTIC', templates: [{ key: 'PLASTIC', fields: [{ key: 'specification', label: '规格', kind: 'text' }] }] }] })
    api.options.mockResolvedValue({ category_key: 'PLASTIC', template_key: 'PLASTIC', scope: 'BASE', fields: [{ key: 'specification', label: '规格', kind: 'text' }], values: [], units: [] })
    const wrapper = mount(AiImportBomForm, { props: { result: input, modelValue: null, taskProducts: [] }, global })
    await flushPromises()
    expect(api.list).toHaveBeenCalledWith(expect.objectContaining({ q: '管套', category: 'FABRIC_SEMI' }))
    expect(api.list).toHaveBeenCalledWith(expect.objectContaining({ q: '扶手', category: 'PLASTIC' }))
    expect(api.detail).toHaveBeenCalledTimes(1)
    const drafts = wrapper.emitted('update:modelValue')!.at(-1)![0] as ReturnType<typeof makeAiBomDrafts>
    const cloth = drafts[0]!.sections.find(section => section.title === '裁剪明细')!.lines
    const plasticLines = drafts[0]!.sections.find(section => section.title === '塑料件类')!.lines
    expect(cloth.map(line => line.part_name)).toEqual(['管套'])
    expect(plasticLines.map(line => line.part_name)).toEqual(['扶手'])
    expect([...cloth, ...plasticLines].every(line => !line.material_catalog_id)).toBe(true)
    wrapper.unmount()
  })

  it('支持真实Vue响应式结果，保存全部BOM与未分类原文', async () => {
    const wrapper = mount(AiImportBomForm, { props: { result: reactive(result), modelValue: null, taskProducts: [] }, global })
    await flushPromises()
    expect(wrapper.text()).toContain('椅子 · 1 项')
    expect(wrapper.findAllComponents({ name: 'ElOption' }).map(option => option.props('label'))).toContain('桌子 · 1 项')
    expect(wrapper.text()).toContain('待选分区')
    const drafts = wrapper.emitted('update:modelValue')!.at(-1)![0] as Array<Record<string, unknown>>
    expect(drafts).toHaveLength(2)
    expect(JSON.stringify(drafts)).toContain('扶手 / A型 / 600个')
    expect(() => (wrapper.vm as unknown as { buildPlans: () => unknown }).buildPlans()).toThrow('未选择分区')
    wrapper.unmount()
  })

  it('恢复编辑原文不重跑目录对应，原文尾列可直接调整', async () => {
    const drafts = makeAiBomDrafts(result, null)
    const line = drafts[0]!.pending_lines.shift()!
    line.ai_original_text = '用户已经调整的原文'
    drafts[0]!.sections.find(item => item.title === '塑料件类')!.lines.push(line)
    const wrapper = mount(AiImportBomForm, { props: { result, modelValue: drafts, taskProducts: [] }, global })
    await flushPromises()
    expect(api.list).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('原始识别内容')
    expect(wrapper.text()).toContain('调整材料')
    const textarea = wrapper.find('textarea[aria-label="原始识别内容"]')
    expect((textarea.element as HTMLTextAreaElement).value).toBe('用户已经调整的原文')
    await textarea.setValue('调整后的完整原文')
    const emitted = wrapper.emitted('update:modelValue')!.at(-1)![0]
    expect(JSON.stringify(emitted)).toContain('调整后的完整原文')
    wrapper.unmount()
  })

  it('真实目录查询失败显示错误，保留识别材料', async () => {
    api.list.mockRejectedValue(new Error('当前账号没有查看材料的权限'))
    const wrapper = mount(AiImportBomForm, { props: { result, modelValue: null, taskProducts: [] }, global })
    await flushPromises()
    expect(wrapper.text()).toContain('当前账号没有查看材料的权限')
    expect(wrapper.text()).toContain('扶手')
    expect(wrapper.findAll('button').some(button => button.text() === '对应 ERP 材料')).toBe(true)
    wrapper.unmount()
  })

  it('当前产品选择切换到有内容的材料分区，并保留另一产品已编辑原文', async () => {
    const wrapper = mount(AiImportBomForm, { props: { result, modelValue: makeAiBomDrafts(result, null), taskProducts: [] }, global })
    await flushPromises()
    await wrapper.find('textarea[aria-label="原始识别内容"]').setValue('保留扶手核对结果')
    const productSelect = wrapper.findComponent({ name: 'ElSelect' })
    productSelect.vm.$emit('update:modelValue', 1)
    productSelect.vm.$emit('change', 1)
    await flushPromises()
    expect(wrapper.find('.section-nav button.active').text()).toContain('五金件')
    expect(wrapper.find('.section-table').text()).toContain('螺丝')
    const saved = wrapper.emitted('update:modelValue')!.at(-1)![0]
    expect(JSON.stringify(saved)).toContain('保留扶手核对结果')
    wrapper.unmount()
  })

  it('待核对内容默认收起，展开后保留完整问题并能进入材料调整', async () => {
    const drafts = makeAiBomDrafts(result, null)
    drafts[0]!.pending_lines[0]!.ai_pending = ['ERP材料：品名有多个候选，需要选择']
    const wrapper = mount(AiImportBomForm, { props: { result, modelValue: drafts, taskProducts: [] }, global })
    await flushPromises()
    expect(wrapper.find('.review-content').exists()).toBe(false)
    const toggle = wrapper.find('.review-toggle')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('.review-content').text()).toContain('请选择 BOM 分区')
    expect(wrapper.find('.review-content').text()).toContain('ERP材料：品名有多个候选，需要选择')
    await wrapper.find('.review-content button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('调整 BOM 材料')
    expect(wrapper.find('.section-nav button.active').text()).toContain('待选分区')
    wrapper.unmount()
  })

  it('全屏移出父卡片，切换待选分区后仍可退出并保留原文', async () => {
    const drafts = makeAiBomDrafts(result, null)
    const line = drafts[0]!.pending_lines.shift()!
    drafts[0]!.sections.find(item => item.title === '塑料件类')!.lines.push(line)
    const host = document.createElement('div')
    host.className = 'bom-test-host'
    document.body.append(host)
    const wrapper = mount(AiImportBomForm, { attachTo: host, props: { result, modelValue: drafts, taskProducts: [] }, global })
    await flushPromises()
    await wrapper.find('textarea[aria-label="原始识别内容"]').setValue('全屏前的核对原文')
    expect(host.querySelector('.ai-bom-form')).not.toBeNull()
    await wrapper.find('button[aria-label="全屏"]').trigger('click')
    await flushPromises()
    const fullscreen = document.body.querySelector('.ai-bom-form.is-fullscreen')!
    expect(fullscreen.parentElement).toBe(document.body)
    const pendingSection = Array.from(fullscreen.querySelectorAll<HTMLButtonElement>('.section-nav button')).find(button => button.textContent?.includes('待选分区'))!
    pendingSection.click()
    await flushPromises()
    expect(fullscreen.querySelector('button[aria-label="退出全屏"]')).toBeNull()
    fullscreen.querySelector<HTMLButtonElement>('.fullscreen-exit')!.click()
    await flushPromises()
    expect(document.body.querySelector('.ai-bom-form.is-fullscreen')).toBeNull()
    expect(host.querySelector('.ai-bom-form')).not.toBeNull()
    expect(JSON.stringify(wrapper.emitted('update:modelValue')!.at(-1)![0])).toContain('全屏前的核对原文')
    wrapper.unmount()
  })

  it('预览先跟随核对数量，关联后优先使用真实任务数量', async () => {
    const wrapper = mount(AiImportBomForm, { props: { result, modelValue: makeAiBomDrafts(result, null), taskProducts: [], productQuantities: { p1: '450' } }, global })
    await flushPromises()
    expect(wrapper.text()).toContain('订单数量：450')
    await wrapper.setProps({ taskProducts: [{ id: 'task-p1', client_key: 'p1', quantity: '500' }], productQuantities: { p1: '900' } })
    expect(wrapper.text()).toContain('订单数量：500')
    await wrapper.setProps({ taskProducts: [{ id: 'task-p1', client_key: 'p1' }] })
    expect(wrapper.text()).toContain('订单数量：待确认')
    wrapper.unmount()
  })

  it('用户编辑时取消进行中的目录对应，迟到结果不覆盖调整', async () => {
    let finish!: (value: unknown) => void
    api.list.mockReturnValue(new Promise(resolve => { finish = resolve }))
    const wrapper = mount(AiImportBomForm, { props: { result, modelValue: null, taskProducts: [] }, global })
    await flushPromises()
    await wrapper.find('textarea[aria-label="原始识别内容"]').setValue('人工调整后的原文')
    finish({ data: [{ id: 'cat1', name: '扶手', category_key: 'PLASTIC', template_key: 'PLASTIC' }], meta: { total_pages: 1 } })
    await flushPromises()
    expect(api.detail).not.toHaveBeenCalled()
    expect(JSON.stringify(wrapper.emitted('update:modelValue')!.at(-1)![0])).toContain('人工调整后的原文')
    wrapper.unmount()
  })

  it('材料调整使用完整属性面板，选米前清空非米原单耗并保留原文', async () => {
    const drafts = makeAiBomDrafts(result, null)
    const line = drafts[0]!.pending_lines.shift()!
    line.unit = '码'
    line.unit_consumption = '0.8'
    line.ai_original_text = '原表单耗0.8码'
    drafts[0]!.sections.find(item => item.title === '面料类')!.lines.push(line)
    const wrapper = mount(AiImportBomForm, { props: { result, modelValue: drafts, taskProducts: [] }, global })
    await flushPromises()
    await wrapper.findAll('button').find(item => item.text() === '调整材料')!.trigger('click')
    await flushPromises()
    const panel = wrapper.findComponent({ name: 'MaterialSelectionPanel' })
    expect(panel.props('presentation')).toBe('panel')
    expect(panel.props('fixedUnit')).toBe('米')
    panel.vm.$emit('loaded')
    await flushPromises()
    expect(panel.props('line').unit_consumption).toBe('')
    expect(panel.props('line').ai_original_text).toBe('原表单耗0.8码')
    expect(wrapper.text()).toContain('请核对后填写米制单耗')
    wrapper.unmount()
  })

  it('订单数量未知时仍显示已识别的原材料长度，保留原精度', async () => {
    const drafts = makeAiBomDrafts(result, null)
    const line = drafts[0]!.pending_lines.shift()!
    line.source_raw_bar_length_m = '6.305'
    line.length_value = '695'
    line.unit_consumption = '6'
    line.tube_cut_piece_count = '9'
    drafts[0]!.sections.find(item => item.title === '管材类')!.lines.push(line)
    const wrapper = mount(AiImportBomForm, { props: { result, modelValue: drafts, taskProducts: [], productQuantities: { p1: '' } }, global })
    await flushPromises()
    const cells = wrapper.find('.el-table__body tbody tr').findAll('td')
    expect(cells[9]!.text()).toBe('6.305')
    expect(cells[7]!.text()).toBe('—')
    expect(cells[10]!.text()).toBe('—')
    expect(wrapper.text()).toContain('订单数量：待确认')
    wrapper.unmount()
  })

  it.each([{ mode: undefined, rule: undefined, allowance: '8' }, { mode: 'MANUAL' as const, rule: 'PLUS_5' as const, allowance: '5' }])('采购根数与余量分开展示且不改原用量：$mode/$allowance', async ({ mode, rule, allowance }) => {
    const drafts = makeAiBomDrafts(result, null), line = drafts[0]!.pending_lines.shift()!
    Object.assign(line, { length_value: '540', unit_consumption: '6', tube_cut_piece_count: '11', source_raw_bar_length_m: '5.99', source_purchase_allowance_percent: '1', purchase_allowance_mode: mode, purchase_allowance_rule: rule })
    drafts[0]!.sections[0]!.lines.push(line)
    const wrapper = mount(AiImportBomForm, { props: { result, modelValue: drafts, taskProducts: [], productQuantities: { p1: '1502' } }, global })
    await flushPromises()
    const table = wrapper.find('.section-table .el-table'), headers = table.findAll('thead th').map(cell => cell.text()), cells = table.find('tbody tr').findAll('td')
    expect(cells[headers.indexOf('采购根数')]!.text()).toBe('820')
    expect(cells[headers.indexOf('采购余量（根）')]!.text()).toBe(allowance)
    const after = (wrapper.emitted('update:modelValue')!.at(-1)![0] as typeof drafts)[0]!.sections[0]!.lines[0]!
    expect(after).toMatchObject({ source_purchase_allowance_percent: '1', length_value: '540', unit_consumption: '6', tube_cut_piece_count: '11' })
    expect(after.purchase_allowance_mode).toBe(mode)
    wrapper.unmount()
  })

  it('管材原长保留三位小数，重量面积读取ERP公式且原表值留末列', async () => {
    const drafts = makeAiBomDrafts(result, null)
    const line = drafts[0]!.pending_lines.shift()!
    line.source_raw_bar_length_m = '6.305'
    line.long_material_unit_weight_kg = '1.28'
    line.coating_unit_area_sqm = '0.15'
    line.fabric_meters_per_set = '0.8'
    line.ai_original_text = '原长6.305m；单根重量1.28kg'
    Object.assign(line, { tube_shape: '圆管', tube_diameter: '22', tube_thickness: '0.6', length_value: '695', tube_cut_piece_count: '9' })
    drafts[0]!.sections.find(item => item.title === '管材类')!.lines.push(line)
    const wrapper = mount(AiImportBomForm, { props: { result, modelValue: drafts, taskProducts: [] }, global })
    await flushPromises()
    await wrapper.findAll('button').find(item => item.text() === '调整材料')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('最多 3 位小数')
    expect(wrapper.find('input[aria-label="原材料长度（m）"]').element).toHaveProperty('value', '6.305')
    expect(wrapper.find('details.more-fields').text()).toContain('原材料单根重量（kg）')
    expect(wrapper.find('input[aria-label="喷塑单位面积（㎡）"]').exists()).toBe(true)
    expect(wrapper.find('input[aria-label="喷塑单位面积（㎡）"]').attributes('readonly')).toBeDefined()
    expect(wrapper.find('input[aria-label="每套耗米"]').exists()).toBe(false)
    await wrapper.find('input[aria-label="原材料长度（m）"]').setValue('6.30')
    await flushPromises()
    expect(calculation.tube).toHaveBeenLastCalledWith(expect.objectContaining({ source_raw_bar_length_m: '6.30' }))
    await wrapper.findAll('button').find(item => item.text() === '保留调整')!.trigger('click')
    await flushPromises()
    const saved = wrapper.emitted('update:modelValue')!.at(-1)![0]
    expect(JSON.stringify(saved)).toContain('"source_raw_bar_length_m":"6.30"')
    expect(JSON.stringify(saved)).toContain('"long_material_unit_weight_kg":"1.9980"')
    expect(JSON.stringify(saved)).toContain('原长6.305m；单根重量1.28kg')
    wrapper.unmount()
  })

  it('公式失败保留原文和待处理状态，不静默退回源重量或零', async () => {
    calculation.tube.mockRejectedValue(new Error('当前形状没有有效公式'))
    const drafts = makeAiBomDrafts(result, null)
    const line = drafts[0]!.pending_lines.shift()!
    Object.assign(line, { tube_shape: '圆管', tube_diameter: '22', tube_thickness: '0.6', length_value: '695', purchase_unit_weight_kg: '1.32', ai_original_text: '原表每成品重量1.32kg' })
    drafts[0]!.sections.find(item => item.title === '管材类')!.lines.push(line)
    const wrapper = mount(AiImportBomForm, { props: { result, modelValue: drafts, taskProducts: [] }, global })
    await flushPromises()
    const saved = wrapper.emitted('update:modelValue')!.at(-1)![0] as typeof drafts
    const pipe = saved[0]!.sections[0]!.lines[0]!
    expect(pipe.purchase_unit_weight_kg).toBe('')
    expect(pipe.ai_original_text).toBe('原表每成品重量1.32kg')
    expect(pipe.ai_pending.join('；')).toContain('没有有效公式')
    wrapper.unmount()
  })

  it('原长能算重量也保留切割支数缺项，补齐后仅清除对应提示', async () => {
    const drafts = makeAiBomDrafts(result, null)
    const line = drafts[0]!.pending_lines.shift()!
    Object.assign(line, { tube_shape: '圆管', tube_diameter: '16', tube_thickness: '0.5', length_value: '540',
      unit_consumption: '6', tube_cut_piece_count: '', source_raw_bar_length_m: '5.990',
      ai_original_text: '原表切11支', ai_pending: ['原表字段冲突：颜色'] })
    drafts[0]!.sections.find(item => item.title === '管材类')!.lines.push(line)
    const wrapper = mount(AiImportBomForm, { props: { result, modelValue: drafts, taskProducts: [] }, global })
    await flushPromises()
    const latest = () => (wrapper.emitted('update:modelValue')!.at(-1)![0] as typeof drafts)[0]!.sections[0]!.lines[0]!
    expect(calculation.tube).toHaveBeenCalled()
    expect(latest().long_material_unit_weight_kg).toBe('1.9980')
    expect(latest().ai_pending).toContain('管材用量：切割支数待补，采购数量暂不能计算。')
    await wrapper.find('.review-toggle').trigger('click')
    expect(wrapper.find('.review-content').text()).toContain('切割支数待补')
    await wrapper.findAll('button').find(item => item.text() === '调整材料')!.trigger('click')
    await flushPromises()
    await wrapper.find('input[aria-label="切割支数"]').setValue('11')
    await flushPromises()
    await wrapper.findAll('button').find(item => item.text() === '保留调整')!.trigger('click')
    await flushPromises()
    expect(latest().tube_cut_piece_count).toBe('11')
    expect(latest().ai_pending.some(item => item.startsWith('管材用量：'))).toBe(false)
    expect(latest().ai_pending).toContain('原表字段冲突：颜色')
    expect(latest().ai_original_text).toBe('原表切11支')
    wrapper.unmount()
  })

  it('编辑单耗会更新用量缺项提示，参数未变时不重复发布', async () => {
    const drafts = makeAiBomDrafts(result, null)
    const line = drafts[0]!.pending_lines.shift()!
    Object.assign(line, { tube_shape: '圆管', tube_diameter: '16', tube_thickness: '0.5', length_value: '540',
      unit_consumption: '6', tube_cut_piece_count: '11', source_raw_bar_length_m: '5.990' })
    drafts[0]!.sections.find(item => item.title === '管材类')!.lines.push(line)
    const wrapper = mount(AiImportBomForm, { props: { result, modelValue: drafts, taskProducts: [] }, global })
    await flushPromises()
    await wrapper.findAll('button').find(item => item.text() === '调整材料')!.trigger('click')
    await flushPromises()
    const consumption = wrapper.find('input[aria-label="单耗"]')
    const callsBefore = calculation.tube.mock.calls.length
    await consumption.setValue('')
    await flushPromises()
    await wrapper.findAll('button').find(item => item.text() === '保留调整')!.trigger('click')
    await flushPromises()
    const latest = () => (wrapper.emitted('update:modelValue')!.at(-1)![0] as typeof drafts)[0]!.sections[0]!.lines[0]!
    expect(latest().ai_pending).toContain('管材用量：单耗待补，采购数量暂不能计算。')
    expect(calculation.tube.mock.calls.length).toBe(callsBefore)
    await wrapper.findAll('button').find(item => item.text() === '调整材料')!.trigger('click')
    await flushPromises()
    await wrapper.find('input[aria-label="单耗"]').setValue('6')
    await flushPromises()
    await wrapper.findAll('button').find(item => item.text() === '保留调整')!.trigger('click')
    await flushPromises()
    expect(latest().ai_pending.some(item => item.startsWith('管材用量：'))).toBe(false)
    const emissions = wrapper.emitted('update:modelValue')!.length
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')!.length).toBe(emissions)
    wrapper.unmount()
  })

  it('旧参数的迟到公式结果不覆盖已保留的新切长', async () => {
    let finish!: (value: unknown) => void
    const oldRequest = new Promise(resolve => { finish = resolve })
    calculation.tube.mockImplementation(payload => payload.length_value === '695' ? oldRequest : Promise.resolve({ formula_version: 'v2', coating_unit_area_sqm: '0.9999', purchase_unit_weight_kg: '0.8888', long_material_unit_weight_kg: '2.1' }))
    const drafts = makeAiBomDrafts(result, null)
    const line = drafts[0]!.pending_lines.shift()!
    Object.assign(line, { tube_shape: '圆管', tube_diameter: '22', tube_thickness: '0.6', length_value: '695' })
    drafts[0]!.sections.find(item => item.title === '管材类')!.lines.push(line)
    const wrapper = mount(AiImportBomForm, { props: { result, modelValue: drafts, taskProducts: [] }, global })
    await flushPromises()
    await wrapper.findAll('button').find(item => item.text() === '调整材料')!.trigger('click')
    await flushPromises()
    await wrapper.find('input[aria-label="切割长度（mm）"]').setValue('700')
    await flushPromises()
    await wrapper.findAll('button').find(item => item.text() === '保留调整')!.trigger('click')
    finish({ formula_version: 'old', coating_unit_area_sqm: '10', purchase_unit_weight_kg: '20', long_material_unit_weight_kg: '30' })
    await flushPromises()
    const saved = wrapper.emitted('update:modelValue')!.at(-1)![0] as typeof drafts
    expect(saved[0]!.sections[0]!.lines[0]).toMatchObject({ length_value: '700', coating_unit_area_sqm: '0.9999', purchase_unit_weight_kg: '0.8888' })
    wrapper.unmount()
  })

  it('五金明确源单重不重算，真正缺失才调用可用公式，冲突不当缺失', async () => {
    const hardware = (key: string, weight?: Record<string, unknown>) => ({ line_key: key, section: '五金件', part_name: field('铆钉'), material: field('钢'), specification: field('Φ5*32'), unit: field('个'), erp_fields: weight ? { unit_material_weight_kg: weight } : {} })
    const input = { products: [result.products[0]], boms: [{ product_key: 'p1', lines: [hardware('known', field('0.0043')), hardware('missing'), hardware('conflict', { ...field('0.03'), status: 'CONFLICT' })] }] }
    const drafts = makeAiBomDrafts(input, null)
    const wrapper = mount(AiImportBomForm, { props: { result: input, modelValue: drafts, taskProducts: [] }, global })
    await flushPromises()
    expect(calculation.hardware).toHaveBeenCalledTimes(1)
    const saved = wrapper.emitted('update:modelValue')!.at(-1)![0] as typeof drafts
    const rows = saved[0]!.sections.find(item => item.title === '五金件')!.lines
    expect(rows.map(row => row.unit_material_weight_kg)).toEqual(['0.0043', '0.0052', ''])
    wrapper.unmount()
  })

  it('重开旧核对稿可只读补回棉原料目录身份，保留已改用量与说明', async () => {
    const input = { products: [result.products[0]], boms: [{ product_key: 'p1', lines: [
      { line_key: 'cotton', section: '辅料类', part_name: field('喷胶棉'), material: field('棉'), specification: field('20mm'), unit: field('米'), notes: field('') },
      { line_key: 'cut', section: '裁剪明细', part_name: field('棉裁片'), material: field('棉'), specification: field('111*64CM'), unit: field('片'), source_line_key: 'cotton' },
    ] }] }
    const drafts = makeAiBomDrafts(input, null)
    const cotton = drafts[0]!.sections.find(item => item.title === '辅料类')!.lines[0]!
    cotton.material_catalog_id = 'cotton-id'
    cotton.material_selection = { catalog_version: 'v1', scope: 'BASE', processing_state: 'RAW', attributes: { thickness: '20mm' }, unit_name: '米' }
    cotton.unit_consumption = '0.45'
    cotton.ai_original_text = '人工核对：每成品0.45米'
    api.detail.mockResolvedValue({ data: { id: 'cotton-id', updated_at: 'v1', category_key: 'AUXILIARY', template_key: 'COTTON', name: '喷胶棉' } })
    const wrapper = mount(AiImportBomForm, { props: { result: input, modelValue: drafts, taskProducts: [] }, global })
    await flushPromises()
    expect(api.list).not.toHaveBeenCalled()
    expect(api.detail).toHaveBeenCalledWith('cotton-id')
    const saved = wrapper.emitted('update:modelValue')!.at(-1)![0] as typeof drafts
    expect(saved[0]!.sections.find(item => item.title === '辅料类')!.lines[0]).toMatchObject({ unit_consumption: '0.45', ai_original_text: '人工核对：每成品0.45米', ai_catalog: { category_key: 'AUXILIARY', template_key: 'COTTON' } })
    wrapper.unmount()
  })
})

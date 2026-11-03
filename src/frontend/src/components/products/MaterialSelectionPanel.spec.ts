import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, reactive } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MaterialSelectionPanel from './MaterialSelectionPanel.vue'
import { blankLine } from '@/views/boms/bomEditorHelpers'
import type { MaterialCatalog } from '@/types/materialCatalog'

const api = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn(), options: vi.fn(), publicOptions: vi.fn() }))
const sampleApi = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn(), options: vi.fn(), publicOptions: vi.fn(), crafts: vi.fn() }))
vi.mock('@/api/sampleMaterialSources', () => ({ fetchSampleMaterials: sampleApi.list, fetchSampleMaterial: sampleApi.detail,
  fetchSampleMaterialOptions: sampleApi.options, fetchSamplePublicOptions: sampleApi.publicOptions, fetchSampleMaterialCrafts: sampleApi.crafts }))
vi.mock('@/api/materialCatalog', () => ({
  fetchMaterialCatalogs: api.list, fetchMaterialCatalog: api.detail, fetchMaterialCatalogOptions: api.options,
  fetchPublicMaterialOptions: api.publicOptions,
  materialCatalogError: (error: Error) => error.message,
}))
vi.mock('@/api/boms', () => ({ fetchBomCatalogSelectionOptions: vi.fn().mockResolvedValue({ crafts: [] }) }))
const catalog: MaterialCatalog = {
  id: 'A', name: '铁管A', category_key: 'TUBE', template_key: 'TUBE', spray_enabled: false, updated_at: '2026-10-29T00:00:00Z',
  base_warehouse_id: null, semi_warehouse_id: null,
  values: [
    { id: 'shape1', scope: 'BASE', field_key: 'shape', value: '方管', parent_id: null },
    { id: 'shape2', scope: 'BASE', field_key: 'shape', value: '圆管', parent_id: null },
    { id: 'size1', scope: 'BASE', field_key: 'section_size', value: '25*25', parent_id: 'shape1' },
    { id: 'size2', scope: 'BASE', field_key: 'section_size', value: '32', parent_id: 'shape2' },
    { id: 'material', scope: 'BASE', field_key: 'material', value: '铁', parent_id: null },
  ], units: [{ id: 'allowed', scope: 'BASE', unit_id: 'root', unit_name: '根' }],
}
function publicOptions() {
  return {
    category_key: 'TUBE', template_key: 'TUBE', scope: 'BASE', fields: [],
    values: [
      ...catalog.values.map(value => ({ ...value, id: `public-${value.id}`, parent_id: value.parent_id ? `public-${value.parent_id}` : null })),
      { id: 'public-aluminium', scope: 'BASE', field_key: 'material', value: '公共铝', parent_id: null },
    ],
    units: [{ id: 'root', unit_name: '根' }],
  }
}
beforeEach(() => {
  vi.clearAllMocks()
  api.list.mockResolvedValue({ data: [catalog, { ...catalog, id: 'B', name: '铁管B' }], meta: { total_pages: 1 } })
  api.detail.mockImplementation(async (id: string) => ({ data: id === 'A' ? catalog : { ...catalog, id, name: '铁管B', values: [], units: [] }, etag: 'v1' }))
  api.publicOptions.mockImplementation(async () => publicOptions())
  api.options.mockResolvedValue({ categories: [{ key: 'TUBE', templates: [{ key: 'TUBE', fields: [
    { key: 'material', label: '材质', kind: 'text' }, { key: 'shape', label: '形状', kind: 'shape' },
    { key: 'section_size', label: '规格', kind: 'dimension' }, { key: 'unit', label: '可用单位', kind: 'unit' },
  ] }] }] })
})
async function start() {
  const line = reactive(blankLine())
  const wrapper = mount(MaterialSelectionPanel, { props: { line, sectionTitle: '管材类' } })
  await flushPromises()
  await wrapper.findAll('.name-option')[0]!.trigger('click')
  await flushPromises()
  return { wrapper, line }
}

describe('打样流程选料', () => {
  it('打样管材只选择需求属性，去掉长度且不改变通用面板字段', async () => {
    const definitions = { categories: [{ key: 'TUBE', templates: [{ key: 'TUBE', fields: [
      { key: 'material', label: '材质', kind: 'text' }, { key: 'color', label: '颜色', kind: 'text' },
      { key: 'shape', label: '截面形状', kind: 'shape' }, { key: 'section_size', label: '规格', kind: 'dimension' },
      { key: 'thickness', label: '厚度', kind: 'text' }, { key: 'length', label: '长度', kind: 'text' },
      { key: 'unit', label: '可用单位', kind: 'unit' },
    ] }] }] }
    api.options.mockResolvedValue(definitions)
    sampleApi.options.mockResolvedValue(definitions)
    sampleApi.list.mockImplementation(api.list.getMockImplementation()!)
    sampleApi.detail.mockImplementation(api.detail.getMockImplementation()!)
    sampleApi.publicOptions.mockImplementation(async () => ({ ...publicOptions(), values: [...publicOptions().values,
      { id: 'thickness', scope: 'BASE', field_key: 'thickness', value: '1.2', parent_id: null },
      { id: 'color', scope: 'BASE', field_key: 'color', value: '黑色', parent_id: null },
    ] }))
    const line = reactive(blankLine())
    const wrapper = mount(MaterialSelectionPanel, { props: { line, sectionTitle: '管材类', source: 'sample', fixedUnit: '根' } })
    await flushPromises()
    await wrapper.get('.name-option').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.attribute-group legend').map(item => item.text())).toEqual(['管材类型', '规格', '厚度', '材质', '颜色'])
    await choose(wrapper, '方管')
    await choose(wrapper, '25*25')
    expect(line.material_selection?.attributes).toMatchObject({ shape: '方管', section_size: '25*25' })
    expect(line.material_selection?.attributes).not.toHaveProperty('length')
    expect(line.unit).toBe('根')
    wrapper.unmount()
    const standard = await start()
    expect(standard.wrapper.findAll('.attribute-group legend').map(item => item.text())).toContain('长度')
    standard.wrapper.unmount()
  })
  it('打样隐藏无候选的属性，未选管材类型时仍保留规格引导，通用面板不变', async () => {
    const definitions = { categories: [{ key: 'TUBE', templates: [{ key: 'TUBE', fields: [
      { key: 'material', label: '材质', kind: 'text' }, { key: 'color', label: '颜色', kind: 'text' },
      { key: 'shape', label: '截面形状', kind: 'shape' }, { key: 'section_size', label: '规格', kind: 'dimension' },
      { key: 'thickness', label: '厚度', kind: 'text' }, { key: 'unit', label: '可用单位', kind: 'unit' },
    ] }] }] }
    api.options.mockResolvedValue(definitions)
    sampleApi.options.mockResolvedValue(definitions)
    sampleApi.list.mockImplementation(api.list.getMockImplementation()!)
    sampleApi.detail.mockImplementation(api.detail.getMockImplementation()!)
    sampleApi.publicOptions.mockImplementation(async () => publicOptions())
    const wrapper = mount(MaterialSelectionPanel, { props: { line: reactive(blankLine()), sectionTitle: '管材类', source: 'sample', fixedUnit: '根' } })
    await flushPromises()
    await wrapper.get('.name-option').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.attribute-group legend').map(item => item.text())).toEqual(['管材类型', '规格', '材质'])
    const specification = wrapper.findAll('.attribute-group').find(item => item.get('legend').text() === '规格')!
    expect(specification.attributes('disabled')).toBeDefined()
    expect(specification.text()).toContain('请先选择截面形状')
    await choose(wrapper, '方管')
    expect(specification.attributes('disabled')).toBeUndefined()
    expect(specification.text()).toContain('25*25')
    wrapper.unmount()

    const standard = await start()
    const labels = standard.wrapper.findAll('.attribute-group legend').map(item => item.text())
    expect(labels).toContain('厚度')
    expect(labels).toContain('颜色')
    standard.wrapper.unmount()
  })
  it('打样没有当前候选但有历史值的属性仍可见，不清空历史内容', async () => {
    sampleApi.options.mockResolvedValue({ categories: [{ key: 'TUBE', templates: [{ key: 'TUBE', fields: [
      { key: 'material', label: '材质', kind: 'text' }, { key: 'color', label: '颜色', kind: 'text' },
      { key: 'shape', label: '截面形状', kind: 'shape' }, { key: 'section_size', label: '规格', kind: 'dimension' },
      { key: 'thickness', label: '厚度', kind: 'text' },
    ] }] }] })
    sampleApi.list.mockImplementation(api.list.getMockImplementation()!)
    sampleApi.detail.mockImplementation(api.detail.getMockImplementation()!)
    sampleApi.publicOptions.mockImplementation(async () => publicOptions())
    const line = reactive(blankLine('根'))
    line.material_catalog_id = 'A'
    line.material_selection_snapshot = { schema_version: 1, catalog_id: 'A', catalog_version: 'old', scope: 'BASE', processing_state: 'RAW',
      category_key: 'TUBE', template_key: 'TUBE', name: '历史管材', unit_id: 'root', unit_name: '根', processing_stage: 'RAW', display_name: '历史管材',
      attributes: { material: '铁', shape: '方管', section_size: '25*25', thickness: '历史厚度', color: '历史颜色' } }
    const snapshot = JSON.stringify(line.material_selection_snapshot)
    const wrapper = mount(MaterialSelectionPanel, { props: { line, sectionTitle: '管材类', source: 'sample', fixedUnit: '根' } })
    await flushPromises()
    expect(wrapper.findAll('.attribute-group legend').map(item => item.text())).toEqual(['管材类型', '规格', '厚度', '材质', '颜色'])
    expect(wrapper.findAll('.historical-value').map(item => item.text())).toEqual(['历史厚度（历史值，待重选）', '历史颜色（历史值，待重选）'])
    expect(line.material_selection?.attributes).toMatchObject({ thickness: '历史厚度', color: '历史颜色' })
    expect(JSON.stringify(line.material_selection_snapshot)).toBe(snapshot)
    wrapper.unmount()
  })
  it('仅使用打样窄源且不暴露完整维护入口，仍可选择品名属性', async () => {
    sampleApi.options.mockImplementation(api.options.getMockImplementation()!)
    sampleApi.list.mockImplementation(api.list.getMockImplementation()!)
    sampleApi.detail.mockImplementation(api.detail.getMockImplementation()!)
    sampleApi.publicOptions.mockImplementation(api.publicOptions.getMockImplementation()!)
    const wrapper = mount(MaterialSelectionPanel, { props: { line: reactive(blankLine()), sectionTitle: '管材类', source: 'sample' } })
    await flushPromises()
    expect(sampleApi.options).toHaveBeenCalledOnce()
    expect(sampleApi.list).toHaveBeenCalledOnce()
    expect(wrapper.find('.maintain-link').exists()).toBe(false)
    await wrapper.findAll('.name-option')[0]!.trigger('click')
    await flushPromises()
    expect(sampleApi.detail).toHaveBeenCalledWith('A')
    expect(sampleApi.publicOptions).toHaveBeenCalledWith({ category_key: 'TUBE', template_key: 'TUBE', scope: 'BASE' })
    expect(wrapper.emitted('loaded')?.[0]?.[0]).toEqual(catalog)
    expect(api.list).not.toHaveBeenCalled()
    expect(api.detail).not.toHaveBeenCalled()
    expect(api.options).not.toHaveBeenCalled()
    expect(api.publicOptions).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
async function choose(wrapper: ReturnType<typeof mount>, label: string) {
  const candidate = wrapper.findAll('.attribute-value').find(item => item.text() === label)
  expect(candidate, label).toBeTruthy()
  await candidate!.get('input').setValue(true)
}
async function history() {
  const line = reactive(blankLine('根'))
  line.material_catalog_id = 'A'
  line.material_selection_snapshot = {
    schema_version: 1, catalog_id: 'A', catalog_version: '2026-10-28T00:00:00Z', category_key: 'TUBE', template_key: 'TUBE',
    name: '历史铁管A', scope: 'BASE', processing_state: 'RAW', processing_stage: 'RAW', completed_craft: null, semi_kind: null,
    attributes: { material: '历史材质', shape: '方管', section_size: '25*25' }, unit_id: 'root', unit_name: '根', display_name: '历史铁管A',
  }
  const wrapper = mount(MaterialSelectionPanel, { props: { line, sectionTitle: '管材类', refreshKey: 0 } })
  await flushPromises()
  return { wrapper, line }
}

describe('普通颜色三字段选择', () => {
  function prepare(categoryKey = 'FABRIC') {
    const data = { ...catalog, category_key: categoryKey, template_key: categoryKey, name: '选料品名' }
    const fields = [{ key: 'material', label: '材质', kind: 'text' }, { key: 'color', label: '颜色', kind: 'text' }]
    const colors = [
      { id: 'color-a', color_card: 'A色卡', color_code: '101', color_name: '米白' },
      { id: 'color-b', color_card: 'B色卡', color_code: '102', color_name: '米白' },
      { id: 'color-c', color_card: '', color_code: '', color_name: '黑色' },
    ].map(row => ({ ...row, product_color_id: row.id, scope: 'BASE', field_key: 'color', value: row.color_name, parent_id: null }))
    api.list.mockResolvedValue({ data: [data], meta: { total_pages: 1 } })
    api.detail.mockResolvedValue({ data, etag: 'v1' })
    api.options.mockResolvedValue({ categories: [{ key: categoryKey, templates: [{ key: categoryKey, fields }] }] })
    api.publicOptions.mockResolvedValue({ category_key: categoryKey, template_key: categoryKey, scope: 'BASE',
      fields: fields.map(field => ({ ...field, source: field.key === 'color' ? 'product-colors' : 'fabric-materials' })), units: [],
      values: [...colors, { id: 'material', scope: 'BASE', field_key: 'material', value: 'PE', parent_id: null }],
    })
  }
  it.each([['TUBE', '管材类'], ['HARDWARE', '五金件'], ['PLASTIC', '塑料件类'], ['FABRIC_SEMI', '裁剪明细']] as const)('%s 仍按颜色名选择，不展开面料色卡色号', async (categoryKey, sectionTitle) => {
    prepare(categoryKey)
    const line = reactive(blankLine())
    const wrapper = mount(MaterialSelectionPanel, { props: { line, sectionTitle } })
    await flushPromises()
    await wrapper.get('.name-option').trigger('click')
    await flushPromises()
    expect(wrapper.find('.color-options-table').exists()).toBe(false)
    const colors = wrapper.findAll('.attribute-value').filter(item => ['米白', '黑色'].includes(item.text()))
    expect(colors.map(item => item.text())).toEqual(['米白', '黑色'])
    await choose(wrapper, '米白')
    expect(line.material_selection?.attributes.color).toBe('米白')
    expect(line.material_selection?.product_color_id).toBeUndefined()
    expect(line.fabric_color_card).toBe('')
    expect(line.fabric_color_code).toBe('')
    wrapper.unmount()
  })
  it('同名不同色卡分行选择，保存完整颜色身份并同步面料回显', async () => {
    prepare()
    const line = reactive(blankLine())
    const wrapper = mount(MaterialSelectionPanel, { props: { line, sectionTitle: '面料类' } })
    await flushPromises()
    await wrapper.get('.name-option').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.color-options-table thead th').map(cell => cell.text())).toEqual(['选择', '色卡', '色号', '颜色'])
    expect(wrapper.findAll('.color-options-table tbody tr')).toHaveLength(3)
    await wrapper.findAll('.color-options-table tbody tr')[1]!.trigger('click')
    expect(line.material_selection).toMatchObject({ product_color_id: 'color-b', color_card: 'B色卡', color_code: '102', color_name: '米白', attributes: { color: '米白' } })
    expect(line).toMatchObject({ fabric_color_card: 'B色卡', fabric_color_code: '102', fabric_color_name: '米白' })
    expect(wrapper.findAll('.color-options-table input:checked')).toHaveLength(1)
    await choose(wrapper, 'PE')
    expect(line.material_selection?.product_color_id).toBe('color-b')
    await wrapper.findAll('.color-options-table tbody tr')[2]!.get('input').setValue(true)
    expect(line).toMatchObject({ fabric_color_card: '', fabric_color_code: '', fabric_color_name: '黑色' })
    expect(wrapper.findAll('.color-options-table tbody tr')[2]!.text()).toContain('——黑色')
    wrapper.unmount()
  })
  it('打样面料使用色卡色号颜色单选列表，回显及重选均保留完整颜色身份', async () => {
    prepare()
    sampleApi.options.mockImplementation(api.options.getMockImplementation()!)
    sampleApi.list.mockImplementation(api.list.getMockImplementation()!)
    sampleApi.detail.mockImplementation(api.detail.getMockImplementation()!)
    sampleApi.publicOptions.mockImplementation(api.publicOptions.getMockImplementation()!)
    const line = reactive(blankLine('米'))
    line.material_catalog_id = 'A'
    line.material_selection_snapshot = { schema_version: 1, catalog_id: 'A', catalog_version: 'old', scope: 'BASE', processing_state: 'RAW',
      category_key: 'FABRIC', template_key: 'FABRIC', name: '布料', unit_id: 'meter', unit_name: '米', processing_stage: 'RAW', display_name: '布料 / B色卡 / 102 / 米白 / 米',
      attributes: { color: '米白' }, product_color_id: 'color-b', color_card: 'B色卡', color_code: '102', color_name: '米白' }
    const snapshot = JSON.stringify(line.material_selection_snapshot)
    const wrapper = mount(MaterialSelectionPanel, { props: { line, sectionTitle: '面料类', source: 'sample' } })
    await flushPromises()
    expect(wrapper.find('.color-options-table').exists()).toBe(false)
    expect(wrapper.find('.attribute-groups--fabric-colors').exists()).toBe(false)
    const colors = wrapper.findAll('.attribute-group').find(group => group.get('legend').text() === '颜色')!
    const options = colors.findAll('.attribute-value')
    expect(options.map(option => option.text())).toEqual(['A色卡-101-米白', 'B色卡-102-米白', '黑色'])
    expect(colors.get('.attribute-value:has(input:checked)').text()).toBe('B色卡-102-米白')
    await options[0]!.get('input[type="radio"]').setValue(true)
    expect(colors.findAll('input:checked')).toHaveLength(1)
    expect(line.material_selection).toMatchObject({ product_color_id: 'color-a', color_card: 'A色卡', color_code: '101', color_name: '米白', attributes: { color: '米白' } })
    expect(line).toMatchObject({ fabric_color_card: 'A色卡', fabric_color_code: '101', fabric_color_name: '米白' })
    expect(JSON.stringify(line.material_selection_snapshot)).toBe(snapshot)
    wrapper.unmount()
  })
  it('历史同名颜色不猜色卡，不修改快照，重选后才补齐身份', async () => {
    prepare()
    const line = reactive(blankLine())
    line.material_catalog_id = 'A'
    line.material_selection_snapshot = { schema_version: 1, catalog_id: 'A', catalog_version: 'old', scope: 'BASE',
      category_key: 'FABRIC', template_key: 'FABRIC', name: '布料', unit_id: 'meter', processing_stage: 'RAW', display_name: '布料 / 米白 / 米',
      processing_state: 'RAW', attributes: { color: '米白' }, unit_name: '米' }
    const snapshot = JSON.stringify(line.material_selection_snapshot)
    const wrapper = mount(MaterialSelectionPanel, { props: { line, sectionTitle: '面料类' } })
    await flushPromises()
    expect(wrapper.findAll('.color-options-table input:checked')).toHaveLength(0)
    expect(wrapper.get('.historical-value').text()).toContain('历史值，待重选')
    expect(line.material_selection?.product_color_id).toBeUndefined()
    await wrapper.findAll('.color-options-table tbody tr')[0]!.trigger('click')
    expect(line.material_selection?.product_color_id).toBe('color-a')
    expect(JSON.stringify(line.material_selection_snapshot)).toBe(snapshot)
    wrapper.unmount()
  })
  it('已有三字段快照加载后保持身份，读取公共候选不覆盖原快照', async () => {
    prepare()
    const line = reactive(blankLine())
    line.material_catalog_id = 'A'
    line.material_selection_snapshot = { schema_version: 1, catalog_id: 'A', catalog_version: 'old', scope: 'BASE', processing_state: 'RAW',
      category_key: 'FABRIC', template_key: 'FABRIC', name: '布料', unit_id: 'meter', processing_stage: 'RAW', display_name: '布料 / B色卡 / 102 / 米白 / 米',
      attributes: { color: '米白' }, unit_name: '米', product_color_id: 'color-b', color_card: 'B色卡', color_code: '102', color_name: '米白' }
    const wrapper = mount(MaterialSelectionPanel, { props: { line, sectionTitle: '面料类' } })
    await flushPromises()
    expect(wrapper.get('.color-options-table tr.selected').text()).toContain('B色卡102米白')
    await choose(wrapper, 'PE')
    expect(line.material_selection).toMatchObject({ product_color_id: 'color-b', color_card: 'B色卡', color_code: '102', color_name: '米白' })
    expect(line.material_selection_snapshot?.catalog_version).toBe('old')
    wrapper.unmount()
  })
  async function openColorDropdown(line = reactive(blankLine())) {
    const wrapper = mount(MaterialSelectionPanel, { props: { line, sectionTitle: '面料类', presentation: 'dropdown' },
      global: { stubs: { ElPopover: PopoverStub } } })
    await flushPromises()
    await wrapper.get('.material-name-trigger').trigger('click')
    if (!line.material_catalog_id) await wrapper.get('.name-option').trigger('click')
    await flushPromises()
    const colors = wrapper.findAll('.attribute-group').find(group => group.get('legend').text() === '颜色')!
    return { line, wrapper, colors }
  }
  it('BOM面料固定米，隐藏单位候选并提交公共米单位ID', async () => {
    prepare()
    const definitions = await api.options()
    definitions.categories[0].templates[0].fields.push({ key: 'unit', label: '可用单位', kind: 'unit' })
    const choices = await api.publicOptions()
    choices.units = [{ id: 'meter', unit_name: '米' }, { id: 'set', unit_name: '套' }]
    const line = reactive(blankLine())
    const wrapper = mount(MaterialSelectionPanel, { props: { line, sectionTitle: '面料类', presentation: 'dropdown', fixedUnit: '米' },
      global: { stubs: { ElPopover: PopoverStub } } })
    await flushPromises()
    await wrapper.get('.material-name-trigger').trigger('click')
    await wrapper.get('.name-option').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('legend').map(item => item.text())).not.toContain('单位')
    expect(wrapper.findAll('.attribute-value').some(item => item.text() === '套')).toBe(false)
    expect(line.unit).toBe('米')
    expect(line.material_selection?.unit_id).toBe('meter')
    line.unit_consumption = '0.5'
    await choose(wrapper, 'PE')
    expect(line.unit).toBe('米')
    expect(line.material_selection?.unit_id).toBe('meter')
    expect(line.unit_consumption).toBe('0.5')
    wrapper.unmount()
  })
  it('BOM面料颜色单选占两列，只拼非空字段并按ID区分同名卡号且不收起外层', async () => {
    prepare()
    const { line, wrapper, colors } = await openColorDropdown()
    expect(wrapper.find('table').exists()).toBe(false)
    expect(wrapper.find('.el-select').exists()).toBe(false)
    expect(wrapper.find('.attribute-groups--fabric-colors').exists()).toBe(true)
    const options = colors.findAll('.group-values > label.attribute-value')
    expect(options.map(option => option.text())).toEqual(['A色卡-101-米白', 'B色卡-102-米白', '黑色'])
    expect(colors.findAll('input:not([type="radio"])')).toHaveLength(0)
    for (const [index, id, card, code] of [[0, 'color-a', 'A色卡', '101'], [1, 'color-b', 'B色卡', '102']] as const) {
      await options[index]!.get('input[type="radio"]').setValue(true)
      expect(colors.findAll('input:checked')).toHaveLength(1)
      expect(line.material_selection).toMatchObject({ product_color_id: id, color_card: card, color_code: code, color_name: '米白', attributes: { color: '米白' } })
      expect(wrapper.get('.material-name-trigger').attributes('aria-expanded')).toBe('true')
    }
    await options[2]!.get('input[type="radio"]').setValue(true)
    expect(line.material_selection?.product_color_id).toBe('color-c')
    expect(line).toMatchObject({ fabric_color_card: '', fabric_color_code: '', fabric_color_name: '黑色' })
    expect(line.material_selection_snapshot).toBeUndefined()
    wrapper.unmount()
  })
  it('BOM面料颜色单选回显历史ID，重选只改草稿而不写历史快照', async () => {
    prepare()
    const line = reactive(blankLine())
    line.material_catalog_id = 'A'
    line.material_selection_snapshot = { schema_version: 1, catalog_id: 'A', catalog_version: 'old', scope: 'BASE', processing_state: 'RAW',
      category_key: 'FABRIC', template_key: 'FABRIC', name: '布料', unit_id: 'meter', processing_stage: 'RAW', display_name: '布料 / B色卡 / 102 / 米白 / 米',
      attributes: { color: '米白' }, unit_name: '米', product_color_id: 'color-b', color_card: 'B色卡', color_code: '102', color_name: '米白' }
    const snapshot = JSON.stringify(line.material_selection_snapshot)
    const { wrapper, colors } = await openColorDropdown(line)
    expect(colors.get('.attribute-value:has(input:checked)').text()).toBe('B色卡-102-米白')
    expect(wrapper.find('table').exists()).toBe(false)
    expect(JSON.stringify(line.material_selection_snapshot)).toBe(snapshot)
    await colors.findAll('.attribute-value')[0]!.get('input[type="radio"]').setValue(true)
    expect(line.material_selection?.product_color_id).toBe('color-a')
    expect(JSON.stringify(line.material_selection_snapshot)).toBe(snapshot)
    wrapper.unmount()
  })
  it('BOM面料颜色单选不猜历史同名色卡，缺身份时待重选且不新增候选', async () => {
    prepare()
    const line = reactive(blankLine())
    line.material_catalog_id = 'A'
    line.material_selection_snapshot = { schema_version: 1, catalog_id: 'A', catalog_version: 'old', scope: 'BASE', processing_state: 'RAW',
      category_key: 'FABRIC', template_key: 'FABRIC', name: '布料', unit_id: 'meter', processing_stage: 'RAW', display_name: '布料 / 米白 / 米',
      attributes: { color: '米白' }, unit_name: '米' }
    const snapshot = JSON.stringify(line.material_selection_snapshot)
    const { wrapper, colors } = await openColorDropdown(line)
    expect(colors.find('input:checked').exists()).toBe(false)
    expect(colors.findAll('.attribute-value')).toHaveLength(3)
    expect(wrapper.get('.historical-value').text()).toContain('米白（历史值，待重选）')
    expect(line.material_selection?.product_color_id).toBeUndefined()
    await colors.findAll('.attribute-value')[1]!.get('input[type="radio"]').setValue(true)
    expect(line.material_selection?.product_color_id).toBe('color-b')
    expect(JSON.stringify(line.material_selection_snapshot)).toBe(snapshot)
    wrapper.unmount()
  })
})
describe('BOM持续选料', () => {
  it('候选来自公共配置，所选品名未使用的属性仍可选择', async () => {
    const { wrapper, line } = await start()
    await wrapper.findAll('.name-option')[1]!.trigger('click')
    await flushPromises()
    await choose(wrapper, '公共铝')
    expect(api.publicOptions).toHaveBeenLastCalledWith({ category_key: 'TUBE', template_key: 'TUBE', scope: 'BASE' })
    expect(line.material_catalog_id).toBe('B')
    expect(line.material_selection?.attributes.material).toBe('公共铝')
    wrapper.unmount()
  })
  it('维护刷新失败不退回旧候选或改草稿，重新读取会重试失败请求', async () => {
    const { wrapper, line } = await start()
    await choose(wrapper, '铁')
    const before = JSON.stringify(line.material_selection)
    api.publicOptions.mockRejectedValueOnce(new Error('公共配置不可用'))
    await wrapper.setProps({ refreshKey: 1 })
    await flushPromises()
    expect(wrapper.findAll('.attribute-group')).toHaveLength(0)
    expect(wrapper.get('[role="alert"]').text()).toContain('公共配置不可用')
    expect(JSON.stringify(line.material_selection)).toBe(before)
    expect(api.publicOptions).toHaveBeenCalledTimes(2)
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(api.publicOptions).toHaveBeenCalledTimes(3)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.findAll('.attribute-group')).toHaveLength(4)
    expect(JSON.stringify(line.material_selection)).toBe(before)
    wrapper.unmount()
  })
  it('公共单位尚未关联当前品名时仍提交公共ID并显示所选名称', async () => {
    api.publicOptions.mockResolvedValueOnce({ ...publicOptions(), units: [{ id: 'public-meter', unit_name: '米' }] })
    const { wrapper, line } = await start()
    await choose(wrapper, '米')
    expect(line.material_selection?.unit_id).toBe('public-meter')
    expect(line.unit).toBe('米')
    wrapper.unmount()
  })
  it('历史快照载入后实际选属性使用已加载目录版本，不改历史快照', async () => {
    const { wrapper, line } = await history()
    const snapshot = JSON.parse(JSON.stringify(line.material_selection_snapshot))
    await choose(wrapper, '铁')
    expect(line.material_selection?.catalog_version).toBe(catalog.updated_at)
    expect(line.material_selection_snapshot).toEqual(snapshot)
  })
  it('只重开或改数量不升级历史选择版本，显式重读也不偷换已有草稿版本', async () => {
    const { wrapper, line } = await history()
    line.material_quantity = '12.75'
    const selection = JSON.parse(JSON.stringify(line.material_selection))
    api.detail.mockResolvedValueOnce({ data: { ...catalog, updated_at: '2026-10-30T00:00:00Z' } })
    await wrapper.setProps({ refreshKey: 1 })
    await flushPromises()
    expect(line.material_selection).toEqual(selection)
    expect(line.material_selection_snapshot?.catalog_version).toBe('2026-10-28T00:00:00Z')
    expect(line.material_quantity).toBe('12.75')
  })
  it('已加载后目录另有变化，不在选择或同步时发起刷新以绕过并发版本', async () => {
    const { wrapper, line } = await history()
    api.detail.mockResolvedValue({ data: { ...catalog, updated_at: '未来的另一版本' } })
    await choose(wrapper, '铁')
    expect(api.detail).toHaveBeenCalledTimes(1)
    expect(line.material_selection?.catalog_version).toBe(catalog.updated_at)
  })
  it('切品名读取失败后不允许用旧品名候选构造另一选择', async () => {
    const { wrapper, line } = await start()
    await choose(wrapper, '铁')
    const selection = JSON.parse(JSON.stringify(line.material_selection))
    api.detail.mockRejectedValueOnce(new Error('B读取失败'))
    await wrapper.findAll('.name-option')[1]!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.attribute-group')).toHaveLength(0)
    expect(line.material_catalog_id).toBe('A')
    expect(line.material_selection).toEqual(selection)
  })
  it('迟到的品名详情不覆盖当前成功响应，版本和品名必须匹配', async () => {
    const { wrapper, line } = await start()
    let finishA!: (value: unknown) => void
    api.detail.mockImplementationOnce(() => new Promise(resolve => { finishA = resolve }))
    api.detail.mockResolvedValueOnce({ data: { ...catalog, id: 'B', name: '铁管B', updated_at: 'B版本' } })
    const vm = wrapper.vm as unknown as { pickName: (id: string) => Promise<void> }
    const late = vm.pickName('A')
    await vm.pickName('B')
    finishA({ data: catalog })
    await late
    await flushPromises()
    await choose(wrapper, '铁')
    expect(line.material_catalog_id).toBe('B')
    expect(line.material_selection?.catalog_version).toBe('B版本')
  })
  it('详情ID不匹配请求品名时不接纳响应或改草稿', async () => {
    const { wrapper, line } = await start()
    const selection = JSON.parse(JSON.stringify(line.material_selection))
    api.detail.mockResolvedValueOnce({ data: catalog })
    await wrapper.findAll('.name-option')[1]!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.attribute-group')).toHaveLength(0)
    expect(line.material_catalog_id).toBe('A')
    expect(line.material_selection).toEqual(selection)
    expect(wrapper.get('[role="alert"]').text()).toContain('品名')
  })
  it('逐组选择不收起，并保留形状规格关联', async () => {
    const { wrapper, line } = await start()
    await choose(wrapper, '铁')
    await choose(wrapper, '方管')
    await choose(wrapper, '25*25')
    await choose(wrapper, '根')
    expect(wrapper.findAll('.attribute-group')).toHaveLength(4)
    expect(line.material_selection?.attributes).toEqual({ material: '铁', shape: '方管', section_size: '25*25' })
    expect(line.material_selection?.unit_id).toBe('root')
    await choose(wrapper, '圆管')
    expect(line.material_selection?.attributes.section_size).toBeUndefined()
    expect(wrapper.text()).not.toContain('25*25')
  })
  it('切换品名清除失效属性及单位，不影响其他BOM数据', async () => {
    const { wrapper, line } = await start()
    line.notes = '保留备注'
    await choose(wrapper, '方管')
    await choose(wrapper, '根')
    await wrapper.findAll('.name-option')[1]!.trigger('click')
    await flushPromises()
    expect(line.material_selection?.attributes).toEqual({})
    expect(line.material_selection?.unit_id).toBeUndefined()
    expect(line.notes).toBe('保留备注')
  })
  it('维护入口只发出事件，已选草稿仍保留', async () => {
    const { wrapper, line } = await start()
    await choose(wrapper, '铁')
    await wrapper.get('.maintain-link').trigger('click')
    expect(wrapper.emitted('maintain')).toHaveLength(1)
    expect(line.material_selection?.attributes.material).toBe('铁')
  })
  it('换数量单位只清显式总量，保留旧采购单耗及制造单耗', async () => {
    api.publicOptions.mockResolvedValueOnce({ ...publicOptions(), units: [{ id: 'root', unit_name: '根' }, { id: 'kg', unit_name: '公斤' }] })
    const { wrapper, line } = await start()
    await choose(wrapper, '根')
    line.material_quantity = '12.5'
    line.purchase_consumption = '7'
    line.unit_consumption = '2'
    await choose(wrapper, '公斤')
    expect(line.material_quantity).toBeNull()
    expect(line.unit).toBe('公斤')
    expect(line.purchase_consumption).toBe('7')
    expect(line.unit_consumption).toBe('2')
  })
  it('详情读取失败显示错误且保留当前草稿', async () => {
    const { wrapper, line } = await start()
    await choose(wrapper, '铁')
    api.detail.mockRejectedValueOnce(new Error('网络不可用'))
    await wrapper.findAll('.name-option')[1]!.trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('网络不可用')
    expect(line.material_catalog_id).toBe('A')
    expect(line.material_selection?.attributes.material).toBe('铁')
  })
})


describe('BOM固定根与公共复用隔离', () => {
  it('BOM按固定根选料，不显示品名任意单位，未配置根时随原选项机制提交根', async () => {
    api.detail.mockResolvedValue({ data: { ...catalog, units: [{ id: 'kg', scope: 'BASE', unit_id: 'kg', unit_name: '公斤' }] } })
    api.publicOptions.mockResolvedValueOnce({ ...publicOptions(), units: [{ id: 'kg', unit_name: '公斤' }] })
    const line = reactive(blankLine('根'))
    const wrapper = mount(MaterialSelectionPanel, { props: { line, sectionTitle: '管材类', fixedUnit: '根' } })
    await flushPromises()
    await wrapper.findAll('.name-option')[0]!.trigger('click')
    await flushPromises()
    await choose(wrapper, '铁')
    expect(line.unit).toBe('根')
    expect(line.material_selection?.unit_name).toBe('根')
    expect(line.material_selection?.unit_id).toBeUndefined()
    expect(wrapper.text()).not.toContain('公斤')
    expect(wrapper.findAll('legend').map(item => item.text())).not.toContain('本次数量单位')
    wrapper.unmount()
  })
  it('只读打开不改历史材料快照，公共默认调用仍保留单位候选', async () => {
    const { wrapper, line } = await history()
    const before = JSON.stringify(line.material_selection_snapshot)
    await wrapper.setProps({ fixedUnit: '根' })
    expect(JSON.stringify(line.material_selection_snapshot)).toBe(before)
    wrapper.unmount()
    api.detail.mockResolvedValueOnce({ data: { ...catalog, units: [{ id: 'meter-option', scope: 'BASE', unit_id: 'meter', unit_name: '米' }] } })
    api.publicOptions.mockResolvedValueOnce({ ...publicOptions(), units: [{ id: 'meter', unit_name: '米' }] })
    const plain = await start()
    expect(plain.wrapper.findAll('legend').map(item => item.text())).toContain('本次数量单位')
    await choose(plain.wrapper, '米')
    expect(plain.line.unit).toBe('米')
    expect(plain.line.material_selection?.unit_id).toBe('meter')
    plain.wrapper.unmount()
  })
})

const PopoverStub = defineComponent({
  name: 'ElPopover',
  props: { visible: Boolean },
  emits: ['update:visible'],
  setup(props, { emit, slots }) {
    return () => h('div', [
      h('div', { onClick: () => emit('update:visible', !props.visible) }, slots.reference?.()),
      props.visible ? h('div', { class: 'popover-content' }, slots.default?.()) : null,
    ])
  },
})

describe('BOM下拉只选公共已有值', () => {
  it('仅BOM管材下拉隐藏基础长度，样品面板及历史长度保留', async () => {
    api.options.mockResolvedValue({ categories: [{ key: 'TUBE', templates: [{ key: 'TUBE', fields: [
      { key: 'material', label: '材质', kind: 'text' }, { key: 'length', label: '长度', kind: 'text' },
    ] }] }] })
    const { wrapper, line } = await history()
    line.material_selection!.attributes.length = '6000'
    line.material_selection_snapshot!.attributes.length = '6000'
    const snapshot = JSON.stringify(line.material_selection_snapshot)
    expect(wrapper.findAll('legend').map(item => item.text())).toContain('长度')
    await wrapper.setProps({ presentation: 'dropdown' })
    expect((wrapper.vm as unknown as { fields: Array<{ key: string }> }).fields.map(field => field.key)).not.toContain('length')
    expect(line.material_selection?.attributes.length).toBe('6000')
    expect(JSON.stringify(line.material_selection_snapshot)).toBe(snapshot)
    await wrapper.setProps({ presentation: 'panel' })
    expect(wrapper.findAll('legend').map(item => item.text())).toContain('长度')
    wrapper.unmount()
  })

  it('属性没有输入或新增入口，程序选择也受公共候选约束', async () => {
    const { wrapper, line } = await start()
    expect(wrapper.findAll('.attribute-group input:not([type="radio"])')).toHaveLength(0)
    expect(wrapper.find('.new-value').exists()).toBe(false)
    expect(line.material_selection?.attributes.material).toBeUndefined()
    const vm = wrapper.vm as unknown as { choose: (key: string, value: string) => void }
    vm.choose('material', '未维护材质')
    expect(line.material_selection?.attributes.material).toBeUndefined()
    await choose(wrapper, '公共铝')
    expect(line.material_selection?.attributes.material).toBe('公共铝')
    wrapper.unmount()
  })

  it('默认面板也过滤旧占位候选', async () => {
    const placeholders = [' ', '/', '-', '—']
    api.publicOptions.mockResolvedValueOnce({ ...publicOptions(), values: [
      ...publicOptions().values,
      ...placeholders.map((value, index) => ({ id: `placeholder-${index}`, scope: 'BASE', field_key: 'material', value, parent_id: null })),
    ] })
    const { wrapper, line } = await start()
    const material = wrapper.findAll('.attribute-group').find(item => item.get('legend').text() === '材质')!
    expect(material.findAll('.attribute-value').map(item => item.text())).toEqual(['铁', '公共铝'])
    const vm = wrapper.vm as unknown as { choose: (key: string, value: string) => void }
    for (const value of placeholders) vm.choose('material', value)
    expect(line.material_selection?.attributes.material).toBeUndefined()
    wrapper.unmount()
  })

  it('缺失的历史值只提示待重选，不能作为新候选选择', async () => {
    const { wrapper, line } = await history()
    const snapshot = JSON.stringify(line.material_selection_snapshot)
    const selection = JSON.stringify(line.material_selection)
    expect(wrapper.get('.historical-value').text()).toBe('历史材质（历史值，待重选）')
    expect(wrapper.get('.historical-value').find('input').exists()).toBe(false)
    const vm = wrapper.vm as unknown as { choose: (key: string, value: string) => void }
    vm.choose('material', '历史材质')
    expect(JSON.stringify(line.material_selection_snapshot)).toBe(snapshot)
    expect(JSON.stringify(line.material_selection)).toBe(selection)
    wrapper.unmount()
  })

  it('品名与多项属性持续选择，完成或外部收起后仍显示已选品名', async () => {
    const line = reactive(blankLine())
    const wrapper = mount(MaterialSelectionPanel, {
      props: { line, sectionTitle: '管材类', presentation: 'dropdown' },
      global: { stubs: { ElPopover: PopoverStub } },
    })
    await flushPromises()
    expect(wrapper.find('.material-selection').exists()).toBe(false)
    await wrapper.get('.material-name-trigger').trigger('click')
    await wrapper.findAll('.name-option')[0]!.trigger('click')
    await flushPromises()
    expect(wrapper.get('.material-name-trigger').attributes('aria-expanded')).toBe('true')
    expect(wrapper.text()).toContain('请先选择截面形状')
    await choose(wrapper, '铁')
    await choose(wrapper, '方管')
    await choose(wrapper, '25*25')
    expect(wrapper.get('.material-name-trigger').attributes('aria-expanded')).toBe('true')
    expect(wrapper.findAll('.maintain-link')).toHaveLength(0)
    expect(wrapper.find('.selection-hint').exists()).toBe(false)
    expect(wrapper.get('.selection-footer').text()).toBe('完成选择')
    expect(wrapper.findAll('.selection-footer button')).toHaveLength(1)
    expect(wrapper.findAll('.attribute-group input:not([type="radio"])')).toHaveLength(0)
    await wrapper.get('.selection-footer .erp-list-button').trigger('click')
    expect(wrapper.find('.material-selection').exists()).toBe(false)
    expect(wrapper.get('.material-name-trigger').text()).toBe('铁管A')
    expect(line.material_selection?.attributes).toEqual({ material: '铁', shape: '方管', section_size: '25*25' })
    await wrapper.get('.material-name-trigger').trigger('click')
    wrapper.findComponent(PopoverStub).vm.$emit('update:visible', false)
    await flushPromises()
    expect(wrapper.find('.material-selection').exists()).toBe(false)
    expect(wrapper.get('.material-name-trigger').text()).toBe('铁管A')
    expect(wrapper.emitted('maintain')).toBeUndefined()
    expect(line.material_selection?.attributes.material).toBe('铁')
    wrapper.unmount()
  })
})

function mockSprayCatalog(categoryKey: 'TUBE' | 'HARDWARE', enabled = true) {
  const data = { ...catalog, category_key: categoryKey, template_key: categoryKey, spray_enabled: enabled }
  api.detail.mockImplementation(async (id: string) => ({ data: { ...data, id }, etag: 'v1' }))
  api.options.mockResolvedValue({ categories: [{ key: categoryKey, templates: [{ key: categoryKey, supports_spray: true, fields: [
    { key: 'color', label: '颜色', kind: 'text' },
  ] }] }] })
  api.publicOptions.mockImplementation(async ({ scope }: { scope: 'BASE' | 'SPRAY' }) => ({
    category_key: categoryKey, template_key: categoryKey, scope, fields: [], units: [],
    values: (scope === 'BASE' ? ['普通白'] : ['喷塑黑', '喷塑白']).map(value => ({ id: value, scope, field_key: 'color', value, parent_id: null })),
  }))
}

function mockTubeChoices() {
  mockSprayCatalog('TUBE')
  api.options.mockResolvedValue({ categories: [{ key: 'TUBE', templates: [{ key: 'TUBE', supports_spray: true, fields: [
    { key: 'material', label: '材质', kind: 'text' }, { key: 'color', label: '颜色', kind: 'text' },
    { key: 'shape', label: '形状', kind: 'shape' }, { key: 'section_size', label: '规格', kind: 'dimension' },
    { key: 'thickness', label: '厚度', kind: 'text' },
  ] }] }] })
  api.publicOptions.mockImplementation(async ({ scope }: { scope: 'BASE' | 'SPRAY' }) => scope === 'BASE' ? {
    ...publicOptions(), values: [...publicOptions().values,
      { id: 'white', scope, field_key: 'color', value: '普通白', parent_id: null },
      { id: 'thickness', scope, field_key: 'thickness', value: '1', parent_id: null },
    ],
  } : {
    category_key: 'TUBE', template_key: 'TUBE', scope, fields: [], units: [],
    values: [{ id: 'spray-black', scope, field_key: 'color', value: '喷塑黑', parent_id: null }],
  })
}

async function openTubePicker(line = reactive(blankLine('根'))) {
  const wrapper = mount(MaterialSelectionPanel, {
    props: { line, sectionTitle: '管材类', presentation: 'dropdown', fixedUnit: '根' },
    global: { stubs: { ElPopover: PopoverStub } },
  })
  await flushPromises()
  await wrapper.get('.material-name-trigger').trigger('click')
  return { wrapper, line }
}

describe('BOM管材换品名保留有效选择', () => {
  it('保留五项有效属性与喷塑色，换用新品名版本且断开旧快照', async () => {
    mockTubeChoices()
    const { wrapper, line } = await openTubePicker()
    await wrapper.findAll('.name-option')[0]!.trigger('click')
    await flushPromises()
    for (const value of ['铁', '普通白', '方管', '25*25', '1', '喷塑黑']) await choose(wrapper, value)
    const attributes = { ...line.material_selection!.attributes }
    line.material_selection_snapshot = { ...line.material_selection!, schema_version: 1, catalog_id: 'A',
      category_key: 'TUBE', template_key: 'TUBE', name: '铁管A', unit_id: 'root', unit_name: '根', processing_stage: 'RAW', display_name: '铁管A' }
    const originalSnapshot = line.material_selection_snapshot
    const snapshotBefore = JSON.stringify(originalSnapshot)
    api.detail.mockResolvedValueOnce({ data: { ...catalog, id: 'B', name: '铁管B', updated_at: 'B新版本', spray_enabled: true } })
    await wrapper.findAll('.name-option')[1]!.trigger('click')
    await flushPromises()
    expect(line.material_selection?.attributes).toEqual(attributes)
    expect(line.material_selection?.catalog_version).toBe('B新版本')
    expect(line.material_selection?.scope).toBe('BASE')
    expect(line.material_catalog_id).toBe('B')
    expect(line.part_name).toBe('铁管B')
    expect(line.tube_coating_color).toBe('喷塑黑')
    expect(line.material_selection_snapshot).toBeUndefined()
    expect(JSON.stringify(originalSnapshot)).toBe(snapshotBefore)
    expect(api.publicOptions).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it.each([
    ['方管', '32', { color: '普通白', shape: '方管', thickness: '1' }],
    ['失效形状', '25*25', { color: '普通白', thickness: '1' }],
  ])('新增草稿继承时剔除缺失候选及不属于%s的规格', async (shape, size, expected) => {
    mockTubeChoices()
    const line = reactive(blankLine('根'))
    line.material_selection = { catalog_version: '上一条版本', scope: 'BASE', processing_state: 'RAW',
      attributes: { material: '失效材质', color: '普通白', shape: shape as string, section_size: size as string, thickness: '1', length: '6000' } }
    line.tube_coating_color = '失效喷塑色'
    const { wrapper } = await openTubePicker(line)
    await wrapper.findAll('.name-option')[0]!.trigger('click')
    await flushPromises()
    expect(line.material_selection?.attributes).toEqual(expected)
    expect(line.material_selection?.catalog_version).toBe(catalog.updated_at)
    expect(line.tube_coating_color).toBe('')
    wrapper.unmount()
  })

  it('新品名未启用半成品时只清喷塑色，不清有效基础颜色', async () => {
    mockTubeChoices()
    const line = reactive(blankLine('根'))
    line.material_selection = { catalog_version: '上一条版本', scope: 'BASE', processing_state: 'RAW', attributes: { color: '普通白' } }
    line.tube_coating_color = '喷塑黑'
    api.detail.mockResolvedValueOnce({ data: { ...catalog, spray_enabled: false } })
    const { wrapper } = await openTubePicker(line)
    await wrapper.findAll('.name-option')[0]!.trigger('click')
    await flushPromises()
    expect(line.material_selection?.attributes).toEqual({ color: '普通白' })
    expect(line.tube_coating_color).toBe('')
    wrapper.unmount()
  })

  it('首次空白选名不自动选择任何属性或喷塑色', async () => {
    mockTubeChoices()
    const { wrapper, line } = await openTubePicker()
    await wrapper.findAll('.name-option')[0]!.trigger('click')
    await flushPromises()
    expect(line.material_selection?.attributes).toEqual({})
    expect(line.tube_coating_color).toBe('')
    expect(wrapper.findAll('.attribute-value.selected')).toHaveLength(0)
    wrapper.unmount()
  })

  it('无selection的旧管材字段只继承公共候选中有效值', async () => {
    mockTubeChoices()
    const line = reactive(blankLine('根'))
    Object.assign(line, { material: '铁', tube_shape: '方管', tube_diameter: '25*25', tube_thickness: '1' })
    const { wrapper } = await openTubePicker(line)
    await wrapper.findAll('.name-option')[0]!.trigger('click')
    await flushPromises()
    expect(line.material_selection?.attributes).toEqual({ material: '铁', shape: '方管', section_size: '25*25', thickness: '1' })
    wrapper.unmount()
  })
})

describe('公共候选仅在当前选择器会话复用', () => {
  it('同模板品名复用BASE和SPRAY，详情仍重新读取；重开组件不沿用缓存', async () => {
    mockSprayCatalog('TUBE')
    const { wrapper, line } = await start()
    expect(api.publicOptions).toHaveBeenCalledTimes(2)
    api.detail.mockResolvedValueOnce({ data: { ...catalog, id: 'B', name: '铁管B', spray_enabled: false, updated_at: 'B新版本' } })
    await wrapper.findAll('.name-option')[1]!.trigger('click')
    await flushPromises()
    expect(api.detail).toHaveBeenCalledTimes(2)
    expect(api.publicOptions).toHaveBeenCalledTimes(2)
    expect(line.material_selection?.catalog_version).toBe('B新版本')
    expect(wrapper.emitted('loaded')?.at(-1)?.[0]).toMatchObject({ id: 'B', spray_enabled: false })
    await choose(wrapper, '普通白')
    expect(api.detail).toHaveBeenCalledTimes(2)
    expect(api.publicOptions).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    const reopened = await start()
    expect(api.publicOptions).toHaveBeenCalledTimes(4)
    reopened.wrapper.unmount()
  })

  it('维护关闭清除两种scope的缓存，更新候选并保留已选草稿', async () => {
    mockSprayCatalog('TUBE')
    const { wrapper, line } = await start()
    await choose(wrapper, '普通白')
    line.tube_coating_color = '喷塑黑'
    const before = JSON.stringify(line.material_selection)
    api.publicOptions.mockImplementation(async ({ scope }: { scope: 'BASE' | 'SPRAY' }) => ({
      category_key: 'TUBE', template_key: 'TUBE', scope, fields: [], units: [],
      values: [{ id: scope, scope, field_key: 'color', value: scope === 'BASE' ? '新增蓝' : '新增喷塑蓝', parent_id: null }],
    }))
    await wrapper.setProps({ refreshKey: 1 })
    await flushPromises()
    expect(api.publicOptions).toHaveBeenCalledTimes(4)
    expect(api.detail).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('新增蓝')
    expect(wrapper.emitted('public-options')?.at(-1)?.[0]).toMatchObject({ values: [{ value: '新增喷塑蓝' }] })
    expect(JSON.stringify(line.material_selection)).toBe(before)
    expect(line.tube_coating_color).toBe('喷塑黑')
    wrapper.unmount()
  })

  it('不同category或template不会复用另一上下文的公共候选', async () => {
    const { wrapper } = await start()
    api.detail.mockResolvedValueOnce({ data: { ...catalog, id: 'B', category_key: 'HARDWARE', template_key: 'HARDWARE' } })
    api.publicOptions.mockResolvedValueOnce({ ...publicOptions(), category_key: 'HARDWARE', template_key: 'HARDWARE' })
    await wrapper.findAll('.name-option')[1]!.trigger('click')
    await flushPromises()
    expect(api.publicOptions).toHaveBeenCalledTimes(2)
    expect(api.publicOptions).toHaveBeenLastCalledWith({ category_key: 'HARDWARE', template_key: 'HARDWARE', scope: 'BASE' })
    wrapper.unmount()
  })

  it('响应上下文不匹配时拒绝并且不缓存，后续选择重新请求', async () => {
    api.publicOptions.mockResolvedValueOnce({ ...publicOptions(), scope: 'SPRAY' })
    const { wrapper, line } = await start()
    expect(wrapper.get('[role="alert"]').text()).toContain('公共属性与当前品名模板不一致')
    expect(line.material_catalog_id).toBeFalsy()
    await wrapper.findAll('.name-option')[0]!.trigger('click')
    await flushPromises()
    expect(api.publicOptions).toHaveBeenCalledTimes(2)
    expect(line.material_catalog_id).toBe('A')
    wrapper.unmount()
  })

  it('维护刷新前迟到的公共候选不能覆盖新选择或写回缓存', async () => {
    let finishOld!: (value: unknown) => void
    api.publicOptions.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
    const wrapper = mount(MaterialSelectionPanel, { props: { line: reactive(blankLine()), sectionTitle: '管材类' } })
    await flushPromises()
    const vm = wrapper.vm as unknown as { pickName: (id: string) => Promise<void> }
    const oldRequest = vm.pickName('A')
    await flushPromises()
    await wrapper.setProps({ refreshKey: 1 })
    await flushPromises()
    await vm.pickName('B')
    finishOld({ ...publicOptions(), values: [{ id: 'old', scope: 'BASE', field_key: 'material', value: '迟到旧候选', parent_id: null }] })
    await oldRequest
    await vm.pickName('A')
    await flushPromises()
    expect(api.publicOptions).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('公共铝')
    expect(wrapper.text()).not.toContain('迟到旧候选')
    wrapper.unmount()
  })
})

describe('BOM包材精简选择属性', () => {
  it.each([
    ['CARTON', ['material', 'layers', 'size', 'box_type', 'model', 'color', 'printing', 'unit']],
    ['BAG', ['material', 'color', 'size', 'box_type', 'model', 'thickness', 'bag_type', 'printing', 'unit']],
    ['PACKAGING_GENERAL', ['material', 'color', 'specification', 'box_type', 'model', 'unit']],
  ] as const)('%s不展示层数和印刷选项，保留纸质、箱型、型号及历史值', async (templateKey, keys) => {
    const labels: Record<string, string> = { material: '纸质/材质', box_type: '箱子形状', model: '型号', layers: '层数', printing: '印刷版本/唛头', unit: '可用单位' }
    api.options.mockResolvedValue({ categories: [{ key: 'PACKAGING', templates: [{ key: templateKey,
      fields: keys.map(key => ({ key, label: labels[key] || key, kind: key === 'unit' ? 'unit' : 'text' })),
    }] }] })
    api.detail.mockResolvedValue({ data: { ...catalog, category_key: 'PACKAGING', template_key: templateKey }, etag: 'v1' })
    api.publicOptions.mockResolvedValue({ category_key: 'PACKAGING', template_key: templateKey, scope: 'BASE',
      fields: [], values: [{ id: 'material', field_key: 'material', value: '新纸质' }], units: [] })
    const hidden = Object.fromEntries(keys.filter(key => ['layers', 'printing'].includes(key)).map(key => [key, '历史原文']))
    const line = reactive({ ...blankLine(), material_catalog_id: 'A', material_selection: {
      catalog_version: catalog.updated_at, scope: 'BASE' as const, processing_state: 'RAW' as const, attributes: { ...hidden },
    } })
    const wrapper = mount(MaterialSelectionPanel, { props: { line, sectionTitle: '包材类', presentation: 'dropdown' },
      global: { stubs: { ElPopover: PopoverStub } } })
    await flushPromises()
    await wrapper.get('.material-name-trigger').trigger('click')
    const shown = wrapper.findAll('legend').map(field => field.text())
    expect(shown).toEqual(expect.arrayContaining(['纸质/材质', '箱子形状', '型号', '本次数量单位']))
    expect(shown.some(label => /层数|印刷/.test(label))).toBe(false)
    await choose(wrapper, '新纸质')
    expect(line.material_selection.attributes).toMatchObject({ ...hidden, material: '新纸质' })
    wrapper.unmount()
  })
})

describe('BOM弹层独立喷塑颜色', () => {
  it.each([
    ['PLASTIC', '塑料件类', ['material', 'color', 'model', 'size', 'tube_size', 'specification', 'unit'], ['材质', '颜色', '规格', '本次数量单位'], 'model'],
    ['FABRIC', '面料类', ['material', 'color', 'fabric_spec', 'width', 'gram_weight', 'finish', 'unit'], ['材质', '颜色', '面料规格', '门幅', '单位'], 'finish'],
  ] as const)('%s精简可选字段，改选时不删除已保存的隐藏属性', async (categoryKey, sectionTitle, keys, labels, hiddenKey) => {
    const fieldLabels: Record<string, string> = { material: '材质', color: '颜色', specification: '规格描述', fabric_spec: '面料规格', width: '门幅', unit: '可用单位' }
    api.options.mockResolvedValue({ categories: [{ key: categoryKey, templates: [{ key: categoryKey,
      fields: keys.map(key => ({ key, label: fieldLabels[key] || key, kind: 'text' })),
    }] }] })
    api.detail.mockResolvedValue({ data: { ...catalog, category_key: categoryKey, template_key: categoryKey }, etag: 'v1' })
    api.publicOptions.mockResolvedValue({ category_key: categoryKey, template_key: categoryKey, scope: 'BASE',
      fields: [], values: [{ id: 'material', field_key: 'material', value: '新材质' }], units: [] })
    const line = reactive({ ...blankLine(), material_catalog_id: 'A', material_selection: {
      catalog_version: catalog.updated_at, scope: 'BASE' as const, processing_state: 'RAW' as const, attributes: { [hiddenKey]: '历史隐藏值' },
    } })
    const wrapper = mount(MaterialSelectionPanel, { props: { line, sectionTitle, presentation: 'dropdown' },
      global: { stubs: { ElPopover: PopoverStub } } })
    await flushPromises()
    await wrapper.get('.material-name-trigger').trigger('click')
    expect(wrapper.findAll('legend').map(field => field.text())).toEqual(labels)
    await choose(wrapper, '新材质')
    expect(line.material_selection.attributes).toMatchObject({ material: '新材质', [hiddenKey]: '历史隐藏值' })
    wrapper.unmount()
  })

  it.each([
    ['TUBE', '管材类', 'tube_coating_color'],
    ['HARDWARE', '五金件', 'powder_coating_color'],
  ] as const)('%s 喷塑颜色与普通颜色分离，并和外部表单共享已选值', async (categoryKey, sectionTitle, colorField) => {
    mockSprayCatalog(categoryKey)
    const line = reactive(blankLine())
    line[colorField] = '原品名喷塑色'
    const wrapper = mount(MaterialSelectionPanel, {
      props: { line, sectionTitle, presentation: 'dropdown', refreshKey: 0 },
      global: { stubs: { ElPopover: PopoverStub } },
    })
    await flushPromises()
    await wrapper.get('.material-name-trigger').trigger('click')
    await wrapper.findAll('.name-option')[0]!.trigger('click')
    await flushPromises()
    expect(line[colorField]).toBe('')
    expect(wrapper.get('.spray-color-group').find('.selected').exists()).toBe(false)
    await choose(wrapper, '普通白')
    await choose(wrapper, '喷塑黑')
    expect(line[colorField]).toBe('喷塑黑')
    expect(line.material_selection?.attributes).toEqual({ color: '普通白' })
    line[colorField] = '喷塑白'
    await flushPromises()
    expect(wrapper.get('.spray-color-group .selected').text()).toBe('喷塑白')
    await wrapper.setProps({ refreshKey: 1 })
    await flushPromises()
    expect(line[colorField]).toBe('喷塑白')
    expect(wrapper.get('.spray-color-group .selected').text()).toBe('喷塑白')
    expect(wrapper.emitted('public-options')?.at(-1)?.[0]).toMatchObject({ scope: 'SPRAY' })
    await wrapper.findAll('.name-option')[1]!.trigger('click')
    await flushPromises()
    expect(line[colorField]).toBe(categoryKey === 'TUBE' ? '喷塑白' : '')
    wrapper.unmount()
  })

  it('五金下拉只保留五项基础属性及已启用的喷塑颜色', async () => {
    mockSprayCatalog('HARDWARE')
    api.options.mockResolvedValue({ categories: [{ key: 'HARDWARE', templates: [{ key: 'HARDWARE', supports_spray: true,
      fields: ['material', 'color', 'surface_finish', 'specification', 'size', 'thread', 'flow_unit', 'unit'].map(key => ({ key, label: key, kind: 'text' })),
    }] }] })
    const wrapper = mount(MaterialSelectionPanel, {
      props: { line: reactive(blankLine()), sectionTitle: '五金件', presentation: 'dropdown' },
      global: { stubs: { ElPopover: PopoverStub } },
    })
    await flushPromises()
    await wrapper.get('.material-name-trigger').trigger('click')
    await wrapper.findAll('.name-option')[0]!.trigger('click')
    await flushPromises()
    expect(wrapper.get('.attribute-groups').classes()).not.toContain('attribute-groups--four-columns')
    expect(wrapper.get('.attribute-groups').attributes('style')).toContain('--material-attribute-rows: 2')
    expect(wrapper.findAll('legend').map(field => field.text())).toEqual(['material', 'color', '型号规格', 'flow_unit', '本次数量单位', '喷塑颜色'])
    wrapper.unmount()
  })

  it.each([['TUBE', '管材类', 'tube_coating_color'], ['HARDWARE', '五金件', 'powder_coating_color']] as const)('%s未启用半成品时隐藏喷塑组且保留载入的历史颜色', async (categoryKey, sectionTitle, colorField) => {
    mockSprayCatalog(categoryKey, false)
    const line = reactive(blankLine())
    line.material_catalog_id = 'A'
    line[colorField] = '旧喷塑色'
    const wrapper = mount(MaterialSelectionPanel, {
      props: { line, sectionTitle, presentation: 'dropdown' },
      global: { stubs: { ElPopover: PopoverStub } },
    })
    await flushPromises()
    await wrapper.get('.material-name-trigger').trigger('click')
    expect(wrapper.find('.spray-color-group').exists()).toBe(false)
    const vm = wrapper.vm as unknown as { chooseSprayColor: (value: string) => void }
    vm.chooseSprayColor('喷塑黑')
    expect(line[colorField]).toBe('旧喷塑色')
    expect(line.material_selection?.attributes.color).toBeUndefined()
    wrapper.unmount()
  })

  it('品名分页使用独立箭头，搜索原文交给后端匹配', async () => {
    api.list.mockResolvedValue({ data: [catalog], meta: { total_pages: 2 } })
    const { wrapper } = await start()
    expect(wrapper.get('.catalog-pages').text()).toBe('1/2')
    expect(wrapper.get('.catalog-name-list').find('.catalog-pages').exists()).toBe(false)
    expect(wrapper.get('[aria-label="上一页"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[aria-label="下一页"]').trigger('click')
    await flushPromises()
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }))
    await wrapper.get('[aria-label="筛选品名"]').setValue('uxzcg')
    await wrapper.get('.catalog-names form').trigger('submit')
    await flushPromises()
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'uxzcg', page: 1 }))
    wrapper.unmount()
  })
})

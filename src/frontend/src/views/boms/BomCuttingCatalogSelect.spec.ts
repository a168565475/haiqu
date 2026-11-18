import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { ElSelect } from 'element-plus'
import { defineComponent, h, reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MaterialCatalog } from '@/types/materialCatalog'
import { blankLine } from './bomEditorHelpers'
import BomCuttingCatalogSelect from './BomCuttingCatalogSelect.vue'
import MaterialSelectionPanel from '@/components/products/MaterialSelectionPanel.vue'

const api = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn(), options: vi.fn(), legacyOptions: vi.fn(), crafts: vi.fn() }))
vi.mock('@/api/materialCatalog', () => ({
  fetchMaterialCatalogs: api.list, fetchMaterialCatalog: api.detail, fetchPublicMaterialOptions: api.options,
  fetchMaterialCatalogOptions: api.legacyOptions,
  materialCatalogError: (issue: Error) => issue.message,
}))
vi.mock('@/api/boms', () => ({ fetchBomCatalogSelectionOptions: api.crafts }))
const catalog: MaterialCatalog = {
  id: 'cutting-a', name: '床面', category_key: 'FABRIC_SEMI', template_key: 'FABRIC_SEMI',
  updated_at: 'v2', spray_enabled: false, base_warehouse_id: null, semi_warehouse_id: null, values: [], units: [],
}
let wrapper: VueWrapper | undefined
const popover = defineComponent({
  name: 'ElPopover', props: { visible: Boolean }, emits: ['update:visible'],
  setup(props, { emit, slots }) {
    return () => h('div', [h('div', { onClick: () => emit('update:visible', !props.visible) }, slots.reference?.()),
      props.visible ? h('div', slots.default?.()) : null])
  },
})
const componentGlobal = { stubs: { ElPopover: popover } }
const createLine = () => reactive({ ...blankLine(), material: '涤纶', specification: '600D', fabric_width: '1.5', cutting_color: '蓝色' })
beforeEach(() => {
  vi.clearAllMocks()
  api.list.mockResolvedValue({ data: [catalog], meta: { page: 1, total_pages: 1 } })
  api.detail.mockResolvedValue({ data: catalog, etag: 'v2' })
  api.options.mockResolvedValue({ category_key: 'FABRIC_SEMI', template_key: 'FABRIC_SEMI', scope: 'BASE', fields: [],
    values: [{ id: 'size', scope: 'BASE', field_key: 'size', value: '50×60cm', parent_id: null }], units: [{ id: 'set-unit', unit_name: '套' }] })
  api.legacyOptions.mockResolvedValue({ categories: [{ key: 'FABRIC_SEMI', templates: [{ key: 'FABRIC_SEMI', fields: [
    { key: 'color', label: '颜色', kind: 'text' }, { key: 'size', label: '加工后尺寸', kind: 'dimension' }, { key: 'unit', label: '可用单位', kind: 'unit' },
  ] }] }], units: [] })
  api.crafts.mockResolvedValue({ crafts: [
    { id: 'external', name: '裁剪', craft_type: 'EXTERNAL', code: 'CUTTING' },
    { id: 'internal', name: '裁剪', craft_type: 'INTERNAL', code: 'CUTTING' },
  ] })
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

describe('裁片普通品名下拉', () => {
  it('表格挂载只回显品名，首次展开读取一次候选，重复展开不重读且搜索仍有效', async () => {
    const line = createLine()
    Object.assign(line, { component_kind: 'SEWN_PART', material_catalog_id: catalog.id, part_name: catalog.name, unit: '个' })
    wrapper = mount(BomCuttingCatalogSelect, { props: { line, lazy: true, refreshKey: 0 }, global: componentGlobal })
    await flushPromises()
    expect(api.list).not.toHaveBeenCalled()
    expect(wrapper.get('.material-name-trigger').text()).toBe('床面')
    await wrapper.setProps({ refreshKey: 1 })
    await flushPromises()
    expect(api.list).not.toHaveBeenCalled()
    await wrapper.get('.material-name-trigger').trigger('click')
    await flushPromises()
    expect(api.list).toHaveBeenCalledTimes(1)
    expect(wrapper.get('.name-option').attributes('disabled')).toBeUndefined()
    await wrapper.get('.material-name-trigger').trigger('click')
    await wrapper.get('.material-name-trigger').trigger('click')
    await flushPromises()
    expect(api.list).toHaveBeenCalledTimes(1)
    await wrapper.get('[aria-label="筛选品名"]').setValue('chuang')
    await wrapper.get('.catalog-names form').trigger('submit')
    await flushPromises()
    expect(api.list).toHaveBeenCalledTimes(2)
    expect(api.list).toHaveBeenLastCalledWith({ category: 'FABRIC_SEMI', q: 'chuang', page: 1, page_size: 50 })
    expect(line.part_name).toBe('床面')
  })

  it.each(['SEWN_PART', 'CUT_PIECE'] as const)('新 %s 使用公共属性和 BOM 单位，保留物料资料且不请求工艺', async kind => {
    const line = createLine()
    Object.assign(line, { component_kind: kind, unit: kind === 'SEWN_PART' ? '个' : '套', notes: '保留', fabric_source_line_id: kind === 'CUT_PIECE' ? 'fabric' : null })
    wrapper = mount(BomCuttingCatalogSelect, { props: { line }, global: componentGlobal })
    await flushPromises()
    await wrapper.get('.material-name-trigger').trigger('click')
    await wrapper.get('.name-option').trigger('click')
    await flushPromises()
    expect(line).toMatchObject({ part_name: '床面', material_catalog_id: catalog.id, material: '涤纶', specification: '600D', fabric_width: '1.5', cutting_color: '蓝色', notes: '保留' })
    expect(line.material_selection).toEqual({ catalog_version: 'v2', scope: 'BASE', processing_state: 'PROCESSED', attributes: {}, unit_name: kind === 'SEWN_PART' ? '个' : '套' })
    expect(wrapper.findAll('legend').map(item => item.text())).toEqual(['加工后尺寸'])
    await wrapper.get('.attribute-value input').setValue(true)
    expect(line.material_selection?.attributes).toEqual({ size: '50×60cm' })
    expect(line.fabric_source_line_id).toBe(kind === 'CUT_PIECE' ? 'fabric' : null)
    expect(api.options).toHaveBeenCalledWith({ category_key: 'FABRIC_SEMI', template_key: 'FABRIC_SEMI', scope: 'BASE' })
    expect(api.crafts).not.toHaveBeenCalled()
    expect(wrapper.find('.craft-field').exists()).toBe(false)
  })

  it.each(['SEWN_PART', 'CUT_PIECE'] as const)('%s 重选品名保留单位，同目录保留属性且换目录不携带旧选项', async kind => {
    const line = createLine()
    Object.assign(line, { component_kind: kind, material_catalog_id: catalog.id, unit: '套',
      material_selection: { catalog_version: 'v1', scope: 'BASE', processing_state: 'PROCESSED', attributes: { color: '蓝色', model: '旧款号' }, unit_name: '套' } })
    wrapper = mount(BomCuttingCatalogSelect, { props: { line }, global: componentGlobal })
    await flushPromises()
    await wrapper.get('.material-name-trigger').trigger('click')
    await wrapper.get('.name-option').trigger('click')
    await flushPromises()
    expect(line.material_selection?.attributes).toEqual({ model: '旧款号' })
    expect(line).toMatchObject({ unit: '套', material_selection: { unit_name: '套' } })
    api.detail.mockResolvedValue({ data: { ...catalog, id: 'different', name: '外袋' } })
    await (wrapper.getComponent(MaterialSelectionPanel).vm as unknown as { pickName: (id: string) => Promise<void> }).pickName('different')
    await flushPromises()
    expect(line.material_selection?.attributes).toEqual({})
    expect(line).toMatchObject({ unit: '套', material_selection: { unit_name: '套' } })
    expect(line.material).toBe('涤纶')
  })

  it('请求途中切换类型不会把旧响应覆盖新类型', async () => {
    let resolveDetail!: (value: { data: MaterialCatalog }) => void
    api.detail.mockImplementation(() => new Promise(resolve => { resolveDetail = resolve }))
    const line = createLine()
    line.component_kind = 'CUT_PIECE'
    wrapper = mount(BomCuttingCatalogSelect, { props: { line }, global: componentGlobal })
    await flushPromises()
    await wrapper.get('.material-name-trigger').trigger('click')
    await wrapper.get('.name-option').trigger('click')
    line.component_kind = 'SEWN_PART'
    await flushPromises()
    resolveDetail({ data: catalog })
    await flushPromises()
    expect(line.material_catalog_id).toBeFalsy()
    expect(wrapper.emitted('selected')).toBeUndefined()
  })
  it('只显示普通品名下拉，无选择面板、属性、单位或工艺选择', async () => {
    wrapper = mount(BomCuttingCatalogSelect, { props: { line: createLine() } })
    await flushPromises()
    expect(wrapper.findAllComponents(ElSelect)).toHaveLength(1)
    expect(wrapper.get('[role="combobox"]').attributes('aria-label')).toBe('裁片品名')
    expect(wrapper.find('.material-selection-field').exists()).toBe(false)
    for (const label of ['本次数量单位', '材质', '门幅', '已完成工艺']) expect(wrapper.text()).not.toContain(label)
    expect(api.list).toHaveBeenCalledWith({ category: 'FABRIC_SEMI', q: '', page: 1, page_size: 100 })
  })

  it('读取所有分页且远程搜索仍传给现有拼音检索接口', async () => {
    api.list.mockResolvedValueOnce({ data: [catalog], meta: { page: 1, total_pages: 2 } })
      .mockResolvedValueOnce({ data: [{ ...catalog, id: 'cutting-b', name: '靠背' }], meta: { page: 2, total_pages: 2 } })
    wrapper = mount(BomCuttingCatalogSelect, { props: { line: createLine() } })
    await flushPromises()
    expect(api.list).toHaveBeenNthCalledWith(2, { category: 'FABRIC_SEMI', q: '', page: 2, page_size: 100 })
    expect(wrapper.findAllComponents({ name: 'ElOption' })).toHaveLength(2)
    const search = wrapper.getComponent(ElSelect).props('remoteMethod') as (query: string) => void
    search('chuang')
    await flushPromises()
    expect(api.list).toHaveBeenLastCalledWith({ category: 'FABRIC_SEMI', q: 'chuang', page: 1, page_size: 100 })
  })

  it('选择后读取真实档案版本，成功前不更改当前选择', async () => {
    let resolveDetail!: (result: { data: MaterialCatalog }) => void
    api.detail.mockImplementation(() => new Promise(resolve => { resolveDetail = resolve }))
    const line = createLine()
    line.material_catalog_id = 'old'
    line.part_name = '历史裁片'
    wrapper = mount(BomCuttingCatalogSelect, { props: { line } })
    await flushPromises()
    wrapper.getComponent(ElSelect).vm.$emit('change', catalog.id)
    await flushPromises()
    expect(wrapper.emitted('selected')).toBeUndefined()
    expect(wrapper.getComponent(ElSelect).props('modelValue')).toBe('old')
    resolveDetail({ data: catalog })
    await flushPromises()
    expect(wrapper.emitted('selected')).toEqual([[catalog]])
    expect(line.unit).toBe('套')
    expect(line.material_selection).toMatchObject({ unit_id: 'set-unit', processing_state: 'PROCESSED', semi_kind: 'CUTTING',
      completed_craft: { id: 'internal', craft_type: 'INTERNAL', code: 'CUTTING' },
      attributes: { material: '涤纶', width: '1.5', color: '蓝色', specification: '600D' } })
    expect(line.material_selection?.unit_name).toBeUndefined()
    expect(api.options).toHaveBeenCalledWith({ category_key: 'FABRIC_SEMI', template_key: 'FABRIC_SEMI', scope: 'BASE' })
    expect(api.legacyOptions).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('裁片单位不可用')
  })

  it('读取失败可重试，错误不伪装为选料成功', async () => {
    api.list.mockRejectedValueOnce(new Error('品名读取失败'))
    wrapper = mount(BomCuttingCatalogSelect, { props: { line: createLine() } })
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('品名读取失败')
    expect(wrapper.getComponent(ElSelect).props('disabled')).toBe(true)
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.emitted('selected')).toBeUndefined()
  })

  it('关闭后不把迟到的档案结果写回其他草稿', async () => {
    let resolveDetail!: (result: { data: MaterialCatalog }) => void
    api.detail.mockImplementation(() => new Promise(resolve => { resolveDetail = resolve }))
    wrapper = mount(BomCuttingCatalogSelect, { props: { line: createLine() } })
    await flushPromises()
    wrapper.getComponent(ElSelect).vm.$emit('change', catalog.id)
    wrapper.unmount()
    resolveDetail({ data: catalog })
    await flushPromises()
    expect(wrapper.emitted('selected')).toBeUndefined()
  })

  it('维护刷新读取新版本，单独通知刷新而非重新选择品名', async () => {
    const line = createLine()
    line.material_catalog_id = catalog.id
    line.part_name = catalog.name
    wrapper = mount(BomCuttingCatalogSelect, { props: { line, refreshKey: 0 } })
    await flushPromises()
    await wrapper.setProps({ refreshKey: 1 })
    await flushPromises()
    expect(wrapper.emitted('refreshed')).toEqual([[catalog]])
    expect(wrapper.emitted('selected')).toBeUndefined()
  })

  it('已有裁片更换品名时保留原单位和实际工艺，不套用新行默认值', async () => {
    const line = createLine()
    line.unit = 'PCS'
    line.material_selection = { catalog_version: 'v1', scope: 'BASE', processing_state: 'PROCESSED',
      attributes: {}, unit_id: 'pcs-unit', semi_kind: 'CUTTING', completed_craft: { id: 'external', craft_type: 'EXTERNAL', code: 'CUTTING' } }
    wrapper = mount(BomCuttingCatalogSelect, { props: { line } })
    await flushPromises()
    wrapper.getComponent(ElSelect).vm.$emit('change', catalog.id)
    await flushPromises()
    expect(line.unit).toBe('PCS')
    expect(line.material_selection).toMatchObject({ unit_id: 'pcs-unit', completed_craft: { id: 'external', craft_type: 'EXTERNAL' } })
    expect(api.options).not.toHaveBeenCalled()
    expect(api.crafts).not.toHaveBeenCalled()
  })

  it.each(['unit', 'craft', 'duplicate-craft'])('缺少或重复的默认配置 %s 不伪造 ID，也不修改草稿', async missing => {
    if (missing === 'unit') api.options.mockResolvedValue({ units: [] })
    else api.crafts.mockResolvedValue({ crafts: missing === 'craft' ? [] : [
      { id: 'one', craft_type: 'INTERNAL', code: 'CUTTING' }, { id: 'two', craft_type: 'INTERNAL', code: 'CUTTING' },
    ] })
    const line = createLine()
    wrapper = mount(BomCuttingCatalogSelect, { props: { line } })
    await flushPromises()
    wrapper.getComponent(ElSelect).vm.$emit('change', catalog.id)
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('配置')
    expect(line.material_catalog_id).toBeFalsy()
    expect(line.unit).toBe('')
    expect(wrapper.emitted('selected')).toBeUndefined()
  })

  it('默认配置请求期间切换编辑草稿，迟到结果不写入旧行或新行', async () => {
    let resolveOptions!: (value: { units: { id: string; unit_name: string }[] }) => void
    api.options.mockImplementation(() => new Promise(resolve => { resolveOptions = resolve }))
    const line = createLine()
    wrapper = mount(BomCuttingCatalogSelect, { props: { line } })
    await flushPromises()
    wrapper.getComponent(ElSelect).vm.$emit('change', catalog.id)
    await flushPromises()
    const nextLine = createLine()
    await wrapper.setProps({ line: nextLine })
    resolveOptions({ units: [{ id: 'set-unit', unit_name: '套' }] })
    await flushPromises()
    expect(line.material_catalog_id).toBeFalsy()
    expect(nextLine.material_catalog_id).toBeFalsy()
  })
})

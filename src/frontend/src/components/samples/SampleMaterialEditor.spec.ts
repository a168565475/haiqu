import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Editor from './SampleMaterialEditor.vue'
import Drawer from './SampleMaterialLineDrawer.vue'
import Picker from './SampleMaterialPicker.vue'
import Selection from './SampleCatalogSelection.vue'
import type { SampleMaterialCandidate, SampleMaterialCategory, SampleMaterialLine } from '@/types/sampleMaterial'

const api = vi.hoisted(() => ({ references: vi.fn(), candidates: vi.fn() }))
vi.mock('@/api/sampleMaterials', () => ({ fetchSampleMaterialReferences: api.references, fetchSampleMaterialCandidates: api.candidates }))
const sourceApi = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn(), options: vi.fn(), publicOptions: vi.fn(), crafts: vi.fn() }))
vi.mock('@/api/sampleMaterialSources', () => ({ fetchSampleMaterials: sourceApi.list, fetchSampleMaterial: sourceApi.detail,
  fetchSampleMaterialOptions: sourceApi.options, fetchSamplePublicOptions: sourceApi.publicOptions, fetchSampleMaterialCrafts: sourceApi.crafts }))
const line = (): SampleMaterialLine => ({ key: 'a', category: 'tube', pipeInputMode: 'TOTAL_METERS', material_catalog_id: 'catalog', material_selection: { catalog_version: 'v1', scope: 'BASE', processing_state: 'RAW', attributes: { section_size: '25' }, unit_id: 'root' }, name: '圆管', specification: '25', material: '铁', color: '', quantity: '12', unitId: 'root', unitLabel: '根', notes: '' })
const units = [{ id: 'm', label: '米', decimalPlaces: 4 }]
const overlay = { props: ['modelValue'], template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>' }
// 编辑器用替身隔离选料面板，六分类选料另用真实子组件验证接口接线。
const global = { plugins: [ElementPlus], stubs: { AppWindowDialog: overlay, SampleCatalogSelection: { props: ['modelValue', 'source'], template: '<div />' } } }
const catalogCandidate = (): SampleMaterialCandidate => ({ id: 'catalog-tube', number: '', name: '圆管', specification: '25', material: '铁', color: '', unitId: 'root', unitLabel: '根',
  material_catalog_id: 'catalog-tube', material_selection: { catalog_version: 'v2', scope: 'BASE', processing_state: 'RAW', attributes: { shape: '圆管', section_size: '25', thickness: '1.2', material: '铁' }, unit_id: 'root' } })
const categoryDefinitions: Record<SampleMaterialCategory, { key: string; template: string; attributes: Record<string, string> }> = {
  tube: { key: 'TUBE', template: 'TUBE', attributes: { shape: '圆管', section_size: '25', thickness: '1.2', material: '铁', color: '蓝' } },
  hardware: { key: 'HARDWARE', template: 'HARDWARE', attributes: { specification: 'M8', material: '铁', color: '蓝' } },
  plastic: { key: 'PLASTIC', template: 'PLASTIC', attributes: { specification: '25', material: '塑料', color: '蓝' } },
  accessory: { key: 'AUXILIARY', template: 'AUXILIARY_GENERAL', attributes: { specification: '25', material: '棉', color: '蓝' } },
  fabric: { key: 'FABRIC', template: 'FABRIC', attributes: { material: '涤纶', fabric_spec: '600D', width: '150', color: '蓝' } },
  packaging: { key: 'PACKAGING', template: 'PACKAGING_GENERAL', attributes: { specification: '25', material: '纸', color: '蓝' } },
}
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  api.references.mockResolvedValue({ tube: {}, fabric: {}, accessory: {}, accessories: [] })
  api.candidates.mockResolvedValue({ data: [], meta: { total: 0 } })
})
async function editor(lines = [line()]) {
  const wrapper = mount(Editor, { props: { modelValue: lines, units, fullscreen: false, 'onUpdate:modelValue': (value: SampleMaterialLine[]) => wrapper.setProps({ modelValue: value }) }, global })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
const button = (wrapper: Pick<ReturnType<typeof mount>, 'findAll'>, text: string) => wrapper.findAll('button').find(item => item.text() === text)!
afterEach(() => { wrappers.splice(0).forEach(item => item.unmount()); vi.restoreAllMocks(); vi.clearAllMocks() })

describe('样品目录选择与历史原料兼容', () => {
  it('侧栏切换保留其他分区，并保留全屏操作', async () => {
    const wrapper = await editor([line(), { ...line(), key: 'b', category: 'fabric', name: '面料' }])
    await wrapper.setProps({ layout: 'sidebar' })
    await wrapper.findAll('.section-tabs button').find(item => item.text().includes('面料类'))!.trigger('click')
    expect(wrapper.text()).toContain('面料')
    expect(wrapper.props('modelValue')).toHaveLength(2)
    await button(wrapper, '全屏填写').trigger('click')
    expect(wrapper.emitted('toggle-fullscreen')).toHaveLength(1)
  })
  it('六分区保留选择入口，不预先读取旧组合候选', async () => {
    const wrapper = await editor([])
    const tabs = wrapper.findAll('.material-tabs button')
    expect(tabs).toHaveLength(6)
    for (const tab of tabs) { await tab.trigger('click'); expect(wrapper.findAll('button').some(item => item.text().startsWith('选择'))).toBe(true) }
    expect(api.references).toHaveBeenCalledOnce(); expect(api.candidates).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('＋ 添加一行')
  })
  it('已保存目录管材需求按米填写，根制来源不替换业务米数', async () => {
    const wrapper = await editor()
    expect(wrapper.text()).toContain('米')
    expect(wrapper.findAll('input[aria-label="第1项单位"]')).toHaveLength(0)
    await wrapper.get('input[aria-label="第1项需求数量"]').setValue('1.25')
    expect(wrapper.props('modelValue')[0]!.quantity).toBe('1.25')
    expect(wrapper.props('modelValue')[0]!.unitLabel).toBe('根')
  })
  it('管材沿原九列表格显示，历史目录属性保留不改写', async () => {
    const row = line()
    row.material_selection!.attributes.thickness = '1.2'
    const wrapper = await editor([row])
    expect(wrapper.findAll('thead th')).toHaveLength(9)
    expect(wrapper.findAll('thead th').map(cell => cell.text())).not.toContain('厚度')
    expect(wrapper.props('modelValue')[0]!.material_selection!.attributes.thickness).toBe('1.2')
    expect(wrapper.text()).not.toContain('部位')
    expect(wrapper.text()).not.toContain('切割长度')
  })
  it('取消选料不产生空行', async () => {
    const wrapper = await editor([])
    await button(wrapper, '选择管材').trigger('click')
    const picker = wrapper.getComponent(Picker)
    await button(picker, '取消').trigger('click')
    expect(wrapper.props('modelValue')).toEqual([])
  })
  it('编辑下一条只应用当前行，取消待新增行不写空行', async () => {
    const wrapper = await editor()
    await wrapper.get('[aria-label="放大编辑当前行"]').trigger('click')
    wrapper.getComponent(Drawer).vm.$emit('apply', { ...line(), quantity: '15' }, true)
    await flushPromises()
    expect(wrapper.props('modelValue')).toHaveLength(1)
    expect(wrapper.props('modelValue')[0]!.quantity).toBe('15')
    expect(wrapper.getComponent(Drawer).props('line').material_catalog_id).toBe('catalog')
    wrapper.getComponent(Drawer).vm.$emit('update:modelValue', false)
    await flushPromises(); expect(wrapper.props('modelValue')).toHaveLength(1)
  })
  it('下一条定位本分区，其他分区草稿不丢失', async () => {
    const wrapper = await editor([line(), { ...line(), key: 'fabric', category: 'fabric' }, { ...line(), key: 'next' }])
    await wrapper.get('[aria-label="放大编辑当前行"]').trigger('click')
    wrapper.getComponent(Drawer).vm.$emit('apply', line(), true)
    await flushPromises()
    expect(wrapper.getComponent(Drawer).props('line').key).toBe('next')
    expect(wrapper.props('modelValue')[1]!.key).toBe('fabric')
  })
  it('管材选入目录属性并保留根制来源，需求按米填写，只读时不应用新材料', async () => {
    const wrapper = await editor([])
    const candidate = catalogCandidate()
    wrapper.getComponent(Picker).vm.$emit('choose', [candidate, candidate])
    await flushPromises(); expect(wrapper.props('modelValue')).toHaveLength(1)
    expect(wrapper.props('modelValue')[0]).toMatchObject({ material_catalog_id: 'catalog-tube', category: 'tube', specification: '25', unitId: 'root', unitLabel: '根', pipeInputMode: 'TOTAL_METERS', material_selection: candidate.material_selection })
    expect(wrapper.props('modelValue')[0]!.rawMaterialId).toBeUndefined()
    expect(wrapper.findAll('tbody td')[6]!.text()).toBe('米')
    candidate.material_selection!.attributes.thickness = '2'
    expect(wrapper.props('modelValue')[0]!.material_selection!.attributes.thickness).toBe('1.2')
    await wrapper.setProps({ disabled: true })
    wrapper.getComponent(Picker).vm.$emit('choose', [{ ...candidate, material_catalog_id: 'other-tube' }])
    await flushPromises(); expect(wrapper.props('modelValue')).toHaveLength(1)
  })
  it('其他分类选入目录身份和具体属性，同品名不同规格保留为两行', async () => {
    const wrapper = await editor([])
    await wrapper.findAll('.material-tabs button').find(item => item.text().includes('五金件'))!.trigger('click')
    const candidate = { ...catalogCandidate(), id: 'catalog-hardware', name: '螺丝', material_catalog_id: 'catalog-hardware', specification: 'M8', unitId: 'm', unitLabel: '米',
      material_selection: { ...catalogCandidate().material_selection!, attributes: { specification: 'M8' }, unit_id: 'm' } }
    wrapper.getComponent(Picker).vm.$emit('choose', [candidate, candidate])
    await flushPromises()
    expect(wrapper.props('modelValue')).toHaveLength(1)
    expect(wrapper.props('modelValue')[0]).toMatchObject({ material_catalog_id: 'catalog-hardware', category: 'hardware', specification: 'M8', material_selection: candidate.material_selection })
    expect(wrapper.props('modelValue')[0]!.rawMaterialId).toBeUndefined()
    wrapper.getComponent(Picker).vm.$emit('choose', [{ ...candidate, specification: 'M10', material_selection: { ...candidate.material_selection, attributes: { specification: 'M10' } } }])
    await flushPromises(); expect(wrapper.props('modelValue')).toHaveLength(2)
    expect(wrapper.findAll('thead th').map(cell => cell.text())).not.toContain('厚度')
  })
  it('已保存旧原料行继续显示和修改数量，不转换为目录身份', async () => {
    const historical = { ...line(), material_catalog_id: undefined, material_selection: undefined, rawMaterialId: 'old-raw', unitId: '', unitLabel: '米' }
    const wrapper = await editor([historical])
    await wrapper.get('input[aria-label="第1项需求数量"]').setValue('2.5')
    expect(wrapper.props('modelValue')[0]).toMatchObject({ rawMaterialId: 'old-raw', quantity: '2.5', unitLabel: '米', pipeInputMode: 'TOTAL_METERS' })
    expect(wrapper.props('modelValue')[0]!.material_catalog_id).toBeUndefined()
    await wrapper.get('[aria-label="放大编辑当前行"]').trigger('click')
    expect(wrapper.getComponent(Drawer).props('line').rawMaterialId).toBe('old-raw')
    expect(wrapper.getComponent(Drawer).findComponent(Selection).exists()).toBe(false)
  })
  it('放大编辑失败不应用，取消保留表格原输入', async () => {
    const original = line(), wrapper = mount(Drawer, { props: { modelValue: true, line: original, units, references: null, hasNext: false }, global })
    wrappers.push(wrapper)
    await wrapper.get('input[aria-label="放大编辑需求数量"]').setValue('-1')
    await button(wrapper, '应用修改').trigger('click')
    expect(wrapper.emitted('apply')).toBeUndefined()
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    await button(wrapper, '取消').trigger('click'); await flushPromises()
    expect(wrapper.emitted('update:modelValue')!.at(-1)).toEqual([false])
    expect(original.quantity).toBe('12')
  })
  it('管材未选齐时按钮可点击并提示缺项，取消不返回草稿', async () => {
    const warning = vi.spyOn(ElMessage, 'warning')
    const wrapper = mount(Picker, { props: { modelValue: false, category: 'tube' }, global }); wrappers.push(wrapper)
    await wrapper.setProps({ modelValue: true }); await flushPromises()
    expect(button(wrapper, '添加材料').attributes('disabled')).toBeUndefined()
    await button(wrapper, '添加材料').trigger('click')
    expect(warning).toHaveBeenLastCalledWith('请先选择品名')
    const selected = { ...line(), material_selection: { ...line().material_selection!, attributes: { section_size: '25', shape: '圆管', material: '铁' } } }
    wrapper.getComponent(Selection).vm.$emit('update:modelValue', selected)
    await flushPromises()
    await button(wrapper, '添加材料').trigger('click')
    expect(warning).toHaveBeenLastCalledWith('请选择厚度')
    expect(wrapper.emitted('choose')).toBeUndefined()
    await wrapper.setProps({ disabled: true })
    expect(button(wrapper, '添加材料').attributes('disabled')).toBeDefined()
    await button(wrapper, '取消').trigger('click')
    expect(wrapper.emitted('choose')).toBeUndefined()
  })
  it.each(['tube', 'hardware', 'plastic', 'accessory', 'fabric', 'packaging'] as const)('%s分类先选最新品名再选公共属性，确认返回目录身份', async category => {
    const definition = categoryDefinitions[category], unitId = category === 'tube' ? 'root' : 'm', unitLabel = category === 'tube' ? '根' : '米'
    const catalog = { id: `catalog-${category}`, name: '材料品名', category_key: definition.key, template_key: definition.template, updated_at: 'v2', spray_enabled: false, values: [], units: [{ id: 'allowed', scope: 'BASE', unit_id: unitId, unit_name: unitLabel }] }
    const fields = Object.keys(definition.attributes).map(key => ({ key, label: key, kind: 'text' }))
    sourceApi.options.mockResolvedValue({ categories: [{ key: definition.key, templates: [{ key: definition.template, fields: [...fields, { key: 'length', label: '长度', kind: 'text' }, { key: 'unit', label: '单位', kind: 'unit' }] }] }] })
    sourceApi.list.mockResolvedValue({ data: [catalog], meta: { total_pages: 1 } })
    sourceApi.detail.mockResolvedValue({ data: catalog })
    sourceApi.publicOptions.mockResolvedValue({ category_key: definition.key, template_key: definition.template, scope: 'BASE', fields: [],
      values: Object.entries(definition.attributes).map(([key, value]) => ({ id: key, scope: 'BASE', field_key: key, value, parent_id: key === 'section_size' ? 'shape' : null })), units: [{ id: unitId, unit_name: unitLabel }] })
    const wrapper = mount(Picker, { props: { modelValue: false, category }, global: { ...global, stubs: { AppWindowDialog: overlay } } }); wrappers.push(wrapper)
    await wrapper.setProps({ modelValue: true }); await flushPromises()
    expect(wrapper.getComponent(Selection).props('source')).toBe('sample')
    expect(sourceApi.list).toHaveBeenCalledWith({ category: definition.key, q: '', page: 1, page_size: 50 })
    expect(api.candidates).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('品名'); expect(wrapper.text()).not.toContain('品号')
    await wrapper.get('.name-option').trigger('click'); await flushPromises()
    expect(sourceApi.detail).toHaveBeenCalledWith(catalog.id)
    expect(sourceApi.publicOptions).toHaveBeenCalledWith({ category_key: definition.key, template_key: definition.template, scope: 'BASE' })
    expect(button(wrapper, '添加材料').attributes('disabled')).toBeUndefined()
    await button(wrapper, '添加材料').trigger('click')
    expect(wrapper.emitted('choose')).toBeUndefined()
    if (category === 'tube') expect(wrapper.findAll('legend').map(item => item.text())).not.toContain('长度')
    for (const value of Object.values(definition.attributes)) {
      await wrapper.findAll('.attribute-value').find(item => item.text() === value)!.get('input').setValue(true)
    }
    if (category !== 'tube') await wrapper.findAll('.attribute-value').find(item => item.text() === unitLabel)!.get('input').setValue(true)
    await flushPromises()
    expect(wrapper.emitted('choose')).toBeUndefined()
    expect(button(wrapper, '添加材料').attributes('disabled')).toBeUndefined()
    await button(wrapper, '添加材料').trigger('click')
    expect(wrapper.emitted('choose')![0]![0]).toEqual([expect.objectContaining({ material_catalog_id: catalog.id, unitId, unitLabel,
      material_selection: expect.objectContaining({ catalog_version: 'v2', attributes: definition.attributes, unit_id: unitId }) })])
  })
})

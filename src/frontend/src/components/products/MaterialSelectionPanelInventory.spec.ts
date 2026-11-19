import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MaterialSelectionPanel from './MaterialSelectionPanel.vue'
import { blankLine } from '@/views/boms/bomEditorHelpers'
import type { MaterialCatalog, MaterialCatalogOptions, PublicMaterialOptions } from '@/types/materialCatalog'

const inboundApi = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn(), options: vi.fn(), publicOptions: vi.fn() }))
const catalogApi = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn(), options: vi.fn(), publicOptions: vi.fn() }))
const sampleApi = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn(), options: vi.fn(), publicOptions: vi.fn(), crafts: vi.fn() }))
const bomCrafts = vi.hoisted(() => vi.fn())
vi.mock('@/api/inventoryMaterialSources', () => ({
  fetchInboundMaterials: inboundApi.list, fetchInboundMaterial: inboundApi.detail,
  fetchInboundMaterialOptions: inboundApi.options, fetchInboundPublicOptions: inboundApi.publicOptions,
}))
vi.mock('@/api/materialCatalog', () => ({
  fetchMaterialCatalogs: catalogApi.list, fetchMaterialCatalog: catalogApi.detail,
  fetchMaterialCatalogOptions: catalogApi.options, fetchPublicMaterialOptions: catalogApi.publicOptions,
  materialCatalogError: (error: Error) => error.message,
}))
vi.mock('@/api/sampleMaterialSources', () => ({
  fetchSampleMaterials: sampleApi.list, fetchSampleMaterial: sampleApi.detail,
  fetchSampleMaterialOptions: sampleApi.options, fetchSamplePublicOptions: sampleApi.publicOptions, fetchSampleMaterialCrafts: sampleApi.crafts,
}))
vi.mock('@/api/boms', () => ({ fetchBomCatalogSelectionOptions: bomCrafts }))

const catalog: MaterialCatalog = {
  id: 'hardware-catalog', name: '入库五金', category_key: 'HARDWARE', template_key: 'HARDWARE', spray_enabled: false,
  updated_at: '2026-11-06T08:00:00Z', base_warehouse_id: 'material-warehouse', semi_warehouse_id: null,
  values: [], units: [{ id: 'allowed-piece', scope: 'BASE', unit_id: 'piece', unit_name: '个' }],
}
const definitions: MaterialCatalogOptions = {
  categories: [{ key: 'HARDWARE', label: '五金件', templates: [{ key: 'HARDWARE', label: '五金件', supports_spray: false, fields: [
    { key: 'material', label: '材质', kind: 'text' }, { key: 'specification', label: '规格', kind: 'text' },
    { key: 'unit', label: '可用单位', kind: 'unit' },
  ] }] }], spray_fields: [], units: [], warehouses: [],
}
const publicOptions: PublicMaterialOptions = {
  category_key: 'HARDWARE', template_key: 'HARDWARE', scope: 'BASE', fields: [],
  values: [
    { id: 'material', scope: 'BASE', field_key: 'material', value: '铁', parent_id: null },
    { id: 'specification', scope: 'BASE', field_key: 'specification', value: 'M8', parent_id: null },
  ], units: [{ id: 'piece', unit_name: '个' }, { id: 'kg', unit_name: '公斤' }],
}
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  vi.resetAllMocks()
  for (const api of [inboundApi, catalogApi]) {
    api.options.mockResolvedValue(definitions)
    api.list.mockResolvedValue({ data: [catalog], meta: { page: 1, page_size: 50, total: 1, total_pages: 1 } })
    api.detail.mockResolvedValue({ data: catalog })
    api.publicOptions.mockResolvedValue(publicOptions)
  }
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))
async function start() {
  const line = reactive(blankLine())
  const wrapper = mount(MaterialSelectionPanel, { props: { line, sectionTitle: '五金件', source: 'inventory' } })
  wrappers.push(wrapper); await flushPromises()
  return { wrapper, line }
}
async function choose(wrapper: ReturnType<typeof mount>, label: string) {
  const option = wrapper.findAll('.attribute-value').find(item => item.text() === label)
  expect(option, label).toBeTruthy()
  await option!.get('input').setValue(true)
}
function expectNoBroaderSources() {
  for (const api of [catalogApi, sampleApi]) for (const method of Object.values(api)) expect(method).not.toHaveBeenCalled()
  expect(bomCrafts).not.toHaveBeenCalled()
}

describe('材料入库专用选料源（真实组件，模拟请求边界）', () => {
  it('在旧公共候选旁选择本品名专用规格和单位，并提交其真实单位 ID', async () => {
    inboundApi.detail.mockResolvedValue({ data: { ...catalog,
      values: [{ id: 'private-spec', scope: 'BASE', field_key: 'specification', value: '档案规格', parent_id: null }],
      units: [...catalog.units, { id: 'binding', scope: 'BASE', unit_id: 'private-unit', unit_name: '专用提' }],
    } })
    const { wrapper, line } = await start()
    await wrapper.get('.name-option').trigger('click'); await flushPromises()
    const options = wrapper.findAll('.attribute-value').map(item => item.text())
    expect(options).toEqual(expect.arrayContaining(['M8', '公斤', '档案规格', '专用提']))
    expect(options.filter(item => item === '个')).toHaveLength(1)
    await choose(wrapper, '档案规格'); await choose(wrapper, '专用提')
    expect(line.material_selection).toMatchObject({ unit_id: 'private-unit', attributes: { specification: '档案规格' } })
    expectNoBroaderSources()
  })
  it('四个读取请求均走入库源，选择规格单位和默认仓回传保持完整且无维护入口', async () => {
    const { wrapper, line } = await start()
    expect(inboundApi.options).toHaveBeenCalledOnce()
    expect(inboundApi.list).toHaveBeenCalledWith({ category: 'HARDWARE', q: '', page: 1, page_size: 50 })
    await wrapper.get('.name-option').trigger('click'); await flushPromises()
    expect(inboundApi.detail).toHaveBeenCalledWith('hardware-catalog')
    expect(inboundApi.publicOptions).toHaveBeenCalledWith({ category_key: 'HARDWARE', template_key: 'HARDWARE', scope: 'BASE' })
    expect(wrapper.emitted('loaded')?.[0]?.[0]).toEqual(catalog)
    await choose(wrapper, '铁'); await choose(wrapper, 'M8'); await choose(wrapper, '公斤')
    expect(line.material_catalog_id).toBe('hardware-catalog')
    expect(line.material_selection).toMatchObject({ catalog_version: catalog.updated_at, scope: 'BASE', processing_state: 'RAW', attributes: { material: '铁', specification: 'M8' }, unit_id: 'kg' })
    expect(line.part_name).toBe('入库五金'); expect(line.specification).toBe('M8'); expect(line.unit).toBe('公斤')
    expect(wrapper.find('.maintain-link').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('生产维护')
    expect(wrapper.emitted('maintain')).toBeUndefined()
    expectNoBroaderSources()
  })

  it('入库源读取失败直接显示错误，不改走需要目录维护权限的通用接口', async () => {
    inboundApi.options.mockRejectedValueOnce(new Error('材料入库选料权限不足'))
    const { wrapper } = await start()
    expect(wrapper.get('[role="alert"]').text()).toContain('材料入库选料权限不足')
    expect(wrapper.findAll('.name-option')).toHaveLength(0)
    expect(inboundApi.list).not.toHaveBeenCalled()
    expectNoBroaderSources()
  })

  it('品名支持喷塑时仍只读取原料公共属性，不申请半成品选项', async () => {
    inboundApi.options.mockResolvedValue({ ...definitions, categories: definitions.categories.map(category => ({ ...category,
      templates: category.templates.map(template => ({ ...template, supports_spray: true })),
    })) })
    inboundApi.detail.mockResolvedValue({ data: { ...catalog, spray_enabled: true } })
    const { wrapper, line } = await start()
    await wrapper.get('.name-option').trigger('click'); await flushPromises()
    expect(inboundApi.publicOptions).toHaveBeenCalledOnce()
    expect(inboundApi.publicOptions).toHaveBeenCalledWith({ category_key: 'HARDWARE', template_key: 'HARDWARE', scope: 'BASE' })
    expect(line.material_selection?.scope).toBe('BASE')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expectNoBroaderSources()
  })
})

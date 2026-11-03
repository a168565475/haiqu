import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MaterialAttributeValue, MaterialCatalog, MaterialCatalogDraft } from '@/types/materialCatalog'
import MaterialCatalogSelect from '@/components/products/MaterialCatalogSelect.vue'
import MaterialColorOptions from '@/components/products/MaterialColorOptions.vue'
import MaterialAttributeOptions from '@/components/products/MaterialAttributeOptions.vue'
import RawMaterialManagementView from './RawMaterialManagementView.vue'

vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))
vi.mock('vue-router', async original => ({ ...await original<object>(), onBeforeRouteLeave: vi.fn(), onBeforeRouteUpdate: vi.fn() }))
const api = vi.hoisted(() => ({ fetchMaterialCatalogOptions: vi.fn(), fetchMaterialCatalogs: vi.fn(), fetchMaterialCatalog: vi.fn(),
  fetchPublicMaterialOptions: vi.fn(), saveMaterialCatalog: vi.fn(), createMaterialCatalog: vi.fn() }))
vi.mock('@/api/materialCatalog', async original => ({ ...await original<object>(), ...api }))

const color = (id: string, card: string, code: string): MaterialAttributeValue => ({ id, scope: 'BASE', field_key: 'color',
  parent_id: null, value: '红色', product_color_id: id, color_card: card, color_code: code, color_name: '红色' })
const colorField = { key: 'color', label: '颜色', kind: 'text', source: 'product-colors', manage_url: '/settings/production-data?tab=colors' }
const catalog: MaterialCatalog = { id: 'catalog-a', category_key: 'FABRIC', template_key: 'FABRIC', name: '布料', spray_enabled: false,
  base_warehouse_id: null, semi_warehouse_id: null, values: [], units: [], updated_at: '2026-10-31T00:00:00Z' }
let wrapper: VueWrapper
beforeEach(() => {
  vi.clearAllMocks()
  api.fetchMaterialCatalogOptions.mockResolvedValue({ categories: ['FABRIC', 'TUBE', 'FABRIC_SEMI'].map(key => ({ key, label: key, templates: [{ key, label: key, supports_spray: key === 'TUBE', fields: [colorField] }] })),
    spray_fields: [{ key: 'color', label: '颜色', kind: 'text' }], warehouses: [], units: [] })
  api.fetchMaterialCatalogs.mockResolvedValue({ data: [catalog], meta: { page: 1, page_size: 50, total: 1, total_pages: 1 } })
  api.fetchMaterialCatalog.mockResolvedValue({ data: catalog, etag: '"version-1"' })
  api.fetchPublicMaterialOptions.mockImplementation(async query => ({ ...query, units: [], fields: [{ ...colorField, source: query.scope === 'BASE' ? 'product-colors' : 'powder-colors' }],
    values: query.scope === 'BASE' ? [color('public-a', '卡A', 'A1'), color('public-b', '卡B', 'B1')] : [] }))
  api.saveMaterialCatalog.mockImplementation(async (_id: string, payload: MaterialCatalogDraft) => ({ data: { ...catalog, ...payload }, etag: '"version-2"' }))
})
afterEach(() => wrapper?.unmount())

describe('原料颜色展示与统一保存', () => {
  it('面料公共颜色整行加入本地草稿，顶部保存一次发送同名不同卡号', async () => {
    wrapper = mount(RawMaterialManagementView)
    await flushPromises()
    const colors = wrapper.getComponent(MaterialColorOptions)
    await colors.get('[data-action="add"]').trigger('click')
    await colors.get('[data-action="add"]').trigger('click')
    const selects = colors.findAllComponents(MaterialCatalogSelect)
    selects[0]!.vm.$emit('update:modelValue', 'public:public-a')
    selects[1]!.vm.$emit('update:modelValue', 'public:public-b')
    await flushPromises()
    expect(api.saveMaterialCatalog).not.toHaveBeenCalled()
    await wrapper.get('[data-testid="save-catalog"]').trigger('click')
    await flushPromises()
    expect(api.saveMaterialCatalog).toHaveBeenCalledTimes(1)
    const [id, payload, etag] = api.saveMaterialCatalog.mock.calls[0] as [string, MaterialCatalogDraft, string]
    expect([id, etag]).toEqual(['catalog-a', '"version-1"'])
    expect(payload.values).toEqual(expect.arrayContaining([
      expect.objectContaining({ product_color_id: 'public-a', color_card: '卡A', color_code: 'A1', color_name: '红色', value: '红色' }),
      expect.objectContaining({ product_color_id: 'public-b', color_card: '卡B', color_code: 'B1', color_name: '红色', value: '红色' }),
    ]))
    const baseIds = payload.values.filter(value => value.scope === 'BASE').map(value => value.id)
    expect(new Set(baseIds).size).toBe(2)
    expect(baseIds).not.toContain('public-a')
    expect(baseIds).not.toContain('public-b')
  })

  it('旧颜色保持原值，输入新三字段无需回车即可由顶部保存收集', async () => {
    const legacy: MaterialAttributeValue = { id: 'legacy', scope: 'BASE', field_key: 'color', value: '旧颜色', parent_id: null }
    api.fetchMaterialCatalog.mockResolvedValue({ data: { ...catalog, values: [legacy] }, etag: '"version-1"' })
    wrapper = mount(RawMaterialManagementView)
    await flushPromises()
    const colors = wrapper.getComponent(MaterialColorOptions)
    expect(colors.findAll('tbody tr')[0]!.findAll('td').slice(0, 3).map(cell => cell.text())).toEqual(['—', '—', '旧颜色'])
    await colors.get('[data-action="add"]').trigger('click')
    await colors.get('input[aria-label="色卡"]').setValue(' 新卡 ')
    await colors.get('input[aria-label="色号"]').setValue(' N1 ')
    await colors.get('input[aria-label="添加颜色"]').setValue(' 新颜色 ')
    await wrapper.get('[data-testid="save-catalog"]').trigger('click')
    await flushPromises()
    const payload = api.saveMaterialCatalog.mock.calls[0]![1] as MaterialCatalogDraft
    expect(payload.values).toContainEqual(legacy)
    expect(payload.values).toContainEqual(expect.objectContaining({ product_color_id: null, color_card: '新卡', color_code: 'N1', color_name: '新颜色', value: '新颜色' }))
  })

  it('移除仅影响品名草稿，公共候选保留，失败保存仍保留草稿', async () => {
    const existing = { ...color('public-a', '卡A', 'A1'), id: 'catalog-color' }
    api.fetchMaterialCatalog.mockResolvedValue({ data: { ...catalog, values: [existing] }, etag: '"version-1"' })
    api.saveMaterialCatalog.mockRejectedValueOnce(new Error('保存失败'))
    wrapper = mount(RawMaterialManagementView)
    await flushPromises()
    const colors = wrapper.getComponent(MaterialColorOptions)
    await colors.get('[data-action="delete"]').trigger('click')
    await flushPromises()
    expect(api.saveMaterialCatalog).not.toHaveBeenCalled()
    expect(colors.props('publicOptions')).toHaveLength(2)
    await wrapper.get('[data-testid="save-catalog"]').trigger('click')
    await flushPromises()
    expect(api.saveMaterialCatalog.mock.calls[0]![1].values).toEqual([])
    expect(colors.props('options')).toEqual([])
    expect(wrapper.text()).toContain('保存失败')
  })

  it.each(['TUBE', 'FABRIC_SEMI'])('%s 恢复单色展示且公共同名候选去重', async categoryKey => {
    const other = { ...catalog, category_key: categoryKey, template_key: categoryKey, spray_enabled: categoryKey === 'TUBE',
      values: [{ id: 'catalog-color', scope: 'BASE' as const, field_key: 'color', value: '黑色', parent_id: null }] }
    api.fetchMaterialCatalogs.mockResolvedValue({ data: [other], meta: { page: 1, page_size: 50, total: 1, total_pages: 1 } })
    api.fetchMaterialCatalog.mockResolvedValue({ data: other, etag: '"version-1"' })
    wrapper = mount(RawMaterialManagementView, { props: { fixedCategory: categoryKey } })
    await flushPromises()
    expect(wrapper.findComponent(MaterialColorOptions).exists()).toBe(false)
    expect(wrapper.find('table').exists()).toBe(false)
    const rows = wrapper.findAllComponents(MaterialAttributeOptions)
    const base = rows.find(row => row.props('scope') === 'BASE')!
    expect(base.props('publicOptions')).toEqual(['红色'])
    expect(base.props('options')).toEqual([{ id: 'catalog-color', label: '黑色' }])
    if (categoryKey === 'TUBE') expect(rows.some(row => row.props('scope') === 'SPRAY')).toBe(true)
    await base.get('[data-action="add"]').trigger('click')
    expect(base.getComponent(MaterialCatalogSelect).props('options')).toEqual([{ value: '红色', label: '红色' }])
    expect(wrapper.find('input[aria-label="色卡"]').exists()).toBe(false)
    expect(wrapper.find('input[aria-label="色号"]').exists()).toBe(false)
    expect(api.saveMaterialCatalog).not.toHaveBeenCalled()
  })
})

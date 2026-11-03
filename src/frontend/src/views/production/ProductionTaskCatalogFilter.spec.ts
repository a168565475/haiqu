import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/productionTasks'
import type { ProductionTaskQuery } from '@/types/productionTask'
import ProductionTaskListView from './ProductionTaskListView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/productionTasks', async original => ({ ...await original<typeof import('@/api/productionTasks')>(), fetchProductionTasks: vi.fn(), fetchProductionTaskFilterOptions: vi.fn(), fetchProductionTaskAdvancedFilterOptions: vi.fn() }))
const id = 'a3e05cd0-3c82-41db-a363-72198d4d5739'
const current = { id, product_code: 'CODE', item_number: 'ITEM', product_name: '同名椅', specification: '50*60' }
const options = { employees: [], products: [current], product_catalogs: [current], order_sources: [], delivery_methods: [] }
interface ListPage { advancedVisible: boolean; advancedFilters: { product_selection: string }; buildQuery: () => ProductionTaskQuery; resetAdvancedFilters: () => void }

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchProductionTasks).mockResolvedValue({ data: [], meta: { total: 0, total_pages: 0 } } as never)
  vi.mocked(api.fetchProductionTaskFilterOptions).mockResolvedValue({ salespeople: [] })
  vi.mocked(api.fetchProductionTaskAdvancedFilterOptions).mockResolvedValue(options)
})

describe('生产列表的新旧产品筛选', () => {
  it('同一UUID按来源分别传参，切换和清空不会残留另一来源的参数', async () => {
    const wrapper = shallowMount(ProductionTaskListView, { global: { plugins: [ElementPlus], stubs: {
      ElPopover: { template: '<div><slot/><slot name="reference"/></div>' },
    } } })
    await flushPromises()
    const page = wrapper.vm as unknown as ListPage
    page.advancedFilters.product_selection = `catalog:${id}`
    expect(page.buildQuery()).toMatchObject({ product_catalog_id: id })
    expect(page.buildQuery()).not.toHaveProperty('product_id')
    page.advancedFilters.product_selection = `legacy:${id}`
    expect(page.buildQuery()).toMatchObject({ product_id: id })
    expect(page.buildQuery()).not.toHaveProperty('product_catalog_id')
    page.advancedVisible = true
    await flushPromises()
    wrapper.findAllComponents(ElSelect).find(select => select.attributes('aria-label') === '筛选产品')!.vm.$emit('update:modelValue', undefined)
    await flushPromises()
    expect(page.buildQuery()).not.toHaveProperty('product_id')
    expect(page.buildQuery()).not.toHaveProperty('product_catalog_id')
    wrapper.unmount()
  })

  it('新旧同名候选分组显示，选项身份不按名称或规格合并', async () => {
    const wrapper = shallowMount(ProductionTaskListView, { global: { plugins: [ElementPlus], stubs: {
      ElPopover: { template: '<div><slot/><slot name="reference"/></div>' },
      ElSelect: { template: '<div><slot/></div>' },
      ElOptionGroup: { props: ['label'], template: '<section :aria-label="label"><slot/></section>' },
      ElOption: { props: ['label', 'value'], template: '<span :data-value="value">{{ label }}</span>' },
    } } })
    await flushPromises()
    ;(wrapper.vm as unknown as ListPage).advancedVisible = true
    await flushPromises()
    expect(wrapper.get('[aria-label="产品管理"] [data-value]').attributes('data-value')).toBe(`catalog:${id}`)
    expect(wrapper.get('[aria-label="历史产品"] [data-value]').attributes('data-value')).toBe(`legacy:${id}`)
    expect(wrapper.get('[aria-label="产品管理"]').text()).toContain('同名椅 · ITEM · 50*60 · CODE')
    wrapper.unmount()
  })
})

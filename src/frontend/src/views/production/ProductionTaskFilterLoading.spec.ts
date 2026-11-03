import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/productionTasks'
import type { ProductionTaskAdvancedFilterOptions } from '@/types/productionTask'
import ProductionTaskListView from './ProductionTaskListView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/productionTasks', async original => ({
  ...await original<typeof import('@/api/productionTasks')>(),
  fetchProductionTasks: vi.fn(), fetchProductionTaskFilterOptions: vi.fn(), fetchProductionTaskAdvancedFilterOptions: vi.fn(),
}))

const basic = { salespeople: [{ id: 'sales-one', display_name: '业务甲' }] }
const advanced: ProductionTaskAdvancedFilterOptions = {
  employees: [{ id: 'follow-one', display_name: '跟单乙' }],
  products: [{ id: 'legacy-one', product_code: 'OLD', item_number: 'L1', product_name: '历史椅子', specification: '小号' }],
  product_catalogs: [{ id: 'catalog-one', product_code: 'NEW', item_number: 'C1', product_name: '新椅子', specification: '大号' }],
  order_sources: [{ value: 'NEW', label: '新订单' }], delivery_methods: [{ value: 'SINGLE', label: '整批交货' }],
}
let view: ReturnType<typeof mount> | undefined
let host: HTMLDivElement | undefined

async function render() {
  host = document.createElement('div')
  document.body.appendChild(host)
  view = mount(ProductionTaskListView, { attachTo: host, global: { plugins: [ElementPlus, createPinia()] } })
  await flushPromises()
  return view
}
async function toggleMore(visible: boolean) {
  const button = view!.findAll('button').find(item => item.text().startsWith('更多筛选'))!
  await button.trigger('click')
  await flushPromises()
  await vi.waitFor(() => expect(Boolean(document.querySelector('.advanced-filter-panel'))).toBe(visible))
}
function select(placeholder: string) {
  return view!.findAllComponents(ElSelect).find(item => item.props('placeholder') === placeholder)!
}
async function clickButton(label: string) {
  const button = Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(item => item.textContent?.trim() === label)
  expect(button).toBeDefined()
  button!.click()
  await flushPromises()
}
function cleanup() {
  view?.unmount(); view = undefined
  host?.remove(); host = undefined
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchProductionTasks).mockResolvedValue({ data: [], meta: { total: 7, total_pages: 1, page: 1, page_size: 50 } })
  vi.mocked(api.fetchProductionTaskFilterOptions).mockResolvedValue(basic)
  vi.mocked(api.fetchProductionTaskAdvancedFilterOptions).mockResolvedValue(advanced)
})
afterEach(cleanup)

describe('生产任务筛选按需加载', () => {
  it('首屏只取列表和业务员；更多筛选在途关闭重开不重复，成功后保留选项与筛选', async () => {
    let resolve!: (value: ProductionTaskAdvancedFilterOptions) => void
    vi.mocked(api.fetchProductionTaskAdvancedFilterOptions).mockReturnValueOnce(new Promise(done => { resolve = done }))
    const page = await render()
    expect(api.fetchProductionTasks).toHaveBeenCalledTimes(1)
    expect(api.fetchProductionTaskFilterOptions).toHaveBeenCalledTimes(1)
    expect(api.fetchProductionTaskAdvancedFilterOptions).not.toHaveBeenCalled()
    expect(page.text()).toContain('7 条')
    await toggleMore(true)
    expect(api.fetchProductionTaskAdvancedFilterOptions).toHaveBeenCalledTimes(1)
    expect(select('全部产品').props()).toMatchObject({ loading: true, disabled: true })
    expect(select('全部业务员').props('disabled')).toBe(false)
    await toggleMore(false)
    await toggleMore(true)
    expect(api.fetchProductionTaskAdvancedFilterOptions).toHaveBeenCalledTimes(1)
    resolve(advanced); await flushPromises()
    expect(select('全部产品').props('disabled')).toBe(false)
    select('全部产品').vm.$emit('update:modelValue', 'catalog:catalog-one')
    select('全部跟单员').vm.$emit('update:modelValue', 'follow-one')
    await flushPromises()
    const apply = Array.from(document.querySelectorAll<HTMLButtonElement>('.advanced-filter-panel button')).find(item => item.textContent?.trim() === '应用筛选')!
    apply.click(); await flushPromises()
    expect(api.fetchProductionTasks).toHaveBeenLastCalledWith(expect.objectContaining({ product_catalog_id: 'catalog-one', follower_id: 'follow-one' }))
    await toggleMore(true)
    expect(select('全部产品').props('modelValue')).toBe('catalog:catalog-one')
    expect(select('全部跟单员').props('modelValue')).toBe('follow-one')
    expect(api.fetchProductionTaskAdvancedFilterOptions).toHaveBeenCalledTimes(1)
    expect(api.fetchProductionTaskFilterOptions).toHaveBeenCalledTimes(1)
  })

  it('基础选项失败仍展示列表并可用更多筛选，业务员单独重试', async () => {
    vi.mocked(api.fetchProductionTaskFilterOptions).mockRejectedValueOnce(new Error('基础暂不可用'))
    const page = await render()
    expect(page.text()).toContain('业务员选项加载失败：基础暂不可用')
    expect(page.text()).toContain('7 条')
    expect(select('业务员：全部').props('disabled')).toBe(true)
    await toggleMore(true)
    expect(select('全部产品').props('disabled')).toBe(false)
    expect(select('全部跟单员').props('disabled')).toBe(false)
    expect(select('全部业务员').props('disabled')).toBe(true)
    await clickButton('重试业务员选项')
    expect(select('业务员：全部').props('disabled')).toBe(false)
    expect(page.text()).not.toContain('基础暂不可用')
    expect(api.fetchProductionTaskFilterOptions).toHaveBeenCalledTimes(2)
    expect(api.fetchProductionTaskAdvancedFilterOptions).toHaveBeenCalledTimes(1)
  })

  it('高级选项失败显示错误且单独重试，不阻塞列表和业务员筛选', async () => {
    vi.mocked(api.fetchProductionTaskAdvancedFilterOptions).mockRejectedValueOnce(new Error('高级暂不可用'))
    await render()
    await toggleMore(true)
    expect(document.querySelector('.advanced-filter-panel')?.textContent).toContain('更多筛选选项加载失败：高级暂不可用')
    expect(select('全部产品').props('disabled')).toBe(true)
    expect(select('全部跟单员').props('disabled')).toBe(true)
    expect(select('全部业务员').props('disabled')).toBe(false)
    select('业务员：全部').vm.$emit('update:modelValue', 'sales-one')
    select('业务员：全部').vm.$emit('change', 'sales-one')
    await flushPromises()
    expect(api.fetchProductionTasks).toHaveBeenLastCalledWith(expect.objectContaining({ salesperson_id: 'sales-one' }))
    await clickButton('重试更多筛选选项')
    expect(select('全部产品').props('disabled')).toBe(false)
    expect(document.querySelector('.advanced-filter-panel')?.textContent).not.toContain('高级暂不可用')
    expect(select('业务员：全部').props('modelValue')).toBe('sales-one')
    expect(api.fetchProductionTaskFilterOptions).toHaveBeenCalledTimes(1)
    expect(api.fetchProductionTaskAdvancedFilterOptions).toHaveBeenCalledTimes(2)
  })

  it('成功的空选项本页重复打开不再读取，页面卸载后新实例重新按需读取', async () => {
    vi.mocked(api.fetchProductionTaskAdvancedFilterOptions).mockResolvedValue({ employees: [], products: [], product_catalogs: [], order_sources: [], delivery_methods: [] })
    await render()
    await toggleMore(true)
    expect(select('全部产品').props('disabled')).toBe(false)
    await toggleMore(false)
    await toggleMore(true)
    expect(api.fetchProductionTaskAdvancedFilterOptions).toHaveBeenCalledTimes(1)
    cleanup()
    await render()
    expect(api.fetchProductionTaskAdvancedFilterOptions).toHaveBeenCalledTimes(1)
    await toggleMore(true)
    expect(api.fetchProductionTaskAdvancedFilterOptions).toHaveBeenCalledTimes(2)
  })
})

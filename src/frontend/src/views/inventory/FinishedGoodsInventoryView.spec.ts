import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import FinishedGoodsInventoryView from './FinishedGoodsInventoryView.vue'

const api = vi.hoisted(() => ({ stock: vi.fn(), options: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ push: vi.fn(), back: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))
vi.mock('@/directives/glassSpotlight', () => ({ vGlassSpotlight: {} }))
vi.mock('@/api/inventory', async importOriginal => ({
  ...await importOriginal<object>(), fetchFinishedGoodsInventory: api.stock, fetchFinishedGoodsFilterOptions: api.options,
}))
let wrapper: ReturnType<typeof mount> | undefined
beforeEach(() => {
  vi.resetAllMocks()
  api.stock.mockResolvedValue({ results: [], count: 0 })
  api.options.mockResolvedValue({ warehouses: [], zones: [] })
})
afterEach(() => wrapper?.unmount())

it('库存首次加载、搜索、重置和翻页都在服务端排除样品', async () => {
  wrapper = mount(FinishedGoodsInventoryView, { global: {
    plugins: [ElementPlus], stubs: { ElDialog: true, AssemblyPlanPicker: true },
  } })
  await flushPromises()
  expect(api.stock).toHaveBeenLastCalledWith(expect.objectContaining({ exclude_sample: true, page: 1 }))
  await wrapper.get('input[placeholder="搜索生产任务单号、品号、品名、货号、规格或颜色"]').setValue('测试品号')
  await wrapper.findAll('button').find(button => button.text() === '应用筛选')!.trigger('click')
  await flushPromises()
  expect(api.stock).toHaveBeenLastCalledWith(expect.objectContaining({ exclude_sample: true, q: '测试品号', page: 1 }))
  await wrapper.findAll('button').find(button => button.text() === '重置')!.trigger('click')
  await flushPromises()
  expect(api.stock).toHaveBeenLastCalledWith(expect.objectContaining({ exclude_sample: true, q: undefined }))
  const pagination = wrapper.findComponent({ name: 'ElPagination' })
  pagination.vm.$emit('update:current-page', 2)
  pagination.vm.$emit('current-change', 2)
  await flushPromises()
  expect(api.stock).toHaveBeenLastCalledWith(expect.objectContaining({ exclude_sample: true, page: 2 }))
})

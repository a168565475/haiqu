import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import FinishedGoodsInventoryView from './FinishedGoodsInventoryView.vue'

const api = vi.hoisted(() => ({ stock: vi.fn(), options: vi.fn() }))
const router = vi.hoisted(() => ({ push: vi.fn(), back: vi.fn() }))
const route = vi.hoisted(() => ({ query: {} as Record<string, string> }))
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => router }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))
vi.mock('@/directives/glassSpotlight', () => ({ vGlassSpotlight: {} }))
vi.mock('@/api/inventory', async importOriginal => ({
  ...await importOriginal<object>(), fetchFinishedGoodsInventory: api.stock, fetchFinishedGoodsFilterOptions: api.options,
}))
let wrapper: ReturnType<typeof mount> | undefined
beforeEach(() => {
  vi.resetAllMocks()
  route.query = {}
  api.stock.mockResolvedValue({ results: [], count: 0 })
  api.options.mockResolvedValue({ warehouses: [], zones: [] })
})
afterEach(() => wrapper?.unmount())

it('删除旧直接入库入口，保留装配待入库入口及历史记录导航', async () => {
  wrapper = mount(FinishedGoodsInventoryView, { global: {
    plugins: [ElementPlus], stubs: { ElDialog: true, AssemblyPlanPicker: true, FinishedReceiptRecordsPanel: true },
  } })
  await flushPromises()
  expect(wrapper.text()).not.toContain('其他入库')
  expect(wrapper.findAllComponents({ name: 'ElDialog' }).map(dialog => dialog.props('title'))).not.toContain('批量入库')
  await wrapper.findAll('button').find(button => button.text() === '成品入库')!.trigger('click')
  expect(wrapper.findComponent({ name: 'AssemblyPlanPicker' }).props('modelValue')).toBe(true)
  await wrapper.findAll('button').find(button => button.text() === '出库记录')!.trigger('click')
  expect(router.push).toHaveBeenCalledWith({ name: 'finished-goods-outbounds' })
  await wrapper.findAll('button').find(button => button.text() === '入库记录')!.trigger('click')
  expect(wrapper.find('finished-receipt-records-panel-stub').exists()).toBe(true)
})

it('保留已有库存选择并携带入库批次进入成品出库', async () => {
  api.stock.mockResolvedValue({ count: 1, results: [{
    inventory_key: 'stock-1', task_number: 'TASK-1', product_number: 'PRODUCT-1',
    product_name: '成品', inventory_quantity: 10, actual_color: '黑色', zone_name: 'A区', receipt_ids: ['receipt-1'],
  }] })
  wrapper = mount(FinishedGoodsInventoryView, { global: {
    plugins: [ElementPlus], stubs: { ElDialog: true, AssemblyPlanPicker: true, FinishedReceiptRecordsPanel: true },
  } })
  await flushPromises()
  const outbound = wrapper.findAll('button').find(button => button.text() === '批量出库')!
  expect(outbound.attributes('disabled')).toBeDefined()
  await wrapper.get('input[aria-label="全选库存"]').setValue(true)
  await outbound.trigger('click')
  expect(router.push).toHaveBeenCalledWith({ name: 'finished-goods-outbound-new', query: { receipt_ids: 'receipt-1' } })
})

it('通知固定tab=records时显示入库记录面板', async () => {
  route.query = { tab: 'records' }
  wrapper = mount(FinishedGoodsInventoryView, { global: {
    plugins: [ElementPlus], stubs: { ElDialog: true, AssemblyPlanPicker: true, FinishedReceiptRecordsPanel: true },
  } })
  await flushPromises()
  expect(wrapper.find('finished-receipt-records-panel-stub').exists()).toBe(true)
  expect(wrapper.find('input[placeholder="搜索生产任务单号、品号、品名、货号、规格或颜色"]').exists()).toBe(false)
})

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

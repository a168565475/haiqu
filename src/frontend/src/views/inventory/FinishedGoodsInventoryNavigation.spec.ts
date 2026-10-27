import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter, type LocationQueryRaw } from 'vue-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import FinishedGoodsInventoryView from './FinishedGoodsInventoryView.vue'
import FinishedReceiptRecordsPanel from './FinishedReceiptRecordsPanel.vue'
import { pageInstanceKey } from '@/utils/pageInstanceKey'

const api = vi.hoisted(() => ({ stock: vi.fn(), outbounds: vi.fn(), records: vi.fn(), options: vi.fn() }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))
vi.mock('@/directives/glassSpotlight', () => ({ vGlassSpotlight: {} }))
vi.mock('@/directives/horizontalOverflow', () => ({ vHorizontalOverflow: {} }))
vi.mock('@/api/inventory', async original => ({
  ...await original<object>(), fetchFinishedGoodsInventory: api.stock,
  fetchFinishedGoodsOutbounds: api.outbounds, fetchFinishedGoodsFilterOptions: api.options,
}))
vi.mock('@/api/finishedReceipts', async original => ({
  ...await original<object>(), fetchFinishedRecords: api.records,
}))

let wrapper: VueWrapper | undefined

async function openPage(query: LocationQueryRaw = {}) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/inventory/finished-goods', name: 'finished-goods-inventory', component: FinishedGoodsInventoryView },
  ] })
  await router.push({ name: 'finished-goods-inventory', query })
  await router.isReady()
  wrapper = mount({
    setup: () => ({ pageInstanceKey }),
    template: '<RouterView v-slot="{ Component, route }"><div :key="pageInstanceKey(route, 1)"><component :is="Component" /></div></RouterView>',
  }, { global: {
    plugins: [ElementPlus, router],
    stubs: { ElDialog: true, AssemblyPlanPicker: true, WarehouseConfigurationDialogs: true },
  } })
  await flushPromises()
  return router
}

async function click(text: string) {
  const button = wrapper!.findAll('button').find(item => item.text() === text)
  expect(button).toBeDefined()
  await button!.trigger('click')
  await flushPromises()
}

beforeEach(() => {
  vi.resetAllMocks()
  api.stock.mockResolvedValue({ results: [], count: 150 })
  api.outbounds.mockResolvedValue({ items: [], total: 0 })
  api.records.mockResolvedValue({ items: [], total: 0 })
  api.options.mockResolvedValue({ warehouses: [], zones: [] })
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

it('真实路由切换三个页签保留父页面实例以及库存关键词和页码', async () => {
  const router = await openPage()
  const inventoryId = wrapper!.getComponent(FinishedGoodsInventoryView).vm.$.uid
  const keyword = 'input[placeholder="搜索生产任务单号、品号、品名、货号、规格或颜色"]'
  await wrapper!.get(keyword).setValue('保留的库存关键词')
  await click('应用筛选')
  const pagination = wrapper!.getComponent({ name: 'ElPagination' })
  pagination.vm.$emit('update:current-page', 2)
  pagination.vm.$emit('current-change', 2)
  await flushPromises()
  expect(api.stock).toHaveBeenLastCalledWith(expect.objectContaining({ q: '保留的库存关键词', page: 2 }))
  const stockCalls = api.stock.mock.calls.length

  for (const [label, tab] of [['出库记录', 'outbounds'], ['入库记录', 'records']] as const) {
    await click(label)
    expect(router.currentRoute.value.query.tab).toBe(tab)
    expect(wrapper!.get('nav button.active').text()).toBe(label)
    expect(wrapper!.getComponent(FinishedGoodsInventoryView).vm.$.uid).toBe(inventoryId)
    expect(api.stock).toHaveBeenCalledTimes(stockCalls)
  }

  await click('库存汇总')
  expect(router.currentRoute.value.query.tab).toBe('stock')
  expect(wrapper!.getComponent(FinishedGoodsInventoryView).vm.$.uid).toBe(inventoryId)
  expect((wrapper!.get(keyword).element as HTMLInputElement).value).toBe('保留的库存关键词')
  expect(wrapper!.getComponent({ name: 'ElPagination' }).props('currentPage')).toBe(2)
  expect(api.stock).toHaveBeenLastCalledWith(expect.objectContaining({ q: '保留的库存关键词', page: 2 }))
  expect(api.stock).toHaveBeenCalledTimes(stockCalls + 1)
})

it('入库来源或通知查询变化只重建入库面板并读取新的范围', async () => {
  const router = await openPage({ tab: 'records', schedule_product_id: 'schedule-1', product_line_id: 'line-1' })
  const inventoryId = wrapper!.getComponent(FinishedGoodsInventoryView).vm.$.uid
  let receiptPanelId = wrapper!.getComponent(FinishedReceiptRecordsPanel).vm.$.uid
  expect(api.stock).not.toHaveBeenCalled()
  expect(api.records).toHaveBeenLastCalledWith(expect.objectContaining({ schedule_product_id: 'schedule-1', product_line_id: 'line-1' }))

  const scopes = [
    { schedule_product_id: 'schedule-2', product_line_id: 'line-1' },
    { schedule_product_id: 'schedule-2', product_line_id: 'line-2' },
    {},
  ]
  for (const scope of scopes) {
    await router.push({ name: 'finished-goods-inventory', query: { tab: 'records', ...scope } })
    await flushPromises()
    expect(wrapper!.getComponent(FinishedGoodsInventoryView).vm.$.uid).toBe(inventoryId)
    const nextPanelId = wrapper!.getComponent(FinishedReceiptRecordsPanel).vm.$.uid
    expect(nextPanelId).not.toBe(receiptPanelId)
    receiptPanelId = nextPanelId
    expect(api.records).toHaveBeenLastCalledWith(expect.objectContaining({
      schedule_product_id: scope.schedule_product_id,
      product_line_id: scope.product_line_id,
    }))
  }
  expect(api.records).toHaveBeenCalledTimes(4)
  expect(api.stock).not.toHaveBeenCalled()
})

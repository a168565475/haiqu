import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { reactive } from 'vue'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import FinishedGoodsInventoryView from './FinishedGoodsInventoryView.vue'
import WarehouseConfigurationDialogs from '@/components/inventory/WarehouseConfigurationDialogs.vue'

const api = vi.hoisted(() => ({ stock: vi.fn(), outbounds: vi.fn(), options: vi.fn(), warehouses: vi.fn(), zones: vi.fn(), locations: vi.fn() }))
const auth = vi.hoisted(() => ({ hasPermission: vi.fn() }))
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }))
const route = vi.hoisted(() => ({ query: {} as Record<string, string> }))
vi.mock('vue-router', () => ({ useRoute: () => reactive(route), useRouter: () => router }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => auth }))
vi.mock('@/directives/glassSpotlight', () => ({ vGlassSpotlight: {} }))
vi.mock('@/directives/horizontalOverflow', () => ({ vHorizontalOverflow: {} }))
vi.mock('@/api/inventory', async importOriginal => ({
  ...await importOriginal<object>(), fetchFinishedGoodsInventory: api.stock, fetchFinishedGoodsFilterOptions: api.options,
  fetchFinishedGoodsOutbounds: api.outbounds,
  fetchWarehouses: api.warehouses, fetchZones: api.zones, fetchLocations: api.locations,
}))
let wrapper: ReturnType<typeof mount> | undefined
beforeEach(() => {
  vi.resetAllMocks()
  route.query = {}
  router.replace.mockImplementation(async ({ query }) => { reactive(route).query = query })
  auth.hasPermission.mockReturnValue(true)
  api.stock.mockResolvedValue({ results: [], count: 0 })
  api.outbounds.mockResolvedValue({ items: [], total: 0 })
  api.options.mockResolvedValue({ warehouses: [], zones: [] })
  api.warehouses.mockResolvedValue([])
  api.zones.mockResolvedValue([])
  api.locations.mockResolvedValue([])
})
afterEach(() => wrapper?.unmount())

it('保留成品入库入口，库存汇总、入库记录、出库记录在同一页面切换', async () => {
  wrapper = mount(FinishedGoodsInventoryView, { global: {
    plugins: [ElementPlus], stubs: { ElDialog: true, AssemblyPlanPicker: true,
      FinishedReceiptRecordsPanel: { template: '<section data-testid="receipt-panel"><slot/></section>' },
    },
  } })
  await flushPromises()
  expect(wrapper.text()).not.toContain('其他入库')
  expect(wrapper.findAllComponents({ name: 'ElDialog' }).map(dialog => dialog.props('title'))).not.toContain('批量入库')
  await wrapper.findAll('button').find(button => button.text() === '成品入库')!.trigger('click')
  expect(wrapper.findComponent({ name: 'AssemblyPlanPicker' }).props('modelValue')).toBe(true)
  await wrapper.findAll('button').find(button => button.text() === '出库记录')!.trigger('click')
  await flushPromises()
  expect(router.push).not.toHaveBeenCalled()
  expect(wrapper.get('nav button.active').text()).toBe('出库记录')
  expect(wrapper.findAll('nav[aria-label="成品库存视图"]')).toHaveLength(1)
  expect(wrapper.text()).toContain('暂无出库记录')
  expect(route.query.tab).toBe('outbounds')
  await wrapper.findAll('button').find(button => button.text() === '从库存选择出库')!.trigger('click')
  await flushPromises()
  expect(wrapper.get('nav button.active').text()).toBe('库存汇总')
  expect(route.query.tab).toBe('stock')
  await wrapper.findAll('button').find(button => button.text() === '入库记录')!.trigger('click')
  expect(wrapper.find('[data-testid="receipt-panel"]').exists()).toBe(true)
  expect(wrapper.get('nav button.active').text()).toBe('入库记录')
  await wrapper.findAll('button').find(button => button.text() === '出库记录')!.trigger('click')
  await flushPromises()
  expect(wrapper.get('nav button.active').text()).toBe('出库记录')
  expect(router.push).not.toHaveBeenCalled()
})

it('出库页签直达、刷新及已有页面内的地址变化保留选中视图和产品筛选', async () => {
  route.query = { tab: 'outbounds', production_task_id: 'task-1', product_line_id: 'line-1' }
  wrapper = mount(FinishedGoodsInventoryView, { global: {
    plugins: [ElementPlus], stubs: { ElDialog: true, AssemblyPlanPicker: true, FinishedReceiptRecordsPanel: true },
  } })
  await flushPromises()
  expect(wrapper.get('nav button.active').text()).toBe('出库记录')
  expect(api.outbounds).toHaveBeenLastCalledWith(expect.objectContaining({ production_task_id: 'task-1', product_line_id: 'line-1' }))
  expect(api.stock).not.toHaveBeenCalled()
  await wrapper.findAll('button').find(button => button.text() === '库存汇总')!.trigger('click')
  await flushPromises()
  expect(route.query).toEqual({ tab: 'stock', production_task_id: 'task-1', product_line_id: 'line-1' })
  reactive(route).query = { tab: 'records' }
  await flushPromises()
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

it.each(['stock', 'records'])('%s 页签使用成品仓配置，成功保存只刷新筛选选项', async tab => {
  route.query = { tab }
  wrapper = mount(FinishedGoodsInventoryView, { global: {
    plugins: [ElementPlus], stubs: {
      ElDialog: true, AssemblyPlanPicker: true,
      FinishedReceiptRecordsPanel: { template: '<section><slot name="heading"/><slot name="actions"/><slot/></section>' },
    },
  } })
  await flushPromises()
  const configuration = wrapper.findComponent(WarehouseConfigurationDialogs)
  expect(configuration.exists()).toBe(true)
  expect(configuration.props('warehouseType')).toBe('FINISHED')
  expect(api.warehouses).not.toHaveBeenCalled()

  wrapper.findComponent({ name: 'ElDropdown' }).vm.$emit('command', 'warehouse')
  await flushPromises()
  expect(api.warehouses).toHaveBeenCalledOnce()
  expect(configuration.findAllComponents({ name: 'ElDialog' })[0]!.props('modelValue')).toBe(true)
  wrapper.findComponent({ name: 'ElDropdown' }).vm.$emit('command', 'location')
  await flushPromises()
  expect(api.zones).toHaveBeenCalledTimes(2)
  expect(api.locations).toHaveBeenCalledTimes(2)
  expect(configuration.findAllComponents({ name: 'ElDialog' })[1]!.props('modelValue')).toBe(true)

  api.options.mockResolvedValueOnce({ warehouses: [{ id: 'new-finished', warehouse_name: '新增成品仓' }], zones: [] })
  configuration.vm.$emit('saved')
  await flushPromises()
  expect(api.options).toHaveBeenCalledTimes(2)
  expect(api.stock).toHaveBeenCalledTimes(tab === 'stock' ? 1 : 0)
  if (tab === 'stock') {
    expect(wrapper.findAllComponents({ name: 'ElOption' }).some(option => option.props('label') === '新增成品仓')).toBe(true)
  }
})

it('无配置查看权限时隐藏入口，也不加载配置数据', async () => {
  auth.hasPermission.mockReturnValue(false)
  wrapper = mount(FinishedGoodsInventoryView, { global: {
    plugins: [ElementPlus], stubs: { ElDialog: true, AssemblyPlanPicker: true, FinishedReceiptRecordsPanel: true },
  } })
  await flushPromises()
  expect(wrapper.text()).not.toContain('仓库配置')
  expect(api.warehouses).not.toHaveBeenCalled()
  expect(api.zones).not.toHaveBeenCalled()
  expect(api.locations).not.toHaveBeenCalled()
})

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, expect, it, vi } from 'vitest'
import * as api from '@/api/inventory'
import { router } from '@/router'
import MaterialInventoryView from './MaterialInventoryView.vue'
import MaterialInboundDetailView from './MaterialInboundDetailView.vue'
import ManualMaterialInboundDialog from '@/components/inventory/ManualMaterialInboundDialog.vue'
import FinishedGoodsInventoryView from './FinishedGoodsInventoryView.vue'

const routeState = vi.hoisted(() => ({ query: {} as Record<string, unknown> }))
vi.mock('@/router', () => ({ router: { push: vi.fn(), replace: vi.fn() } }))
vi.mock('vue-router', () => ({ useRoute: () => routeState, useRouter: () => router }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))
vi.mock('@/api/inventory', async importOriginal => {
  const original = await importOriginal<typeof api>()
  return Object.fromEntries(Object.keys(original).map(key => [key, vi.fn()]))
})
const filters = { warehouses: [], zones: [], sections: [] }
beforeEach(() => {
  vi.resetAllMocks()
  Object.keys(routeState.query).forEach(key => { delete routeState.query[key] })
  vi.mocked(api.fetchMaterialFilterOptions).mockResolvedValue(filters)
  vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue(filters)
  vi.mocked(api.fetchFinishedGoodsFilterOptions).mockResolvedValue(filters)
  vi.mocked(api.fetchMaterialInventory).mockResolvedValue({ count: 0, results: [] } as never)
  vi.mocked(api.fetchFinishedGoodsInventory).mockResolvedValue({ count: 0, results: [] })
  vi.mocked(api.fetchMaterialInboundDetails).mockResolvedValue([])
  vi.mocked(api.fetchManualMaterialOptions).mockResolvedValue({ categories: [], materials: [] })
})
it('三个库存读取页面仅加载筛选选项，明细和空列表可独立完成', async () => {
  for (const component of [MaterialInventoryView, MaterialInboundDetailView, FinishedGoodsInventoryView]) {
    const wrapper = shallowMount(component, { global: { plugins: [ElementPlus] } }); await flushPromises()
    expect((wrapper.vm as unknown as { loading: boolean }).loading).toBe(false)
    wrapper.unmount()
  }
  expect(api.fetchMaterialFilterOptions).toHaveBeenCalledTimes(2)
  expect(api.fetchFinishedGoodsFilterOptions).toHaveBeenCalledTimes(1)
  expect(api.fetchMaterialInventoryOptions).not.toHaveBeenCalled()
  expect(api.fetchInventoryOptions).not.toHaveBeenCalled()
})
it('手工入库只取材料仓和库区，未填写时不能提交', async () => {
  const wrapper = shallowMount(ManualMaterialInboundDialog, { global: { plugins: [ElementPlus] } }); await flushPromises()
  expect(api.fetchMaterialReceivingOptions).toHaveBeenCalledOnce()
  expect((wrapper.vm as unknown as { ready: boolean }).ready).toBe(false)
  expect(api.createManualMaterialReceipt).not.toHaveBeenCalled(); wrapper.unmount()
})
it('材料入库在列表弹出，关闭不跳页，成功刷新当前库存', async () => {
  const wrapper = shallowMount(MaterialInventoryView, { global: { plugins: [ElementPlus], stubs: { ElButton: { template: '<button><slot /></button>' } } } }); await flushPromises()
  expect(wrapper.findAll('button').some(button => button.text() === '材料入库')).toBe(true)
  const vm = wrapper.vm as unknown as { inboundOpen: boolean }
  vm.inboundOpen = true; await flushPromises()
  wrapper.findComponent(ManualMaterialInboundDialog).vm.$emit('close'); await flushPromises()
  expect(wrapper.findComponent(ManualMaterialInboundDialog).exists()).toBe(false)
  expect(router.push).not.toHaveBeenCalled(); expect(router.replace).not.toHaveBeenCalled()
  vm.inboundOpen = true; await flushPromises()
  vi.mocked(api.fetchMaterialInventory).mockClear()
  wrapper.findComponent(ManualMaterialInboundDialog).vm.$emit('saved'); await flushPromises()
  expect(wrapper.findComponent(ManualMaterialInboundDialog).exists()).toBe(false)
  expect(api.fetchMaterialInventory).toHaveBeenCalledOnce()
  wrapper.unmount()
})
it('材料库存旧响应和卸载后的响应失效', async () => {
  const wrapper = shallowMount(MaterialInventoryView, { global: { plugins: [ElementPlus] } }); await flushPromises()
  const vm = wrapper.vm as unknown as { loadRows: () => Promise<void>; total: number; loading: boolean }
  let finish!: (value: never) => void
  vi.mocked(api.fetchMaterialInventory).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
  const pending = vm.loadRows(); vi.mocked(api.fetchMaterialInventory).mockResolvedValueOnce({ count: 2, results: [] } as never)
  await vm.loadRows(); finish({ count: 1, results: [] } as never); await pending
  expect(vm.total).toBe(2); expect(vm.loading).toBe(false)
  vi.mocked(api.fetchMaterialInventory).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
  const late = vm.loadRows(); wrapper.unmount(); finish({ count: 3, results: [] } as never); await late; expect(vm.total).toBe(2)
})
it('材料库存遵循紧凑列表字段规范', async () => {
  const wrapper = shallowMount(MaterialInventoryView, { global: { plugins: [ElementPlus] } }); await flushPromises()
  expect(wrapper.find('.summary-grid').exists()).toBe(false)
  expect(wrapper.find('.page-heading').text()).toContain('材料库存')
  const source = readFileSync(resolve(process.cwd(), 'src/views/inventory/MaterialInventoryView.vue'), 'utf8')
  expect(source).toContain('aria-label="材料分类" placeholder="材料分类：全部"')
  expect(source).toContain('label="材料分类"')
  expect(source).toContain('label="颜色"')
  expect(source).toContain('label-class-name="sequence-column"')
  expect(source).toContain("{{ row.warehouse_name || '—' }}")
  expect(source).not.toContain('label="BOM 分区"')
  expect(source).not.toContain('label="原料信息"')
  expect(source).not.toContain('label="入库批次"')
  wrapper.unmount()
})
it('半成品库存入口从路由读取库存性质并传递加工状态筛选', async () => {
  routeState.query.stock_kind = 'SEMI'
  const wrapper = shallowMount(MaterialInventoryView, { global: { plugins: [ElementPlus], stubs: { ElButton: { template: '<button><slot /></button>' } } } }); await flushPromises()
  expect(api.fetchMaterialInventory).toHaveBeenCalledWith(expect.objectContaining({ stock_kind: 'SEMI', processing_status: undefined }))
  const source = readFileSync(resolve(process.cwd(), 'src/views/inventory/MaterialInventoryView.vue'), 'utf8')
  expect(source).toContain('placeholder="加工状态：全部"')
  expect(source).toContain('label="加工状态"')
  expect(wrapper.findAll('button').some(button => button.text() === '喷塑入库')).toBe(false)
  expect(wrapper.findAll('button').some(button => button.text() === '入库记录')).toBe(true)
  expect(wrapper.findComponent(ManualMaterialInboundDialog).exists()).toBe(false)
  expect(source).toContain('processing_status_label')
  wrapper.unmount()
})
it('成品库存出库入口仅传递选中批次，由出库页面加载操作选项', async () => {
  const wrapper = shallowMount(FinishedGoodsInventoryView, { global: { plugins: [ElementPlus] } }); await flushPromises()
  const vm = wrapper.vm as unknown as { selectedRows: unknown[]; openOutbound: () => Promise<void> }
  vm.selectedRows = [{ task_number: 'TASK-1', receipt_ids: ['new'] }]
  await vm.openOutbound(); await flushPromises()
  expect(router.push).toHaveBeenCalledWith({ name: 'finished-goods-outbound-new', query: { receipt_ids: 'new' } })
  expect(api.fetchInventoryOptions).not.toHaveBeenCalled()
  expect(api.fetchOutboundBatches).not.toHaveBeenCalled()
  expect(api.createFinishedGoodsOutbound).not.toHaveBeenCalled(); wrapper.unmount()
})

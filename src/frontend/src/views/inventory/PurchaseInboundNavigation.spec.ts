import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PurchaseInboundListView from '../procurement/PurchaseInboundListView.vue'
import MaterialPurchaseInboundView from './MaterialPurchaseInboundView.vue'
import { router as detachedRouter } from '@/router'

// 重现开发热更新后的情况：模块导出的路由与应用安装的路由不是同一个实例。
vi.mock('@/router', async () => {
  const { createMemoryHistory, createRouter } = await import('vue-router')
  return { router: createRouter({ history: createMemoryHistory(), routes: [
    { path: '/purchase-inbound', name: 'purchase-inbounds', component: { template: '<div />' } },
    { path: '/purchase-inbound/:id/details', name: 'purchase-inbound-detail', component: { template: '<div />' } },
    { path: '/purchase-inbound/order/:purchaseOrderId', name: 'material-purchase-inbound', component: { template: '<div />' } },
  ] }) }
})
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))
vi.mock('@/api/inventory', () => ({
  fetchProcurementInboundOrders: vi.fn().mockResolvedValue([]),
  fetchMaterialReceivingOptions: vi.fn().mockResolvedValue({ warehouses: [], zones: [] }),
  fetchEligibleMaterialPurchaseOrders: vi.fn().mockResolvedValue([]),
  fetchEligibleMaterialLinesWithVersion: vi.fn().mockResolvedValue({ data: [], etag: '"v1"' }),
  createMaterialReceiving: vi.fn(),
}))

const order = { id: 'order-1', workflow_status: 'WAITING_RECEIVING', remaining_line_count: 1, return_status: 'NONE' }

async function mountPage(component: typeof PurchaseInboundListView | typeof MaterialPurchaseInboundView, start: string) {
  const appRouter = createRouter({ history: createMemoryHistory(), routes: detachedRouter.getRoutes() })
  await appRouter.push(start)
  const wrapper = shallowMount(component, { global: { plugins: [appRouter, ElementPlus] } })
  await flushPromises()
  return { wrapper, appRouter }
}

describe('采购入库使用当前应用的路由', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    localStorage.clear()
    await detachedRouter.push('/purchase-inbound')
  })

  it.each([
    ['openDetails', '/purchase-inbound/order-1/details'],
    ['openReceiving', '/purchase-inbound/order/order-1'],
  ] as const)('%s 同时更新当前应用路由', async (action, expected) => {
    const { wrapper, appRouter } = await mountPage(PurchaseInboundListView, '/purchase-inbound')
    try {
      const vm = wrapper.vm as unknown as { openDetails: (row: typeof order) => void; openReceiving: (row: typeof order) => void }
      vm[action](order)
      await flushPromises()
      expect(appRouter.currentRoute.value.fullPath).toBe(expected)
      expect(detachedRouter.currentRoute.value.fullPath).toBe('/purchase-inbound')
    } finally { wrapper.unmount() }
  })

  it('已完成采购单仍不可办理入库', async () => {
    const { wrapper, appRouter } = await mountPage(PurchaseInboundListView, '/purchase-inbound')
    try {
      const vm = wrapper.vm as unknown as { openReceiving: (row: typeof order) => void }
      vm.openReceiving({ ...order, workflow_status: 'COMPLETED' })
      await flushPromises()
      expect(appRouter.currentRoute.value.fullPath).toBe('/purchase-inbound')
      expect(detachedRouter.currentRoute.value.fullPath).toBe('/purchase-inbound')
    } finally { wrapper.unmount() }
  })

  it('办理页返回列表更新当前应用路由', async () => {
    const { wrapper, appRouter } = await mountPage(MaterialPurchaseInboundView, '/purchase-inbound/order/order-1')
    try {
      wrapper.get('.head-actions').findAllComponents({ name: 'ElButton' })[1]!.vm.$emit('click')
      await flushPromises()
      expect(appRouter.currentRoute.value.fullPath).toBe('/purchase-inbound')
    } finally { wrapper.unmount() }
  })

  it('采购入库、退货明细和生产领料保留旧路径并使用仓库上下文', async () => {
    const { router: actualRouter } = await vi.importActual<typeof import('@/router')>('@/router')
    const expected = [
      ['purchase-inbounds', '/purchase-inbound', '采购入库'],
      ['purchase-returns', '/purchase-returns', '退货明细'],
      ['material-issues', '/workshop/material-issues', '生产领料'],
    ] as const
    for (const [name, path, label] of expected) {
      const route = actualRouter.getRoutes().find(item => item.name === name)
      expect(route?.path).toBe(path)
      expect(route?.meta.headerTitle).toBe(`仓库管理 / ${label}`)
      expect((route?.meta.breadcrumbs as Array<{ label: string }>)[0]?.label).toBe('仓库管理')
    }
    const procurementRoute = actualRouter.getRoutes().find(item => item.name === 'purchase-return-records')
    expect(procurementRoute?.path).toBe('/purchase-return-records')
    expect(procurementRoute?.meta.headerTitle).toBe('采购管理 / 退货记录')
    expect((procurementRoute?.meta.breadcrumbs as Array<{ label: string }>)[0]?.label).toBe('采购管理')
  })
})

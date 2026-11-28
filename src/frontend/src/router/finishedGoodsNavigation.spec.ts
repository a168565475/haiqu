import { createPinia, setActivePinia } from 'pinia'
import { expect, it } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import { router } from './index'

it('原成品库存收发链接进入独立记录页，保留来源筛选', async () => {
  setActivePinia(createPinia())
  useAuthStore().applyAuthResponse({ authenticated: true, user: {
    id: 1, username: 'warehouse', display_name: '仓库', is_superuser: false, employee: null,
    permissions: ['inventory.view_finishedgoodsreceipt', 'inventory.view_finishedgoodsoutbound'], data_scope: 'ALL',
  } })
  const filters = { production_task_id: 'task-1', product_line_id: 'line-1', schedule_product_id: 'schedule-1' }
  for (const [tab, name, title] of [
    ['outbounds', 'finished-goods-outbounds', '成品出库记录'],
    ['records', 'finished-goods-inbound-records', '成品入库记录'],
  ] as const) {
    await router.push({ name: 'finished-goods-inventory', query: { ...filters, tab } })
    expect(router.currentRoute.value.name).toBe(name)
    expect(router.currentRoute.value.query).toEqual(filters)
    expect(router.currentRoute.value.meta.headerTitle).toBe('仓库管理 / ' + title)
  }
  await router.push({ name: 'finished-goods-outbound-detail', params: { outboundId: 'out-1' } })
  await router.push({ path: '/inventory/finished-goods/outbounds', query: filters })
  expect(router.currentRoute.value.name).toBe('finished-goods-outbounds')
  expect(router.currentRoute.value.query).toEqual(filters)
})

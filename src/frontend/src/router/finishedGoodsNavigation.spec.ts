import { expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { router } from './index'

it('旧出库列表和详情返回入口统一进入成品库存出库页签，保留来源筛选', async () => {
  const navigation = createRouter({ history: createMemoryHistory(), routes: router.getRoutes() })
  await navigation.push('/inventory/finished-goods/outbounds?production_task_id=task-1&product_line_id=line-1&schedule_product_id=schedule-1')
  expect(navigation.currentRoute.value.name).toBe('finished-goods-inventory')
  expect(navigation.currentRoute.value.query).toEqual({
    tab: 'outbounds', production_task_id: 'task-1', product_line_id: 'line-1', schedule_product_id: 'schedule-1',
  })
  expect(navigation.currentRoute.value.meta.headerTitle).toBe('仓库管理 / 成品库存')
  await navigation.push({ name: 'finished-goods-outbound-detail', params: { outboundId: 'out-1' } })
  await navigation.push({ name: 'finished-goods-outbounds' })
  expect(navigation.currentRoute.value.name).toBe('finished-goods-inventory')
  expect(navigation.currentRoute.value.query).toEqual({ tab: 'outbounds' })
})

import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { router } from './index'

describe('委外新建入口退役后的路由', () => {
  it('半成品旧喷塑入库入口不再打开选单弹窗，统一进入仓库委外管理', async () => {
    const navigation = createRouter({ history: createMemoryHistory(), routes: router.getRoutes() })
    await navigation.push('/inventory/semi-finished/tube-return')
    expect(navigation.currentRoute.value.name).toBe('warehouse-outsourcing')
    await navigation.push('/inventory/semi-finished/tube-return?order_id=order-1&category=cutting&record=existing')
    expect(navigation.currentRoute.value.name).toBe('warehouse-outsourcing-tube-return')
    expect(navigation.currentRoute.value.params.id).toBe('order-1')
    expect(navigation.currentRoute.value.query).toEqual({ category: 'cutting', record: 'existing' })
    expect(navigation.currentRoute.value.meta.activeMenu).toBe('warehouse-outsourcing')
  })

  it('丝印旧菜单地址进入委外加工，旧建单与详情地址仍归属同一菜单', async () => {
    const navigation = createRouter({ history: createMemoryHistory(), routes: router.getRoutes() })
    await navigation.push('/workshop/cut-piece-printing')
    expect(navigation.currentRoute.value.name).toBe('workshop-outsourcing')
    for (const path of ['/workshop/cut-piece-printing/new', '/workshop/cut-piece-printing/order-1',
      '/workshop/outsourcing/screen-printing/new', '/workshop/outsourcing/screen-printing/order-1']) {
      expect(router.resolve(path).meta.activeMenu).toBe('workshop-outsourcing')
    }
  })

  it('旧回货表单入口转到仓库，保留单据和查询参数', async () => {
    const navigation = createRouter({ history: createMemoryHistory(), routes: router.getRoutes() })
    await navigation.push('/workshop/outsourcing/tube/order-1/return?record=existing')
    expect(navigation.currentRoute.value.name).toBe('warehouse-outsourcing-tube-return')
    expect(navigation.currentRoute.value.params.id).toBe('order-1')
    expect(navigation.currentRoute.value.query.record).toBe('existing')
    expect(navigation.currentRoute.value.meta.activeMenu).toBe('warehouse-outsourcing')
  })

  it.each(['/warehouse/outsourcing', '/warehouse/outsourcing/order-1', '/warehouse/outsourcing/tube/order-1', '/warehouse/outsourcing/rework/order-1'])('仓库入口 %s 保持仓库上下文', path => {
    const target = router.resolve(path)
    expect(target.meta.outsourcingWorkspace).toBe('warehouse')
    expect(target.meta.activeMenu).toBe('warehouse-outsourcing')
  })
  it('旧新建地址返回列表，不把 new 当成历史单据编号', async () => {
    const navigation = createRouter({ history: createMemoryHistory(), routes: router.getRoutes() })
    await navigation.push('/workshop/outsourcing/new?source_issue_line_id=old-source')
    expect(navigation.currentRoute.value.name).toBe('workshop-outsourcing')
    expect(navigation.currentRoute.value.params.orderId).toBeUndefined()
    expect(router.hasRoute('workshop-outsourcing-new')).toBe(false)
  })

  it.each([
    ['/workshop/outsourcing/tube/new', 'workshop-outsourcing-tube-new'],
    ['/workshop/outsourcing/tube/new?category=cutting', 'workshop-outsourcing-tube-new'],
    ['/workshop/outsourcing/8e554916-bf79-4930-9e77-05ea814893af', 'workshop-outsourcing-detail'],
  ])('保留 %s 的目标页面', (path, name) => {
    expect(router.resolve(path).name).toBe(name)
  })
})

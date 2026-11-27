import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { SewingWorkbenchActivity, SewingWorkbenchOrder, SewingWorkbenchOverview } from '@/types/sewingOutsourcingWorkbench'
import SewingOutsourcingWorkbench from './SewingOutsourcingWorkbench.vue'

const api = vi.hoisted(() => ({ overview: vi.fn(), activity: vi.fn(), items: vi.fn(), inbox: vi.fn() }))
vi.mock('@/api/sewingOutsourcingWorkbench', () => ({
  getSewingOverview: api.overview, getSewingActivity: api.activity, getSewingItems: api.items,
}))
vi.mock('@/api/notifications', async original => ({
  ...await original<typeof import('@/api/notifications')>(), getNotificationInbox: api.inbox,
}))

const overview: SewingWorkbenchOverview = {
  as_of: '2026-11-26', counts: { send: 4, working: 7, soon: 3, today: 1, overdue: 2, late_send: 2, today_send: 1, partial: 1 },
  upcoming: ['11-26', '11-27', '11-28', '11-29', '11-30', '12-01', '12-02'].map((day, i) => ({ date: '2026-' + day, count: i < 4 ? 1 : 0 })),
}
const month: SewingWorkbenchActivity = {
  start_date: '2026-11-01', end_date: '2026-11-26', dispatch_orders: 8, dispatch_factories: 2,
  receipt_orders: 6, receipt_factories: 2, receipt_events: 7, quantities: [{ quantity: '735', unit: '件' }],
  factories: [
    { id: 'factory-a', name: '一厂', order_count: 2, quantities: [{ unit: '件', quantity: '435' }] },
    { id: 'factory-b', name: '二厂', order_count: 4, quantities: [{ unit: '件', quantity: '300' }] },
  ],
}
const order: SewingWorkbenchOrder = {
  id: 'order-1', is_plan: true, task_number: 'SC-12', order_number: 'WF-14', product_name: '扶手椅',
  planned_dispatch_date: '2026-11-20', expected_return_date: '2026-11-25', last_dispatch_date: '2026-11-22', last_receipt_date: '2026-11-23',
  factories: ['一厂'], materials: [{ name: '椅面裁片', factory_name: '一厂', target: '200', actual: '120', remaining: '80', unit: '片' }],
  parts: [{ name: '椅面', factory_name: '一厂', target: '100', actual: '70', remaining: '30', unit: '件' }],
}

const mounted: ReturnType<typeof mount>[] = []
async function render() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
  await router.push('/')
  const page = mount(SewingOutsourcingWorkbench, { global: {
    plugins: [createPinia(), router],
    stubs: { AppWindowDialog: { template: '<div role="dialog"><slot /></div>' }, RouterLink: RouterLinkStub, ElPagination: true, ElButton: { template: '<button><slot /></button>' } },
  } })
  mounted.push(page)
  await flushPromises()
  return page
}
beforeEach(() => {
  vi.clearAllMocks()
  api.overview.mockResolvedValue(overview)
  api.activity.mockResolvedValue(month)
  api.items.mockResolvedValue({ data: [order], meta: { total: 1, page: 1, page_size: 20, total_pages: 1 } })
  api.inbox.mockResolvedValue({ count: 1, data: [{ id: 'message-1', title: '已登记回货', created_at: '2026-11-24T00:30:00Z' }] })
})
afterEach(() => mounted.splice(0).forEach(wrapper => wrapper.unmount()))

describe('车缝外协工作台', () => {
  it('首屏显示五项待办、实际收发汇总、七天日历及未读；点逾期可看到欠回部位并进入外协单', async () => {
    const page = await render()
    expect(page.findAll('.todo strong').map(n => n.text())).toEqual(['4', '7', '3', '1', '2'])
    expect(page.findAll('.week-bars button')).toHaveLength(7)
    expect(page.find('.msgrow').text()).toContain('已登记回货')
    expect(api.inbox).toHaveBeenCalledWith(1, expect.any(AbortSignal), true)
    expect(page.get('.factory-panel .rank').text()).toContain('一厂')
    expect(page.find('table').exists()).toBe(false)
    await page.findAll('.todo')[4]!.trigger('click'); await flushPromises()
    expect(api.items).toHaveBeenCalledWith('overdue', 1, undefined, expect.any(AbortSignal))
    expect(page.get('th').text()).toBe('生产任务单号')
    expect(page.get('tbody').text()).toContain('30 件')
    expect(page.get('tbody').text()).toContain('逾期 1 天')
    expect(page.getComponent(RouterLinkStub).props('to')).toEqual({ name: 'workshop-outsourcing-tube-detail', params: { id: 'order-1' } })
  })
  it('补发读取裁片单位，点七天图的某天只查那天的外协单', async () => {
    const page = await render()
    await page.findAll('.follow-row')[2]!.trigger('click'); await flushPromises()
    expect(page.get('tbody').text()).toContain('80 片')
    expect(api.items).toHaveBeenLastCalledWith('partial', 1, undefined, expect.any(AbortSignal))
    await page.findAll('.week-bars button')[1]!.trigger('click'); await flushPromises()
    expect(api.items).toHaveBeenLastCalledWith('upcoming', 1, '2026-11-27', expect.any(AbortSignal))
    expect(page.get('tbody').text()).toContain('30 件')
  })
  it('切换季度重取周期数据，多单位分别显示，工厂按有回货单数排', async () => {
    const page = await render()
    api.activity.mockResolvedValueOnce({ ...month, start_date: '2026-10-01', quantities: [{ unit: '套', quantity: '25' }, ...month.quantities],
      factories: [{ ...month.factories[1], quantities: [{ unit: '套', quantity: '25' }, ...month.factories[1]!.quantities] }, month.factories[0]],
    })
    await page.findAll('.period-toggle button')[1]!.trigger('click'); await flushPromises()
    expect(api.activity).toHaveBeenLastCalledWith('quarter', expect.any(AbortSignal))
    expect(page.get('.period-toggle [aria-pressed=true]').text()).toBe('本季')
    expect(page.findAll('.quantities .metric-value').map(n => n.text())).toEqual(['25套', '735件'])
    expect(page.get('.factory-panel .rank').text()).toContain('二厂')
    expect(page.get('.factory-panel .subtitle').text()).toContain('按有回货的总单数排序')
    expect(page.get('.range').text()).toContain('10/01')
    expect(api.overview).toHaveBeenCalledTimes(1)
  })
  it('加载出错可重试，空待办、空汇总和未读显示真实状态', async () => {
    api.overview.mockRejectedValueOnce(new Error('network'))
    api.items.mockResolvedValueOnce({ data: [], meta: { page: 1, page_size: 20, total: 0, total_pages: 0 } })
    api.activity.mockResolvedValueOnce({ ...month, factories: [], quantities: [], receipt_events: 0, receipt_orders: 0 })
    api.inbox.mockResolvedValueOnce({ count: 0, data: [] })
    const page = await render()
    expect(page.get('[role=alert]').text()).toContain('加载车缝外协工作台失败')
    await page.get('[role=alert] button').trigger('click'); await flushPromises()
    expect(page.text()).toContain('本期暂无加工厂回货')
    expect(page.text()).toContain('暂无未读消息')
    await page.get('.todo').trigger('click'); await flushPromises()
    expect(page.get('[role=dialog]').text()).toContain('当前没有这类外协单')
  })
})

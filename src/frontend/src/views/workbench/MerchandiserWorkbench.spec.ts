import { enableAutoUnmount, flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import type { MerchandiserActivity, MerchandiserItems, MerchandiserOverview } from '@/types/merchandiserWorkbench'
import MerchandiserWorkbench from './MerchandiserWorkbench.vue'

const api = vi.hoisted(() => ({ overview: vi.fn(), activity: vi.fn(), items: vi.fn(), inbox: vi.fn() }))
vi.mock('@/api/merchandiserWorkbench', () => ({
  getMerchandiserOverview: api.overview, getMerchandiserActivity: api.activity, getMerchandiserItems: api.items,
}))
vi.mock('@/api/notifications', async original => ({
  ...await original<typeof import('@/api/notifications')>(), getNotificationInbox: api.inbox,
}))
enableAutoUnmount(afterEach)

const overview: MerchandiserOverview = {
  as_of: '2026-11-26', counts: { need: 5, soon: 4, late: 3, owing: 2, past: 1, unsent: 3, returns: 1, ordinary: 1 },
  upcoming: ['11-26', '11-27', '11-28', '11-29', '11-30', '12-01', '12-02'].map((day, i) => ({ date: '2026-' + day, count: i - 2 > 0 ? 1 : 0 })),
}
const activity: MerchandiserActivity = {
  start_date: '2026-11-01', end_date: '2026-11-30', as_of: '2026-11-26', task_count: 5, purchase_order_count: 4, supplier_count: 2,
  amounts: [{ currency: 'CNY', amount: '1234.50' }, { currency: 'USD', amount: '1200' }], unpriced_count: 1, undated_count: 2, unknown_supplier_count: 0,
  suppliers: [
    { id: 's1', name: '纸箱厂', order_count: 3, unpriced_count: 1, amounts: [{ currency: 'CNY', amount: '1234.50' }] },
    { id: 's2', name: '吊牌厂', order_count: 1, unpriced_count: 0, amounts: [{ currency: 'USD', amount: '1200' }] },
  ],
}
const items: MerchandiserItems = {
  data: { columns: [{ key: 'supplier', label: '丝印厂' }, { key: 'due', label: '丝印厂待交' }],
    rows: [{ task_id: 'task-1', task_number: 'SC-11', cells: { supplier: '丝印一厂', due: '70 片' } }] },
  meta: { page: 1, page_size: 20, total: 1, total_pages: 1 },
}
async function render() {
  const pinia = createPinia()
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
  await router.push('/')
  const page = mount(MerchandiserWorkbench, { global: {
    plugins: [pinia, router], stubs: { AppWindowDialog: { template: '<div role="dialog"><slot /></div>' }, RouterLink: RouterLinkStub,
      ElButton: { template: '<button><slot /></button>' }, ElPagination: true },
  } })
  await flushPromises()
  return { page, auth: useAuthStore(pinia) }
}
beforeEach(() => {
  vi.resetAllMocks()
  api.overview.mockResolvedValue(overview)
  api.activity.mockResolvedValue(activity)
  api.items.mockResolvedValue(items)
  api.inbox.mockResolvedValue({ count: 1, data: [{ id: 'n1', title: '包材 BOM 已确认', created_at: '2026-11-26T00:00:00Z' }] })
})

describe('跟单工作台', () => {
  it('首屏保留五项待办和未读消息，点丝印待交先看真实单号，再进生产任务', async () => {
    const { page } = await render()
    expect(page.get('h1').text()).toContain('本人跟进的生产任务')
    expect(page.findAll('.todo strong').map(node => node.text())).toEqual(['5', '4', '3', '2', '1'])
    expect(page.find('table').exists()).toBe(false)
    expect(page.get('.msgrow').text()).toContain('包材 BOM 已确认')
    await page.findAll('.todo')[3]!.trigger('click')
    await flushPromises()
    expect(api.items).toHaveBeenLastCalledWith(expect.objectContaining({ category: 'owing' }), 1, expect.any(AbortSignal))
    expect(page.get('th').text()).toBe('生产任务单号')
    expect(page.get('tbody').text()).toContain('70 片')
    expect(page.getComponent(RouterLinkStub).props('to')).toEqual({ name: 'production-task-detail', params: { taskId: 'task-1' } })
  })
  it('点交期仅查当天，切季度后按新的周期查任务、已确认采购与供应商明细', async () => {
    const { page } = await render()
    expect(page.findAll('.week-bars button')).toHaveLength(7)
    await page.findAll('.week-bars button')[1]!.trigger('click')
    await flushPromises()
    expect(api.items).toHaveBeenLastCalledWith(expect.objectContaining({ category: 'day', date: '2026-11-27' }), 1, expect.any(AbortSignal))
    await page.findAll('.period-toggle button')[1]!.trigger('click')
    await flushPromises()
    expect(api.activity).toHaveBeenLastCalledWith('quarter', expect.any(AbortSignal))
    for (const [i, category] of ['period_tasks', 'period_purchases'].entries()) {
      await page.findAll('.metric')[i]!.trigger('click')
      await flushPromises()
      expect(api.items).toHaveBeenLastCalledWith(expect.objectContaining({ category, period: 'quarter' }), 1, expect.any(AbortSignal))
    }
    await page.findAll('.metric')[2]!.trigger('click')
    await page.findAll('.directory button')[1]!.trigger('click')
    await flushPromises()
    expect(api.items).toHaveBeenLastCalledWith(expect.objectContaining({ category: 'supplier', period: 'quarter', supplier_id: 's2' }), 1, expect.any(AbortSignal))
  })
  it('采购额和供应商排名按币种展示，待计价及缺日期可见', async () => {
    const { page } = await render()
    expect(page.findAll('.quantities .metric-value').map(n => n.text())).toEqual(['¥1,234.5', '1,200 USD'])
    expect(page.get('.missing').text()).toContain('2 行缺确认日期')
    expect(page.findAll('.rank')).toHaveLength(1)
    expect(page.get('.rank').text()).toContain('纸箱厂')
    await page.get('select').setValue('USD')
    expect(page.get('.rank').text()).toContain('吊牌厂')
    expect(page.get('.factory-panel .totals b').text()).toBe('1 家 · 1,200 USD')
  })
  it('无查看权限与零分开；失败可重试，切换身份会关闭前一账号的明细', async () => {
    api.overview.mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce({ ...overview,
      counts: { ...overview.counts, late: null, unsent: null, past: 0 } })
    api.activity.mockResolvedValueOnce({ ...activity, amounts: [], suppliers: [], supplier_count: null, purchase_order_count: null, unpriced_count: 0, undated_count: 0 })
    api.items.mockResolvedValueOnce({ ...items, data: { columns: [], rows: [] } })
    const { page, auth } = await render()
    expect(page.get('[role=alert]').text()).toContain('加载跟单工作台失败')
    await page.get('[role=alert] button').trigger('click')
    await flushPromises()
    expect(page.findAll('.todo')[2]!.attributes('disabled')).toBeDefined()
    expect(page.findAll('.todo')[4]!.get('strong').text()).toBe('0')
    expect(page.get('.factory-panel .empty').text()).toBe('无查看权限')
    await page.findAll('.todo')[4]!.trigger('click')
    await flushPromises()
    expect(page.get('[role=dialog]').text()).toContain('当前没有符合条件的记录')
    auth.identityGeneration++
    await flushPromises()
    expect(page.find('[role=dialog]').exists()).toBe(false)
    expect(api.inbox).toHaveBeenCalledTimes(2)
    expect(page.findAll('.todo')[2]!.get('strong').text()).toBe('3')
  })
})

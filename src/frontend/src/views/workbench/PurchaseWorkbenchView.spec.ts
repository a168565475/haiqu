import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import PurchaseWorkbenchView from './PurchaseWorkbenchView.vue'
import PurchaseSpendTrend from './PurchaseSpendTrend.vue'

const service = vi.hoisted(() => ({ summary: vi.fn(), items: vi.fn(), spend: vi.fn(), unread: vi.fn() }))
vi.mock('@/api/purchaseWorkbench', () => ({
  getPurchaseWorkbench: service.summary, getPurchaseWorkbenchItems: service.items, getPurchaseWorkbenchSpend: service.spend,
}))
vi.mock('@/api/notifications', async importOriginal => ({
  ...await importOriginal<typeof import('@/api/notifications')>(), getNotificationInbox: service.unread,
}))
const counts = { unstarted: 1, shortage: 2, near_due: 1, due_today: 0, overdue: 3, late_for_use: null, missing_due: 1, bom_changed: 0 }
const supplier = (index: number) => ({ supplier_id: String(index), supplier_name: '供应商' + index, supplier_category: '面料',
  amount: String((7 - index) * 1000), order_count: 1, line_count: 1, unpriced_count: 0 })

const wrappers: ReturnType<typeof mount>[] = []
async function render() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/workbench/purchase', component: { template: '<div />' } }] })
  await router.push('/workbench/purchase')
  const wrapper = mount(PurchaseWorkbenchView, {
    global: { plugins: [createPinia(), router], stubs: { AppWindowDialog: { template: '<div><slot /></div>' }, RouterLink: RouterLinkStub,
      ElPagination: true, ElButton: { template: '<button><slot /></button>' } } },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return { wrapper, router }
}
beforeEach(() => {
  vi.clearAllMocks()
  service.summary.mockResolvedValue({ as_of: '2026-11-26', counts, missing_use_date_count: 1,
    availability_reasons: { shortage: '另有 4 项需求量待核对', late_for_use: '缺少排产材料入库日' } })
  service.spend.mockImplementation((period: string) => Promise.resolve({
    start_date: period === 'month' ? '2026-11-01' : '2026-01-01', end_date: '2026-11-26', year: 2026, period, unknown_date_count: 0,
    currencies: [{ currency: 'CNY', amount: period === 'month' ? '21000' : '40000', unpriced_count: 1, line_count: 6, order_count: 3,
      supplier_count: 6, suppliers: Array.from({ length: 6 }, (_, i) => supplier(i + 1)),
      trend: Array.from({ length: 12 }, (_, i) => ({ month: i + 1, amount: '1000', line_count: 1, unpriced_count: 0 })) }],
  }))
  service.items.mockResolvedValue({ data: [{ row_key: 'd:1', production_task_id: 'task-42', task_number: 'SC-42', material_count: 2 }],
    meta: { total: 1, page: 1, page_size: 20, total_pages: 1 } })
  service.unread.mockResolvedValue({ count: 1, data: [{ id: 'notice-1', title: '采购确认提醒', created_at: '2026-11-26T00:30:00Z' }] })
})
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()) })

describe('采购工作台', () => {
  it('整月未计价的折线留缺口，当前月提示待计价，实际零金额可绘制', () => {
    const trend = [
      { month: 1, amount: '0', line_count: 1, unpriced_count: 0 },
      { month: 2, amount: '0', line_count: 2, unpriced_count: 2 },
      { month: 3, amount: '80', line_count: 2, unpriced_count: 0 },
      { month: 4, amount: '20', line_count: 1, unpriced_count: 0 },
      { month: 5, amount: '0', line_count: 3, unpriced_count: 3 },
    ]
    const chart = mount(PurchaseSpendTrend, { props: { trend, asOf: '2026-05-16', divisor: 1, unit: '元' } })
    wrappers.push(chart)
    const segments = chart.findAll('.trend-segment')
    expect(segments).toHaveLength(2)
    expect(segments[0]!.get('circle').attributes('cy')).toBe('170')
    expect(segments[1]!.get('path[stroke]').attributes('d')).toMatch(/^M[^ML]+ L[^ML]+$/)
    expect(chart.find('circle[r="4"]').exists()).toBe(false)
    expect(chart.findAll('.trend-notes b').map(e => e.text())).toEqual(['3 月 · 80.00 元', '待计价'])
  })
  it('按岗位范围展示五项待办、真实未读和有数据的走势月份；未知不显示零', async () => {
    const { wrapper, router } = await render()
    expect(wrapper.findAll('.todo img')).toHaveLength(5)
    expect(wrapper.findAll('.todo b').map(n => n.text())).toEqual(['1', '2', '1', '0', '3'])
    expect(wrapper.get('.follow-row').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.todo-panel .reason').text()).toBe('另有 4 项需求量待核对')
    expect(wrapper.get('.sidepanel .reason').text()).toContain('缺少排产')
    expect(wrapper.get('.money-rule').text()).toContain('本岗可见普通采购')
    expect(wrapper.get('.month .periodmoney').text()).toContain('2.10')
    expect(wrapper.get('svg[role="img"]').text()).toContain('11月')
    expect(wrapper.get('svg[role="img"]').text()).not.toContain('12月')
    expect(service.unread).toHaveBeenCalledWith(1, expect.any(AbortSignal), true)
    await wrapper.get('.msgrow').trigger('click'); await flushPromises()
    expect(router.currentRoute.value.query.notification).toBe('notice-1')
  })
  it('切换周期、展开供应商，可从未下单任务查看该单所有物料', async () => {
    const { wrapper } = await render()
    expect(wrapper.findAll('.rank')).toHaveLength(5)
    await wrapper.get('.rankfoot button').trigger('click')
    expect(wrapper.findAll('.rank')).toHaveLength(6)
    await wrapper.findAll('.period-toggle button')[2]!.trigger('click')
    expect(wrapper.get('.period-toggle [aria-pressed=true]').text()).toBe('本年')
    expect(wrapper.get('.rankfoot').text()).toContain('4.00')
    expect(wrapper.findAll('.rank')).toHaveLength(5)
    await wrapper.get('.todo').trigger('click'); await flushPromises()
    expect(service.items).toHaveBeenCalledWith('unstarted', 1, expect.any(AbortSignal))
    expect(wrapper.get('tbody').text()).toContain('2 项')
    expect(wrapper.getComponent(RouterLinkStub).props('to')).toEqual({
      name: 'purchase-alerts', query: { production_task_id: 'task-42', purchase_scope: 'STANDARD' },
    })
  })
  it('未到货行优先进入有权查看的真实采购批次', async () => {
    service.items.mockResolvedValueOnce({ data: [{ row_key: 'o:5', production_task_id: 'task-42', task_number: 'SC-42',
      purchase_order_id: 'order-5', actions: [{ kind: 'view_order' }], ordered_quantity: '10', received_quantity: '2', unreceived_quantity: '8',
      ordered_root_count: null, received_root_count: null, unreceived_root_count: null, unit: '米' }], meta: { total: 1 } })
    const { wrapper } = await render()
    await wrapper.findAll('.todo')[4]!.trigger('click'); await flushPromises()
    expect(wrapper.getComponent(RouterLinkStub).props('to')).toEqual({ name: 'purchase-order-detail', params: { id: 'order-5' } })
    expect(wrapper.get('tbody').text()).toContain('尚欠 8 米')
  })
  it('加载失败清楚提示，空采购和空未读均能正常显示', async () => {
    service.summary.mockRejectedValueOnce(new Error('network'))
    service.spend.mockResolvedValue({ currencies: [], start_date: '2026-11-01', end_date: '2026-11-26', unknown_date_count: 0 })
    service.unread.mockResolvedValue({ count: 0, data: [] })
    const { wrapper } = await render()
    expect(wrapper.get('[role=alert]').text()).toContain('加载采购工作台失败')
    expect(wrapper.find('.todo').exists()).toBe(false)
    await wrapper.get('[role=alert] button').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('本期暂无供应商采购记录')
    expect(wrapper.text()).toContain('暂无未读消息')
    expect(wrapper.find('.periodmoney').text()).toContain('0.00')
  })
  it('历史采购缺少确认日时显示未知金额，避免把未归期的明细显示为零', async () => {
    service.spend.mockResolvedValue({ currencies: [], start_date: '2026-11-01', end_date: '2026-11-26', unknown_date_count: 42 })
    const { wrapper } = await render()
    expect(wrapper.findAll('.periodmoney').map(card => card.text())).toEqual(['—元', '—元', '—元'])
    expect(wrapper.text()).toContain('42 项采购明细确认日期待核对')
    expect(wrapper.text()).toContain('暂无可归期金额')
    expect(wrapper.find('.rankfoot').exists()).toBe(false)
    expect(wrapper.find('svg[role="img"]').exists()).toBe(false)
  })
})

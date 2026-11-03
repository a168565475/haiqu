import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { Button, Empty, Icon, Loading, Tag } from 'vant'

const api = vi.hoisted(() => ({ context: vi.fn(), records: vi.fn() }))
vi.mock('@/api/reporting', () => ({ fetchReportingContext: api.context, fetchWorkReports: api.records }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))
import RecordsView from './report-records.vue'

const query = { schedule_product_id: '11111111-1111-4111-8111-111111111111', workshop_id: '22222222-2222-4222-8222-222222222222', craft_id: '33333333-3333-4333-8333-333333333333', plan_category: 'METAL' }
const context = {
  schedule_product: { id: query.schedule_product_id, product_name: '测试产品', task_number: 'TASK-TEST', product_number: 'PRODUCT-TEST' },
  workshops: [{ id: query.workshop_id, name: '金工车间' }],
  crafts: [{ id: query.craft_id, workshop_id: query.workshop_id, plan_category: 'METAL', name: '加工' }], employees: [],
}
const record = {
  id: 'report-a', report_number: 'WR-TEST-1', production_date: '2026-10-31', recorder: '测试班组长', total_amount: '10.00', scheme_version: 2,
  workshop: { id: query.workshop_id, name: '金工车间' }, scope_craft: { id: query.craft_id, name: '切割加工' },
  created_at: '2026-10-31T02:30:00Z', updated_at: '2026-10-31T02:30:00Z', completed_plan: false,
  lines: [{ id: 'line', employee_name: '测试员工', operation_name: '切割', display_name: '椅脚', quantity: '10.0000', production_line: null, unit_price: '1.0000', amount: '10.00', required_quantity: '100.0000', cumulative_quantity: '50.0000' }],
}
let wrapper: VueWrapper | undefined
async function openPage(params: Record<string, string> = query) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div>任务列表</div>' } }, { path: '/report-records', component: RecordsView }, { path: '/plan', component: { template: '<div>选择工艺</div>' } }] })
  await router.push({ path: '/report-records', query: params })
  await router.isReady()
  wrapper = mount({ template: '<router-view />' }, { global: { plugins: [router], components: { VanButton: Button, VanEmpty: Empty, VanIcon: Icon, VanLoading: Loading, VanTag: Tag } } })
  await flushPromises()
  return wrapper
}
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  vi.resetAllMocks()
  api.context.mockResolvedValue(structuredClone(context))
  api.records.mockResolvedValue({ data: [structuredClone(record)], meta: { page: 1, page_size: 20, total: 21, total_pages: 2 } })
})
afterEach(async () => {
  wrapper?.unmount(); wrapper = undefined
  // Vant 导航栏仍有延迟测高任务，在 jsdom 销毁前完成它们。
  try { await vi.runOnlyPendingTimersAsync() }
  finally { vi.useRealTimers() }
})

describe('手机报工记录', () => {
  it('展示真实返回记录及可展开的员工、次数和工价快照', async () => {
    const view = await openPage()
    expect(view.text()).toContain('WR-TEST-1')
    expect(view.text()).toContain('测试员工：切割 10 次')
    await view.find('.records-expand').trigger('click')
    expect(view.text()).toContain('工价第 2 版')
    expect(view.text()).toContain('当前累计已报')
    expect(view.find('.records-expand').attributes('aria-expanded')).toBe('true')
  })
  it('工艺当前分类改变后仍按排产分类快照读取指定工艺历史', async () => {
    const changed = structuredClone(context)
    changed.crafts[0].plan_category = 'CUTTING'
    api.context.mockResolvedValueOnce(changed)
    const view = await openPage()
    expect(api.records).toHaveBeenCalledWith(query, 1, expect.any(AbortSignal))
    expect(view.text()).toContain('WR-TEST-1')
    expect(view.text()).not.toContain('生产任务范围已经变化')
  })
  it('指定工艺仍在上下文时必须属于当前车间', async () => {
    const changed = structuredClone(context)
    changed.crafts[0].workshop_id = 'other-workshop'
    api.context.mockResolvedValueOnce(changed)
    const view = await openPage()
    expect(view.text()).toContain('生产任务范围已经变化')
    expect(view.text()).not.toContain('WR-TEST-1')
  })
  it('翻页保持当前任务范围，失败时清掉旧记录并显示重试', async () => {
    const view = await openPage()
    api.records.mockRejectedValueOnce(new Error('当前账号不能查看该车间记录'))
    await view.findAllComponents(Button).find(button => button.text() === '下一页')!.trigger('click')
    await flushPromises()
    expect(api.records).toHaveBeenLastCalledWith(query, 2, expect.any(AbortSignal))
    expect(view.text()).toContain('当前账号不能查看该车间记录')
    expect(view.text()).not.toContain('WR-TEST-1')
    expect(view.text()).not.toContain('暂时没有报工记录')
  })
  it('空数据和缺失范围分别展示，不把缺参数变成全量查询', async () => {
    api.records.mockResolvedValueOnce({ data: [], meta: { page: 1, page_size: 20, total: 0, total_pages: 0 } })
    const view = await openPage()
    expect(view.text()).toContain('暂时没有报工记录')
    view.unmount(); wrapper = undefined
    api.records.mockClear()
    const invalid = await openPage({})
    expect(invalid.text()).toContain('返回任务列表重新选择')
    expect(api.records).not.toHaveBeenCalled()
  })
  it('计划入口不带工艺时展示全部工艺历史，新增返回计划明确选择工艺', async () => {
    const { craft_id: _craft, ...planQuery } = query
    const second = { ...structuredClone(record), id: 'report-b', report_number: 'WR-TEST-2', scope_craft: { id: '44444444-4444-4444-8444-444444444444', name: '焊接加工' } }
    api.records.mockResolvedValueOnce({ data: [structuredClone(record), second], meta: { page: 1, page_size: 20, total: 2, total_pages: 1 } })
    const view = await openPage(planQuery)
    expect(api.records).toHaveBeenLastCalledWith(planQuery, 1, expect.any(AbortSignal))
    expect(view.text()).toContain('本计划全部工艺')
    expect(view.text()).toContain('金工车间 · 切割加工')
    expect(view.text()).toContain('金工车间 · 焊接加工')
    await view.findAllComponents(Button).find(button => button.text() === '选择工艺并报工')!.trigger('click')
    await flushPromises()
    expect(view.vm.$router.currentRoute.value.path).toBe('/plan')
    expect(view.vm.$router.currentRoute.value.query).toEqual({ ...planQuery, action: 'report' })
  })
})

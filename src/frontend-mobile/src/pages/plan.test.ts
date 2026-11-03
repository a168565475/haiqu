import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { Button, Icon, Loading } from 'vant'
import type { MobilePlan } from '@/types/mobilePlan'
import PlanPage from './plan.vue'

const api = vi.hoisted(() => ({ fetch: vi.fn() }))
vi.mock('@/api/mobilePlans', () => ({ fetchMobilePlan: api.fetch }))
vi.mock('@/components/WorkPage.vue', () => ({ default: { template: '<div><slot /></div>' } }))
vi.mock('@/components/ProductImage.vue', () => ({ default: { template: '<div />' } }))
function plan(id: string): MobilePlan {
  return {
    key: id, schedule_product_id: id, schedule_id: 'schedule', schedule_number: 'schedule', production_task_id: 'task', product_line_id: 'product', task_number: `任务-${id}`,
    product: { name: `产品-${id}`, number: 'TEST', specification: '', color: '', material: '', quantity: '10', order_quantity: '10', unit: '件', image_url: null },
    plan_category: 'METAL', plan_category_label: '金工', workshop: { id: 'workshop', name: '金工车间' }, plan_date: null, task_status: 'ACTIVE', task_status_display: '生产中',
    can_issue: true, issue_reason: '', can_report: true, can_open_report: true, report_reason: '', can_view_issues: true, can_view_reports: true, progress: null, reporting_crafts: [],
    can_receive_finished: false, finished_receipt_reason: '',
    can_receive_semi: false, semi_receipt_reason: '',
  }
}
const query = (id: string) => ({ schedule_product_id: id, plan_category: 'METAL', workshop_id: 'workshop' })
let wrapper: VueWrapper | undefined
async function openPage() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/plan', component: PlanPage }] })
  await router.push({ path: '/plan', query: query('one') }); await router.isReady()
  wrapper = mount({ template: '<router-view />' }, { global: { plugins: [router], components: { VanButton: Button, VanIcon: Icon, VanLoading: Loading } } })
  await flushPromises()
  return router
}
beforeEach(() => { vi.resetAllMocks(); api.fetch.mockImplementation(async id => plan(id)) })
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

describe('计划详情范围刷新', () => {
  it('金工与车缝详情保留半成品入库权限和仓库确认说明', async () => {
    api.fetch.mockResolvedValue({ ...plan('one'), can_receive_semi: true })
    const router = await openPage()
    expect(wrapper!.text()).toContain('提交后由仓库确认入库。')
    expect(wrapper!.findAll('button').find(button => button.text() === '半成品入库')!.attributes('disabled')).toBeUndefined()
    api.fetch.mockResolvedValue({ ...plan('two'), plan_category: 'SEWING', semi_receipt_reason: '没有半成品入库权限' })
    await router.push({ path: '/plan', query: { ...query('two'), plan_category: 'SEWING' } }); await flushPromises()
    expect(wrapper!.text()).toContain('没有半成品入库权限')
    expect(wrapper!.findAll('button').find(button => button.text() === '半成品入库')!.attributes('disabled')).toBeDefined()
    api.fetch.mockResolvedValue({ ...plan('three'), plan_category: 'CUTTING' })
    await router.push({ path: '/plan', query: { ...query('three'), plan_category: 'CUTTING' } }); await flushPromises()
    expect(wrapper!.findAll('button').some(button => button.text() === '半成品入库')).toBe(false)
  })
  it('装配详情保留成品入库入口与仓库确认说明，权限禁用来自服务端', async () => {
    api.fetch.mockResolvedValue({ ...plan('one'), plan_category: 'ASSEMBLY', can_receive_finished: true })
    const router = await openPage()
    expect(wrapper!.text()).toContain('提交后由仓库确认入库。')
    expect(wrapper!.findAll('button').find(button => button.text() === '成品入库')!.attributes('disabled')).toBeUndefined()
    api.fetch.mockResolvedValue({ ...plan('two'), plan_category: 'ASSEMBLY', finished_receipt_reason: '没有入库权限' })
    await router.push({ path: '/plan', query: query('two') }); await flushPromises()
    expect(wrapper!.text()).toContain('没有入库权限')
    expect(wrapper!.findAll('button').find(button => button.text() === '成品入库')!.attributes('disabled')).toBeDefined()
  })
  it('同一路由换计划后读取新范围，操作入口带新计划', async () => {
    const router = await openPage()
    expect(wrapper!.text()).toContain('产品-one')
    await router.push({ path: '/plan', query: query('two') }); await flushPromises()
    expect(api.fetch).toHaveBeenLastCalledWith('two', { plan_category: 'METAL', workshop_id: 'workshop' }, expect.any(AbortSignal))
    expect(wrapper!.text()).toContain('产品-two')
    expect(wrapper!.text()).not.toContain('产品-one')
  })
  it('旧计划响应晚到也不能覆盖新计划，并取消旧请求', async () => {
    let resolveOld!: (value: MobilePlan) => void
    api.fetch.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const router = await openPage()
    const oldSignal = api.fetch.mock.calls[0]![2] as AbortSignal
    await router.push({ path: '/plan', query: query('two') }); await flushPromises()
    expect(oldSignal.aborted).toBe(true)
    expect(wrapper!.text()).toContain('产品-two')
    resolveOld(plan('one')); await flushPromises()
    expect(wrapper!.text()).toContain('产品-two')
    expect(wrapper!.text()).not.toContain('产品-one')
  })
  it('切到缺参范围时清空旧计划，旧请求失败不盖掉缺参提示', async () => {
    let rejectOld!: (error: Error) => void
    api.fetch.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectOld = reject }))
    const router = await openPage()
    await router.push({ path: '/plan', query: {} }); await flushPromises()
    rejectOld(new Error('旧计划加载失败')); await flushPromises()
    expect(wrapper!.text()).toContain('任务信息不完整')
    expect(wrapper!.text()).not.toContain('旧计划加载失败')
    expect(wrapper!.text()).not.toContain('申请领料')
  })
})

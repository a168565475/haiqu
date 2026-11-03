import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { Button, Empty, Icon, Search, Tab, Tabs } from 'vant'
import type { MobilePlan } from '@/types/mobilePlan'
import IndexPage from './index.vue'

const mocks = vi.hoisted(() => ({ context: vi.fn(), fetch: vi.fn(), push: vi.fn(), replace: vi.fn() }))
vi.mock('@/api/mobilePlans', () => ({ fetchMobileContext: mocks.context, fetchMobilePlans: mocks.fetch }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.push, replace: mocks.replace }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { display_name: '测试班组长' }, logout: vi.fn() }) }))
vi.mock('@/components/WorkPage.vue', () => ({ default: { template: '<div><slot name="header-action" /><slot /></div>' } }))
vi.mock('@/components/ProductionPlanList.vue', () => ({ default: {
  name: 'ProductionPlanList', props: ['plans', 'mode'], emits: ['open', 'issue', 'report', 'receiveFinished', 'receiveSemi'],
  template: '<div data-testid="production-plans" :data-mode="mode">{{ plans.length }} 项</div>',
} }))

function plan(id: string): MobilePlan {
  return {
    key: id, schedule_product_id: `schedule-product-${id}`, schedule_id: `schedule-${id}`, schedule_number: `SCH-${id}`,
    production_task_id: `task-${id}`, product_line_id: `product-${id}`, task_number: `SC-${id}`,
    product: { name: `产品-${id}`, number: `P-${id}`, specification: '规格', color: '蓝色', material: '钢材', quantity: '100', order_quantity: '200', unit: '件', image_url: null },
    plan_category: 'METAL', plan_category_label: '金工', workshop: { id: 'workshop-metal', name: '金工一车间' }, plan_date: '2026-11-02',
    task_status: 'ACTIVE', task_status_display: '生产中', can_issue: true, issue_reason: '', can_report: true, can_open_report: true, report_reason: '',
    can_view_issues: true, can_view_reports: true, progress: { status: 'ACTIVE', percentage: 40 },
    can_receive_finished: false, finished_receipt_reason: '',
    can_receive_semi: false, semi_receipt_reason: '',
    reporting_crafts: [{ id: 'craft-one', name: '切割', can_report: true, can_open_report: true, reason: '', progress: null }],
  }
}
const workshops = [
  { id: 'workshop-metal', name: '金工车间' },
  { id: 'workshop-sewing', name: '车缝车间' },
  { id: 'workshop-empty', name: '装配车间' },
  { id: 'workshop-eyelet', name: '敲布孔' },
]
const managementContext = () => ({ workshop_filter: { enabled: true, options: workshops, default_id: 'workshop-sewing' } })
const workshopContext = () => ({ workshop_filter: { enabled: false, options: [], default_id: null } })
const listStub = { name: 'VanList', props: ['loading', 'finished', 'error'], emits: ['load', 'update:loading'], template: '<div><slot /></div>' }
let wrapper: VueWrapper | undefined
async function openPage() {
  wrapper = mount(IndexPage, { global: {
    components: { VanButton: Button, VanEmpty: Empty, VanIcon: Icon, VanSearch: Search, VanTab: Tab, VanTabs: Tabs, VanList: listStub },
    stubs: { VanPullRefresh: { template: '<div><slot /></div>' } },
  } })
  await flushPromises()
  return wrapper
}
const child = (view: VueWrapper) => view.getComponent({ name: 'ProductionPlanList' })
async function switchMode(view: VueWrapper, name: '切换为摘要式' | '切换为清单式') {
  await view.get(`button[aria-label="${name}"]`).trigger('click')
  await flushPromises()
}
async function clickButton(view: VueWrapper, text: string) {
  const button = view.findAll('button').find(item => item.text() === text)
  expect(button).toBeDefined()
  await button!.trigger('click')
  await flushPromises()
}
async function switchCategory(view: VueWrapper, name: string) {
  const tab = view.findAll('[role="tab"]').find(item => item.text() === name)
  expect(tab).toBeDefined()
  await tab!.trigger('click')
  await flushPromises()
}
beforeEach(() => {
  vi.resetAllMocks()
  mocks.context.mockResolvedValue(managementContext())
  mocks.fetch.mockImplementation(async ({ page }) => ({ data: [plan(String(page))], meta: { page, page_size: 12, total: 36, total_pages: 3 } }))
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

describe('首页生产分类与生产计划视图切换', () => {
  it('半成品入库导航保留金工/车缝类别，拒绝其他类别与无权限入口', async () => {
    const view = await openPage()
    for (const category of ['METAL', 'SEWING']) {
      const item = { ...plan('semi'), plan_category: category, can_receive_semi: true }
      child(view).vm.$emit('receiveSemi', item)
      await flushPromises()
      expect(mocks.push).toHaveBeenLastCalledWith({ path: '/semi-receipt', query: { schedule_product_id: item.schedule_product_id, plan_category: category } })
    }
    mocks.push.mockClear()
    for (const item of [{ ...plan('semi'), can_receive_semi: false }, { ...plan('semi'), can_receive_semi: true, plan_category: 'CUTTING' }, { ...plan('semi'), can_receive_semi: true, plan_category: 'ASSEMBLY' }]) child(view).vm.$emit('receiveSemi', item)
    await flushPromises()
    expect(mocks.push).not.toHaveBeenCalled()
  })
  it('成品入库只路由至已授权装配计划，传真实排产产品 ID', async () => {
    const view = await openPage()
    const assembly = { ...plan('assembly'), plan_category: 'ASSEMBLY', can_receive_finished: true }
    child(view).vm.$emit('receiveFinished', assembly)
    await flushPromises()
    expect(mocks.push).toHaveBeenCalledWith({ path: '/finished-receipt', query: { schedule_product_id: assembly.schedule_product_id } })
    mocks.push.mockClear()
    child(view).vm.$emit('receiveFinished', { ...assembly, can_receive_finished: false })
    child(view).vm.$emit('receiveFinished', { ...assembly, plan_category: 'CUTTING' })
    await flushPromises()
    expect(mocks.push).not.toHaveBeenCalled()
  })
  it('管理账号使用 ERP 四个生产分类，默认金工，裁剪和车缝分别传稳定分类键', async () => {
    mocks.fetch.mockImplementation(async ({ plan_category }) => ({ data: plan_category === 'ASSEMBLY' ? [] : [plan('one')], meta: { page: 1, page_size: 12, total: plan_category === 'ASSEMBLY' ? 0 : 1, total_pages: 1 } }))
    const view = await openPage()
    expect(mocks.context).toHaveBeenCalledWith(expect.any(AbortSignal))
    expect(mocks.fetch).toHaveBeenLastCalledWith({ page: 1, page_size: 12, search: undefined, plan_category: 'METAL' }, expect.any(AbortSignal))
    expect(view.findAll('[role="tab"]').map(tab => tab.text())).toEqual(['金工', '裁剪', '车缝', '装配'])
    expect(view.findAll('[role="tab"]').some(tab => ['全部', '敲布孔'].includes(tab.text()))).toBe(false)
    await switchCategory(view, '裁剪')
    expect(mocks.fetch).toHaveBeenLastCalledWith({ page: 1, page_size: 12, search: undefined, plan_category: 'CUTTING' }, expect.any(AbortSignal))
    await switchCategory(view, '车缝')
    expect(mocks.fetch).toHaveBeenLastCalledWith({ page: 1, page_size: 12, search: undefined, plan_category: 'SEWING' }, expect.any(AbortSignal))
    await switchCategory(view, '装配')
    expect(mocks.fetch).toHaveBeenLastCalledWith({ page: 1, page_size: 12, search: undefined, plan_category: 'ASSEMBLY' }, expect.any(AbortSignal))
    expect(view.text()).toContain('暂无可查看的生产计划')
    expect(view.findAll('[role="tab"]')).toHaveLength(4)
    for (const [params] of mocks.fetch.mock.calls) expect(params).not.toHaveProperty('workshop_id')
  })
  it('搜索分页和刷新保留所选分类，切换视图保留搜索及已加载页且不额外请求', async () => {
    const view = await openPage()
    expect(child(view).props('mode')).toBe('list')
    await switchCategory(view, '车缝')
    const search = view.getComponent(Search)
    search.vm.$emit('update:modelValue', '椅子')
    await flushPromises()
    search.vm.$emit('search', '椅子'); await flushPromises()
    expect(mocks.fetch).toHaveBeenLastCalledWith({ page: 1, page_size: 12, search: '椅子', plan_category: 'SEWING' }, expect.any(AbortSignal))
    const contextCount = mocks.context.mock.calls.length
    view.getComponent({ name: 'VanList' }).vm.$emit('load'); await flushPromises()
    expect(mocks.fetch).toHaveBeenLastCalledWith({ page: 2, page_size: 12, search: '椅子', plan_category: 'SEWING' }, expect.any(AbortSignal))
    expect(mocks.context).toHaveBeenCalledTimes(contextCount)
    expect(child(view).props('plans')).toHaveLength(2)
    const requestCount = mocks.fetch.mock.calls.length
    await switchMode(view, '切换为摘要式')
    expect(child(view).props('mode')).toBe('summary')
    expect(search.props('modelValue')).toBe('椅子')
    expect(child(view).props('plans')).toHaveLength(2)
    expect(mocks.fetch).toHaveBeenCalledTimes(requestCount)
    expect(mocks.context).toHaveBeenCalledTimes(contextCount)
    view.getComponent({ name: 'VanList' }).vm.$emit('load'); await flushPromises()
    expect(mocks.fetch).toHaveBeenLastCalledWith({ page: 3, page_size: 12, search: '椅子', plan_category: 'SEWING' }, expect.any(AbortSignal))
    await switchMode(view, '切换为清单式')
    expect(child(view).props('mode')).toBe('list')
    expect(child(view).props('plans')).toHaveLength(3)
    expect(mocks.fetch).toHaveBeenCalledTimes(requestCount + 1)
    expect(mocks.context).toHaveBeenCalledTimes(contextCount)
    await clickButton(view, '刷新')
    expect(mocks.fetch).toHaveBeenLastCalledWith({ page: 1, page_size: 12, search: '椅子', plan_category: 'SEWING' }, expect.any(AbortSignal))
    expect(mocks.context).toHaveBeenCalledTimes(contextCount + 1)
    expect(child(view).props('plans')).toHaveLength(1)
  })
  it('车间账号不显示选项卡和车间筛选，合并后端返回的授权任务', async () => {
    mocks.context.mockResolvedValue(workshopContext())
    const metal = plan('metal')
    const sewing = { ...plan('sewing'), plan_category: 'SEWING', plan_category_label: '车缝', workshop: { id: 'workshop-sewing', name: '车缝车间' } }
    mocks.fetch.mockResolvedValue({ data: [metal, sewing], meta: { page: 1, page_size: 12, total: 2, total_pages: 1 } })
    const view = await openPage()
    expect(view.find('[role="tablist"]').exists()).toBe(false)
    expect(mocks.fetch.mock.calls[0]![0]).not.toHaveProperty('workshop_id')
    expect(mocks.fetch.mock.calls[0]![0]).not.toHaveProperty('plan_category')
    expect(child(view).props('plans')).toEqual([metal, sewing])
    await switchMode(view, '切换为摘要式')
    expect(child(view).props('plans')).toEqual([metal, sewing])
    expect(mocks.fetch).toHaveBeenCalledTimes(1)
    expect(mocks.context).toHaveBeenCalledTimes(1)
  })
  it('管理账号的分类选项不依赖车间字典或当前计划，空列表仍保留四个分类', async () => {
    mocks.context.mockResolvedValue({ workshop_filter: { enabled: true, options: [], default_id: null } })
    mocks.fetch.mockResolvedValue({ data: [], meta: { page: 1, page_size: 12, total: 0, total_pages: 0 } })
    const view = await openPage()
    expect(view.findAll('[role="tab"]').map(tab => tab.text())).toEqual(['金工', '裁剪', '车缝', '装配'])
    expect(mocks.fetch.mock.calls[0]![0]).not.toHaveProperty('workshop_id')
    expect(mocks.fetch.mock.calls[0]![0].plan_category).toBe('METAL')
    expect(child(view).props('plans')).toEqual([])
    expect(view.text()).toContain('暂无可查看的生产计划')
  })
  it('上下文读取失败不请求计划，错误下仍可切换视图并重新加载', async () => {
    mocks.context.mockRejectedValueOnce(new Error('车间范围读取失败'))
    const view = await openPage()
    expect(mocks.fetch).not.toHaveBeenCalled()
    expect(view.get('[role="alert"]').text()).toContain('车间范围读取失败')
    await switchMode(view, '切换为摘要式')
    expect(mocks.context).toHaveBeenCalledTimes(1)
    expect(mocks.fetch).not.toHaveBeenCalled()
    await clickButton(view, '重新加载')
    expect(mocks.context).toHaveBeenCalledTimes(2)
    expect(mocks.fetch).toHaveBeenCalledTimes(1)
    expect(view.find('[role="alert"]').exists()).toBe(false)
    expect(child(view).props('mode')).toBe('summary')
  })
  it('刷新重新读取权限范围，管理权限收紧后清除旧分类选择并合并授权范围', async () => {
    const view = await openPage()
    await switchCategory(view, '车缝')
    expect(mocks.fetch.mock.calls.at(-1)![0].plan_category).toBe('SEWING')
    const contextCount = mocks.context.mock.calls.length
    mocks.context.mockResolvedValue(workshopContext())
    await clickButton(view, '刷新')
    expect(mocks.context).toHaveBeenCalledTimes(contextCount + 1)
    expect(view.find('[role="tablist"]').exists()).toBe(false)
    expect(mocks.fetch).toHaveBeenLastCalledWith({ page: 1, page_size: 12, search: undefined }, expect.any(AbortSignal))
    expect(mocks.fetch.mock.calls.at(-1)![0]).not.toHaveProperty('workshop_id')
    expect(mocks.fetch.mock.calls.at(-1)![0]).not.toHaveProperty('plan_category')
    expect(child(view).props('plans')).toHaveLength(1)
  })
  it('空列表仍可切换视图，不把切换当作刷新', async () => {
    mocks.fetch.mockResolvedValue({ data: [], meta: { page: 1, page_size: 12, total: 0, total_pages: 0 } })
    const view = await openPage()
    expect(view.text()).toContain('暂无可查看的生产计划')
    await switchMode(view, '切换为摘要式')
    expect(view.find('button[aria-label="切换为清单式"]').exists()).toBe(true)
    expect(view.text()).toContain('暂无可查看的生产计划')
    expect(mocks.fetch).toHaveBeenCalledTimes(1)
    view.getComponent(Search).vm.$emit('update:modelValue', '不存在的产品'); await flushPromises()
    view.getComponent(Search).vm.$emit('search', '不存在的产品'); await flushPromises()
    expect(view.text()).toContain('没有找到相关计划')
    expect(view.text()).toContain('试试其他生产单号或产品。')
    expect(view.text()).not.toContain('车间类型')
  })
  it('加载错误时仍可切换，保留错误和重新加载入口', async () => {
    mocks.fetch.mockRejectedValue(new Error('测试网络故障'))
    const view = await openPage()
    await switchMode(view, '切换为摘要式')
    expect(view.get('[role="alert"]').text()).toContain('测试网络故障')
    expect(view.text()).toContain('重新加载')
    expect(view.find('button[aria-label="切换为清单式"]').exists()).toBe(true)
    expect(mocks.fetch).toHaveBeenCalledTimes(1)
  })
  it('两个视图都使用所点计划的完整范围导航，单工艺与多工艺报工入口保持原规则', async () => {
    const view = await openPage()
    for (const mode of ['list', 'summary']) {
      if (mode === 'summary') await switchMode(view, '切换为摘要式')
      const selected = mode === 'list' ? plan('metal') : { ...plan('sewing'), plan_category: 'SEWING', plan_category_label: '车缝', workshop: { id: 'workshop-sewing', name: '车缝车间' } }
      const expectedQuery = { schedule_product_id: selected.schedule_product_id, production_task_id: selected.production_task_id, product_line_id: selected.product_line_id, plan_category: selected.plan_category, workshop_id: selected.workshop.id }
      child(view).vm.$emit('open', selected)
      expect(mocks.push).toHaveBeenLastCalledWith({ path: '/plan', query: expectedQuery })
      child(view).vm.$emit('issue', selected)
      expect(mocks.push).toHaveBeenLastCalledWith({ path: '/issue', query: expectedQuery })
      child(view).vm.$emit('report', selected)
      expect(mocks.push).toHaveBeenLastCalledWith({ path: '/report', query: { ...expectedQuery, craft_id: 'craft-one' } })
      child(view).vm.$emit('report', { ...selected, reporting_crafts: [...selected.reporting_crafts, { ...selected.reporting_crafts[0]!, id: 'craft-two' }] })
      expect(mocks.push).toHaveBeenLastCalledWith({ path: '/plan', query: { ...expectedQuery, action: 'report' } })
    }
  })
})

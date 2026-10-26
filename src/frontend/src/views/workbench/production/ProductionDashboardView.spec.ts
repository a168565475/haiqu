import { createPinia } from 'pinia'
import { flushPromises, mount, RouterLinkStub, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ProductionDashboardPayload } from '@/types/productionDashboard'
import ProductionDashboardView from './ProductionDashboardView.vue'

type RouterLinkWrapper = VueWrapper<InstanceType<typeof RouterLinkStub>>

const { fetchDashboard } = vi.hoisted(() => ({ fetchDashboard: vi.fn() }))
vi.mock('@/api/productionDashboard', () => ({ fetchProductionDashboard: fetchDashboard }))

function payload(): ProductionDashboardPayload {
  return {
    generated_at: '2026-10-17T04:00:00Z',
    filters: { q: '', days: 7, status: 'ALL', focus: 'ALL', workshop: 'METAL', production_date: '2026-10-17', task_date: null, task_page: 1 },
    sections: {
      tasks: { state: 'READY', reason: '', data: {
        counts: { total: 24, overdue: 2, due_soon: 4, unscheduled: 1, completed: 3, paused: 1 },
        status_distribution: [{ status: 'IN_PRODUCTION', label: '生产中', count: 24 }],
        due_series: [{ date: '2026-10-18', count: 4 }],
        items: [{ id: 'task-1', task_number: 'SC-TEST-001', customer_name: '测试客户', delivery_date: '2026-10-16', days_to_due: -1, status: 'IN_PRODUCTION', status_display: '生产中', priority: 'NORMAL', products: [{ id: 'p-1', name: '测试产品', quantity: '120', unit: '把' }, { id: 'p-2', name: '另一产品', quantity: '40', unit: '张' }], schedule_id: 'schedule-1', href: '/production-tasks/task-1', stages: { metal: { state: 'READY', percent: 60, label: '60%' }, sewing: { state: 'NOT_CONFIGURED', percent: null, label: '待配置工价' }, assembly: { state: 'READY', percent: 0, label: '0%' } } }], total: 24, truncated: true,
      } },
      outsourcing: { state: 'FORBIDDEN', reason: '没有委外查看权限', data: null },
      receipts: { state: 'EMPTY', reason: '', data: { pending_state: 'EMPTY', today_count: 0, today_quantities: [], pending_products: [], items: [], total: 0, truncated: false } },
      workshop: { state: 'READY', reason: '', data: { category: 'METAL', plan_count: 1, items: [{ key: 'job-1', schedule_id: 'schedule-1', task_number: 'SC-TEST-001', name: '测试产品', craft_name: '弯管', unit: '支', plan_date: '2026-10-17', status: 'IN_PROGRESS', required: '240', cumulative: '100', today: '20', remaining: '140', progress: { state: 'READY', percent: 41.67, label: '41.67%' }, href: '/workshop/scheduling/schedule-1' }], total: 1, truncated: false } },
      reports: { state: 'EMPTY', reason: '', data: { date: '2026-10-17', report_count: 0, employee_count: 0, items: [], total: 0, truncated: false } },
    },
  }
}

const wrappers: ReturnType<typeof mount>[] = []
function render(role: 'owner' | 'executive' | 'workshop' = 'owner') {
  const wrapper = mount(ProductionDashboardView, {
    props: { role },
    global: { plugins: [createPinia()], stubs: { RouterLink: RouterLinkStub, AppWindowDialog: { props: ['modelValue'], template: '<section v-if="modelValue"><slot /><slot name="footer" /></section>' } } },
  })
  wrappers.push(wrapper)
  return wrapper
}

async function expandModule(wrapper: ReturnType<typeof mount>, key: string) {
  const button = wrapper.find(`[data-module="${key}"] [data-module-open]`)
  if (button.exists()) await button.trigger('click')
  await flushPromises()
}
beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-17T04:00:00Z'))
  fetchDashboard.mockReset().mockResolvedValue(payload())
})

afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('生产工作台真实数据和状态', () => {
  it('负责人展开后显示已加载任务，缩略切换和收起保留业务链接及权限说明', async () => {
    const result = payload()
    const task = result.sections.tasks.data!.items[0]!
    result.sections.tasks.data!.items = Array.from({ length: 7 }, (_, index) => ({ ...task, id: `task-${index + 1}`, task_number: `SC-TEST-${index + 1}`, href: `/production-tasks/task-${index + 1}` }))
    fetchDashboard.mockResolvedValueOnce(result)
    const wrapper = render('owner')
    await flushPromises()
    const layout = wrapper.get('[data-testid="production-module-layout"]')
    const original = layout.findAll('[data-module]').map(module => module.element)
    expect(original).toHaveLength(4)
    expect(wrapper.findAll('.pd-task-table tbody tr')).toHaveLength(5)
    await expandModule(wrapper, 'production')
    expect(layout.attributes('data-active-module')).toBe('production')
    expect(wrapper.findAll('.pd-task-table tbody tr')).toHaveLength(7)
    expect(wrapper.get('[data-module="production"]').text()).toContain('展示 7 / 24 单')
    expect(wrapper.get('[data-module="production"]').findAllComponents(RouterLinkStub).some((link: RouterLinkWrapper) => link.props('to') === '/production-tasks/task-7')).toBe(true)
    await expandModule(wrapper, 'outsourcing')
    expect(layout.attributes('data-active-module')).toBe('outsourcing')
    expect(wrapper.get('[data-module="outsourcing"]').text()).toContain('没有委外查看权限')
    expect(layout.findAll('.is-mini')).toHaveLength(3)
    await wrapper.get('[data-module-close]').trigger('click')
    await flushPromises()
    expect(layout.attributes('data-active-module')).toBe('overview')
    expect(wrapper.findAll('.pd-task-table tbody tr')).toHaveLength(5)
    expect(layout.findAll('[data-module]').map(module => module.element)).toEqual(original)
    expect(fetchDashboard).toHaveBeenCalledTimes(1)
  })

  it('负责人委外指标直接展开待回货明细，未知回货量保留原因', async () => {
    const result = payload()
    result.sections.outsourcing = { state: 'READY', reason: '', data: { pending_count: 1, overdue_count: 0, total: 1, truncated: false, items: [{ id: 'out-1', row_key: 'TUBE:out-1', order_number: 'WW-TEST-1', delivery_date: null, status: 'DISPATCHED', status_display: '已发出', factory_names: ['测试加工厂'], quantities: [], receipt_state: 'UNKNOWN', href: '/workshop/outsourcing/tube/out-1' }] } }
    fetchDashboard.mockResolvedValueOnce(result)
    const wrapper = render('owner')
    await flushPromises()
    await wrapper.get('[data-testid="production-metric-outsourcing"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="production-module-layout"]').attributes('data-active-module')).toBe('outsourcing')
    const module = wrapper.get('[data-module="outsourcing"]')
    expect(module.text()).toContain('回货数量待核实')
    expect(module.text()).not.toContain('已回货：0')
    expect(module.findAllComponents(RouterLinkStub).some((link: RouterLinkWrapper) => link.props('to') === '/workshop/outsourcing/tube/out-1')).toBe(true)
    expect(fetchDashboard).toHaveBeenCalledTimes(1)
  })

  it('车间详情显示全部已加载记录，工序切换后仍按报工和入库分别统计', async () => {
    const result = payload()
    const job = result.sections.workshop.data!.items[0]!
    result.sections.workshop.data!.items = Array.from({ length: 4 }, (_, index) => ({ ...job, key: `job-${index + 1}`, href: `/workshop/scheduling/schedule-${index + 1}` }))
    result.sections.workshop.data!.total = 4
    result.sections.reports = { state: 'READY', reason: '', data: { date: '2026-10-17', report_count: 6, employee_count: 2, total: 6, truncated: false, items: Array.from({ length: 6 }, (_, index) => ({ id: `report-${index + 1}`, number: `BG-TEST-${index + 1}`, task_number: 'SC-TEST-001', workshop_name: '金工车间', production_date: '2026-10-17', lines: [{ operation: '弯管', quantity: '20', unit: '支' }], href: `/workshop/work-reports/report-${index + 1}` })) } }
    fetchDashboard.mockResolvedValue(result)
    const wrapper = render('workshop')
    await flushPromises()
    expect(wrapper.findAll('.pd-job')).toHaveLength(3)
    expect(wrapper.get('[data-module="output"]').findAll('.pd-report')).toHaveLength(5)
    await expandModule(wrapper, 'production')
    expect(wrapper.findAll('.pd-job')).toHaveLength(4)
    expect(wrapper.get('[data-module="production"]').findAllComponents(RouterLinkStub).some((link: RouterLinkWrapper) => link.props('to') === '/workshop/scheduling/schedule-4')).toBe(true)
    await expandModule(wrapper, 'output')
    expect(wrapper.get('[data-module="output"]').findAll('.pd-report')).toHaveLength(6)
    expect(wrapper.get('[data-module="output"]').text()).toContain('弯管 20 支')

    const assembly = payload()
    assembly.filters.workshop = 'ASSEMBLY'
    assembly.sections.workshop.data!.category = 'ASSEMBLY'
    assembly.sections.receipts = { state: 'READY', reason: '', data: { pending_state: 'EMPTY', today_count: 6, today_quantities: [{ quantity: '60', unit: '把' }], pending_products: [], total: 6, truncated: false, items: Array.from({ length: 6 }, (_, index) => ({ id: `receipt-${index + 1}`, number: `RK-TEST-${index + 1}`, date: '2026-10-17', name: '入库产品', quantity: '10', unit: '把', href: `/inventory/finished-goods/receipt-${index + 1}` })) } }
    fetchDashboard.mockResolvedValueOnce(assembly)
    await wrapper.get('[data-testid="production-process-ASSEMBLY"]').trigger('click')
    await flushPromises()
    expect(fetchDashboard.mock.calls.at(-1)?.[0]).toMatchObject({ workshop: 'ASSEMBLY' })
    await expandModule(wrapper, 'output')
    const output = wrapper.get('[data-module="output"]')
    expect(output.text()).toContain('当日成品入库记录')
    expect(output.findAll('.pd-report')).toHaveLength(6)
    expect(output.text()).toContain('10 把')
    expect(output.text()).not.toContain('BG-TEST-')
    expect(output.text()).not.toContain('弯管 20 支')
    expect(output.findAllComponents(RouterLinkStub).some((link: RouterLinkWrapper) => link.props('to') === '/inventory/finished-goods/receipt-6')).toBe(true)
  })

  it('总览五模块原位展开、切换和Esc归位，保留模块DOM与权限原因', async () => {
    const wrapper = render('executive')
    await flushPromises()
    const original = wrapper.findAll('.po-module').map(module => module.element)
    expect(original).toHaveLength(5)
    await expandModule(wrapper, 'production')
    expect(wrapper.findAll('.is-mini')).toHaveLength(4)
    expect(wrapper.get('[data-module="production"]').text()).toContain('待配置工价')
    await expandModule(wrapper, 'outsourcing')
    expect(wrapper.get('[data-module="outsourcing"]').text()).toContain('没有委外查看权限')
    expect(wrapper.get('[data-module="outsourcing"]').text()).not.toContain('0 单待回')
    await wrapper.get('[data-module-close]').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(wrapper.get('[data-testid="production-overview"]').attributes('data-active-module')).toBe('overview')
    expect(wrapper.findAll('.po-module').map(module => module.element)).toEqual(original)
  })

  it('上海业务日期跨日时外发明细仍与逾期汇总一致', async () => {
    const result = payload()
    result.generated_at = '2026-10-17T17:00:00Z'
    result.sections.outsourcing = { state: 'READY', reason: '', data: { pending_count: 1, overdue_count: 1, total: 1, truncated: false, items: [{ id: 'out-1', row_key: 'TUBE:out-1', order_number: 'WW-TEST-1', delivery_date: '2026-10-17', status: 'DISPATCHED', status_display: '已发出', factory_names: ['加工厂'], quantities: [], receipt_state: 'UNKNOWN', href: '/workshop/outsourcing/tube/out-1' }] } }
    fetchDashboard.mockResolvedValueOnce(result)
    const wrapper = render('executive')
    await flushPromises()
    expect(wrapper.get('[data-module="outsourcing"]').text()).toContain('回货已逾期')
  })

  it('总览跨上海零点刷新时今日入库日期同步更新', async () => {
    const wrapper = render('executive')
    await flushPromises()
    vi.setSystemTime(new Date('2026-10-17T16:01:00Z'))
    await wrapper.get('[data-testid="production-refresh"]').trigger('click')
    await flushPromises()
    expect(fetchDashboard.mock.calls.at(-1)?.[0]).toMatchObject({ production_date: '2026-10-18' })
  })

  it('无排产权限的空schedule_id不被解释为尚未排产', async () => {
    const result = payload()
    const task = result.sections.tasks.data!.items[0]!
    task.schedule_id = null
    for (const stage of Object.values(task.stages)) Object.assign(stage, { state: 'FORBIDDEN', percent: null, label: '无排产读取权限' })
    fetchDashboard.mockResolvedValueOnce(result)
    const wrapper = render('executive')
    await flushPromises()
    await expandModule(wrapper, 'production')
    expect(wrapper.get('[data-module="production"]').text()).toContain('无排产读取权限')
    expect(wrapper.get('[data-module="production"]').text()).not.toContain('尚未排产')
  })

  it('全空范围仍保留五个可展开模块，不借用示例数字', async () => {
    const result = payload()
    for (const section of Object.values(result.sections)) { section.state = 'EMPTY'; section.data = null }
    fetchDashboard.mockResolvedValueOnce(result)
    const wrapper = render('executive')
    await flushPromises()
    expect(wrapper.attributes('data-state')).toBe('empty')
    expect(wrapper.findAll('.po-module')).toHaveLength(5)
    await expandModule(wrapper, 'production')
    expect(wrapper.get('[data-module="production"]').text()).toContain('当前范围没有生产任务')
    expect(wrapper.text()).not.toContain('示例')
  })

  it('先加载后展示真实分区，保留单位和未知原因，并说明列表截断', async () => {
    const wrapper = render()
    expect(wrapper.attributes('data-state')).toBe('loading')
    await flushPromises()
    expect(wrapper.attributes('data-state')).toBe('ready')
    expect(wrapper.text()).toContain('测试产品')
    expect(wrapper.text()).toContain('120 把')
    expect(wrapper.text()).toContain('40 张')
    expect(wrapper.text()).toContain('待配置工价')
    expect(wrapper.text()).toContain('展示 1 / 24 单')
    expect(wrapper.get('[data-testid="production-metric-outsourcing"]').text()).toContain('—')
    expect(wrapper.text()).not.toContain('演示数据')
  })

  it('筛选在应用后请求，重置恢复7天和全部状态', async () => {
    const wrapper = render()
    await flushPromises()
    await wrapper.get('input[aria-label="查找任务"]').setValue('SC-001')
    await wrapper.get('select[aria-label="交期范围"]').setValue('3')
    expect(fetchDashboard).toHaveBeenCalledTimes(1)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(fetchDashboard.mock.calls.at(-1)?.[0]).toMatchObject({ q: 'SC-001', days: 3, status: 'ALL' })
    await wrapper.get('[data-testid="production-reset"]').trigger('click')
    await flushPromises()
    expect(fetchDashboard.mock.calls.at(-1)?.[0]).toMatchObject({ q: '', days: 7, status: 'ALL', focus: 'ALL' })
  })

  it('刷新失败保留旧快照并明确过期，403随后清除敏感数据', async () => {
    const wrapper = render()
    await flushPromises()
    fetchDashboard.mockRejectedValueOnce(new Error('network failed'))
    await wrapper.get('[data-testid="production-refresh"]').trigger('click')
    await flushPromises()
    expect(wrapper.attributes('data-state')).toBe('stale')
    expect(wrapper.text()).toContain('测试产品')
    expect(wrapper.text()).toContain('上次快照')
    fetchDashboard.mockRejectedValueOnce({ response: { status: 403 } })
    await wrapper.get('[data-testid="production-refresh"]').trigger('click')
    await flushPromises()
    expect(wrapper.attributes('data-state')).toBe('forbidden')
    expect(wrapper.text()).not.toContain('测试产品')
    expect(wrapper.text()).not.toContain('SC-TEST-001')
  })

  it('超过5分钟显示过期，未发起自动网络刷新', async () => {
    const wrapper = render()
    await flushPromises()
    await vi.advanceTimersByTimeAsync(301_000)
    expect(wrapper.attributes('data-state')).toBe('stale')
    expect(wrapper.text()).toContain('数据已过期')
    expect(fetchDashboard).toHaveBeenCalledTimes(1)
  })

  it('较早查询迟到时不覆盖最新筛选的结果', async () => {
    let finishEarlier!: (value: ProductionDashboardPayload) => void
    fetchDashboard.mockImplementationOnce(() => new Promise(resolve => { finishEarlier = resolve }))
    const wrapper = render()
    await wrapper.get('input[aria-label="查找任务"]').setValue('最新')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const earlier = payload()
    earlier.sections.tasks.data!.items[0]!.products[0]!.name = '旧请求内容'
    finishEarlier(earlier)
    await flushPromises()
    expect(wrapper.text()).not.toContain('旧请求内容')
    expect(wrapper.text()).toContain('测试产品')
  })

  it('装配视角请求ASSEMBLY并使用成品入库标签', async () => {
    const wrapper = render('workshop')
    await flushPromises()
    await wrapper.get('[data-testid="production-process-ASSEMBLY"]').trigger('click')
    await flushPromises()
    expect(fetchDashboard.mock.calls.at(-1)?.[0]).toMatchObject({ workshop: 'ASSEMBLY' })
    expect(wrapper.text()).toContain('当日成品入库记录')
    expect(wrapper.text()).not.toContain('当日报工记录')
    expect(wrapper.text()).not.toContain('装配报工')
  })

  it('所有分区无权时不显示统计零，首次请求失败可重试', async () => {
    fetchDashboard.mockRejectedValueOnce(new Error('offline'))
    const wrapper = render()
    await flushPromises()
    expect(wrapper.attributes('data-state')).toBe('error')
    const forbidden = payload()
    for (const section of Object.values(forbidden.sections)) { section.state = 'FORBIDDEN'; section.data = null }
    fetchDashboard.mockResolvedValueOnce(forbidden)
    await wrapper.get('[data-testid="production-retry"]').trigger('click')
    await flushPromises()
    expect(wrapper.attributes('data-state')).toBe('forbidden')
    expect(wrapper.find('[data-testid="production-metric-overdue"]').exists()).toBe(false)
  })

  it('库存可读但任务不可读时，入库差额说明权限限制', async () => {
    const limited = payload()
    limited.sections.receipts.state = 'READY'
    limited.sections.receipts.data!.pending_state = 'FORBIDDEN'
    fetchDashboard.mockResolvedValueOnce(limited)
    const wrapper = render('executive')
    await flushPromises()
    await expandModule(wrapper, 'output')
    expect(wrapper.get('[data-testid="production-receipt-gaps"]').text()).toContain('没有查看入库差额所需的任务权限')
    expect(wrapper.get('[data-testid="production-receipt-gaps"]').text()).not.toContain('暂无成品入库差额')
  })

  it('委外数量标明已回货，不与发出原料相减', async () => {
    const result = payload()
    result.sections.outsourcing = { state: 'READY', reason: '', data: { pending_count: 1, overdue_count: 0, total: 1, truncated: false, items: [{ id: 'out-1', row_key: 'TUBE:out-1', order_number: 'WW-TEST-1', delivery_date: null, status: 'DISPATCHED', status_display: '已发出', factory_names: ['测试加工厂'], quantities: [{ quantity: '60', unit: '套', name: '测试裁片' }], receipt_state: 'READY', href: '/workshop/outsourcing/tube/out-1' }] } }
    fetchDashboard.mockResolvedValueOnce(result)
    const wrapper = render()
    await flushPromises()
    expect(wrapper.get('[data-module="outsourcing"]').text()).toContain('已回货：测试裁片 60 套')
  })

  it('外部或脚本地址不会成为任务链接', async () => {
    const unsafe = payload()
    unsafe.sections.tasks.data!.items[0]!.href = 'javascript:alert(1)'
    fetchDashboard.mockResolvedValueOnce(unsafe)
    const wrapper = render()
    await flushPromises()
    expect(wrapper.text()).toContain('测试产品')
    expect(wrapper.findAllComponents(RouterLinkStub).some(link => link.props('to') === 'javascript:alert(1)')).toBe(false)
  })

  it('无执行记录的任务明确显示状态待核实，不推断正在执行', async () => {
    const result = payload()
    result.sections.workshop.data!.items[0]!.status = 'UNKNOWN'
    fetchDashboard.mockResolvedValueOnce(result)
    const wrapper = render('workshop')
    await flushPromises()
    expect(wrapper.get('.pd-job').text()).toContain('状态待核实')
    expect(wrapper.get('.pd-job').text()).not.toContain('执行中')
  })

  it('入库单位口径异常时不显示虚假剩余量', async () => {
    const result = payload()
    result.sections.receipts.state = 'READY'
    result.sections.receipts.data!.pending_state = 'UNKNOWN'
    result.sections.receipts.data!.pending_products = [{ product_line_id: 'p-1', task_number: 'SC-TEST-001', name: '测试产品', unit: '把', required: '120', received: null, remaining: null, href: '/production-tasks/task-1', state: 'UNKNOWN' }]
    fetchDashboard.mockResolvedValueOnce(result)
    const wrapper = render('executive')
    await flushPromises()
    await expandModule(wrapper, 'output')
    const region = wrapper.get('[data-testid="production-receipt-gaps"]')
    expect(region.text()).toContain('数量与单位口径待核实')
    expect(region.text()).not.toContain('0 把')
  })

  it('全屏成功后禁用卡片动效，浏览器退出全屏时恢复常规视图', async () => {
    const wrapper = render('workshop')
    await flushPromises()
    let active: Element | null = null
    const previous = Object.getOwnPropertyDescriptor(document, 'fullscreenElement')
    Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => active })
    const element = wrapper.element as HTMLElement
    element.requestFullscreen = async () => { active = element; document.dispatchEvent(new Event('fullscreenchange')) }
    try {
      await wrapper.get('[data-testid="production-fullscreen"]').trigger('click')
      await flushPromises()
      expect(wrapper.classes()).toContain('is-fullscreen')
      expect(wrapper.get('[data-testid="production-fullscreen"]').text()).toBe('退出全屏')
      active = null
      document.dispatchEvent(new Event('fullscreenchange'))
      await flushPromises()
      expect(wrapper.classes()).not.toContain('is-fullscreen')
    } finally {
      active = null
      if (previous) Object.defineProperty(document, 'fullscreenElement', previous)
      else Reflect.deleteProperty(document, 'fullscreenElement')
    }
  })

  it('点击日期柱独立查询完整日期明细并翻页，主页面摘要保持不变', async () => {
    const wrapper = render('executive')
    await flushPromises()
    const first = payload()
    first.sections.tasks.data!.total = 40
    first.sections.tasks.data!.items[0]!.products[0]!.name = '日期明细第一页'
    fetchDashboard.mockResolvedValueOnce(first)
    await expandModule(wrapper, 'delivery')
    await wrapper.get('.pd-chart__bar').trigger('click')
    await flushPromises()
    expect(fetchDashboard.mock.calls.at(-1)?.[0]).toMatchObject({ task_date: '2026-10-18', task_page: 1, focus: 'ALL' })
    const dialog = wrapper.get('[data-testid="production-due-dialog"]')
    expect(dialog.text()).toContain('日期明细第一页')
    expect(dialog.text()).toContain('共 40 单')
    const second = payload()
    second.sections.tasks.data!.total = 40
    second.sections.tasks.data!.items[0]!.products[0]!.name = '日期明细第二页'
    fetchDashboard.mockResolvedValueOnce(second)
    await wrapper.get('[data-testid="production-due-next"]').trigger('click')
    await flushPromises()
    expect(fetchDashboard.mock.calls.at(-1)?.[0]).toMatchObject({ task_date: '2026-10-18', task_page: 2 })
    expect(dialog.text()).toContain('日期明细第二页')
    expect(dialog.text()).not.toContain('日期明细第一页')
    expect(wrapper.get('[data-module="production"]').text()).toContain('24')
  })

  it('筛选或角色变化关闭日期弹窗并忽略迟到的明细响应', async () => {
    const wrapper = render('executive')
    await flushPromises()
    let finishDate!: (value: ProductionDashboardPayload) => void
    fetchDashboard.mockImplementationOnce(() => new Promise(resolve => { finishDate = resolve }))
    await expandModule(wrapper, 'delivery')
    await wrapper.get('.pd-chart__bar').trigger('click')
    const dateSignal = fetchDashboard.mock.calls.at(-1)?.[1] as AbortSignal
    expect(wrapper.get('[data-testid="production-due-dialog"]').attributes('data-state')).toBe('loading')
    expect(wrapper.get('[data-testid="production-due-dialog"]').text()).not.toContain('共 0 单')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(dateSignal.aborted).toBe(true)
    expect(wrapper.find('[data-testid="production-due-dialog"]').exists()).toBe(false)
    finishDate(payload())
    await flushPromises()
    expect(wrapper.find('[data-testid="production-due-dialog"]').exists()).toBe(false)
    await expandModule(wrapper, 'delivery')
    await wrapper.get('.pd-chart__bar').trigger('click')
    await flushPromises()
    await wrapper.setProps({ role: 'owner' })
    await flushPromises()
    expect(wrapper.find('[data-testid="production-due-dialog"]').exists()).toBe(false)
  })

  it('主请求403关闭弹窗并阻止迟到明细重新显示', async () => {
    const wrapper = render('executive')
    await flushPromises()
    let finishDate!: (value: ProductionDashboardPayload) => void
    fetchDashboard.mockImplementationOnce(() => new Promise(resolve => { finishDate = resolve }))
    await expandModule(wrapper, 'delivery')
    await wrapper.get('.pd-chart__bar').trigger('click')
    const dateSignal = fetchDashboard.mock.calls.at(-1)?.[1] as AbortSignal
    fetchDashboard.mockRejectedValueOnce({ response: { status: 403 } })
    await wrapper.get('[data-testid="production-refresh"]').trigger('click')
    await flushPromises()
    expect(wrapper.attributes('data-state')).toBe('forbidden')
    expect(wrapper.find('[data-testid="production-due-dialog"]').exists()).toBe(false)
    expect(dateSignal.aborted).toBe(true)
    finishDate(payload())
    await flushPromises()
    expect(wrapper.text()).not.toContain('SC-TEST-001')
  })

  it('日期明细请求403清除主快照与弹窗，并阻止并行刷新恢复敏感数据', async () => {
    const wrapper = render('executive')
    await flushPromises()
    const first = payload()
    first.sections.tasks.data!.total = 40
    fetchDashboard.mockResolvedValueOnce(first)
    await expandModule(wrapper, 'delivery')
    await wrapper.get('.pd-chart__bar').trigger('click')
    await flushPromises()
    let finishRefresh!: (value: ProductionDashboardPayload) => void
    fetchDashboard.mockImplementationOnce(() => new Promise(resolve => { finishRefresh = resolve }))
    await wrapper.get('[data-testid="production-refresh"]').trigger('click')
    const refreshSignal = fetchDashboard.mock.calls.at(-1)?.[1] as AbortSignal
    fetchDashboard.mockRejectedValueOnce({ response: { status: 403 } })
    await wrapper.get('[data-testid="production-due-next"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="production-due-dialog"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('SC-TEST-001')
    expect(wrapper.attributes('data-state')).toBe('forbidden')
    expect(refreshSignal.aborted).toBe(true)
    finishRefresh(payload())
    await flushPromises()
    expect(wrapper.attributes('data-state')).toBe('forbidden')
    expect(wrapper.text()).not.toContain('SC-TEST-001')
  })

  it('日期响应撤销任务权限时清主任务及入库差额，保留获准区域并阻止旧刷新恢复', async () => {
    const original = payload()
    original.sections.receipts.state = 'READY'
    original.sections.receipts.data!.pending_state = 'READY'
    original.sections.receipts.data!.pending_products = [{ product_line_id: 'p-1', task_number: 'SC-TEST-001', name: '待清除的入库差额', unit: '把', required: '120', received: '20', remaining: '100', href: '/production-tasks/task-1', state: 'READY' }]
    fetchDashboard.mockResolvedValueOnce(original)
    const wrapper = render('executive')
    await flushPromises()
    await expandModule(wrapper, 'output')
    expect(wrapper.text()).toContain('待清除的入库差额')
    let finishRefresh!: (value: ProductionDashboardPayload) => void
    fetchDashboard.mockImplementationOnce(() => new Promise(resolve => { finishRefresh = resolve }))
    await wrapper.get('[data-testid="production-refresh"]').trigger('click')
    const refreshSignal = fetchDashboard.mock.calls.at(-1)?.[1] as AbortSignal
    const limited = payload()
    limited.sections.tasks = { state: 'FORBIDDEN', reason: '任务权限不足', data: null }
    limited.sections.receipts.data!.pending_state = 'FORBIDDEN'
    fetchDashboard.mockResolvedValueOnce(limited)
    await expandModule(wrapper, 'delivery')
    await wrapper.get('.pd-chart__bar').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="production-due-dialog"]').attributes('data-state')).toBe('forbidden')
    expect(wrapper.text()).not.toContain('SC-TEST-001')
    expect(wrapper.text()).not.toContain('待清除的入库差额')
    expect(wrapper.get('[data-module="production"]').text()).not.toContain('24')
    await expandModule(wrapper, 'output')
    expect(wrapper.get('[data-testid="production-receipt-gaps"]').text()).toContain('没有查看入库差额所需的任务权限')
    expect(refreshSignal.aborted).toBe(true)
    expect(wrapper.attributes('data-state')).toBe('ready')
    finishRefresh(original)
    await flushPromises()
    expect(wrapper.text()).not.toContain('SC-TEST-001')
    expect(wrapper.text()).not.toContain('待清除的入库差额')
    expect(wrapper.attributes('data-state')).toBe('ready')
  })

  it('日期响应撤销入库分区权限时只清该分区，不覆盖主任务筛选', async () => {
    const original = payload()
    original.sections.receipts.state = 'READY'
    original.sections.receipts.data!.pending_state = 'READY'
    original.sections.receipts.data!.pending_products = [{ product_line_id: 'p-1', task_number: 'SC-TEST-001', name: '待清除的入库差额', unit: '把', required: '120', received: '20', remaining: '100', href: '/production-tasks/task-1', state: 'READY' }]
    fetchDashboard.mockResolvedValueOnce(original)
    const wrapper = render('executive')
    await flushPromises()
    const limited = payload()
    limited.sections.tasks.data!.counts.total = 4
    limited.sections.receipts = { state: 'FORBIDDEN', reason: '入库权限不足', data: null }
    fetchDashboard.mockResolvedValueOnce(limited)
    await expandModule(wrapper, 'delivery')
    await wrapper.get('.pd-chart__bar').trigger('click')
    await flushPromises()
    await expandModule(wrapper, 'output')
    expect(wrapper.get('[data-testid="production-receipt-gaps"]').text()).toContain('入库权限不足')
    expect(wrapper.text()).not.toContain('待清除的入库差额')
    expect(wrapper.get('[data-module="production"]').text()).toContain('24')
    expect(wrapper.get('[data-testid="production-due-dialog"]').attributes('data-state')).toBe('ready')
  })
})

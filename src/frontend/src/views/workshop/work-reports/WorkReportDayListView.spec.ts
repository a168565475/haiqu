import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElOption, ElPagination, ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

import WorkReportDayListView from './WorkReportDayListView.vue'

enableAutoUnmount(afterEach)

const api = vi.hoisted(() => ({ context: vi.fn(), list: vi.fn(), detail: vi.fn(), records: vi.fn(), tasks: vi.fn(), products: vi.fn(), workshops: vi.fn() }))
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }))
const auth = vi.hoisted(() => ({
  user: { is_superuser: true, permissions: [] } as {
    is_superuser: boolean
    permissions: string[]
    effective_access?: { roles: { code: string }[] }
  },
  hasPermission: vi.fn((permission: string) => auth.user.permissions.includes(permission)),
}))
const route = reactive({ query: {} as Record<string, string | string[]> })

vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => router }))
vi.mock('@/api/workshopReporting', () => ({
  fetchReportingContext: api.context,
  fetchWorkReportDay: api.detail,
  fetchWorkReportDays: api.list,
  fetchWorkReports: api.records,
  fetchWorkReportTaskOptions: api.tasks,
  fetchWorkReportProductOptions: api.products,
  fetchWorkReportWorkshops: api.workshops,
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => auth,
}))

const report = {
  id: 'report-1', report_number: 'BG-202609-000001', production_date: '2026-09-28',
  production_task: { id: 'task-1', task_number: 'HT26050', order_number: 'SO-202609-000076' },
  product: { name: '六边形围炉桌', number: 'FLOW260917-P020', code: 'HTC-001B' },
  product_line_id: 'line-1', schedule_product_id: 'schedule-product-1',
  workshop: { id: 'workshop-1', name: '金工车间' }, scope_craft: { id: 'craft-1', name: '管材加工' },
  scheme_id: 'scheme-1', scheme_version: 1, revision: 1, recorder: '业务员 A',
  total_amount: '5.4', updated_by: '业务员 A', line_count: 1,
  created_at: '2026-09-28T08:16:00Z', updated_at: '2099-01-01T00:00:00Z',
  lines: [{
    id: 'line-1', line_number: 1, scheme_line_id: 'scheme-line-1', work_item_id: 'work-item-1',
    workshop_employee_id: 'employee-1', employee_name: '员工甲', production_line: null,
    display_name: '下伸缩管-18*0.8*440', cutting_length_mm: 440, craft_name: '管材加工', operation_name: '管口冲员', unit_name: '',
    quantity: '12', order_quantity_snapshot: 350,
    cumulative_quantity: '36', required_quantity: '1400', unit_price: '0.2', amount: '2.4',
  }],
}
const secondReport = { ...report, id: 'report-2', report_number: 'BG-202609-000002',
  recorder: '业务员 B', total_amount: '60', created_at: '2026-09-28T07:36:00Z',
  product: { name: '靠背椅', number: 'CHAIR-001', code: 'CHAIR-CODE' },
  lines: [{ ...report.lines[0]!, id: 'line-2', employee_name: '员工乙', quantity: '300', amount: '60' }] }
const recordsResponse = (data = [report, secondReport], page = 1, total = data.length) => ({
  data, meta: { page, page_size: 20, total, total_pages: Math.ceil(total / 20) },
})
const workshopRows = [{ id: 'workshop-1', name: '金工车间' }, { id: 'workshop-2', name: '装配车间' }]
const tasks = [{ id: 'task-1', task_number: 'HT26050' }, { id: 'task-2', task_number: 'HT26170' }]
const products = [
  { id: 'line-1', production_task_id: 'task-1', task_number: 'HT26050', name: '六边形围炉桌', code: 'HTC-001B', number: 'P020' },
  { id: 'line-2', production_task_id: 'task-2', task_number: 'HT26170', name: '靠背椅', code: 'CHAIR-CODE', number: 'P021' },
]
const filterSelect = (wrapper: VueWrapper, name: string) => wrapper.findAllComponents(ElSelect)
  .find(select => select.attributes('data-testid') === `work-report-${name}-filter`)!
const button = (wrapper: VueWrapper, label: string) => wrapper.findAll('button').find(item => item.text() === label)!

beforeEach(() => {
  vi.clearAllMocks()
  Object.values(api).forEach(mock => mock.mockReset())
  auth.user = { is_superuser: true, permissions: [] }
  route.query = { schedule_product_id: 'schedule-product-1', workshop_id: 'workshop-1' }
  router.replace.mockImplementation(async (location: { query?: Record<string, string> }) => {
    route.query = location.query || {}
  })
  api.tasks.mockResolvedValue(tasks)
  api.products.mockResolvedValue(products)
  api.workshops.mockResolvedValue(workshopRows)
  api.context.mockResolvedValue({
    schedule_product: {
      id: 'schedule-product-1', product_line_id: 'line-1', production_task_id: 'task-1',
      task_number: 'HT26050', order_number: 'SO-202609-000076',
      product_name: '六边形围炉桌', product_number: 'FLOW260917-P020', product_code: 'HTC-001B',
      product_specification: '标准款', product_color: '黑色', planned_quantity: '350',
      order_quantity: '350', unit_name: '件',
    },
    schedule_products: [],
    workshops: workshopRows,
    crafts: [
      { id: 'craft-1', name: '管材加工', workshop_id: 'workshop-1', plan_category: 'METAL' },
      { id: 'craft-2', name: '装配', workshop_id: 'workshop-2', plan_category: 'ASSEMBLY' },
    ],
    operations: [], bom_items: [], employees: [],
  })
  api.records.mockResolvedValue(recordsResponse())
})

it('只读账号不显示新增按钮', async () => {
    auth.user = { is_superuser: false, permissions: ['workshop_reporting.view_workreport'] }
    const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.find('.wr-report-records__create').exists()).toBe(false)
    expect(wrapper.find('.wr-report-group__header .el-button').exists()).toBe(false)
    wrapper.unmount()
})

it('按实际报工次数分页，只读取当前页且翻页立即清空旧明细', async () => {
    api.records.mockResolvedValueOnce(recordsResponse([report], 1, 21))
    const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(api.records).toHaveBeenCalledTimes(1)
    expect(wrapper.findComponent(ElPagination).props('total')).toBe(21)
    let finishPage!: (value: unknown) => void
    api.records.mockImplementationOnce(() => new Promise(resolve => { finishPage = resolve }))
    wrapper.findComponent(ElPagination).vm.$emit('update:current-page', 2)
    wrapper.findComponent(ElPagination).vm.$emit('current-change', 2)
    await flushPromises()
    expect(api.records).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }))
    expect(wrapper.find('.wr-report-group').exists()).toBe(false)
    finishPage(recordsResponse([secondReport], 2, 21))
    await flushPromises()
    expect(wrapper.find('.wr-report-group').text()).toContain(secondReport.product.code)
    wrapper.unmount()
})

it('从报工菜单直接加载记录，并显示两个可搜索的多选框', async () => {
  route.query = {}
  const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
  await flushPromises()

  expect(router.replace).not.toHaveBeenCalled()
  expect(api.context).not.toHaveBeenCalled()
  expect(api.records).toHaveBeenCalledWith(expect.objectContaining({ workshop_id: 'workshop-1' }))
  expect(api.tasks).not.toHaveBeenCalled()
  expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  for (const name of ['task', 'product']) {
    expect(filterSelect(wrapper, name).props()).toMatchObject({ multiple: true, filterable: true, remote: true })
  }
  expect(wrapper.find('.wr-report-context').text()).not.toContain('生产订单：')
})

it('按任务和车间读取全部产品，不显示新增入口，每条保存记录标注产品', async () => {
  route.query = { production_task_id: 'task-1', workshop_id: 'workshop-1' }
  const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  expect(api.tasks).toHaveBeenCalledWith(expect.objectContaining({ production_task_ids: ['task-1'] }))
  expect(api.context).not.toHaveBeenCalled()
  expect(api.records).toHaveBeenCalledWith(expect.objectContaining({ production_task_id: 'task-1', workshop_id: 'workshop-1' }))
  expect(api.list).not.toHaveBeenCalled()
  expect(api.detail).not.toHaveBeenCalled()
  expect(wrapper.find('.wr-report-records__create').exists()).toBe(false)
  expect(filterSelect(wrapper, 'product').props('modelValue')).toEqual([])
  expect(wrapper.find('.wr-report-group__header').text()).toContain('六边形围炉桌')
  expect(wrapper.find('.wr-report-group__header').text()).toMatch(/HTC-001B\s*生产日期：2026-09-28/)
  expect(wrapper.find('.wr-report-group__header').text()).not.toContain(report.report_number)
  expect(wrapper.get('.wr-report-list-panel').text()).toContain('生产任务单号')
  expect(wrapper.get('.wr-report-list-panel').text()).toContain('HT26050')
  expect(wrapper.get('.wr-report-list-panel').text()).not.toContain(report.report_number)
  expect(wrapper.get('.wr-report-group').text()).toContain('切割长度')
  expect(wrapper.get('.wr-report-group').text()).toContain('440 mm')
  await wrapper.find('.wr-report-group__header .el-button').trigger('click')
  expect(router.push).toHaveBeenCalledWith({ name: 'work-report-edit', params: { reportId: 'report-1' }, query: { production_task_id: 'task-1' } })
  wrapper.unmount()
})

it('搜索任务及产品编码，应用时发送多选，取消任务后移除不再关联的产品', async () => {
  route.query = {}
  const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
  await flushPromises()

  const task = filterSelect(wrapper, 'task')
  const product = filterSelect(wrapper, 'product')
  task.props('remoteMethod')!('HT26')
  await flushPromises()
  expect(api.tasks).toHaveBeenCalledWith(expect.objectContaining({ q: 'HT26', workshop_id: 'workshop-1' }))
  await task.setValue(tasks)
  task.vm.$emit('change', tasks)
  await product.get('.el-select__wrapper').trigger('click')
  await flushPromises()
  product.props('remoteMethod')!('HTC-001B')
  await flushPromises()
  expect(api.products).toHaveBeenCalledWith(expect.objectContaining({
    q: 'HTC-001B', production_task_ids: ['task-1', 'task-2'], workshop_id: 'workshop-1',
  }))
  expect(product.findAllComponents(ElOption).map(option => option.props('label'))).toContain('HTC-001B · 六边形围炉桌 · HT26050')
  await product.setValue(products)
  await button(wrapper, '应用筛选').trigger('click')
  await flushPromises()
  expect(api.records).toHaveBeenLastCalledWith(expect.objectContaining({
    page: 1, production_task_ids: ['task-1', 'task-2'], product_line_ids: ['line-1', 'line-2'],
  }))

  await task.setValue([tasks[0]])
  task.vm.$emit('change', [tasks[0]])
  await button(wrapper, '应用筛选').trigger('click')
  await flushPromises()
  expect(api.records).toHaveBeenLastCalledWith(expect.objectContaining({
    production_task_ids: ['task-1'], product_line_ids: ['line-1'],
  }))
})

it('裁剪和车缝用同一车间 ID，但请求各自分类，也不显示金工切割长度列', async () => {
  const sewing = { id: 'workshop-sewing', name: '车缝车间' }
  route.query = { production_task_id: 'task-1', workshop_id: sewing.id, plan_category: 'CUTTING' }
  api.workshops.mockResolvedValue([sewing])
  api.records.mockResolvedValue(recordsResponse([{ ...report, workshop: sewing }]))
  const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  expect(api.records).toHaveBeenLastCalledWith(expect.objectContaining({ workshop_id: sewing.id, plan_category: 'CUTTING' }))
  expect(wrapper.get('.wr-report-group').text()).not.toContain('切割长度')
  await filterSelect(wrapper, 'workshop').setValue(`${sewing.id}:SEWING`)
  await button(wrapper, '应用筛选').trigger('click')
  await flushPromises()
  expect(api.records).toHaveBeenLastCalledWith(expect.objectContaining({
    workshop_id: sewing.id, plan_category: 'SEWING', production_task_ids: ['task-1'],
  }))
})

it.each([
  ['METAL_DIRECTOR', workshopRows[0]!],
  ['ASSEMBLY_DIRECTOR', workshopRows[1]!],
])('%s 以固定车间进入，其他有权账号可使用车间下拉', async (role, workshop) => {
  route.query = {}
  api.workshops.mockResolvedValue([workshop])
  auth.user = { is_superuser: false, permissions: ['workshop_reporting.view_workreport'], effective_access: { roles: [{ code: role }] } }
  const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  expect(wrapper.find('[data-testid="work-report-workshop-filter"]').exists()).toBe(false)
  expect(wrapper.get('.wr-report-context__workshop').text()).toContain(workshop.name)
  expect(api.records).toHaveBeenLastCalledWith(expect.objectContaining({ workshop_id: workshop.id }))
  wrapper.unmount()

  auth.user = { is_superuser: false, permissions: ['workshop_reporting.view_workreport'], effective_access: { roles: [{ code: 'FACTORY_MANAGER' }] } }
  const manager = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  expect(manager.find('[data-testid="work-report-workshop-filter"]').exists()).toBe(true)
})

it.each([
  { production_task_id: 'missing-task', workshop_id: 'workshop-1' },
  { production_task_id: 'task-1', workshop_id: 'missing-workshop' },
  { production_task_id: ['task-1', 'task-2'], workshop_id: 'workshop-1' },
])('非法任务或车间地址不会回落到第一条记录：%j', async (query) => {
  route.query = query
  const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  expect(api.records).not.toHaveBeenCalled()
  expect(api.detail).not.toHaveBeenCalled()
  expect(wrapper.find('.wr-report-records__error').exists()).toBe(true)
  wrapper.unmount()
})

it('任务接口拒绝访问时显示错误，不读取报工列表', async () => {
  route.query = { production_task_id: 'task-1', workshop_id: 'workshop-1' }
  api.tasks.mockRejectedValueOnce({ response: { data: { error: { message: '没有该任务查看权限。' } } } })
  const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  expect(wrapper.text()).toContain('没有该任务查看权限。')
  expect(api.records).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('排产链接失效时仍可重置并用同一页面筛选授权记录', async () => {
  api.context.mockRejectedValueOnce({ response: { data: { error: { message: '排产产品已失效' } } } })
  const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  expect(wrapper.get('.wr-report-records__error').text()).toContain('排产产品已失效')
  expect(api.records).not.toHaveBeenCalled()
  await button(wrapper, '重置').trigger('click')
  await flushPromises()
  expect(api.records).toHaveBeenLastCalledWith(expect.objectContaining({ workshop_id: 'workshop-1' }))
  expect(wrapper.find('.wr-report-records__error').exists()).toBe(false)
})

it('切换车间读取失败时清空旧记录并显示实际错误', async () => {
  route.query = { production_task_id: 'task-1', workshop_id: 'workshop-1' }
  const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  api.records.mockRejectedValueOnce({ response: { data: { error: { message: '车间范围已变化' } } } })
  await filterSelect(wrapper, 'workshop').setValue('workshop-2')
  await button(wrapper, '应用筛选').trigger('click')
  await flushPromises()
  expect(api.records).toHaveBeenLastCalledWith(expect.objectContaining({ workshop_id: 'workshop-2' }))
  expect(wrapper.find('.wr-report-records__error').text()).toContain('车间范围已变化')
  expect(wrapper.find('.wr-report-group').exists()).toBe(false)
})

it('切换任务时清空旧数据并忽略先前未完成的请求', async () => {
  route.query = { production_task_id: 'task-1', workshop_id: 'workshop-1' }
  let finishOldRequest!: (value: unknown) => void
  api.records.mockImplementationOnce(() => new Promise(resolve => { finishOldRequest = resolve }))
  const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  route.query = { production_task_id: 'missing-task', workshop_id: 'workshop-1' }
  await flushPromises()
  finishOldRequest({ data: [{ production_date: '1999-01-01' }], meta: { total: 1 } })
  await flushPromises()
  expect(wrapper.text()).not.toContain('1999-01-01')
  expect(api.detail).not.toHaveBeenCalled()
  expect(wrapper.find('.wr-report-records__error').exists()).toBe(true)
  wrapper.unmount()
})

describe('按每次报工查看记录', () => {
  it('同一天两次报工各占一行，按生产日期显示所选报工', async () => {
    const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(api.context).toHaveBeenCalledWith('schedule-product-1', 'work_report')
    expect(api.records).toHaveBeenCalledWith(expect.objectContaining({
      page: 1,
      page_size: 20,
      schedule_product_id: 'schedule-product-1',
      workshop_id: 'workshop-1',
    }))
    expect(api.list).not.toHaveBeenCalled()
    expect(api.detail).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('HT26050')
    expect(wrapper.text()).toContain('六边形围炉桌')
    expect(wrapper.findAll('.wr-report-list-panel__table .el-table__row')).toHaveLength(2)
    expect(wrapper.find('.wr-report-list-panel__table .el-table__header').text()).toContain('生产日期')
    expect(wrapper.findAll('.wr-report-date').map(cell => cell.text())).toEqual(['2026-09-28', '2026-09-28'])
    expect(wrapper.find('.wr-report-group').text()).toContain('生产日期：2026-09-28')
    expect(wrapper.text()).not.toContain('报工时间')
    expect(wrapper.find('.wr-report-group').text()).toContain('管材加工')
    expect(wrapper.find('.wr-report-group').text()).toContain('员工甲')
    expect(wrapper.find('.wr-report-group').text()).not.toContain('员工乙')
    expect(wrapper.text()).not.toContain('保存次数')
    expect(wrapper.text()).not.toContain('次保存')
    expect(wrapper.text()).not.toContain('当日工费')
    expect(wrapper.text()).not.toContain('2099')
    expect(wrapper.text()).toContain('需完成次数')
    expect(wrapper.text()).toContain('1,400')
    expect(wrapper.text()).toContain('累计进度')
    expect(wrapper.text()).toContain('已报 36 / 总需 1,400')
    expect(wrapper.text()).toContain('3%')
    expect(wrapper.text()).not.toContain('累计报工')
    expect(wrapper.find('.el-date-editor').exists()).toBe(false)
    await wrapper.find('.wr-report-group__header .el-button').trigger('click')
    expect(router.push).toHaveBeenCalledWith({ name: 'work-report-edit', params: { reportId: 'report-1' } })

    await wrapper.findAll('.wr-report-list-panel__table .el-table__row')[1].trigger('click')
    await flushPromises()
    expect(wrapper.find('.wr-report-group').text()).toContain('员工乙')
    expect(wrapper.find('.wr-report-group').text()).toContain('靠背椅')
    expect(wrapper.find('.wr-report-group').text()).not.toContain('员工甲')
    expect(wrapper.findAll('.wr-report-group')).toHaveLength(1)
    expect(api.records).toHaveBeenCalledTimes(1)

    const workshopSelect = wrapper.find('.wr-report-context__workshop').findComponent(ElSelect)
    await workshopSelect.setValue('workshop-2')
    await button(wrapper, '应用筛选').trigger('click')
    await flushPromises()
    expect(api.records).toHaveBeenLastCalledWith(expect.objectContaining({ workshop_id: 'workshop-2' }))

    await wrapper.find('.wr-report-records__create').trigger('click')
    expect(router.push).toHaveBeenCalledWith({
      name: 'work-report-new',
      query: expect.objectContaining({ schedule_product_id: 'schedule-product-1', workshop_id: 'workshop-2', craft_id: 'craft-2' }),
    })
    wrapper.unmount()
  })

  it('刷新保留所选报工，所选已不存在时改选当前页第一条', async () => {
    const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    await wrapper.findAll('.wr-report-list-panel__table .el-table__row')[1].trigger('click')
    await button(wrapper, '刷新').trigger('click')
    await flushPromises()
    expect(wrapper.find('.wr-report-group').text()).toContain('员工乙')
    api.records.mockResolvedValueOnce(recordsResponse([report]))
    await button(wrapper, '刷新').trigger('click')
    await flushPromises()
    expect(wrapper.find('.wr-report-group').text()).toContain('员工甲')
    wrapper.unmount()
  })

  it('无报工时显示空态，接口拒绝时清空旧记录并显示错误', async () => {
    api.records.mockResolvedValueOnce(recordsResponse([]))
    const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(wrapper.text()).toContain('当前车间暂无报工记录')
    expect(wrapper.find('.wr-report-group').exists()).toBe(false)
    api.records.mockRejectedValueOnce({ response: { data: { error: { message: '没有报工查看权限。' } } } })
    await button(wrapper, '刷新').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('没有报工查看权限。')
    expect(wrapper.find('.wr-report-group').exists()).toBe(false)
    wrapper.unmount()
  })
})

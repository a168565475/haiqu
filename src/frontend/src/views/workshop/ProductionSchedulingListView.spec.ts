import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ProductionSchedulingListView from './ProductionSchedulingListView.vue'
import ScheduleListStageProgress from '@/components/productionScheduling/ScheduleListStageProgress.vue'
import type { CompleteScheduleResult, ProductionSchedule, ScheduleCompletionPreview, ScheduleProduct } from '@/types/productionScheduling'
import type { ScheduleProgressStatus, ScheduleStageKey } from '@/types/workshopReporting'
import { scheduleRiskColors } from '@/utils/scheduleListDisplay'

const api = vi.hoisted(() => ({ schedules: vi.fn(), preview: vi.fn(), progress: vi.fn(), complete: vi.fn(), push: vi.fn() }))
const state = vi.hoisted(() => ({ finish: true }))
vi.mock('@/api/productionScheduling', () => ({ fetchSchedules: api.schedules, fetchScheduleCompletionPreview: api.preview, completeSchedule: api.complete, scheduleProductImageUrl: () => '/product.png' }))
vi.mock('@/api/workshopReporting', () => ({ fetchScheduleProgressStatuses: api.progress }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: api.push }) }))
vi.mock('@/directives/glassSpotlight', () => ({ vGlassSpotlight: {} }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({
  user: { is_superuser: false }, hasPermission: () => false,
  moduleCan: (permission: string, legacy: string) => permission === 'access_control.finish_productiontask' && legacy === 'production_tasks.change_productiontask' && state.finish,
}) }))

function schedule(overrides: Partial<ProductionSchedule> = {}): ProductionSchedule {
  return { id: 'schedule-1', schedule_number: 'PC-001', production_task_id: 'task-1', record_status: 'ACTIVE',
    record_status_display: '有效', source_current_status: 'IN_PRODUCTION', source_current_status_display: '生产中', source: { task_number: 'HT-001' },
    products: [], date_ranges: {}, created_by: { id: 'employee-1', name: '员工' }, created_at: '2026-10-21', ...overrides } as ProductionSchedule
}
function progress(): ScheduleCompletionPreview['progress'] {
  return Object.fromEntries(['MATERIAL', 'METAL', 'SEWING', 'ASSEMBLY'].map(key => [key, { percentage: 100, display: '100%', status: 'READY' }])) as ScheduleCompletionPreview['progress']
}
function product(overrides: Partial<ScheduleProduct> = {}): ScheduleProduct {
  return { id: 'p1', product_line_id: 'line-1', line_number: 1, planned_quantity: 100, source_quantity: 100,
    unit_id: 'unit-set', unit_name: '套', image_file_id: null,
    product: { product_name: '导演椅', color_name: '酒红色', material: 'PE', specification: '57*49*78' },
    material_inbound_date: '2026-10-22', metal_return_date: '2026-10-24', sewing_return_date: '2026-10-28',
    finished_inbound_date: '2026-10-31', crafts: [], ...overrides }
}
function displayProgress(): ScheduleProgressStatus {
  const percentages: Record<ScheduleStageKey, number> = { METAL: 100, CUTTING: 0, SEWING: 50, ASSEMBLY: 25 }
  return { schedule_id: 'schedule-1', progress: progress(), as_of_date: '2026-10-22', overall_percentage: 63,
    outbound_progress: { status: 'READY', percentage: 20, products: [{ schedule_product_id: 'p1', status: 'READY', percentage: 20, planned_date: null, received_quantity: 50, order_quantity: 100, outbound_quantity: 20 }] },
    stage_progress: Object.fromEntries(Object.entries(percentages).map(([key, percentage]) => [key, {
      status: 'READY', percentage, products: [{ schedule_product_id: 'p1', status: 'READY', percentage, planned_date: '2026-10-31' }],
    }])) as ScheduleProgressStatus['stage_progress'] }
}
function preview(): ScheduleCompletionPreview {
  return { schedule_id: 'schedule-1', schedule_number: 'PC-001', schedule_etag: '"schedule-v1"',
    task: { id: 'task-1', task_number: 'HT-001', status: 'IN_PRODUCTION', status_display: '生产中', etag: '"task-v2"' },
    progress: progress(), products: [{ schedule_product_id: 'p1', product_name: '靠背凳', specification: '28x59', color: '酒红', material: 'PE', required_quantity: 200, received_quantity: 199, unit_name: '箱' }],
    sales_order: { id: null, order_number: null, status: null, status_display: null, etag: null, can_sync: false, reason: '当前账号无关联销售订单查看权限。' } }
}
function result(): CompleteScheduleResult {
  return { schedule_id: 'schedule-1', production_task_id: 'task-1', production_task_status: 'COMPLETED',
    production_sync: { before_status: 'IN_PRODUCTION', after_status: 'COMPLETED' }, progress: progress(),
    sales_sync: { status: 'SKIPPED', reason: '余款尚未登记完成。', before_status: 'FULFILLING', after_status: 'FULFILLING' } }
}
const wrappers: ReturnType<typeof mount>[] = []
async function createView() {
  const wrapper = mount(ProductionSchedulingListView, { global: { plugins: [ElementPlus], stubs: {
    ScheduleCompletionDialog: { name: 'ScheduleCompletionDialog', props: ['modelValue', 'preview', 'submitting', 'result', 'error', 'uncertain'], emits: ['update:modelValue', 'confirm'], template: '<section v-if="modelValue" data-testid="completion-dialog"><span>{{ preview.task.task_number }}</span><button data-testid="confirm" @click="$emit(\'confirm\', \'核对完成\')">确认</button><span v-if="result" data-testid="result">{{ result.sales_sync.reason }}</span><span v-if="error" data-testid="error">{{ error }}</span></section>' },
  } } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
function dialog(wrapper: ReturnType<typeof mount>) { return wrapper.findComponent({ name: 'ScheduleCompletionDialog' }) }
function completionItem(wrapper: ReturnType<typeof mount>) { return wrapper.findAllComponents({ name: 'ElDropdownItem' }).find(item => item.props('command') === 'complete')! }
async function openCompletion(wrapper: ReturnType<typeof mount>) {
  await wrapper.findAll('button').find(button => button.text() === '更多')!.trigger('click')
  await completionItem(wrapper).get('li[role="menuitem"]').trigger('click')
  await flushPromises()
}
function responseError(status: number, message: string) {
  const error = new AxiosError(message)
  error.response = { status, data: { error: { message } } } as never
  return error
}
beforeEach(() => {
  vi.resetAllMocks()
  state.finish = true
  api.schedules.mockResolvedValue({ data: [schedule()], meta: { total: 1 } })
  api.progress.mockResolvedValue([{ schedule_id: 'schedule-1', progress: progress() }])
  api.preview.mockResolvedValue(preview())
  api.complete.mockResolvedValue(result())
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks(); ElMessage.closeAll() })

describe('计划排产列表展示', () => {
  it.each(['METAL', 'SEWING'] as const)('%s外发悬浮按单据展示基础信息，不显示产品部位', stage => {
    const display = displayProgress()
    const record = {
      id: 'TUBE:order-1', order_number: 'WF-001', craft_name: '喷塑', factory_name: '加工厂甲',
      expected_return_date: '2026-10-24', remaining_quantity: '800', quantity_unit: '支', remaining_display: '800 支',
      state: 'IN_PROGRESS' as const, risk: 'slow' as const, description: '距交期 2 天，尚未回齐',
      schedule_product_id: 'p1', part_name: '前后交叉管',
    }
    display.outsourcing_status = {
      METAL: { state: 'NONE', risk: 'none', description: '暂无外发', records: [] },
      SEWING: { state: 'NONE', risk: 'none', description: '暂无外发', records: [] },
      [stage]: { state: 'IN_PROGRESS', risk: 'slow', description: record.description, records: [record] },
    }
    const wrapper = mount(ScheduleListStageProgress, {
      props: { schedule: schedule({ products: [product()] }), progress: display, failed: false },
      global: { stubs: { ElPopover: { template: '<div><slot name="reference" /><slot /></div>' }, ElProgress: true } },
    })
    wrappers.push(wrapper)
    expect(wrapper.findAll('.outsourcing-record')).toHaveLength(1)
    const card = wrapper.get('.outsourcing-record').text()
    for (const value of ['WF-001', '喷塑', '加工厂甲', '2026-10-24', '未回 800 支', record.description]) expect(card).toContain(value)
    expect(card).not.toContain('导演椅')
    expect(card).not.toContain('前后交叉管')
    const outbound = wrapper.findAll('.stage-product-list').at(-1)!.text()
    expect(outbound).toContain('订单 100 套')
    expect(outbound).toContain('出库 20 套')
    expect(outbound).not.toContain('入库 50 套')
    expect(wrapper.findAll('.schedule-stage-trigger').at(-1)!.attributes('aria-label')).toContain('累计出库数量 ÷ 订单数量')
  })
  it('显示金额零值及生产任务单当前跟单员，未知金额不冒充零', async () => {
    api.schedules.mockResolvedValue({ data: [schedule({
      list_amounts: { estimated_wage: '0.00', reported_amount: '1234.50' },
      factory_follower_names: ['跟单甲', '跟单乙'],
      source: { followers: [{ name: '旧跟单员' }] },
    })], meta: { total: 1 } })
    const wrapper = await createView()
    const text = wrapper.get('.el-table__body-wrapper tbody tr').text()
    expect(text).toContain('0.00')
    expect(text).toContain('1,234.50')
    expect(text).toContain('跟单甲、跟单乙')
    expect(text).not.toContain('旧跟单员')
  })
  it('保留列表操作并显示产品汇总、计划开始和交货日期，不显示旧日期及创建人列', async () => {
    api.schedules.mockResolvedValue({ data: [schedule({
      source: { task_number: 'HT-001', planned_start_date: '2026-10-20', delivery_date: '2026-11-06' },
      products: [product(), product({ id: 'p2', product_line_id: 'line-2', planned_quantity: 50 })],
    })], meta: { total: 1 } })
    const wrapper = await createView()
    const headers = wrapper.findAll('.el-table__header-wrapper th .cell').map(cell => cell.text())
    expect(headers).toEqual(['排产单号', '生产任务单', '产品', '计划开始', '交货日期', '总进度', '工序进度', '总工价', '报工总额', '工厂跟单员', '操作'])
    expect(headers).not.toEqual(expect.arrayContaining(['创建人', '创建时间', '创建日期', '计划日期范围']))
    expect(wrapper.get('.schedule-products-summary').text()).toBe('2 项产品 · 共 150 套')
    const row = wrapper.get('.el-table__body-wrapper tbody tr')
    expect(row.text()).toContain('2026-10-20')
    expect(row.text()).toContain('2026-11-06')
    expect(row.text()).not.toContain('2026-10-21')
    expect(row.text()).toContain('更多')
  })
  it('总进度直接显示接口值，四环节按金工、裁剪、车缝、装配顺序展示', async () => {
    api.schedules.mockResolvedValue({ data: [schedule({ products: [product()] })], meta: { total: 1 } })
    api.progress.mockResolvedValue([displayProgress()])
    const wrapper = await createView()
    expect(wrapper.get('.schedule-overall-progress').text()).toBe('63%')
    expect(wrapper.findComponent({ name: 'ElProgress' }).props('percentage')).toBe(63)
    const stages = wrapper.findAll('.schedule-stage-trigger:not(.schedule-outsourcing-trigger)')
    expect(stages.map(stage => stage.get('.schedule-stage-label').text())).toEqual(['金工完成', '裁剪完成', '车缝完成', '装配入库', '出库'])
    expect(stages.map(stage => stage.get('.schedule-stage-ring > span').text())).toEqual(['100%', '0%', '50%', '25%', '20%'])
  })
  it('缺少新进度数据时总进度和四圈显示未知，不将旧进度或缺值显示成零或绿色', async () => {
    api.schedules.mockResolvedValue({ data: [schedule({ products: [product()] })], meta: { total: 1 } })
    const wrapper = await createView()
    expect(wrapper.get('.schedule-overall-progress').text()).toBe('—')
    expect(wrapper.findComponent({ name: 'ElProgress' }).exists()).toBe(false)
    expect(wrapper.findAll('.schedule-stage:not(.is-outsourcing) .schedule-stage-ring > span').map(cell => cell.text())).toEqual(['—', '—', '—', '—', '—'])
    expect(wrapper.findAll('.schedule-stage:not(.is-outsourcing) .stage-fill')).toHaveLength(0)
    for (const stage of wrapper.findAll('.schedule-stage')) {
      expect((stage.element as HTMLElement).style.getPropertyValue('--stage-color')).toBe(scheduleRiskColors.unknown)
    }
  })
  it('进度接口失败时保留产品列表并显示未知，完成订单继续禁用', async () => {
    api.schedules.mockResolvedValue({ data: [schedule({ products: [product()] })], meta: { total: 1 } })
    api.progress.mockRejectedValue(new AxiosError('network failure'))
    const wrapper = await createView()
    expect(wrapper.get('.schedule-products-summary').text()).toBe('1 项产品 · 共 100 套')
    expect(wrapper.get('.schedule-overall-progress').text()).toBe('—')
    expect(wrapper.get('.schedule-overall-progress').attributes('title')).toContain('进度加载失败')
    expect(completionItem(wrapper).props('disabled')).toBe(true)
  })
  it('新增工序进度和总进度不改变既有完成订单门槛', async () => {
    api.schedules.mockResolvedValue({ data: [schedule({ products: [product()] })], meta: { total: 1 } })
    const display = displayProgress()
    display.overall_percentage = null
    api.progress.mockResolvedValue([display])
    const wrapper = await createView()
    expect(wrapper.findAll('.schedule-stage:not(.is-outsourcing) .schedule-stage-ring > span')[1]!.text()).toBe('0%')
    expect(completionItem(wrapper).props('disabled')).toBe(false)
    await openCompletion(wrapper)
    expect(api.preview).toHaveBeenCalledWith('schedule-1')
    expect(dialog(wrapper).props('modelValue')).toBe(true)
    expect(api.complete).not.toHaveBeenCalled()
  })
  it('外发圈插在金工和车缝之后，无外发时浅蓝空心且不影响总进度', async () => {
    api.schedules.mockResolvedValue({ data: [schedule({ products: [product()] })], meta: { total: 1 } })
    const display = displayProgress()
    const empty = { state: 'NONE', risk: 'none', description: '暂无可查看的有效外发单', records: [] } as const
    display.outsourcing_status = { METAL: { ...empty, records: [] }, SEWING: { ...empty, records: [] } }
    api.progress.mockResolvedValue([display])
    const wrapper = await createView()
    expect(wrapper.findAll('.schedule-stage-label').map(el => el.text())).toEqual(['金工完成', '金工外发', '裁剪完成', '车缝完成', '裁剪外发', '装配入库', '出库'])
    expect(wrapper.findAll('.schedule-outsourcing-ring.is-empty')).toHaveLength(2)
    expect(wrapper.findAll('.schedule-outsourcing-ring > span').map(el => el.text())).toEqual(['', ''])
    expect(wrapper.get('.schedule-overall-progress').text()).toBe('63%')
    expect((wrapper.get('.is-outsourcing').element as HTMLElement).style.getPropertyValue('--stage-color')).toBe('#72a7d1')
  })
  it('未回齐且交期紧张显示感叹号，全部回齐显示勾号，外发不显示百分比', async () => {
    api.schedules.mockResolvedValue({ data: [schedule({ products: [product()] })], meta: { total: 1 } })
    const display = displayProgress()
    display.outsourcing_status = {
      METAL: { state: 'IN_PROGRESS', risk: 'urgent', description: '今日交期，尚未回齐，后续工序有阻塞风险', records: [] },
      SEWING: { state: 'RETURNED', risk: 'normal', description: '关联外发已全部回齐', records: [] },
    }
    api.progress.mockResolvedValue([display])
    const wrapper = await createView()
    expect(wrapper.findAll('.schedule-outsourcing-ring > span').map(el => el.text())).toEqual(['!', '✓'])
    expect(wrapper.findAll('.schedule-outsourcing-trigger')[0]!.attributes('aria-label')).toContain('阻塞风险')
    expect(wrapper.findAll('.schedule-outsourcing-trigger').every(el => !el.text().includes('%'))).toBe(true)
  })
})
describe('排产完成预览与提交编排', () => {
  it('更多中查看仍跳转详情，完成读取真实预览但不提交', async () => {
    const wrapper = await createView()
    await wrapper.findAllComponents({ name: 'ElDropdownItem' }).find(item => item.props('command') === 'view')!.get('li[role="menuitem"]').trigger('click')
    expect(api.push).toHaveBeenCalledWith('/workshop/scheduling/schedule-1')
    await openCompletion(wrapper)
    expect(api.preview).toHaveBeenCalledWith('schedule-1')
    expect(dialog(wrapper).props('preview').products[0]).toMatchObject({ required_quantity: 200, received_quantity: 199 })
    expect(api.complete).not.toHaveBeenCalled()
  })
  it.each([
    ['空对象', {}], ['缺少材料', { METAL: { percentage: 100 }, SEWING: { percentage: 100 }, ASSEMBLY: { percentage: 100 } }],
    ['进度不足', { ...progress(), METAL: { percentage: 99 } }],
  ])('%s时禁止预览和提交', async (_name, value) => {
    api.progress.mockResolvedValue([{ schedule_id: 'schedule-1', progress: value }])
    const wrapper = await createView()
    expect(completionItem(wrapper).props('disabled')).toBe(true)
    await openCompletion(wrapper)
    expect(api.preview).not.toHaveBeenCalled()
  })
  it.each(['DRAFT', 'PENDING_VALIDATION', 'READY', 'COMPLETED', 'CANCELLED', 'PAUSED'])('任务%s时不允许完成', async status => {
    api.schedules.mockResolvedValue({ data: [schedule({ source_current_status: status })], meta: { total: 1 } })
    const wrapper = await createView()
    await openCompletion(wrapper)
    expect(api.preview).not.toHaveBeenCalled()
  })
  it('无完成权限时不读取预览', async () => {
    state.finish = false
    const wrapper = await createView()
    await openCompletion(wrapper)
    expect(api.preview).not.toHaveBeenCalled()
  })
  it('新预览发现进度下降时阻止打开完成窗口', async () => {
    const current = preview(); current.progress.ASSEMBLY.percentage = 99
    api.preview.mockResolvedValue(current)
    const wrapper = await createView()
    await openCompletion(wrapper)
    expect(dialog(wrapper).props('modelValue')).toBe(false)
    expect(api.complete).not.toHaveBeenCalled()
  })
  it('预览读取失败明确报错，不打开空窗口', async () => {
    api.preview.mockRejectedValue(responseError(403, '超出操作范围'))
    const message = vi.spyOn(ElMessage, 'error')
    const wrapper = await createView()
    await openCompletion(wrapper)
    expect(message).toHaveBeenCalledWith('超出操作范围')
    expect(dialog(wrapper).props('modelValue')).toBe(false)
  })
  it('只提交说明与预览版本，不覆盖数量或批次', async () => {
    const wrapper = await createView(); await openCompletion(wrapper)
    dialog(wrapper).vm.$emit('confirm', '  核对完成  '); await flushPromises()
    expect(api.complete).toHaveBeenCalledWith('schedule-1', { task_etag: '"task-v2"', reason: '核对完成' }, '"schedule-v1"')
    expect(dialog(wrapper).props('modelValue')).toBe(true)
    expect(dialog(wrapper).props('result')).toEqual(result())
    expect(api.schedules).toHaveBeenCalledTimes(2)
    dialog(wrapper).vm.$emit('confirm', '重复'); await flushPromises()
    expect(api.complete).toHaveBeenCalledOnce()
  })
  it.each([false, true])('仅can_sync=%s并有销售版本时发送销售版本', async canSync => {
    const current = preview(); current.sales_order = { id: 'sales-1', order_number: 'SO1', status: 'FULFILLING', status_display: '履约中', etag: '"sales-v3"', can_sync: canSync, reason: '' }
    api.preview.mockResolvedValue(current)
    const wrapper = await createView(); await openCompletion(wrapper)
    dialog(wrapper).vm.$emit('confirm', '核对完成'); await flushPromises()
    expect(api.complete.mock.calls[0]![1].sales_order_etag).toBe(canSync ? '"sales-v3"' : undefined)
  })
  it('提交中只传递处理中状态，不提前显示成功，并阻止重复提交', async () => {
    let resolveCompletion: (value: CompleteScheduleResult) => void = () => {}
    api.complete.mockImplementation(() => new Promise(resolve => { resolveCompletion = resolve }))
    const wrapper = await createView(); await openCompletion(wrapper)
    dialog(wrapper).vm.$emit('confirm', '核对完成'); await flushPromises()
    expect(dialog(wrapper).props('submitting')).toBe(true)
    expect(dialog(wrapper).props('result')).toBeNull()
    dialog(wrapper).vm.$emit('confirm', '重复'); await flushPromises()
    expect(api.complete).toHaveBeenCalledOnce()
    resolveCompletion(result()); await flushPromises()
    expect(dialog(wrapper).props('result').sales_sync.status).toBe('SKIPPED')
    expect(dialog(wrapper).props('modelValue')).toBe(true)
  })
  it('412明确拒绝保留表单，不声称成功', async () => {
    api.complete.mockRejectedValue(responseError(412, '版本已变化'))
    const wrapper = await createView(); await openCompletion(wrapper)
    dialog(wrapper).vm.$emit('confirm', '核对完成'); await flushPromises()
    expect(dialog(wrapper).props('error')).toBe('版本已变化')
    expect(dialog(wrapper).props('uncertain')).toBe(false)
    expect(dialog(wrapper).props('result')).toBeNull()
    expect(api.schedules).toHaveBeenCalledOnce()
  })
  it.each([new AxiosError('timeout'), responseError(502, 'proxy failure')])('未收到可靠结果时标记待核实，禁止直接重发', async error => {
    api.complete.mockRejectedValue(error)
    const wrapper = await createView(); await openCompletion(wrapper)
    dialog(wrapper).vm.$emit('confirm', '核对完成'); await flushPromises()
    expect(dialog(wrapper).props('uncertain')).toBe(true)
    expect(dialog(wrapper).props('error')).toContain('刷新列表核实')
    dialog(wrapper).vm.$emit('confirm', '重发'); await flushPromises()
    expect(api.complete).toHaveBeenCalledOnce()
    expect(dialog(wrapper).props('result')).toBeNull()
  })
})

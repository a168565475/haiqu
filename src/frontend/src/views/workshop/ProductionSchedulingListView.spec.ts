import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ProductionSchedulingListView from './ProductionSchedulingListView.vue'
import type { CompleteScheduleResult, ProductionSchedule, ScheduleCompletionPreview } from '@/types/productionScheduling'

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

describe('计划排产列表进度列', () => {
  it('在计划日期范围后显示四行对应进度，材料入库固定为 100%', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/workshop/ProductionSchedulingListView.vue'), 'utf8')
    expect(source.indexOf('label="进度"')).toBeGreaterThan(source.indexOf('label="计划日期范围"'))
    expect(source).toContain("if (key === 'MATERIAL') return '100%'")
    for (const key of ['METAL', 'SEWING', 'ASSEMBLY']) expect(source).toContain(`progressDisplay(row, '${key}')`)
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

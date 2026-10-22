import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ProductionSchedulingDetailView from './ProductionSchedulingDetailView.vue'
import type { ScheduleExecutionSummary } from '@/types/scheduleExecution'

const api = vi.hoisted(() => ({ fetch: vi.fn(), summary: vi.fn(), voidSchedule: vi.fn(), push: vi.fn() }))
const state = vi.hoisted(() => ({ route: {} as { params: { scheduleId: string } }, permissions: new Set<string>() }))
vi.mock('@/api/productionScheduling', () => ({ fetchSchedule: api.fetch, voidSchedule: api.voidSchedule, scheduleProductImageUrl: () => '/product.png' }))
vi.mock('@/api/scheduleExecution', () => ({ fetchScheduleExecutionSummary: api.summary }))
vi.mock('vue-router', () => ({ useRoute: () => state.route, useRouter: () => ({ push: api.push }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: false }, hasPermission: (permission: string) => state.permissions.has(permission) }) }))

function schedule(id = 'schedule-1') {
  return { id, schedule_number: 'PC-001', production_task_id: 'task-1', record_status: 'ACTIVE', record_status_display: '有效', source_current_status: 'READY', source_is_archived: false, version: 1,
    source: { task_number: 'HT-001', delivery_date: '2026-11-05' }, created_by: { id: 'employee-1', name: '业务员' }, created_at: '2026-10-20',
    products: [{ id: 'schedule-product-1', product_line_id: 'product-line-1', line_number: 1, planned_quantity: 1000, source_quantity: 1000, unit_name: '套', image_file_id: null,
      product: { product_name: '导演椅', item_number: 'XY-144', specification: '47×55×79 cm 酒红色 PE', specification_display: '47×55×79 cm', color_name: '酒红色', material: 'PE' },
      material_inbound_date: '2026-10-21', metal_return_date: '2026-10-27', sewing_return_date: '2026-10-29', finished_inbound_date: '2026-11-02', crafts: [],
    }],
  }
}
function summary(id = 'schedule-1'): ScheduleExecutionSummary {
  return { schedule_id: id, products: [{ schedule_product_id: 'schedule-product-1', internal_plans: [], estimated_wage: '100.00', reported_amount: '0.00', estimated_amount_status: 'READY', reported_amount_status: 'READY', outsourcing: { allowed: true, records: [], planned_amount: '20.00' }, material_issues: { allowed: true, records: [] } }],
    totals: { estimated_wage: '100.00', reported_amount: '0.00', outsourcing_planned_amount: '20.00', complete_scope: true, reason: '' },
  }
}
const wrappers: ReturnType<typeof mount>[] = []
async function createView() {
  const wrapper = mount(ProductionSchedulingDetailView, {
    global: { plugins: [ElementPlus], stubs: { ProductionTimeline: true, ScheduleExecutionOverview: true, AppWindowDialog: { template: '<div><slot /><slot name="footer" /></div>' } } },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
beforeEach(() => {
  vi.clearAllMocks()
  state.route = reactive({ params: { scheduleId: 'schedule-1' } })
  state.permissions = new Set(['production_scheduling.change_productionschedule', 'production_scheduling.void_productionschedule'])
  api.fetch.mockResolvedValue({ data: schedule(), etag: '"v1"' })
  api.summary.mockResolvedValue(summary())
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('排产详情执行汇总接入', () => {
  it('分别展示规格、颜色、材质和后端汇总金额', async () => {
    const wrapper = await createView()
    const fields = wrapper.findAll('.detail-product-main dl > div')
    expect(fields.find(field => field.get('dt').text() === '规格')?.get('dd').text()).toBe('47×55×79 cm')
    expect(fields.find(field => field.get('dt').text() === '颜色')?.get('dd').text()).toBe('酒红色')
    expect(fields.find(field => field.get('dt').text() === '材质')?.get('dd').text()).toBe('PE')
    expect(wrapper.get('[data-testid="schedule-estimated-total"]').text()).toBe('¥100.00')
    expect(wrapper.get('[data-testid="schedule-reported-total"]').text()).toBe('¥0.00')
    expect(api.summary).toHaveBeenCalledWith('schedule-1')
  })
  it('总额不可用时不拿产品部分金额拼出总额', async () => {
    const value = summary()
    value.totals = { estimated_wage: null, reported_amount: null, outsourcing_planned_amount: null, complete_scope: false, reason: '部分车间无查看权限，无法汇总全部金额。' }
    api.summary.mockResolvedValue(value)
    const wrapper = await createView()
    expect(wrapper.get('[data-testid="schedule-estimated-total"]').text()).toBe('—')
    // 用户此前已要求移除汇总提示；缺值仍保持未知。
    expect(wrapper.text()).not.toContain('部分车间无查看权限')
    expect(wrapper.get('[data-testid="schedule-outsourcing-total"]').text()).toBe('—')
  })
  it('规格清理后为空时显示缺值，不回退原拼接规格', async () => {
    const value = schedule()
    value.products[0]!.product.specification_display = ''
    api.fetch.mockResolvedValue({ data: value, etag: '"v1"' })
    const wrapper = await createView()
    expect(wrapper.get('[data-field="specification"]').text()).toBe('—')
    expect(wrapper.get('[data-field="color"]').text()).toBe('酒红色')
    expect(wrapper.get('[data-field="material"]').text()).toBe('PE')
  })
  it('关联加载失败保留基本详情与操作并可单独重试', async () => {
    api.summary.mockRejectedValueOnce(new Error('network unavailable'))
    const wrapper = await createView()
    expect(wrapper.text()).toContain('导演椅')
    expect(wrapper.text()).toContain('整单作废')
    expect(wrapper.text()).toContain('编辑排产')
    expect(wrapper.get('[data-testid="schedule-reported-total"]').text()).toBe('—')
    const retry = wrapper.findAll('button').find(button => button.text() === '重试关联信息')!
    await retry.trigger('click')
    await flushPromises()
    expect(api.fetch).toHaveBeenCalledOnce()
    expect(api.summary).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[data-testid="schedule-reported-total"]').text()).toBe('¥0.00')
  })
  it('切换排产后忽略旧汇总响应', async () => {
    let resolveOld: (value: ScheduleExecutionSummary) => void = () => {}
    api.summary.mockImplementationOnce(() => new Promise<ScheduleExecutionSummary>(resolve => { resolveOld = resolve }))
    const wrapper = await createView()
    api.fetch.mockResolvedValue({ data: schedule('schedule-2'), etag: '"v2"' })
    const next = summary('schedule-2')
    next.totals.reported_amount = '88.00'
    api.summary.mockResolvedValue(next)
    state.route.params.scheduleId = 'schedule-2'
    await flushPromises()
    resolveOld(summary())
    await flushPromises()
    expect(wrapper.get('[data-testid="schedule-reported-total"]').text()).toBe('¥88.00')
  })
  it('整单作废继续携带原ETag和原因，成功后刷新关联信息', async () => {
    api.voidSchedule.mockResolvedValue({ data: { ...schedule(), record_status: 'VOID', record_status_display: '已作废' }, etag: '"v2"' })
    const wrapper = await createView()
    await wrapper.findAll('button').find(button => button.text() === '整单作废')!.trigger('click')
    await wrapper.get('textarea').setValue('计划调整')
    await wrapper.findAll('button').find(button => button.text() === '确认作废')!.trigger('click')
    await flushPromises()
    expect(api.voidSchedule).toHaveBeenCalledWith('schedule-1', '计划调整', '"v1"')
    expect(api.summary).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('button').some(button => button.text() === '编辑排产')).toBe(false)
  })
})

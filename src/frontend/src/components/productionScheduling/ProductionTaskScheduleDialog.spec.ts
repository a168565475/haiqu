import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus, { ElCheckbox, ElInputNumber, ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import BatchScheduleFillDialog from './BatchScheduleFillDialog.vue'
import ProductionTaskScheduleDialog from './ProductionTaskScheduleDialog.vue'
import type { ScheduleTaskCandidate, ScheduleTaskProduct } from '@/types/productionScheduling'

const api = vi.hoisted(() => ({ fetchTask: vi.fn(), fetchOptions: vi.fn(), create: vi.fn() }))
vi.mock('@/api/productionScheduling', () => ({
  fetchTaskCandidate: api.fetchTask, fetchScheduleOptions: api.fetchOptions,
  createSchedule: api.create, scheduleProductImageUrl: () => '/product.png',
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

function product(id: string, status: ScheduleTaskProduct['bom_status']): ScheduleTaskProduct {
  return { id, product_id: null, line_number: 1, product_number: '', product_code: '', item_number: '',
    product_name: id, specification: '', color_name: '', color_code: '', quantity: 10,
    unit_id: 'piece', unit_name: '件', image_file_id: null, bom_status: status,
    bom_status_display: status === 'VERIFIED' ? '已确认' : status === 'NOT_CREATED' ? '未建立' : '待确认',
    purchase_status: 'NOT_STARTED', purchase_status_display: '未发起' }
}
function candidate(): ScheduleTaskCandidate {
  return { id: 'task-1', task_number: 'HT-001', order_number: '', sales_order_number: null,
    customer_id: '', customer_name: '', order_date: '2026-11-05', delivery_date: '2026-11-30',
    salesperson_name: '', follower_names: [], planned_start_date: null, planned_end_date: null,
    status: 'READY', status_display: '已接单', product_count: 3, selectable: true, unselectable_reason: '',
    existing_schedule_id: null, source_revision_hash: 'revision-1', scheduling_ready: true,
    scheduling_blockers: [], product_summaries: [],
    products: [product('待确认产品', 'PENDING_CONFIRMATION'), product('已确认产品', 'VERIFIED'), product('未建BOM产品', 'NOT_CREATED')] }
}
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  vi.clearAllMocks()
  api.fetchTask.mockResolvedValue(candidate())
  api.fetchOptions.mockResolvedValue({ crafts: [
    { id: 'metal', name: '金工', craft_type: 'INTERNAL', craft_type_display: '厂内工艺', plan_category: 'METAL', workshop_name: '金工车间' },
    { id: 'print', name: '丝印', craft_type: 'EXTERNAL', craft_type_display: '厂外工艺', plan_category: null, workshop_name: null },
  ], plan_categories: [], customers: [] })
  api.create.mockResolvedValue({ data: { id: 'schedule-1' } })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); ElMessage.closeAll() })

async function render() {
  const wrapper = mount(ProductionTaskScheduleDialog, {
    props: { modelValue: false, task: { id: 'task-1', task_number: 'HT-001' } },
    global: { plugins: [ElementPlus, createPinia()], stubs: { AppWindowDialog: { template: '<div><slot /><slot name="footer" /></div>' }, BatchScheduleFillDialog: true } },
  })
  wrappers.push(wrapper)
  await wrapper.setProps({ modelValue: true })
  await flushPromises()
  return wrapper
}

describe('生产任务产品排产弹窗', () => {
  it('部分 BOM 确认时只默认选择可排产品，保留不可排产品并显示原因', async () => {
    const wrapper = await render()
    expect(wrapper.findAll('.schedule-product-row')).toHaveLength(3)
    const choices = wrapper.findAllComponents(ElCheckbox)
    expect(choices.map(choice => choice.props('modelValue'))).toEqual([false, true, false])
    expect(choices.map(choice => choice.props('disabled'))).toEqual([true, false, true])
    expect(wrapper.get('.schedule-editor__heading').text()).toContain('已确认产品 · 排产信息')
    expect(wrapper.text()).toContain('最新 BOM 未确认，暂不可排产')
    expect(wrapper.text()).toContain('未建立 BOM，暂不可排产')

    await wrapper.findAll('.schedule-product-row')[0]!.trigger('click')
    expect(wrapper.findComponent(ElInputNumber).props('disabled')).toBe(true)
    choices[0]!.vm.$emit('update:modelValue', true)
    await flushPromises()
    expect(choices[0]!.props('modelValue')).toBe(false)

    wrapper.findComponent(BatchScheduleFillDialog).vm.$emit('apply', {
      material_inbound_date: '2026-11-06', metal_return_date: '2026-11-07',
      sewing_return_date: '2026-11-08', finished_inbound_date: '2026-11-09', internal_craft_ids: ['metal'],
    })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '保存排产')!.trigger('click')
    await flushPromises()
    expect(api.create).toHaveBeenCalledWith({ production_task_id: 'task-1', source_revision_hash: 'revision-1',
      client_request_id: expect.any(String), items: [{ product_line_id: '已确认产品', planned_quantity: 10,
        material_inbound_date: '2026-11-06', metal_return_date: '2026-11-07', sewing_return_date: '2026-11-08',
        finished_inbound_date: '2026-11-09', craft_ids: ['metal'] }] })
  })

  it('没有已确认产品时保留候选说明并禁用保存', async () => {
    const task = candidate()
    task.products = [product('待确认产品', 'PENDING_CONFIRMATION')]
    task.scheduling_ready = false
    task.scheduling_blockers = ['至少一个产品的最新 BOM 已确认']
    api.fetchTask.mockResolvedValue(task)
    const wrapper = await render()
    expect(wrapper.findComponent(ElCheckbox).props('modelValue')).toBe(false)
    expect(wrapper.findComponent(ElCheckbox).props('disabled')).toBe(true)
    expect(wrapper.findAll('button').find(button => button.text() === '保存排产')!.attributes('disabled')).toBeDefined()
    expect(api.create).not.toHaveBeenCalled()
  })
})

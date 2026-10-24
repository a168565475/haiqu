import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElDatePicker, ElInputNumber, ElMessage, ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ProductionSchedulingFormView from './ProductionSchedulingFormView.vue'
import type { ScheduleOptions, ScheduleTaskCandidate, ScheduleTaskProduct, ScheduleWriteItem } from '@/types/productionScheduling'

const api = vi.hoisted(() => ({
  fetchSchedule: vi.fn(), fetchOptions: vi.fn(), fetchTask: vi.fn(),
  update: vi.fn(), create: vi.fn(), push: vi.fn(), replace: vi.fn(),
}))
vi.mock('@/api/productionScheduling', () => ({
  fetchSchedule: api.fetchSchedule, fetchScheduleOptions: api.fetchOptions,
  fetchTaskCandidate: api.fetchTask, updateSchedule: api.update,
  createSchedulesBatch: api.create, scheduleProductImageUrl: () => '/product.png',
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { scheduleId: 'schedule-1' } }),
  useRouter: () => ({ push: api.push, replace: api.replace }),
}))

const options: ScheduleOptions = {
  crafts: [
    { id: 'metal', name: '管材加工', craft_type: 'INTERNAL', craft_type_display: '厂内工艺', plan_category: 'METAL', workshop_name: '金工车间' },
    { id: 'print', name: '丝印', craft_type: 'EXTERNAL', craft_type_display: '厂外工艺', plan_category: null, workshop_name: null },
  ],
  plan_categories: [], customers: [],
}

function product(id: string, line: number, quantity: number): ScheduleTaskProduct {
  return {
    id, product_id: `product-${line}`, line_number: line, product_number: `P-${line}`,
    product_code: `CODE-${line}`, item_number: `ITEM-${line}`, product_name: `产品${line}`,
    specification: '47×55×79 cm', color_name: '酒红色', color_code: 'RED', quantity,
    unit_id: 'unit-1', unit_name: '套', image_file_id: null,
    bom_status: 'VERIFIED', bom_status_display: '已确认',
    purchase_status: 'ORDER_COMPLETED', purchase_status_display: '已完成采购',
  }
}

function source(): ScheduleTaskCandidate {
  return {
    id: 'task-1', task_number: 'HT-001', order_number: 'ORDER-1', sales_order_number: null,
    customer_id: 'customer-1', customer_name: '客户', order_date: '2026-10-01', delivery_date: '2026-11-05',
    salesperson_name: '业务员', follower_names: ['跟单员'], planned_start_date: '2026-10-20', planned_end_date: '2026-11-02',
    status: 'IN_PRODUCTION', status_display: '生产中', product_count: 2,
    selectable: false, unselectable_reason: '已有有效排产计划', existing_schedule_id: 'schedule-1',
    source_revision_hash: 'current-in-production-revision', product_summaries: [],
    products: [product('line-1', 1, 100), product('line-2', 2, 60)],
  }
}

function savedItems(): ScheduleWriteItem[] {
  return [
    { product_line_id: 'line-1', planned_quantity: 80, material_inbound_date: '2026-10-21', metal_return_date: '2026-10-24', sewing_return_date: '2026-10-27', finished_inbound_date: '2026-11-01', craft_ids: ['metal', 'print'] },
    { product_line_id: 'line-2', planned_quantity: 30, material_inbound_date: '2026-10-22', metal_return_date: '2026-10-25', sewing_return_date: '2026-10-28', finished_inbound_date: '2026-11-02', craft_ids: ['metal'] },
  ]
}

const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  vi.clearAllMocks()
  api.fetchOptions.mockResolvedValue(options)
  api.fetchTask.mockResolvedValue(source())
  api.fetchSchedule.mockResolvedValue({
    etag: '"schedule-v3"',
    data: {
      id: 'schedule-1', production_task_id: 'task-1', source_revision_hash: 'saved-ready-revision',
      products: savedItems().reverse().map(({ craft_ids, ...item }) => ({
        ...item,
        crafts: craft_ids.map(id => ({ ...options.crafts.find(craft => craft.id === id)!, is_active: true })),
      })),
    },
  })
  api.update.mockResolvedValue({ data: { id: 'schedule-1' }, etag: '"schedule-v4"' })
})
afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  ElMessage.closeAll()
})

describe('进行中排产编辑回填', () => {
  it('按产品行回填数量、四个日期和内外工艺，并使用当前来源版本及原ETag保存', async () => {
    const wrapper = mount(ProductionSchedulingFormView, {
      global: {
        plugins: [ElementPlus],
        stubs: { ProductionTaskSelectDialog: true, BatchScheduleFillDialog: true, AppWindowDialog: true },
      },
    })
    wrappers.push(wrapper)
    await flushPromises()

    expect(api.fetchSchedule).toHaveBeenCalledWith('schedule-1')
    expect(api.fetchTask).toHaveBeenCalledWith('task-1')
    expect(wrapper.get('h1').text()).toBe('编辑排产')
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    expect(wrapper.findAllComponents(ElInputNumber).map(input => input.props('modelValue'))).toEqual([80, 30])
    expect(wrapper.findAllComponents(ElDatePicker).map(input => input.props('modelValue'))).toEqual([
      '2026-10-21', '2026-10-24', '2026-10-27', '2026-11-01',
      '2026-10-22', '2026-10-25', '2026-10-28', '2026-11-02',
    ])
    expect(wrapper.findAllComponents(ElSelect).map(select => select.props('modelValue'))).toEqual([
      ['metal'], ['print'], ['metal'], [],
    ])
    expect(wrapper.findAll('.craft-select__summary').map(summary => summary.text())).toEqual(['管材加工', '丝印', '管材加工'])

    await wrapper.findAll('button').find(button => button.text() === '保存排产')!.trigger('click')
    await flushPromises()

    expect(api.update).toHaveBeenCalledWith('schedule-1', {
      source_revision_hash: 'current-in-production-revision', items: savedItems(),
    }, '"schedule-v3"')
    expect(api.create).not.toHaveBeenCalled()
    expect(api.replace).toHaveBeenCalledWith('/workshop/scheduling/schedule-1')
  })
})

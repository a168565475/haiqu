import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus, { ElCheckbox, ElDatePicker, ElInputNumber, ElMessage, ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ProductionSchedulingFormView from './ProductionSchedulingFormView.vue'
import ProductionTaskSelectDialog from '@/components/productionScheduling/ProductionTaskSelectDialog.vue'
import BatchScheduleFillDialog from '@/components/productionScheduling/BatchScheduleFillDialog.vue'
import type { ScheduleOptions, ScheduleTaskCandidate, ScheduleTaskProduct, ScheduleWriteItem } from '@/types/productionScheduling'

const api = vi.hoisted(() => ({
  fetchSchedule: vi.fn(), fetchOptions: vi.fn(), fetchTask: vi.fn(),
  update: vi.fn(), create: vi.fn(), push: vi.fn(), replace: vi.fn(),
  routeParams: { scheduleId: 'schedule-1' } as Record<string, string>,
}))
vi.mock('@/api/productionScheduling', () => ({
  fetchSchedule: api.fetchSchedule, fetchScheduleOptions: api.fetchOptions,
  fetchTaskCandidate: api.fetchTask, updateSchedule: api.update,
  createSchedulesBatch: api.create, scheduleProductImageUrl: () => '/product.png',
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: api.routeParams }),
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
  api.routeParams.scheduleId = 'schedule-1'
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
  api.create.mockResolvedValue({ data: [{ id: 'schedule-1' }] })
})
afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  ElMessage.closeAll()
})

describe('进行中排产编辑回填', () => {
  async function render() {
    const wrapper = mount(ProductionSchedulingFormView, {
      global: { plugins: [ElementPlus, createPinia()], stubs: { ProductionTaskSelectDialog: true, BatchScheduleFillDialog: true, AppWindowDialog: true } },
    })
    wrappers.push(wrapper)
    await flushPromises()
    return wrapper
  }

  it('新增默认只选最新 BOM 已确认产品，未确认和未建立产品保持可见且禁选', async () => {
    delete api.routeParams.scheduleId
    const task = source()
    task.products = [product('line-1', 1, 100),
      { ...product('line-2', 2, 60), bom_status: 'PENDING_CONFIRMATION', bom_status_display: '待确认' },
      { ...product('line-3', 3, 40), bom_status: 'NOT_CREATED', bom_status_display: '未建立' }]
    const wrapper = await render()
    wrapper.findComponent(ProductionTaskSelectDialog).vm.$emit('select', [task])
    await flushPromises()

    expect(wrapper.findAll('tbody tr')).toHaveLength(3)
    const choices = wrapper.findAllComponents(ElCheckbox)
    expect(choices.map(choice => choice.props('modelValue'))).toEqual([true, false, false])
    expect(choices.map(choice => choice.props('disabled'))).toEqual([false, true, true])
    expect(wrapper.text()).toContain('最新 BOM 未确认，暂不可排产')
    expect(wrapper.text()).toContain('未建立 BOM，暂不可排产')
    expect(wrapper.findAllComponents(ElInputNumber).map(input => input.props('disabled'))).toEqual([false, true, true])

    wrapper.findComponent(BatchScheduleFillDialog).vm.$emit('apply', { ...savedItems()[0], internal_craft_ids: ['metal'] })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().startsWith('批量生成排产'))!.trigger('click')
    await flushPromises()
    expect(api.create).toHaveBeenCalledWith({ schedules: [{
      production_task_id: 'task-1', source_revision_hash: task.source_revision_hash,
      client_request_id: expect.any(String), items: [{ ...savedItems()[0], planned_quantity: 100, craft_ids: ['metal'] }],
    }] })
  })

  it('编辑保留原计划勾选，并允许勾选后续已确认产品补排', async () => {
    const saved = savedItems()[0]!
    api.fetchSchedule.mockResolvedValue({ etag: '"schedule-v3"', data: {
      id: 'schedule-1', production_task_id: 'task-1', products: [{ ...saved, crafts: options.crafts }],
    } })
    const wrapper = await render()
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    expect(wrapper.findAllComponents(ElCheckbox).map(choice => choice.props('modelValue'))).toEqual([true, false])
    await wrapper.findAll('input[type="checkbox"]')[1]!.setValue(true)
    wrapper.findComponent(BatchScheduleFillDialog).vm.$emit('apply', { ...saved, internal_craft_ids: ['metal'], external_craft_ids: ['print'] })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '保存排产')!.trigger('click')
    await flushPromises()
    expect(api.update).toHaveBeenCalledWith('schedule-1', { source_revision_hash: 'current-in-production-revision', items: [saved,
      { ...saved, product_line_id: 'line-2', planned_quantity: 60 }],
    }, '"schedule-v3"')
  })

  it('已排产品最新 BOM 变为未确认时保留原勾选与数据，明确阻止保存而非悄悄丢弃', async () => {
    const task = source()
    task.products![0]!.bom_status = 'PENDING_CONFIRMATION'
    task.products![0]!.bom_status_display = '待确认'
    api.fetchTask.mockResolvedValue(task)
    const warning = vi.spyOn(ElMessage, 'warning')
    const wrapper = await render()
    const choices = wrapper.findAllComponents(ElCheckbox)
    expect(choices.map(choice => choice.props('modelValue'))).toEqual([true, true])
    expect(choices[0]!.props('disabled')).toBe(true)
    expect(wrapper.findAllComponents(ElInputNumber)[0]!.props('modelValue')).toBe(80)
    await wrapper.findAll('button').find(button => button.text() === '保存排产')!.trigger('click')
    await flushPromises()
    expect(warning).toHaveBeenCalledWith(expect.stringContaining('最新 BOM 未确认'))
    expect(api.update).not.toHaveBeenCalled()
    warning.mockRestore()
  })

  it('按产品行回填数量、四个日期和内外工艺，并使用当前来源版本及原ETag保存', async () => {
    const wrapper = mount(ProductionSchedulingFormView, {
      global: {
        plugins: [ElementPlus, createPinia()],
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

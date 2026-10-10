import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import WorkReportDayListView from './WorkReportDayListView.vue'

const api = vi.hoisted(() => ({ context: vi.fn(), list: vi.fn(), detail: vi.fn() }))
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }))
const auth = vi.hoisted(() => ({
  user: { is_superuser: true, permissions: [] as string[] },
  hasPermission: vi.fn((permission: string) => auth.user.permissions.includes(permission)),
}))
const route = vi.hoisted(() => ({
  query: { schedule_product_id: 'schedule-product-1', workshop_id: 'workshop-1' } as Record<string, string>,
}))

vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => router }))
vi.mock('@/api/workshopReporting', () => ({
  fetchReportingContext: api.context,
  fetchWorkReportDay: api.detail,
  fetchWorkReportDays: api.list,
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => auth,
}))

beforeEach(() => {
  vi.clearAllMocks()
  auth.user = { is_superuser: true, permissions: [] }
  route.query = { schedule_product_id: 'schedule-product-1', workshop_id: 'workshop-1' }
  api.context.mockResolvedValue({
    schedule_product: {
      id: 'schedule-product-1', product_line_id: 'line-1', production_task_id: 'task-1',
      task_number: 'HT26050', order_number: 'SO-202609-000076',
      product_name: '六边形围炉桌', product_number: 'FLOW260917-P020',
      product_specification: '标准款', product_color: '黑色', planned_quantity: '350',
      order_quantity: '350', unit_name: '件',
    },
    schedule_products: [],
    workshops: [{ id: 'workshop-1', name: '金工车间' }, { id: 'workshop-2', name: '裁剪车间' }],
    crafts: [
      { id: 'craft-1', name: '管材加工', workshop_id: 'workshop-1', plan_category: 'METAL' },
      { id: 'craft-2', name: '裁剪', workshop_id: 'workshop-2', plan_category: 'CUTTING' },
    ],
    operations: [], bom_items: [], employees: [],
  })
  api.list.mockResolvedValue({
    data: [
      {
        production_date: '2026-09-28', report_count: 3, order_count: 1, product_count: 1,
        employee_count: 3, line_count: 9, total_amount: '12.6', last_saved_at: '2026-09-28T08:00:00Z',
      },
      {
        production_date: '2026-09-27', report_count: 2, order_count: 1, product_count: 1,
        employee_count: 2, line_count: 7, total_amount: '8.32', last_saved_at: '2026-09-27T08:00:00Z',
      },
    ],
    meta: { page: 1, page_size: 20, total: 2, total_pages: 1 },
  })
  api.detail.mockResolvedValue({
    data: [{
      id: 'report-1', report_number: 'BG-202609-000001', production_date: '2026-09-28',
      production_task: { id: 'task-1', task_number: 'HT26050', order_number: 'SO-202609-000076' },
      product: { name: '六边形围炉桌', number: 'FLOW260917-P020' },
      product_line_id: 'line-1', schedule_product_id: 'schedule-product-1',
      workshop: { id: 'workshop-1', name: '金工车间' }, scheme_id: 'scheme-1', scheme_version: 1,
      revision: 1, recorder: '业务员 A', total_amount: '5.4', updated_by: '业务员 A', line_count: 1,
      created_at: '2026-09-28T08:16:00Z', updated_at: '2026-09-28T08:16:00Z',
      lines: [{
        id: 'line-1', line_number: 1, scheme_line_id: 'scheme-line-1', work_item_id: 'work-item-1',
        workshop_employee_id: 'employee-1', employee_name: '员工甲', production_line: null,
        display_name: '下伸缩管-18*0.8*440', craft_name: '管材加工', operation_name: '管口冲员', unit_name: '',
        quantity: '12', order_quantity_snapshot: 350,
        cumulative_quantity: '36', required_quantity: '1400', unit_price: '0.2', amount: '2.4',
      }],
    }],
    meta: { page: 1, page_size: 100, total: 1, total_pages: 1 },
  })
})

it('只读账号不显示新增按钮', async () => {
    auth.user = { is_superuser: false, permissions: ['workshop_reporting.view_workreport'] }
    const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.find('.wr-report-records__create').exists()).toBe(false)
    wrapper.unmount()
})

it('同一天超过一页时继续加载全部保存记录', async () => {
    api.detail.mockImplementation((_date, params: { page: number }) => Promise.resolve(
      params.page === 1
        ? { data: [], meta: { page: 1, page_size: 100, total: 101, total_pages: 2 } }
        : {
            data: [{
              id: 'report-101', report_number: 'BG-202609-000101', production_date: '2026-09-28',
              recorder: '业务员 B', total_amount: '1.2', updated_at: '2026-09-28T10:00:00Z', lines: [],
            }],
            meta: { page: 2, page_size: 100, total: 101, total_pages: 2 },
          },
    ))
    const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(api.detail).toHaveBeenCalledWith('2026-09-28', expect.objectContaining({ page: 2 }))
    expect(wrapper.text()).toContain('BG-202609-000101')
    wrapper.unmount()
})

it('没有排产产品上下文时返回内部计划选择产品', async () => {
    route.query = {}
    const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(router.replace).toHaveBeenCalledWith({ name: 'workshop-metalworking-plan' })
    expect(api.context).not.toHaveBeenCalled()
    wrapper.unmount()
})

describe('按车间和日期查看报工记录', () => {
  it('默认选择最后一个报工日，并在右侧直接显示该车间明细', async () => {
    const wrapper = mount(WorkReportDayListView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(api.context).toHaveBeenCalledWith('schedule-product-1', 'work_report')
    expect(api.list).toHaveBeenCalledWith(expect.objectContaining({
      page: 1,
      page_size: 20,
      schedule_product_id: 'schedule-product-1',
      workshop_id: 'workshop-1',
    }))
    expect(api.detail).toHaveBeenCalledWith('2026-09-28', expect.objectContaining({
      page_size: 100,
      schedule_product_id: 'schedule-product-1',
      workshop_id: 'workshop-1',
    }))
    expect(wrapper.text()).toContain('HT26050')
    expect(wrapper.text()).toContain('六边形围炉桌')
    expect(wrapper.text()).toContain('2026-09-28 · 金工车间')
    expect(wrapper.text()).toContain('需完成次数')
    expect(wrapper.text()).toContain('1,400')
    expect(wrapper.text()).toContain('进度')
    expect(wrapper.text()).toContain('已报 36 / 总需 1,400')
    expect(wrapper.text()).toContain('3%')
    expect(wrapper.text()).not.toContain('累计报工')
    expect(wrapper.find('.el-date-editor').exists()).toBe(false)

    await wrapper.findAll('.wr-report-days-panel__table .el-table__row')[1].trigger('click')
    await flushPromises()
    expect(api.detail).toHaveBeenLastCalledWith('2026-09-27', expect.objectContaining({ workshop_id: 'workshop-1' }))

    const workshopSelect = wrapper.find('.wr-report-context__workshop').findComponent(ElSelect)
    await workshopSelect.setValue('workshop-2')
    workshopSelect.vm.$emit('change', 'workshop-2')
    await flushPromises()
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ workshop_id: 'workshop-2' }))
    expect(api.detail).toHaveBeenLastCalledWith('2026-09-28', expect.objectContaining({ workshop_id: 'workshop-2' }))

    await wrapper.find('.wr-report-records__create').trigger('click')
    expect(router.push).toHaveBeenCalledWith({
      name: 'work-report-new',
      query: { schedule_product_id: 'schedule-product-1', workshop_id: 'workshop-2', craft_id: 'craft-2' },
    })
    wrapper.unmount()
  })
})

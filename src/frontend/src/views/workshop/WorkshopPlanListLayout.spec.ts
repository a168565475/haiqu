import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import WorkshopPlanListView from './WorkshopPlanListView.vue'
import type { ScheduleItem } from '@/types/productionScheduling'

const state = vi.hoisted(() => ({
  route: { name: 'workshop-metalworking-plan', path: '/workshop/metalworking', query: { schedule_id: 'schedule-1' } },
  push: vi.fn(),
  replace: vi.fn(),
  fetchScheduleItems: vi.fn(),
  fetchPlanWageStatuses: vi.fn(),
}))
vi.mock('vue-router', () => ({ useRoute: () => state.route, useRouter: () => ({ push: state.push, replace: state.replace }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: true }, hasPermission: () => true }) }))
vi.mock('@/api/productionScheduling', () => ({ fetchScheduleItems: state.fetchScheduleItems }))
vi.mock('@/api/workshopReporting', () => ({ fetchPlanWageStatuses: state.fetchPlanWageStatuses }))
vi.mock('@/views/workshop/wage-schemes/WageSchemeDetailDialog.vue', () => ({ default: { template: '<div />' } }))

const item: ScheduleItem = {
  id: 'product-plan-1', schedule_id: 'schedule-1', product_line_id: 'line-1', schedule_number: 'PC-1',
  production_task_id: 'task-1', task_number: 'SC-1', sales_order_number: null, customer_name: '客户', customer_id: 'customer-1',
  product: { product_name: '折叠椅', specification: '旧复合规格', specification_display: '45×52×47', color_name: '酒红色', material: '尼龙' },
  planned_quantity: 100, unit_name: '把', image_file_id: null, plan_date: '2026-10-18', craft_names: ['金工'],
  line_number: 1, job_status: 'IN_PROGRESS', job_status_display: '进行中',
}
let wrapper: VueWrapper | undefined

beforeEach(() => {
  vi.clearAllMocks()
  state.route.name = 'workshop-metalworking-plan'
  state.fetchScheduleItems.mockResolvedValue({ data: [item], meta: { total: 1, page: 1, page_size: 50, total_pages: 1 } })
  state.fetchPlanWageStatuses.mockResolvedValue([])
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

async function setup() {
  wrapper = mount(WorkshopPlanListView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  return wrapper
}

describe('内部计划列表布局与独立产品字段', () => {
  it.each([
    ['workshop-metalworking-plan', 'METAL'], ['workshop-cutting-plan', 'CUTTING'],
    ['workshop-sewing-plan', 'SEWING'], ['workshop-assembly-plan', 'ASSEMBLY'],
  ])('%s 共用内容区页签和独立规格、颜色、材质列', async (routeName, category) => {
    state.route.name = routeName
    const view = await setup()
    expect(view.find('.erp-list-filter .internal-plan-tabs').exists()).toBe(false)
    expect(view.get('.erp-list-data .internal-plan-tabs').findAll('[role="tab"]')).toHaveLength(4)
    expect(view.get('.erp-list-heading').text()).toBe('内部计划')
    const headers = view.findAll('.el-table__header th .cell').map(cell => cell.text())
    expect(headers.filter(label => label === '颜色')).toHaveLength(1)
    expect(headers.slice(headers.indexOf('规格'), headers.indexOf('规格') + 3)).toEqual(['规格', '颜色', '材质'])
    const row = view.get('.el-table__body tbody tr').text()
    expect(row).toContain('45×52×47')
    expect(row).not.toContain('旧复合规格')
    expect(row).toContain('酒红色')
    expect(row).toContain('尼龙')
    expect(state.fetchScheduleItems).toHaveBeenCalledWith(expect.objectContaining({ category, schedule_id: 'schedule-1' }))
  })

  it('历史接口缺独立规格或材质时保留原规格并明确空材质，不猜测拆分', async () => {
    state.fetchScheduleItems.mockResolvedValue({ data: [{ ...item, product: { product_name: '折叠椅', specification: '旧规格/原材质', color_name: '蓝色' } }], meta: { total: 1 } })
    const view = await setup()
    const cells = view.findAll('.el-table__body tbody tr td .cell').map(cell => cell.text())
    expect(cells[3]).toBe('旧规格/原材质')
    expect(cells[4]).toBe('蓝色')
    expect(cells[5]).toBe('—')
  })

  it('页签移动后仍按真实路由切换并保留排产上下文', async () => {
    const view = await setup()
    const sewingTab = view.get('.erp-list-data .internal-plan-tabs').findAll('[role="tab"]').find(tab => tab.text() === '车缝计划')!
    await sewingTab.trigger('click')
    expect(state.push).toHaveBeenCalledWith({ name: 'workshop-sewing-plan', query: { schedule_id: 'schedule-1' } })
  })

  it('刷新、重置、应用筛选同组且仍调用既有查询', async () => {
    const view = await setup()
    const actions = view.get('.erp-list-filter-actions').findAll('button')
    expect(actions.map(button => button.text())).toEqual(['刷新', '重置', '应用筛选'])
    await view.get('.schedule-search input').setValue('折叠椅')
    await actions[2]!.trigger('click'); await flushPromises()
    expect(state.fetchScheduleItems).toHaveBeenLastCalledWith(expect.objectContaining({ search: '折叠椅', page: 1 }))
    await actions[1]!.trigger('click'); await flushPromises()
    expect(state.fetchScheduleItems).toHaveBeenLastCalledWith(expect.objectContaining({ search: undefined, page: 1 }))
    expect((view.get('.schedule-search input').element as HTMLInputElement).value).toBe('')
  })
})

import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/productionTasks'
import * as scheduleApi from '@/api/productionScheduling'
import type { ProductionTaskListItem } from '@/types/productionTask'
import type { ScheduleTaskCandidate } from '@/types/productionScheduling'
import ProductionTaskListView from './ProductionTaskListView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/productionTasks', async original => ({
  ...await original<typeof import('@/api/productionTasks')>(),
  fetchProductionTasks: vi.fn(), fetchProductionTaskFilterOptions: vi.fn(),
  fetchProductionTask: vi.fn(), cancelProductionTask: vi.fn(), finishProductionTask: vi.fn(),
}))
vi.mock('@/api/productionScheduling', async original => ({
  ...await original<typeof import('@/api/productionScheduling')>(),
  fetchTaskCandidate: vi.fn(), fetchScheduleOptions: vi.fn(),
}))

function summary(overrides: Partial<ProductionTaskListItem> = {}): ProductionTaskListItem {
  return {
    id: 'task-one', task_number: 'HT-SUMMARY', source_sales_order_number: null, sales_order_id: null,
    delivery_date: '2026-11-30', salesperson: { display_name: '业务甲' }, followers: [{ display_name: '跟单乙' }],
    status: 'READY', status_display: '已接单', bom_status: 'VERIFIED', bom_status_display: '已确认',
    purchase_status: 'NOT_STARTED', purchase_status_display: '未发起',
    allowed_permissions: ['access_control.cancel_productiontask', 'access_control.finish_productiontask'],
    products: [{
      id: 'product-one', customer_product_name: '列表产品甲', product_name: '原产品', item_number: 'ITEM-A',
      specification_display: '大号', customer_specification: '', specification: '', material: '棉',
      customer_color: '红色', color_name: '', color_code: '', quantity: 2,
      unit_id: null, unit_name: '', unit_code: '', product_selection_snapshot: { unit_name: '箱' },
      local_total_amount: '0.1000',
    }, {
      id: 'product-two', product_name: '列表产品乙', item_number: 'ITEM-B', specification: '小号',
      material: '钢', color_name: '蓝色', color_code: '', quantity: 3,
      unit_id: 'piece', unit_name: '件', unit_code: 'PCS', local_total_amount: '0.2000',
    }],
    ...overrides,
  }
}

const filterOptions = { employees: [], salespeople: [], products: [], customers: [], order_sources: [], delivery_methods: [], statuses: [] }
let view: ReturnType<typeof mount> | undefined
let host: HTMLDivElement | undefined

async function render(row = summary()) {
  vi.mocked(api.fetchProductionTasks).mockResolvedValue({ data: [row], meta: { total: 1, total_pages: 1, page: 1, page_size: 50 } })
  host = document.createElement('div')
  document.body.appendChild(host)
  view = mount(ProductionTaskListView, { attachTo: host, global: { plugins: [ElementPlus, createPinia()] } })
  await flushPromises()
  return view
}

async function chooseAction(label: string) {
  const trigger = view!.get('[aria-label="打开生产任务 HT-SUMMARY 操作菜单"]')
  await trigger.trigger('click')
  await flushPromises()
  let item: HTMLElement | undefined
  await vi.waitFor(() => {
    const menu = document.getElementById(trigger.attributes('aria-controls') || '')
    item = Array.from(menu?.querySelectorAll<HTMLElement>('[role="menuitem"]') || []).find(element => element.textContent?.trim() === label)
    expect(item).toBeDefined()
  })
  item!.click()
  await flushPromises()
}

function dialog(title: string) {
  const element = document.querySelector<HTMLElement>(`[role="dialog"][aria-label="${title}"]`)
  expect(element).not.toBeNull()
  return element!
}

async function clickDialogButton(title: string, label: string) {
  const button = Array.from(dialog(title).querySelectorAll<HTMLButtonElement>('button')).find(item => item.textContent?.trim() === label)
  expect(button).toBeDefined()
  button!.click()
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchProductionTaskFilterOptions).mockResolvedValue(filterOptions)
  vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
})
afterEach(() => {
  view?.unmount(); view = undefined
  host?.remove(); host = undefined
  vi.restoreAllMocks()
})

describe('生产任务列表摘要契约', () => {
  it('仅有列表字段仍渲染产品、分单位数量、人民币金额和状态，不加载详情或图片', async () => {
    const page = await render()
    const text = page.get('.el-table__body-wrapper').text()
    for (const label of ['HT-SUMMARY', '手动创建', '列表产品甲 · ITEM-A', '列表产品乙 · ITEM-B', '大号', '小号', '棉', '钢', '红色', '蓝色', '2 箱 / 3 件', '¥ 0.3', '2026-11-30', '业务甲', '跟单乙', '已接单', '已确认', '未发起']) {
      expect(text).toContain(label)
    }
    expect(page.find('.el-table__body-wrapper img').exists()).toBe(false)
    expect(api.fetchProductionTask).not.toHaveBeenCalled()
    expect(scheduleApi.fetchTaskCandidate).not.toHaveBeenCalled()
  })

  it('摘要行打开真实排产弹窗后按任务 ID 独立取得排产产品', async () => {
    const candidate: ScheduleTaskCandidate = {
      id: 'task-one', task_number: 'HT-SUMMARY', order_number: '', sales_order_number: null,
      customer_id: '', customer_name: '', order_date: '2026-11-03', delivery_date: '2026-11-30',
      salesperson_name: '业务甲', follower_names: ['跟单乙'], planned_start_date: null, planned_end_date: null,
      status: 'READY', status_display: '已接单', product_count: 1, selectable: true, unselectable_reason: '',
      existing_schedule_id: null, source_revision_hash: 'revision-one', scheduling_ready: true, product_summaries: [],
      products: [{
        id: 'schedule-product', product_id: null, line_number: 1, product_number: '', product_code: '', item_number: '',
        product_name: '排产接口产品', specification: '排产规格', color_name: '绿色', color_code: '', quantity: 7,
        unit_id: 'piece', unit_name: '件', image_file_id: null, bom_status: 'VERIFIED', bom_status_display: '已确认',
        purchase_status: 'NOT_STARTED', purchase_status_display: '未发起',
      }],
    }
    vi.mocked(scheduleApi.fetchTaskCandidate).mockResolvedValue(candidate)
    vi.mocked(scheduleApi.fetchScheduleOptions).mockResolvedValue({ crafts: [], plan_categories: [], customers: [] })
    await render()
    await chooseAction('计划排产')
    expect(scheduleApi.fetchTaskCandidate).toHaveBeenCalledExactlyOnceWith('task-one')
    expect(scheduleApi.fetchScheduleOptions).toHaveBeenCalledTimes(1)
    expect(dialog('计划排产 · HT-SUMMARY').textContent).toContain('排产接口产品 · 排产信息')
    expect(dialog('计划排产 · HT-SUMMARY').textContent).toContain('订单数量 7 件')
    expect(api.fetchProductionTask).not.toHaveBeenCalled()
  })

  it('摘要行取消仍在提交时读取最新详情和版本', async () => {
    const row = summary()
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: row, etag: 'latest-cancel' } as never)
    await render(row)
    await chooseAction('取消订单')
    expect(api.fetchProductionTask).not.toHaveBeenCalled()
    const reason = dialog('取消订单').querySelector<HTMLTextAreaElement>('textarea')!
    reason.value = '当前订单取消'
    reason.dispatchEvent(new Event('input', { bubbles: true }))
    await flushPromises()
    await clickDialogButton('取消订单', '确认取消')
    expect(api.fetchProductionTask).toHaveBeenCalledExactlyOnceWith('task-one')
    expect(api.cancelProductionTask).toHaveBeenCalledWith('task-one', '当前订单取消', 'latest-cancel')
  })

  it('销售来源摘要行没有总量与批次，完结时使用现查详情并再次校验最新版本', async () => {
    const row = summary({ status: 'IN_PRODUCTION', status_display: '生产中', sales_order_id: 'sales-one' })
    const detail = { ...row, total_quantity: '7', run_batches: [{ batch_number: 'B1', planned_quantity: '7', actual_quantity: '0.0000', good_quantity: '0.0000', status: 'PLANNED', note: '' }] }
    vi.mocked(api.fetchProductionTask)
      .mockResolvedValueOnce({ data: detail, etag: 'before-finish' } as never)
      .mockResolvedValueOnce({ data: detail, etag: 'latest-finish' } as never)
    await render(row)
    await chooseAction('完结生产')
    expect(api.fetchProductionTask).toHaveBeenCalledExactlyOnceWith('task-one')
    expect(Array.from(dialog('结束订单').querySelectorAll<HTMLInputElement>('.finish-quantities input')).map(input => input.value)).toEqual(['7', '7'])
    await clickDialogButton('结束订单', '确认结束')
    expect(api.fetchProductionTask).toHaveBeenCalledTimes(2)
    expect(api.finishProductionTask).toHaveBeenCalledWith('task-one', '', 'latest-finish', {
      actual_quantity: '7', actual_good_quantity: '7',
      run_batches: [{ batch_number: 'B1', planned_quantity: '7', actual_quantity: '7', good_quantity: '7', note: '', status: 'COMPLETED' }],
    })
  })
})

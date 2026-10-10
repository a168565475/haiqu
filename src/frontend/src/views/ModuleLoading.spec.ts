import { beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { ref } from 'vue'
import ElementPlus from 'element-plus'
import * as quotations from '@/api/quotations'
import * as sales from '@/api/salesOrders'
import * as tasks from '@/api/tasks'
import * as complaints from '@/api/complaints'
import * as saved from '@/api/savedViews'
import * as customers from '@/api/customers'
import QuotationList from './quotations/QuotationListView.vue'
import SalesList from './salesOrders/SalesOrderListView.vue'
import TaskCenter from './tasks/TaskCenterView.vue'
import TaskDetail from './tasks/TaskDetailView.vue'
import ComplaintList from './complaints/ComplaintListView.vue'
import RelatedRecords from '@/components/customers/CustomerRelatedRecordsV2.vue'
import DuplicateCenter from './customers/CustomerDuplicateCenterView.vue'

const deniedPermissions = vi.hoisted(() => new Set<string>())
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { taskId: 'task-1' }, query: {} }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: (permission: string) => !deniedPermissions.has(permission), canFor: () => true, moduleCan: () => true, user: null }) }))
vi.mock('@/composables/useOptions', () => ({ useOptions: () => ({ options: ref([]), load: vi.fn().mockResolvedValue([]) }) }))
vi.mock('@/api/quotations', async original => Object.fromEntries(Object.keys(await original<object>()).map(key => [key, vi.fn()])))
vi.mock('@/api/salesOrders', async original => Object.fromEntries(Object.keys(await original<object>()).map(key => [key, vi.fn()])))
vi.mock('@/api/tasks', async original => Object.fromEntries(Object.keys(await original<object>()).map(key => [key, vi.fn()])))
vi.mock('@/api/complaints', async original => Object.fromEntries(Object.keys(await original<object>()).map(key => [key, vi.fn()])))
vi.mock('@/api/savedViews', async original => Object.fromEntries(Object.keys(await original<object>()).map(key => [key, vi.fn()])))
vi.mock('@/api/customers', async original => Object.fromEntries(Object.keys(await original<object>()).map(key => [key, vi.fn()])))

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const list = (total = 0) => ({ data: [], meta: { total } }) as never
const global = { plugins: [ElementPlus] }
beforeEach(() => {
  vi.resetAllMocks()
  deniedPermissions.clear()
  vi.mocked(quotations.fetchQuotations).mockResolvedValue(list())
  vi.mocked(quotations.fetchQuotationSummary).mockResolvedValue({ all: 0 } as never)
  vi.mocked(quotations.fetchQuotationOptions).mockResolvedValue({} as never)
  vi.mocked(saved.fetchQuotationSavedViews).mockResolvedValue([])
  vi.mocked(saved.fetchSavedViews).mockResolvedValue([])
  vi.mocked(sales.fetchSalesOrders).mockResolvedValue(list())
  vi.mocked(sales.fetchSalesOrderOptions).mockResolvedValue({} as never)
  vi.mocked(tasks.fetchTasks).mockResolvedValue(list())
  vi.mocked(tasks.fetchTaskOptions).mockResolvedValue({} as never)
  vi.mocked(tasks.fetchTaskMetrics).mockResolvedValue({} as never)
  vi.mocked(complaints.fetchComplaints).mockResolvedValue(list())
  vi.mocked(complaints.fetchComplaintOptions).mockResolvedValue({} as never)
  vi.mocked(complaints.fetchComplaintStats).mockResolvedValue({ by_type: [], by_owner: [], sla: {} } as never)
})

it('报价和销售列表的旧响应、旧失败与卸载响应不会覆盖新筛选', async () => {
  for (const [component, api, method] of [[QuotationList, quotations.fetchQuotations, 'loadRows'], [SalesList, sales.fetchSalesOrders, 'load']] as const) {
    const wrapper = shallowMount(component, { global }); await flushPromises()
    const vm = wrapper.vm as unknown as { loadRows: () => Promise<void>; load: () => Promise<void>; total: number; errorMessage: string; loading: boolean }
    const old = deferred<never>(); vi.mocked(api).mockReturnValueOnce(old.promise)
    const pending = vm[method](); vi.mocked(api).mockResolvedValueOnce(list(2)); await vm[method]()
    old.resolve(list(1)); await pending; expect(vm.total).toBe(2)
    const failed = deferred<never>(); vi.mocked(api).mockReturnValueOnce(failed.promise)
    const failure = vm[method](); vi.mocked(api).mockResolvedValueOnce(list(3)); await vm[method]()
    failed.reject(new Error('旧请求失败')); await failure; expect(vm.errorMessage).toBe(''); expect(vm.total).toBe(3)
    const late = deferred<never>(); vi.mocked(api).mockReturnValueOnce(late.promise)
    const last = vm[method](); wrapper.unmount(); late.resolve(list(4)); await last; expect(vm.total).toBe(3)
  }
})

it('任务首屏不等待筛选项和保存视图，仍显示正确列表', async () => {
  const options = deferred<never>(), views = deferred<never>()
  vi.mocked(tasks.fetchTaskOptions).mockReturnValueOnce(options.promise)
  vi.mocked(saved.fetchSavedViews).mockReturnValueOnce(views.promise)
  vi.mocked(tasks.fetchTasks).mockResolvedValueOnce(list(9))
  const wrapper = shallowMount(TaskCenter, { global }); await flushPromises()
  const vm = wrapper.vm as unknown as { total: number; loading: boolean }
  expect(tasks.fetchTasks).toHaveBeenCalledOnce(); expect(vm.total).toBe(9); expect(vm.loading).toBe(false)
  options.resolve({} as never); views.resolve([] as never); await flushPromises(); wrapper.unmount()
})

it('未授权个人视图时不请求或显示保存入口，任务主体正常加载', async () => {
  deniedPermissions.add('preferences.view_savedview')
  deniedPermissions.add('preferences.add_savedview')
  vi.mocked(tasks.fetchTasks).mockResolvedValueOnce(list(2))
  const wrapper = shallowMount(TaskCenter, { global }); await flushPromises()
  const vm = wrapper.vm as unknown as { total: number; errorMessage: string; saveCurrentView: () => Promise<void> }
  expect(vm.total).toBe(2)
  expect(vm.errorMessage).toBe('')
  expect(saved.fetchSavedViews).not.toHaveBeenCalled()
  expect(wrapper.text()).not.toContain('保存视图')
  await vm.saveCurrentView()
  expect(saved.createSavedView).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('任务主体不等待活动记录，活动失败只显示局部错误且可重试', async () => {
  const activities = deferred<never>()
  vi.mocked(tasks.fetchTaskActivity).mockReturnValueOnce(activities.promise)
  vi.mocked(tasks.fetchTask).mockResolvedValue({ etag: 'v1', data: {
    id: 'task-1', title: '测试任务', priority: 'NORMAL', status: 'OPEN', assignee: {}, reminders: [],
    checklist_progress: { completed: 0, total: 0 }, checklist_items: [], source_attachments: [],
  } } as never)
  const wrapper = shallowMount(TaskDetail, { global }); await flushPromises()
  const vm = wrapper.vm as unknown as { loading: boolean; activityLoading: boolean; activityErrorMessage: string; errorMessage: string; loadActivities: () => Promise<void> }
  expect(vm.loading).toBe(false); expect(vm.activityLoading).toBe(true); expect(wrapper.text()).toContain('测试任务')
  activities.reject(new Error('活动服务异常')); await flushPromises()
  expect(vm.errorMessage).toBe(''); expect(vm.activityErrorMessage).not.toBe(''); expect(vm.activityLoading).toBe(false)
  vi.mocked(tasks.fetchTaskActivity).mockResolvedValue([]); await vm.loadActivities(); expect(vm.activityErrorMessage).toBe(''); wrapper.unmount()
})

it('客诉列表不等待统计和选项，统计失败保留列表并支持独立重试', async () => {
  const stats = deferred<never>(), options = deferred<never>()
  vi.mocked(complaints.fetchComplaintStats).mockReturnValueOnce(stats.promise)
  vi.mocked(complaints.fetchComplaintOptions).mockReturnValueOnce(options.promise)
  vi.mocked(complaints.fetchComplaints).mockResolvedValueOnce(list(7))
  const wrapper = shallowMount(ComplaintList, { global }); await flushPromises()
  const vm = wrapper.vm as unknown as { loading: boolean; total: number; statsError: string; errorMessage: string; options: unknown; loadStats: () => Promise<void> }
  expect(vm.total).toBe(7); expect(vm.loading).toBe(false)
  options.resolve({ statuses: [{ value: 'OPEN', label: '处理中' }] } as never); await flushPromises()
  expect(vm.options).toEqual({ statuses: [{ value: 'OPEN', label: '处理中' }] })
  stats.reject(new Error('统计失败')); await flushPromises()
  expect(vm.total).toBe(7); expect(vm.errorMessage).toBe(''); expect(vm.statsError).not.toBe('')
  await vm.loadStats(); expect(vm.statsError).toBe(''); expect(complaints.fetchComplaints).toHaveBeenCalledOnce(); wrapper.unmount()
})

it('客户补充页面切换客户时旧列表和旧统计不能覆盖当前客户', async () => {
  const oldRows = deferred<never>(), oldStats = deferred<never>()
  vi.mocked(quotations.fetchQuotations).mockReturnValueOnce(oldRows.promise)
  vi.mocked(quotations.fetchQuotationSummary).mockReturnValueOnce(oldStats.promise)
  const wrapper = shallowMount(RelatedRecords, { global, props: { kind: 'quotations', customerId: 'a', customerName: '甲' } })
  vi.mocked(quotations.fetchQuotations).mockResolvedValueOnce(list(8))
  vi.mocked(quotations.fetchQuotationSummary).mockResolvedValueOnce({ all: 8 } as never)
  await wrapper.setProps({ customerId: 'b', customerName: '乙' }); await flushPromises()
  oldRows.resolve(list(1)); oldStats.resolve({ all: 1 } as never); await flushPromises()
  const vm = wrapper.vm as unknown as { total: number; quotationSummary: { all: number } }
  expect(vm.total).toBe(8); expect(vm.quotationSummary.all).toBe(8); wrapper.unmount()
})

it('重复客户列表已到达时不等待字段对比，加载期间不允许切换案例', async () => {
  const detail = deferred<never>()
  vi.mocked(customers.fetchCustomerDuplicateCases).mockResolvedValue({ data: [{ id: 'case-1', candidates: [], status: 'OPEN' }] } as never)
  vi.mocked(customers.fetchCustomerDuplicateCase).mockReturnValueOnce(detail.promise)
  const wrapper = shallowMount(DuplicateCenter, { global }); await flushPromises()
  const vm = wrapper.vm as unknown as { loading: boolean; actionLoading: boolean; cases: unknown[] }
  expect(vm.cases.length).toBe(1); expect(vm.loading).toBe(false); expect(vm.actionLoading).toBe(true)
  detail.resolve({ data: { id: 'case-1', candidates: [] }, etag: 'v1' } as never); await flushPromises()
  expect(vm.actionLoading).toBe(false); wrapper.unmount()
})

it('重复客户刷新期间禁止发起合并预览写入', async () => {
  vi.mocked(customers.fetchCustomerDuplicateCases).mockResolvedValue({ data: [] } as never)
  const wrapper = shallowMount(DuplicateCenter, { global }); await flushPromises()
  const vm = wrapper.vm as unknown as { loading: boolean; selectedCase: unknown; survivorId: string; runPreview: () => Promise<void> }
  vm.selectedCase = { id: 'case-1', candidates: [{ id: 'a', customer: { id: 'a' } }, { id: 'b', customer: { id: 'b' } }] }
  vm.survivorId = 'a'; vm.loading = true
  await vm.runPreview()
  expect(customers.decideCustomerDuplicateCandidate).not.toHaveBeenCalled()
  expect(customers.previewCustomerMerge).not.toHaveBeenCalled()
  wrapper.unmount()
})

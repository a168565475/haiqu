import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElInput } from 'element-plus'
import { beforeEach, expect, it, vi } from 'vitest'
import { fetchTaskOptions, fetchTasks } from '@/api/tasks'
import TaskCreateDialog from '@/components/tasks/TaskCreateDialog.vue'
import type { TaskFilters, TaskScope } from '@/types/task'
import TaskCenterView from './TaskCenterView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/tasks', async original => ({ ...await original<typeof import('@/api/tasks')>(), fetchTasks: vi.fn(), fetchTaskOptions: vi.fn() }))

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchTasks).mockResolvedValue({ data: [], meta: { total: 0 } } as never)
  vi.mocked(fetchTaskOptions).mockResolvedValue({ scopes: [{ value: 'ME', label: '我的任务' }, { value: 'TEAM', label: '团队任务' }], assignees: [], task_types: [], statuses: [], priorities: [] })
})

const global = { plugins: [ElementPlus], stubs: { ElInput: false, ElButton: false } }

it('回车、放大镜和清空只重置页码并保留筛选，中文输入确认不提交', async () => {
  const wrapper = shallowMount(TaskCenterView, { global })
  await flushPromises()
  const vm = wrapper.vm as unknown as { filters: TaskFilters }
  Object.assign(vm.filters, { page: 4, scope: 'TEAM', status: 'PENDING', assignee_employee_id: 'employee-1', priority: 'HIGH' })
  const input = wrapper.get('.search-filter input')
  await input.setValue('  跟进客户  ')
  vi.mocked(fetchTasks).mockClear()
  await input.trigger('keydown', { key: 'Enter', isComposing: true })
  expect(fetchTasks).not.toHaveBeenCalled()
  expect(vm.filters.page).toBe(4)
  await input.trigger('keydown', { key: 'Enter' })
  await flushPromises()
  expect(fetchTasks).toHaveBeenCalledOnce()
  expect(vm.filters).toMatchObject({ q: '跟进客户', page: 1, scope: 'TEAM', status: 'PENDING', assignee_employee_id: 'employee-1', priority: 'HIGH' })
  vm.filters.page = 3
  await wrapper.get('button[aria-label="搜索任务"]').trigger('click')
  await flushPromises()
  expect(fetchTasks).toHaveBeenCalledTimes(2)
  expect(vm.filters.page).toBe(1)
  vm.filters.page = 2
  wrapper.findComponent(ElInput).vm.$emit('update:modelValue', '')
  wrapper.findComponent(ElInput).vm.$emit('clear')
  await flushPromises()
  expect(fetchTasks).toHaveBeenCalledTimes(3)
  expect(vm.filters).toMatchObject({ q: '', page: 1, scope: 'TEAM', status: 'PENDING', assignee_employee_id: 'employee-1', priority: 'HIGH' })
  wrapper.unmount()
})

it('嵌入客户页保留客户、新建负责人及范围切换约束，移除选择框和专用工具栏', async () => {
  const wrapper = shallowMount(TaskCenterView, { global, props: { embedded: true, customerId: 'customer-1', customerName: '客户甲', defaultScope: 'ALL', defaultAssigneeId: 'employee-1' } })
  await flushPromises()
  const vm = wrapper.vm as unknown as { filters: TaskFilters; changeScopeFromFilter: (scope: TaskScope) => Promise<void>; resetFilters: () => Promise<void> }
  expect(wrapper.findComponent(TaskCreateDialog).props()).toMatchObject({ fixedCustomerId: 'customer-1', fixedCustomerName: '客户甲', defaultAssigneeId: 'employee-1', scope: 'ALL' })
  expect(wrapper.find('.task-filters .task-filter-actions').exists()).toBe(true)
  expect(wrapper.find('.task-metrics, .task-toolbar, el-table-column-stub[type="selection"]').exists()).toBe(false)
  vm.filters.page = 3
  await vm.changeScopeFromFilter('TEAM')
  expect(fetchTaskOptions).toHaveBeenLastCalledWith('TEAM')
  expect(vm.filters).toMatchObject({ scope: 'TEAM', customer_id: 'customer-1', page: 1 })
  await vm.resetFilters()
  expect(vm.filters).toMatchObject({ scope: 'TEAM', customer_id: 'customer-1', page: 1 })
  await wrapper.setProps({ customerId: 'customer-2', defaultScope: 'ME' })
  await flushPromises()
  expect(vm.filters).toMatchObject({ scope: 'ME', customer_id: 'customer-2', page: 1 })
  expect(fetchTaskOptions).toHaveBeenLastCalledWith('ME')
  wrapper.unmount()
})

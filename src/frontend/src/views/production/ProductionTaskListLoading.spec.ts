import { flushPromises, shallowMount, mount as mountWithTable } from '@vue/test-utils'
import ElementPlus, { ElInput, ElMessageBox, ElMessage } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/productionTasks'
import ProductionTaskListView from './ProductionTaskListView.vue'

const route = vi.hoisted(() => ({ query: {} as Record<string, string> }))
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => router }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/productionTasks', async original => ({ ...await original<typeof import('@/api/productionTasks')>(), fetchProductionTask: vi.fn(), deleteProductionTask: vi.fn(), fetchProductionTasks: vi.fn(), fetchProductionTaskOptions: vi.fn(), fetchProductionTaskFilterOptions: vi.fn(), cancelProductionTask: vi.fn(), finishProductionTask: vi.fn() }))
const options = { employees: [], salespeople: [], products: [], customers: [], order_sources: [], delivery_methods: [], statuses: [] }
const mount = () => shallowMount(ProductionTaskListView, { global: { plugins: [ElementPlus] } })
beforeEach(() => { route.query = {} })

describe('任务列表按对象动作授权', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchProductionTasks).mockResolvedValue({ data: [], meta: { total: 0, total_pages: 0 } } as never)
    vi.mocked(api.fetchProductionTaskFilterOptions).mockResolvedValue(options)
  })
  it('PMC 可编辑计划和完结，但编辑权限不能代替取消或删除权限', async () => {
    const wrapper = mount(); await flushPromises()
    const page = wrapper.vm as unknown as { canEditTask: (row: unknown) => boolean; canChangeLifecycle: (row: unknown, action: string) => boolean; handleRowAction: (command: string, row: unknown) => void }
    const row = { id: 'one', status: 'IN_PRODUCTION', allowed_permissions: ['access_control.edit_productionplan', 'access_control.finish_productiontask'] }
    expect(page.canEditTask(row)).toBe(true)
    expect(page.canChangeLifecycle(row, 'finish')).toBe(true)
    expect(page.canChangeLifecycle(row, 'cancel')).toBe(false)
    page.handleRowAction('edit', row)
    expect(router.push).toHaveBeenCalledWith({ name: 'production-task-edit', params: { taskId: 'one' } })
    expect(page.canChangeLifecycle({ ...row, allowed_permissions: ['production_tasks.change_productiontask'] }, 'finish')).toBe(false)
    router.push.mockClear()
    page.handleRowAction('edit', { ...row, allowed_permissions: [] })
    page.handleRowAction('delete', { ...row, status: 'CANCELLED', allowed_permissions: [] })
    expect(router.push).not.toHaveBeenCalled()
    expect(api.fetchProductionTask).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('详情完结入口复用数量窗口并提交数量和批次，权限回收后不能提交', async () => {
    route.query = { finish: 'one' }
    const row = { id: 'one', status: 'IN_PRODUCTION', sales_order_id: 'sales', total_quantity: '10', run_batches: [], allowed_permissions: ['access_control.finish_productiontask'] }
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: row, etag: 'v2' } as never)
    const wrapper = mount(); await flushPromises()
    const page = wrapper.vm as unknown as { lifecycleDialogVisible: boolean; confirmLifecycleAction: () => Promise<void> }
    expect(page.lifecycleDialogVisible).toBe(true)
    expect(router.replace).toHaveBeenCalledWith({ query: { finish: undefined } })
    vi.mocked(api.fetchProductionTask).mockResolvedValueOnce({ data: { ...row, allowed_permissions: [] }, etag: 'v3' } as never)
    await page.confirmLifecycleAction()
    expect(api.finishProductionTask).not.toHaveBeenCalled()
    await page.confirmLifecycleAction()
    expect(api.finishProductionTask).toHaveBeenCalledWith('one', '', 'v2', { actual_quantity: '10', actual_good_quantity: '10', run_batches: [] })
    wrapper.unmount()
  })
})

describe('生产任务列表分区加载', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchProductionTasks).mockResolvedValue({ data: [], meta: { total: 4, total_pages: 1 } } as never)
    vi.mocked(api.fetchProductionTaskOptions).mockResolvedValue(options as never)
    vi.mocked(api.fetchProductionTaskFilterOptions).mockResolvedValue(options)
  })
  it('首次打开列表直接显示任务、BOM、采购状态，无需手动勾选列', async () => {
    const wrapper = mountWithTable(ProductionTaskListView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(wrapper.findAll('th').map(cell => cell.text())).toEqual(expect.arrayContaining(['状态', 'BOM状态', '采购状态', '人民币金额合计', '业务员', '跟单员']))
    wrapper.unmount()
  })
  it('慢筛选选项不拖住列表，搜索不重新读取选项', async () => {
    let finish!: (value: never) => void
    const slow = new Promise<never>(resolve => { finish = resolve })
    vi.mocked(api.fetchProductionTaskOptions).mockReturnValue(slow)
    vi.mocked(api.fetchProductionTaskFilterOptions).mockReturnValue(slow)
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as { total: number; loading: boolean; search: () => void }
    expect(vm.total).toBe(4)
    expect(vm.loading).toBe(false)
    vm.search(); await flushPromises()
    expect(api.fetchProductionTasks).toHaveBeenCalledTimes(2)
    expect(api.fetchProductionTaskFilterOptions).toHaveBeenCalledTimes(1)
    expect(api.fetchProductionTaskOptions).not.toHaveBeenCalled()
    finish(options as never); await flushPromises(); wrapper.unmount()
  })
  it('搜索的回车、放大镜和清空回第一页保留筛选，中文输入确认不提交', async () => {
    const wrapper = shallowMount(ProductionTaskListView, { global: { plugins: [ElementPlus], stubs: { ElInput: false, ElButton: false } } }); await flushPromises()
    const vm = wrapper.vm as unknown as { page: number; activeStatusTab: string; dueSoon: boolean; advancedFilters: { salesperson_id: string } }
    vm.page = 4; vm.activeStatusTab = 'pending'; vm.dueSoon = true; vm.advancedFilters.salesperson_id = 'sales-1'
    const input = wrapper.get('.search-filter input')
    await input.setValue('  HT26001  ')
    vi.mocked(api.fetchProductionTasks).mockClear()
    await input.trigger('keydown', { key: 'Enter', isComposing: true })
    expect(api.fetchProductionTasks).not.toHaveBeenCalled(); expect(vm.page).toBe(4)
    await input.trigger('keydown', { key: 'Enter' }); await flushPromises()
    expect(api.fetchProductionTasks).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, search: 'HT26001', status: 'PENDING_VALIDATION', salesperson_id: 'sales-1', due_within_days: 30 }))
    vm.page = 3
    await wrapper.get('button[aria-label="搜索生产任务单"]').trigger('click'); await flushPromises()
    expect(api.fetchProductionTasks).toHaveBeenCalledTimes(2); expect(vm.page).toBe(1)
    vm.page = 2
    wrapper.findComponent(ElInput).vm.$emit('update:modelValue', '')
    wrapper.findComponent(ElInput).vm.$emit('clear'); await flushPromises()
    expect(api.fetchProductionTasks).toHaveBeenCalledTimes(3)
    expect(api.fetchProductionTasks).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, search: undefined, status: 'PENDING_VALIDATION', salesperson_id: 'sales-1', due_within_days: 30 }))
    expect(wrapper.find('.status-tabs, .list-toolbar__views, el-table-column-stub[type="selection"]').exists()).toBe(false)
    expect(wrapper.find('.list-filters .list-filter-actions').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('生产任务删除保护', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchProductionTasks).mockResolvedValue({ data: [], meta: { total: 0, total_pages: 0 } } as never)
    vi.mocked(api.fetchProductionTaskFilterOptions).mockResolvedValue(options)
  })
  it('非取消状态拒绝删除；确认后携带最新版本并刷新', async () => {
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as { deleteTask: (row: unknown) => Promise<void> }
    await vm.deleteTask({ id: '1', status: 'READY' })
    expect(api.fetchProductionTask).not.toHaveBeenCalled()
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: { status: 'CANCELLED' }, etag: '"v3"' } as never)
    vi.mocked(api.deleteProductionTask).mockResolvedValue()
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const success = vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
    await vm.deleteTask({ id: '1', task_number: 'SC-1', status: 'CANCELLED' })
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('不可恢复'), '删除生产任务单', expect.any(Object))
    expect(api.deleteProductionTask).toHaveBeenCalledWith('1', '"v3"')
    expect(api.fetchProductionTasks).toHaveBeenCalledTimes(2)
    confirm.mockRestore(); success.mockRestore(); wrapper.unmount()
  })
  it('用户取消确认不删除；状态变化也不删除', async () => {
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as { deleteTask: (row: unknown) => Promise<void> }
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: { status: 'CANCELLED' }, etag: '"v3"' } as never)
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
    await vm.deleteTask({ id: '1', status: 'CANCELLED' })
    expect(api.deleteProductionTask).not.toHaveBeenCalled()
    confirm.mockRestore(); wrapper.unmount()
  })
})

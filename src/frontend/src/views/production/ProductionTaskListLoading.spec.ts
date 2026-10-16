import { flushPromises, shallowMount, mount as mountWithTable } from '@vue/test-utils'
import ElementPlus, { ElMessageBox, ElMessage } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/productionTasks'
import { fetchProductionTaskSavedViews } from '@/api/savedViews'
import ProductionTaskListView from './ProductionTaskListView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))
vi.mock('@/api/productionTasks', async original => ({ ...await original<typeof import('@/api/productionTasks')>(), fetchProductionTask: vi.fn(), deleteProductionTask: vi.fn(), fetchProductionTasks: vi.fn(), fetchProductionTaskStats: vi.fn(), fetchProductionTaskOptions: vi.fn(), fetchProductionTaskFilterOptions: vi.fn() }))
vi.mock('@/api/savedViews', async original => ({ ...await original<typeof import('@/api/savedViews')>(), fetchProductionTaskSavedViews: vi.fn() }))
const options = { employees: [], products: [], customers: [], order_sources: [], delivery_methods: [], statuses: [] }
const stats = { all: 4, draft: 2, pending_validation: 1, ready: 1, in_production: 0, completed: 0, paused: 0, cancelled: 0, split_delivery: 0 }
const mount = () => shallowMount(ProductionTaskListView, { global: { plugins: [ElementPlus] } })

describe('生产任务列表分区加载', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchProductionTasks).mockResolvedValue({ data: [], meta: { total: 4, total_pages: 1 } } as never)
    vi.mocked(api.fetchProductionTaskStats).mockResolvedValue(stats)
    vi.mocked(api.fetchProductionTaskOptions).mockResolvedValue(options as never)
    vi.mocked(api.fetchProductionTaskFilterOptions).mockResolvedValue(options)
    vi.mocked(fetchProductionTaskSavedViews).mockResolvedValue([])
  })
  it('首次打开列表直接显示任务、BOM、采购状态，无需手动勾选列', async () => {
    const wrapper = mountWithTable(ProductionTaskListView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(wrapper.findAll('th').map(cell => cell.text())).toEqual(expect.arrayContaining(['状态', 'BOM状态', '采购状态', '人民币金额合计', '业务员', '跟单员']))
    wrapper.unmount()
  })
  it('选项和个人视图未返回时统计已可用，搜索只刷新列表及统计', async () => {
    let finish!: (value: never) => void
    const slow = new Promise<never>(resolve => { finish = resolve })
    vi.mocked(api.fetchProductionTaskOptions).mockReturnValue(slow)
    vi.mocked(api.fetchProductionTaskFilterOptions).mockReturnValue(slow)
    vi.mocked(fetchProductionTaskSavedViews).mockReturnValue(new Promise(() => {}))
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as { stats: typeof stats; statsLoading: boolean; search: () => void }
    expect(vm.stats.all).toBe(4)
    expect(vm.statsLoading).toBe(false)
    vm.search(); await flushPromises()
    expect(api.fetchProductionTaskStats).toHaveBeenCalledTimes(2)
    expect(api.fetchProductionTaskFilterOptions).toHaveBeenCalledTimes(1)
    expect(api.fetchProductionTaskOptions).not.toHaveBeenCalled()
    expect(fetchProductionTaskSavedViews).toHaveBeenCalledTimes(1)
    finish(options as never); await flushPromises(); wrapper.unmount()
  })
  it('快速重复筛选时只接收最后一次统计；失败不能显示旧条件的数量', async () => {
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as { loadStats: () => Promise<boolean>; stats: typeof stats; statsReady: boolean; statsError: string }
    let finish!: (value: typeof stats) => void
    vi.mocked(api.fetchProductionTaskStats).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
      .mockResolvedValueOnce({ ...stats, all: 2 })
    const first=vm.loadStats(); await vm.loadStats(); finish({ ...stats, all: 1 }); await first
    expect(vm.stats.all).toBe(2)
    vi.mocked(api.fetchProductionTaskStats).mockRejectedValueOnce(new Error('统计失败'))
    await vm.loadStats()
    expect(vm.statsReady).toBe(false); expect(vm.statsError).toBe('统计失败')
    wrapper.unmount()
  })
})

describe('生产任务删除保护', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchProductionTasks).mockResolvedValue({ data: [], meta: { total: 0, total_pages: 0 } } as never)
    vi.mocked(api.fetchProductionTaskStats).mockResolvedValue(stats)
    vi.mocked(api.fetchProductionTaskFilterOptions).mockResolvedValue(options)
    vi.mocked(fetchProductionTaskSavedViews).mockResolvedValue([])
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

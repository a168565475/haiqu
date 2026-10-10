import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/productionTasks'
import { fetchProductionTaskSavedViews } from '@/api/savedViews'
import ProductionTaskListView from './ProductionTaskListView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))
vi.mock('@/api/productionTasks', async original => ({ ...await original<typeof import('@/api/productionTasks')>(), fetchProductionTasks: vi.fn(), fetchProductionTaskStats: vi.fn(), fetchProductionTaskOptions: vi.fn(), fetchProductionTaskFilterOptions: vi.fn() }))
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

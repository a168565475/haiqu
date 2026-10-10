import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/boms'
import BomListView from './BomListView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))
vi.mock('@/api/boms', async original => ({ ...await original<typeof import('@/api/boms')>(), fetchBoms: vi.fn(), fetchBomStats: vi.fn(), fetchBomOptions: vi.fn(), fetchBomFilterOptions: vi.fn() }))
const stats = { total: 4, pending_confirmation: 2, verified: 2, maintenance_reference_count: 6 }
const options = { product_categories: [] }
const mount = () => shallowMount(BomListView, { global: { plugins: [ElementPlus] } })

describe('BOM 列表分区读取', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchBoms).mockResolvedValue({ data: [], meta: { total: 4, total_pages: 1 } } as never)
    vi.mocked(api.fetchBomStats).mockResolvedValue(stats)
    vi.mocked(api.fetchBomOptions).mockResolvedValue(options as never)
    vi.mocked(api.fetchBomFilterOptions).mockResolvedValue(options)
  })
  it('慢筛选选项不拖住统计，搜索不重新读取选项', async () => {
    vi.mocked(api.fetchBomOptions).mockReturnValue(new Promise(() => {}))
    vi.mocked(api.fetchBomFilterOptions).mockReturnValue(new Promise(() => {}))
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as { stats: typeof stats; statsLoading: boolean; search: () => void }
    expect(vm.stats.total).toBe(4); expect(vm.statsLoading).toBe(false)
    vm.search(); await flushPromises()
    expect(api.fetchBomStats).toHaveBeenCalledTimes(2)
    expect(api.fetchBomFilterOptions).toHaveBeenCalledTimes(1)
    expect(api.fetchBomOptions).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('新筛选结果优先，统计失败后显示未知，重新加载可恢复', async () => {
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as { loadStats: () => Promise<boolean>; stats: typeof stats; statsReady: boolean; statsError: string }
    let finish!: (value: typeof stats) => void
    vi.mocked(api.fetchBomStats).mockReturnValueOnce(new Promise(resolve => { finish = resolve })).mockResolvedValueOnce({ ...stats, total: 2 })
    const first = vm.loadStats(); await vm.loadStats(); finish({ ...stats, total: 1 }); await first
    expect(vm.stats.total).toBe(2)
    vi.mocked(api.fetchBomStats).mockRejectedValueOnce(new Error('统计失败'))
    await vm.loadStats(); expect(vm.statsReady).toBe(false); expect(vm.statsError).toBe('统计失败')
    await vm.loadStats(); expect(vm.statsReady).toBe(true); expect(vm.statsError).toBe('')
    wrapper.unmount()
  })
})

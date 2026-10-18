import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElInput } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/boms'
import BomListView from './BomListView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))
vi.mock('@/api/boms', async original => ({ ...await original<typeof import('@/api/boms')>(), fetchBoms: vi.fn(), fetchBomOptions: vi.fn(), fetchBomFilterOptions: vi.fn() }))
const options = { product_categories: [] }
const mount = () => shallowMount(BomListView, { global: { plugins: [ElementPlus] } })

describe('BOM 列表分区读取', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchBoms).mockResolvedValue({ data: [], meta: { total: 4, total_pages: 1 } } as never)
    vi.mocked(api.fetchBomOptions).mockResolvedValue(options as never)
    vi.mocked(api.fetchBomFilterOptions).mockResolvedValue(options)
  })
  it('慢筛选选项不拖住列表，搜索不重新读取选项', async () => {
    vi.mocked(api.fetchBomOptions).mockReturnValue(new Promise(() => {}))
    vi.mocked(api.fetchBomFilterOptions).mockReturnValue(new Promise(() => {}))
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as { total: number; loading: boolean; search: () => void }
    expect(vm.total).toBe(4); expect(vm.loading).toBe(false)
    vm.search(); await flushPromises()
    expect(api.fetchBoms).toHaveBeenCalledTimes(2)
    expect(api.fetchBomFilterOptions).toHaveBeenCalledTimes(1)
    expect(api.fetchBomOptions).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('新筛选结果优先，列表失败保留错误且可重新加载', async () => {
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as { loadRows: () => Promise<boolean>; total: number; errorMessage: string }
    let finish!: (value: never) => void
    vi.mocked(api.fetchBoms).mockReturnValueOnce(new Promise(resolve => { finish = resolve })).mockResolvedValueOnce({ data: [], meta: { total: 2, total_pages: 1 } } as never)
    const first = vm.loadRows(); await vm.loadRows(); finish({ data: [], meta: { total: 1, total_pages: 1 } } as never); await first
    expect(vm.total).toBe(2)
    vi.mocked(api.fetchBoms).mockRejectedValueOnce(new Error('列表失败'))
    await vm.loadRows(); expect(vm.total).toBe(0); expect(vm.errorMessage).toBe('列表失败')
    await vm.loadRows(); expect(vm.total).toBe(4); expect(vm.errorMessage).toBe('')
    wrapper.unmount()
  })
  it('回车、放大镜和清空保留状态、类别与日期筛选，中文输入确认不提交', async () => {
    const wrapper = shallowMount(BomListView, { global: { plugins: [ElementPlus], stubs: { ElInput: false, ElButton: false } } }); await flushPromises()
    const vm = wrapper.vm as unknown as { page: number; filters: { status: string; product_category_id: string }; updatedRange: [string, string] }
    vm.page = 4; vm.filters.status = 'VERIFIED'; vm.filters.product_category_id = 'category-1'; vm.updatedRange = ['2026-10-01', '2026-10-16']
    const input = wrapper.get('.search-filter input')
    await input.setValue('  BOM-01  ')
    vi.mocked(api.fetchBoms).mockClear()
    await input.trigger('keydown', { key: 'Enter', isComposing: true })
    expect(api.fetchBoms).not.toHaveBeenCalled(); expect(vm.page).toBe(4)
    await input.trigger('keydown', { key: 'Enter' }); await flushPromises()
    expect(api.fetchBoms).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, q: 'BOM-01', status: 'VERIFIED', product_category_id: 'category-1', updated_after: '2026-10-01', updated_before: '2026-10-16' }))
    vm.page = 3
    await wrapper.get('button[aria-label="搜索 BOM"]').trigger('click'); await flushPromises()
    expect(api.fetchBoms).toHaveBeenCalledTimes(2); expect(vm.page).toBe(1)
    vm.page = 2
    wrapper.findComponent(ElInput).vm.$emit('update:modelValue', '')
    wrapper.findComponent(ElInput).vm.$emit('clear'); await flushPromises()
    expect(api.fetchBoms).toHaveBeenCalledTimes(3)
    expect(api.fetchBoms).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, q: undefined, status: 'VERIFIED', product_category_id: 'category-1', updated_after: '2026-10-01', updated_before: '2026-10-16' }))
    expect(wrapper.find('.status-tabs').exists()).toBe(false)
    expect(wrapper.find('.erp-list-toolbar .bom-filter-actions').exists()).toBe(true)
    wrapper.unmount()
  })
})

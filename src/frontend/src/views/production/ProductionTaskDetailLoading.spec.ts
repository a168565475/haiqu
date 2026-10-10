import { flushPromises, shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import * as api from '@/api/productionTasks'
import ProductionTaskDetailView from './ProductionTaskDetailView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { taskId: 'one' } }), useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true, moduleCan: () => true }) }))
vi.mock('@/api/productionTasks', async original => ({ ...await original<typeof import('@/api/productionTasks')>(), fetchProductionTask: vi.fn(), fetchProductionTaskOptions: vi.fn(), decideProductionTaskByPmc: vi.fn() }))

describe('生产任务详情按需选项', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: { id: 'one', task_number: 'PROD-ONE', status: 'PENDING_VALIDATION', salesperson: { display_name: '业务员' }, products: [], followers: [], delivery_batches: [], current_boms: [], audit_timeline: [] }, etag: 'v1' } as never)
  })
  it('首屏不读取选项，确认窗口加载失败可重试，未就绪不能提交', async () => {
    const wrapper = shallowMount(ProductionTaskDetailView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(api.fetchProductionTaskOptions).not.toHaveBeenCalled()
    const vm = wrapper.vm as unknown as { openPmcDialog: (mode: 'CONFIRM' | 'RETURN') => void; loadPmcOptions: () => Promise<void>; decideByPmc: () => Promise<void>; optionsLoading: boolean; optionsError: string; options: unknown }
    vm.openPmcDialog('RETURN')
    expect(api.fetchProductionTaskOptions).not.toHaveBeenCalled()
    let fail!: (reason: Error) => void
    vi.mocked(api.fetchProductionTaskOptions).mockImplementationOnce(() => new Promise((_, reject) => { fail = reject }))
    vm.openPmcDialog('CONFIRM')
    expect(vm.optionsLoading).toBe(true)
    await vm.decideByPmc()
    expect(api.decideProductionTaskByPmc).not.toHaveBeenCalled()
    fail(new Error('选项加载失败'))
    await flushPromises()
    expect(vm.optionsError).toBe('选项加载失败')
    await vm.decideByPmc()
    expect(api.decideProductionTaskByPmc).not.toHaveBeenCalled()
    vi.mocked(api.fetchProductionTaskOptions).mockResolvedValueOnce({ employees: [] } as never)
    await vm.loadPmcOptions()
    expect(vm.optionsError).toBe('')
    expect(vm.options).toEqual({ employees: [] })
    wrapper.unmount()
  })
})

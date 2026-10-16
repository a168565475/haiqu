import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import { router } from '@/router'
import * as api from '@/api/productionTasks'
import ProductionTaskCreateView from './ProductionTaskCreateView.vue'

vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({
  isAuthenticated: true, ensureFreshAuthentication: vi.fn(), initialize: vi.fn(),
  hasPermission: () => true, moduleCan: () => true,
}) }))
vi.mock('@/api/productionData', () => ({ fetchAllProductionDataRecords: vi.fn().mockResolvedValue([]) }))
vi.mock('@/components/InquiryWangEditor.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/api/productionTasks', async original => ({
  ...await original<typeof import('@/api/productionTasks')>(),
  fetchProductionTaskOptions: vi.fn(), reserveProductionTaskContractNumber: vi.fn(), fetchProductionSalesOrderSources: vi.fn().mockResolvedValue({ data: [] }),
}))

describe('手动生产任务路由', () => {
  it('无需销售订单即可打开真实注册路由并挂载手动表单', async () => {
    vi.mocked(api.fetchProductionTaskOptions).mockResolvedValue({ employees: [], products: [], colors: [], currencies: [], units: [], detail_template: [], recent_task_numbers: [] } as never)
    vi.mocked(api.reserveProductionTaskContractNumber).mockResolvedValue({ contract_number: 'CONTRACT-1', token: 'reservation' })
    await router.push('/production-tasks/new/manual')
    await router.isReady()
    expect(router.currentRoute.value.name).toBe('production-task-manual-create')
    const component = router.currentRoute.value.matched.at(-1)?.components?.default
    expect(component).toBe(ProductionTaskCreateView)
    const wrapper = shallowMount(ProductionTaskCreateView, { global: { plugins: [ElementPlus, router] } })
    await flushPromises()
    const page = wrapper.vm as unknown as { manualMode: boolean; activeStep: number }
    expect(page.manualMode).toBe(true)
    expect(page.activeStep).toBe(1)
    expect(wrapper.find('[aria-label="创建方式"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('选择已有产品或填写定制产品，金额使用人民币。')
    expect(wrapper.text()).not.toContain('继续添加产品')
    wrapper.unmount()
  })
})

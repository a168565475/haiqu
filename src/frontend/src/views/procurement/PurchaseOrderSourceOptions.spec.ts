import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchPurchaseOrderOptions } from '@/api/purchaseOrders'
import PurchaseOrderFormView from './PurchaseOrderFormView.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), useRoute: () => ({ name: 'purchase-order-create', query: {} }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: true }, hasPermission: () => true }) }))
vi.mock('@/api/purchaseOrders', () => ({
  fetchPurchaseOrderOptions: vi.fn(), fetchPurchaseOrderSource: vi.fn(),
  fetchSamplePurchaseOrderSource: vi.fn(), createPurchaseOrder: vi.fn(),
}))

describe('新建采购订单来源选项', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchPurchaseOrderOptions).mockResolvedValue({
      production_tasks: [
        { id: 'ready', task_number: '可采购生产单', can_create: true },
        { id: 'purchased', task_number: '已建采购单', can_create: false },
        { id: 'pending', task_number: 'BOM待确认', can_create: false },
      ],
      sample_requests: [
        { id: 'sample-ready', source_number: '可采购打样单', source_type: 'SAMPLE', can_create: true },
        { id: 'sample-blocked', source_number: '不可采购打样单', source_type: 'SAMPLE', can_create: false },
      ],
      suppliers: [], currencies: [], default_currency_id: null,
    } as never)
  })

  it('全部来源和分类筛选均只显示可采购记录，刷新后资格失效的记录消失', async () => {
    const wrapper = shallowMount(PurchaseOrderFormView, { global: { plugins: [ElementPlus] } })
    try {
      await flushPromises()
      const vm = wrapper.vm as unknown as {
        visibleSourceOptions: { id: string }[]
        sourceTypeFilter: string
        loadOptions: () => Promise<void>
      }
      expect(vm.visibleSourceOptions.map(item => item.id)).toEqual(['ready', 'sample:sample-ready'])
      vm.sourceTypeFilter = 'PRODUCTION'
      expect(vm.visibleSourceOptions.map(item => item.id)).toEqual(['ready'])
      vm.sourceTypeFilter = 'SAMPLE'
      expect(vm.visibleSourceOptions.map(item => item.id)).toEqual(['sample:sample-ready'])
      vi.mocked(fetchPurchaseOrderOptions).mockResolvedValueOnce({
        production_tasks: [{ id: 'ready', task_number: '刚被采购', can_create: false }],
        sample_requests: [], suppliers: [], currencies: [], default_currency_id: null,
      } as never)
      await vm.loadOptions()
      vm.sourceTypeFilter = 'ALL'
      expect(vm.visibleSourceOptions).toEqual([])
    } finally { wrapper.unmount() }
  })
})

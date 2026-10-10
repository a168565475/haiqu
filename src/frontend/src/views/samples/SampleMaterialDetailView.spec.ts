import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MaterialDetailPage from './SampleMaterialDetailView.vue'
import { useAuthStore } from '@/stores/auth'

const api = vi.hoisted(() => ({ fetchSample: vi.fn(), fetchMaterials: vi.fn(), push: vi.fn() }))
vi.mock('@/api/samples', () => ({ fetchSample: api.fetchSample }))
vi.mock('@/api/sampleMaterials', () => ({ fetchSampleMaterials: api.fetchMaterials }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { sampleId: 'sample-1' } }),
  useRouter: () => ({ push: api.push }),
}))

const sample = {
  id: 'sample-1', request_number: 'SRQ-1', customer_name: '客户 A', status: 'WAREHOUSE_PENDING', status_display: '待仓库核对', requested_at: '2026-10-07T08:00:00Z',
  products: [{ product_name: '户外餐椅', specification: '57×61×83 cm', details: [] }],
}
const progress = {
  label: '待核对 2 项', status: 'WAREHOUSE_PENDING',
  lines: [
    { key: 'tube-1', category: 'tube', name: '圆管', specification: 'Φ25 × 1.2 mm', material: '铝合金6063', color: '哑黑 / B-12 / 9011', quantity: '12', unitLabel: '根', supplyQuantity: '8', arrivedQuantity: '0', remainingQuantity: '4', issuedQuantity: null, shortageQuantity: '—' },
    { key: 'hardware-1', category: 'hardware', name: '螺丝', specification: 'M6 × 20', material: '不锈钢', color: '无颜色', quantity: '24', unitLabel: '个', supplyQuantity: '24', arrivedQuantity: '0', remainingQuantity: '0', issuedQuantity: null, shortageQuantity: '—' },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchSample.mockResolvedValue({ data: sample, etag: 'v1' })
  api.fetchMaterials.mockResolvedValue({ available: true, canEdit: true, status: 'WAREHOUSE_PENDING', statusLabel: '待仓库核对', draft: { lines: [], notes: '' }, etag: 'v1', submittedAt: null, progress })
})

describe('样品用料需求详情', () => {
  it('默认展示第一个有材料的分类并显示独立列', async () => {
    const wrapper = mount(MaterialDetailPage, { global: { plugins: [ElementPlus, createPinia()] } })
    await flushPromises()
    expect(wrapper.find('h1').text()).toBe('样品用料需求详情')
    expect(wrapper.findAll('.material-detail-table th').map((cell) => cell.text())).toEqual(expect.arrayContaining(['材料分类', '规格', '需采购', '实际领料', '未领缺口']))
    expect(wrapper.findAll('.material-detail-table tbody tr')).toHaveLength(1)
    expect(wrapper.find('.material-detail-tabs button.active').text()).toContain('管材类')
  })

  it('可从详情返回材料填写页', async () => {
    const wrapper = mount(MaterialDetailPage, { global: { plugins: [ElementPlus, createPinia()] } })
    await flushPromises()
    await wrapper.find('button[type="button"]').trigger('click')
    await wrapper.findAll('button').find((button) => button.text() === '编辑需求')!.trigger('click')
    expect(api.push).toHaveBeenCalledWith({ name: 'sample-materials', params: { sampleId: 'sample-1' } })
  })

  it('有待采购缺料且具备采购权限时可进入采购明细', async () => {
    const pinia = createPinia()
    const authStore = useAuthStore(pinia)
    authStore.user = {
      id: 1,
      username: 'buyer',
      display_name: '采购员',
      is_superuser: false,
      employee: null,
      permissions: ['procurement.add_purchaseorder'],
      data_scope: 'ALL',
    }
    api.fetchMaterials.mockResolvedValueOnce({
      available: true,
      canEdit: false,
      status: 'PROCUREMENT_PENDING',
      statusLabel: '等待采购',
      draft: { lines: [], notes: '' },
      etag: 'v1',
      submittedAt: '2026-10-07T08:00:00Z',
      procurementRequest: { id: 'proc-1', submittedAt: '2026-10-07T08:01:00Z' },
      progress: { ...progress, label: '等待采购', status: 'PROCUREMENT_PENDING' },
    })
    const wrapper = mount(MaterialDetailPage, { global: { plugins: [ElementPlus, pinia] } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '去创建采购单')!.trigger('click')
    expect(api.push).toHaveBeenCalledWith({
      name: 'purchase-order-create-details',
      query: { source_type: 'SAMPLE', source_id: 'proc-1' },
    })
  })
})

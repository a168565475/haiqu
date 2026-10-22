import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MaterialDetailPage from './SampleMaterialDetailView.vue'
import { useAuthStore } from '@/stores/auth'

const api = vi.hoisted(() => ({ fetchSample: vi.fn(), fetchMaterials: vi.fn(), procurementContext: vi.fn(), push: vi.fn() }))
vi.mock('@/api/samples', () => ({ fetchSample: api.fetchSample }))
vi.mock('@/api/sampleMaterials', () => ({ fetchSampleMaterials: api.fetchMaterials, fetchSampleProcurementMaterialContext: api.procurementContext }))
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
  it('采购缺料身份使用窄接口，保留原页面并且不请求整份样品资料', async () => {
    const pinia = createPinia()
    useAuthStore(pinia).user = { id: 1, username: 'buyer', display_name: '采购员', is_superuser: false, employee: null,
      permissions: ['samples.view_sample_procurement', 'procurement.add_purchaseorder'], data_scope: 'ALL' }
    api.procurementContext.mockResolvedValue({ sample: { ...sample, product_name: '户外餐椅', specification: '57×61×83 cm', color: '蓝色', quantity_label: '3 PCS' },
      materials: { available: true, canEdit: false, status: 'PROCUREMENT_PENDING', statusLabel: '等待采购', draft: { lines: [], notes: '' }, etag: 'v1', submittedAt: null,
        progress: { ...progress, status: 'PROCUREMENT_PENDING', label: '等待采购' }, procurementRequest: { id: 'proc-1', submittedAt: '' } } })
    const wrapper = mount(MaterialDetailPage, { global: { plugins: [ElementPlus, pinia] } })
    await flushPromises()
    expect(api.procurementContext).toHaveBeenCalledWith('sample-1')
    expect(api.fetchSample).not.toHaveBeenCalled()
    expect(api.fetchMaterials).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('3 PCS')
    expect(wrapper.text()).toContain('去创建采购单')
    expect(wrapper.text()).not.toContain('编辑需求')
  })
  it('默认展示第一个有材料的分类并显示独立列', async () => {
    const wrapper = mount(MaterialDetailPage, { global: { plugins: [ElementPlus, createPinia()] } })
    await flushPromises()
    expect(wrapper.find('h1').text()).toBe('样品用料需求详情')
    expect(wrapper.findAll('.material-detail-table th').map((cell) => cell.text())).toEqual(expect.arrayContaining(['材料分类', '规格', '需采购', '实际领料', '未领缺口']))
    expect(wrapper.findAll('.material-detail-table tbody tr')).toHaveLength(1)
    expect(wrapper.find('.material-detail-tabs button.active').text()).toContain('管材类')
  })

  it('即使材料可编辑也不显示重复填写按钮，只读详情仍可返回列表', async () => {
    const wrapper = mount(MaterialDetailPage, { global: { plugins: [ElementPlus, createPinia()] } })
    await flushPromises()
    expect(wrapper.text()).not.toContain('编辑需求')
    expect(wrapper.findAll('input, textarea')).toHaveLength(0)
    await wrapper.findAll('button').find((button) => button.text() === '返回列表')!.trigger('click')
    expect(api.push).toHaveBeenCalledWith({ name: 'samples' })
  })

  it.each(['2', '4'])('到货%s个后仍显示冻结采购需求，不混用未到货和未领缺口', async arrivedQuantity => {
    api.fetchMaterials.mockResolvedValueOnce({
      available: true, canEdit: false, draft: { lines: [], notes: '' }, etag: 'v2',
      progress: { ...progress, status: 'MATERIALS_ISSUED', label: '已领料', lines: [{
        ...progress.lines[0], procurementQuantity: '4.0000', arrivedQuantity,
        remainingQuantity: String(4 - Number(arrivedQuantity)), shortageQuantity: '1.0000',
      }] },
    })
    const wrapper = mount(MaterialDetailPage, { global: { plugins: [ElementPlus, createPinia()] } })
    await flushPromises()
    const cells = wrapper.findAll('.material-detail-table tbody tr td')
    expect(cells[7]!.text()).toBe('4.0000')
    expect(cells[8]!.text()).toBe(arrivedQuantity)
    expect(cells[10]!.text()).toBe('1.0000')
  })

  it('尚未核库时不把估算缺口显示成已核定采购量', async () => {
    const wrapper = mount(MaterialDetailPage, { global: { plugins: [ElementPlus, createPinia()] } })
    await flushPromises()
    expect(wrapper.findAll('.material-detail-table tbody tr td')[7]!.text()).toBe('—')
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

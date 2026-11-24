import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { SampleListSummary } from '@/types/sample'
import CustomerRelatedRecordsV2 from './CustomerRelatedRecordsV2.vue'

const api = vi.hoisted(() => ({ rows: vi.fn(), options: vi.fn(), stats: vi.fn(), push: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: api.push }) }))
vi.mock('@/api/samples', () => ({ fetchSamples: api.rows, fetchSampleOptions: api.options, fetchSampleStats: api.stats }))

let wrapper: ReturnType<typeof mount> | undefined
beforeEach(() => {
  vi.clearAllMocks()
  localStorage.removeItem('haiqu.customer-detail.samples.columns')
  api.options.mockResolvedValue({ statuses: [], sample_types: [], owners: [] })
  api.stats.mockResolvedValue({ all: 1, in_transit: 1, pending_feedback: 0, pending_payment: 1, finished: 0 })
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

it('客户关联页以列表摘要展示物流、申请时间和独立费用统计，查看仍进入详情', async () => {
  const row: SampleListSummary = {
    id: 'sample-summary', request_number: 'HTS-SUMMARY', customer_name: '客户甲',
    status: 'SHIPPED', status_display: '已寄出', sample_type_display: '售前样',
    item_summary: { text: '折叠椅 2 件', count: 1 }, owner: { id: 'owner', display_name: '业务甲' },
    requested_at: '2026-11-05T08:00:00+08:00', requested_due_at: null,
    latest_shipment: { status: 'IN_TRANSIT', status_display: '运输中' },
  }
  api.rows.mockResolvedValue({ data: [row], meta: { total: 1 } })
  wrapper = mount(CustomerRelatedRecordsV2, {
    props: { kind: 'samples', customerId: 'customer', customerName: '客户甲' },
    global: { plugins: [createPinia(), ElementPlus] },
  })
  await flushPromises()
  const table = wrapper.get('.el-table')
  for (const label of ['HTS-SUMMARY', '折叠椅 2 件', '已寄出', '售前样', '业务甲', '运输中', '2026/11/05']) {
    expect(table.text()).toContain(label)
  }
  expect(api.rows).toHaveBeenCalledWith(expect.objectContaining({ customer_id: 'customer', page: 1 }))
  expect(api.options).toHaveBeenCalledTimes(1)
  expect(api.stats).toHaveBeenCalledWith({ customer_id: 'customer' })
  const fee = wrapper.findAll('.customer-detail-list-shell__metrics article').find(item => item.text().includes('费用待确认'))!
  expect(fee.find('strong').text()).toBe('1')
  await table.get('button').trigger('click')
  expect(api.push).toHaveBeenCalledWith({ name: 'sample-detail', params: { sampleId: 'sample-summary' } })
})

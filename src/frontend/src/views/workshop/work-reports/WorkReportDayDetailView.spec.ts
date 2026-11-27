import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import WorkReportDayDetailView from './WorkReportDayDetailView.vue'

const api = vi.hoisted(() => ({ detail: vi.fn() }))
const router = vi.hoisted(() => ({ push: vi.fn() }))

vi.mock('vue-router', () => ({
  useRoute: () => ({
    params: { productionDate: '2026-09-28' },
    query: { schedule_product_id: 'schedule-product-1' },
  }),
  useRouter: () => router,
}))
vi.mock('@/api/workshopReporting', () => ({ fetchWorkReportDay: api.detail, deleteWorkReport: vi.fn(), fetchWorkReport: vi.fn() }))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { is_superuser: true }, hasPermission: () => true }),
}))

beforeEach(() => {
  vi.clearAllMocks()
  api.detail.mockResolvedValue({
    data: [],
    meta: { page: 1, page_size: 20, total: 0, total_pages: 0 },
  })
})

describe('内部作业计划报工日期明细', () => {
  it('用生产任务单号作为记录卡片标题，报工单号放在辅助信息首位', async () => {
    api.detail.mockResolvedValue({
      data: [{
        id: 'report-1', report_number: 'BG-001', production_task: { task_number: 'HT-001' },
        product: { name: '折叠椅', number: 'CHAIR-01' }, workshop: { name: '装配' },
        recorder: '录入人', updated_by: '修改人', total_amount: '0', lines: [],
      }],
      meta: { page: 1, page_size: 20, total: 1, total_pages: 1 },
    })
    const wrapper = mount(WorkReportDayDetailView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.get('.wr-card-title h2').text()).toBe('HT-001')
    expect(wrapper.get('.wr-card-title p').text()).toMatch(/^BG-001 · 折叠椅/)
    wrapper.unmount()
  })

  it('查询和返回汇总都保留排产产品筛选', async () => {
    const wrapper = mount(WorkReportDayDetailView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(api.detail).toHaveBeenCalledWith('2026-09-28', expect.objectContaining({
      schedule_product_id: 'schedule-product-1',
    }))
    expect(wrapper.text()).toContain('已按当前作业计划筛选')

    await wrapper.findAll('button').find(button => button.text().includes('返回汇总'))!.trigger('click')
    expect(router.push).toHaveBeenCalledWith({
      name: 'work-report-days',
      query: { schedule_product_id: 'schedule-product-1' },
    })
    wrapper.unmount()
  })
})

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
  it('查询和返回汇总都保留排产产品筛选', async () => {
    const wrapper = mount(WorkReportDayDetailView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(api.detail).toHaveBeenCalledWith('2026-09-28', expect.objectContaining({
      schedule_product_id: 'schedule-product-1',
    }))
    expect(wrapper.text()).toContain('已按当前内部作业计划筛选')

    await wrapper.findAll('button').find(button => button.text().includes('返回汇总'))!.trigger('click')
    expect(router.push).toHaveBeenCalledWith({
      name: 'work-report-days',
      query: { schedule_product_id: 'schedule-product-1' },
    })
    wrapper.unmount()
  })
})

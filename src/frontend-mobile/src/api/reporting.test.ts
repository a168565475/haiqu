import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReportingScope } from '@/types/reporting'
const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/utils/request', () => ({ apiClient: client }))
import { createWorkReport, fetchReportingContext, fetchReportingScheme, fetchWorkReports } from './reporting'

const scope: ReportingScope = { schedule_product_id: 'schedule-product', workshop_id: 'workshop', craft_id: 'craft', plan_category: 'METAL' }
beforeEach(() => vi.resetAllMocks())

describe('报工真实接口契约', () => {
  it('上下文使用work_report权限用途，工价包含排产产品限制累计范围', async () => {
    client.get.mockResolvedValueOnce({ data: { data: { schedule_product: { id: 'schedule-product' }, employees: [], workshops: [], crafts: [] } } })
    await fetchReportingContext(scope.schedule_product_id)
    expect(client.get).toHaveBeenLastCalledWith('/api/v1/workshop-reporting/context/', expect.objectContaining({ params: { schedule_product_id: 'schedule-product', purpose: 'work_report' } }))
    client.get.mockResolvedValueOnce({ data: { data: { id: 'scheme', status: 'APPROVED', revision: 1, product_line_id: 'product', workshop: { id: 'workshop' }, scope_craft: { id: 'craft' }, lines: [] } } })
    await fetchReportingScheme(scope, 'product', '2026-10-31')
    expect(client.get).toHaveBeenLastCalledWith('/api/v1/workshop-reporting/work-reports/price-context/', expect.objectContaining({ params: { product_line_id: 'product', schedule_product_id: 'schedule-product', workshop_id: 'workshop', craft_id: 'craft', production_date: '2026-10-31' } }))
  })
  it('记录请求始终带产品、车间与工艺范围及服务端分页', async () => {
    client.get.mockResolvedValue({ data: { data: [], meta: { page: 2, total: 25, total_pages: 2 } } })
    await fetchWorkReports(scope, 2)
    expect(client.get).toHaveBeenLastCalledWith('/api/v1/workshop-reporting/work-reports/', expect.objectContaining({ params: { schedule_product_id: 'schedule-product', workshop_id: 'workshop', plan_category: 'METAL', craft_id: 'craft', page: 2, page_size: 20 } }))
  })
  it('计划全部工艺查询省略craft_id，但保留计划分类和车间边界', async () => {
    client.get.mockResolvedValue({ data: { data: [], meta: { page: 1, total: 0, total_pages: 0 } } })
    const { craft_id: _craft, ...planScope } = scope
    await fetchWorkReports(planScope, 1)
    expect(client.get).toHaveBeenLastCalledWith('/api/v1/workshop-reporting/work-reports/', expect.objectContaining({ params: { schedule_product_id: 'schedule-product', workshop_id: 'workshop', plan_category: 'METAL', page: 1, page_size: 20 } }))
  })
  it('缺少服务端保存结果时不显示假成功', async () => {
    client.post.mockResolvedValue({ data: {} })
    await expect(createWorkReport({ client_request_id: 'request', production_date: '2026-10-31', schedule_product_id: 'product', scheme_id: 'scheme', scheme_revision: 1, confirm_plan_completion: false, lines: [] })).rejects.toThrow('未收到报工结果')
  })
})

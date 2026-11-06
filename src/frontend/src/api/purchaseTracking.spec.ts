import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from './request'
import { fetchPurchaseTrackingArrivals, fetchPurchaseTrackingCoverage, fetchPurchaseTrackingFilterOptions, fetchPurchaseTrackingPolicy, updatePurchaseTrackingPolicy } from './purchaseTracking'

vi.mock('./request', () => ({ apiClient: { get: vi.fn(), patch: vi.fn() } }))

describe('采购跟踪只读接口', () => {
  beforeEach(() => vi.clearAllMocks())

  it.each([
    [fetchPurchaseTrackingArrivals, 'arrivals'],
    [fetchPurchaseTrackingCoverage, 'coverage'],
  ] as const)('保留分页、历史定位和未知数量：%s', async (fetchRows, resource) => {
    const body = { data: [{ row_key: 'coverage:product:bom-line', remaining_quantity: null }], meta: { page: 2, page_size: 20, total: 21, total_pages: 2 } }
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: body })
    const query = { page: 2, page_size: 20, include_history: true, row_key: 'coverage:product:bom-line', production_task_id: 'task-1' }
    const signal = new AbortController().signal
    expect(await fetchRows(query, signal)).toEqual(body)
    expect(apiClient.get).toHaveBeenCalledWith(`/api/v1/purchase-tracking/${resource}/`, { params: query, signal })
  })

  it('选项使用专门的可见需求接口，失败原样传给页面', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { data: { production_tasks: [{ id: 'no-group', task_number: 'SC-1', order_number: '' }] } } })
    expect((await fetchPurchaseTrackingFilterOptions()).production_tasks[0]?.id).toBe('no-group')
    const error = { response: { status: 403 } }
    vi.mocked(apiClient.get).mockRejectedValueOnce(error)
    await expect(fetchPurchaseTrackingFilterOptions()).rejects.toBe(error)
  })

  it('规则从服务端读取，保存保留空值并携带并发版本', async () => {
    const data = { bom_timeout_days: 2, category_lead_days: { TUBE: 2 }, categories: [{ key: 'TUBE', label: '管材' }], etag: 'policy-v1', can_manage: true }
    const signal = new AbortController().signal
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { data } })
    expect(await fetchPurchaseTrackingPolicy(signal)).toEqual(data)
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/purchase-tracking-policy/', { signal })
    const payload = { bom_timeout_days: null, category_lead_days: { TUBE: 0 } }
    vi.mocked(apiClient.patch).mockResolvedValueOnce({ data: { data: { ...data, ...payload, etag: 'policy-v2' } } })
    expect((await updatePurchaseTrackingPolicy(payload, data.etag)).etag).toBe('policy-v2')
    expect(apiClient.patch).toHaveBeenCalledWith('/api/v1/purchase-tracking-policy/', payload, { headers: { 'If-Match': 'policy-v1' } })
  })

  it('规则冲突原样交给调用者处理', async () => {
    const error = { response: { status: 412 } }
    vi.mocked(apiClient.patch).mockRejectedValueOnce(error)
    await expect(updatePurchaseTrackingPolicy({ bom_timeout_days: 2, category_lead_days: {} }, 'old')).rejects.toBe(error)
  })
})

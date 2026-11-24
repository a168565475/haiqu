import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchSamples, fetchSampleStats, fetchSampleOptions, fetchSampleFilterOptions, fetchSampleInventoryEligible, fetchSampleOutboundEligible, fetchSampleLoanEligible } from './samples'

const get = vi.hoisted(() => vi.fn())
vi.mock('./request', () => ({ apiClient: { get } }))

describe('打样列表 API 契约', () => {
  beforeEach(() => { get.mockReset(); get.mockResolvedValue({ data: { data: [], meta: { total: 0 } } }) })
  it('查询将 search 映射为后端实际使用的 q', async () => {
    const query = { page: 1, page_size: 20, search: '  SRQ-12  ', status: 'PMC_REVIEW' }
    await fetchSamples(query)
    expect(get).toHaveBeenLastCalledWith('/api/v1/sample-requests/', { params: { page: 1, page_size: 20, q: 'SRQ-12', status: 'PMC_REVIEW' } })
    expect(query.search).toBe('  SRQ-12  ')
  })

  it('个人统计用服务端 summary 的真实 owner_employee_id 过滤', async () => {
    get.mockResolvedValueOnce({ data: { data: { all: 3 } } })
    await fetchSampleStats({ owner_employee_id: 'me' })
    expect(get).toHaveBeenLastCalledWith('/api/v1/sample-requests/summary/', { params: { owner_employee_id: 'me' } })
  })

  it('列表读取轻量筛选，费用和客户页继续读取完整选项', async () => {
    const filters = { sample_types: [], statuses: [], owner_filters: [{ id: 'owner', display_name: '业务员' }] }
    get.mockResolvedValueOnce({ data: { data: filters } })
    expect(await fetchSampleFilterOptions()).toEqual(filters)
    expect(get).toHaveBeenLastCalledWith('/api/v1/sample-requests/options/', { params: { scope: 'filters' } })
    await fetchSampleOptions()
    expect(get).toHaveBeenLastCalledWith('/api/v1/sample-requests/options/')
  })
})

describe('打样编辑 API 契约', () => {
  it('借出候选支持后续页并拒绝非法页码', async () => {
    get.mockResolvedValue({ data: { data: [], meta: { total: 0 } } })
    await fetchSampleLoanEligible(2)
    expect(get).toHaveBeenLastCalledWith('/api/v1/sample-loans/eligible/', { params: { page: 2, page_size: 100 } })
    const calls = get.mock.calls.length
    await expect(fetchSampleLoanEligible(-1)).rejects.toThrow('页码必须为正整数')
    expect(get).toHaveBeenCalledTimes(calls)
  })
  it('出库候选支持后续页并拒绝非法页码', async () => {
    get.mockResolvedValue({ data: { data: [], meta: { total: 0 } } })
    await fetchSampleOutboundEligible(2)
    expect(get).toHaveBeenLastCalledWith('/api/v1/sample-outbound/eligible/', { params: { page: 2, page_size: 100 } })
    const calls = get.mock.calls.length
    await expect(fetchSampleOutboundEligible(1.5)).rejects.toThrow('页码必须为正整数')
    expect(get).toHaveBeenCalledTimes(calls)
  })
  it('入库候选支持后续页并拒绝非法页码', async () => {
    get.mockResolvedValue({ data: { data: [], meta: { total: 0 } } })
    await fetchSampleInventoryEligible(2)
    expect(get).toHaveBeenLastCalledWith('/api/v1/sample-inventory/eligible/', { params: { page: 2, page_size: 100 } })
    const calls = get.mock.calls.length
    await expect(fetchSampleInventoryEligible(0)).rejects.toThrow('页码必须为正整数')
    expect(get).toHaveBeenCalledTimes(calls)
  })
})

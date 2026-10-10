import { beforeEach, describe, expect, it, vi } from 'vitest'
import { exportSamples, fetchSamples, fetchSampleStats, patchSampleForm, fetchSampleInventoryEligible, fetchSampleOutboundEligible, fetchSampleLoanEligible } from './samples'
import type { SampleRequestFormInput } from '@/types/sample'

const get = vi.hoisted(() => vi.fn())
const patch = vi.hoisted(() => vi.fn())
vi.mock('./request', () => ({ apiClient: { get, patch } }))

describe('打样列表 API 契约', () => {
  beforeEach(() => { get.mockReset(); get.mockResolvedValue({ data: { data: [], meta: { total: 0 } } }) })
  it('查询与导出都将 search 映射为后端实际使用的 q', async () => {
    const query = { page: 1, page_size: 20, search: '  SRQ-12  ', status: 'PMC_REVIEW' }
    await fetchSamples(query)
    expect(get).toHaveBeenLastCalledWith('/api/v1/sample-requests/', { params: { page: 1, page_size: 20, q: 'SRQ-12', status: 'PMC_REVIEW' } })
    await exportSamples(query)
    expect(get).toHaveBeenLastCalledWith('/api/v1/sample-requests/export/', { params: { page: 1, page_size: 20, q: 'SRQ-12', status: 'PMC_REVIEW' }, responseType: 'blob' })
    expect(query.search).toBe('  SRQ-12  ')
  })

  it('个人统计用服务端 summary 的真实 owner_employee_id 过滤', async () => {
    get.mockResolvedValueOnce({ data: { data: { all: 3 } } })
    await fetchSampleStats({ owner_employee_id: 'me' })
    expect(get).toHaveBeenLastCalledWith('/api/v1/sample-requests/summary/', { params: { owner_employee_id: 'me' } })
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
  it('报工编辑发送完整 JSON 与 If-Match，省略文件字段以保留已有附件', async () => {
    const payload = { purpose: '补充说明', products: [{ id: 'product', client_key: 'product', details: [{ id: 'line' }], sampling_details: [{ id: 'material', client_key: 'material' }] }] } as SampleRequestFormInput
    patch.mockResolvedValueOnce({ data: { data: { id: 'sample' } }, headers: { etag: '"new-version"' } })
    const result = await patchSampleForm('sample', payload, {}, {}, '"old-version"')
    const [url, body, config] = patch.mock.calls[0]!
    expect(url).toBe('/api/v1/sample-requests/sample/form/')
    expect(config.headers['If-Match']).toBe('"old-version"')
    expect(body).toBeInstanceOf(FormData)
    expect(Array.from(body.keys())).toEqual(['payload'])
    expect(JSON.parse(body.get('payload'))).toEqual(payload)
    expect(result).toEqual({ data: { id: 'sample' }, etag: '"new-version"' })
  })
})

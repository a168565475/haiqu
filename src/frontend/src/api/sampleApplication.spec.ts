import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchSampleApplicationListSummary, submitSampleApplication, reviewSampleApplication } from './sampleApplication'
import type { SampleApplicationDraft } from '@/types/sampleApplication'
const stats = vi.hoisted(() => vi.fn())
const post = vi.hoisted(() => vi.fn())
vi.mock('./samples', () => ({ fetchSampleStats: stats }))
vi.mock('./request', () => ({ apiClient: { post } }))
beforeEach(() => stats.mockReset())

describe('V3 快捷分类真实统计', () => {
  it('个人统计失败不丢失全部统计，不把失败视为零', async () => {
    stats.mockResolvedValueOnce({ all: 128 }).mockRejectedValueOnce(new Error('Forbidden'))
    const value = await fetchSampleApplicationListSummary('employee')
    expect(value.all).toBe(128)
    expect(value.responsible).toBeNull()
    expect(value.failures[0]?.scope).toBe('responsible')
    expect(stats).toHaveBeenLastCalledWith({ owner_employee_id: 'employee' })
  })

  it('未关联员工只查询全部统计', async () => {
    stats.mockResolvedValue({ all: 0 })
    expect(await fetchSampleApplicationListSummary(null)).toEqual({ all: 0, responsible: null, failures: [] })
    expect(stats).toHaveBeenCalledTimes(1)
  })

  it.each([null, {}, { all: -1 }, { all: 1.5 }, { all: '12' }])('拒绝无效计数 %j', async value => {
    stats.mockResolvedValue(value)
    const result = await fetchSampleApplicationListSummary(null)
    expect(result.all).toBeNull()
    expect(result.failures).toHaveLength(1)
  })
})

describe('申请提交和厂长审核接口', () => {
  const draft: SampleApplicationDraft = {
    sourceType: null, sourceId: '', sourceProductId: '', customerId: 'customer', contactId: '', ownerId: 'owner',
    sampleType: 'PRE_SALES', shippingMethod: 'MAIL', deliveryBatch: 'SINGLE', repeatOrder: false,
    orderDate: '', dueDate: '', productName: '折叠椅', specification: '黑色', lengthCm: '50', armrestWidthCm: '', seatWidthCm: '', backHeightCm: '', seatHeightCm: '',
    requirements: '包装要求', quantity: 2, referenceImage: null,
  }
  beforeEach(() => { post.mockReset() })
  it('提交全部原型字段、参考图片和稳定的提交标识，使用真实返回编号', async () => {
    const image = new File(['png'], 'reference.png', { type: 'image/png' })
    post.mockResolvedValue({ data: { data: { id: 'created', etag: 'v1' } }, headers: { etag: 'v1' } })
    expect(await submitSampleApplication({ ...draft, referenceImage: image }, { key: 'stable-key' })).toEqual({ id: 'created', etag: 'v1' })
    const [url, body] = post.mock.calls[0]!
    expect(url).toBe('/api/v1/sample-requests/applications/')
    expect(body.get('reference_image')).toBe(image)
    expect(JSON.parse(body.get('payload'))).toMatchObject({ idempotency_key: 'stable-key', quantity: 2, length_cm: '50', sample_due_date: null, purpose: '包装要求' })
  })
  it('审核及退回重提都携带 If-Match，服务失败不会返回假成功', async () => {
    post.mockRejectedValue(new Error('断网'))
    await expect(submitSampleApplication(draft, { key: 'key', sampleId: 'existing', etag: 'v1' })).rejects.toThrow('断网')
    expect(post.mock.calls[0]![0]).toBe('/api/v1/sample-requests/existing/application-resubmit/')
    expect(post.mock.calls[0]![2].headers).toEqual({ 'If-Match': 'v1' })
    await expect(reviewSampleApplication({ sampleId: 'existing', etag: 'v2', decision: 'return', note: ' 补充规格 ' })).rejects.toThrow('断网')
    expect(post).toHaveBeenLastCalledWith('/api/v1/sample-requests/existing/director-review/', { decision: 'return', note: '补充规格' }, { headers: { 'If-Match': 'v2' } })
  })
  it('缺少版本和退回意见时不发送请求', async () => {
    await expect(reviewSampleApplication({ sampleId: 'sample', etag: '', decision: 'approve', note: '' })).rejects.toThrow('版本')
    await expect(reviewSampleApplication({ sampleId: 'sample', etag: 'v1', decision: 'return', note: ' ' })).rejects.toThrow('退回时')
    expect(post).not.toHaveBeenCalled()
  })
})

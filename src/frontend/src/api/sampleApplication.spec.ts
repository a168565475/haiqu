import { beforeEach, describe, expect, it, vi } from 'vitest'
import { submitSampleApplication, reviewSampleApplication, completeSampleApplicationProducts } from './sampleApplication'
import type { SampleApplicationBasicInput, SampleApplicationDraft } from '@/types/sampleApplication'
import type { SampleProductEdit } from '@/types/sampleEditor'
const post = vi.hoisted(() => vi.fn())
const patch = vi.hoisted(() => vi.fn())
vi.mock('./request', () => ({ apiClient: { post, patch } }))

describe('申请提交和厂长审核接口', () => {
  const draft: SampleApplicationDraft = {
    sourceType: null, sourceId: '', sourceProductId: '', productId: 'product-id', customerId: 'customer', contactId: '', ownerId: 'owner',
    sampleType: 'PRE_SALES', shippingMethod: 'MAIL', deliveryBatch: 'SINGLE', repeatOrder: false,
    orderDate: '', dueDate: '', productName: '折叠椅', specification: '黑色', lengthCm: '50', armrestWidthCm: '', seatWidthCm: '', backHeightCm: '', seatHeightCm: '',
    requirements: '包装要求', quantity: 2, referenceImage: null,
  }
  beforeEach(() => { post.mockReset(); patch.mockReset() })
  it('合并展示中的材质独立提交，删除标签可以明确清空材质', async () => {
    patch.mockResolvedValue({ data: { data: { id: 'sample' } }, headers: { etag: 'v2' } })
    const product: SampleProductEdit = { id: 'p', product_id: '', category_id: 'c', product_name: '椅子',
      specification: '60×80；颜色：黑色；材质：铝', length_cm: null, armrest_width_cm: null,
      seat_width_cm: null, back_height_cm: null, seat_height_cm: null, details: [] }
    await completeSampleApplicationProducts('sample', 'v1', [product], '')
    expect(patch.mock.calls[0]![1].products[0].material_snapshot).toBe('铝')
    await completeSampleApplicationProducts('sample', 'v2', [{ ...product, specification: '60×80；颜色：黑色' }], '')
    expect(patch.mock.calls[1]![1].products[0].material_snapshot).toBe('')
  })
  it('基础字段与产品及图片使用同一版本原子提交', async () => {
    patch.mockResolvedValue({ data: { data: { id: 'sample', etag: 'v2' } }, headers: { etag: 'v2' } })
    const basic: SampleApplicationBasicInput = { source_type: null, source_id: null, customer_account_id: 'customer', customer_contact_id: null, owner_employee_id: 'owner', sample_type: 'PRE_SALES', shipping_method: 'MAIL', delivery_batch: 'SINGLE', is_repeat_order: false, order_date: null, sample_due_date: null }
    await completeSampleApplicationProducts('sample', 'v1', [], '要求', undefined, basic)
    expect(patch.mock.calls[0]![1].basic).toEqual(basic)
    await completeSampleApplicationProducts('sample', 'v2', [], '要求', new File(['png'], 'reference.png', { type: 'image/png' }), basic)
    expect(JSON.parse(patch.mock.calls[1]![1].get('payload')).basic).toEqual(basic)
    expect(patch.mock.calls[1]![2].headers).toEqual({ 'If-Match': 'v2' })
  })
  it('产品完善无图保留JSON，有图同PATCH发送multipart及If-Match，不使用创建接口', async () => {
    patch.mockResolvedValue({ data: { data: { id: 'sample', etag: 'v2' } }, headers: { etag: 'v2' } })
    await completeSampleApplicationProducts('sample', 'v1', [], '要求')
    expect(patch.mock.calls[0]).toEqual(['/api/v1/sample-requests/sample/application-products/', { products: [], purpose: '要求' }, { headers: { 'If-Match': 'v1' } }])
    const image = new File(['png'], 'reference.png', { type: 'image/png' })
    await completeSampleApplicationProducts('sample', 'v1', [], '要求', image)
    const [url, body, config] = patch.mock.calls[1]!
    expect(url).toBe('/api/v1/sample-requests/sample/application-products/')
    expect(body.get('reference_image')).toBe(image)
    expect(JSON.parse(body.get('payload'))).toEqual({ products: [], purpose: '要求' })
    expect(config).toEqual({ headers: { 'If-Match': 'v1' }, timeout: 60000 })
    expect(post).not.toHaveBeenCalled()
  })
  it('提交全部原型字段、参考图片和稳定的提交标识，使用真实返回编号', async () => {
    const image = new File(['png'], 'reference.png', { type: 'image/png' })
    post.mockResolvedValue({ data: { data: { id: 'created', etag: 'v1', status: 'DIRECTOR_REVIEW' } }, headers: { etag: 'v1' } })
    expect(await submitSampleApplication({ ...draft, referenceImage: image }, { key: 'stable-key' })).toEqual({ id: 'created', etag: 'v1', status: 'DIRECTOR_REVIEW' })
    const [url, body] = post.mock.calls[0]!
    expect(url).toBe('/api/v1/sample-requests/applications/')
    expect(body.get('reference_image')).toBe(image)
    expect(JSON.parse(body.get('payload'))).toMatchObject({ idempotency_key: 'stable-key', quantity: 2, product_id: 'product-id', length_cm: '50', sample_due_date: null, purpose: '包装要求' })
  })
  it('返回服务端真实生效状态，供创建页决定后续入口', async () => {
    post.mockResolvedValue({ data: { data: { id: 'factory-created', etag: 'v1', status: 'PENDING_COMPLETION' } }, headers: {} })
    expect((await submitSampleApplication(draft, { key: 'factory-key' })).status).toBe('PENDING_COMPLETION')
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

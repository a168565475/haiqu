import { beforeEach, describe, expect, it, vi } from 'vitest'
import { submitSampleApplication, reviewSampleApplication, completeSampleApplicationProducts } from './sampleApplication'
import type { SampleApplicationBasicInput, SampleApplicationDraft } from '@/types/sampleApplication'
import type { SampleProductEdit } from '@/types/sampleEditor'
import { emptyProductEntry } from '@/utils/productEntryDraft'
const post = vi.hoisted(() => vi.fn())
const patch = vi.hoisted(() => vi.fn())
vi.mock('./request', () => ({ apiClient: { post, patch } }))

describe('申请提交和厂长审核接口', () => {
  const draft: SampleApplicationDraft = {
    manualRequestNumber: '123', productColorId: 'color1', isSalesperson: true,
    sourceType: null, sourceId: '', sourceProductId: '', productId: 'product-id', customerId: 'customer', contactId: '', ownerId: 'owner',
    sampleType: 'PRE_SALES', shippingMethod: 'MAIL', deliveryBatch: 'SINGLE', repeatOrder: false,
    orderDate: '', dueDate: '', productName: '折叠椅', specification: '黑色', lengthCm: '50', armrestWidthCm: '', seatWidthCm: '', backHeightCm: '', seatHeightCm: '',
    requirements: '包装要求', quantity: 2, referenceImage: null,
  }
  beforeEach(() => { post.mockReset(); patch.mockReset() })
  it('无目录 ID 的产品草稿可提交和完善，保留输入来源且保留公共颜色身份', async () => {
    post.mockResolvedValue({ data: { data: { id: 'sample', status: 'DIRECTOR_REVIEW' } }, headers: { etag: 'v1' } })
    patch.mockResolvedValue({ data: { data: { id: 'sample' } }, headers: { etag: 'v2' } })
    const selection = { draft: { ...emptyProductEntry(), category_name: '新类别', name: '新椅子', specification: '60×80', unit_name: '新单位', color_name: '酒红', material: '新材质' } }
    await submitSampleApplication({ ...draft, productCatalogId: '', productSelection: selection }, { key: 'typed-product' })
    expect(JSON.parse(post.mock.calls[0]![1].get('payload'))).toMatchObject({ product_id: null, product_catalog_id: null, product_selection: selection })
    const product: SampleProductEdit = { id: 'p', product_id: 'old', category_id: 'old-category', product_name: '新椅子', product_catalog_id: null, product_selection: selection,
      specification: '60×80', length_cm: null, armrest_width_cm: null, seat_width_cm: null, back_height_cm: null, seat_height_cm: null,
      details: [{ id: 'detail', product_color_id: 'old-color', color_code: '', sample_quantity: 2, tolerance: 'NONE', notes: '' }] }
    await completeSampleApplicationProducts('sample', 'v1', [product], '')
    const saved = patch.mock.calls[0]![1].products[0]
    expect(saved).toMatchObject({ product_id: null, category_id: null, product_catalog_id: null, product_selection: selection })
    expect(saved.details[0].product_color_id).toBe('old-color')
    expect(saved).not.toHaveProperty('material_snapshot')
  })
  it('新产品提交新ID和属性，来源单据不重选且不发送旧产品ID', async () => {
    post.mockResolvedValue({ data: { data: { id: 'sample', status: 'DIRECTOR_REVIEW' } }, headers: { etag: 'v1' } })
    const selection = { catalog_version: '2026-10-31T00:00:00+00:00', color_id: 'blue', material: '铁', thickness: '0.8' }
    await submitSampleApplication({ ...draft, productCatalogId: 'catalog-1', productSelection: selection }, { key: 'create-new' })
    expect(JSON.parse(post.mock.calls[0]![1].get('payload'))).toMatchObject({ product_id: null, product_catalog_id: 'catalog-1', product_selection: selection })
    await submitSampleApplication({ ...draft, sourceType: 'quotation', sourceId: 'quote-1', sourceProductId: 'line-1', productCatalogId: 'catalog-1', productSelection: selection }, { key: 'create-source' })
    const inherited = JSON.parse(post.mock.calls[1]![1].get('payload'))
    expect(inherited.product_catalog_id).toBe('catalog-1')
    expect(inherited.product_selection).toEqual(selection)
  })
  it('完善新产品不提交只读快照或旧类别ID，不从展示规格清空材质', async () => {
    patch.mockResolvedValue({ data: { data: { id: 'sample' } }, headers: { etag: 'v2' } })
    const product: SampleProductEdit = { id: 'p', product_id: 'legacy', category_id: 'old-category', product_name: '椅子',
      product_catalog_id: 'catalog-1', product_selection: null, product_selection_snapshot: null,
      specification: '60×80', length_cm: null, armrest_width_cm: null, seat_width_cm: null, back_height_cm: null, seat_height_cm: null,
      details: [{ id: 'detail', product_color_id: 'old-color', color_code: '', sample_quantity: 1, tolerance: 'NONE', notes: '' }] }
    await completeSampleApplicationProducts('sample', 'v1', [product], '')
    const saved = patch.mock.calls[0]![1].products[0]
    expect(saved).toMatchObject({ product_id: null, product_catalog_id: 'catalog-1', category_id: null, product_selection: null })
    expect(saved.details[0].product_color_id).toBe('old-color')
    expect(saved).not.toHaveProperty('product_selection_snapshot')
    expect(saved).not.toHaveProperty('material_snapshot')
  })
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
  it('提交手填单号和公共颜色及参考图片，使用真实返回编号', async () => {
    const image = new File(['png'], 'reference.png', { type: 'image/png' })
    post.mockResolvedValue({ data: { data: { id: 'created', etag: 'v1', status: 'DIRECTOR_REVIEW' } }, headers: { etag: 'v1' } })
    expect(await submitSampleApplication({ ...draft, referenceImage: image }, { key: 'stable-key' })).toEqual({ id: 'created', etag: 'v1', status: 'DIRECTOR_REVIEW' })
    const [url, body] = post.mock.calls[0]!
    expect(url).toBe('/api/v1/sample-requests/applications/')
    expect(body.get('reference_image')).toBe(image)
    expect(JSON.parse(body.get('payload'))).toMatchObject({ manual_request_number: '123', product_color_id: 'color1', idempotency_key: 'stable-key', quantity: 2, product_id: 'product-id', length_cm: '50', sample_due_date: null, purpose: '包装要求' })
  })
  it('非业务员新建和编辑均不发送隐藏的客户联系人字段', async () => {
    post.mockResolvedValue({ data: { data: { id: 'sample', status: 'DIRECTOR_REVIEW' } }, headers: { etag: 'v1' } })
    patch.mockResolvedValue({ data: { data: { id: 'sample' } }, headers: { etag: 'v2' } })
    await submitSampleApplication({ ...draft, isSalesperson: false }, { key: 'internal' })
    const created = JSON.parse(post.mock.calls[0]![1].get('payload'))
    expect(created).not.toHaveProperty('customer_account_id')
    expect(created).not.toHaveProperty('customer_contact_id')
    const basic: SampleApplicationBasicInput = { manual_request_number: '456', is_salesperson: false, source_type: null, source_id: null, customer_account_id: 'retained', customer_contact_id: 'retained-contact', owner_employee_id: 'owner', sample_type: 'PRE_SALES', shipping_method: 'MAIL', delivery_batch: 'SINGLE', is_repeat_order: false, order_date: null, sample_due_date: null }
    await completeSampleApplicationProducts('sample', 'v1', [], '', undefined, basic)
    expect(patch.mock.calls[0]![1].basic).toMatchObject({ manual_request_number: '456' })
    expect(patch.mock.calls[0]![1].basic).not.toHaveProperty('customer_account_id')
    expect(patch.mock.calls[0]![1].basic).not.toHaveProperty('is_salesperson')
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

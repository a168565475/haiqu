import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchInquiryHandlingSettings, saveInquiryHandlingSettings } from './inquiryHandlingSettings'
import { fetchQuotationInquiryImages, selectQuotationInquiryImage, uploadQuotationLineProductImage } from './quotations'
const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }))
vi.mock('./request', () => ({ apiClient: api }))
beforeEach(() => vi.clearAllMocks())
describe('规则与来源询盘图片接口', () => {
  it('读取及保存规则保留服务端版本', async () => {
    const data = { stage_minutes: { FIRST_RESPONSE: 240 }, work_calendar: { mode: 'ALTERNATING_WEEKS_V1' } } as never
    api.get.mockResolvedValue({ data: { data }, headers: { etag: 'v1' } })
    expect(await fetchInquiryHandlingSettings()).toEqual({ data, etag: 'v1' })
    api.put.mockResolvedValue({ data: { data }, headers: { etag: 'v2' } })
    expect(await saveInquiryHandlingSettings(data, 'v1')).toEqual({ data, etag: 'v2' })
    expect(api.put).toHaveBeenCalledWith('/api/v1/inquiry-handling-time/settings/', data, { headers: { 'If-Match': 'v1' } })
  })
  it('选图使用当前报价图片接口并传递报价版本，上传仍使用文件', async () => {
    const images = [{ id: 'image', name: '产品.png', url: '/image.png' }]
    api.get.mockResolvedValue({ data: { data: images } })
    expect(await fetchQuotationInquiryImages('quote')).toEqual(images)
    expect(api.get).toHaveBeenCalledWith('/api/v1/quotations/quote/inquiry-images/')
    api.post.mockResolvedValue({ data: { data: { id: 'line' } }, headers: { etag: 'v2' } })
    expect(await selectQuotationInquiryImage('line', 'image', 'v1')).toEqual({ data: { id: 'line' }, etag: 'v2' })
    expect(api.post).toHaveBeenCalledWith('/api/v1/quotation-lines/line/product-image/', { source_image_id: 'image' }, { headers: { 'If-Match': 'v1' } })
    const image = new File(['png'], 'replacement.png', { type: 'image/png' })
    await uploadQuotationLineProductImage('line', image, 'v2')
    expect(api.post.mock.calls[1]![1].get('file')).toBe(image)
    expect(api.post.mock.calls[1]![2].headers['If-Match']).toBe('v2')
  })
})

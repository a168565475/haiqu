import { describe, expect, it } from 'vitest'
import type { SampleApplicationDraft } from '@/types/sampleApplication'
import { validateSampleApplication, validateSampleReferenceImage } from './sampleApplication'

const validDraft = (): SampleApplicationDraft => ({
  sourceType: null, sourceId: '', sourceProductId: '', productId: '', customerId: 'customer', contactId: '', ownerId: 'owner',
  sampleType: 'PRE_SALES', shippingMethod: 'EXPRESS', deliveryBatch: 'ONCE', repeatOrder: false, orderDate: '', dueDate: '',
  productName: '椅子', specification: '', lengthCm: '', armrestWidthCm: '', seatWidthCm: '', backHeightCm: '', seatHeightCm: '',
  requirements: '', quantity: 2, referenceImage: null,
})

describe('V3 创建页校验与接口门禁', () => {
  it('允许原型中的可选日期、尺寸和图片为空，不再强求色卡与打样明细', () => {
    expect(validateSampleApplication(validDraft())).toBe('')
  })
  it.each([0, -1, 1.2, NaN, Infinity, null])('拒绝非法数量 %s', quantity => {
    expect(validateSampleApplication({ ...validDraft(), quantity })).toContain('大于 0 的整数')
  })
  it('来源存在时必须明确选择产品，尺寸不接受负数或过多小数', () => {
    expect(validateSampleApplication({ ...validDraft(), sourceId: 'inquiry' })).toContain('来源中的样品')
    expect(validateSampleApplication({ ...validDraft(), lengthCm: '-1' })).toContain('尺寸')
    expect(validateSampleApplication({ ...validDraft(), lengthCm: '1.234' })).toContain('尺寸')
    expect(validateSampleApplication({ ...validDraft(), lengthCm: '57.25' })).toBe('')
  })
  it('拒绝空文件、错误类型和超过 5MB 的图片', () => {
    expect(validateSampleReferenceImage({ type: 'image/png', size: 0 })).toContain('为空')
    expect(validateSampleReferenceImage({ type: 'application/pdf', size: 100 })).toContain('仅支持')
    expect(validateSampleReferenceImage({ type: 'image/jpeg', size: 5 * 1024 * 1024 + 1 })).toContain('5MB')
    expect(validateSampleReferenceImage({ type: 'image/png', size: 5 * 1024 * 1024 })).toBe('')
  })
})

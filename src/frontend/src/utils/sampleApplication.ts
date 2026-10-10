import { sampleDimensionFields, type SampleApplicationDraft } from '@/types/sampleApplication'

export function validateSampleApplication(draft: SampleApplicationDraft): string {
  if (!draft.customerId || !draft.ownerId) return '请选择客户和业务员。'
  if (!draft.sampleType || !draft.shippingMethod || !draft.deliveryBatch || draft.repeatOrder === null) return '请选择样品类型、寄送方式、交货方式和是否返单。'
  if (draft.sourceId && !draft.sourceProductId) return '请选择来源中的样品。'
  if (!draft.productName.trim()) return '请填写产品名称。'
  if (!Number.isSafeInteger(draft.quantity) || Number(draft.quantity) <= 0) return '打样数量必须是大于 0 的整数。'
  for (const field of sampleDimensionFields) {
    const value = draft[field.key].trim()
    if (value && (!/^\d+(\.\d{1,2})?$/.test(value) || Number(value) <= 0 || Number(value) >= 100000000)) return `${field.label}请填写大于 0、最多两位小数的尺寸。`
  }
  if (draft.requirements.length > 2000) return '特殊要求不能超过 2000 字。'
  return draft.referenceImage ? validateSampleReferenceImage(draft.referenceImage) : ''
}

export function validateSampleReferenceImage(file: Pick<File, 'type' | 'size'>): string {
  if (!['image/jpeg', 'image/png'].includes(file.type)) return '参考图片仅支持 JPG、PNG。'
  if (file.size <= 0) return '参考图片为空，请重新选择。'
  if (file.size > 5 * 1024 * 1024) return '单张参考图片不能超过 5MB。'
  return ''
}

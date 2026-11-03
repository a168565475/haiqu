import { sampleDimensionFields, type SampleApplicationDraft } from '@/types/sampleApplication'
import { emptyProductEntry, productEntryFromSnapshot } from './productEntryDraft'
import type { ProductSelectionInput, ProductSelectionSnapshot } from '@/types/productCatalog'

export function validateSampleApplication(draft: SampleApplicationDraft): string {
  const numberError = validateSampleNumber(draft.manualRequestNumber)
  if (numberError) return numberError
  if (draft.isSalesperson && !draft.customerId) return '请选择客户。'
  if (!draft.ownerId) return '请选择业务员。'
  if (!draft.sampleType || !draft.shippingMethod || !draft.deliveryBatch || draft.repeatOrder === null) return '请选择样品类型、寄送方式、交货方式和是否返单。'
  if (draft.sourceId && !draft.sourceProductId) return '请选择来源中的样品。'
  if (!draft.productName.trim()) return '请填写产品名称。'
  if (!draft.productSelection?.draft?.category_name.trim()) return '请选择或填写类别。'
  if (!draft.specification.trim()) return '请填写规格。'
  if (!draft.productColorId) return '请选择色卡 / 色号 / 颜色。'
  if (!Number.isSafeInteger(draft.quantity) || Number(draft.quantity) <= 0) return '打样数量必须是大于 0 的整数。'
  for (const field of sampleDimensionFields) {
    const value = draft[field.key].trim()
    if (value && (!/^\d+(\.\d{1,2})?$/.test(value) || Number(value) <= 0 || Number(value) >= 100000000)) return `${field.label}请填写大于 0、最多两位小数的尺寸。`
  }
  if (draft.requirements.length > 2000) return '特殊要求不能超过 2000 字。'
  return draft.referenceImage ? validateSampleReferenceImage(draft.referenceImage) : ''
}

export function validateSampleNumber(value: string): string {
  if (!value.trim()) return '请填写打样单号后缀。'
  if (/^HTS/i.test(value.trim())) return '只需填写打样单号后缀，不要重复填写 HTS。'
  return ''
}

export function sampleProductSelection(name: string, specification: string, snapshot?: ProductSelectionSnapshot | null, colorName = ''): ProductSelectionInput {
  const draft = snapshot?.name ? productEntryFromSnapshot(snapshot) : emptyProductEntry()
  return { draft: { ...draft, name_id: null, name: name.trim(), specification: specification.trim(),
    unit_name: draft.unit_name || 'PCS', color_id: null, color_name: colorName || draft.color_name,
    sources: { ...draft.sources, name: 'typed', specification: 'typed', color_name: 'typed', item_number: 'typed', product_code: 'typed', material: 'typed' } } }
}

export function validateSampleReferenceImage(file: Pick<File, 'type' | 'size'>): string {
  if (!['image/jpeg', 'image/png'].includes(file.type)) return '参考图片仅支持 JPG、PNG。'
  if (file.size <= 0) return '参考图片为空，请重新选择。'
  if (file.size > 5 * 1024 * 1024) return '单张参考图片不能超过 5MB。'
  return ''
}

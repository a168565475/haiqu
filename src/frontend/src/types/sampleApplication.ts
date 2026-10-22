// V3 前端录入模型，与旧版 SampleRequestFormInput 分开，避免隐式补造后端必填明细。
export interface SampleApplicationDraft {
  sourceType: 'inquiry' | 'quotation' | null
  sourceId: string
  sourceProductId: string
  productId: string
  customerId: string
  contactId: string
  ownerId: string
  sampleType: string
  shippingMethod: string
  deliveryBatch: string
  repeatOrder: boolean | null
  orderDate: string
  dueDate: string
  productName: string
  specification: string
  lengthCm: string
  armrestWidthCm: string
  seatWidthCm: string
  backHeightCm: string
  seatHeightCm: string
  requirements: string
  quantity: number | null
  referenceImage: File | null
  sourceReferenceImageId?: string
  removeReferenceImage?: boolean
}

export interface SampleApplicationBasicInput {
  source_type: 'inquiry' | 'quotation' | null
  source_id: string | null
  customer_account_id: string
  customer_contact_id: string | null
  owner_employee_id: string
  sample_type: string
  shipping_method: string
  delivery_batch: string
  is_repeat_order: boolean | null
  order_date: string | null
  sample_due_date: string | null
}

export const sampleDimensionFields = [
  { key: 'lengthCm', label: '长（cm）' },
  { key: 'armrestWidthCm', label: '扶手宽（cm）' },
  { key: 'seatWidthCm', label: '坐宽（cm）' },
  { key: 'backHeightCm', label: '背高（cm）' },
  { key: 'seatHeightCm', label: '坐高（cm）' },
] as const

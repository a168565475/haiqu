import type { SampleApplicationDraft } from '@/types/sampleApplication'
import { apiClient } from './request'
import type { SampleDetail } from '@/types/sample'

export async function submitSampleApplication(draft: SampleApplicationDraft, submission: { key: string; sampleId?: string; etag?: string }): Promise<{ id: string; etag: string }> {
  const body = new FormData()
  body.append('payload', JSON.stringify({
    customer_account_id: draft.customerId, customer_contact_id: draft.contactId || null, owner_employee_id: draft.ownerId,
    source_type: draft.sourceType, source_id: draft.sourceId || null, source_product_id: draft.sourceProductId || null,
    product_id: draft.productId || null,
    sample_type: draft.sampleType, shipping_method: draft.shippingMethod, delivery_batch: draft.deliveryBatch, is_repeat_order: draft.repeatOrder,
    order_date: draft.orderDate || null, sample_due_date: draft.dueDate || null,
    product_name: draft.productName.trim(), specification: draft.specification, purpose: draft.requirements, quantity: draft.quantity,
    length_cm: draft.lengthCm || null, armrest_width_cm: draft.armrestWidthCm || null, seat_width_cm: draft.seatWidthCm || null,
    back_height_cm: draft.backHeightCm || null, seat_height_cm: draft.seatHeightCm || null,
    idempotency_key: submission.key, remove_reference_image: draft.removeReferenceImage || false,
    source_reference_image_id: draft.sourceReferenceImageId || null,
  }))
  if (draft.referenceImage) body.append('reference_image', draft.referenceImage)
  if (submission.sampleId && !submission.etag) throw new Error('缺少申请版本，请刷新后重试。')
  const url = submission.sampleId ? `/api/v1/sample-requests/${submission.sampleId}/application-resubmit/` : '/api/v1/sample-requests/applications/'
  const response = await apiClient.post<{ data: SampleDetail }>(url, body, { timeout: 60000, headers: submission.sampleId ? { 'If-Match': submission.etag } : {} })
  return { id: response.data.data.id, etag: response.headers.etag || response.data.data.etag }
}

export async function reviewSampleApplication(input: { sampleId: string; etag: string; decision: 'approve' | 'return'; note: string }): Promise<void> {
  if (!input.sampleId) throw new Error('缺少申请编号，请重新加载。')
  if (input.decision === 'return' && !input.note.trim()) throw new Error('退回时请填写需要业务员补充的内容。')
  if (input.note.length > 500) throw new Error('处理意见不能超过 500 字。')
  if (!input.etag) throw new Error('缺少申请版本，请刷新后重试。')
  await apiClient.post(`/api/v1/sample-requests/${input.sampleId}/director-review/`, { decision: input.decision, note: input.note.trim() }, { headers: { 'If-Match': input.etag } })
}
